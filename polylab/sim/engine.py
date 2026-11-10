"""Event-driven backtester for Up/Down markets.

For every market, in time order, the engine walks the seconds a strategy asked
for, hands it a `View` restricted to the past, and simulates fills with
polylab.sim.fills. Positions are held to resolution (payout $1 or $0/share).
"""
import datetime as dt

import numpy as np

from ..data.history import PRE
from ..fees import taker_fee
from ..strategies.base import Cancel, Order, Trade
from . import fills
from .market import Market, SpotSeries

# The official strike ("price to beat") is NOT published through the public API while a
# window is live (checked 10 Nov 2026: Gamma only fills it in after the window). So by
# default a bot never sees it: it estimates strike = exchange 60s average + the
# Chainlink-vs-exchange basis observed on the previous window (error ~ $5 for BTC).
# Set STRIKE_DELAY to a small number to simulate having the authenticated price stream.
STRIKE_DELAY = 10**9
QUOTE_MAX_AGE = 10   # seconds; older tape evidence is treated as "no quote"


class View:
    """Everything a strategy may know at second `t` of a market (no future)."""

    def __init__(self, m: Market, spot: SpotSeries, history: list, last_basis: float, aux: dict | None = None):
        self._m, self._spot = m, spot
        self._aux = aux or {}
        self.asset, self.start_ts, self.dur = m.asset, m.start_ts, m.dur
        self.fee_rate = m.fee_rate
        self.history = history            # closed markets: (start_ts, outcome_up, strike, final)
        self.day = dt.datetime.fromtimestamp(m.start_ts, dt.timezone.utc).date()
        self.t = -PRE
        self.fills: list[Trade] = []      # own fills so far in this market
        self._basis_prev = last_basis
        self._tw0 = spot.mean(m.start_ts - 60, m.start_ts)
        self._basis = m.strike - self._tw0

    # -- time
    @property
    def secs_left(self) -> int:
        return self.dur - self.t

    # -- reference price
    @property
    def strike(self) -> float:
        """Price to beat. Official value once published, our own estimate before."""
        if self.t >= STRIKE_DELAY:
            return self._m.strike
        if self.t >= 0:
            return self._tw0 + self._basis_prev
        return float("nan")

    @property
    def basis(self) -> float:
        """Chainlink minus Binance, estimated without look-ahead."""
        return self._basis if self.t >= STRIKE_DELAY else self._basis_prev

    @property
    def spot(self) -> float:
        """Last completed 1s exchange close, shifted onto the Chainlink scale."""
        return self._spot.at(self.start_ts + self.t - 1) + self.basis

    def raw_spot(self, secs_ago: int = 0) -> float:
        return self._spot.at(self.start_ts + self.t - 1 - secs_ago)

    def aux_ret(self, name: str, n: int) -> float:
        """Return of another asset (e.g. 'btc' when trading ETH) over the last n seconds."""
        a = self._aux[name]
        e = self.start_ts + self.t - 1
        return a.at(e) / a.at(e - n) - 1.0

    def spot_hist(self, n: int) -> np.ndarray:
        """Last n completed 1s closes (raw exchange price), oldest first."""
        e = self.start_ts + self.t
        return self._spot.window(e - n, e)

    def spot_mean(self, rel0: int, rel1: int) -> float:
        """Mean Chainlink-scale price over window seconds [rel0, rel1), rel1 <= t."""
        assert rel1 <= self.t
        return self._spot.mean(self.start_ts + rel0, self.start_ts + rel1) + self.basis

    def flow(self, n: int, kind: str = "spot") -> float:
        """Signed taker flow over the last n seconds, in [-1, 1]."""
        if kind == "spot":
            e = self.start_ts + self.t - self._spot.t0
            v = self._spot.vol[e - n:e].sum()
            b = self._spot.buy_vol[e - n:e].sum()
            return float((2 * b - v) / v) if v > 0 else 0.0
        i = PRE + self.t
        a = self._m.ask_vol[max(i - n, 0):i].sum()
        b = self._m.bid_vol[max(i - n, 0):i].sum()
        return float((a - b) / (a + b)) if a + b > 0 else 0.0

    # -- market quotes (from tape evidence stamped before t)
    def _last(self, arr) -> float:
        i = PRE + self.t
        seg = arr[max(i - QUOTE_MAX_AGE, 0):i]
        ok = np.flatnonzero(~np.isnan(seg))
        return float(seg[ok[-1]]) if len(ok) else float("nan")

    def ask(self, side: str = "UP") -> float:
        return self._last(self._m.ask_hi) if side == "UP" else 1.0 - self._last(self._m.bid_lo)

    def bid(self, side: str = "UP") -> float:
        return self._last(self._m.bid_lo) if side == "UP" else 1.0 - self._last(self._m.ask_hi)

    def mid(self, side: str = "UP") -> float:
        a, b = self.ask(side), self.bid(side)
        if a != a:
            return b
        if b != b:
            return a
        return 0.5 * (a + b)


