"""Облигации — троичный сигнал наравне с акциями (REVIEW мультиассет).

Бонд проще акции: YTM контрактная. Логика:
  real_YTM = YTM − E[инфляция];  spread = YTM − КБД(дюрация) [не-ОФЗ]
  rate_signal: длинный ФИКС «+» при снижении КС (capital gain ≈ дюрация×Δставки); флоатер «+» при росте
  credit_ok = spread ≥ PD×LGD + премия  (см. credit_pd)
Троичный: ПОКУПАЙ если real_YTM ≥ hurdle+MoS И rate_signal не встречный И credit_ok; иначе Воздержись/Граница.
Hurdle — ОБЩИЙ реальный таргет (как у акций). Carry (номинальная КС по траектории) — альт. парковка.

NB РФ-специфика (для полноты, входы извне): оферты → yield-to-PUT не -to-maturity; амортизация;
модиф. дюрация для capital gain; фильтр ликвидности (неликвид → YTM по посл. сделке нерепрезентативна).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.core.credit_pd import credit_ok as _credit_ok, LGD_DEFAULT


@dataclass
class BondAssessment:
    real_ytm: float
    spread: float | None
    rate_signal: str            # благоприятен | нейтрален | встречный
    credit_ok: bool
    signal: str                 # ПОКУПАЙ | ГРАНИЦА | ВОЗДЕРЖИСЬ
    notes: list[str] = field(default_factory=list)


def rate_signal_for(*, rate_direction: str, floater: bool) -> str:
    """Длинный фикс выигрывает при СНИЖЕНИИ КС; флоатер — при РОСТЕ (купон переоценивается вверх)."""
    d = (rate_direction or "hold").lower()
    if floater:
        return "благоприятен" if d == "hike" else ("встречный" if d == "cut" else "нейтрален")
    return "благоприятен" if d == "cut" else ("встречный" if d == "hike" else "нейтрален")


def assess_bond(
    *,
    ytm: float,
    e_inflation: float,
    hurdle_real: float,
    buffer: float,
    rate_direction: str = "hold",
    floater: bool = False,
    kbd_at_duration: float | None = None,
    pd: float = 0.0,
    lgd: float = LGD_DEFAULT,
    is_ofz: bool = False,
    risk_premium: float = 0.01,
) -> BondAssessment:
    """Троичный сигнал по облигации. is_ofz → кредитный фильтр пройден (безриск)."""
    real_ytm = ytm - e_inflation
    spread = None if (is_ofz or kbd_at_duration is None) else ytm - kbd_at_duration
    rsig = rate_signal_for(rate_direction=rate_direction, floater=floater)
    if is_ofz:
        cred = True
    elif spread is None:
        cred = False
    else:
        cred = _credit_ok(spread=spread, pd=pd, lgd=lgd, risk_premium=risk_premium)

    notes: list[str] = []
    if real_ytm >= hurdle_real + buffer and rsig != "встречный" and cred:
        signal = "ПОКУПАЙ"
    elif real_ytm < hurdle_real - buffer or not cred:
        signal = "ВОЗДЕРЖИСЬ"
        if not cred:
            notes.append("Кредитный фильтр НЕ пройден: спред не покрывает PD×LGD + премию — компенсация за риск мала.")
    else:
        signal = "ГРАНИЦА"
    if rsig == "встречный":
        notes.append("Ставочный сигнал встречный: "
                     + ("флоатер при снижении КС теряет купон." if floater
                        else "длинный фикс при росте КС теряет в цене (дюрация×Δставки)."))
    return BondAssessment(real_ytm=round(real_ytm, 4), spread=round(spread, 4) if spread is not None else None,
                          rate_signal=rsig, credit_ok=cred, signal=signal, notes=notes)
