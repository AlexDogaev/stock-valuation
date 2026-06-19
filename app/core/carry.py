"""Carry — единый рублёвый безрисковый ориентир по ТРАЕКТОРИИ КС (REVIEW мультиассет).

`carry(horizon)` = средняя ожидаемая рублёвая безрисковая доходность по прогнозной траектории
ключевой ставки за период удержания, НЕ спот-ставка. Унифицирует hurdle/альтернативную стоимость
для ВСЕХ классов (акция/облигация/FX/золото): «припарковать в ОФЗ под среднюю КС» — база сравнения.

Та же траектория КС, что кормит дефлятор (terminal_inflation_from_ks) и градацию ставки.
"""
from __future__ import annotations


def carry_rate(current_ks: float, terminal_ks: float | None, years: int | None) -> float:
    """Средняя КС по линейному глайду current→terminal за horizon (для линейного = (нач+кон)/2).

    Горизонт ≤ 1 года или нет терминала → спот-КС (глайда нет). Это НОМИНАЛЬНЫЙ безриск —
    стоимость carry для FX и альтернативная парковка в ОФЗ.
    """
    if terminal_ks is None or years is None or years <= 1:
        return current_ks
    n = int(years)
    # среднее по годам: год t (0..n-1) = current + (terminal-current)*t/(n-1)
    return sum(current_ks + (terminal_ks - current_ks) * t / (n - 1) for t in range(n)) / n
