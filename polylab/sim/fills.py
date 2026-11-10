"""Fill simulation from the trade tape (pure functions, unit-tested).

We do not have historical order books, only prints. Rules:

TAKER (marketable buy, "fill-and-kill" with a limit price)
  A decision made at second t can only be filled by liquidity that shows up in
  the tape at stamps [t+delay, t+delay+window). `delay` covers both our own
  latency and the fact that tape stamps are Polygon block times: measured, a
  print's stamp trails the exchange move that caused it by 3-4 seconds (see
  FINDINGS.md). The default delay of 4 therefore means "about one second of
  real latency", and it stops the simulator from trading on prints that
  really happened before the decision. Price = worst print of the first second that has evidence
  (+ optional slippage). No evidence, or price above the limit -> no fill.

MAKER (resting buy at limit L)
  Filled only when a later print trades STRICTLY THROUGH the limit (someone
  sold lower than our bid). Touching the price is not enough because we would
  be behind other orders in the queue. This naturally includes adverse
  selection: we get filled exactly when the market moves against us.

Everything is expressed for buying a SIDE ("UP" or "DOWN"). Buying DOWN at q
is the mirror of selling UP at 1-q.
"""
import numpy as np

from ..data.history import PRE

EPS = 1e-6


def taker_fill(m, side: str, t: int, limit: float = 0.999, delay: int = 4, window: int = 3,
               slip: float = 0.0, worst: bool = False, px_mode: str = "mid"):
    """Return (fill_rel, price) or None."""
    a, b = PRE + t + delay, PRE + t + delay + window
    end = PRE + m.dur            # no trading after the window closes
    b = min(b, end)
    if a >= b:
        return None
    if side == "UP":
        hi, lo = m.ask_hi[a:b], m.ask_lo[a:b]
    else:
        hi, lo = 1.0 - m.bid_lo[a:b], 1.0 - m.bid_hi[a:b]
    ev = hi if px_mode == "worst" else (lo if px_mode == "best" else 0.5 * (hi + lo))
    ok = ~np.isnan(ev)
    if not ok.any():
        return None
    if worst:
        px, k = float(np.nanmax(ev)), int(np.nanargmax(ev))
    else:
        k = int(np.argmax(ok))
        px = float(ev[k])
    px = min(px + slip, 0.999)
    if px > limit + EPS:
        return None
    return t + delay + k, px


def maker_fill(m, side: str, t: int, price: float, ttl: int, delay: int = 4, through: float = 0.0):
    """Resting buy of `side` at `price` placed at t. Return fill_rel or None.

    through: how far past our price a print must trade (0 -> strictly below).
    """
    a = PRE + t + delay
    b = min(PRE + t + ttl, PRE + m.dur)
    if a >= b:
        return None
    if side == "UP":            # someone must SELL Up below our bid
        hit = m.bid_lo[a:b] < price - through - EPS
    else:                       # someone must lift Up above 1 - our Down bid
        hit = m.ask_hi[a:b] > (1.0 - price) + through + EPS
    if not hit.any():
        return None
    return t + delay + int(np.argmax(hit))


def settle(side: str, outcome_up: int) -> float:
    """Payout per share at resolution."""
    return 1.0 if (side == "UP") == (outcome_up == 1) else 0.0
