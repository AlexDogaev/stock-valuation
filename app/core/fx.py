"""Валюта как класс инструмента в меню альтернатив (REVIEW мультиассет).

Закрытие акцие-центричной слепоты: на горизонте 1 год валюта может быть лучшим вложением.
  E[отдача] = E[курсовая по РАСПРЕДЕЛЕНИЮ] + купон − carry
Сравнение с hurdle + ПОВЫШЕННЫЙ MoS (прогноз курса ненадёжен). Правило ДОМИНИРОВАНИЯ: при наличии
купонного аналога (замещайка/юаневый бонд) голую валюту НЕ предлагать. Левый хвост (укрепление) — в риск,
не только в EV. Барбелл: купонно-валютные — и защитное плечо (девал-хедж+доход), и тактическая атака.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FXAssessment:
    e_return: float            # E[курс] + купон − carry
    e_fx_move: float           # ожидаемое курсовое по распределению
    left_tail: float           # худший сценарий (укрепление рубля) — риск
    signal: str
    dominated: bool            # голая валюта при наличии купонного аналога
    notes: list[str] = field(default_factory=list)


def assess_fx(
    *,
    scenarios: list[tuple[float, float]],   # [(вероятность, курсовая доходность), ...]
    carry: float,                           # стоимость carry (номинальная рублёвая безриск по траектории КС)
    hurdle: float,                          # ориентир (carry или таргет)
    buffer: float,
    coupon: float = 0.0,                    # купон валютного инструмента (0 = голая валюта)
    has_coupon_analog: bool = False,        # есть ли купонная замена этой валюты
) -> FXAssessment:
    """Троичный сигнал по FX-позиции с повышенным MoS и правилом доминирования."""
    wsum = sum(p for p, _ in scenarios) or 1.0
    e_fx = sum(p * m for p, m in scenarios) / wsum
    e_return = e_fx + coupon - carry
    left_tail = min((m for _, m in scenarios), default=0.0)
    mos = buffer * 2.0                       # курс ненадёжен → повышенная маржа безопасности

    notes: list[str] = []
    dominated = coupon == 0.0 and has_coupon_analog
    if dominated:
        notes.append("Голая валюта ДОМИНИРУЕМА: есть купонный аналог (замещайка/юаневый бонд) — "
                     "тот же курсовой риск + купон. Не предлагать голую.")
    if e_return >= hurdle + mos:
        signal = "ПОКУПАЙ"
    elif e_return < hurdle - mos:
        signal = "ВОЗДЕРЖИСЬ"
    else:
        signal = "ГРАНИЦА"
    if dominated and signal == "ПОКУПАЙ":
        signal = "ГРАНИЦА"                   # доминируемую не рекомендуем к покупке
    notes.append(f"Левый хвост (укрепление рубля) {left_tail*100:+.0f}% — учитывать в риске, не только EV. "
                 "Купонно-валютные — кандидат и в защитное плечо барбелла (девал-хедж + доход).")
    return FXAssessment(e_return=round(e_return, 4), e_fx_move=round(e_fx, 4),
                        left_tail=round(left_tail, 4), signal=signal, dominated=dominated, notes=notes)
