#!/usr/bin/env python3
"""Download Up/Down market history (metadata + trade tape) day by day.

Example:  python scripts/download_history.py --asset btc --duration 5m --start 2026-08-14 --end 2026-11-09
Resumable: days already on disk are skipped. Newest days are fetched first.
"""
import argparse
import datetime as dt
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from polylab.data.history import download_day  # noqa: E402

DUR = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400}

ap = argparse.ArgumentParser()
ap.add_argument("--asset", default="btc")
ap.add_argument("--duration", default="5m", choices=list(DUR))
ap.add_argument("--start", required=True)
ap.add_argument("--end", required=True)
ap.add_argument("--workers", type=int, default=12)
ap.add_argument("--ascending", action="store_true", help="oldest day first")
a = ap.parse_args()

d0, d1 = dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end)
days = [d0 + dt.timedelta(days=i) for i in range((d1 - d0).days + 1)]
for day in (days if a.ascending else reversed(days)):
    t = time.time()
    n = download_day(a.asset, a.duration, DUR[a.duration], day, a.workers)
    print(f"{a.asset} {a.duration} {day}: {n} markets in {time.time() - t:.0f}s", flush=True)
