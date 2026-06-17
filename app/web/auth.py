"""HTTP Basic Auth для прод-доступа ограниченного круга (per-user).

Креды — в файле `.auth` в корне проекта (gitignored, ТОЛЬКО на сервере): строки
`username:password` (одна на человека; # — комментарий). Файла нет/пуст →
авторизация ВЫКЛЮЧЕНА (локальная разработка остаётся открытой).

ВАЖНО: наружу в интернет — только через HTTPS (Cloudflare Tunnel / reverse-proxy).
Basic шлёт креды base64 (не шифрование) — по голому HTTP их видно в трафике.
"""
from __future__ import annotations

import base64
import os
import secrets

from app.config import BASE_DIR

AUTH_FILE = BASE_DIR / ".auth"


def load_users() -> dict[str, str]:
    """Собрать {user: password}. Источники: env APP_AUTH (для Docker) + файл .auth
    (для сервера; дополняет/переопределяет env). Пусто → авторизация выключена."""
    users: dict[str, str] = {}
    # 1) env APP_AUTH="user:pass,user2:pass2"
    for pair in os.environ.get("APP_AUTH", "").split(","):
        pair = pair.strip()
        if ":" in pair:
            u, p = pair.split(":", 1)
            if u.strip() and p.strip():
                users[u.strip()] = p.strip()
    # 2) файл .auth
    fname = os.environ.get("APP_AUTH_FILE")
    path = (BASE_DIR / fname) if fname else AUTH_FILE
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            u, p = line.split(":", 1)
            if u.strip() and p.strip():
                users[u.strip()] = p.strip()
    return users


def check_basic(header: str | None, users: dict[str, str]) -> bool:
    """Проверить заголовок Authorization: Basic ... против списка (constant-time)."""
    if not header or not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:]).decode("utf-8")
        user, pwd = decoded.split(":", 1)
    except Exception:  # noqa: BLE001 — любой кривой заголовок = отказ
        return False
    expected = users.get(user)
    if expected is None:
        return False
    return secrets.compare_digest(pwd, expected)
