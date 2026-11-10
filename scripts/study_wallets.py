#!/usr/bin/env python3
"""Who makes money as a TAKER in 5-minute BTC markets, and does it persist?

For every public fill we score the taker's decision against the final outcome:
  BUY  at p -> profit = payout - p - fee        (per share)
  SELL at p -> profit = p - payout - fee
Wallets are ranked on the first half of the days and re-measured on the second
half. If "sharp" wallets stay sharp, copying them is a candidate strategy; if
not, a wallet's past profit is luck. Wallet addresses are public on-chain data.

    python scripts/study_wallets.py 2026-11-04 2026-11-09
"""
import datetime as dt
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from polylab.config import HIST, RESULTS  # noqa: E402
from polylab.data import polymarket as pm  # noqa: E402

OUT = HIST / "wallets"
OUT.mkdir(exist_ok=True)


def day_frame(day: dt.date) -> pd.DataFrame:
    p = OUT / f"{day}.parquet"
    if p.exists():
        return pd.read_parquet(p)
    meta = pd.read_parquet(HIST / "btc_5m" / f"meta_{day}.parquet")

    def one(r):
        try:
            tr = pm.trades_for_condition(r.condition_id)
        except Exception:
            return None
        if not tr:
            return None
        d = pd.DataFrame(tr)[["proxy_wallet", "side", "outcome_index", "size", "price", "timestamp"]]
        payout = np.where(d["outcome_index"] == 0, r.outcome_up, 1 - r.outcome_up)
        fee = 0.07 * d["price"] * (1 - d["price"])
        buy = d["side"] == "BUY"
        d["pnl"] = d["size"] * (np.where(buy, payout - d["price"], d["price"] - payout) - fee)
        d["notional"] = d["size"] * d["price"]
        d["rel"] = d["timestamp"] - r.start_ts
        d["start_ts"] = r.start_ts
        return d[["proxy_wallet", "start_ts", "rel", "size", "price", "notional", "pnl"]]

    with ThreadPoolExecutor(12) as ex:
        parts = [x for x in ex.map(one, list(meta.itertuples())) if x is not None]
    df = pd.concat(parts, ignore_index=True)
    df.to_parquet(p, index=False)
    return df


if __name__ == "__main__":
    d0, d1 = dt.date.fromisoformat(sys.argv[1]), dt.date.fromisoformat(sys.argv[2])
    days = [d0 + dt.timedelta(days=i) for i in range((d1 - d0).days + 1)]
    frames = []
    for d in days:
        f = day_frame(d)
        f["day"] = d
        frames.append(f)
        print(d, len(f), flush=True)
    t = pd.concat(frames, ignore_index=True)
    half = days[len(days) // 2]
    t["period"] = np.where(t["day"] < half, "first", "second")
    print(f"\n{len(t):,} taker fills, {t.proxy_wallet.nunique():,} wallets, notional ${t.notional.sum():,.0f}")
    print(f"all takers together: pnl ${t.pnl.sum():,.0f} = {t.pnl.sum() / t.notional.sum():+.2%} of notional")
    w = t.groupby(["proxy_wallet", "period"]).agg(n=("pnl", "size"), pnl=("pnl", "sum"), notional=("notional", "sum")).unstack()
    w.columns = [f"{a}_{b}" for a, b in w.columns]
    w = w.dropna()
    w = w[(w.n_first >= 300) & (w.n_second >= 300)].copy()
    w["roi_first"], w["roi_second"] = w.pnl_first / w.notional_first, w.pnl_second / w.notional_second
    print(f"wallets with >=300 taker fills in both halves: {len(w)}")
    print("share profitable in first half:", round(float((w.pnl_first > 0).mean()), 3),
          "| in second half:", round(float((w.pnl_second > 0).mean()), 3))
    print("rank correlation of ROI, first half vs second half:", round(float(w.roi_first.rank().corr(w.roi_second.rank())), 3))
    w["decile"] = pd.qcut(w.roi_first, 10, labels=False, duplicates="drop") + 1
    dec = w.groupby("decile").agg(wallets=("n_first", "size"), roi_first=("roi_first", "median"),
                                  roi_second_median=("roi_second", "median"),
                                  pnl_second=("pnl_second", "sum"), notional_second=("notional_second", "sum"),
                                  share_profitable_second=("pnl_second", lambda s: float((s > 0).mean())))
    dec["roi_second_pooled"] = dec.pnl_second / dec.notional_second
    pd.set_option("display.width", 200)
    print(dec.round(4).to_string())
    dec.reset_index().to_csv(RESULTS / "wallet_persistence.csv", index=False)
    # timing: when do winning takers trade?
    t["phase"] = pd.cut(t["rel"], [-10**6, 0, 60, 180, 240, 280, 10**6], labels=["pre-open", "0-60s", "60-180s", "180-240s", "240-280s", "last 20s+"])
    ph = t.groupby("phase", observed=True).agg(fills=("pnl", "size"), notional=("notional", "sum"), pnl=("pnl", "sum"))
    ph["roi"] = ph.pnl / ph.notional
    print(ph.round(4).to_string())
    ph.reset_index().to_csv(RESULTS / "taker_pnl_by_phase.csv", index=False)
