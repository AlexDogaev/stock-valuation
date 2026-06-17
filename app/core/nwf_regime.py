"""Режим рынка по состоянию ФНБ + бюджетного правила (чистая функция).

Тающий ликвидный ФНБ + дефицитный бюджет (Urals ниже отсечки) = структурное
фискально-девальвационное давление. В РФ оно традиционно стравливается через
ОСЛАБЛЕНИЕ РУБЛЯ (слабый рубль раздувает нефтегаз-доходы в рублях, закрывая дефицит).
Поэтому это не «всё хорошо», а девальвационный риск → перевес в защиту и СМЕЩЕНИЕ
защиты из рублёвых ОФЗ-фикс в золото/флоатеры, атаки — в экспортёров (выручка в валюте).

Скоринг давления (0..6): ликвидный ФНБ + месяцы до нуля + дефицит (каждый 0/1/2).
Дефицит — полноценный драйвер, а не сноска. Глубокая просадка рынка = ШОК-override.
"""
from __future__ import annotations

from dataclasses import dataclass

SHOCK_DRAWDOWN = 0.27          # просадка рынка от максимума → ШОК
NWF_THIN_PCT, NWF_ACUTE_PCT = 3.0, 1.5        # ликвидный ФНБ, % ВВП: тонкий / острый
NWF_THIN_MONTHS, NWF_ACUTE_MONTHS = 24, 12    # месяцев до исчерпания: тревожно / остро
DEFICIT_DEEP = 10.0           # Urals ниже отсечки на ≥$N — глубокий дефицит
RISK_SCORE = 3                # скор давления, с которого режим = RISK


@dataclass
class NwfRegime:
    regime: str            # NORMAL | RISK | SHOCK
    defense: float         # доля защиты
    attack: float          # доля атаки
    budget_sign: float     # Urals − отсечка: <0 → бюджет дефицитный
    deval_score: int       # 0..6 — фискально-девальвационное давление
    deval_pressure: str    # low | elevated | high
    note: str


def _fiscal_pressure(liquid_nwf_pct: float, months_to_zero: float,
                     urals: float, cutoff: float) -> int:
    """0..6: ликвидность ФНБ + горизонт + дефицит бюджета (драйвер девальвации)."""
    score = 0
    if liquid_nwf_pct < NWF_ACUTE_PCT:
        score += 2
    elif liquid_nwf_pct < NWF_THIN_PCT:
        score += 1
    if months_to_zero < NWF_ACUTE_MONTHS:
        score += 2
    elif months_to_zero < NWF_THIN_MONTHS:
        score += 1
    deficit = cutoff - urals
    if deficit >= DEFICIT_DEEP:
        score += 2
    elif deficit > 0:
        score += 1
    return score


def _pressure_level(score: int) -> str:
    if score >= 4:
        return "high"
    if score >= 2:
        return "elevated"
    return "low"


def nwf_regime(*, liquid_nwf_pct: float, months_to_zero: float,
               urals: float, cutoff: float, market_drawdown: float) -> NwfRegime:
    budget_sign = urals - cutoff
    score = _fiscal_pressure(liquid_nwf_pct, months_to_zero, urals, cutoff)
    pressure = _pressure_level(score)

    if market_drawdown > SHOCK_DRAWDOWN:
        return NwfRegime(
            regime="SHOCK", defense=0.20, attack=0.80, budget_sign=budget_sign,
            deval_score=score, deval_pressure=pressure,
            note=f"Просадка рынка {market_drawdown*100:.0f}% > {SHOCK_DRAWDOWN*100:.0f}% — "
                 f"жадный добор качества (ШОК важнее фундамента ФНБ).")

    if score >= RISK_SCORE:
        deficit_txt = "" if budget_sign >= 0 else f" Бюджет дефицитный (Urals {urals:.0f} < отсечки {cutoff:.0f})."
        return NwfRegime(
            regime="RISK", defense=0.70, attack=0.30, budget_sign=budget_sign,
            deval_score=score, deval_pressure=pressure,
            note=f"Фискально-девальвационное давление {'ВЫСОКОЕ' if pressure == 'high' else 'повышенное'} "
                 f"(скор {score}/6): ликвидный ФНБ {liquid_nwf_pct:.1f}% ВВП, {months_to_zero:.0f} мес до нуля."
                 f"{deficit_txt} Риск ослабления рубля → защита в золото/флоатеры, атака в экспортёров.")

    if pressure != "low":
        tail = " Девал-давление умеренное — следить."
    elif liquid_nwf_pct < NWF_THIN_PCT:
        # буфер тонкий, но текущий триггер не взведён (нефть выше отсечки) — честная оговорка
        tail = (f" Буфер тонкий: ликвидный ФНБ {liquid_nwf_pct:.1f}% ВВП — перевернётся в RISK, "
                f"если Urals уйдёт ниже отсечки {cutoff:.0f}$ (сейчас {urals:.0f}$).")
    else:
        tail = ""
    head = ("ФНБ устойчив — нормальный режим, базовый поток в атаку." if liquid_nwf_pct >= NWF_THIN_PCT
            else "Нормальный режим: оил-правило в профиците (Urals выше отсечки), ФНБ пополняется.")
    return NwfRegime(
        regime="NORMAL", defense=0.30, attack=0.70, budget_sign=budget_sign,
        deval_score=score, deval_pressure=pressure,
        note=head + tail + ("" if budget_sign >= 0 else " Бюджет дефицитный — следить."))
