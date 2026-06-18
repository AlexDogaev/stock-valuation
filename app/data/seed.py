"""Seed БД из Excel-модели «Модель_справедливой_стоимости.xlsx».

Данные извлечены из листов:
  • «ТОП-25 (2 слоя)»   → div_yield, g_base, compression, structural_mult
  • «Структурный слой»  → детальные баллы по 6 осям (8 эмитентов)
  • «Зрелый режим» / «X5 и МиД» / «Фарма PRMD OZPH» / «Под инвестора»
                         → ROE, equity, payout, roic, wacc, тренд тела

MVP-узкое место уровня 2 (SPEC §3.2) закрыто ручными данными по ликвидным
именам. Живые котировки/капа/дивдоходность подтягиваются из MOEX (refresh).
"""
from __future__ import annotations

from datetime import datetime

from app.data.db import get_db, init_db, upsert
from app.data.moex import MoexClient

# (secid, имя, сектор, div_yield, g_base, compression, mult_seed)
TOP = [
    ("SBER", "Сбербанк",       "Банк",       0.110, 0.09, 1.00, 1.0),
    ("T",    "Т-Технологии",   "Банк",       0.068, 0.20, 0.96, 1.0),
    ("X5",   "X5",             "Ритейл",     0.141, 0.08, 1.00, 1.0),
    ("SVCB", "Совкомбанк",     "Банк",       0.087, 0.13, 1.00, 1.0),
    ("BSPB", "БСПБ",           "Банк",       0.135, 0.08, 1.00, 1.0),
    ("YDEX", "Яндекс",         "IT",         0.000, 0.20, 0.91, 1.1),
    ("OZON", "Ozon",           "IT/e-com",   0.000, 0.20, 0.90, 1.0),
    ("LKOH", "Лукойл",         "Нефтегаз",   0.168, 0.01, 1.00, 0.5),
    ("ROSN", "Роснефть",       "Нефтегаз",   0.121, 0.03, 1.00, 0.5),
    ("GAZP", "Газпром",        "Нефтегаз",   0.040, 0.00, 1.00, 0.0),
    ("NVTK", "НОВАТЭК",        "Нефтегаз",   0.128, 0.03, 1.00, 0.8),
    ("TATN", "Татнефть",       "Нефтегаз",   0.166, 0.00, 1.00, 0.5),
    ("SIBN", "Газпром нефть",  "Нефтегаз",   0.156, 0.02, 1.00, 0.5),
    ("TRNFP","Транснефть пр",  "Инфраструк.",0.140, 0.05, 1.00, 0.85),
    ("GMKN", "Норникель",      "Металл",     0.030, 0.05, 1.00, 1.0),
    ("PLZL", "Полюс",          "Золото",     0.079, 0.08, 0.99, 1.0),
    ("CHMF", "Северсталь",     "Металл",     0.080, 0.00, 1.00, 0.5),
    ("PHOR", "Фосагро",        "Удобрения",  0.125, 0.04, 1.00, 1.0),
    ("MTSS", "МТС",            "Телеком",    0.150, 0.00, 1.00, 1.0),
    ("MOEX", "Мосбиржа",       "Финансы",    0.105, 0.03, 1.00, 1.0),
    ("PRMD", "Промомед",       "Фарма",      0.020, 0.20, 0.93, 1.1),
    ("OZPH", "Озон Фарма",     "Фарма",      0.005, 0.15, 0.95, 1.0),
    ("MDMG", "Мать и Дитя",    "Медицина",   0.064, 0.18, 0.95, 1.0),
    ("HEAD", "Хэдхантер",      "IT",         0.130, 0.15, 0.89, 0.0),
    ("MGNT", "Магнит",         "Ритейл",     0.100, 0.04, 1.00, 1.0),
]

# детальные структурные баллы: secid → (moat,disruption,tam,regulation,demo,gosnaves,note)
STRUCT = {
    "HEAD": (-1, -2, -1, 0, 0, 0, "ИИ убивает white-collar + демография под двойным ударом"),
    "YDEX": (2, 1, 1, 0, 0, 0, "Сам ИИ-лидер РФ, поиск-монополия, экосистема"),
    "SBER": (2, 0, 1, 0, 0, -1, "Масштаб+экосистема+системность; финтех давит, но Сбер лидер"),
    "T":    (1, 1, 1, -1, -1, 0, "Финтех-дизраптор; риск надзора ЦБ; демо двойственна"),
    "PRMD": (1, 0, 2, 0, 2, 0, "Стареющее население, спрос на лекарства растёт (демо +2)"),
    "X5":   (1, 0, 0, 0, 0, 0, "Масштаб ритейла, логистика; конкуренция жёсткая"),
    "LKOH": (1, -1, -1, -2, 0, -2, "Энергопереход, спрос-плато, рост НДПИ/изъятие"),
    "OZON": (1, 0, 1, -1, 0, 0, "Сетевой эффект растёт, e-com проникновение; НДС/регуляторика"),
    "MDMG": (2, 0, 1, 0, 2, 0, "Демография (старение + переток в платную медицину) — надёжный медленный множитель; консолидатор фрагментированного рынка"),
}

