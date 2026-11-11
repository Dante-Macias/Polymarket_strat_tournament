# Polymarket + Crypto Strategy Lab

A research lab that tests about 20 trading ideas on Polymarket (5-minute crypto markets, sports,
long-dated outrights) with real historical data, then runs the same bots live **on paper**.

**It never places orders, never touches a wallet, and needs no API keys.** Everything is read-only.

Start with:

1. `REPORT.md` – the ranked results and a plain verdict on each of Dante's hypotheses.
2. `research/RESEARCH.md` – how Polymarket actually works today (fees, settlement, APIs), with sources.
3. `FINDINGS.md` – the lab notebook: what was measured, in the order it was found.
4. `PLAN.md` – what is done and what is next.

## Setup (Mac)

```bash
git clone <this repo> && cd Polymarket_strat_tournament
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q                      # 14 tests: fills, P&L, fees, metrics, paper engines
```

## Run things

```bash
# 1. Live paper league for BTC 5-minute markets (also records order books). Ctrl-C to stop.
python scripts/run_paper.py

# 2. Paper league for sports favourites, near-certain outcomes, sum arbitrage, sportsbook lines
python scripts/run_slow_league.py

# 3. Optional extra recorders (one terminal each)
python scripts/run_recorder.py --asset eth --duration 5m
python scripts/run_recorder.py --asset btc --duration 15m

# 4. Rebuild the history and re-run every backtest (takes about 1.5 hours the first time)
python scripts/download_binance.py --start 2026-08-13 --end 2026-11-09
python scripts/download_history.py --start 2026-08-14 --end 2026-11-09
python scripts/run_backtests.py
python scripts/analyze.py && python scripts/analyze_slow.py
```

To keep the league running after you close the terminal or the lid:

```bash
caffeinate -i nohup python scripts/run_paper.py > data/live/paper.log 2>&1 &
caffeinate -i nohup python scripts/run_slow_league.py > data/live/slow.log 2>&1 &
```

(`caffeinate -i` stops the Mac from idle-sleeping while the command runs; `tail -f data/live/paper.log`
shows what the bots are doing; `pkill -f run_paper.py` / `pkill -f run_slow_league.py` stops them.)

## The live sheet

After every settled market the engine rewrites `results/live/`:

| File | What it is |
| - | - |
| `leaderboard.csv` | One row per bot, best first. Open it in Numbers/Excel, or import it into Google Sheets. |
| `paper_league.xlsx` | Same leaderboard plus one tab per bot with every paper trade. |
| `trades_<bot>.csv` | Every paper trade of one bot. |

The slow league writes the same files to `results/live_slow/`.

Columns of the leaderboard:

| Column | Meaning |
| - | - |
| `trades`, `days` | Sample size. Below a few hundred trades almost nothing is meaningful. |
| `hit_rate` | Share of trades that paid out. Always compare with `avg_price`: buying at 90¢ and winning 88% loses money. |
| `pnl`, `pnl_per_trade`, `roi` | Dollars won after fees (5 shares per trade); per trade; and per dollar staked. |
| `edge_per_share` | Average profit per share in dollars. 0.01 = one cent of edge per share. |
| `brier`, `brier_market` | Accuracy of the bot's probabilities vs. the market's (lower is better; 0.25 = coin flip). |
| `sharpness` | How far the bot's probability sits from the market price on average. |
| `max_dd` | Worst peak-to-trough loss so far. |
| `green_days` | Share of days that ended in profit. |
| `t_stat`, `p_value` | How unlikely the result is if the bot had no edge. With ~20 bots, only trust p below 0.0025. |
| `trades_needed` | Rough number of trades before the current edge estimate would be statistically clear. |

Google Sheets: the free and simple route is *File → Import → Upload* `leaderboard.csv`, or keep this
folder inside Google Drive for desktop so the file syncs by itself. A direct API sync needs a Google
Cloud service-account key, which is not worth the setup at this stage.

## How it is built

```
polylab/
  data/        read-only clients: Polymarket (Gamma, CLOB, Data API v2), Binance, history downloader
  sim/         market data model, tape-based fill simulator, event-driven backtester
  live/        live feeds, SQLite recorder, paper-trading engines (5-minute and slow buckets)
  strategies/  one small class per strategy (fast.py: 5-minute bots, slow.py: sports/outright bots)
  model.py     fair-value model for markets that settle on a 60-second average
  metrics.py   hit rate, ROI, Sharpe, drawdown, Brier, day-clustered t-tests, bootstrap
  league.py    the list of bots with their locked parameters
  slow.py      data collection for sports / long-dated studies
scripts/       command-line entry points
tests/         unit tests for fills and P&L
results/       small result tables (committed); results/live is the live sheet
data/          downloaded history and live SQLite files (git-ignored, can be rebuilt)
```

### Writing a new bot

```python
from polylab.strategies.base import Order, Strategy

class MyBot(Strategy):
    name = "my_bot"
    def ticks(self, dur):          # seconds of the 5-minute window at which to think
        return [60]
    def decide(self, v):           # v = what is known right now (no future data)
        if v.ask("UP") < 0.45 and v.spot > v.strike:
            return [Order("UP", "taker", price=0.46, prob=0.55)]
        return []
```

Add it to `polylab/league.py` and it runs in both the backtester and the paper engine.

## Honest limits

* History has **trades, not order books**. The backtester infers what was buyable from prints and
  is deliberately conservative; the live recorder exists to replace that inference with real books.
* The official settlement price stream needs API credentials, so bots estimate the strike from
  Binance (typical error about $5 on BTC).
* Paper fills are optimistic about one thing: they assume your order would not have moved the
  market. True at 5 shares, not at 5,000.
