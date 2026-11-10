"""Paper-trading engine: runs strategies against live data, never sends an order.

Fill rules (real order books, so simpler than the backtester):
  taker  - decided at second t, filled on the NEXT book snapshot by walking the
           real asks for the order size; skipped if that costs more than the limit.
  limit  - rests at its price; counts as filled the first time the real best ask
           of that side is at or below our bid (a seller would have hit us).
Trades settle on the official Polymarket resolution.
"""
import time
import traceback

from ..config import LIVE, RESULTS
from ..data import polymarket as pm
from ..data.http import get_json
from ..fees import taker_fee
from ..sheet import write_sheet
from ..strategies.base import Cancel, Trade
from .feed import SYM, LiveView, MarketFeed, SpotFeed
from .store import Store


def walk(asks, size):
    """Average price to buy `size` shares from an ask ladder [(price, size)...]; None if too thin."""
    need, cost = size, 0.0
    for px, sz in asks:
        take = min(need, sz)
        cost += take * px
        need -= take
        if need <= 1e-9:
            return cost / size
    return None


class PaperEngine:
    def __init__(self, strategies, asset="btc", duration="5m", db_name="paper.sqlite", sheet=True, log=print):
        self.S = strategies
        self.mf, self.spot = MarketFeed(asset, duration), SpotFeed(SYM[asset])
        self.asset, self.duration = asset, duration
        self.db_path = LIVE / db_name
        self.store = Store(self.db_path)
        self.sheet_dir = RESULTS / "live" if sheet else None
        self.log = log
        self.history: list = []
        self.basis: float | None = None
        self.view: LiveView | None = None
        self.state: dict = {}          # per strategy: ticks, last_t, fills, takers, limits
        self.unsettled: dict = {}      # start_ts -> {view, trades:[(id, Trade)], by_strategy}
        self.need_tape = any(getattr(s, "source", "") == "tape" for s in strategies)

    # ---------------------------------------------------------------- helpers
    def _update_basis(self):
        """Chainlink minus exchange, from the newest window whose strike is published."""
        for back in (1, 2, 3):
            st = self.mf.start_ts - back * self.mf.dur
            try:
                k = self.mf.published_strike(st)
            except Exception:
                k = None
            if k:
                self.basis = k - self.spot.mean(st - 60, st)
                return
        if self.basis is None:
            self.basis = 0.0

    def _new_market(self):
        self._update_basis()
        self.view = LiveView(self.mf, self.spot, self.history, self.basis)
        late = int(time.time()) - self.mf.start_ts
        # joined mid-window (e.g. just started): skip the decision times already missed
        skip = late if late > 3 else -10**9
        self.state = {s.name: {"ticks": sorted(set(s.ticks(self.mf.dur))), "last": skip, "fills": [],
                               "takers": [], "limits": []} for s in self.S}
        self.unsettled[self.mf.start_ts] = {"view": self.view, "trades": []}
        self.store.market(self.asset, self.duration, self.mf.start_ts, self.mf.info["slug"], self.view.strike, self.basis)
        self.log(f"[{time.strftime('%H:%M:%S')}] new market {self.mf.info['slug']} strike~{self.view.strike:.1f} basis {self.basis:.1f}")

    def _tape_flow(self, n=30):
        try:
            d = get_json(f"{pm.DATA_API}/v2/trades", {"condition": self.mf.info["condition_id"], "limit": 500},
                         retries=1, timeout=5).get("data") or []
        except Exception:
            return 0.0
        now, a, b = time.time(), 0.0, 0.0
        for r in d:
            if now - r["timestamp"] > n:
                continue
            lift = (r["outcome_index"] == 0) == (r["side"] == "BUY")
            if lift:
                a += r["size"]
            else:
                b += r["size"]
        return (a - b) / (a + b) if a + b > 0 else 0.0

    def _record(self, s, tr: Trade):
        tid = self.store.add_trade(tr, time.time())
        self.state[s.name]["fills"].append(tr)
        self.unsettled[tr.start_ts]["trades"].append((tid, tr, s))
        self.log(f"    {s.name}: {tr.kind} BUY {tr.side} {tr.size:g} @ {tr.price:.3f} (bot p={tr.prob}, mkt={tr.mkt_price})")

    def _process_fills(self, t):
        for s in self.S:
            st = self.state[s.name]
            for o, t_dec, mkt in st["takers"]:
                px = walk(self.mf.books[o.side][1], o.size)
                if px is not None and px <= o.price + 1e-9:
                    fee = taker_fee(o.size, px, self.view.fee_rate)
                    self._record(s, Trade(s.name, self.asset, self.mf.start_ts, o.side, "taker", t_dec, t, px,
                                          o.size, fee, o.prob, mkt, o.tag))
            st["takers"] = []
            keep = []
            for o, t_dec, mkt, expiry in st["limits"]:
                ask = self.mf.best(o.side)[1]
                if ask == ask and ask <= o.price + 1e-9:
                    self._record(s, Trade(s.name, self.asset, self.mf.start_ts, o.side, "limit", t_dec, t, o.price,
                                          o.size, 0.0, o.prob, mkt, o.tag))
                elif t < expiry:
                    keep.append((o, t_dec, mkt, expiry))
            st["limits"] = keep

    def _decide(self, t):
        v = self.view
        v.t = t
        for s in self.S:
            st = self.state[s.name]
            due = [k for k in st["ticks"] if st["last"] < k <= t]
            if not due:
                continue
            st["last"] = t
            v.fills = st["fills"]
            try:
                orders = s.decide(v) or []
            except Exception:
                self.log(f"  ! {s.name} decide() failed:\n{traceback.format_exc()}")
                continue
            for o in orders:
                if isinstance(o, Cancel):
                    st["limits"] = [x for x in st["limits"] if x[0].tag != o.tag]
                elif o.kind == "taker":
                    st["takers"].append((o, t, v.mid(o.side)))
                else:
                    a = v.ask(o.side)
                    if a == a and a <= o.price + 1e-9:
                        continue     # post-only: a bid at/above the ask would not rest, so it is rejected
                    st["limits"].append((o, t, v.mid(o.side), t + o.ttl))

    def _settle(self):
        for st_ts in sorted(self.unsettled):
            if st_ts + self.mf.dur > time.time() - 20:
                continue
            u = self.unsettled[st_ts]
            if time.time() < u.get("next_check", 0):
                continue
            u["next_check"] = time.time() + 20
            try:
                res = self.mf.resolution(st_ts)
            except Exception:
                res = None
            if not res:
                continue
            up = res["outcome_up"]
            self.store.resolve(self.asset, self.duration, st_ts, res["strike"], res["final"], up)
            by = {}
            for tid, tr, s in u["trades"]:
                tr.outcome_up = up
                tr.payout = tr.size if (tr.side == "UP") == (up == 1) else 0.0
                tr.pnl = tr.payout - tr.price * tr.size - tr.fee
                self.store.settle_trade(tid, up, tr.payout, tr.pnl)
                by.setdefault(s.name, (s, []))[1].append(tr)
            v = u["view"]
            v.t = self.mf.dur
            for s in self.S:
                s.on_market_end(v, by.get(s.name, (s, []))[1])
            self.history.append((st_ts, up, res["strike"], res["final"]))
            del self.unsettled[st_ts]
            self.store.commit()
            pnl = sum(tr.pnl for _, tr, _ in u["trades"])
            self.log(f"[{time.strftime('%H:%M:%S')}] settled {st_ts}: {'UP' if up else 'DOWN'} "
                     f"({len(u['trades'])} paper trades, pnl {pnl:+.2f})")
            if self.sheet_dir:
                write_sheet(self.db_path, self.sheet_dir)

    # ---------------------------------------------------------------- main loop
    def run(self, seconds: float | None = None):
        self.log("warming up spot history ...")
        self.spot.warmup()
        t_end = time.time() + seconds if seconds else None
        last_sec = 0
        while t_end is None or time.time() < t_end:
            now = time.time()
            if int(now) == last_sec:
                time.sleep(max(0.02, int(now) + 1.02 - now))
                continue
            last_sec = int(now)
            try:
                self.spot.poll()
                if self.mf.roll(now):
                    self._new_market()
                if not self.view:
                    continue
                self.mf.poll_books()
                t = last_sec - self.mf.start_ts
                if self.need_tape and t % 5 == 0:
                    self.view.tape_flow = self._tape_flow()
                self.store.snapshot(now, self.asset, self.duration, self.mf.start_ts, t, self.spot.close[-1], self.mf.books)
                self._process_fills(t)
                self._decide(t)
                if last_sec % 10 == 0:
                    self.store.commit()
                    self._settle()
            except KeyboardInterrupt:
                break
            except Exception as e:     # network hiccup: log, keep running
                self.log(f"  ! loop error: {e}")
                time.sleep(1)
        self.store.commit()
