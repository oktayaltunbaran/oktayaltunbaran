"""Supertrend stratejisi: sinyal, plan, iz suren stop yonetimi, cok pozisyon, backtest."""

import time
import unittest

from bot import indicators as ta
from bot.backtest import run_backtest
from bot.engine import Engine
from bot.execution import PaperBroker
from bot.storage import Storage
from bot.strategy import Strategy
from tests.helpers import TF, FakeMD, FakeTelegram, make_snapshot, make_st_candles, settings


def st_settings(**kw):
    base = dict(strategy="supertrend", max_sl_pct=6.0, risk_per_trade_usdt=1.0, max_daily_loss_usdt=3.0,
                max_consecutive_losses=6, max_open_positions=3)
    base.update(kw)
    return settings(**base)


class TestStSignal(unittest.TestCase):
    def test_long_flip_signal(self):
        cfg = st_settings()
        c = make_st_candles(+1)
        an = Strategy(cfg).analyze("X/USDT", c, make_snapshot(c[-1][4]), None)
        self.assertIsNotNone(an.signal, (an.checks, an.blocks))
        s = an.signal
        self.assertEqual(s.side, "long")
        self.assertEqual(s.tp, 0.0)  # sabit hedef yok
        # stop = ST cizgisi - 1 ATR
        self.assertAlmostEqual(s.sl, an.st_line - cfg.st_stop_atr * an.atr, places=6)
        self.assertLess(s.sl, an.st_line)

    def test_short_flip_signal(self):
        cfg = st_settings()
        c = make_st_candles(-1)
        an = Strategy(cfg).analyze("X/USDT", c, make_snapshot(c[-1][4], funding=-0.0001), None)
        self.assertEqual(an.signal.side, "short")
        self.assertGreater(an.signal.sl, an.st_line)

    def test_no_flip_gives_trigger_plan(self):
        cfg = st_settings()
        c = make_st_candles(+1)[:-1]  # donusten bir onceki mum: ST hala asagi
        an = Strategy(cfg).analyze("X/USDT", c, make_snapshot(c[-1][4]), None)
        self.assertIsNone(an.signal)
        pl = an.plan
        self.assertEqual(pl.side, "long")
        self.assertEqual(pl.current_trend, "short")
        self.assertAlmostEqual(pl.trigger, an.st_line)
        self.assertGreater(pl.trigger, an.close)  # long tetik fiyatin ustunde
        self.assertLess(pl.sl, pl.trigger)

    def test_ema200_filter(self):
        cfg = st_settings(ema_slow=300, ema_mid=50)
        c = make_st_candles(+1)
        st = Strategy(cfg)
        ind = st.compute(c)
        an = st.evaluate("X/USDT", ind, len(c) - 1, make_snapshot(c[-1][4]), None)
        es = ind["es"][-1]
        self.assertEqual(an.signal is not None, c[-1][4] > es)

    def test_max_sl_blocks(self):
        cfg = st_settings(max_sl_pct=0.5, min_sl_pct=0.1)
        c = make_st_candles(+1)
        an = Strategy(cfg).analyze("X/USDT", c, make_snapshot(c[-1][4]), None)
        self.assertIsNone(an.signal)
        self.assertTrue(any("Stop" in b for b in an.blocks))


class StHarness:
    def __init__(self, symbols=("X/USDT",), **kw):
        self.cfg = st_settings(symbols=list(symbols), auto_trade=True, **kw)
        now = int(time.time() * 1000)
        self.c = {}
        prices, snaps = {}, {}
        for k, sym in enumerate(symbols):
            base = make_st_candles(+1 if k % 2 == 0 else -1)
            last_open = now - TF - 60_000
            shift = last_open - base[-1][0]
            rows = [[r[0] + shift] + r[1:] for r in base]
            self.c[sym] = rows
            prices[sym] = rows[-1][4]
            snaps[sym] = make_snapshot(rows[-1][4], funding=0.0)
        self.md = FakeMD(self.c, snaps, prices)
        self.tg = FakeTelegram()
        self.st = Storage(self.cfg.data_dir / "s.sqlite3")
        unittest.addModuleCleanup(self.st.close)
        self.broker = PaperBroker(self.cfg, self.md, self.st)
        self.eng = Engine(self.cfg, tg=self.tg, md=self.md, storage=self.st, broker=self.broker)

    def next_bar(self, sym, mult):
        """Yeni bir 2s mum ekle (mevcut son mumu 1 mum geriye kaydirip)."""
        rows = self.c[sym]
        for r in rows:
            r[0] -= TF
        # zaman akti: acik/kapali islemlerin zaman damgalari da 1 mum geriye
        for t in self.st.open_trades() + self.st.closed_trades():
            t.opened_bar_ts -= TF
            t.opened_at -= TF
            if t.closed_at:
                t.closed_at -= TF
            if "managed_bar" in t.meta:
                t.meta["managed_bar"] -= TF
            self.st.update_trade(t)
        o = rows[-1][4]
        p = o * mult
        rows.append([rows[-1][0] + TF, o, max(o, p) * 1.002, min(o, p) * 0.998, p, 1.0])
        self.md.prices[sym] = p
        return rows


