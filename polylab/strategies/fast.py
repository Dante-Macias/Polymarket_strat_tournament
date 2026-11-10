"""Strategies for the fast bucket (5-minute crypto Up/Down markets).

Each class is deliberately small. `prob` on an order is the bot's own
probability that the side it buys will win; it feeds the calibration and
"edge vs market" metrics.
"""
import datetime as dt
import random

import numpy as np

from ..model import view_p_up
from .base import Cancel, DayStop, Order, Strategy

OTHER = {"UP": "DOWN", "DOWN": "UP"}


class OncePerMarket(Strategy):
    """Helper: remembers whether we already traded this market."""

    def __init__(self):
        self._mkt = None

    def fresh(self, v) -> bool:
        return self._mkt != v.start_ts

    def mark(self, v):
        self._mkt = v.start_ts


# ------------------------------------------------------------------ baselines
class RandomSide(OncePerMarket):
    """Dumb baseline: coin flip, taker, at second `t`."""
    family = "baseline"

    def __init__(self, t=30, seed=7, name=None):
        super().__init__()
        self.t, self.rng = t, random.Random(seed)
        self.name = name or f"base_random_t{t}"

    def ticks(self, dur):
        return [self.t]

    def decide(self, v):
        return [Order(self.rng.choice(["UP", "DOWN"]), "taker", prob=0.5)]


class AlwaysFavorite(OncePerMarket):
    """Dumb baseline: buy whichever side the market prices above 50c at second `t`."""
    family = "baseline"

    def __init__(self, t=30, name=None):
        super().__init__()
        self.t = t
        self.name = name or f"base_favorite_t{t}"

    def ticks(self, dur):
        return [self.t]

    def decide(self, v):
        m = v.mid("UP")
        if m != m or abs(m - 0.5) < 0.005:
            return []
        side = "UP" if m > 0.5 else "DOWN"
        return [Order(side, "taker", prob=max(m, 1 - m))]


# ------------------------------------------------------------------ S01 (hypothesis A)
class Early60(OncePerMarket):
    """If a side is priced lo..hi within the first `within` seconds, buy it (or fade it)."""
    family = "A_early60"

    def __init__(self, lo=0.57, hi=0.63, within=10, kind="taker", fade=False, name=None):
        super().__init__()
        self.lo, self.hi, self.within, self.kind, self.fade = lo, hi, within, kind, fade
        self.name = name or f"S01_early60_{kind}{'_fade' if fade else ''}"

    def ticks(self, dur):
        return range(1, self.within + 1)

    def decide(self, v):
        if not self.fresh(v):
            return []
        for side in ("UP", "DOWN"):
            a = v.ask(side)
            if a == a and self.lo <= a <= self.hi:
                self.mark(v)
                buy = OTHER[side] if self.fade else side
                if self.kind == "taker":
                    lim = (1 - self.lo + 0.03) if self.fade else self.hi + 0.03
                    return [Order(buy, "taker", lim, prob=(1 - a) if self.fade else a)]
                px = round((1 - a) - 0.01, 3) if self.fade else round(a - 0.01, 3)
                return [Order(buy, "limit", px, ttl=60, prob=px)]
        return []


# ------------------------------------------------------------------ S02 (hypothesis B)
def macd_hist(closes: np.ndarray, fast=12, slow=26, sig=9) -> float:
    def ema(x, n):
        k, e = 2.0 / (n + 1), x[0]
        out = np.empty(len(x))
        for i, val in enumerate(x):
            e = val * k + e * (1 - k)
            out[i] = e
        return out
    line = ema(closes, fast) - ema(closes, slow)
    return float(line[-1] - ema(line, sig)[-1])


