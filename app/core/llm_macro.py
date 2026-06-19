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

from app.data import llm, cbr
from app.data.db import upsert, get_macro
from app.data.minfin import current_regime
from app.core import rate_trajectory as rt

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
    "Социально-политическая нестабильность РФ (разворот образовательной премии от ИИ + рост неравенства → фрустрация образованного городского класса; фитиль длинный, severity при детонации высокая)",
]

SYSTEM_SHOCK = """Ты — макро-риск-аналитик по РФ. Оцениваешь форвардный РИСК рыночного ШОКА
(глубокая просадка рынка акций РФ, −27%+ от максимума). ЧЕСТНО СУБЪЕКТИВНАЯ оценка, не рыночная.
Для КАЖДОГО сценария дай:
- prob_pct (0-100): вероятность, что ИМЕННО он вызовет шок в горизонте;
- severity_pct (0-100): ЕСЛИ реализуется — ожидаемая глубина просадки IMOEX. ВАЖНО: падение нефти
  бьёт по РУБЛЮ/бюджету, а не напрямую по IMOEX → severity ниже; война/банковский кризис → выше;
- factor: общий драйвер — "risk-off" | "геополитика" | "оба" | "идиосинкр.";
- rationale (1 фраза).
Затем АГРЕГИРОВАННАЯ вероятность хотя бы одного шока, УЧТЯ корреляцию ЧЕРЕЗ ОБЩИЕ ДРАЙВЕРЫ
(война↔нефть↔санкции↔risk-off кластеризуются — НЕ складывай наивно, дисконтируй за корреляцию).
И ВЕКТОР ШОКА — если шок (любой) реализуется, в СРЕДНЕМ за следующие ~2 года:
- shock_infl_pp: насколько подскочит инфляция РФ, пп (девальвация→импорт дорожает);
- shock_fx_pct: девальвация рубля, % (ослабление = положительное);
- shock_ks_pp: насколько ЦБ поднимет КС в ответ, пп.
Верни СТРОГО JSON без обрамления:
{"horizon":"12 мес","aggregate_pct":int,"scenarios":[{"name":"...","prob_pct":int,"severity_pct":int,"factor":"...","rationale":"1 фраза"}],"shock_infl_pp":float,"shock_fx_pct":float,"shock_ks_pp":float,"note":"итог 2-3 фразы (раздели «вероятно но переживём» и «маловероятно но катастрофа»)"}"""


def _shock_user(regime: dict, context_md: str) -> str:
    sc = "\n".join(f"- {s}" for s in SHOCK_SCENARIOS)
    return (
        f"ГОРИЗОНТ: 12 месяцев.\nСЦЕНАРИИ ШОКА:\n{sc}\n\n"
        f"ТЕКУЩИЙ РЕЖИМ (по правилам): {regime['regime']}, девал-скор {regime.get('deval_score')}/6.\n"
        f"Входы: {json.dumps(regime.get('inputs', {}), ensure_ascii=False)}.\n\n"
        f"КУРИРУЕМЫЙ БРИФИНГ СВЕЖИХ ДАННЫХ:\n{context_md or '(брифинг не заполнен)'}\n\n"
        f"Дай оценку строго в JSON (проценты — целые)."
    )


# ── Траектория ключевой ставки: градация Opus по пейсу решений + риторике ЦБ ──
SYSTEM_TRAJ = """Ты — аналитик денежно-кредитной политики ЦБ РФ. По ДИНАМИКЕ последних
решений по ключевой ставке (пейс) и ТЕКСТУ последнего заявления Председателя (риторика,
сигнал о будущих шагах) определи ТРАЕКТОРИЮ ставки — направление и скорость.
Грейд строго один из: "агрессивное снижение", "обычное снижение", "медленное снижение",
"удержание", "медленное повышение", "обычное повышение", "агрессивное повышение".
Опирайся И на темп (пп за заседание), И на сигнал в риторике (смягчение/ужесточение,
"будет оценивать целесообразность снижения" и т.п.) — риторика может менять скорость
относительно голого пейса. Дай также ТЕРМИНАЛЬНУЮ ставку (куда сойдёт КС в долгосроке, %)
из риторики/нейтрального уровня. Не выдумывай чисел сверх данных.
Дай также disinflation_months — за СКОЛЬКО МЕСЯЦЕВ инфляция выйдет на терминал (нормализация):
оцени по темпу выхода КС на терминал И по риторике ЦБ (осторожно/решительно), с учётом лага
трансмиссии; НЕ наивно экстраполируй крупные антикризисные шаги — у терминала ЦБ тормозит.
Верни СТРОГО JSON без обрамления:
{"grade":"...","terminal_ks_pct":float,"disinflation_months":float,"confidence":"низкая|средняя|высокая",
"signal_read":"как прочитан сигнал ЦБ, 1-2 фразы","rationale":"обоснование 2-3 предложения"}"""


