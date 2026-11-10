"""In-memory representation of one Up/Down market and the spot price series.

Array index i corresponds to second `rel = i - PRE` relative to the window
start, so index PRE is the first second of the window.
"""
import datetime as dt
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..config import HIST
from ..data.history import PRE

POST = 31


@dataclass
class Market:
    asset: str
    start_ts: int
    dur: int
    strike: float          # Chainlink "price to beat" (60s TWAP ending at start)
    final: float           # Chainlink final price (60s TWAP ending at window end)
    outcome_up: int        # 1 if Up won, 0 if Down won
    fee_rate: float
    ask_lo: np.ndarray     # Up-ask evidence per second (NaN = no print)
    ask_hi: np.ndarray
    ask_vol: np.ndarray
    bid_lo: np.ndarray     # Up-bid evidence per second
    bid_hi: np.ndarray
    bid_vol: np.ndarray

    def i(self, rel: int) -> int:
        return rel + PRE


class SpotSeries:
    """Second-by-second exchange closes with O(1) lookup by unix time."""

    def __init__(self, df: pd.DataFrame):
        self.t0 = int(df["ts"].iloc[0])
        n = int(df["ts"].iloc[-1]) - self.t0 + 1
        idx = (df["ts"].to_numpy() - self.t0).astype(np.int64)

        def fill(col):
            a = np.full(n, np.nan)
            a[idx] = df[col].to_numpy()
            return a

        close = fill("close")
        # forward-fill the rare missing seconds
        mask = np.isnan(close)
        if mask.any():
            last = np.where(~mask, np.arange(n), 0)
            np.maximum.accumulate(last, out=last)
            close = close[last]
        self.close = close
        self.vol = np.nan_to_num(fill("volume"))
        self.buy_vol = np.nan_to_num(fill("taker_buy_vol"))
        self.csum = np.concatenate([[0.0], np.cumsum(close)])
        self.n = n

    def has(self, ts0: int, ts1: int) -> bool:
        return ts0 >= self.t0 and ts1 < self.t0 + self.n

    def at(self, ts: int) -> float:
        """Close of the 1-second bar that STARTED at `ts` (known at ts+1)."""
        return float(self.close[ts - self.t0])

    def window(self, ts0: int, ts1: int) -> np.ndarray:
        return self.close[ts0 - self.t0: ts1 - self.t0]

    def mean(self, ts0: int, ts1: int) -> float:
        """Average close over seconds [ts0, ts1)."""
        return float((self.csum[ts1 - self.t0] - self.csum[ts0 - self.t0]) / (ts1 - ts0))


def available_days(asset: str, duration: str) -> list[dt.date]:
    d = HIST / f"{asset}_{duration}"
    return sorted(dt.date.fromisoformat(p.stem.split("_")[1]) for p in d.glob("meta_*.parquet"))


def load_day(asset: str, duration: str, dur: int, day: dt.date) -> list[Market]:
    d = HIST / f"{asset}_{duration}"
    meta = pd.read_parquet(d / f"meta_{day}.parquet")
    bars = pd.read_parquet(d / f"bars_{day}.parquet")
    L = PRE + dur + POST
    meta = meta.dropna(subset=["strike", "final", "outcome_up"]).sort_values("start_ts")
    pos = {int(s): k for k, s in enumerate(meta["start_ts"])}
    n = len(meta)
    arr = {k: np.full((n, L), np.nan, dtype=np.float32) for k in ("ask_lo", "ask_hi", "bid_lo", "bid_hi")}
    vol = {k: np.zeros((n, L), dtype=np.float32) for k in ("ask_vol", "bid_vol")}
    if len(bars):
        b = bars[bars["start_ts"].isin(pos)]
        row = b["start_ts"].map(pos).to_numpy()
        col = b["rel"].to_numpy().astype(np.int64) + PRE
        ok = (col >= 0) & (col < L)
        up = (b["dir"].to_numpy() == 1) & ok
        dn = (b["dir"].to_numpy() == -1) & ok
        arr["ask_lo"][row[up], col[up]] = b["lo"].to_numpy()[up]
        arr["ask_hi"][row[up], col[up]] = b["hi"].to_numpy()[up]
        vol["ask_vol"][row[up], col[up]] = b["vol"].to_numpy()[up]
        arr["bid_lo"][row[dn], col[dn]] = b["lo"].to_numpy()[dn]
        arr["bid_hi"][row[dn], col[dn]] = b["hi"].to_numpy()[dn]
        vol["bid_vol"][row[dn], col[dn]] = b["vol"].to_numpy()[dn]
    out = []
    for k, r in enumerate(meta.itertuples()):
        out.append(Market(asset, int(r.start_ts), dur, float(r.strike), float(r.final), int(r.outcome_up),
                          float(r.fee_rate) if r.fee_rate == r.fee_rate and r.fee_rate is not None else 0.07,
                          arr["ask_lo"][k], arr["ask_hi"][k], vol["ask_vol"][k],
                          arr["bid_lo"][k], arr["bid_hi"][k], vol["bid_vol"][k]))
    return out
