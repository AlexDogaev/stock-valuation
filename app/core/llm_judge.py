"""LLM-черновик структурного слоя (Opus). Класс B — суждение, человек в петле.

Собирает контекст эмитента (метрики + методология), просит Opus предложить баллы
6 осей + monetization_proven + обоснование. Результат — ЧЕРНОВИК (structural_draft),
который человек подтверждает через карточку. Финальный вердикт LLM не выносит.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from app.core import engine
from app.data import llm
from app.data.db import upsert

SYSTEM = """Ты — финансовый аналитик российского рынка (MOEX). Оцениваешь СТРУКТУРНЫЙ
слой эмитента по 6 осям, шкала −2 (угроза) … +2 (попутно):
- moat (ров): сетевые эффекты, переключательные издержки, бренд, масштаб, лицензии.
- disruption (дизрупция спроса): технология убивает (−) или создаёт (+) спрос. Это
  ГАДАНИЕ — оценивай со скромностью, близко к 0 при неопределённости.
- tam (секулярный TAM): рынок растёт/сжимается (поведенчески, без демографии).
- regulation (регуляторика): правила игры — лицензии, ограничения, доступ к рынку.
- demo (демо-вектор): ДЕТЕРМИНИРОВАН (когорта ядра спроса уже родилась) — оценивай
  жёстко, с уверенностью; двунаправлен.
- gosnaves (госнавес): изъятие ренты налогом/тарифом ДО акционера (НДПИ, пошлины,
  windfall, тарифное сдерживание). Бьёт по РЕНТНЫМ (ресурсы, госмонополии), почти не
  трогает бизнесы добавленной стоимости. ПРАВИЛО «ОДИН РАЗ»: если низкий рост УЖЕ
  отражает госнавес — не дублируй (ставь 0).
- monetization_proven (0/1): доказан ли путь монетизации (для перспективного качества).
Верни СТРОГО JSON без пояснений вокруг:
{"moat":int,"disruption":int,"tam":int,"regulation":int,"demo":int,"gosnaves":int,"monetization_proven":0|1,"rationale":"2-3 предложения на русском"}"""

DRAFT_FIELDS = ("moat", "disruption", "tam", "regulation", "demo", "gosnaves",
                "monetization_proven")


def _context(card: dict) -> str:
    i, c = card.get("inputs", {}), card.get("classification") or {}
    g = lambda d, k: (d.get(k) or {}).get("value") if isinstance(d.get(k), dict) else d.get(k)
    return (
        f"Эмитент: {card['name']} ({card['secid']}), сектор: {card.get('sector','—')}, "
        f"тип: {card.get('type','—')}.\n"
        f"ROE: {g(i,'roe')}, payout: {g(i,'payout')}, базовый рост g: {g(i,'g_base')}, "
        f"дивдоходность: {g(i,'div_yield')}.\n"
        f"ROIC−WACC: {c.get('roic_minus_wacc')}, классификация: {c.get('detailed','—')}.\n"
        f"Дай структурную оценку 6 осей и monetization_proven строго в JSON."
    )


def draft_structural(db: sqlite3.Connection, secid: str) -> dict:
    """Сгенерировать LLM-черновик структурных баллов и сохранить в structural_draft."""
    if not llm.enabled():
        return {"error": "LLM не настроен (нет .anthropic_key)"}
    card = engine.evaluate_issuer(db, secid)
    if not card:
        return {"error": f"эмитент {secid} не найден"}

    data, err = llm.call_json(SYSTEM, _context(card))
    if err:
        return {"error": err}

    draft = {k: int(data.get(k, 0)) for k in DRAFT_FIELDS}
    draft["rationale"] = str(data.get("rationale", ""))[:1000]
    import os
    upsert(db, "structural_draft", dict(
        secid=secid.upper(), **draft,
        model=os.environ.get("ANTHROPIC_MODEL", llm.DEFAULT_MODEL),
        created_at=datetime.now().isoformat(timespec="seconds"),
    ), pk="secid")
    return {"secid": secid.upper(), "draft": draft}


def get_draft(db: sqlite3.Connection, secid: str) -> dict | None:
    row = db.execute("SELECT * FROM structural_draft WHERE secid = ?", (secid.upper(),)).fetchone()
    return dict(row) if row else None


def apply_draft(db: sqlite3.Connection, secid: str) -> dict:
    """Применить черновик к активным структурным баллам (после подтверждения человеком)."""
    d = get_draft(db, secid)
    if not d:
        return {"error": "черновика нет"}
    upsert(db, "structural", dict(
        secid=secid.upper(),
        moat=d["moat"], disruption=d["disruption"], tam=d["tam"],
        regulation=d["regulation"], demo=d["demo"], gosnaves=d["gosnaves"],
        monetization_proven=d["monetization_proven"],
        note=f"LLM-черновик принят: {d['rationale'][:200]}",
        updated_by="llm+human", updated_at=datetime.now().isoformat(timespec="seconds"),
    ), pk="secid")
    return engine.evaluate_issuer(db, secid)
