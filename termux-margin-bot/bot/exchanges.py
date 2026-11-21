"""ccxt istemci fabrikasi ve uc borsadan (Binance / OKX / Bybit) spot + vadeli
(USDT perpetual) veri toplama.

Tasarim kararlari
-----------------
* Yalnizca ccxt'nin SENKRON API'si kullanilir (aiohttp gerekmez -> Termux'ta
  C derlemesi yok).
* Her borsa/piyasa tipi icin ayri istemci: ``load_markets`` sadece gereken tipi
  indirir (mobil veri ve RAM tasarrufu: OKX/Bybit opsiyon listeleri cok buyuk).
* Birlesik semboller: spot ``BTC/USDT``, perp ``BTC/USDT:USDT``.
* Bir borsanin hata vermesi analizi durdurmaz; o borsa ``None`` doner ve
  mesajda belirtilir (kismi veri ile karar verme kurallari strategy.py'de).
"""

from __future__ import annotations

import logging
import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import ccxt

from .config import SUPPORTED_EXCHANGES, ExchangeKeys

log = logging.getLogger("bot.exchanges")

_COMMON = {"enableRateLimit": True, "timeout": 15_000}


def perp_symbol(spot_symbol: str) -> str:
    base, quote = spot_symbol.split("/")
    return f"{base}/{quote}:{quote}"


def make_client(name: str, kind: str, keys: Optional[ExchangeKeys] = None, testnet: bool = False) -> ccxt.Exchange:
    """kind: 'spot' | 'swap'."""
    if name not in SUPPORTED_EXCHANGES:
        raise ValueError(name)
    if kind not in ("spot", "swap"):
        raise ValueError(kind)
    cfg: Dict[str, Any] = dict(_COMMON)
    opts: Dict[str, Any] = {"adjustForTimeDifference": True}  # Android saati kayabilir
    if name == "binance":
        if kind == "spot":
            cls = ccxt.binance
            opts.update(defaultType="spot", fetchMarkets={"types": ["spot"]})
        else:
            cls = ccxt.binanceusdm
            opts.update(fetchMarkets={"types": ["linear"]})
    elif name == "bybit":
        cls = ccxt.bybit
        opts.update(
            defaultType="spot" if kind == "spot" else "swap",
            fetchMarkets={"types": ["spot"] if kind == "spot" else ["linear"]},
        )
    else:  # okx
        cls = ccxt.okx
        opts.update(
            defaultType="spot" if kind == "spot" else "swap",
            fetchMarkets={"types": ["spot"] if kind == "spot" else ["swap"]},
        )
    cfg["options"] = opts
    if keys is not None and keys.present:
        cfg["apiKey"] = keys.api_key
        cfg["secret"] = keys.secret
        if keys.password:
            cfg["password"] = keys.password
    ex = cls(cfg)
    # Para birimi listesi (Binance'te sapi/capital, OKX'te asset/currencies) bot icin
    # gereksiz: her load_markets'te ekstra agir istek ve ek API izni demek.
    # Bakiye/islem ayristirmasi bu liste olmadan da calisir.
    ex.has["fetchCurrencies"] = False
    if testnet:
        if name == "okx":
            ex.set_sandbox_mode(True)  # OKX demo: x-simulated-trading header
        else:
            ex.enable_demo_trading(True)  # Binance/Bybit demo trading
    return ex


def _interval_hours(fr: Dict[str, Any]) -> float:
    iv = fr.get("interval")
    if isinstance(iv, str) and iv.endswith("h"):
        try:
            h = float(iv[:-1])
            if h > 0:
                return h
        except ValueError:
            pass
    return 8.0


@dataclass
class ExchangeSnapshot:
    exchange: str
    spot: Optional[float] = None
    perp: Optional[float] = None
    funding_8h: Optional[float] = None  # 8 saate normalize oran (0.0001 = %0.01)
    oi_usd: Optional[float] = None
    errors: List[str] = field(default_factory=list)


@dataclass
class MarketSnapshot:
    symbol: str
    ts: int
    per_exchange: Dict[str, ExchangeSnapshot]

    def _vals(self, attr: str) -> List[float]:
        return [getattr(s, attr) for s in self.per_exchange.values() if getattr(s, attr) is not None]

    @property
    def spot_median(self) -> Optional[float]:
        v = self._vals("spot")
        return statistics.median(v) if v else None

    @property
    def perp_median(self) -> Optional[float]:
        v = self._vals("perp")
        return statistics.median(v) if v else None

    @property
    def funding_avg(self) -> Optional[float]:
        v = self._vals("funding_8h")
        return sum(v) / len(v) if v else None

    @property
    def oi_total(self) -> Optional[float]:
        v = self._vals("oi_usd")
        # Toplam OI yalnizca TUM borsalardan veri geldiyse anlamli; aksi halde
        # bir borsanin dusmesi sahte bir "OI cokusu" gibi gorunur.
        return sum(v) if len(v) == len(self.per_exchange) else None

    @property
    def basis_pct(self) -> Optional[float]:
        s, p = self.spot_median, self.perp_median
        if s and p:
            return (p - s) / s * 100
        return None

    @property
    def divergence_pct(self) -> Optional[float]:
        """Borsalar arasi en buyuk fiyat sapmasi. Spot ve perp AYRI olculur
        (spot-perp farki normal bazdir, anomali degildir); buyuk olan doner."""
        out: List[float] = []
        for attr in ("spot", "perp"):
            v = self._vals(attr)
            if len(v) >= 2:
                out.append((max(v) - min(v)) / statistics.median(v) * 100)
        return max(out) if out else None

    @property
    def sources_ok(self) -> int:
        return sum(1 for s in self.per_exchange.values() if s.perp is not None)


