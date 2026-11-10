"""Parameter grids for Phase 3. Defined BEFORE any results were looked at.

Each family maps to a list of strategy instances. The selection rule is fixed
in scripts/run_backtests.py: inside a family, pick the configuration with the
highest in-sample t-statistic (minimum 200 in-sample trades), freeze it, and
only then evaluate it out-of-sample.
"""
from .strategies.fast import (AheadSide, AlwaysFavorite, Early60, EarlyDayMomentum, FairValueTaker, FlowSignal,
                              ModelMaker, OpenGap, PairMaker, PairTaker, PriceBucket, RandomSide, TrendCandle,
                              TwapLock)


def families() -> dict[str, list]:
    f: dict[str, list] = {}
    f["baseline_random"] = [RandomSide(t, name=f"base_random_t{t}") for t in (5, 30, 120, 240)]
    f["baseline_favorite"] = [AlwaysFavorite(t, name=f"base_favorite_t{t}") for t in (5, 30, 120, 240)]

    # S01 - hypothesis A. No tuning: the rule is exactly as Dante stated it, in four flavours.
    f["S01_early60"] = [Early60(kind="taker"), Early60(kind="limit"),
                        Early60(kind="taker", fade=True), Early60(kind="limit", fade=True)]
    # S02 - hypothesis B
    f["S02_trend"] = [TrendCandle("macd"), TrendCandle("prev")]
    # S03 - hypothesis C: (signal window, trade until), minutes of the UTC day
    f["S03_daymom"] = [EarlyDayMomentum(0, 60, 360), EarlyDayMomentum(0, 60, 1440, name="S03_daymom_0_60_allday"),
                       EarlyDayMomentum(810, 870, 1200, name="S03_daymom_us_open"),
                       EarlyDayMomentum(0, 240, 720, name="S03_daymom_0_240_720")]
    # S04 / S05 - hypothesis D
    f["S04_pair_taker"] = [PairTaker(m) for m in (0.02, 0.04, 0.06)]
    f["S05_pair_maker"] = ([PairMaker(p) for p in (0.40, 0.42, 0.44, 0.46, 0.48, 0.49)]
                           + [PairMaker(p, bail=60, name=f"S05_pair_maker_{int(p * 100)}_bail60") for p in (0.44, 0.48)])
    # S06 - hypothesis E entry: time x threshold x unit
    g = []
    for t in (60, 120, 180, 210, 240, 270):
        g += [AheadSide(t, x, "usd") for x in (25, 50, 75, 100, 150)]
        g += [AheadSide(t, x, "bp") for x in (3, 5, 7.5, 10, 15)]
        g += [AheadSide(t, x, "z") for x in (0.5, 1.0, 1.5, 2.0)]
    f["S06_ahead"] = g
    # S07 / S08 - model vs market
    f["S07_fairvalue"] = ([FairValueTaker(m) for m in (0.02, 0.03, 0.05, 0.08, 0.12)]
                          + [FairValueTaker(m, t0=5, t1=120, name=f"S07_fairvalue_m{int(m * 100)}_early") for m in (0.03, 0.05, 0.08)])
    f["S08_twaplock"] = [TwapLock(m, p, name=f"S08_twaplock_m{int(m * 100)}_p{int(p * 100)}")
                         for m in (0.02, 0.03, 0.05) for p in (0.80, 0.90, 0.95)]
    # S09 - opening gap
    f["S09_opengap"] = [OpenGap(x, c, t, name=f"S09_opengap_x{x}_cap{int(c * 100)}_t{t}")
                        for x in (10, 20, 30, 50) for c in (0.55, 0.62, 0.70) for t in (1, 3)]
    # S10 / S11 - flow
    f["S10_tapeflow"] = [FlowSignal("tape", 30, t, thr, fade, name=f"S10_tapeflow_{'fade' if fade else 'follow'}_t{t}_thr{int(thr * 10)}")
                         for t in (30, 60) for thr in (0.2, 0.5) for fade in (False, True)]
    f["S11_spotflow"] = [FlowSignal("spot", n, t, thr, fade, name=f"S11_spotflow_{'fade' if fade else 'follow'}_n{n}_t{t}_thr{int(thr * 10)}")
                         for n in (30, 120) for t in (0, 60) for thr in (0.2, 0.5) for fade in (False, True)]
    # S12 - model-anchored maker
    f["S12_model_maker"] = [ModelMaker(e) for e in (0.02, 0.04, 0.06, 0.08)]
    # S15 - favourite-longshot buckets
    f["S15_bucket"] = [PriceBucket(lo, hi, t) for t in (30, 120, 240, 280)
                       for lo, hi in ((0.03, 0.10), (0.10, 0.25), (0.25, 0.45), (0.55, 0.75), (0.75, 0.90), (0.90, 0.97))]
    return f


def all_strategies() -> list:
    out, seen = [], set()
    for lst in families().values():
        for s in lst:
            assert s.name not in seen, s.name
            seen.add(s.name)
            out.append(s)
    return out


def family_of() -> dict[str, str]:
    return {s.name: fam for fam, lst in families().items() for s in lst}
