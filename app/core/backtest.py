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
    rank_corr: float | None = None         # Спирмен предсказ↔реализ (дискриминация, red-team #8)
    discrimination_pp: float | None = None  # реализ верх.половины − нижней (пп): «бьёт ли сигнал»
    signal_verdict: str = ""


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    """Ранговая корреляция Спирмена (Пирсон на рангах)."""
    n = len(xs)
    if n < 3:
        return None

    def _ranks(v: list[float]) -> list[float]:
        order = sorted(range(n), key=lambda i: v[i])
        rk = [0.0] * n
        for pos, i in enumerate(order):
            rk[i] = float(pos)
        return rk

    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = mean(rx), mean(ry)
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    den = (sum((rx[i] - mx) ** 2 for i in range(n)) * sum((ry[i] - my) ** 2 for i in range(n))) ** 0.5
    return round(num / den, 3) if den else None


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

    # ДИСКРИМИНАЦИЯ СИГНАЛА (red-team #8): бьёт ли высокий прогноз более высокий ФАКТ.
    # Калибровка (hit_rate) ≠ дискриминация: модель может мазать по абсолюту, но верно РАНЖИРОВАТЬ.
    rank_corr = _spearman([c.predicted for c in out], [c.realized for c in out])
    discrimination_pp = None
    signal_verdict = "мало кейсов для дискриминации"
    if len(out) >= 6:
        ordered = sorted(out, key=lambda c: c.predicted)
        half = len(ordered) // 2
        low_real = mean([c.realized for c in ordered[:half]])
        high_real = mean([c.realized for c in ordered[-half:]])
        discrimination_pp = round((high_real - low_real) * 100.0, 1)
        if discrimination_pp > 2:
            signal_verdict = (f"Сигнал РАЗЛИЧАЕТ: верх по прогнозу обогнал низ на {discrimination_pp:+.1f}пп факта "
                              f"(ранг.корр {rank_corr}). «Покупай» исторически бьёт «воздержись».")
        elif discrimination_pp < -2:
            signal_verdict = (f"Сигнал ИНВЕРТИРОВАН ({discrimination_pp:+.1f}пп) — высокий прогноз дал НИЖЕ факт. "
                              f"Красный флаг предсказательности.")
        else:
            signal_verdict = (f"Сигнал НЕ различает ({discrimination_pp:+.1f}пп, ранг.корр {rank_corr}) — "
                              f"прогноз не ранжирует доходность лучше монетки.")
    return BacktestSummary(out, me, sd, hit_rate, verdict,
                           rank_corr=rank_corr, discrimination_pp=discrimination_pp,
                           signal_verdict=signal_verdict)
