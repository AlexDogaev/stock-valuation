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
EQUITY_RISK_PREMIUM = 0.04                                   # реальная премия акций над ОФЗ (допущение, тюнится)
SHOCK_HORIZON_MIN = 3                                        # шок-драг в сценарии включаем от 3 лет (Саша)


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

    def base_inflation(self, maturity: float | None = None) -> float:
        """Базовая ожидаемая инфляция за срок (срочная структура felt→terminal за norm_years)."""
        M = maturity if maturity else self.horizon_years
        return valuation.inflation_to_maturity(self.felt, self.terminal, M, norm_years=self.norm_years)

    def e_inflation(self, maturity: float | None = None) -> float:
        """E[инфляция] = база + вклад шок-ветки (взвешен по p и доле срока в окне дезинфляции).

        Шок «переоткрывает» дезинфляцию: повышенная инфляция держится ~norm_years. Короткая
        бумага полностью внутри окна → весь вклад; длинная — разбавляет.
        """
        M = maturity if maturity else self.horizon_years
        share = min(self.norm_years, M) / M if M else 1.0
        return self.base_inflation(M) + self.shock.p * self.shock.infl_pp * share

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

    def equity_shock_drag(self, horizon: float) -> float:
        """Ожидаемый годовой РЕАЛЬНЫЙ драг акций от шоков, тайминг равновероятен по месяцам.

        Шок в месяце m: условная просадка D, за год восстанавливается доля r → перманентный
        остаток D·(1−r) (компаундится по всем шокам) + временный D·r, ещё не отыгранный к концу
        горизонта (только если шок в последние 12 мес). Усреднение по всем месяцам = равновероятный
        тайминг. Возвращает годовой драг (положит. = вычитается из доходности)."""
        if horizon < SHOCK_HORIZON_MIN:
            return 0.0
        D = abs(self.shock.equity_dd)
        r = self.shock.recovery_1y
        p_m = self.shock.p / 12.0
        N = int(round(horizon * 12))
        ln_mult = 0.0
        for m in range(N):
            tau = (N - 1 - m) / 12.0                              # лет до конца горизонта от шока в мес. m
            resid = D * (1.0 - r) + D * r * max(0.0, 1.0 - tau)   # перманент + невосстановл. временный
            ln_mult += p_m * math.log(max(1e-6, 1.0 - resid))
        return -(ln_mult / horizon)                              # годовой драг

    def real_return(self, asset: str, horizon: float, *, nominal: float | None = None,
                    fx_ytm: float | None = None) -> dict:
        """Реальная доходность buy-and-hold за H (CAGR), с учётом инфляции и шока.

        asset: 'ofz' (фикс HtM: real=nominal−E[инфл], шок не бьёт — цена к номиналу, инфл.всплеск
        уже в E[инфл]); 'fx' (real=fx_ytm+E[курс]−E[инфл], шок в плюс); 'equity' (real=ОФЗ-реал+ERP
        − драг шоков)."""
        e_infl = self.e_inflation(horizon)
        if asset == "ofz":
            base = (nominal or 0.0) - e_infl
            return {"base_real": round(base, 4), "shock_drag": 0.0, "net_real": round(base, 4)}
        if asset == "fx":
            base = (fx_ytm or 0.0) + self.e_fx() - e_infl
            return {"base_real": round(base, 4), "shock_drag": 0.0, "net_real": round(base, 4)}
        # equity: база = ОФЗ-реал + премия; минус драг шоков (накопленный за горизонт)
        ofz_real = (nominal or 0.0) - e_infl
        base = ofz_real + EQUITY_RISK_PREMIUM
        drag = self.equity_shock_drag(horizon)
        return {"base_real": round(base, 4), "shock_drag": round(drag, 4), "net_real": round(base - drag, 4)}

    def as_dict(self) -> dict:
        return {
            "horizon_years": self.horizon_years,
            "felt": round(self.felt, 4),
            "terminal": (round(self.terminal, 4) if self.terminal is not None else None),
            "norm_years": round(self.norm_years, 2),
            "norm_source": self.norm_source,
            "p_shock": round(self.shock.p, 4),
            "base_inflation_h": round(self.base_inflation(), 4),
            "e_inflation_h": round(self.e_inflation(), 4),
            "shock": {"infl_pp": round(self.shock.infl_pp, 4), "fx_pct": round(self.shock.fx_pct, 4),
                      "ks_pp": round(self.shock.ks_pp, 4), "equity_dd": round(self.shock.equity_dd, 4),
                      "recovery_1y": round(self.shock.recovery_1y, 4), "sectoral": self.shock.sectoral},
            "e_fx": round(self.e_fx(), 4),
        }


