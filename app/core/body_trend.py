"""Тренд тела бизнеса — автоматический прокси (лист «Тренд тела (авто)»).

Тело ≠ рублёвая выручка. Прокси из РЕАЛЬНОЙ выручки, капекс/D&A, тренда ROIC.
Ловит «выемку» (низкий капекс при высоких дивах) и реальную стагнацию.
НЕ ловит физику ресурсных (добыча/запасы) — для них флаг ручной проверки.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BodyTrend:
    nominal_cagr: float
    real_cagr: float
    capex_to_da: float
    roic_trend: float
    verdict: str         # "ТАЕТ (−1)" / "РАСТЁТ (+1)" / "СТАБИЛЬНО (0)"
    body_trend_int: int  # −1 / +1 / 0  → вход в классификацию
    confidence_flag: str


def body_trend(
    *,
    revenue_old: float,
    revenue_last: float,
    years: int,
    capex: float,
    depreciation: float,
    roic_old: float,
    roic_last: float,
    avg_inflation: float,
    is_resource: bool = False,
) -> BodyTrend:
    nominal_cagr = (revenue_last / revenue_old) ** (1.0 / years) - 1.0
    real_cagr = nominal_cagr - avg_inflation
    capex_da = capex / depreciation if depreciation else float("inf")
    roic_trend = roic_last - roic_old

    if real_cagr < 0 and capex_da < 1.1:
        verdict, trend_int = "ТАЕТ (−1)", -1
    elif real_cagr > 0.03 and capex_da > 1.2:
        verdict, trend_int = "РАСТЁТ (+1)", 1
    else:
        verdict, trend_int = "СТАБИЛЬНО (0)", 0

    if is_resource:
        flag = "РЕСУРСНЫЙ: проверь добычу/запасы вручную (прокси не ловит физику)!"
    elif abs(real_cagr) < 0.02:
        flag = "у нуля — низкая уверенность"
    else:
        flag = "ок"

    return BodyTrend(
        nominal_cagr=nominal_cagr, real_cagr=real_cagr, capex_to_da=capex_da,
        roic_trend=roic_trend, verdict=verdict, body_trend_int=trend_int,
        confidence_flag=flag,
    )
