"""Тектоническая рама (§1-7) + калибровка §7 NOTES_2: период, факторы, маршрутизация."""
from app.core.tectonic import tectonic_g, period_for_year, CORRIDOR_HI, CORRIDOR_LO


def test_period_for_year():
    assert period_for_year(2026) == "P1"
    assert period_for_year(2033) == "P2"
    assert period_for_year(2038) == "P3"
    assert period_for_year(2044) == "P4"


def test_aging_flat_plateau():
    # §7 поправка: старение РОВНОЕ ~+2пп (плато), НЕ восходящий (механизмы в противофазе)
    ds = [tectonic_g("Медицина", "DOMESTIC", year=y).sector_delta for y in (2027, 2033, 2038, 2044)]
    assert all(d > 0.015 for d in ds)           # сильный попутный всюду (~+2пп)
    assert max(ds) - min(ds) <= 0.006           # плато, узкий разброс


def test_mdmg_subsector_ascending():
    # MDMG = под-сегмент «Медицина_роды»: дно P1 (родовспоможение−), смягчение к P3 → ВОСХОДЯЩИЙ
    p1 = tectonic_g("Медицина", "DOMESTIC", year=2027, secid="MDMG").sector_delta
    p3 = tectonic_g("Медицина", "DOMESTIC", year=2037, secid="MDMG").sector_delta
    assert p3 > p1
    # и ниже общей медицины в P1 (роды тянут вниз)
    assert p1 < tectonic_g("Медицина", "DOMESTIC", year=2027).sector_delta


def test_exporter_routed_zero():
    r = tectonic_g("Нефтегаз", "EXPORTER", year=2027)
    assert r.routed is False and r.sector_delta == 0.0


def test_child_headwind_acute_clamped():
    # детское: рождаемость −2.5пп в P1 → клампится к полу коридора −1.5пп
    r = tectonic_g("Детское", "DOMESTIC", year=2027)
    assert r.sector_delta == CORRIDOR_LO


def test_bank_labor_cog_tailwind():
    # банки: ИИ режет клерикал (женский бэк-офис) + сбережения пожилых → попутный
    assert tectonic_g("Банк", "DOMESTIC", year=2027).sector_delta > 0


def test_corridor_bounds():
    for sec in ("Медицина", "Детское", "Девелопмент", "Банк"):
        for y in (2027, 2033, 2038, 2044):
            for sid in (None, "MDMG"):
                d = tectonic_g(sec, "DOMESTIC", year=y, secid=sid).sector_delta
                assert CORRIDOR_LO <= d <= CORRIDOR_HI
