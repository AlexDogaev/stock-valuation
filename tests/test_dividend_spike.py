"""Детектор аномальной TTM-дивдоходности (разовый спецдивиденд).

Критерий не должен трогать зрелые дивидендные имена (высокая дивдох — их норма),
но обязан ловить разовый спецдив (X5 после редомициляции).
"""
from app.data.moex import is_dividend_spike


def test_x5_spike_absolute():
    # X5: TTM 26.9%, типичной нормы нет (короткая история) → spike по абсолюту
    assert is_dividend_spike(0.269, None) is True


def test_moex_spike_relative():
    # Мосбиржа: 14.7% против типичных 7.6% → > 1.8× → spike
    assert is_dividend_spike(0.147, 0.076) is True


def test_lukoil_not_spike():
    # Лукойл: 16.8% против 11.7% → 16.8 < 1.8×11.7=21.06 → НЕ spike (норма)
    assert is_dividend_spike(0.168, 0.117) is False


def test_mts_not_spike():
    # МТС: стабильно высокая дивдох — норма, не аномалия
    assert is_dividend_spike(0.153, 0.153) is False


def test_sber_not_spike():
    assert is_dividend_spike(0.107, 0.090) is False


def test_none_not_spike():
    assert is_dividend_spike(None, None) is False


def test_high_but_typical_not_spike():
    # высокая, но соответствует исторической норме → не аномалия
    assert is_dividend_spike(0.19, 0.18) is False
