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
from datetime import datetime, timezone
from typing import Callable, List, Optional

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


@dataclass
class BTResult:
    trades: List[BTTrade]
    end_equity: float
    rejected: int  # risk/asgari tutar nedeniyle acilamayan sinyal sayisi
    candles: List[List[float]]


def run_backtest(
    cfg: Settings,
    candles: List[List[float]],
    symbol: str = "SYM",
    contract_size: float = 1.0,
    amount_to_precision: Optional[Callable[[float], float]] = None,
    min_amount: Optional[float] = None,
    min_cost: Optional[float] = 5.0,
) -> BTResult:
    """Borsanin gercek kontrat buyuklugu / hassasiyet / asgari tutarlari
    verilirse canlidaki gibi boyutlandirir (or. BTC'de 100 USDT asgari)."""
    a2p = amount_to_precision or (lambda x: math.floor(x * 1e5) / 1e5)
    rejected = 0
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
                plan = size_position(cfg, s.side, entry, sl, tp, contract_size, a2p, min_amount, min_cost, equity)
            except RiskReject:
                rejected += 1
                i += 1
                continue
            pos = BTTrade(s.side, nxt[0], entry, sl, tp, plan.base_qty, r=s.sl_dist)
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
    return BTResult(trades, equity, rejected, candles)


def _stats(trades: List[BTTrade], start_equity: float) -> dict:
    pnls = [t.pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gl = -sum(losses)
    eq, peak, mdd = start_equity, start_equity, 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak * 100)
    return {
        "n": len(trades),
        "win": len(wins) / len(trades) * 100 if trades else 0.0,
        "pf": (sum(wins) / gl) if gl > 0 else float("inf"),
        "net": sum(pnls),
        "mdd": mdd,
        "avg_win": sum(wins) / len(wins) if wins else 0.0,
        "avg_loss": sum(losses) / len(losses) if losses else 0.0,
    }


def _d(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%d.%m.%y")


def report_lines(res: BTResult, start_equity: float, symbol: str, timeframe: str, last_n: int = 5) -> List[str]:
    """Duz metin rapor satirlari (Telegram'da <pre> icinde gosterilir)."""
    c = res.candles
    if not c:
        return [f"{symbol}: veri yok"]
    days = (c[-1][0] - c[0][0]) / 86_400_000
    bh = (c[-1][4] - c[0][4]) / c[0][4] * 100
    out = [
        f"{symbol} {timeframe} | {_d(c[0][0])} - {_d(c[-1][0])} ({days:.0f} gun, {len(c)} mum)",
    ]
    tr = res.trades
    if not tr:
        out.append("Bu donemde kurallara uyan islem olmadi.")
        if res.rejected:
            out.append(f"Asgari tutar/risk nedeniyle acilamayan sinyal: {res.rejected}")
        out.append(f"Al-tut (fiyat degisimi): %{bh:+.1f}")
        return out
    st = _stats(tr, start_equity)
    ret = (res.end_equity - start_equity) / start_equity * 100
    pf = "sonsuz" if st["pf"] == float("inf") else f"{st['pf']:.2f}"
    hold_h = sum((t.exit_ts - t.entry_ts) for t in tr) / len(tr) / 3_600_000
    out += [
        f"Sermaye   {start_equity:.2f} -> {res.end_equity:.2f} USDT ({ret:+.1f}%)",
        f"Islem     {st['n']} (ayda ~{st['n'] / max(days / 30, 1e-9):.1f}) | Isabet %{st['win']:.1f}",
        f"Kar fakt. {pf} | Maks. dusus %{st['mdd']:.1f}",
        f"Ort.kazanc {st['avg_win']:+.2f} | Ort.kayip {st['avg_loss']:+.2f} | Ort.sure {hold_h:.0f} sa",
    ]
    for side in ("long", "short"):
        sub = [t for t in tr if t.side == side]
        if sub:
            ss = _stats(sub, start_equity)
            out.append(f"{side.upper():<5}     {ss['n']} islem | isabet %{ss['win']:.0f} | net {ss['net']:+.2f}")
    by: dict = {}
    for t in tr:
        by[t.reason] = by.get(t.reason, 0) + 1
    out.append("Cikis     " + ", ".join(f"{k} {v}" for k, v in sorted(by.items())))
    if res.rejected:
        out.append(f"Acilamayan sinyal (asgari tutar/risk): {res.rejected}")
    out.append(f"Al-tut    fiyat %{bh:+.1f}")
    out.append("")
    out.append(f"Son {min(last_n, len(tr))} islem (giris -> cikis):")
    for t in tr[-last_n:]:
        out.append(f"{_d(t.entry_ts)} {t.side[0].upper()} {t.entry:.6g} -> {t.exit:.6g} {t.reason:<5} {t.pnl:+.2f}")
    return out


def summarize(trades: List[BTTrade], start_equity: float, end_equity: float) -> str:
    if not trades:
        return "Islem yok."
    st = _stats(trades, start_equity)
    return (
        f"Islem: {st['n']}  Isabet: %{st['win']:.1f}  Kar faktoru: {st['pf']:.2f}\n"
        f"Net: {st['net']:+.2f} USDT  Baslangic {start_equity:.2f} -> Bitis {end_equity:.2f}\n"
        f"Maks. dusus: %{st['mdd']:.1f}"
    )


def backtest_symbol(cfg: Settings, ex, symbol: str, days: int) -> List[str]:
    """Borsadan gecmis veriyi indirir, borsanin gercek asgari tutarlariyla test eder."""
    from .exchanges import perp_symbol

    psym = perp_symbol(symbol)
    if ex.markets is None:
        ex.load_markets()
    m = ex.market(psym)
    lim = m.get("limits") or {}
    candles = fetch_history(ex, psym, cfg.timeframe, days)
    res = run_backtest(
        cfg, candles, symbol,
        contract_size=float(m.get("contractSize") or 1.0),
        amount_to_precision=lambda x: float(ex.amount_to_precision(psym, x)),
        min_amount=(lim.get("amount") or {}).get("min"),
        min_cost=(lim.get("cost") or {}).get("min"),
    )
    return report_lines(res, cfg.paper_start_equity, symbol, cfg.timeframe)
