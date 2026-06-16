"""Барбелл-калькулятор (лист «Барбелл-калькулятор», SPEC §4.4).

Защита (≈0% реального, порох) + Атака (качество в дислокациях). Основная
доходность приходит в ШОК, не в спокойное время. Цель +5% реального держится
на доборе ~40% атаки в шоки под ~+18% от глубокого дна.
"""
from __future__ import annotations

from dataclasses import dataclass


def average_attack(*, base: float, shock_share: float, shock_return: float) -> float:
    """Средняя атака = (1−доля_в_шоки)×база + доля_в_шоки×шоковая_доходность."""
    return (1.0 - shock_share) * base + shock_share * shock_return


def portfolio_return(
    *, attack_share: float, avg_attack: float, defense_return: float = 0.0
) -> float:
    """Портфель = доля_атаки×ср.атака + доля_защиты×защита."""
    return attack_share * avg_attack + (1.0 - attack_share) * defense_return


@dataclass
class BarbellResult:
    attack_share: float
    base: float
    defense_return: float
    shock_share: float
    shock_return: float
    avg_attack: float
    portfolio: float
    target: float
    meets_target: bool
    scenarios: dict[str, float]  # доля атаки в шоки → доходность портфеля


def barbell(
    *,
    attack_share: float = 0.5,
    base: float = 0.05,
    defense_return: float = 0.0,
    shock_share: float = 0.4,
    shock_return: float = 0.18,
    target: float = 0.05,
) -> BarbellResult:
    avg = average_attack(base=base, shock_share=shock_share, shock_return=shock_return)
    port = portfolio_return(attack_share=attack_share, avg_attack=avg,
                            defense_return=defense_return)

    def scen(sh: float) -> float:
        a = average_attack(base=base, shock_share=sh, shock_return=shock_return)
        return portfolio_return(attack_share=attack_share, avg_attack=a,
                                defense_return=defense_return)

    return BarbellResult(
        attack_share=attack_share, base=base, defense_return=defense_return,
        shock_share=shock_share, shock_return=shock_return,
        avg_attack=avg, portfolio=port, target=target,
        meets_target=port >= target,
        scenarios={
            "только спокойное (0%)": scen(0.0),
            "20% атаки в шоки": scen(0.20),
            "40% атаки в шоки": scen(0.40),
        },
    )