# класс B из базы знаний эмитентов: путь монетизации доказан / платформенный критерий
MONETIZATION_PROVEN = {"OZON", "T", "X5", "SBER", "MDMG"}
PLATFORM = {"OZON"}   # ядро loss-leader, монетизирует экосистема (§3)

# финансы (уровень 2) где есть в Excel: secid → dict
FIN = {
    "SBER": dict(net_profit=1700, equity=7500, roe=0.227, payout=0.50, revenue_growth=0.10,
                 roic=0.227, wacc=0.20, body_trend=0, is_rentier=0, is_resource=0, etype="зрелый"),
    "X5":   dict(net_profit=120, equity=286, roe=0.42, payout=0.90, revenue_growth=0.10,
                 roic=0.2875, wacc=0.20, body_trend=0, is_rentier=0, is_resource=0, etype="зрелый"),
    "YDEX": dict(net_profit=141, equity=390, roe=0.40, payout=0.10, revenue_growth=0.32,
                 roic=0.40, wacc=0.20, body_trend=1, is_rentier=0, is_resource=0, etype="растущий"),
    "MDMG": dict(net_profit=11, equity=50, roe=0.22, payout=0.40, revenue_growth=0.18,
                 roic=0.22, wacc=0.20, body_trend=1, is_rentier=0, is_resource=0, etype="растущий"),
    "PRMD": dict(net_profit=7.2, equity=36, roe=0.20, payout=0.10, revenue_growth=0.20,
                 roic=0.18, wacc=0.20, body_trend=1, is_rentier=0, is_resource=0, etype="растущий"),
    "OZPH": dict(net_profit=6.2, equity=33, roe=0.188, payout=0.05, revenue_growth=0.15,
                 roic=0.19, wacc=0.20, body_trend=1, is_rentier=0, is_resource=0, etype="растущий"),
    "OZON": dict(net_profit=49, equity=130, roe=0.27, payout=0.0, revenue_growth=0.20,
                 roic=0.20, wacc=0.20, body_trend=1, is_rentier=0, is_resource=0, etype="растущий"),
    "LKOH": dict(net_profit=850, equity=6000, roe=0.14, payout=0.90, revenue_growth=0.03,
                 roic=0.15, wacc=0.18, body_trend=-1, is_rentier=1, is_resource=1, etype="ликвидационный"),
    "GAZP": dict(net_profit=600, equity=15000, roe=0.04, payout=0.50, revenue_growth=0.0,
                 roic=0.05, wacc=0.18, body_trend=-1, is_rentier=1, is_resource=1, etype="кризис"),
    "TATN": dict(net_profit=200, equity=900, roe=0.22, payout=0.80, revenue_growth=0.0,
                 roic=0.20, wacc=0.18, body_trend=0, is_rentier=1, is_resource=1, etype="зрелый"),
}


# Экспертная ретроспектива: лет устойчивого ROIC ≥ WACC (для маркеров качества,
# пока financials_history не накопит реальную серию снапшотами). Голубые фишки —
# стабильны 5-10 лет; недавние IPO / структурно слабые — <5. Оценка, не точные данные.
PROVEN_ROIC = {
    "SBER": 10, "LKOH": 10, "TATN": 8, "GMKN": 8, "NVTK": 7, "MOEX": 7, "SIBN": 7,
    "PLZL": 6, "PHOR": 6, "ROSN": 6, "MTSS": 6, "MGNT": 6, "BSPB": 6, "TRNFP": 6,
    "CHMF": 5, "X5": 5, "MDMG": 4, "HEAD": 4, "T": 4, "SVCB": 3, "YDEX": 3,
    "PRMD": 2, "OZPH": 2, "GAZP": 2, "OZON": 0,
}

