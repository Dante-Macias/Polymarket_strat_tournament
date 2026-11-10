"""The bot league: which strategy instances run in backtests and on paper.

Parameters here were fixed on in-sample data only (see FINDINGS.md); do not
edit them to make a backtest look better.
"""
from .strategies.base import DayStop
from .strategies.fast import (AheadSide, AlwaysFavorite, Early60, EarlyDayMomentum, FairValueTaker, FlowSignal,
                              ModelMaker, OpenGap, PairMaker, PairTaker, PriceBucket, RandomSide, TrendCandle,
                              TwapLock)


def fast_league():
    """One instance per fast-bucket strategy, with the locked parameters."""
    return [
        RandomSide(30),
        AlwaysFavorite(30),
        Early60(kind="taker"),
        Early60(kind="limit"),
        Early60(kind="taker", fade=True),
        TrendCandle("macd"),
        TrendCandle("prev"),
        EarlyDayMomentum(0, 60, 360),
        EarlyDayMomentum(810, 870, 1200, name="S03_daymom_us_session"),
        PairTaker(0.04),
        PairMaker(0.45),
        PairMaker(0.40),
        AheadSide(180, 50, "usd"),
        AheadSide(180, 50, "usd", day_stop=DayStop(take_profit=2.0), name="S06_ahead_t180_usd50_daystop"),
        AheadSide(240, 1.0, "z"),
        FairValueTaker(0.05),
        TwapLock(0.03),
        OpenGap(20, 0.60),
        FlowSignal("tape", 30, 30, 0.3),
        FlowSignal("tape", 30, 30, 0.3, fade=True),
        FlowSignal("spot", 30, 0, 0.3),
        ModelMaker(0.04),
        PriceBucket(0.90, 0.97, 240),
    ]
