"""ccxt'nin botun parametrelerini borsaya giden GERCEK HTTP istegine nasil
cevirdigini ag olmadan dogrular (Exchange.fetch yamalanir).

ccxt surumu yukseltildiginde once bu testler calistirilmalidir: Binance'in
kosullu emirleri algo endpoint'ine tasimasi gibi degisiklikler burada yakalanir.
"""

import json
import time
import unittest
from urllib.parse import parse_qs

from bot.config import ExchangeKeys
from bot.exchanges import make_client
from bot.execution import LiveBroker
from tests.helpers import settings

KEYS = ExchangeKeys("k" * 20, "s" * 20, "p" * 8)
SYM = "ETH/USDT:USDT"

BINANCE_INFO = {"symbols": [{
    "symbol": "ETHUSDT", "pair": "ETHUSDT", "contractType": "PERPETUAL", "deliveryDate": 4133404800000,
    "onboardDate": 1569398400000, "status": "TRADING", "baseAsset": "ETH", "quoteAsset": "USDT",
    "marginAsset": "USDT", "pricePrecision": 2, "quantityPrecision": 3, "baseAssetPrecision": 8,
    "quotePrecision": 8, "underlyingType": "COIN", "triggerProtect": "0.0500",
    "filters": [
        {"filterType": "PRICE_FILTER", "minPrice": "0.01", "maxPrice": "100000", "tickSize": "0.01"},
        {"filterType": "LOT_SIZE", "stepSize": "0.001", "maxQty": "10000", "minQty": "0.001"},
        {"filterType": "MARKET_LOT_SIZE", "stepSize": "0.001", "maxQty": "2000", "minQty": "0.001"},
        {"filterType": "MIN_NOTIONAL", "notional": "20"}],
    "orderTypes": ["MARKET", "STOP_MARKET", "TAKE_PROFIT_MARKET"], "timeInForce": ["GTC"]}]}

BYBIT_INST = {"retCode": 0, "retMsg": "OK", "time": 1, "result": {"category": "linear", "nextPageCursor": "", "list": [{
    "symbol": "ETHUSDT", "contractType": "LinearPerpetual", "status": "Trading", "baseCoin": "ETH",
    "quoteCoin": "USDT", "launchTime": "1585526400000", "deliveryTime": "0", "priceScale": "2",
    "leverageFilter": {"minLeverage": "1", "maxLeverage": "100.00", "leverageStep": "0.01"},
    "priceFilter": {"minPrice": "0.01", "maxPrice": "199999.98", "tickSize": "0.01"},
    "lotSizeFilter": {"maxOrderQty": "7240.00", "minOrderQty": "0.01", "qtyStep": "0.01", "minNotionalValue": "5"},
    "unifiedMarginTrade": True, "fundingInterval": 480, "settleCoin": "USDT"}]}}

OKX_INST = {"code": "0", "msg": "", "data": [{
    "alias": "", "baseCcy": "", "category": "1", "ctMult": "1", "ctType": "linear", "ctVal": "0.1",
    "ctValCcy": "ETH", "expTime": "", "instFamily": "ETH-USDT", "instId": "ETH-USDT-SWAP", "instType": "SWAP",
    "lever": "100", "listTime": "1611916828000", "lotSz": "0.01", "maxMktSz": "20000", "minSz": "0.01",
    "optType": "", "quoteCcy": "", "settleCcy": "USDT", "state": "live", "stk": "", "tickSz": "0.01",
    "uly": "ETH-USDT"}]}


