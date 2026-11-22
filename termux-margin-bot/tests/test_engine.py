import time
import unittest

from bot.engine import Engine
from bot.execution import PaperBroker
from bot.storage import Storage
from tests.helpers import TF, FakeMD, FakeTelegram, make_candles, make_snapshot, settings


def fresh_candles(trend=+1):
    """Son mum ~1 dk once kapanmis olacak sekilde zaman damgalanmis sinyal mumlari."""
    now = int(time.time() * 1000)
    n = 320
    last_open = now - TF - 60_000
    c = make_candles(trend, n=n, start_ts=last_open - n * TF)
    live = [last_open + TF, c[-1][4], c[-1][4], c[-1][4], c[-1][4], 0]  # canli (kapanmamis) mum
    return c + [live]


class Harness:
    def __init__(self, trend=+1, auto=False, **cfgkw):
        self.cfg = settings(symbols=["X/USDT"], auto_trade=auto, **cfgkw)
        self.candles = fresh_candles(trend)
        price = self.candles[-2][4]
        self.md = FakeMD({"X/USDT": self.candles}, {"X/USDT": make_snapshot(price, funding=0.0001 * trend)},
                         {"X/USDT": price})
        self.tg = FakeTelegram()
        self.st = Storage(self.cfg.data_dir / "e.sqlite3")
        unittest.addModuleCleanup(self.st.close)
        self.broker = PaperBroker(self.cfg, self.md, self.st)
        self.eng = Engine(self.cfg, tg=self.tg, md=self.md, storage=self.st, broker=self.broker)

    @property
    def price(self):
        return self.md.prices["X/USDT"]

    def set_price(self, p):
        self.md.prices["X/USDT"] = p

    def minute(self, hi, lo, close, offset_ms=60_000):
        ts = int(time.time() * 1000) + offset_ms
        self.md.minute_candles.setdefault("X/USDT", []).append([ts, close, hi, lo, close, 1])

    def press(self, data, chat=42):
        self.eng.on_update({"callback_query": {"id": "c1", "data": data, "message": {"chat": {"id": chat}}}})

    def cmd(self, text, chat=42):
        self.eng.on_update({"message": {"chat": {"id": chat}, "text": text}})


