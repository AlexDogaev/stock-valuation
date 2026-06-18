"""Сервисный слой: соединяет данные БД с расчётным ядром.

Прозрачность (SPEC §6): каждая входная метрика — с источником и датой;
карточка включает все промежуточные величины (g, сжатие, full_nominal, real,
спред r−g, confidence), структурный балл с разбивкой, итоговый сигнал.
Расчётные величины НЕ хранятся — считаются на лету (смена настроек → пересчёт).
"""
from __future__ import annotations

import sqlite3
from typing import Any

from app.config import FORECAST_YEARS, DEFAULTS
from app.core import valuation, structural, classify, rate, quality_markers, decision
from app.data.db import get_db, get_settings, get_macro, roic_years


# ── дефлятор реальной доходности = ОЩУЩАЕМАЯ инфляция (вводится вручную) ──────
def active_deflator_value(settings: dict) -> float:
    """Дефлятор = ощущаемая инфляция из настроек (заменила пресеты тактич./стратег.)."""
    fi = settings.get("felt_inflation")
    return fi if fi is not None else DEFAULTS["felt_inflation"]


# ── структурный множитель: детальные баллы или seed ──────────────────────────
def structural_for(srow: sqlite3.Row | dict) -> tuple[structural.StructuralResult, float, bool]:
    """Возвращает (результат структурного слоя, эффективный множитель, детальный?).

    Если все баллы нулевые, но задан mult_seed — берём seed (недетализировано).
    Иначе считаем множитель из баллов (детальная оценка).
    """
    s = dict(srow)
    scores = (s.get("moat", 0), s.get("disruption", 0), s.get("tam", 0),
              s.get("regulation", 0), s.get("demo", 0))
    detailed = any(scores)
    res = structural.evaluate_structural(
        moat=s.get("moat", 0), disruption=s.get("disruption", 0),
        tam=s.get("tam", 0), regulation=s.get("regulation", 0),
        demo=s.get("demo", 0), gosnaves=s.get("gosnaves", 0),
        is_rentier=bool(s.get("is_rentier", 0)),
    )
    if detailed:
        return res, res.multiplier, True
    seed = s.get("mult_seed")
    return res, (seed if seed is not None else 1.0), False


# ── макро-поправка hurdle: здоровье ФНБ + риск ШОКа → системная риск-премия ──
MACRO_F0, MACRO_BONUS, MACRO_PENALTY = 0.30, 0.015, 0.030  # нейтраль / бонус(здорово) / штраф(хрупко)
SHOCK_NO_BUY = 80.0  # риск ШОКа ≥ этого % — покупать вообще нет смысла (жёсткий потолок)


def macro_fragility(db: sqlite3.Connection) -> dict:
    """Индекс хрупкости макро ∈[0,1] из ФНБ (deval_score) + риска ШОКа (%). Считать ОДИН раз."""
    deval, regime, shock_pct = 0, "NORMAL", None
    try:
        from app.data.minfin import current_regime
        reg = current_regime()
        deval = reg.get("deval_score") or 0
        regime = reg.get("regime") or "NORMAL"
    except Exception:  # noqa: BLE001 — макро не должно ронять оценку
        pass
    try:
        from app.core import llm_macro
        sh = llm_macro.get_shock(db)
        shock_pct = (sh or {}).get("aggregate_pct")
    except Exception:  # noqa: BLE001
        pass
    f_nwf = min(max(deval / 6.0, 0.0), 1.0)
    f_shock = min(max(((shock_pct or 0.0) - 15.0) / 25.0, 0.0), 1.0)
    return {"F": 0.5 * f_nwf + 0.5 * f_shock, "regime": regime,
            "deval_score": deval, "shock_pct": shock_pct}


def macro_hurdle_delta(F: float, qmark: str) -> float:
    """Поправка к реальному hurdle: здорово → ниже (агрессивнее), хрупко → выше.
    Штраф хрупкости меньше для качества (барбелл: качество добираем и в напряжении)."""
    if F <= MACRO_F0:
        return -MACRO_BONUS * (MACRO_F0 - F) / MACRO_F0
    q = 0.4 if qmark in ("PROVEN_QUALITY", "PROSPECTIVE_QUALITY") else 1.0
    return MACRO_PENALTY * (F - MACRO_F0) / (1.0 - MACRO_F0) * q


