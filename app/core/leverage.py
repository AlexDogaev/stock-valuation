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


# ─────────────────────────────────────────────────────────────────────────────
# Дифференциал рычага и качество прибыли (INSTRUCTIONS §6, NOTES §5)
# ─────────────────────────────────────────────────────────────────────────────

# ложное качество: высокий ROE, тонкий дифференциал, большое плечо
FALSE_QUALITY_ROE = 0.20       # ROE выше — «высокий»
FALSE_QUALITY_DIFF = 0.03      # дифференциал ROIC−Kd ниже — «тонкий»
FALSE_QUALITY_DE = 1.0         # D/E выше — «большое плечо»


@dataclass
class LeverageDiff:
    roe: float
    roic: float
    kd_after_tax: float
    differential: float        # ROIC − Kd: знак вклада долга (>0 работает, <0 разрушает)
    spread_roe_roic: float     # ROE − ROIC: прямое проявление рычага в отчётности
    de_ratio: float
    false_quality: bool        # высокий ROE на тонком дифференциале + большом плече
    verdict: str
    note: str = ""


def leverage_differential(
    *,
    roe: float,
    roic: float,
    cost_of_debt_after_tax: float,
    de_ratio: float,
    is_bank: bool = False,
) -> LeverageDiff:
    """Создаёт ли долг ценность (§6). Для НЕфинансовых компаний.

    ROE = ROIC + (ROIC − Kd)·D/E: дифференциал = знак, плечо = масштаб.
    Высокий ROE на тонком дифференциале и большом D/E — замаскированная хрупкость
    (ложное качество). Банки — отдельная ветка (плечо = бизнес-модель).
    """
    diff = roic - cost_of_debt_after_tax
    spread = roe - roic

    if is_bank:
        return LeverageDiff(
            roe=roe, roic=roic, kd_after_tax=cost_of_debt_after_tax,
            differential=diff, spread_roe_roic=spread, de_ratio=de_ratio,
            false_quality=False, verdict="банк — дифференциал рычага неприменим",
            note="Плечо = бизнес-модель банка. Смотреть ROE vs стоимость капитала, "
                 "ROA, норматив достаточности Н1.0 (см. bank_quality).")

    false_q = (roe >= FALSE_QUALITY_ROE and diff < FALSE_QUALITY_DIFF
               and de_ratio >= FALSE_QUALITY_DE)
    if false_q:
        verdict = "ЛОЖНОЕ качество: высокий ROE опёрт на плечо при тонком дифференциале (хрупкость)"
    elif diff < 0:
        verdict = "долг РАЗРУШАЕТ стоимость (ROIC < Kd → ROE < ROIC)"
    elif diff > 0:
        verdict = "долг работает (ROIC > Kd → ROE > ROIC)"
    else:
        verdict = "долг нейтрален"
    return LeverageDiff(
        roe=roe, roic=roic, kd_after_tax=cost_of_debt_after_tax,
        differential=diff, spread_roe_roic=spread, de_ratio=de_ratio,
        false_quality=false_q, verdict=verdict)


@dataclass
class BankQuality:
    roe: float
    cost_of_equity: float
    spread_coe: float          # ROE − CoE: создание стоимости для банка
    roa: float | None
    car_n1: float | None       # норматив достаточности Н1.0
    verdict: str
    warnings: list[str]


def bank_quality(
    *,
    roe: float,
    cost_of_equity: float,
    roa: float | None = None,
    car_n1: float | None = None,
    n1_min: float = 0.08,
) -> BankQuality:
    """Качество банка (§6, NOTES §5): ROE vs стоимость капитала, ROA, Н1.0.

    Дифференциал ROIC−WACC к банку неприменим (долг = сырьё). Пороги тоньше:
    положительный спред ROE−CoE уже = создание стоимости.
    """
    spread = roe - cost_of_equity
    warnings: list[str] = []
    if spread > 0:
        verdict = "создаёт стоимость (ROE > стоимости капитала)"
    elif spread > -0.02:
        verdict = "около стоимости капитала (пограничный)"
    else:
        verdict = "разрушает стоимость (ROE < стоимости капитала)"
    if car_n1 is not None and car_n1 < n1_min:
        warnings.append(f"Н1.0 {car_n1*100:.1f}% ниже минимума {n1_min*100:.0f}% — "
                        f"дефицит капитала, рост/дивиденды под угрозой.")
    return BankQuality(roe=roe, cost_of_equity=cost_of_equity, spread_coe=spread,
                       roa=roa, car_n1=car_n1, verdict=verdict, warnings=warnings)
