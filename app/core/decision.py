"""Матрица решения: вердикт = пересечение [качество] × [цена] (INSTRUCTIONS §1).

Самое важное и легче всего нарушаемое правило двухслойности: качество (свойство
бизнеса) и цена (margin of safety) считаются РАЗДЕЛЬНО, а итоговое действие — их
ПЕРЕСЕЧЕНИЕ, не одно из двух. Качество (даже высокое) + отрицательная margin of
safety → «список ожидания на обвал», НЕ «покупка». Здесь модель не должна
поддаваться на «блеск» (§11: высокий оптимизм = уже оплачен, понижает, а не
повышает привлекательность).

Цена раскладывается в зону {cheap | edge | expensive}; «оптимизм в цене» (§7) или
отрицательная margin of safety перебивают номинальный троичный сигнал в expensive.
"""
from __future__ import annotations

# ── зоны цены ────────────────────────────────────────────────────────────────
ZONE_CHEAP = "cheap"        # BUY-зона: положительная margin of safety
ZONE_EDGE = "edge"          # граница
ZONE_EXPENSIVE = "expensive"  # дорого / оптимизм заложен в цену

ZONE_LABELS_RU = {
    ZONE_CHEAP: "дёшево (margin of safety +)",
    ZONE_EDGE: "граница",
    ZONE_EXPENSIVE: "дорого (оптимизм в цене)",
}


def price_zone(*, signal: str, optimism_priced_in: bool = False) -> str:
    """Зона цены из троичного сигнала, с одной перебивкой — «оптимизм в цене».

    Сам троичный сигнал уже несёт margin of safety через буфер: ПОКУПАЙ =
    real ≥ hurdle+buffer (положительная MoS), ВОЗДЕРЖИСЬ = real < hurdle−buffer
    (отрицательная MoS), ГРАНИЦА = в пределах буфера (≈ноль). Поэтому отдельно
    margin of safety НЕ переучитываем (это было бы двойным счётом).

    Единственная перебивка — «оптимизм в цене» (§7): расчётная доходность может
    выглядеть ок, но высокий мультипликатор уже заложил будущий рост → блеск
    оплачен, это дорого вне зависимости от номинального сигнала (§11).
    """
    if optimism_priced_in:
        return ZONE_EXPENSIVE
    if signal == "ПОКУПАЙ":
        return ZONE_CHEAP
    if signal == "ВОЗДЕРЖИСЬ":
        return ZONE_EXPENSIVE
    return ZONE_EDGE


# ── матрица [маркер качества] × [зона цены] → действие (§1) ───────────────────
MATRIX: dict[tuple[str, str], str] = {
    ("PROVEN_QUALITY", ZONE_CHEAP): "докупать ядро",
    ("PROVEN_QUALITY", ZONE_EDGE): "держать",
    ("PROVEN_QUALITY", ZONE_EXPENSIVE): "держать, не докупать",
    ("STRUCTURAL_QUALITY", ZONE_CHEAP): "докупать",
    ("STRUCTURAL_QUALITY", ZONE_EDGE): "держать",
    ("STRUCTURAL_QUALITY", ZONE_EXPENSIVE): "держать, не докупать",
    ("PROSPECTIVE_QUALITY", ZONE_CHEAP): "докупать",
    ("PROSPECTIVE_QUALITY", ZONE_EDGE): "наблюдать",
    ("PROSPECTIVE_QUALITY", ZONE_EXPENSIVE): "список ожидания на обвал",
    ("PROSPECTIVE_NO_QUALITY", ZONE_CHEAP): "спекулятивно малой долей",
    ("PROSPECTIVE_NO_QUALITY", ZONE_EDGE): "наблюдать",
    ("PROSPECTIVE_NO_QUALITY", ZONE_EXPENSIVE): "мимо",
}

# для «обычного» качества дёшево/граница отдаются троичному сигналу (§1, строка 4)
_ORDINARY_BY_SIGNAL = {
    "ПОКУПАЙ": "покупать по сигналу",
    "ГРАНИЦА": "держать / наблюдать",
    "ВОЗДЕРЖИСЬ": "мимо",
}


def matrix_action(*, qmark: str, zone: str, signal: str) -> str:
    """Действие из матрицы §1. Для «обычного» дёшево/граница → по троичному сигналу."""
    if qmark == "ordinary":
        if zone == ZONE_EXPENSIVE:
            return "мимо"
        return _ORDINARY_BY_SIGNAL.get(signal, signal)
    return MATRIX[(qmark, zone)]


# действия, означающие «не покупка сейчас, ждём обвала» — для подсветки в UI/событиях
WATCHLIST_ACTIONS = {"список ожидания на обвал"}
