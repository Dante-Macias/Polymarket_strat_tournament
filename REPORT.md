# Strategy Lab — Report

*10–11 November 2026. Everything here is research and paper trading; no order was ever placed.*

## The short answer

**Nothing tested beats the market after fees.** Of 21 strategies (198 parameter variants on the
5-minute markets alone), none produced an out-of-sample profit that is distinguishable from luck,
and most lose steadily. The losses are not random: they line up with the taker fee, the 1¢ spread,
and being picked off by faster traders.

This is a useful result, not a failure:

* Polymarket's 5-minute BTC markets are **efficiently priced**. The side that is ahead wins as often
  as its price says, the opening price already contains what the exchange price knows, and the
  taker fee (up to 1.75¢ per share) is larger than any pattern found.
* Sports moneylines and long-dated outrights are **calibrated to about one cent**. Your baskets
  and favourites are fair bets minus costs.
* Your "stop when green" idea **changes the shape of results, not the total**: it turns a losing
  strategy into one that is green 86–90% of days and occasionally has a very bad one.
* The only people visibly winning as takers are a handful of very active wallets trading 1–4
  minutes into each window, almost certainly with faster data and better models than a simple bot.

Four ideas came out of the data that are worth testing next (section 7). None is proven.

Details and every number's source: `FINDINGS.md` (lab notebook) and `results/` (tables).
How Polymarket works today: `research/RESEARCH.md`.

---

## 1. What was tested and how

| | |
| - | - |
| 5-minute BTC markets | 25,310 windows, 14 Aug – 9 Nov 2026 (the whole period under the current settlement rule), 39.8 million fills |
| ETH 5-minute, BTC 15-minute | 31 days each |
| Sports | 4,826 game-winner markets (MLB, NBA, NFL, NHL, college football, WNBA) since March 2026 |
| Outrights / multi-outcome | 1,813 resolved single-winner events since June 2025 |
| Near-certain outcomes | 4,374 binary markets with volume over $100k |
| Live order books | recorded once per second since 10 Nov (BTC; ETH from 11 Nov) |
| Taker behaviour | all 2.64 million taker fills of 4–9 Nov, by wallet |

Method for the 5-minute strategies:

1. Every parameter combination was written down (`polylab/grid.py`) before seeing any result.
2. The first 52 days were used to pick one combination per family, by a fixed rule (highest
   t-statistic, at least 200 trades).
3. That choice was then run **once** on the last 36 days (out-of-sample).
4. Stress tests: 1.5× fees, slower fills, worst price in the second, an optimistic best-price
   bound, and a one-cent-worse rule for resting orders. Splits by time of day, volatility, and
   half of the period.
5. Multiple-testing correction: Bonferroni over the 15 families, a day-level bootstrap, and the
   number of trades each result would need to be statistically clear.

Fees, spread and realistic fills are included everywhere. Two judgement calls are disclosed in
`FINDINGS.md` §2–3: the fill price was changed from "worst print" to "middle print" after a sanity
check showed the first rule was too harsh (the conclusion holds under both), and a 6-day smoke
test ran before the grid was fixed (no parameter came from it).

## 2. Ranked table

ROI = profit ÷ money staked, after fees. "OOS" = the 36 unseen days (5 Oct – 9 Nov) unless noted.
Verdicts: **promising** = positive out-of-sample and robust (none qualified); **inconclusive** =
around zero, too few trades or too fragile to call; **dead** = reliably negative or untradeable.