class MarketData:
    """Uc borsadan herkese acik (public) veriler. API anahtari gerekmez."""

    def __init__(self, exchanges=SUPPORTED_EXCHANGES):
        self.names = list(exchanges)
        self.spot: Dict[str, ccxt.Exchange] = {n: make_client(n, "spot") for n in self.names}
        self.swap: Dict[str, ccxt.Exchange] = {n: make_client(n, "swap") for n in self.names}
        self._loaded: Dict[str, float] = {}

    def _ensure(self, ex: ccxt.Exchange) -> None:
        key = f"{ex.id}:{ex.options.get('defaultType', '')}"
        last = self._loaded.get(key, 0)
        if ex.markets is None or time.time() - last > 6 * 3600:  # 6 saatte bir tazele
            ex.load_markets(reload=ex.markets is not None)
            self._loaded[key] = time.time()

    def ohlcv(self, exchange: str, symbol: str, timeframe: str, limit: int = 1000) -> List[List[float]]:
        """Son ``limit`` mumu sayfalayarak getirir.

        EMA200'un baslangic tohumunun etkisi (1-2/201)^k ile soner: 300 mumda
        ~%37, 1000 mumda ~%0.03. Bu yuzden TradingView ile tutarli EMA200 icin
        ~1000 mum gerekir. OKX tek istekte en fazla 300 mum verdigi icin 300'luk
        sayfalar kullanilir (uc borsada da calisir)."""
        ex = self.swap[exchange]
        self._ensure(ex)
        psym = perp_symbol(symbol)
        tf_ms = int(ex.parse_timeframe(timeframe) * 1000)
        now = ex.milliseconds()
        since = now - limit * tf_ms
        page = 300
        out: List[List[float]] = []
        for _ in range(limit // page + 3):
            batch = ex.fetch_ohlcv(psym, timeframe, since=since, limit=page)
            if out:
                batch = [b for b in batch if b[0] > out[-1][0]]
            if not batch:
                break
            out.extend(batch)
            since = int(batch[-1][0]) + tf_ms
            if since > now:
                break
        return out[-limit:]

    def snapshot(self, symbol: str) -> MarketSnapshot:
        psym = perp_symbol(symbol)
        out: Dict[str, ExchangeSnapshot] = {}
        for n in self.names:
            snap = ExchangeSnapshot(exchange=n)
            sp, sw = self.spot[n], self.swap[n]
            try:
                self._ensure(sp)
                snap.spot = float(sp.fetch_ticker(symbol)["last"])
            except Exception as e:  # noqa: BLE001
                snap.errors.append(f"spot: {type(e).__name__}")
                log.warning("%s spot %s: %s", n, symbol, e)
            try:
                self._ensure(sw)
                snap.perp = float(sw.fetch_ticker(psym)["last"])
            except Exception as e:  # noqa: BLE001
                snap.errors.append(f"perp: {type(e).__name__}")
                log.warning("%s perp %s: %s", n, psym, e)
            try:
                fr = sw.fetch_funding_rate(psym)
                rate = fr.get("fundingRate")
                if rate is not None:
                    snap.funding_8h = float(rate) * 8.0 / _interval_hours(fr)
            except Exception as e:  # noqa: BLE001
                snap.errors.append(f"funding: {type(e).__name__}")
                log.warning("%s funding %s: %s", n, psym, e)
            try:
                oi = sw.fetch_open_interest(psym)
                val = oi.get("openInterestValue")
                if val is None and oi.get("openInterestAmount") is not None and snap.perp:
                    csize = float(sw.market(psym).get("contractSize") or 1.0)
                    val = float(oi["openInterestAmount"]) * csize * snap.perp
                if val is not None:
                    snap.oi_usd = float(val)
            except Exception as e:  # noqa: BLE001
                snap.errors.append(f"oi: {type(e).__name__}")
                log.warning("%s OI %s: %s", n, psym, e)
            out[n] = snap
        return MarketSnapshot(symbol=symbol, ts=int(time.time() * 1000), per_exchange=out)


def closed_candles(ohlcv: List[List[float]], timeframe_ms: int, now_ms: Optional[int] = None) -> List[List[float]]:
    """Henuz kapanmamis (canli) mumu atar. Borsalar son elemanda acik mumu dondurur;
    kapanmamis mumla sinyal uretmek 'repaint' (yanlis sinyal) demektir."""
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    return [c for c in ohlcv if c[0] + timeframe_ms <= now_ms]
