"""Маркеры качества эмитента (чистая функция, §3 плана автономности).

Автоприсвоение поверх количественного сигнала и структурного балла:
- PROVEN_QUALITY        — доказанное качество, ядро рукава атаки (всегда держим).
- STRUCTURAL_QUALITY    — структурно сильное, но НЕ дивидендно-зрелое (устойчивый ROIC + рва есть,
                          payout мал — реинвестирует: золото-капекс/уник.активы). НЕ «спекулятивное».
- PROSPECTIVE_QUALITY   — перспективное с доказанной монетизацией, добор в шок.
- PROSPECTIVE_NO_QUALITY — спекулятивное (нет доказанной структурной базы), только наблюдение.
- ordinary              — обычное (структурный балл низкий).
"""
from __future__ import annotations

HYPER_GROWTH = 0.30       # рост выручки выше — гипер-рост (не «доказанное» качество)
EXPENSIVE_COMPRESSION = 0.92  # сжатие ниже — дорогой мультипликатор (растущий)
MIN_SCORE = 2             # минимальный структурный балл для не-ordinary
                          # (калибровка по эталону X5: зрелое качество с мягким
                          # структурным баллом 2 — PROVEN держат уже количественные
                          # гейты roic_years/payout/не-hyper/не-дорогой, не балл)
MIN_ROIC_YEARS = 5        # лет устойчивого ROIC для доказанного качества
MIN_PAYOUT = 0.40         # дивиденды как признак зрелой монетизации

LABELS_RU = {
    "PROVEN_QUALITY": "Доказанное качество",
    "STRUCTURAL_QUALITY": "Структурное качество (реинвест)",
    "PROSPECTIVE_QUALITY": "Перспективное качество",
    "PROSPECTIVE_NO_QUALITY": "Перспективное без качества",
    "ordinary": "Обычное",
}


def quality_marker(*, structural_score: int, roic_years: int, payout: float | None,
                   revenue_growth: float | None, compression: float | None,
                   monetization_proven: int, is_platform: int = 0) -> str:
    is_hyper = (revenue_growth or 0.0) > HYPER_GROWTH
    is_multiple = compression is not None and compression < EXPENSIVE_COMPRESSION

    if structural_score < MIN_SCORE:
        return "ordinary"
    # Платформа (§3, NOTES §2): критерий — ЭКОСИСТЕМНАЯ монетизация, не автономная
    # прибыльность торгового ядра (ядро by design loss-leader). Ядро платформы
    # реинвестирует (низкий payout) → к доказанному (дивидендная зрелость) не идёт;
    # категориальная ловушка — считать «большую платформу» качеством без доказанной
    # монетизации. monetization_proven здесь = доказана экосистемная монетизация.
    if is_platform == 1:
        return "PROSPECTIVE_QUALITY" if monetization_proven == 1 else "PROSPECTIVE_NO_QUALITY"
    # доказанная СТРУКТУРНАЯ база без payout-гейта: устойчивый ROIC, не гипер-рост, не дорогой мультипликатор
    proven_core = (roic_years >= MIN_ROIC_YEARS and not is_hyper and not is_multiple)
    if proven_core and (payout or 0.0) >= MIN_PAYOUT:
        return "PROVEN_QUALITY"                    # + дивидендная зрелость
    if proven_core:
        return "STRUCTURAL_QUALITY"                 # силён структурно, но реинвестирует (payout мал) — НЕ спекул.
    if monetization_proven == 1:
        return "PROSPECTIVE_QUALITY"
    return "PROSPECTIVE_NO_QUALITY"