class Backtester:
    def __init__(self, spot: SpotSeries, delay: int = 3, window: int = 3, slip: float = 0.0,
                 worst: bool = False, fee_mult: float = 1.0, maker_through: float = 0.0, aux: dict | None = None):
        self.spot, self.delay, self.window = spot, delay, window
        self.aux = aux
        self.slip, self.worst, self.fee_mult, self.maker_through = slip, worst, fee_mult, maker_through

    def run(self, strategies: list, markets: list[Market]) -> dict[str, list[Trade]]:
        out = {s.name: [] for s in strategies}
        history: list = []
        last_basis = None
        for m in markets:
            if not self.spot.has(m.start_ts - 11000, m.start_ts + m.dur + 1):
                continue
            if last_basis is None:
                last_basis = m.strike - self.spot.mean(m.start_ts - 60, m.start_ts)
            for s in strategies:
                out[s.name] += self._run_market(s, m, history, last_basis)
            history.append((m.start_ts, m.outcome_up, m.strike, m.final))
            last_basis = m.strike - self.spot.mean(m.start_ts - 60, m.start_ts)
        return out

    def _run_market(self, s, m: Market, history, last_basis) -> list[Trade]:
        v = View(m, self.spot, history, last_basis, self.aux)
        done: list[Trade] = []
        pending: list[tuple[Order, int, Trade]] = []   # (order, fill_rel, trade)
        for t in s.ticks(m.dur):
            v.t = t
            # limit orders whose fill time has arrived become visible fills
            for item in [p for p in pending if p[1] <= t]:
                pending.remove(item)
                done.append(item[2])
            v.fills = done
            for o in s.decide(v) or []:
                if isinstance(o, Cancel):
                    pending = [p for p in pending if p[0].tag != o.tag]
                    continue
                mkt = v.mid(o.side)
                if o.kind == "taker":
                    f = fills.taker_fill(m, o.side, t, o.price, self.delay, self.window, self.slip, self.worst)
                    if f is None:
                        continue
                    ft, px = f
                    fee = taker_fee(o.size, px, m.fee_rate) * self.fee_mult
                    done.append(Trade(s.name, m.asset, m.start_ts, o.side, "taker", t, ft, px, o.size, fee,
                                      o.prob, mkt, o.tag))
                else:
                    a = v.ask(o.side)
                    if a == a and a <= o.price + 1e-9:
                        continue     # post-only: a bid at/above the ask would not rest, so it is rejected
                    ft = fills.maker_fill(m, o.side, t, o.price, o.ttl, self.delay, self.maker_through)
                    if ft is None:
                        continue
                    pending.append((o, ft, Trade(s.name, m.asset, m.start_ts, o.side, "limit", t, ft,
                                                 o.price, o.size, 0.0, o.prob, mkt, o.tag)))
        done += [p[2] for p in pending]     # never cancelled -> they did fill later in the window
        for tr in done:
            tr.outcome_up = m.outcome_up
            tr.payout = fills.settle(tr.side, m.outcome_up) * tr.size
            tr.pnl = tr.payout - tr.price * tr.size - tr.fee
        v.t = m.dur
        s.on_market_end(v, done)
        return done
