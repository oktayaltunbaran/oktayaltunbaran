import itertools
import unittest
from unittest import mock

import ccxt

from bot.execution import ExecutionError, LiveBroker
from bot.risk import size_position
from bot.storage import Storage, Trade
from tests.helpers import FakeMarket, settings


class FakeExchange(FakeMarket):
    def __init__(self, name="binance", margin_mode="isolated", fail_sl=0, liq=None, **kw):
        super().__init__(**kw)
        self.name = name
        self.price = 100.0
        self.margin_mode = margin_mode
        self.fail_sl = fail_sl
        self.liq = liq
        self.calls = []
        self.positions = {}
        self.open_orders = {}
        self.fills = []
        self._ids = itertools.count(1)

    # hesap ayarlari
    def set_position_mode(self, hedged, symbol=None, params={}):
        self.calls.append(("set_position_mode", hedged))

    def set_margin_mode(self, mode, symbol=None, params={}):
        self.calls.append(("set_margin_mode", mode))

    def set_leverage(self, lev, symbol=None, params={}):
        self.calls.append(("set_leverage", lev, dict(params)))

    # veri
    def fetch_ticker(self, sym):
        return {"last": self.price}

    def fetch_balance(self):
        return {"free": {"USDT": 30.0}, "total": {"USDT": 30.0}}

    def fetch_positions(self, syms=None):
        return [dict(p) for p in self.positions.values()]

    def fetch_open_orders(self, sym, since=None, limit=None, params={}):
        self.calls.append(("fetch_open_orders", dict(params)))
        return [{"id": i} for i in self.open_orders]

    def fetch_my_trades(self, sym, since=None):
        return list(self.fills)

    # emirler
    def create_order(self, sym, typ, side, amount, price=None, params={}):
        params = dict(params)
        oid = str(next(self._ids))
        self.calls.append(("create_order", sym, typ, side, amount, params))
        if "stopLossPrice" in params:
            if self.fail_sl > 0:
                self.fail_sl -= 1
                raise ccxt.ExchangeError("SL reddedildi")
            self.open_orders[oid] = params
            return {"id": oid}
        if "takeProfitPrice" in params:
            self.open_orders[oid] = params
            return {"id": oid}
        if params.get("reduceOnly"):
            self.positions.pop(sym, None)
            self.fills.append({"side": side, "amount": amount, "price": self.price, "timestamp": 10**15})
            return {"id": oid}
        pside = "long" if side == "buy" else "short"
        liq = self.liq if self.liq is not None else (80.5 if pside == "long" else 119.5)
        self.positions[sym] = {"symbol": sym, "contracts": amount, "side": pside, "entryPrice": self.price,
                               "liquidationPrice": liq, "marginMode": self.margin_mode, "markPrice": self.price}
        return {"id": oid, "average": self.price}

    def cancel_order(self, oid, sym=None, params={}):
        self.calls.append(("cancel_order", oid, dict(params)))
        self.open_orders.pop(oid, None)


def broker(name="binance", **kw):
    cfg = settings(exec_exchange=name, mode="live")
    st = Storage(cfg.data_dir / "t.sqlite3")
    unittest.addModuleCleanup(st.close)
    b = LiveBroker(cfg, st)
    b.ex = FakeExchange(name, **kw)
    return cfg, b


def plan(cfg, b, side="long", sl_dist=1.5):
    mi = b.market_info("X/USDT")
    d = 1 if side == "long" else -1
    return size_position(cfg, side, 100.0, 100 - d * sl_dist, 100 + d * 3.0, mi.contract_size,
                         mi.amount_to_precision, mi.min_amount, mi.min_cost, 30.0)


