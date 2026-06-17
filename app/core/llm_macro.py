"""Opus-аналитик макро-режима (advisory, класс B).

Читает: (1) механический режим по правилам (nwf_regime), (2) КУРИРУЕМЫЙ брифинг
свежих данных (macro_context — заполняется человеком/агентом с веб-сверкой, т.к.
сам сервис веб-поиск в рантайме не делает), (3) методологию. Выдаёт нюансированный
разбор ПЕРЕД публикацией. НЕ перекрывает режим — это advisory-слой, человек в петле.
Результат кешируется в macro_analysis; гоняется по расписанию, не на каждый просмотр.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime

from app.data import llm
from app.data.db import upsert
from app.data.minfin import current_regime

SYSTEM = """Ты — макро-аналитик по РФ (бюджет, ФНБ, бюджетное правило, рубль) для
инвестора с 20-летним горизонтом DCA. Тебе дают механический режим рынка по правилам
модели, КУРИРУЕМЫЙ брифинг свежих данных и методологию. Задача — ГЛУБОКИЙ разбор перед
публикацией: поймать нюансы, которые слепые пороги упускают. Особое внимание:
- снижение ликвидного ФНБ от ПЕРЕОЦЕНКИ (цена золота, курс рубля) — это НЕ дренаж на дефицит;
- покупает или продаёт Минфин валюту/золото по бюджетному правилу (профицит vs дефицит
  нефтегаз-доходов относительно цены отсечения);
