import unittest

from bot.exchanges import closed_candles
from bot.strategy import Strategy
from tests.helpers import TF, make_candles, make_snapshot, settings


class TestStrategy(unittest.TestCase):
    def setUp(self):
        self.cfg = settings()
        self.s = Strategy(self.cfg)

    def test_long_signal(self):
        c = make_candles(+1)
        an = self.s.analyze("X/USDT", c, make_snapshot(c[-1][4]), 1.0)
        self.assertIsNotNone(an.signal, an.checks + [("blocks", an.blocks)])
        sig = an.signal
        self.assertEqual(sig.side, "long")
        self.assertLess(sig.sl, sig.entry_ref)
        self.assertAlmostEqual(sig.tp - sig.entry_ref, 2 * (sig.entry_ref - sig.sl))
        self.assertAlmostEqual(sig.entry_ref - sig.sl, 1.5 * sig.atr)

    def test_short_signal(self):
        c = make_candles(-1)
        an = self.s.analyze("X/USDT", c, make_snapshot(c[-1][4], funding=-0.0001), None)
        self.assertIsNotNone(an.signal)
        self.assertEqual(an.signal.side, "short")
        self.assertGreater(an.signal.sl, an.signal.entry_ref)

    def test_no_pullback_no_signal(self):
        c = make_candles(+1, signal_bar=False)
        an = self.s.analyze("X/USDT", c, make_snapshot(c[-1][4]), None)
        self.assertEqual(an.bias, "long")
        self.assertIsNone(an.signal)

    def test_funding_blocks_crowded_long(self):
        c = make_candles(+1)
        an = self.s.analyze("X/USDT", c, make_snapshot(c[-1][4], funding=0.001), None)
        self.assertIsNone(an.signal)
        self.assertTrue(any("Funding" in b for b in an.blocks))

    def test_divergence_blocks(self):
        c = make_candles(+1)
        an = self.s.analyze("X/USDT", c, make_snapshot(c[-1][4], spread=0.01), None)
        self.assertIsNone(an.signal)
        self.assertTrue(any("sapma" in b for b in an.blocks))

    def test_missing_market_blocks_live(self):
        c = make_candles(+1)
        self.assertIsNone(self.s.analyze("X/USDT", c, None, None).signal)
        self.assertIsNotNone(self.s.analyze("X/USDT", c, None, None, require_market=False).signal)

    def test_insufficient_sources(self):
        c = make_candles(+1)
        snap = make_snapshot(c[-1][4])
        snap.per_exchange["okx"].perp = None
        snap.per_exchange["bybit"].perp = None
        an = self.s.analyze("X/USDT", c, snap, None)
        self.assertIsNone(an.signal)

    def test_max_sl_rejects(self):
        cfg = settings(max_sl_pct=0.5, min_sl_pct=0.1)
        c = make_candles(+1)
        an = Strategy(cfg).analyze("X/USDT", c, make_snapshot(c[-1][4]), None)
        self.assertIsNone(an.signal)
        self.assertTrue(any("volatilite" in b for b in an.blocks))

    def test_not_enough_bars(self):
        with self.assertRaises(ValueError):
            self.s.analyze("X/USDT", make_candles(+1, n=100), None, None)

    def test_closed_candles_drops_live_bar(self):
        c = [[0, 1, 1, 1, 1, 1], [TF, 1, 1, 1, 1, 1]]
        self.assertEqual(len(closed_candles(c, TF, now_ms=2 * TF - 1)), 1)
        self.assertEqual(len(closed_candles(c, TF, now_ms=2 * TF)), 2)


if __name__ == "__main__":
    unittest.main()
