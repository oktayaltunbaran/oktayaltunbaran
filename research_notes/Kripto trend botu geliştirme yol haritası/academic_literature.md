# Academic and Practitioner Literature: Trend Following, Volatility Sizing and Derivatives Signals in Crypto (for a 2h Supertrend perp bot)

Method note: this was put together from web search results, mostly abstracts, repository listings and secondary summaries. Direct page fetches to arxiv.org and cxoadvisory.com failed: those hosts are outside this session's allowed network. Several figures therefore come from search snippets or secondary summaries, and each one is flagged. "PR" means peer-reviewed. "WP" means working paper. "Blog" means practitioner or informal material.

---

## 1. Time-series momentum / trend following in crypto: lookbacks, horizons, intraday vs daily, breakout vs MA

### Takeaway
In crypto, time-series (absolute) momentum has much stronger evidence than cross-sectional momentum. The best-documented horizons are daily to weekly signals, held for days to weeks. Ensembles of Donchian breakouts over several lookbacks, with volatility targeting, are the most credible recent practitioner design. Evidence below daily is thin, and the strongest piece of it (a Sharpe of about 1.6) is gross of fees. That matches the bot's own finding that 5m–30m frames fail after fees.

### Cited Findings
- **Liu & Tsyvinski (2021), RFS 34(6):2689–2727 (PR).** Crypto returns are predicted by crypto-specific factors, not by stock, FX or commodity factors. There is a "strong time-series momentum effect", and investor-attention proxies forecast returns. The working paper reports TSMOM at both daily and weekly frequencies for BTC, XRP and ETH. — [NBER w24877](https://nber.org/papers/w24877); [RePEc](https://econpapers.repec.org/RePEc:oup:rfinst:v:34:y:2021:i:6:p:2689-2727.)
- **Liu, Tsyvinski & Wu (2022), Journal of Finance 77(2):1133–1177 (PR).** Three factors (crypto market, size, momentum) capture most of the cross-sectional expected returns. 9 of 25 tested price-based factors were significant. A secondary summary reports weekly long-short momentum excess returns of about 2.5–4.1% per week, depending on lookback (not verified in the full text). — [RePEc](https://econpapers.repec.org/RePEc:bla:jfinan:v:77:y:2022:i:2:p:1133-1177); [NBER w25882](https://www.nber.org/papers/w25882)
- **Han, Kang & Ryu (Journal of Financial Markets, 2024, PR per citing references).** Under realistic assumptions (costs, liquidation risk), "evidence of time-series momentum is strong, whereas evidence of cross-sectional momentum is weak". TSMOM profits are concentrated in bull markets, and the strategy loses money in most falling-market cases. They also argue that a simple t-test of mean return is insufficient to test profitability. I could not obtain specific lookback results. — [ACFR PDF](https://acfr.aut.ac.nz/__data/assets/pdf_file/0009/918729/Time_Series_and_Cross_Sectional_Momentum_in_the_Cryptocurrency_Market_with_IA.pdf)
- **Grobys & Sapkota (2019), Economics Letters (PR).** On monthly data for 143 coins (2014–2018), they find no strong evidence of Moskowitz-Ooi-Pedersen TSMOM, and some strategies give negative payoffs. Later Grobys co-authored work says plain crypto momentum is "highly sample-dependent". **Conflict:** this contradicts Liu & Tsyvinski and Han et al. The difference is likely driven by monthly vs daily/weekly horizons and by the small-coin universe. — [Univ. Vaasa repository](https://osuva.uwasa.fi/server/api/core/bitstreams/397c4059-360e-46e6-937f-f80054ae6180/content)
- **Zarattini, Pagani & Barbon, "Catching Crypto Trends: A Tactical Approach for Bitcoin and Altcoins" (2025, Swiss Finance Institute RP 25-80, WP).**
  - Design: an ensemble of Donchian-channel breakout models with different lookbacks, applied daily, long-only, across up to 20 liquid coins. It uses volatility targeting (25% target per summary) and monthly rebalancing, with costs of 0.10%. Sample: Jan 2015 to mid-Mar 2025.
  - Reported results: 18% net CAGR and about 11% annual net alpha vs BTC buy-and-hold (CXO summary). Another summary gives the "Combo" at 30% CAGR, Sharpe 1.58, Sortino 2.03 and 14% alpha. **The two summaries disagree**, probably because they describe different variants. Check the SFI PDF before quoting.
  - Bias: the work is in-sample and multi-lookback, but the ensemble reduces parameter-selection risk.
  - Sources: [IDEAS/RePEc](https://ideas.repec.org/p/chf/rpseri/rp2580.html); [author page](https://abarbon.com/papers/catching-crypto-trends); [Concretum summary](https://concretumgroup.com/catching-crypto-trends-a-tactical-approach-for-bitcoin-and-altcoins/); [CXO summary](https://www.cxoadvisory.com/technical-trading/crypto-asset-trend-following-strategies/); [Quantified Strategies](https://www.quantifiedstrategies.com/?p=1192563)
- **Hudson & Urquhart (2019), "Technical trading and cryptocurrencies", Annals of Operations Research (PR).**
  - They test 14,919 rules from 5 families (MA, breakout/support-resistance, filter, etc.). Average annualized returns are significant at 5% for every family and every coin.
  - Breakeven transaction costs are well above actual crypto costs.
  - Technical rules significantly reduce the buy-and-hold drawdown.
  - Many rules stay significant after data-snooping corrections.
  - They cite Detzel et al. (2018): 5- to 100-day MA rules have in- and out-of-sample predictive power for BTC.
  - Source: [Springer](https://link.springer.com/article/10.1007/s10479-019-03357-1)
- **Contrary or weaker evidence (PR or WP).** A trend-following study on 2011–2019 data found "no predictable and attractive Sharpe ratios" when strategies trained on 1 year were tested out of sample. A 12-coin study found that only a short-term log-MA ratio rule showed genuine in- and out-of-sample profitability. — [arXiv 2009.12155 "A Decade of Evidence of Trend Following Investing in Cryptocurrencies"](https://ar5iv.labs.arxiv.org/html/2009.12155); [Glasgow eprint](https://eprints.gla.ac.uk/302711/1/302711.pdf)
- **Intraday (PR).** Shen, Urquhart & Wang (2022), *Financial Review* 57:319–344: Bitcoin intraday TSMOM, where the first half-hour return predicts the last half-hour return (using a volume-defined "day"). They attribute it to liquidity provision. It is strongest in the highest-volume or highest-volatility sessions. — [Birmingham repository](https://research.birmingham.ac.uk/en/publications/bitcoin-intraday-time-series-momentum/); [Reading repository](https://centaur.reading.ac.uk/100181)
- **Intraday (Blog/WP, gross of fees).** Concretum: a high-frequency BTC trend benchmark had a Sharpe of about 1.6 **gross of fees** (2018–2025), vs just under 0.8 for vol-targeted (20%) long-only BTC. Trends tend to persist when major financial centres are active. — [Concretum](https://concretumgroup.com/seasonality-in-bitcoin-intraday-trend-trading/)
- **Hourly overreaction (PR).** Caporale & Plastun (2020), FMPM: hourly BTC, ETH and LTC data show momentum-type behaviour after one-day abnormal returns. — [Springer](https://link.springer.com/doi/10.1007/s11408-020-00357-1)

### Inferences
- The bot's 2h Supertrend(10,3) has an effective signal horizon of roughly 1–3 days, which sits at the short end of the horizons with evidence. The literature's best-supported improvement is adding **longer horizons** (multi-lookback ensemble, e.g. Donchian 20/50/100 days), not adding filters on the same horizon. This fits the bot's finding that daily-trend, ADX and MACD confluence filters hurt: those filters cut trades without diversifying across horizons.
- Long-only or bull-concentrated TSMOM (Han et al.; Zarattini long-only) suggests the short side in crypto is weaker. The bot should check its short-side R/trade separately.
- Ensembles over lookbacks are preferred to choosing one "best" lookback, because single-parameter crypto results are sample-dependent (Grobys; arXiv 2009.12155).

### Gaps
- I could not retrieve Rozario et al. or Huang, Sangiorgi & Urquhart; no reliable results surfaced in searches.
- I found no PR study that tests Supertrend specifically, or the 2h frame specifically.
- Zarattini's exact lookback set and Sharpe table were not verified (arxiv and CXO were blocked).

---

## 2. Volatility targeting / volatility-scaled sizing

### Takeaway
Volatility targeting reliably cuts tail events and drawdowns. It improves Sharpe mainly for "risk assets" with a leverage effect. Crypto is a high-vol risk asset, so the case is reasonable, and a crypto-specific PR paper finds vol management mitigates momentum crashes. The bot's fixed 1 USDT risk per trade with ATR-based stops is already a form of per-trade volatility normalization.

### Cited Findings
- **Harvey, Hoyle, Korgaonkar, Rattray, Sargaison & Van Hemert (2018), "The Impact of Volatility Targeting", JPM (PR; Man Group authors).** 60+ assets with daily data back to 1926, at a 10% vol target.
  - Sharpe improves for equities and credit: US equities from about 0.40 to about 0.48–0.51 (secondary summary).
  - The effect on bonds, FX and commodities is negligible.
  - It reduces maximum drawdowns and the likelihood of extreme returns (vol-of-vol) across all assets.
  - Mechanism: the leverage effect (vol rises when prices fall).
  - Sources: [Duke PDF](https://people.duke.edu/~charvey/Research/Published_Papers/P135_The_impact_of.pdf); [Man Institute](https://www.man.com/maninstitute/the-impact-of-volatility-targeting); [Quantpedia summary](https://quantpedia.com/the-impact-of-volatility-targeting-on-equities-bonds-commodities-and-currencies)
- **"Cryptocurrency momentum has (not) its moments" (2025), Financial Markets and Portfolio Management (PR; Grobys et al., Univ. Vaasa).**
  - Large-cap crypto momentum suffers severe crashes. Vol-managed versions raise weekly average raw returns by **more than 200%** vs plain strategies, with alphas significant at 5%.
  - Vol management does **not** significantly change tail risk (power-law exponents).
  - Crashes come from extreme jumps in a single coin in the short leg, not from market reversals.
  - Caveat: Liu et al. (2019) argue vol scaling can suffer look-ahead bias.
  - Sources: [Springer](https://link.springer.com/article/10.1007/s11408-025-00474-9); [Vaasa repository](https://osuva.uwasa.fi/handle/10024/20018)
- **Zarattini et al. (2025)** use 25% vol targeting in their crypto trend ensemble (see Q1). — [IDEAS](https://ideas.repec.org/p/chf/rpseri/rp2580.html)
- **Practitioner (Blog).** BTC's annualized vol has historically been about 50–65%, which is the basis for vol-target sizing examples. — [Advisor Perspectives](https://www.advisorperspectives.com/commentaries/2025/11/02/client-portfolios-cant-stomach-ride-considered-crypto)
- **Downside-risk targeting (WP).** One study reports a higher Sharpe, better drawdown protection and higher utility than plain vol targeting. — [GARP whitepaper 2019](https://www.garp.org/hubfs/Whitepapers/a2r1W0000015Rx0QAE_Whitepaper.TailRisk.Oct19.pdf)

### Inferences
- Fixed-R sizing with an ATR stop already equalizes risk per trade across coins, a per-position "risk parity". What it lacks is **portfolio-level** vol control. When all 3 positions are in highly correlated coins (e.g. all long in alts), true portfolio risk is close to 3R on one factor. Possible fixes: a portfolio-level cap on correlated exposure, or scaling risk per trade down when realized market vol (e.g. BTC 30-day vol) is high.
- The evidence says vol targeting helps drawdowns more reliably than mean return. Judge it in the backtest on max drawdown and losing streaks, not only on R/trade.

### Gaps
- I found no crypto PR study testing vol-scaling specifically for single-asset trend-following on intraday bars.
- I did not retrieve Moreira & Muir (2017, JF) crypto replications.

---

## 3. Diversification across coins: correlation, number of coins, cross-sectional vs time-series

### Takeaway
Large-cap crypto is dominated by one market factor (BTC beta). Large-cap alts rise with BTC and fall harder. Diversification across 9 large caps is therefore much smaller than the count suggests. Cross-sectional (relative) momentum has weak evidence in crypto, while time-series momentum is stronger.

### Cited Findings
- The crypto market factor is one of the three factors that capture most crypto cross-sectional returns, consistent with a dominant common factor. — [Liu, Tsyvinski & Wu, JF 2022](https://econpapers.repec.org/RePEc:bla:jfinan:v:77:y:2022:i:2:p:1133-1177)
- **Kaiko (Blog).** ETH, SOL, XRP and ADA typically rise with BTC but sell off harder on BTC corrections; diversification is "selective", not broad. Some pairs show low correlation (SOL–DOGE 0.06, XRP–SOL 0.18 in one window). In one Q2, alts fell up to −31.3% vs −18.05% for BTC, attributed to thinner books and fewer market makers. — [Kaiko](https://www.kaiko.com/resources/gap-grows-between-bitcoin-and-altcoins?page=30); [Kaiko KT5](https://research.kaiko.com/insights/moving-beyond-bitcoin-with-the-kt5-index); [CoinDesk on correlations](https://www.coindesk.com/business/2023/09/13/what-correlations-tell-us-about-the-value-of-multi-asset-crypto-portfolios/)
- **Cross-sectional vs time-series.** TSMOM evidence is strong and cross-sectional evidence weak under realistic assumptions — [Han, Kang & Ryu](https://acfr.aut.ac.nz/__data/assets/pdf_file/0009/918729/Time_Series_and_Cross_Sectional_Momentum_in_the_Cryptocurrency_Market_with_IA.pdf). Momentum crashes are driven by single-coin jumps in the short leg — [FMPM 2025](https://link.springer.com/article/10.1007/s11408-025-00474-9).
- Zarattini et al. found that expanding from BTC to a universe of up to 20 liquid coins with a trend filter added alpha vs BTC. — [Concretum summary](https://concretumgroup.com/catching-crypto-trends-a-tactical-approach-for-bitcoin-and-altcoins/)

### Inferences
- With a high common factor, the "3 concurrent positions" cap acts mainly as a cap on directional market exposure. A sensible portfolio rule is a net-direction limit, e.g. at most 2 positions in the same direction, or treating BTC-correlated alts as one risk bucket. Test this; I found no direct paper on it.
- Shorting single small or volatile alts carries jump risk (momentum crash mechanism). Stops and isolated margin limit, but do not remove, gap-through-stop losses.

### Gaps
- I found no source that quantifies how many coins capture most of the diversification benefit in crypto trend portfolios.
- I found no reliable study on BTC-dominance filters.

---

## 4. Funding rates, open interest, basis, long/short ratio, liquidations

### Takeaway
PR evidence shows that perp/futures basis ("carry") is large, time-varying and driven by trend-chasing leveraged retail demand. High carry predicts subsequent crashes, which makes it a crowding indicator. Evidence that funding, OI or long/short ratio works as a **directional entry filter** for trend trades is limited to blogs, small samples and mixed results. Carry-trade profits have compressed since 2024.

### Cited Findings
- **Schmeling, Schrimpf & Todorov, "Crypto Carry" (BIS WP 1087, 2023, rev. 2025; Management Science, PR).** Futures-spot carry often exceeds 40% p.a. and reaches up to 60% p.a., varying strongly over time. It is driven by demand from smaller, trend-chasing investors seeking leverage, together with scarce arbitrage capital. The paper studies carry's **predictive power for future crashes**. Arbitrage is risky because of margin spikes and liquidations in drawdowns. — [BIS PDF](https://www.bis.org/publ/work1087.pdf); [BIS page](https://www.bis.org/publications/working-paper-1087-crypto-carry); [Management Science](https://pubsonline.informs.org/doi/fpi/10.1287/mnsc.2024.05069)
- **He, Manela, Ross & von Wachter, "Fundamentals of Perpetual Futures" (arXiv 2212.06888, WP; 2024 draft).** Perp deviations from no-arbitrage prices are much larger than in FX, comove across coins and shrink over time. Their strategy trades spread convergence, not direction. — [arXiv](https://arxiv.org/abs/2212.06888v3)
- **Carry trade (WP, CMU).** Long-spot/short-perp carry was "unusually profitable", with **in-sample** annual Sharpe of about 7–10 (flag: in-sample). — [CMU PDF](https://www.andrew.cmu.edu/user/azj/files/CarryTrade.v1.0.pdf)
- **"Cryptocurrency as an Investable Asset Class: Coming of Age" (arXiv 2510.14435, 2025, WP).** Crypto carry "used to be highly profitable" but has compressed sharply since 2024. — [arXiv](https://arxiv.org/pdf/2510.14435)
- **Inan, "Predictability of Funding Rates" (IRFA 2026, PR; known via secondary write-up).** BTCUSDT funding from Jan 2024 to Mar 2025 is forecastable out of sample, but a cross-exchange strategy based on it is wiped out by costs. Predictability varies over time and across exchanges. — reported in search summary; original not retrieved (see Gaps).
- **BitMEX funding vs BTC price (arXiv 1912.03270, WP).** Studies the correlation of funding with the exchange rate. — [arXiv](https://arxiv.org/pdf/1912.03270)
- **"The Quarter-Hour Effect" (arXiv 2607.09426, 2026, WP).** Periodic algorithmic trading creates return predictability in crypto futures. Relevant to execution timing; details not retrieved. — [arXiv](https://arxiv.org/pdf/2607.09426)
- **Blog/informal evidence on funding as a filter (low quality, small samples).**
  - On Binance BTC/ETH perps (2022–2026), a z-scored funding contrarian signal is **decaying**. A vol-gated version recovers some edge on BTC (small sample). — [askrubyai blog](https://askrubyai.github.io/blog/posts/2026-02-26-funding-regime-filter/index.html)
  - Extreme funding mean-reverts reliably, but price direction does not follow. — [Medium](https://medium.com/crypto-alpha-drip/the-signal-in-bitcoins-funding-rate-e19abee4842e)
  - A dollar-neutral cross-sectional funding factor (long low funding, short high funding) had a walk-forward OOS Sharpe of 0.39. The level-based carry is "competed away", and crowded-long reversal is "at best a faint tailwind". — [Alpha Research Paper 2](https://bryanvine.github.io/alpha-research/paper2.html)
- **Open interest / liquidations.** I found no PR study testing OI or liquidations as return predictors. What I found was only market commentary (e.g. Block Scholes / Bybit reports). — [Block Scholes](https://www.blockscholes.com/research/block-scholes-x-bybit-crypto-derivatives-december-12th)

### Inferences
- The best-supported use of derivatives data for this bot is a **crowding/risk filter, not an entry signal**. For example, skip or downsize long entries when funding or annualized basis is extreme (top decile, e.g. >30–40% annualized), because high carry predicts crashes (BIS). Validate this in the bot's backtest before adoption. The PR evidence is about crash risk at the market level, not about 2h trend entries.
- Funding is also a direct cost. Trend longs in bull markets pay funding exactly when trends work, so include it in the backtest P&L.

### Gaps
- Original text of Inan (2026) not verified.
- I found no PR evidence on the long/short account ratio.
- I found no PR test of funding or OI filters combined with trend entries.

---

## 5. Regime filters: volatility regime, trend strength, BTC trend as market filter, weekend/time-of-day, halving

### Takeaway
The robust "regime" finding is that crypto TSMOM makes most of its money in bull markets and loses in falling markets (Han et al.). This argues for a market-level BTC trend/regime check mainly for alt **longs**. Time-of-day seasonality exists in BTC, but the evidence comes from practitioner backtests. I found no credible evidence on halving-cycle or BTC-dominance filters.

### Cited Findings
- TSMOM is concentrated in bullish markets and loses in most falling-market cases. — [Han, Kang & Ryu](https://acfr.aut.ac.nz/__data/assets/pdf_file/0009/918729/Time_Series_and_Cross_Sectional_Momentum_in_the_Cryptocurrency_Market_with_IA.pdf)
- Intraday trends persist more when major financial centres are active. Intraweek seasonality differs between 2018–2020H1 and 2020H2–2025 subsamples (Blog). — [Concretum](https://concretumgroup.com/seasonality-in-bitcoin-intraday-trend-trading/)
- Buying BTC at 21:00 UTC and selling at 23:00 UTC gives a Calmar of 1.96 (Padyšák & Vojtko, WP summarized by Quantpedia; flag: data-mined seasonality). — [Quantpedia](https://quantpedia.com/strategies/intraday-seasonality-in-bitcoin)
- Intraday TSMOM is strongest in the highest-volume or highest-volatility sessions (PR). — [Reading repository](https://centaur.reading.ac.uk/100181)
- Vol-gating made a decaying funding signal work again on BTC (Blog, small sample). — [askrubyai](https://askrubyai.github.io/blog/posts/2026-02-26-funding-regime-filter/index.html)

### Inferences
- The bot already uses EMA200 on 2h (about 17 days), a regime filter. Adding a daily trend filter made results worse, consistent with over-filtering. A **BTC regime filter applied only to alt longs** has the most literature backing (bull-concentration of TSMOM, alt beta to BTC), but it is untested here.
- Avoid time-of-day filters unless they are shown to be robust across subsamples (Concretum shows the seasonality changes between eras).

### Gaps
- I found no PR evidence on halving cycles, weekend effects for trend entries, ADX-type trend-strength filters in crypto, or BTC dominance.

---

## 6. Exits: trailing stops vs time stops vs fixed targets; pyramiding

### Takeaway
Theory and evidence say stop-losses add value only when returns are serially dependent (momentum). Trend-following edges come from letting winners run, so trailing exits fit, and fixed profit targets truncate the right tail. This is consistent with the bot's finding that 2R/3R targets and partial take-profit hurt.

### Cited Findings
- **Kaminski & Lo (2014), "When Do Stop-Loss Rules Stop Losses?", Journal of Financial Markets 18:234–254 (PR).**
  - Under a random walk, stop-losses always reduce expected return.
  - Under momentum or regime-switching they can add value. Empirically (US, 1950–2004 monthly), certain stop rules added 50–100 bp/month vs buy-and-hold during stop-out periods.
  - At longer sampling frequencies they can raise expected return while substantially reducing volatility.
  - Sources: [MIT DSpace](https://dspace.mit.edu/handle/1721.1/114876); [RePEc](https://econpapers.repec.org/RePEc:eee:finmar:v:18:y:2014:i:c:p:234-254)
- Technical trend rules significantly reduce buy-and-hold drawdowns in crypto. — [Hudson & Urquhart 2019](https://link.springer.com/article/10.1007/s10479-019-03357-1)
- **Practitioner (Blog).** A "~21-day trend breaker" to sit out bear markets worked, while drawdown-from-high and fast-EMA gates "did NOT work — too laggy / too whippy". — [degen-ai strategy notes](https://timbrinded.github.io/degen-ai/strategies/funding-flip-fade.html)

### Inferences
- Keep the trailing Supertrend/ATR exit. Positive skew with a ~34% win rate is the classic trend signature, and fixed targets cut exactly the tail that pays.
- Time stops and pyramiding: I found no crypto-specific evidence. Pyramiding would raise correlated exposure on a 30 USDT account and should be tested only with a portfolio risk cap.

### Gaps
- I did not retrieve Clare et al. (stop-loss/trend in equities) or crypto-specific tests of time stops and pyramiding.

---

## 7. Transaction costs: fees, slippage, funding

### Takeaway
Base USDT-M taker fees are about 0.05% per side (0.10% round trip). Hudson & Urquhart found breakeven costs for daily-ish rules well above crypto costs. The literature consistently shows that higher-frequency or arbitrage edges vanish after costs: intraday Sharpe 1.6 is gross of fees, and Inan finds funding predictability wiped out by costs. This mirrors the bot's 5m–30m failure.

### Cited Findings
- Binance USDT-M regular tier (secondary sources): **0.02% maker / 0.05% taker**; paying with BNB gives about 10% off, so about 0.045% taker. Rates change by policy and VIP tier. — [Binance FAQ](https://www.binance.com/support/faq/360033544231); [Finder](https://www.finder.com/binance-futures-fees); [Bitsgap](https://bitsgap.com/blog/binance-trading-fees-explained-what-it-costs)
- Breakeven costs for most of 14,919 tested rules are "substantially higher" than crypto costs. — [Hudson & Urquhart 2019](https://link.springer.com/article/10.1007/s10479-019-03357-1)
- Zarattini et al. assume 0.10% costs (per trade or rebalance) on daily or monthly rebalanced signals. — [CXO summary](https://www.cxoadvisory.com/technical-trading/crypto-asset-trend-following-strategies/)
- Funding-rate predictability is real but not profitable after costs (Inan 2026, via secondary summary). Concretum's intraday BTC trend Sharpe of about 1.6 is **gross** of fees. — [Concretum](https://concretumgroup.com/seasonality-in-bitcoin-intraday-trend-trading/)
- Practitioner warning: about 73% of raw-backtest trades were "un-fillable" on one exchange; liquidity-aware sizing matters. — [degen-ai notes](https://timbrinded.github.io/degen-ai/strategies/funding-flip-fade.html)
- Carry (and hence the funding a trend long pays) can reach 40–60% p.a. in frothy periods. — [BIS WP 1087](https://www.bis.org/publ/work1087.pdf)

### Inferences (own arithmetic, not sourced)
- **Fees in R.** With 1 USDT risk and stop distance d (as a fraction of price), notional = 1/d. A taker round trip at 0.10% costs 0.001/d R. That is about 0.033R at a 3% stop and about 0.10R at a 1% stop.
  - Tight stops on short timeframes explain why 5m–30m failed.
  - At 2h with ATR stops, fees are probably about 0.03–0.07R per trade, material against +0.24R.
  - Using maker (post-only) entries where possible could save about 0.01–0.02R per trade.
- **Stop slippage.** Stop exits are taker orders and can slip in fast markets; model at least 1–2 bps extra on stop fills.
- **Funding.** In high-carry bull phases, a multi-day long can pay several tenths of a percent of notional. At notional = 1/d, that becomes a few hundredths of R per day, so include funding in the backtest.
- **Leverage cap.** 30 USDT at 5x caps total notional at 150 USDT. With 3 positions and tight stops (notional = 1/d, so ≥33 USDT at d = 3%, 100 USDT at d = 1%), the margin cap can bind and silently change risk per trade. Check this in the bot.

### Gaps
- I did not verify OKX and Bybit fee tiers.
- I found no academic study quantifying perp slippage for small orders on large caps. For orders of about 30–150 USDT notional on top-10 coins, impact is likely negligible beyond the spread, but this is unsourced.
