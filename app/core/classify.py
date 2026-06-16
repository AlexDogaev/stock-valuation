"""Классификация эмитента — какой режим оценки применять.

Лист Excel «Структурный профиль»: по СТРУКТУРЕ (ROIC−WACC, тренд тела,
рост, payout), а не по отраслевому ярлыку (НОВАТЭК ≠ Лукойл).
Плюс упрощённая троичная ветка SPEC §4.2.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# Детальная классификация (6 типов) — лист «Структурный профиль»
def detailed_type(
    *,
    body_trend: int,        # 1 растёт / 0 стабильно / −1 тает
    revenue_growth: float,  # рост выручки, доля/год
    roic_minus_wacc: float,
    payout: float,
) -> str:
    if body_trend < 0:
        return "ЛИКВИДАЦИОННЫЙ"
    if revenue_growth > 0.20:
        if roic_minus_wacc > 0.10:
            return "РАСТУЩИЙ КАЧЕСТВ."
        if roic_minus_wacc > 0:
            return "РАСТУЩИЙ СРЕДН."
        return "РАСТУЩИЙ СЖИГАЮЩИЙ"
    if payout > 0.70 and roic_minus_wacc < 0.05:
        return "ЗРЕЛЫЙ ДИВИДЕНДНЫЙ"
    if roic_minus_wacc >= 0:
        return "ЗРЕЛЫЙ КАЧЕСТВ."
    return "ЗРЕЛЫЙ СЛАБЫЙ"


def valuation_regime(detailed: str) -> str:
    """Какой режим оценки соответствует типу."""
    if detailed == "ЛИКВИДАЦИОННЫЙ":
        return "Ликвидация: дивы − эрозия тела"
    if detailed.startswith("РАСТУЩИЙ"):
        return "Growth: двухстадийный DCF со сжатием"
    return "Зрелый: P/B=(ROE−g)/(r−g)"


# Упрощённая троичная классификация — SPEC §4.2
def simple_type(
    *,
    structural_score: int,
    body_trend_or_growth: float,  # рост тела (<0 → вырождение)
    roic: float,
    wacc: float,
    growth: float,
    inflation: float,
) -> str:
    if structural_score <= -4 or body_trend_or_growth < 0:
        return "вырождающийся"
    if roic > wacc and growth > inflation:
        return "растущий"
    return "зрелый"


def phase_years(roic_minus_wacc: float) -> int:
    """Длительность фазы роста N (SPEC §4.2, лист «Growth калиброванный»).
    ROIC−WACC > 15 п.п. → 7 лет; > 0 → 5; < 0 → 3.
    """
    if roic_minus_wacc > 0.15:
        return 7
    if roic_minus_wacc > 0:
        return 5
    return 3


def calibrated_terminal_r(roic_minus_wacc: float) -> float:
    """Терминальная ставка r, калиброванная по качеству (лист «Growth калибр.»).
    Качество доказано (большой спред) → риск-надбавка ниже.
    """
    if roic_minus_wacc > 0.15:
        return 0.18
    if roic_minus_wacc > 0:
        return 0.20
    return 0.23


@dataclass
class Classification:
    detailed: str
    regime: str
    simple: str
    phase_n: int
    terminal_r: float
    roic_minus_wacc: float


def classify(
    *,
    body_trend: int,
    revenue_growth: float,
    roic: float,
    wacc: float,
    payout: float,
    structural_score: int = 0,
    inflation: float = 0.10,
) -> Classification:
    spread = roic - wacc
    detailed = detailed_type(
        body_trend=body_trend, revenue_growth=revenue_growth,
        roic_minus_wacc=spread, payout=payout,
    )
    simple = simple_type(
        structural_score=structural_score, body_trend_or_growth=body_trend,
        roic=roic, wacc=wacc, growth=revenue_growth, inflation=inflation,
    )
    return Classification(
        detailed=detailed,
        regime=valuation_regime(detailed),
        simple=simple,
        phase_n=phase_years(spread),
        terminal_r=calibrated_terminal_r(spread),
        roic_minus_wacc=spread,
    )
