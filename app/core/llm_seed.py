"""Opus-сид фундаментала + структуры для НОВЫХ эмитентов (класс B, needs_review).

Для имён без выверенного Excel (расширение вселенной): Opus ОЦЕНИВАЕТ уровень-2
(ROE/рост/сжатие/ROIC/WACC/payout/тип) + структурные баллы по знаниям до янв-2026.
Всё пишется как ОЦЕНКА с needs_review=1 и source='llm-seed' — НЕ выдаётся за факт,
человек уточняет важные имена. Рыночные данные (цена/капа/дивы) — отдельно из MOEX.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime

from app.data import llm
from app.data.db import upsert

SYSTEM_SEED = """Ты — аналитик акций MOEX. Для эмитента дай ЧЕСТНУЮ ОЦЕНКУ ключевых
параметров модели справедливой стоимости (по знаниям до января 2026; это оценки, не факт).
Доли — десятичные (20% = 0.20). Поля:
- roe: рентабельность собственного капитала (доля); для убыточных — 0 или отрицательная.
- payout: доля чистой прибыли на дивиденды (0, если не платит).
- g_base: устойчивый базовый рост тела/прибыли (доля), КОНСЕРВАТИВНО.
- compression: множитель сжатия мультипликатора (зрелый ≈1.0; дорогой растущий 0.85-0.95; дешёвый >1.0).
- revenue_growth: рост выручки (доля).
- roic: отдача на инвестированный капитал (доля); для банков ≈ roe.
- wacc: стоимость капитала (доля); сейчас в РФ высокая (~0.18-0.22 при КС 14.5%).
- proven_roic_years: сколько лет подряд ROIC≥WACC (целое 0-10, консервативно).
- is_resource (0/1): сырьевой/ресурсный. is_rentier (0/1): рентный (рента изымается налогом/пошлиной).
- etype: один из "растущий"|"зрелый"|"ресурсный"|"циклический".
- body_trend: -1 (тело сжимается)|0|1 (растёт).
- Структурные баллы (−2 угроза … +2 попутно): moat, disruption, tam, regulation, demo, gosnaves.
- monetization_proven (0/1): доказан ли путь монетизации.
- rationale: 2-3 фразы по-русски.
Верни СТРОГО JSON со ВСЕМИ полями, без обрамления."""

FIN_FIELDS = ("roe", "payout", "g_base", "compression", "revenue_growth", "roic", "wacc")
STRUCT_FIELDS = ("moat", "disruption", "tam", "regulation", "demo", "gosnaves")


def _user(secid: str, name: str, sector: str, market: dict | None) -> str:
    m = market or {}
    md = ""
    if m.get("price") is not None:
        md = (f"Рыночные данные MOEX: цена {m.get('price')} ₽, "
              f"капитализация {round((m.get('cap') or 0)/1e9)} млрд ₽, "
              f"дивдоходность TTM {round((m.get('div_yield') or 0)*100,1)}%.")
    return (f"Эмитент: {name} ({secid}), сектор: {sector}.\n{md}\n"
            f"Дай оценку всех параметров строго в JSON.")


def seed_fundamentals(db: sqlite3.Connection, secid: str) -> dict:
    """Opus-оценка фундаментала + структуры для эмитента; запись с needs_review=1."""
    if not llm.enabled():
        return {"error": "LLM не настроен (нет .anthropic_key)"}
    row = db.execute(
        "SELECT i.secid, i.shortname, i.sector, m.price, m.cap, m.div_yield "
        "FROM issuers i LEFT JOIN market_data m ON m.secid=i.secid WHERE i.secid=?",
        (secid.upper(),)).fetchone()
    if not row:
        return {"error": f"эмитент {secid} не найден (сначала добавь в issuers)"}
    r = dict(row)
    data, err = llm.call_json(
        SYSTEM_SEED, _user(r["secid"], r["shortname"] or secid, r["sector"] or "—", r),
        max_tokens=1400)
    if err:
        return {"error": err}

    now = datetime.now().isoformat(timespec="seconds")
    fin = {k: _f(data.get(k)) for k in FIN_FIELDS}
    upsert(db, "financials", dict(
        secid=r["secid"], period="2025",
        net_profit=None, equity=None, **fin,
        body_trend=_i(data.get("body_trend")),
        is_resource=_i(data.get("is_resource")), is_rentier=_i(data.get("is_rentier")),
        etype=str(data.get("etype", ""))[:20] or None,
        source="llm-seed (оценка Opus)", updated_at=now,
        proven_roic_years=_i(data.get("proven_roic_years")), needs_review=1,
    ), pk="secid")
    rationale = str(data.get("rationale", ""))[:400]
    upsert(db, "structural", dict(
        secid=r["secid"], **{k: _i(data.get(k)) for k in STRUCT_FIELDS},
        monetization_proven=_i(data.get("monetization_proven")), mult_seed=1.0,
        note=f"LLM-seed (оценка, требует проверки): {rationale}",
        updated_by="llm-seed", updated_at=now,
    ), pk="secid")
    return {"secid": r["secid"], "fin": fin, "rationale": rationale}


SYSTEM_REGROUND = """Ты — аналитик акций MOEX. Тебе ДАНЫ свежие ФАКТЫ (ROE, payout,
дивдоходность из отчётности/рынка) — НЕ переоценивай их. Оцени только СУЖДЁННЫЕ параметры,
СОГЛАСОВАННЫЕ с этими фактами и текущим макро-РФ (КС 14.5%, стоимость капитала высокая ~0.18-0.22).
Доли — десятичные. Поля:
- g_base (устойчивый рост тела, консервативно), compression (сжатие мультипликатора: зрелый≈1.0,
  дорогой растущий 0.85-0.95, дешёвый >1.0), revenue_growth, roic (СОГЛАСУЙ с данным ROE), wacc,
  proven_roic_years (0-10), body_trend (-1|0|1), is_resource (0/1), is_rentier (0/1),
  etype ("растущий"|"зрелый"|"ресурсный"|"циклический").
