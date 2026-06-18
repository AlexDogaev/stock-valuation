"""Платформенный слой (§3), разложение апсайда (§4), флоут (§5), дифференциал рычага (§6).

Кейс ОЗОН как эталон: монетизация доказана, но все источники упёрты → кратного
апсайда нет; флоут конечен; лимит максимума отсрочки бьёт по средней сильнее.
"""
from app.core import platform_check, upside, float_analysis, leverage
from app.core.quality_markers import quality_marker


# ── §3 платформенный критерий качества ────────────────────────────────────────
def test_platform_needs_proven_monetization():
    # большая платформа без доказанной монетизации — НЕ качество (категориальная ловушка)
    assert quality_marker(structural_score=4, roic_years=2, payout=0.0,
                          revenue_growth=0.25, compression=1.0,
                          monetization_proven=0, is_platform=1) == "PROSPECTIVE_NO_QUALITY"


def test_platform_with_proven_monetization_is_prospective_quality():
    assert quality_marker(structural_score=4, roic_years=2, payout=0.0,
                          revenue_growth=0.25, compression=1.0,
                          monetization_proven=1, is_platform=1) == "PROSPECTIVE_QUALITY"


def test_platform_monetization_criterion():
    assert platform_check.platform_monetization_ok(mechanism_clear=True, started_proving=True)
    assert not platform_check.platform_monetization_ok(mechanism_clear=True, started_proving=False)


# ── §3 насыщение слоя ─────────────────────────────────────────────────────────
def test_saturation_ozon_advertising():
    # реклама ОЗОН: takerate выше Amazon, инвентарь занят, CPM упёрся → слой насыщен
    res = platform_check.assess_saturation(
        takerate=0.07, benchmark_takerate=0.055,
        inventory_occupancy=0.90, cpm_headroom=0.0)
    assert res.layer_saturated is True


def test_saturation_unknown_inputs_flagged():
    res = platform_check.assess_saturation()
    assert res.layer_saturated is False
    assert res.warnings  # помечено, что нужен класс B


# ── §4 разложение апсайда ─────────────────────────────────────────────────────
def test_upside_all_capped_no_multiple():
    sources = [
        upside.UpsideSource("торговля", capped=True, headroom=2.0, note="проникновение ~×2 упёрто"),
        upside.UpsideSource("юзеры", capped=True, note="насыщены"),
        upside.UpsideSource("реклама", capped=True, note="near-saturation"),
        upside.UpsideSource("флоут", capped=True, note="конечен на ×2 GMV"),
    ]
    res = upside.decompose_upside(sources)
    assert res.has_uncapped is False
    assert res.multiple_warranted is False
    assert res.warnings


def test_upside_one_uncapped_warrants_multiple():
    sources = [
        upside.UpsideSource("реклама", capped=True),
        upside.UpsideSource("новый рынок", capped=False, headroom=1.6),
    ]
    res = upside.decompose_upside(sources)
    assert res.multiple_warranted is True
    assert res.combined_headroom == 1.6


# ── §5 флоут ──────────────────────────────────────────────────────────────────
def test_avg_delay_from_max_cap_drops_more_than_to_cap():
    # лимит максимума 14 дн → средняя 10.5 (не 14), почти вдвое от 20.5
    assert float_analysis.avg_delay_from_max_cap(14.0) == 10.5
    assert float_analysis.avg_delay_from_max_cap(24.0) == 20.5


def test_float_scales_with_delay_and_balance_check():
    base = float_analysis.platform_float(
        gmv_bln=4110.0, share_3p=0.95, seller_payout_share=0.75, avg_delay_days=20.5,
        paid_deposits_bln=438.0, capital_bln=70.0, interest_assets_bln=677.0)
    assert 150 < base.float_bln < 180     # ≈164 млрд (NOTES §4: база 0.71×GMV)
    assert base.balance_ok is True
    stress = float_analysis.float_stress(base_result=base, new_avg_delay_days=10.5,
                                         fintech_profit_bln=62.0)
    assert stress["delta_float_bln"] < 0   # отсрочка режется → флоут сжимается
    assert stress["lost_income_bln_per_year"] > 0


# ── §6 дифференциал рычага ────────────────────────────────────────────────────
def test_false_quality_high_roe_thin_differential():
    res = leverage.leverage_differential(roe=0.30, roic=0.11, cost_of_debt_after_tax=0.10,
                                         de_ratio=2.0)
    assert res.false_quality is True
    assert res.spread_roe_roic > 0


def test_healthy_leverage_not_false_quality():
    res = leverage.leverage_differential(roe=0.25, roic=0.22, cost_of_debt_after_tax=0.10,
                                         de_ratio=0.5)
    assert res.false_quality is False
    assert res.differential > 0


def test_bank_branch_uses_coe_not_differential():
    diff = leverage.leverage_differential(roe=0.25, roic=0.0, cost_of_debt_after_tax=0.0,
                                          de_ratio=8.0, is_bank=True)
    assert "банк" in diff.verdict
    bq = leverage.bank_quality(roe=0.25, cost_of_equity=0.20, roa=0.03, car_n1=0.07)
    assert bq.spread_coe > 0
    assert bq.warnings  # Н1.0 ниже минимума → флаг