class TestEngineFlow(unittest.TestCase):
    def test_confirm_flow_tp(self):
        h = Harness()
        h.eng.run_cycle()
        self.assertEqual(len(h.eng.pending), 1)
        msg = h.tg.sent[-1]
        self.assertIn("LONG", msg["text"])
        self.assertIsNotNone(msg["buttons"])
        pid = list(h.eng.pending)[0]
        h.press(f"open:{pid}")
        ot = h.st.open_trades()
        self.assertEqual(len(ot), 1)
        t = ot[0]
        self.assertEqual(t.side, "long")
        self.assertLess(t.sl, t.entry_price)
        self.assertLessEqual(abs(t.entry_price - t.sl) * t.base_qty, h.cfg.risk_per_trade_usdt)
        self.assertLessEqual(t.notional_usdt, h.cfg.max_notional_usdt)
        # TP'ye fitil
        h.minute(t.tp * 1.001, t.entry_price, t.tp)
        h.eng.monitor()
        self.assertEqual(h.st.open_trades(), [])
        closed = h.st.closed_trades()
        self.assertEqual(closed[0].exit_reason, "TP")
        self.assertGreater(closed[0].pnl_usdt, 0)
        self.assertAlmostEqual(h.broker.equity(), 30 + closed[0].pnl_usdt)
        self.assertIn("Pozisyon kapandi", h.tg.sent[-1]["text"])

    def test_same_bar_not_processed_twice(self):
        h = Harness()
        h.eng.run_cycle()
        h.eng.pending.clear()
        n = len(h.tg.sent)
        h.eng.run_cycle()
        self.assertEqual(len(h.tg.sent), n)
        self.assertEqual(h.eng.pending, {})

    def test_skip_and_unauthorized(self):
        h = Harness()
        h.eng.run_cycle()
        pid = list(h.eng.pending)[0]
        h.press(f"open:{pid}", chat=999)  # yabanci sohbet
        self.assertEqual(h.st.open_trades(), [])
        self.assertIn(pid, h.eng.pending)
        h.press(f"skip:{pid}")
        self.assertEqual(h.eng.pending, {})
        self.assertEqual(h.st.open_trades(), [])
        h.press(f"open:{pid}")  # ayni butona tekrar basma
        self.assertEqual(h.st.open_trades(), [])

    def test_auto_short_sl(self):
        h = Harness(trend=-1, auto=True)
        h.eng.run_cycle()
        t = h.st.open_trades()[0]
        self.assertEqual(t.side, "short")
        h.minute(t.sl * 1.001, t.entry_price * 0.999, t.sl)
        h.eng.monitor()
        c = h.st.closed_trades()[0]
        self.assertEqual(c.exit_reason, "SL")
        self.assertLess(c.pnl_usdt, 0)
        # kayip komisyon+kayma dahil risk limitini anlamli olcude asmamali
        self.assertLessEqual(-c.pnl_usdt, h.cfg.risk_per_trade_usdt * 1.05)

    def test_breakeven_then_be_exit(self):
        h = Harness(auto=True)
        h.eng.run_cycle()
        t = h.st.open_trades()[0]
        r = t.entry_price - t.sl
        h.minute(t.entry_price + 1.1 * r, t.entry_price, t.entry_price + 1.05 * r)
        h.eng.monitor()
        t2 = h.st.open_trades()[0]
        self.assertEqual(t2.breakeven_done, 1)
        self.assertGreater(t2.sl, t2.entry_price)  # komisyonu karsilayan BE
        h.minute(t2.entry_price + 0.5 * r, t2.sl * 0.999, t2.sl * 0.999, offset_ms=120_000)
        h.eng.monitor()
        c = h.st.closed_trades()[0]
        self.assertEqual(c.exit_reason, "BE")
        self.assertGreater(c.pnl_usdt, -0.1)

    def test_drift_rejects(self):
        h = Harness()
        h.eng.run_cycle()
        pid = list(h.eng.pending)[0]
        sig = h.eng.pending[pid]["an"].signal
        h.set_price(sig.entry_ref + 0.8 * sig.sl_dist)
        h.press(f"open:{pid}")
        self.assertEqual(h.st.open_trades(), [])
        self.assertIn("R:R bozuldu", h.tg.sent[-1]["text"])

    def test_consecutive_losses_pause(self):
        h = Harness(auto=True)
        for k in range(3):
            h.st.set("last_bar:X/USDT", None)
            h.eng.run_cycle()
            t = h.st.open_trades()[0]
            h.minute(t.entry_price, t.sl * 0.99, t.sl * 0.99, offset_ms=60_000 * (k + 1) * 10)
            h.eng.monitor()
            # kaybi onceki bir mumda gerceklesmis say (ayni mumda yeniden giris kurali)
            c = h.st.closed_trades()[-1]
            c.closed_at = h.candles[-2][0] - 1
            h.st.update_trade(c)
        self.assertEqual(len(h.st.closed_trades()), 3)
        self.assertTrue(any("Koruma devrede" in m["text"] for m in h.tg.sent))
        h.st.set("last_bar:X/USDT", None)
        h.eng.run_cycle()
        self.assertEqual(h.st.open_trades(), [])  # 4. islem acilmadi (gunluk limit / seri)
        h.cmd("/devam")
        g, _ = h.eng.guards()
        # Gunluk limit (3 x ~1.5 = 4.5) hala gecerli olabilir; seri sayaci sifirlandi
        self.assertTrue(g.allowed or "Gunluk" in g.reason)

    def test_stale_signal_not_traded(self):
        h = Harness(auto=True)
        # Son mumu 1 saat once kapanmis gibi kaydir
        for row in h.candles:
            row[0] -= 3_600_000
        h.eng.run_cycle()
        self.assertEqual(h.st.open_trades(), [])

    def test_one_position_rule(self):
        h = Harness(auto=True)
        h.eng.run_cycle()
        self.assertEqual(len(h.st.open_trades()), 1)
        h.st.set("last_bar:X/USDT", None)
        h.eng.run_cycle()
        self.assertEqual(len(h.st.open_trades()), 1)

    def test_commands(self):
        h = Harness()
        for c in ("/durum", "/analiz", "/ayarlar", "/rapor", "/yardim", "/pozisyon", "/oto", "/bilinmeyen"):
            h.cmd(c)
        self.assertTrue(any("Durum" in m["text"] for m in h.tg.sent))
        self.assertTrue(any("EMA21" in m["text"] for m in h.tg.sent))
        h.cmd("/oto ac")
        self.assertTrue(h.eng.auto)
        h.cmd("/dur")
        self.assertTrue(h.eng.paused)
        h.cmd("/devam")
        self.assertFalse(h.eng.paused)

    def test_manual_close(self):
        h = Harness(auto=True)
        h.eng.run_cycle()
        h.cmd("/kapat")
        data = h.tg.sent[-1]["buttons"][0][0]["callback_data"]
        self.assertTrue(data.startswith("close:") and data != "close:confirm")
        h.press("close:confirm")  # eski/sahte onay reddedilir
        self.assertEqual(len(h.st.open_trades()), 1)
        h.press(data)
        self.assertEqual(h.st.open_trades(), [])
        self.assertEqual(h.st.closed_trades()[0].exit_reason, "MANUEL")
        h.press(data)  # ikinci basis: tek kullanimlik
        self.assertIn("gecersiz", h.tg.answers[-1][1])

    def test_close_confirm_expires(self):
        h = Harness(auto=True)
        h.eng.run_cycle()
        h.cmd("/kapat")
        data = h.tg.sent[-1]["buttons"][0][0]["callback_data"]
        nonce = data.split(":")[1]
        h.eng.pending_close[nonce] -= 61
        h.press(data)
        self.assertEqual(len(h.st.open_trades()), 1)

    def test_heartbeat_once_per_day(self):
        h = Harness()
        h.eng.heartbeat()
        h.eng.heartbeat()
        self.assertEqual(sum("Bot calisiyor" in m["text"] for m in h.tg.sent), 1)

    def test_time_stop(self):
        h = Harness(auto=True, max_hold_candles=1)
        h.eng.run_cycle()
        t = h.st.open_trades()[0]
        t.opened_bar_ts -= 2 * TF
        h.st.update_trade(t)
        h.eng.monitor()
        self.assertTrue(h.st.closed_trades()[0].exit_reason.startswith("ZAMAN"))

    def test_next_cycle_alignment(self):
        h = Harness()
        t = 5 * TF + 123
        self.assertEqual(h.eng.compute_next_cycle(t), 6 * TF + h.cfg.candle_close_delay_sec * 1000)


if __name__ == "__main__":
    unittest.main()
