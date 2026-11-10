# FINDINGS — lab notebook

Chronological record of what was measured. Every number comes from a file in `results/` or from
a command you can re-run. `REPORT.md` is the summary; this is the evidence trail.

All times UTC. Session date: 10 Nov 2026.

---

## 1. Data facts (Phase 1)

| Fact | Value | How measured |
| - | - | - |
| BTC 5-minute markets downloaded | 25,310 (14 Aug – 9 Nov 2026, 88 days) | `scripts/download_history.py` |
| Fills in those markets | 39.8 million | Data API v2 trade tape |
| Share resolving Up | 49.92% | Gamma outcomes |
| P(same direction as previous window) | 49.81% | Gamma outcomes |
| Strike of window *i+1* equals final price of window *i* | 100% of cases | Gamma `eventMetadata` |
| Std of (strike − Binance spot at the open) | $28 | 288 markets, 9 Nov |
| Std of (strike − Binance 60 s average before the open) | $6 | same |
| Chainlink − Binance gap, change from one window to the next | $4.8 std | 3,423 markets |
| Median distance between final price and strike | $54 | 288 markets, 9 Nov |
| Typical live book | 1¢ spread, ~$800 at the best ask | live recorder |
| Lag between a Binance move and the matching tape timestamps | 3–4 s (correlation peaks at 3 s) | cross-correlation, 9 Nov |

Two of these changed the design:

* **The official strike is not available through the public API while the window is live**
  (Gamma fills it in afterwards). Bots therefore estimate it: Binance 60-second average plus the
  Chainlink–Binance gap seen on the previous window. Error about $5.
* **Tape timestamps run 3–4 seconds late**, because they are blockchain block times. A backtest
  that lets a bot trade on a print stamped "now" is really letting it trade in the past. The
  simulator only lets a decision at second *t* fill on prints stamped *t+4* or later.

## 2. Fill model sanity check, and one correction

First pass: taker fills priced at the **worst** print of the fill second. Under that rule a coin
flip lost 5.2% per dollar staked, when fee (3.5%) plus half the real 1¢ spread (1%) predicts about
4.5%, and the gap was much larger in the last minute of a window, where prices move several cents
within one second. That is a pessimistic bias, so the base case was changed to the **middle of the
prints in that second**, with worst-print kept as a stress test and best-print as an optimistic
bound. The first-pass tables are kept in `results/conservative_first_pass/` for transparency: the
ranking and the conclusion are the same under all three.

For resting limit orders two rules bracket the truth: *trade-through* (a later print must go
strictly past our price; pessimistic) and *touch* (any print at our price fills us, as if we were
always first in the queue; optimistic).

## 3. The grid (Phase 3)

* 198 configurations in 15 families (`polylab/grid.py`), fixed before any result was seen.
* In-sample: first 52 days (14 Aug – 4 Oct). Out-of-sample: last 36 days (5 Oct – 9 Nov).
* Selection rule, coded in `scripts/run_backtests.py`: within each family take the configuration
  with the highest in-sample t-statistic (≥ 200 trades). Then open out-of-sample once.

Disclosure: before the grid existed I ran a 6-day smoke test (4–9 Nov, inside what later became
out-of-sample) with default parameters to check the code ran. No parameter was chosen from it.

### Result (`results/selected.csv`)

| Family | Selected config | OOS trades | Hit rate | Avg price | OOS ROI | t-stat |
| - | - | - | - | - | - | - |
| S15 favourite bucket | buy 90–97¢ at 4:40 | 154 | 87.0% | 86.2¢ | +0.3% | +0.2 |
| S10 tape flow | fade first-30 s flow | 799 | 51.6% | 50.3¢ | −0.6% | −0.2 |
| S08 TWAP lock | model ≥ 95%, 2¢ margin | 164 | 86.6% | 86.4¢ | −0.6% | −0.2 |
| S01 early 60¢ (A) | taker | 5,535 | 59.3% | 58.1¢ | −0.8% | −0.7 |
| S06 ahead side (E) | ≥ 2σ ahead at 2:00 | 374 | 94.1% | 94.5¢ | −0.7% | −0.7 |
| S09 opening gap | $10 gap, cap 55¢ | 569 | 50.4% | 52.2¢ | −6.4% | −1.8 |
| S04 pair taker (D) | 4¢ margin | 335 | 34.9% | 38.9¢ | −13.5% | −2.5 |
| baseline: favourite | at 4:00 | 5,089 | 84.8% | 85.4¢ | −1.4% | −2.7 |
| S02 trend (B) | MACD | 8,250 | 45.5% | 46.1¢ | −4.8% | −3.7 |
| S07 fair value | 8¢ margin, first 2 min | 2,097 | 47.3% | 48.8¢ | −6.0% | −4.1 |
| baseline: coin flip | at 4:00 | 6,408 | 39.9% | 40.6¢ | −3.0% | −4.6 |
| S03 day momentum (C) | first 4 h → next 8 h | 2,686 | 43.8% | 46.2¢ | −8.4% | −4.6 |
| S11 exchange flow | fade 120 s flow | 2,830 | 29.8% | 32.1¢ | −10.8% | −4.8 |
| S05 pair maker (D) | 44¢ both sides, bail 60 s | 6,316 | 39.5% | 44.0¢ | −10.2% | −8.5 |
| S12 model maker | 8¢ inside fair value | 18,079 | 48.0% | 51.2¢ | −6.1% | −17.5 |