@mock.patch("bot.execution.time.sleep", lambda *_: None)
class TestLiveBroker(unittest.TestCase):
    def test_open_long_binance(self):
        cfg, b = broker("binance")
        p = plan(cfg, b)
        res = b.open_position("X/USDT", "long", p, 1.5, 3.0)
        orders = [c for c in b.ex.calls if c[0] == "create_order"]
        self.assertEqual(len(orders), 3)
        _, sym, typ, side, amt, params = orders[0]
        self.assertEqual((sym, typ, side), ("X/USDT:USDT", "market", "buy"))
        self.assertNotIn("reduceOnly", params)
        sl = orders[1][5]
        self.assertEqual(orders[1][3], "sell")
        self.assertEqual(sl["stopLossPrice"], 98.5)
        self.assertTrue(sl["reduceOnly"])
        self.assertEqual(sl["workingType"], "MARK_PRICE")
        tp = orders[2][5]
        self.assertEqual(tp["takeProfitPrice"], 103.0)
        self.assertTrue(tp["reduceOnly"])
        self.assertEqual(res["sl"], 98.5)
        self.assertIn(("set_margin_mode", "isolated"), b.ex.calls)
        self.assertIn(("set_position_mode", False), b.ex.calls)

    def test_short_okx_params(self):
        cfg, b = broker("okx")
        p = plan(cfg, b, "short")
        b.open_position("X/USDT", "short", p, 1.5, 3.0)
        orders = [c for c in b.ex.calls if c[0] == "create_order"]
        self.assertEqual(orders[0][3], "sell")
        for o in orders:
            self.assertEqual(o[5]["marginMode"], "isolated")
        self.assertEqual(orders[1][5]["slTriggerPxType"], "mark")
        self.assertEqual(orders[1][3], "buy")
        self.assertEqual(orders[1][5]["stopLossPrice"], 101.5)
        lev = [c for c in b.ex.calls if c[0] == "set_leverage"][0]
        self.assertEqual(lev[2]["marginMode"], "isolated")

    def test_sl_failure_closes_position(self):
        cfg, b = broker("bybit", fail_sl=3)
        p = plan(cfg, b)
        with self.assertRaises(ExecutionError):
            b.open_position("X/USDT", "long", p, 1.5, 3.0)
        self.assertEqual(b.ex.positions, {})  # korumasiz pozisyon kalmadi
        closes = [c for c in b.ex.calls if c[0] == "create_order" and c[5].get("reduceOnly") and "stopLossPrice" not in c[5]]
        self.assertEqual(len(closes), 1)

    def test_sl_retry_succeeds(self):
        cfg, b = broker("bybit", fail_sl=2)
        res = b.open_position("X/USDT", "long", plan(cfg, b), 1.5, 3.0)
        self.assertIsNotNone(res["sl_order_id"])
        self.assertIn("X/USDT:USDT", b.ex.positions)

    def test_cross_margin_rejected(self):
        cfg, b = broker("bybit", margin_mode="cross")
        with self.assertRaises(ExecutionError):
            b.open_position("X/USDT", "long", plan(cfg, b), 1.5, 3.0)
        self.assertEqual(b.ex.positions, {})

    def test_liq_too_close_rejected(self):
        cfg, b = broker("binance", liq=98.0)  # likidasyon stoptan once
        with self.assertRaises(ExecutionError):
            b.open_position("X/USDT", "long", plan(cfg, b), 1.5, 3.0)
        self.assertEqual(b.ex.positions, {})

    def test_existing_position_refused(self):
        cfg, b = broker("binance")
        b.open_position("X/USDT", "long", plan(cfg, b), 1.5, 3.0)
        with self.assertRaises(ExecutionError):
            b.open_position("X/USDT", "short", plan(cfg, b, "short"), 1.5, 3.0)

    def _trade(self, b, res):
        return Trade("live", b.exname, "X/USDT", "long", res["qty"], 1.0, res["entry"], res["sl"], res["sl"],
                     res["tp"], 1.0, 50, 0, 0, sl_order_id=res["sl_order_id"], tp_order_id=res["tp_order_id"])

    def test_move_stop_new_before_cancel(self):
        cfg, b = broker("binance")
        res = b.open_position("X/USDT", "long", plan(cfg, b), 1.5, 3.0)
        t = self._trade(b, res)
        n0 = len(b.ex.calls)
        new_id = b.move_stop(t, 100.12)
        tail = b.ex.calls[n0:]
        kinds = [c[0] for c in tail]
        self.assertLess(kinds.index("create_order"), kinds.index("cancel_order"))
        self.assertEqual(tail[kinds.index("cancel_order")][1], res["sl_order_id"])
        self.assertEqual(tail[kinds.index("cancel_order")][2], {"trigger": True})
        self.assertIn(new_id, b.ex.open_orders)

    def test_check_closed_cleans_up_and_reads_fill(self):
        cfg, b = broker("binance")
        res = b.open_position("X/USDT", "long", plan(cfg, b), 1.5, 3.0)
        t = self._trade(b, res)
        # TP borsada tetiklendi: pozisyon yok, TP fill var, SL emri hala acik (yetim)
        b.ex.positions.clear()
        b.ex.open_orders.pop(res["tp_order_id"])
        b.ex.fills.append({"side": "sell", "amount": res["qty"], "price": 103.0, "timestamp": 10**15})
        st = b.check(t)
        self.assertFalse(st.open)
        self.assertEqual(st.exit_price, 103.0)
        self.assertEqual(st.exit_reason, "TP")
        self.assertEqual(b.ex.open_orders, {})  # yetim SL iptal edildi

    def test_check_open_retries_missing_tp(self):
        cfg, b = broker("binance")
        res = b.open_position("X/USDT", "long", plan(cfg, b), 1.5, 3.0)
        t = self._trade(b, res)
        t.tp_order_id = None
        st = b.check(t)
        self.assertTrue(st.open)
        self.assertIsNotNone(t.tp_order_id)

    def test_benign_setting_errors_ignored(self):
        cfg, b = broker("binance")

        def boom(*a, **k):
            raise ccxt.ExchangeError('binance {"code":-4046,"msg":"No need to change margin type."}')

        b.ex.set_margin_mode = boom
        b.prepare("X/USDT")  # hata firlatmamali


if __name__ == "__main__":
    unittest.main()
