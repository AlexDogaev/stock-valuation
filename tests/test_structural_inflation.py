"""Согласованность структурного слоя и личной инфляции с Excel."""
import math

from app.core.structural import (
    structural_score, score_zone, score_multiplier, evaluate_structural,
)
from app.core.inflation import (
    weighted_inflation, compute_deflator, active_deflator, DEFAULT_BASKET,
)


def approx(a, b, tol=0.005):
    return math.isclose(a, b, abs_tol=tol)


# ── Структурный слой (лист «Структурный слой») ───────────────────────────────
def test_headhunter_threat():
    # Ров −1, дизрупция −2, TAM −1, регуляторика 0, демо 0 → балл −4 → УГРОЗА
    s = structural_score(moat=-1, disruption=-2, tam=-1, regulation=0, demo=0)
    assert s == -4
    assert score_zone(s) == "УГРОЗА"
    assert score_multiplier(s) == 0.0


def test_yandex_strong():
    # 2+1+1+0+0 = 4 → крепкий → 1.1
    s = structural_score(moat=2, disruption=1, tam=1, regulation=0, demo=0)
    assert s == 4
    assert score_multiplier(s) == 1.1


def test_demo_excluded_from_score_topdown():
    # §2 рефактор: демография TOP-DOWN (тектоника), в балл эмитента НЕ входит.
    # 1+0+2+0 = 3 (demo=2 игнорируется — иначе двойной счёт с тектоническим множителем).
    s = structural_score(moat=1, disruption=0, tam=2, regulation=0, demo=2)
    assert s == 3
    assert structural_score(moat=1, disruption=0, tam=2, regulation=0, demo=0) == s  # demo не влияет


def test_gosnaves_excluded_from_score():
    # госнавес −2 НЕ входит в балл (правило «один раз»)
    r = evaluate_structural(moat=1, disruption=-1, tam=-1, regulation=-2,
                            demo=0, gosnaves=-2, is_rentier=True, g_base=0.01)
    assert r.score == -3          # 1−1−1−2+0, без госнавеса
    assert r.multiplier == 0.5
    # валидатор предупреждает о двойном счёте
    assert any("двойн" in w.lower() for w in r.warnings)


def test_multiplier_norma():
    assert score_multiplier(0) == 1.0
    assert score_multiplier(3) == 1.0
    assert score_multiplier(-1) == 0.5


# ── Личная инфляция (лист «Личная инфляция») ─────────────────────────────────
def test_personal_inflation_anchor():
    # SUMPRODUCT дефолтной корзины = 0.1413
    assert approx(weighted_inflation(DEFAULT_BASKET), 0.1413)


def test_deflator_premium_and_presets():
    d = compute_deflator(rosstat_current=0.118, rosstat_smoothed=0.07)
    assert approx(d.personal, 0.1413)
    assert approx(d.basket_premium, 0.0233)
    assert approx(d.tactical, 0.1413)      # = личная
    assert approx(d.strategic, 0.0933)     # 0.07 + 0.0233


def test_active_deflator_preset():
    d = compute_deflator()
    assert approx(active_deflator(d, "тактический"), d.tactical)
    assert approx(active_deflator(d, "стратегический"), d.strategic)


def test_weights_sum_to_one():
    assert approx(sum(c.weight for c in DEFAULT_BASKET), 1.0)
