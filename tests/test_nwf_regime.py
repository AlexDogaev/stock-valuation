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


def test_deficit_drives_risk():
    # горизонт ФНБ здоровый, но тонкий ФНБ + глубокий дефицит → RISK (дефицит = драйвер)
    r = nwf_regime(liquid_nwf_pct=2.5, months_to_zero=36, urals=45, cutoff=60,
                   market_drawdown=0.05)
    assert r.deval_score == 3      # ФНБ тонкий +1, дефицит ≥10 +2
    assert r.regime == "RISK"


def test_deval_pressure_high():
    r = nwf_regime(liquid_nwf_pct=1.0, months_to_zero=8, urals=48, cutoff=60,
                   market_drawdown=0.05)
    assert r.deval_score == 6
    assert r.deval_pressure == "high"
    assert r.regime == "RISK"


def test_normal_low_pressure():
    r = nwf_regime(liquid_nwf_pct=5.0, months_to_zero=60, urals=70, cutoff=60,
                   market_drawdown=0.05)
    assert r.deval_score == 0
    assert r.deval_pressure == "low"
