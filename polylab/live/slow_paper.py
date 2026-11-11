"""Paper engine for the slow bots: scans every few minutes, logs paper trades,
settles them when Polymarket resolves the market. Never places orders."""
import datetime as dt
import json
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

from ..config import GAMMA, LIVE, RESULTS
from ..data import polymarket as pm
from ..data.http import get_json
from ..fees import taker_fee
from ..sheet import write_sheet
from ..strategies.base import Trade
from .feed import top
from .paper import walk
from .store import Store

SPORT_TAGS = ("nfl", "nba", "nhl", "cfb", "mlb", "wnba", "cbb")


def _iso(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts(s):
    if not s:
        return None
    s = s.replace(" ", "T").replace("Z", "+00:00")
    if s.endswith("+00"):
        s += ":00"
    try:
        return dt.datetime.fromisoformat(s).timestamp()
    except ValueError:
        return None


class Scanner:
    """Finds candidate markets and attaches live books (best ask + ask ladder per outcome)."""

    def __init__(self):
        self.cache: dict = {}

    def _enrich(self, m: dict) -> dict | None:
        toks = json.loads(m.get("clobTokenIds") or "[]")
        outs = json.loads(m.get("outcomes") or "[]")
        if len(toks) != 2 or not m.get("acceptingOrders", True) or m.get("closed"):
            return None
        asks, ladders = [], []
        for tok in toks:
            try:
                b = pm.order_book(tok)
                _, a = top(b, 10)
            except Exception:
                a = []
            ladders.append(a)
            asks.append(a[0][0] if a else float("nan"))
        fee = (m.get("feeSchedule") or {}).get("rate")
        return dict(id=str(m["id"]), question=m.get("question", "")[:120], outcomes=outs, ask=asks, ladders=ladders,
                    fee_rate=fee if fee is not None else 0.05, slug=m.get("slug", ""), end=_ts(m.get("endDate")))

    def _enrich_all(self, ms):
        with ThreadPoolExecutor(8) as ex:
            return [x for x in ex.map(self._enrich, ms) if x]

    def games_starting(self, minutes: int):
        now = dt.datetime.now(dt.timezone.utc)
        ms = []
        for tag in SPORT_TAGS:
            try:
                evs = get_json(f"{GAMMA}/events", {"closed": "false", "tag_slug": tag, "limit": 100,
                                                   "end_date_min": _iso(now - dt.timedelta(hours=6)),
                                                   "end_date_max": _iso(now + dt.timedelta(days=2))})
            except Exception:
                continue
            for e in evs:
                for m in e.get("markets", []):
                    gs = _ts(m.get("gameStartTime"))
                    if m.get("sportsMarketType") == "moneyline" and gs and 0 < gs - now.timestamp() <= minutes * 60:
                        ms.append(m)
        return self._enrich_all(ms)

    def ending_between(self, h0: float, h1: float):
        now = dt.datetime.now(dt.timezone.utc)
        try:
            ms = get_json(f"{GAMMA}/markets", {"closed": "false", "limit": 200, "volume_num_min": 100000,
                                               "end_date_min": _iso(now + dt.timedelta(hours=h0)),
                                               "end_date_max": _iso(now + dt.timedelta(hours=h1))})
        except Exception:
            return []
        ms = [m for m in ms if "updown" not in (m.get("slug") or "")]
        return self._enrich_all(ms)

    def multi_outcome_events(self, top_n: int = 60):
        try:
            evs = get_json(f"{GAMMA}/events", {"closed": "false", "active": "true", "limit": 100,
                                               "order": "volume24hr", "ascending": "false"})
        except Exception:
            return []
        out = []
        for e in [e for e in evs if e.get("negRisk")][:top_n]:
            ms = [m for m in e.get("markets", []) if m.get("active") and not m.get("closed") and m.get("enableOrderBook")]
            if len(ms) < 2:
                continue
            em = self._enrich_all(ms)
            if len(em) != len(ms):
                continue
            out.append(dict(id=str(e["id"]), title=e["title"], augmented=bool(e.get("negRiskAugmented")), markets=em,
                            fee_rate=max(m["fee_rate"] for m in em)))
        return out

    def markets_by_id(self, ids):
        ms = []
        for i in ids:
            try:
                ms.append(get_json(f"{GAMMA}/markets/{i}"))
            except Exception:
                pass
        return self._enrich_all(ms)


class SlowPaperEngine:
    def __init__(self, bots, every_min: float = 5.0, db_name="paper_slow.sqlite", log=print):
        self.bots, self.every = bots, every_min * 60
        self.db_path = LIVE / db_name
        self.store = Store(self.db_path)
        self.scanner = Scanner()
        self.log = log
        # do not trade a market twice after a restart
        # tag format: "<market_id>:<outcome_index>" plus "|event:<event_id>" for sum-arbitrage legs
        by_name = {b.name: b for b in bots}
        for strategy, tag in self.store.db.execute("SELECT strategy, tag FROM trades"):
            b = by_name.get(strategy)
            if b is None or not tag:
                continue
            leg, _, event = tag.partition("|")
            mid, _, idx = leg.partition(":")
            b.done.update({mid, (mid, int(idx or 0))})
            if event:
                b.done.add(event.split(":", 1)[1])

    def _paper_fill(self, bot, o, m_by_id):
        m = m_by_id.get(o.market_id)
        if m is None:
            return
        px = walk(m["ladders"][o.outcome_index], 5.0)
        if px is None or px > o.price + 0.005:
            return
        fee = taker_fee(5.0, px, m["fee_rate"])
        tag = f"{o.market_id}:{o.outcome_index}" + (f"|{o.tag}" if o.tag else "")
        tr = Trade(bot.name, o.question[:60], int(time.time()), o.outcome, "taker", 0, 0, px, 5.0, fee, o.prob,
                   o.price, tag)
        self.store.add_trade(tr, time.time())
        self.log(f"  {bot.name}: BUY {o.outcome!r} @ {px:.3f}  ({o.question[:70]})")

    def scan_once(self):
        for bot in self.bots:
            try:
                items = bot.candidates(self.scanner)
                orders = bot.decide(items)
            except Exception:
                self.log(f"  ! {bot.name}: {traceback.format_exc(limit=2)}")
                continue
            m_by_id = {}
            for it in items:
                for m in it.get("markets", [it]):
                    m_by_id[m["id"]] = m
            for o in orders:
                self._paper_fill(bot, o, m_by_id)
        self.store.commit()

    def settle(self):
        rows = self.store.db.execute("SELECT id, tag, size, price, fee FROM trades WHERE pnl IS NULL").fetchall()
        for tid, tag, size, price, fee in rows:
            mid, idx = tag.split("|")[0].split(":")
            try:
                m = get_json(f"{GAMMA}/markets/{mid}")
            except Exception:
                continue
            if not m.get("closed"):
                continue
            pr = [float(x) for x in json.loads(m.get("outcomePrices") or "[]")]
            if len(pr) != 2:
                continue
            win = pr[int(idx)]
            if 0.01 < win < 0.99:
                continue          # disputed or 50/50: wait
            payout = size * round(win)
            self.store.settle_trade(tid, None, payout, payout - price * size - fee)
        self.store.commit()

    def run(self, hours: float | None = None):
        t_end = time.time() + hours * 3600 if hours else None
        while t_end is None or time.time() < t_end:
            t0 = time.time()
            self.log(f"[{time.strftime('%H:%M:%S')}] scan")
            try:
                self.scan_once()
                self.settle()
                write_sheet(self.db_path, RESULTS / "live_slow")
            except KeyboardInterrupt:
                break
            except Exception as e:
                self.log(f"  ! scan error: {e}")
            time.sleep(max(5, self.every - (time.time() - t0)))