# ── полный прогон одного эмитента ────────────────────────────────────────────
def evaluate_issuer(db: sqlite3.Connection, secid: str, macro_frag: dict | None = None) -> dict[str, Any] | None:
    row = db.execute(
        """SELECT i.secid, i.shortname, i.sector,
                  m.price, m.cap, m.div_yield, m.div_typical, m.div_spike, m.fetched_at,
                  f.g_base, f.compression, f.roe, f.payout, f.equity,
                  f.roic, f.wacc, f.body_trend, f.revenue_growth, f.etype,
                  f.is_rentier, f.is_resource, f.net_profit, f.source AS fin_source,
                  s.moat, s.disruption, s.tam, s.regulation, s.demo, s.gosnaves,
                  s.mult_seed, s.note AS struct_note, s.monetization_proven, s.is_platform,
                  f.needs_review
           FROM issuers i
           LEFT JOIN market_data m ON m.secid = i.secid
           LEFT JOIN financials f ON f.secid = i.secid
           LEFT JOIN structural s ON s.secid = i.secid
           WHERE i.secid = ?""",
        (secid.upper(),),
    ).fetchone()
    if row is None:
        return None
    r = dict(row)

    settings = get_settings(db)
    macro = get_macro(db)
    deflator = active_deflator_value(settings)

    struct_res, mult, detailed = structural_for(r)

    div_yield = r["div_yield"] or 0.0
    g_base = r["g_base"] or 0.0
    compression = r["compression"] if r["compression"] is not None else 1.0

    # калибровка разового дивиденда (спайк): сигнал/реал считаем на УСТОЙЧИВОЙ
    # дивдоходности = payout × прибыль / капа (≡ payout/PE), а не на TTM-выплате,
    # которая могла включать догоняющий/спецдивиденд. Без прибыли — на типичной
    # исторической; иначе на фактической. Дисплей показывает фактическую TTM.
    div_spike = bool(r["div_spike"])
    div_yield_signal = div_yield
    if div_spike:
        np_, cap_, po_ = r["net_profit"], r["cap"], r["payout"]
        if po_ is not None and np_ and np_ > 0 and cap_:
            sustainable = po_ * np_ / (cap_ / 1e9)
        elif r["div_typical"]:
            sustainable = r["div_typical"]
        else:
            sustainable = 0.0
        div_yield_signal = min(div_yield, max(0.0, sustainable))

    # маркер качества — нужен ДО сигнала (для гейта и макро-поправки hurdle)
    qmark = quality_markers.quality_marker(
        structural_score=struct_res.score, roic_years=roic_years(db, r["secid"]),
        payout=r["payout"], revenue_growth=r["revenue_growth"],
        compression=compression, monetization_proven=r["monetization_proven"] or 0,
        is_platform=r["is_platform"] or 0,
    )
    # макро-поправка hurdle: здоровье ФНБ + риск ШОКа (× качество, барбелл).
    # Реализованный ШОК-режим обнуляет hurdle внутри full_return — форвардная
    # осторожность ему уступает (до шторма строже, в шторм — добор качества).
    if macro_frag is None:
        macro_frag = macro_fragility(db)
    macro_delta = macro_hurdle_delta(macro_frag["F"], qmark)
    hurdle_eff = settings["hurdle"] + macro_delta

    # требуемая доходность r (для теста достоверности зоны)
    asset_premium = 0.05 if (r["etype"] or "").startswith("раст") else 0.0
    r_req = rate.default_r(risk_premium=settings["risk_premium"],
                           asset_premium=asset_premium).r

    fr = valuation.full_return(
        div_yield=div_yield_signal, g_base=g_base, compression=compression,
        structural_mult=mult, deflator=deflator,
        hurdle=hurdle_eff, buffer=settings["buffer"],
        regime=settings["regime"], r=r_req,
    )

    # классификация (если есть метрики)
    classification = None
    if r["roic"] is not None and r["wacc"] is not None:
        c = classify.classify(
            body_trend=r["body_trend"] if r["body_trend"] is not None else 0,
            revenue_growth=r["revenue_growth"] or 0.0,
            roic=r["roic"], wacc=r["wacc"], payout=r["payout"] or 0.0,
            structural_score=struct_res.score, inflation=deflator,
        )
        classification = {
            "detailed": c.detailed, "regime": c.regime, "simple": c.simple,
            "phase_n": c.phase_n, "terminal_r": c.terminal_r,
            "roic_minus_wacc": c.roic_minus_wacc,
        }

    # зрелая оценка справедливой капы (если есть ROE/equity)
    mature = None
    if r["roe"] is not None and r["equity"] and r["cap"]:
        try:
            mv = valuation.mature_valuation(
                roe=r["roe"], g=g_base or valuation.sustainable_g(r["roe"], r["payout"] or 0),
                r=r_req, payout=r["payout"] or 0.0, equity=r["equity"],
                current_cap=r["cap"] / 1e9, deflator=deflator,
                hurdle_real=settings["hurdle"],
            )
            mature = {
                "fair_pb": mv.fair_pb, "fair_cap_bln": mv.fair_cap,
                "current_pb": mv.current_pb, "verdict": mv.verdict,
                "implied_nominal": mv.implied_nominal, "implied_real": mv.implied_real,
                "spread": mv.spread, "confidence": mv.confidence,
                "needed_drawdown": mv.needed_drawdown,
            }
        except ValueError:
            mature = {"error": "r ≤ g — зона неоцениваема"}

    # рыночные мультипликаторы: цена, капа, P/E, P/B
    cap_bln = r["cap"] / 1e9 if r["cap"] else None
    net_profit = r["net_profit"]
    equity = r["equity"]
    pe = None
    pe_src = None
    loss = net_profit is not None and net_profit < 0
    if loss:
        pe_src = "убыток TTM (P/E неприменим)"
    elif net_profit and net_profit > 0 and cap_bln:
        pe, pe_src = cap_bln / net_profit, "капа / чистая прибыль"
    elif r["payout"] and div_yield and div_yield > 0:
        # тождество: дивдох = payout/PE → PE = payout/дивдох
        pe, pe_src = r["payout"] / div_yield, "payout / дивдоходность"
    # P/B только при положительном капитале (отриц. капитал → неинформативно)
    pb = cap_bln / equity if (cap_bln and equity and equity > 0) else None
    market = {
        "price": r["price"], "cap_bln": round(cap_bln, 1) if cap_bln else None,
        "pe": round(pe, 1) if pe else None, "pe_source": pe_src,
        "pb": round(pb, 2) if pb else None,
        "net_profit_bln": round(net_profit, 0) if net_profit is not None else None,
        "equity_bln": round(equity, 0) if equity is not None else None,
        "loss": loss, "negative_equity": equity is not None and equity < 0,
        "fetched_at": r["fetched_at"],
    }

    # прогноз на N лет (горизонт из настроек, по умолчанию 3): цена тела + доходность
    n = settings.get("forecast_years") or FORECAST_YEARS
    price_cagr = (1.0 + fr.g_final) * fr.compression - 1.0  # ценовой CAGR (без дивов)
    price_target = r["price"] * (1.0 + price_cagr) ** n if r["price"] else None
    forecast = {
        "years": n,
        "price_cagr": price_cagr,
        "price_now": r["price"],
        "price_target": round(price_target, 2) if price_target else None,
        "price_upside": (1.0 + price_cagr) ** n - 1.0,            # рост котировки
        "total_return": (1.0 + fr.full_nominal) ** n - 1.0,       # с дивидендами
        "real_return": (1.0 + fr.real) ** n - 1.0,                # над инфляцией
    }

    warnings = list(fr.notes) + list(struct_res.warnings)
    if div_spike:
        warnings.append(
            f"Дивдоходность {div_yield*100:.0f}% — разовая выплата (TTM-спайк). Сигнал и "
            f"реальная доходность калиброваны на устойчивую ≈{div_yield_signal*100:.0f}% "
            f"(payout × прибыль / капа).")
    if loss:
        warnings.append("Чистая прибыль TTM отрицательна. У холдингов это часто РСБУ "
                        "материнской компании (≠ МСФО группы) — P/E неприменим, сверь источник.")
    if market["negative_equity"]:
        warnings.append("Отрицательный собственный капитал (накопленные убытки) — "
                        "P/B и ROE неинформативны.")
    if r["is_resource"]:
        warnings.append("Ресурсный: тренд тела (добыча/запасы) проверять вручную.")
    if abs(macro_delta) >= 0.005:
        warnings.append(
            f"Макро-поправка hurdle {macro_delta*100:+.1f}пп "
            f"({'осторожнее' if macro_delta > 0 else 'агрессивнее'}): "
            f"ФНБ деваль {macro_frag['deval_score']}/6, риск ШОКа {macro_frag['shock_pct']}%.")

    # качественный гейт (owner-rule): «обычное» качество НЕ может быть ПОКУПАЙ.
    # Защита от value-trap и завышенного сигнала (фантомные/разовые дивы, дешёвые
    # некачественные имена). Понижаем на одну ступень: ПОКУПАЙ → ГРАНИЦА.
    signal = fr.signal
    if qmark == "ordinary" and signal == "ПОКУПАЙ":
        signal = "ГРАНИЦА"
        warnings.append("Сигнал понижен ПОКУПАЙ→ГРАНИЦА: «обычное» качество не даёт «покупай» "
                        "(защита от value-trap и завышенного сигнала по некачественным именам).")

    # жёсткий потолок: при экстремальном форвардном риске ШОКа покупать нет смысла
    sp_ = macro_frag.get("shock_pct")
    if sp_ is not None and sp_ >= SHOCK_NO_BUY and signal == "ПОКУПАЙ":
        signal = "ВОЗДЕРЖИСЬ"
        warnings.append(f"Сигнал снят ПОКУПАЙ→ВОЗДЕРЖИСЬ: риск ШОКа {sp_:.0f}% ≥ {SHOCK_NO_BUY:.0f}% — "
                        f"системно покупать нет смысла (держать порох сухим до реализации шока).")

    # тест «аванс в цене» (§7): какую прибыль имплицирует капа при нормальном P/E.
    # Убыток/околоноль или кратное превышение → оптимизм заложен в цену.
    opt = valuation.optimism_priced_in(cap_bln=cap_bln, net_profit_bln=net_profit)
    optimism_flag = bool(opt and opt.flag)
    if opt and opt.flag:
        if opt.ratio is None:
            warnings.append(
                f"Аванс в цене (§7): капа имплицирует ≈{opt.implied_profit:.0f} млрд прибыли "
                f"(при P/E {opt.normal_pe:.0f}) против убытка/околонуля TTM — оптимизм заложен в "
                f"цену, апсайд только при ПРЕВЫШЕНИИ заложенного.")
        else:
            warnings.append(
                f"Аванс в цене (§7): капа имплицирует ≈{opt.implied_profit:.0f} млрд прибыли "
                f"(при P/E {opt.normal_pe:.0f}) — ×{opt.ratio:.1f} к текущей; оптимизм заложен в цену.")

    # матрица §1: вердикт = пересечение [маркер качества] × [зона цены].
    # Зона из сигнала (буфер = margin of safety); «оптимизм в цене» (§7) → expensive.
    zone = decision.price_zone(signal=signal, optimism_priced_in=optimism_flag)
    action = decision.matrix_action(qmark=qmark, zone=zone, signal=signal)
    if action in decision.WATCHLIST_ACTIONS:
        warnings.append(
            "Качество при отрицательной margin of safety → «список ожидания на обвал», не покупка: "
            "восхититься бизнесом — да, купить на блеске — нет (добор на обвале, когда выйдет аванс).")

    return {
        "secid": r["secid"],
        "name": r["shortname"],
        "sector": r["sector"],
        "type": r["etype"],
        "inputs": {
            "price": {"value": r["price"], "source": "MOEX ISS", "date": r["fetched_at"]},
            "cap_bln": {"value": round(r["cap"] / 1e9, 1) if r["cap"] else None,
                        "source": "MOEX ISS", "date": r["fetched_at"]},
            "div_yield": {"value": div_yield, "source": r["fetched_at"] if div_yield else "Excel/MOEX",
                          "spike": div_spike, "typical": r["div_typical"], "signal_value": div_yield_signal},
            "g_base": {"value": g_base, "source": r["fin_source"] or "Excel"},
            "compression": {"value": compression, "source": "модель"},
            "roe": {"value": r["roe"], "source": "Excel (ур.2)"},
            "payout": {"value": r["payout"], "source": "Excel (ур.2)"},
            "r_required": {"value": round(r_req, 4), "source": "лист «Ставка r»"},
        },
        "structural": {
            "moat": struct_res.moat, "disruption": struct_res.disruption,
            "tam": struct_res.tam, "regulation": struct_res.regulation,
            "demo": struct_res.demo, "gosnaves": struct_res.gosnaves,
            "score": struct_res.score, "zone": struct_res.zone,
            "multiplier": mult, "detailed": detailed,
            "monetization_proven": bool(r["monetization_proven"]),
            "is_platform": bool(r["is_platform"]),
            "note": r["struct_note"], "warnings": struct_res.warnings,
        },
        "calc": {
            "g_final": fr.g_final, "compression": fr.compression,
            "full_nominal": fr.full_nominal, "deflator": deflator,
            "real": fr.real, "confidence": fr.confidence,
        },
        "market": market,
        "forecast": forecast,
        "signal": signal,
        "action": action,
        "price_zone": zone,
        "price_zone_label": decision.ZONE_LABELS_RU[zone],
        "optimism_priced_in": optimism_flag,
        "optimism": ({"implied_profit_bln": round(opt.implied_profit, 0),
                      "current_profit_bln": opt.current_profit,
                      "ratio": round(opt.ratio, 1) if opt.ratio is not None else None,
                      "normal_pe": opt.normal_pe} if opt else None),
        "quality_marker": qmark,
        "quality_label": quality_markers.LABELS_RU[qmark],
        "macro_adj": {"delta_pp": round(macro_delta * 100, 2), "fragility": round(macro_frag["F"], 2),
                      "deval_score": macro_frag["deval_score"], "shock_pct": macro_frag["shock_pct"]},
        "needs_review": bool(r["needs_review"]),
        "real_return": fr.real,
        "classification": classification,
        "mature": mature,
        "warnings": warnings,
    }


