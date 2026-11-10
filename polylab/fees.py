"""Polymarket fee model (docs.polymarket.com/trading/fees, verified Nov 2026).

fee (USDC) = shares * rate * p * (1 - p)        - charged to TAKERS only.
Makers (resting limit orders) pay nothing and may earn a rebate, which the
lab ignores to stay conservative.
"""

FEE_RATE = {
    "crypto": 0.07, "sports": 0.05, "finance": 0.04, "politics": 0.04,
    "economics": 0.05, "culture": 0.05, "weather": 0.05, "other": 0.05,
    "mentions": 0.04, "tech": 0.04, "geopolitics": 0.0, "combos": 0.05,
}


def taker_fee(shares: float, price: float, rate: float = 0.07) -> float:
    """Fee in USDC for a taker fill of `shares` at `price`."""
    return round(shares * rate * price * (1.0 - price), 5)


def breakeven_winrate(price: float, rate: float = 0.07, taker: bool = True) -> float:
    """Win probability needed to break even buying one share at `price`."""
    cost = price + (rate * price * (1.0 - price) if taker else 0.0)
    return cost
