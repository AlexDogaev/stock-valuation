"""Облигации с MOEX ISS — данные для бонд-модуля (фаза 2 мультиассета).

ОФЗ-кривая строится из самих ОФЗ (дюрация→YTM) — это и есть безрисковая база (КБД), без
зависимости от cbr.ru (там были проблемы с сертификатом). Спред корпората = YTM − ОФЗ-кривая(дюр).
Оферта → yield-to-put (YIELDTOOFFER), не -to-maturity. fetch_bonds(fx=True) → валютные (замещайки/юаневые).
"""
from __future__ import annotations

import time

import httpx

from app.config import MOEX_BASE

OFZ_BOARD = "TQOB"    # ОФЗ
CORP_BOARD = "TQCB"   # корпоративные
RUB = {"SUR", "RUB"}
CLASSIC = {"Фикс", "Флоат", "Линкер"}   # классические бонды (структурные/конверт. — вне скринера)


def classify_coupon(bondtype: str | None) -> str:
    """Тип купона из MOEX BONDTYPE → Фикс | Флоат | Линкер | Прочее."""
    bt = (bondtype or "").lower()
    if "флоат" in bt:
        return "Флоат"
    if "линкер" in bt or "индексир" in bt:
        return "Линкер"
    if "фикс" in bt or "аморт" in bt or "дисконт" in bt:
        return "Фикс"
    return "Прочее"   # структурные/конвертируемые/валютные — не классический бонд
_CACHE_TTL = 15 * 60
_cache: dict[str, tuple[float, list[dict]]] = {}


def fetch_bonds(board: str, *, fx: bool = False) -> list[dict]:
    """Облигации борда с YTM/дюрацией/офертой/ликвидностью (кэш 15 мин).
    fx=False → рублёвые; fx=True → валютные (замещайки/юаневые: FACEUNIT ≠ RUB)."""
    ckey = f"{board}:{'fx' if fx else 'rub'}"
    hit = _cache.get(ckey)
    if hit and time.time() - hit[0] < _CACHE_TTL:
        return hit[1]
    url = f"{MOEX_BASE}/engines/stock/markets/bonds/boards/{board}/securities.json"
    r = httpx.get(url, params={"iss.meta": "off", "iss.only": "securities,marketdata"}, timeout=30.0)
    r.raise_for_status()
    d = r.json()
    sc = {c: i for i, c in enumerate(d["securities"]["columns"])}
    mc = {c: i for i, c in enumerate(d["marketdata"]["columns"])}
    md = {row[mc["SECID"]]: row for row in d["marketdata"]["data"]}
    out: list[dict] = []
    for s in d["securities"]["data"]:
        secid = s[sc["SECID"]]
        faceunit = s[sc["FACEUNIT"]]
        if (faceunit in RUB) == fx:      # fx=True → нужны валютные; fx=False → рублёвые
            continue
        m = md.get(secid)
        ytm = (m[mc["YIELD"]] if m else None) or s[sc["YIELDATPREVWAPRICE"]]
        dur_days = m[mc["DURATION"]] if m else None
        if ytm is None or not dur_days:
            continue
        offer = s[sc["OFFERDATE"]] or s[sc["PUTOPTIONDATE"]]
        ytm_offer = m[mc["YIELDTOOFFER"]] if m else None
        eff_ytm = ytm_offer if (offer and ytm_offer) else ytm   # оферта → yield-to-put (РФ-критично)
        out.append({
            "secid": secid, "name": s[sc["SHORTNAME"]], "board": board,
            "ytm": eff_ytm / 100.0, "duration_years": round(dur_days / 365.0, 2),
            "coupon_pct": s[sc["COUPONPERCENT"]], "matdate": s[sc["MATDATE"]],
            "offer": offer or None, "num_trades": (m[mc["NUMTRADES"]] if m else 0) or 0,
            "coupon_type": classify_coupon(s[sc["BONDTYPE"]]), "faceunit": faceunit,
            "listlevel": (s[sc["LISTLEVEL"]] if "LISTLEVEL" in sc else None),  # уровень листинга MOEX (1-2 ИГ / 3 ВДО)
        })
    _cache[ckey] = (time.time(), out)
    return out


# Фильтр качества: отсекает шум (бумаги при погашении dur≈0 → YTM взрывается; дефолтные/неликвид).
def is_sane(b: dict, *, min_dur: float, ytm_lo: float, ytm_hi: float, min_trades: int) -> bool:
    return (b["duration_years"] >= min_dur and ytm_lo <= b["ytm"] <= ytm_hi
            and b["num_trades"] >= min_trades)


def ofz_curve(ofz: list[dict]) -> list[tuple[float, float]]:
    """Безрисковая кривая (дюрация_лет, YTM), отсортирована по дюрации."""
    return sorted((b["duration_years"], b["ytm"]) for b in ofz
                  if b["ytm"] and b["duration_years"])


def curve_at(curve: list[tuple[float, float]], dur: float) -> float | None:
    """Линейная интерполяция YTM кривой на дюрацию (плоско за краями)."""
    if not curve:
        return None
    if dur <= curve[0][0]:
        return curve[0][1]
    if dur >= curve[-1][0]:
        return curve[-1][1]
    for (d0, y0), (d1, y1) in zip(curve, curve[1:]):
        if d0 <= dur <= d1 and d1 > d0:
            return y0 + (y1 - y0) * (dur - d0) / (d1 - d0)
    return curve[-1][1]
