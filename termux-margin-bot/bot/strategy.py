"""2 saatlik trend-takip + geri cekilme (pullback) stratejisi ve turev filtresi.

Mantik (yalnizca KAPANMIS mumlarda; son kapanan mum = i):

LONG (SHORT bunun aynasidir)
  1. Rejim     : close > EMA200 ve EMA50 > EMA200          (ana trend yukari)
  2. Guc       : ADX(14) >= ADX_MIN                        (yatay piyasayi ele)
  3. Geri cekilme: son 2 mumun en dusugu EMA21 + 0.25*ATR'ye degmis
  4. Devam     : close > EMA21 ve mum yesil (close > open)
  5. Momentum  : RSI(14) RSI_LONG_MIN..RSI_LONG_MAX        (asiri alimda girme)
  6. Uzama yok : close - EMA21 <= 1.0 * ATR                (kovalamama)

Turev / coklu borsa filtresi (Binance + OKX + Bybit spot & perp):
  * Borsalar arasi fiyat sapmasi > MAX_PRICE_DIVERGENCE_PCT -> veri anomalisi, islem yok
  * En az 2 borsada perp fiyati olmali (capraz dogrulama)
  * Ortalama funding (8s esdegeri) > +FUNDING_LIMIT -> long kalabalik, long yok
                                    < -FUNDING_LIMIT -> short kalabalik, short yok
  * Spot-perp baz > +MAX_BASIS_PCT long'u, < -MAX_BASIS_PCT short'u engeller
  * Acik pozisyon (OI) degisimi bilgi amaclidir (fiyat+OI ayni yon = teyit).

Stop / hedef:
  SL mesafesi = ATR_SL_MULT * ATR ; MIN_SL_PCT altinda ise MIN_SL_PCT'ye genisletilir,
  MAX_SL_PCT ustunde ise islem reddedilir (volatilite riski kaldiramaz).
  TP = giris +/- TP_R_MULT * SL mesafesi.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import indicators as ta
from .config import Settings
from .exchanges import MarketSnapshot


@dataclass
class Signal:
    symbol: str
    side: str  # long | short
    bar_ts: int  # sinyal mumunun acilis zamani (ms)
    entry_ref: float
    sl: float
    tp: float
    atr: float
    sl_pct: float

    @property
    def sl_dist(self) -> float:
        return abs(self.entry_ref - self.sl)


@dataclass
class Analysis:
    symbol: str
    bar_ts: int
    close: float
    ema_fast: float
    ema_mid: float
    ema_slow: float
    rsi: float
    adx: float
    atr: float
    bias: str  # long | short | none
    checks: List[Tuple[str, bool]] = field(default_factory=list)
    blocks: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    signal: Optional[Signal] = None

    @property
    def atr_pct(self) -> float:
        return self.atr / self.close * 100


class Strategy:
    def __init__(self, cfg: Settings):
        self.cfg = cfg

    @property
    def min_bars(self) -> int:
        c = self.cfg
        return max(c.ema_slow, 2 * c.adx_len, c.rsi_len + 1, c.atr_len + 1) + 5

    def compute(self, candles: List[List[float]]) -> Dict[str, list]:
        """Tum seri icin indikatorleri BIR KEZ hesaplar. Indikatorler nedenseldir
        (i. deger yalnizca <= i verilere bagli), bu yuzden backtest ayni seriyi
        her indekste bakis-ileri (look-ahead) olmadan degerlendirebilir."""
        c = self.cfg
        o = [float(x[1]) for x in candles]
        h = [float(x[2]) for x in candles]
        l = [float(x[3]) for x in candles]
        cl = [float(x[4]) for x in candles]
        return {
            "ts": [int(x[0]) for x in candles], "o": o, "h": h, "l": l, "c": cl,
            "ef": ta.ema(cl, c.ema_fast), "em": ta.ema(cl, c.ema_mid), "es": ta.ema(cl, c.ema_slow),
            "rsi": ta.rsi(cl, c.rsi_len), "atr": ta.atr(h, l, cl, c.atr_len), "adx": ta.adx(h, l, cl, c.adx_len),
        }

    def analyze(
        self,
        symbol: str,
        candles: List[List[float]],
        snap: Optional[MarketSnapshot] = None,
        oi_change_pct: Optional[float] = None,
        require_market: bool = True,
    ) -> Analysis:
        if len(candles) < self.min_bars:
            raise ValueError(f"{symbol}: yetersiz mum ({len(candles)} < {self.min_bars})")
        ind = self.compute(candles)
        return self.evaluate(symbol, ind, len(candles) - 1, snap, oi_change_pct, require_market)

    def evaluate(
        self,
        symbol: str,
        ind: Dict[str, list],
        i: int,
        snap: Optional[MarketSnapshot] = None,
        oi_change_pct: Optional[float] = None,
        require_market: bool = True,
    ) -> Analysis:
        c = self.cfg
        if i < self.min_bars - 1:
            raise ValueError(f"{symbol}: yetersiz mum (index {i})")
        ts, o, h, l, cl = ind["ts"], ind["o"], ind["h"], ind["l"], ind["c"]
        vals = (ind["ef"][i], ind["em"][i], ind["es"][i], ind["rsi"][i], ind["atr"][i], ind["adx"][i])
        if any(v is None for v in vals):
            raise ValueError(f"{symbol}: indikator hesaplanamadi")
        efi, emi, esi, ri, ai, di = (float(v) for v in vals)  # type: ignore[arg-type]
        close = cl[i]

        an = Analysis(symbol, ts[i], close, efi, emi, esi, ri, di, ai, "none")

        if close > esi and emi > esi:
            an.bias = "long"
        elif close < esi and emi < esi:
            an.bias = "short"

        if an.bias == "none":
            an.checks.append(("Rejim (EMA50/EMA200 + fiyat)", False))
            an.notes.append("Trend rejimi net degil (EMA'lar karisik).")
            return an

        long_ = an.bias == "long"
        recent_low = min(l[i], l[i - 1])
        recent_high = max(h[i], h[i - 1])
        an.checks = [
            ("Rejim (EMA50/EMA200 + fiyat)", True),
            (f"ADX >= {c.adx_min:g}", di >= c.adx_min),
            (
                "EMA21'e geri cekilme",
                recent_low <= efi + 0.25 * ai if long_ else recent_high >= efi - 0.25 * ai,
            ),
            (
                "EMA21 ustunde/altinda donus mumu",
                (close > efi and close > o[i]) if long_ else (close < efi and close < o[i]),
            ),
            (
                f"RSI {c.rsi_long_min:g}-{c.rsi_long_max:g}" if long_ else f"RSI {c.rsi_short_min:g}-{c.rsi_short_max:g}",
                (c.rsi_long_min <= ri <= c.rsi_long_max) if long_ else (c.rsi_short_min <= ri <= c.rsi_short_max),
            ),
            ("Asiri uzama yok (<=1 ATR)", abs(close - efi) <= 1.0 * ai),
        ]
        tech_ok = all(ok for _, ok in an.checks)

        # ---- turev / coklu borsa filtresi ----
        if snap is not None:
            div = snap.divergence_pct
            if div is not None and div > c.max_price_divergence_pct:
                an.blocks.append(f"Borsalar arasi fiyat sapmasi %{div:.2f} (> %{c.max_price_divergence_pct:g})")
            if snap.sources_ok < 2:
                an.blocks.append(
                    f"Capraz dogrulama icin yetersiz borsa ({snap.sources_ok}/{len(snap.per_exchange)})"
                )
            fa = snap.funding_avg
            if fa is not None:
                if long_ and fa > c.funding_limit:
                    an.blocks.append(f"Funding %{fa * 100:.4f} -> long tarafi kalabalik")
                if not long_ and fa < -c.funding_limit:
                    an.blocks.append(f"Funding %{fa * 100:.4f} -> short tarafi kalabalik")
            b = snap.basis_pct
            if b is not None:
                if long_ and b > c.max_basis_pct:
                    an.blocks.append(f"Perp primi %{b:.2f} -> asiri iyimserlik")
                if not long_ and b < -c.max_basis_pct:
                    an.blocks.append(f"Perp iskontosu %{b:.2f} -> asiri karamsarlik")
        elif require_market:
            an.blocks.append("Piyasa anlik verisi alinamadi")

        if oi_change_pct is not None:
            price_up = close > cl[i - 1]
            oi_up = oi_change_pct > 0
            if price_up == oi_up:
                an.notes.append(f"OI %{oi_change_pct:+.2f}: fiyat ile ayni yonde (teyit)")
            else:
                an.notes.append(f"OI %{oi_change_pct:+.2f}: fiyatla ters (pozisyon kapanisi olabilir)")

        if not tech_ok or an.blocks:
            return an

        # ---- SL / TP ----
        sl_dist = c.atr_sl_mult * ai
        min_dist = close * c.min_sl_pct / 100
        if sl_dist < min_dist:
            an.notes.append(f"SL mesafesi min %{c.min_sl_pct:g}'e genisletildi")
            sl_dist = min_dist
        sl_pct = sl_dist / close * 100
        if sl_pct > c.max_sl_pct:
            an.blocks.append(f"SL %{sl_pct:.2f} > max %{c.max_sl_pct:g} (volatilite cok yuksek)")
            return an
        if long_:
            sl, tp = close - sl_dist, close + c.tp_r_mult * sl_dist
        else:
            sl, tp = close + sl_dist, close - c.tp_r_mult * sl_dist
        an.signal = Signal(symbol, an.bias, ts[i], close, sl, tp, ai, sl_pct)
        return an
