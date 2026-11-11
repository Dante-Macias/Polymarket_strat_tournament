"""Paper bots for the daily and long buckets (sports, near-certain outcomes,
multi-outcome sum arbitrage, sportsbook-line value).

Unlike the 5-minute bots these do not see a second-by-second View. Each bot
gets a list of candidate markets every few minutes (already enriched with the
live order book) and returns paper orders. All orders are taker orders for 5
shares at the current best ask, held to resolution.

Parameters are the ones fixed in the offline studies (FINDINGS.md section 8);
the backtests said none of these is profitable, so they run as a forward check,
not because they are expected to win.
"""
import csv
import time
from dataclasses import dataclass
from pathlib import Path

from ..config import DATA


@dataclass
class SlowOrder:
    market_id: str
    outcome_index: int
    outcome: str
    question: str
    price: float            # the ask we are willing to pay
    prob: float | None
    tag: str = ""           # groups legs of one trade (sum arbitrage)


class SlowBot:
    name = "slow"
    family = ""
    bucket = "daily"

    def __init__(self):
        self.done: set = set()   # market ids already traded (one trade per market)

    def candidates(self, scanner) -> list:
        return []

    def decide(self, items) -> list[SlowOrder]:
        return []


class SportsFavourite(SlowBot):
    """S16: buy the pre-game favourite when its ask is >= `min_price`, within
    `minutes` before the scheduled start."""
    family, bucket = "S16_sports", "daily"

    def __init__(self, min_price=0.75, minutes=15):
        super().__init__()
        self.min_price, self.minutes = min_price, minutes
        self.name = f"S16_sports_fav_{int(min_price * 100)}"

    def candidates(self, scanner):
        return scanner.games_starting(self.minutes)

    def decide(self, items):
        out = []
        for m in items:
            if m["id"] in self.done:
                continue
            i = max(range(2), key=lambda k: m["ask"][k] if m["ask"][k] == m["ask"][k] else -1)
            a = m["ask"][i]
            if a == a and self.min_price <= a < 0.99:
                self.done.add(m["id"])
                out.append(SlowOrder(m["id"], i, m["outcomes"][i], m["question"], a, a))
        return out


class NearCertain(SlowBot):
    """S18: buy the side priced between lo and hi about 24 hours before the scheduled end."""
    family, bucket = "S18_bonds", "daily"

    def __init__(self, lo=0.95, hi=0.995, hours=(20, 28)):
        super().__init__()
        self.lo, self.hi, self.hours = lo, hi, hours
        self.name = f"S18_bonds_{int(lo * 100)}"

    def candidates(self, scanner):
        return scanner.ending_between(*self.hours)

    def decide(self, items):
        out = []
        for m in items:
            if m["id"] in self.done:
                continue
            for i in range(2):
                a = m["ask"][i]
                if a == a and self.lo <= a <= self.hi:
                    self.done.add(m["id"])
                    out.append(SlowOrder(m["id"], i, m["outcomes"][i], m["question"], a, a))
                    break
        return out


class SumArb(SlowBot):
    """S20: in an exhaustive multi-outcome event, buy one YES of every outcome when
    the asks plus taker fees add up to less than $1 - margin."""
    family, bucket = "S20_sumarb", "long"

    def __init__(self, margin=0.01):
        super().__init__()
        self.margin = margin
        self.name = f"S20_sumarb_m{int(margin * 100)}"

    def candidates(self, scanner):
        return scanner.multi_outcome_events()

    def decide(self, events):
        out = []
        for e in events:
            if e["id"] in self.done or e["augmented"]:
                continue          # "augmented" events can add outcomes later -> not exhaustive
            asks = [m["ask"][0] for m in e["markets"]]
            if any(a != a for a in asks):
                continue
            cost = sum(a + e["fee_rate"] * a * (1 - a) for a in asks)
            if cost < 1.0 - self.margin:
                self.done.add(e["id"])
                tag = f"event:{e['id']}"
                out += [SlowOrder(m["id"], 0, m["outcomes"][0], m["question"], m["ask"][0], None, tag)
                        for m in e["markets"]]
        return out


class SharpLine(SlowBot):
    """S17: buy when Polymarket's ask is below a sharp sportsbook's no-vig
    probability by `margin`.

    The lab has no free odds feed, so the fair probabilities come from a CSV you
    fill in yourself (or from any odds source you add later):
        data/odds/sharp_lines.csv  with columns  market_id,outcome_index,fair_prob,source
    With an empty or missing file the bot simply never trades.
    """
    family, bucket = "S17_sharp_line", "daily"

    def __init__(self, margin=0.03, path: Path = DATA / "odds" / "sharp_lines.csv"):
        super().__init__()
        self.margin, self.path = margin, path
        self.name = f"S17_sharp_line_m{int(margin * 100)}"

    def lines(self) -> dict:
        if not self.path.exists():
            return {}
        with open(self.path) as f:
            return {(r["market_id"], int(r["outcome_index"])): float(r["fair_prob"]) for r in csv.DictReader(f)}

    def candidates(self, scanner):
        ids = sorted({k[0] for k in self.lines()})
        return scanner.markets_by_id(ids) if ids else []

    def decide(self, items):
        fair = self.lines()
        out = []
        for m in items:
            for i in range(2):
                p, a = fair.get((m["id"], i)), m["ask"][i]
                if p is None or a != a or (m["id"], i) in self.done:
                    continue
                if p - a - m["fee_rate"] * a * (1 - a) >= self.margin:
                    self.done.add((m["id"], i))
                    out.append(SlowOrder(m["id"], i, m["outcomes"][i], m["question"], a, p))
        return out


def slow_league():
    return [SportsFavourite(0.75), SportsFavourite(0.55), NearCertain(0.95), NearCertain(0.90),
            SumArb(0.01), SharpLine(0.03)]


def now() -> float:
    return time.time()
