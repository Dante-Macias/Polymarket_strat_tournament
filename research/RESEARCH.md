# Phase 1 research

Everything here was checked on **10 Nov 2026** against the live docs and live APIs, not from memory.
Where I verified something empirically with downloaded data, it says "measured".

Sources are numbered in [Sources](#sources) and referenced like [S3].

---

## 1. Polymarket mechanics

### 1.1 The public APIs (all read-only, no key needed)

| Service | Base URL | What the lab uses it for |
| - | - | - |
| Gamma | `https://gamma-api.polymarket.com` | Events/markets metadata, fee schedule, resolution prices of crypto markets |
| CLOB | `https://clob.polymarket.com` | Live order books (`/book`), coarse price history (`/prices-history`) |
| Data API v2 | `https://data-api.polymarket.com/v2` | **The full public trade tape** (`/v2/trades?condition=…`) |
| Market websocket | `wss://ws-subscriptions-clob.polymarket.com/ws/market` | Live book/price updates (optional, the recorder polls REST instead) |

Things I verified [S1][S2][S3]:

* **Data API v1 was retired on 2 Nov 2026.** `GET /trades` now returns HTTP 410. Any tutorial or bot
  that still calls the old routes is broken. v2 wraps results in `{data, pagination}` and pages with
  an opaque cursor.
* `/v2/trades` returns each fill **once, on the taker side** (`taker_only=true` default) with
  `side`, `outcome`, `price`, `size`, `timestamp` (1-second resolution). A 5-minute BTC market has
  ~1,600 fills on average (measured, 9 Nov 2026: min 622, max 3,394).
* `/prices-history` is too coarse for 5-minute work: about one point per minute. For resolved
  markets only coarse fidelity (daily) returns data when using `interval=max`.
* **Historical order books are not available anywhere.** Only the current book. This is the one
  thing that must be recorded going forward (the recorder in this repo does it).
* The official live TWAP reference-price stream (the price the crypto markets settle on) needs CLOB
  API credentials, so the lab does not use it. We approximate it from Binance (section 1.4).

### 1.2 Rate limits [S4]

Limits are per IP, sliding 10-second windows, and requests over the limit are queued rather than
rejected. The ones that matter: Gamma `/events` 500 / 10 s, CLOB `/book` 1,500 / 10 s,
Data API `/v2/trades` 300 / 10 s. The lab caps itself at 25 requests per second in total, far below
all of them.

### 1.3 Fees [S5]

`fee = shares × rate × p × (1 − p)`, charged in USDC, **takers only**. Makers pay nothing and get
a share of the fees back as a rebate (the lab ignores rebates to stay conservative).

| Category | Rate | Fee at 50¢ per share | As % of stake at 50¢ |
| - | - | - | - |
| Crypto (all durations) | 0.07 | 1.75¢ | 3.5% |
| Sports, Economics, Culture, Weather, Other, **Combos** | 0.05 | 1.25¢ | 2.5% |
| Politics, Finance, Tech, Mentions | 0.04 | 1.00¢ | 2.0% |
| Geopolitics | 0 | 0 | 0 |

What this means in practice:

* On a 5-minute crypto market, a taker who buys at 50¢ needs to win **51.75%** of the time just to
  break even. Buying at 80¢ needs 81.12%; at 95¢ needs 95.33%.
* Buying *both* sides as a taker costs two fees. At 50/50 that is 3.5¢ per pair, so a taker-taker
  "both sides under $1" trade needs the two asks to add up to less than about **96.5¢**.
* Fee schedules have changed three times in 2026 (launch at "peak 1.56%", then the current
  0.07 linear formula). Each market carries its own `feeSchedule` in Gamma, which the lab reads
  per market instead of hard-coding.
* Since **17 Aug 2026 the taker delay on crypto markets is 50 ms** (down from 250 ms) [S6]. Fast
  takers are barely slowed down any more, which matters for anyone resting limit orders.

### 1.4 How 5-minute crypto Up/Down markets resolve — the most important finding

This changed in August and most online descriptions are out of date [S6][S7]:

* Before 7 Aug 2026: one Chainlink price snapshot at the start vs. one at the end.
* 7 Aug: switched to a **30-second Chainlink TWAP** (time-weighted average price).
* **Since 14 Aug 2026: 60-second TWAP.** "Up" wins if the average price over the **last 60 seconds
  of the window** is ≥ the "price to beat", which is itself the **average over the 60 seconds
  before the window opened**.

Measured on 288 markets (9 Nov 2026), comparing Gamma's published prices with Binance BTCUSDT
1-second closes:

| Comparison | Std of difference |
| - | - |
| price to beat vs. Binance spot at the open | $28 |
| price to beat vs. Binance 60 s average before the open | **$6** |
| final price vs. Binance spot at the close | $28 |
| final price vs. Binance 60 s average at the end | **$6** |

Also measured: the next market's price to beat is *exactly* the previous market's final price
(100% of cases), and Binance sits about **$95 above** Chainlink BTC/USD (it quotes in USDT). That
gap drifts slowly, so within one 5-minute window it is nearly constant. Predicting the outcome
from Binance averages alone agrees with the real resolution 98.3% of the time; the misses are
windows that finish within a few dollars of the strike.

Three consequences that drive several strategies below:

1. **The market does not open at 50/50.** At the open the spot price already differs from the
   60-second average that sets the strike, so one side starts ahead. Prices of 60¢+ in the first
   seconds (hypothesis A) are mostly this, not a signal.
2. **In the last minute the result is progressively locked in.** With 20 seconds left, two thirds
   of the final average is already known. A side that is "ahead" late is safer than a simple
   spot-vs-strike view suggests. If traders under-appreciate this, late favourites are underpriced.
3. **"BTC is +$50 from the start price" needs care.** The median |final − strike| is about $54
   (measured), so +$50 mid-window is an ordinary move, and what matters is the move relative to
   the time left and current volatility.

Other mechanics (measured from Gamma): markets are created ~24 hours ahead and trade at ~50¢ until
the window opens; tick size 0.001; minimum order 5 shares; volume $40–100k per 5-minute BTC market;
the BTC 5-minute series does about $13M per day.

### 1.5 Negative risk, Combos, Perps

* **Negative risk** [S8]: in a multi-outcome event where exactly one outcome wins, one NO share
  can be converted into one YES share of every other outcome. This is what makes "buy all the
  NOs" arbitrage capital-efficient, and why the YES prices of such events should sum to about $1.
* **Combos (parlays)** [S9]: quote-driven (RFQ). You request a price, market makers have 400 ms to
  quote, you have 10 s to accept, and the maker can have a 1 s "last look". There is no public
  history of quotes, so Combos cannot be backtested, only reasoned about. Fee rate 0.05 on the
  combo price regardless of the legs.
* **Perps** [S10]: leveraged perpetual futures on a separate order book, 0.04% taker / 0.0125%
  maker at the entry tier. Not used by the lab: leverage and liquidation risk are out of scope for
  a paper-trading research project, and none of your hypotheses need them.

### 1.6 What history exists vs. what must be recorded

| Data | Retrievable? | How |
| - | - | - |
| Every fill of every market, back to market creation | Yes | Data API v2 `/trades` |
| Strike and final price of crypto Up/Down markets | Yes | Gamma `eventMetadata` |
| Coarse price series | Yes | CLOB `/prices-history` |
| Exchange prices, 1-second | Yes | Binance public archives [S11] |
| **Order book depth / best bid-ask over time** | **No** | Record it yourself (`scripts/run_recorder.py`) |
| Combo quotes | No | Not public |
| Historical sportsbook closing lines | Not free | Needs a paid odds feed or manual collection |

The lab downloaded: BTC 5-minute markets from 14 Aug to 9 Nov 2026 (the whole current resolution
regime, ~25,000 markets), BTC 15-minute and ETH 5-minute for the last 31 days, and Binance
1-second prices for the same dates.

### 1.7 Terms of use, automation and Mexico [S12][S13]

I am not a lawyer; this is what the published documents say.

* **Mexico is not on the restricted list.** The Terms define "Restricted Jurisdictions" by
  reference to the docs' geoblock page. That page lists 4 fully blocked countries/regions and 30+
  "close-only" jurisdictions (including the US, UK, France, Germany, Brazil, Argentina, Australia).
  Mexico is in neither group as of 10 Nov 2026. The list can change without notice, so check
  `https://polymarket.com/api/geoblock` from your own connection before you ever fund anything.
* **Never use a VPN to change your apparent location.** The Terms prohibit it explicitly and allow
  them to put the wallet in close-only mode.
* **Automation**: the API is documented and public, and API trading by individuals is clearly
  expected (there are SDKs, market-maker docs, rebate programs). The Terms do prohibit scraping the
  *website* with robots/crawlers, and they restrict data use by professional trading firms. The lab
  only calls the documented APIs, read-only.
* **Market-integrity rules apply to bots too**: no wash trading (trading with yourself), no
  spoofing (placing orders you intend to cancel). Relevant to hypothesis D: buying both sides from
  *other people* is fine; your own Up order must never fill against your own Down order.
* Mexican tax and regulatory treatment of winnings is something to ask a local accountant about.

---

## 2. Known prediction-market inefficiencies

**Favourite–longshot bias (FLB).** In betting markets, longshots win less often than their price
implies and favourites slightly more [S14]. The largest recent study of a prediction exchange
(Kalshi, 300k contracts) finds the same: contracts under 10¢ lose badly, takers lose more than
makers, and the average return of all contracts after fees is about −22% [S15]. The proposed
mechanism is that people overweight small probabilities and pay for immediacy. Expectation for the
lab: buying longshots as a taker is the worst possible habit; any FLB edge would come from being
on the favourite side or from *making* rather than taking.

**Calibration.** Prediction-market prices are well calibrated on average and get more accurate
close to resolution [S15][S16]. An inefficiency has to be found in a specific corner (a category,
a time-to-expiry, a price bucket), not in the market as a whole.

**Arbitrage.** A study of Polymarket on-chain data (Apr 2024–Apr 2025) estimates about $40M of
realised arbitrage profit, split between single-market rebalancing (YES+NO ≠ $1, or all outcomes of
an event ≠ $1) and combinatorial arbitrage across logically related markets [S17]. Two lessons: the
opportunities are real, and they are harvested by fast specialised bots, so what is left for a
slow, small account is whatever is too small or too awkward for them.

**Late-resolution drift / "bonds".** Outcomes trading at 95–99¢ shortly before resolution pay a
few percent for waiting. Whether that is free money or compensation for rare disasters
(disputed resolutions, last-minute reversals) is exactly an FLB question at the top of the price
range. Tested in strategy S18.

**Market making on thin books.** Makers earn the spread and pay no fee but suffer adverse
selection: they get filled when the informed side wants to trade [S15]. In 5-minute crypto
markets the "informed side" is anyone watching the exchange price move, 50 ms ahead of you.

**Sportsbook closing lines.** The closing line of sharp bookmakers is the best public estimate of
a game's true probability; beating it consistently is the standard test of skill, and betting only
when a soft price deviates from the sharp consensus has been shown to be profitable until the
bookmaker limits the account [S18]. Polymarket cannot limit you, which is why this family is on the
list, but it needs an odds feed the lab does not have for free.

---

## 3. Short-horizon crypto direction

* **Intraday momentum** exists at specific horizons: in equities the first half-hour return
  predicts the last half-hour [S19]; a Bitcoin version finds the same pattern and attributes it to
  liquidity provision [S20]. This is a session-level effect, not a "next 5 minutes" effect.
* **At 5-minute horizons** returns are close to unpredictable from past returns, with weak
  negative autocorrelation (mean reversion) at the very short end and at 1–4 hours [S21]. A
  trend-following rule on 5-minute candles should be expected to sit near 50%.
* **Order-flow imbalance** (signed taker volume, or changes at the best bid/ask) explains
  *contemporaneous* price changes well and has some predictive power over the next seconds, which
  decays quickly [S22]. Usable only if the Polymarket price reacts more slowly than the signal.
* **Funding rates / open interest** move on hours-to-days horizons. No evidence they forecast a
  5-minute window; not prioritised.
* **Volatility and time of day.** Crypto volatility clusters and is highest around the US cash
  open and macro releases. This does not predict direction but it changes how much a given dollar
  move "means", so every threshold in the lab is also tested in volatility units (z-scores).
* **Exchange → Polymarket lead-lag.** The settlement price is built from exchange prices, so the
  exchange leads by construction. The only question is whether Polymarket quotes are stale for
  long enough, and by more than the fee, for someone without co-location to trade on it. The tape
  timestamps are block times and lag the true match by a few seconds, so naive backtests
  overstate this edge; the simulator adds a fill delay for that reason.

---

## 4. Pitfalls and how the lab guards against each

| Pitfall | Guard |
| - | - |
| Look-ahead on the reference price | Strategies only see the last *completed* 1-second bar. The official strike is hidden for the first 3 s of a window; before that the bot must use its own estimate. |
| Look-ahead through tape timestamps | A print stamped at second *s* was matched earlier. Takers can only fill on prints stamped ≥ 3 s after the decision (5 s in the stress test). |
| Fills that would not happen | Taker fills need a real print on the right side of the book in the fill window, at the worst price of that second. Limit orders fill only when a later print trades *through* the price. |
| Fees | Per-market fee schedule from Gamma, applied to every taker fill. Maker rebates ignored. |
| Binance ≠ Chainlink | Basis re-estimated every window from the published strike; outcomes always use the official resolution. |
| Survivorship | All markets of a series in the date range are included, chosen by timestamp, not by browsing what looks interesting. |
| Overfitting | Parameters are chosen on the first 60% of days only and frozen before touching the last 40%. |
| Multiple testing | ~20 strategies × parameter grids: p-values are Bonferroni-adjusted and the report states the number of trades needed for significance. |
| Regime change | Only the post-14-Aug (60 s TWAP) regime is used for 5-minute strategies; older data follows different rules. |
| Stopping-rule illusions | Daily-stop variants are compared with the identical strategy without the stop, on total P&L and the full daily distribution. |

---

## 5. Candidate strategies

You asked me to pause here for review. **You were not available during this session, so I
proceeded to build and test, as your instructions allowed.** Nothing below places orders.

"Who is on the other side" is the key question for each: if nobody is plausibly wrong, there is
no edge.

### Fast bucket — 5-minute crypto

**S01 · Early 60¢ follow (your hypothesis A).** If a side trades at 57–63¢ within the first 10
seconds, buy it and hold. Variants: taker, or a resting limit at 60¢. Data: tape. *Other side:*
market makers who priced the opening gap. Why it might fail: the 60¢ already reflects that spot is
away from the 60-second-average strike (section 1.4).

**S02 · Trend-follow every candle (hypothesis B).** At each open, buy Up if MACD(12,26,9) on
5-minute closes is positive, else Down. Simple variant: follow the previous window's direction.
*Other side:* nobody in particular; this is a bet that 5-minute returns are positively
autocorrelated, which the literature doubts.

**S03 · Early-day momentum (hypothesis C).** Measure BTC's return over the first hour of the UTC
day (and of the US session); trade that direction at the open of each window in the following
hours. *Other side:* same as S02, at a horizon where there is some published support.

**S04 · Both-sides taker arbitrage (hypothesis D, method 1).** Buy Up and Down at the same moment
when the two asks sum to less than $1 minus both fees. Data: tape gives a proxy (opposite-side
prints in the same second); the recorder gives the real answer from order books. *Other side:*
nobody for long; makers quote both sides from one model.

**S05 · Both-sides resting limits (hypothesis D, method 2).** Rest a bid of X¢ on Up and X¢ on
Down (X from 40 to 49) and wait for volatility to fill both. Profit per completed pair is
100 − 2X; a single fill is an unhedged bet entered at the worst moment. Measured: completion rate,
profit per pair, loss on orphan legs. *Other side:* takers reacting to the exchange price, i.e.
people better informed than the resting order.

**S06 · Buy the side that is ahead (hypothesis E entry).** When BTC is ≥ X from the strike with T
seconds gone, buy the leading side. Grid over X in dollars, in %, and in volatility units, and
over T. Then the separate question of the daily stop. *Other side:* sellers of the favourite who
want out early or underestimate how sticky a lead is.

**S07 · Fair-value model vs. market.** Compute the probability of Up from spot, strike, time left
and recent volatility, with the 60-second averaging handled properly; take when the ask is below
the model by more than a margin. *Other side:* stale quotes. This is the latency game, and the
honest prior is that co-located bots win it.

**S08 · TWAP lock (new, from section 1.4).** In the final 60 seconds, compute how much of the
final average is already fixed; buy the favourite when the model says it is nearly certain but
the market still offers a discount. *Other side:* traders who think of the market as "spot vs
strike at the bell" and overestimate late reversal risk.

**S09 · Opening-gap drift (new).** At the open, spot minus strike is already known. Buy the side
spot favours in the first seconds if the price has not adjusted. *Other side:* orders resting at
~50¢ from before the open.

**S10 · Follow or fade the tape ("other bots' lean").** Net taker buying in the first 30–60
seconds: follow it, or fade it. *Other side:* either slow traders (follow) or overreacting ones
(fade); the data decides.

**S11 · Exchange order-flow imbalance.** Binance signed taker volume over the last 10–60 seconds
predicts the next move; trade it at the open or mid-window. *Other side:* quotes that track price
but not flow.

**S12 · Model-anchored maker.** Rest bids a few cents below model fair value on both sides and
refresh. Pays no fee. *Other side:* impatient takers; the risk is the informed ones.

**S13 · BTC leads ETH.** Use the BTC move to trade the ETH 5-minute market, on the idea that ETH
quotes follow ETH spot but ETH spot follows BTC. *Other side:* single-asset market makers.

**S14 · 5-minute vs 15-minute consistency (hypothesis D, method 4).** Every third 5-minute window
ends at the same instant as a 15-minute window and settles on the same final price with a
different strike. If the 5-minute strike is higher, "Up 5m" implies "Up 15m", so
Up-15m + Down-5m always pays at least $1. Buy the pair when it costs less. *Other side:* two
separate books that are not always synchronised.

**S15 · Favourite–longshot inside 5-minute markets.** Calibration by price bucket and time: do
90¢+ sides win more than 90%? Trade the favourite if so. *Other side:* lottery-ticket buyers.

### Daily bucket

**S16 · Sports favourites at kickoff.** Calibration of pre-game moneyline prices on resolved
games; buy favourites above a threshold if they are underpriced after the 0.05 fee. *Other side:*
fans backing the underdog.

**S17 · Value vs. sharp sportsbook line.** Bet when Polymarket's price is cheaper than the
no-vig sharp line by a margin. Needs a historical odds feed the lab does not have for free, so
this ships as a paper bot with a pluggable odds input and no backtest.

**S18 · Near-certain "bonds".** Buy outcomes at 95–99¢ a day before resolution across categories;
measure realised win rate vs. price. *Other side:* holders who want their cash back early.

### Long bucket

**S19 · Engineered-ROI basket (your outright method).** Buy the top-k outcomes of a
multi-outcome event sized for equal payout. Mathematically this is one bet: "the winner is in my
basket", priced at the sum of the k prices. Tested on resolved events: does the basket win more
often than it costs? *Other side:* longshot buyers in the field.

**S20 · Multi-outcome sum arbitrage (hypothesis D, method 3).** In negative-risk events, buy every
YES when the asks sum to < $1 (or every NO when the bids sum to > $1). Live scan of real order
books. *Other side:* nobody for long; see [S17].

**S21 · Combos / parlays.** No data to backtest. Analysed with arithmetic: each leg's spread and
the 0.05 fee compound, and the maker has a last look.

---

## Sources

* [S1] Polymarket docs index — https://docs.polymarket.com/llms.txt
* [S2] Data API v1 → v2 migration — https://docs.polymarket.com/migrate/data-api-v1-to-v2
* [S3] List trades reference — https://docs.polymarket.com/api-reference/feeds/list-trades
* [S4] Rate limits — https://docs.polymarket.com/api-reference/rate-limits
* [S5] Fees — https://docs.polymarket.com/trading/fees
* [S6] Predictions changelog (TWAP changes 7 and 14 Aug 2026, taker delay 17 Aug, fee history) — https://docs.polymarket.com/changelog/predictions
* [S7] Live market metadata, e.g. `GET https://gamma-api.polymarket.com/events?slug=btc-updown-5m-1794333900` (description, `cryptoMarketConfig`, `eventMetadata`)
* [S8] Negative risk — https://docs.polymarket.com/concepts/negative-risk
* [S9] Combos overview — https://docs.polymarket.com/trading/combos/overview
* [S10] Perps overview and fees — https://docs.polymarket.com/perps/overview , https://docs.polymarket.com/perps/learn-about-trading/fees
* [S11] Binance public data — https://data.binance.vision
* [S12] Polymarket Terms of Use — https://polymarket.com/tos
* [S13] Geographic restrictions — https://docs.polymarket.com/api-reference/geoblock
* [S14] Snowberg & Wolfers (2010), "Explaining the Favorite–Long Shot Bias: Is it Risk-Love or Misperceptions?", Journal of Political Economy 118(4)
* [S15] Bürgi, Deng & Whelan (2025/2026), "Makers and Takers: The Economics of the Kalshi Prediction Market" — https://www.karlwhelan.com/Papers/Kalshi.pdf
* [S16] Page & Clemen (2013), "Do Prediction Markets Produce Well-Calibrated Probability Forecasts?", Economic Journal 123
* [S17] Saguillo, Ghafouri, Kiffer & Suarez-Tangil (2025), "Unravelling the Probabilistic Forest: Arbitrage in Prediction Markets" — https://arxiv.org/abs/2508.03474
* [S18] Kaunitz, Zhong & Kreiner (2017), "Beating the bookies with their own numbers" — https://arxiv.org/abs/1710.02824
* [S19] Gao, Han, Li & Zhou (2018), "Market intraday momentum", Journal of Financial Economics 129(2)
* [S20] Shen, Urquhart & Wang (2022), "Bitcoin intraday time series momentum", Financial Review 57(2) — https://centaur.reading.ac.uk/100181
* [S21] Eross, McGroarty, Urquhart & Wolfe (2019), "The intraday dynamics of Bitcoin" — https://eprints.soton.ac.uk/429352/
* [S22] Cont, Kukanov & Stoikov (2014), "The Price Impact of Order Book Events" — https://arxiv.org/abs/1011.6402
* [S23] Bailey & López de Prado (2014), "The Deflated Sharpe Ratio" (multiple-testing correction used in Phase 3)
