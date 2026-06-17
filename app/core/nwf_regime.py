"""Режим рынка по состоянию ФНБ + бюджетного правила (чистая функция).

Логика: тающий ликвидный ФНБ + дефицитный бюджет (Urals ниже цены отсечения) =
структурный риск → больше защиты. Глубокая просадка рынка = ШОК-override →
жадный добор качества (это важнее текущего фундамента ФНБ).

alloc = (доля защиты, доля атаки) в портфеле.
"""
from __future__ import annotations

from dataclasses import dataclass

SHOCK_DRAWDOWN = 0.27   # просадка рынка от максимума, при которой включается ШОК
NWF_RISK_PCT = 2.0      # ликвидный ФНБ < 2% ВВП — тревожно
NWF_RISK_MONTHS = 18    # < 18 мес до исчерпания при текущем дефиците — тревожно


@dataclass
class NwfRegime:
    regime: str            # NORMAL | RISK | SHOCK
    defense: float         # доля защиты
    attack: float          # доля атаки
    budget_sign: float     # Urals − cutoff: <0 → бюджет дефицитный, буфер тает
    note: str


def nwf_regime(*, liquid_nwf_pct: float, months_to_zero: float,
               urals: float, cutoff: float, market_drawdown: float) -> NwfRegime:
    budget_sign = urals - cutoff
    base_risk = (liquid_nwf_pct < NWF_RISK_PCT and months_to_zero < NWF_RISK_MONTHS)

    if market_drawdown > SHOCK_DRAWDOWN:
        return NwfRegime(
            regime="SHOCK", defense=0.20, attack=0.80, budget_sign=budget_sign,
            note=f"Просадка рынка {market_drawdown*100:.0f}% > {SHOCK_DRAWDOWN*100:.0f}% — "
                 f"жадный добор качества (ШОК важнее фундамента ФНБ).")

    if base_risk:
        return NwfRegime(
            regime="RISK", defense=0.70, attack=0.30, budget_sign=budget_sign,
            note=f"ФНБ {liquid_nwf_pct:.1f}% ВВП и {months_to_zero:.0f} мес до нуля — "
                 f"структурный риск, перевес в защиту."
                 + ("" if budget_sign >= 0 else " Бюджет дефицитный (Urals<отсечки)."))

    return NwfRegime(
        regime="NORMAL", defense=0.30, attack=0.70, budget_sign=budget_sign,
        note="ФНБ устойчив — нормальный режим, базовый поток в атаку."
             + ("" if budget_sign >= 0 else " Но бюджет дефицитный — следить."))
