"""Личный дефлятор инфляции (лист Excel «Личная инфляция», SPEC §4.4).

Доходность реальна только над ЛИЧНОЙ инфляцией. Для дорогого услуги-тяжёлого
стиля корзина состоит из категорий-лидеров инфляции → личная выше официальной.

Дефлятор = официальная (Росстат, авто) + премия корзины.
Премия НЕ константа — пересчитывается как (личная − официальная).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Category:
    name: str
    weight: float       # вес в тратах
    inflation: float    # инфляция категории
    source: str = ""


# Дефолтная корзина из листа «Личная инфляция» (расход ~450 тыс/мес)
DEFAULT_BASKET = [
    Category("Продукты дома", 0.16, 0.15, "Мясо/молочка/овощи +10-25%"),
    Category("Доставка еды + рестораны", 0.16, 0.17, "НДС, курьеры"),
    Category("Путешествия (авиа+отели)", 0.15, 0.12, "Туруслуги +10,7%, турналог"),
    Category("Такси", 0.08, 0.20, "Дефицит водителей, утильсбор"),
    Category("Техника/смартфоны", 0.07, 0.15, "Импорт, пошлины +10-25%"),
    Category("ЖКХ/быт/жильё", 0.15, 0.12, "Тарифы индексируются выше цели"),
    Category("Одежда/услуги/прочее", 0.23, 0.12, "Услуги быстрее товаров"),
]


def weighted_inflation(basket: list[Category]) -> float:
    """Личная инфляция = SUMPRODUCT(вес, инфл) / SUM(вес)."""
    total_w = sum(c.weight for c in basket)
    if total_w == 0:
        raise ValueError("Сумма весов корзины = 0")
    return sum(c.weight * c.inflation for c in basket) / total_w


@dataclass
class Deflator:
    personal: float          # личная посчитанная (взвешенная корзина)
    rosstat_current: float   # офиц. текущая
    basket_premium: float    # премия = личная − Росстат (аддитивная)
    tactical: float          # Росстат текущий + премия (для «дёшево ли сейчас»)
    strategic: float         # Росстат сглаженный + премия (для 20-летнего DCA)
    weights_sum: float = 1.0
    warnings: list[str] = field(default_factory=list)


def compute_deflator(
    *,
    basket: list[Category] | None = None,
    rosstat_current: float = 0.118,
    rosstat_smoothed: float = 0.07,
) -> Deflator:
    """Авто-пересчёт тактического и стратегического дефлятора."""
    basket = basket if basket is not None else DEFAULT_BASKET
    personal = weighted_inflation(basket)
    premium = personal - rosstat_current  # аддитивная, консервативнее
    warnings: list[str] = []
    w_sum = sum(c.weight for c in basket)
    if abs(w_sum - 1.0) > 0.001:
        warnings.append(f"Сумма весов корзины = {w_sum:.3f}, не 100%.")
    if premium < 0:
        warnings.append(
            "Премия корзины отрицательна — личная инфляция ниже официальной. "
            "Проверь веса/категории."
        )
    return Deflator(
        personal=personal,
        rosstat_current=rosstat_current,
        basket_premium=premium,
        tactical=rosstat_current + premium,      # = личная
        strategic=rosstat_smoothed + premium,
        weights_sum=w_sum,
        warnings=warnings,
    )


def active_deflator(d: Deflator, preset: str) -> float:
    """Выбор пресета: 'тактический' (сейчас) / 'стратегический' (20 лет)."""
    return d.strategic if preset.lower().startswith("страт") else d.tactical