**No family has a positive out-of-sample result that is distinguishable from zero.** The best
in-sample t-statistic of any selected config was 1.4. After a Bonferroni correction for 15 families
every out-of-sample p-value is 1.0.

Across the whole grid: 43 of 198 configs were positive in-sample and 35 out-of-sample, about what
chance gives when the true edge is slightly negative. The in-sample and out-of-sample ROI of a
config correlate at 0.84, which means the *losses* are structural and stable (fee, spread, adverse
selection), not noise.

### Stress tests (`results/stress.csv`, out-of-sample ROI)

| Config | Base | Fees ×1.5 | Worst print | 3 s slower + worst + 1¢ | Best print (optimistic) |
| - | - | - | - | - | - |
| S15 90–97¢ at 4:40 | +0.3% | 0.0% | −2.6% | −15.1% | +3.6% |
| S08 TWAP lock | −0.6% | −1.0% | −6.0% | −7.5% | +3.5% |
| S06 ahead ≥ 2σ at 2:00 | −0.7% | −0.9% | −1.2% | −1.8% | 0.0% |
| S01 early 60¢ taker | −0.8% | −2.2% | −1.7% | −5.5% | +0.8% |
| S10 tape-flow fade | −0.6% | −2.1% | −2.1% | −5.5% | +0.8% |
| coin flip at 4:00 | −3.0% | −3.7% | −6.7% | −10.7% | +1.1% |

Even under the optimistic bound (which makes a coin flip profitable, so it is clearly too kind)
the best strategy earns about 3.5%, and the late-window strategies collapse when fills are slower.
Late-window results are the most sensitive to execution assumptions and the least trustworthy.

### Where the money goes: taker edge by price and time (`results/calibration_edge_*.csv`)

Edge per share after fees, in-sample / out-of-sample, mid-window (90–180 s):

| Price paid | In-sample | Out-of-sample |
| - | - | - |
| under 10¢ | −1.3¢ | −1.1¢ |
| 10–25¢ | −2.3¢ | −2.3¢ |
| 25–40¢ | −1.9¢ | −1.5¢ |
| 40–50¢ | −2.0¢ | −1.5¢ |
| 50–60¢ | −2.2¢ | −2.3¢ |
| 60–75¢ | −1.7¢ | −2.3¢ |
| 75–90¢ | −0.5¢ | −0.5¢ |
| 90–97¢ | −0.2¢ | −0.4¢ |
| over 97¢ | −0.2¢ | +0.1¢ |

A clean favourite–longshot gradient: relative to the amount staked, longshots are the worst
purchase (a 1¢ loss on a 7¢ share is −15%) and heavy favourites are close to break-even after
fees. Nothing is reliably positive.

### How many trades before a result means anything?

For the selected configs the "trades needed for 2 standard errors" column ranges from about
300–2,000 (clearly losing strategies) to 4,000–90,000 for the near-zero ones. In plain terms: an edge of
half a cent per share on a 90¢ favourite needs **several thousand trades**, i.e. months of live
paper trading at 5–15 trades a day, before it can be told apart from zero.

## 4. Hypothesis A — a side at ~60¢ in the first 10 seconds

`results/hypA_early60.csv`, all 88 days, 13,404 taker trades: hit rate **58.1%** at an average
price of **57.8¢**. Before fees that is +0.3¢ per share; the fee at 58¢ is 1.7¢. Net ROI **−2.3%**
(t = −2.8). Out-of-sample alone: −0.8%.

Resting a limit at 60¢ instead of taking is worse (−5.3%): the order fills when the price is
falling through it. Fading the 60¢ side loses 7–10%.

