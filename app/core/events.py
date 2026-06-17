"""Событийная система: детекция изменений маркеров/режима/сигналов + уведомления.

В отличие от расчётных величин (считаются на лету), предыдущее состояние
ХРАНИТСЯ (issuer_state, macro.last_regime) — чтобы поймать смену. После пересчёта
изменения пишутся в events и шлются в Telegram (если задан токен).
Первый запуск инициализирует состояние без спама уведомлениями.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from app.core import engine
from app.data import telegram
from app.data.db import upsert


def detect_changes(db: sqlite3.Connection, *, notify: bool = True) -> list[dict]:
    """Сравнить текущее состояние с сохранённым, записать события, уведомить."""
    now = datetime.now().isoformat(timespec="seconds")
    new_events: list[dict] = []

    # ── эмитенты: смена сигнала / маркера качества ──────────────────────────
    prev = {r["secid"]: r for r in db.execute(
        "SELECT secid, signal, quality_marker FROM issuer_state")}
    for x in engine.screen_all(db):
        secid, sig, qm = x["secid"], x["signal"], x["quality_marker"]
        p = prev.get(secid)
        if p is None:
            upsert(db, "issuer_state", dict(secid=secid, signal=sig,
                   quality_marker=qm, updated_at=now), pk="secid")
            continue  # инициализация без события
        if p["signal"] != sig:
            new_events.append({"kind": "signal", "secid": secid,
                "message": f"{x['name']} ({secid}): сигнал {p['signal']} → {sig}"})
        if p["quality_marker"] != qm:
            new_events.append({"kind": "quality", "secid": secid,
                "message": f"{x['name']} ({secid}): качество "
                           f"{p['quality_marker']} → {qm}"})
        if p["signal"] != sig or p["quality_marker"] != qm:
            upsert(db, "issuer_state", dict(secid=secid, signal=sig,
                   quality_marker=qm, updated_at=now), pk="secid")

    # ── режим рынка (ФНБ) ───────────────────────────────────────────────────
    try:
        from app.data.minfin import current_regime
        reg = current_regime()["regime"]
        last = db.execute("SELECT last_regime FROM macro WHERE id = 1").fetchone()["last_regime"]
        if last and last != reg:
            new_events.append({"kind": "regime", "secid": None,
                "message": f"Режим рынка: {last} → {reg}"})
        if last != reg:
            db.execute("UPDATE macro SET last_regime = ? WHERE id = 1", (reg,))
    except Exception:  # noqa: BLE001 — режим не должен валить детекцию
        pass

    # ── запись событий + уведомления ────────────────────────────────────────
    for e in new_events:
        cur = db.execute(
            "INSERT INTO events (ts, kind, secid, message, notified) VALUES (?,?,?,?,0)",
            (now, e["kind"], e["secid"], e["message"]))
        e["id"] = cur.lastrowid
        if notify and telegram.enabled():
            if telegram.send_message("🔔 " + e["message"]):
                db.execute("UPDATE events SET notified = 1 WHERE id = ?", (e["id"],))
    return new_events