class TrendCandle(OncePerMarket):
    """Trade every window in the trend direction. mode: 'macd' or 'prev' (last candle)."""
    family = "B_trend"

    def __init__(self, mode="macd", day_stop: DayStop | None = None, name=None):
        super().__init__()
        self.mode, self.stop = mode, day_stop
        self.name = name or f"S02_trend_{mode}"

    def ticks(self, dur):
        return [0]

    def decide(self, v):
        if self.stop:
            self.stop.roll(v.day)
            if self.stop.stopped:
                return []
        if self.mode == "prev":
            if not v.history:
                return []
            up = v.history[-1][1] == 1
        else:
            c = v.spot_hist(35 * 300)[299::300]
            h = macd_hist(c)
            if h == 0:
                return []
            up = h > 0
        return [Order("UP" if up else "DOWN", "taker", 0.60, prob=0.5)]

    def on_market_end(self, v, trades):
        if self.stop:
            for tr in trades:
                self.stop.add(tr.pnl)


# ------------------------------------------------------------------ S03 (hypothesis C)
class EarlyDayMomentum(OncePerMarket):
    """Sign of the return in a morning window decides the side for the next hours.

    signal window [sig0, sig1) and trading window [sig1, trade_end) are minutes of the UTC day.
    """
    family = "C_daymom"

    def __init__(self, sig0=0, sig1=60, trade_end=360, min_bp=0.0, name=None):
        super().__init__()
        self.sig0, self.sig1, self.trade_end, self.min_bp = sig0, sig1, trade_end, min_bp
        self.name = name or f"S03_daymom_{sig0}_{sig1}_{trade_end}"

    def ticks(self, dur):
        return [0]

    def decide(self, v):
        mins = (v.start_ts % 86400) // 60
        if not (self.sig1 <= mins < self.trade_end):
            return []
        ago1 = (mins - self.sig1) * 60
        ago0 = (mins - self.sig0) * 60
        r = v.raw_spot(ago1) / v.raw_spot(ago0) - 1.0
        if abs(r) * 1e4 <= self.min_bp:
            return []
        return [Order("UP" if r > 0 else "DOWN", "taker", 0.60, prob=0.5)]


# ------------------------------------------------------------------ S04 / S05 (hypothesis D)
class PairTaker(OncePerMarket):
    """Buy both sides at once when the two asks sum to less than 1 - margin."""
    family = "D_pair"

    def __init__(self, margin=0.04, name=None):
        super().__init__()
        self.margin = margin
        self.name = name or f"S04_pair_taker_m{int(margin * 100)}"

    def ticks(self, dur):
        return range(5, dur - 10)

    def decide(self, v):
        if not self.fresh(v):
            return []
        au, ad = v.ask("UP"), v.ask("DOWN")
        if au == au and ad == ad and au + ad < 1.0 - self.margin:
            self.mark(v)
            return [Order("UP", "taker", au + 0.01, prob=None, tag="pair"),
                    Order("DOWN", "taker", ad + 0.01, prob=None, tag="pair")]
        return []


class PairMaker(OncePerMarket):
    """Rest a bid at `price` on BOTH sides from second `start`; hold whatever fills.

    Only starts when both bids can actually rest (each side's ask is above our
    price), i.e. when the market is still close to 50/50.
    bail: if only one leg has filled after `bail` seconds, cancel the other leg
    (None = leave it resting to the end).
    """
    family = "D_pair"

    def __init__(self, price=0.45, start=5, bail=None, name=None):
        super().__init__()
        self.price, self.start, self.bail = price, start, bail
        self.name = name or f"S05_pair_maker_{int(round(price * 100))}"

    def ticks(self, dur):
        return [self.start] + ([self.start + self.bail] if self.bail else [])

    def decide(self, v):
        if v.t == self.start:
            au, ad = v.ask("UP"), v.ask("DOWN")
            if not (au > self.price and ad > self.price):     # also false when a quote is missing
                return []
            return [Order("UP", "limit", self.price, ttl=v.dur, tag="U"),
                    Order("DOWN", "limit", self.price, ttl=v.dur, tag="D")]
        got = {f.tag for f in v.fills}
        return [Cancel(t) for t in ("U", "D") if t not in got] if len(got) == 1 else []


