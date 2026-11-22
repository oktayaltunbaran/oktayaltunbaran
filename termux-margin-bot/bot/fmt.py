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
        sg = an.signal
        lines.append(f"\n<b>Sonuc:</b> {side_label(sg.side)} SINYALI")
        lines.append(f"Giris <code>{px(sg.entry_ref)}</code> · Stop <code>{px(sg.sl)}</code> · "
                     + (f"Hedef <code>{px(sg.tp)}</code>" if sg.tp > 0 else "Cikis: Supertrend donusu"))
    elif an.plan:
        lines.append("")
        lines += plan_block(an.plan)
    else:
        lines.append("\n<b>Sonuc:</b> sinyal yok · trend net degil, islem plani yok")
    return "\n".join(lines)


def plan_block(pl) -> list:
    if pl.trigger is not None:
        return st_plan_block(pl)
    d = 1 if pl.side == "long" else -1
    sl_pct = (pl.sl - pl.entry) / pl.entry * 100
    tp_pct = (pl.tp - pl.entry) / pl.entry * 100
    where = "asagida" if pl.distance_pct < 0 else "yukarida"
    inv = "altinda" if d == 1 else "ustunde"
    lines = [
        f"📍 <b>Islem plani (tahmini)</b> · {side_label(pl.side)}",
        f"Giris bolgesi <code>{px(pl.zone_low)} – {px(pl.zone_high)}</code>",
        f"  (simdiki fiyatin %{abs(pl.distance_pct):.2f} {where})",
        f"Stop  <code>{px(pl.sl)}</code> ({pct(sl_pct)})",
        f"Hedef <code>{px(pl.tp)}</code> ({pct(tp_pct)})",
        f"Iptal: 2s kapanis EMA200 ({px(pl.invalidation)}) {inv}",
    ]
    if pl.waiting_for:
        lines.append("Beklenen: " + "; ".join(esc(w) for w in pl.waiting_for))
    lines.append("<i>Kosullar olusunca bot sinyal verir; oto modda kendisi girer, "
                 "stop/hedef borsaya konur.</i>")
    return lines


