"""Леверидж: качество (ROIC) и обслуживаемость/выживание (лист «Леверидж и ROIC»).

НЕ уровень долга (он уже в r и ROE), а: создаёт ли долг стоимость
(ROIC−WACC) + риск дефолта (покрытие процентов → PD → выживание за N лет).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LeverageResult:
    roic: float
    spread_wacc: float       # ROIC − WACC: >0 создаёт стоимость
    spread_debt: float       # ROIC − стоимость долга
    quality_verdict: str
    interest_coverage: float
    net_debt_ebitda: float
    annual_pd: float
    survival_prob: float     # P(дожить за N лет)
    serviceability_flag: str
    going_concern_cap: float | None = None
    survival_adjusted_cap: float | None = None
    default_discount: float | None = None


def leverage_quality(
    *,
    ebit: float,
    tax_rate: float,
    invested_capital: float,
    interest_expense: float,
    net_debt: float,
    ebitda: float,
    cost_of_debt: float,
    wacc: float,
    horizon_years: int = 10,
    going_concern_cap: float | None = None,
) -> LeverageResult:
    roic = ebit * (1.0 - tax_rate) / invested_capital
    spread_wacc = roic - wacc
    spread_debt = roic - cost_of_debt

    if roic < wacc:
        quality = "РАЗРУШАЕТ стоимость (ROIC<WACC)"
    elif roic < cost_of_debt:
        quality = "Долг дороже отдачи"
    else:
        quality = "Леверидж здоровый"

    coverage = ebit / interest_expense if interest_expense else float("inf")
    nd_ebitda = net_debt / ebitda if ebitda else float("inf")
    # грубая годовая PD ~ 4%/покрытие, капается 20%
    annual_pd = min(0.20, 0.04 / coverage) if coverage else 0.20
    survival = (1.0 - annual_pd) ** horizon_years

    if coverage < 1.5:
        flag = "ОПАСНО"
    elif coverage < 3:
        flag = "Напряжённо"
    elif nd_ebitda > 3.5:
        flag = "Долг великоват"
    else:
        flag = "Обслуживает легко"

    res = LeverageResult(
        roic=roic, spread_wacc=spread_wacc, spread_debt=spread_debt,
        quality_verdict=quality, interest_coverage=coverage,
        net_debt_ebitda=nd_ebitda, annual_pd=annual_pd, survival_prob=survival,
        serviceability_flag=flag,
    )
    if going_concern_cap is not None:
        res.going_concern_cap = going_concern_cap
        res.survival_adjusted_cap = going_concern_cap * survival
        res.default_discount = survival - 1.0
    return res