Price paid in seconds 2–10 vs. how often that side won (`results/hypA_early_price_calibration.csv`):

| Price paid | n | Won | Edge before fee | Edge after fee |
| - | - | - | - | - |
| 45–50¢ | 35,863 | 47.5% | −0.4¢ | −2.2¢ |
| 50–55¢ | 35,185 | 52.2% | −0.5¢ | −2.2¢ |
| 55–60¢ | 29,426 | 58.2% | +0.7¢ | −1.0¢ |
| 60–65¢ | 25,508 | 63.2% | +0.8¢ | −0.9¢ |
| 65–70¢ | 15,794 | 67.5% | −0.1¢ | −1.6¢ |

So the observation behind the hypothesis is real but small: a side at 55–65¢ early does win
slightly more often than its price (by under 1¢), and the 1.7¢ taker fee is twice that.

## 5. Hypothesis D — both sides under $1

**Taker-taker** (`results/hypD_pairs_backtest.csv`): the signal "both asks sum to under 96¢"
appeared in 702 of 25,310 markets, but by the time both orders could execute, both legs filled in
only **5** of them. The rest became single unhedged legs that lost 3¢ per share on average.

**Resting bids on both sides**, 5 shares per leg, trade-through fills:

| Bid on each side | Both legs filled | One leg only | Completion | Profit per completed pair | Loss per orphan leg | Net per market entered |
| - | - | - | - | - | - | - |
| 40¢ | 10,055 | 7,740 | 56% | +20¢ | −40¢ | −6.1¢/share |
| 44¢ | 8,323 | 4,227 | 66% | +12¢ | −44¢ | −6.9¢/share |
| 48¢ | 5,144 | 1,530 | 77% | +4¢ | −48¢ | −7.9¢/share |
| 49¢ | 4,342 | 1,086 | 80% | +2¢ | −49¢ | −8.2¢/share |

Orphan legs win essentially 0% of the time. That is not bad luck, it is arithmetic: if the side you
hold later recovered, the other side would have fallen to your bid and completed the pair. An
orphan is by construction the side that fell and never came back.

With the optimistic touch-fill rule the loss shrinks only slightly (−4.8 to −7.0¢ per share per
market, `results/maker_touch_optimistic.csv`). Cancelling the unfilled leg after 60 seconds cuts
the loss per orphan (to −14¢) but halves the completion rate; still −5.6¢ per share per market.

In a market where prices are fair, a resting bid has zero expected value and the completed pairs
would exactly pay for the orphans. The measured loss of 3–4¢ per filled share is **adverse
selection**: when Bitcoin jumps, fast takers hit stale bids within 50 ms, so a static bid is filled
at 44¢ at the moment the share is worth 40¢.

**5-minute vs 15-minute overlap** (`results/s14_nested.csv`): the logic is sound (our strike
ordering was right in 99.9% of 2,455 overlapping pairs), but a cost under $1 after fees showed up
in only 20 pairs, and both legs filled in 4 of them, for 1–2¢ each.

**Real order books** (live recorder): see section 9.

## 6. Hypothesis E — buy the side that is ahead; stop when green

### Entry signal (`results/analysis_fast.txt`, `results/grid_*.csv`)

84 definitions were tested (6 times × 14 thresholds in dollars, basis points and volatility
units). Out-of-sample ROI after fees sits between −2.7% and +1.7% for all 49 definitions with at least
200 trades (median −0.6%). The literal rule, "BTC at least $50 from the strike at 3:00, buy the leader":

| Sample | Trades | Hit rate | Avg price | ROI |
| - | - | - | - | - |
| In-sample | 2,283 | 91.4% | 91.6¢ | −0.8% |
| Out-of-sample | 1,193 | 92.7% | 91.4¢ | +0.8% |
| All 88 days | 3,476 | 91.9% | 91.5¢ | −0.2% |

The side that is ahead wins 92% of the time, and the market charges 91.5¢ for it. The half-cent
difference is the fee. Net result over 88 days: −$37 on $15,900 staked, i.e. zero.

Best-looking cell in both samples: "at least 2σ ahead after 60 seconds" (363 trades over 88 days,
hit 95.9% at 92.5¢, +3.1% ROI, per-trade t = 2.8). It is one of 84 cells, its neighbours
(1.5σ at 1:00, 2σ at 2:00) are at zero, and a Bonferroni correction leaves p ≈ 0.2. It is in the
paper league as a watch candidate, not a finding.

