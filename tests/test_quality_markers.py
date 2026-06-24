"""Авто-маркеры качества."""
from app.core.quality_markers import quality_marker


def qm(**kw):
    base = dict(structural_score=3, roic_years=10, payout=0.5,
                revenue_growth=0.10, compression=1.0, monetization_proven=0)
    base.update(kw)
    return quality_marker(**base)


def test_proven_quality():
    assert qm() == "PROVEN_QUALITY"


def test_low_score_ordinary():
    # порог MIN_SCORE=2 (калибровка по X5): балл < 2 → ordinary
    assert qm(structural_score=1) == "ordinary"


def test_hyper_growth_not_proven():
    # гипер-рост (>30%) исключает доказанное даже при долгом ROIC
    assert qm(revenue_growth=0.40) == "PROSPECTIVE_NO_QUALITY"


def test_expensive_multiple_not_proven():
    # дорогой мультипликатор (сильное сжатие) — не доказанное
    assert qm(compression=0.89) == "PROSPECTIVE_NO_QUALITY"


def test_short_roic_not_proven():
    assert qm(roic_years=3) == "PROSPECTIVE_NO_QUALITY"


def test_prospective_quality_with_monetization():
    # короткий ROIC, но монетизация доказана → перспективное качество
    assert qm(roic_years=3, monetization_proven=1) == "PROSPECTIVE_QUALITY"


def test_low_payout_is_structural_quality():
    # доказанная структурная база (устойч.ROIC, не гипер, не дорогой), но payout мал → реинвестирует
    # → СТРУКТУРНОЕ качество, НЕ «спекулятивное» (кейс PLZL/GMKN: золото-капекс / уник.активы)
    assert qm(payout=0.10) == "STRUCTURAL_QUALITY"
    assert qm(payout=0.0) == "STRUCTURAL_QUALITY"


def test_structural_needs_proven_core():
    # без доказанной базы (короткий ROIC) низкий payout → именно спекулятивное, не структурное
    assert qm(roic_years=3, payout=0.10) == "PROSPECTIVE_NO_QUALITY"
    assert qm(revenue_growth=0.40, payout=0.10) == "PROSPECTIVE_NO_QUALITY"   # гипер-рост убивает core


def test_structural_quality_in_decision_matrix():
    # новый тир должен быть в матрице решений (иначе KeyError в matrix_action)
    from app.core.decision import MATRIX, ZONE_CHEAP, ZONE_EDGE, ZONE_EXPENSIVE
    for z in (ZONE_CHEAP, ZONE_EDGE, ZONE_EXPENSIVE):
        assert ("STRUCTURAL_QUALITY", z) in MATRIX
