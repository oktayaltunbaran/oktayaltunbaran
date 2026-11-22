# Open-source crypto trading bot frameworks: best practices for a small Python trend-following bot

Scope note: researched 2026-11-22. In this session freqtrade.io, docs.jesse.trade and hummingbot.org could not be fetched directly (network allow-list), so Freqtrade, NautilusTrader and Passivbot facts come from the **doc source files in their GitHub repositories** (same text the websites render). Freqtrade `stable` branch reports `__version__ = "2026.10"` ([freqtrade/__init__.py](https://github.com/freqtrade/freqtrade/blob/stable/freqtrade/__init__.py)). Jesse and Hummingbot facts come from search-result excerpts of the official docs plus the Jesse GitHub README and source; these are lower-confidence and flagged as such. The equivalent website URL for a Freqtrade doc file `docs/X.md` is `https://www.freqtrade.io/en/stable/X/`.

Target bot context: single-threaded Python, ccxt sync, no numpy, Android/Termux, Telegram long-polling, SQLite, USDT perps (Binance/OKX/Bybit), 2h candles, Supertrend + EMA200 entries, exchange-side trailing stop, paper/live/backtest, unit tests.

## Freqtrade: protections, hyperopt, analysis tools, backtest realism, dry-run, Telegram, pairlists, stoploss_on_exchange, trailing, futures, FreqAI

### Takeaway
Freqtrade is the richest source of directly copyable practices: a small set of declarative "protections" (trade locks) that are also simulated in backtests, explicit documented backtest fill assumptions, a dry-run with modelled slippage, two automated bias detectors (lookahead and recursive), a liquidation buffer between stop and liquidation, and a mature Telegram command set with per-event notification levels. The Edge position-sizing module no longer exists (removed 2025.6).

### Cited Findings

**Protections (pair/global trade locks)**
- Four built-in protections: `StoplossGuard`, `MaxDrawdown`, `LowProfitPairs`, `CooldownPeriod`. Common params: `stop_duration_candles` / `stop_duration` (minutes), `lookback_period_candles` / `lookback_period`, `trade_limit`, `unlock_at` ("HH:MM"). All protection end times are rounded up to the next candle "to avoid sudden, unexpected intra-candle buys". Each protection can be configured multiple times (short-term/long-term layers) and they are evaluated in definition order — [protections.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/includes/protections.md)
- Protections are supported in backtesting/hyperopt only with `--enable-protections` — [protections.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/includes/protections.md)
- `StoplossGuard`: if `trade_limit` or more trades ended in stoploss within the lookback, stop trading for `stop_duration`. Global by default; `only_per_pair: true` per pair; `only_per_side: true` (futures) locks only the losing side so shorts can continue after a series of long stoplosses. `required_profit` default 0.0. Counts exit reasons `stop_loss`, `stoploss_on_exchange`, `trailing_stop_loss` with negative profit. Example: `lookback_period_candles: 24, trade_limit: 4, stop_duration_candles: 4` — [protections.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/includes/protections.md)
- `MaxDrawdown`: two modes — `calculation_mode: "ratios"` (default, legacy approximation from cumulative profit ratios) and `"equity"` (standard peak-to-trough on account equity; "recommended for new setups"). Example: `lookback_period_candles: 48, trade_limit: 20, stop_duration_candles: 12, max_allowed_drawdown: 0.2` — [protections.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/includes/protections.md)
- `LowProfitPairs`: locks a pair if its profit ratio over the lookback is below `required_profit` (example `lookback_period_candles: 6, trade_limit: 2, stop_duration: 60, required_profit: 0.02`); supports `only_per_side` — [protections.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/includes/protections.md)
- `CooldownPeriod`: locks a pair for `stop_duration_candles` after exit (e.g. 2 candles); pair-level only, ignores lookback — [protections.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/includes/protections.md)
- Telegram exposes `/locks` and `/unlock <pair or lock_id>`; notification types `protection_trigger` and `protection_trigger_global` — [telegram-usage.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/telegram-usage.md)

**Edge positioning**
- "The edge module has been deprecated in 2023.9 and removed in 2025.6. All functionalities of edge have been removed, and having edge configured will result in an error." — [deprecated.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/deprecated.md)

**Hyperopt and overfitting warnings**
- Uses Optuna; default sampler NSGAIIISampler; starts with 30 random epochs (marked `*`) — [hyperopt.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/hyperopt.md)
- Built-in loss functions include `SharpeHyperOptLoss(Daily)`, `SortinoHyperOptLoss(Daily)`, `MaxDrawDownHyperOptLoss`, `MaxDrawDownRelativeHyperOptLoss`, `MaxDrawDownPerPairHyperOptLoss` (optimizes the worst pair "so we prevent one or more pairs with good results from inflating the metrics"), `CalmarHyperOptLoss`, `ProfitDrawDownHyperOptLoss`, `MultiMetricHyperOptLoss` (profit, drawdown, profit factor, expectancy ratio, winrate) — [hyperopt.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/hyperopt.md)
- "Best results are usually not improving much after 500-1000 epochs"; `--early-stop` suggested at 20-30% of epochs (minimum 20); different `--random-state` runs "will most likely produce different results" — [hyperopt.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/hyperopt.md)
- Decimal search spaces are limited to 3 decimal places because "every value more precise than this will usually result in overfitted results" — [hyperopt.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/hyperopt.md)
- Hyperopt-vs-backtest mismatch checklist: indicator params placed in `populate_indicators()` computed only once for all epochs; config overriding `stoploss`, `max_open_trades`, `trailing_stop`; protections enabled in one but not the other — [hyperopt.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/hyperopt.md)
- FAQ: "12 trades is just not enough to say anything" — profitability is only visible over thousands of trades — [faq.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/faq.md)
- Hyperopt is not advised on a Raspberry Pi ("very resource-heavy") — [installation.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/installation.md)

**Lookahead-analysis and recursive-analysis**
- `lookahead-analysis` runs a baseline backtest, then re-runs a backtest per entry/exit with data sliced at that signal and compares indicator columns/signals; forces `--cache none`, market orders (late entries), infinite wallet, stake 10k, protections off, to avoid false positives — [lookahead-analysis.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/lookahead-analysis.md)
- `recursive-analysis` recomputes indicators with different `startup_candle_count` values and compares the last-row values; recommends a long timerange (at least 5000 candles). Motivation: recursive indicators (EMA-like) differ when live has fewer candles than backtest. Binance gives 1000 candles per call and freqtrade caps bulk fetch to ~5 calls, so max `startup_candle_count` ~4999 — [recursive-analysis.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/recursive-analysis.md)
- Documented lookahead mistakes: `shift(-1)`, absolute `.iloc[-1]` inside vectorized functions, full-column aggregates like `.mean()` (use rolling), `.resample('1h')` without `label='right'`, plain `.merge()` of higher timeframe (date is open date, not close date). "A negative result of each does not guarantee that there are none" — [strategy-customization.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/strategy-customization.md)

**Backtesting realism (fill assumptions)**
- Entries at open price; all orders filled at requested price with **no slippage** if within high/low; exit-signal exits at next candle open; stoploss exits exactly at stop price even if low was lower (but loss charged `2 * fees`); stoploss evaluated before ROI within a candle; "Low happens before high for stoploss"; evaluation order exit-signal > stoploss > ROI > trailing — [backtesting.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/backtesting.md)
- Trailing stop in backtest: high assumed first (adjust stop), then low tested against adjusted stop; on the entry candle the `trailing_stop_positive_offset` is assumed instead of the high — [backtesting.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/backtesting.md)
- `--timeframe-detail 5m` simulates intra-candle movement with a lower timeframe to reduce OHLC ordering bias — [backtesting.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/backtesting.md)
- Historic exchange limits/precision are unknown; current min amounts applied to historic prices can inflate minimum stake (e.g. BTC min 0.001 at 50k = $50) — [backtesting.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/backtesting.md)
- `--fee` overrides fee; "backtesting will never replace running a strategy in dry-run mode" — [backtesting.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/backtesting.md)

**Dry-run**
- Dry-run: only read-only exchange calls; wallet simulated from `dry_run_wallet` (default 1000); market orders fill on order book volume with max 5% slippage; limit orders fill when price reaches level or time out per `unfilledtimeout`; limit orders crossing price by >1% become market; with `stoploss_on_exchange`, stop price assumed filled; open orders kept across restarts assuming not filled offline — [configuration.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/configuration.md)
- Separate DBs by default: `tradesv3.dryrun.sqlite` vs `tradesv3.sqlite` — [configuration.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/configuration.md)

**stoploss_on_exchange and trailing**
- Defaults: `stoploss_on_exchange: False`, `stoploss_on_exchange_interval: 60` (seconds; "cannot do these every 5 seconds... otherwise it would get banned"), `stoploss_on_exchange_limit_ratio: 0.99`, `emergency_exit: "market"` (used if placing the stop fails) — [stoploss.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/stoploss.md)
- If the on-exchange stop is cancelled manually, the bot re-creates it on the next interval check — [stoploss.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/stoploss.md)
- With trailing + on-exchange stop, the bot cancels the old stop order and places a new higher one — [stoploss.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/stoploss.md)
- Recommends stop-market over stop-limit ("get me the hell out of here at whatever price") — [stoploss.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/stoploss.md)
- Futures `stoploss_price_type`: `"last"`, `"mark"`, `"index"`, validated at startup — [stoploss.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/stoploss.md)
- Trailing options: `trailing_stop`, `trailing_stop_positive` (e.g. 0.02), `trailing_stop_positive_offset` (e.g. 0.03; set higher than positive so first trailed stop locks profit), `trailing_only_offset_is_reached` (default False) — [stoploss.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/stoploss.md)
- Stoploss is "risk on this trade": 10% stoploss at 10x triggers on a 1% move — [stoploss.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/stoploss.md)

**Leverage / futures / liquidation**
- "You can't run 2 bots on the same account with leverage"; freqtrade assumes it is the only user of the account for liquidation math — [leverage.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/leverage.md)
- `margin_mode`: `isolated` or `cross` (cross "increases the risk of full account liquidation") — [leverage.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/leverage.md)
- `liquidation_buffer` default 0.05: `freqtrade_liquidation_price = liquidation_price ± (abs(open_rate - liquidation_price) * liquidation_buffer)`; e.g. entry 10, liq 8 → minimum stop 8.1. Liquidation fees are not tracked — [leverage.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/leverage.md)
- `liquidation_warn_ratio` default 0.2 (fraction of `100%/leverage` move): a 10x position is warned when within 2% of its liquidation stop; explicitly "a last resort notification, not a risk management tool" — [leverage.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/leverage.md)
- Funding fees are modelled; `futures_funding_rate` fallback when historical rates unavailable; dynamic funding intervals down to 1h supported since 2025.12 — [configuration.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/configuration.md); [deprecated.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/deprecated.md)

**Telegram**
- Commands: `/start`, `/pause|/stopentry` (no new entries; open trades still managed; NOT persisted across restart), `/stop`, `/reload_config`, `/show_config`, `/logs`, `/status [table]`, `/order`, `/trades`, `/count`, `/locks`, `/unlock`, `/forceexit <id>|all` (alias `/fx`, buttons if no arg), `/forcelong|/forceshort` (needs `force_entry_enable`), `/delete`, `/reload_trade` (re-sync a trade from exchange), `/cancel_open_order`, `/profit [n]`, `/profit_long|short`, `/performance`, `/balance [full]`, `/daily n` (default 7), `/weekly n` (8), `/monthly n` (6), `/stats`, `/exits`, `/entries`, `/whitelist`, `/blacklist` — [telegram-usage.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/telegram-usage.md)
- Security: `chat_id` restricts the chat; in groups, `authorized_users: ["1234567"]` limits who can command; an empty list means nobody can control the bot — [telegram-usage.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/telegram-usage.md)
- Noise control: `notification_settings` per event type with `on` / `silent` (no sound) / `off`, per exit reason (wildcard `*`), `*_fill` events off by default, `liquidation_warning`, `protection_trigger_global` — [telegram-usage.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/telegram-usage.md)
- Recommended orderly shutdown: `/stopentry` then `/forceexit all` — [faq.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/faq.md)

**Pairlists**
- Generators/filters: StaticPairList, VolumePairList, PercentChangePairList, MarketCapPairList, AgeFilter, DelistFilter, PrecisionFilter, PriceFilter, ShuffleFilter, SpreadFilter, RangeStabilityFilter, VolatilityFilter, PerformanceFilter, etc. — [pairlists.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/includes/pairlists.md)
- VolumePairList example `number_assets: 20, sort_key: "quoteVolume", min_value: 0, refresh_period: 1800` (default 1800 s); optional `lookback_days`; **not supported in backtesting** (survivorship/lookahead) — [pairlists.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/includes/pairlists.md)
- AgeFilter `min_days_listed` default 10 (new listings' price discovery); DelistFilter removes pairs scheduled for delisting (Bybit/Bitget futures, Binance); SpreadFilter `max_spread_ratio` default 0.005; PrecisionFilter "pointless for futures" — [pairlists.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/includes/pairlists.md)

**Engineering/runtime**
- `internals.process_throttle_secs` default 5 s loop; `internals.heartbeat_interval` default 60 s log heartbeat; `internals.sd_notify` systemd keep-alive; `cancel_open_orders_on_exit`; `unfilledtimeout.exit_timeout_count` triggers emergency exit after N exit-order timeouts; `exchange.enable_ws` per-stream websocket toggles — [configuration.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/configuration.md)
- Bot assumes it alone manages its trades; if capital is sold manually it tries "best-effort" re-finding exchange orders — [faq.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/faq.md)
- Data sanity warnings: "Price jump between 2 candles detected" (>30%), "Missing data fillup", "Outdated history" — [faq.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/faq.md)

**FreqAI**
- ML sandbox: self-adaptive retraining live, 10k+ features, retraining on separate thread, backtesting that emulates periodic retraining — [freqai.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/freqai.md)

### Inferences
- Highest-value cheap copies for the target bot: (1) CooldownPeriod + StoplossGuard + equity-mode MaxDrawdown implemented as SQLite "locks" with candle-rounded expiry and simulated in the backtester; (2) a periodic (e.g. 60 s) "is my exchange stop still there and correct?" check that re-creates a missing stop, with market-close fallback (`emergency_exit`); (3) a `liquidation_buffer`-style startup/entry check that the stop sits well inside the liquidation price; (4) `/stopentry` vs `/stop` distinction and `/fx` with inline buttons.
- EMA200 is a recursive indicator: the bot should verify that the number of 2h candles fetched live (e.g. 1000 candles ≈ 83 days) gives the same EMA200 as the backtester's long history — i.e. run its own "recursive analysis" unit test. Supertrend's ATR (Wilder smoothing) is recursive too.
- Since `/pause` is not persisted in Freqtrade (a documented weakness), the bot should persist pause state in SQLite.
- 2h candles + exchange-side trailing stop is exactly the case where `--timeframe-detail` matters: backtest the trailing stop on 5m/15m data inside each 2h bar.

### Gaps
- Could not render freqtrade.io directly; exchange-feature table (which exchanges support stop-market vs stop-limit on futures) is an include file not reviewed.
- Default `trailing_stop_positive_offset` semantics with on-exchange trailing orders (native exchange trailing vs bot-managed) were not confirmed; Freqtrade re-places stop orders itself rather than using native exchange trailing orders as far as the docs show.

## Jesse: backtest engine, look-ahead avoidance, optimization/walk-forward, metrics, live/paper

### Takeaway
Jesse emphasises no-look-ahead multi-timeframe backtests, a train/test split inside its Optuna optimizer plus a separate validation period, Monte Carlo robustness tests (trade-order shuffling and candle-based), a rule-significance test against random entries, and a broad metric set (Sharpe, Sortino, Calmar, Omega, Serenity, smart variants, expectancy, max underwater period).

### Cited Findings
- Features: multiple timeframes/symbols "without look-ahead bias"; Optimize mode with Optuna and Ray; Monte Carlo analysis "with trade-order shuffling and candles-based simulations to distinguish skill from luck and guard against overfitting"; built-in ML pipeline; paper and live trading with Telegram/Slack/Discord notifications; Benchmark batch backtests — [Jesse README](https://github.com/jesse-ai/jesse/blob/master/README.md)
- Rule significance test: "Jesse compares the rule against a bootstrap distribution of random entries on the same market history" before building a full strategy — [Jesse README](https://github.com/jesse-ai/jesse/blob/master/README.md)
- Optimize mode splits the given range into training (85%) and testing (15%); dashboard shows both periods' win rate/PNL; pick DNAs good on both; then validate on a held-out period (example: six months); short optimization windows invite overfitting (per search excerpt of docs, not fetched directly) — [Preventing Overfitting](https://docs.jesse.trade/docs/optimize/overfitting); [Executing optimize mode](https://docs.jesse.trade/docs/optimize/executing-the-optimize-mode)
- Research `optimize()` takes separate training and testing candles; `optimal_total` (default 200) should approximate expected trade count in training period (search excerpt) — [research/optimize](https://docs.jesse.trade/docs/research/optimize)
- Metric keys computed in source: `sharpe_ratio`, `smart_sharpe`, `sortino_ratio`, `smart_sortino`, `calmar_ratio`, `omega_ratio`, `serenity_index`, `max_drawdown`, `max_underwater_period`, `expectancy`, `expectancy_percentage`, `ratio_avg_win_loss`, `win_rate_longs/shorts`, `winning_streak`, `losing_streak`, `positive_months`, `negative_months`, `largest_losing_trade`, `avg_trades_per_week`, `fee`, `open_pl` — [jesse/services/metrics.py](https://github.com/jesse-ai/jesse/blob/master/jesse/services/metrics.py)
- Calmar defined as annual return ÷ |max drawdown| (docs example 250.55% / 17.03% = 14.71) — [Backtest results](https://docs.jesse.trade/docs/backtest/results)
- Monte Carlo overfit check: compare original metric against distribution of candle-based MC scenarios — [Jesse monte carlo docs](https://docs.jesse.trade/docs/research/monte_carlo)

### Inferences
- The target bot (no numpy) can still implement: Sharpe/Sortino on daily equity returns, Calmar, expectancy, max underwater period, longest losing streak, monthly win/loss counts — all pure-Python.
- A pure-Python trade-order shuffle Monte Carlo (resample trade returns 1000x, report 5th-percentile max DD) is cheap and directly answers "is my max DD estimate luck?".
- A walk-forward scheme (rolling train/test windows) is not explicitly confirmed in Jesse docs; Jesse's documented approach is a single train/test split plus holdout validation.

### Gaps
- Could not read docs.jesse.trade directly; Jesse's exact intrabar simulation (whether it builds higher timeframes from 1m candles in backtest) was not confirmed from a primary source in this session.
- No primary confirmation of Jesse walk-forward or k-fold cross-validation features.

## Hummingbot, OctoBot, Passivbot, NautilusTrader: risk engines, reconciliation after restart, websocket vs REST, rate limits, kill switches

### Takeaway
NautilusTrader provides the clearest model: a pre-trade RiskEngine with trading states (ACTIVE / REDUCING / HALTED) and a startup reconciliation that treats the exchange as truth and **fails closed** if positions cannot be reconciled. Passivbot contributes account-level equity hard stop, realized-loss gate, and "another instance is trading this account" detection; Hummingbot contributes a P&L kill switch and a weighted API throttler.

### Cited Findings
**NautilusTrader**
- Backtest-vs-live differences listed explicitly: venue capabilities, transport (a network failure can leave an order outcome unknown), timing/interleaving, persistence, external activity (orders created outside the node), reconciliation — [live.md](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/live.md)
- Startup reconciliation fetches order status reports, fill reports, position reports; dedups; reconciles orders → fills → positions; if positions mismatch it generates synthetic orders tagged RECONCILIATION; if still mismatched, "Startup fails, actors and strategies do not start" — [reconciliation.md](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/execution/reconciliation.md)
- "An explicit position report is authoritative... A missing report... a null quantity... are not evidence of a flat position. Missing reports do not mean flat." — [reconciliation.md](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/execution/reconciliation.md)
- Runtime checks: monitor in-flight orders exceeding a threshold, periodic open-order reconciliation, periodic position checks; `reconciliation_startup_delay_secs`, `reconciliation_lookback_mins`, `inflight_check_retries`; timed-out SUBMITTED orders rejected with `INFLIGHT_TIMEOUT` — [reconciliation.md](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/execution/reconciliation.md)
- RiskEngine validates price/qty precision, min/max quantity, `reduce_only` not increasing position, `max_notional_per_order`, submit/modify rate limits, trading state. States: ACTIVE (normal), REDUCING (only reduce-only submits, cancels, queries), HALTED (cancels/queries only; "HALTED denies released orders, including protective stops") — [execution/index.md](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/execution/index.md)
- WebSocket clients reconnect on heartbeat timeout, default 3 heartbeat intervals; separate feed-idle timeout — [live.md](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/live.md)

**Passivbot (v8)**
- Perpetual-futures bot (Python + Rust); same Rust order-planning orchestrator used in live and backtest "for speed and consistency"; evolutionary optimizer — [Passivbot README](https://github.com/enarjord/passivbot/blob/master/README.md)
- Concurrent-instance protection: detects newer Passivbot-looking open orders not emitted by the current runtime; if repeated within a rolling window, the bot stops itself — [docs/live.md](https://github.com/enarjord/passivbot/blob/master/docs/live.md)
- Exits with status 1 after sustained order-create failures; advises supervisors use restart delay and retry limit to avoid endless restart loops on auth failures — [docs/live.md](https://github.com/enarjord/passivbot/blob/master/docs/live.md)
- With websockets disabled, orders and positions are still refreshed by REST polling on the normal schedule — [docs/live.md](https://github.com/enarjord/passivbot/blob/master/docs/live.md)
- Realized-loss gate `live.max_realized_loss_pct`: `balance_peak = current_balance + (realized_pnl_cumsum_max - realized_pnl_cumsum_last)`, `balance_floor = balance_peak * (1 - pct)`, blocks lossy closes that would breach floor (default 1.0 = disabled; panic closes exempt); reconstructed from fill history, not process memory — [risk_management.md](https://github.com/enarjord/passivbot/blob/master/docs/risk_management.md)
- Equity Hard Stop Loss: same Rust evaluator in live/backtest/optimizer; signal = min(raw equity drawdown, its EMA); breach authorizes panic orders; cooldown after episode; "A local journal never preserves a past panic decision" (state is reconstructed from exchange facts) — [risk_management.md](https://github.com/enarjord/passivbot/blob/master/docs/risk_management.md)
- Wallet exposure limits and position/total exposure enforcers issue reduce-only orders — [risk_management.md](https://github.com/enarjord/passivbot/blob/master/docs/risk_management.md)

**Hummingbot** (search-excerpt level; site not fetchable)
- Kill switch stops the bot when performance crosses a positive or negative threshold (`kill_switch_mode` with `kill_switch_rate`; older `kill_switch_enabled`), using same return calc as `history`; config in `conf_client.yml` — [Kill Switch](https://hummingbot.org/global-configs/kill-switch); [Academy](https://hummingbot.org/academy-content/commands-and-configs---part-2/)
- `rate_limits_share_pct` divides an account's API rate limit between multiple bot instances — [Rate Limits Share Pct](https://hummingbot.org/global-configs/rate-limits-share-pct)
- Connector API throttler documentation exists (weighted, per-endpoint limits) — [api throttler](https://hummingbot.org/developers/connectors/api_throttler) (content not retrieved)

**OctoBot**
- Third-party guide: arm64 Linux build on Raspberry Pi, web UI on port 5001, run in `screen`, `@reboot` crontab for auto restart after power loss — [install on Raspberry Pi (third-party mirror)](https://astrolab-site.vercel.app/en/guides/octobot-installation/install-octobot-on-raspberry-pi)

### Inferences
- For the target bot, the restart procedure should mirror Nautilus: on boot, fetch positions + open orders (including stop/trailing orders) from the exchange, compare to SQLite, and refuse to trade (enter REDUCING/HALTED-like state and alert on Telegram) on any unexplained mismatch; never treat "no position returned due to error" as flat.
- Track "in-flight" orders: if a create-order call times out, query by client order id before retrying, to avoid duplicates (Nautilus' unknown-outcome rule). Using ccxt `clientOrderId`/`newClientOrderId` deterministic ids makes this feasible.
- A Hummingbot/Passivbot-style account-level kill switch (daily loss % or equity drawdown from peak → close all + halt) complements Freqtrade's per-trade protections. Note Nautilus' warning: a HALT state must not cancel or block protective stop orders.
- Passivbot's "detect a second instance" is relevant for a phone bot that might be accidentally started twice (Termux session + boot script): a PID/lock file plus checking for unknown bot-tagged orders.
- REST polling is acceptable for a 2h-candle strategy (Passivbot keeps REST fallback); websockets are not required.

### Gaps
- Nautilus `RiskEngineConfig` default submit/modify rate values not confirmed (risk doc page path not found).
- OctoBot official docs (risk settings, Telegram interface) not retrievable; only a third-party Pi guide.
- Hummingbot throttler internals not retrieved.

## Common causes of live-vs-backtest divergence and mitigations

### Takeaway
The communities converge on: look-ahead bias, recursive-indicator warm-up differences, unrealistic fills (no slippage, stop filled exactly at price), intra-candle ordering ambiguity, survivorship in dynamic pairlists, historic limits/precision unknown, funding fees, config overrides, and unknown order outcomes/external activity in live.

### Cited Findings
- Look-ahead (shift(-1), full-column stats, resample/merge of higher timeframes) → `lookahead-analysis` — [strategy-customization.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/strategy-customization.md); [lookahead-analysis.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/lookahead-analysis.md)
- Recursive indicators with limited live history → `recursive-analysis`, `startup_candle_count` — [recursive-analysis.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/recursive-analysis.md)
- No slippage, stoploss filled at exact stop price, low-before-high assumption; "you can often see more trades with the stoploss exit reason compar[ed] to Dry Run/Live" → `--timeframe-detail`, dry-run with 5% max slippage model — [backtesting.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/backtesting.md); [configuration.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/configuration.md)
- VolumePairList not usable in backtesting; historic precision/min-notional not available — [pairlists.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/includes/pairlists.md); [backtesting.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/backtesting.md)
- Config values overriding strategy (stoploss, trailing, max_open_trades); protections on in one mode only — [hyperopt.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/hyperopt.md)
- Liquidation fees not tracked → profit inaccuracies if liquidated — [leverage.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/leverage.md)
- Live-only: unknown command outcomes, interleaving, external orders — [live.md (Nautilus)](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/live.md)
- Shared code path for live and backtest (Passivbot's Rust orchestrator; Nautilus shares strategy code) as structural mitigation — [Passivbot README](https://github.com/enarjord/passivbot/blob/master/README.md); [live.md](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/live.md)

### Inferences
- For the target bot: (a) ensure signals only use closed 2h candles (drop the forming last candle from ccxt `fetch_ohlcv`); (b) backtest the exchange trailing stop with sub-candle data and charge slippage + taker fees on stop exits; (c) include funding fees in the backtester; (d) use one signal function shared by paper/live/backtest; (e) keep a "paper vs live" shadow log to measure real slippage and feed it back into the backtest.

### Gaps
- Did not collect quantitative community reports (e.g. typical slippage % on stop-market exits for Binance/OKX/Bybit perps).

## Telegram interface patterns and security

### Takeaway
Freqtrade's pattern: bind to a single `chat_id`, optionally whitelist `authorized_users`, separate "pause entries" from "stop", provide quick emergency exit (`/fx` with inline buttons), granular notification levels, and read-only metrics commands.

### Cited Findings
- `chat_id` + `authorized_users` (empty = nobody may control) — [telegram-usage.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/telegram-usage.md)
- `/forceexit` without args shows buttons per open trade; `/fx` alias "faster to type in emergency situations"; `/forcelong` disabled unless `force_entry_enable: true` — [telegram-usage.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/telegram-usage.md)
- Custom keyboard of command shortcut buttons supported — [telegram-usage.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/telegram-usage.md)
- Notification levels on/silent/off; fill events separate from placement events — [telegram-usage.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/telegram-usage.md)
- `/balance` RPC can trigger a balance refresh at most once per hour — [faq.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/faq.md)
- `/reload_trade` re-syncs a trade from the exchange — [telegram-usage.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/telegram-usage.md)

### Inferences
- Add confirmation step (inline "Yes/No" callback with short expiry) for destructive commands (`/fx all`, live-mode switch), and drop updates from any non-whitelisted user id silently. Freqtrade's docs did not describe a confirm dialog; this is an extrapolation.
- Cache expensive calls (balance) to avoid exchange rate-limit hits triggered by Telegram spam.

### Gaps
- No primary source found on Telegram API rate-limit handling by these bots (e.g. 429 retry_after handling, ~30 msg/s global limit).

## Low-resource devices and reliability (watchdogs, heartbeats, state persistence)

### Takeaway
Run the live bot on the small device, do research/optimization elsewhere; use heartbeats, supervisor restarts with backoff, persistent DB state, and exchange-truth reconciliation on restart.

### Cited Findings
- Freqtrade on Raspberry Pi: tested on Pi 3 with Raspberry Pi OS Lite; recommends arm64; installation "can take multiple hours", Docker image recommended; do not hyperopt on a Pi; 64-bit Python recommended due to memory limits — [installation.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/installation.md)
- `heartbeat_interval` 60 s, `sd_notify` systemd watchdog keep-alive, `process_throttle_secs` 5 s — [configuration.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/configuration.md)
- `/pause` not persisted across restart (documented limitation) — [telegram-usage.md](https://github.com/freqtrade/freqtrade/blob/stable/docs/telegram-usage.md)
- Passivbot: exit code 1 on sustained failures; supervisor should use restart delay and retry limit; self-healing short-lived file locks with stale cleanup for shared OHLCV cache — [docs/live.md](https://github.com/enarjord/passivbot/blob/master/docs/live.md); [README](https://github.com/enarjord/passivbot/blob/master/README.md)
- Passivbot HSL state reconstructed from exchange fill history rather than a local journal — [risk_management.md](https://github.com/enarjord/passivbot/blob/master/docs/risk_management.md)
- OctoBot Pi guide: `screen` + `@reboot` crontab for auto restart after power outage (third-party) — [guide](https://astrolab-site.vercel.app/en/guides/octobot-installation/install-octobot-on-raspberry-pi)
- Nautilus heartbeat timeout default = 3 heartbeat intervals for websocket reconnect — [live.md](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/live.md)

### Inferences
- Android/Termux equivalents: `termux-wake-lock`, Termux:Boot for start-on-boot, a wrapper loop with exponential backoff and max retries, and an external dead-man's switch (e.g. bot sends heartbeat; if a second watcher—or a Telegram scheduled check—sees no heartbeat for N minutes it alerts). Because the stop/trailing stop lives on the exchange, a phone crash leaves positions protected; this is the main reason to keep exchange-side stops.
- Derive risk state (daily loss, peak equity) from exchange fills/balance on restart rather than only SQLite, as Passivbot does.
- None of the researched projects officially document Android/Termux support (not found).

### Gaps
- No official Android/Termux guidance found in any of the frameworks' docs.
- No primary data on memory/CPU footprints of these frameworks on Pi.