class TestStEngine(unittest.TestCase):
    def test_open_trail_and_exit_on_flip(self):
        h = StHarness()
        h.eng.run_cycle()
        t = h.st.open_trades()[0]
        self.assertEqual(t.side, "long")
        self.assertEqual(t.tp, 0.0)
        self.assertIsNone(t.tp_order_id)
        self.assertEqual(t.meta["strategy"], "supertrend")
        sl0 = t.sl
        self.assertLessEqual(abs(t.entry_price - t.sl) * t.base_qty, 1.0 + 1e-6)
        # trend devam: yukselen mumlar -> stop lehte tasinmali
        for _ in range(4):
            h.next_bar("X/USDT", 1.02)
            h.eng.run_cycle()
        t = h.st.open_trades()[0]
        self.assertGreater(t.sl, sl0)
        self.assertTrue(any("iz suren stop" in m["text"] for m in h.tg.sent))
        # hizli dusus: ST asagi doner -> kapanis
        for _ in range(12):
            if not h.st.open_trades():
                break
            h.next_bar("X/USDT", 0.985)
            h.eng.run_cycle()
        c = h.st.closed_trades()
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0].exit_reason, "ST-DONUS")
        # kapanan mumda yeniden (ters yone) giris yapilmadi
        self.assertEqual(h.st.open_trades(), [])

    def test_stop_never_loosens(self):
        h = StHarness()
        h.eng.run_cycle()
        t = h.st.open_trades()[0]
        sl0 = t.sl
        h.next_bar("X/USDT", 0.997)  # hafif aleyhte, ST donmedi
        h.eng.run_cycle()
        t2 = h.st.open_trades()[0]
        self.assertGreaterEqual(t2.sl, sl0)

    def test_paper_stop_hit_intrabar(self):
        h = StHarness()
        h.eng.run_cycle()
        t = h.st.open_trades()[0]
        ts = int(time.time() * 1000) + 60_000
        h.md.minute_candles["X/USDT"] = [[ts, t.entry_price, t.entry_price, t.sl * 0.99, t.sl * 0.99, 1]]
        h.eng.monitor()
        c = h.st.closed_trades()[0]
        self.assertEqual(c.exit_reason, "SL")
        self.assertLess(c.pnl_usdt, 0)
        self.assertLessEqual(-c.pnl_usdt, 1.0 * 1.05)

    def test_multiple_positions(self):
        h = StHarness(symbols=("A/USDT", "B/USDT", "C/USDT", "D/USDT"))
        h.eng.run_cycle()
        ot = h.st.open_trades()
        self.assertEqual(len(ot), 3)  # MAX_OPEN_POSITIONS
        self.assertEqual(len({t.symbol for t in ot}), 3)
        self.assertEqual({t.side for t in ot}, {"long", "short"})

    def test_analysis_and_signal_text(self):
        h = StHarness()
        h.cfg.auto_trade = False
        h.st.set("auto_trade", False)
        h.eng.run_cycle()
        txt = h.tg.sent[-1]["text"]
        self.assertIn("Supertrend", txt)
        self.assertNotIn("Hedef  <code>", txt)


class TestSummary(unittest.TestCase):
    def test_analiz_summary_and_detail(self):
        h = StHarness(symbols=("A/USDT", "B/USDT", "C/USDT"))
        h.cmd = lambda text: h.eng.on_update({"message": {"chat": {"id": 42}, "text": text}})
        h.cmd("/analiz")
        txt = h.tg.sent[-1]["text"]
        self.assertIn("Piyasa ozeti", txt)
        for c in ("A", "B", "C"):
            self.assertIn(c, txt)
        h.cmd("/analiz A")
        self.assertIn("A/USDT", h.tg.texts())

    def test_plan_block_text(self):
        h = StHarness(symbols=("A/USDT", "B/USDT", "C/USDT"))
        for sym in ("A/USDT",):
            h.c[sym].pop()  # donusten onceki mum -> plan
        h.eng.on_update({"message": {"chat": {"id": 42}, "text": "/analiz A"}})
        txt = h.tg.sent[-1]["text"]
        self.assertIn("Giris / cikis semasi", txt)
        self.assertIn("Tetik", txt)
        self.assertIn("Supertrend", txt)


class TestStBacktest(unittest.TestCase):
    def test_backtest_trailing(self):
        from tests.test_data_backtest import random_rows

        cfg = st_settings()
        res = run_backtest(cfg, random_rows(3000), "X")
        self.assertGreater(len(res.trades), 5)
        for t in res.trades:
            self.assertIn(t.reason, ("SL", "IZ-STOP", "ST-DONUS"))
            self.assertEqual(t.tp, 0.0)
            if t.reason == "SL":
                self.assertLessEqual(-t.pnl, cfg.risk_per_trade_usdt * 1.02)
        self.assertAlmostEqual(res.end_equity, cfg.paper_start_equity + sum(t.pnl for t in res.trades), places=6)

    def test_supertrend_matches_pine_reference(self):
        from tests.test_data_backtest import random_rows

        rows = random_rows(1500)
        H = [r[2] for r in rows]
        L = [r[3] for r in rows]
        C = [r[4] for r in rows]
        a = ta.atr(H, L, C, 10)
        up_p = dn_p = None
        tr = 1
        ref = []
        for i in range(len(C)):
            if a[i] is None:
                ref.append(None)
                continue
            hl2 = (H[i] + L[i]) / 2
            up, dn = hl2 - 3 * a[i], hl2 + 3 * a[i]
            up1 = up if up_p is None else up_p
            dn1 = dn if dn_p is None else dn_p
            if C[i - 1] > up1:
                up = max(up, up1)
            if C[i - 1] < dn1:
                dn = min(dn, dn1)
            if tr == -1 and C[i] > dn1:
                tr = 1
            elif tr == 1 and C[i] < up1:
                tr = -1
            up_p, dn_p = up, dn
            ref.append(tr)
        self.assertEqual(ta.supertrend(H, L, C, 10, 3.0)[1], ref)


if __name__ == "__main__":
    unittest.main()
