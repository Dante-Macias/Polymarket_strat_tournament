"""One-off studies that need more than one market at a time."""
import numpy as np
import pandas as pd

from .data.history import PRE
from .fees import taker_fee
from .sim import fills


def _seen(arr, i, max_age=10):
    seg = arr[max(i - max_age, 0):i]
    ok = np.flatnonzero(~np.isnan(seg))
    return float(seg[ok[-1]]) if len(ok) else float("nan")


def nested_pairs(m5_list, m15_list, spot, margin=0.0, delay=3, basis_guard=15.0) -> pd.DataFrame:
    """S14: 5-minute window vs the 15-minute window that ends at the same instant.

    Both settle on the same final price F. If strike5 > strike15 then "Up 5m"
    implies "Up 15m", so buying Up-15m + Down-5m pays at least $1 (and $2 when F
    lands between the strikes). Mirror image when strike5 < strike15.
    We only act when our ESTIMATED strikes differ by more than `basis_guard`
    dollars, so the ordering is not in doubt. One attempt per pair: the first
    second where the two seen asks cost less than 1 - margin after fees.
    """
    by_start = {m.start_ts: m for m in m15_list}
    rows = []
    for m5 in m5_list:
        m15 = by_start.get(m5.start_ts - 600)
        if m15 is None or not spot.has(m15.start_ts - 100, m5.start_ts + 301):
            continue
        # strike estimates a bot could make itself (exchange 60s averages; the basis cancels)
        k5 = spot.mean(m5.start_ts - 60, m5.start_ts)
        k15 = spot.mean(m15.start_ts - 60, m15.start_ts)
        if abs(k5 - k15) < basis_guard:
            continue
        s15, s5 = ("UP", "DOWN") if k5 > k15 else ("DOWN", "UP")
        true_order_ok = (m5.strike > m15.strike) == (k5 > k15)
        rec = dict(start_ts=m5.start_ts, gap=k5 - k15, order_ok=true_order_ok, triggered=False)
        for t in range(5, 285):
            i5, i15 = PRE + t, PRE + 600 + t
            a15 = _seen(m15.ask_hi, i15) if s15 == "UP" else 1 - _seen(m15.bid_lo, i15)
            a5 = _seen(m5.ask_hi, i5) if s5 == "UP" else 1 - _seen(m5.bid_lo, i5)
            if a15 != a15 or a5 != a5:
                continue
            cost = a15 + a5 + 0.07 * (a15 * (1 - a15) + a5 * (1 - a5))
            if cost < 1.0 - margin:
                f15 = fills.taker_fill(m15, s15, 600 + t, a15 + 0.02, delay)
                f5 = fills.taker_fill(m5, s5, t, a5 + 0.02, delay)
                pay15 = fills.settle(s15, m15.outcome_up) if f15 else 0.0
                pay5 = fills.settle(s5, m5.outcome_up) if f5 else 0.0
                c = (f15[1] + taker_fee(1, f15[1]) if f15 else 0.0) + (f5[1] + taker_fee(1, f5[1]) if f5 else 0.0)
                rec.update(triggered=True, t=t, seen_cost=cost, leg15=bool(f15), leg5=bool(f5), paid=c,
                           payout=pay15 + pay5, pnl=pay15 + pay5 - c)
                break
        rows.append(rec)
    return pd.DataFrame(rows)


def apply_day_stop(df: pd.DataFrame, take_profit: float | None = None, stop_loss: float | None = None) -> pd.DataFrame:
    """Keep only the trades a daily take-profit / stop-loss rule would have allowed.

    Trades are processed in time order within each UTC day; once the running
    day P&L reaches +take_profit (or -stop_loss) the rest of that day is skipped.
    """
    df = df.sort_values(["start_ts", "t_fill"])
    keep = np.ones(len(df), dtype=bool)
    day, run, stopped = None, 0.0, False
    for k, (d, st, pnl) in enumerate(zip(df["day"].to_numpy(), df["start_ts"].to_numpy(), df["pnl"].to_numpy())):
        if d != day:
            day, run, stopped, cur_mkt = d, 0.0, False, None
        if stopped and st != cur_mkt:
            keep[k] = False
            continue
        run += pnl
        cur_mkt = st
        if (take_profit is not None and run >= take_profit) or (stop_loss is not None and run <= -stop_loss):
            stopped = True
    return df[keep]


def daily_distribution(df: pd.DataFrame) -> dict:
    d = df.groupby("day")["pnl"].sum()
    g, r = d[d > 0], d[d <= 0]
    c = d.cumsum()
    return dict(days=len(d), trades=len(df), total=float(d.sum()), green_days=float((d > 0).mean()),
                avg_green=float(g.mean()) if len(g) else 0.0, avg_red=float(r.mean()) if len(r) else 0.0,
                worst_day=float(d.min()), best_day=float(d.max()),
                p5=float(d.quantile(0.05)), median=float(d.median()), p95=float(d.quantile(0.95)),
                max_dd=float((c.cummax().clip(lower=0) - c).max()))
