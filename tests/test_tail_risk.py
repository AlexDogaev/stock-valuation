"""Обнуляющие РФ-риски: гейт сигнала (red-team #5)."""
from app.core.tail_risk import assess_tail_risk


def test_no_risk_passes():
    t = assess_tail_risk()
    assert t.gate is None and t.max_severity == 0 and t.flags == {}


def test_acute_blocks():
    t = assess_tail_risk(expropriation=2)          # острый → block (→ ВОЗДЕРЖИСЬ)
    assert t.gate == "block" and t.max_severity == 2 and "expropriation" in t.flags


def test_elevated_caps():
    t = assess_tail_risk(minority=1, liquidity=1)  # повышенный → cap (ПОКУПАЙ→ГРАНИЦА)
    assert t.gate == "cap" and t.max_severity == 1 and len(t.flags) == 2


def test_acute_dominates_elevated():
    t = assess_tail_risk(minority=1, delisting=2)
    assert t.gate == "block"                        # любой острый → block