def signal_text(
    an: Analysis, plan: SizePlan, snap: Optional[MarketSnapshot], oi_change: Optional[float], cfg, broker_name: str,
    expires_min: Optional[int],
) -> str:
    s = an.signal
    assert s is not None
    sl_pct = (plan.sl - plan.entry) / plan.entry * 100
    tp_pct = (plan.tp - plan.entry) / plan.entry * 100 if plan.tp > 0 else 0.0
    lines = [
        f"{side_label(s.side)} · <b>{esc(s.symbol)}</b> · {cfg.timeframe}",
        f"<i>{esc(broker_name)}</i>",
        "",
        f"Giris  <code>{px(plan.entry)}</code>",
        f"Stop   <code>{px(plan.sl)}</code>  ({pct(sl_pct)})",
    ]
    if plan.tp > 0:
        rr = abs(plan.tp - plan.entry) / abs(plan.entry - plan.sl)
        lines.append(f"Hedef  <code>{px(plan.tp)}</code>  ({pct(tp_pct)})  R:R 1:{rr:.1f}")
        if cfg.fixed:
            lines.append(f"Sabit sema: hedefte +%{cfg.tp_roi_pct:g} ROI · stopta -{cfg.sl_loss_usdt:g}$ (net)")
    else:
        lines += [
            "Stop takibi: her 2s kapanista Supertrend cizgisine (lehte) tasinir",
            "Cikis  : 2s mum Supertrend'in ters tarafinda kapaninca",
        ]
    lines += [
        f"Likid. ≈ <code>{px(plan.liq_est)}</code>",
        "",
        f"Nominal {plan.notional:.2f} USDT · Marjin {plan.margin:.2f} USDT ({cfg.leverage}x izole)",
        f"Stopta kayip ≈ <b>{plan.loss_at_sl:.2f} USDT</b>"
        + (f" · Hedefte kar ≈ {plan.notional * (abs(tp_pct) / 100 - 2 * cfg.fee_rate):.2f} USDT" if plan.tp > 0 else ""),
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
            f"Stop <code>{px(t.sl)}</code> · "
            + (f"Hedef <code>{px(t.tp)}</code>" if t.tp > 0 else "Cikis: Supertrend donusu (iz suren stop)"),
            f"Likid. <code>{px(t.liq_price)}</code> · Nominal {t.notional_usdt:.2f} USDT",
            "Stop borsada (sunucu tarafli) tanimli.",
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


def st_plan_block(pl) -> list:
    """Supertrend: bir sonraki islemin giris/cikis semasi."""
    long_ = pl.side == "long"
    cur = {"long": "🟢 YUKARI", "short": "🔴 ASAGI"}.get(pl.current_trend or "", "—")
    where = "ustunde" if long_ else "altinda"
    sl_pct = (pl.sl - pl.trigger) / pl.trigger * 100
    lines = [
        "📍 <b>Giris / cikis semasi</b>",
        f"Simdiki trend: {cur} (bu yondeki giris firsati, donus aninda verilmisti)",
        "",
        f"<b>Sonraki islem:</b> {side_label(pl.side)}",
        f"Tetik  : 2s mum <code>{px(pl.trigger)}</code> {where} kapanirsa "
        f"(fiyattan %{abs(pl.distance_pct):.2f} uzakta)",
        "Giris  : tetik mumunun kapanisi (piyasa emri)",
        f"Stop   : ≈ <code>{px(pl.sl)}</code> ({pct(sl_pct)}) · borsada durur",
        "Stop takibi: her 2s kapanista yeni Supertrend cizgisine (yalnizca lehte) tasinir",
        "Cikis  : 2s mum Supertrend'in ters tarafinda kapaninca (sabit hedef yok, kazanan kosar)",
    ]
    if pl.waiting_for:
        lines.append("Ek sart: " + "; ".join(esc(w) for w in pl.waiting_for))
    lines.append("<i>Seviyeler tahminidir; kesin degerler tetik mumunun kapanisinda hesaplanir.</i>")
    return lines


def summary_text(rows, tf: str) -> str:
    """/analiz (argumansiz): tum semboller tek mesajda."""
    lines = [f"{'Coin':<5}{'Fiyat':>10}  Trend  Sonraki islem tetigi"]
    sig = []
    for an in rows:
        base = an.symbol.split("/")[0][:5]
        trend = {"long": "▲", "short": "▼"}.get(an.bias, "–")
        if an.signal:
            nxt = f"SINYAL {an.signal.side.upper()}"
            sig.append(an.symbol)
        elif an.plan and an.plan.trigger is not None:
            pl = an.plan
            op = ">" if pl.side == "long" else "<"
            nxt = f"{pl.side.upper():<5} {op} {px(pl.trigger)} ({pl.distance_pct:+.1f}%)"
            if pl.waiting_for:
                nxt += " *"
        elif an.plan:
            nxt = f"{an.plan.side.upper()} bolge {px(an.plan.entry)}"
        else:
            nxt = "-"
        lines.append(f"{base:<5}{px(an.close):>10}  {trend:^5}  {nxt}")
    out = [f"🧭 <b>Piyasa ozeti</b> · {tf} · son kapanan mum", f"<pre>{esc(chr(10).join(lines))}</pre>"]
    out.append("Tetik: 2s mum bu seviyenin otesinde kapanirsa giris. "
               "<i>* = ek sart var (EMA200/filtre)</i>")
    if sig:
        out.append("🔔 Sinyal: " + ", ".join(esc(x) for x in sig))
    out.append("Ayrinti ve giris/cikis semasi: <code>/analiz ETH</code>")
    return "\n".join(out)


# ------------------------------------------------------------------ coin listeleri
def _vol(v: float) -> str:
    if v >= 1e9:
        return f"${v / 1e9:.1f}B"
    if v >= 1e6:
        return f"${v / 1e6:.0f}M"
    return f"${v / 1e3:.0f}K"


def _chg(v) -> str:
    return "—" if v is None else f"{v:+.1f}%"


def top_text(coins, resolver, trading: set, source: str, exchange: str) -> str:
    lines = [f"📈 <b>24s hacme gore Top {len(coins)}</b> · {esc(source)}",
             "<i>stablecoin / altin / wrapped haric</i>", ""]
    for i, c in enumerate(coins, 1):
        found = resolver(c.symbol)
        if found:
            perp = found[0].split("/")[0]
            mark = "✅ islemde" if found[0] in trading else "⛔ riskli meme"
            perp_txt = f"{esc(perp)} · {mark}"
        else:
            perp_txt = f"{esc(exchange)} vadelide yok"
        lines.append(f"{i}. <b>{esc(c.symbol)}</b> {_vol(c.volume_24h)} {_chg(c.change_24h)} · {perp_txt}")
    lines.append("")
    lines.append(f"Bot {len(trading)} coini 2s grafikte izliyor (/analiz).")
    return "\n".join(lines)


def meme_text(memes, security: dict, source: str, pending: int) -> str:
    from .coins import LEVEL_ICON, UNKNOWN

    lines = [f"🐸 <b>24s hacme gore Top {len(memes)} meme coin</b> · {esc(source)}", ""]
    for i, m in enumerate(memes, 1):
        rep = security.get(m.id)
        lvl = LEVEL_ICON[rep.level if rep else UNKNOWN]
        chain = esc(m.chain_name) + (f" +{m.other_chains}" if m.other_chains else "")
        lines.append(f"{i}. <b>{esc(m.symbol)}</b> · {chain} · {_vol(m.volume_24h)} {_chg(m.change_24h)} · {lvl}")
    lines.append("")
    if pending:
        lines.append(f"⏳ {pending} coin icin guvenlik taramasi arka planda suruyor.")
    lines.append("Ayrinti: <code>/meme PEPE</code>")
    lines.append("<i>Etiket kontrat ve holder riskini olcer (rug pull, honeypot, mint/freeze, vergi, "
                 "dagilim, likidite). Fiyat riskini olcmez: meme coinler cok oynaktir.</i>")
    return "\n".join(lines)


def meme_detail(m, rep) -> str:
    from .coins import LEVEL_ICON, UNKNOWN

    lines = [f"🐸 <b>{esc(m.name)} ({esc(m.symbol)})</b>",
             f"Ag: {esc(m.chain_name)}" + (f" (+{m.other_chains} agda daha)" if m.other_chains else "")]
    if m.address:
        lines.append(f"Kontrat: <code>{esc(m.address)}</code>")
    lines.append(f"Fiyat {px(m.price)} · 24s {_chg(m.change_24h)} · hacim {_vol(m.volume_24h)}"
                 + (f" · sira #{m.rank}" if m.rank else ""))
    lines.append("")
    if rep is None:
        lines.append(LEVEL_ICON[UNKNOWN] + " — guvenlik taramasi sirada")
        return "\n".join(lines)
    lines.append(f"<b>Guvenlik: {LEVEL_ICON[rep.level]}</b>")
    facts = []
    if rep.holders:
        facts.append(f"holder {rep.holders:,}")
    if rep.top10_pct is not None:
        facts.append(f"ilk 10 cuzdan %{rep.top10_pct:.0f}")
    if rep.liquidity_usd is not None:
        facts.append(f"DEX likidite {_vol(rep.liquidity_usd)}")
    if rep.age_days is not None:
        facts.append(f"yas {rep.age_days:.0f} gun")
    if facts:
        lines.append(" · ".join(facts))
    for r in rep.reasons:
        icon = "⛔" if rep.level == "RISKLI" and r == rep.reasons[0] else "•"
        lines.append(f"{icon} {esc(r)}")
    if rep.checked_at:
        lines.append(f"<i>Kaynak: {esc(', '.join(rep.sources))} · {ts_str(int(rep.checked_at * 1000))}</i>")
    lines.append("<i>Ilk 10 cuzdan orani borsa, yakim ve kilitli cuzdanlar haric hesaplanir.</i>")
    return "\n".join(lines)
