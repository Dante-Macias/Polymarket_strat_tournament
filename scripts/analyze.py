#!/usr/bin/env python3
"""Hypothesis-level analysis on top of the backtest runs (writes results/*.csv and prints).

    python scripts/analyze.py [A] [D] [E] [calib] [regimes] [live] [nested] [leadlag]
"""
import datetime as dt
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from polylab.config import HIST, LIVE, RESULTS  # noqa: E402
from polylab.data import binance  # noqa: E402
from polylab.metrics import summarize  # noqa: E402
from polylab.sim.market import SpotSeries, available_days, load_day  # noqa: E402
from polylab.studies import apply_day_stop, daily_distribution, nested_pairs  # noqa: E402

spec = importlib.util.spec_from_file_location("rb", ROOT / "scripts" / "run_backtests.py")
rb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rb)
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
COLS = ["name", "trades", "hit_rate", "avg_price", "pnl", "pnl_per_trade", "roi", "t_stat"]


def both_samples(names):
    is_days, oos_days = rb.split_days()
    base = rb.load_run("base")
    base = base[base["strategy"].isin(names)]
    isd = set(is_days)
    return base[base["day"].isin(isd)], base[~base["day"].isin(isd)]


def tab(df, label):
    t = pd.DataFrame([summarize(g, n) for n, g in df.groupby("strategy")])
    t.insert(0, "sample", label)
    return t


def probe() -> pd.DataFrame:
    p = pd.concat(pd.read_parquet(f) for f in sorted((HIST / "probe_btc_5m").glob("*.parquet")))
    is_days, _ = rb.split_days()
    p["sample"] = np.where(p["day"].isin(set(is_days)), "in_sample", "out_of_sample")
    return p


# ---------------------------------------------------------------------- A
def A():
    names = ["S01_early60_taker", "S01_early60_limit", "S01_early60_taker_fade", "S01_early60_limit_fade"]
    a, b = both_samples(names)
    t = pd.concat([tab(a, "in_sample"), tab(b, "out_of_sample"), tab(pd.concat([a, b]), "all")])
    print("\n=== Hypothesis A: a side at ~60c in the first 10 seconds")
    print(t[["sample"] + COLS].round(4).to_string(index=False))
    t.to_csv(RESULTS / "hypA_early60.csv", index=False)
    # calibration of early prices: what you pay (taker fill) vs how often it wins
    p = probe()
    p = p[p["t"].isin([2, 4, 6, 8, 10])]
    rows = []
    for side, px, win in (("UP", p["fill_up"], p["up"]), ("DOWN", p["fill_dn"], 1 - p["up"])):
        rows.append(pd.DataFrame({"price": px, "win": win, "fee": p["fee_rate"] * px * (1 - px), "day": p["day"]}))
    s = pd.concat(rows).dropna()
    s["bucket"] = pd.cut(s["price"], [0.30, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.80])
    g = s.groupby("bucket", observed=True)
    c = g.agg(n=("win", "size"), avg_paid=("price", "mean"), win_rate=("win", "mean"), fee=("fee", "mean"))
    c["edge_before_fee"] = c["win_rate"] - c["avg_paid"]
    c["edge_after_fee"] = c["edge_before_fee"] - c["fee"]
    print("\nPrice paid in seconds 2-10 vs. how often that side won (all days):")
    print(c.round(4).to_string())
    c.reset_index().to_csv(RESULTS / "hypA_early_price_calibration.csv", index=False)


# ---------------------------------------------------------------------- D
def D():
    names = [n for n in rb.grid.family_of() if n.startswith(("S04_", "S05_"))]
    a, b = both_samples(names)
    allt = pd.concat([a, b])
    n_markets = sum(len(pd.read_parquet(HIST / "btc_5m" / f"meta_{d}.parquet")) for d in available_days("btc", "5m"))
    rows = []
    for name, g in allt.groupby("strategy"):
        per = g.groupby("start_ts").agg(legs=("side", "nunique"), pnl=("pnl", "sum"), cost=("price", "sum"))
        both, one = per[per.legs == 2], per[per.legs == 1]
        rows.append(dict(strategy=name, markets=n_markets, both_legs=len(both), one_leg=len(one),
                         completion_rate=len(both) / max(len(per), 1),
                         share_of_all_markets_completed=len(both) / n_markets,
                         profit_per_completed_pair=both.pnl.mean() / 5 if len(both) else np.nan,
                         pnl_per_orphan_leg=one.pnl.mean() / 5 if len(one) else np.nan,
                         orphan_win_rate=float((one.pnl > 0).mean()) if len(one) else np.nan,
                         total_pnl=per.pnl.sum(), pnl_completed=both.pnl.sum(), pnl_orphans=one.pnl.sum(),
                         pnl_per_market_entered=per.pnl.mean()))
    r = pd.DataFrame(rows)
    print("\n=== Hypothesis D on the tape (5 shares per leg; per-share numbers in dollars)")
    print(r.round(4).to_string(index=False))
    r.to_csv(RESULTS / "hypD_pairs_backtest.csv", index=False)
    t = pd.concat([tab(a, "in_sample"), tab(b, "out_of_sample")])
    print(t[["sample"] + COLS].round(4).to_string(index=False))
    t.to_csv(RESULTS / "hypD_pairs_is_oos.csv", index=False)


