"""Minimal, bagimliliksiz (yalnizca requests) Telegram Bot API istemcisi.

* Long polling (getUpdates) -> webhook / acik port gerekmez; mobil ag ve NAT
  arkasinda sorunsuz calisir.
* 429 (flood) yanitlarinda ``retry_after`` kadar bekler.
* Token URL'de bulundugu icin istek URL'leri asla log'a yazilmaz.
* Yalnizca yetkili chat id'den gelen mesajlar/islemler kabul edilir
  (kontrol engine.py'de).
"""

from __future__ import annotations

import html
import logging
import time
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger("bot.telegram")

MAX_LEN = 4000  # Telegram limiti 4096; HTML etiketleri icin pay


def esc(s: Any) -> str:
    return html.escape(str(s), quote=False)


class TelegramError(Exception):
    pass


class Telegram:
    def __init__(self, token: str, chat_id: int, session: Optional[requests.Session] = None):
        self.base = f"https://api.telegram.org/bot{token}/"
        self.chat_id = chat_id
        self.s = session or requests.Session()
        self.offset: Optional[int] = None

    def _call(self, method: str, payload: Dict[str, Any], timeout: float = 20) -> Any:
        for attempt in range(4):
            try:
                r = self.s.post(self.base + method, json=payload, timeout=timeout)
            except requests.RequestException as e:
                log.warning("Telegram %s ag hatasi (%s), deneme %d", method, type(e).__name__, attempt + 1)
                time.sleep(2 * (attempt + 1))
                continue
            try:
                data = r.json()
            except ValueError:
                data = {"ok": False, "description": f"HTTP {r.status_code}"}
            if data.get("ok"):
                return data.get("result")
            if r.status_code == 429:
                wait = int((data.get("parameters") or {}).get("retry_after", 5))
                log.warning("Telegram flood limit, %ss bekleniyor", wait)
                time.sleep(wait + 1)
                continue
            if r.status_code >= 500:
                time.sleep(2 * (attempt + 1))
                continue
            raise TelegramError(f"{method}: {data.get('description')}")
        raise TelegramError(f"{method}: tekrar denemeler tukendi")

    # ---------- gonderim ----------
    def send(self, text: str, buttons: Optional[List[List[Dict[str, str]]]] = None, silent: bool = False) -> Optional[int]:
        chunks = [text[i : i + MAX_LEN] for i in range(0, len(text), MAX_LEN)] or [""]
        msg_id = None
        for n, chunk in enumerate(chunks):
            payload: Dict[str, Any] = {
                "chat_id": self.chat_id,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
                "disable_notification": silent,
            }
            if buttons and n == len(chunks) - 1:
                payload["reply_markup"] = {"inline_keyboard": buttons}
            try:
                res = self._call("sendMessage", payload)
                msg_id = res.get("message_id") if res else None
            except TelegramError as e:
                log.error("Mesaj gonderilemedi: %s", e)
        return msg_id

    def edit(self, message_id: int, text: str) -> None:
        try:
            self._call(
                "editMessageText",
                {"chat_id": self.chat_id, "message_id": message_id, "text": text[:MAX_LEN], "parse_mode": "HTML"},
            )
        except TelegramError as e:
            log.warning("Mesaj duzenlenemedi: %s", e)

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        try:
            self._call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:190]})
        except TelegramError as e:
            log.debug("answerCallbackQuery: %s", e)

    def set_commands(self, commands: List[tuple]) -> None:
        try:
            self._call("setMyCommands", {"commands": [{"command": c, "description": d} for c, d in commands]})
        except TelegramError as e:
            log.warning("Komut listesi ayarlanamadi: %s", e)

    # ---------- alim ----------
    def get_updates(self, timeout: int = 10) -> List[Dict[str, Any]]:
        payload: Dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
        if self.offset is not None:
            payload["offset"] = self.offset
        try:
            res = self._call("getUpdates", payload, timeout=timeout + 15)
        except TelegramError as e:
            log.warning("getUpdates: %s", e)
            time.sleep(3)
            return []
        updates = res or []
        if updates:
            self.offset = max(u["update_id"] for u in updates) + 1
        return updates

    def skip_pending(self) -> None:
        """Bot kapaliyken birikmis eski komutlari (or. eski bir 'AC' tusu) yok say."""
        try:
            res = self._call("getUpdates", {"offset": -1, "timeout": 0})
            if res:
                self.offset = res[-1]["update_id"] + 1
        except TelegramError as e:
            log.warning("skip_pending: %s", e)