# валютный профиль (#11): EXPORTER (выручка в валюте — хедж девальвации) | DOMESTIC | MIXED.
# Из базы знаний: X5/Сбер/Т/Озон/MDMG = DOMESTIC. Сырьевики/рентье = EXPORTER (по is_resource).
CURRENCY = {
    "X5": "DOMESTIC", "SBER": "DOMESTIC", "T": "DOMESTIC", "OZON": "DOMESTIC", "MDMG": "DOMESTIC",
    "YDEX": "DOMESTIC", "MTSS": "DOMESTIC", "BSPB": "DOMESTIC", "SVCB": "DOMESTIC", "HEAD": "DOMESTIC",
    "PRMD": "DOMESTIC", "OZPH": "DOMESTIC", "MOEX": "DOMESTIC", "VTBR": "DOMESTIC",
}


def _currency_profile(secid: str, finrow: dict) -> str:
    if secid in CURRENCY:
        return CURRENCY[secid]
    if finrow.get("is_resource") or finrow.get("is_rentier"):
        return "EXPORTER"
    return "MIXED"


def seed_static() -> dict:
    """Залить статические данные модели в БД (без обращения к сети)."""
    init_db()
    now = datetime.now().isoformat(timespec="seconds")
    with get_db() as db:
        for secid, name, sector, dy, g, comp, mult in TOP:
            upsert(db, "issuers", dict(
                secid=secid, shortname=name, latname="", sector=sector,
                board="TQBR", issuesize=None, is_pref=1 if "пр" in name else 0,
            ), pk="secid")
            fin = dict(secid=secid, period="2025", g_base=g, compression=comp,
                       source="Excel: ТОП-25", updated_at=now)
            fin.update(FIN.get(secid, {}))
            if secid in PROVEN_ROIC:
                fin["proven_roic_years"] = PROVEN_ROIC[secid]
            fin["currency_profile"] = _currency_profile(secid, FIN.get(secid, {}))
            upsert(db, "financials", fin, pk="secid")
            # стартовая дивдоходность из Excel (перезапишется живой из MOEX)
            upsert(db, "market_data", dict(
                secid=secid, price=None, cap=None, div_yield=dy, fetched_at="Excel",
            ), pk="secid")
            mp = 1 if secid in MONETIZATION_PROVEN else 0
            pf = 1 if secid in PLATFORM else 0
            if secid in STRUCT:
                m, d, t, r, de, go, note = STRUCT[secid]
                upsert(db, "structural", dict(
                    secid=secid, moat=m, disruption=d, tam=t, regulation=r,
                    demo=de, gosnaves=go, mult_seed=mult, note=note,
                    monetization_proven=mp, is_platform=pf,
                    updated_by="seed", updated_at=now,
                ), pk="secid")
            else:
                upsert(db, "structural", dict(
                    secid=secid, moat=0, disruption=0, tam=0, regulation=0,
                    demo=0, gosnaves=0, mult_seed=mult,
                    monetization_proven=mp, is_platform=pf,
                    note="seed: множитель из ТОП-25, баллы не детализированы",
                    updated_by="seed", updated_at=now,
                ), pk="secid")
    return {"issuers": len(TOP), "structural_detailed": len(STRUCT), "financials": len(FIN)}


def refresh_market(secids: list[str] | None = None) -> dict:
    """Подтянуть живые цену/капу/дивдоходность из MOEX и записать снимок."""
    client = MoexClient()
    try:
        quotes = {q.secid: q for q in client.list_quotes()}
        now = datetime.now().isoformat(timespec="seconds")
        updated, missing = 0, []
        with get_db() as db:
            targets = secids or [r["secid"] for r in db.execute("SELECT secid FROM issuers")]
            for secid in targets:
                q = quotes.get(secid)
                if not q:
                    missing.append(secid)
                    continue
                da = client.dividend_analysis(secid, q.price)
                dy = da["ttm_yield"]
                div_typical = da["typical_yield"]
                div_spike = 1 if da["is_spike"] else 0
                # не затираем дивдоходность из Excel нулём (нет закрытия реестра за TTM)
                if not dy:
                    prev = db.execute(
                        "SELECT div_yield FROM market_data WHERE secid = ?", (secid,)
                    ).fetchone()
                    dy = prev["div_yield"] if prev else None
                upsert(db, "issuers", dict(secid=secid, latname=q.latname,
                                           issuesize=q.issuesize), pk="secid")
                upsert(db, "market_data", dict(
                    secid=secid, price=q.price, cap=q.cap, div_yield=dy,
                    div_typical=div_typical, div_spike=div_spike, fetched_at=now,
                ), pk="secid")
                # сохранить дивиденды
                for d in client.dividends(secid):
                    upsert(db, "dividends", dict(
                        secid=secid, reg_date=d.reg_date, value=d.value,
                        currency=d.currency), pk="secid, reg_date")
                updated += 1
        return {"updated": updated, "missing": missing}
    finally:
        client.close()


