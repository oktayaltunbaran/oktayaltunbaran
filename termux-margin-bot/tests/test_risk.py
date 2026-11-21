import math
import unittest

from bot.risk import RiskReject, check_guards, liquidation_estimate, realized_pnl, size_position
from bot.storage import Trade
from tests.helpers import settings


def trunc(step):
    return lambda x: math.floor(x / step + 1e-9) * step


class TestSizing(unittest.TestCase):
    def test_risk_respected(self):
        cfg = settings()  # risk 1.5, cap 150
        p = size_position(cfg, "long", 100.0, 98.5, 103.0, 1.0, trunc(0.001), 0.001, 5, 30)
        self.assertLessEqual(p.loss_at_sl, cfg.risk_per_trade_usdt + 1e-9)
        # 1.5 / (0.015 + 0.0012 + 0.0005) = 89.82
        self.assertAlmostEqual(p.notional, 89.82, delta=0.1)
        self.assertAlmostEqual(p.margin, p.notional / 5)
        self.assertFalse(p.capped_by_leverage)

    def test_leverage_cap(self):
        cfg = settings(risk_per_trade_usdt=10.0, max_daily_loss_usdt=20)
        p = size_position(cfg, "short", 100.0, 100.5, 99.0, 1.0, trunc(0.001), None, None, 30)
        self.assertLessEqual(p.notional, 150.0 + 1e-9)
        self.assertTrue(p.capped_by_leverage)

    def test_balance_cap(self):
        cfg = settings()
        p = size_position(cfg, "long", 100.0, 99.0, 102.0, 1.0, trunc(0.001), None, None, 10.0)
        self.assertLessEqual(p.margin, 10.0 * 0.97 + 1e-9)

    def test_min_cost_reject(self):
        cfg = settings()
        with self.assertRaises(RiskReject):
            size_position(cfg, "long", 100.0, 98.5, 103.0, 1.0, trunc(0.001), 0.001, 100.0, 30)

    def test_okx_contract_size(self):
        cfg = settings()
        # BTC ~ 60000, ctVal 0.01 BTC: tam kontrat adiminda 1 kontrat = 600 USDT > nominal -> 0
        with self.assertRaises(RiskReject):
            size_position(cfg, "long", 60000, 59100, 61800, 0.01, trunc(1), 1, None, 30)
        # OKX lotSz 0.01: 89.82 USDT / 600 = 0.1497 -> asagi yuvarlama 0.14 kontrat
        p = size_position(cfg, "long", 60000, 59100, 61800, 0.01, trunc(0.01), 0.01, None, 30)
        self.assertAlmostEqual(p.qty, 0.14)
        self.assertAlmostEqual(p.notional, 0.14 * 0.01 * 60000)
        # ETH ~ 3000, ctVal 0.1 ETH, lot 0.01 -> 1 kontrat = 300; 0.29 kontrat ok
        p = size_position(cfg, "long", 3000, 2955, 3090, 0.1, trunc(0.01), 0.01, None, 30)
        self.assertAlmostEqual(p.base_qty, p.qty * 0.1)
        self.assertLessEqual(p.loss_at_sl, 1.5 + 1e-9)

    def test_wrong_side(self):
        cfg = settings()
        with self.assertRaises(RiskReject):
            size_position(cfg, "long", 100, 101, 103, 1, trunc(0.001), None, None, 30)
        with self.assertRaises(RiskReject):
            size_position(cfg, "short", 100, 99, 97, 1, trunc(0.001), None, None, 30)

    def test_liq_estimate(self):
        self.assertAlmostEqual(liquidation_estimate("long", 100, 5, 0.005), 80.5)
        self.assertAlmostEqual(liquidation_estimate("short", 100, 5, 0.005), 119.5)

    def test_pnl(self):
        pnl, fees = realized_pnl("long", 100, 102, 1.0, 0.0005)
        self.assertAlmostEqual(fees, (100 + 102) * 0.0005)
        self.assertAlmostEqual(pnl, 2 - fees)
        pnl, _ = realized_pnl("short", 100, 102, 1.0, 0.0)
        self.assertAlmostEqual(pnl, -2)


def tr(pnl, closed=1):
    t = Trade("paper", "binance", "X/USDT", "long", 1, 1, 100, 99, 99, 102, 1, 100, 0, 0)
    t.status, t.pnl_usdt, t.closed_at = "closed", pnl, closed
    return t


class TestGuards(unittest.TestCase):
    def test_guards(self):
        cfg = settings()
        self.assertTrue(check_guards(cfg, [], [], 30, False).allowed)
        self.assertFalse(check_guards(cfg, [], [], 30, True).allowed)
        self.assertFalse(check_guards(cfg, [], [], 19.9, False).allowed)
        self.assertFalse(check_guards(cfg, [tr(-3), tr(-1.6)], [], 30, False).allowed)
        self.assertTrue(check_guards(cfg, [tr(-3), tr(1)], [], 30, False).allowed)
        streak = [tr(1), tr(-1), tr(-1), tr(-1)]
        self.assertFalse(check_guards(cfg, [], streak, 30, False).allowed)
        self.assertTrue(check_guards(cfg, [], streak[:-1], 30, False).allowed)


if __name__ == "__main__":
    unittest.main()
