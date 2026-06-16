"""Согласованность growth-DCF, SOTP, леверидж, тренд тела с Excel."""
import math

from app.core.growth import growth_calibrated, growth_projection
from app.core.sotp import ozon_sotp
from app.core.leverage import leverage_quality
from app.core.body_trend import body_trend


def approx(a, b, tol=0.01):
    return math.isclose(a, b, abs_tol=tol)


# ── Growth калиброванный (Яндекс, лист «Growth калиброванный») ────────────────
def test_growth_calibrated_yandex():
    g = growth_calibrated(
        earnings=141, growth_phase=0.20, roic=0.40, wacc=0.20,
        terminal_g=0.09, payout=0.60, current_cap=1590,
        sbc_dilution=0.08, deflator=0.145,
    )
    assert g.phase_n == 7
    assert approx(g.terminal_r, 0.18)
    assert approx(g.terminal_pe, 7.267, tol=0.05)
    assert approx(g.irr, 0.1137, tol=0.005)
    assert approx(g.real, -0.027, tol=0.005)   # совпадает с листом «СИГНАЛ»
    assert g.verdict == "Дороговато"


# ── Growth режим / проекция (Ozon, лист «Growth режим») ──────────────────────
def test_growth_projection_ozon():
    scenarios = [
        {"label": "Медв.", "assets": 2000, "roa": 0.05, "roe": 0.22,
         "g": 0.06, "r_mature": 0.21, "r_path": 0.24, "n": 4},
        {"label": "База", "assets": 2000, "roa": 0.07, "roe": 0.27,
         "g": 0.08, "r_mature": 0.19, "r_path": 0.22, "n": 3},
        {"label": "Бычий", "assets": 2000, "roa": 0.09, "roe": 0.32,
         "g": 0.09, "r_mature": 0.18, "r_path": 0.20, "n": 3},
    ]
    p = growth_projection(scenarios=scenarios, current_cap=816)
    base = p.scenarios[1]
    assert approx(base.payout, 0.7037, tol=0.005)
    assert approx(base.fair_today, 532.7, tol=2.0)
    assert approx(p.fair_expected, 497.2, tol=3.0)
    assert p.verdict == "Дороговато (выше ожидаемой)"


# ── SOTP (Ozon, лист «Ozon SOTP») ────────────────────────────────────────────
def test_ozon_sotp():
    s = ozon_sotp(
        non_fintech_profit=80, non_fintech_pe=6,
        fintech_profit=49, fintech_capital=130,
        fintech_g=0.15, fintech_r=0.24,
        corporate_debt=120, conglomerate_discount=0.15, current_cap=816,
    )
    assert approx(s.non_fintech_ev, 480)
    assert approx(s.fintech_roe, 0.3769, tol=0.005)
    assert approx(s.net_fair, 584.6, tol=2.0)
    assert s.verdict == "Дороговато"


# ── Леверидж (X5, лист «Леверидж и ROIC») ────────────────────────────────────
def test_leverage_x5():
    lv = leverage_quality(
        ebit=230, tax_rate=0.25, invested_capital=600,
        interest_expense=15, net_debt=330, ebitda=280,
        cost_of_debt=0.18, wacc=0.20, horizon_years=10,
        going_concern_cap=832,
    )
    assert approx(lv.roic, 0.2875)
    assert lv.quality_verdict == "Леверидж здоровый"
    assert approx(lv.interest_coverage, 15.333, tol=0.1)
    assert approx(lv.survival_prob, 0.9742, tol=0.005)
    assert lv.serviceability_flag == "Обслуживает легко"
    assert approx(lv.survival_adjusted_cap, 810.5, tol=2.0)


# ── Тренд тела (лист «Тренд тела (авто)») ─────────────────────────────────────
def test_body_trend_lukoil_melting():
    b = body_trend(revenue_old=8000, revenue_last=8600, years=4,
                   capex=700, depreciation=650, roic_old=0.18, roic_last=0.15,
                   avg_inflation=0.09, is_resource=True)
    assert b.verdict == "ТАЕТ (−1)"
    assert b.body_trend_int == -1
    assert "РЕСУРСНЫЙ" in b.confidence_flag


def test_body_trend_yandex_growing():
    b = body_trend(revenue_old=520, revenue_last=1441, years=4,
                   capex=180, depreciation=90, roic_old=0.20, roic_last=0.40,
                   avg_inflation=0.09, is_resource=False)
    assert b.verdict == "РАСТЁТ (+1)"
    assert b.body_trend_int == 1


def test_body_trend_x5_stable():
    b = body_trend(revenue_old=2600, revenue_last=4000, years=4,
                   capex=200, depreciation=180, roic_old=0.30, roic_last=0.42,
                   avg_inflation=0.09, is_resource=False)
    assert b.verdict == "СТАБИЛЬНО (0)"
    assert b.body_trend_int == 0
