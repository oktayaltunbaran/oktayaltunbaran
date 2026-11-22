"""Faz 0 guvenlik: stop bekcisi, belirsiz giris, uzlastirma (fail-closed), kilit, isinma, API anahtari uyarisi."""

import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

import ccxt

from bot import indicators as ta
from bot.engine import Engine
from bot.execution import LiveBroker
from bot.storage import Storage, Trade
from tests.helpers import FakeTelegram, settings
from tests.test_data_backtest import random_rows
from tests.test_execution import FakeExchange, broker, plan


class GuardExchange(FakeExchange):
    """FakeExchange + tetik emirlerinin listelenmesi (stop bekcisi icin)."""

    def __init__(self, *a, fail_list=False, fail_place=0, immediate=False, **kw):
        super().__init__(*a, **kw)
        self.fail_list = fail_list
        self.fail_place = fail_place
        self.immediate = immediate

    def fetch_open_orders(self, sym, since=None, limit=None, params={}):
        if self.fail_list:
            raise ccxt.NetworkError("timeout")
        out = []
        for oid, p in self.open_orders.items():
            o = {"id": oid}
            if "stopLossPrice" in p:
                o["stopLossPrice"] = p["stopLossPrice"]
            if "takeProfitPrice" in p:
                o["takeProfitPrice"] = p["takeProfitPrice"]
            out.append(o)
        return out

    def create_order(self, sym, typ, side, amount, price=None, params={}):
        if "stopLossPrice" in params and self.positions:
            if self.immediate:
                raise ccxt.InvalidOrder('binance {"code":-2021,"msg":"Order would immediately trigger."}')
            if self.fail_place > 0:
                self.fail_place -= 1
                raise ccxt.ExchangeError("gecici hata")
        return super().create_order(sym, typ, side, amount, price, params)


def live(name="binance", **kw):
    cfg, b = broker(name)
    b.ex = GuardExchange(name, **kw)
    return cfg, b


def open_trade(b, cfg):
    res = b.open_position("X/USDT", "long", plan(cfg, b), 1.5, 3.0)
    t = Trade("live", b.exname, "X/USDT", "long", res["qty"], 1.0, res["entry"], res["sl"], res["sl"], res["tp"],
              1.0, 50, 0, 0, sl_order_id=res["sl_order_id"], tp_order_id=res["tp_order_id"])
    return t


@mock.patch("bot.execution.time.sleep", lambda *_: None)
class TestStopGuard(unittest.TestCase):
    def test_missing_stop_is_recreated(self):
        cfg, b = live()
        t = open_trade(b, cfg)
        b.ex.open_orders.pop(t.sl_order_id)  # birisi stopu elle sildi
        st = b.check(t)
        self.assertTrue(st.open)
        self.assertIn(t.sl_order_id, b.ex.open_orders)
        self.assertEqual(b.ex.open_orders[t.sl_order_id]["stopLossPrice"], t.sl)
        self.assertTrue(any("yeniden kuruldu" in n for n in st.notes))

    def test_stop_cannot_be_placed_closes_position(self):
        cfg, b = live()
        t = open_trade(b, cfg)
        b.ex.open_orders.pop(t.sl_order_id)
        b.ex.fail_place = 5
        st = b.check(t)
        self.assertFalse(st.open)
        self.assertEqual(st.exit_reason, "KORUMA")
        self.assertEqual(b.ex.positions, {})

    def test_immediate_trigger_closes_without_retry(self):
        cfg, b = live()
        t = open_trade(b, cfg)
        b.ex.open_orders.pop(t.sl_order_id)
        b.ex.immediate = True
        st = b.check(t)
        self.assertFalse(st.open)
        self.assertEqual(b.ex.positions, {})

    def test_list_failure_does_nothing(self):
        cfg, b = live()
        t = open_trade(b, cfg)
        b.ex.open_orders.clear()
        b.ex.fail_list = True  # emir listesi okunamadi -> 'emir yok' VARSAYMA
        n_orders = len([c for c in b.ex.calls if c[0] == "create_order"])
        st = b.check(t)
        self.assertTrue(st.open)
        self.assertEqual(len([c for c in b.ex.calls if c[0] == "create_order"]), n_orders)

    def test_guard_rate_limited(self):
        cfg, b = live()
        t = open_trade(b, cfg)
        b.check(t)
        n = len([c for c in b.ex.calls if c[0] == "fetch_open_orders"])
        b.check(t)  # 60 sn dolmadi
        self.assertEqual(len([c for c in b.ex.calls if c[0] == "fetch_open_orders"]), n)

    def test_missing_tp_recreated(self):
        cfg, b = live()
        t = open_trade(b, cfg)
        b.ex.open_orders.pop(t.tp_order_id)
        st = b.check(t)
        self.assertIn(t.tp_order_id, b.ex.open_orders)
        self.assertTrue(any("hedef" in n for n in st.notes))