def live():
    """Hypothesis D measured on REAL order books recorded by the paper engine."""
    db = LIVE / "paper.sqlite"
    if not db.exists():
        print("(no live recording yet)")
        return
    con = sqlite3.connect(db)
    s = pd.read_sql_query("SELECT ts,start_ts,t,up_bid,up_ask,dn_bid,dn_ask,up_asks,dn_asks FROM snapshots "
                          "WHERE t BETWEEN 0 AND 299", con)
    mk = pd.read_sql_query("SELECT start_ts,outcome_up FROM markets", con)
    con.close()
    s = s.dropna(subset=["up_ask", "dn_ask"])
    s["sum_ask"] = s["up_ask"] + s["dn_ask"]
    s["fees"] = 0.07 * (s.up_ask * (1 - s.up_ask) + s.dn_ask * (1 - s.dn_ask))
    s["spread_up"] = s["up_ask"] - s["up_bid"]
    hours = (s.ts.max() - s.ts.min()) / 3600
    out = dict(hours_recorded=hours, snapshots=len(s), markets=s.start_ts.nunique(),
               median_sum_of_asks=s.sum_ask.median(), min_sum_of_asks=s.sum_ask.min(),
               share_sum_below_1=float((s.sum_ask < 0.9999).mean()),
               share_sum_at_most_0_99=float((s.sum_ask <= 0.99 + 1e-9).mean()),
               share_profitable_after_taker_fees=float((s.sum_ask + s.fees < 0.9999).mean()),
               median_spread_up=s.spread_up.median(),
               median_ask_size_up=float(np.median([json.loads(x)[0][1] for x in s.up_asks.iloc[::20] if x and x != "[]"])))
    print("\n=== Hypothesis D on real order books (live recording)")
    for k, v in out.items():
        print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")
    pd.DataFrame([out]).to_csv(RESULTS / "hypD_live_books.csv", index=False)
    # resting bids on both sides, filled when the real ask comes down to our price
    rows = []
    mk = mk.dropna().set_index("start_ts")["outcome_up"]
    for x in (0.40, 0.44, 0.46, 0.48, 0.49):
        for st, g in s.groupby("start_ts"):
            g = g.sort_values("t")
            if st not in mk.index or g.t.min() > 8 or g.t.max() < 290:
                continue
            g0 = g[g.t >= 5]
            first = g0.iloc[0]
            if not (first.up_ask > x and first.dn_ask > x):
                continue
            fu, fd = bool((g0.up_ask <= x + 1e-9).any()), bool((g0.dn_ask <= x + 1e-9).any())
            up = mk[st]
            pnl = (fu * ((up == 1) - x)) + (fd * ((up == 0) - x))
            rows.append(dict(price=x, start_ts=st, legs=int(fu) + int(fd), pnl=pnl))
    if rows:
        r = pd.DataFrame(rows)
        g = r.groupby("price")
        t = g.agg(markets_entered=("legs", "size"), both=("legs", lambda v: int((v == 2).sum())),
                  one=("legs", lambda v: int((v == 1).sum())), none=("legs", lambda v: int((v == 0).sum())),
                  pnl_per_share_total=("pnl", "sum"), pnl_per_market=("pnl", "mean"))
        print("\nResting bids on both sides, real books (per share):")
        print(t.round(4).to_string())
        t.reset_index().to_csv(RESULTS / "hypD_live_resting_pairs.csv", index=False)


