# Popular Retail Crypto Futures Strategies: Claims vs. Independent Evidence

Scope note: about 18 searches and fetches. These hosts could not be reached from this session (DNS blocked): liberatedstocktrader.com, www.tradingview.com (Pine docs), www.mql5.com. Several findings below therefore come from search-result snippets rather than full text, and are marked that way. Context for the reader: the user's bot is a 2h Supertrend(10,3)+EMA200 trend follower on 9 large-cap USDT perps. It made +0.24R/trade out-of-sample. Pullback-to-EMA21, MACD-cross, Donchian+volume and 6-indicator confluence entries were negative or weaker in their tests, and 5m-30m timeframes were unprofitable after fees.

## Q1. Which strategies dominate YouTube/TradingView crypto content (2022-2026), and what is claimed?

### Takeaway
Retail content mostly packages trend/ATR-trailing indicators (Supertrend, UT Bot, Half Trend, Chandelier Exit), counter-trend oscillators (RSI divergence, Bollinger), "price-action" frameworks (SMC/ICT order blocks, FVG, liquidity sweeps) and automated bots (grid, DCA, martingale). Headline claims are usually win rates of 60-90% from "100-trade" tests. I found no large-sample independent validation for SMC, UT Bot, Half Trend, Squeeze Momentum, Heikin-Ashi or Elliott Wave in crypto.