| Rank | Strategy | Market | OOS ROI | OOS trades | Verdict | Confidence | Main risk / reason |
| - | - | - | - | - | - | - | - |
| 1 | S15 Buy heavy favourite (90–97¢) at 4:40 | BTC 5m | +0.3% | 154 | inconclusive | low | Last-20-seconds execution: −2.6% at worst prices, −15% with 3 s more latency |
| 2 | S06 **E**: buy the side ahead (best: ≥ 2σ ahead at 2:00) | BTC 5m | −0.7% | 374 | inconclusive | medium | The leader is correctly priced; variant "≥ 2σ at 1:00" is +3.1% over 88 days (363 trades) but is 1 of 84 cells |
| 3 | S08 TWAP lock (final-minute favourite) | BTC 5m | −0.6% | 164 | inconclusive | low | Same execution sensitivity as S15 |
| 4 | S10 Fade the first-30-second tape flow | BTC 5m | −0.6% | 799 | inconclusive | medium | Needs ~90,000 trades to tell from zero |
| 5 | S20 Multi-outcome sum arbitrage | live books | +2.6¢/set, 1 event | 3 scans | inconclusive | low | Real but tiny (~$80 per opportunity); "augmented" events look like arbs but are not |
| 6 | S13 BTC leads ETH | ETH 5m | −5.2% (κ=1); +1.7% with no lead-lag | 901 / 412 | dead (lead-lag) | medium | ETH already prices BTC's move |
| 7 | S01 **A**: a side at ~60¢ in the first 10 s | BTC 5m | −0.8% (−2.3% all days) | 5,535 | dead | high | Real edge ≈ +0.5¢, fee ≈ 1.7¢ |
| 8 | S16 Sports favourite ≥ 75¢ before the game | sports | −0.4% | 433 | dead | high | Lines calibrated to ~1¢ |
| 9 | S19 Engineered-ROI basket (yours) | outrights | negative at all sizes and horizons | 1,813 events | dead as an edge | high | Overround ~2.6¢; favourites fairly priced |
| 10 | S14 5-minute vs 15-minute overlap | BTC 5m+15m | 1–2¢ per completed pair | 4 pairs | dead | high | Happens ~once a week |
| 11 | S09 Opening gap | BTC 5m | −6.4% | 569 | dead | high | Opening price already includes the gap |
| 12 | S04 **D** both sides as taker | BTC 5m | −13.5% | 335 | dead | high | Both legs completed in 5 of 25,310 windows |
| 13 | S02 **B**: trend every candle (MACD) | BTC 5m | −4.8% | 8,250 | dead | high | Outcomes have no autocorrelation (49.8% repeat) |
| 14 | S07 Fair-value model vs market | BTC 5m | −6.0% | 2,097 | dead | high | Model over-confident early; market is faster |
| 15 | S03 **C**: early-day momentum | BTC 5m | −8.4% | 2,686 | dead | high | No intraday momentum at this horizon |
| 16 | S11 Exchange order-flow signal | BTC 5m | −10.8% | 2,830 | dead | high | Flow is priced within seconds |
| 17 | S05 **D** resting bids on both sides | BTC 5m | −10.2% | 6,316 | dead | high | One-sided fills almost never win (adverse selection) |
| 18 | S12 Model-anchored market maker | BTC 5m | −6.1% | 18,079 | dead | very high | Same adverse selection, t = −17.5 |
| 19 | S18 Near-certain "bonds" 95–99.5¢ | all categories | −4.4% | 129 | dead | medium | Rare upsets cost more than the 1–3¢ earned |
| 20 | S17 Value vs sharp sportsbook line | sports | not tested | — | not tested | — | Needs a historical odds feed (none free). Paper bot ready with a CSV input |
| 21 | S21 Combos / parlays | combos | not testable | — | dead on arithmetic | medium | Spread compounds per leg, 0.05 fee, maker gets last look |
| – | Baseline: always the favourite | BTC 5m | −1.4% | 5,089 | — | — | — |
| – | Baseline: coin flip | BTC 5m | −3.0% | 6,408 | — | — | — |

Note on ranks 1–4: their out-of-sample results are *better than the baselines* but are not
positive with any confidence, and they are the most sensitive to execution assumptions. They stay
in the paper league as watch candidates.

## 3. Verdicts on your hypotheses

### A — "A side at ~60¢ in the first 10 seconds wins more than its price"
**Partly true, not profitable.** Sides bought at 55–65¢ early won about 0.7–0.8¢ more often than
their price, but the taker fee at 60¢ is 1.7¢. Over 88 days: 13,404 trades, 58.1% wins at
57.8¢, ROI −2.3%. A limit order at 60¢ is worse (−5.3%): it fills when the price is falling through
it. The 60¢ early price exists mainly because the market settles against a 60-second average, so
at the open one side is already ahead.

### B — "Trade every candle in the trend direction (MACD), stop at a daily target"
**Doesn't work.** −4.8% out-of-sample (8,250 trades, 45.5% wins at 46.1¢). Up/Down outcomes
repeat 49.8% of the time, i.e. no trend at all from one window to the next. The daily target
doesn't help (see E).

### C — "Early-day momentum gives a better-than-coin-flip signal"
**Doesn't work.** Four definitions (first hour, first four hours, US open), all between −3% and
−11%. The best of them in-sample was −8.4% out-of-sample.

