"""Paths and constants shared by the whole lab."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"            # local only, git-ignored
HIST = DATA / "history"         # downloaded history (parquet, one file per day)
LIVE = DATA / "live"            # recorder + paper-trading SQLite files
RESULTS = ROOT / "results"      # small result tables that ARE committed

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
DATA_API = "https://data-api.polymarket.com"
BINANCE = "https://data-api.binance.vision"      # public market-data mirror
BINANCE_BULK = "https://data.binance.vision"     # daily zip archives

DEFAULT_SHARES = 5.0            # every paper trade stakes 5 shares
USER_AGENT = "polylab-research/0.1 (read-only)"

for _p in (DATA, HIST, LIVE, RESULTS):
    _p.mkdir(parents=True, exist_ok=True)
