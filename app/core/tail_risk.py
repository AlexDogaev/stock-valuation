"""Обнуляющие РФ-риски — слой, режущий ТЕЛО инвестиции (red-team аудит #5, 20.06.2026).

Justified-оценка (P/B, full_return) молча предполагает, что прибыль ДОЙДЁТ до миноритария и из
позиции МОЖНО выйти. В РФ это не дано: экспроприация (FESCO), делистинг (ГлобалТранс),
санкц.заморозка/неторгуемость, размытие миноритария/вывод активов, неликвидность выхода (в шок
выйти невозможно). Эти риски ОБНУЛЯЮТ исход, а не искажают доходность — буфер/MoS не спасают.
Поэтому слой работает ГЕЙТОМ (снимает BUY), а не плавным дисконтом.

Шкала каждого риска: 0 нет / 1 повышенный / 2 острый (реализуется/анонсирован).
Острый (≥2) → block (сигнал → ВОЗДЕРЖИСЬ); повышенный (1) → cap (ПОКУПАЙ → ГРАНИЦА).
"""
from __future__ import annotations

from dataclasses import dataclass, field

RISK_LABELS = {
    "minority": "корп.управление / риск миноритария (размытие, вывод активов, принуд.выкуп)",
    "expropriation": "экспроприация / национализация",
    "delisting": "делистинг / уход с биржи",
    "sanctions": "санкц.заморозка / неторгуемость",
    "liquidity": "неликвидность выхода (в шок выход невозможен)",
}


@dataclass
class TailRisk:
    max_severity: int           # 0 / 1 / 2
    gate: str | None            # 'block' (→ ВОЗДЕРЖИСЬ) | 'cap' (→ max ГРАНИЦА) | None
    flags: dict                 # {риск: severity} только ненулевые
    notes: list[str] = field(default_factory=list)


def assess_tail_risk(*, minority: int = 0, expropriation: int = 0, delisting: int = 0,
                     sanctions: int = 0, liquidity: int = 0) -> TailRisk:
    """Свод обнуляющих рисков эмитента → гейт. Острый любой → block; иначе повышенный → cap."""
    raw = {"minority": minority, "expropriation": expropriation, "delisting": delisting,
           "sanctions": sanctions, "liquidity": liquidity}
    flags = {k: int(v) for k, v in raw.items() if v}
    if not flags:
        return TailRisk(0, None, {})
    mx = max(flags.values())
    gate = "block" if mx >= 2 else "cap"
    notes = [f"{RISK_LABELS[k]} — {'ОСТРЫЙ' if v >= 2 else 'повышенный'}" for k, v in flags.items()]
    return TailRisk(max_severity=mx, gate=gate, flags=flags, notes=notes)