def _traj_user(decisions: list, pace: dict, current_ks: float, signal: list[dict]) -> str:
    dec = ", ".join(f"{d} {v*100:.2f}%" for d, v in decisions[-6:]) or "(нет данных)"
    sig = signal[0]["text"] if signal else "(заявление ЦБ не получено — оценивай по пейсу)"
    return (
        f"ТЕКУЩАЯ КС: {current_ks*100:.2f}%.\n"
        f"ПОСЛЕДНИЕ РЕШЕНИЯ (точки изменения): {dec}.\n"
        f"ЧИСЛОВОЙ ПЕЙС: средний шаг {pace['avg_step_pp']} пп за заседание "
        f"(предварительный грейд по числам: {pace['grade']}).\n\n"
        f"ТЕКСТ ПОСЛЕДНЕГО ЗАЯВЛЕНИЯ ЦБ (риторика):\n{sig}\n\n"
        f"Дай градацию строго в JSON."
    )


def get_rate_signal(db: sqlite3.Connection) -> dict:
    """Ручной текст риторики ЦБ (override авто-фетча keypr)."""
    row = db.execute("SELECT * FROM rate_signal WHERE id = 1").fetchone()
    return dict(row) if row else {"text": "", "updated_at": None}


def set_rate_signal(db: sqlite3.Connection, text: str) -> dict:
    upsert(db, "rate_signal", dict(
        id=1, text=(text or "").strip()[:6000],
        updated_at=datetime.now().isoformat(timespec="seconds")), pk="id")
    return get_rate_signal(db)


def get_rate_trajectory(db: sqlite3.Connection) -> dict | None:
    row = db.execute("SELECT * FROM rate_trajectory WHERE id = 1").fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["decisions"] = json.loads(d.get("decisions_json") or "[]")
    except (json.JSONDecodeError, TypeError):
        d["decisions"] = []
    return d


def _store_trajectory(db, *, grade, terminal_ks, avg_step_pp, confidence, rationale,
                      signal_read, source, decisions, model, disinflation_months=None):
    upsert(db, "rate_trajectory", dict(
        id=1, grade=grade[:40], terminal_ks=terminal_ks,
        avg_step_pp=avg_step_pp, confidence=str(confidence)[:20],
        rationale=str(rationale)[:1500], signal_read=str(signal_read)[:800],
        source=source, decisions_json=json.dumps(decisions, ensure_ascii=False)[:1000],
        model=model, disinflation_months=disinflation_months,
        created_at=datetime.now().isoformat(timespec="seconds"),
    ), pk="id")
    return get_rate_trajectory(db)


