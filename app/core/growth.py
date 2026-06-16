"""Growth-режимы оценки (листы «Growth калиброванный» и «Growth режим»).

Растущие компании: дорогой мультипликатор обязан нормализоваться вниз
(сжатие). Упрощённое «рост + дивы» завышает доходность в разы.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.classify import phase_years, calibrated_terminal_r
from app.core.valuation import real_return, confidence_zone


# ─────────────────────────────────────────────────────────────────────────────
# Growth v3 калиброванный (лист «Growth калиброванный»): выход — доходность
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class GrowthCalibrated:
    phase_n: int
    terminal_r: float
    terminal_g: float
    roic_minus_wacc: float
    terminal_pe: float
    earnings_end: float
    terminal_cap: float
    fair_today: float
    fair_after_sbc: float
    current_cap: float
    verdict: str
    irr: float                # ожидаемая годовая доходность от цены
    real: float
    confidence: str


def growth_calibrated(
    *,
    earnings: float,        # текущая скорр. прибыль
    growth_phase: float,    # темп роста в фазе
    roic: float,
    wacc: float,
    terminal_g: float,
    payout: float,
    current_cap: float,
    sbc_dilution: float = 0.0,   # разводнение SBC (минус к стоимости)
    deflator: float = 0.145,
) -> GrowthCalibrated:
    """Двухстадийный DCF: фаза N (калибр. по ROIC−WACC) → терминал → дисконт.

    Качество (ROIC>WACC) → длиннее фаза, ниже терминальная ставка.
    Выход: IRR от текущей цены (условная доходность при сбытии прогноза прибыли).
    """
    spread = roic - wacc
    n = phase_years(spread)
    r_term = calibrated_terminal_r(spread)
    terminal_pe = payout * (1.0 + terminal_g) / (r_term - terminal_g)
    earnings_end = earnings * (1.0 + growth_phase) ** n
    terminal_cap = earnings_end * terminal_pe
    fair_today = terminal_cap / (1.0 + r_term) ** n
    fair_after_sbc = fair_today * (1.0 - sbc_dilution)

    if current_cap < fair_after_sbc * 0.9:
        verdict = "Недооценён"
    elif current_cap > fair_after_sbc * 1.1:
        verdict = "Дороговато"
    else:
        verdict = "Справедливо"

    irr = (terminal_cap * (1.0 - sbc_dilution) / current_cap) ** (1.0 / n) - 1.0
    real = real_return(irr, deflator)

    return GrowthCalibrated(
        phase_n=n, terminal_r=r_term, terminal_g=terminal_g,
        roic_minus_wacc=spread, terminal_pe=terminal_pe,
        earnings_end=earnings_end, terminal_cap=terminal_cap,
        fair_today=fair_today, fair_after_sbc=fair_after_sbc,
        current_cap=current_cap, verdict=verdict, irr=irr, real=real,
        confidence=confidence_zone(r_term, terminal_g),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Growth-режим через проекцию зрелой прибыли (лист «Growth режим», Ozon)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class GrowthScenario:
    label: str
    mature_profit: float
    payout: float
    terminal_pe: float
    mature_cap: float
    fair_today: float


@dataclass
class GrowthProjection:
    scenarios: list[GrowthScenario]
    fair_min: float
    fair_max: float
    fair_expected: float
    current_cap: float
    verdict: str


def growth_projection(
    *,
    scenarios: list[dict],     # [{label, assets, roa, roe, g, r_mature, r_path, n}]
    current_cap: float,
    weights: tuple[float, float, float] = (0.35, 0.45, 0.20),
) -> GrowthProjection:
    """Проекция: зрелая прибыль = активы×ROA, payout=1−g/ROE,
    P/E_term = payout(1+g)/(r_зрел−g), дисконт по r_path за N лет.
    Ожидаемая = взвешенная по сценариям (медв/база/бычий).
    """
    out: list[GrowthScenario] = []
    for sc in scenarios:
        mature_profit = sc["assets"] * sc["roa"]
        payout = 1.0 - sc["g"] / sc["roe"]
        terminal_pe = payout * (1.0 + sc["g"]) / (sc["r_mature"] - sc["g"])
        mature_cap = mature_profit * terminal_pe
        fair_today = mature_cap / (1.0 + sc["r_path"]) ** sc["n"]
        out.append(GrowthScenario(
            label=sc["label"], mature_profit=mature_profit, payout=payout,
            terminal_pe=terminal_pe, mature_cap=mature_cap, fair_today=fair_today,
        ))
    fairs = [s.fair_today for s in out]
    expected = sum(f * w for f, w in zip(fairs, weights))
    if current_cap < min(fairs):
        verdict = "Недооценён"
    elif current_cap > max(fairs):
        verdict = "Переоценён"
    elif current_cap > expected:
        verdict = "Дороговато (выше ожидаемой)"
    else:
        verdict = "Справедливо"
    return GrowthProjection(
        scenarios=out, fair_min=min(fairs), fair_max=max(fairs),
        fair_expected=expected, current_cap=current_cap, verdict=verdict,
    )
