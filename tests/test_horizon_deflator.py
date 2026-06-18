"""Дефлятор с траекторией снижения инфляции по горизонту (КС-trajectory)."""
from app.core.valuation import horizon_deflator


def test_horizon_one_year_is_flat():
    assert horizon_deflator(0.141, 0.08, 1) == 0.141


def test_no_terminal_is_flat():
    assert horizon_deflator(0.141, None, 3) == 0.141


def test_terminal_equals_felt_is_flat():
    assert abs(horizon_deflator(0.10, 0.10, 5) - 0.10) < 1e-9


def test_three_year_glide_geomean():
    # 14.1% → 8% за 3 года: годы 14.1 / 11.05 / 8.0 → геом. среднее ≈ 11.0%
    d = horizon_deflator(0.141, 0.08, 3)
    assert 0.108 < d < 0.112


def test_lower_terminal_lowers_deflator():
    assert horizon_deflator(0.141, 0.06, 3) < horizon_deflator(0.141, 0.10, 3) < 0.141


def test_deflator_between_terminal_and_felt():
    d = horizon_deflator(0.141, 0.08, 3)
    assert 0.08 < d < 0.141
