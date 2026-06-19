"""Верхний слой модели: макро-прогноз на горизонт = инфляция (база) + риск шока (вектор).

Дерево из двух веток (решение Саши 20.06.2026): база (дезинфляция к терминалу, p=1−p_shock)
и шок (инфляция↑/курс↓/КС↑, p=p_shock). Из него — агрегированный прогноз: E[инфляция|срок],
курс-сценарии для FX, hurdle/MoS. Все доходности считаются ОТ этой ожидаемой инфляции.
Инфляция и шок НЕ ортогональны — шок сам разгоняет инфляцию, поэтому именно дерево, а не
«база минус штраф». Opus генерит обе ветки (агрегат + вектор), человек может override.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core import valuation

# Дефолты шок-вектора (если Opus не дал) — типовой РФ-шок (девальвация/война/банковский кризис).
DEFAULT_SHOCK = {"infl_pp": 0.08, "fx_pct": 0.25, "ks_pp": 0.07, "equity_dd": -0.30}
SHOCK_DURATION_YEARS = 2.0                                   # длительность повышенной инфляции в шоке
REGIME_P_SHOCK = {"NORMAL": 0.10, "RISK": 0.25, "SHOCK": 0.45}  # p_shock по режиму, если нет агрегата Opus
WORLD_INFLATION = 0.03                                       # внешняя инфляция (прокси для базового дрейфа рубля)


@dataclass
class ShockVector:
    p: float            # вероятность шока на горизонте (доля)
    infl_pp: float      # +доля к инфляции в шоке (годовых)
    fx_pct: float       # девальвация рубля в шоке (доля, + = ослабление)
    ks_pp: float        # +доля к КС в шоке
    equity_dd: float    # просадка акций в шоке (доля, отрицательная)


@dataclass
class MacroOutlook:
    horizon_years: int
    felt: float                 # ощущаемая инфляция сейчас (год 1)
    terminal: float | None      # терминальная инфляция (из траектории КС)
    shock: ShockVector

    def base_inflation(self, maturity: float | None = None) -> float:
        """Базовая ожидаемая инфляция за срок (срочная структура felt→terminal, без шока)."""
        M = maturity if maturity else self.horizon_years
        return valuation.inflation_to_maturity(self.felt, self.terminal, M)

    def e_inflation(self, maturity: float | None = None) -> float:
        """E[инфляция] = база + вклад шок-ветки (взвешен по p и доле срока в окне шока).

        Короткая бумага полностью внутри шок-окна → весь вклад; длинная — разбавляет.
        """
        M = maturity if maturity else self.horizon_years
        share = min(SHOCK_DURATION_YEARS, M) / M if M else 1.0
        return self.base_inflation(M) + self.shock.p * self.shock.infl_pp * share

    def fx_scenarios(self) -> list[tuple[float, float]]:
        """Курс-сценарии для FX (заменяют хардкод): база (дрейф ≈ инфл.дифференциал) + ветка шока."""
        base_drift = max(0.0, (self.terminal if self.terminal is not None else self.felt) - WORLD_INFLATION)
        p = self.shock.p
        return [(round(1.0 - p, 4), round(base_drift, 4)), (round(p, 4), round(self.shock.fx_pct, 4))]

    def e_fx(self) -> float:
        return sum(prob * mv for prob, mv in self.fx_scenarios())

    def as_dict(self) -> dict:
        return {
            "horizon_years": self.horizon_years,
            "felt": round(self.felt, 4),
            "terminal": (round(self.terminal, 4) if self.terminal is not None else None),
            "p_shock": round(self.shock.p, 4),
            "base_inflation_h": round(self.base_inflation(), 4),
            "e_inflation_h": round(self.e_inflation(), 4),
            "shock": {"infl_pp": round(self.shock.infl_pp, 4), "fx_pct": round(self.shock.fx_pct, 4),
                      "ks_pp": round(self.shock.ks_pp, 4), "equity_dd": round(self.shock.equity_dd, 4)},
            "e_fx": round(self.e_fx(), 4),
        }


def _shock_vector(db) -> ShockVector:
    """Шок-вектор из Opus (get_shock), с дефолтами по режиму если данных нет."""
    p = infl = fx = ks = eqdd = None
    try:
        from app.core import llm_macro
        sh = llm_macro.get_shock(db) or {}
        agg = sh.get("aggregate_pct")
        p = (agg / 100.0) if agg is not None else None
        infl, fx, ks = sh.get("shock_infl_pp"), sh.get("shock_fx_pct"), sh.get("shock_ks_pp")
        sev = sh.get("expected_damage_pct")
        eqdd = -(sev / 100.0) if sev is not None else None
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
    )


def build_outlook(db, horizon: int | None = None) -> MacroOutlook:
    """Собрать макро-прогноз на горизонт из настроек (инфляция) + Opus (траектория КС, шок)."""
    from app.data.db import get_settings
    from app.core.engine import terminal_inflation, DEFAULTS, FORECAST_YEARS
    settings = get_settings(db)
    years = horizon or settings.get("forecast_years") or FORECAST_YEARS
    felt = settings.get("felt_inflation")
    felt = felt if felt is not None else DEFAULTS["felt_inflation"]
    terminal = terminal_inflation(settings, db)
    return MacroOutlook(horizon_years=years, felt=felt, terminal=terminal, shock=_shock_vector(db))
