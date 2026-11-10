"""Data collection for the slower market families (sports, near-certain "bonds",
multi-outcome baskets, multi-outcome sum arbitrage). Read-only.

Prices here come from CLOB /prices-history, which is a mid/last price, not an
executable quote, so every study adds an explicit spread assumption on top.
"""
import datetime as dt
import json
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from .data import polymarket as pm


def _ts(s: str | None) -> int | None:
    if not s:
        return None
    s = s.replace(" ", "T").replace("Z", "+00:00")
    if s.endswith("+00"):
        s += ":00"
    try:
        return int(dt.datetime.fromisoformat(s).timestamp())
    except ValueError:
        return None


def _iso(d: dt.date) -> str:
    return f"{d}T00:00:00Z"


def month_windows(d0: dt.date, d1: dt.date, step_days: int = 14):
    """Gamma refuses offsets beyond ~2000 rows, so long ranges are fetched in short date windows."""
    a = d0
    while a < d1:
        b = min(a + dt.timedelta(days=step_days), d1)
        yield a, b
        a = b


def paged_events(max_pages=20, **params) -> list[dict]:
    out = []
    for i in range(max_pages):
        try:
            page = pm.list_events(limit=100, offset=100 * i, **params)
        except RuntimeError:
            break
        out += page
        if len(page) < 100:
            break
    return out


def price_at(token: str, ts: int, lookback: int = 6 * 3600, fidelity: int = 10) -> float | None:
    """Last recorded price at or before `ts` (None if nothing in the lookback)."""
    h = pm.price_history(token, startTs=ts - lookback, endTs=ts, fidelity=fidelity)
    h = [x for x in h if x["t"] <= ts]
    return float(h[-1]["p"]) if h else None


def _winner(m: dict) -> int | None:
    pr = [float(x) for x in json.loads(m.get("outcomePrices") or "[]")]
    if len(pr) != 2 or not m.get("closed"):
        return None
    if pr[0] > 0.99:
        return 0
    if pr[1] > 0.99:
        return 1
    return None       # 50/50 or cancelled resolutions are dropped


# ------------------------------------------------------------------ sports
def sports_moneylines(d0: dt.date, d1: dt.date, tags=("nfl", "nba", "mlb", "nhl", "cfb", "wnba")) -> pd.DataFrame:
    """Two-outcome game-winner markets with the price shortly before the game started."""
    jobs = []
    for tag in tags:
        evs = [e for a, b in month_windows(d0, d1)
               for e in paged_events(closed="true", tag_slug=tag, end_date_min=_iso(a), end_date_max=_iso(b), volume_min=20000)]
        for e in evs:
            for m in e.get("markets", []):
                if m.get("sportsMarketType") != "moneyline":
                    continue
                gs, w = _ts(m.get("gameStartTime")), _winner(m)
                toks = json.loads(m.get("clobTokenIds") or "[]")
                if gs is None or w is None or len(toks) != 2:
                    continue
                jobs.append((tag, e["title"], m, gs, w, toks[0]))

    def one(j):
        tag, title, m, gs, w, tok = j
        try:
            p = price_at(tok, gs - 300)
        except Exception:
            p = None
        fee = (m.get("feeSchedule") or {}).get("rate")
        return dict(league=tag, title=title, game_start=gs, p0=p, win0=int(w == 0),
                    volume=float(m.get("volumeNum") or 0), fee_rate=fee if fee is not None else 0.05)

    with ThreadPoolExecutor(10) as ex:
        rows = list(ex.map(one, jobs))
    return pd.DataFrame(rows).dropna(subset=["p0"]).drop_duplicates(["title", "game_start"])


# ------------------------------------------------------------------ bonds
def near_expiry_markets(d0: dt.date, d1: dt.date, min_volume=100_000, hours_before=24, max_markets=6000) -> pd.DataFrame:
    """Binary markets with the YES price `hours_before` their SCHEDULED end date.

    Using the scheduled end (known in advance) instead of the actual resolution
    time avoids look-ahead. Markets already closed by then are skipped.
    """
    ms = []
    for a, b in month_windows(d0, d1):
        for i in range(4):
            try:
                page = pm.list_markets(closed="true", limit=500, offset=500 * i, end_date_min=_iso(a), end_date_max=_iso(b),
                                       volume_num_min=min_volume, order="volumeNum", ascending="false")
            except RuntimeError:
                break
            ms += page
            if len(page) < 100:
                break
    seen = set()
    ms = [m for m in ms if not (m["id"] in seen or seen.add(m["id"]))][:max_markets * 3]
    jobs = []
    for m in ms:
        end, closed_t, w = _ts(m.get("endDate")), _ts(m.get("closedTime")), _winner(m)
        toks = json.loads(m.get("clobTokenIds") or "[]")
        if None in (end, closed_t, w) or len(toks) != 2 or "updown" in (m.get("slug") or ""):
            continue
        snap = end - hours_before * 3600
        if closed_t <= snap:
            continue
        jobs.append((m, snap, w, toks[0]))

    def one(j):
        m, snap, w, tok = j
        try:
            p = price_at(tok, snap, lookback=12 * 3600, fidelity=30)
        except Exception:
            p = None
        fs = m.get("feeSchedule") or {}
        return dict(question=m["question"][:90], snap=snap, p0=p, win0=int(w == 0), fee_type=m.get("feeType") or "none",
                    fee_rate=fs.get("rate") or 0.0, volume=float(m.get("volumeNum") or 0),
                    neg_risk=bool(m.get("negRisk")), days_to_close=(_ts(m.get("closedTime")) - snap) / 86400)

    with ThreadPoolExecutor(10) as ex:
        rows = list(ex.map(one, jobs))
    return pd.DataFrame(rows).dropna(subset=["p0"])