- Структура −2..+2: moat, disruption, tam, regulation, demo, gosnaves; monetization_proven 0/1.
- rationale: 2-3 фразы.
Верни СТРОГО JSON со всеми полями (БЕЗ roe/payout — они уже известны)."""

REGROUND_FIN = ("g_base", "compression", "revenue_growth", "roic", "wacc")


def reground_judgment(db: sqlite3.Connection, secid: str) -> dict:
    """Переоценить ТОЛЬКО суждённые поля (g/сжатие/roic/wacc/структура), заякорив на
    свежие отчётные ROE/payout/дивы. ROE/payout/прибыль/капитал НЕ трогаем (T-Invest)."""
    if not llm.enabled():
        return {"error": "LLM не настроен (нет .anthropic_key)"}
    row = db.execute(
        "SELECT i.shortname, i.sector, f.roe, f.payout, f.net_profit, m.price, m.cap, m.div_yield "
        "FROM issuers i LEFT JOIN financials f ON f.secid=i.secid "
        "LEFT JOIN market_data m ON m.secid=i.secid WHERE i.secid=?", (secid.upper(),)).fetchone()
    if not row:
        return {"error": f"эмитент {secid} не найден"}
    r = dict(row)
    facts = (f"ФАКТЫ (свежие, НЕ переоценивай): ROE={r['roe']}, payout={r['payout']}, "
             f"дивдоходность={r['div_yield']}, прибыль(млрд)={r['net_profit']}.")
    user = (f"Эмитент: {r['shortname'] or secid} ({secid.upper()}), сектор: {r['sector'] or '—'}.\n"
            f"{facts}\nОцени суждённые параметры строго в JSON.")
    data, err = llm.call_json(SYSTEM_REGROUND, user, max_tokens=1200)
    if err:
        return {"error": err}

    sets = {k: _f(data.get(k)) for k in REGROUND_FIN}
    sets["proven_roic_years"] = _i(data.get("proven_roic_years"))
    sets["body_trend"] = _i(data.get("body_trend"))
    sets["is_resource"] = _i(data.get("is_resource"))
    sets["is_rentier"] = _i(data.get("is_rentier"))
    sets["etype"] = str(data.get("etype", ""))[:20] or None
    cols = ", ".join(f"{k}=?" for k in sets)
    db.execute(f"UPDATE financials SET {cols} WHERE secid=?", (*sets.values(), secid.upper()))

    now = datetime.now().isoformat(timespec="seconds")
    rationale = str(data.get("rationale", ""))[:400]
    upsert(db, "structural", dict(
        secid=secid.upper(), **{k: _i(data.get(k)) for k in STRUCT_FIELDS},
        monetization_proven=_i(data.get("monetization_proven")), mult_seed=1.0,
        note=f"LLM-reground (заякорено на T-Invest, требует проверки): {rationale}",
        updated_by="llm-reground", updated_at=now,
    ), pk="secid")
    return {"secid": secid.upper(), "roic": sets.get("roic"), "g_base": sets.get("g_base")}


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _i(x):
    try:
        return int(round(float(x)))
    except (TypeError, ValueError):
        return 0
