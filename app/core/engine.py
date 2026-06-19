"""Сервисный слой: соединяет данные БД с расчётным ядром.

Прозрачность (SPEC §6): каждая входная метрика — с источником и датой;
карточка включает все промежуточные величины (g, сжатие, full_nominal, real,
спред r−g, confidence), структурный балл с разбивкой, итоговый сигнал.
Расчётные величины НЕ хранятся — считаются на лету (смена настроек → пересчёт).
"""
from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

from app.config import FORECAST_YEARS, DEFAULTS
from app.core import valuation, structural, classify, rate, quality_markers, decision, tax, tectonic
from app.data.db import get_db, get_settings, get_macro, roic_years


# ── дефлятор = ощущаемая инфляция с учётом траектории снижения КС за горизонт ──
def terminal_inflation(settings: dict, db: sqlite3.Connection | None = None) -> float | None:
    """Терминальная инфляция: из Opus-градации траектории КС (приоритет) или вручную.

    Если есть оценка траектории КС с терминальной ставкой — инфляция = КС − реальный
    спред (rate_trajectory). Иначе ручная настройка inflation_terminal.
    """
    if db is not None:
        try:
            from app.core import llm_macro, rate_trajectory as rt
            tr = llm_macro.get_rate_trajectory(db)
            if tr and tr.get("terminal_ks") is not None:
                return rt.terminal_inflation_from_ks(tr["terminal_ks"])
        except Exception:  # noqa: BLE001 — траектория не должна ронять оценку
            pass
    return settings.get("inflation_terminal")


def active_deflator_value(settings: dict, db: sqlite3.Connection | None = None) -> float:
    """Эффективный дефлятор за горизонт: глайд от ощущаемой (год 1) к терминальной.

    Терминал — из траектории КС (Opus) или ручной. Геом. среднее по траектории
    (valuation.horizon_deflator). Горизонт 1 год или терминал = текущей → плоско.
    """
    felt = settings.get("felt_inflation")
    felt = felt if felt is not None else DEFAULTS["felt_inflation"]
    years = settings.get("forecast_years") or FORECAST_YEARS
    return valuation.horizon_deflator(felt, terminal_inflation(settings, db), years)


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


# валютный множитель штрафа хрупкости (#10/#14): экспортёру девальвация — В ПЛЮС
# (выручка в валюте), поэтому в хрупком макро его штрафуем меньше; внутреннее имя — полный
# штраф (в RISK режут первым). Спит при здоровом макро (F≤F0 → бонус общий).
CURRENCY_FRAGILITY = {"EXPORTER": 0.3, "MIXED": 0.7, "DOMESTIC": 1.0}


def macro_hurdle_delta(F: float, qmark: str, currency_profile: str = "MIXED") -> float:
    """Поправка к реальному hurdle: здорово → ниже (агрессивнее), хрупко → выше.
    Штраф хрупкости меньше для качества (барбелл) И для экспортёров (хедж девальвации)."""
    if F <= MACRO_F0:
        return -MACRO_BONUS * (MACRO_F0 - F) / MACRO_F0
    q = 0.4 if qmark in ("PROVEN_QUALITY", "PROSPECTIVE_QUALITY") else 1.0
    cur = CURRENCY_FRAGILITY.get(currency_profile, 0.7)
    return MACRO_PENALTY * (F - MACRO_F0) / (1.0 - MACRO_F0) * q * cur