# ------------------------------------------------------------------ baskets
def multi_outcome_events(d0: dt.date, d1: dt.date, min_volume=500_000, days_before=(30, 7, 1)) -> pd.DataFrame:
    """Resolved 'exactly one winner' events: YES price of every outcome N days before the end."""
    evs = [e for a, b in month_windows(d0, d1, 30)
           for e in paged_events(closed="true", end_date_min=_iso(a), end_date_max=_iso(b), volume_min=min_volume,
                                 order="volume", ascending="false")]
    seen = set()
    evs = [e for e in evs if not (e["id"] in seen or seen.add(e["id"]))]
    jobs = []
    for e in evs:
        if not e.get("negRisk"):
            continue
        ms = [m for m in e.get("markets", []) if m.get("closed") and _winner(m) is not None]
        winners = [m for m in ms if _winner(m) == 0]
        end = _ts(e.get("endDate"))
        if len(ms) < 4 or len(winners) != 1 or end is None:
            continue
        for m in ms:
            jobs.append((e, m, end))

    def one(j):
        e, m, end = j
        tok = json.loads(m["clobTokenIds"])[0]
        try:
            h = pm.price_history(tok, interval="max", fidelity=1440)
        except Exception:
            h = []
        row = dict(event=e["title"], event_id=e["id"], end=end, n_markets=len(e["markets"]), volume=float(e.get("volume") or 0),
                   outcome=m.get("groupItemTitle") or m["question"][:60], won=int(_winner(m) == 0),
                   closed_t=_ts(m.get("closedTime")))
        for d in days_before:
            pts = [x for x in h if x["t"] <= end - d * 86400]
            row[f"p_{d}d"] = float(pts[-1]["p"]) if pts and pts[-1]["t"] >= end - (d + 4) * 86400 else None
        return row

    with ThreadPoolExecutor(10) as ex:
        rows = list(ex.map(one, jobs))
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ sum arbitrage (live books)
def scan_sum_arb(top_events=120, min_volume=100_000) -> pd.DataFrame:
    """Snapshot of live multi-outcome events: cost of buying every YES, and of every NO."""
    evs = paged_events(closed="false", active="true", order="volume24hr", ascending="false", max_pages=6)
    evs = [e for e in evs if e.get("negRisk") and float(e.get("volume") or 0) >= min_volume][:top_events]
    out = []

    def book(tok):
        try:
            b = pm.order_book(tok)
            bids = sorted(((float(x["price"]), float(x["size"])) for x in b.get("bids", [])), reverse=True)
            asks = sorted((float(x["price"]), float(x["size"])) for x in b.get("asks", []))
            return (bids[0] if bids else (0.0, 0.0)), (asks[0] if asks else (1.0, 0.0))
        except Exception:
            return None

    for e in evs:
        ms = [m for m in e.get("markets", []) if m.get("active") and not m.get("closed") and m.get("enableOrderBook")]
        if len(ms) < 2:
            continue
        with ThreadPoolExecutor(8) as ex:
            books = list(ex.map(lambda m: book(json.loads(m["clobTokenIds"])[0]), ms))
        if any(b is None for b in books):
            continue
        fee_rate = max(((m.get("feeSchedule") or {}).get("rate") or 0.0) for m in ms)
        ask_sum = sum(b[1][0] for b in books)
        bid_sum = sum(b[0][0] for b in books)
        fee_yes = sum(fee_rate * b[1][0] * (1 - b[1][0]) for b in books)
        fee_no = sum(fee_rate * b[0][0] * (1 - b[0][0]) for b in books)
        n = len(ms)
        out.append(dict(ts=time.time(), event=e["title"], n=n, augmented=bool(e.get("negRiskAugmented")),
                        ask_sum=ask_sum, bid_sum=bid_sum, fee_rate=fee_rate,
                        # buy every YES: pays $1 if the listed outcomes are exhaustive
                        edge_buy_all_yes=1 - ask_sum - fee_yes,
                        size_yes=min(b[1][1] for b in books),
                        # buy every NO (= sell every YES at the bids): n-1 of them pay $1
                        edge_buy_all_no=(n - 1) - sum(1 - b[0][0] for b in books) - fee_no,
                        size_no=min(b[0][1] for b in books),
                        volume=float(e.get("volume") or 0)))
    return pd.DataFrame(out)