# ---------------------------------------------------------------------- E
def E():
    gi = pd.read_csv(RESULTS / "grid_in_sample.csv")
    go = pd.read_csv(RESULTS / "grid_out_of_sample.csv")
    for label, g in (("in-sample", gi), ("out-of-sample", go)):
        g = g[g["family"] == "S06_ahead"].copy()
        g["t"] = g["name"].str.extract(r"_t(\d+)_").astype(int)
        g["rule"] = g["name"].str.extract(r"_t\d+_(.*)$")
        print(f"\n=== Hypothesis E entry, {label}: ROI after fees by time into the window (rows) and threshold (cols)")
        print(g.pivot(index="t", columns="rule", values="roi").round(3).to_string())
        print("trades:")
        print(g.pivot(index="t", columns="rule", values="trades").to_string())
        print("hit rate / avg price paid:")
        print((g.pivot(index="t", columns="rule", values="hit_rate").round(3).astype(str) + "/"
               + g.pivot(index="t", columns="rule", values="avg_price").round(3).astype(str)).to_string())
    sel = pd.read_csv(RESULTS / "selected.csv").set_index("family")["selected"]
    cases = {"E entry (selected)": sel["S06_ahead"], "the literal rule: +$50 at 3:00": "S06_ahead_t180_usd50",
             "coin flip": "base_random_t30", "always the favourite": "base_favorite_t30",
             "trend follower (B)": sel["S02_trend"]}
    _, oos_days = rb.split_days()
    base = rb.load_run("base")
    rows = []
    for label, name in cases.items():
        for sample, df in (("all days", base), ("out-of-sample", base[base["day"].isin(set(oos_days))])):
            df = df[df["strategy"] == name]
            for tp, sl in ((None, None), (1.0, None), (2.0, None), (5.0, None), (2.0, 4.0), (None, 4.0)):
                kept = apply_day_stop(df, tp, sl)
                rows.append(dict(case=label, strategy=name, sample=sample,
                                 daily_take_profit=tp if tp else "none", daily_stop_loss=sl if sl else "none",
                                 **daily_distribution(kept),
                                 pnl_per_trade=kept.pnl.mean() if len(kept) else 0.0))
    r = pd.DataFrame(rows)
    print("\n=== Hypothesis E: the daily stop rule (5 shares per trade, dollars)")
    print(r.drop(columns=["strategy"]).round(3).to_string(index=False))
    r.to_csv(RESULTS / "hypE_daily_stop.csv", index=False)
    # full daily P&L series for the report
    name = cases["E entry (selected)"]
    d0 = base[base["strategy"] == name]
    daily = pd.DataFrame({"no_stop": d0.groupby("day").pnl.sum(),
                          "take_profit_2": apply_day_stop(d0, 2.0).groupby("day").pnl.sum()}).fillna(0.0)
    daily.to_csv(RESULTS / "hypE_daily_pnl_series.csv")


# ---------------------------------------------------------------------- calibration
def calib():
    p = probe()
    rows = []
    for side, px, win in (("UP", p["fill_up"], p["up"]), ("DOWN", p["fill_dn"], 1 - p["up"])):
        rows.append(pd.DataFrame({"t": p["t"], "price": px, "win": win, "fee": p["fee_rate"] * px * (1 - px),
                                  "sample": p["sample"], "day": p["day"]}))
    s = pd.concat(rows).dropna()
    s["edge"] = s["win"] - s["price"] - s["fee"]
    s["bucket"] = pd.cut(s["price"], [0, 0.10, 0.25, 0.40, 0.50, 0.60, 0.75, 0.90, 0.97, 1.0])
    s["phase"] = pd.cut(s["t"], [-1, 10, 60, 180, 240, 300], labels=["0-10s", "15-60s", "90-180s", "210-240s", "250-293s"])
    for sample in ("in_sample", "out_of_sample"):
        x = s[s["sample"] == sample]
        e = x.pivot_table(index="bucket", columns="phase", values="edge", aggfunc="mean", observed=True)
        n = x.pivot_table(index="bucket", columns="phase", values="edge", aggfunc="size", observed=True)
        print(f"\n=== Taker edge per share after fees, by price paid and time in window ({sample})")
        print(e.round(4).to_string())
        print(n.to_string())
        e.to_csv(RESULTS / f"calibration_edge_{sample}.csv")
        n.to_csv(RESULTS / f"calibration_n_{sample}.csv")
    # model calibration
    p["pb"] = (p["p_model"] * 10).clip(0, 9.999).astype(int) / 10
    m = p[p["t"].isin([30, 120, 240, 280])].pivot_table(index="pb", columns="t", values="up", aggfunc="mean")
    print("\nModel calibration: model P(Up) bucket vs actual Up frequency")
    print(m.round(3).to_string())
    m.to_csv(RESULTS / "model_calibration.csv")


