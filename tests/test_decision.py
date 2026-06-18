"""Матрица решения качество×цена (§1) + тест «аванс в цене» (§7) +
регрессионный тест на ПОНИМАНИЕ двухслойности — кейс ОЗОН (§13).

§13 — это регрессия на правильность МЫШЛЕНИЯ, не на точность числа: на входных
данных Озона модель обязана выдать цепочку «перспективное качество × дорого →
список ожидания», а НЕ «покупай — растущий чемпион».
"""
from app.core import decision
from app.core.valuation import optimism_priced_in


# ── матрица §1 ────────────────────────────────────────────────────────────────
def test_matrix_proven_quality():
    assert decision.matrix_action(qmark="PROVEN_QUALITY", zone=decision.ZONE_CHEAP,
                                  signal="ПОКУПАЙ") == "докупать ядро"
    assert decision.matrix_action(qmark="PROVEN_QUALITY", zone=decision.ZONE_EXPENSIVE,
                                  signal="ВОЗДЕРЖИСЬ") == "держать, не докупать"


def test_matrix_prospective_quality_expensive_is_watchlist():
    # ключевое правило: качество + дорого → НЕ покупка, а список ожидания
    assert decision.matrix_action(qmark="PROSPECTIVE_QUALITY", zone=decision.ZONE_EXPENSIVE,
                                  signal="ПОКУПАЙ") == "список ожидания на обвал"


def test_matrix_ordinary_defers_to_signal():
    assert decision.matrix_action(qmark="ordinary", zone=decision.ZONE_CHEAP,
                                  signal="ГРАНИЦА") == "держать / наблюдать"
    assert decision.matrix_action(qmark="ordinary", zone=decision.ZONE_EXPENSIVE,
                                  signal="ВОЗДЕРЖИСЬ") == "мимо"


# ── зона цены: оптимизм / отрицательная MoS перебивают сигнал ─────────────────
def test_optimism_overrides_signal_to_expensive():
    # даже при номинальном ПОКУПАЙ оптимизм в цене → дорого
    assert decision.price_zone(signal="ПОКУПАЙ", optimism_priced_in=True) == decision.ZONE_EXPENSIVE


def test_zone_from_signal_no_double_count():
    # без оптимизма зона = сигнал (буфер уже несёт margin of safety; не переучитываем)
    assert decision.price_zone(signal="ПОКУПАЙ") == decision.ZONE_CHEAP
    assert decision.price_zone(signal="ГРАНИЦА") == decision.ZONE_EDGE
    assert decision.price_zone(signal="ВОЗДЕРЖИСЬ") == decision.ZONE_EXPENSIVE


# ── тест «аванс в цене» §7 ────────────────────────────────────────────────────
def test_optimism_flag_on_loss():
    # убыток/околоноль → флаг всегда (любая имплицированная прибыль кратно выше)
    res = optimism_priced_in(cap_bln=1000.0, net_profit_bln=0.5)
    assert res.flag is True
    assert res.implied_profit > 100  # ~167 млрд при P/E 6


def test_optimism_flag_off_for_fairly_priced():
    # капа ≈ нормальный P/E × текущая прибыль → аванса нет
    res = optimism_priced_in(cap_bln=60.0, net_profit_bln=10.0)  # implied 10 == current
    assert res.flag is False


# ── §13: регрессионный тест ОЗОН (цепочка мышления) ───────────────────────────
def test_ozon_regression_chain():
    """ОЗОН: качество есть (платформа), но все источники апсайда упёрты и оптимизм
    в цене → перспективное качество × дорого → СПИСОК ОЖИДАНИЯ, не покупка."""
    # 1. качество модели есть → перспективное качество (платформенный критерий)
    qmark = "PROSPECTIVE_QUALITY"

    # 3. флаг «аванс в цене»: капа имплицирует ~100 млрд против околонулевой прибыли
    opt = optimism_priced_in(cap_bln=900.0, net_profit_bln=2.0)
    assert opt.flag is True, "оптимизм должен быть распознан как заложенный в цену"

    # 2+4. зона = дорого (оптимизм перебивает любой номинальный сигнал)
    zone = decision.price_zone(signal="ПОКУПАЙ", optimism_priced_in=opt.flag)
    assert zone == decision.ZONE_EXPENSIVE

    # итог матрицы: перспективное качество × дорого → список ожидания на обвал
    action = decision.matrix_action(qmark=qmark, zone=zone, signal="ПОКУПАЙ")
    assert action == "список ожидания на обвал", (
        "регрессия мышления: качество×дорого обязано дать список ожидания, не покупку")
    assert action in decision.WATCHLIST_ACTIONS
