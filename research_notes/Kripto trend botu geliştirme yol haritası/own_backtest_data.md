# Own backtest data (bot's own engine, Binance USDT-M archive, 2h, Supertrend(10,3)+EMA200, stop ST-1ATR trailed, exit on ST flip)

Costs: 0.06% taker/side + 0.05% slippage, pessimistic intrabar stop. No funding modeled. Period Nov 2022-Nov 2026, 10 coins.

- All trades n=826: mean +0.203R, std 1.79R, SE 0.062, t=3.26, 95% CI [+0.081, +0.325]
- Out-of-sample (Jul 2025-Nov 2026) n=345: mean +0.254R, std 1.78R, t=2.64, 95% CI [+0.066, +0.442]
- Win rate 35.1%; median R -0.31; best +17.6R; worst -1.08R
- Concentration: top 5% of trades contribute +255.5R of total +167.8R
- Holding time: median 63 h, mean 85 h (funding exposure ~10.7 funding intervals/trade)
- Longest losing streak in sequence: 18; streaks >=6: 31, >=8: 17
- Per-coin total R: BTC +16.9 (n=139), ETH +13.7 (n=105), SOL +39.8 (n=56), BNB +32.7 (n=128), XRP +13.4 (n=89), DOGE +11.7 (n=63), ADA +8.8 (n=46), AVAX +8.2 (n=52), LINK +9.6 (n=55), LTC +13.1 (n=93)

## Monte Carlo (bootstrap of all trade R-multiples, 150 trades ~ 1 year with 9 coins/3 slots, $30 start, $20 floor guard)

| risk/trade | P(hit $20 floor) | median maxDD | 95th pct maxDD | median end | 5th pct end |
|---|---|---|---|---|---|
| 0.5 USDT | 1.4% | 13% | 29% | 44.6 | 28.1 |
| 0.75 USDT | 6.3% | 18% | 37% | 51.4 | 19.9 |
| 1.0 USDT | 12.6% | 23% | 42% | 58.2 | 19.6 |
| 1.5 USDT | 25.2% | 31% | 50% | 68.0 | 19.1 |
| 2.0 USDT | 35.3% | 35% | 56% | 71.7 | 18.7 |

- Trades needed for mean>0 at 95% given mean 0.20R and std 1.79R: ~299; for live verification of half the effect (+0.10R): ~1196

## Other own findings already established
- Timeframe sweep (2y 5m data, same rules): 5m -0.24R (0/10 coins), 15m -0.07R, 30m -0.05R, 1h +0.02R, 2h +0.23R (8/10), 4h +0.27R but only 0.3 trades/month/coin. Zero fees on 5m still -0.11R.
- Filters that made results WORSE in-sample: daily-trend (EMA600 on 2h) filter, ADX>=20, MACD confluence, partial TP at 1R/2R/3R, fixed 2R/3R targets, stop exactly at ST line (intrabar).
- Funding filter (skip if |funding| against side > 0.05%/8h): roughly neutral to slightly positive.
- Old pullback-to-EMA21 strategy: -0.12R IS, -0.08R OOS.
- Portfolio sim $30: risk 1.5 single position hit $20 floor after 19 trades in one path; 9 coins risk 1.0 max 3 pos: 4y 30->133 (maxDD 25%), OOS 30->84 (maxDD 19%).
