"""Giris noktasi.

  python -m bot              -> botu calistir
  python -m bot check        -> yapilandirma + borsa + Telegram baglanti testi
  python -m bot backtest ETH 365  -> geriye donuk test (sembol yoksa hepsi)
  python -m bot chatid       -> bota yazdiginiz mesajdan chat id'nizi gosterir
  python -m bot ayar-guncelle -> .env'yi yeni sablona tasir (token/anahtar/mod korunur)
"""

from __future__ import annotations

import logging
import os
import sys
import time

from .config import ConfigError, load_settings
from .logger import register_secrets, setup_logging


def _secrets(cfg):
    vals = [cfg.telegram_token]
    for k in cfg.keys.values():
        vals += [k.api_key, k.secret, k.password]
    register_secrets(vals)


_LOCK = None


def acquire_lock(path) -> bool:
    """Tek ornek kilidi (Passivbot ilkesi): Termux:Boot servisi ve elle baslatilan ikinci
    kopya ayni hesapta cakismasin. Isletim sistemi kilidi surec olunce kendiliginden kalkar."""
    import fcntl

    global _LOCK
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return False
    fh.seek(0)
    fh.truncate()
    fh.write(str(os.getpid()))
    fh.flush()
    _LOCK = fh
    return True


def cmd_run() -> int:
    cfg = load_settings()
    setup_logging(cfg.data_dir / "logs")
    _secrets(cfg)
    if not acquire_lock(cfg.data_dir / "bot.lock"):
        print("HATA: Bot zaten calisiyor (data/bot.lock kilitli). Ikinci kopya baslatilmadi.\n"
              "Servis kuruluysa: sv status marginbot")
        if os.environ.get("BOT_SUPERVISED"):
            time.sleep(60)
        return 4
    from .engine import Engine

    log = logging.getLogger("bot")
    log.info("Baslatiliyor: mode=%s exchange=%s symbols=%s", cfg.mode, cfg.exec_exchange, cfg.symbols)
    Engine(cfg).run()
    return 0


def cmd_check() -> int:
    cfg = load_settings()
    setup_logging(cfg.data_dir / "logs")
    _secrets(cfg)
    from .exchanges import MarketData
    from .strategy import Strategy
    from .telegram_api import Telegram

    ok = True
    print(f"[ayar] OK  mode={cfg.mode} exchange={cfg.exec_exchange} symbols={cfg.symbols}")
    try:
        tg = Telegram(cfg.telegram_token, cfg.telegram_chat_id)
        me = tg._call("getMe", {})
        print(f"[telegram] OK  @{me.get('username')}")
        tg.send("✅ Baglanti testi: bot bu sohbete mesaj gonderebiliyor.")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"[telegram] HATA {e}")
    md = MarketData(cfg.data_exchanges)
    sym = cfg.symbols[0]
    try:
        snap = md.snapshot(sym)
        for n, s in snap.per_exchange.items():
            print(f"[{n}] spot={s.spot} perp={s.perp} funding8h={s.funding_8h} oi_usd={s.oi_usd} hatalar={s.errors}")
        print(f"[piyasa] sapma=%{snap.divergence_pct} baz=%{snap.basis_pct}")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"[piyasa] HATA {e}")
    try:
        from .exchanges import closed_candles
        c = closed_candles(md.ohlcv(cfg.exec_exchange, sym, cfg.timeframe, 1000), cfg.timeframe_ms)
        an = Strategy(cfg).analyze(sym, c, None, None, require_market=False)
        print(f"[strateji] OK  {sym} close={an.close} bias={an.bias} rsi={an.rsi:.1f} adx={an.adx:.1f}")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"[strateji] HATA {e}")
    if cfg.is_live:
        try:
            from .execution import LiveBroker
            from .storage import Storage
            b = LiveBroker(cfg, Storage(cfg.data_dir / "bot.sqlite3"))
            print("[borsa-ozel]", b.self_test())
            for s_ in cfg.symbols:
                mi = b.market_info(s_)
                print(f"  {mi.symbol}: contractSize={mi.contract_size} minAmount={mi.min_amount} minCost={mi.min_cost}")
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"[borsa-ozel] HATA {e}")
    print("SONUC:", "HER SEY HAZIR" if ok else "HATALAR VAR")
    return 0 if ok else 1


