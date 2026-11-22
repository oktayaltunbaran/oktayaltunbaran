"""Ana motor: zamanlayici, sinyal dongusu, onay akisi, pozisyon izleme, komutlar.

Tek is parcacikli (single-threaded) olay dongusu bilincli bir tercihtir:
yaris durumu (race condition) yoktur, Android'de dusuk kaynak kullanir ve
davranisi deterministiktir. Dongu ~5 sn'lik Telegram long-poll ile atar.
"""

from __future__ import annotations

import logging
import secrets
import signal as _signal
import time
from typing import Any, Dict, List, Optional

from . import fmt
from .config import Settings
from .exchanges import MarketData, MarketSnapshot, closed_candles, perp_symbol
from .execution import ExecutionError, LiveBroker, PaperBroker
from .risk import RiskReject, check_guards, size_fixed, size_position, utc_day_start_ms
from .storage import Storage, Trade
from .strategy import Analysis, Strategy
from .telegram_api import Telegram, esc

log = logging.getLogger("bot.engine")

COMMANDS = [
    ("durum", "Bot, bakiye ve risk durumu"),
    ("analiz", "Tum sembolleri simdi analiz et (islem acmaz)"),
    ("pozisyon", "Acik pozisyon ayrintisi"),
    ("kapat", "Acik pozisyonu piyasa fiyatindan kapat"),
    ("rapor", "Performans istatistikleri"),
    ("dur", "Yeni islem acmayi duraklat"),
    ("devam", "Duraklatmayi kaldir"),
    ("oto", "Otomatik islem: /oto ac | /oto kapat"),
    ("backtest", "Gecmis veride test: /backtest [ETH] [gun]"),
    ("ayarlar", "Gecerli ayarlar"),
    ("yardim", "Komut listesi"),
]


def now_ms() -> int:
    return int(time.time() * 1000)


