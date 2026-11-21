import unittest

from bot import indicators as ta


class TestIndicators(unittest.TestCase):
    def test_sma_ema_basic(self):
        v = [1, 2, 3, 4, 5, 6]
        self.assertEqual(ta.sma(v, 3), [None, None, 2.0, 3.0, 4.0, 5.0])
        e = ta.ema(v, 3)  # alpha 0.5, seed 2
        self.assertEqual(e[:2], [None, None])
        self.assertAlmostEqual(e[2], 2.0)
        self.assertAlmostEqual(e[3], 3.0)
        self.assertAlmostEqual(e[5], 5.0)

    def test_rsi_extremes(self):
        up = [float(i) for i in range(30)]
        self.assertEqual(ta.rsi(up, 14)[-1], 100.0)
        down = [float(30 - i) for i in range(30)]
        self.assertEqual(ta.rsi(down, 14)[-1], 0.0)
        flat = [5.0] * 30
        self.assertEqual(ta.rsi(flat, 14)[-1], 50.0)

    def test_rsi_known_value(self):
        # Wilder (1978) klasik ornegi civari: 14 bar degisimleri -> elle hesap
        closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
                  45.89, 46.03, 45.61, 46.28, 46.28]
        r = ta.rsi(closes, 14)
        self.assertAlmostEqual(r[14], 70.46, places=1)

    def test_atr_constant_range(self):
        h = [11.0] * 40
        l = [9.0] * 40
        c = [10.0] * 40
        a = ta.atr(h, l, c, 14)
        self.assertIsNone(a[13])
        self.assertAlmostEqual(a[14], 2.0)
        self.assertAlmostEqual(a[-1], 2.0)

    def test_adx_strong_trend_high(self):
        n = 80
        c = [100 + i for i in range(n)]
        h = [x + 0.5 for x in c]
        l = [x - 0.5 for x in c]
        d = ta.adx(h, l, c, 14)
        self.assertIsNone(d[26])
        self.assertIsNotNone(d[27])
        self.assertGreater(d[-1], 90)

    def test_lengths_and_short_input(self):
        self.assertEqual(ta.ema([1, 2], 5), [None, None])
        self.assertEqual(len(ta.adx([1] * 10, [1] * 10, [1] * 10, 14)), 10)
        with self.assertRaises(ValueError):
            ta.ema([1, 2, 3], 0)


if __name__ == "__main__":
    unittest.main()
