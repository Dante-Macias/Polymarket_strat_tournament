#!/usr/bin/env python3
"""Download Binance spot klines day by day. Example:
python scripts/download_binance.py --symbol BTCUSDT --interval 1s --start 2026-08-13 --end 2026-11-09"""
import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from polylab.data.binance import download_day  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--symbol", default="BTCUSDT")
ap.add_argument("--interval", default="1s")
ap.add_argument("--start", required=True)
ap.add_argument("--end", required=True)
a = ap.parse_args()
day, d0 = dt.date.fromisoformat(a.end), dt.date.fromisoformat(a.start)
while day >= d0:
    try:
        n = download_day(a.symbol, a.interval, day)
        print(a.symbol, a.interval, day, n, flush=True)
    except Exception as e:
        print("!", day, e, flush=True)
    day -= dt.timedelta(days=1)
