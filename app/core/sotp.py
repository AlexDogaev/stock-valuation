"""Оценка по частям — Sum-of-the-Parts (лист «Ozon SOTP»).

Не-финтех (ROIC/прибыль × P/E) + Финтех (банк, P/B) − корп.долг
− конгломератный дисконт. Сумма частей склонна ЗАВЫШАТЬ → дисконт обязателен.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.valuation import justified_pb, confidence_zone


@dataclass
class SOTPResult:
    non_fintech_ev: float
    fintech_roe: float
    fintech_pb: float
    fintech_value: float
    gross: float
    conglomerate_discount: float
    net_fair: float
    current_cap: float
    verdict: str
    fintech_confidence: str
    notes: list[str]


def ozon_sotp(
    *,
    non_fintech_profit: float,
    non_fintech_pe: float,
    fintech_profit: float,
    fintech_capital: float,
    fintech_g: float,
    fintech_r: float,
    corporate_debt: float,
    conglomerate_discount: float,
    current_cap: float,
) -> SOTPResult:
    non_fintech_ev = non_fintech_profit * non_fintech_pe
    fintech_roe = fintech_profit / fintech_capital
    fintech_pb = justified_pb(fintech_roe, fintech_g, fintech_r)
    fintech_value = fintech_capital * fintech_pb
    gross = non_fintech_ev + fintech_value - corporate_debt
    net_fair = gross * (1.0 - conglomerate_discount)

    if current_cap < net_fair * 0.9:
        verdict = "Недооценён"
    elif current_cap > net_fair * 1.1:
        verdict = "Дороговато"
    else:
        verdict = "Справедливо"

    notes = [
        "Сумма частей склонна завышать: реклама не существует без маркетплейса; "
        "финтех живёт на клиентской базе. Нетто — верхняя граница, реальность ниже.",
        "Банковский P/B оптимистичен для субприм-портфеля (COR растёт) — в кризис просядет.",
    ]
    return SOTPResult(
        non_fintech_ev=non_fintech_ev, fintech_roe=fintech_roe,
        fintech_pb=fintech_pb, fintech_value=fintech_value, gross=gross,
        conglomerate_discount=conglomerate_discount, net_fair=net_fair,
        current_cap=current_cap, verdict=verdict,
        fintech_confidence=confidence_zone(fintech_r, fintech_g), notes=notes,
    )
