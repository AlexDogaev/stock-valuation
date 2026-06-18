"""Градация траектории ключевой ставки (направление × скорость) и её влияние.

Опус классифицирует траекторию по последним решениям ЦБ + риторике (см.
llm_macro.assess_rate_trajectory). Здесь — чистые функции: числовой fallback по
темпу (когда Opus недоступен) и маппинг грейд → терминальная КС → терминальная
инфляция (дефолты; owner может калибровать). Терминальная инфляция кормит глайд
дефлятора (valuation.horizon_deflator).
"""
from __future__ import annotations

# 7 грейдов: направление × скорость + удержание
GRADES = [
    "агрессивное снижение", "обычное снижение", "медленное снижение",
    "удержание",
    "медленное повышение", "обычное повышение", "агрессивное повышение",
]

# пороги среднего шага за заседание (пп) для числового fallback
STEP_HOLD = 0.13      # |шаг| ниже — удержание
STEP_NORMAL = 0.35    # ≥ — «обычное», иначе «медленное»
STEP_AGGR = 0.85      # ≥ — «агрессивное»

NEUTRAL_KS = 0.09     # долгосрочная нейтральная КС РФ (дефолт; Opus уточняет терминал)
REAL_SPREAD = 0.025   # целевой реальный спред КС − инфляция (долгосрочно)


def pace_grade(decisions: list[tuple[str, float]]) -> dict:
    """Числовая градация по темпу последних решений (fallback без Opus).

    decisions: [(ISO-дата, ставка-доля), ...] точки изменения по возрастанию.
    Берёт последние ≤4 решения (≤3 шага), средний шаг в пп.
    """
    pts = decisions[-4:]
    if len(pts) < 2:
        return {"grade": "удержание", "avg_step_pp": 0.0, "n": len(pts)}
    steps = [(pts[i + 1][1] - pts[i][1]) * 100 for i in range(len(pts) - 1)]
    avg = sum(steps) / len(steps)
    mag = abs(avg)
    if mag < STEP_HOLD:
        grade = "удержание"
    else:
        speed = ("агрессивное" if mag >= STEP_AGGR
                 else "обычное" if mag >= STEP_NORMAL else "медленное")
        grade = f"{speed} {'снижение' if avg < 0 else 'повышение'}"
    return {"grade": grade, "avg_step_pp": round(avg, 2), "n": len(pts)}


def grade_terminal_ks(grade: str, current_ks: float) -> float:
    """Терминальная КС (куда сойдёт) по грейду — дефолт для fallback.

    Снижение → к нейтральной; удержание → текущая; повышение → выше на шаг по скорости.
    Opus возвращает терминал явно и перекрывает эту оценку.
    """
    if "удержание" in grade:
        return current_ks
    if "снижение" in grade:
        return min(current_ks, NEUTRAL_KS)
    bump = 0.03 if "агрессив" in grade else 0.02 if "обычн" in grade else 0.01
    return current_ks + bump


def terminal_inflation_from_ks(terminal_ks: float, spread: float = REAL_SPREAD) -> float:
    """Терминальная инфляция = терминальная КС − целевой реальный спред (≥0)."""
    return max(0.0, terminal_ks - spread)
