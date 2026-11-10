"""Live, read-only market data for the recorder and the paper engine.

Polls (REST, once per second):
  * the order books of the current Up/Down market (both outcome tokens)
  * Binance 1-second klines for the reference price
and keeps a rolling in-memory history so a `LiveView` can offer exactly the
same interface as the backtester's `View`.
"""
import datetime as dt
import time

import numpy as np

from ..config import BINANCE
from ..data import polymarket as pm
from ..data.http import get_json

SYM = {"btc": "BTCUSDT", "eth": "ETHUSDT"}
DUR = {"5m": 300, "15m": 900}
KEEP = 12_000   # seconds of spot history kept in memory


class SpotFeed:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.ts: list[int] = []
        self.close: list[float] = []
        self.vol: list[float] = []
        self.buy: list[float] = []

    def _add(self, rows):
        for r in rows:
            t = r[0] // 1000
            if self.ts and t <= self.ts[-1]:
                if t == self.ts[-1]:     # bar still forming: overwrite
                    self.close[-1], self.vol[-1], self.buy[-1] = float(r[4]), float(r[5]), float(r[9])
                continue
            while self.ts and t > self.ts[-1] + 1:      # fill gaps so index == seconds
                self.ts.append(self.ts[-1] + 1)
                self.close.append(self.close[-1])
                self.vol.append(0.0)
                self.buy.append(0.0)
            self.ts.append(t)
            self.close.append(float(r[4]))
            self.vol.append(float(r[5]))
            self.buy.append(float(r[9]))
        if len(self.ts) > KEEP + 2000:
            for a in (self.ts, self.close, self.vol, self.buy):
                del a[:-KEEP]

    def warmup(self):
        end = int(time.time()) * 1000
        start = end - KEEP * 1000
        while start < end:
            rows = get_json(f"{BINANCE}/api/v3/klines",
                            {"symbol": self.symbol, "interval": "1s", "startTime": start, "limit": 1000})
            if not rows:
                break
            self._add(rows)
            start = rows[-1][0] + 1000

    def poll(self):
        self._add(get_json(f"{BINANCE}/api/v3/klines", {"symbol": self.symbol, "interval": "1s", "limit": 5},
                           retries=2, timeout=5))

    # helpers working on COMPLETED bars only (bars with open time < ts_now)
    def _idx(self, ts: int) -> int:
        """Index of the bar that opened at `ts` (clamped)."""
        return max(0, min(len(self.ts) - 1, ts - self.ts[0]))

    def at(self, ts: int) -> float:
        return self.close[self._idx(ts)]

    def window(self, ts0: int, ts1: int) -> np.ndarray:
        return np.asarray(self.close[self._idx(ts0): self._idx(ts1 - 1) + 1])

    def mean(self, ts0: int, ts1: int) -> float:
        w = self.window(ts0, ts1)
        return float(w.mean()) if len(w) else float("nan")

    def flow(self, ts0: int, ts1: int) -> float:
        a, b = self._idx(ts0), self._idx(ts1 - 1) + 1
        v, buy = sum(self.vol[a:b]), sum(self.buy[a:b])
        return (2 * buy - v) / v if v > 0 else 0.0


def top(book: dict, n: int = 5):
    bids = sorted(((float(x["price"]), float(x["size"])) for x in book.get("bids", [])), reverse=True)[:n]
    asks = sorted((float(x["price"]), float(x["size"])) for x in book.get("asks", []))[:n]
    return bids, asks


class MarketFeed:
    """Tracks the currently-open Up/Down market of one series."""

    def __init__(self, asset="btc", duration="5m"):
        self.asset, self.duration, self.dur = asset, duration, DUR[duration]
        self.info: dict | None = None
        self.start_ts = 0
        self.books = {"UP": ([], []), "DOWN": ([], [])}
        self.book_time = 0.0

    def roll(self, now: float) -> bool:
        """Switch to the window containing `now`. True if a new market was loaded."""
        st = int(now) // self.dur * self.dur
        if st == self.start_ts and self.info:
            return False
        ev = pm.event_by_slug(pm.updown_slug(self.asset, self.duration, st))
        info = pm.parse_updown_event(ev)
        if not info:
            return False
        self.info, self.start_ts = info, st
        self.books = {"UP": ([], []), "DOWN": ([], [])}
        return True

    def poll_books(self):
        if not self.info:
            return
        for side, tok in (("UP", self.info["tok_up"]), ("DOWN", self.info["tok_down"])):
            self.books[side] = top(get_json(f"{pm.CLOB}/book", {"token_id": tok}, retries=2, timeout=5))
        self.book_time = time.time()

    def best(self, side: str):
        bids, asks = self.books[side]
        return (bids[0][0] if bids else float("nan")), (asks[0][0] if asks else float("nan"))

    def resolution(self, start_ts: int) -> dict | None:
        """Outcome of a finished window, or None if not resolved yet."""
        info = pm.parse_updown_event(pm.event_by_slug(pm.updown_slug(self.asset, self.duration, start_ts)))
        if info and info["outcome_up"] is not None:
            return info
        return None

    def published_strike(self, start_ts: int):
        info = pm.parse_updown_event(pm.event_by_slug(pm.updown_slug(self.asset, self.duration, start_ts)))
        return info["strike"] if info else None


class LiveView:
    """Same interface as polylab.sim.engine.View, backed by live feeds."""

    def __init__(self, mf: MarketFeed, spot: SpotFeed, history: list, basis: float):
        self._mf, self._spot = mf, spot
        self.asset, self.start_ts, self.dur = mf.asset, mf.start_ts, mf.dur
        self.fee_rate = (mf.info or {}).get("fee_rate") or 0.07
        self.history = history
        self.day = dt.datetime.fromtimestamp(mf.start_ts, dt.timezone.utc).date()
        self.t = 0
        self.fills = []
        self.basis = basis
        self._tw0 = spot.mean(mf.start_ts - 60, mf.start_ts)
        self.tape_flow = 0.0

    @property
    def secs_left(self):
        return self.dur - self.t

    @property
    def strike(self):
        return self._tw0 + self.basis

    @property
    def spot(self):
        return self._spot.at(self.start_ts + self.t - 1) + self.basis

    def raw_spot(self, secs_ago=0):
        return self._spot.at(self.start_ts + self.t - 1 - secs_ago)

    def spot_hist(self, n):
        e = self.start_ts + self.t
        return self._spot.window(e - n, e)

    def spot_mean(self, rel0, rel1):
        return self._spot.mean(self.start_ts + rel0, self.start_ts + rel1) + self.basis

    def flow(self, n, kind="spot"):
        if kind == "spot":
            e = self.start_ts + self.t
            return self._spot.flow(e - n, e)
        return self.tape_flow

    def ask(self, side="UP"):
        return self._mf.best(side)[1]

    def bid(self, side="UP"):
        return self._mf.best(side)[0]

    def mid(self, side="UP"):
        b, a = self._mf.best(side)
        if a != a:
            return b
        if b != b:
            return a
        return 0.5 * (a + b)
