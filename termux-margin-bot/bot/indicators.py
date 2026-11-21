"""Saf Python teknik indikatorler (numpy/pandas gerektirmez -> Termux dostu).

Tum fonksiyonlar girdiyle ayni uzunlukta liste dondurur. Yeterli veri olmayan
ilk elemanlar ``None`` olur. Hesaplamalar TA-Lib / TradingView ile ayni klasik
tanimlari izler:

* EMA : ilk deger SMA(n) ile tohumlanir, alpha = 2/(n+1)
* RSI : Wilder yumusatmasi (RMA), ilk ortalama = ilk n degisimin SMA'si
* ATR : Wilder yumusatmasi, TR = max(H-L, |H-C1|, |L-C1|)
* ADX : Wilder +DI / -DI / DX / ADX
"""

from __future__ import annotations

from typing import List, Optional, Sequence

Series = List[Optional[float]]


def _check_period(n: int) -> None:
    if not isinstance(n, int) or n < 1:
        raise ValueError(f"period pozitif tam sayi olmali, gelen: {n!r}")


def sma(values: Sequence[float], n: int) -> Series:
    _check_period(n)
    out: Series = [None] * len(values)
    if len(values) < n:
        return out
    window = sum(values[:n])
    out[n - 1] = window / n
    for i in range(n, len(values)):
        window += values[i] - values[i - n]
        out[i] = window / n
    return out


def ema(values: Sequence[float], n: int) -> Series:
    _check_period(n)
    out: Series = [None] * len(values)
    if len(values) < n:
        return out
    alpha = 2.0 / (n + 1)
    prev = sum(values[:n]) / n
    out[n - 1] = prev
    for i in range(n, len(values)):
        prev = alpha * values[i] + (1 - alpha) * prev
        out[i] = prev
    return out


def rsi(closes: Sequence[float], n: int = 14) -> Series:
    _check_period(n)
    out: Series = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = 0.0
    losses = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        if d > 0:
            gains += d
        else:
            losses -= d
    avg_g = gains / n
    avg_l = losses / n

    def _val(g: float, l: float) -> float:
        if l == 0:
            return 100.0 if g > 0 else 50.0
        rs = g / l
        return 100.0 - 100.0 / (1.0 + rs)

    out[n] = _val(avg_g, avg_l)
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        g = d if d > 0 else 0.0
        l = -d if d < 0 else 0.0
        avg_g = (avg_g * (n - 1) + g) / n
        avg_l = (avg_l * (n - 1) + l) / n
        out[i] = _val(avg_g, avg_l)
    return out


def true_range(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]) -> List[float]:
    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("high/low/close uzunluklari esit olmali")
    tr: List[float] = []
    for i in range(len(highs)):
        if i == 0:
            tr.append(highs[0] - lows[0])
        else:
            pc = closes[i - 1]
            tr.append(max(highs[i] - lows[i], abs(highs[i] - pc), abs(lows[i] - pc)))
    return tr


def atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], n: int = 14) -> Series:
    """Wilder ATR. Ilk deger index ``n``'de (TR[1..n] ortalamasi), TA-Lib ile ayni."""
    _check_period(n)
    tr = true_range(highs, lows, closes)
    out: Series = [None] * len(tr)
    if len(tr) <= n:
        return out
    prev = sum(tr[1 : n + 1]) / n
    out[n] = prev
    for i in range(n + 1, len(tr)):
        prev = (prev * (n - 1) + tr[i]) / n
        out[i] = prev
    return out


def adx(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], n: int = 14) -> Series:
    """Wilder ADX. Ilk deger index ``2n-1``'de."""
    _check_period(n)
    length = len(highs)
    out: Series = [None] * length
    if length < 2 * n:
        return out
    tr = true_range(highs, lows, closes)
    pdm = [0.0] * length
    mdm = [0.0] * length
    for i in range(1, length):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        pdm[i] = up if (up > down and up > 0) else 0.0
        mdm[i] = down if (down > up and down > 0) else 0.0

    # Wilder toplamlari, TA-Lib ile birebir: 1..n-1 toplanir, n. bar Wilder
    # guncellemesiyle eklenir (s = s - s/n + x).
    s_tr = sum(tr[1:n])
    s_p = sum(pdm[1:n])
    s_m = sum(mdm[1:n])
    s_tr = s_tr - s_tr / n + tr[n]
    s_p = s_p - s_p / n + pdm[n]
    s_m = s_m - s_m / n + mdm[n]

    def _dx(str_: float, sp: float, sm: float) -> float:
        if str_ <= 0:
            return 0.0
        pdi = 100.0 * sp / str_
        mdi = 100.0 * sm / str_
        tot = pdi + mdi
        return 0.0 if tot == 0 else 100.0 * abs(pdi - mdi) / tot

    dxs: List[float] = [_dx(s_tr, s_p, s_m)]  # index n
    for i in range(n + 1, length):
        s_tr = s_tr - s_tr / n + tr[i]
        s_p = s_p - s_p / n + pdm[i]
        s_m = s_m - s_m / n + mdm[i]
        dxs.append(_dx(s_tr, s_p, s_m))
    # dxs[k] -> bar index n+k ; ADX ilk = ilk n DX ortalamasi -> index 2n-1
    prev = sum(dxs[:n]) / n
    out[2 * n - 1] = prev
    for k in range(n, len(dxs)):
        prev = (prev * (n - 1) + dxs[k]) / n
        out[n + k] = prev
    return out