### Cited Findings
- Trading Rush style "tested 100 times" claims: a TradingView script built from the channel's tests reports a MACD-based setup on 30m EURUSD/EURJPY with 1.5 R:R and win rates of about 50-62% over 100 trades. These are the channel's own figures, not an audit — [TradingView script "Trading Rush Signals Alerts"](https://my.tradingview.com/script/4gXXEI5Y-Trading-Rush-Signals-Alerts/?amp) (snippet)
- Independent re-tests contradict the viral MACD+200EMA claim. A TradingView commenter found "mostly poor backtest results, across all TF and tickers" with 1:1 ATR targets — [TradingView idea "Trading Rush MACD strategy, 200 TREMA"](https://id.tradingview.com/chart/ETHUSDT/qv5lQBYK-Tradign-Rush-MACD-strategy-200-TREMA) (snippet). An MQL5 re-test of the MACD-below-zero + 200 EMA rule on 30m gold, 2010-2025, reports a 31.4% win rate, losses after costs, and only 2 of 16 years positive, against an "86%" claim — [MQL5 blog "Three Viral Trading Strategies Re-Tested on 16+ Years of Data"](https://www.mql5.com/en/blogs/post/780027) (snippet only, host blocked)
- "Real or fake: backtesting an 87 percent win rate strategy" is the title of an article debunking a viral win-rate claim — [BrokerXplorer](https://www.brokerxplorer.com/article/real-or-fake-backtesting-an-87-percent-win-rate-strategy-6745) (title only; content not retrieved)
- Liberated Stock Trader runs large-sample indicator tests (for example "I Tested 606,422 MACD Indicator Trades", and Supertrend over 4,052 test trades). Per snippets, Supertrend on 5-minute AAPL was unprofitable for day trading, and the site says MACD tests better on Heikin-Ashi charts — [LST Supertrend](https://liberatedstocktrader.com/?p=28272); [LST MACD](https://liberatedstocktrader.com/?p=24867) (host blocked, snippets only; these are stocks, not crypto)
- A Share.Market writer's 200,000-trade Supertrend test on Nifty 500 stocks reports that the best results required long holding periods — [Share.Market](https://www.share.market/buzz/insights/i-backtested-200000-trades-using-the-supertrend-indicator-here-is-what-actually-works) (snippet)
- QuantifiedStrategies' Supertrend test uses weekly S&P 500 data back to 1960 with non-optimized rules and concludes Supertrend "can add value as a systematic trend-following tool" — [QuantifiedStrategies Substack](https://quantifiedstrategies.substack.com/p/the-supertrend-indicator-backtested). A secondary summary reports $100k growing to about $5.4M with a 68% win rate across only 41 trades (unverified, paywalled) — [pulse.bot summary](https://www.pulse.bot/stock-trading/blogs/the-supertrend-indicator-backtested-8014db44-4e08-4165-bad7-d8a724819ddf)
- Smart Money Concepts / order blocks: a placebo-controlled TradingView study compared real order blocks with matched random "placebo" zones. "No tested configuration showed a reliable difference", and pooled estimates were slightly below zero, with a confidence interval that included zero. It also notes a 54% win rate can be worse than random on real data — [TradingView "Order Block (OB) Statistics: Real Win Rate vs Random Levels"](https://vn.tradingview.com/script/yFmy3VBi-Order-Block-OB-Statistics-Real-Win-Rate-vs-Random-Levels/) (snippet)
- SMC claims from a broker blog: 1,000 mechanical trades on FX majors, 64.8% FVG mitigation frequency, 58.2% liquidity-sweep follow-through and a 43.1% standalone order-block bounce rate. Methodology is undisclosed and the broker has a commercial interest — [FXNX blog](https://fxnx.com/en/blog/smart-money-concepts-work-backtest-evidence)
- A Bitcoin SMC vendor indicator advertises "backtest-verified" results from 90 trades (small sample, marketing) — [TradingView scripts listing](https://cn.tradingview.com/scripts/bitcoinprice/)

### Inferences
- Trading Rush, the "TradeSmart"-style channels and similar "100 trades" tests are mostly on FX, use short timeframes and often skip fees or slippage. A sample of 100 trades at a 55% win rate has a standard error of about ±5 percentage points, which is not enough to separate a small edge from noise.
- The ATR-trailing indicators (UT Bot, Half Trend, Chandelier Exit, Supertrend) are close cousins of each other. If Supertrend works on 2h, the others are mostly re-parameterisations of the same trend-following exposure, so testing them is unlikely to add an independent edge. Their main value would be as alternative exit/trailing rules.

### Gaps
- I found no quantitative popularity ranking (TradingView script likes or YouTube views) for 2022-2026. Popularity is inferred from the user's list, not measured.
- I found no independent large-sample crypto tests for UT Bot, Half Trend, LazyBear Squeeze Momentum, Hull MA, Fibonacci or Elliott Wave.
- The full text of the TradeSmart/Trading Rush test summaries was not retrieved.

## Q2. Independent large-sample and academic tests of TA in crypto: what survives transaction costs?

### Takeaway
Academic evidence on crypto is moderately favourable to **trend-following / breakout / moving-average** rules, mostly on daily data, and unfavourable to **counter-trend** rules (RSI, Bollinger mean reversion). The strongest recent evidence is for **multi-lookback Donchian breakout ensembles with volatility targeting**, which survive 0.10-0.50% costs. Shorter-horizon trends appear to have weakened recently. All of this is consistent with the user's own results.

### Cited Findings
- Hudson & Urquhart, "Technical trading and cryptocurrencies" (Annals of Operations Research, 2019 online / 2021): almost 15,000 rules from five families (filters, moving averages, support/resistance, channel breakouts, on-balance volume) tested on two Bitcoin markets and three other major coins. The rules show significant predictive power, and average annualised returns are significant at the 5% level for each coin. Results survive data-snooping corrections, give higher risk-adjusted returns than buy-and-hold, and significantly reduce drawdowns — [Springer](https://link.springer.com/article/10.1007/s10479-019-03357-1); [Hull repository](https://hull-repository.worktribe.com/output/2328042)
- Hudson & Urquhart also report break-even transaction costs "substantially higher than those typically found in cryptocurrency markets" — [Springer, via search summary](https://link.springer.com/article/10.1007/s10479-019-03357-1)
- Corbet, Eraslan, Lucey & Sensoy (2019, Finance Research Letters 31:32-37), "The effectiveness of technical trading rules in cryptocurrency markets": moving-average oscillator and trading-range-breakout rules on 1-minute Bitcoin data (about 2.34M observations). There is significant support for MA strategies, the variable-length MA performed best, and buy signals beat sell signals — [IDEAS/RePEc](https://ideas.repec.org/a/eee/finlet/v31y2019icp32-37.html); [DORAS DCU](https://doras.dcu.ie/25053)
- Gerritsen, Bouri, Ramezanifar & Roubaud (2020, Finance Research Letters 34), "The profitability of technical trading rules in the Bitcoin market": seven trend-following rules on daily BTC, July 2010-Jan 2019. Trading range breakout has significant forecasting power, and MACD outperformed in some specifications. Counter-trend RSI and Bollinger Bands generally underperformed buy-and-hold, sometimes with negative Sharpe. The **transaction costs are not modelled** — [IDEAS/RePEc](https://ideas.repec.org/a/eee/finlet/v34y2020ics1544612319303770.html); [Utrecht portal](https://research-portal.uu.nl/en/publications/the-profitability-of-technical-trading-rules-in-the-bitcoin-marke/); summary via [TradingView idea](https://my.tradingview.com/chart/BTCUSD/tK5t6vU6-The-profitability-of-TA-trading-rules-in-the-Bitcoin-market)
- Grobys, Ahmed & Sapkota (2020, FRL), "Technical trading rules in the cryptocurrency market": a variable moving average works, notably the 20-day MA rule — [IDEAS](https://ideas.repec.org/a/eee/finlet/v32y2020ics1544612319308852.html); [Osuva PDF](https://osuva.uwasa.fi/bitstream/10024/11192/2/Osuva_%20Grobys_Ahmed_Sapkota_2020.pdf)
- Ahmed, Grobys & Sapkota (2020): simple MA rules on the 10 most-traded **privacy coins** do not yield consistent profits beyond buy-and-hold. Grobys reads this as privacy coins forming a more efficient market — [Osuva PDF](https://osuva.uwasa.fi/bitstream/10024/11193/2/Osuva_Ahmed_Grobys_Sapkota_2020.pdf); [Cointelegraph op-ed by Grobys](https://cointelegraph.com/opinion/is-technical-trading-in-cryptocurrency-markets-profitable)
- Svogun & Bazán-Palomino (2022): transaction costs reduce the likelihood of TA profitability for Ripple and Litecoin but increase it for Bitcoin and Ethereum (as summarised in search results) — [Emerald JCMS](https://emerald.com/insight/content/doi/10.1108/JCMS-10-2021-0030)
- Wei et al. (Glasgow) challenge the genuine value of TA, and of fundamentals, in crypto — [Glasgow eprints](https://eprints.gla.ac.uk/302711/1/302711.pdf)
- Zarattini, Pagani & Barbon (2025, SFI Research Paper 25-80), "Catching Crypto Trends": an ensemble of Donchian channel breakout models with different lookbacks, long-only, across up to 20 liquid coins, 25% volatility target. Costs of 0.10%, 0.25% and 0.50% are tested. Reported results vary by summary: "Combo" CAGR 30%, Sharpe 1.58, Sortino 2.03, alpha 14% vs BTC; another summary gives 18% net CAGR and 11% net alpha (Jan 2015-Mar 2025). Long trends remain statistically robust, but **shorter trends have weakened in the recent era** — [IDEAS](https://ideas.repec.org/p/chf/rpseri/rp2580.html); [Concretum](https://concretumgroup.com/catching-crypto-trends-a-tactical-approach-for-bitcoin-and-altcoins/); [CXO Advisory](https://www.cxoadvisory.com/technical-trading/crypto-asset-trend-following-strategies/) (numbers not verified against the PDF)
- Wits thesis (Ismail): TA rules including Bollinger Bands, plus a Kalman filter, outperformed on crypto even after transaction costs (thesis, not peer-reviewed) — [WIReDSpace](https://wiredspace.wits.ac.za/bitstreams/daebe561-6830-4ff5-9e0f-2a052156eef5/download)

### Inferences
- The consensus across these papers is that trend/breakout and MA rules have edge in crypto at daily frequency, while counter-trend rules do not. This matches the user's finding that Supertrend+EMA200 works while pullback/MACD-cross entries are weaker.
- The Zarattini result suggests two avenues are more promising than adding entry indicators: (a) diversifying across lookbacks, as an ensemble of Supertrend/Donchian at several periods, and (b) volatility-targeted position sizing across more coins. The note that short-term trends have weakened supports staying at 2h-daily rather than going lower.
- Many academic studies are long-only spot on daily bars and ignore funding rates. Perp shorts and funding can change the results.

### Gaps
- I did not find a paper explicitly testing Supertrend, Heikin-Ashi or Chandelier Exit on crypto at scale.
- Full-text numbers for Hudson & Urquhart (per-rule breakeven costs) and Corbet et al. (cost-adjusted returns) were not retrieved.

## Q3. Ichimoku, Heikin-Ashi, Chandelier Exit, Keltner/Bollinger breakouts, multi-timeframe: crypto-specific evidence

### Takeaway
Crypto-specific evidence for these tools is thin and mostly informal: student reports, TradingView ideas and Medium posts. Bollinger counter-trend use underperforms in peer-reviewed work. Breakout-type rules (TRB/Donchian) have the better evidence, so Keltner/Bollinger *breakout* variants are plausible but unproven.

### Cited Findings
- Ichimoku: an HKUST independent study (Byun, 2021) tests Ichimoku on BTC and ETH vs buy-and-hold. The author calls its usefulness "questionable" given crypto volatility (full results not seen) — [HKUST PDF](https://cse.hkust.edu.hk/~rossiter/independent_studies_projects/ichimoku_cloud_strategy/ichimoku_cloud_strategy.pdf)
- A TradingView idea on "best Ichimoku numbers for Bitcoin, 10 years of data" (informal, parameter search, so optimisation risk) — [TradingView](https://in.tradingview.com/chart/BTCUSD/NDeiRzY2-BEST-Ichimoku-Numbers-for-Bitcoin-10-Years-of-Data-Says). A 15m ETH Ichimoku backtest post admits wrong settings — [TradingView](https://tw.tradingview.com/chart/ETHUSD/4dBwHB43-Backtest-Ichimoku-strategy-15M)
- Bollinger (counter-trend) underperformed buy-and-hold on daily BTC, 2010-2019 — [Gerritsen et al. via IDEAS](https://ideas.repec.org/a/eee/finlet/v34y2020ics1544612319303770.html)
- Bollinger/Keltner squeeze: a Superalgos data-mining study on BTC/USDT (Medium, not peer-reviewed; costs not evident) — [Medium/Superalgos](https://medium.com/superalgos/a-quantitative-study-of-the-bollinger-bands-squeeze-strategy-9f47143f33fb)
- Heikin-Ashi: the only evidence found is Liberated Stock Trader's claim (stocks) that MACD tests better on HA charts — [LST](https://www.liberatedstocktrader.com/macd-indicator/) (snippet). Note that HA candles have synthetic open/close prices, so backtests that fill at HA prices are unrealistic (see Q6).
- Trading range breakout (Donchian-like) is the most consistently supported rule family — [Gerritsen et al.](https://ideas.repec.org/a/eee/finlet/v34y2020ics1544612319303770.html); [Zarattini et al.](https://ideas.repec.org/p/chf/rpseri/rp2580.html)

### Inferences
- Ichimoku is essentially a mid-channel (Donchian midpoint) trend filter, so it overlaps heavily with EMA200+Supertrend.
- The user's own Donchian+volume test was negative, while Zarattini's Donchian ensemble was positive. The difference may be the volume filter, the single lookback, or the absence of vol-targeting. Worth re-testing a no-volume, multi-lookback version on daily/4h.
- Chandelier Exit is worth testing as an *exit* alternative (ATR trail from highest high) on existing Supertrend entries, not as a new entry system.

### Gaps
- I found no peer-reviewed or large-sample crypto study of Heikin-Ashi, Chandelier Exit, Keltner breakout, or multi-timeframe confirmation.

## Q4. Grid, DCA and martingale bots: risks, liquidations, exchange stats

### Takeaway
Exchanges publish risk warnings and marketing, not aggregate PnL or liquidation statistics. The structural risk is clear: grids and martingale/DCA are short-volatility, mean-reversion bets that lose heavily when price trends out of range, and leverage on futures grids adds liquidation risk.

### Cited Findings
- Binance names losses from "undisciplined setting, unilateral quotation, market prices out of the grid range". It warns of liquidation if margin falls below requirements and states the feature is used "at your own risk" — [Binance Futures Grid FAQ](https://www.binance.com/en-IN/support/faq/f4c453bab89648beb722aa26634120c3); [Binance blog "Demystifying the Futures Grid Bot"](https://www.binance.com/blog/markets/demystifying-the-futures-grid-bot-5592639286007523221)
- Binance offered "Futures Grid Loss Protection Vouchers" to selected users, with no compensation if total grid PnL is positive. The existence of a loss-compensation promo suggests losses are common, though this is an inference — [Binance FAQ](https://www.binance.com/en/support/faq/detail/bb51a1f516c54dd6ab057db6c0dbd6d0)
- In one Binance Square backtest example, BTC rose 14.15% while the grid bot returned 7.35%, so grids underperform in trends (single example) — [Binance Square](https://www.binance.com/en/square/post/438172)
- User complaints about losses on futures grid bots with trailing (anecdotal) — [Sikayetvar](https://www.sikayetvar.com/en/binance-us/binance-futures-grid-bot-triggered-opposite-trades-and-caused-me-a-loss)
- DCA/safety-order bots: an anecdote that safety orders trigger more during crashes, leaving a "stuck" bot — [TradingView "DCA Bot is stuck"](https://pl.tradingview.com/chart/BNBUSD/jIsBTJc7-DCA-Bot-is-stuck)
- Platform risk: in October 2022, FTX API keys linked to 3Commas were exploited for unauthorized trades. Several users reported losses over $1M each, and FTX said it would cover about $6M. 3Commas initially blamed phishing — [The Block](https://www.theblock.co/news/regulation/2022-10-23-ftx-api-keys-3commas-exploited-179237); [Web3 Is Going Great](https://web3isgoinggreat.com/single/several-users-report-losing-more-than-a-million-dollars-each-in-3commasftx-theft); [Bitcoinist](https://bitcoinist.com/ftx-compensate-users-affected-by-3commas-phishing/)

### Inferences
- Martingale/DCA payoff profiles show many small wins and rare catastrophic losses, so high win rates on leaderboards are expected and say nothing about expectancy.
- Grid bots are structurally opposite to the user's trend bot. They could diversify it in range regimes, but only with hard range-exit stops and no or low leverage.

### Gaps
- I found no published aggregate PnL or liquidation-rate statistics from Binance, Bybit or Pionex. No independent study of grid-bot returns across users was found.

## Q5. Telegram/Discord signal groups and copy-trading: performance studies

### Takeaway
Independent research shows signal channels are heavily used for pump-and-dumps, and influencer calls lose money on average. Copy-trading leaderboards suffer documented ranking and survivorship distortions. No credible study shows that typical paid signal groups have positive net expectancy.

### Cited Findings
- Hamrick et al., "An examination of the cryptocurrency pump-and-dump ecosystem" (Information Processing & Management, 2021) covers about six months of 2018 data. The published version counts 2,469 pumps on Telegram and 952 on Discord; an earlier version counts 3,767 Telegram and 1,051 Discord signals. Median pump return was 4.1%. For top-75 coins the median rise was 4.8% (Telegram) and 3.5% (Discord); for coins ranked above 500 it was 19% and 23%. 10% of Telegram pumps rose more than 18% within 5 minutes — [UCL PDF](https://discovery.ucl.ac.uk/10133232/1/SSRN-id3303365%20%281%29.pdf); [CEPR/VoxEU](https://cepr.org/voxeu/columns/economics-cryptocurrency-pump-and-dump-schemes); [The Block](https://www.theblock.co/amp/linked/5667/university-researchers-identified-over-4800-pump-and-dump-schemes-involving-crypto-over-a-six-month-period)
- Follow-up research on the long-term impact of pumps (Clough & Edwards 2023) — [arXiv](https://arxiv.org/pdf/2309.06608.pdf)
- A three-university study of 36,000 tweets from 180 crypto influencers on X found average cumulative returns from following their signals of -2.24% after 10 days and -6.53% after 30 days — [ForkLog](https://forklog.com/en/study-reveals-crypto-influencers-recommendations-lead-to-losses/)
- Telegram signal evaluation via NLP and backtest (NCI student thesis, preliminary) — [NCIRL](https://norma.ncirl.ie/8791/1/mohiburrehman.pdf)
- Copy-trading leaderboards: a CMU CHI 2024 paper (Kawai et al.) finds weak correlation between ranking and actual returns. Leaders chase rank, and low-ranked portfolios are invisible — [CMU PDF](https://www.andrew.cmu.edu/user/nicolasc/publications/Kawai-CHI24.pdf)
- Survivorship: practitioners report that losing portfolios get closed and disappear from leaderboards, and leaders hide positions while in drawdown — [Habr](https://habr.com/en/articles/808639); [Bitsgap blog](https://bitsgap.com/blog/why-copying-on-chain-whale-trades-usually-backfires)
- A widely repeated claim says about 97% of leaders were profitable but only about 44% of copiers, over 90 days, 100k+ outcomes on Binance/Bybit/MEXC. It traces to an unnamed source cited by KuCoin, which has a commercial interest. **Unverified** — [KuCoin blog](https://www.kucoin.com/blog/ph-is-crypto-copytrading-profitable-in-2026)
- "Best Telegram signals" lists with win rates are self-reported marketing — [Coincub](https://coincub.com/blog/best-crypto-signals-telegram-channels-2026/)

### Inferences
- Signal and copy-trading performance as displayed is subject to survivorship bias, selective reporting and execution lag. For copiers, slippage and later fills erode whatever edge exists.

### Gaps
- I found no peer-reviewed study of paid futures-signal Telegram groups' net returns, and no exchange-published copy-trading copier PnL distribution.

## Q6. Red flags for overfit or fake backtests in YouTube/TradingView content

### Takeaway
Common failure modes are repainting indicators, lookahead in higher-timeframe requests, fills at unrealistic prices (Heikin-Ashi or intrabar), no fees, slippage or funding, tiny samples and parameter mining. The user's own fee-sensitivity finding on 5m-30m matches the typical way these short-timeframe "90% win rate" videos fail.

### Cited Findings
- The placebo-controlled OB study shows raw win rate is misleading without a random-entry baseline: "a 54% win rate can be worse than random" — [TradingView OB statistics script](https://vn.tradingview.com/script/yFmy3VBi-Order-Block-OB-Statistics-Real-Win-Rate-vs-Random-Levels/)
- Viral MACD+200EMA "86% win rate" collapses to 31.4% and losses after costs over 16 years — [MQL5 blog](https://www.mql5.com/en/blogs/post/780027) (snippet)
- Ichimoku and Bitcoin "best numbers from 10 years of data" is an example of in-sample parameter search — [TradingView](https://in.tradingview.com/chart/BTCUSD/NDeiRzY2-BEST-Ichimoku-Numbers-for-Bitcoin-10-Years-of-Data-Says)
- Gerritsen et al. ignore transaction costs, so even academic results can overstate tradable profits — [IDEAS](https://ideas.repec.org/a/eee/finlet/v34y2020ics1544612319303770.html)
- Vendor claim that 90 trades "approach the 100-trade benchmark for statistical significance" (a false benchmark) — [TradingView](https://cn.tradingview.com/scripts/bitcoinprice/)

### Inferences
Checklist, based on general Pine Script knowledge. The official docs page (tradingview.com/pine-script-docs/concepts/repainting/) could not be fetched, so this needs verification.
- Repainting: ZigZag, pivot-based divergence and fractal indicators confirm only N bars later but get plotted at the pivot bar. `request.security()` with `lookahead=barmerge.lookahead_on` and no `[1]` offset leaks future higher-timeframe closes. Signals computed on the unconfirmed real-time bar change intrabar.
- Heikin-Ashi charts used as the strategy chart make fills happen at synthetic prices. TradingView's "fill orders using standard OHLC" option exists for this reason.
- Default strategy tester settings use zero commission and zero slippage. On perps there is also funding.
- Other flags: fewer than 100-200 trades; one asset or one period; no out-of-sample or walk-forward test; win rate quoted without average win/loss or expectancy; "magic" parameters; screenshots of the strategy tester on the asset/timeframe that happened to work (for example "the pair and the time frame you see is the winner" — [TradingView KivancOzbilgic Supertrend backtesting idea](https://in.tradingview.com/chart/XAGSGD/5itTjU4I-SuperTrend-STRATEGY-by-KivancOzbilgic-INDICES-ME-Backtesting)).

### Gaps
- The TradingView Pine docs on repainting and strategy-tester caveats were not retrievable (host blocked), so direct quotes are missing.

### What looks worth testing next (inference, ranked by evidence)
1. Multi-lookback trend ensemble (Supertrend/Donchian at 3-5 periods, no volume filter) with volatility-targeted sizing across more liquid perps, at 4h/daily — supported by Zarattini et al., Hudson & Urquhart and Gerritsen (TRB).
2. Exit variants on the existing entries: Chandelier Exit or ATR trail vs. Supertrend flip — low cost, tests a known weak spot.
3. Higher-timeframe regime filter (daily EMA200 or daily Supertrend) as multi-timeframe confirmation, implemented without lookahead.
4. Low priority (evidence weak or negative): RSI divergence, Bollinger mean reversion, SMC/order blocks, Heikin-Ashi entries, Ichimoku (redundant), grid/martingale overlays, signal or copy feeds.