def _shock_vector(db) -> ShockVector:
    """Шок-вектор из Opus (get_shock), с КАЛИБРОВКОЙ 2014/2022 как дефолтами.

    p — ГОДОВОЙ hazard (aggregate_pct = вероятность шока за 12 мес). equity_dd — УСЛОВНАЯ просадка
    (imoex_drawdown_pct), НЕ expected_damage (то — безусловное p×severity)."""
    p = infl = fx = ks = eqdd = rec = sect = None
    try:
        from app.core import llm_macro
        sh = llm_macro.get_shock(db) or {}
        agg = sh.get("aggregate_pct")
        p = (agg / 100.0) if agg is not None else None
        infl, fx, ks = sh.get("shock_infl_pp"), sh.get("shock_fx_pct"), sh.get("shock_ks_pp")
        dd = sh.get("imoex_drawdown_pct")
        eqdd = -(dd / 100.0) if dd is not None else None
        rec = sh.get("recovery_1y")
        sect = sh.get("sectoral")
    except Exception:  # noqa: BLE001 — прогноз не должен ронять сервис
        pass
    if p is None:
        try:
            from app.data.minfin import current_regime
            reg = current_regime().get("regime", "NORMAL")
        except Exception:  # noqa: BLE001
            reg = "NORMAL"
        p = REGIME_P_SHOCK.get(reg, 0.10)
    return ShockVector(
        p=p,
        infl_pp=infl if infl is not None else DEFAULT_SHOCK["infl_pp"],
        fx_pct=fx if fx is not None else DEFAULT_SHOCK["fx_pct"],
        ks_pp=ks if ks is not None else DEFAULT_SHOCK["ks_pp"],
        equity_dd=eqdd if eqdd is not None else DEFAULT_SHOCK["equity_dd"],
        recovery_1y=rec if rec is not None else DEFAULT_SHOCK["recovery_1y"],
        sectoral=sect if isinstance(sect, dict) and sect else dict(SECTORAL_DD),
    )


def _norm_years(db) -> tuple[float, str]:
    """Окно дезинфляции: приоритет — оценка Opus из риторики ЦБ (disinflation_months);
    иначе расчёт по темпу траектории; иначе резерв. НЕ хардкод (решение Саши 20.06.2026)."""
    from app.core import rate_trajectory as rt
    try:
        from app.core import llm_macro
        from app.data.db import get_macro
        tr = llm_macro.get_rate_trajectory(db) or {}
        dim = tr.get("disinflation_months")
        if dim:
            lo, hi = rt.NORM_YEARS_BOUNDS
            return max(lo, min(hi, dim / 12.0)), "Opus/риторика ЦБ"
        if tr.get("terminal_ks") is not None:
            cur_ks = (get_macro(db) or {}).get("key_rate")
            return rt.disinflation_years(cur_ks, tr["terminal_ks"], tr.get("avg_step_pp")), "темп траектории КС"
    except Exception:  # noqa: BLE001
        pass
    return rt.NORM_YEARS_FALLBACK, "резерв (нет траектории)"


def build_outlook(db, horizon: int | None = None) -> MacroOutlook:
    """Собрать макро-прогноз на горизонт из настроек (инфляция) + Opus (траектория КС, шок)."""
    from app.data.db import get_settings
    from app.core.engine import terminal_inflation, DEFAULTS, FORECAST_YEARS
    settings = get_settings(db)
    years = horizon or settings.get("forecast_years") or FORECAST_YEARS
    felt = settings.get("felt_inflation")
    felt = felt if felt is not None else DEFAULTS["felt_inflation"]
    terminal = terminal_inflation(settings, db)
    norm_years, norm_source = _norm_years(db)
    return MacroOutlook(horizon_years=years, felt=felt, terminal=terminal,
                        norm_years=norm_years, norm_source=norm_source, shock=_shock_vector(db))
