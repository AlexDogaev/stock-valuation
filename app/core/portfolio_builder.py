"""Блок «Что купить» — конструктор портфеля купил-и-держи (задумка Саши 20.06.2026).

Входы: горизонт (1-20л), агрессивность (доля акций 70/50/30%), ожидаемая инфляция за горизонт,
таргет реальной доходности (год). Выход: портфель из акций + облигаций + валютных бондов, лучше
всего подходящих под «купил и держи», + три риск-метрика: РИСК НЕ ОБЫГРАТЬ ИНФЛЯЦИЮ, РИСК −50% РЕАЛ,
РИСК ПОЛНОГО ОБНУЛЕНИЯ.

Доходности — РЕАЛЬНЫЕ над ВЫБРАННОЙ инфляцией, с поправкой на шок (драг просадки/дефолтов/девал).
Принцип survival-first: defensive-рукав (ОФЗ/линкер/замещайка) держит хвост; атака — качество под лимитом.
Риски — оценки от макро-прогноза (вероятность шока × глубина по составу), не точные числа.
"""
from __future__ import annotations

import math

from app.core import macro_outlook as mo

AGGRESSIVENESS = {
    "Агрессивный": 0.70,
    "Сбалансированный": 0.50,
    "Консервативный": 0.30,
}
NAME_LIMIT = 0.12          # лимит на одно имя (диверсификация)
FX_SHARE_OF_DEFENSIVE = 0.15   # доля валютного хеджа в защитном рукаве (девал-хедж)
DEEP_DD = 0.55            # глубокая (L-образная) просадка акций в тяжёлом шоке
CORP_SHOCK_LOSS = 0.18   # условная потеря корп-бонда в шоке (всплеск дефолтов/спредов)
LGD = 0.65
# клин личная:официальная инфляция — канон в macro_outlook.ROSSTAT_RATIO (линкеры индексируются на офиц.CPI)
# Годовая вола РЕАЛЬНОЙ доходности по классам (ОБЫЧНАЯ дисперсия = диффузия поверх макро-сценариев-прыжков).
REAL_VOL = {"Акция": 0.22, "Облигация": 0.06, "Замещайка": 0.12}


def _fisher_real(nominal: float, inflation: float) -> float:
    return (1.0 + nominal) / (1.0 + inflation) - 1.0


