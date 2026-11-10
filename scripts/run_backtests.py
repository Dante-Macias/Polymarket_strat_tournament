#!/usr/bin/env python3
"""Phase 3 pipeline for the 5-minute BTC strategies.

    python scripts/run_backtests.py grid       # run every grid configuration on every day
    python scripts/run_backtests.py select     # pick one config per family on IN-SAMPLE days only
    python scripts/run_backtests.py stress     # re-run the selected configs under harsher assumptions
    python scripts/run_backtests.py            # all three

In-sample = first 60% of days, out-of-sample = last 40%. The selection rule is
mechanical (highest in-sample t-stat, >= 200 trades), so nobody "peeks".
"""
import datetime as dt
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from polylab import grid  # noqa: E402
from polylab.config import DATA, RESULTS  # noqa: E402
from polylab.data import binance  # noqa: E402
from polylab.metrics import bonferroni, bootstrap_days, summarize, trades_frame  # noqa: E402
from polylab.sim.engine import Backtester  # noqa: E402
from polylab.sim.market import SpotSeries, available_days, load_day  # noqa: E402

BT = DATA / "bt"
IS_FRACTION = 0.6
MIN_IS_TRADES = 200
STRESS = {
    "slow_fills": dict(delay=5, worst=True, slip=0.01),      # 5s latency, worst print, +1c slippage
    "fees_x1.5": dict(fee_mult=1.5),
    "maker_through_1c": dict(maker_through=0.01),             # limit orders need a 1c trade-through
}
KEEP = ["strategy", "start_ts", "side", "kind", "t_decision", "t_fill", "price", "size", "fee", "prob",
        "mkt_price", "tag", "outcome_up", "payout", "pnl", "day", "win", "stake"]


def run_day(args):
    day, run, names, kw = args
    out = BT / run / f"{day}.parquet"
    if out.exists():
        return day
    df = binance.load("BTCUSDT", "1s", day - dt.timedelta(days=1), day)
    if len(df) < 150_000:
        return None
    strategies = [s for s in grid.all_strategies() if names is None or s.name in names]
    res = Backtester(SpotSeries(df), **kw).run(strategies, load_day("btc", "5m", 300, day))
    frames = [trades_frame(v)[KEEP] for v in res.values() if v]
    out.parent.mkdir(parents=True, exist_ok=True)
    (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=KEEP)).to_parquet(out, index=False)
    return day


def run_all(run: str, days, names=None, **kw):
    with ProcessPoolExecutor(4) as ex:
        for d in ex.map(run_day, [(d, run, names, kw) for d in days]):
            pass
    return load_run(run, days)


def load_run(run: str, days=None) -> pd.DataFrame:
    files = sorted((BT / run).glob("*.parquet"))
    if days is not None:
        want = {str(d) for d in days}
        files = [f for f in files if f.stem in want]
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    df["day"] = pd.to_datetime(df["start_ts"], unit="s").dt.date
    return df


def split_days():
    days = available_days("btc", "5m")
    k = int(len(days) * IS_FRACTION)
    return days[:k], days[k:]


def table(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame([summarize(g, n) for n, g in df.groupby("strategy")])


def stage_grid():
    is_days, oos_days = split_days()
    print(f"grid: {len(is_days)} in-sample days ({is_days[0]}..{is_days[-1]}), "
          f"{len(oos_days)} out-of-sample days ({oos_days[0]}..{oos_days[-1]})", flush=True)
    run_all("base", is_days + oos_days)


def stage_select():
    is_days, oos_days = split_days()
    fam = grid.family_of()
    t_is = table(load_run("base", is_days)).set_index("name")
    t_is["family"] = t_is.index.map(fam)
    t_is.reset_index().to_csv(RESULTS / "grid_in_sample.csv", index=False)
    picks = []
    for f, g in t_is.groupby("family"):
        ok = g[g["trades"] >= MIN_IS_TRADES]
        if not len(ok):
            ok = g
        picks.append(ok["t_stat"].idxmax())
    pd.Series(picks, name="strategy").to_csv(RESULTS / "selected_names.csv", index=False)
    # ---- only now is out-of-sample opened
    oos = load_run("base", oos_days)
    t_oos = table(oos).set_index("name")
    t_oos["family"] = t_oos.index.map(fam)
    t_oos.reset_index().to_csv(RESULTS / "grid_out_of_sample.csv", index=False)
    n_fam = len(picks)
    rows = []
    for name in picks:
        a, b = t_is.loc[name], t_oos.loc[name] if name in t_oos.index else None
        lo, hi, p0 = bootstrap_days(oos[oos["strategy"] == name]) if b is not None else (None, None, None)
        fam_oos = t_oos[t_oos["family"] == fam[name]]
        rows.append({
            "family": fam[name], "selected": name, "configs_in_family": int((t_is["family"] == fam[name]).sum()),
            "is_trades": a["trades"], "is_hit": a["hit_rate"], "is_avg_price": a["avg_price"], "is_pnl_per_trade": a["pnl_per_trade"],
            "is_roi": a["roi"], "is_t": a["t_stat"],
            "oos_trades": b["trades"] if b is not None else 0, "oos_days": b["days"] if b is not None else 0,
            "oos_hit": b["hit_rate"] if b is not None else None, "oos_avg_price": b["avg_price"] if b is not None else None,
            "oos_pnl": b["pnl"] if b is not None else None, "oos_pnl_per_trade": b["pnl_per_trade"] if b is not None else None,
            "oos_roi": b["roi"] if b is not None else None, "oos_sharpe": b["sharpe"] if b is not None else None,
            "oos_max_dd": b["max_dd"] if b is not None else None, "oos_green_days": b["green_days"] if b is not None else None,
            "oos_t": b["t_stat"] if b is not None else None, "oos_p": b["p_value"] if b is not None else None,
            "oos_p_bonferroni": bonferroni(b["p_value"], n_fam) if b is not None else None,
            "oos_boot_p5": lo, "oos_boot_p95": hi, "oos_boot_p_loss": p0,
            "oos_trades_needed": b["trades_needed"] if b is not None else None,
            "family_oos_share_positive": float((fam_oos["pnl"] > 0).mean()),
            "family_oos_median_roi": float(fam_oos["roi"].median()),
        })
    sel = pd.DataFrame(rows).sort_values("oos_t", ascending=False)
    sel.to_csv(RESULTS / "selected.csv", index=False)
    pd.set_option("display.width", 250)
    print(sel[["family", "selected", "is_trades", "is_roi", "is_t", "oos_trades", "oos_hit", "oos_avg_price",
               "oos_roi", "oos_t", "oos_p_bonferroni", "family_oos_share_positive"]].round(3).to_string())


def stage_stress():
    _, oos_days = split_days()
    names = set(pd.read_csv(RESULTS / "selected_names.csv")["strategy"])
    rows = []
    base = table(load_run("base", oos_days)).set_index("name")
    for name in names:
        if name in base.index:
            rows.append({"scenario": "base", **base.loc[name].to_dict(), "name": name})
    for scen, kw in STRESS.items():
        t = table(run_all(f"stress_{scen}", oos_days, names, **kw))
        for r in t.to_dict("records"):
            rows.append({"scenario": scen, **r})
    out = pd.DataFrame(rows)
    out.to_csv(RESULTS / "stress.csv", index=False)
    print(out.pivot_table(index="name", columns="scenario", values="roi").round(4).to_string())


if __name__ == "__main__":
    stages = sys.argv[1:] or ["grid", "select", "stress"]
    if "grid" in stages:
        stage_grid()
    if "select" in stages:
        stage_select()
    if "stress" in stages:
        stage_stress()
