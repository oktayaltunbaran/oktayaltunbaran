# Exchange APIs (Binance USDⓈ-M, Bybit V5 linear, OKX V5 SWAP) and Telegram bot UX/security for a small trend-following bot

Research date: 2026-11-22. **Method caveat:** In this session the official doc hosts (developers.binance.com, bybit-exchange.github.io, www.okx.com) could NOT be fetched directly (DNS blocked in the sandbox). Findings below come from web-search summaries of those official pages, plus third-party SDK docs. Items marked **[UNVERIFIED – prior knowledge]** come from the researcher's background knowledge of the APIs (pre-2026), not from a source checked in this session; the report writer should present them as "to be confirmed against live docs / exchangeInfo".

---

## 1. Order types: stops, trailing, position-attached TP/SL, amend vs cancel+replace

### Takeaway
Binance moved all conditional orders (STOP_MARKET, TAKE_PROFIT_MARKET, TRAILING_STOP_MARKET, etc.) to a separate Algo Service in early Dec 2025 and offers no modify for them, so cancel+replace (ideally place-new-then-cancel-old) is the only way to move a stop. Bybit and OKX both allow amending a conditional order's trigger price in place, and both offer position-level TP/SL (Bybit `/v5/position/trading-stop`, OKX `attachAlgoOrds`/conditional with close-position), which removes the "two stops at once" window.

