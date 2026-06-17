"""Слой refresh-джобов: единая точка обновления данных для планировщика и API.

Переиспользует существующую логику из seed.py (refresh_market/fundamentals/macro),
оборачивая её логированием и защитой от падений (джоб не должен ронять процесс).
Эти функции одинаково зовутся и из APScheduler (app/scheduler.py), и при желании
из отдельных Windows Task Scheduler-скриптов на сервере.
"""
from __future__ import annotations

import logging
from datetime import datetime

from app.data.seed import refresh_market, refresh_macro, refresh_fundamentals

log = logging.getLogger("refresh")


def _run(name: str, fn, *args) -> dict:
    """Запуск задачи с логом и перехватом ошибок (автономность не падает)."""
    started = datetime.now().isoformat(timespec="seconds")
    try:
        res = fn(*args)
        log.info("job %s OK @ %s: %s", name, started, res)
        return {"job": name, "ok": True, "result": res, "at": started}
    except Exception as e:  # noqa: BLE001
        log.exception("job %s FAILED @ %s", name, started)
        return {"job": name, "ok": False, "error": f"{type(e).__name__}: {e}", "at": started}


def job_refresh_quotes() -> dict:
    """Котировки/капа/дивы из MOEX (после закрытия торгов)."""
    return _run("refresh_quotes", refresh_market)


def job_refresh_macro() -> dict:
    """Ставка ЦБ + инфляция (еженедельно)."""
    return _run("refresh_macro", refresh_macro)


def job_refresh_fundamentals() -> dict:
    """Фундаментал из T-Invest (ежемесячно). Без токена — graceful skip внутри."""
    return _run("refresh_fundamentals", refresh_fundamentals)


def job_snapshot_history() -> dict:
    """Записать текущий срез фундаментала в financials_history (поквартально).
    Накапливает историю ROIC ВПЕРЁД — база для roic_years в маркерах качества.
    """
    from app.data.db import get_db, snapshot_financials
    from datetime import datetime

    def _snap():
        now = datetime.now()
        with get_db() as db:
            n = snapshot_financials(db, now.year, now.isoformat(timespec="seconds"))
        return {"year": now.year, "rows": n}

    return _run("snapshot_history", _snap)


def job_recompute_markers() -> dict:
    """Пересчёт и детекция изменений (сигнал/маркер/режим) → события + Telegram."""
    from app.data.db import get_db
    from app.core.events import detect_changes

    def _recompute():
        with get_db() as db:
            events = detect_changes(db, notify=True)
        return {"new_events": len(events),
                "messages": [e["message"] for e in events][:10]}

    return _run("recompute_markers", _recompute)