def generate_backtest(db: sqlite3.Connection, client, horizons=(1, 2, 3)) -> dict:
    """Backtest на истории MOEX (лист «Backtest»).

    Для каждого эмитента с фундаменталом и каждого горизонта h лет:
      • realized — фактический номинальный CAGR из истории цен MOEX + дивиденды
        за период (реальные данные);
      • predicted — implied номинальная доходность модели на исторической цене.

    ВАЖНОЕ ДОПУЩЕНИЕ: predicted считается с ТЕКУЩИМ фундаменталом (ROE/g/payout),
    т.к. архива исторической отчётности нет. Это смещает оценку — настоящая
    проверка предсказательности требует фундаментала НА ДАТУ входа. Поэтому
    результат — иллюстрация механизма, а не доказательство предсказательной силы.
    """
    from app.core import backtest as bt
    from datetime import date, timedelta

    settings = get_settings(db)
    r_req = rate.default_r(risk_premium=settings["risk_premium"]).r
    today = date.today()

    rows = db.execute(
        """SELECT f.secid, i.shortname, f.roe, f.payout, f.g_base, f.equity, i.issuesize
           FROM financials f JOIN issuers i ON i.secid = f.secid
           WHERE f.roe IS NOT NULL AND f.equity IS NOT NULL AND i.issuesize IS NOT NULL
           ORDER BY f.secid"""
    ).fetchall()

    cases: list[tuple[str, float, float]] = []
    skipped: list[str] = []
    max_h = max(horizons)
    for row in rows:
        r = dict(row)
        hist = client.history_close(r["secid"], days=max_h * 365 + 45)
        if len(hist) < 30:
            skipped.append(r["secid"])
            continue
        hist.sort(key=lambda x: x[0])
        now_date, price_now = hist[-1]
        divs = client.dividends(r["secid"])
        g = r["g_base"] or valuation.sustainable_g(r["roe"], r["payout"] or 0)
        for h in horizons:
            target = (today - timedelta(days=h * 365)).isoformat()
            then = next(((d, p) for d, p in hist if d >= target), None)
            if then is None or then[1] <= 0:
                continue
            then_date, price_then = then
            div_total = sum(
                d.value for d in divs
                if d.currency in ("RUB", "SUR") and then_date <= d.reg_date <= now_date
            )
            realized = ((price_now + div_total) / price_then) ** (1.0 / h) - 1.0
            cap_then_bln = price_then * r["issuesize"] / 1e9
            try:
                mv = valuation.mature_valuation(
                    roe=r["roe"], g=g, r=r_req, payout=r["payout"] or 0.0,
                    equity=r["equity"], current_cap=cap_then_bln)
                predicted = mv.implied_nominal
            except (ValueError, ZeroDivisionError):
                continue
            if predicted is None:
                continue
            cases.append((f"{r['shortname']} · {h}г ({then_date}→{now_date})",
                          round(predicted, 4), round(realized, 4)))

    summary = bt.run_backtest(cases)
    from dataclasses import asdict
    out = asdict(summary)
    out["skipped"] = skipped
    out["assumption"] = (
        "predicted считается с ТЕКУЩИМ фундаменталом (архива отчётности нет) — "
        "это смещение. Realized — фактические данные MOEX. Настоящая проверка "
        "предсказательности требует фундаментала на дату входа."
    )
    return out


def screen_all(db: sqlite3.Connection) -> list[dict]:
    secids = [r["secid"] for r in db.execute("SELECT secid FROM issuers ORDER BY secid")]
    macro = macro_fragility(db)  # один раз на всю вселенную (не дёргать MOEX по 50×)
    out = []
    for secid in secids:
        res = evaluate_issuer(db, secid, macro_frag=macro)
        if res:
            out.append(res)
    # сортировка по реальной доходности (лучшие сверху)
    out.sort(key=lambda x: (x["real_return"] is None, -(x["real_return"] or -99)))
    return out
