"""Giris noktasi.

  python -m bot              -> botu calistir
  python -m bot check        -> yapilandirma + borsa + Telegram baglanti testi
  python -m bot backtest ETH 365  -> geriye donuk test (sembol yoksa hepsi)
  python -m bot chatid       -> bota yazdiginiz mesajdan chat id'nizi gosterir
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


def cmd_run() -> int:
    cfg = load_settings()
    setup_logging(cfg.data_dir / "logs")
    _secrets(cfg)
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
