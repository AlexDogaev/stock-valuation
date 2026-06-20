"""Движок вероятности шока — статичная догадка → динамическая хрупкость (REVIEW C2/C3, 20.06.2026).

Мгновенный hazard h = базовый_фон (история, якорь, широкий интервал)
                     + структурный_горб(год) (детерминир. окна: транзит власти/долговые стены/энергопик)
                     + множитель_EWI (нефть/перегрев/спреды/дефолты — наблюдаемая хрупкость, ДЫШИТ).
FORWARD: все решения по условной вероятности от «сейчас», rolling-окна (НЕ накопленная от фикс.старта).
Срочная структура (горизонты Саши): 1/3/6/12 мес + 1/3/5/10/20 лет. Тактика — по ближнему окну;
структурный горб проступает в дальнем. Геотриггер — РАВНОМЕРНЫЙ фон (может выстрелить вне горба).

Калибровка на 4 событиях → hazard ДИАПАЗОНОМ, не точкой (робастность к 20-45%, а не оптимум под 31%).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

BASE_FOND = 0.14            # годовой фон (гео+случайное) = частота глубоких РФ-кризисов (~2 за 12л); широкий интервал
EWI_MULT_RANGE = (0.6, 2.2)  # множитель хрупкости: спокойно → ×0.6, экстремум EWI → ×2.2
HAZARD_CAP = 0.60          # потолок годового hazard (выше — бессмысленно)
# Интерим-дефолт EWI (умеренная РФ-напряжённость), пока нет live-парсеров (нефть/спреды/дефолты/сенсор).
DEFAULT_EWI = {"oil_below_cutoff": 0.3, "valuation_overheat": 0.3, "credit_spread": 0.3,
               "default_trend": 0.3, "global_riskoff": 0.3}

# Структурные окна повышенной хрупкости (детерминир. тайминг → ГОРБ; окно, НЕ дата).
# pp — добавка к годовому hazard в пик окна; гауссов спад к краям.
STRUCTURAL_WINDOWS = {
    "транзит власти": {"center": 2036, "sigma": 3.0, "peak": 0.08},   # конституц.сроки/возраст → политнестабильность
    "энергопик/EROI": {"center": 2035, "sigma": 5.0, "peak": 0.03},   # пик спроса на нефть, истощение
}

# EWI: наблюдаемые ранние индикаторы (0..1, где 1 = максимальная тревога). Веса → совокупный EWI-скор.
EWI_WEIGHTS = {
    "oil_below_cutoff": 0.30,   # нефть ниже бюджетной отсечки (сквозной EWI РФ)
    "valuation_overheat": 0.15,  # перегрев оценок рынка (P/E vs норма)
    "credit_spread": 0.20,       # расширение кредитных спредов (опережающий)
    "default_trend": 0.20,       # динамика дефолтов (наш PD-слой)
    "global_riskoff": 0.15,      # перегрев США/глоб. risk-off — ВХОДИТ ЧЕРЕЗ НЕФТЬ (D1), скромный вес
}


@dataclass
class HazardResult:
    annual: float                       # мгновенный годовой hazard «сейчас»
    annual_band: tuple                  # дов.интервал (4 события → широкий)
    base_fond: float
    structural_hump: float              # вклад структурных окон в текущем году
    ewi_score: float                    # совокупный EWI 0..1
    ewi_multiplier: float
    forward: dict = field(default_factory=dict)   # {окно: P(шок) кумулятив}
    notes: list = field(default_factory=list)


def structural_hump(year: int) -> float:
    """Сумма гауссовых горбов структурных окон в данном году (добавка к годовому hazard)."""
    h = 0.0
    for w in STRUCTURAL_WINDOWS.values():
        h += w["peak"] * math.exp(-((year - w["center"]) ** 2) / (2.0 * w["sigma"] ** 2))
    return h


def ewi_score(ewi: dict | None) -> float:
    """Совокупный EWI 0..1 из взвешенных индикаторов (каждый 0..1). Нет данных → интерим-дефолт."""
    e = ewi if ewi else DEFAULT_EWI
    return sum(EWI_WEIGHTS[k] * min(1.0, max(0.0, float(e.get(k, DEFAULT_EWI[k])))) for k in EWI_WEIGHTS)


def compute_hazard(*, year: int, ewi: dict | None = None, base_fond: float = BASE_FOND) -> HazardResult:
    """Мгновенный годовой hazard + forward срочная структура (rolling-окна от «сейчас»)."""
    es = ewi_score(ewi)
    mult = EWI_MULT_RANGE[0] + (EWI_MULT_RANGE[1] - EWI_MULT_RANGE[0]) * es
    hump = structural_hump(year)
    annual = min(HAZARD_CAP, base_fond * mult + hump)
    # дов.интервал: 4 разнородных события → широкий (как red-team #1), вокруг точки
    band = (round(max(0.0, annual * 0.65), 4), round(min(HAZARD_CAP, annual * 1.45), 4))
    # forward кумулятив 1−exp(−h·W); дальние окна добирают структурный горб впереди
    fwd = {}
    for label, W in (("1мес", 1 / 12), ("3мес", 0.25), ("6мес", 0.5), ("12мес", 1.0),
                     ("3г", 3.0), ("5г", 5.0), ("10г", 10.0), ("20г", 20.0)):
        if W <= 1.0:
            h_eff = annual
        else:  # средний h по годам окна (структурный горб может нарастать впереди)
            h_eff = sum(min(HAZARD_CAP, base_fond * mult + structural_hump(year + t))
                        for t in range(int(W))) / int(W)
        fwd[label] = round(1.0 - math.exp(-h_eff * W), 4)
    notes = []
    if hump > 0.01:
        notes.append(f"Структурный горб +{hump*100:.1f}пп (окна транзита власти/энергопика ~2033-40) — "
                     f"ОКНО хрупкости, не дата; геотриггер может выстрелить вне окна.")
    if es > 0.5:
        notes.append(f"EWI-скор {es:.2f} высокий — хрупкость повышена (×{mult:.2f}).")
    return HazardResult(annual=round(annual, 4), annual_band=band, base_fond=base_fond,
                        structural_hump=round(hump, 4), ewi_score=round(es, 3),
                        ewi_multiplier=round(mult, 3), forward=fwd, notes=notes)
