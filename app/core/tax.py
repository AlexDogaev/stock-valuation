"""Посленалоговый слой (INSTRUCTION §5, NOTES РМ).

Налоги бьют по компонентам доходности АСИММЕТРИЧНО:
- дивиденды/купоны — НДФЛ ежегодно при получении (ЛДВ НЕ освобождает; в ИИС-3 дивы тоже облагаются);
- курсовой рост — налог только при продаже, ЛДВ освобождает при владении ≥ 3 лет; ИИС-3 освобождает финрезультат.

Следствие: рост налогово-эффективнее купонов/дивов. Валовое сравнение ЗАВЫШАЕТ
купонно-дивидендные инструменты против ростовых (ОФЗ 15%→~13% после налога на купон;
ростовая 15% под ЛДВ→~15%, разрыв ~2пп из режима, не из бизнеса). Поэтому сравнивать
инструменты и с hurdle на ПОСЛЕналоговой основе. Для защитного рукава ОФЗ — роль защиты,
не доходности: поправка меняет ранжирование доходных альтернатив, не выкидывает из защиты.
"""
from __future__ import annotations

from dataclasses import dataclass

LDV_YEARS = 3          # льгота долгосрочного владения освобождает курсовой рост при горизонте ≥
DEFAULT_TAX_RATE = 0.13


@dataclass
class AfterTax:
    gross_nominal: float
    after_tax_nominal: float
    div_tax: float            # удержано с дивидендов/год (доля цены)
    gains_tax: float          # удержано с курсового роста/год (амортизировано)
    growth_exempt: bool       # освобождён ли рост (ЛДВ ≥3г или ИИС-3)
    note: str


def after_tax(
    *,
    div_yield: float,
    price_component: float,
    years: int | None,
    tax_rate: float = DEFAULT_TAX_RATE,
    iis3: bool = False,
    ldv_years: int = LDV_YEARS,
) -> AfterTax:
    """Годовая посленалоговая номинальная доходность по компонентам.

    div_yield        — дивидендная доходность (облагается ежегодно ВСЕГДА);
    price_component  — курсовая часть годовой доходности (рост котировки);
    years            — горизонт (для ЛДВ); iis3 — обёртка ИИС-3.
    """
    div_tax = max(0.0, div_yield) * tax_rate
    growth_exempt = (years is not None and years >= ldv_years) or iis3
    gains_tax = 0.0 if growth_exempt else max(0.0, price_component) * tax_rate

    gross = div_yield + price_component
    at = (div_yield - div_tax) + (price_component - gains_tax)

    if growth_exempt:
        why = f"ИИС-3" if iis3 and (years is None or years < ldv_years) else f"ЛДВ ≥{ldv_years}г"
        note = f"рост освобождён ({why}); дивы −{tax_rate*100:.0f}% ежегодно"
    else:
        note = f"рост и дивы −{tax_rate*100:.0f}% (горизонт < {ldv_years}г, ЛДВ не действует)"
    return AfterTax(gross_nominal=gross, after_tax_nominal=at, div_tax=div_tax,
                    gains_tax=gains_tax, growth_exempt=growth_exempt, note=note)
