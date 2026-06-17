"""Режим рынка по ФНБ + бюджетному правилу + просадке рынка."""
from app.core.nwf_regime import nwf_regime


def test_normal_regime():
    r = nwf_regime(liquid_nwf_pct=5.0, months_to_zero=60, urals=70, cutoff=60,
                   market_drawdown=0.05)
    assert r.regime == "NORMAL"
    assert (r.defense, r.attack) == (0.30, 0.70)
    assert r.budget_sign == 10  # 70 − 60, профицит


def test_risk_regime():
    r = nwf_regime(liquid_nwf_pct=1.5, months_to_zero=12, urals=55, cutoff=60,
                   market_drawdown=0.05)
    assert r.regime == "RISK"
    assert (r.defense, r.attack) == (0.70, 0.30)
    assert r.budget_sign == -5  # дефицит


def test_shock_override_beats_fundamentals():
    # глубокая просадка → ШОК даже при здоровом ФНБ
    r = nwf_regime(liquid_nwf_pct=5.0, months_to_zero=60, urals=70, cutoff=60,
                   market_drawdown=0.30)
    assert r.regime == "SHOCK"
    assert (r.defense, r.attack) == (0.20, 0.80)


def test_shock_threshold_boundary():
    # ровно на границе 27% — ещё не ШОК
    r = nwf_regime(liquid_nwf_pct=5.0, months_to_zero=60, urals=70, cutoff=60,
                   market_drawdown=0.27)
    assert r.regime != "SHOCK"
