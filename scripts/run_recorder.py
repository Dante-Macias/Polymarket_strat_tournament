#!/usr/bin/env python3
"""Record order books + spot for Up/Down markets, without any strategies.

    python scripts/run_recorder.py --asset eth --duration 5m
    python scripts/run_recorder.py --asset btc --duration 15m

(BTC 5-minute books are already recorded by run_paper.py.) One process per
series; each writes data/live/recorder_<asset>_<duration>.sqlite.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from polylab.live.paper import PaperEngine  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--asset", default="eth", choices=["btc", "eth"])
ap.add_argument("--duration", default="5m", choices=["5m", "15m"])
ap.add_argument("--minutes", type=float, default=None)
a = ap.parse_args()
PaperEngine([], a.asset, a.duration, db_name=f"recorder_{a.asset}_{a.duration}.sqlite", sheet=False,
            log=lambda m: print(m, flush=True)).run(a.minutes * 60 if a.minutes else None)
