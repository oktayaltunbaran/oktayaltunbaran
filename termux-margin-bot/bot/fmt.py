"""Telegram mesaj bicimlendirme (sade, profesyonel, HTML parse_mode)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, List, Optional

from .exchanges import MarketSnapshot
from .risk import SizePlan
from .storage import Trade
from .strategy import Analysis
from .telegram_api import esc


def px(v: Optional[float]) -> str:
    if v is None:
        return "—"
    a = abs(v)
    if a >= 1000:
        return f"{v:,.2f}"
    if a >= 1:
        return f"{v:.4f}".rstrip("0").rstrip(".")
    return f"{v:.6g}"


def pct(v: Optional[float], digits: int = 2, sign: bool = True) -> str:
    if v is None:
        return "—"
    return f"{v:+.{digits}f}%" if sign else f"{v:.{digits}f}%"


def usd(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"{v:+.2f}" if v < 0 or v > 0 else "0.00"


def ts_str(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%d.%m %H:%M UTC")


def side_label(side: str) -> str:
    return "🟢 LONG" if side == "long" else "🔴 SHORT"


def market_block(snap: Optional[MarketSnapshot], oi_change: Optional[float]) -> List[str]:
    if snap is None:
        return ["<i>Piyasa verisi yok</i>"]
    lines = ["<b>Piyasa</b> · Binance / OKX / Bybit"]
    rows = []
    for name, s in snap.per_exchange.items():
        f = pct(s.funding_8h * 100, 4) if s.funding_8h is not None else "—"
        rows.append(f"{name[:3].upper():<4}{px(s.spot):>11} {px(s.perp):>11} {f:>9}")
    lines.append("<pre>" + esc(f"{'':<4}{'spot':>11} {'perp':>11} {'fund8s':>9}") + "\n" + esc("\n".join(rows)) + "</pre>")
    lines.append(
        f"Baz {pct(snap.basis_pct, 3)} · Sapma {pct(snap.divergence_pct, 3, False)} · "
        f"Fund. ort {pct(snap.funding_avg * 100 if snap.funding_avg is not None else None, 4)} · OI Δ {pct(oi_change)}"
    )
    return lines


def analysis_text(an: Analysis, snap: Optional[MarketSnapshot], oi_change: Optional[float], tf: str) -> str:
    bias = {"long": "Yukari trend", "short": "Asagi trend", "none": "Kararsiz"}[an.bias]
    lines = [
        f"<b>{esc(an.symbol)}</b> · {tf} · {ts_str(an.bar_ts)} mumu",
        f"Fiyat <code>{px(an.close)}</code> · {bias}",
        f"EMA21 {px(an.ema_fast)} · EMA50 {px(an.ema_mid)} · EMA200 {px(an.ema_slow)}",
        f"RSI {an.rsi:.1f} · ADX {an.adx:.1f} · ATR {pct(an.atr_pct, 2, False)}",
    ]
    if an.checks:
        lines.append("")
        lines += [f"{'✅' if ok else '▫️'} {esc(name)}" for name, ok in an.checks]
    for b in an.blocks:
        lines.append(f"⛔ {esc(b)}")
    for n in an.notes:
        lines.append(f"ℹ️ {esc(n)}")
    lines.append("")
    lines += market_block(snap, oi_change)
    if an.signal:
        lines.append(f"\n<b>Sonuc:</b> {side_label(an.signal.side)} sinyali")
    else:
        lines.append("\n<b>Sonuc:</b> sinyal yok")
    return "\n".join(lines)


def signal_text(
    an: Analysis, plan: SizePlan, snap: Optional[MarketSnapshot], oi_change: Optional[float], cfg, broker_name: str,
    expires_min: Optional[int],
) -> str:
    s = an.signal
    assert s is not None
    sl_pct = (plan.sl - plan.entry) / plan.entry * 100
    tp_pct = (plan.tp - plan.entry) / plan.entry * 100
    lines = [
        f"{side_label(s.side)} · <b>{esc(s.symbol)}</b> · {cfg.timeframe}",
        f"<i>{esc(broker_name)}</i>",
        "",
        f"Giris  <code>{px(plan.entry)}</code>",
        f"Stop   <code>{px(plan.sl)}</code>  ({pct(sl_pct)})",
        f"Hedef  <code>{px(plan.tp)}</code>  ({pct(tp_pct)})  R:R 1:{cfg.tp_r_mult:g}",
        f"Likid. ≈ <code>{px(plan.liq_est)}</code>",
        "",
        f"Nominal {plan.notional:.2f} USDT · Marjin {plan.margin:.2f} USDT ({cfg.leverage}x izole)",
        f"Stopta kayip ≈ <b>{plan.loss_at_sl:.2f} USDT</b> · Hedefte kar ≈ "
        f"{plan.notional * (abs(tp_pct) / 100 - 2 * cfg.fee_rate):.2f} USDT",
    ]
    if plan.capped_by_leverage:
        lines.append("<i>Nominal, kaldirac/bakiye tavanina gore sinirlandi.</i>")
    lines.append(f"RSI {an.rsi:.1f} · ADX {an.adx:.1f} · ATR {pct(an.atr_pct, 2, False)}")
    lines.append("")
    lines += market_block(snap, oi_change)
    for n in an.notes:
        lines.append(f"ℹ️ {esc(n)}")
    if expires_min:
        lines.append(
            f"\n⏳ Onay suresi {expires_min} dk. Fiyat girisden 0.5R'den fazla uzaklasirsa sinyal gecersiz olur."
        )
    return "\n".join(lines)


def trade_open_text(t: Trade, broker_name: str) -> str:
    return "\n".join(
        [
            f"✅ <b>Pozisyon acildi</b> · {side_label(t.side)} {esc(t.symbol)}",
            f"<i>{esc(broker_name)}</i>",
            f"Giris <code>{px(t.entry_price)}</code> · Miktar {t.base_qty:g}",
            f"Stop <code>{px(t.sl)}</code> · Hedef <code>{px(t.tp)}</code>",
            f"Likid. <code>{px(t.liq_price)}</code> · Nominal {t.notional_usdt:.2f} USDT",
            "Stop ve hedef borsada (sunucu tarafli) tanimli.",
        ]
    )


def trade_close_text(t: Trade) -> str:
    icon = "🟩" if (t.pnl_usdt or 0) >= 0 else "🟥"
    r_mult = None
    risk = abs(t.entry_price - t.initial_sl) * t.base_qty
    if risk > 0 and t.pnl_usdt is not None:
        r_mult = t.pnl_usdt / risk
    return "\n".join(
        [
            f"{icon} <b>Pozisyon kapandi</b> · {esc(t.exit_reason)} · {side_label(t.side)} {esc(t.symbol)}",
            f"Giris {px(t.entry_price)} → Cikis {px(t.exit_price)}",
            f"Net K/Z <b>{usd(t.pnl_usdt)} USDT</b>"
            + (f" ({r_mult:+.2f}R)" if r_mult is not None else "")
            + f" · Komisyon ≈ {t.fees_usdt or 0:.2f}",
        ]
    )


def stats_text(trades: Iterable[Trade], title: str) -> str:
    ts = list(trades)
    if not ts:
        return f"<b>{esc(title)}</b>\nKapanmis islem yok."
    pnls = [t.pnl_usdt or 0.0 for t in ts]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gp, gl = sum(wins), -sum(losses)
    pf = (gp / gl) if gl > 0 else float("inf")
    eq = 0.0
    peak = 0.0
    mdd = 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    return "\n".join(
        [
            f"<b>{esc(title)}</b>",
            f"Islem {len(ts)} · Kazanan {len(wins)} · Kaybeden {len(losses)} · Isabet %{len(wins) / len(ts) * 100:.0f}",
            f"Net K/Z <b>{sum(pnls):+.2f} USDT</b> · Kar faktoru {pf:.2f}",
            f"Ort. kazanc {gp / len(wins) if wins else 0:.2f} · Ort. kayip {-gl / len(losses) if losses else 0:.2f}",
            f"Maks. dusus {mdd:.2f} USDT",
        ]
    )