### Cited Findings
**Binance USDⓈ-M**
- Conditional orders migrated to a new "Algo Service"; old `/fapi/v1/order` returns error -4120 for conditional types and points users to the Algo Order API. Effective date conflicts between sources: 2025-12-02 per an SDK PR vs 2025-12-09 per a Nautilus Trader bug report and a MultiCharts forum thread — [sieblyio/binance PR #604](https://github.com/sieblyio/binance/pull/604); [nautilus_trader issue #3287](https://github.com/nautechsystems/nautilus_trader/issues/3287); [MultiCharts forum](https://www.multicharts.com/discussion/viewtopic.php?p=151301)
- New Algo Order endpoint (algoType CONDITIONAL) supports STOP_MARKET, TAKE_PROFIT_MARKET, STOP, TAKE_PROFIT, TRAILING_STOP_MARKET; separate Cancel Algo Order / Query Algo Order endpoints exist; algo order status changes are pushed via a new `ALGO_UPDATE` user-data event (status NEW until triggered) — [Binance New Algo Order docs](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Algo-Order); [Binance Event Algo Order Update](https://developers.binance.com/legacy-docs/derivatives/portfolio-margin/user-data-streams/Event-Algo-Order-Update)
- USDⓈ-M "Modify Order" currently supports only LIMIT orders ("Currently only LIMIT order modification is supported, modified orders will be reordered in the match queue") — so no amend of stop trigger price — [Binance Modify Order](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Modify-Order); TradingView likewise says Binance orders cannot be modified, must cancel and re-place — [TradingView support](https://in.tradingview.com/support/solutions/43000705044-why-can-t-orders-be-modified/)
- A March 2026 report says Binance USDT-M UI would gradually upgrade "Take Profit/Stop Loss" orders into "Conditional Orders" from 2026-03-25 (UI change, separate from the API migration) — search summary of [Binance Square / MEXC news](https://www.mexc.com/news/980129) (weakly sourced)
- Placing a stop whose trigger is already crossed returns -2021 "Order would immediately trigger" — search summary referencing Binance docs (treat as [UNVERIFIED – prior knowledge], consistent with long-standing behaviour)
- **[UNVERIFIED – prior knowledge]** Algo orders keep the classic params: `workingType` (MARK_PRICE / CONTRACT_PRICE, default CONTRACT_PRICE), `priceProtect` (TRUE/FALSE; blocks trigger when mark vs last deviates beyond the symbol's `triggerProtect` threshold), `closePosition=true` (closes whole position; cannot be combined with `quantity`/`reduceOnly`), `reduceOnly`, and for TRAILING_STOP_MARKET `callbackRate` with min 0.1 and max 10 (percent; older docs said max 5) plus optional `activatePrice`. Binance has no native OCO for futures; TP and SL are independent orders (closePosition stops are cancelled when the position closes).

**Bybit V5 (linear)**
- `POST /v5/position/trading-stop` sets TP, SL or trailing stop on the position; `trailingStop` is a price distance (0 cancels it; USDT perpetual only), `activePrice` = price at which trailing begins; `tpslMode` Full (whole position, only Market SL) or Partial (needs `tpSize`/`slSize`); also `tpTriggerBy`/`slTriggerBy` (MarkPrice/LastPrice/IndexPrice) and `positionIdx` required — [Bybit Set Trading Stop](https://bybit-exchange.github.io/docs/v5/position/trading-stop); [Bybit TP/SL mode](https://bybit-exchange.github.io/docs/v5/position/tpsl-mode)
- `POST /v5/order/amend`: only unfilled/partially filled orders can be modified; for conditional orders `triggerPrice` can be amended (must stay on the correct side of market); amendable fields include `triggerPrice`, `triggerBy`, `takeProfit`, `stopLoss`, `slLimitPrice`. Batch amend does NOT support conditional orders — [Bybit Amend Order](https://bybit-exchange.github.io/docs/v5/order/amend-order); [Bybit Batch Amend](https://bybit-exchange.github.io/docs/v5/order/batch-amend)
- Practical implication: calling trading-stop again with a new `stopLoss` simply moves the position SL (one request, no gap) — inferred from the endpoint semantics above.

**OKX V5 (SWAP)**
- Algo `ordType` values: conditional, oco, trigger, move_order_stop (trailing), iceberg, twap (plus chase, smart iceberg in newer SDKs) — [aiviaio/okex Go SDK docs](https://pkg.go.dev/github.com/aiviaio/okex@v1.4.65/requests/rest/trade); [Nautilus OKXAlgoOrderType](https://nautilustrader.io/docs/rust-api-latest/nautilus_okx/common/enums/enum.OKXAlgoOrderType.html)
- `POST /api/v5/trade/amend-algos` exists; for conditional SL orders (including close-position `closeFraction` stops) the stop is changed via `newSlTriggerPx` (and `newSlOrdPx`, -1 = market), not `newTriggerPx` — [Nautilus OKXAmendAlgoOrderRequest](https://nautilustrader.io/docs/rust-api-latest/nautilus_okx/http/models/struct.OKXAmendAlgoOrderRequest.html)
- `attachAlgoOrds` on place-order attaches TP/SL to the entry order — [Nautilus OKXAttachAlgoOrdRequest](https://nautilustrader.io/docs/rust-api-latest/nautilus_okx/http/models/struct.OKXAttachAlgoOrdRequest.html)
- **[UNVERIFIED – prior knowledge]** amend-algos is limited to SWAP/FUTURES conditional and trigger orders (not move_order_stop); `slTriggerPxType` = last/index/mark; move_order_stop `callbackRatio` roughly 0.001–0.1 (0.1%–10%) or `callbackSpread`; OKX supports native OCO (`ordType=oco`).

### Inferences
- For Binance, "place new stop, then cancel old" is the safest ordering (never naked), and with `reduceOnly`/`closePosition` a double trigger cannot open a reverse position. Because `ALGO_UPDATE` is a new event and the order IDs are `algoId`, ccxt must be on a version that supports the algo endpoints (ccxt added routing after the Dec 2025 migration; verify version).
- For Bybit/OKX, prefer amend (one call, no transient double stop, fewer rate-limit hits). Bybit position-level SL via trading-stop is the simplest and survives order-ID bookkeeping errors.
- Native trailing stops do not match a "move stop once per closed 2h bar" rule (they trail tick by tick), so keep the bar-based manual move; native trailing could serve as a disaster backstop only.
- Use mark price triggers (Binance `workingType=MARK_PRICE`, Bybit `slTriggerBy=MarkPrice`, OKX `slTriggerPxType=mark`) to avoid wicks on last price; liquidation is also mark-based.

### Gaps
- Exact Binance migration date (12-02 vs 12-09) and whether `priceProtect`/`closePosition` behaviour changed on the algo endpoint — official changelog not fetchable here.
- Current Binance callbackRate bounds and OKX callbackRatio bounds not verified in 2025-26 docs.
- Whether OKX amend-algos accepts move_order_stop.

---

## 2. Fees and funding

### Takeaway
Regular-tier perpetual fees are ~0.02% maker / 0.05% taker on Binance and OKX, 0.02% / 0.055% on Bybit; a market-in, stop-out round trip costs ~0.10–0.11% of notional (~0.15 USDT on a 150 USDT position). Funding is nominally 8h but Binance (and others) dynamically shorten to 4h/1h for capped symbols.

### Cited Findings
- Binance USDⓈ-M regular: maker 0.02%, taker 0.05%; 10% discount when paying with BNB held in the USDⓈ-M futures wallet (if BNB insufficient, fee charged in USDT without discount); regular tier = <$15M 30-day volume or <25 BNB — [Binance Futures fee FAQ](https://www.binance.com/support/faq/360033544231); [Finder](https://www.finder.com/binance-futures-fees)
- Binance Taker Program discounts stack on top of BNB discount and VIP rates (2025-08-12 update) — [Binance announcement 2025-08-12](https://www.binance.com/support/announcement/detail/bec831262e4b4a49b021e6f4030921be)
- Bybit perpetuals: 0.02% maker / 0.055% taker for non-VIP; first VIP tier needs ~$100k assets; rates may vary by region — [Analytics Insight OKX vs Bybit](https://www.analyticsinsight.net/cryptocurrency-analytics-insight/okx-vs-bybit-fees-features-crypto-trading-options-compared); [crypto.news fee comparison](https://crypto.news/maker-and-taker-fees-compared-across-8-crypto-exchanges/). One GitHub page claims 0.01%/0.06% — conflicting, likely unreliable.
- OKX regular: 0.02% maker / 0.05% taker futures; VIP1 from 50,000 USDT assets — [OKX Learn: crypto futures fees compared](https://www.okx.com/ua/learn/crypto-futures-fees-compared)
- Binance funding: default every 8h; interval auto-shortens (8h/4h → 1h) when previous settlement hits cap/floor; symbol-specific caps e.g. ±2.00% (MYXUSDT, MUSDT, ERAUSDT...) and ±0.75% (XTZUSDT) when 4h was restored on 2025-07-22; UUSD reverts from 1h to 4h after 36 hourly periods with |rate| ≤0.002% (from 2025-09-01) — [Binance funding frequency update 2025-05-02](https://www.binance.com/en/support/announcement/3243c81a35bd4f0c86a37315c3dc96cc); [crypto.news 2025-07-22](https://crypto.news/binance-resumes-funding-rate-settlement-frequency-for-these-five-perpetual-contracts-on-july-22/); [Binance funding FAQ](https://www.binance.com/fr/support/faq/360033525031)
- Binance updated its funding-rate formula and mark-price calculation (announcement 2025-09-18) — [Binance announcement](https://www.binance.com/en-AE/support/announcement/detail/c00588a7e8504b3eb28d02a2da00530b)
- Search summary claimed BTCUSDT moved to 1h funding after hitting -0.3% in April 2025 — **suspect / unverified** (could not confirm in primary source; treat as doubtful).
- **[UNVERIFIED – prior knowledge]** Bybit and OKX also use 8h default with per-symbol 4h/2h/1h intervals for many altcoins; read `fundingInterval` (Bybit instruments-info) / `fundingTime`/`nextFundingTime` (OKX) / `GET /fapi/v1/fundingInfo` (Binance) per symbol at runtime. Referral programs typically give a fee rebate/discount (often 10–20%) for a limited period.

### Inferences
- At 30 USDT equity, fees and funding are small in absolute USDT but large relative to expected edge: a 0.1% round trip at 5x is 0.5% of equity per trade. Since entries are market (taker) and stops are market, maker rebates are irrelevant; BNB discount on Binance saves ~10%.
- Holding trend positions for days on 1h-funding altcoins can cost more than fees; prefer majors with 8h funding and check interval before entry.

### Gaps
- Official 2026 fee pages for Bybit/OKX not fetched; regional (Turkey) fee differences unknown.

---

## 3. Minimum notional / quantity, filters, leverage brackets

### Takeaway
Minimums must be read live from `exchangeInfo` / instruments-info; with 30 USDT at 5x (≤150 USDT notional) BTC on Binance is likely unusable if its min notional is still 100 USDT, while OKX's small contract sizes are friendliest to micro accounts.

### Cited Findings
- Binance MIN_NOTIONAL filter = price × quantity (mark price used for market orders); Binance says it adjusts thresholds "from time to time without prior announcement" — [Binance New Minimum Order Notional rule](https://www.binance.com/en/support/announcement/76719bbaeeb847bbac4daa2906fcdcc0); [Binance common definitions](https://developers.binance.com/docs/derivatives/usds-margined-futures/common-definition); per-symbol values at [Binance futures trading rules](https://www.binance.com/en/futures/trading-rules/)
- **[UNVERIFIED – prior knowledge]** Binance USDⓈ-M MIN_NOTIONAL: BTCUSDT 100 USDT, ETHUSDT 20 USDT, most others 5 USDT; filters PRICE_FILTER (tickSize), LOT_SIZE / MARKET_LOT_SIZE (stepSize, minQty, maxQty), MAX_NUM_ORDERS, MAX_NUM_ALGO_ORDERS, PERCENT_PRICE. Leverage/maintenance brackets via `GET /fapi/v1/leverageBracket`; lowest bracket allows max leverage (e.g. 125x BTC) and lowest maintenance margin (e.g. 0.4% BTC) — small positions always sit in tier 1.
- **[UNVERIFIED – prior knowledge]** Bybit linear: `minOrderQty`, `qtyStep`, `minNotionalValue` (~5 USDT) in `/v5/market/instruments-info`; BTCUSDT minOrderQty 0.001 BTC. OKX SWAP: `ctVal` (BTC-USDT-SWAP 0.01 BTC per contract), `lotSz`/`minSz` (0.01 contracts → 0.0001 BTC), `tickSz` in `/api/v5/public/instruments`; risk tiers via `/api/v5/public/position-tiers`.

### Inferences
- Sizing by fixed-risk (e.g. 1% of 30 USDT = 0.3 USDT risk) with a wide trend stop often yields notional below minimums; bot must round down to step size and skip trades below min notional/qty rather than inflate size. Isolated 5x with tier-1 MMR means liquidation is ~19% away from entry for longs — stop should always be far inside that.

### Gaps
- Current 2026 Binance BTCUSDT/ETHUSDT min notional not confirmed from a primary source in this session.

---

## 4. Rate limits, polling, websockets, clock sync

### Takeaway
A 2h-bar bot polling every 30–60 s uses a tiny fraction of limits on all three exchanges; websockets add complexity and are fragile on a mobile connection — REST polling plus exchange-side stops is adequate, but reconcile state after any reconnect.

### Cited Findings
- Binance USDⓈ-M: default 2,400 request weight/min per IP, 1,200 orders/min per account, plus 300 orders/10 s — [Binance Rate Limits FAQ](https://www.binance.com/en/support/faq/281596e222414cdd9051664ea621cdc3); [Binance general info](https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info)
- Bybit V5 rate limits are per-endpoint/per-UID; demo accounts get default limits that cannot be upgraded — [Bybit rate limit](https://bybit-exchange.github.io/docs/v5/rate-limit); [Bybit demo](https://bybit-exchange.github.io/docs/v5/demo)
- OKX algo order endpoints rate-limited per instrument/UID (third-party mirror shows place-algo "3 requests per 10 seconds" for a different venue — not OKX; OKX value unverified) — [apidocliquidity mirror](https://apidocliquidity.readme.io/reference/place-algo-order)
- **[UNVERIFIED – prior knowledge]** Binance listenKey (user data stream) valid 60 min, extend with PUT every ~30 min, connection dropped at 24 h; 418/429 responses escalate to IP bans (2 min → 3 days). `recvWindow` default 5000 ms (max 60000); timestamps must be within window of server time — call `GET /fapi/v1/time` (ccxt `load_time_difference()` / `adjustForTimeDifference: true`). Bybit: `X-BAPI-RECV-WINDOW` default 5000 ms. OKX: request timestamp must be within 30 s of server time; `expTime` header optional. Bybit/OKX private WS need ping every 20–30 s.

### Inferences
- On Android with changing IP, IP-based weight counters reset per IP; not a concern at this volume. Clock drift on phones is real — enable ccxt time-difference adjustment and widen recvWindow (e.g. 10 s) rather than rely on phone NTP.
- Websockets on mobile: Doze mode, network handovers and NAT timeouts break long-lived sockets; Binance algo fills now arrive on `ALGO_UPDATE`, so a WS client would need updating anyway. Recommended: poll positions/open algo orders every 30–60 s and on each bar close; treat REST as source of truth.

### Gaps
- Exact OKX/Bybit per-endpoint limits for 2026 not fetched.

---

## 5. API key security, IP whitelisting, expiry, sub-accounts

### Takeaway
All three exchanges penalise keys without IP binding: Binance deletes unrestricted keys after 30 days of inactivity, Bybit expires them after ~90 days regardless of use, OKX deletes trade-enabled unbound keys after 14 days of inactivity. With a phone on a changing mobile IP, IP whitelisting is impossible unless traffic goes via a static-IP proxy/VPS.

### Cited Findings
- Binance: 90-day rule for unrestricted spot/margin keys (2021) no longer applies since 2023-10-24; since Dec 2022 keys without IP whitelist that are inactive 30 days are auto-deleted; Binance strongly recommends IP whitelisting on all keys — [Binance API permission rules announcement (2021-07-26, updated 2023-10-24)](https://www.binance.com/en/support/announcement/11e4c2f44e7a47b9b5fc0e479c0b256f); [TradersPost blog](https://blog.traderspost.io/article/managing-binance-api-key-expiry-on-traderspost); [Binance API FAQ](https://www.binance.com/en/support/faq/360004492232)
- Bybit: keys without IP restriction expire after 90 days (some say 3 months/91 days) and must be renewed — [Fireblocks](https://support.fireblocks.io/hc/en-us/articles/5138770767004); [Altrady](https://support.altrady.com/en/article/how-to-add-an-ip-whitelist-to-your-api-keys-1jbbzbw); [Blockpit](https://intercom.help/blockpit/en/articles/12136950-how-to-import-data-via-bybit-api-key) (third-party; official doc not fetched)
- OKX: since Jan 2023, keys with trade/withdraw permission not bound to IP are auto-deleted after 14 days of inactivity; up to 20 IPs per key — [OKX API FAQ](https://www.okx.com/en-gb/help/api-faq); [OKX press release via FinTech Futures](https://www.fintechfutures.com/press-releases/okx-announces-comprehensive-api-key-security-protection-features-further-enhances-user-protection-against-external-threats)
- **[UNVERIFIED – prior knowledge]** Binance requires IP restriction to enable the withdrawal permission; futures permission requires futures account opened and can be on unrestricted keys. All three support sub-accounts (Binance sub-accounts need ≥ some account level/VIP0 enablement for regular users; Bybit and OKX allow sub-accounts freely) and withdrawal address whitelists; OKX keys have a passphrase and trade/read/withdraw scopes.

### Inferences
- Minimum safe setup: trade-only key (no withdraw, no transfer), dedicated sub-account funded with only the 30 USDT, withdrawal whitelist + 2FA on main account. Note expiry/deletion rules in the bot: alert via Telegram on auth errors (Binance -2014/-2015, Bybit 10003/10004, OKX 50111/50113) and a calendar reminder for Bybit 90-day renewal.
- Option: route API calls through a cheap VPS or static-IP proxy so keys can be IP-bound (removes expiry and greatly reduces theft impact). Storing keys on a phone (Termux etc.) — use Android Keystore/encrypted file, never in source or Telegram messages.

### Gaps
- Official Bybit doc wording on the 90-day rule; whether Binance's 30-day rule still stands in 2026.

---

## 6. Regional availability / regulation for users in Turkey

### Takeaway
Under Law No. 7518 (in force 2024-07-02) crypto asset service providers need SPK (CMB) authorisation; Binance TR, Bybit TR (Bybit Kripto Varlık Alım Satım Platformu A.Ş.) and OKX TR appear on SPK's list of entities that are operating while applying, which is not a licence, and local TR platforms offer no futures/leverage. Whether a Turkish resident may use the global offshore futures products is legally unclear and sources conflict.

### Cited Findings
- Law 7518, effective 2024-07-02, brought crypto asset service providers under SPK supervision with licensing and capital requirements (50 million TL cited) — [Pega Hukuk](https://pegahukuk.com/is-crypto-legal-in-turkey/)
- SPK list dated 2026-11-09 shows 39 platforms; being listed is not authorisation; Binance TR, Bybit TR and OKX TR listed as "on SPK operating list (not authorised)" — [VASP Tracker Türkiye](https://vasptracker.com/en/tr/); [Datawallet](https://www.datawallet.com/crypto/best-crypto-exchanges-turkey). Register entry numbers differ between sources — [cesayazilim list](https://www.cesayazilim.com/en/blog/blockchain/crypto-intermediary-institutions-list)
- Council of State (Danıştay) 2025-05-28: no ban on buying/selling crypto, but providing crypto services without authorisation is a crime — [Pega Hukuk](https://pegahukuk.com/is-crypto-legal-in-turkey/)
- Crypto payments banned by CBRT since 2021-04-30 — [Pega Hukuk](https://pegahukuk.com/is-crypto-legal-in-turkey/)
- Bybit TR and OKX TR offer no futures; local Turkish exchanges do not provide leverage/derivatives — [Datawallet](https://www.datawallet.com/crypto/best-crypto-exchanges-turkey); [copytradeinsider](https://www.copytradeinsider.com/blog/best-crypto-exchanges-turkey-2026/)
- Offshore platforms reportedly still offer derivatives to Turkish accounts (via P2P TRY rather than direct lira rails); foreign platforms cannot market directly to Turkish users; SPK has blocked 100+ foreign sites — [copytradeinsider](https://www.copytradeinsider.com/blog/best-crypto-exchanges-turkey-2026/); [Bitget Academy](https://www.bitget.com/academy/are-there-any-specific-regulations-for-binance-users-in-turkey-2026-comprehensive-guide) (low-quality / interested sources)
- Bybit's excluded-jurisdiction list (as of 2026-06-26) does not name Turkey; Binance EEA services ended 2026-07-01 — [Kraken Learn / Coin Bureau summaries](https://coinbureau.com/review/bybit-vs-okx)

### Inferences
- Practical risk: a Turkish-KYC'd user may be steered to the TR entity (spot only), and access to global futures can change with little notice. The bot must handle "account restricted" errors gracefully. User should confirm their own account's futures eligibility and seek local legal/tax advice.

### Gaps
- No primary SPK or exchange statement found on Turkish residents' eligibility for global Binance/Bybit/OKX futures in 2025-26. MASAK transfer rules not researched.

---

## 7. Telegram Bot API UX and security

### Takeaway
Stay well under 1 msg/s per chat (20/min in groups); use inline keyboards with edited "status" messages instead of message floods, restrict all handlers to the owner's chat_id, require two-step confirmation with expiring/nonce'd callback data for any order action, and treat the bot token as a secret.

### Cited Findings
- Official limits: avoid >1 message/s in a single chat (short bursts tolerated, then 429); groups ≤20 messages/min; ~30 msg/s applies to bulk notifications to many users; paid broadcasts allow up to 1000 msg/s — [Telegram Bots FAQ](https://core.telegram.org/bots/faq); [grammY flood guide](https://grammy.dev/advanced/flood); [python-telegram-bot wiki](https://github.com/python-telegram-bot/python-telegram-bot/wiki/Avoiding-flood-limits)
- 429 responses include `retry_after`; libraries provide rate limiters (PTB AIORateLimiter, grammY auto-retry) — [grammY flood guide](https://grammy.dev/advanced/flood)
- **[UNVERIFIED – prior knowledge, core.telegram.org/bots/api]** `callback_data` max 64 bytes; every callback query must be answered with `answerCallbackQuery` (otherwise the client shows a spinner); `editMessageText`/`editMessageReplyMarkup` to update one status message; long polling via `getUpdates` with `timeout` (e.g. 30–50 s) and `offset = last_update_id+1` to acknowledge; getUpdates and webhook are mutually exclusive (409 conflict if two pollers run); updates are kept on Telegram servers up to 24 h; bot token can be revoked/regenerated via @BotFather `/revoke`; `message.from.id`/`chat.id` used for allow-listing; `allowed_updates` to limit update types; `drop_pending_updates` on start to avoid executing stale commands.

### Inferences
- Security: whitelist the single owner `chat_id` and ignore all others (log attempts); never echo API keys; keep token in an env/encrypted file; set bot privacy and don't add it to groups.
- Stale/duplicate callbacks: embed an action nonce + timestamp in callback_data (≤64 bytes), store pending actions server-side with a short TTL (e.g. 60 s), reject reused or expired nonces, and remove the keyboard (edit message) after one use. On startup, skip updates older than N minutes so a phone reconnect doesn't replay "close position" taps.
- 2-step confirmation pattern: "/close BTC" → message with [Confirm] [Cancel] showing current price/size → on confirm, re-check position state before acting → edit message to result.
- Notification hygiene: one edited "dashboard" message per position plus discrete alerts for fills, stop moves, errors; batch/debounce non-critical messages.
- Notable open-source UX references: Freqtrade's Telegram module (commands /status, /profit, /forceexit with inline confirm, /stopentry, chat_id authorisation) and Hummingbot's Telegram interface — [UNVERIFIED – prior knowledge; see freqtrade.io docs "Telegram usage"].

### Gaps
- Could not fetch the Bot API reference to confirm parameter limits in the latest (2026) version.

---

## 8. Demo / testnet environments

### Takeaway
All three offer API-accessible paper trading: Binance Futures demo (demo-fapi.binance.com), Bybit demo trading (api-demo.bybit.com, reduced endpoint set), OKX demo (same host with `x-simulated-trading: 1` header and separate demo keys). They are good for testing order flow (including Binance's new algo endpoints) but not for realistic fills/funding.

### Cited Findings
- Binance futures demo REST `https://demo-fapi.binance.com`, WS `demo-fstream.binance.com`; API-only; separate demo API key from the Futures Demo Trading page; "most of the endpoints can be used"; spot testnet is `testnet.binance.vision` — [Binance USDⓈ-M general info](https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info); [Binance derivatives quick start](https://developers.binance.com/docs/derivatives/quick-start)
- Bybit demo: REST `api-demo.bybit.com`; not every API available (e.g. closed-pnl returns error 10032 "Demo trading are not supported"); demo WS only private streams, public data from mainnet; no WS trading; orders retained 7 days; default rate limits, not upgradable; balance starts at zero, top up via demo-apply-money; demo keys created from mainnet account; account refreshed/cleared after 30 days inactive — [Bybit Demo Trading Service](https://bybit-exchange.github.io/docs/v5/demo); [pybit issue #353](https://github.com/bybit-exchange/pybit/issues/353); [Bybit Demo FAQ](https://www.bybit.com/zh-TW/help-center/article/FAQ-Demo-Trading)
- **[UNVERIFIED – prior knowledge]** OKX demo trading uses the production REST host with header `x-simulated-trading: 1`, demo-specific API keys, and WS `wspap.okx.com`; ccxt supports `set_sandbox_mode(True)` for Binance (demo), Bybit (testnet; demo via `enable_demo_trading`), OKX (demo header).

### Inferences
- Run the full stop-move cycle (place new algo stop → cancel old → verify) on Binance demo after any ccxt upgrade, since the Dec 2025 migration broke many libraries. Demo liquidity/slippage and funding are not representative; validate minimum-notional handling on mainnet with the smallest size.

### Gaps
- Bybit's separate legacy testnet (api-testnet.bybit.com) status in 2026 and OKX demo limitations not verified.
