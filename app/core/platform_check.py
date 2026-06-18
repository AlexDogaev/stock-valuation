"""Платформы: критерий монетизации + проверка насыщения слоя (INSTRUCTIONS §3, NOTES §2).

Категориальная ошибка (НЕ делать): оценивать платформу по автономной прибыльности
торгового ядра. Ядро by design loss-leader; монетизирует экосистема (реклама,
финтех, логистика). Правильный критерий: понятен ли механизм экосистемной
монетизации И начал ли доказываться.

Высокомаржинальный слой даёт КРАТНЫЙ апсайд только если НЕ насыщен. Зрелый,
агрессивно монетизированный слой = признак ОТСУТСТВИЯ апсайда. Три теста (класс B,
входы — суждение/веб-заземление):
  1. takerate против бенчмарка (выше эталона → ближе к насыщению);
  2. занятость инвентаря (доля платных позиций/показов);
  3. цена/CPM против юнит-экономики платящего клиента (есть ли запас).
Вывод кормит разложение апсайда (§4 → upside.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field

OCCUPANCY_SATURATED = 0.85   # занятость инвентаря выше — слой плотно занят


@dataclass
class SaturationResult:
    tests_passed: int            # сколько из 3 тестов сигналят насыщение
    tests_total: int
    layer_saturated: bool        # большинство → слой насыщен (апсайда в нём нет)
    detail: dict[str, bool | None]
    warnings: list[str] = field(default_factory=list)


def assess_saturation(
    *,
    takerate: float | None = None,
    benchmark_takerate: float | None = None,
    inventory_occupancy: float | None = None,
    cpm_headroom: float | None = None,   # запас цены над юнит-экономикой клиента: ≤0 → упёрто
) -> SaturationResult:
    """Насыщен ли монетизационный слой. Большинство сработавших тестов → насыщен."""
    t_takerate = (takerate >= benchmark_takerate
                  if takerate is not None and benchmark_takerate is not None else None)
    t_occupancy = (inventory_occupancy >= OCCUPANCY_SATURATED
                   if inventory_occupancy is not None else None)
    t_price = (cpm_headroom <= 0.0 if cpm_headroom is not None else None)

    flags = [t_takerate, t_occupancy, t_price]
    known = [f for f in flags if f is not None]
    passed = sum(1 for f in known if f)
    # насыщен, если большинство ИЗВЕСТНЫХ тестов сигналят (минимум 2 при 3 известных)
    saturated = bool(known) and passed >= max(2, (len(known) + 1) // 2)

    warnings: list[str] = []
    if not known:
        warnings.append("Тесты насыщения без входов (takerate/занятость/CPM) — нужен класс B "
                        "(LLM-черновик + веб-заземление + человек).")
    elif saturated:
        warnings.append("Монетизационный слой насыщен → кратного апсайда в нём НЕТ "
                        "(растёт ≈ с оборотом, не быстрее). Это признак исчерпанности, не силы.")
    return SaturationResult(
        tests_passed=passed, tests_total=len(known), layer_saturated=saturated,
        detail={"takerate_above_benchmark": t_takerate,
                "inventory_occupied": t_occupancy, "cpm_maxed": t_price},
        warnings=warnings,
    )


def platform_monetization_ok(*, mechanism_clear: bool, started_proving: bool) -> bool:
    """Критерий монетизации ДЛЯ ПЛАТФОРМЫ (§3): механизм экосистемной монетизации
    понятен И начал доказываться — а НЕ «прибыльно ли торговое ядро автономно»."""
    return bool(mechanism_clear and started_proving)
