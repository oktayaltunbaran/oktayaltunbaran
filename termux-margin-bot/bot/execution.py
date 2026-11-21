"""Emir yurutme: PaperBroker (simulasyon) ve LiveBroker (ccxt, gercek emir).

LiveBroker guvenlik ilkeleri
----------------------------
1. Tek yonlu (one-way / net) pozisyon modu, IZOLE marjin, sabit kaldirac.
2. Giristen hemen sonra pozisyon borsadan okunur; GERCEK giris fiyati,
   miktar, likidasyon fiyati ve marjin modu dogrulanir.
3. Stop-loss BORSADA (sunucu tarafli, reduceOnly, mark fiyat tetikli) durur.
   Telefon kapansa / Termux oldurulse bile stop calisir.
4. Stop-loss konamazsa pozisyon DERHAL piyasa emriyle kapatilir: korumasiz
   (naked) pozisyon asla birakilmaz.
5. Stop tasima (breakeven): once YENI stop konur, sonra eskisi iptal edilir;
   arada korumasiz an olmaz. Ikisi de reduceOnly oldugundan cift tetiklenme
   ters pozisyon acamaz.
6. Pozisyon kapaninca kalan tetik (SL/TP) emirleri temizlenir (yetim emir yok).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import ccxt

from .config import Settings
from .exchanges import MarketData, make_client, perp_symbol
from .risk import SizePlan, realized_pnl
from .storage import Trade

log = logging.getLogger("bot.execution")


class ExecutionError(Exception):
    pass


@dataclass
class MarketInfo:
    symbol: str  # perp birlesik sembol
    contract_size: float
    min_amount: Optional[float]
    min_cost: Optional[float]
    ex: ccxt.Exchange

    def amount_to_precision(self, x: float) -> float:
        return float(self.ex.amount_to_precision(self.symbol, x))

    def price_to_precision(self, x: float) -> float:
        return float(self.ex.price_to_precision(self.symbol, x))


@dataclass
class PositionStatus:
    open: bool
    mark: Optional[float] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    fees: Optional[float] = None


def _market_info(ex: ccxt.Exchange, symbol: str) -> MarketInfo:
    psym = perp_symbol(symbol)
    if ex.markets is None:
        ex.load_markets()
    m = ex.market(psym)
    if not m.get("active", True):
        raise ExecutionError(f"{psym} borsada aktif degil")
    if not m.get("linear"):
        raise ExecutionError(f"{psym} dogrusal (USDT-M) kontrat degil")
    lim = m.get("limits") or {}
    return MarketInfo(
        symbol=psym,
        contract_size=float(m.get("contractSize") or 1.0),
        min_amount=(lim.get("amount") or {}).get("min"),
        min_cost=(lim.get("cost") or {}).get("min"),
        ex=ex,
    )


def _exit_reason(t: Trade, exit_price: float) -> str:
    return "TP" if abs(exit_price - t.tp) < abs(exit_price - t.sl) else ("BE" if t.breakeven_done else "SL")


# ============================================================== PAPER
class PaperBroker:
    """Gercek piyasa verisiyle simulasyon. 1 dakikalik mumlarla SL/TP fitil
    kontrolu yapar; ayni dakikada ikisi de degdiyse KOTUMSER varsayim (SL)."""

    mode = "paper"

    def __init__(self, cfg: Settings, md: MarketData, storage):
        self.cfg = cfg
        self.md = md
        self.ex = md.swap[cfg.exec_exchange]
        self.storage = storage
        if storage.get("paper_equity") is None:
            storage.set("paper_equity", cfg.paper_start_equity)

    @property
    def name(self) -> str:
        return f"{self.cfg.exec_exchange} (paper)"

    def prepare(self, symbol: str) -> None:
        self.md._ensure(self.ex)

    def market_info(self, symbol: str) -> MarketInfo:
        self.md._ensure(self.ex)
        return _market_info(self.ex, symbol)

    def equity(self) -> float:
        return float(self.storage.get("paper_equity", self.cfg.paper_start_equity))

    def free_balance(self) -> float:
        used = sum(t.notional_usdt / self.cfg.leverage for t in self.storage.open_trades() if t.mode == "paper")
        return self.equity() - used

    def last_price(self, symbol: str) -> float:
        return float(self.ex.fetch_ticker(perp_symbol(symbol))["last"])

    def open_position(self, symbol: str, side: str, plan: SizePlan, sl_dist: float, tp_dist: float) -> Dict[str, Any]:
        px = self.last_price(symbol)
        slip = self.cfg.slippage_pct / 100
        entry = px * (1 + slip) if side == "long" else px * (1 - slip)
        d = 1 if side == "long" else -1
        mi = self.market_info(symbol)
        return {
            "entry": entry,
            "qty": plan.qty,
            "sl": mi.price_to_precision(entry - d * sl_dist),
            "tp": mi.price_to_precision(entry + d * tp_dist),
            "liq": plan.liq_est,
            "sl_order_id": "paper-sl",
            "tp_order_id": "paper-tp",
        }

    def check(self, t: Trade) -> PositionStatus:
        psym = perp_symbol(t.symbol)
        since = int(t.meta.get("paper_checked_ms", t.opened_at))
        candles = self.ex.fetch_ohlcv(psym, "1m", since=since, limit=500)
        for c in candles:
            # Giris dakikasi (giristen onceki fiyatlari da icerir) ve oncesi atlanir
            if c[0] < t.opened_at:
                continue
            hi, lo = float(c[2]), float(c[3])
            hit_sl = lo <= t.sl if t.side == "long" else hi >= t.sl
            hit_tp = hi >= t.tp if t.side == "long" else lo <= t.tp
            if hit_sl:  # kotumser: ayni mumda ikisi de varsa SL
                slip = self.cfg.slippage_pct / 100
                ex_px = t.sl * (1 - slip) if t.side == "long" else t.sl * (1 + slip)
                return PositionStatus(False, exit_price=ex_px, exit_reason="BE" if t.breakeven_done else "SL")
            if hit_tp:
                return PositionStatus(False, exit_price=t.tp, exit_reason="TP")
        # Son (henuz kapanmamis olabilecek) dakikayi bir sonraki turda yeniden tara;
        # 500 mumdan fazla birikmisse kaldigi yerden devam eder (veri atlanmaz).
        if len(candles) >= 2:
            t.meta["paper_checked_ms"] = max(since, int(candles[-1][0]))
        mark = float(candles[-1][4]) if candles else self.last_price(t.symbol)
        return PositionStatus(True, mark=mark)

    def move_stop(self, t: Trade, new_sl: float) -> str:
        return "paper-sl"

    def close_position(self, t: Trade) -> PositionStatus:
        px = self.last_price(t.symbol)
        slip = self.cfg.slippage_pct / 100
        ex_px = px * (1 - slip) if t.side == "long" else px * (1 + slip)
        return PositionStatus(False, exit_price=ex_px, exit_reason="MANUEL")

    def on_closed(self, t: Trade) -> None:
        self.storage.set("paper_equity", self.equity() + (t.pnl_usdt or 0.0))

    def fee_for(self, t: Trade, exit_price: float) -> tuple:
        return realized_pnl(t.side, t.entry_price, exit_price, t.base_qty, self.cfg.fee_rate)


# ============================================================== LIVE
_BENIGN = (
    "no need to change",  # binance -4046/-4059
    "not modified",  # bybit 110043/110025/110026
    "-4046",
    "-4059",
    "110025",
    "110026",
    "110043",
    "59000",  # okx: ayar zaten ayni / degistirilemez durumda
)


def _benign(e: Exception) -> bool:
    s = str(e).lower()
    return any(b in s for b in _BENIGN)


class LiveBroker:
    mode = "live"

    def __init__(self, cfg: Settings, storage):
        self.cfg = cfg
        self.storage = storage
        self.exname = cfg.exec_exchange
        self.ex = make_client(self.exname, "swap", cfg.keys.get(self.exname), testnet=cfg.use_testnet)
        self._prepared: Dict[str, bool] = {}
        self.hedged = False  # OKX long/short modunda kalirsa True

    @property
    def name(self) -> str:
        return f"{self.exname}{' (demo)' if self.cfg.use_testnet else ''}"

    # ---------- hazirlik ----------
    def self_test(self) -> str:
        """Anahtar ve izin dogrulamasi (baslangicta)."""
        self.ex.load_markets()
        bal = self.free_balance()
        return f"{self.name}: baglanti OK, serbest USDT = {bal:.2f}"

    def prepare(self, symbol: str) -> None:
        psym = perp_symbol(symbol)
        if self._prepared.get(psym):
            return
        if self.ex.markets is None:
            self.ex.load_markets()
        ex = self.ex
        # 1) tek yonlu pozisyon modu
        try:
            if self.exname == "bybit":
                ex.set_position_mode(False, psym)
            else:
                ex.set_position_mode(False)
        except Exception as e:  # noqa: BLE001
            if not _benign(e):
                log.warning("set_position_mode: %s", e)
                if self.exname == "okx":
                    self.hedged = self._okx_is_hedged()
        # 2) izole marjin
        if self.exname in ("binance", "bybit"):
            try:
                if self.exname == "bybit":
                    ex.set_margin_mode("isolated", psym, {"leverage": self.cfg.leverage})
                else:
                    ex.set_margin_mode("isolated", psym)
            except Exception as e:  # noqa: BLE001
                if not _benign(e):
                    log.warning("set_margin_mode: %s", e)
        # 3) kaldirac
        try:
            if self.exname == "okx":
                sides = ["long", "short"] if self.hedged else ["net"]
                for ps in sides:
                    ex.set_leverage(self.cfg.leverage, psym, {"marginMode": "isolated", "posSide": ps})
            else:
                ex.set_leverage(self.cfg.leverage, psym)
        except Exception as e:  # noqa: BLE001
            if not _benign(e):
                raise ExecutionError(f"Kaldirac ayarlanamadi: {e}") from e
        self._prepared[psym] = True

    def _okx_is_hedged(self) -> bool:
        try:
            r = self.ex.privateGetAccountConfig()
            mode = r["data"][0].get("posMode", "net_mode")
            return mode == "long_short_mode"
        except Exception as e:  # noqa: BLE001
            log.warning("OKX posMode okunamadi: %s", e)
            return False

    def market_info(self, symbol: str) -> MarketInfo:
        return _market_info(self.ex, symbol)

    # ---------- hesap ----------
    def free_balance(self) -> float:
        b = self.ex.fetch_balance()
        return float((b.get("free") or {}).get("USDT") or 0.0)

    def equity(self) -> float:
        b = self.ex.fetch_balance()
        return float((b.get("total") or {}).get("USDT") or 0.0)

    def last_price(self, symbol: str) -> float:
        return float(self.ex.fetch_ticker(perp_symbol(symbol))["last"])

    def _order_params(self, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        p: Dict[str, Any] = {}
        if self.exname == "okx":
            p["marginMode"] = "isolated"
            if self.hedged:
                p["hedged"] = True
        if extra:
            p.update(extra)
        return p

    def _fetch_position(self, psym: str, side: str) -> Optional[Dict[str, Any]]:
        for p in self.ex.fetch_positions([psym]):
            if p.get("symbol") != psym:
                continue
            c = float(p.get("contracts") or 0.0)
            if c <= 0:
                continue
            pside = p.get("side")
            if pside in (None, side):
                return p
        return None

    def _place_stop(self, psym: str, side: str, qty: float, sl: float) -> str:
        close_side = "sell" if side == "long" else "buy"
        extra: Dict[str, Any] = {"stopLossPrice": sl, "reduceOnly": True}
        if self.exname == "binance":
            extra["workingType"] = "MARK_PRICE"
        elif self.exname == "bybit":
            extra["triggerBy"] = "MarkPrice"
        elif self.exname == "okx":
            extra["slTriggerPxType"] = "mark"
        o = self.ex.create_order(psym, "market", close_side, qty, None, self._order_params(extra))
        return str(o["id"])

    def _place_tp(self, psym: str, side: str, qty: float, tp: float) -> str:
        close_side = "sell" if side == "long" else "buy"
        extra: Dict[str, Any] = {"takeProfitPrice": tp, "reduceOnly": True}
        o = self.ex.create_order(psym, "market", close_side, qty, None, self._order_params(extra))
        return str(o["id"])

    def _cancel(self, psym: str, order_id: Optional[str]) -> None:
        if not order_id:
            return
        # Binance/OKX: tetik emirleri ayri (algo) endpoint'te -> trigger=True sart.
        # Bybit linear: kosullu emir normal id ile iptal edilir; ekstra parametre
        # ham istege eklenecegi icin gonderilmez.
        params = {} if self.exname == "bybit" else {"trigger": True}
        try:
            self.ex.cancel_order(order_id, psym, params)
        except ccxt.OrderNotFound:
            pass
        except Exception as e:  # noqa: BLE001
            log.warning("iptal %s %s: %s", psym, order_id, e)

    def cleanup_orders(self, psym: str) -> int:
        """Semboldeki tum acik tetik (SL/TP) emirlerini iptal eder."""
        params: Dict[str, Any] = {"trigger": True}
        if self.exname == "okx":
            params["ordType"] = "conditional"
        n = 0
        try:
            for o in self.ex.fetch_open_orders(psym, None, None, params):
                self._cancel(psym, str(o["id"]))
                n += 1
        except Exception as e:  # noqa: BLE001
            log.warning("cleanup %s: %s", psym, e)
        return n

    def _market_close(self, psym: str, side: str, qty: float) -> Dict[str, Any]:
        close_side = "sell" if side == "long" else "buy"
        return self.ex.create_order(psym, "market", close_side, qty, None, self._order_params({"reduceOnly": True}))

    # ---------- giris ----------
    def open_position(self, symbol: str, side: str, plan: SizePlan, sl_dist: float, tp_dist: float) -> Dict[str, Any]:
        psym = perp_symbol(symbol)
        self.prepare(symbol)
        mi = self.market_info(symbol)
        if self._fetch_position(psym, side) is not None or self._fetch_position(psym, "short" if side == "long" else "long"):
            raise ExecutionError(f"{psym} icin borsada zaten acik pozisyon var; bot ust uste binmez")
        self.cleanup_orders(psym)  # eski yetim tetik emirleri

        order_side = "buy" if side == "long" else "sell"
        order = self.ex.create_order(psym, "market", order_side, plan.qty, None, self._order_params())
        log.info("Giris emri: %s %s %s qty=%s id=%s", self.exname, psym, order_side, plan.qty, order.get("id"))

        pos = None
        for _ in range(8):
            time.sleep(1.0)
            pos = self._fetch_position(psym, side)
            if pos is not None:
                break
        if pos is None:
            raise ExecutionError("Emir gonderildi ama pozisyon gorunmuyor! Borsayi elle kontrol edin.")

        qty = float(pos["contracts"])
        entry = float(pos.get("entryPrice") or order.get("average") or plan.entry)
        liq = pos.get("liquidationPrice")
        liq = float(liq) if liq else None
        mmode = (pos.get("marginMode") or "").lower()
        d = 1 if side == "long" else -1
        sl = mi.price_to_precision(entry - d * sl_dist)
        tp = mi.price_to_precision(entry + d * tp_dist)

        problems: List[str] = []
        if self.cfg.require_isolated and mmode and mmode != "isolated":
            problems.append(f"marjin modu '{mmode}' (izole bekleniyordu)")
        if liq:
            if (side == "long" and not liq < sl) or (side == "short" and not liq > sl):
                problems.append(f"likidasyon {liq} stop {sl}'in onunde")
            elif abs(entry - sl) >= 0.7 * abs(entry - liq):
                problems.append(f"stop likidasyona cok yakin (liq {liq})")
        if problems:
            self._emergency_close(psym, side, qty)
            raise ExecutionError("Pozisyon guvenlik kontrolunden gecemedi ve kapatildi: " + "; ".join(problems))

        sl_id = None
        last_err: Optional[Exception] = None
        for attempt in range(3):
            try:
                sl_id = self._place_stop(psym, side, qty, sl)
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
                log.error("SL denemesi %d basarisiz: %s", attempt + 1, e)
                time.sleep(1.5)
        if sl_id is None:
            self._emergency_close(psym, side, qty)
            raise ExecutionError(f"Stop-loss konamadi, pozisyon kapatildi: {last_err}")

        tp_id = None
        try:
            tp_id = self._place_tp(psym, side, qty, tp)
        except Exception as e:  # noqa: BLE001
            log.error("TP konamadi (SL aktif, izlemede tekrar denenecek): %s", e)

        return {"entry": entry, "qty": qty, "sl": sl, "tp": tp, "liq": liq, "sl_order_id": sl_id, "tp_order_id": tp_id}

    def _emergency_close(self, psym: str, side: str, qty: float) -> None:
        try:
            self._market_close(psym, side, qty)
        except Exception as e:  # noqa: BLE001
            log.critical("ACIL KAPATMA BASARISIZ %s: %s", psym, e)
        self.cleanup_orders(psym)

    # ---------- izleme ----------
    def check(self, t: Trade) -> PositionStatus:
        psym = perp_symbol(t.symbol)
        pos = self._fetch_position(psym, t.side)
        if pos is not None:
            if not t.tp_order_id:  # TP eksikse tekrar dene
                try:
                    t.tp_order_id = self._place_tp(psym, t.side, float(pos["contracts"]), t.tp)
                except Exception as e:  # noqa: BLE001
                    log.warning("TP tekrar denemesi: %s", e)
            mark = pos.get("markPrice")
            return PositionStatus(True, mark=float(mark) if mark else None)
        # Pozisyon kapanmis -> cikis fiyatini islemlerden bul
        exit_px, fees = self._exit_from_fills(psym, t)
        self.cleanup_orders(psym)
        if exit_px is None:
            exit_px = self.last_price(t.symbol)
        return PositionStatus(False, exit_price=exit_px, exit_reason=_exit_reason(t, exit_px), fees=fees)

    def _exit_from_fills(self, psym: str, t: Trade):
        close_side = "sell" if t.side == "long" else "buy"
        try:
            fills = self.ex.fetch_my_trades(psym, since=t.opened_at)
        except Exception as e:  # noqa: BLE001
            log.warning("fetch_my_trades: %s", e)
            return None, None
        qty = 0.0
        val = 0.0
        fees = 0.0
        for f in fills:
            if f.get("side") != close_side or f.get("timestamp", 0) < t.opened_at:
                continue
            a = float(f.get("amount") or 0.0)
            qty += a
            val += a * float(f.get("price") or 0.0)
            fee = f.get("fee") or {}
            if fee.get("currency") in ("USDT", None) and fee.get("cost") is not None:
                fees += abs(float(fee["cost"]))
        if qty <= 0:
            return None, None
        return val / qty, fees

    def move_stop(self, t: Trade, new_sl: float) -> str:
        psym = perp_symbol(t.symbol)
        pos = self._fetch_position(psym, t.side)
        if pos is None:
            raise ExecutionError("Pozisyon yok, stop tasinmadi")
        new_sl = self.market_info(t.symbol).price_to_precision(new_sl)
        new_id = self._place_stop(psym, t.side, float(pos["contracts"]), new_sl)  # once yeni
        self._cancel(psym, t.sl_order_id)  # sonra eski
        return new_id

    def close_position(self, t: Trade) -> PositionStatus:
        psym = perp_symbol(t.symbol)
        pos = self._fetch_position(psym, t.side)
        self.cleanup_orders(psym)
        if pos is not None:
            o = self._market_close(psym, t.side, float(pos["contracts"]))
            time.sleep(1.0)
            log.info("Manuel kapatma emri %s", o.get("id"))
        exit_px, fees = self._exit_from_fills(psym, t)
        if exit_px is None:
            exit_px = self.last_price(t.symbol)
        return PositionStatus(False, exit_price=exit_px, exit_reason="MANUEL", fees=fees)

    def on_closed(self, t: Trade) -> None:
        pass

    def fee_for(self, t: Trade, exit_price: float) -> tuple:
        return realized_pnl(t.side, t.entry_price, exit_price, t.base_qty, self.cfg.fee_rate)
