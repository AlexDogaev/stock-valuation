"""Структурный слой (лист Excel «Структурный слой», SPEC §4.3).

Качественное суждение (−2 … +2), корректирующее рост g ПЕРЕД количественным
прогоном. Машина считает считаемое; человек судит о несчитаемом.

ВАЖНО (расхождение SPEC ↔ Excel): балл считается по 5 измерениям
(ров + дизрупция + секул.TAM + регуляторика + демо). Госнавес в сумму
НЕ входит — он учитывается ОДИН раз (правило §4.3): либо уже сидит в
низком g, либо корректирует отдельно, но не дублируется множителем.
Это поведение листа Excel (формула F = B+C+D+E+K, без L=госнавес).
"""
from __future__ import annotations

from dataclasses import dataclass, field


# Шкала каждого измерения: −2 (угроза) … +2 (попутно)
DIMENSIONS = ("moat", "disruption", "tam", "regulation")
# demo и gosnaves — отдельные измерения, НЕ в балл (см. ниже)


def structural_score(
    *,
    moat: int,
    disruption: int,
    tam: int,
    regulation: int,
    demo: int = 0,   # §2 рефактор: демография — TOP-DOWN (тектоника), в балл эмитента НЕ входит
) -> int:
    """Балл = сумма измерений БЕЗ демографии и госнавеса.

    §2 тектонической рамы: демография поднята с ур.4 (эмитент) на ур.0 (top-down: базовый
    g рынка + секторный тектонический множитель). Per-эмитентный demo-балл больше НЕ
    суммируется (иначе двойной счёт с тектоникой); параметр оставлен для совместимости/дисплея
    как РЕЗИДУАЛ (эмитент-специфичная демография сверх сектора — сейчас не взвешивается)."""
    return moat + disruption + tam + regulation


def score_zone(score: int) -> str:
    if score <= -4:
        return "УГРОЗА"
    if score < 0:
        return "риск"
    if score >= 4:
        return "крепкий"
    return "норма"


def score_multiplier(score: int) -> float:
    """Балл → множитель к росту g (SPEC §4.3)."""
    if score <= -4:
        return 0.0      # вырождающийся: g обнуляется
    if score < 0:
        return 0.5
    if score >= 4:
        return 1.1
    return 1.0


@dataclass
class StructuralResult:
    moat: int
    disruption: int
    tam: int
    regulation: int
    demo: int
    gosnaves: int          # справочно, в балл НЕ входит
    score: int
    zone: str
    multiplier: float
    warnings: list[str] = field(default_factory=list)


def evaluate_structural(
    *,
    moat: int = 0,
    disruption: int = 0,
    tam: int = 0,
    regulation: int = 0,
    demo: int = 0,
    gosnaves: int = 0,
    is_rentier: bool = False,
    g_base: float | None = None,
) -> StructuralResult:
    """Полный прогон структурного слоя + валидатор двойного счёта госнавеса.

    Валидатор (SPEC §4.3, §9): если у РЕНТНОГО эмитента низкий базовый g
    (госнавес уже придушил рост) И отрицательный госнавес — предупреждаем
    о риске двойного счёта (не вычитать госнавес ещё раз множителем).
    """
    score = structural_score(
        moat=moat, disruption=disruption, tam=tam,
        regulation=regulation, demo=demo,
    )
    warnings: list[str] = []
    if is_rentier and gosnaves < 0 and g_base is not None and g_base < 0.03:
        warnings.append(
            "Двойной счёт госнавеса: у рентного эмитента низкий g уже отражает "
            "налоговое/тарифное придушивание. Госнавес учитывать ОДИН раз — "
            "не дублировать множителем."
        )
    if demo != 0:
        warnings.append(
            "Демография — TOP-DOWN (§2): учтена в базовом g рынка + секторном тектоническом "
            "множителе, в балл эмитента НЕ входит (анти-двойной-счёт). Этот demo-балл — резидуал."
        )
    if disruption != 0:
        warnings.append(
            "Дизрупция — гадание (низкая уверенность). Применять как риск-дисконт, "
            "не как факт."
        )
    return StructuralResult(
        moat=moat, disruption=disruption, tam=tam, regulation=regulation,
        demo=demo, gosnaves=gosnaves, score=score, zone=score_zone(score),
        multiplier=score_multiplier(score), warnings=warnings,
    )
