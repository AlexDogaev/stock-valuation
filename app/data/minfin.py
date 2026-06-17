"""ФНБ / бюджетное правило: сборка входов и текущего режима рынка.

ФНБ-показатели (ликвидная часть % ВВП, месяцы до исчерпания, Urals, цена
отсечения) — ручной ввод в таблицу macro (позже можно парсить Минфин).
Просадка рынка — автоматически из истории индекса IMOEX (MOEX).
"""
from __future__ import annotations

from app.core.nwf_regime import nwf_regime, NwfRegime
from app.data.db import get_db, get_macro
from app.data.moex import MoexClient


def current_regime() -> dict:
    """Собрать входы и вернуть текущий режим рынка (ФНБ + просадка IMOEX)."""
    with get_db() as db:
        m = get_macro(db)
    drawdown = None
    client = MoexClient()
    try:
        drawdown = client.index_drawdown("IMOEX")
    except Exception:  # noqa: BLE001 — режим не должен падать из-за сети
        drawdown = None
    finally:
        client.close()

    r: NwfRegime = nwf_regime(
        liquid_nwf_pct=m.get("nwf_liquid_pct") or 2.0,
        months_to_zero=m.get("nwf_months_to_zero") or 24,
        urals=m.get("urals") or 60,
        cutoff=m.get("oil_cutoff") or 60,
        market_drawdown=drawdown if drawdown is not None else 0.0,
    )
    from app.core.barbell import regime_allocation
    from dataclasses import asdict
    alloc = regime_allocation(regime=r.regime, defense_share=r.defense,
                              attack_share=r.attack, deval_pressure=r.deval_pressure)
    return {
        "regime": r.regime, "defense": r.defense, "attack": r.attack,
        "budget_sign": round(r.budget_sign, 2), "note": r.note,
        "deval_score": r.deval_score, "deval_pressure": r.deval_pressure,
        "allocation": asdict(alloc),
        "inputs": {
            "nwf_liquid_pct": m.get("nwf_liquid_pct"),
            "nwf_months_to_zero": m.get("nwf_months_to_zero"),
            "urals": m.get("urals"), "oil_cutoff": m.get("oil_cutoff"),
            "market_drawdown": round(drawdown, 3) if drawdown is not None else None,
        },
    }


def update_nwf(*, nwf_liquid_pct: float | None = None,
               nwf_months_to_zero: float | None = None,
               urals: float | None = None, oil_cutoff: float | None = None) -> dict:
    """Ручное обновление ФНБ-показателей в macro (через настройки)."""
    patch = {k: v for k, v in dict(
        nwf_liquid_pct=nwf_liquid_pct, nwf_months_to_zero=nwf_months_to_zero,
        urals=urals, oil_cutoff=oil_cutoff).items() if v is not None}
    if not patch:
        return get_macro_nwf()
    with get_db() as db:
        cols = ", ".join(f"{k} = ?" for k in patch)
        db.execute(f"UPDATE macro SET {cols} WHERE id = 1", tuple(patch.values()))
    return get_macro_nwf()


def get_macro_nwf() -> dict:
    with get_db() as db:
        m = get_macro(db)
    return {k: m.get(k) for k in
            ("nwf_liquid_pct", "nwf_months_to_zero", "urals", "oil_cutoff")}
