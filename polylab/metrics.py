"""Performance metrics and significance tests for a list of trades.

Glossary (kept short on purpose):
  hit rate   - share of trades that paid out.
  ROI        - profit divided by money staked.
  Sharpe     - average daily profit divided by its day-to-day variability, annualised
               (x sqrt(365)). Higher = steadier. Meaningless with few days.
  drawdown   - largest peak-to-trough fall of cumulative profit.
  Brier      - mean squared error of the bot's probabilities (0 = perfect, 0.25 = coin flip).
  edge       - what was actually won per share minus what was paid per share (fees included).
  t-stat / p - how surprising the average profit is if the true edge were zero. Days are
               treated as the independent unit (trades inside a day are correlated).
"""
import math

import numpy as np
import pandas as pd


def trades_frame(trades) -> pd.DataFrame:
    df = pd.DataFrame([t.__dict__ for t in trades])
    if len(df):
        df["day"] = pd.to_datetime(df["start_ts"], unit="s").dt.date
        df["win"] = (df["payout"] > 0).astype(int)
        df["stake"] = df["price"] * df["size"] + df["fee"]
    return df


def daily_pnl(df: pd.DataFrame) -> pd.Series:
    return df.groupby("day")["pnl"].sum() if len(df) else pd.Series(dtype=float)


def max_drawdown(pnl: np.ndarray) -> float:
    if len(pnl) == 0:
        return 0.0
    c = np.cumsum(pnl)
    return float(np.max(np.maximum.accumulate(np.maximum(c, 0)) - c))


def norm_sf(z: float) -> float:
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def day_clustered_t(df: pd.DataFrame) -> tuple[float, float]:
    """t-statistic of mean pnl per trade with day-clustered standard errors, and one-sided p."""
    if len(df) < 2:
        return 0.0, 0.5
    g = df.groupby("day")["pnl"].agg(["sum", "count"])
    n, k = g["count"].sum(), len(g)
    if k < 3:
        return 0.0, 0.5
    mean = g["sum"].sum() / n
    resid = g["sum"] - mean * g["count"]
    se = math.sqrt((resid ** 2).sum() * k / (k - 1)) / n
    if se == 0:
        return 0.0, 0.5
    t = mean / se
    return float(t), float(norm_sf(t))


def trades_needed(df: pd.DataFrame, z: float = 2.0) -> float:
    """Trades needed before the observed mean edge would be `z` standard errors from zero."""
    if len(df) < 2 or df["pnl"].mean() == 0:
        return float("inf")
    return float((z * df["pnl"].std() / abs(df["pnl"].mean())) ** 2)


def summarize(df: pd.DataFrame, name: str = "") -> dict:
    if not len(df):
        return {"name": name, "trades": 0}
    d = daily_pnl(df)
    t, p = day_clustered_t(df)
    prob = df["prob"].dropna() if "prob" in df else pd.Series(dtype=float)
    brier = float(((df.loc[prob.index, "prob"] - df.loc[prob.index, "win"]) ** 2).mean()) if len(prob) else float("nan")
    mk = df["mkt_price"].dropna()
    brier_mkt = float(((mk - df.loc[mk.index, "win"]) ** 2).mean()) if len(mk) else float("nan")
    sharp = float((df["prob"] - df["mkt_price"]).abs().mean()) if len(prob) and len(mk) else float("nan")
    cost = (df["price"] * df["size"] + df["fee"]).sum()
    return {
        "name": name,
        "trades": int(len(df)),
        "days": int(len(d)),
        "hit_rate": float(df["win"].mean()),
        "avg_price": float(df["price"].mean()),
        "pnl": float(df["pnl"].sum()),
        "pnl_per_trade": float(df["pnl"].mean()),
        "roi": float(df["pnl"].sum() / cost) if cost else 0.0,
        "edge_per_share": float((df["pnl"] / df["size"]).mean()),
        "sharpe": float(d.mean() / d.std() * math.sqrt(365)) if len(d) > 2 and d.std() > 0 else float("nan"),
        "max_dd": max_drawdown(df.sort_values(["start_ts", "t_fill"])["pnl"].to_numpy()),
        "green_days": float((d > 0).mean()) if len(d) else float("nan"),
        "brier": brier,
        "brier_market": brier_mkt,
        "sharpness": sharp,
        "t_stat": t,
        "p_value": p,
        "trades_needed": trades_needed(df),
    }


def calibration_curve(prob: pd.Series, win: pd.Series, bins: int = 10) -> pd.DataFrame:
    b = (prob * bins).clip(0, bins - 1e-9).astype(int)
    g = pd.DataFrame({"bin": b, "prob": prob, "win": win}).groupby("bin")
    return g.agg(n=("win", "size"), avg_prob=("prob", "mean"), win_rate=("win", "mean")).reset_index()


def bonferroni(p: float, n_tests: int) -> float:
    return min(1.0, p * n_tests)


def bootstrap_days(df: pd.DataFrame, n: int = 2000, seed: int = 1) -> tuple[float, float, float]:
    """Resample whole days. Returns (5th pct, 95th pct of total pnl, P(total <= 0))."""
    d = daily_pnl(df).to_numpy()
    if len(d) < 3:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    tot = d[rng.integers(0, len(d), size=(n, len(d)))].sum(axis=1)
    return float(np.percentile(tot, 5)), float(np.percentile(tot, 95)), float((tot <= 0).mean())
