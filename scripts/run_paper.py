#!/usr/bin/env python3
"""Run the paper-trading league live (no orders are ever sent).

    python scripts/run_paper.py                 # BTC 5-minute league, runs until Ctrl-C
    python scripts/run_paper.py --minutes 30    # stop after 30 minutes

Also records every order-book snapshot it sees into data/live/paper.sqlite and
rewrites results/live/ (leaderboard.csv, paper_league.xlsx) after each market.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from polylab.league import fast_league  # noqa: E402
from polylab.live.paper import PaperEngine  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--asset", default="btc", choices=["btc", "eth"])
ap.add_argument("--minutes", type=float, default=None)
a = ap.parse_args()


def log(msg):
    print(msg, flush=True)


PaperEngine(fast_league(), a.asset, "5m", log=log).run(a.minutes * 60 if a.minutes else None)