### D — "Buy both sides for under $1"
**The arithmetic is right; the trade almost never completes in your favour.**

| Method | How often both legs complete | Profit per completed pair | Loss per one-sided fill | Net |
| - | - | - | - | - |
| Both asks < 96¢, buy both as taker | 5 of 25,310 windows | ~1¢ | −3¢ | −13.5% |
| Rest 44¢ bids on both sides | 66% of windows entered | +12¢ | −44¢ | −6.9¢ per share per window |
| Rest 48¢ bids on both sides | 77% | +4¢ | −48¢ | −7.9¢ per share per window |
| Same, cancel the other leg after 60 s | 33% | +12¢ | −14¢ | −5.6¢ per share per window |
| 5-minute vs 15-minute overlapping windows | 4 pairs in 2,455 | 1–2¢ | — | negligible |
| Every outcome of a multi-outcome event | 1 real case in 3 scans | 2.6¢ | — | ~$80 capacity |

Live order books agree: Up ask + Down ask is **$1.01** at the median, under $1 in 1.1% of seconds,
and profitable after fees in 0.3%.

Why resting bids lose: if the side you hold would have recovered, the other side would have
dropped to your bid and completed the pair. So a one-sided fill is, almost by definition, the side
that fell and stayed down; those win about 0% of the time. When BTC jumps, faster traders hit your
stale bid in 50 milliseconds. Size: the best ask typically has ~580 shares (~$290), so capacity was
never the limit.

### E — "Buy the side that is already ahead; stop for the day when green"

**The entry has no edge after fees.** I tested 84 definitions of "ahead" (dollars, percent,
volatility units; 1:00 to 4:30 into the window). Your literal rule, "+$50 at 3:00", over all 88
days: 3,476 trades, **91.9% wins at 91.5¢**, ROI −0.2%, total −$37. The leader wins exactly as often
as the market charges for. Out-of-sample, the 49 definitions with at least 200 trades range from
−2.7% to +1.7% (median −0.6%).

**The daily stop does not create profit.** 88 days, 5 shares per trade:

| Strategy | Daily rule | Total P&L | Green days | Avg green day | Avg red day | Worst day | Max drawdown | P&L per trade |
| - | - | - | - | - | - | - | - | - |
| +$50 at 3:00 | none | −$37 | 59% | +$5.23 | −$8.52 | −$43 | $103 | −$0.01 |
| +$50 at 3:00 | stop at +$1 | −$63 | 86% | +$1.21 | −$12.56 | −$43 | $80 | −$0.07 |
| +$50 at 3:00 | stop at +$2 | −$39 | 82% | +$2.02 | −$12.01 | −$43 | $79 | −$0.03 |
| +$50 at 3:00 | +$2 / stop-loss −$4 | +$8 | 73% | +$1.98 | −$5.00 | −$7 | $21 | +$0.01 |
| Coin flip | none | −$2,321 | 25% | +$19.18 | −$41.56 | −$106 | $2,404 | −$0.10 |
| Coin flip | stop at +$1 | −$349 | **90%** | +$2.11 | **−$57.23** | −$106 | $442 | −$0.11 |

The coin flip row is the whole story: with a +$1 daily stop, a strategy with **no edge at all** is
green nine days out of ten, and on the tenth day it gives back more than the previous nine. The
stop shrinks the total loss only by trading less. A stop-loss on top cuts the bad tail, and P&L
per trade stays the strategy's own (the +$8 row is 605 trades at +1¢ each: noise).

Full daily series: `results/hypE_daily_pnl_series.csv`; all variants: `results/hypE_daily_stop.csv`.

### Your engineered-ROI basket (outrights)
**A good way to express a view; not an edge by itself.** Whatever the sizing, a basket of *k*
outcomes pays $1 if the winner is inside, so it is one bet priced at the sum of the *k* prices.
Across 1,813 resolved events, favourites win almost exactly as often as their prices imply (most
cells within two standard errors; see `FINDINGS.md` §8). At real prices, with the ~2.6¢ overround
of the whole event, every basket size loses 2–18% on average. Your World Cup basket cost about 81¢
thirty days out and won, as an 81% bet should four times in five.

Where the method *can* make money: when your picks are better than the market's, typically in
thin events where you know the domain (your Israeli PM bet is that kind of case). The lab can't
test that from history; the way to measure it is to log each manual basket with your own
probabilities and score it the same way as the bots (calibration and edge vs. price). The sheet
format already supports that.

