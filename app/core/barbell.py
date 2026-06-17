"""Барбелл-калькулятор (лист «Барбелл-калькулятор», SPEC §4.4).

Защита (≈0% реального, порох) + Атака (качество в дислокациях). Основная
доходность приходит в ШОК, не в спокойное время. Цель +5% реального держится
на доборе ~40% атаки в шоки под ~+18% от глубокого дна.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ── Режимная аллокация рукавов (§4 плана автономности) ────────────────────────
# Защита делится: ОФЗ-фикс 60% / золото 28% / флоатеры 12% рукава защиты.
# Атака: ядро доказанного качества (целевой минимум ~30% портфеля, если хватает)
# + резерв на добор перспективного качества в шок.
DEF_OFZ, DEF_GOLD, DEF_FLOATER = 0.60, 0.28, 0.12
# девал-тилт: смещение защиты из рублёвых ОФЗ-фикс в золото/флоатеры (ОФЗ, золото, флоатер)
DEF_SPLIT_DEVAL = {
    "elevated": (0.40, 0.40, 0.20),
    "high":     (0.25, 0.50, 0.25),
}
CORE_TARGET = 0.30  # целевая доля ядра доказанного качества от всего портфеля


@dataclass
class RegimeAllocation:
    regime: str
    defense_total: float
    attack_total: float
    defense: dict           # ofz_fixed / gold / floater (доли портфеля)
    attack: dict            # core_proven / shock_reserve (доли портфеля)
    notes: list[str] = field(default_factory=list)


def regime_allocation(*, regime: str, defense_share: float, attack_share: float,
                      deval_pressure: str = "low") -> RegimeAllocation:
    """Собрать структуру портфеля по режиму (из nwf_regime: defense/attack).

    deval_pressure (low|elevated|high) тилтует СПЛИТ защиты: из рублёвых ОФЗ-фикс
    в золото/флоатеры (защита от девальвации/инфляции).
    """
    ofz_w, gold_w, fl_w = DEF_SPLIT_DEVAL.get(deval_pressure, (DEF_OFZ, DEF_GOLD, DEF_FLOATER))
    defense = {
        "ofz_fixed": round(defense_share * ofz_w, 3),
        "gold": round(defense_share * gold_w, 3),
        "floater": round(defense_share * fl_w, 3),
    }
    core = min(attack_share, CORE_TARGET)
    reserve = round(max(0.0, attack_share - core), 3)
    attack = {"core_proven": round(core, 3), "shock_reserve": reserve}

    notes = []
    if regime == "SHOCK":
        notes.append("ШОК: рукав атаки расширен — жадно добираем подешевевшее качество.")
    elif regime == "RISK":
        notes.append("RISK: перевес в защиту; ядро доказанного качества держим, добор отложен.")
    else:
        notes.append("NORMAL: базовый поток в атаку, резерв на шоковый добор перспективного.")
    if deval_pressure != "low":
        notes.append("Девал-тилт: защита смещена из ОФЗ-фикс в золото+флоатеры; "
                     "в атаке перевес экспортёров (выручка в валюте).")
    if defense.get("gold"):
        notes.append(f"Золото ≈ {defense['gold']*100:.0f}% портфеля (физический металл, хвостовая защита).")
    return RegimeAllocation(
        regime=regime, defense_total=round(defense_share, 3),
        attack_total=round(attack_share, 3), defense=defense, attack=attack, notes=notes,
    )


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
