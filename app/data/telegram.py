"""Telegram-нотификатор (отправка уведомлений о событиях).

Токен — из env TELEGRAM_TOKEN или файла .telegram_token (в .gitignore, не в репо).
chat_id — из env TELEGRAM_CHAT_ID / файла .telegram_chat / DEFAULT_CHAT_ID.
Без токена — graceful: enabled() == False, send_message молча возвращает False.
"""
from __future__ import annotations

import logging
import os

import httpx

from app.config import BASE_DIR

TOKEN_FILE = BASE_DIR / ".telegram_token"
CHAT_FILE = BASE_DIR / ".telegram_chat"
DEFAULT_CHAT_ID = "872030421"  # owner; перекрывается env/файлом

log = logging.getLogger("telegram")


def get_token() -> str | None:
    tok = os.environ.get("TELEGRAM_TOKEN")
    if tok:
        return tok.strip()
    for f in (TOKEN_FILE, BASE_DIR / ".telegram_token.txt"):
        if f.exists():
            t = f.read_text(encoding="utf-8").strip()
            if t:
                return t
    return None


def get_chat_id() -> str:
    cid = os.environ.get("TELEGRAM_CHAT_ID")
    if cid:
        return cid.strip()
    if CHAT_FILE.exists():
        c = CHAT_FILE.read_text(encoding="utf-8").strip()
        if c:
            return c
    return DEFAULT_CHAT_ID


def enabled() -> bool:
    return get_token() is not None


def send_message(text: str, chat_id: str | None = None) -> bool:
    """Отправить сообщение. True/False. Никогда не бросает (нотификатор не критичен)."""
    token = get_token()
    if not token:
        log.info("telegram: токен не задан — пропуск уведомления")
        return False
    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id or get_chat_id(), "text": text,
                  "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=15.0,
        )
        # НЕ логируем URL (содержит токен). Только статус и описание ошибки от Telegram.
        if r.status_code != 200:
            try:
                desc = r.json().get("description", "")
            except Exception:  # noqa: BLE001
                desc = ""
            log.warning("telegram send: HTTP %s %s", r.status_code, desc)
            return False
        return True
    except httpx.HTTPError as e:  # сетевые — без URL (в нём токен)
        log.warning("telegram send: %s", type(e).__name__)
        return False
