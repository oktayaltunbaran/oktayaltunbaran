"""Donen (rotating) dosya log'u + konsol. API anahtarlari ve Telegram token'i
log'a yazilmadan once maskelenir."""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Iterable

_SECRETS: list = []
_TOKEN_RE = re.compile(r"\d{6,}:[A-Za-z0-9_-]{30,}")


class _RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        red = _TOKEN_RE.sub("<telegram-token>", msg)
        for s in _SECRETS:
            if s and s in red:
                red = red.replace(s, "<secret>")
        if red != msg:
            record.msg = red
            record.args = ()
        return True


def register_secrets(values: Iterable[str]) -> None:
    for v in values:
        if v and len(v) >= 6 and v not in _SECRETS:
            _SECRETS.append(v)


def setup_logging(log_dir: Path, level: int = logging.INFO) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = RotatingFileHandler(log_dir / "bot.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    flt = _RedactFilter()
    for h in (fh, sh):
        h.addFilter(flt)
        root.addHandler(h)
    # ccxt/urllib3 cok konusur; uyarilari tut
    for noisy in ("urllib3", "ccxt"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return logging.getLogger("bot")
