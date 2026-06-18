"""Клиент данных ЦБ РФ: ключевая ставка (надёжно) + инфляция (best-effort).

Ключевая ставка — официальный SOAP-сервис (стабилен). Инфляция РФ не имеет
надёжного открытого API (международные агрегаторы заморозили РФ после 2022,
ЕМИСС отдаёт 403), поэтому берётся best-effort парсингом страницы ЦБ с
fallback на последнее сохранённое значение.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

import httpx

CBR_SOAP = "https://www.cbr.ru/DailyInfoWebServ/DailyInfo.asmx"
CBR_INFL = "https://www.cbr.ru/hd_base/infl/"
_UA = {"User-Agent": "stock-valuation-local/1.0"}


def fetch_key_rate() -> float | None:
    """Ключевая ставка ЦБ (доля, напр. 0.145) через SOAP KeyRate. Надёжно."""
    till = date.today()
    frm = till - timedelta(days=60)
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        '<soap:Body><KeyRate xmlns="http://web.cbr.ru/">'
        f"<fromDate>{frm.isoformat()}</fromDate><ToDate>{till.isoformat()}</ToDate>"
        "</KeyRate></soap:Body></soap:Envelope>"
    )
    try:
        r = httpx.post(CBR_SOAP, content=body.encode("utf-8"), timeout=20.0,
                       headers={**_UA, "Content-Type": "text/xml; charset=utf-8",
                                "SOAPAction": "http://web.cbr.ru/KeyRate"})
        r.raise_for_status()
        # пары (дата, ставка); DT включает таймзону (+03:00) → берём [^<]+
        pairs = re.findall(r"<DT>([^<]+)</DT>\s*<Rate>([\d.]+)</Rate>", r.text)
        if not pairs:
            return None
        dt, rate = max(pairs, key=lambda p: p[0])  # ISO-дата сортируется как строка
        return float(rate) / 100.0
    except Exception:  # noqa: BLE001
        return None


def fetch_key_rate_history(days: int = 430) -> list[tuple[str, float]]:
    """Точки изменения КС за период: [(ISO-дата решения, ставка-доля), ...] по возрастанию.

    Возвращает только решения, где ставка ИЗМЕНИЛАСЬ (последовательные удержания
    схлопнуты в одну точку), плюс гарантированно последнюю точку = текущая ставка.
    Пусто при сбое. Для оценки темпа снижения/повышения (3-4 последних решения).
    """
    till = date.today()
    frm = till - timedelta(days=days)
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        '<soap:Body><KeyRate xmlns="http://web.cbr.ru/">'
        f"<fromDate>{frm.isoformat()}</fromDate><ToDate>{till.isoformat()}</ToDate>"
        "</KeyRate></soap:Body></soap:Envelope>"
    )
    try:
        r = httpx.post(CBR_SOAP, content=body.encode("utf-8"), timeout=25.0,
                       headers={**_UA, "Content-Type": "text/xml; charset=utf-8",
                                "SOAPAction": "http://web.cbr.ru/KeyRate"})
        r.raise_for_status()
        pairs = re.findall(r"<DT>([^<]+)</DT>\s*<Rate>([\d.]+)</Rate>", r.text)
        series = sorted({(p[0][:10], float(p[1]) / 100.0) for p in pairs})
        if not series:
            return []
        out: list[tuple[str, float]] = []
        last = None
        for d, v in series:
            if v != last:
                out.append((d, v))
                last = v
        return out
    except Exception:  # noqa: BLE001
        return []


CBR_KEYPR = "https://www.cbr.ru/press/keypr/"  # выделенная страница решений по ключевой ставке


def fetch_rate_signal(chars: int = 3200) -> list[dict]:
    """Заявление по последнему решению ЦБ о ключевой ставке (риторика/сигнал).

    Выделенная страница решений (keypr) сама содержит полный текст заявления
    Председателя по последнему решению. Чистим до текста, якоримся на начале
    заявления («Совет директоров…») и берём выдержку. Пусто при сбое — Opus
    тогда работает по числовому пейсу.
    """
    try:
        r = httpx.get(CBR_KEYPR, timeout=20.0, headers=_UA, follow_redirects=True)
        r.raise_for_status()
        body = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", r.text)
        body = re.sub(r"<[^>]+>", " ", body)
        body = re.sub(r"&[a-z]+;|&#\d+;", " ", body)
        body = re.sub(r"\s+", " ", body).strip()
        anchor = re.search(r"Совет\w*\s+директоров", body)
        start = anchor.start() if anchor else 0
        text = body[start:start + chars].strip()
        if not text:
            return []
        head = re.search(r"ключев\w*\s+ставку[^.]{0,140}", text)
        title = head.group(0).strip() if head else ""
        return [{"url": CBR_KEYPR, "title": title, "text": text}]
    except Exception:  # noqa: BLE001
        return []


def fetch_inflation(months: int = 6) -> float | None:
    """Годовая инфляция РФ (доля) — СРЕДНЕЕ за последние `months` месяцев.

    Сглаживает месячную волатильность (в дезинфляцию даёт уровень выше последнего
    месяца — консервативно). Best-effort парсинг hd_base/infl
    (столбцы: Дата | Ключевая ставка | Инфляция г/г | Цель → инфляция = cells[2]).
    None при сбое → fallback на БД.
    """
    try:
        r = httpx.get(CBR_INFL, timeout=20.0, headers=_UA, follow_redirects=True)
        r.raise_for_status()
        rows = []  # (YYYYMM, инфляция %)
        for row in re.findall(r"<tr>(.*?)</tr>", r.text, re.S):
            cells = [re.sub(r"<[^>]+>", "", c).strip().replace("\xa0", "").replace(",", ".")
                     for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
            if len(cells) >= 3 and re.match(r"\d{2}\.\d{4}", cells[0]):
                try:
                    val = float(cells[2])
                except ValueError:
                    continue
                mm, yyyy = cells[0].split(".")
                rows.append((yyyy + mm, val))
        if not rows:
            return None
        rows.sort(reverse=True)              # свежие первыми
        recent = [v for _, v in rows[:months]]
        return sum(recent) / len(recent) / 100.0
    except Exception:  # noqa: BLE001
        return None
