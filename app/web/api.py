"""REST API сервиса (SPEC §6). Все расчёты — на лету из ядра."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import DISCLAIMER
from app.core import engine, barbell, growth, sotp, leverage, body_trend, backtest
from app.core import valuation, inflation, portfolio as pf
from app.data.db import get_db, get_settings, upsert
from app.data.seed import refresh_market, refresh_fundamentals, refresh_macro

router = APIRouter(prefix="/api")


@router.get("/issuers")
def list_issuers():
    with get_db() as db:
        rows = engine.screen_all(db)
    return {"disclaimer": DISCLAIMER, "count": len(rows), "issuers": rows}


@router.get("/issuers/{secid}")
def get_issuer(secid: str):
    with get_db() as db:
        res = engine.evaluate_issuer(db, secid)
    if res is None:
        raise HTTPException(404, f"Эмитент {secid} не найден")
    res["disclaimer"] = DISCLAIMER
    return res


# ── настройки ────────────────────────────────────────────────────────────────
class Settings(BaseModel):
    hurdle: float | None = None
    buffer: float | None = None
    regime: str | None = None
    risk_premium: float | None = None
    deflator_preset: str | None = None
    rosstat_current: float | None = None
    rosstat_smoothed: float | None = None
    forecast_years: int | None = None


@router.get("/settings")
def read_settings():
    with get_db() as db:
        s = get_settings(db)
        deflator, d = engine.active_deflator_value(s)
    s["deflator_active"] = deflator
    s["deflator_tactical"] = d.tactical
    s["deflator_strategic"] = d.strategic
    s["personal_inflation"] = d.personal
    s["basket_premium"] = d.basket_premium
    return s


@router.put("/settings")
def update_settings(body: Settings):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if not patch:
        raise HTTPException(400, "Нет полей для обновления")
    with get_db() as db:
        cols = ", ".join(f"{k} = ?" for k in patch)
        db.execute(f"UPDATE user_settings SET {cols} WHERE id = 1", tuple(patch.values()))
        s = get_settings(db)
    return s


# ── структурные баллы (админка) ──────────────────────────────────────────────
class StructuralIn(BaseModel):
    moat: int = 0
    disruption: int = 0
    tam: int = 0
    regulation: int = 0
    demo: int = 0
    gosnaves: int = 0
    note: str | None = None


@router.put("/issuers/{secid}/structural")
def update_structural(secid: str, body: StructuralIn):
    with get_db() as db:
        exists = db.execute("SELECT 1 FROM issuers WHERE secid = ?", (secid.upper(),)).fetchone()
        if not exists:
            raise HTTPException(404, f"Эмитент {secid} не найден")
        data = body.model_dump()
        data.update(secid=secid.upper(), updated_by="user",
                    updated_at=datetime.now().isoformat(timespec="seconds"))
        upsert(db, "structural", data, pk="secid")
        res = engine.evaluate_issuer(db, secid)
    return res


# ── портфель ─────────────────────────────────────────────────────────────────
class PortfolioIn(BaseModel):
    weights: dict[str, float]  # {secid: вес}


@router.get("/portfolio")
def get_portfolio():
    with get_db() as db:
        rows = db.execute("SELECT secid, weight FROM portfolio").fetchall()
        weights = {r["secid"]: r["weight"] for r in rows}
        if not weights:
            return {"weights": {}, "note": "Портфель пуст. POST /api/portfolio с весами."}
        sectors = {}
        for secid in weights:
            row = db.execute("SELECT sector FROM issuers WHERE secid = ?", (secid,)).fetchone()
            sectors[secid] = row["sector"] if row else "—"
    loadings = pf.loadings_by_sector(sectors)
    decomp = pf.factor_decomposition(loadings, weights=weights)
    stress = pf.stress_test(decomp)
    sector_flags = pf.sector_concentration(sectors, weights=weights)
    return {
        "weights": weights,
        "sectors": sectors,
        "loadings": loadings,
        "concentration": decomp.concentration,
        "dominant_factor": decomp.dominant_factor,
        "factor_flags": decomp.flags,
        "sector_flags": sector_flags,
        "stress": [asdict(s) for s in stress],
        "disclaimer": DISCLAIMER,
    }


@router.post("/portfolio")
def set_portfolio(body: PortfolioIn):
    with get_db() as db:
        db.execute("DELETE FROM portfolio")
        for secid, w in body.weights.items():
            db.execute("INSERT INTO portfolio (secid, weight) VALUES (?, ?)",
                       (secid.upper(), w))
    return get_portfolio()


# ── обновление данных из MOEX ────────────────────────────────────────────────
@router.post("/refresh")
def refresh():
    return refresh_market()


@router.post("/refresh_fundamentals")
def refresh_funds():
    """Обновить фундаментал уровня 2 из T-Invest API (нужен TINVEST_TOKEN)."""
    return refresh_fundamentals()


@router.post("/refresh_macro")
def refresh_macro_ep():
    """Обновить макро из ЦБ: ключевая ставка (надёжно) + инфляция (best-effort)."""
    return refresh_macro()


# ── backtest на истории MOEX ─────────────────────────────────────────────────
@router.get("/backtest")
def backtest_history(years: str = "1,2,3"):
    from app.data.moex import MoexClient
    horizons = tuple(int(y) for y in years.split(",") if y.strip().isdigit())
    client = MoexClient()
    try:
        with get_db() as db:
            return engine.generate_backtest(db, client, horizons or (1, 2, 3))
    finally:
        client.close()


# ── калькуляторы (POST /api/calc/*) ──────────────────────────────────────────
@router.post("/calc/barbell")
def calc_barbell(body: dict):
    return asdict(barbell.barbell(**body))


@router.post("/calc/maturity")
def calc_maturity(body: dict):
    try:
        return asdict(valuation.mature_valuation(**body))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/calc/growth_calibrated")
def calc_growth_cal(body: dict):
    return asdict(growth.growth_calibrated(**body))


@router.post("/calc/growth_projection")
def calc_growth_proj(body: dict):
    return asdict(growth.growth_projection(**body))


@router.post("/calc/sotp")
def calc_sotp(body: dict):
    return asdict(sotp.ozon_sotp(**body))


@router.post("/calc/leverage")
def calc_leverage(body: dict):
    return asdict(leverage.leverage_quality(**body))


@router.post("/calc/body_trend")
def calc_body_trend(body: dict):
    return asdict(body_trend.body_trend(**body))


@router.post("/calc/backtest")
def calc_backtest(body: dict):
    cases = [tuple(c) for c in body.get("cases", [])]
    return asdict(backtest.run_backtest(cases))


@router.post("/calc/inflation")
def calc_inflation(body: dict):
    basket = [inflation.Category(**c) for c in body["basket"]] if body.get("basket") else None
    d = inflation.compute_deflator(
        basket=basket,
        rosstat_current=body.get("rosstat_current", 0.118),
        rosstat_smoothed=body.get("rosstat_smoothed", 0.07),
    )
    return asdict(d)
