"""Клиент Anthropic (Opus) для черновиков класса B.

Ключ — env ANTHROPIC_API_KEY или файл .anthropic_key (в .gitignore, не в репо).
Доступ из РФ — через VPN на уровне машины (base_url стандартный). Если нужен
прокси — задать ANTHROPIC_BASE_URL. Модель — env ANTHROPIC_MODEL (дефолт Opus).
LLM НЕ выносит финальный вердикт — только черновик, человек подтверждает.
"""
from __future__ import annotations

import json
import logging
import os
import re

from app.config import BASE_DIR

KEY_FILE = BASE_DIR / ".anthropic_key"
DEFAULT_MODEL = "claude-opus-4-8"

log = logging.getLogger("llm")


def get_key() -> str | None:
    k = os.environ.get("ANTHROPIC_API_KEY")
    if k:
        return k.strip()
    for f in (KEY_FILE, BASE_DIR / ".anthropic_key.txt"):
        if f.exists():
            t = f.read_text(encoding="utf-8").strip()
            if t:
                return t
    return None


def enabled() -> bool:
    return get_key() is not None


def call_json(system: str, user: str, *, max_tokens: int = 1500) -> tuple[dict | None, str | None]:
    """Запрос к Opus, ожидается JSON в ответе. Возвращает (данные, ошибка)."""
    key = get_key()
    if not key:
        return None, "ANTHROPIC_API_KEY не задан (.anthropic_key)"
    try:
        from anthropic import Anthropic
        base_url = os.environ.get("ANTHROPIC_BASE_URL")  # опц. прокси; при VPN не нужен
        client = Anthropic(api_key=key, base_url=base_url) if base_url else Anthropic(api_key=key)
        model = os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)
        msg = client.messages.create(
            model=model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        # вытащить JSON (на случай обрамляющего текста/```json)
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return None, "в ответе модели нет JSON"
        return json.loads(m.group(0)), None
    except Exception as e:  # noqa: BLE001 — без утечки ключа в лог
        log.warning("anthropic call failed: %s", type(e).__name__)
        return None, f"{type(e).__name__}: {e}"
