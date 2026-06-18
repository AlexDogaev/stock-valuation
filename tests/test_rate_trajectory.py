"""Градация траектории КС: числовой пейс + маппинг в терминал/инфляцию."""
from app.core import rate_trajectory as rt


def test_pace_steady_cuts_is_normal():
    # −0.5пп за заседание (как ЦБ сейчас) → обычное снижение
    dec = [("2025-12-22", 0.16), ("2026-02-16", 0.155), ("2026-03-23", 0.15), ("2026-04-27", 0.145)]
    g = rt.pace_grade(dec)
    assert g["grade"] == "обычное снижение"
    assert g["avg_step_pp"] == -0.5


def test_pace_hold():
    dec = [("2026-02-16", 0.15), ("2026-03-23", 0.15), ("2026-04-27", 0.15)]
    assert rt.pace_grade(dec)["grade"] == "удержание"


def test_pace_aggressive_cut():
    dec = [("2025-12-22", 0.18), ("2026-02-16", 0.16), ("2026-04-27", 0.14)]  # −2пп/шаг
    assert rt.pace_grade(dec)["grade"] == "агрессивное снижение"


def test_pace_slow_hike():
    dec = [("2026-02-16", 0.14), ("2026-04-27", 0.1425)]  # +0.25пп
    assert rt.pace_grade(dec)["grade"] == "медленное повышение"


def test_pace_too_few():
    assert rt.pace_grade([("2026-04-27", 0.145)])["grade"] == "удержание"


def test_terminal_ks_cut_goes_to_neutral():
    assert rt.grade_terminal_ks("обычное снижение", 0.145) == rt.NEUTRAL_KS
    assert rt.grade_terminal_ks("удержание", 0.145) == 0.145
    assert rt.grade_terminal_ks("агрессивное повышение", 0.145) == 0.145 + 0.03


def test_terminal_inflation_from_ks():
    # терминал КС 9% − реальный спред 2.5пп = 6.5%
    assert abs(rt.terminal_inflation_from_ks(0.09) - 0.065) < 1e-9
    assert rt.terminal_inflation_from_ks(0.02) == 0.0  # не уходит в минус
