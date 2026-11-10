#!/usr/bin/env python3
"""Analyse the slow-family datasets (S16 sports, S18 bonds, S19 baskets, S20 sum arbitrage).

Writes CSV tables into results/ and prints them. Prices are historical mid/last
prices, so each study adds an explicit cost: half-spread + the market's taker fee.
"""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from polylab.config import HIST, RESULTS  # noqa: E402

SLOW = HIST / "slow"
pd.set_option("display.width", 250)
HALF_SPREAD = 0.01      # we assume we pay 1 cent above the recorded price


def tstat(x: pd.Series) -> float:
    return float(x.mean() / x.std() * math.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else 0.0


def two_sided(df: pd.DataFrame, pcol="p0", wcol="win0") -> pd.DataFrame:
    """One row per side of each binary market."""
    a = df.assign(price=df[pcol], win=df[wcol])
    b = df.assign(price=1 - df[pcol], win=1 - df[wcol])
    out = pd.concat([a, b], ignore_index=True)
    out = out[(out["price"] > 0.005) & (out["price"] < 0.995)].copy()
    out["cost"] = (out["price"] + HALF_SPREAD).clip(upper=0.999)
    out["cost"] += out["fee_rate"] * out["cost"] * (1 - out["cost"])
    out["pnl"] = out["win"] - out["cost"]          # per share
    return out


def bucket_table(s: pd.DataFrame, edges) -> pd.DataFrame:
    s = s.assign(bucket=pd.cut(s["price"], edges))
    g = s.groupby("bucket", observed=True)
    t = g.agg(n=("win", "size"), avg_price=("price", "mean"), win_rate=("win", "mean"),
              avg_cost=("cost", "mean"), edge_per_share=("pnl", "mean"))
    t["roi"] = t["edge_per_share"] / t["avg_cost"]
    t["t_stat"] = g["pnl"].apply(tstat)
    return t.reset_index()


def split(df: pd.DataFrame, col: str):
    cut = df[col].quantile(0.6)
    return df[df[col] <= cut], df[df[col] > cut]


def sports():
    df = pd.read_parquet(SLOW / "sports.parquet")
    s = two_sided(df)
    print(f"\n=== S16 sports moneylines: {len(df)} games, {df.league.value_counts().to_dict()}")
    print("fee rates seen:", df.fee_rate.value_counts().to_dict())
    edges = [0, 0.2, 0.35, 0.5, 0.65, 0.8, 1.0]
    t = bucket_table(s, edges)
    print(t.round(4).to_string(index=False))
    t.to_csv(RESULTS / "s16_sports_calibration.csv", index=False)
    rows = []
    is_, oos = split(s, "game_start")
    for x in (0.55, 0.65, 0.75):
        for label, part in (("in_sample", is_), ("out_of_sample", oos)):
            f = part[part["price"] >= x]
            rows.append(dict(rule=f"buy favourite >= {x}", sample=label, n=len(f), avg_price=f.price.mean(),
                             win_rate=f.win.mean(), edge_per_share=f.pnl.mean(), roi=f.pnl.sum() / f.cost.sum(), t_stat=tstat(f.pnl)))
    for label, part in (("in_sample", is_), ("out_of_sample", oos)):
        f = part[part["price"] < 0.35]
        rows.append(dict(rule="buy underdog < 0.35", sample=label, n=len(f), avg_price=f.price.mean(),
                         win_rate=f.win.mean(), edge_per_share=f.pnl.mean(), roi=f.pnl.sum() / f.cost.sum(), t_stat=tstat(f.pnl)))
    r = pd.DataFrame(rows)
    print(r.round(4).to_string(index=False))
    r.to_csv(RESULTS / "s16_sports_rules.csv", index=False)
    by = s[s.price >= 0.5].groupby("league").agg(n=("win", "size"), avg_price=("price", "mean"), win_rate=("win", "mean"),
                                                edge=("pnl", "mean")).round(4)
    print(by.to_string())


def bonds():
    df = pd.read_parquet(SLOW / "bonds.parquet")
    s = two_sided(df)
    print(f"\n=== S18 near-certain outcomes 24h before scheduled end: {len(df)} markets")
    t = bucket_table(s[s.price >= 0.5], [0.5, 0.7, 0.85, 0.90, 0.95, 0.98, 1.0])
    print(t.round(4).to_string(index=False))
    t.to_csv(RESULTS / "s18_bonds_calibration.csv", index=False)
    rows = []
    is_, oos = split(s, "snap")
    for lo, hi in ((0.90, 0.95), (0.95, 0.98), (0.98, 0.995), (0.95, 0.995)):
        for label, part in (("in_sample", is_), ("out_of_sample", oos)):
            f = part[(part.price >= lo) & (part.price < hi)]
            if not len(f):
                continue
            rows.append(dict(rule=f"buy {lo}-{hi}", sample=label, n=len(f), avg_price=f.price.mean(), win_rate=f.win.mean(),
                             edge_per_share=f.pnl.mean(), roi=f.pnl.sum() / f.cost.sum(), t_stat=tstat(f.pnl),
                             losers=int((f.win == 0).sum()), median_days_held=f.days_to_close.median()))
    r = pd.DataFrame(rows)
    print(r.round(4).to_string(index=False))
    r.to_csv(RESULTS / "s18_bonds_rules.csv", index=False)
    f = s[(s.price >= 0.95) & (s.price < 0.995)]
    print(f.groupby("fee_type").agg(n=("win", "size"), win_rate=("win", "mean"), avg_price=("price", "mean"),
                                    edge=("pnl", "mean")).round(4).to_string())
    print("losers at >=95c:", f[f.win == 0][["question", "price"]].head(12).to_string(index=False))


def baskets():
    df = pd.read_parquet(SLOW / "baskets.parquet")
    print(f"\n=== S19 engineered-ROI baskets: {df.event_id.nunique()} resolved single-winner events")
    rows, per_event = [], []
    for d in (30, 7, 1):
        col = f"p_{d}d"
        for eid, g in df.groupby("event_id"):
            g = g.dropna(subset=[col]).sort_values(col, ascending=False)
            if len(g) < 4 or g["won"].sum() != 1 or not (0.85 < g[col].sum() < 1.25):
                continue        # need a full, sane set of prices on that date
            p, won = g[col].to_numpy(), g["won"].to_numpy()
            for k in (1, 2, 3, 5, 8):
                if k > len(g):
                    continue
                cost = float(np.sum(p[:k] + 0.005 + 0.04 * p[:k] * (1 - p[:k])))
                hit = int(won[:k].sum())
                if cost >= 0.995:
                    continue    # basket costs ~$1 for a $1 payout: nothing to win
                per_event.append(dict(days_before=d, k=k, event=g["event"].iloc[0], cost=cost, hit=hit,
                                      ret=(1 / cost - 1) if hit else -1.0, end=g["end"].iloc[0]))
    pe = pd.DataFrame(per_event)
    for (d, k), g in pe.groupby(["days_before", "k"]):
        rows.append(dict(days_before=d, basket_size=k, events=len(g), avg_cost=g.cost.mean(), hit_rate=g.hit.mean(),
                         edge=g.hit.mean() - g.cost.mean(), avg_return=g.ret.mean(), t_stat=tstat(g.ret),
                         worst=g.ret.min()))
    r = pd.DataFrame(rows)
    print(r.round(4).to_string(index=False))
    r.to_csv(RESULTS / "s19_baskets.csv", index=False)
    pe.to_csv(RESULTS / "s19_baskets_events.csv", index=False)


def sumarb():
    df = pd.read_parquet(SLOW / "sumarb_scans.parquet")
    df["scan"] = (df["ts"] // 600).astype(int)
    print(f"\n=== S20 sum arbitrage: {df.scan.nunique()} live scans, {len(df)} event snapshots")
    ex = df[~df["augmented"]]
    rows = []
    for label, part in (("all events", df), ("exhaustive only", ex)):
        rows.append(dict(sample=label, snapshots=len(part), median_ask_sum=part.ask_sum.median(),
                         median_bid_sum=part.bid_sum.median(),
                         yes_arb=int((part.edge_buy_all_yes > 0.002).sum()), no_arb=int((part.edge_buy_all_no > 0.002).sum()),
                         best_yes_edge=part.edge_buy_all_yes.max(), best_no_edge=part.edge_buy_all_no.max()))
    r = pd.DataFrame(rows)
    print(r.round(4).to_string(index=False))
    r.to_csv(RESULTS / "s20_sumarb.csv", index=False)
    hits = ex[(ex.edge_buy_all_yes > 0.002) | (ex.edge_buy_all_no > 0.002)]
    cols = ["event", "n", "ask_sum", "bid_sum", "edge_buy_all_yes", "size_yes", "edge_buy_all_no", "size_no", "fee_rate"]
    print(hits[cols].round(4).to_string(index=False))
    hits[cols].to_csv(RESULTS / "s20_sumarb_hits.csv", index=False)


if __name__ == "__main__":
    for name in sys.argv[1:] or ["sports", "bonds", "baskets", "sumarb"]:
        if (SLOW / {"sports": "sports.parquet", "bonds": "bonds.parquet", "baskets": "baskets.parquet",
                    "sumarb": "sumarb_scans.parquet"}[name]).exists():
            globals()[name]()
        else:
            print(f"(no data yet for {name})")
