"""Probe pass: one row per (market, decision time) with everything needed for
vectorised grid research - what a bot would have seen, and what it would have
paid on each side under the fill model. Out-of-sample discipline is applied
later by splitting these rows by day.
"""
import math

import numpy as np
import pandas as pd

from .data.history import PRE
from .model import view_p_up
from .sim import fills
from .sim.engine import View

T_GRID = [0, 2, 4, 6, 8, 10, 15, 20, 30, 45, 60, 90, 120, 150, 180, 210, 240, 250, 260, 270, 280, 285, 290, 293]


def probe_markets(markets, spot, delay=3, window=3, t_grid=T_GRID) -> pd.DataFrame:
    rows = []
    history, last_basis = [], None
    for m in markets:
        if not spot.has(m.start_ts - 11000, m.start_ts + m.dur + 1):
            continue
        if last_basis is None:
            last_basis = m.strike - spot.mean(m.start_ts - 60, m.start_ts)
        v = View(m, spot, history, last_basis)
        for t in t_grid:
            v.t = t
            p, sig, d = view_p_up(v)
            fu = fills.taker_fill(m, "UP", t, 0.999, delay, window)
            fd = fills.taker_fill(m, "DOWN", t, 0.999, delay, window)
            wu = fills.taker_fill(m, "UP", t, 0.999, delay + 2, window, worst=True)
            wd = fills.taker_fill(m, "DOWN", t, 0.999, delay + 2, window, worst=True)
            rows.append((m.start_ts, t, d, sig, p, v.ask("UP"), v.bid("UP"),
                         fu[1] if fu else np.nan, fd[1] if fd else np.nan,
                         wu[1] if wu else np.nan, wd[1] if wd else np.nan,
                         v.flow(30, "tape"), v.flow(30, "spot"), v.flow(120, "spot"),
                         m.outcome_up, m.fee_rate))
        history.append((m.start_ts, m.outcome_up, m.strike, m.final))
        last_basis = m.strike - spot.mean(m.start_ts - 60, m.start_ts)
    df = pd.DataFrame(rows, columns=["start_ts", "t", "d", "sigma", "p_model", "ask_up", "bid_up",
                                     "fill_up", "fill_dn", "wfill_up", "wfill_dn",
                                     "flow_tape30", "flow_spot30", "flow_spot120", "up", "fee_rate"])
    df["day"] = pd.to_datetime(df["start_ts"], unit="s").dt.date
    return df
