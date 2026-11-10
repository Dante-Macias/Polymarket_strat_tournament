"""Fair-value model for an Up/Down market that settles on a 60-second average.

Assume the price follows a driftless random walk with volatility `sigma`
(dollars per square-root-second). "Up" wins if A >= K, where K is the strike
and A is the average price over the last `twap` seconds of the window.

* Before the averaging starts (tau0 seconds away): A - S_now is normal with
  variance sigma^2 * (tau0 + twap/3). (The average of a random walk over a
  span T has variance sigma^2 * T / 3.)
* Inside the averaging window, e seconds are already known (mean M) and
  r = twap - e remain: A = (e*M + r*avg_rest)/twap, where avg_rest is normal
  around S_now with variance sigma^2 * r / 3. The known part is locked in.
"""
import math

import numpy as np


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def sigma_per_sqrt_sec(closes: np.ndarray, step: int = 5) -> float:
    """Realised volatility from `step`-second changes (less bid-ask noise than 1s)."""
    x = closes[::step]
    if len(x) < 10:
        return float("nan")
    d = np.diff(x)
    return float(np.sqrt(np.mean(d * d) / step))


def p_up(spot: float, strike: float, t: int, dur: int, sigma: float, twap: int = 60,
         known_mean: float | None = None, basis_sd: float = 0.0) -> float:
    """Probability that Up wins, seen at second t of the window."""
    start_avg = dur - twap
    if t <= start_avg:
        mean = spot
        var = sigma * sigma * ((start_avg - t) + twap / 3.0)
    else:
        e = t - start_avg
        r = twap - e
        m = spot if known_mean is None else known_mean
        mean = (e * m + r * spot) / twap
        var = (r / twap) ** 2 * sigma * sigma * (r / 3.0)
    sd = math.sqrt(max(var + basis_sd * basis_sd, 1e-12))
    return norm_cdf((mean - strike) / sd)


def view_p_up(v, vol_window: int = 900, vol_mult: float = 1.0, basis_bp: float = 0.7, spot_shift: float = 0.0):
    """Model probability from a strategy View. Returns (p, sigma, distance).

    basis_bp: our uncertainty about where the Chainlink price is relative to the
    exchange price we can see, in basis points of price (1 bp = 0.01%). Measured
    for BTC: the gap moves ~$4.8 between windows = ~0.7 bp.
    spot_shift: optional adjustment added to spot (used by the lead-lag strategy).
    """
    sigma = sigma_per_sqrt_sec(v.spot_hist(vol_window)) * vol_mult
    spot, strike = v.spot + spot_shift, v.strike
    basis_sd = strike * basis_bp * 1e-4 if strike == strike else 0.0
    known = None
    start_avg = v.dur - 60
    if v.t > start_avg:
        known = v.spot_mean(start_avg, v.t)
    if not (sigma == sigma) or sigma <= 0 or strike != strike:
        return float("nan"), sigma, float("nan")
    return p_up(spot, strike, v.t, v.dur, sigma, 60, known, basis_sd), sigma, spot - strike