class Engine:
    def __init__(self, cfg: Settings, tg: Optional[Telegram] = None, md: Optional[MarketData] = None,
                 storage: Optional[Storage] = None, broker: Any = None):
        self.cfg = cfg
        self.storage = storage or Storage(cfg.data_dir / "bot.sqlite3")
        self.md = md or MarketData(cfg.data_exchanges)
        self.strategy = Strategy(cfg)
        self.tg = tg or Telegram(cfg.telegram_token, cfg.telegram_chat_id)
        if broker is not None:
            self.broker = broker
        elif cfg.is_live:
            self.broker = LiveBroker(cfg, self.storage)
        else:
            self.broker = PaperBroker(cfg, self.md, self.storage)
        self.pending: Dict[str, Dict[str, Any]] = {}
        self.running = True
        self.next_cycle_ms = 0
        self.last_monitor = 0.0
        self._last_err_notice = 0.0

    # ------------------------------------------------------------ helpers
    @property
    def auto(self) -> bool:
        return bool(self.storage.get("auto_trade", self.cfg.auto_trade))

    @property
    def paused(self) -> bool:
        return bool(self.storage.get("paused", False))

    def notify(self, text: str, **kw) -> Optional[int]:
        return self.tg.send(text, **kw)

    def notify_error(self, where: str, e: Exception) -> None:
        log.exception("%s: %s", where, e)
        if time.time() - self._last_err_notice > 600:  # en fazla 10 dk'da bir
            self._last_err_notice = time.time()
            self.notify(f"⚠️ <b>Hata</b> ({esc(where)}): <code>{esc(type(e).__name__)}: {esc(str(e)[:300])}</code>")

    def compute_next_cycle(self, t_ms: Optional[int] = None) -> int:
        t_ms = now_ms() if t_ms is None else t_ms
        tf = self.cfg.timeframe_ms
        boundary = (t_ms // tf + 1) * tf
        return boundary + self.cfg.candle_close_delay_sec * 1000

    def guards(self):
        day = self.storage.closed_trades(utc_day_start_ms(), mode=self.broker.mode)
        reset = int(self.storage.get("streak_reset_ms", 0))
        recent = self.storage.closed_trades(reset, mode=self.broker.mode)
        try:
            eq = self.broker.equity()
        except Exception as e:  # noqa: BLE001
            log.warning("equity: %s", e)
            eq = None
        return check_guards(self.cfg, day, recent, eq, self.paused), eq

    # ------------------------------------------------------------ analysis
    def analyze_symbol(self, symbol: str, record_oi: bool = False):
        raw = self.md.ohlcv(self.cfg.exec_exchange, symbol, self.cfg.timeframe, limit=max(1000, self.strategy.min_bars + 10))
        candles = closed_candles(raw, self.cfg.timeframe_ms)
        snap: Optional[MarketSnapshot]
        try:
            snap = self.md.snapshot(symbol)
        except Exception as e:  # noqa: BLE001
            log.warning("snapshot %s: %s", symbol, e)
            snap = None
        oi_change = None
        if snap is not None and snap.oi_total:
            prev = self.storage.prev_oi(symbol, snap.ts - self.cfg.timeframe_ms // 2)
            if prev:
                oi_change = (snap.oi_total - prev) / prev * 100
            if record_oi:
                self.storage.add_oi(symbol, snap.ts, snap.oi_total)
        an = self.strategy.analyze(symbol, candles, snap, oi_change)
        return an, snap, oi_change

    def plan_for(self, symbol: str, side: str, sl_dist: float, entry: Optional[float] = None):
        self.broker.prepare(symbol)
        mi = self.broker.market_info(symbol)
        price = entry if entry is not None else self.broker.last_price(symbol)
        d = 1 if side == "long" else -1
        sl = price - d * sl_dist
        tp = 0.0 if self.cfg.trailing else price + d * sl_dist * self.cfg.tp_r_mult
        try:
            free = self.broker.free_balance()
        except Exception as e:  # noqa: BLE001
            log.warning("free_balance: %s", e)
            free = None
        if self.cfg.fixed:
            return size_fixed(self.cfg, side, price, mi.contract_size, mi.amount_to_precision,
                              mi.min_amount, mi.min_cost, free)
        return size_position(
            self.cfg, side, price, sl, tp, mi.contract_size, mi.amount_to_precision, mi.min_amount, mi.min_cost, free
        )

    # ------------------------------------------------------------ cycle
    def run_cycle(self) -> None:
        cfg = self.cfg
        cand: List[tuple] = []
        summary: List[str] = []
        bar_close_limit = cfg.timeframe_ms // 4  # mum kapanisindan sonra en fazla 30 dk (2s icin)
        for sym in cfg.symbols:
            try:
                an, snap, oi = self.analyze_symbol(sym, record_oi=True)
            except Exception as e:  # noqa: BLE001
                self.notify_error(f"analiz {sym}", e)
                continue
            for t in self.storage.open_trades():
                if t.symbol == sym and t.mode == self.broker.mode and t.tp <= 0:
                    self.manage_trailing(t, an)
            key = f"last_bar:{sym}"
            if self.storage.get(key) == an.bar_ts:
                continue  # bu mum zaten islendi (yeniden baslatma vb.)
            self.storage.set(key, an.bar_ts)
            age = now_ms() - (an.bar_ts + cfg.timeframe_ms)
            fresh = age <= bar_close_limit
            summary.append(
                f"{esc(sym)}: {fmt.px(an.close)} · {an.bias} · RSI {an.rsi:.0f} · ADX {an.adx:.0f}"
                + (f" → {fmt.side_label(an.signal.side)}" if an.signal else "")
            )
            self.storage.log_signal(sym, an.signal.side if an.signal else None, "analyzed",
                                    {"blocks": an.blocks, "checks": an.checks, "fresh": fresh})
            if an.signal and fresh and self._closed_during(sym, an.bar_ts):
                # Bu mumda kapanan pozisyonun ardindan ayni mumda yeniden giris yok
                # (4 yillik testte "ters yone aninda donme" sinanmadi).
                self.storage.log_signal(sym, an.signal.side, "skipped_just_closed")
            elif an.signal and fresh:
                cand.append((an, snap, oi))
            elif an.signal and not fresh:
                log.info("%s sinyali bayat (mum %ss once kapandi), atlandi", sym, age // 1000)

        if cfg.cycle_report and summary:
            self.notify("🕑 <b>2s mum kapanisi</b>\n" + "\n".join(summary), silent=True)
        if not cand:
            return
        open_now = [t for t in self.storage.open_trades() if t.mode == self.broker.mode]
        held = {t.symbol for t in open_now}
        slots = self.cfg.max_open_positions - len(open_now)
        cand = [x for x in cand if x[0].symbol not in held]  # ayni sembolde ikinci pozisyon yok
        if slots <= 0 or not cand:
            if cand:
                for an, _, _ in cand:
                    self.storage.log_signal(an.symbol, an.signal.side, "skipped_max_positions")
                self.notify(
                    f"ℹ️ Sinyal(ler) atlandi: acik pozisyon sayisi limitte ({self.cfg.max_open_positions}): "
                    + ", ".join(f"{esc(a.symbol)} {a.signal.side}" for a, _, _ in cand),
                    silent=True,
                )
            return
        guard, _ = self.guards()
        if not guard.allowed:
            self.notify(f"⏸ Sinyal atlandi: {esc(guard.reason)}", silent=True)
            return
        # Bos yer kadar sinyal; once en guclu trend (ADX)
        cand.sort(key=lambda x: x[0].adx, reverse=True)
        for an, snap, oi in cand[:slots]:
            self.handle_signal(an, snap, oi)

    def _closed_during(self, symbol: str, bar_open_ms: int) -> bool:
        return any(t.symbol == symbol for t in self.storage.closed_trades(bar_open_ms, mode=self.broker.mode))

    def manage_trailing(self, t: Trade, an: Analysis) -> None:
        """Supertrend islemi: her yeni 2s kapanista
        1) Supertrend ters yone dondu -> piyasa emriyle cik
        2) aksi halde borsadaki felaket stopunu (ST cizgisi -/+ k*ATR) yalnizca LEHTE tasi."""
        if an.st_dir is None or an.st_line is None or an.bar_ts <= t.opened_bar_ts:
            return
        if t.meta.get("managed_bar") == an.bar_ts:
            return
        t.meta["managed_bar"] = an.bar_ts
        if an.st_dir != t.direction:
            try:
                st = self.broker.close_position(t)
                self.finalize(t, st.exit_price, "ST-DONUS")
            except Exception as e:  # noqa: BLE001
                self.notify_error("supertrend cikisi", e)
                self.storage.update_trade(t)
            return
        new_sl = self.strategy.st_stop(an.st_line, an.atr, t.side)
        if t.direction * (new_sl - t.sl) <= 0:
            self.storage.update_trade(t)
            return
        try:
            price = self.broker.last_price(t.symbol)
            if (t.side == "long" and new_sl >= price) or (t.side == "short" and new_sl <= price):
                self.storage.update_trade(t)
                return  # fiyat zaten stopun otesinde; borsa stopu/kapanis halleder
            t.sl_order_id = self.broker.move_stop(t, new_sl)
            old = t.sl
            t.sl = new_sl
            self.storage.update_trade(t)
            self.notify(f"🔁 {esc(t.symbol)} iz suren stop: <code>{fmt.px(old)}</code> → <code>{fmt.px(new_sl)}</code>",
                        silent=True)
        except Exception as e:  # noqa: BLE001
            self.storage.update_trade(t)
            self.notify_error("stop tasima", e)

    def handle_signal(self, an: Analysis, snap, oi) -> None:
        s = an.signal
        assert s is not None
        try:
            plan = self.plan_for(s.symbol, s.side, s.sl_dist)
        except RiskReject as e:
            self.storage.log_signal(s.symbol, s.side, "risk_reject", str(e))
            self.notify(f"{fmt.side_label(s.side)} {esc(s.symbol)} sinyali <b>risk kurali</b> nedeniyle reddedildi:\n{esc(e)}")
            return
        except Exception as e:  # noqa: BLE001
            self.notify_error(f"boyutlama {s.symbol}", e)
            return

        if self.auto:
            self.notify(fmt.signal_text(an, plan, snap, oi, self.cfg, self.broker.name, None))
            self.execute(an)
            return
        pid = secrets.token_hex(4)
        self.pending[pid] = {"an": an, "created": time.time(), "msg_id": None}
        buttons = [[
            {"text": "✅ Pozisyonu ac", "callback_data": f"open:{pid}"},
            {"text": "❌ Gec", "callback_data": f"skip:{pid}"},
        ]]
        mid = self.notify(fmt.signal_text(an, plan, snap, oi, self.cfg, self.broker.name, self.cfg.confirm_timeout_min),
                          buttons=buttons)
        self.pending[pid]["msg_id"] = mid
        self.storage.log_signal(s.symbol, s.side, "awaiting_confirm", {"pid": pid})

    def execute(self, an: Analysis) -> Optional[Trade]:
        s = an.signal
        assert s is not None
        open_now = [t for t in self.storage.open_trades() if t.mode == self.broker.mode]
        if any(t.symbol == s.symbol for t in open_now):
            self.notify(f"⛔ {esc(s.symbol)} icin zaten acik pozisyon var; yeni islem acilmadi.")
            return None
        if len(open_now) >= self.cfg.max_open_positions:
            self.notify(f"⛔ Acik pozisyon limiti dolu ({self.cfg.max_open_positions}); islem acilmadi.")
            return None
        guard, _ = self.guards()
        if not guard.allowed:
            self.notify(f"⛔ Islem acilmadi: {esc(guard.reason)}")
            return None
        try:
            price = self.broker.last_price(s.symbol)
            d = 1 if s.side == "long" else -1
            drift_r = d * (price - s.entry_ref) / s.sl_dist
            if drift_r > 0.5:
                raise RiskReject(f"Fiyat sinyalden bu yana lehte {drift_r:.2f}R kacti; R:R bozuldu")
            if drift_r < -0.5:
                raise RiskReject(f"Fiyat sinyalden bu yana aleyhte {drift_r:.2f}R gitti; kurulum bozuldu")
            plan = self.plan_for(s.symbol, s.side, s.sl_dist, entry=price)
            if self.cfg.fixed:
                sl_dist, tp_dist = abs(plan.entry - plan.sl), abs(plan.tp - plan.entry)
            else:
                sl_dist = s.sl_dist
                tp_dist = 0.0 if self.cfg.trailing else s.sl_dist * self.cfg.tp_r_mult
            res = self.broker.open_position(s.symbol, s.side, plan, sl_dist, tp_dist)
        except RiskReject as e:
            self.notify(f"⛔ Islem acilmadi: {esc(e)}")
            return None
        except ExecutionError as e:
            self.notify(f"🚨 <b>Yurutme hatasi</b>: {esc(e)}")
            log.error("ExecutionError: %s", e)
            return None
        except Exception as e:  # noqa: BLE001
            self.notify_error("islem acma", e)
            return None

        mi = self.broker.market_info(s.symbol)
        entry = float(res["entry"])
        t = Trade(
            mode=self.broker.mode,
            exchange=self.cfg.exec_exchange,
            symbol=s.symbol,
            side=s.side,
            qty=float(res["qty"]),
            contract_size=mi.contract_size,
            entry_price=entry,
            initial_sl=float(res["sl"]),
            sl=float(res["sl"]),
            tp=float(res["tp"]),
            risk_usdt=abs(entry - float(res["sl"])) * float(res["qty"]) * mi.contract_size,
            notional_usdt=entry * float(res["qty"]) * mi.contract_size,
            opened_at=now_ms(),
            opened_bar_ts=s.bar_ts,
            liq_price=res.get("liq"),
            sl_order_id=res.get("sl_order_id"),
            tp_order_id=res.get("tp_order_id"),
            meta={"signal_close": s.entry_ref, "atr": s.atr, "adx": an.adx, "rsi": an.rsi,
                  "strategy": self.cfg.strategy, "risk_mode": self.cfg.risk_mode},
        )
        self.storage.insert_trade(t)
        self.storage.log_signal(s.symbol, s.side, "opened", {"trade_id": t.id})
        self.notify(fmt.trade_open_text(t, self.broker.name))
        return t

    # ------------------------------------------------------------ monitor
    def monitor(self) -> None:
        for t in self.storage.open_trades():
            if t.mode != self.broker.mode:
                continue
            try:
                st = self.broker.check(t)
            except Exception as e:  # noqa: BLE001
                self.notify_error(f"izleme {t.symbol}", e)
                continue
            if not st.open:
                self.finalize(t, st.exit_price, st.exit_reason or "?")
                continue
            if t.tp <= 0:  # iz suren (supertrend) islem: stop/cikis mum kapanisinda yonetilir
                self.storage.update_trade(t)
                continue
            if t.meta.get("risk_mode") == "fixed":  # sabit sema: yalnizca borsadaki SL/TP
                self.storage.update_trade(t)
                continue
            # Breakeven: fiyat +BREAKEVEN_AT_R lehte gidince stop giris(+komisyon)'a
            if self.cfg.breakeven_at_r > 0 and not t.breakeven_done and st.mark:
                r = abs(t.entry_price - t.initial_sl)
                prog = t.direction * (st.mark - t.entry_price) / r if r > 0 else 0
                if prog >= self.cfg.breakeven_at_r:
                    new_sl = t.entry_price * (1 + t.direction * 2 * self.cfg.fee_rate)
                    valid = new_sl < st.mark if t.side == "long" else new_sl > st.mark
                    if valid:
                        try:
                            t.sl_order_id = self.broker.move_stop(t, new_sl)
                            t.sl = new_sl
                            t.breakeven_done = 1
                            self.notify(f"🛡 {esc(t.symbol)} stop basabase tasindi: <code>{fmt.px(new_sl)}</code>")
                        except Exception as e:  # noqa: BLE001
                            self.notify_error("stop tasima", e)
            # Zaman stopu
            held = (now_ms() - (t.opened_bar_ts + self.cfg.timeframe_ms)) // self.cfg.timeframe_ms
            if self.cfg.max_hold_candles > 0 and held >= self.cfg.max_hold_candles:
                try:
                    st2 = self.broker.close_position(t)
                    self.finalize(t, st2.exit_price, f"ZAMAN ({held} mum)")
                    continue
                except Exception as e:  # noqa: BLE001
                    self.notify_error("zaman stopu", e)
            self.storage.update_trade(t)

    def finalize(self, t: Trade, exit_price: Optional[float], reason: str) -> None:
        if exit_price is None:
            exit_price = self.broker.last_price(t.symbol)
        pnl, fees = self.broker.fee_for(t, exit_price)
        t.status = "closed"
        t.closed_at = now_ms()
        t.exit_price = exit_price
        t.pnl_usdt = pnl
        t.fees_usdt = fees
        t.exit_reason = reason
        self.storage.update_trade(t)
        self.broker.on_closed(t)
        self.notify(fmt.trade_close_text(t))
        guard, eq = self.guards()
        if not guard.allowed:
            self.notify(f"⏸ <b>Koruma devrede</b>: {esc(guard.reason)}")

    # ------------------------------------------------------------ commands
    def on_update(self, u: Dict[str, Any]) -> None:
        if "callback_query" in u:
            cq = u["callback_query"]
            chat = ((cq.get("message") or {}).get("chat") or {}).get("id")
            if chat != self.cfg.telegram_chat_id:
                log.warning("Yetkisiz callback: chat=%s", chat)
                return
            self.on_callback(cq)
            return
        msg = u.get("message") or {}
        chat = (msg.get("chat") or {}).get("id")
        if chat != self.cfg.telegram_chat_id:
            log.warning("Yetkisiz mesaj: chat=%s", chat)
            return
        text = (msg.get("text") or "").strip()
        if not text.startswith("/"):
            return
        parts = text.split()
        cmd = parts[0][1:].split("@")[0].lower()
        args = parts[1:]
        handler = getattr(self, f"cmd_{cmd}", None)
        if handler is None:
            self.notify("Bilinmeyen komut. /yardim")
            return
        try:
            handler(args)
        except Exception as e:  # noqa: BLE001
            self.notify_error(f"/{cmd}", e)

    def on_callback(self, cq: Dict[str, Any]) -> None:
        data = cq.get("data") or ""
        action, _, pid = data.partition(":")
        if action == "close" and pid == "confirm":
            self.tg.answer_callback(cq["id"], "Kapatiliyor…")
            self._close_open()
            return
        p = self.pending.pop(pid, None)
        if p is None:
            self.tg.answer_callback(cq["id"], "Bu sinyal artik gecerli degil")
            return
        an: Analysis = p["an"]
        if action == "skip":
            self.tg.answer_callback(cq["id"], "Gecildi")
            self.storage.log_signal(an.symbol, an.signal.side, "user_skip")
            if p.get("msg_id"):
                self.tg.edit(p["msg_id"], f"❌ <s>{esc(an.symbol)} {an.signal.side}</s> — gecildi")
            return
        if action == "open":
            if time.time() - p["created"] > self.cfg.confirm_timeout_min * 60:
                self.tg.answer_callback(cq["id"], "Sure doldu")
                return
            self.tg.answer_callback(cq["id"], "Emir gonderiliyor…")
            self.execute(an)

    def expire_pending(self) -> None:
        lim = self.cfg.confirm_timeout_min * 60
        for pid in [k for k, v in self.pending.items() if time.time() - v["created"] > lim]:
            p = self.pending.pop(pid)
            an = p["an"]
            self.storage.log_signal(an.symbol, an.signal.side, "expired")
            if p.get("msg_id"):
                self.tg.edit(p["msg_id"], f"⌛ {esc(an.symbol)} {an.signal.side} sinyalinin onay suresi doldu.")

    def cmd_start(self, args): self.cmd_yardim(args)

    def cmd_yardim(self, args):
        lines = ["<b>Margin Long/Short Bot</b>", ""] + [f"/{c} — {esc(d)}" for c, d in COMMANDS]
        self.notify("\n".join(lines))

    def cmd_durum(self, args):
        guard, eq = self.guards()
        ot = self.storage.open_trades()
        lines = [
            "<b>Durum</b>",
            f"Mod: <b>{self.broker.mode.upper()}</b> · {esc(self.broker.name)}",
            f"Oto islem: {'ACIK' if self.auto else 'KAPALI (onayli)'} · {'⏸ DURAKLATILDI' if self.paused else '▶️ aktif'}",
            f"Bakiye: {eq:.2f} USDT" if eq is not None else "Bakiye: okunamadi",
            f"Acik pozisyon: {len(ot)}",
            f"Risk: {'✅ islem acilabilir' if guard.allowed else '⛔ ' + esc(guard.reason)}",
            f"Sonraki analiz: {fmt.ts_str(self.next_cycle_ms)}",
            f"Semboller: {esc(', '.join(self.cfg.symbols))} · {self.cfg.timeframe}",
        ]
        day = self.storage.closed_trades(utc_day_start_ms(), mode=self.broker.mode)
        lines.append(f"Bugun: {len(day)} islem, {sum(t.pnl_usdt or 0 for t in day):+.2f} USDT")
        self.notify("\n".join(lines))

    def cmd_analiz(self, args):
        if not args and len(self.cfg.symbols) > 2:
            rows = []
            for sym in self.cfg.symbols:
                try:
                    raw = self.md.ohlcv(self.cfg.exec_exchange, sym, self.cfg.timeframe,
                                        limit=max(1000, self.strategy.min_bars + 10))
                    rows.append(self.strategy.analyze(sym, closed_candles(raw, self.cfg.timeframe_ms), None, None,
                                                      require_market=False))
                except Exception as e:  # noqa: BLE001
                    log.warning("ozet %s: %s", sym, e)
            self.notify(fmt.summary_text(rows, self.cfg.timeframe))
            return
        syms = [a.upper() if "/" in a else f"{a.upper()}/USDT" for a in args] or self.cfg.symbols
        for sym in syms:
            try:
                an, snap, oi = self.analyze_symbol(sym)
                self.notify(fmt.analysis_text(an, snap, oi, self.cfg.timeframe), silent=True)
            except Exception as e:  # noqa: BLE001
                self.notify(f"{esc(sym)}: analiz yapilamadi ({esc(type(e).__name__)}: {esc(str(e)[:200])})")

    def cmd_pozisyon(self, args):
        ot = self.storage.open_trades()
        if not ot:
            self.notify("Acik pozisyon yok.")
            return
        for t in ot:
            try:
                mark = self.broker.last_price(t.symbol)
            except Exception:  # noqa: BLE001
                mark = None
            upnl = t.direction * (mark - t.entry_price) * t.base_qty if mark else None
            self.notify("\n".join([
                f"{fmt.side_label(t.side)} <b>{esc(t.symbol)}</b> · {esc(t.mode)}",
                f"Giris {fmt.px(t.entry_price)} · Simdi {fmt.px(mark)}",
                f"Stop {fmt.px(t.sl)}{' (BE)' if t.breakeven_done else ''} · "
                + (f"Hedef {fmt.px(t.tp)}" if t.tp > 0 else "Cikis: Supertrend donusu") + f" · Liq {fmt.px(t.liq_price)}",
                f"Gerceklesmemis K/Z: <b>{fmt.usd(upnl)} USDT</b> (komisyon haric)",
                f"Acilis {fmt.ts_str(t.opened_at)}",
            ]))

    def cmd_kapat(self, args):
        if not self.storage.open_trades():
            self.notify("Acik pozisyon yok.")
            return
        self.notify("Acik pozisyon piyasa fiyatindan kapatilsin mi?",
                    buttons=[[{"text": "⚠️ Evet, kapat", "callback_data": "close:confirm"}]])

    def _close_open(self):
        for t in self.storage.open_trades():
            try:
                st = self.broker.close_position(t)
                self.finalize(t, st.exit_price, "MANUEL")
            except Exception as e:  # noqa: BLE001
                self.notify_error("kapatma", e)

    def cmd_rapor(self, args):
        allt = self.storage.closed_trades(0, mode=self.broker.mode)
        week = self.storage.closed_trades(now_ms() - 7 * 86_400_000, mode=self.broker.mode)
        self.notify(fmt.stats_text(week, "Son 7 gun") + "\n\n" + fmt.stats_text(allt, "Tum zamanlar"))

    def cmd_backtest(self, args):
        from .backtest import backtest_symbol

        syms = [a.upper() if "/" in a else f"{a.upper()}/USDT" for a in args if not a.isdigit()] or self.cfg.symbols
        days = next((int(a) for a in args if a.isdigit()), 365)
        days = max(30, min(days, 1095))
        self.notify(f"⏳ Backtest: {esc(', '.join(syms))} · {days} gun · {self.cfg.timeframe}. "
                    f"Veri indiriliyor, sembol basina ~10-30 sn surer…", silent=True)
        ex = self.md.swap[self.cfg.exec_exchange]
        for sym in syms:
            try:
                lines = backtest_symbol(self.cfg, ex, sym, days)
                self.notify(f"📊 <b>Backtest · {esc(sym)}</b>\n<pre>{esc(chr(10).join(lines))}</pre>")
            except Exception as e:  # noqa: BLE001
                self.notify(f"{esc(sym)}: backtest yapilamadi ({esc(type(e).__name__)}: {esc(str(e)[:200])})")
        self.notify(
            "<i>Varsayimlar kotumser: giris sonraki mum acilisi + kayma, ayni mumda SL ve TP varsa SL, "
            "komisyon dahil. Funding/OI filtresi gecmise uygulanmaz. Gecmis sonuc gelecegi garanti etmez.</i>",
            silent=True,
        )

    def cmd_dur(self, args):
        self.storage.set("paused", True)
        self.notify("⏸ Yeni islemler duraklatildi. Acik pozisyon (varsa) borsadaki SL/TP ile korunmaya devam eder.")

    def cmd_devam(self, args):
        self.storage.set("paused", False)
        self.storage.set("streak_reset_ms", now_ms())
        self.notify("▶️ Bot aktif. (Ust uste kayip sayaci sifirlandi; gunluk limit gecerliligini korur.)")

    def cmd_oto(self, args):
        if not args or args[0].lower() not in ("ac", "kapat"):
            self.notify(f"Oto islem su an {'ACIK' if self.auto else 'KAPALI'}. Kullanim: /oto ac | /oto kapat")
            return
        on = args[0].lower() == "ac"
        self.storage.set("auto_trade", on)
        self.notify("🤖 Otomatik islem ACIK: sinyaller onaysiz uygulanir." if on
                    else "🖐 Otomatik islem KAPALI: her sinyal onay ister.")

    def cmd_ayarlar(self, args):
        c = self.cfg
        self.notify("\n".join([
            "<b>Ayarlar</b> (degistirmek icin .env + yeniden baslatma)",
            f"Borsa {c.exec_exchange} · Mod {c.mode} · Testnet {c.use_testnet}",
            f"Marjin {c.margin_usdt:g} USDT · Kaldirac {c.leverage}x · Max nominal {c.max_notional_usdt:g}",
            f"Islem basi risk {c.risk_per_trade_usdt:g} · Gunluk max kayip {c.max_daily_loss_usdt:g}",
            f"Ust uste kayip limiti {c.max_consecutive_losses} · Min bakiye {c.min_equity_usdt:g}",
            f"Strateji: <b>{c.strategy}</b> · risk modu: <b>{c.risk_mode}</b>",
            (f"Sabit sema: {c.fixed_margin_usdt:g}$ x {c.leverage} = {c.fixed_margin_usdt * c.leverage:g}$ nominal · "
             f"hedef +%{c.tp_roi_pct:g} ROI (~{c.fixed_margin_usdt * c.tp_roi_pct / 100:g}$ net) · "
             f"stop -{c.sl_loss_usdt:g}$ net" if c.fixed else ""),
            (f"Supertrend({c.st_len},{c.st_mult:g}) + EMA{c.ema_slow} · stop ST∓{c.st_stop_atr:g}ATR "
             f"(%{c.min_sl_pct:g}–%{c.max_sl_pct:g}) · cikis: ST donusu" if c.trailing else
             f"SL {c.atr_sl_mult:g}×ATR (%{c.min_sl_pct:g}–%{c.max_sl_pct:g}) · TP {c.tp_r_mult:g}R · "
             f"BE {c.breakeven_at_r:g}R · maks. {c.max_hold_candles} mum"),
            f"Funding limit %{c.funding_limit * 100:g}",
        ]))

    # ------------------------------------------------------------ lifecycle
    def reconcile(self) -> None:
        """Acilista: DB ile borsa durumunu esitle."""
        if not isinstance(self.broker, LiveBroker):
            return
        known = {t.symbol for t in self.storage.open_trades()}
        for sym in self.cfg.symbols:
            try:
                psym = perp_symbol(sym)
                for side in ("long", "short"):
                    pos = self.broker._fetch_position(psym, side)
                    if pos is not None and sym not in known:
                        self.notify(f"⚠️ Borsada botun bilmedigi bir {side} {esc(sym)} pozisyonu var. "
                                    f"Bot buna dokunmaz; elle yonetin. Bu sembolde yeni islem acilmaz.")
            except Exception as e:  # noqa: BLE001
                log.warning("reconcile %s: %s", sym, e)
        self.monitor()  # DB'de acik ama borsada kapanmis olanlari kapatir

    def stop(self, *_):
        self.running = False

    def run(self) -> None:
        _signal.signal(_signal.SIGTERM, self.stop)
        _signal.signal(_signal.SIGINT, self.stop)
        self.tg.skip_pending()
        self.tg.set_commands(COMMANDS)
        startup = [f"🚀 <b>Bot basladi</b> · {self.broker.mode.upper()} · {esc(self.broker.name)}"]
        if isinstance(self.broker, LiveBroker):
            try:
                startup.append(esc(self.broker.self_test()))
            except Exception as e:  # noqa: BLE001
                startup.append(f"🚨 Borsa baglanti testi BASARISIZ: {esc(e)}")
        else:
            startup.append(f"Paper bakiye: {self.broker.equity():.2f} USDT")
        startup.append(f"{esc(', '.join(self.cfg.symbols))} · {self.cfg.timeframe} · oto islem {'acik' if self.auto else 'kapali'}")
        self.notify("\n".join(startup))
        try:
            self.reconcile()
        except Exception as e:  # noqa: BLE001
            self.notify_error("reconcile", e)

        # Acilista son kapanan mum henuz islenmediyse ve tazeyse hemen analiz et
        self.next_cycle_ms = now_ms()
        while self.running:
            try:
                for u in self.tg.get_updates(timeout=5):
                    self.on_update(u)
                if now_ms() >= self.next_cycle_ms:
                    self.next_cycle_ms = self.compute_next_cycle()
                    self.run_cycle()
                if time.time() - self.last_monitor >= self.cfg.monitor_interval_sec:
                    self.last_monitor = time.time()
                    self.monitor()
                self.expire_pending()
            except Exception as e:  # noqa: BLE001
                self.notify_error("ana dongu", e)
                time.sleep(5)
        self.notify("🛑 Bot durduruldu. Acik pozisyonlar borsadaki SL/TP emirleriyle korunuyor.")
        self.storage.close()