### Your general idea: "the edge is in when to stop"
Tested above. A stopping rule cannot turn a zero- or negative-edge strategy into a positive one;
it only moves losses from many small days into a few large ones. Where it *does* help is risk
control on a strategy that already has an edge: a daily stop-loss caps the worst day.

## 4. The closest candidates, in detail

None of these is a recommendation to fund. They are the ones worth keeping an eye on.

**1. Buy the leader only when it is far ahead early (S06, "≥ 2σ ahead at 1:00").**
*Logic:* after one minute, if BTC is more than two "typical remaining moves" from the strike, buy
the leading side. *Evidence:* 363 trades over 88 days, 95.9% wins at 92.5¢, +3.1% ROI, per-trade
t = 2.8, positive in both halves (+3.0% on 198 in-sample trades, +3.3% on 165 out-of-sample). It
missed the mechanical selection only because it had 198 in-sample trades against a minimum of 200.
*Against it:* it is the best of 84 cells, its neighbours are at zero, and after correcting for 84
tests it is not significant. *Capacity:* ~4 trades a day, ~$290
at the best ask; tiny. *What kills it:* faster takers, or a single 5% upset rate instead of 4%.

**2. Heavy favourites in the last minute (S15 / S08).** *Logic:* when a side is at 86–97¢ with 20
seconds left, the 60-second average is two-thirds locked in. *Evidence:* +0.3% / −0.6% out of
sample, positive under the optimistic fill bound (+3.5%), −15% with three seconds more latency.
*Verdict:* the edge, if any, belongs to whoever is fastest. Not for a bot on a laptop in Mexico.

**3. Multi-outcome sum arbitrage on exhaustive events (S20).** *Logic:* if one YES of every
outcome costs under $1 after fees, one of them must pay $1. *Evidence:* one live case (Discord IPO
brackets, 2.6¢ per set, ~$80 of size, still open across three scans). *Capacity:* tens of dollars
per opportunity. *Risks:* "augmented" events can add outcomes later (most apparent arbs were
these); cancelled or disputed resolutions; capital locked until resolution. Now scanned every 5
minutes by the slow paper league.

**4. Fair value on ETH rather than BTC (S13 with κ = 0).** *Evidence:* +1.7% and +1.5% out of
sample for two margins (412 and 267 trades), against −6.0% for the same model on BTC. Not
significant (t < 1). *Why it might be real:* ETH books are smaller, so slower to update. *Next
step:* the ETH recorder is now running; re-test with a month more data.

## 5. What would change these conclusions

| More of this | Could change | How |
| - | - | - |
| Weeks of recorded order books | Maker strategies (D, S12), latency-sensitive ones (S08, S15) | Real queue position and real best ask instead of inferring from trades |
| 2–3 months of paper league | Ranks 1–4 | Trades needed to separate them from zero: 4,000–90,000 |
| A historical odds feed (paid) | S17 sharp-line value | The only family with strong published evidence that was not testable |
| The official Chainlink price stream | All 5-minute strategies slightly | Needs authenticated API credentials, which are created by signing with a wallet's private key. **Out of scope by your rules.** Bots estimate it instead (error ~$5). |
| More assets (ETH, SOL, XRP 5-minute) | S13 / idea 3 below | Smaller books may be slower |
| Fatter-tailed model | S07 | Model over-confident at the open (says 5%, happens 12%) |

## 6. Keep it running on your Mac

One-time setup:

```bash
cd ~/Polymarket_strat_tournament
python3 -m venv .venv
```

```bash
source .venv/bin/activate && pip install -r requirements.txt && pytest -q
```

Start everything (each keeps running after you close the terminal; `caffeinate -i` stops the Mac
from sleeping while it runs):

```bash
caffeinate -i nohup python scripts/run_paper.py > data/live/paper.log 2>&1 &
```

```bash
caffeinate -i nohup python scripts/run_slow_league.py > data/live/slow.log 2>&1 &
```

```bash
caffeinate -i nohup python scripts/run_recorder.py --asset eth --duration 5m > data/live/rec_eth.log 2>&1 &
```

Check on them and stop them:

```bash
tail -f data/live/paper.log
```

```bash
pkill -f run_paper.py; pkill -f run_slow_league.py; pkill -f run_recorder.py
```

Reading the results:

* `results/live/leaderboard.csv` — 5-minute bots; `results/live_slow/leaderboard.csv` — sports,
  bonds, sum arbitrage, sharp lines. Each has a matching `paper_league.xlsx` with one tab per bot.
* Rules of thumb: ignore any bot with fewer than a few hundred trades; always compare `hit_rate`
  with `avg_price` (that difference, minus the fee, is the edge); a `p_value` must be below 0.0025
  to mean anything with 20 bots competing; `trades_needed` says how long to wait.
* Re-running the research after new data:
  `python scripts/download_history.py --start <date> --end <date>`, then
  `python scripts/run_backtests.py`, `python scripts/analyze.py`, `python scripts/analyze_slow.py`.
* To test the sportsbook-line bot, put rows in `data/odds/sharp_lines.csv`:
  `market_id,outcome_index,fair_prob,source` (fair probability with the bookmaker's margin removed).

Your Mac's clock and internet matter more than its speed. If it sleeps, bots miss windows (they
pick up the next one cleanly).

## 7. New ideas worth testing next

Each comes from something measured, and each has a concrete test.

1. **A maker that steps aside when BTC moves.** The data says resting orders lose because they are
   filled right after jumps (one-sided fills win ~0%), not because spreads are too thin. A maker
   that quotes only when BTC has been quiet for the last few seconds, and cancels the instant it
   moves, keeps the spread and avoids the worst fills. *Test:* simulate on the recorded books
   with a realistic cancel latency (you are 50–200 ms behind; the fast takers are not). Its
   viability depends entirely on that latency.
2. **Maker bids on heavy favourites, collecting the rebate.** Takers buying 90–97¢ sides mid-window
   lose only about 0.2¢ per share after fees, so before fees they are roughly fair. A maker pays no
   fee and receives 20% of the taker fees back. *Test:* rest bids at 1¢ under the ask on the
   leading side after 2:00, with the recorded books, counting adverse selection honestly.
3. **Smaller crypto markets (ETH, SOL, XRP).** The same fair-value model that loses 6% on BTC is
   around +1.5% on ETH. *Test:* record and paper-trade ETH for a month (the recorder is running).
4. **Time-of-window filter.** All takers together lose least 3–4 minutes into a window (−0.4%), and
   the few persistently winning wallets make most of their money between minutes 1 and 4. *Test:*
   restrict any model bot to that window.

Ideas I checked and would **not** pursue: copying winning wallets (only 0.14 persistence, and the
public trade feed is 3–4 seconds late), the 5m/15m overlap arbitrage (once a week), Combos
(arithmetic against you), and near-certain "bonds" (upsets cost more than the yield).

## 8. Things to know before ever using real money

* **Mexico** is not on Polymarket's restricted list as of 10 Nov 2026 (`research/RESEARCH.md`
  §1.7). Check `https://polymarket.com/api/geoblock` from your own connection. Never use a VPN
  to appear elsewhere; the terms prohibit it and allow freezing the wallet.
* **Automation** through the documented API is allowed; scraping the website is not. The lab uses
  only the documented read-only APIs.
* **Your own Up and Down orders must never trade with each other** (wash trading rule). Relevant
  to any both-sides strategy.
* Placing orders requires signing with a wallet's private key. The lab deliberately has no code
  for that.

## 9. Glossary

* **Taker / maker**: a taker crosses the spread and trades now (pays the fee); a maker rests an
  order in the book and waits (no fee, small rebate).
* **Spread**: the gap between the best price to buy and the best price to sell.
* **Adverse selection**: your resting order gets filled mostly when the price is about to go
  against you, because better-informed traders choose when to trade with you.
* **In-sample / out-of-sample**: data used to choose parameters vs. data kept aside to check them.
* **ROI**: profit divided by money staked.
* **t-statistic, p-value**: how surprising a result is if the true edge were zero. With 20
  strategies, one will look "significant" at p < 0.05 by chance; hence the Bonferroni correction
  (multiply p by the number of tests).
* **Brier score**: average squared error of a probability forecast; 0.25 is a coin flip.
* **Calibration**: whether things priced at 70% happen 70% of the time.
* **Overround**: the amount by which all outcome prices of an event add up to more than $1.
* **TWAP**: time-weighted average price; the 5-minute markets settle on a 60-second one.
* **Favourite–longshot bias**: longshots tend to be overpriced and favourites slightly underpriced.