def assess_rate_trajectory(db: sqlite3.Connection) -> dict:
    """Градация траектории КС: Opus по пейсу решений + риторике ЦБ; кеш.

    Fallback без Opus — числовой грейд по темпу решений (rate_trajectory.pace_grade)
    и терминал по дефолтному маппингу. Терминал кормит дефлятор (engine).
    """
    decisions = cbr.fetch_key_rate_history()
    pace = rt.pace_grade(decisions)
    current_ks = decisions[-1][1] if decisions else (get_macro(db).get("key_rate") or 0.145)

    if not llm.enabled():
        grade = pace["grade"]
        tks = rt.grade_terminal_ks(grade, current_ks)
        return _store_trajectory(
            db, grade=grade, terminal_ks=tks, avg_step_pp=pace["avg_step_pp"],
            confidence="—", rationale="Числовая градация по темпу решений (Opus не настроен).",
            signal_read="", source="пейс (без Opus)", decisions=decisions[-6:],
            disinflation_months=round(rt.disinflation_years(current_ks, tks, pace["avg_step_pp"]) * 12, 1),
            model="")

    # риторика: ручной ввод (override) приоритетнее авто-фетча keypr
    manual = get_rate_signal(db)
    if manual.get("text", "").strip():
        signal = [{"url": "(вручную)", "title": "", "text": manual["text"].strip()}]
        sig_src = "вручную"
    else:
        signal = cbr.fetch_rate_signal()
        sig_src = "авто keypr" if signal else "без риторики"
    data, err = llm.call_json(SYSTEM_TRAJ, _traj_user(decisions, pace, current_ks, signal),
                              max_tokens=1100)
    if err or not data:
        grade = pace["grade"]
        tks = rt.grade_terminal_ks(grade, current_ks)
        return _store_trajectory(
            db, grade=grade, terminal_ks=tks, avg_step_pp=pace["avg_step_pp"],
            confidence="—", rationale=f"Fallback на пейс: {err or 'пустой ответ Opus'}.",
            signal_read="", source="пейс (Opus недоступен)", decisions=decisions[-6:],
            disinflation_months=round(rt.disinflation_years(current_ks, tks, pace["avg_step_pp"]) * 12, 1),
            model="")

    grade = data.get("grade") if data.get("grade") in rt.GRADES else pace["grade"]
    try:
        tks = float(data["terminal_ks_pct"]) / 100.0
        if not (0.0 < tks < 0.40):
            tks = rt.grade_terminal_ks(grade, current_ks)
    except (KeyError, TypeError, ValueError):
        tks = rt.grade_terminal_ks(grade, current_ks)
    try:                                    # окно дезинфляции из риторики (Opus); иначе из траектории
        dim = float(data["disinflation_months"])
        dim = dim if 1.0 <= dim <= 60.0 else rt.disinflation_years(current_ks, tks, pace["avg_step_pp"]) * 12
    except (KeyError, TypeError, ValueError):
        dim = rt.disinflation_years(current_ks, tks, pace["avg_step_pp"]) * 12
    return _store_trajectory(
        db, grade=grade, terminal_ks=tks, avg_step_pp=pace["avg_step_pp"],
        confidence=data.get("confidence", ""), rationale=data.get("rationale", ""),
        signal_read=data.get("signal_read", ""), source=f"Opus + риторика ({sig_src})",
        decisions=decisions[-6:], disinflation_months=round(dim, 1),
        model=os.environ.get("ANTHROPIC_MODEL", llm.DEFAULT_MODEL))


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
    # компиляция (#15): наивно-независимая для прозрачности корреляции; P×severity (две оси);
    # P за горизонт решения 3 года (годовые P накапливаются).
    scs = data.get("scenarios", []) or []
    ps = [float(s["prob_pct"]) / 100 for s in scs if s.get("prob_pct") is not None]
    indep = None
    if ps:
        prod = 1.0
        for p in ps:
            prod *= (1.0 - p)
        indep = round((1.0 - prod) * 100, 1)
    exp_dmg = round(sum(
        (float(s.get("prob_pct", 0)) / 100) * (float(s.get("severity_pct", 0)) / 100)
        for s in scs) * 100, 1) if scs else None       # ожидаемая просадка IMOEX, пп
    p3 = round((1.0 - (1.0 - agg / 100) ** 3) * 100, 1) if agg is not None else None
    def _f(key):  # пп/проценты → доля, безопасно
        try:
            return float(data.get(key)) / 100.0
        except (TypeError, ValueError):
            return None
    upsert(db, "shock_risk", dict(
        id=1, aggregate_pct=agg,
        horizon=str(data.get("horizon", "12 мес"))[:20],
        scenarios_json=json.dumps(scs, ensure_ascii=False)[:3000],
        note=str(data.get("note", ""))[:1000],
        expected_damage_pct=exp_dmg, independent_pct=indep, p_horizon3_pct=p3,
        shock_infl_pp=_f("shock_infl_pp"), shock_fx_pct=_f("shock_fx_pct"), shock_ks_pp=_f("shock_ks_pp"),
        model=os.environ.get("ANTHROPIC_MODEL", llm.DEFAULT_MODEL),
        created_at=datetime.now().isoformat(timespec="seconds"),
    ), pk="id")
    return get_shock(db)