class TimeoutEntryExchange(GuardExchange):
    def __init__(self, *a, opens=True, **kw):
        super().__init__(*a, **kw)
        self.opens = opens

    def create_order(self, sym, typ, side, amount, price=None, params={}):
        if not params.get("reduceOnly") and "stopLossPrice" not in params and "takeProfitPrice" not in params:
            self.calls.append(("create_order", sym, typ, side, amount, dict(params)))
            if self.opens:  # emir borsaya ulasti ama yanit kayboldu
                self.positions[sym] = {"symbol": sym, "contracts": amount, "side": "long", "entryPrice": self.price,
                                       "liquidationPrice": 80.5, "marginMode": "isolated", "markPrice": self.price}
            raise ccxt.RequestTimeout("read timeout")
        return super().create_order(sym, typ, side, amount, price, params)


@mock.patch("bot.execution.time.sleep", lambda *_: None)
class TestAmbiguousEntry(unittest.TestCase):
    def test_timeout_but_filled_gets_stop(self):
        cfg, b = broker("binance")
        b.ex = TimeoutEntryExchange("binance", opens=True)
        res = b.open_position("X/USDT", "long", plan(cfg, b), 1.5, 3.0)
        self.assertIsNotNone(res["sl_order_id"])  # korumasiz kalmadi
        entries = [c for c in b.ex.calls if c[0] == "create_order" and not c[5].get("reduceOnly")]
        self.assertEqual(len(entries), 1)  # kor yeniden gonderim YOK
        self.assertTrue(entries[0][5]["clientOrderId"].startswith("mb"))

    def test_timeout_not_filled_raises(self):
        cfg, b = broker("binance")
        b.ex = TimeoutEntryExchange("binance", opens=False)
        with self.assertRaises(Exception):
            b.open_position("X/USDT", "long", plan(cfg, b), 1.5, 3.0)
        self.assertEqual(b.ex.positions, {})


class ReconExchange(GuardExchange):
    def __init__(self, *a, fail=False, **kw):
        super().__init__(*a, **kw)
        self.fail = fail

    def fetch_positions(self, syms=None):
        if self.fail:
            raise ccxt.NetworkError("down")
        return super().fetch_positions(syms)


class TestReconcile(unittest.TestCase):
    def _engine(self, ex):
        cfg = settings(mode="live", exec_exchange="binance", symbols=["X/USDT"])
        st = Storage(cfg.data_dir / "r.sqlite3")
        self.addCleanup(st.close)
        b = LiveBroker(cfg, st)
        b.ex = ex
        tg = FakeTelegram()
        eng = Engine(cfg, tg=tg, md=object(), storage=st, broker=b)
        return eng, tg, st

    def test_fail_closed(self):
        eng, tg, st = self._engine(ReconExchange("binance", fail=True))
        self.assertFalse(eng.reconcile())
        self.assertFalse(eng.reconciled)

    def test_unknown_position_blocks_symbol_then_unblocks(self):
        ex = ReconExchange("binance")
        ex.positions["Y/USDT:USDT"] = {"symbol": "Y/USDT:USDT", "contracts": 1.0, "side": "short"}
        eng, tg, st = self._engine(ex)
        self.assertTrue(eng.reconcile())
        self.assertEqual(st.get("blocked_symbols"), ["Y/USDT"])
        self.assertIn("bilmedigi", tg.texts())
        n = len(tg.sent)
        eng.reconcile()  # ayni durum tekrar bildirilmez
        self.assertEqual(len(tg.sent), n)
        ex.positions.clear()
        eng.reconcile()
        self.assertEqual(st.get("blocked_symbols"), [])
        self.assertIn("kilidi kalkti", tg.texts())

    def test_auth_error_message(self):
        eng, tg, st = self._engine(ReconExchange("binance"))
        eng.notify_error("test", ccxt.AuthenticationError("invalid api-key"))
        self.assertIn("API anahtari reddedildi", tg.texts())


class TestLockAndWarmup(unittest.TestCase):
    def test_single_instance_lock(self):
        d = Path(tempfile.mkdtemp())
        code = textwrap.dedent(f"""
            import sys, time; sys.path.insert(0, {json.dumps(str(Path.cwd()))})
            from pathlib import Path
            from bot.__main__ import acquire_lock
            print(acquire_lock(Path({json.dumps(str(d))}) / "bot.lock"), flush=True)
            time.sleep(3)
        """)
        p1 = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
        self.assertEqual(p1.stdout.readline().strip(), "True")
        p2 = subprocess.run([sys.executable, "-c", code.replace("time.sleep(3)", "")], capture_output=True, text=True)
        self.assertEqual(p2.stdout.strip(), "False")
        p1.kill()
        p1.wait()
        p1.stdout.close()

    def test_supertrend_warmup_1000_equals_full_history(self):
        # Canli bot ~1000 mum ceker; ozyinelemeli Supertrend uzun gecmisle ayni sinyali vermeli
        rows = random_rows(5000, seed=11)
        h = [r[2] for r in rows]
        lo = [r[3] for r in rows]
        c = [r[4] for r in rows]
        _, full = ta.supertrend(h, lo, c, 10, 3.0)
        efull = ta.ema(c, 200)
        for end in range(2000, 5000, 500):
            w = slice(end - 1000, end)
            _, part = ta.supertrend(h[w], lo[w], c[w], 10, 3.0)
            self.assertEqual(part[-300:], full[end - 300:end])
            ew = ta.ema(c[w], 200)
            self.assertLess(abs(ew[-1] - efull[end - 1]) / efull[end - 1], 1e-4)


if __name__ == "__main__":
    unittest.main()
