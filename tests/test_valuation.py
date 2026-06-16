"""Согласованность количественного ядра с числами Excel-модели.

Якоря взяты прямо из листов: «Примеры (валидация)», «ТОП-25 (2 слоя)»,
«СИГНАЛ (боевой)», «Под инвестора». Совпадение доказывает, что ядро
повторяет модель (это согласованность, НЕ предсказательность — см. Backtest).
"""
import math

from app.core.valuation import (
    justified_pb, justified_pe, sustainable_g, real_return, fisher_nominal,
    confidence_zone, ternary_signal, effective_hurdle, full_return,
    mature_valuation,
)
from app.core.classify import classify, phase_years, calibrated_terminal_r
from app.core.rate import weighted_riskfree, default_r

DEFLATOR = 0.1413  # личная инфляция из листа «Личная инфляция» (SUMPRODUCT)


def approx(a, b, tol=0.005):
    return math.isclose(a, b, abs_tol=tol)


# ── Лист «Примеры (валидация)» ────────────────────────────────────────────────
def test_justified_pb_sber():
    # Сбер: ROE 0.23, g 0.11, r 0.25 → P/B ≈ 0.857 (факт 0.82)
    assert approx(justified_pb(0.23, 0.11, 0.25), 0.857)


def test_justified_pb_x5():
    # X5: ROE 0.42, g 0.15, r 0.25 → P/B = 2.7 (факт 2.8)
    assert approx(justified_pb(0.42, 0.15, 0.25), 2.7)


# ── Лист «ТОП-25 (2 слоя)» ────────────────────────────────────────────────────
def test_full_return_sber_granica():
    # Сбер: дивдох 0.11, g 0.09, сжатие 1, структ.множ 1
    r = full_return(div_yield=0.11, g_base=0.09, compression=1.0,
                    structural_mult=1.0, deflator=DEFLATOR,
                    hurdle=0.05, buffer=0.02)
    assert approx(r.full_nominal, 0.20)
    assert approx(r.real, 0.0514)
    assert r.signal == "ГРАНИЦА"


def test_full_return_yandex_vozderzhis():
    # Яндекс: дивдох 0, g 0.2, сжатие 0.91, структ.множ 1.1 → реал ≈ −0.027
    r = full_return(div_yield=0.0, g_base=0.2, compression=0.91,
                    structural_mult=1.1, deflator=DEFLATOR,
                    hurdle=0.05, buffer=0.02)
    assert approx(r.real, -0.027)
    assert r.signal == "ВОЗДЕРЖИСЬ"


def test_full_return_gazprom_degenerate():
    # Газпром: структурный множитель 0 → g обнулён
    r = full_return(div_yield=0.04, g_base=0.0, compression=1.0,
                    structural_mult=0.0, deflator=DEFLATOR,
                    hurdle=0.05, buffer=0.02)
    assert r.g_final == 0.0
    assert r.signal == "ВОЗДЕРЖИСЬ"


# ── Лист «Под инвестора» (обратный режим) ─────────────────────────────────────
def test_implied_real_sber():
    # Сбер: B 7500, ROE 0.227, g 0.08, капа 7200, инфл 0.145 → implied real ≈ 0.077
    v = mature_valuation(roe=0.227, g=0.08, r=0.21, payout=0.5,
                         equity=7500, current_cap=7200, deflator=0.145)
    assert approx(v.implied_nominal, 0.2331)
    assert approx(v.implied_real, 0.077)


def test_max_price_under_hurdle():
    # hurdle +7%: Сбер (implied 7.7%) проходит → есть запас, просадка не нужна
    v7 = mature_valuation(roe=0.227, g=0.08, r=0.21, payout=0.5,
                          equity=7500, current_cap=7200,
                          deflator=0.145, hurdle_real=0.07)
    assert v7.max_price_cap > v7.current_cap
    assert v7.needed_drawdown > 0
    # hurdle +10% (атака, лист «Под инвестора»): цена дороговата → нужна просадка
    v10 = mature_valuation(roe=0.227, g=0.08, r=0.21, payout=0.5,
                           equity=7500, current_cap=7200,
                           deflator=0.145, hurdle_real=0.10)
    assert v10.needed_drawdown < 0


# ── Определения и связи ───────────────────────────────────────────────────────
def test_sustainable_g():
    assert approx(sustainable_g(0.227, 0.5), 0.1135)


def test_fisher_roundtrip():
    nom = fisher_nominal(0.145, 0.10)
    assert approx(real_return(nom, 0.145), 0.10)


def test_confidence_zone():
    assert confidence_zone(0.21, 0.08) == "применимо"   # спред 0.13
    assert confidence_zone(0.20, 0.165) == "хрупко"      # спред 0.035
    assert confidence_zone(0.20, 0.19) == "вне зоны"     # спред 0.01


def test_ternary_and_regime():
    assert ternary_signal(0.10, 0.05, 0.02) == "ПОКУПАЙ"
    assert ternary_signal(0.02, 0.05, 0.02) == "ВОЗДЕРЖИСЬ"
    assert ternary_signal(0.05, 0.05, 0.02) == "ГРАНИЦА"
    assert effective_hurdle(0.05, "ШОК") == 0.0
    assert effective_hurdle(0.05, "спокойное") == 0.05


# ── Классификация ─────────────────────────────────────────────────────────────
def test_classify_yandex_growth():
    c = classify(body_trend=1, revenue_growth=0.32, roic=0.40, wacc=0.20,
                 payout=0.10)
    assert c.detailed == "РАСТУЩИЙ КАЧЕСТВ."
    assert c.phase_n == 7           # ROIC−WACC = 0.20 > 0.15
    assert approx(c.terminal_r, 0.18)


def test_classify_lukoil_liquidation():
    c = classify(body_trend=-1, revenue_growth=0.03, roic=0.15, wacc=0.18,
                 payout=0.90)
    assert c.detailed == "ЛИКВИДАЦИОННЫЙ"


def test_classify_sber_mature():
    c = classify(body_trend=0, revenue_growth=0.10, roic=0.227, wacc=0.20,
                 payout=0.50)
    assert c.detailed == "ЗРЕЛЫЙ КАЧЕСТВ."


# ── Ставка r ──────────────────────────────────────────────────────────────────
def test_weighted_riskfree():
    # лист «Ставка r»: 0.09×0.35 + 0.11×0.45 + 0.14×0.20 = 0.109
    assert approx(weighted_riskfree([(0.09, 0.35), (0.11, 0.45), (0.14, 0.20)]),
                  0.109)


def test_default_r_market_premium():
    rb = default_r(risk_premium=0.10, asset_premium=0.0)
    assert approx(rb.r, 0.209)  # 0.109 + 0.10
