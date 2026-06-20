"""Движок шока: типология, hazard-движок, геом-скаляр, интеграция (пересборка 20.06.2026)."""
from app.core import shock_typology as st, hazard_engine as he, ranking, integration as integ


def test_typology_blend_includes_L_tail():
    b = st.blend()
    # смесь включает L-тип → recovery ниже чистого V (geo 0.55), dd в разумном диапазоне
    assert -0.50 < b["equity_dd"] < -0.25 and b["recovery_1y"] < 0.55 and b["dominant"] == "geo"


def test_typology_weights_shift():
    b = st.blend({"geo": 0, "commodity": 0, "global": 0, "financial": 0, "lstag": 1.0})  # чистый L
    assert b["dominant"] == "lstag" and b["recovery_1y"] < 0.3


def test_hazard_engine_ewi_dynamic():
    calm = he.compute_hazard(year=2026, ewi={k: 0.0 for k in he.EWI_WEIGHTS})
    hot = he.compute_hazard(year=2026, ewi={k: 1.0 for k in he.EWI_WEIGHTS})
    assert hot.annual > calm.annual                          # EWI дышит
    assert calm.forward["1мес"] < calm.forward["12мес"] < calm.forward["20г"]  # forward растёт
    assert calm.annual_band[0] < calm.annual < calm.annual_band[1]


def test_hazard_structural_hump():
    # горб у окна (~2036) выше, чем сейчас
    assert he.structural_hump(2036) > he.structural_hump(2026)


def test_geom_penalizes_tail():
    # одна база, разный хвост: глубокий хвост → ниже геом (A5)
    shallow = ranking.fork(0.3, 0.12, -0.05)["geom_real"]
    deep = ranking.fork(0.3, 0.12, -0.40)["geom_real"]
    assert shallow > deep


def test_integration_pe_deisolation():
    iso = integ.assess({"financial_west": 0.05})
    open_ = integ.assess({"financial_west": 0.30})
    assert open_.terminal_pe_mult > iso.terminal_pe_mult     # деизоляция → P/E вверх
