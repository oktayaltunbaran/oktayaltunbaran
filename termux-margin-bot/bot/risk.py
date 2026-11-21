"""Pozisyon buyuklugu, likidasyon guvenligi ve gunluk risk korumalari.

Temel ilke: KALDIRAC RISK DEGILDIR. 5x yalnizca bir UST SINIRDIR
(30 USDT * 5 = en fazla 150 USDT nominal). Gercek risk stop mesafesiyle
tanimlanir:

    nominal = RISK_PER_TRADE / (SL% + 2*komisyon + kayma)
    nominal = min(nominal, MARGIN_USDT * LEVERAGE)

Boylece stop calistiginda kayip (komisyon dahil) RISK_PER_TRADE_USDT'yi asmaz.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, List, Optional

from .config import Settings
from .storage import Trade


class RiskReject(Exception):
    """Islem risk kurallarina takildi (hata degil, bilincli red)."""


@dataclass
class SizePlan:
    qty: float  # kontrat adedi (borsa birimi)
    contract_size: float
    entry: float
    sl: float
    tp: float
    notional: float
    margin: float
    loss_at_sl: float  # komisyon + kayma dahil tahmini kayip
    liq_est: float
    capped_by_leverage: bool

    @property
    def base_qty(self) -> float:
        return self.qty * self.contract_size


def liquidation_estimate(side: str, entry: float, leverage: int, mmr: float) -> float:
    """Izole, dogrusal (USDT-M) kontrat icin yaklasik likidasyon fiyati.
    Gercek deger kademeli MMR ve komisyonlara bagli; pozisyon acilinca borsanin
    bildirdigi deger kullanilir. Bu tahmin yalnizca on-kontrol icindir."""
    if side == "long":
        return entry * (1 - 1 / leverage + mmr)
    return entry * (1 + 1 / leverage - mmr)


def size_position(
    cfg: Settings,
    side: str,
    entry: float,
    sl: float,
    tp: float,
    contract_size: float,
    amount_to_precision: Callable[[float], float],
    min_amount: Optional[float],
    min_cost: Optional[float],
    free_balance: Optional[float],
) -> SizePlan:
    if entry <= 0 or sl <= 0 or contract_size <= 0:
        raise RiskReject("Gecersiz fiyat/kontrat verisi")
    if (side == "long" and not sl < entry < tp) or (side == "short" and not tp < entry < sl):
        raise RiskReject("SL/TP giris fiyatinin yanlis tarafinda")

    sl_frac = abs(entry - sl) / entry
    cost_frac = sl_frac + 2 * cfg.fee_rate + cfg.slippage_pct / 100
    notional_by_risk = cfg.risk_per_trade_usdt / cost_frac
    cap = cfg.max_notional_usdt
    capped = notional_by_risk > cap
    notional_target = min(notional_by_risk, cap)

    if free_balance is not None:
        # Izole marjin + komisyon icin %3 tampon
        max_by_balance = free_balance * cfg.leverage * 0.97
        if notional_target > max_by_balance:
            notional_target = max_by_balance
            capped = True

    raw_qty = notional_target / (entry * contract_size)
    qty = float(amount_to_precision(raw_qty))  # ccxt: TRUNCATE (asagi yuvarlar)
    if qty <= 0 or math.isnan(qty):
        raise RiskReject(
            f"Hesaplanan miktar borsanin hassasiyetine gore 0'a yuvarlandi (nominal {notional_target:.2f} USDT)"
        )
    notional = qty * contract_size * entry
    if min_amount is not None and qty < min_amount:
        raise RiskReject(f"Miktar {qty} < borsa min {min_amount}")
    if min_cost is not None and notional < min_cost:
        raise RiskReject(
            f"Nominal {notional:.2f} USDT < borsa min {min_cost:g} USDT. "
            f"Risk limiti ({cfg.risk_per_trade_usdt:g} USDT) bu sembol icin cok dusuk."
        )

    loss = notional * cost_frac
    # Yuvarlama sadece asagi oldugu icin loss <= risk olmali; yine de dogrula
    if loss > cfg.risk_per_trade_usdt * 1.0001:
        raise RiskReject(f"Tahmini kayip {loss:.2f} > risk limiti {cfg.risk_per_trade_usdt:g}")

    liq = liquidation_estimate(side, entry, cfg.leverage, cfg.maint_margin_rate)
    liq_dist = abs(entry - liq)
    if abs(entry - sl) >= 0.7 * liq_dist:
        raise RiskReject(
            f"SL ({sl:.6g}) likidasyona ({liq:.6g}) cok yakin; stop likidasyondan once calismayabilir"
        )

    return SizePlan(
        qty=qty,
        contract_size=contract_size,
        entry=entry,
        sl=sl,
        tp=tp,
        notional=notional,
        margin=notional / cfg.leverage,
        loss_at_sl=loss,
        liq_est=liq,
        capped_by_leverage=capped,
    )


def realized_pnl(side: str, entry: float, exit_: float, base_qty: float, fee_rate: float) -> tuple:
    """(net_pnl, fees). Komisyon her iki bacak icin nominal uzerinden."""
    direction = 1 if side == "long" else -1
    gross = direction * (exit_ - entry) * base_qty
    fees = (entry * base_qty + exit_ * base_qty) * fee_rate
    return gross - fees, fees


def utc_day_start_ms(now_ms: Optional[int] = None) -> int:
    now = datetime.fromtimestamp((now_ms or time.time() * 1000) / 1000, tz=timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp() * 1000)


@dataclass
class GuardState:
    allowed: bool
    reason: str = ""


def check_guards(
    cfg: Settings, closed_today: List[Trade], recent_closed: List[Trade], equity: Optional[float], paused: bool
) -> GuardState:
    if paused:
        return GuardState(False, "Bot duraklatildi (/devam ile surdurun)")
    if equity is not None and equity < cfg.min_equity_usdt:
        return GuardState(
            False, f"Bakiye {equity:.2f} < MIN_EQUITY_USDT {cfg.min_equity_usdt:g}: islem durduruldu"
        )
    day_pnl = sum(t.pnl_usdt or 0.0 for t in closed_today)
    if day_pnl <= -cfg.max_daily_loss_usdt:
        return GuardState(False, f"Gunluk kayip limiti doldu ({day_pnl:.2f} USDT). UTC 00:00'da sifirlanir")
    streak = 0
    for t in reversed(recent_closed):
        if (t.pnl_usdt or 0.0) < 0:
            streak += 1
        else:
            break
    if streak >= cfg.max_consecutive_losses:
        return GuardState(False, f"Ust uste {streak} kayip: bot otomatik duraklatildi (/devam)")
    return GuardState(True)