def cmd_backtest(args) -> int:
    cfg = load_settings(validate=False)
    syms = [a.upper() if "/" in a else f"{a.upper()}/USDT" for a in args if not a.isdigit()] or cfg.symbols
    days = next((int(a) for a in args if a.isdigit()), 365)
    from .backtest import backtest_symbol
    from .exchanges import make_client

    ex = make_client(cfg.exec_exchange, "swap")
    ex.load_markets()
    for sym in syms:
        print(f"... {cfg.exec_exchange} {sym} {cfg.timeframe} {days} gun")
        print("\n".join(backtest_symbol(cfg, ex, sym, days)))
        print()
    return 0


def cmd_chatid() -> int:
    cfg = load_settings(validate=False)
    from .telegram_api import Telegram

    if not cfg.telegram_token:
        print("Once .env icine TELEGRAM_BOT_TOKEN yazin.")
        return 1
    tg = Telegram(cfg.telegram_token, 0)
    print("Telegram'da botunuza herhangi bir mesaj yazin (60 sn bekleniyor)...")
    for _ in range(6):
        for u in tg.get_updates(timeout=10):
            chat = (u.get("message") or {}).get("chat") or {}
            if chat:
                print(f"chat id: {chat.get('id')}  (tip: {chat.get('type')})  -> .env TELEGRAM_CHAT_ID={chat.get('id')}")
                return 0
    print("Mesaj gelmedi.")
    return 1


KEEP_KEYS = (
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "MODE", "AUTO_TRADE", "EXEC_EXCHANGE", "USE_TESTNET",
    "DATA_EXCHANGES", "DATA_DIR",
    "BINANCE_API_KEY", "BINANCE_API_SECRET", "BYBIT_API_KEY", "BYBIT_API_SECRET",
    "OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSWORD",
)


def cmd_env_update() -> int:
    """Mevcut .env'deki kimlik/mod degerlerini koruyup geri kalan her seyi yeni
    .env.example'daki (test edilmis) varsayilanlara gunceller. Yedek: .env.bak"""
    from pathlib import Path

    from .config import parse_env_file

    base = Path(__file__).resolve().parent.parent
    env, example = base / ".env", base / ".env.example"
    old = parse_env_file(env)
    if not old:
        print(".env bulunamadi veya bos.")
        return 1
    bak = base / ".env.bak"
    bak.write_text(env.read_text(encoding="utf-8"), encoding="utf-8")
    os.chmod(bak, 0o600)  # token/anahtar icerir
    out = []
    kept = []
    for line in example.read_text(encoding="utf-8").splitlines():
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key in KEEP_KEYS and key in old:
            out.append(f"{key}={old[key]}")
            if old[key]:
                kept.append(key)
        else:
            out.append(line)
    env.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.chmod(env, 0o600)
    print("Korunan: " + ", ".join(kept))
    print("Diger ayarlar yeni varsayilanlara guncellendi. Eski dosya: .env.bak")
    load_settings()  # dogrula
    print("Dogrulama OK.")
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if not argv:
            return cmd_run()
        sub, rest = argv[0], argv[1:]
        if sub == "check":
            return cmd_check()
        if sub == "backtest":
            return cmd_backtest(rest)
        if sub == "chatid":
            return cmd_chatid()
        if sub in ("ayar-guncelle", "env-update"):
            return cmd_env_update()
        print(__doc__)
        return 2
    except ConfigError as e:
        print(e, file=sys.stderr)
        if os.environ.get("BOT_SUPERVISED"):
            # runit servisi aninda yeniden baslatir; hatali ayarda saniyede bir
            # yeniden baslama dongusune (pil/log tuketimi) girmemek icin bekle.
            time.sleep(60)
        return 3


if __name__ == "__main__":
    sys.exit(main())