# ── полный прогон одного эмитента ────────────────────────────────────────────
def evaluate_issuer(db: sqlite3.Connection, secid: str, macro_frag: dict | None = None) -> dict[str, Any] | None:
    row = db.execute(
        """SELECT i.secid, i.shortname, i.sector,
                  m.price, m.cap, m.div_yield, m.div_typical, m.div_spike, m.fetched_at,
                  f.g_base, f.compression, f.roe, f.payout, f.equity,
                  f.roic, f.wacc, f.body_trend, f.revenue_growth, f.etype,
                  f.is_rentier, f.is_resource, f.net_profit, f.source AS fin_source, f.currency_profile,
                  s.moat, s.disruption, s.tam, s.regulation, s.demo, s.gosnaves,
                  s.mult_seed, s.note AS struct_note, s.monetization_proven, s.is_platform,
                  s.moat_risk, s.is_enabler,
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
    deflator = active_deflator_value(settings, db)

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
    currency_profile = r["currency_profile"] or "MIXED"
    # тектоническая поправка к g (рама §1-7): сектор × ТЕКУЩАЯ пятилетка, маршрут по валюте.
    # EXPORTER → 0 (РФ-демография в их спрос не идёт). Коридор −1.5…+3пп (намеренно скромен —
    # тектоника двигает g медленно; щедрый множитель задвоил бы то, что рынок уже знает).
    tect = tectonic.tectonic_g(r["sector"], currency_profile, year=date.today().year, secid=r["secid"])
    g_eff = g_base + tect.sector_delta
    macro_delta = macro_hurdle_delta(macro_frag["F"], qmark, currency_profile)
    hurdle_eff = settings["hurdle"] + macro_delta

    # требуемая доходность r (для теста достоверности зоны)
    asset_premium = 0.05 if (r["etype"] or "").startswith("раст") else 0.0
    r_req = rate.default_r(risk_premium=settings["risk_premium"],
                           asset_premium=asset_premium).r

    fr = valuation.full_return(
        div_yield=div_yield_signal, g_base=g_eff, compression=compression,
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

    # посленалоговый слой (§5): дивы −налог ежегодно; курсовой рост — ЛДВ освобождает при
    # горизонте ≥3г / ИИС-3. Сигнал и сравнение с hurdle — на ПОСЛЕналоговой основе
    # (tax_aware), иначе валовое сравнение завышает дивидендные имена против ростовых.
    price_comp = fr.full_nominal - div_yield_signal
    _tr = settings.get("tax_rate")
    at = tax.after_tax(div_yield=div_yield_signal, price_component=price_comp, years=n,
                       tax_rate=_tr if _tr is not None else DEFAULTS["tax_rate"],
                       iis3=bool(settings.get("iis3", 0)))
    at_real = valuation.real_return(at.after_tax_nominal, deflator)
    tax_aware = bool(settings.get("tax_aware", 1))
    eff_real = at_real if tax_aware else fr.real

    price_cagr = (1.0 + fr.g_final) * fr.compression - 1.0  # ценовой CAGR (без дивов)
    price_target = r["price"] * (1.0 + price_cagr) ** n if r["price"] else None
    forecast = {
        "years": n,
        "price_cagr": price_cagr,
        "price_now": r["price"],
        "price_target": round(price_target, 2) if price_target else None,
        "price_upside": (1.0 + price_cagr) ** n - 1.0,            # рост котировки
        "total_return": (1.0 + fr.full_nominal) ** n - 1.0,       # с дивидендами (валовое)
        "real_return": (1.0 + eff_real) ** n - 1.0,               # над инфляцией, посленалогово
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
    if macro_frag["F"] > MACRO_F0 and currency_profile != "MIXED":
        warnings.append(
            "Экспортёр (выручка в валюте): девальвация в плюс — штраф макро снижен, в RISK ДЕРЖАТЬ как хедж."
            if currency_profile == "EXPORTER" else
            "Внутреннее имя: нет валютного хеджа — полный штраф макро, в RISK режут первым.")
    if abs(tect.sector_delta) >= 0.003:
        warnings.append(
            f"Тектоника (рама §1-7): {tect.note}. g скорректирован {tect.sector_delta*100:+.1f}пп; "
            f"базовый g рынка {tect.g_market_base*100:.1f}% реальн. ({tect.period}). NB §2: демография — "
            f"top-down, per-эмитентный demo-балл должен быть РЕЗИДУАЛЬНЫМ (открытая калибровка §13).")
    if (r["moat_risk"] or 0) >= 1:
        warnings.append(
            f"Уязвимость рва к дизрупции (§4/§9, уровень {r['moat_risk']}/2): технология — фактор РИСКА "
            f"(защита рва, НЕ в g); не переоценивать. Расщепление: «волна придёт» детерминир., кто/когда — гадание.")
    if r["is_enabler"]:
        warnings.append("ENABLER (инфраструктура-рельса): рента устойчивее звёзд конкретной волны — «лопаты в золотую лихорадку».")
    # госнавес-риск перераспределения на дивиденды (§7 NOTES_2) — флаг на высокодивидендные
    if (r["payout"] or 0) >= 0.4:
        warnings.append(
            "Госнавес-риск перераспределения (§7): цель Джини 0.37/2030 + ИИ-неравенство → риск роста "
            "налогов на капитал/дивиденды/прибыль (введён прогрессивный НДФЛ-2025). Прямой вычет из "
            "дивдоходности при реализации — держать как риск-флаг на дивидендную историю (политически реверсивно).")
    if r["sector"] == "Ритейл":
        warnings.append(
            "Потребительский барбелл (§7): поляризация доходов (КС-процикличная) → премиум+жёсткий дискаунтер "
            "попутны, середина вымывается. МУЛЬТИФОРМАТ (X5: Чижик+у-дома+Перекрёсток) выигрывает с обоих концов.")
    if r["sector"] == "Ритейл" or r["is_platform"]:
        warnings.append(
            "География (NOTES_3): рынок РФ считать ПО УЗЛАМ (Москва-плато+Питер+Юг+Кавказ), не по карте — "
            "~84% городов выпадают из живой экономики. Агломерация = ПЕРЕРАСПРЕДЕЛЕНИЕ сжимающегося пирога "
            "(не китайский рост): консолидатор берёт долю, пирог географически стягивается. Логистический РОВ "
            "(масштаб РФ) — непробиваемый физбарьер маркетплейсов/ритейла, ИИ-волной не смывается (контраст с tech).")
    _felt = settings.get("felt_inflation") or DEFAULTS["felt_inflation"]
    _term = terminal_inflation(settings, db)
    _yrs = settings.get("forecast_years") or FORECAST_YEARS
    if _term is not None and _yrs > 1 and abs(_term - _felt) > 0.001:
        _src = ""
        try:
            from app.core import llm_macro
            _tr = llm_macro.get_rate_trajectory(db)
            if _tr and _tr.get("terminal_ks") is not None:
                _src = f"; траектория КС: {_tr['grade']} → терминал {_tr['terminal_ks']*100:.1f}%"
        except Exception:  # noqa: BLE001
            pass
        warnings.append(
            f"Дефлятор {deflator*100:.1f}% — среднее по траектории за {_yrs}г "
            f"(инфляция {_felt*100:.1f}%→{_term*100:.1f}%{_src}), не плоские {_felt*100:.1f}%.")

    if tax_aware and abs(fr.real - at_real) > 0.003:
        warnings.append(
            f"Посленалогово: реал {fr.real*100:.1f}%→{at_real*100:.1f}% "
            f"({at.note}); сигнал и сравнение с таргетом — на чистой основе.")

    # сигнал — троичный на ЭФФЕКТИВНОЙ (посленалоговой при tax_aware) реальной доходности
    signal = valuation.ternary_signal(
        eff_real, valuation.effective_hurdle(hurdle_eff, settings["regime"]), settings["buffer"])
    # качественный гейт (owner-rule): «обычное» качество НЕ может быть ПОКУПАЙ.
    # Защита от value-trap и завышенного сигнала (фантомные/разовые дивы, дешёвые
    # некачественные имена). Понижаем на одну ступень: ПОКУПАЙ → ГРАНИЦА.
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
            "moat_risk": r["moat_risk"] or 0, "is_enabler": bool(r["is_enabler"]),
            "note": r["struct_note"], "warnings": struct_res.warnings,
        },
        "calc": {
            "g_final": fr.g_final, "compression": fr.compression,
            "full_nominal": fr.full_nominal, "deflator": deflator,
            "real": fr.real, "confidence": fr.confidence,
            "real_after_tax": at_real, "tax_aware": tax_aware,
            "after_tax_nominal": at.after_tax_nominal, "growth_exempt": at.growth_exempt,
            "tax_note": at.note,
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
        "currency_profile": currency_profile,
        "tectonic": {"period": tect.period, "g_market_base": tect.g_market_base,
                     "sector_delta": tect.sector_delta, "routed": tect.routed,
                     "peak_period": tect.peak_period, "note": tect.note},
        "real_return": eff_real,
        "classification": classification,
        "mature": mature,
        "warnings": warnings,
    }


def screen_bonds(db: sqlite3.Connection) -> dict:
    """Скринер облигаций (фаза 2 мультиассета): ОФЗ-кривая из самих ОФЗ → спред корпоратов →
    PD из спреда → троичный сигнал (общий hurdle/инфляция/траектория КС, как у акций)."""
    from app.data import moex_bonds as mb
    from app.core import bonds as bmod, credit_pd
    settings = get_settings(db)
    e_infl = active_deflator_value(settings, db)
    # Бонды = ЗАЩИТНЫЙ рукав: бар = бить инфляцию (real≥0) + кредит, НЕ +10% таргет атаки (акций).
    # Буфер меньше (бонд контрактный, неопределённость ниже). PD_CAP — интерим кредит-фильтр по
    # РЫНОЧНОЙ PD (отсекает junk); независимая PD (рейтинг/фундаментал) = Фаза 2b.
    bond_hurdle, bond_buffer, PD_CAP = 0.0, 0.01, 0.10
    rate_direction = "hold"
    tr = None
    try:
        from app.core import llm_macro
        tr = llm_macro.get_rate_trajectory(db)
        g = (tr or {}).get("grade", "") or ""
        rate_direction = "cut" if "снижение" in g else ("hike" if "повышение" in g else "hold")
    except Exception:  # noqa: BLE001
        pass
    # ПОДЧИНЕНИЕ ОБЩЕЙ МОДЕЛИ: те же ФНБ/шок-режим + carry по траектории КС, что и у акций.
    frag = macro_fragility(db)
    stress = 1.0 + 0.5 * frag["F"]               # кредит ухудшается в хрупком макро (F∈[0,1] → до ×1.5)
    years = settings.get("forecast_years") or FORECAST_YEARS
    cur_ks = (get_macro(db) or {}).get("key_rate") or 0.145
    from app.core import carry as carrymod
    carry_val = carrymod.carry_rate(cur_ks, (tr or {}).get("terminal_ks"), years)
    try:
        ofz = mb.fetch_bonds(mb.OFZ_BOARD)
        corp = mb.fetch_bonds(mb.CORP_BOARD)
    except Exception as e:  # noqa: BLE001 — без сети скринер не должен ронять сервис
        return {"error": f"MOEX ISS недоступен: {type(e).__name__}", "bonds": [], "count": 0}

    LGD = credit_pd.LGD_DEFAULT
    # только классические бонды (Фикс/Флоат/Линкер); структурные/конвертируемые — вне скринера
    ofz_clean = [b for b in ofz if mb.is_sane(b, min_dur=0.25, ytm_lo=0.05, ytm_hi=0.30, min_trades=0)
                 and b["coupon_type"] in mb.CLASSIC]
    curve = mb.ofz_curve([b for b in ofz_clean if b["coupon_type"] == "Фикс"])  # кривая = ФИКС ОФЗ
    out: list[dict] = []
    for b in ofz_clean:
        is_lk = b["coupon_type"] == "Линкер"   # у линкера YTM УЖЕ реальный → не вычитать инфляцию
        a = bmod.assess_bond(ytm=b["ytm"], e_inflation=(0.0 if is_lk else e_infl), hurdle_real=bond_hurdle,
                             buffer=bond_buffer, rate_direction=rate_direction,
                             floater=(b["coupon_type"] == "Флоат"), is_ofz=True)
        out.append({**b, "type": "ОФЗ", "spread": None, "pd": 0.0, "pd_horizon": 0.0,
                    "real_ytm": a.real_ytm, "risk_adj_yield": a.real_ytm, "rate_signal": a.rate_signal,
                    "credit_ok": True, "signal": a.signal})
    corp_clean = sorted([b for b in corp if mb.is_sane(b, min_dur=0.5, ytm_lo=0.06, ytm_hi=0.40, min_trades=10)
                         and b["coupon_type"] in mb.CLASSIC], key=lambda x: -x["num_trades"])[:90]
    for b in corp_clean:
        is_lk = b["coupon_type"] == "Линкер"
        kbd = mb.curve_at(curve, b["duration_years"])
        spread = (b["ytm"] - kbd) if (kbd is not None and not is_lk) else None
        pd_raw = credit_pd.pd_market(spread) if spread is not None else None
        pd_ann = min((pd_raw or 0.0) * stress, 0.99)   # годовая PD под текущим макро-режимом (стресс)
        cred = pd_raw is None or pd_ann <= PD_CAP       # интерим: отсечь junk по (стресс.) PD
        a = bmod.assess_bond(ytm=b["ytm"], e_inflation=(0.0 if is_lk else e_infl), hurdle_real=bond_hurdle,
                             buffer=bond_buffer, rate_direction=rate_direction,
                             floater=(b["coupon_type"] == "Флоат"), kbd_at_duration=kbd, credit_ok_override=cred)
        pd_hz = 1.0 - (1.0 - pd_ann) ** max(b["duration_years"], 0.1)   # кумулятивная PD за срок (Q2/Q4)
        out.append({**b, "type": "Корп", "spread": round(spread, 4) if spread is not None else None,
                    "pd": round(pd_ann, 4), "pd_horizon": round(pd_hz, 4), "real_ytm": a.real_ytm,
                    "risk_adj_yield": round(a.real_ytm - pd_ann * LGD, 4),   # реал. за вычетом ожид. потерь (год)
                    "rate_signal": a.rate_signal, "credit_ok": a.credit_ok, "signal": a.signal})
    out.sort(key=lambda x: (x["risk_adj_yield"] is None, -(x.get("risk_adj_yield") or -99)))  # по реал. с уч. риска
    return {"bonds": out, "count": len(out), "buy": sum(1 for b in out if b["signal"] == "ПОКУПАЙ"),
            "ofz_curve": [[d, round(y, 4)] for d, y in curve], "rate_direction": rate_direction,
            "e_inflation": round(e_infl, 4), "bond_hurdle": bond_hurdle,
            "carry": round(carry_val, 4), "regime": frag["regime"], "macro_F": round(frag["F"], 3),
            "current_ks": round(cur_ks, 4), "terminal_ks": (tr or {}).get("terminal_ks"),
            "horizon_years": years}


# Курсовое распределение (год), смещение к ослаблению рубля (структурный взгляд ФНБ/нефть).
# Интерим-дефолт; редактируемые сценарии — следующий шаг (как felt_inflation).
FX_SCENARIOS = [(0.45, 0.06), (0.30, 0.18), (0.25, -0.08)]   # E[курс] ≈ +6.1%/год


def screen_fx(db: sqlite3.Connection) -> dict:
    """Валютная секция (фаза 2 мультиассета): замещайки/юаневые бонды через fx.assess_fx.
    E[отдача,₽] = FX-YTM + E[курс по распределению] − carry (избыток над рублёвой парковкой в ОФЗ)."""
    from app.data import moex_bonds as mb
    from app.core import fx as fxmod, carry as carrymod
    settings = get_settings(db)
    years = settings.get("forecast_years") or FORECAST_YEARS
    cur_ks = (get_macro(db) or {}).get("key_rate") or 0.145
    tr = None
    try:
        from app.core import llm_macro
        tr = llm_macro.get_rate_trajectory(db)
    except Exception:  # noqa: BLE001
        pass
    carry_val = carrymod.carry_rate(cur_ks, (tr or {}).get("terminal_ks"), years)
    try:
        fxb = mb.fetch_bonds(mb.CORP_BOARD, fx=True) + mb.fetch_bonds(mb.OFZ_BOARD, fx=True)
    except Exception as e:  # noqa: BLE001
        return {"error": f"MOEX ISS недоступен: {type(e).__name__}", "bonds": [], "count": 0}
    # FX-доходности ниже рублёвых (в валюте бумаги): диапазон 2–20%, ликвидность скромнее
    clean = sorted([b for b in fxb if mb.is_sane(b, min_dur=0.5, ytm_lo=0.02, ytm_hi=0.20, min_trades=3)
                    and b["coupon_type"] in mb.CLASSIC], key=lambda x: -x["num_trades"])[:60]
    e_fx = sum(p * m for p, m in FX_SCENARIOS) / (sum(p for p, _ in FX_SCENARIOS) or 1.0)
    out: list[dict] = []
    for b in clean:
        fa = fxmod.assess_fx(scenarios=FX_SCENARIOS, carry=carry_val, hurdle=0.0, buffer=0.01,
                             coupon=b["ytm"], has_coupon_analog=True)   # купонный инструмент → не доминируем
        out.append({**b, "ytm_fx": b["ytm"], "e_fx_move": fa.e_fx_move,
                    "e_return": fa.e_return,                            # избыток над carry
                    "e_return_total": round(b["ytm"] + e_fx, 4),       # полная рублёвая E[отдача]
                    "signal": fa.signal})
    out.sort(key=lambda x: -x["e_return"])
    return {"bonds": out, "count": len(out), "buy": sum(1 for b in out if b["signal"] == "ПОКУПАЙ"),
            "carry": round(carry_val, 4), "e_fx": round(e_fx, 4), "scenarios": FX_SCENARIOS,
            "current_ks": round(cur_ks, 4), "horizon_years": years}


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


# ── счётчик короткого списка = индикатор дороговизны + логика пороха (§ короткий список) ──
SHORTLIST_EXPENSIVE = 3  # проходящих ПОКУПАЙ меньше → рынок дорог (оценочный риск)


def screen_summary(db: sqlite3.Connection, results: list[dict] | None = None) -> dict:
    """Две НЕЗАВИСИМЫЕ оси: ФНБ-режим (девальв. риск) и число проходящих имён
    (оценочный риск). Мало ПОКУПАЙ = рынок дорог; разрыв ёмкости атаки → в ПОРОХ
    (RISK — защитный золото/фикс; NORMAL — доходный ОФЗ), НЕ в непрошедшие имена."""
    results = results if results is not None else screen_all(db)
    total = len(results)
    buy = sum(1 for r in results if r.get("signal") == "ПОКУПАЙ")
    edge = sum(1 for r in results if r.get("signal") == "ГРАНИЦА")
    watch = sum(1 for r in results if r.get("action") in decision.WATCHLIST_ACTIONS)
    regime = (macro_fragility(db).get("regime") or "NORMAL").upper()
    expensive = buy < SHORTLIST_EXPENSIVE
    powder = ("защитный порох — золото/длинный фикс (хедж девальвации)" if regime == "RISK"
              else "доходный порох — ОФЗ/флоатер (парковка в ожидании ценности, не убежище)")
    if expensive:
        tail = ("Режим RISK: добавлен девальвационный риск — порох защитный."
                if regime == "RISK"
                else "Режим NORMAL: девальвации не грозит — спокойно-дороговатый рынок на нефти, "
                     "не «кровь на улицах».")
        note = (f"Проходящих ПОКУПАЙ: {buy} из {total} — мало = рынок дорог (оценочный риск). "
                f"Разрыв ёмкости атаки → в {powder}, НЕ в непрошедшие имена (право не играть). {tail}")
    else:
        note = (f"Проходящих ПОКУПАЙ: {buy} из {total} — рынок предлагает ценность; "
                f"заполнять атаку под лимитом ~12% на имя.")
    return {"total": total, "buy_count": buy, "edge_count": edge, "watchlist_count": watch,
            "regime": regime, "expensive": expensive, "note": note}
