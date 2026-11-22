import random
import unittest

from bot.backtest import report_lines, run_backtest, summarize
from bot.exchanges import MarketData, MarketSnapshot, ExchangeSnapshot
from bot.strategy import Strategy
from tests.helpers import TF, make_candles, settings


def random_rows(n=3000, seed=7):
    """Rastgele yuruyus + 400 mumda bir yon degistiren rejimler."""
    rnd = random.Random(seed)
    rows, p = [], 100.0
    for k in range(n):
        drift = 0.002 if (k // 400) % 2 == 0 else -0.002
        o = p
        p *= 1 + drift + rnd.gauss(0, 0.008)
        rows.append([k * TF, o, max(o, p) * (1 + abs(rnd.gauss(0, 0.003))),
                     min(o, p) * (1 - abs(rnd.gauss(0, 0.003))), p, 1])
    return rows


class PagedExchange:
    """OKX gibi: istek basina en fazla 300 mum, since'ten itibaren."""

    def __init__(self, n=1500, now=None):
        self.now = now or (10_000 * TF)
        self.rows = [[self.now - (n - k) * TF, 1, 2, 0.5, 1.5, 1] for k in range(n)]
        self.calls = 0
        self.markets = {}
        self.options = {"defaultType": "swap"}
        self.id = "paged"

    def parse_timeframe(self, tf):
        return TF // 1000

    def milliseconds(self):
        return self.now

    def fetch_ohlcv(self, sym, tf, since=None, limit=None):
        self.calls += 1
        rows = [r for r in self.rows if r[0] >= since]
        return rows[: min(limit or 300, 300)]


class TestOhlcvPaging(unittest.TestCase):
    def test_pages_to_1000(self):
        md = MarketData.__new__(MarketData)
        md._loaded = {}
        ex = PagedExchange()
        md.swap = {"okx": ex}
        md._ensure = lambda e: None
        out = md.ohlcv("okx", "ETH/USDT", "2h", limit=1000)
        self.assertEqual(len(out), 1000)
        self.assertEqual(out[-1][0], ex.rows[-1][0])
        self.assertTrue(all(b[0] - a[0] == TF for a, b in zip(out, out[1:])))  # bosluk / tekrar yok
        self.assertLessEqual(ex.calls, 5)


class TestSnapshotMath(unittest.TestCase):
    def test_aggregates(self):
        per = {
            "binance": ExchangeSnapshot("binance", 100, 100.1, 0.0001, 1e9),
            "bybit": ExchangeSnapshot("bybit", 100.2, 100.3, 0.0003, 5e8),
            "okx": ExchangeSnapshot("okx", None, None, None, None),
        }
        s = MarketSnapshot("X/USDT", 0, per)
        self.assertAlmostEqual(s.spot_median, 100.1)
        self.assertAlmostEqual(s.perp_median, 100.2)
        self.assertAlmostEqual(s.funding_avg, 0.0002)
        self.assertIsNone(s.oi_total)  # eksik borsa -> sahte OI dususu uretme
        self.assertEqual(s.sources_ok, 2)
        # spot: (100.2-100)/100.1 ; perp: (100.3-100.1)/100.2 -> buyugu
        self.assertAlmostEqual(s.divergence_pct, max(0.2 / 100.1, 0.2 / 100.2) * 100)
        # sadece baz farki (spot != perp) sapma sayilmaz
        per2 = {n: ExchangeSnapshot(n, 100, 100.4) for n in ("binance", "bybit")}
        self.assertAlmostEqual(MarketSnapshot("X", 0, per2).divergence_pct, 0.0)


class TestBacktest(unittest.TestCase):
    def test_evaluate_matches_analyze(self):
        cfg = settings()
        st = Strategy(cfg)
        c = make_candles(+1)
        a1 = st.analyze("X", c, None, None, require_market=False)
        a2 = st.evaluate("X", st.compute(c), len(c) - 1, None, None, require_market=False)
        self.assertEqual(a1.signal, a2.signal)
        self.assertEqual(a1.checks, a2.checks)

    def test_runs_and_accounts(self):
        cfg = settings()
        rows = random_rows()
        res = run_backtest(cfg, rows, "X")
        trades, end = res.trades, res.end_equity
        self.assertGreater(len(trades), 0)
        self.assertAlmostEqual(end, cfg.paper_start_equity + sum(t.pnl for t in trades), places=6)
        for t in trades:
            self.assertGreater(t.exit_ts, t.entry_ts)
            self.assertIn(t.reason, ("SL", "TP", "BE", "ZAMAN"))
            if t.reason == "SL":  # stop kaybi risk limitini (komisyon+kayma dahil) asmamali
                self.assertLessEqual(-t.pnl, cfg.risk_per_trade_usdt * 1.02)
        # pozisyonlar ust uste binmez
        for a, b in zip(trades, trades[1:]):
            self.assertGreaterEqual(b.entry_ts, a.exit_ts - TF)
        self.assertIn("Islem", summarize(trades, cfg.paper_start_equity, end))
        rep = "\n".join(report_lines(res, cfg.paper_start_equity, "X/USDT", "2h"))
        for key in ("Sermaye", "Isabet", "Kar fakt.", "Maks. dusus", "Son ", "Al-tut"):
            self.assertIn(key, rep)

    def test_min_cost_rejections_counted(self):
        cfg = settings()
        rows = random_rows()
        self.assertGreater(len(run_backtest(cfg, rows, "X").trades), 0)  # normalde islem var
        res = run_backtest(cfg, rows, "X", min_cost=10_000)  # hicbir islem acilamaz
        self.assertEqual(res.trades, [])
        self.assertGreater(res.rejected, 0)
        self.assertIn("acilamayan", "\n".join(report_lines(res, 30, "X/USDT", "2h")))


if __name__ == "__main__":
    unittest.main()
