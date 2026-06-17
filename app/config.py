"""Конфигурация сервиса. Локальный single-user MVP."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
# путь к БД переопределяем через env (для Docker-тома: DB_PATH=/data/data.sqlite3)
DB_PATH = Path(os.environ["DB_PATH"]) if os.environ.get("DB_PATH") else BASE_DIR / "data.sqlite3"

# MOEX ISS
MOEX_BASE = "https://iss.moex.com/iss"
MOEX_BOARD = "TQBR"  # основной режим торгов акциями
MOEX_RPS = 5  # вежливый троттлинг (запросов в секунду)
MOEX_CACHE_TTL_SEC = 15 * 60  # кэш рыночных данных, 15 мин

# Дефолты модели (параметры пользователя, см. user_settings в БД)
DEFAULTS = {
    "hurdle": 0.05,        # SPEC §4.4 — база атаки в спокойное время
    "buffer": 0.02,        # маржа безопасности троичного сигнала
    "regime": "спокойное",  # 'спокойное' | 'шок'
    "risk_premium": 0.10,  # премия за риск эквити (рыночная РФ), для r
    # дефлятор: премия корзины поверх Росстата; пресет тактический/стратегический
    "deflator_premium": 0.0,    # пересчитывается из корзины, см. inflation
    "rosstat_current": 0.118,   # текущая офиц. инфляция (обновляется)
    "rosstat_smoothed": 0.07,   # сглаженная по циклу (для стратег. дефлятора)
    "deflator_preset": "тактический",  # 'тактический' | 'стратегический'
}

# Горизонт прогнозной модели (лет)
FORECAST_YEARS = 3

# Минимальный достоверный спред r-g (тест зоны оценки), SPEC §4.2
SPREAD_OK = 0.05      # >= → применимо
SPREAD_FRAGILE = 0.025  # >= → хрупко; < → вне зоны

DISCLAIMER = (
    "Не индивидуальная инвестиционная рекомендация. Сервис даёт расчёт и "
    "суждение для собственного решения пользователя."
)
