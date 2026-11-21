"""Basit ama durust geriye donuk test (yalnizca TEKNIK kurallar).

Varsayimlar (bilerek kotumser):
* Sinyal mum KAPANISINDA olusur, giris bir SONRAKI mumun ACILISINDAN + kayma.
* Ayni mumda hem SL hem TP'ye degildiyse SL kabul edilir.
* Breakeven tetiklendigi mumda degil, bir sonraki mumdan itibaren gecerlidir.
* Komisyon her iki bacakta FEE_RATE, kayma SLIPPAGE_PCT.
* Turev filtresi (funding/OI/baz) gecmis veride uygulanmaz -> canli davranis
  bundan daha secici olur.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import List, Optional

from .config import Settings
from .risk import RiskReject, realized_pnl, size_position
from .strategy import Strategy


@dataclass
class BTTrade:
    side: str
    entry_ts: int
    entry: float
    sl: float
    tp: float
    qty: float
    r: float = 0.0  # ilk stop mesafesi (fiyat)
    exit_ts: int = 0
    exit: float = 0.0
    reason: str = ""
    pnl: float = 0.0


def fetch_history(ex, symbol: str, timeframe: str, days: int) -> List[List[float]]:
    tf_ms = ex.parse_timeframe(timeframe) * 1000
    since = ex.milliseconds() - days * 86_400_000
    out: List[List[float]] = []
    while True:
        batch = ex.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
        if not batch:
            break
        if out and batch[0][0] <= out[-1][0]:
            batch = [c for c in batch if c[0] > out[-1][0]]
            if not batch:
                break
        out += batch
        since = batch[-1][0] + tf_ms
        if since > ex.milliseconds():
            break
        time.sleep(ex.rateLimit / 1000)
    now = ex.milliseconds()
    return [c for c in out if c[0] + tf_ms <= now]


def run_backtest(cfg: Settings, candles: List[List[float]], symbol: str = "SYM"):
    strat = Strategy(cfg)
    ind = strat.compute(candles)  # tek seferde, nedensel
    equity = cfg.paper_start_equity
    trades: List[BTTrade] = []
    pos: Optional[BTTrade] = None
    be_armed = False
    be_pending = False
    entry_idx = 0
    tf_ms = cfg.timeframe_ms
    start = max(strat.min_bars - 1, 1)
    i = start
    n = len(candles)
    while i < n - 1:
        if pos is None:
            an = strat.evaluate(symbol, ind, i, None, None, require_market=False)
            if an.signal is None:
                i += 1
                continue
            s = an.signal
            nxt = candles[i + 1]
            slip = cfg.slippage_pct / 100
            entry = nxt[1] * (1 + slip) if s.side == "long" else nxt[1] * (1 - slip)
            d = 1 if s.side == "long" else -1
            sl = entry - d * s.sl_dist
            tp = entry + d * s.sl_dist * cfg.tp_r_mult
            try:
                plan = size_position(cfg, s.side, entry, sl, tp, 1.0, lambda x: math.floor(x * 1e5) / 1e5,
                                     None, 5.0, equity)
            except RiskReject:
                i += 1
                continue
            pos = BTTrade(s.side, nxt[0], entry, sl, tp, plan.qty, r=s.sl_dist)
            be_armed = False
            be_pending = False
            entry_idx = i + 1
            i += 1
            continue

        # --- acik pozisyon: mum i'yi isle ---
        c = candles[i]
        hi, lo, cl = c[2], c[3], c[4]
        if be_pending:
            be_armed, be_pending = True, False
            pos.sl = pos.entry * (1 + (1 if pos.side == "long" else -1) * 2 * cfg.fee_rate)
        exit_px = None
        reason = ""
        if pos.side == "long":
            if lo <= pos.sl:
                exit_px, reason = pos.sl * (1 - cfg.slippage_pct / 100), "BE" if be_armed else "SL"
            elif hi >= pos.tp:
                exit_px, reason = pos.tp, "TP"
        else:
            if hi >= pos.sl:
                exit_px, reason = pos.sl * (1 + cfg.slippage_pct / 100), "BE" if be_armed else "SL"
            elif lo <= pos.tp:
                exit_px, reason = pos.tp, "TP"
        if exit_px is None and cfg.max_hold_candles > 0 and i - entry_idx + 1 >= cfg.max_hold_candles:
            exit_px, reason = cl, "ZAMAN"
        if exit_px is None and cfg.breakeven_at_r > 0 and not be_armed:
            r = pos.r
            fav = (hi - pos.entry) if pos.side == "long" else (pos.entry - lo)
            if r > 0 and fav / r >= cfg.breakeven_at_r:
                be_pending = True
        if exit_px is not None:
            pnl, _ = realized_pnl(pos.side, pos.entry, exit_px, pos.qty, cfg.fee_rate)
            pos.exit_ts, pos.exit, pos.reason, pos.pnl = c[0] + tf_ms, exit_px, reason, pnl
            equity += pnl
            trades.append(pos)
            pos = None
        i += 1
    return trades, equity


def summarize(trades: List[BTTrade], start_equity: float, end_equity: float) -> str:
    if not trades:
        return "Islem yok."
    pnls = [t.pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gl = -sum(losses)
    pf = sum(wins) / gl if gl > 0 else float("inf")
    eq, peak, mdd = start_equity, start_equity, 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak * 100)
    by = {}
    for t in trades:
        by[t.reason] = by.get(t.reason, 0) + 1
    return (
        f"Islem: {len(trades)}  Isabet: %{len(wins) / len(trades) * 100:.1f}  Kar faktoru: {pf:.2f}\n"
        f"Net: {sum(pnls):+.2f} USDT  Baslangic {start_equity:.2f} -> Bitis {end_equity:.2f}\n"
        f"Maks. dusus: %{mdd:.1f}  Ort/islem: {sum(pnls) / len(trades):+.3f} USDT\n"
        f"Cikis nedenleri: {by}"
    )
