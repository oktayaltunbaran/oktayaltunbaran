import unittest

from bot.strategy import Strategy
from tests.helpers import TF, FakeMarket, make_candles, make_snapshot, settings
from tests.test_data_backtest import random_rows
from tests.test_engine import Harness


class TestTradePlan(unittest.TestCase):
    def test_plan_when_no_signal_long(self):
        cfg = settings()
        c = make_candles(+1, signal_bar=False)
        an = Strategy(cfg).analyze("X/USDT", c, make_snapshot(c[-1][4]), None)
        self.assertIsNone(an.signal)
        pl = an.plan
        self.assertIsNotNone(pl)
        self.assertEqual(pl.side, "long")
        self.assertAlmostEqual(pl.entry, an.ema_fast)
        self.assertLess(pl.zone_low, pl.entry)
        self.assertGreater(pl.zone_high, pl.entry)
        self.assertLess(pl.sl, pl.entry)
        self.assertAlmostEqual(pl.tp - pl.entry, cfg.tp_r_mult * (pl.entry - pl.sl))
        self.assertAlmostEqual(pl.entry - pl.sl, max(1.5 * an.atr, pl.entry * 0.004), delta=pl.entry * 0.004)
        self.assertTrue(pl.waiting_for)  # neyi bekledigini soyler

    def test_plan_short_mirror(self):
        cfg = settings()
        c = make_candles(-1, signal_bar=False)
        pl = Strategy(cfg).analyze("X/USDT", c, make_snapshot(c[-1][4], funding=-0.0001), None).plan
        self.assertEqual(pl.side, "short")
        self.assertGreater(pl.sl, pl.entry)
        self.assertLess(pl.tp, pl.entry)

    def test_no_plan_when_signal(self):
        c = make_candles(+1)
        an = Strategy(settings()).analyze("X/USDT", c, make_snapshot(c[-1][4]), None)
        self.assertIsNotNone(an.signal)
        self.assertIsNone(an.plan)


class HistExchange(FakeMarket):
    rateLimit = 0

    def __init__(self, rows):
        super().__init__(min_cost=5.0)
        self.rows = rows
        self.now = rows[-1][0] + TF + 1

    def parse_timeframe(self, tf):
        return TF // 1000

    def milliseconds(self):
        return self.now

    def fetch_ohlcv(self, sym, tf, since=None, limit=None):
        return [r for r in self.rows if since is None or r[0] >= since][: limit or 1000]


class TestBacktestCommand(unittest.TestCase):
    def test_telegram_backtest(self):
        h = Harness()
        rows = random_rows(3000)
        ex = HistExchange(rows)
        h.md.swap["binance"] = ex
        h.cmd("/backtest ETH 200")
        texts = h.tg.texts()
        self.assertIn("Backtest · ETH/USDT", texts)
        self.assertIn("Sermaye", texts)
        self.assertIn("200 gun", texts)  # istenen gun sayisi baslikta

    def test_analiz_shows_plan(self):
        h = Harness()
        h.candles[:] = make_candles(+1, signal_bar=False, start_ts=h.candles[0][0])
        h.cmd("/analiz")
        self.assertIn("Islem plani", h.tg.texts())
        self.assertIn("Giris bolgesi", h.tg.texts())


if __name__ == "__main__":
    unittest.main()
