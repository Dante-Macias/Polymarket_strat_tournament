"""The live results sheet: CSV files plus one Excel workbook.

  results/live/leaderboard.csv      one row per bot, ranked
  results/live/trades_<bot>.csv     every paper trade of that bot
  results/live/paper_league.xlsx    the same, one tab per bot + a Leaderboard tab

Rewritten after every settled market, so opening the file always shows the
latest state (re-open it in Excel/Numbers to refresh).
"""
import sqlite3
from pathlib import Path

import pandas as pd

from .metrics import summarize

LEADER_COLS = ["name", "trades", "days", "hit_rate", "avg_price", "pnl", "pnl_per_trade", "roi",
               "edge_per_share", "brier", "brier_market", "sharpness", "max_dd", "green_days",
               "t_stat", "p_value", "trades_needed"]


def load_trades(db_path: Path) -> pd.DataFrame:
    con = sqlite3.connect(db_path, timeout=30)
    df = pd.read_sql_query("SELECT * FROM trades", con)
    con.close()
    if len(df):
        df["day"] = pd.to_datetime(df["start_ts"], unit="s").dt.date
        df["time_utc"] = pd.to_datetime(df["ts_fill"], unit="s").dt.strftime("%Y-%m-%d %H:%M:%S")
    return df


def leaderboard(df: pd.DataFrame) -> pd.DataFrame:
    done = df.dropna(subset=["pnl"]).copy()
    if not len(done):
        return pd.DataFrame(columns=LEADER_COLS)
    done["win"] = (done["payout"] > 0).astype(int)
    rows = [summarize(g, name) for name, g in done.groupby("strategy")]
    lb = pd.DataFrame(rows)[LEADER_COLS].sort_values("pnl_per_trade", ascending=False)
    return lb.round(4)


def write_sheet(db_path: Path, out_dir: Path) -> pd.DataFrame:
    out_dir.mkdir(parents=True, exist_ok=True)
    df = load_trades(db_path)
    lb = leaderboard(df) if len(df) else pd.DataFrame(columns=LEADER_COLS)
    lb.to_csv(out_dir / "leaderboard.csv", index=False)
    cols = ["time_utc", "strategy", "asset", "start_ts", "side", "kind", "t_decision", "t_fill", "price", "size",
            "fee", "prob", "mkt_price", "outcome_up", "payout", "pnl"]
    try:
        with pd.ExcelWriter(out_dir / "paper_league.xlsx") as xl:
            lb.to_excel(xl, sheet_name="Leaderboard", index=False)
            for name, g in (df.groupby("strategy") if len(df) else []):
                g[cols].to_csv(out_dir / f"trades_{name}.csv", index=False)
                g[cols].to_excel(xl, sheet_name=name[:31], index=False)
    except PermissionError:      # workbook open in Excel on Windows; CSVs are still updated
        pass
    return lb
