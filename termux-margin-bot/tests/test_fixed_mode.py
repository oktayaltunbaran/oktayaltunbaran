"""Kullanici semasi: 30$ x 5x, net %25 ROI hedef, net 2.5$ stop."""

import unittest

from bot.backtest import run_backtest
from bot.risk import RiskReject, realized_pnl, size_fixed
from tests.helpers import settings
from tests.test_data_backtest import random_rows
from tests.test_risk import trunc
from tests.test_supertrend import StHarness


def fx(**kw):
    base = dict(strategy="supertrend", risk_mode="fixed", fixed_margin_usdt=30.0, leverage=5, tp_roi_pct=25.0,
                sl_loss_usdt=2.5, max_sl_pct=6.0, max_daily_loss_usdt=5.0, max_open_positions=1,
                max_consecutive_losses=6)
    base.update(kw)
    return settings(**base)


class TestSizeFixed(unittest.TestCase):
    def test_net_loss_and_profit_exact(self):
        cfg = fx()
        for side in ("long", "short"):
            p = size_fixed(cfg, side, 100.0, 1.0, trunc(0.0001), None, 5.0, 30.0 / 0.97 + 1)
            self.assertAlmostEqual(p.notional, 150.0, delta=0.01)
            self.assertAlmostEqual(p.margin, 30.0, delta=0.01)
            loss, _ = realized_pnl(side, 100.0, p.sl, p.base_qty, cfg.fee_rate)
            slip = p.notional * cfg.slippage_pct / 100
            self.assertAlmostEqual(-loss + slip, 2.5, delta=0.01)  # net zarar = 2.5$
            gain, _ = realized_pnl(side, 100.0, p.tp, p.base_qty, cfg.fee_rate)
            self.assertGreaterEqual(gain - slip, 7.5 - 0.01)  # net kar >= %25 ROI
            self.assertAlmostEqual(p.loss_at_sl, 2.5, delta=0.01)

    def test_balance_cap_scales_down(self):
        cfg = fx()
        p = size_fixed(cfg, "long", 100.0, 1.0, trunc(0.0001), None, 5.0, 20.0)
        self.assertLessEqual(p.margin, 20.0 * 0.97 + 1e-6)
        self.assertTrue(p.capped_by_leverage)
        self.assertAlmostEqual(p.loss_at_sl, 2.5, delta=1e-6)  # zarar yine tam 2.5$

    def test_btc_min_notional_now_ok(self):
        cfg = fx()
        p = size_fixed(cfg, "long", 60000.0, 1.0, trunc(0.001), 0.001, 100.0, 40.0)
        self.assertGreaterEqual(p.notional, 100.0)

    def test_no_balance_rejects(self):
        with self.assertRaises(RiskReject):
            size_fixed(fx(), "long", 100.0, 1.0, trunc(0.001), None, 5.0, 0.0)

    def test_config_validation(self):
        cfg = fx(sl_loss_usdt=0.1)
        with self.assertRaises(Exception):
            cfg.validate()


class TestFixedEngine(unittest.TestCase):
    def test_signal_opens_fixed_trade(self):
        h = StHarness(**{k: v for k, v in dict(risk_mode="fixed", fixed_margin_usdt=30.0, tp_roi_pct=25.0,
                                                sl_loss_usdt=2.5, max_daily_loss_usdt=5.0,
                                                max_open_positions=1).items()})
        h.eng.run_cycle()
        t = h.st.open_trades()[0]
        self.assertGreater(t.tp, 0)
        self.assertEqual(t.meta["risk_mode"], "fixed")
        # 30$ bakiyede borsa giris komisyonunu da istedigi icin nominal ~145.5$
        self.assertAlmostEqual(t.notional_usdt, 145.5, delta=1.0)
        cost = t.notional_usdt * (2 * 0.0006 + 0.0005)
        loss = abs(t.entry_price - t.sl) / t.entry_price * t.notional_usdt + cost
        gain = abs(t.tp - t.entry_price) / t.entry_price * t.notional_usdt - cost
        self.assertAlmostEqual(loss, 2.5, delta=0.02)
        self.assertGreaterEqual(gain, 7.5 - 0.02)
        txt = h.tg.texts()
        self.assertIn("%25 ROI", txt)


class TestFixedBacktest(unittest.TestCase):
    def test_backtest_fixed(self):
        cfg = fx(paper_start_equity=1000.0)
        res = run_backtest(cfg, random_rows(3000), "X")
        self.assertGreater(len(res.trades), 5)
        for t in res.trades:
            self.assertIn(t.reason, ("SL", "TP"))
            if t.reason == "SL":
                self.assertAlmostEqual(t.pnl, -2.5, delta=0.1)
            else:
                self.assertGreaterEqual(t.pnl, 7.5 - 0.1)


if __name__ == "__main__":
    unittest.main()