- Urals против цены отсечения; чем финансируется дефицит бюджета (ОФЗ vs ФНБ);
- структурная фрагильность (тонкий буфер) ОТДЕЛЬНО от текущего триггера (взведён он или нет).
Не выдумывай чисел, которых нет в брифинге. Если данных не хватает — прямо скажи, каких.
Верни СТРОГО JSON без обрамления:
{"regime_opus":"NORMAL|RISK|SHOCK","confidence":"низкая|средняя|высокая",
"verdict":"итог 1-2 фразы","nuances":["нюанс 1","нюанс 2"],"note":"разбор 3-5 предложений"}"""


def _user(regime: dict, context_md: str) -> str:
    return (
        f"МЕХАНИЧЕСКИЙ РЕЖИМ (по правилам): {regime['regime']}; "
        f"девал-скор {regime.get('deval_score')}/6; давление {regime.get('deval_pressure')}; "
        f"budget_sign(Urals−отсечка)={regime.get('budget_sign')}.\n"
        f"Входы режима: {json.dumps(regime.get('inputs', {}), ensure_ascii=False)}.\n"
        f"Заметка правил: {regime.get('note', '')}\n\n"
        f"КУРИРУЕМЫЙ БРИФИНГ СВЕЖИХ ДАННЫХ:\n{context_md or '(брифинг не заполнен)'}\n\n"
        f"Дай разбор строго в JSON."
    )


def get_context(db: sqlite3.Connection) -> dict:
    row = db.execute("SELECT * FROM macro_context WHERE id = 1").fetchone()
    return dict(row) if row else {"context_md": "", "source": "", "updated_at": None}


def set_context(db: sqlite3.Connection, context_md: str, source: str = "") -> dict:
    upsert(db, "macro_context", dict(
        id=1, context_md=context_md, source=source,
        updated_at=datetime.now().isoformat(timespec="seconds")), pk="id")
    return get_context(db)


def get_analysis(db: sqlite3.Connection) -> dict | None:
    row = db.execute("SELECT * FROM macro_analysis WHERE id = 1").fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["nuances"] = json.loads(d.get("nuances_json") or "[]")
    except (json.JSONDecodeError, TypeError):
        d["nuances"] = []
    d["diverges"] = bool(d.get("regime_opus")) and d.get("regime_opus") != d.get("regime_rule")
    return d


def analyze_macro(db: sqlite3.Connection) -> dict:
    """Прогнать Opus-разбор над текущим режимом + курируемым контекстом, закешировать."""
    if not llm.enabled():
        return {"error": "LLM не настроен (нет .anthropic_key)"}
    regime = current_regime()
    ctx = get_context(db)
    data, err = llm.call_json(SYSTEM, _user(regime, ctx.get("context_md", "")), max_tokens=1200)
    if err:
        return {"error": err}
    upsert(db, "macro_analysis", dict(
        id=1,
        regime_rule=regime["regime"],
        regime_opus=str(data.get("regime_opus", "")).upper()[:10],
        confidence=str(data.get("confidence", ""))[:20],
        verdict=str(data.get("verdict", ""))[:400],
        nuances_json=json.dumps(data.get("nuances", []), ensure_ascii=False)[:2000],
        note=str(data.get("note", ""))[:1500],
        model=os.environ.get("ANTHROPIC_MODEL", llm.DEFAULT_MODEL),
        created_at=datetime.now().isoformat(timespec="seconds"),
    ), pk="id")
    return get_analysis(db)


# ── Форвардная вероятность ШОКА по сценариям (субъективная оценка Opus) ──
SHOCK_SCENARIOS = [
    "Резкое и устойчивое падение цен на нефть (Urals ниже ~$45-50)",
    "Большая война или резкая военная эскалация (расширение конфликта, прямое столкновение с НАТО)",
    "Вторичные санкции против покупателей РФ-нефти (Китай/Индия) — удар по экспортной выручке",
    "Системный внутренний финансовый/банковский кризис РФ (плохие долги, кризис ликвидности)",
    "Глобальная рецессия / risk-off на развивающихся рынках",
]

SYSTEM_SHOCK = """Ты — макро-риск-аналитик по РФ. Оцениваешь ВЕРОЯТНОСТЬ рыночного ШОКА
(глубокая просадка рынка акций РФ, порядка −27%+ от максимума) в заданном горизонте по списку
сценариев. Это ЧЕСТНО СУБЪЕКТИВНАЯ экспертная оценка, не калиброванная/рыночная вероятность.
Для КАЖДОГО сценария дай вероятность 0-100%, что ИМЕННО он вызовет такой шок в горизонте, с
краткой аргументацией от текущего контекста. Затем дай АГРЕГИРОВАННУЮ вероятность хотя бы одного
шока, УЧТЯ корреляцию сценариев (война↔нефть↔санкции связаны — НЕ складывай наивно).
Верни СТРОГО JSON без обрамления:
{"horizon":"12 мес","aggregate_pct":int,"scenarios":[{"name":"...","prob_pct":int,"rationale":"1 фраза"}],"note":"итог 2-3 фразы"}"""


def _shock_user(regime: dict, context_md: str) -> str:
    sc = "\n".join(f"- {s}" for s in SHOCK_SCENARIOS)
    return (
        f"ГОРИЗОНТ: 12 месяцев.\nСЦЕНАРИИ ШОКА:\n{sc}\n\n"
        f"ТЕКУЩИЙ РЕЖИМ (по правилам): {regime['regime']}, девал-скор {regime.get('deval_score')}/6.\n"
        f"Входы: {json.dumps(regime.get('inputs', {}), ensure_ascii=False)}.\n\n"
        f"КУРИРУЕМЫЙ БРИФИНГ СВЕЖИХ ДАННЫХ:\n{context_md or '(брифинг не заполнен)'}\n\n"
        f"Дай оценку строго в JSON (проценты — целые)."
    )


def get_shock(db: sqlite3.Connection) -> dict | None:
    row = db.execute("SELECT * FROM shock_risk WHERE id = 1").fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["scenarios"] = json.loads(d.get("scenarios_json") or "[]")
    except (json.JSONDecodeError, TypeError):
        d["scenarios"] = []
    return d


def assess_shock(db: sqlite3.Connection) -> dict:
    """Оценить форвардную вероятность ШОКА по сценариям (Opus), закешировать."""
    if not llm.enabled():
        return {"error": "LLM не настроен (нет .anthropic_key)"}
    regime = current_regime()
    ctx = get_context(db)
    data, err = llm.call_json(SYSTEM_SHOCK, _shock_user(regime, ctx.get("context_md", "")), max_tokens=1300)
    if err:
        return {"error": err}
    try:
        agg = float(data.get("aggregate_pct"))
    except (TypeError, ValueError):
        agg = None
    upsert(db, "shock_risk", dict(
        id=1, aggregate_pct=agg,
        horizon=str(data.get("horizon", "12 мес"))[:20],
        scenarios_json=json.dumps(data.get("scenarios", []), ensure_ascii=False)[:3000],
        note=str(data.get("note", ""))[:1000],
        model=os.environ.get("ANTHROPIC_MODEL", llm.DEFAULT_MODEL),
        created_at=datetime.now().isoformat(timespec="seconds"),
    ), pk="id")
    return get_shock(db)
