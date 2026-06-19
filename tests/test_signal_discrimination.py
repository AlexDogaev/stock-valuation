"""Дискриминация сигнала в бэктесте (red-team #8)."""
from app.core.backtest import run_backtest


def test_discriminating_signal():
    # высокий прогноз → высокий факт (монотонно) → дискриминация положительна
    cases = [(f"c{i}", i / 100.0, i / 100.0) for i in range(1, 13)]
    s = run_backtest(cases)
    assert s.rank_corr == 1.0 and s.discrimination_pp > 2 and "РАЗЛИЧАЕТ" in s.signal_verdict


def test_inverted_signal():
    # высокий прогноз → НИЗКИЙ факт → инверсия
    cases = [(f"c{i}", i / 100.0, (13 - i) / 100.0) for i in range(1, 13)]
    s = run_backtest(cases)
    assert s.rank_corr == -1.0 and s.discrimination_pp < -2 and "ИНВЕРТ" in s.signal_verdict
