"""Фискальное доминирование: индикатор `fiscal_drain` (спека §2).

Тезис: денег фиксированное количество, государству они сейчас нужнее → пул сбережений выгребается
в ОФЗ → акциям меньше бида → дисконт к их оценке. fiscal_drain = РЕЖИМНЫЙ МНОЖИТЕЛЬ-дисконт (в пп к
требуемой доходности при оценке P/E), НЕ добавка к hurdle/F (иначе двойной счёт с deval_score —
блокер §10: deval_score = ФНБ+нефте-прокси → канал ДЕВАЛЬВАЦИИ; fiscal_drain = фактический дефицит →
канал ДИСКОНТА АКЦИЙ; разные выходы).

Считается от ЁМКОСТИ ПУЛА (≈ВВП), не от объёма долга (спека §2/§5): пул статичен (стагнация+закрытая
рента), потребность принуждённо растёт → разрыв → эмиссия → структурно высокая КС → пылесос.
"""
from __future__ import annotations

from dataclasses import dataclass

FISCAL_DRAIN_MAX = 0.09       # потолок дисконта пылесоса, пп (при максимальной интенсивности)
DEFICIT_GDP_FULL = 0.04       # дефицит ≥4% ВВП (run-rate) = сильный дренаж (полная шкала по этой оси)
W_GDP, W_OVERSHOOT = 0.6, 0.4 # веса: глубина (% ВВП) и превышение плана (административный сдвиг плана к факту)


@dataclass
class FiscalDrain:
    drain_pp: float       # дисконт к оценке акций, пп (входит в r равновесного P/E, §3)
    intensity: float      # 0..1
    level: str            # низкий | повышенный | высокий
    deficit_pct_gdp: float
    overshoot: float      # факт/план − 1
    note: str


def fiscal_drain(*, deficit_trln: float, plan_trln: float, gdp_trln: float) -> FiscalDrain:
    """Дисконт пылесоса из дефицита (run-rate/прогноз, трлн) vs ВВП и плана.

    intensity = W_GDP·(дефицит%ВВП / 4%) + W_OVERSHOOT·min(1, превышение плана). drain = MAX·intensity.
    От ёмкости пула (ВВП), не от долга. Превышение плана учитывается, т.к. Минфин «уточняет параметры
    без поправок в закон» → план де-факто подвинут к факту → метрика «факт−план» сама по себе слепнет."""
    gdp = gdp_trln or 200.0
    pct_gdp = max(0.0, deficit_trln) / gdp
    overshoot = max(0.0, (deficit_trln / plan_trln) - 1.0) if plan_trln else 0.0
    intensity = min(1.0, W_GDP * (pct_gdp / DEFICIT_GDP_FULL) + W_OVERSHOOT * min(1.0, overshoot))
    drain_pp = FISCAL_DRAIN_MAX * intensity
    level = "высокий" if intensity >= 0.66 else ("повышенный" if intensity >= 0.33 else "низкий")
    note = (f"Дисконт пылесоса {drain_pp*100:.1f}пп (интенсивность {intensity:.0%}, {level}): дефицит "
            f"{deficit_trln:.1f} трлн = {pct_gdp*100:.1f}% ВВП, превышение плана {overshoot*100:.0f}%. "
            f"Пул сбережений выгребается в ОФЗ → бида акциям меньше → дисконт к равновесному P/E (§2/§3). "
            f"НЕ в hurdle (отдельный канал от deval_score, §10).")
    return FiscalDrain(drain_pp=round(drain_pp, 4), intensity=round(intensity, 3), level=level,
                       deficit_pct_gdp=round(pct_gdp, 4), overshoot=round(overshoot, 3), note=note)