def refresh_fundamentals(secids: list[str] | None = None) -> dict:
    """Обновить фундаментал уровня 2 (ROE, прибыль, payout, капитал) из T-Invest.

    Дополняет ручной seed: обновляет только пришедшие поля, не затирая
    модельные (g_base, compression, wacc, body_trend). Без токена — graceful skip.
    """
    from app.data.tinvest import get_token, TinvestClient
    token = get_token()
    if not token:
        return {"error": "TINVEST_TOKEN не задан. Положи токен в переменную "
                "окружения TINVEST_TOKEN или в файл .tinvest_token в корне проекта."}
    client = TinvestClient(token)
    now = datetime.now().isoformat(timespec="seconds")
    try:
        with get_db() as db:
            targets = secids or [r["secid"] for r in db.execute("SELECT secid FROM issuers")]
            uid_to_secid: dict[str, str] = {}
            errors: list[str] = []
            for secid in targets:
                try:
                    uid = client.asset_uid(secid)
                    if uid:
                        uid_to_secid[uid] = secid
                    else:
                        errors.append(f"{secid}: asset_uid не найден")
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{secid}: {type(e).__name__}")
            funds = client.get_fundamentals(list(uid_to_secid))
            updated = 0
            skipped: list[str] = []
            for f in funds:
                secid = uid_to_secid.get(f.get("assetUid"))
                if not secid:
                    continue
                d = client.parse(secid, f)
                # ЗАЩИТА от РСБУ-искажения холдингов: T-Invest для холдингов отдаёт
                # РСБУ материнской компании (убыток от переоценки дочек), а не МСФО
                # группы. Если прибыль отрицательна, НО эмитент платит дивиденды
                # (признак МСФО-прибыльности) — не затираем прежнюю/ручную прибыль.
                if d.net_profit_bln is not None and d.net_profit_bln < 0:
                    mrow = db.execute(
                        "SELECT div_yield FROM market_data WHERE secid = ?", (secid,)
                    ).fetchone()
                    dy = mrow["div_yield"] if mrow else None
                    if dy and dy > 0:
                        skipped.append(f"{secid} (РСБУ-убыток {d.net_profit_bln:.0f} "
                                       f"млрд при дивдох {dy*100:.0f}% — оставлена МСФО)")
                        continue
                patch = {"secid": secid, "source": "T-Invest API", "updated_at": now}
                if d.net_profit_bln is not None:
                    patch["net_profit"] = round(d.net_profit_bln, 2)
                if d.roe is not None:
                    patch["roe"] = round(d.roe, 4)
                if d.payout is not None:
                    patch["payout"] = round(d.payout, 4)
                if d.equity_bln is not None:
                    patch["equity"] = round(d.equity_bln, 1)
                if d.roic is not None:
                    patch["roic"] = round(d.roic, 4)
                upsert(db, "financials", patch, pk="secid")
                updated += 1
            return {"updated": updated, "mapped": len(uid_to_secid),
                    "skipped_rsbu": skipped, "errors": errors[:10],
                    "source": "T-Invest GetAssetFundamentals"}
    finally:
        client.close()


def refresh_macro() -> dict:
    """Обновить макроданные из ЦБ: ключевая ставка (SOAP, надёжно) +
    инфляция (best-effort парсинг). При сбое поля не затираются (fallback на БД).
    """
    from app.data.cbr import fetch_key_rate, fetch_inflation
    kr = fetch_key_rate()
    infl = fetch_inflation()
    now = datetime.now().isoformat(timespec="seconds")
    with get_db() as db:
        macro_updates = {}
        if kr is not None:
            macro_updates["key_rate"] = kr
        if infl is not None:
            macro_updates["cpi_official"] = infl
        if macro_updates:
            cols = ", ".join(f"{k} = ?" for k in macro_updates)
            db.execute(f"UPDATE macro SET {cols}, updated_at = ? WHERE id = 1",
                       (*macro_updates.values(), now))
        # rosstat_current — в user_settings (источник дефлятора)
        if infl is not None:
            db.execute("UPDATE user_settings SET rosstat_current = ? WHERE id = 1", (infl,))
    return {"key_rate": kr, "cpi_official": infl,
            "key_rate_source": "ЦБ SOAP (надёжно)",
            "cpi_source": "ЦБ hd_base (best-effort)" if infl is not None else "сбой — оставлено прежнее"}


if __name__ == "__main__":
    print("seed_static:", seed_static())
    print("refresh_market:", refresh_market())
    print("refresh_macro:", refresh_macro())
