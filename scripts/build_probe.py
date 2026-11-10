#!/usr/bin/env python3
"""Build the research probe table for an Up/Down series (one parquet per day)."""
import argparse
import datetime as dt
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from polylab.config import HIST  # noqa: E402
from polylab.data import binance  # noqa: E402
from polylab.research_probe import probe_markets  # noqa: E402
from polylab.sim.market import SpotSeries, available_days, load_day  # noqa: E402

DUR = {"5m": 300, "15m": 900}
SYM = {"btc": "BTCUSDT", "eth": "ETHUSDT"}


def one(args):
    asset, duration, day = args
    out = HIST / f"probe_{asset}_{duration}" / f"{day}.parquet"
    if out.exists():
        return day, 0
    df = binance.load(SYM[asset], "1s", day - dt.timedelta(days=1), day)
    if len(df) < 100000:
        return day, -1
    spot = SpotSeries(df)
    p = probe_markets(load_day(asset, duration, DUR[duration], day), spot)
    out.parent.mkdir(exist_ok=True)
    p.to_parquet(out, index=False)
    return day, len(p)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", default="btc")
    ap.add_argument("--duration", default="5m")
    a = ap.parse_args()
    days = available_days(a.asset, a.duration)
    with ProcessPoolExecutor(4) as ex:
        for day, n in ex.map(one, [(a.asset, a.duration, d) for d in days]):
            if n:
                print(day, n, flush=True)
