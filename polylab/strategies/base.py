"""Strategy interface shared by the backtester and the paper-trading engine.

A strategy only ever sees a `View` (information available *now*) and answers
with a list of `Order`s. It never touches raw data, so the same class runs on
history and live.
"""
from dataclasses import dataclass, field


@dataclass
class Order:
    side: str                 # "UP" or "DOWN" - we only ever BUY a side and hold to resolution
    kind: str = "taker"       # "taker" (cross the spread now) or "limit" (rest in the book)
    price: float = 0.999      # limit price (for taker: the most we accept to pay)
    size: float = 5.0
    ttl: int = 300            # seconds a limit order stays alive
    prob: float | None = None  # the bot's own probability that `side` wins
    tag: str = ""


@dataclass
class Cancel:
    tag: str


@dataclass
class Trade:
    strategy: str
    asset: str
    start_ts: int
    side: str
    kind: str
    t_decision: int
    t_fill: int
    price: float
    size: float
    fee: float
    prob: float | None
    mkt_price: float | None    # market's price for that side when we decided
    tag: str = ""
    outcome_up: int | None = None
    payout: float | None = None
    pnl: float | None = None


class Strategy:
    """Base class. Override `decide`; optionally `ticks` and `on_settle`."""

    name = "base"
    family = ""
    bucket = "fast"            # fast / daily / long
    market = "btc_5m"

    def ticks(self, dur: int):
        """Seconds (relative to window start) at which `decide` is called."""
        return range(0, dur)

    def decide(self, v) -> list:
        return []

    def on_market_end(self, v, trades: list[Trade]):
        """Called after resolution with this strategy's trades in that market."""


@dataclass
class DayStop:
    """Reusable daily take-profit / stop-loss tracker (Hypothesis E)."""
    take_profit: float | None = None
    stop_loss: float | None = None
    day: object = None
    pnl: float = 0.0
    stopped: bool = False
    log: list = field(default_factory=list)

    def roll(self, day):
        if day != self.day:
            if self.day is not None:
                self.log.append((self.day, self.pnl, self.stopped))
            self.day, self.pnl, self.stopped = day, 0.0, False

    def add(self, pnl: float):
        self.pnl += pnl
        if self.take_profit is not None and self.pnl >= self.take_profit:
            self.stopped = True
        if self.stop_loss is not None and self.pnl <= -self.stop_loss:
            self.stopped = True
