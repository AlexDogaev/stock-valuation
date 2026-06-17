"""Планировщик автономного обновления (APScheduler, в процессе FastAPI).

Время — Europe/Moscow. Джобы переиспользуют app/data/refresh.py.
На сервере альтернативно те же job_* можно дёргать из Windows Task Scheduler
(отдельные скрипты), тогда планировщик можно не запускать (SCHEDULER_ENABLED=0).
"""
from __future__ import annotations

import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler

from app.data.refresh import (
    job_refresh_quotes, job_refresh_macro,
    job_refresh_fundamentals, job_recompute_markers, job_snapshot_history,
)

log = logging.getLogger("scheduler")
_scheduler: BackgroundScheduler | None = None


def start_scheduler() -> BackgroundScheduler | None:
    """Запустить фоновый планировщик. Идемпотентно; выключается env-флагом."""
    global _scheduler
    if os.environ.get("SCHEDULER_ENABLED", "1") == "0":
        log.info("scheduler отключён (SCHEDULER_ENABLED=0)")
        return None
    if _scheduler and _scheduler.running:
        return _scheduler

    sch = BackgroundScheduler(timezone="Europe/Moscow")
    # котировки — после закрытия основной сессии MOEX
    sch.add_job(job_refresh_quotes, "cron", hour=19, minute=30,
                id="quotes", replace_existing=True, misfire_grace_time=3600)
    # макро (ставка ЦБ + инфляция) — еженедельно
    sch.add_job(job_refresh_macro, "cron", day_of_week="mon", hour=9,
                id="macro", replace_existing=True, misfire_grace_time=3600)
    # фундаментал (T-Invest) — раз в месяц
    sch.add_job(job_refresh_fundamentals, "cron", day=1, hour=6,
                id="fundamentals", replace_existing=True, misfire_grace_time=6 * 3600)
    # снапшот фундаментала в историю — поквартально (накопление ROIC вперёд)
    sch.add_job(job_snapshot_history, "cron", month="1,4,7,10", day=5, hour=7,
                id="snapshot", replace_existing=True, misfire_grace_time=6 * 3600)
    # пересчёт маркеров/событий — ежедневно вечером, после котировок
    sch.add_job(job_recompute_markers, "cron", hour=20,
                id="markers", replace_existing=True, misfire_grace_time=3600)
    sch.start()
    _scheduler = sch
    log.info("scheduler запущен: %s", [j.id for j in sch.get_jobs()])
    return sch


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None
