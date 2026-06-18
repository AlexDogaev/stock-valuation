"""Посленалоговый слой (§5): асимметрия дивы/купоны vs курсовой рост, ЛДВ, ИИС-3."""
from app.core.tax import after_tax


def test_dividends_taxed_growth_exempt_at_long_horizon():
    # горизонт 3г: ЛДВ освобождает рост; дивы −13%
    r = after_tax(div_yield=0.05, price_component=0.10, years=3, tax_rate=0.13)
    assert r.growth_exempt is True
    assert abs(r.div_tax - 0.05 * 0.13) < 1e-9
    assert r.gains_tax == 0.0
    assert abs(r.after_tax_nominal - (0.05 * 0.87 + 0.10)) < 1e-9


def test_short_horizon_taxes_both():
    # горизонт 1г: ЛДВ не действует — облагается и рост, и дивы
    r = after_tax(div_yield=0.05, price_component=0.10, years=1, tax_rate=0.13)
    assert r.growth_exempt is False
    assert r.gains_tax > 0
    assert abs(r.after_tax_nominal - (0.15 * 0.87)) < 1e-9


def test_iis3_exempts_growth_but_not_dividends():
    # ИИС-3 на коротком горизонте: рост освобождён, дивы всё равно облагаются
    r = after_tax(div_yield=0.05, price_component=0.10, years=1, tax_rate=0.13, iis3=True)
    assert r.growth_exempt is True
    assert r.div_tax > 0
    assert r.gains_tax == 0.0


def test_dividend_name_loses_more_than_growth_name():
    # тот же валовой 15%: дивидендное имя теряет больше ростового под ЛДВ (перекос барбелла)
    div_heavy = after_tax(div_yield=0.15, price_component=0.0, years=3, tax_rate=0.13)
    growth = after_tax(div_yield=0.0, price_component=0.15, years=3, tax_rate=0.13)
    assert div_heavy.gross_nominal == growth.gross_nominal == 0.15
    assert growth.after_tax_nominal > div_heavy.after_tax_nominal  # рост налогово-эффективнее


def test_rate_15_percent():
    r = after_tax(div_yield=0.10, price_component=0.0, years=1, tax_rate=0.15)
    assert abs(r.after_tax_nominal - 0.10 * 0.85) < 1e-9