# ------------------------------------------------------------------ S06 (hypothesis E)
class AheadSide(OncePerMarket):
    """At second `t`, if spot is at least `x` from the strike, buy the leading side.

    unit: 'usd' (dollars), 'bp' (hundredths of a percent of price) or 'z'
    (distance divided by the typical move still to come).
    max_price caps what we pay; day_stop adds the daily take-profit rule.
    """
    family = "E_ahead"

    def __init__(self, t=180, x=50.0, unit="usd", max_price=0.97, min_price=0.0,
                 day_stop: DayStop | None = None, name=None):
        super().__init__()
        self.t, self.x, self.unit, self.max_price, self.min_price, self.stop = t, x, unit, max_price, min_price, day_stop
        self.name = name or f"S06_ahead_t{t}_{unit}{x:g}"

    def ticks(self, dur):
        return [self.t]

    def decide(self, v):
        if self.stop:
            self.stop.roll(v.day)
            if self.stop.stopped:
                return []
        p, sigma, d = view_p_up(v)
        if d != d:
            return []
        if self.unit == "usd":
            s = abs(d)
        elif self.unit == "bp":
            s = abs(d) / v.strike * 1e4
        else:
            s = abs(d) / (sigma * max(v.secs_left, 1) ** 0.5) if sigma > 0 else 0.0
        if s < self.x:
            return []
        side = "UP" if d > 0 else "DOWN"
        a = v.ask(side)
        if a == a and a < self.min_price:
            return []
        return [Order(side, "taker", self.max_price, prob=p if side == "UP" else 1 - p)]

    def on_market_end(self, v, trades):
        if self.stop:
            for tr in trades:
                self.stop.add(tr.pnl)


# ------------------------------------------------------------------ S07 / S08
class FairValueTaker(OncePerMarket):
    """Buy a side when its ask is below model fair value by `margin` (after the fee)."""
    family = "model"

    def __init__(self, margin=0.05, t0=5, t1=240, step=5, p_min=0.0, vol_mult=1.0, name=None):
        super().__init__()
        self.margin, self.t0, self.t1, self.step, self.p_min, self.vol_mult = margin, t0, t1, step, p_min, vol_mult
        self.name = name or f"S07_fairvalue_m{int(margin * 100)}"

    def ticks(self, dur):
        return range(self.t0, self.t1 + 1, self.step)

    def decide(self, v):
        if not self.fresh(v):
            return []
        p, _, _ = view_p_up(v, vol_mult=self.vol_mult)
        if p != p:
            return []
        for side, ps in (("UP", p), ("DOWN", 1 - p)):
            a = v.ask(side)
            if a != a or ps < self.p_min:
                continue
            fee = v.fee_rate * a * (1 - a)
            if ps - a - fee >= self.margin:
                self.mark(v)
                return [Order(side, "taker", round(ps - fee - self.margin, 3), prob=ps)]
        return []


class TwapLock(FairValueTaker):
    """S07 restricted to the final minute, favourites only: the average is partly locked in."""
    family = "model"

    def __init__(self, margin=0.03, p_min=0.85, name=None):
        super().__init__(margin=margin, t0=242, t1=294, step=4, p_min=p_min,
                         name=name or f"S08_twaplock_m{int(margin * 100)}")


# ------------------------------------------------------------------ S09
class OpenGap(OncePerMarket):
    """At the open, buy the side spot already favours versus the (estimated) strike."""
    family = "open_gap"

    def __init__(self, x=20.0, max_price=0.60, t=1, name=None):
        super().__init__()
        self.x, self.max_price, self.t = x, max_price, t
        self.name = name or f"S09_opengap_x{x:g}_cap{int(max_price * 100)}"

    def ticks(self, dur):
        return [self.t]

    def decide(self, v):
        d = v.spot - v.strike
        if d != d or abs(d) < self.x:
            return []
        p, _, _ = view_p_up(v)
        side = "UP" if d > 0 else "DOWN"
        return [Order(side, "taker", self.max_price, prob=p if side == "UP" else 1 - p)]


