#!/usr/bin/env python3
"""Paper league for the daily / long buckets (sports favourites, near-certain
outcomes, sum arbitrage, sportsbook-line value). Scans every 5 minutes.

    python scripts/run_slow_league.py            # until Ctrl-C
    python scripts/run_slow_league.py --once     # one scan, then exit

Results: results/live_slow/leaderboard.csv and paper_league.xlsx.
Sportsbook lines (optional): data/odds/sharp_lines.csv with columns
market_id,outcome_index,fair_prob,source
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from polylab.live.slow_paper import SlowPaperEngine  # noqa: E402
from polylab.strategies.slow import slow_league  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--once", action="store_true")
ap.add_argument("--every", type=float, default=5.0, help="minutes between scans")
a = ap.parse_args()
eng = SlowPaperEngine(slow_league(), a.every, log=lambda m: print(m, flush=True))
if a.once:
    eng.scan_once()
    eng.settle()
else:
    eng.run()