def build(db, *, horizon: int, equity_cap: float, exp_inflation: float, target_real: float,
          name_limit: float = NAME_LIMIT) -> dict:
    """Собрать портфель + риск-метрики. Доходности реальные над exp_inflation, шок-скорректированные."""
    from app.core import engine
    outlook = mo.build_outlook(db, horizon)
    p_shock = outlook.cumulative_shock_p(horizon)          # кумулятивная вероятность шока за горизонт
    tw = (outlook.typology or {}).get("weights", {})
    deep_share = tw.get("financial", 0.15) + tw.get("lstag", 0.10) + 0.30 * tw.get("geo", 0.35)  # доля «глубоких» шоков
    lstag_w = tw.get("lstag", 0.10)

    # ── АКЦИИ: проходящие (сигнал не «воздержись», качество не «обычное», не обнуляющий гейт) ──
    macro_frag = engine.macro_fragility(db)   # ОДИН раз на всю вселенную (не дёргать MOEX по 50× — как в скринере)
    eq_candidates = []
    for row in db.execute("SELECT secid FROM issuers").fetchall():
        x = engine.evaluate_issuer(db, row["secid"], macro_frag=macro_frag)
        if not x or x["signal"] == "ВОЗДЕРЖИСЬ":
            continue
        if x["quality_marker"] == "ordinary" or (x.get("tail_risk") or {}).get("gate") == "block":
            continue
        nominal = x["calc"]["full_nominal"]                # годовая номинальная полная (с дивами)
        real = _fisher_real(nominal, exp_inflation) - (x.get("shock_drag") or 0.0)   # реал над выбр.инфл − шок-драг
        eq_candidates.append({
            "secid": x["secid"], "name": x["name"], "asset": "Акция",
            "real": round(real, 4), "shock_drag": round(x.get("shock_drag") or 0.0, 4),
            "quality": x["quality_marker"], "currency_profile": x.get("currency_profile", "MIXED"),
            "tail_gate": (x.get("tail_risk") or {}).get("gate"), "signal": x["signal"]})
    eq_candidates.sort(key=lambda e: -e["real"])

    # ── ОБЛИГАЦИИ + ВАЛЮТА ──
    rb = engine.screen_bonds(db)
    bonds_unavailable = bool(rb.get("error"))
    bonds = []
    for b in rb.get("bonds", []):
        if b["signal"] == "ВОЗДЕРЖИСЬ" or not b.get("credit_ok", True):
            continue
        # реал над ВЫБРАННОЙ (личной) инфл. Линкер индексируется на ОФИЦИАЛЬНЫЙ CPI (= личная/RATIO),
        # его YTM — реальная над официальным → номинал = (1+real_ytm)(1+офиц)−1, потом дефлируем личной.
        if b["coupon_type"] == "Линкер":
            official = exp_inflation / mo.ROSSTAT_RATIO
            nominal = (1.0 + b["ytm"]) * (1.0 + official) - 1.0
            real = _fisher_real(nominal, exp_inflation)
        else:
            real = _fisher_real(b["ytm"], exp_inflation)
        real -= (b.get("pd") or 0.0) * LGD + (b.get("shock_drag") or 0.0)
        bonds.append({"secid": b["secid"], "name": b["name"], "asset": "Облигация",
                      "subtype": f"{b['type']}·{b['coupon_type']}", "real": round(real, 4),
                      "shock_drag": round(b.get("shock_drag") or 0.0, 4),
                      "pd_horizon": b.get("pd_horizon") or 0.0, "coupon_type": b["coupon_type"],
                      "is_corp": b["type"] == "Корп"})
    bonds.sort(key=lambda x: -x["real"])

    fx = []
    rf = engine.screen_fx(db)
    for f in rf.get("bonds", []):
        if f["signal"] == "ВОЗДЕРЖИСЬ":
            continue
        real = _fisher_real(f["ytm_fx"] + f.get("e_fx_move", 0.0), exp_inflation)   # FX-YTM + E[курс] над инфл
        fx.append({"secid": f["secid"], "name": f["name"], "asset": "Замещайка",
                   "subtype": f.get("faceunit", "FX"), "real": round(real, 4), "shock_drag": 0.0})  # замещайка — девал-хедж
    fx.sort(key=lambda x: -x["real"])

    # ── АЛЛОКАЦИЯ: атака (акции) до cap, защита = остальное (замещайки-хедж + бонды) ──
    holdings, w = [], 0.0
    for e in eq_candidates:
        if w >= equity_cap - 1e-9:
            break
        wt = min(name_limit, equity_cap - w)
        holdings.append({**e, "weight": round(wt, 4)})
        w += wt
    equity_weight = w
    defensive = max(0.0, 1.0 - equity_weight)
    fx_target = defensive * FX_SHARE_OF_DEFENSIVE if fx else 0.0
    wf = 0.0
    for f in fx:
        if wf >= fx_target - 1e-9:
            break
        wt = min(name_limit, fx_target - wf)
        holdings.append({**f, "weight": round(wt, 4)})
        wf += wt
    bond_target = defensive - wf
    wb = 0.0
    for b in bonds:
        if wb >= bond_target - 1e-9:
            break
        wt = min(name_limit, bond_target - wb)
        holdings.append({**b, "weight": round(wt, 4)})
        wb += wt
    cash = round(max(0.0, 1.0 - sum(h["weight"] for h in holdings)), 4)   # порох (не хватило инструментов)

    # ── ВЕСА ПО КЛАССАМ ──
    eqw = sum(h["weight"] for h in holdings if h["asset"] == "Акция")
    corpw = sum(h["weight"] for h in holdings if h["asset"] == "Облигация" and h.get("is_corp"))
    fxw = sum(h["weight"] for h in holdings if h["asset"] == "Замещайка")

    # ── ОЖИДАЕМАЯ РЕАЛЬНАЯ (взвешенная, шок-скорректированная); кэш=0 реал ──
    exp_real = round(sum(h["weight"] * h["real"] for h in holdings), 4)

    # ── ЕДИНАЯ МОДЕЛЬ РИСКА: 4 сценария за горизонт → ТРИ ВЛОЖЕННЫХ порога (находка Саши). ──
    # Исправляет нестыковку: «не обыграть инфляцию» (реал<0) ⊇ «−50% реал» ⊇ «обнуление ≥90%» —
    # три события вложены, значит miss ≥ loss50 ≥ wipeout ПО ПОСТРОЕНИЮ. Раньше три независимые
    # формулы давали miss=0 при loss50=5.8% (логически невозможно: потеря 50% реала ЕСТЬ реал<0).
    g_shock = sum(h["weight"] * (h.get("shock_drag") or 0.0) for h in holdings)
    r_base = exp_real + g_shock                                      # годовая реал БЕЗ шока
    base_cum = (1.0 + r_base) ** horizon - 1.0                      # накопленная реал без шока (обычно > 0)
    fx_hedge = fxw * outlook.shock.fx_pct * 0.5                     # девал-выигрыш замещаек в шоке
    bond_default = sum(h["weight"] * (h.get("pd_horizon") or 0.0) * LGD
                       for h in holdings if h["asset"] == "Облигация")   # перм.дефолты бондов за срок
    # перманентные просадки портфеля (доля стоимости) по тяжести шока:
    eq_perm = abs(outlook.shock.equity_dd) * (1.0 - outlook.shock.recovery_1y)   # норм.шок: акции с V-отскоком
    central_dd = max(0.0, eqw * eq_perm + corpw * CORP_SHOCK_LOSS - fx_hedge)
    deep_dd    = max(0.0, eqw * DEEP_DD + corpw * CORP_SHOCK_LOSS - fx_hedge)
    cat_dd     = min(1.0, eqw * 0.90 + corpw * 0.50 + bond_default)              # L: акции −90% без отскока + дефолты
    # всплеск инфляции в шоке бьёт ФИКС-НОМИНАЛ (купон фиксирован; линкер/флоат защищены), кумул. за окно:
    fixed_nom_w = sum(h["weight"] for h in holdings
                      if h["asset"] == "Облигация" and h.get("coupon_type") == "Фикс") + cash
    infl_erosion = fixed_nom_w * outlook.shock.infl_pp * min(float(horizon), outlook.norm_years)
    # тиры шока (L ⊂ deep): нормальный / глубокий-не-L / L-катастрофа; ΣP = 1
    dshare = min(1.0, deep_share); lw = min(lstag_w, dshare)
    p_L, p_deep, p_norm = lw, dshare - lw, 1.0 - dshare

    def _cum(dd):                                                   # накопл. реал в шоке = просадка + инфл-эрозия
        return (1.0 + base_cum) * (1.0 - dd) - 1.0 - infl_erosion
    scen = [                                                        # (вероятность, СРЕДНЯЯ накопл. реал)
        (1.0 - p_shock, base_cum),                                 # без шока
        (p_shock * p_norm, _cum(central_dd)),                      # нормальный шок (V-отскок)
        (p_shock * p_deep, _cum(deep_dd)),                         # глубокий
        (p_shock * p_L,    _cum(cat_dd)),                          # L-катастрофа (без отскока)
    ]
    # ОБЫЧНАЯ дисперсия (диффузия) ВНУТРИ каждого сценария: акции волатильны и БЕЗ макро-шока
    # (промах прибыли/дерейтинг). σ кумул = вола классов · √H. Не заменяет хвост (прыжки в scen),
    # а добавляет ординарный разброс → портфель с акциями НЕ может иметь 0% риска. Φ монотонна →
    # вложенность miss ≥ loss50 ≥ wipeout сохраняется (пороги 0 > −0.5 > −0.9).
    sigma_annual = sum(h["weight"] * REAL_VOL.get(h["asset"], 0.0) for h in holdings)   # коррелир. (консерв.)
    sigma_cum = sigma_annual * math.sqrt(max(1, horizon))

    def _phi(x):
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    def _p_below(thr):                                              # P(накопл.реал < thr) по прыжкам + диффузия
        if sigma_cum < 1e-6:
            return sum(pr for pr, rc in scen if rc < thr)
        return sum(pr * _phi((thr - rc) / sigma_cum) for pr, rc in scen)
    miss_infl_risk = round(_p_below(0.0), 4)        # P(реал<0) — не обыграть инфляцию ⊇
    loss50_risk    = round(_p_below(-0.50), 4)      # P(потеря ≥50% реала)                ⊇
    wipeout_risk   = round(_p_below(-0.90), 4)      # P(обнуление ≥90%)

    meets_target = exp_real >= target_real

    return {
        "inputs": {"horizon": horizon, "equity_cap": equity_cap, "exp_inflation": round(exp_inflation, 4),
                   "target_real": round(target_real, 4)},
        "p_shock_cum": round(p_shock, 4),
        "weights": {"equity": round(eqw, 4), "corp": round(corpw, 4), "fx": round(fxw, 4),
                    "bond_total": round(sum(h["weight"] for h in holdings if h["asset"] == "Облигация"), 4),
                    "cash": cash},
        "exp_real": exp_real, "target_real": round(target_real, 4), "meets_target": meets_target,
        "loss50_risk": loss50_risk, "wipeout_risk": wipeout_risk, "miss_infl_risk": miss_infl_risk,
        "holdings": sorted(holdings, key=lambda h: -h["weight"]),
        "bonds_unavailable": bonds_unavailable,
        "n_equity": len([h for h in holdings if h["asset"] == "Акция"]),
        "n_bond": len([h for h in holdings if h["asset"] == "Облигация"]),
        "n_fx": len([h for h in holdings if h["asset"] == "Замещайка"]),
    }
