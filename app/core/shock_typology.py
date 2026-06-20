"""Типология шока — 5 типов вместо одного усреднённого вектора (REVIEW C3/C5, 20.06.2026).

Прежний единый вектор усреднён по 2014/2022 (оба V-образные) → зашит recovery ~55%, СЛЕП к
затяжному L-кризису. Здесь шок развёрнут в ТИПЫ, каждый со своим вектором + предиктором.
ПРИРОДА шока = взвешенная СМЕСЬ типов (веса от предикторов/Opus), не одна клякса. Это убирает
V-bias и держит L-тип ЯВНО. Ожидаемый вектор = Σ вес·вектор_типа.

Калибровка типов — РФ-история (1998/2008/2014/2022) + L как структурный сценарий без прецедента.
"""
from __future__ import annotations

# Каждый тип: УСЛОВНЫЙ вектор «если шок этого типа». equity_dd<0 просадка IMOEX; recovery доля за год;
# fx девальвация (+ослабление); ks/infl всплеск (доля). Секторальные — общий профиль (экспортёр мягче).
SHOCK_TYPES = {
    "geo": {        # геополитический (2014/2022): деваль сильная, экспортёры защищены, V-отскок
        "label": "Геополитический", "equity_dd": -0.40, "recovery_1y": 0.55,
        "fx_pct": 0.45, "ks_pp": 0.09, "infl_pp": 0.10,
        "predictor": "качественный сенсор геонапряжения (НЕ количественный)"},
    "commodity": {  # сырьевой (обвал нефти): бьёт бюджет+экспортёров+рубль, IMOEX мягче (автостабилизатор)
        "label": "Сырьевой", "equity_dd": -0.22, "recovery_1y": 0.60,
        "fx_pct": 0.35, "ks_pp": 0.05, "infl_pp": 0.07,
        "predictor": "нефть vs бюджетное правило, спрос"},
    "global": {     # глобальный risk-off: для пост-2022 РФ через сырьевой канал (нефть↓), не портфельный
        "label": "Глобальный risk-off", "equity_dd": -0.33, "recovery_1y": 0.62,
        "fx_pct": 0.30, "ks_pp": 0.04, "infl_pp": 0.05,
        "predictor": "мировые кредитные циклы/оценки (S&P перегрев → через нефть)"},
    "financial": {  # внутренний банковско-долговой (РФ не знала в чистом виде; ВДО-пузырь готовит)
        "label": "Внутренний финансовый", "equity_dd": -0.45, "recovery_1y": 0.45,
        "fx_pct": 0.25, "ks_pp": 0.10, "infl_pp": 0.08,
        "predictor": "credit gap, дефолтная волна, refinancing wall"},
    "lstag": {      # L-образный стагфляционный: структурный упадок БЕЗ отскока. Опаснее всего на горизонте
        "label": "L-стагфляционный", "equity_dd": -0.40, "recovery_1y": 0.10,
        "fx_pct": 0.50, "ks_pp": 0.12, "infl_pp": 0.14,
        "predictor": "нет прецедента → не в калибровке (держать явно)"},
}

# Дефолтные веса природы (Σ=1): геополитика доминирует РФ-историю; L держим заметным весом.
DEFAULT_WEIGHTS = {"geo": 0.35, "commodity": 0.20, "global": 0.20, "financial": 0.15, "lstag": 0.10}

VECTOR_KEYS = ("equity_dd", "recovery_1y", "fx_pct", "ks_pp", "infl_pp")


def normalize_weights(weights: dict | None) -> dict:
    w = {k: max(0.0, float((weights or {}).get(k, DEFAULT_WEIGHTS[k]))) for k in SHOCK_TYPES}
    s = sum(w.values()) or 1.0
    return {k: v / s for k, v in w.items()}


def blend(weights: dict | None = None) -> dict:
    """Ожидаемый шок-вектор = взвешенная смесь типов. Возвращает {equity_dd, recovery_1y, fx_pct,
    ks_pp, infl_pp, weights, dominant}."""
    w = normalize_weights(weights)
    out = {k: round(sum(w[t] * SHOCK_TYPES[t][k] for t in SHOCK_TYPES), 4) for k in VECTOR_KEYS}
    out["weights"] = {t: round(w[t], 3) for t in w}
    out["dominant"] = max(w, key=w.get)
    return out


def types_table() -> list[dict]:
    """Для дашборда: список типов с метками, векторами, предикторами."""
    return [{"key": t, **SHOCK_TYPES[t]} for t in SHOCK_TYPES]
