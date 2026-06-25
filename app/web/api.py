"""REST API сервиса (SPEC §6). Все расчёты — на лету из ядра."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import DISCLAIMER
from app.core import engine, barbell, growth, sotp, leverage, body_trend, backtest
from app.core import valuation, inflation, portfolio as pf
from app.data.db import get_db, get_settings, get_macro, upsert
from app.data.seed import refresh_market, refresh_fundamentals, refresh_macro

router = APIRouter(prefix="/api")


@router.get("/issuers")
def list_issuers():
    with get_db() as db:
        rows = engine.screen_all(db)
        summary = engine.screen_summary(db, rows)
    return {"disclaimer": DISCLAIMER, "count": len(rows), "issuers": rows, "summary": summary}


@router.get("/bonds")
def list_bonds():
    """Скринер облигаций (мультиассет фаза 2): ОФЗ + корпораты с MOEX ISS, троичный сигнал."""
    with get_db() as db:
        return engine.screen_bonds(db)


@router.get("/fx")
def list_fx():
    """Валютная секция: замещайки/юаневые бонды, E[отдача,₽] = FX-YTM + E[курс] − carry."""
    with get_db() as db:
        return engine.screen_fx(db)


@router.get("/compare")
def compare_classes():
    """ЕДИНЫЙ экран сравнения классов (v6 / red-team #7): акции + облигации + замещайки на ОДНОЙ
    линейке — годовая РЕАЛЬНАЯ доходность (над дефлятором, с учётом шока) + общий троичный сигнал."""
    from app.core import macro_outlook as mo
    with get_db() as db:
        s = get_settings(db)
        n = s.get("forecast_years") or engine.FORECAST_YEARS
        outlook = mo.build_outlook(db, n)
        defl = outlook.e_inflation(n)
        items = []
        for x in engine.screen_all(db):                       # АКЦИИ (real_return = шок-скорр., посленалогово)
            if x.get("real_return") is None:
                continue
            note = (x.get("quality_label") or "")
            if x.get("group_ab"):
                note += f" · гр.{x['group_ab']}"
            if (x.get("tail_risk") or {}).get("gate"):
                note += " · ⚠обнул.риск"
            items.append({"name": x["name"], "secid": x["secid"], "klass": "Акция",
                          "real": x["real_return"], "signal": x["signal"], "note": note.strip(" ·")})
        for b in engine.screen_bonds(db).get("bonds", []):    # ОБЛИГАЦИИ (shock_adj_yield = реал−риск−шок)
            if b.get("shock_adj_yield") is None:
                continue
            note = f"{b['type']}·{b['coupon_type']}"
            if b.get("pd"):
                note += f" · PD {b['pd']*100:.0f}%"
            items.append({"name": b["name"], "secid": b["secid"], "klass": "Облигация",
                          "real": b["shock_adj_yield"], "signal": b["signal"], "note": note})
        for f in engine.screen_fx(db).get("bonds", []):       # ЗАМЕЩАЙКИ (FX-YTM + E[курс] − дефлятор)
            real = (1.0 + f.get("ytm_fx", 0.0) + f.get("e_fx_move", 0.0)) / (1.0 + defl) - 1.0
            items.append({"name": f["name"], "secid": f["secid"], "klass": "Замещайка",
                          "real": round(real, 4), "signal": f["signal"], "note": f.get("faceunit", "FX")})
        items.sort(key=lambda z: -z["real"])
    return {"items": items, "deflator": round(defl, 4), "hurdle": s["risk_premium"],
            "horizon": n, "p_shock_cum": round(outlook.cumulative_shock_p(n), 4),
            "buy": sum(1 for z in items if z["signal"] == "ПОКУПАЙ"), "count": len(items),
            "disclaimer": DISCLAIMER}


@router.get("/outlook")
def macro_outlook():
    """Верхний слой: макро-прогноз на горизонт = инфляция (база) + риск шока (вектор) + окно рывка."""
    from app.core import macro_outlook as mo
    from app.core import breakthrough as bt
    from app.core import fiscal
    from app.data.db import get_macro
    from datetime import date
    with get_db() as db:
        _o = mo.build_outlook(db)
        out = _o.as_dict()
        h = get_settings(db).get("forecast_years") or 1
        m = get_macro(db)
    # felt-коридор (§6): дефлятор ± по неопределённости клина [1.6..2.4 vs центр 2.0]. После бенч=ОФЗ
    # СИГНАЛ дефлятор-независим (инфл сокращается) — коридор влияет лишь на абсолютный реал%, не на вердикт.
    _defl = _o.e_inflation(h)
    out["deflator"] = round(_defl, 4)
    out["deflator_corridor"] = [round(_defl * mo.ROSSTAT_RATIO_LO / mo.ROSSTAT_RATIO, 4),
                                round(_defl * mo.ROSSTAT_RATIO_HI / mo.ROSSTAT_RATIO, 4)]
    yr = date.today().year
    out["breakthrough"] = bt.breakthrough_window(yr, h)   # Гл.14: фронтирный рывок, окно К КОНЦУ горизонта
    out["renovation"] = bt.renovation_window(yr, h)       # Гл.15-17: Реновация Триады Жильё-ЖКХ-Электро
    _fd = fiscal.fiscal_drain(deficit_trln=m.get("fiscal_deficit_trln") or 7.5,
                              plan_trln=m.get("fiscal_plan_trln") or 3.786, gdp_trln=m.get("gdp_trln") or 200.0)
    out["fiscal_drain"] = {"drain_pp": _fd.drain_pp, "intensity": _fd.intensity, "level": _fd.level,
                           "deficit_pct_gdp": _fd.deficit_pct_gdp, "overshoot": _fd.overshoot, "note": _fd.note}
    return out


@router.get("/build_portfolio")
def build_portfolio(horizon: int = 5, aggressiveness: str = "Сбалансированный",
                    inflation: float = 0.08, target: float = 0.05):
    """Блок «Что купить»: портфель купил-держи под горизонт/агрессивность/инфляцию/таргет + риски."""
    from app.core import portfolio_builder as pb
    cap = pb.AGGRESSIVENESS.get(aggressiveness, 0.50)
    with get_db() as db:
        res = pb.build(db, horizon=horizon, equity_cap=cap, exp_inflation=inflation, target_real=target)
    res["aggressiveness"] = aggressiveness
    res["aggressiveness_options"] = list(pb.AGGRESSIVENESS.keys())
    return res


@router.get("/scenario")
def scenario():
    """Сценарий buy-and-hold: реальная доходность за 3/5/10/20 лет с учётом инфляции и шока."""
    with get_db() as db:
        return engine.scenario_table(db)


class RiskInputs(BaseModel):
    """Ручной контроль движка шока: EWI, индекс интеграции, веса типологии."""
    ewi: dict | None = None
    integration: dict | None = None
    shock_weights: dict | None = None


@router.put("/risk_inputs")
def update_risk_inputs(body: RiskInputs):
    """Записать EWI/интеграцию/веса типологии (иначе движок на интерим-дефолтах)."""
    import json
    patch = {}
    if body.ewi is not None:
        patch["ewi_json"] = json.dumps(body.ewi, ensure_ascii=False)
    if body.integration is not None:
        patch["integration_json"] = json.dumps(body.integration, ensure_ascii=False)
    if body.shock_weights is not None:
        patch["shock_weights_json"] = json.dumps(body.shock_weights, ensure_ascii=False)
    if not patch:
        raise HTTPException(400, "Нет полей")
    with get_db() as db:
        cols = ", ".join(f"{k} = ?" for k in patch)
        db.execute(f"UPDATE user_settings SET {cols} WHERE id = 1", tuple(patch.values()))
    from app.core import macro_outlook as mo
    with get_db() as db:
        return mo.build_outlook(db).as_dict()


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
    felt_inflation: float | None = None
    inflation_terminal: float | None = None
    forecast_years: int | None = None
    tax_rate: float | None = None
    tax_aware: int | None = None
    iis3: int | None = None
    normal_pe: float | None = None
    key_rate_override: float | None = None
    inflation_terminal_override: float | None = None


@router.get("/settings")
def read_settings():
    from app.data.db import effective_key_rate, get_macro
    with get_db() as db:
        s = get_settings(db)
        s["deflator_active"] = engine.active_deflator_value(s, db)
        s["key_rate_eff"] = effective_key_rate(db)             # действующая (override или ЦБ SOAP)
        s["key_rate_fetched"] = get_macro(db).get("key_rate")  # из ЦБ SOAP (для подсказки)
        s["terminal_inflation_eff"] = engine.terminal_inflation(s, db)  # действующий терминал (override/траектория)
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
    monetization_proven: int = 0
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


class TailRiskIn(BaseModel):
    """Обнуляющие РФ-риски (0 нет / 1 повышенный / 2 острый)."""
    minority_risk: int = 0
    expropriation_risk: int = 0
    delisting_risk: int = 0
    sanctions_risk: int = 0
    liquidity_risk: int = 0


@router.put("/issuers/{secid}/tail_risk")
def update_tail_risk(secid: str, body: TailRiskIn):
    """Отдельный апдейт обнуляющих рисков (не клобберит структурные баллы)."""
    with get_db() as db:
        exists = db.execute("SELECT 1 FROM issuers WHERE secid = ?", (secid.upper(),)).fetchone()
        if not exists:
            raise HTTPException(404, f"Эмитент {secid} не найден")
        data = body.model_dump()
        data.update(secid=secid.upper())
        upsert(db, "structural", data, pk="secid")
        res = engine.evaluate_issuer(db, secid)
    return res


class FormIn(BaseModel):
    """v6 §0.3/0.4 + книга Гл.7: порода + ценопрессинг (3-й канал) + Долг/EBITDA (профиль предперехвата). Суждение."""
    breed: str | None = None       # privatization|state|oligarch|venture|debt|None
    pricing_pressure: int = 0      # 0 нет / 1 повышенный / 2 острый
    nd_ebitda: float | None = None # Долг/EBITDA — частная порода × высокий долг → предперехват
    renovation_node: int = 0       # 1 = поставщик узла реновации Триады (книга Гл.16): кабель/трубы/металл/цемент


@router.put("/issuers/{secid}/form")
def update_form(secid: str, body: FormIn):
    """Апдейт породы + ценопрессинга (не клобберит структурные баллы / tail_risk)."""
    with get_db() as db:
        exists = db.execute("SELECT 1 FROM issuers WHERE secid = ?", (secid.upper(),)).fetchone()
        if not exists:
            raise HTTPException(404, f"Эмитент {secid} не найден")
        data = body.model_dump()
        data.update(secid=secid.upper())
        upsert(db, "structural", data, pk="secid")
        res = engine.evaluate_issuer(db, secid)
    return res


@router.post("/issuers/{secid}/llm_draft")
def gen_llm_draft(secid: str):
    """Сгенерировать LLM-черновик структурных баллов (Opus). Нужен .anthropic_key."""
    from app.core import llm_judge
    with get_db() as db:
        return llm_judge.draft_structural(db, secid)


@router.get("/issuers/{secid}/llm_draft")
def read_llm_draft(secid: str):
    from app.core import llm_judge
    with get_db() as db:
        d = llm_judge.get_draft(db, secid)
    return d or {"draft": None}


@router.post("/issuers/{secid}/apply_draft")
def apply_llm_draft(secid: str):
    """Применить LLM-черновик к активным баллам (подтверждение человеком)."""
    from app.core import llm_judge
    with get_db() as db:
        return llm_judge.apply_draft(db, secid)


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
    try:
        from app.data.minfin import current_regime
        regime = current_regime().get("regime", "NORMAL")
    except Exception:  # noqa: BLE001
        regime = "NORMAL"
    breaches = pf.check_limits(weights, sectors, regime=regime, loadings=loadings)
    return {
        "weights": weights,
        "sectors": sectors,
        "loadings": loadings,
        "concentration": decomp.concentration,
        "dominant_factor": decomp.dominant_factor,
        "factor_flags": decomp.flags,
        "sector_flags": sector_flags,
        "stress": [asdict(s) for s in stress],
        "regime": regime,
        "limit_breaches": [asdict(b) for b in breaches],
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


@router.post("/jobs/{name}")
def run_job(name: str):
    """Ручной запуск задачи планировщика (для проверки/триггера).
    name: quotes | macro | fundamentals | markers.
    """
    from app.data import refresh
    jobs = {
        "quotes": refresh.job_refresh_quotes,
        "macro": refresh.job_refresh_macro,
        "fundamentals": refresh.job_refresh_fundamentals,
        "snapshot": refresh.job_snapshot_history,
        "markers": refresh.job_recompute_markers,
        "macro_analysis": refresh.job_macro_analysis,
    }
    if name not in jobs:
        raise HTTPException(404, f"Неизвестная задача '{name}'. Доступны: {list(jobs)}")
    return jobs[name]()


# ── режим рынка (ФНБ + бюджетное правило + просадка IMOEX) ────────────────────
class NwfIn(BaseModel):
    nwf_liquid_pct: float | None = None
    nwf_months_to_zero: float | None = None
    urals: float | None = None
    oil_cutoff: float | None = None


@router.get("/regime")
def get_regime():
    from app.data.minfin import current_regime
    from app.core import llm_macro
    r = current_regime()
    with get_db() as db:
        r["analysis"] = llm_macro.get_analysis(db)
        r["context"] = llm_macro.get_context(db)
        r["shock"] = llm_macro.get_shock(db)
        r["rate_trajectory"] = llm_macro.get_rate_trajectory(db)
        r["rate_signal"] = llm_macro.get_rate_signal(db)
    return r


@router.post("/regime/analyze")
def regime_analyze():
    """Прогнать Opus-разбор макро-режима (advisory). Нужен .anthropic_key."""
    from app.core import llm_macro
    with get_db() as db:
        return llm_macro.analyze_macro(db)


@router.post("/regime/shock_assess")
def regime_shock_assess():
    """Оценить форвардную вероятность ШОКА по сценариям (Opus, субъективно)."""
    from app.core import llm_macro
    with get_db() as db:
        return llm_macro.assess_shock(db)


@router.post("/regime/rate_trajectory")
def regime_rate_trajectory():
    """Градация траектории КС: Opus по пейсу решений ЦБ + риторике (fallback — пейс)."""
    from app.core import llm_macro
    with get_db() as db:
        return llm_macro.assess_rate_trajectory(db)


class RateSignalIn(BaseModel):
    text: str


@router.put("/regime/rate_signal")
def put_rate_signal(body: RateSignalIn):
    """Ручной ввод риторики ЦБ (override авто-фетча keypr). Пусто → снова авто."""
    from app.core import llm_macro
    with get_db() as db:
        return llm_macro.set_rate_signal(db, body.text)


class UralsPointIn(BaseModel):
    month: str   # YYYY-MM
    urals: float


@router.put("/regime/urals_point")
def put_urals_point(body: UralsPointIn):
    """Помесячная точка Urals для сглаживания режима (#9): MA фильтрует overshoot."""
    from app.data.minfin import add_urals_point
    return add_urals_point(body.month, body.urals)


# ── причинный граф (§10): query-only, в живой сигнал НЕ входит ──
@router.get("/causal")
def causal_nodes():
    from app.core import causal_graph
    return {"nodes": causal_graph.nodes(),
            "note": "Прогон узла: GET /api/causal/{node}. Класс B, query-only (§10)."}


@router.get("/causal/{node}")
def causal_node(node: str):
    from app.core import causal_graph
    return causal_graph.run_node(node)


class MacroContextIn(BaseModel):
    context_md: str
    source: str | None = None


@router.put("/macro/context")
def put_macro_context(body: MacroContextIn):
    """Обновить курируемый макро-брифинг (факты для анализа Опусом)."""
    from app.core import llm_macro
    with get_db() as db:
        return llm_macro.set_context(db, body.context_md, body.source or "")


@router.get("/events")
def list_events(limit: int = 50):
    """Последние события (смена сигнала/маркера/режима)."""
    with get_db() as db:
        rows = db.execute(
            "SELECT ts, kind, secid, message, notified FROM events "
            "ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return {"events": [dict(r) for r in rows]}


@router.post("/telegram/test")
def telegram_test():
    """Проверка Telegram-уведомлений (шлёт тестовое сообщение)."""
    from app.data import telegram
    if not telegram.enabled():
        return {"ok": False, "error": "токен не задан (.telegram_token)"}
    ok = telegram.send_message("✅ Тест: уведомления оценки акций MOEX подключены.")
    return {"ok": ok, "chat_id": telegram.get_chat_id()}


@router.put("/macro/nwf")
def put_nwf(body: NwfIn):
    from app.data.minfin import update_nwf
    return update_nwf(**body.model_dump())


# ── фискальный пылесос (§2): ручной ввод Минфина → fiscal_drain (дисконт акций) ──
class FiscalIn(BaseModel):
    fiscal_deficit_trln: float | None = None   # дефицит-прогноз/run-rate, трлн ₽/год
    fiscal_plan_trln: float | None = None       # плановый дефицит года, трлн ₽
    gdp_trln: float | None = None               # номинальный ВВП, трлн ₽


def _fiscal_state(m: dict) -> dict:
    from app.core import fiscal as fmod
    fd = fmod.fiscal_drain(deficit_trln=m.get("fiscal_deficit_trln") or 7.5,
                           plan_trln=m.get("fiscal_plan_trln") or 3.786,
                           gdp_trln=m.get("gdp_trln") or 200.0)
    return {"fiscal_deficit_trln": m.get("fiscal_deficit_trln"), "fiscal_plan_trln": m.get("fiscal_plan_trln"),
            "gdp_trln": m.get("gdp_trln"), "drain_pp": fd.drain_pp, "intensity": fd.intensity,
            "level": fd.level, "deficit_pct_gdp": fd.deficit_pct_gdp, "note": fd.note}


@router.get("/macro/fiscal")
def get_fiscal():
    with get_db() as db:
        return _fiscal_state(get_macro(db))


@router.put("/macro/fiscal")
def put_fiscal(body: FiscalIn):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    with get_db() as db:
        if patch:
            cols = ", ".join(f"{k} = ?" for k in patch)
            db.execute(f"UPDATE macro SET {cols} WHERE id = 1", tuple(patch.values()))
        return _fiscal_state(get_macro(db))


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
