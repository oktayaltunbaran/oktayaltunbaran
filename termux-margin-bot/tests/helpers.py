"""Test yardimcilari: sentetik mum uretici, sahte Telegram / borsa / piyasa verisi."""

from __future__ import annotations

import itertools
import math
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from bot import indicators as ta
from bot.config import Settings
from bot.exchanges import ExchangeSnapshot, MarketSnapshot

TF = 2 * 3600 * 1000


def make_candles(trend: int = 1, n: int = 320, start_ts: int = 0, signal_bar: bool = True) -> List[List[float]]:
    """Dalgali bir trend + (istege bagli) son mumda EMA21'e geri cekilip donus."""
    c: List[List[float]] = []
    p = 100.0
    for i in range(n):
        step = 0.006 if i % 5 < 3 else -0.0055
        o = p
        p *= 1 + trend * step
        c.append([start_ts + i * TF, o, max(o, p) * 1.002, min(o, p) * 0.998, p, 1.0])
    if signal_bar:
        closes = [x[4] for x in c]
        e = ta.ema(closes, 21)[-1]
        a = ta.atr([x[2] for x in c], [x[3] for x in c], closes, 14)[-1]
        if trend > 0:
            o, cl, lo = e + 0.1 * a, e + 0.5 * a, e - 0.1 * a
            hi = cl + 0.1 * a
        else:
            o, cl, hi = e - 0.1 * a, e - 0.5 * a, e + 0.1 * a
            lo = cl - 0.1 * a
        c.append([start_ts + n * TF, o, hi, lo, cl, 1.0])
    return c


def make_st_candles(trend: int = 1, n: int = 330, start_ts: int = 0) -> List[List[float]]:
    """Trend -> Supertrend'i ters ceviren geri cekilme -> trend yonunde ILK donus
    mumunda biten seri (son mum = Supertrend giris sinyali)."""
    c: List[List[float]] = []
    p = 100.0

    def add(mult):
        nonlocal p
        o = p
        p *= mult
        c.append([start_ts + len(c) * TF, o, max(o, p) * 1.002, min(o, p) * 0.998, p, 1.0])

    def st_dir():
        return ta.supertrend([x[2] for x in c], [x[3] for x in c], [x[4] for x in c], 10, 3.0)[1][-1]

    for i in range(n):
        add(1 + trend * 0.004 * (1 if i % 5 < 3 else -0.6))
    while st_dir() != -trend:
        add(1 - trend * 0.012)
    while st_dir() != trend:
        add(1 + trend * 0.015)
    return c


def make_snapshot(price: float, funding: float = 0.0001, spread: float = 0.0, oi: float = 1e9) -> MarketSnapshot:
    per = {}
    for k, name in enumerate(("binance", "bybit", "okx")):
        f = 1 + spread * (k - 1)
        per[name] = ExchangeSnapshot(name, spot=price * f, perp=price * f * 1.0002, funding_8h=funding, oi_usd=oi)
    return MarketSnapshot("X/USDT", 0, per)


def settings(**kw) -> Settings:
    s = Settings()
    s.telegram_token = "123456:" + "A" * 35
    s.telegram_chat_id = 42
    s.data_dir = Path(tempfile.mkdtemp())
    s.strategy = "pullback"  # eski testler pullback icin yazildi; supertrend testleri acikca secer
    s.risk_mode = "risk"  # eski testler risk bazli boyutlama icin; sabit sema testleri acikca secer
    s.auto_symbols = False  # testler sabit sembol listesi kullanir
    s.coins_enabled = False
    s.max_sl_pct = 4.0
    s.risk_per_trade_usdt = 1.5
    s.max_daily_loss_usdt = 4.5
    s.max_consecutive_losses = 3
    s.max_open_positions = 1
    for k, v in kw.items():
        setattr(s, k, v)
    return s


class FakeTelegram:
    def __init__(self):
        self.sent: List[Dict[str, Any]] = []
        self.edits: List[tuple] = []
        self.answers: List[tuple] = []
        self._ids = itertools.count(1)

    def send(self, text, buttons=None, silent=False):
        mid = next(self._ids)
        self.sent.append({"text": text, "buttons": buttons, "silent": silent, "id": mid})
        return mid

    def edit(self, mid, text):
        self.edits.append((mid, text))

    def answer_callback(self, cid, text=""):
        self.answers.append((cid, text))

    def get_updates(self, timeout=5):
        return []

    def skip_pending(self):
        pass

    def set_commands(self, c):
        pass

    def texts(self) -> str:
        return "\n----\n".join(m["text"] for m in self.sent)


class FakeMarket:
    """ccxt Exchange'in botun kullandigi alt kumesi (precision/market bilgisi)."""

    def __init__(self, contract_size=1.0, amount_step=0.001, price_step=0.01, min_amount=0.001, min_cost=5.0):
        self.contract_size = contract_size
        self.amount_step = amount_step
        self.price_step = price_step
        self.min_amount = min_amount
        self.min_cost = min_cost
        self.markets: Optional[dict] = {}
        self.options = {"defaultType": "swap"}
        self.id = "fake"

    def load_markets(self, reload=False):
        self.markets = {}
        return {}

    def market(self, sym):
        return {
            "symbol": sym, "active": True, "linear": True, "contractSize": self.contract_size,
            "limits": {"amount": {"min": self.min_amount}, "cost": {"min": self.min_cost}},
        }

    def amount_to_precision(self, sym, x):
        steps = math.floor(x / self.amount_step + 1e-9)
        return repr(round(steps * self.amount_step, 10))

    def price_to_precision(self, sym, x):
        return repr(round(round(x / self.price_step) * self.price_step, 10))


class FakeMD:
    """MarketData yerine: sabit mum + snapshot doner; swap istemcisi FakeMarket."""

    def __init__(self, candles_by_symbol, snap_by_symbol, price_by_symbol, ex=None):
        self.candles = candles_by_symbol
        self.snaps = snap_by_symbol
        self.prices = price_by_symbol
        self.minute_candles: Dict[str, List[List[float]]] = {}
        outer = self

        class _Swap(FakeMarket if ex is None else type(ex)):
            def fetch_ticker(self, sym):
                return {"last": outer.prices[sym.split(":")[0]]}

            def fetch_ohlcv(self, sym, tf, since=None, limit=None):
                rows = outer.minute_candles.get(sym.split(":")[0], [])
                return [r for r in rows if since is None or r[0] >= since][: limit or 500]

        self.swap = {n: (_Swap() if ex is None else ex) for n in ("binance", "bybit", "okx")}

    def _ensure(self, ex):
        pass

    def ohlcv(self, exchange, symbol, timeframe, limit=300):
        return self.candles[symbol]

    def snapshot(self, symbol):
        return self.snaps[symbol]
