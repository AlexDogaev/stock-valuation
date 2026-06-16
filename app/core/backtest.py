"""Backtest — проверка ПРЕДСКАЗАТЕЛЬНОЙ силы (лист «Backtest»).

Validation ≠ предсказание. Воспроизведение известной цены подбором r и g
доказывает только внутреннюю СОГЛАСОВАННОСТЬ модели, НЕ предсказательность.
Единственная настоящая проверка — слепой прогон прошлого: вводишь цену и
фундаментал ПРОШЛОГО, модель даёт предсказанную доходность, сравниваешь с фактом.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, pstdev


@dataclass
class BacktestCase:
    label: str
    predicted: float
    realized: float
    error_pp: float       # (предсказ − реализ) × 100
    hit: bool             # |ошибка| < 5 п.п.


@dataclass
class BacktestSummary:
    cases: list[BacktestCase]
    mean_error_pp: float
    std_error_pp: float
    hit_rate: float
    verdict: str


def run_backtest(cases: list[tuple[str, float, float]], *, tol: float = 0.05) -> BacktestSummary:
    """cases: [(label, predicted, realized), ...]. tol — допуск попадания (5 п.п.)."""
    out: list[BacktestCase] = []
    for label, pred, real in cases:
        err = (pred - real) * 100.0
        out.append(BacktestCase(label, pred, real, err, abs(pred - real) < tol))
    if not out:
        return BacktestSummary([], 0.0, 0.0, 0.0, "нет кейсов")
    errs = [c.error_pp for c in out]
    hit_rate = sum(c.hit for c in out) / len(out)
    me = mean(errs)
    sd = pstdev(errs) if len(errs) > 1 else 0.0
    if len(out) < 10:
        verdict = ("Мало кейсов: предсказательность НЕ доказана. Нужны десятки "
                   "слепых прогонов на истории.")
    elif abs(me) < 3 and sd < 8:
        verdict = "Малая ошибка без системного смещения — модель предсказывает."
    else:
        verdict = "Системное смещение/большой разброс — модель НЕ предсказывает."
    return BacktestSummary(out, me, sd, hit_rate, verdict)
