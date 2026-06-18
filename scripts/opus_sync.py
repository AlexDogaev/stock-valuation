#!/usr/bin/env python
"""Dev→prod синхронизация Opus-advisory (прод гео-заблокирован Anthropic, 403).

Прод-сервер (RU) не достаёт api.anthropic.com — региональная блокировка. Поэтому
Opus гоняется на DEV-машине (она достаёт Anthropic), а результаты кладутся в ПРОД БД.

Считает 3 advisory по КУРИРУЕМЫМ входам прода (macro_context, rate_signal, macro):
  • macro_analysis  — Opus-разбор режима ФНБ
  • shock_risk      — форвардная вероятность ШОКА
  • rate_trajectory — градация траектории КС (пейс решений ЦБ + риторика)
и пушит ТОЛЬКО эти 3 строки в живую прод-БД (остальные данные прода не трогает).

Запуск на dev (ключ SSH загружен в агент /tmp/cc-ssh.sock, есть .anthropic_key):
    python scripts/opus_sync.py

Расписание: можно повесить на dev (Task Scheduler), но нужен не-passphrase доступ
к серверу. Пока — по требованию; кэш на проде живёт между прогонами.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

try:  # вывод UTF-8 (Windows-консоль по умолчанию cp1251 — падает на →/✓)
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

REPO = Path(__file__).resolve().parent.parent
HOST = "invest@solarwings.tech"
PROJ = "/opt/invest/stock-valuation"
PROD_DB = f"{PROJ}/data/data.sqlite3"
PUSH_JSON_HOST = f"{PROJ}/data/_opus_push.json"
SSH_SOCK = os.environ.get("SSH_AUTH_SOCK", "/tmp/cc-ssh.sock")
TABLES = ["macro_analysis", "shock_risk", "rate_trajectory"]


def _run(cmd: list[str]) -> None:
    env = {**os.environ, "SSH_AUTH_SOCK": SSH_SOCK}
    subprocess.run(cmd, env=env, check=True)


def main() -> None:
    sys.path.insert(0, str(REPO))
    tmp = REPO / "scripts" / ".prod_db.sqlite3"
    payload = REPO / "scripts" / "_opus_push.json"

    print(f"· тяну прод-БД → {tmp.name}")
    _run(["scp", "-o", "ConnectTimeout=25", f"{HOST}:{PROD_DB}", str(tmp)])

    # ВАЖНО: DB_PATH до импорта app.config — чтобы оценки шли по входам прода
    os.environ["DB_PATH"] = str(tmp)
    from app.data import llm
    if not llm.enabled():
        sys.exit("✗ локальный Opus-ключ не найден (.anthropic_key) — нечем считать")
    from app.core import llm_macro
    from app.data.db import get_db, init_db
    init_db()  # схема на случай старого снимка

    with get_db() as db:
        a = llm_macro.analyze_macro(db)
        s = llm_macro.assess_shock(db)
        t = llm_macro.assess_rate_trajectory(db)
        rows = {}
        for tbl in TABLES:
            r = db.execute(f"SELECT * FROM {tbl} WHERE id=1").fetchone()
            rows[tbl] = dict(r) if r else None

    print(f"· Opus: ФНБ={ (a or {}).get('regime_opus') } | "
          f"ШОК={ (s or {}).get('aggregate_pct') }% | КС={ (t or {}).get('grade') }")

    payload.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    print("· пушу 3 строки в прод (живая БД)")
    _run(["scp", "-o", "ConnectTimeout=25", str(payload), f"{HOST}:{PUSH_JSON_HOST}"])
    apply_cmd = (
        f"cd {PROJ} && docker compose -f docker-compose.prod.yml exec -T app python -c "
        "\"import json; from app.data.db import connect, upsert; "
        "d=json.load(open('/data/_opus_push.json', encoding='utf-8')); "
        "db=connect(); "
        "[upsert(db,k,v,pk='id') for k,v in d.items() if v]; "
        "db.commit(); db.close(); "
        "print('  pushed:', [k for k,v in d.items() if v])\" "
        f"&& rm -f {PUSH_JSON_HOST}"
    )
    _run(["ssh", "-o", "ConnectTimeout=25", HOST, apply_cmd])

    tmp.unlink(missing_ok=True)
    payload.unlink(missing_ok=True)
    print("✓ готово — прод показывает свежие Opus-оценки")


if __name__ == "__main__":
    main()
