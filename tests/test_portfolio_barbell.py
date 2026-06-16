"""Согласованность барбелла, портфельного риска и backtest с Excel."""
import math

from app.core.barbell import barbell
from app.core.portfolio import (
    factor_decomposition, sector_concentration, stress_test,
)
from app.core.backtest import run_backtest


def approx(a, b, tol=0.005):
    return math.isclose(a, b, abs_tol=tol)


# ── Барбелл (лист «Барбелл-калькулятор») ─────────────────────────────────────
def test_barbell_default():
    b = barbell(attack_share=0.5, base=0.05, defense_return=0.0,
                shock_share=0.4, shock_return=0.18, target=0.05)
    assert approx(b.avg_attack, 0.102)        # 0.6×0.05 + 0.4×0.18
    assert approx(b.portfolio, 0.051)         # 0.5×0.102
    assert b.meets_target is True
    assert approx(b.scenarios["только спокойное (0%)"], 0.025)
    assert approx(b.scenarios["20% атаки в шоки"], 0.038)
    assert approx(b.scenarios["40% атаки в шоки"], 0.051)


# ── Портфельный риск (лист «Портфельный риск (Aladdin)») ─────────────────────
PORTFOLIO_LOADINGS = {
    "Сбербанк":      {"РФ-бета": 1.0, "Ставка ЦБ": 0.8, "Потребитель": 0.3, "Рента/гос": 0.2, "Growth-стиль": 0.2},
    "Т-Технологии":  {"РФ-бета": 0.9, "Ставка ЦБ": 0.4, "Потребитель": 0.4, "Рента/гос": 0.0, "Growth-стиль": 0.8},
    "Совкомбанк":    {"РФ-бета": 1.0, "Ставка ЦБ": 0.9, "Потребитель": 0.2, "Рента/гос": 0.0, "Growth-стиль": 0.4},
    "БСПБ":          {"РФ-бета": 0.9, "Ставка ЦБ": 0.8, "Потребитель": 0.1, "Рента/гос": 0.0, "Growth-стиль": 0.2},
    "X5":            {"РФ-бета": 0.7, "Ставка ЦБ": 0.2, "Потребитель": 1.0, "Рента/гос": 0.0, "Growth-стиль": 0.4},
    "Мать и Дитя":   {"РФ-бета": 0.6, "Ставка ЦБ": 0.2, "Потребитель": 0.6, "Рента/гос": 0.0, "Growth-стиль": 0.6},
    "Транснефть пр": {"РФ-бета": 0.7, "Ставка ЦБ": 0.3, "Потребитель": 0.0, "Рента/гос": 1.0, "Growth-стиль": 0.0},
}


def test_factor_concentration():
    d = factor_decomposition(PORTFOLIO_LOADINGS)
    assert approx(d.concentration["РФ-бета"], 0.8286)
    assert approx(d.concentration["Ставка ЦБ"], 0.5143)
    assert d.dominant_factor == "РФ-бета"
    assert len(d.flags) >= 1   # доминирующий фактор → флаг


def test_sector_concentration_banks():
    sectors = {
        "Сбербанк": "Банк", "Т-Технологии": "Банк", "Совкомбанк": "Банк",
        "БСПБ": "Банк", "X5": "Ритейл", "Мать и Дитя": "Медицина",
        "Транснефть пр": "Инфраструктура",
    }
    flags = sector_concentration(sectors, limit=0.30)
    assert any("Банк" in f for f in flags)   # 4 банка из 7 = 57% > 30%


def test_stress_market_shock():
    d = factor_decomposition(PORTFOLIO_LOADINGS)
    st = stress_test(d)
    market = next(s for s in st if s.scenario.startswith("Шок"))
    assert approx(market.quant_reaction, -0.414, tol=0.01)  # −0.5 × 0.8286


# ── Backtest (лист «Backtest») ───────────────────────────────────────────────
def test_backtest_few_cases_not_proven():
    s = run_backtest([("Сбер 06.2024", 0.22, 0.0)])
    assert s.cases[0].hit is False           # ошибка 22 п.п. > 5
    assert approx(s.cases[0].error_pp, 22.0, tol=0.1)
    assert "не доказана" in s.verdict.lower()
