"""2 saatlik stratejiler ve turev filtresi.

STRATEGY=supertrend (VARSAYILAN)
--------------------------------
Binance USDT-M 10 coin x 4 yil (2022-11..2026-11) 2 saatlik veride secildi;
tasarim 2022-11..2025-06'da yapildi, 2025-07..2026-11 hic bakilmadan tek
seferlik dogrulandi (islem basina +0.24R, kar faktoru 1.67, 10 coinin 9'u kar).
  Giris : Supertrend(10, 3) yon DEGISTIRDIGI mumun kapanisinda, fiyat EMA200 ile
          ayni taraftaysa (long: close > EMA200).
  Stop  : borsada "felaket stopu" = Supertrend cizgisi -/+ ST_STOP_ATR * ATR;
          her 2s kapanista trend yonunde (yalnizca lehte) tasinir.
  Cikis : 2s mum Supertrend'in ters tarafinda kapanirsa piyasa emriyle cikilir.
          Sabit hedef YOK: kazananlar kosar, kaybedenler erken kesilir.
Testte ISE YARAMADIGI gorulen ve bu yuzden eklenmeyenler: gunluk trend filtresi,
ADX, kismi kar alma, MACD ile birlestirme, sabit 2R/3R hedef.

STRATEGY=pullback (eski, 4 yillik testte zararda; karsilastirma icin duruyor)
--------------------------------
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
    tp: float  # 0 = sabit hedef yok (iz suren cikis)
    atr: float
    sl_pct: float

    @property
    def sl_dist(self) -> float:
        return abs(self.entry_ref - self.sl)


@dataclass
class TradePlan:
    """Sinyal HENUZ yokken trend yonunde beklenen islemin tahmini seviyeleri.

    Strateji bir geri cekilme stratejisi oldugu icin beklenen giris bolgesi
    EMA21 +/- 0.25*ATR'dir. Stop ve hedef, sinyal tetiklendiginde kullanilacak
    ayni formulle (ATR_SL_MULT*ATR, TP_R_MULT*R) bu referans girise gore
    hesaplanir. Gercek seviyeler, tetikleyen mumun kapanisina gore yeniden
    hesaplanir; bu yuzden bunlar YAKLASIK degerlerdir."""

    side: str
    zone_low: float
    zone_high: float
    entry: float
    sl: float
    tp: float
    invalidation: float  # bu seviyenin otesinde kapanis -> plan iptal (EMA200)
    distance_pct: float  # simdiki fiyatin giris referansina uzakligi (%)
    waiting_for: List[str] = field(default_factory=list)
    trigger: Optional[float] = None  # supertrend: bu seviyenin otesinde 2s kapanis = giris
    current_trend: Optional[str] = None


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
    plan: Optional[TradePlan] = None
    st_line: Optional[float] = None
    st_dir: Optional[int] = None  # +1 yukari, -1 asagi

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
            **dict(zip(("stl", "std"), ta.supertrend(h, l, cl, c.st_len, c.st_mult))),
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
        ts, cl = ind["ts"], ind["c"]
        vals = (ind["ef"][i], ind["em"][i], ind["es"][i], ind["rsi"][i], ind["atr"][i], ind["adx"][i])
        if any(v is None for v in vals):
            raise ValueError(f"{symbol}: indikator hesaplanamadi")
        efi, emi, esi, ri, ai, di = (float(v) for v in vals)  # type: ignore[arg-type]
        close = cl[i]

        an = Analysis(symbol, ts[i], close, efi, emi, esi, ri, di, ai, "none")
        an.st_line = ind["stl"][i]
        an.st_dir = ind["std"][i]
        if c.strategy == "supertrend":
            return self._eval_supertrend(an, ind, i, snap, oi_change_pct, require_market)
        return self._eval_pullback(an, ind, i, snap, oi_change_pct, require_market)

    # ------------------------------------------------------------------ ortak
    def _market_filters(self, an: Analysis, long_: bool, snap, oi_change_pct, cl, i, require_market) -> None:
        c = self.cfg
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
            price_up = cl[i] > cl[i - 1]
            if price_up == (oi_change_pct > 0):
                an.notes.append(f"OI %{oi_change_pct:+.2f}: fiyat ile ayni yonde (teyit)")
            else:
                an.notes.append(f"OI %{oi_change_pct:+.2f}: fiyatla ters (pozisyon kapanisi olabilir)")

    def st_stop(self, st_line: float, atr: float, side: str) -> float:
        """Borsadaki felaket stopu seviyesi (Supertrend cizgisi -/+ k*ATR)."""
        d = 1 if side == "long" else -1
        return st_line - d * self.cfg.st_stop_atr * atr

    # ------------------------------------------------------------- supertrend
    def _eval_supertrend(self, an: Analysis, ind, i, snap, oi_change_pct, require_market) -> Analysis:
        c = self.cfg
        dr, pdr, stl = ind["std"][i], ind["std"][i - 1], ind["stl"][i]
        if dr is None or pdr is None or stl is None:
            raise ValueError(f"{an.symbol}: supertrend hesaplanamadi")
        close, ai, esi = an.close, an.atr, an.ema_slow
        side = "long" if dr == 1 else "short"
        long_ = dr == 1
        an.bias = side
        flipped = dr != pdr
        ema_ok = (close > esi) if long_ else (close < esi)
        an.checks = [
            (f"Supertrend({c.st_len},{c.st_mult:g}) bu mumda {'yukari' if long_ else 'asagi'} dondu", flipped),
            (f"Fiyat EMA200'un {'ustunde' if long_ else 'altinda'}", ema_ok),
        ]
        self._market_filters(an, long_, snap, oi_change_pct, ind["c"], i, require_market)

        sl = self.st_stop(stl, ai, side)
        sl_dist = max(abs(close - sl), 0.5 * ai, close * c.min_sl_pct / 100)
        sl_pct = sl_dist / close * 100
        if flipped and ema_ok and not an.blocks:
            if sl_pct > c.max_sl_pct and not c.fixed:  # sabit semada stop ST'den bagimsiz
                an.blocks.append(f"Stop %{sl_pct:.2f} > max %{c.max_sl_pct:g} (volatilite cok yuksek)")
            else:
                d = 1 if long_ else -1
                an.signal = Signal(an.symbol, side, ind["ts"][i], close, close - d * sl_dist, 0.0, ai, sl_pct)
                return an
        an.plan = self._st_plan(an, stl, ai, esi)
        return an

    def _st_plan(self, an: Analysis, stl: float, atr: float, ema200: float) -> TradePlan:
        """Bir SONRAKI giris icin tetik seviyesi. Supertrend su an yukariysa bir
        sonraki islem SHORT olabilir: 2s kapanis cizginin (stl) altina inerse.
        Donus aninda yeni cizgi ~ (hl2 -/+ mult*ATR) olur; tahmini stop bundan
        ST_STOP_ATR*ATR daha otededir."""
        c = self.cfg
        cur = an.bias
        nxt = "short" if cur == "long" else "long"
        d = 1 if nxt == "long" else -1
        est_line = stl - d * c.st_mult * atr
        sl = est_line - d * c.st_stop_atr * atr
        plan = TradePlan(
            side=nxt, zone_low=stl, zone_high=stl, entry=stl, sl=sl, tp=0.0,
            invalidation=ema200, distance_pct=(stl - an.close) / an.close * 100,
            trigger=stl, current_trend=cur,
        )
        if (nxt == "long") != (stl > ema200):
            plan.waiting_for.append(f"Fiyat EMA200'un {'ustune' if nxt == 'long' else 'altina'} gecmeli")
        plan.waiting_for += [f"Filtre: {b}" for b in an.blocks]
        return plan

    # --------------------------------------------------------------- pullback
    def _eval_pullback(self, an: Analysis, ind, i, snap, oi_change_pct, require_market) -> Analysis:
        c = self.cfg
        o, h, l, cl, ts = ind["o"], ind["h"], ind["l"], ind["c"], ind["ts"]
        close, efi, emi, esi, ri, ai, di = an.close, an.ema_fast, an.ema_mid, an.ema_slow, an.rsi, an.atr, an.adx
        symbol = an.symbol
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

        self._market_filters(an, long_, snap, oi_change_pct, cl, i, require_market)

        # ---- SL / TP mesafesi ----
        sl_dist = c.atr_sl_mult * ai
        min_dist = close * c.min_sl_pct / 100
        widened = sl_dist < min_dist
        sl_dist = max(sl_dist, min_dist)

        if not tech_ok or an.blocks:
            an.plan = self._plan(an, long_, efi, esi, ai, sl_dist, close)
            return an

        if widened:
            an.notes.append(f"SL mesafesi min %{c.min_sl_pct:g}'e genisletildi")
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

    def _plan(self, an: Analysis, long_: bool, ema21: float, ema200: float, atr: float,
              sl_dist: float, close: float) -> TradePlan:
        c = self.cfg
        d = 1 if long_ else -1
        entry = ema21
        plan = TradePlan(
            side="long" if long_ else "short",
            zone_low=ema21 - 0.25 * atr,
            zone_high=ema21 + 0.25 * atr,
            entry=entry,
            sl=entry - d * sl_dist,
            tp=entry + d * c.tp_r_mult * sl_dist,
            invalidation=ema200,
            distance_pct=(entry - close) / close * 100,
        )
        for name, ok in an.checks:
            if not ok:
                plan.waiting_for.append(name)
        if sl_dist / entry * 100 > c.max_sl_pct:
            plan.waiting_for.append(f"Volatilite dusmeli (SL > %{c.max_sl_pct:g})")
        plan.waiting_for += [f"Filtre: {b}" for b in an.blocks]
        return plan

