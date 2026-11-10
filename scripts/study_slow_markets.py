#!/usr/bin/env python3
"""Collect the datasets for the slow families (S16, S18, S19, S20) into data/history/slow/."""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from polylab import slow  # noqa: E402
from polylab.config import HIST  # noqa: E402

out = HIST / "slow"
out.mkdir(exist_ok=True)
what = sys.argv[1:] or ["sports", "bonds", "baskets", "sumarb"]
d0, d1 = dt.date(2026, 3, 1), dt.date(2026, 11, 9)
if "sumarb" in what:
    df = slow.scan_sum_arb()
    p = out / "sumarb_scans.parquet"
    if p.exists():
        import pandas as pd
        df = pd.concat([pd.read_parquet(p), df], ignore_index=True)
    df.to_parquet(p, index=False)
    print("sumarb scans", len(df), flush=True)
if "sports" in what:
    df = slow.sports_moneylines(d0, d1)
    df.to_parquet(out / "sports.parquet", index=False)
    print("sports", len(df), flush=True)
if "bonds" in what:
    df = slow.near_expiry_markets(d0, d1)
    df.to_parquet(out / "bonds.parquet", index=False)
    print("bonds", len(df), flush=True)
if "baskets" in what:
    df = slow.multi_outcome_events(dt.date(2025, 6, 1), d1)
    df.to_parquet(out / "baskets.parquet", index=False)
    print("baskets", len(df), df.event_id.nunique() if len(df) else 0, flush=True)
