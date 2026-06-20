"""Верхний слой модели: макро-прогноз на горизонт = инфляция (база) + риск шока (вектор).

Дерево из двух веток (решение Саши 20.06.2026): база (дезинфляция к терминалу, p=1−p_shock)
и шок (инфляция↑/курс↓/КС↑, p=p_shock). Из него — агрегированный прогноз: E[инфляция|срок],
курс-сценарии для FX, hurdle/MoS. Все доходности считаются ОТ этой ожидаемой инфляции.
Инфляция и шок НЕ ортогональны — шок сам разгоняет инфляцию, поэтому именно дерево, а не
«база минус штраф». Opus генерит обе ветки (агрегат + вектор), человек может override.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.core import valuation

# Дефолты шок-профиля — КАЛИБРОВКА по 2014 и 2022 (два глубоких шока РФ). Opus уточняет.
#   equity_dd — УСЛОВНАЯ просадка IMOEX *если* шок (2014 −30%, 2022 −43% → ~−37%);
#   recovery_1y — доля просадки, восстановленная за год (2014 быстро через экспортёров, 2022 частично);
#   fx_pct девальвация (2014 +50%, 2022 +30% устойчиво); ks_pp реакция ЦБ (2014→17%, 2022→20%);
#   infl_pp всплеск инфляции (~+9пп пик). Секторально — для описания шока (не в расчёт реала).
DEFAULT_SHOCK = {"infl_pp": 0.09, "fx_pct": 0.40, "ks_pp": 0.085, "equity_dd": -0.37, "recovery_1y": 0.55}
SECTORAL_DD = {"экспортёры": -0.18, "внутренние": -0.45, "банки": -0.45, "IT": -0.50}  # 2014/2022 калибровка
REGIME_P_SHOCK = {"NORMAL": 0.10, "RISK": 0.25, "SHOCK": 0.45}  # годовой hazard по режиму, если нет агрегата Opus
WORLD_INFLATION = 0.03                                       # внешняя инфляция (прокси для базового дрейфа рубля)
ROSSTAT_RATIO = 2.0  # личная (ощущаемая) инфляция : официальный Росстат CPI (Саша 20.06.2026): 12 → офиц 6.
                     # Линкеры (ОФЗ-ИН) индексируются на ОФИЦИАЛЬНЫЙ CPI = личная/RATIO; дефлятор реала — личная.
EQUITY_RISK_PREMIUM = 0.04                                   # реальная премия акций над ОФЗ (допущение, тюнится)
SHOCK_HORIZON_MIN = 3                                        # шок-драг в сценарии включаем от 3 лет (Саша)
# Мультипликативный дов.интервал hazard (red-team #1): 4 разнородных события → ~18-45% вокруг ~31%.
HAZARD_CI = (0.6, 1.45)
ADVISORY_NOTE = ("Шок/hazard/траектория — КОНСЕНСУС-ПРОКСИ Opus (суждение по истории + риторике), "
                 "НЕ независимый внешний якорь. hazard из 4 разнородных кризисов → широкий интервал.")


@dataclass
class ShockVector:
    p: float            # ГОДОВОЙ hazard шока (доля); кумулятив за H = 1−(1−p)^H
    infl_pp: float      # +доля к инфляции в шоке (годовых)
    fx_pct: float       # девальвация рубля в шоке (доля, + = ослабление)
    ks_pp: float        # +доля к КС в шоке
    equity_dd: float    # УСЛОВНАЯ просадка акций *если* шок (доля, отрицательная)
    recovery_1y: float = 0.55           # доля просадки, восстановленная за год
    sectoral: dict = field(default_factory=lambda: dict(SECTORAL_DD))   # секторальные просадки (описание)


@dataclass
class MacroOutlook:
    horizon_years: int
    felt: float                 # ощущаемая инфляция сейчас (год 1)
    terminal: float | None      # терминальная инфляция (из траектории КС)
    norm_years: float           # окно дезинфляции — ВЫВОДИТСЯ из траектории/риторики, НЕ хардкод
    shock: ShockVector
    norm_source: str = ""       # источник окна: Opus/риторика | темп траектории | резерв
    hazard: dict = field(default_factory=dict)      # движок: forward срочная структура + EWI (дашборд)
    typology: dict = field(default_factory=dict)    # смесь типов шока (дашборд)

    def base_inflation(self, maturity: float | None = None) -> float:
        """Базовая ожидаемая инфляция за срок (срочная структура felt→terminal за norm_years)."""
        M = maturity if maturity else self.horizon_years
        return valuation.inflation_to_maturity(self.felt, self.terminal, M, norm_years=self.norm_years)

    def e_inflation(self, maturity: float | None = None) -> float:
        """E[инфляция] = база (срочная структура) + СТАЦИОНАРНЫЙ вклад шок-инфляции.

        Шок поднимает инфляцию на infl_pp на ~norm_years. В среднем доля «шоковых» лет =
        частота × длительность = min(1, hazard·norm_years) — учитывает ~hazard·H шоков за длинный
        горизонт (раньше share=окно/H недосчитывал: моделировал ~один шок). Базовая дезинфляция
        остаётся срочно-зависимой: короткая бумага видит высокую ТЕКУЩУЮ инфляцию, длинная — терминал.
        """
        M = maturity if maturity else self.horizon_years
        elevated = min(1.0, self.shock.p * self.norm_years)   # доля лет с шок-инфляцией (стационарно)
        return self.base_inflation(M) + self.shock.infl_pp * elevated

    def fx_scenarios(self) -> list[tuple[float, float]]:
        """Курс-сценарии для FX (заменяют хардкод): база (дрейф ≈ инфл.дифференциал) + ветка шока."""
        base_drift = max(0.0, (self.terminal if self.terminal is not None else self.felt) - WORLD_INFLATION)
        p = self.shock.p
        return [(round(1.0 - p, 4), round(base_drift, 4)), (round(p, 4), round(self.shock.fx_pct, 4))]

    def e_fx(self) -> float:
        return sum(prob * mv for prob, mv in self.fx_scenarios())

    # ── сценарий по горизонтам: вероятность шока + реальная доходность buy-and-hold ──
    def cumulative_shock_p(self, horizon: float) -> float:
        """P(≥1 шок за горизонт H) = 1−(1−hazard)^H. За 20 лет ≈ почти точно (референс Саши)."""
        return 1.0 - (1.0 - self.shock.p) ** horizon

    def hazard_band(self) -> tuple[float, float]:
        """Дов.интервал годового hazard (4 разнородных события → широкий, red-team #1)."""
        return (round(self.shock.p * HAZARD_CI[0], 4), round(min(0.6, self.shock.p * HAZARD_CI[1]), 4))

    def cumulative_shock_p_range(self, horizon: float) -> tuple[float, float]:
        """Кумулятив P(шок) как ИНТЕРВАЛ (от hazard_lo до hazard_hi) — честная неопределённость."""
        lo, hi = self.hazard_band()
        return (round(1.0 - (1.0 - lo) ** horizon, 4), round(1.0 - (1.0 - hi) ** horizon, 4))

    def equity_shock_drag(self, horizon: float, *, recovery: float | None = None) -> float:
        """Ожидаемый годовой РЕАЛЬНЫЙ драг акций от шоков, тайминг равновероятен по месяцам.

        Шок в месяце m: условная просадка D, за год восстанавливается доля r → перманентный
        остаток D·(1−r) (компаундится по всем шокам) + временный D·r, ещё не отыгранный к концу
        горизонта (только если шок в последние 12 мес). Усреднение по всем месяцам = равновероятный
        тайминг. Возвращает годовой драг (положит. = вычитается из доходности)."""
        if horizon < SHOCK_HORIZON_MIN:
            return 0.0
        D = abs(self.shock.equity_dd)
        r = self.shock.recovery_1y if recovery is None else recovery   # recovery=0 → L-кризис (без отскока)
        p_m = self.shock.p / 12.0
        N = int(round(horizon * 12))
        ln_mult = 0.0
        for m in range(N):
            tau = (N - 1 - m) / 12.0                              # лет до конца горизонта от шока в мес. m
            resid = D * (1.0 - r) + D * r * max(0.0, 1.0 - tau)   # перманент + невосстановл. временный
            ln_mult += p_m * math.log(max(1e-6, 1.0 - resid))
        return -(ln_mult / horizon)                              # годовой драг

    def real_return(self, asset: str, horizon: float, *, nominal: float | None = None,
                    fx_ytm: float | None = None, recovery: float | None = None) -> dict:
        """Реальная доходность buy-and-hold за H (CAGR), с учётом инфляции и шока.

        asset: 'ofz' (фикс HtM: real=nominal−E[инфл], шок не бьёт — цена к номиналу, инфл.всплеск
        уже в E[инфл]); 'fx' (real=fx_ytm+E[курс]−E[инфл], шок в плюс); 'equity' (real=ОФЗ-реал+ERP
        − драг шоков)."""
        e_infl = self.e_inflation(horizon)
        if asset == "ofz":
            base = (nominal or 0.0) - e_infl
            res = {"base_real": round(base, 4), "shock_drag": 0.0, "net_real": round(base, 4)}
        elif asset == "fx":
            base = (fx_ytm or 0.0) + self.e_fx() - e_infl
            res = {"base_real": round(base, 4), "shock_drag": 0.0, "net_real": round(base, 4)}
        else:  # equity: база = ОФЗ-реал + премия; минус драг шоков (накопленный за горизонт)
            ofz_real = (nominal or 0.0) - e_infl
            base = ofz_real + EQUITY_RISK_PREMIUM
            drag = self.equity_shock_drag(horizon, recovery=recovery)
            res = {"base_real": round(base, 4), "shock_drag": round(drag, 4), "net_real": round(base - drag, 4)}
        # накопленная (total) реальная за весь горизонт: компаундинг годовой CAGR
        res["net_real_total"] = round((1 + res["net_real"]) ** horizon - 1, 4)
        return res

    def as_dict(self) -> dict:
        return {
            "horizon_years": self.horizon_years,
            "felt": round(self.felt, 4),
            "terminal": (round(self.terminal, 4) if self.terminal is not None else None),
            "norm_years": round(self.norm_years, 2),
            "norm_source": self.norm_source,
            "p_shock": round(self.shock.p, 4),                                  # годовой hazard
            "hazard_band": self.hazard_band(),                                  # дов.интервал hazard
            "p_shock_cum": round(self.cumulative_shock_p(self.horizon_years), 4),  # кумулятив за горизонт
            "p_shock_cum_band": self.cumulative_shock_p_range(self.horizon_years),  # кумулятив как интервал
            "advisory_note": ADVISORY_NOTE,
            "base_inflation_h": round(self.base_inflation(), 4),
            "e_inflation_h": round(self.e_inflation(), 4),
            "shock": {"infl_pp": round(self.shock.infl_pp, 4), "fx_pct": round(self.shock.fx_pct, 4),
                      "ks_pp": round(self.shock.ks_pp, 4), "equity_dd": round(self.shock.equity_dd, 4),
                      "recovery_1y": round(self.shock.recovery_1y, 4), "sectoral": self.shock.sectoral},
            "hazard": self.hazard,            # forward срочная структура 1/3/6/12мес + EWI + горб (дашборд)
            "typology": self.typology,        # смесь типов шока + доминирующий (дашборд)
            "e_fx": round(self.e_fx(), 4),
        }


def _json(s):
    import json
    try:
        return json.loads(s) if s else None
    except (ValueError, TypeError):
        return None


def _shock_from_engine(settings, year: int):
    """Шок-вектор из ТИПОЛОГИИ (смесь 5 типов) + hazard из ДВИЖКА (фон+горб+EWI). REVIEW C2/C3.

    Заменяет одну цифру Opus движком: природа = смесь типов (убирает V-bias, держит L),
    вероятность = базовый_фон×EWI + структурный_горб. Веса/EWI — из настроек (ручной/Opus),
    иначе дефолты. Возвращает (ShockVector, hazard_result, typology_blend)."""
    from app.core import shock_typology as st, hazard_engine as he
    weights = _json(settings.get("shock_weights_json"))
    ewi = _json(settings.get("ewi_json"))
    blend = st.blend(weights)
    hr = he.compute_hazard(year=year, ewi=ewi)
    sv = ShockVector(
        p=hr.annual, infl_pp=blend["infl_pp"], fx_pct=blend["fx_pct"], ks_pp=blend["ks_pp"],
        equity_dd=blend["equity_dd"], recovery_1y=blend["recovery_1y"], sectoral=dict(SECTORAL_DD))
    typ = {"weights": blend["weights"], "dominant": blend["dominant"], "types": st.types_table()}
    haz = {"annual": hr.annual, "annual_band": hr.annual_band, "base_fond": hr.base_fond,
           "structural_hump": hr.structural_hump, "ewi_score": hr.ewi_score,
           "ewi_multiplier": hr.ewi_multiplier, "forward": hr.forward, "notes": hr.notes}
    return sv, haz, typ


def _norm_years(db) -> tuple[float, str]:
    """Окно дезинфляции: приоритет — оценка Opus из риторики ЦБ (disinflation_months);
    иначе расчёт по темпу траектории; иначе резерв. НЕ хардкод (решение Саши 20.06.2026)."""
    from app.core import rate_trajectory as rt
    try:
        from app.core import llm_macro
        from app.data.db import effective_key_rate
        tr = llm_macro.get_rate_trajectory(db) or {}
        dim = tr.get("disinflation_months")
        if dim:
            lo, hi = rt.NORM_YEARS_BOUNDS
            return max(lo, min(hi, dim / 12.0)), "Opus/риторика ЦБ"
        if tr.get("terminal_ks") is not None:
            cur_ks = effective_key_rate(db)
            return rt.disinflation_years(cur_ks, tr["terminal_ks"], tr.get("avg_step_pp")), "темп траектории КС"
    except Exception:  # noqa: BLE001
        pass
    return rt.NORM_YEARS_FALLBACK, "резерв (нет траектории)"


def build_outlook(db, horizon: int | None = None) -> MacroOutlook:
    """Собрать макро-прогноз: инфляция (срочн.структура) + ДВИЖОК шока (фон+горб+EWI) + ТИПОЛОГИЯ."""
    from datetime import date
    from app.data.db import get_settings
    from app.core.engine import terminal_inflation, DEFAULTS, FORECAST_YEARS
    settings = get_settings(db)
    years = horizon or settings.get("forecast_years") or FORECAST_YEARS
    felt = settings.get("felt_inflation")
    felt = felt if felt is not None else DEFAULTS["felt_inflation"]
    terminal = terminal_inflation(settings, db)
    norm_years, norm_source = _norm_years(db)
    shock, haz, typ = _shock_from_engine(settings, date.today().year)
    return MacroOutlook(horizon_years=years, felt=felt, terminal=terminal, norm_years=norm_years,
                        norm_source=norm_source, shock=shock, hazard=haz, typology=typ)
