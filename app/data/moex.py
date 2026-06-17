"""Клиент MOEX ISS API (публичный, без ключа).

Уровень 1 (надёжно автоматизируется): котировки, капитализация, дивиденды,
история. Вежливый троттлинг (≤ MOEX_RPS) + in-memory кэш с TTL — не долбить
на каждый запрос фронта (SPEC §3.1).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import median
from typing import Any

import httpx

from app.config import MOEX_BASE, MOEX_BOARD, MOEX_RPS, MOEX_CACHE_TTL_SEC


@dataclass
class Quote:
    secid: str
    shortname: str
    latname: str
    isin: str
    price: float | None          # текущая (MARKETPRICE/LAST) с fallback PREVPRICE
    prevprice: float | None
    issuesize: float | None
    cap: float | None            # рыночная капитализация, ₽
    board: str = MOEX_BOARD


@dataclass
class Dividend:
    secid: str
    reg_date: str
    value: float
    currency: str


def _num(x: Any) -> float | None:
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def is_dividend_spike(ttm_yield: float | None, typical_yield: float | None) -> bool:
    """Аномалия TTM-дивдоходности: абсолютно высока (>20%) ИЛИ кратно (>1.8×)
    выше типичной годовой нормы эмитента. Ловит разовый спецдивиденд, не трогает
    зрелые дивидендные имена (у них высокая дивдох — норма, не аномалия).
    """
    if ttm_yield is None:
        return False
    if ttm_yield > 0.20:
        return True
    if typical_yield and ttm_yield > 1.8 * typical_yield and ttm_yield > 0.10:
        return True
    return False


class MoexClient:
    def __init__(self, *, rps: int = MOEX_RPS, ttl: int = MOEX_CACHE_TTL_SEC):
        self._min_interval = 1.0 / max(rps, 1)
        self._last_call = 0.0
        self._ttl = ttl
        self._cache: dict[str, tuple[float, Any]] = {}
        self._client = httpx.Client(
            base_url=MOEX_BASE, timeout=20.0,
            headers={"User-Agent": "stock-valuation-local/1.0"},
        )

    # ── низкоуровневый запрос с троттлингом и кэшем ──────────────────────────
    def _get(self, path: str, params: dict | None = None) -> dict:
        key = path + "?" + "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))
        now = time.time()
        hit = self._cache.get(key)
        if hit and now - hit[0] < self._ttl:
            return hit[1]
        # троттлинг
        wait = self._min_interval - (now - self._last_call)
        if wait > 0:
            time.sleep(wait)
        r = self._client.get(path, params=params)
        self._last_call = time.time()
        r.raise_for_status()
        data = r.json()
        self._cache[key] = (time.time(), data)
        return data

    @staticmethod
    def _rows(block: dict) -> list[dict]:
        cols = block["columns"]
        return [dict(zip(cols, row)) for row in block["data"]]

    # ── публичные методы ─────────────────────────────────────────────────────
    def list_quotes(self) -> list[Quote]:
        """Все бумаги основного режима TQBR с ценой и капитализацией."""
        data = self._get(
            f"/engines/stock/markets/shares/boards/{MOEX_BOARD}/securities.json",
            {"iss.meta": "off"},
        )
        sec = {r["SECID"]: r for r in self._rows(data["securities"])}
        md = {r["SECID"]: r for r in self._rows(data["marketdata"])}
        out: list[Quote] = []
        for secid, s in sec.items():
            m = md.get(secid, {})
            price = _num(m.get("MARKETPRICE")) or _num(m.get("LAST")) or _num(s.get("PREVPRICE"))
            issuesize = _num(s.get("ISSUESIZE"))
            cap = _num(m.get("ISSUECAPITALIZATION"))
            if cap is None and price is not None and issuesize is not None:
                cap = price * issuesize
            out.append(Quote(
                secid=secid, shortname=s.get("SHORTNAME", ""),
                latname=s.get("LATNAME", ""), isin=s.get("ISIN", ""),
                price=price, prevprice=_num(s.get("PREVPRICE")),
                issuesize=issuesize, cap=cap,
            ))
        return out

    def quote(self, secid: str) -> Quote | None:
        for q in self.list_quotes():
            if q.secid == secid.upper():
                return q
        return None

    def dividends(self, secid: str) -> list[Dividend]:
        data = self._get(f"/securities/{secid.upper()}/dividends.json", {"iss.meta": "off"})
        return [
            Dividend(secid=r["secid"], reg_date=r["registryclosedate"],
                     value=_num(r["value"]) or 0.0, currency=r.get("currencyid", "RUB"))
            for r in self._rows(data["dividends"])
        ]

    def dividend_yield(self, secid: str, price: float | None) -> tuple[float | None, list[str]]:
        """Дивдоходность = сумма выплат за 12 мес / текущая цена."""
        a = self.dividend_analysis(secid, price)
        return a["ttm_yield"], a["warnings"]

    def dividend_analysis(self, secid: str, price: float | None) -> dict:
        """TTM-дивдоходность + детектор аномалии (разовый спецдив).

        Аномалия (spike), если TTM-дивдоходность абсолютно высока (> 20%) ИЛИ
        кратно (> 1.8×) выше типичной годовой дивдоходности эмитента (медиана
        по непустым годам). Ловит X5 (спецдив после редомициляции), не трогает
        зрелые дивидендные (МТС, Лукойл — у них высокая дивдох это норма).
        """
        if not price:
            return {"ttm_yield": None, "typical_yield": None, "n_payments_ttm": 0,
                    "is_spike": False, "warnings": ["нет цены для расчёта дивдоходности"]}
        cutoff = (date.today() - timedelta(days=365)).isoformat()
        divs = self.dividends(secid)
        warnings: list[str] = []

        # TTM-сумма (только рублёвые; инвалюту флагуем)
        ttm = 0.0
        n_ttm = 0
        for d in divs:
            if d.reg_date >= cutoff:
                if d.currency in ("RUB", "SUR"):
                    ttm += d.value
                    n_ttm += 1
                else:
                    warnings.append(f"инвалютная выплата {d.value} {d.currency} не учтена")

        # годовые суммы за последние 5 календарных лет (для типичной нормы)
        cur_year = int(date.today().isoformat()[:4])
        by_year: dict[int, float] = {}
        for d in divs:
            if d.currency not in ("RUB", "SUR"):
                continue
            try:
                y = int(d.reg_date[:4])
            except (ValueError, TypeError):
                continue
            if cur_year - 5 <= y <= cur_year:
                by_year[y] = by_year.get(y, 0.0) + d.value
        nonzero = sorted(v for v in by_year.values() if v > 0)
        typical_annual = median(nonzero) if len(nonzero) >= 2 else None

        ttm_yield = ttm / price
        typical_yield = (typical_annual / price) if typical_annual else None
        # несопоставимая история (до-сплитовые дивиденды на текущую цену) → не доверяем
        if typical_yield is not None and typical_yield > 0.5:
            typical_yield = None
            warnings.append("История выплат несопоставима с текущей ценой "
                            "(вероятно сплит акций) — типичная норма не рассчитана.")

        is_spike = is_dividend_spike(ttm_yield, typical_yield)
        if is_spike:
            warnings.append(
                f"TTM-дивдоходность {ttm_yield*100:.0f}% аномальна "
                f"(вероятно разовый спецдивиденд) — проверь устойчивость потока. "
                + (f"Типичная годовая ≈ {typical_yield*100:.0f}%." if typical_yield else
                   "Короткая/прерывистая история выплат.")
            )
        return {"ttm_yield": ttm_yield, "typical_yield": typical_yield,
                "n_payments_ttm": n_ttm, "is_spike": is_spike, "warnings": warnings}

    def history_close(self, secid: str, *, days: int = 365) -> list[tuple[str, float]]:
        """История дневных CLOSE (для тренда/корреляций). Пагинация start=."""
        till = date.today().isoformat()
        frm = (date.today() - timedelta(days=days)).isoformat()
        out: list[tuple[str, float]] = []
        start = 0
        while True:
            data = self._get(
                f"/history/engines/stock/markets/shares/boards/{MOEX_BOARD}/securities/{secid.upper()}.json",
                {"iss.meta": "off", "from": frm, "till": till, "start": start},
            )
            rows = self._rows(data["history"])
            if not rows:
                break
            for r in rows:
                c = _num(r.get("CLOSE"))
                if c is not None:
                    out.append((r.get("TRADEDATE"), c))
            if len(rows) < 100:
                break
            start += 100
        return out

    def index_drawdown(self, index: str = "IMOEX", *, days: int = 365) -> float | None:
        """Просадка индекса от локального максимума за период (≥0). Для ШОК-режима.

        index — рыночный индекс (рынок 'index', борд SNDX). Возвращает (max−last)/max.
        """
        till = date.today().isoformat()
        frm = (date.today() - timedelta(days=days)).isoformat()
        closes: list[float] = []
        start = 0
        while True:
            data = self._get(
                f"/history/engines/stock/markets/index/boards/SNDX/securities/{index}.json",
                {"iss.meta": "off", "from": frm, "till": till, "start": start,
                 "history.columns": "TRADEDATE,CLOSE"},
            )
            rows = self._rows(data["history"])
            if not rows:
                break
            for r in rows:
                c = _num(r.get("CLOSE"))
                if c is not None:
                    closes.append(c)
            if len(rows) < 100:
                break
            start += 100
        if not closes:
            return None
        mx = max(closes)
        return (mx - closes[-1]) / mx if mx else None

    def close(self):
        self._client.close()
