"""Yapilandirma: ``.env`` dosyasindan okunur, tip ve aralik kontrolu yapilir.

python-dotenv bagimliligi yok; basit ve deterministik bir ayristirici kullanilir.
Ortam degiskenleri (os.environ) .env'deki degerleri EZER.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

SUPPORTED_EXCHANGES = ("binance", "bybit", "okx")
TIMEFRAME_MS = {
    "15m": 15 * 60_000,
    "30m": 30 * 60_000,
    "1h": 60 * 60_000,
    "2h": 2 * 60 * 60_000,
    "4h": 4 * 60 * 60_000,
}


class ConfigError(ValueError):
    pass


def parse_env_file(path: Path) -> Dict[str, str]:
    """KEY=VALUE satirlari. ``#`` ile baslayan satirlar ve bos satirlar atlanir.
    Degerin etrafindaki tek/cift tirnaklar soyulur. Satir sonu yorumlarina
    (tirnaksiz degerde `` #``) izin verilir."""
    data: Dict[str, str] = {}
    if not path.exists():
        return data
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            raise ConfigError(f"{path}:{lineno}: '=' bulunamadi")
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        elif " #" in val:
            val = val.split(" #", 1)[0].rstrip()
        data[key] = val
    return data


def _bool(v: str) -> bool:
    s = v.strip().lower()
    if s in ("1", "true", "yes", "on", "evet"):
        return True
    if s in ("0", "false", "no", "off", "hayir", ""):
        return False
    raise ConfigError(f"Gecersiz boolean: {v!r}")


@dataclass
class ExchangeKeys:
    api_key: str = ""
    secret: str = ""
    password: str = ""  # OKX passphrase

    @property
    def present(self) -> bool:
        return bool(self.api_key and self.secret)


@dataclass
class Settings:
    # Telegram
    telegram_token: str = ""
    telegram_chat_id: int = 0

    # Calisma modu
    mode: str = "paper"  # paper | live
    auto_trade: bool = False  # False: her sinyal Telegram'dan onay ister
    exec_exchange: str = "binance"
    data_exchanges: List[str] = field(default_factory=lambda: list(SUPPORTED_EXCHANGES))
    use_testnet: bool = False
    symbols: List[str] = field(default_factory=lambda: ["BTC/USDT", "ETH/USDT", "SOL/USDT"])
    timeframe: str = "2h"
    candle_close_delay_sec: int = 20
    confirm_timeout_min: int = 15
    cycle_report: bool = False  # her 2s mumda kisa ozet gonder

    # Sermaye ve risk
    margin_usdt: float = 30.0
    leverage: int = 5
    risk_per_trade_usdt: float = 1.5
    max_daily_loss_usdt: float = 4.5
    max_consecutive_losses: int = 3
    min_equity_usdt: float = 20.0
    paper_start_equity: float = 30.0
    require_isolated: bool = True
    fee_rate: float = 0.0006  # taker, tek yon, muhafazakar
    slippage_pct: float = 0.05  # yuzde
    maint_margin_rate: float = 0.005

    # Strateji
    ema_fast: int = 21
    ema_mid: int = 50
    ema_slow: int = 200
    rsi_len: int = 14
    atr_len: int = 14
    adx_len: int = 14
    adx_min: float = 20.0
    rsi_long_min: float = 45.0
    rsi_long_max: float = 70.0
    rsi_short_min: float = 30.0
    rsi_short_max: float = 55.0
    atr_sl_mult: float = 1.5
    tp_r_mult: float = 2.0
    breakeven_at_r: float = 1.0  # 0 = kapali
    max_hold_candles: int = 24
    min_sl_pct: float = 0.4
    max_sl_pct: float = 4.0
    funding_limit: float = 0.0005  # 8 saatlik esdegerde %0.05
    max_price_divergence_pct: float = 0.5
    max_basis_pct: float = 0.5

    # Izleme
    monitor_interval_sec: int = 30

    # Anahtarlar
    keys: Dict[str, ExchangeKeys] = field(default_factory=dict)

    # Dosyalar
    data_dir: Path = Path("data")

    # ---- turetilmis ----
    @property
    def timeframe_ms(self) -> int:
        return TIMEFRAME_MS[self.timeframe]

    @property
    def max_notional_usdt(self) -> float:
        return self.margin_usdt * self.leverage

    @property
    def is_live(self) -> bool:
        return self.mode == "live"

    def validate(self) -> None:
        errs: List[str] = []
        if not self.telegram_token or ":" not in self.telegram_token:
            errs.append("TELEGRAM_BOT_TOKEN eksik/gecersiz (BotFather'dan alin)")
        if self.telegram_chat_id == 0:
            errs.append("TELEGRAM_CHAT_ID eksik (README: chat id ogrenme)")
        if self.mode not in ("paper", "live"):
            errs.append("MODE paper veya live olmali")
        if self.exec_exchange not in SUPPORTED_EXCHANGES:
            errs.append(f"EXEC_EXCHANGE {SUPPORTED_EXCHANGES} icinden olmali")
        bad = [x for x in self.data_exchanges if x not in SUPPORTED_EXCHANGES]
        if bad:
            errs.append(f"DATA_EXCHANGES gecersiz: {bad}")
        if self.exec_exchange not in self.data_exchanges:
            errs.append("EXEC_EXCHANGE, DATA_EXCHANGES listesinde olmali")
        if len(self.data_exchanges) < 2:
            errs.append("Capraz dogrulama icin DATA_EXCHANGES en az 2 borsa icermeli")
        if self.timeframe not in TIMEFRAME_MS:
            errs.append(f"TIMEFRAME {list(TIMEFRAME_MS)} icinden olmali")
        if not self.symbols:
            errs.append("SYMBOLS bos olamaz")
        for s in self.symbols:
            if not s.endswith("/USDT") or s.count("/") != 1:
                errs.append(f"Sembol 'BASE/USDT' formatinda olmali: {s}")
        if not (1 <= self.leverage <= 20):
            errs.append("LEVERAGE 1..20 araliginda olmali (bu bot yuksek kaldiraci bilerek engeller)")
        if self.margin_usdt <= 0:
            errs.append("MARGIN_USDT > 0 olmali")
        if self.risk_per_trade_usdt <= 0:
            errs.append("RISK_PER_TRADE_USDT > 0 olmali")
        if self.risk_per_trade_usdt > self.margin_usdt:
            errs.append("RISK_PER_TRADE_USDT, MARGIN_USDT'den buyuk olamaz")
        if self.max_daily_loss_usdt < self.risk_per_trade_usdt:
            errs.append("MAX_DAILY_LOSS_USDT en az RISK_PER_TRADE_USDT kadar olmali")
        if not (0 < self.min_sl_pct < self.max_sl_pct):
            errs.append("0 < MIN_SL_PCT < MAX_SL_PCT olmali")
        # Stop, likidasyondan once tetiklenmeli: max SL < likidasyon mesafesinin %70'i
        liq_pct = (1.0 / self.leverage - self.maint_margin_rate) * 100
        if self.max_sl_pct >= 0.7 * liq_pct:
            errs.append(
                f"MAX_SL_PCT ({self.max_sl_pct}%) likidasyon mesafesine (~{liq_pct:.1f}%) cok yakin; "
                f"{0.7 * liq_pct:.1f}%'in altinda olmali"
            )
        if self.tp_r_mult <= 0:
            errs.append("TP_R_MULT > 0 olmali")
        if self.breakeven_at_r < 0:
            errs.append("BREAKEVEN_AT_R >= 0 olmali")
        if not (self.ema_fast < self.ema_mid < self.ema_slow):
            errs.append("EMA_FAST < EMA_MID < EMA_SLOW olmali")
        if self.monitor_interval_sec < 10:
            errs.append("MONITOR_INTERVAL_SEC >= 10 olmali (rate-limit)")
        if self.is_live:
            k = self.keys.get(self.exec_exchange, ExchangeKeys())
            if not k.present:
                errs.append(f"MODE=live icin {self.exec_exchange.upper()}_API_KEY/SECRET gerekli")
            if self.exec_exchange == "okx" and not k.password:
                errs.append("OKX icin OKX_API_PASSWORD (passphrase) gerekli")
        if errs:
            raise ConfigError("Yapilandirma hatalari:\n  - " + "\n  - ".join(errs))


_FLOAT_FIELDS = {
    "MARGIN_USDT": "margin_usdt",
    "RISK_PER_TRADE_USDT": "risk_per_trade_usdt",
    "MAX_DAILY_LOSS_USDT": "max_daily_loss_usdt",
    "MIN_EQUITY_USDT": "min_equity_usdt",
    "PAPER_START_EQUITY": "paper_start_equity",
    "FEE_RATE": "fee_rate",
    "SLIPPAGE_PCT": "slippage_pct",
    "MAINT_MARGIN_RATE": "maint_margin_rate",
    "ADX_MIN": "adx_min",
    "RSI_LONG_MIN": "rsi_long_min",
    "RSI_LONG_MAX": "rsi_long_max",
    "RSI_SHORT_MIN": "rsi_short_min",
    "RSI_SHORT_MAX": "rsi_short_max",
    "ATR_SL_MULT": "atr_sl_mult",
    "TP_R_MULT": "tp_r_mult",
    "BREAKEVEN_AT_R": "breakeven_at_r",
    "MIN_SL_PCT": "min_sl_pct",
    "MAX_SL_PCT": "max_sl_pct",
    "FUNDING_LIMIT": "funding_limit",
    "MAX_PRICE_DIVERGENCE_PCT": "max_price_divergence_pct",
    "MAX_BASIS_PCT": "max_basis_pct",
}
_INT_FIELDS = {
    "LEVERAGE": "leverage",
    "MAX_CONSECUTIVE_LOSSES": "max_consecutive_losses",
    "CANDLE_CLOSE_DELAY_SEC": "candle_close_delay_sec",
    "CONFIRM_TIMEOUT_MIN": "confirm_timeout_min",
    "EMA_FAST": "ema_fast",
    "EMA_MID": "ema_mid",
    "EMA_SLOW": "ema_slow",
    "RSI_LEN": "rsi_len",
    "ATR_LEN": "atr_len",
    "ADX_LEN": "adx_len",
    "MAX_HOLD_CANDLES": "max_hold_candles",
    "MONITOR_INTERVAL_SEC": "monitor_interval_sec",
}
_BOOL_FIELDS = {
    "AUTO_TRADE": "auto_trade",
    "USE_TESTNET": "use_testnet",
    "REQUIRE_ISOLATED": "require_isolated",
    "CYCLE_REPORT": "cycle_report",
}


def load_settings(env_path: Optional[Path] = None, validate: bool = True) -> Settings:
    base = Path(__file__).resolve().parent.parent
    env_path = env_path or base / ".env"
    raw = parse_env_file(env_path)
    raw.update({k: v for k, v in os.environ.items() if k in _known_keys()})

    s = Settings()
    s.data_dir = base / "data"
    try:
        s.telegram_token = raw.get("TELEGRAM_BOT_TOKEN", "").strip()
        s.telegram_chat_id = int(raw.get("TELEGRAM_CHAT_ID", "0") or 0)
        s.mode = raw.get("MODE", s.mode).strip().lower()
        s.exec_exchange = raw.get("EXEC_EXCHANGE", s.exec_exchange).strip().lower()
        s.timeframe = raw.get("TIMEFRAME", s.timeframe).strip()
        if raw.get("DATA_EXCHANGES"):
            s.data_exchanges = [x.strip().lower() for x in raw["DATA_EXCHANGES"].split(",") if x.strip()]
        if raw.get("SYMBOLS"):
            s.symbols = [x.strip().upper() for x in raw["SYMBOLS"].split(",") if x.strip()]
        for env, attr in _FLOAT_FIELDS.items():
            if env in raw and raw[env] != "":
                setattr(s, attr, float(raw[env]))
        for env, attr in _INT_FIELDS.items():
            if env in raw and raw[env] != "":
                setattr(s, attr, int(raw[env]))
        for env, attr in _BOOL_FIELDS.items():
            if env in raw:
                setattr(s, attr, _bool(raw[env]))
        if raw.get("DATA_DIR"):
            s.data_dir = Path(raw["DATA_DIR"]).expanduser()
    except ValueError as e:
        raise ConfigError(f"Sayisal deger okunamadi: {e}") from e

    for ex in SUPPORTED_EXCHANGES:
        p = ex.upper()
        s.keys[ex] = ExchangeKeys(
            api_key=raw.get(f"{p}_API_KEY", "").strip(),
            secret=raw.get(f"{p}_API_SECRET", "").strip(),
            password=raw.get(f"{p}_API_PASSWORD", "").strip(),
        )
    if validate:
        s.validate()
    return s


def _known_keys() -> set:
    keys = set(_FLOAT_FIELDS) | set(_INT_FIELDS) | set(_BOOL_FIELDS)
    keys |= {"TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "MODE", "EXEC_EXCHANGE", "TIMEFRAME", "SYMBOLS", "DATA_DIR", "DATA_EXCHANGES"}
    for ex in SUPPORTED_EXCHANGES:
        p = ex.upper()
        keys |= {f"{p}_API_KEY", f"{p}_API_SECRET", f"{p}_API_PASSWORD"}
    return keys