def patched(name):
    ex = make_client(name, "swap", KEYS)
    log = []

    def fetch(url, method="GET", headers=None, body=None):
        path, _, qs = url.partition("?")
        log.append((method, path, qs, body))
        now = int(time.time() * 1000)
        if name == "binance":
            if path.endswith("/time"):
                return {"serverTime": now}
            if "exchangeInfo" in path:
                return BINANCE_INFO
            if "algoOrder" in path:
                return {"algoId": 321, "symbol": "ETHUSDT", "algoStatus": "NEW", "algoType": "CONDITIONAL"}
            return {"orderId": 1, "symbol": "ETHUSDT", "status": "NEW"}
        if name == "bybit":
            if "market/time" in path:
                return {"retCode": 0, "time": now, "result": {"timeSecond": str(now // 1000), "timeNano": str(now * 10**6)}}
            if "instruments-info" in path:
                return BYBIT_INST
            if "order/create" in path:
                return {"retCode": 0, "retMsg": "OK", "time": now, "result": {"orderId": "abc", "orderLinkId": ""}}
            return {"retCode": 0, "retMsg": "OK", "time": now, "result": {}}
        # okx
        if "public/time" in path:
            return {"code": "0", "data": [{"ts": str(now)}]}
        if "instruments" in path:
            return OKX_INST
        if "order-algo" in path or "cancel-algos" in path:
            return {"code": "0", "data": [{"algoId": "777", "sCode": "0", "sMsg": ""}]}
        if "trade/" in path:
            return {"code": "0", "data": [{"ordId": "1", "clOrdId": "", "sCode": "0", "sMsg": ""}]}
        return {"code": "0", "data": [{}]}

    ex.fetch = fetch
    ex.load_markets()
    return ex, log


def body(entry):
    method, path, qs, b = entry
    if b:
        try:
            d = json.loads(b)
            return d[0] if isinstance(d, list) else d
        except ValueError:
            qs = b + "&" + qs  # form-urlencoded govde
    return {k: v[0] for k, v in parse_qs(qs).items()}


def broker_with(ex, name):
    b = LiveBroker(settings(exec_exchange=name, mode="live"), storage=None)
    b.ex = ex
    return b


class TestBinanceWire(unittest.TestCase):
    def test_orders(self):
        ex, log = patched("binance")
        b = broker_with(ex, "binance")
        self.assertEqual(ex.market(SYM)["limits"]["cost"]["min"], 20.0)
        b._place_stop(SYM, "long", 0.03, 2950.0)
        b._place_tp(SYM, "long", 0.03, 3100.0)
        b._market_close(SYM, "long", 0.03)
        b._cancel(SYM, "321")
        orders = [e for e in log if "order" in e[1].lower()]
        sl, tp, close, cancel = (body(e) for e in orders[:4])
        self.assertTrue(orders[0][1].endswith("/fapi/v1/algoOrder"))
        self.assertEqual(sl["type"], "STOP_MARKET")
        self.assertEqual(sl["side"], "SELL")
        self.assertEqual(sl["triggerPrice"], "2950")
        self.assertEqual(sl["reduceOnly"], "true")
        self.assertEqual(sl["workingType"], "MARK_PRICE")
        self.assertEqual(sl["algoType"], "CONDITIONAL")
        self.assertEqual(tp["type"], "TAKE_PROFIT_MARKET")
        self.assertTrue(orders[2][1].endswith("/fapi/v1/order"))
        self.assertEqual((close["type"], close["reduceOnly"]), ("MARKET", "true"))
        self.assertEqual(orders[3][0], "DELETE")
        self.assertTrue(orders[3][1].endswith("/fapi/v1/algoOrder"))
        self.assertEqual(cancel["algoId"], "321")


class TestBybitWire(unittest.TestCase):
    def test_orders(self):
        ex, log = patched("bybit")
        b = broker_with(ex, "bybit")
        b._place_stop(SYM, "long", 0.03, 2950.0)
        b._place_tp(SYM, "long", 0.03, 3100.0)
        b._place_stop(SYM, "short", 0.03, 3100.0)
        b._cancel(SYM, "abc")
        creates = [body(e) for e in log if "order/create" in e[1]]
        sl_l, tp_l, sl_s = creates
        self.assertEqual((sl_l["side"], sl_l["triggerDirection"], sl_l["triggerPrice"]), ("Sell", 2, "2950"))
        self.assertTrue(sl_l["reduceOnly"])
        self.assertEqual(sl_l["triggerBy"], "MarkPrice")
        self.assertEqual(sl_l["orderType"], "Market")
        self.assertEqual((tp_l["side"], tp_l["triggerDirection"]), ("Sell", 1))
        self.assertEqual((sl_s["side"], sl_s["triggerDirection"]), ("Buy", 1))
        cancel = [body(e) for e in log if "order/cancel" in e[1]][0]
        self.assertEqual(cancel, {"symbol": "ETHUSDT", "orderId": "abc", "category": "linear"})


class TestOkxWire(unittest.TestCase):
    def test_orders(self):
        ex, log = patched("okx")
        b = broker_with(ex, "okx")
        self.assertEqual(b.market_info("ETH/USDT").contract_size, 0.1)
        b._place_stop(SYM, "long", 0.29, 2950.0)
        b._place_tp(SYM, "long", 0.29, 3100.0)
        b._market_close(SYM, "long", 0.29)
        b._cancel(SYM, "777")
        algos = [body(e) for e in log if e[1].endswith("order-algo")]
        sl, tp = algos
        self.assertEqual((sl["ordType"], sl["tdMode"], sl["side"]), ("conditional", "isolated", "sell"))
        self.assertEqual((sl["slTriggerPx"], sl["slOrdPx"], sl["slTriggerPxType"]), ("2950", "-1", "mark"))
        self.assertTrue(sl["reduceOnly"])
        self.assertEqual(sl["sz"], "0.29")
        self.assertEqual((tp["tpTriggerPx"], tp["tpOrdPx"]), ("3100", "-1"))
        close = [body(e) for e in log if "batch-orders" in e[1] or e[1].endswith("trade/order")][0]
        self.assertEqual((close["ordType"], close["tdMode"]), ("market", "isolated"))
        self.assertTrue(close["reduceOnly"])
        self.assertTrue(any(e[1].endswith("cancel-algos") for e in log))


if __name__ == "__main__":
    unittest.main()