# ---------------------------------------------------------------------- regimes
def regimes():
    names = list(pd.read_csv(RESULTS / "selected_names.csv")["strategy"])
    _, oos_days = rb.split_days()
    base = rb.load_run("base", oos_days)
    base = base[base["strategy"].isin(names)].copy()
    hour = (base["start_ts"] % 86400) // 3600
    base["session"] = pd.cut(hour, [-1, 7, 12, 20, 23], labels=["Asia 0-8", "Europe 8-13", "US 13-21", "late 21-24"])
    # daily realised volatility tercile
    vol = {}
    for d in oos_days:
        k = binance.load("BTCUSDT", "1s", d, d)
        c = k["close"].to_numpy()[::300]
        vol[d] = float(np.std(np.diff(np.log(c)))) if len(c) > 10 else np.nan
    v = pd.Series(vol)
    q = v.quantile([1 / 3, 2 / 3]).to_numpy()
    base["vol"] = base["day"].map(lambda d: "low vol" if vol[d] <= q[0] else ("mid vol" if vol[d] <= q[1] else "high vol"))
    base["half"] = np.where(base["day"] <= oos_days[len(oos_days) // 2], "first half", "second half")
    rows = []
    for col in ("session", "vol", "half"):
        for (name, key), g in base.groupby(["strategy", col], observed=True):
            rows.append(dict(strategy=name, split=col, bucket=str(key), trades=len(g), roi=g.pnl.sum() / g.stake.sum(),
                             pnl_per_trade=g.pnl.mean()))
    r = pd.DataFrame(rows)
    piv = r.pivot_table(index="strategy", columns=["split", "bucket"], values="roi")
    print("\n=== Out-of-sample ROI of the selected configs by regime")
    print(piv.round(3).to_string())
    r.to_csv(RESULTS / "regimes.csv", index=False)


# ---------------------------------------------------------------------- S14
def nested():
    days = [d for d in available_days("btc", "15m") if d in set(available_days("btc", "5m"))]
    k = int(len(days) * 0.6)
    rows = []
    for margin in (0.0, 0.02):
        for i, d in enumerate(days):
            spot = SpotSeries(binance.load("BTCUSDT", "1s", d - dt.timedelta(days=1), d))
            r = nested_pairs(load_day("btc", "5m", 300, d), load_day("btc", "15m", 900, d), spot, margin=margin)
            r["day"], r["sample"], r["margin"] = d, "in_sample" if i < k else "out_of_sample", margin
            rows.append(r)
    r = pd.concat(rows, ignore_index=True)
    out = []
    for (margin, sample), g in r.groupby(["margin", "sample"]):
        tr = g[g["triggered"]]
        both = tr[tr.leg15 & tr.leg5]
        out.append(dict(margin=margin, sample=sample, pairs_checked=len(g), strike_order_correct=g.order_ok.mean(),
                        triggered=len(tr), both_legs=len(both), one_leg=int((tr.leg15 ^ tr.leg5).sum()),
                        avg_seen_cost=tr.seen_cost.mean(), avg_paid_both=both.paid.mean(),
                        pnl_per_pair_both=both.pnl.mean(), share_double_payout=float((both.payout == 2).mean()),
                        share_zero_payout=float((both.payout == 0).mean()),
                        total_pnl_per_share=tr.pnl.sum(), pnl_one_leg=tr[tr.leg15 ^ tr.leg5].pnl.sum()))
    o = pd.DataFrame(out)
    print("\n=== S14: 5-minute vs 15-minute nested windows (per share)")
    print(o.round(4).to_string(index=False))
    o.to_csv(RESULTS / "s14_nested.csv", index=False)


# ---------------------------------------------------------------------- S13
def leadlag():
    from polylab.metrics import trades_frame
    from polylab.sim.engine import Backtester
    from polylab.strategies.fast import LeadLagTaker
    days = available_days("eth", "5m")
    k = int(len(days) * 0.6)
    frames = []
    for i, d in enumerate(days):
        eth = binance.load("ETHUSDT", "1s", d - dt.timedelta(days=1), d)
        btc = binance.load("BTCUSDT", "1s", d - dt.timedelta(days=1), d)
        if len(eth) < 150_000 or len(btc) < 150_000:
            continue
        S = [LeadLagTaker(kap, 30, m) for kap in (0.0, 0.5, 1.0) for m in (0.05, 0.08)]
        res = Backtester(SpotSeries(eth), aux={"btc": SpotSeries(btc)}).run(S, load_day("eth", "5m", 300, d))
        for v in res.values():
            if v:
                f = trades_frame(v)
                f["sample"] = "in_sample" if i < k else "out_of_sample"
                frames.append(f)
    t = pd.concat(frames, ignore_index=True)
    rows = []
    for (name, sample), g in t.groupby(["strategy", "sample"]):
        rows.append({"sample": sample, **summarize(g, name)})
    r = pd.DataFrame(rows)
    print("\n=== S13: BTC leads ETH (kappa 0 = plain fair-value taker on ETH)")
    print(r[["sample"] + COLS].round(4).to_string(index=False))
    r.to_csv(RESULTS / "s13_leadlag.csv", index=False)


if __name__ == "__main__":
    for name in sys.argv[1:] or ["A", "D", "E", "calib", "regimes", "live", "nested", "leadlag"]:
        globals()[name]()
