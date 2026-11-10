"""Unit tests for the fill logic and P&L math (run with: pytest -q)."""
import numpy as np
import pytest

from polylab.data.history import PRE, tape_to_bars
from polylab.fees import taker_fee
from polylab.sim import fills
from polylab.sim.engine import Backtester
from polylab.sim.market import POST, Market, SpotSeries
from polylab.strategies.base import Order, Strategy

DUR = 300
L = PRE + DUR + POST


def mk(outcome_up=1, strike=100.0):
    nan = lambda: np.full(L, np.nan, dtype=np.float32)  # noqa: E731
    z = lambda: np.zeros(L, dtype=np.float32)  # noqa: E731
    return Market("btc", 10_000, DUR, strike, strike + (1 if outcome_up else -1), outcome_up, 0.07,
                  nan(), nan(), z(), nan(), nan(), z())


def put(m, rel, d, lo, hi=None, vol=10):
    i = PRE + rel
    if d == 1:
        m.ask_lo[i], m.ask_hi[i], m.ask_vol[i] = lo, hi or lo, vol
    else:
        m.bid_lo[i], m.bid_hi[i], m.bid_vol[i] = lo, hi or lo, vol


def test_fee_formula_matches_docs_table():
    # docs: 100 shares of a crypto market at $0.50 -> $1.75, at $0.30 -> $1.47
    assert taker_fee(100, 0.50) == pytest.approx(1.75)
    assert taker_fee(100, 0.30) == pytest.approx(1.47)
    assert taker_fee(100, 0.30) == pytest.approx(taker_fee(100, 0.70))
    assert taker_fee(100, 0.50, rate=0.05) == pytest.approx(1.25)   # sports


def test_tape_to_bars_maps_everything_to_up_price():
    tr = [dict(timestamp=1005, price=0.60, size=5, outcome_index=0, side="BUY"),    # lifts Up ask 0.60
          dict(timestamp=1005, price=0.38, size=5, outcome_index=1, side="SELL"),   # = Up ask 0.62
          dict(timestamp=1006, price=0.41, size=7, outcome_index=1, side="BUY"),    # = Up bid 0.59
          dict(timestamp=1006, price=0.58, size=3, outcome_index=0, side="SELL")]   # Up bid 0.58
    b = tape_to_bars(tr, 1000, 300).set_index(["rel", "dir"])
    assert b.loc[(5, 1), "lo"] == pytest.approx(0.60) and b.loc[(5, 1), "hi"] == pytest.approx(0.62)
    assert b.loc[(6, -1), "lo"] == pytest.approx(0.58) and b.loc[(6, -1), "hi"] == pytest.approx(0.59)
    assert b.loc[(6, -1), "vol"] == pytest.approx(10)


def test_taker_cannot_use_prints_before_the_delay():
    m = mk()
    put(m, 10, 1, 0.55)        # too early: stamped at the decision second
    put(m, 14, 1, 0.61, 0.63)
    assert fills.taker_fill(m, "UP", 10, delay=3, window=3) == (14, pytest.approx(0.63))
    assert fills.taker_fill(m, "UP", 10, delay=3, window=1) is None     # nothing at t+3 only
    assert fills.taker_fill(m, "UP", 10, limit=0.62) is None            # above our limit


def test_taker_down_uses_mirror_of_up_bid():
    m = mk()
    put(m, 20, -1, 0.70, 0.72)   # Up bid evidence 0.70..0.72 -> Down ask 0.28..0.30
    ft, px = fills.taker_fill(m, "DOWN", 17)
    assert ft == 20 and px == pytest.approx(0.30)


def test_taker_never_fills_after_close():
    m = mk()
    put(m, 301, 1, 0.99)
    assert fills.taker_fill(m, "UP", 297) is None


def test_maker_needs_trade_through_not_touch():
    m = mk()
    put(m, 30, -1, 0.45)            # touches a 0.45 bid: no fill
    assert fills.maker_fill(m, "UP", 10, 0.45, ttl=100) is None
    put(m, 40, -1, 0.44)            # trades through
    assert fills.maker_fill(m, "UP", 10, 0.45, ttl=100) == 40
    assert fills.maker_fill(m, "UP", 10, 0.45, ttl=20) is None          # expired first
    assert fills.maker_fill(m, "UP", 38, 0.45, ttl=100) is None         # print inside the delay


def test_maker_down_side():
    m = mk()
    put(m, 50, 1, 0.56)             # Up lifted at 0.56 -> Down sold at 0.44
    assert fills.maker_fill(m, "DOWN", 10, 0.45, ttl=100) == 50
    assert fills.maker_fill(m, "DOWN", 10, 0.44, ttl=100) is None


class BuyOnce(Strategy):
    name = "buy_once"

    def __init__(self, side, kind="taker", price=0.999):
        self.side, self.kind, self.price = side, kind, price

    def ticks(self, dur):
        return [10]

    def decide(self, v):
        return [Order(self.side, self.kind, self.price, 5.0, ttl=200, prob=0.7)]


def spot_series():
    import pandas as pd
    ts = np.arange(0, 20_000)
    return SpotSeries(pd.DataFrame({"ts": ts, "close": 100.0, "volume": 1.0, "taker_buy_vol": 0.5}))


def test_pnl_math_winner_and_loser():
    bt = Backtester(spot_series())
    m = mk(outcome_up=1)
    put(m, 13, 1, 0.60)
    put(m, 13, -1, 0.58)
    win = bt.run([BuyOnce("UP")], [m])["buy_once"][0]
    fee = 5 * 0.07 * 0.6 * 0.4
    assert win.price == pytest.approx(0.60) and win.fee == pytest.approx(fee)
    assert win.pnl == pytest.approx(5 * 1.0 - 5 * 0.60 - fee)
    lose = bt.run([BuyOnce("DOWN")], [m])["buy_once"][0]
    assert lose.price == pytest.approx(0.42)
    assert lose.pnl == pytest.approx(-5 * 0.42 - 5 * 0.07 * 0.42 * 0.58)


def test_maker_fill_pays_no_fee():
    bt = Backtester(spot_series())
    m = mk(outcome_up=0)
    put(m, 60, -1, 0.39)
    tr = bt.run([BuyOnce("UP", "limit", 0.40)], [m])["buy_once"][0]
    assert tr.kind == "limit" and tr.fee == 0 and tr.price == pytest.approx(0.40)
    assert tr.pnl == pytest.approx(-2.0)


def test_view_has_no_lookahead_on_quotes_and_spot():
    from polylab.sim.engine import View
    m = mk()
    put(m, 20, 1, 0.80)
    v = View(m, spot_series(), [], 0.0)
    v.t = 20
    assert np.isnan(v.ask("UP"))     # print stamped at 20 is not visible at t=20
    v.t = 21
    assert v.ask("UP") == pytest.approx(0.80)
    v.t = 40
    assert np.isnan(v.ask("UP"))     # stale after 10s
