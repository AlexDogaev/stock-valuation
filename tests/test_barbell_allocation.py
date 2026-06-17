"""Режимная аллокация рукавов (защита 60/28/12, атака ядро+резерв)."""
import math
from app.core.barbell import regime_allocation


def approx(a, b, tol=0.005):
    return math.isclose(a, b, abs_tol=tol)


def test_normal_allocation():
    a = regime_allocation(regime="NORMAL", defense_share=0.30, attack_share=0.70)
    # защита 30% → ОФЗ 18% / золото 8.4% / флоатер 3.6%
    assert approx(a.defense["ofz_fixed"], 0.18)
    assert approx(a.defense["gold"], 0.084)
    assert approx(a.defense["floater"], 0.036)
    # атака 70% → ядро 30% + резерв 40%
    assert approx(a.attack["core_proven"], 0.30)
    assert approx(a.attack["shock_reserve"], 0.40)


def test_risk_allocation():
    a = regime_allocation(regime="RISK", defense_share=0.70, attack_share=0.30)
    assert approx(a.defense["ofz_fixed"], 0.42)
    assert approx(a.attack["core_proven"], 0.30)   # всё ядро
    assert approx(a.attack["shock_reserve"], 0.0)  # резерва нет


def test_shock_allocation():
    a = regime_allocation(regime="SHOCK", defense_share=0.20, attack_share=0.80)
    assert approx(a.attack["core_proven"], 0.30)
    assert approx(a.attack["shock_reserve"], 0.50)  # большой добор в шок
    assert any("ШОК" in n for n in a.notes)


def test_shares_sum_to_one():
    a = regime_allocation(regime="NORMAL", defense_share=0.30, attack_share=0.70)
    total = sum(a.defense.values()) + sum(a.attack.values())
    assert approx(total, 1.0)


def test_deval_tilt_high():
    # high: защита 70% → ОФЗ 25 / золото 50 / флоат 25 %
    a = regime_allocation(regime="RISK", defense_share=0.70, attack_share=0.30,
                          deval_pressure="high")
    assert approx(a.defense["ofz_fixed"], 0.175)
    assert approx(a.defense["gold"], 0.35)
    assert a.defense["gold"] > a.defense["ofz_fixed"]      # золото перевешивает рублёвые ОФЗ
    assert any("Девал-тилт" in n for n in a.notes)
    # сумма долей сохраняется
    assert approx(sum(a.defense.values()) + sum(a.attack.values()), 1.0)


def test_no_tilt_default():
    a = regime_allocation(regime="RISK", defense_share=0.70, attack_share=0.30)
    assert approx(a.defense["ofz_fixed"], 0.42)            # базовый сплит без тилта
