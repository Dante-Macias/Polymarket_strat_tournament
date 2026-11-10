"""The bot league that runs on paper.

Every bot here is a configuration from polylab/grid.py, chosen mechanically on
in-sample data (results/selected.csv), plus Dante's literal rules and two
"watch" candidates. Do not edit parameters to make results look better - add a
new named bot instead, so the old track record stays intact.
"""
from .grid import all_strategies
from .strategies.base import DayStop
from .strategies.fast import AheadSide

LEAGUE = [
    # dumb baselines every bot must beat
    "base_random_t30", "base_favorite_t30",
    # A - a side at ~60c in the first 10 seconds
    "S01_early60_taker", "S01_early60_limit", "S01_early60_taker_fade",
    # B - trend every candle
    "S02_trend_macd", "S02_trend_prev",
    # C - early-day momentum
    "S03_daymom_0_240_720", "S03_daymom_us_open",
    # D - both sides under $1
    "S04_pair_taker_m4", "S05_pair_maker_44", "S05_pair_maker_48", "S05_pair_maker_44_bail60",
    # E - buy the side that is ahead (literal rule, selected rule, watch candidate)
    "S06_ahead_t180_usd50", "S06_ahead_t120_z2", "S06_ahead_t60_z2",
    # model and others
    "S07_fairvalue_m8_early", "S08_twaplock_m2_p95", "S09_opengap_x10_cap55_t3",
    "S10_tapeflow_fade_t30_thr5", "S11_spotflow_fade_n120_t60_thr5", "S12_model_maker_e8",
    "S15_bucket_90_97_t280",
]


def fast_league():
    by_name = {s.name: s for s in all_strategies()}
    bots = [by_name[n] for n in LEAGUE]
    # E with the daily take-profit: stop for the day once the bot is up $2
    bots.append(AheadSide(180, 50, "usd", day_stop=DayStop(take_profit=2.0), name="S06_ahead_t180_usd50_stop_at_plus2"))
    return bots