### Daily stop (`results/hypE_daily_stop.csv`, all 88 days, 5 shares per trade)

| Strategy | Daily rule | Trades | Total P&L | Green days | Avg green day | Avg red day | Worst day | P&L per trade |
| - | - | - | - | - | - | - | - | - |
| Literal +$50 rule | none | 3,476 | −$37 | 59% | +$5.23 | −$8.52 | −$43 | −$0.01 |
| Literal +$50 rule | stop at +$1 | 960 | −$63 | 86% | +$1.21 | −$12.56 | −$43 | −$0.07 |
| Literal +$50 rule | stop at +$2 | 1,350 | −$39 | 82% | +$2.02 | −$12.01 | −$43 | −$0.03 |
| Coin flip | none | 24,311 | −$2,321 | 25% | +$19.18 | −$41.56 | −$106 | −$0.10 |
| Coin flip | stop at +$1 | 3,261 | −$349 | 90% | +$2.11 | −$57.23 | −$106 | −$0.11 |
| Coin flip | stop at +$2 | 5,062 | −$549 | 84% | +$3.03 | −$55.24 | −$106 | −$0.11 |
| Trend follower | stop at +$1 | 3,842 | −$434 | 86% | +$2.33 | −$50.94 | −$100 | −$0.11 |

What the stop rule does, on every strategy:

* **Green days go up a lot** (59% → 86%; a coin flip reaches 90%).
* **P&L per trade does not improve.** It is the same or slightly worse.
* **Red days get bigger relative to green days.** With a +$1 stop the coin flip makes +$2 on nine
  days out of ten and loses $57 on the tenth.
* Total loss shrinks only because fewer trades are placed, exactly as it would by trading less in
  any other way.

A stop-loss added on top (+$2 / −$4) cuts both tails and the number of trades; P&L per trade is
still the strategy's own. Over 36 out-of-sample days the trend follower with a +$2 stop even shows
a profit (+$34, 97% green days) because its one disaster day (−$69) happened not to be followed by
a second. Over 88 days the same rule is −$585. That is the trap in one row.

## 7. Hypotheses B and C

* **B, trend each candle** (`results/grid_out_of_sample.csv`): MACD −4.8% ROI out-of-sample
  (8,250 trades, hit 45.5% at 46.1¢); "same as previous candle" −5.2%. Outcomes are not
  autocorrelated at all (49.8% repeat), and what direction information exists at the open is
  already in the opening price.
* **C, early-day momentum**: four definitions, all between −3% and −11%. The selected one (first
  four hours decide the next eight) is −8.4% out-of-sample.

## 8. Slow markets

### S16 sports favourites (`results/s16_sports_*.csv`)

4,826 resolved game-winner markets since March 2026 (MLB 2,470, college football 697, NHL 612,
NBA 513, WNBA 355, NFL 179), price five minutes before the start, cost = price + 1¢ + fee.

| Pre-game price | n | Avg price | Won | Edge after costs |
| - | - | - | - | - |
| under 20¢ | 459 | 11.3¢ | 10.2% | −2.4¢ |
| 20–35¢ | 879 | 28.9¢ | 27.8% | −2.9¢ |
| 35–50¢ | 3,459 | 43.7¢ | 44.2% | −1.5¢ |
| 50–65¢ | 3,458 | 56.3¢ | 55.8% | −2.4¢ |
| 65–80¢ | 878 | 71.1¢ | 72.3% | −0.5¢ |
| over 80¢ | 459 | 88.7¢ | 89.8% | −0.2¢ |

Prices are calibrated to within about one cent. Underdogs are slightly overpriced, heavy favourites
slightly underpriced (the classic bias), by less than the cost of trading. "Buy favourites ≥ 75¢":
+0.4% in-sample, −0.4% out-of-sample.

### S18 near-certain "bonds" (`results/s18_bonds_*.csv`)

Binary markets with volume over $100k, priced 24 hours before their scheduled end.

| Price | n | Won | Edge after costs |
| - | - | - | - |
| 90–95¢ | 227 | 87.7% | −6.3¢ |
| 95–98¢ | 170 | 91.8% | −6.1¢ |
| 98–99.5¢ | 234 | 98.3% | −1.4¢ |

In this sample the "safe" side lost more often than its price implied. The losers are the
expected kind: geopolitical deadlines that flipped on the last day, crypto price thresholds,
soccer over/unders. The sample is small (20 losers above 95¢) and mixes very different market
types, so the right reading is "no evidence that 95–99¢ is free money, and some evidence it is
overpriced", not a proven short.