# ------------------------------------------------------------------ S10 / S11
class FlowSignal(OncePerMarket):
    """Follow (or fade) recent signed taker flow. source: 'tape' (Polymarket) or 'spot' (exchange)."""
    family = "flow"

    def __init__(self, source="tape", n=30, t=30, thr=0.3, fade=False, max_price=0.75, name=None):
        super().__init__()
        self.source, self.n, self.t, self.thr, self.fade, self.max_price = source, n, t, thr, fade, max_price
        self.name = name or f"S{'10' if source == 'tape' else '11'}_{source}flow_{'fade' if fade else 'follow'}_t{t}"

    def ticks(self, dur):
        return [self.t]

    def decide(self, v):
        f = v.flow(self.n, self.source)
        if abs(f) < self.thr:
            return []
        up = (f > 0) != self.fade
        return [Order("UP" if up else "DOWN", "taker", self.max_price, prob=0.5)]


# ------------------------------------------------------------------ S12
class ModelMaker(Strategy):
    """Rest bids `edge` below model fair value on both sides, refreshed every `step` seconds.

    At most one fill per side per market.
    """
    family = "maker"

    def __init__(self, edge=0.04, step=10, t0=10, t1=240, name=None):
        self.edge, self.step, self.t0, self.t1 = edge, step, t0, t1
        self.name = name or f"S12_model_maker_e{int(edge * 100)}"

    def ticks(self, dur):
        return range(self.t0, self.t1 + 1, self.step)

    def decide(self, v):
        p, _, _ = view_p_up(v)
        if p != p:
            return []
        have = {f.side for f in v.fills}
        out = [Cancel("q")]
        for side, ps in (("UP", p), ("DOWN", 1 - p)):
            px = round(ps - self.edge, 2)
            if side in have or px < 0.05 or px > 0.95:
                continue
            out.append(Order(side, "limit", px, ttl=self.step, prob=ps, tag="q"))
        return out


# ------------------------------------------------------------------ S15
class PriceBucket(OncePerMarket):
    """Buy any side whose ask is inside [lo, hi] at second `t` (favourite-longshot test)."""
    family = "flb"

    def __init__(self, lo=0.90, hi=0.97, t=240, name=None):
        super().__init__()
        self.lo, self.hi, self.t = lo, hi, t
        self.name = name or f"S15_bucket_{int(lo * 100)}_{int(hi * 100)}_t{t}"

    def ticks(self, dur):
        return [self.t]

    def decide(self, v):
        for side in ("UP", "DOWN"):
            a = v.ask(side)
            if a == a and self.lo <= a <= self.hi:
                return [Order(side, "taker", self.hi + 0.01, prob=a)]
        return []


# ------------------------------------------------------------------ S13
class LeadLagTaker(FairValueTaker):
    """Fair-value taker for one asset (ETH) that shifts spot by the move another asset (BTC)
    has made but this one has not yet: shift = kappa * (lead_return - own_return) * spot.

    kappa = 0 is the plain fair-value taker, so comparing kappa 0 vs >0 isolates the lead-lag idea.
    Backtest only (the live engine follows a single asset).
    """
    family = "leadlag"

    def __init__(self, kappa=0.5, lookback=30, margin=0.05, lead="btc", name=None):
        super().__init__(margin=margin, name=name or f"S13_leadlag_k{int(kappa * 100)}_m{int(margin * 100)}")
        self.kappa, self.lookback, self.lead = kappa, lookback, lead

    def decide(self, v):
        if not self.fresh(v):
            return []
        shift = 0.0
        if self.kappa:
            own = v.raw_spot(0) / v.raw_spot(self.lookback) - 1.0
            shift = self.kappa * (v.aux_ret(self.lead, self.lookback) - own) * v.raw_spot(0)
        p, _, _ = view_p_up(v, spot_shift=shift)
        if p != p:
            return []
        for side, ps in (("UP", p), ("DOWN", 1 - p)):
            a = v.ask(side)
            if a != a:
                continue
            fee = v.fee_rate * a * (1 - a)
            if ps - a - fee >= self.margin:
                self.mark(v)
                return [Order(side, "taker", round(ps - fee - self.margin, 3), prob=ps)]
        return []
