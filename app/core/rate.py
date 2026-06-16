"""Расчёт требуемой доходности r (лист Excel «Ставка r»).

r = ожидаемый безриск (взвешенная траектория КС) + премия за риск
    + надбавка за риск актива.
"""
from __future__ import annotations

from dataclasses import dataclass


def weighted_riskfree(scenarios: list[tuple[float, float]]) -> float:
    """Ожидаемый безриск = Σ(безриск × вес) / Σ(вес).

    scenarios: [(безриск, вес), ...] — траектория КС с вероятностями.
    """
    total_w = sum(w for _, w in scenarios)
    if total_w == 0:
        raise ValueError("Сумма весов сценариев = 0")
    return sum(rate * w for rate, w in scenarios) / total_w


def build_r(riskfree: float, risk_premium: float, asset_premium: float = 0.0) -> float:
    """r = безриск + премия за риск эквити + надбавка за риск актива."""
    return riskfree + risk_premium + asset_premium


# Дефолтная траектория КС (лист «Ставка r»): мягкий/базовый/жёсткий
DEFAULT_RATE_PATH = [
    (0.09, 0.35),  # мягкий: КС → 8-9 долгосрочно
    (0.11, 0.45),  # базовый: КС → 11-12
    (0.14, 0.20),  # жёсткий: разворот вверх
]


@dataclass
class RateBuild:
    riskfree: float
    risk_premium: float
    asset_premium: float
    r: float


def default_r(
    *,
    risk_premium: float = 0.10,
    asset_premium: float = 0.0,
    rate_path: list[tuple[float, float]] | None = None,
) -> RateBuild:
    rf = weighted_riskfree(rate_path or DEFAULT_RATE_PATH)
    r = build_r(rf, risk_premium, asset_premium)
    return RateBuild(
        riskfree=rf, risk_premium=risk_premium,
        asset_premium=asset_premium, r=r,
    )
