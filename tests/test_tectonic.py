"""Тектоническая рама (§1-7): период, секторный множитель, маршрутизация по валюте."""
from app.core.tectonic import tectonic_g, period_for_year, CORRIDOR_HI, CORRIDOR_LO


def test_period_for_year():
    assert period_for_year(2026) == "P1"
    assert period_for_year(2033) == "P2"
    assert period_for_year(2038) == "P3"
    assert period_for_year(2044) == "P4"


def test_medicine_domestic_ascending():
    # старение → восходящий профиль (P3 сильнее P1) — кейс MDMG
    p1 = tectonic_g("Медицина", "DOMESTIC", year=2027)
    p3 = tectonic_g("Медицина", "DOMESTIC", year=2037)
    assert p1.routed and p1.sector_delta > 0
    assert p3.sector_delta > p1.sector_delta          # восходящий
    assert p1.peak_period in ("P3", "P4")


def test_exporter_routed_zero():
    # РФ-демография в спрос экспортёра не идёт
    r = tectonic_g("Нефтегаз", "EXPORTER", year=2027)
    assert r.routed is False
    assert r.sector_delta == 0.0


def test_domestic_headwind_negative():
    # детское: рождаемость − (дно P1)
    r = tectonic_g("Детское", "DOMESTIC", year=2027)
    assert r.sector_delta < 0


def test_unknown_sector_neutral():
    r = tectonic_g("Криптомайнинг", "DOMESTIC", year=2027)
    assert r.sector_delta == 0.0 and r.routed


def test_corridor_bounds():
    for sec in ("Медицина", "Нефтегаз", "Детское"):
        for y in (2027, 2033, 2038, 2044):
            d = tectonic_g(sec, "DOMESTIC", year=y).sector_delta
            assert CORRIDOR_LO <= d <= CORRIDOR_HI
