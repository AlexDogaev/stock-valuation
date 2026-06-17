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
    assert qm(structural_score=2) == "ordinary"


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


def test_low_payout_not_proven():
    assert qm(payout=0.10) == "PROSPECTIVE_NO_QUALITY"
