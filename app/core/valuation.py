"""Количественный слой оценки.

Чистые функции без побочных эффектов. Все формулы — из методологии
(SPEC §4.2, лист Excel «ТОП-25 (2 слоя)», «Зрелый режим», «Под инвестора»).

Принцип: точность входов не критична (троичный сигнал робастен к ошибке
10-20%), критична верифицируемость и консистентность определений.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.config import SPREAD_OK, SPREAD_FRAGILE


# ─────────────────────────────────────────────────────────────────────────────
# Базовые связи определений (SPEC §4.1)
# ─────────────────────────────────────────────────────────────────────────────

def sustainable_g(roe: float, payout: float) -> float:
    """Устойчивый темп роста = ROE × (1 − payout). НЕ задаётся произвольно."""
    return roe * (1.0 - payout)


def roe_from_dupont(roa: float, leverage: float) -> float:
    """ROE = ROA × Леверидж (Активы / Капитал)."""
    return roa * leverage


def real_return(nominal: float, deflator: float) -> float:
    """Реальная доходность над личным дефлятором (Фишер): (1+ном)/(1+дефл) − 1."""
    return (1.0 + nominal) / (1.0 + deflator) - 1.0


def fisher_nominal(inflation: float, real: float) -> float:
    """Номинальный hurdle из реального по Фишеру: (1+i)(1+r) − 1."""
    return (1.0 + inflation) * (1.0 + real) - 1.0


def horizon_deflator(felt: float, terminal: float | None, years: int | None) -> float:
    """Эффективный дефлятор за горизонт с учётом траектории снижения инфляции (КС).

    Инфляция глайдит линейно от текущей ощущаемой (год 1 = felt) к терминальной
    (год N = terminal, куда сойдёт при нормализации КС). Дефлятор = геометрическое
    среднее по годам — именно оно корректно дисконтирует N-летнюю номинальную
    доходность: (1+real)^N = (1+nom)^N / Π(1+infl_t).

    Горизонт ≤ 1 года или терминал не задан → плоско = felt (траектории нет).
    """
    if terminal is None or years is None or years <= 1:
        return felt
    prod = 1.0
    for t in range(years):
        infl = felt + (terminal - felt) * (t / (years - 1))
        prod *= 1.0 + infl
    return prod ** (1.0 / years) - 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Justified-мультипликаторы (зрелый режим)
# ─────────────────────────────────────────────────────────────────────────────

def justified_pb(roe: float, g: float, r: float) -> float:
    """Справедливый P/B = (ROE − g) / (r − g). Только при r > g."""
    if r - g <= 0:
        raise ValueError("r должно быть строго больше g (зона r≈g неоцениваема)")
    return (roe - g) / (r - g)


def justified_pe(payout: float, g: float, r: float) -> float:
    """Справедливый P/E зрелой компании = payout(1+g)/(r−g)."""
    if r - g <= 0:
        raise ValueError("r должно быть строго больше g")
    return payout * (1.0 + g) / (r - g)


# ─────────────────────────────────────────────────────────────────────────────
# Тест достоверности (зона r − g), SPEC §4.2
# ─────────────────────────────────────────────────────────────────────────────

def confidence_zone(r: float, g: float) -> str:
    """'применимо' / 'хрупко' / 'вне зоны'. Цена взрывается при r → g."""
    spread = r - g
    if spread >= SPREAD_OK:
        return "применимо"
    if spread >= SPREAD_FRAGILE:
        return "хрупко"
    return "вне зоны"


# ─────────────────────────────────────────────────────────────────────────────
# Троичный сигнал (SPEC §4.2)
# ─────────────────────────────────────────────────────────────────────────────

def ternary_signal(real: float, hurdle: float, buffer: float) -> str:
    """ПОКУПАЙ / ГРАНИЦА / ВОЗДЕРЖИСЬ с буфером (маржа безопасности)."""
    if real >= hurdle + buffer:
        return "ПОКУПАЙ"
    if real < hurdle - buffer:
        return "ВОЗДЕРЖИСЬ"
    return "ГРАНИЦА"


def effective_hurdle(hurdle_base: float, regime: str) -> float:
    """В режиме ШОК hurdle снимается (бери жадно подешевевшее качество)."""
    return 0.0 if regime.upper() == "ШОК" else hurdle_base


# ─────────────────────────────────────────────────────────────────────────────
# Главная формула — ожидаемая полная доходность с поправкой на сжатие
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class FullReturn:
    """Результат прогона полной доходности эмитента (лист «ТОП-25»)."""
    div_yield: float
    g_base: float
    structural_mult: float
    g_final: float
    compression: float
    full_nominal: float
    deflator: float
    real: float
    signal: str
    confidence: Optional[str] = None
    notes: list[str] = field(default_factory=list)


def full_return(
    *,
    div_yield: float,
    g_base: float,
    compression: float,
    structural_mult: float,
    deflator: float,
    hurdle: float,
    buffer: float,
    regime: str = "спокойное",
    r: Optional[float] = None,
) -> FullReturn:
    """Полная номинальная = (1 + g_итог)·сжатие − 1 + дивдоходность.

    g_итог = g_базовый × структурный_множитель (SPEC §4.2-4.3).
    Сжатие мультипликатора ОБЯЗАТЕЛЬНО (для зрелых = 1, для растущих < 1).
    Реальная = (1+ном)/(1+дефлятор) − 1. Сигнал — троичный с буфером.
    """
    g_final = g_base * structural_mult
    full_nominal = (1.0 + g_final) * compression - 1.0 + div_yield
    real = real_return(full_nominal, deflator)
    h = effective_hurdle(hurdle, regime)
    signal = ternary_signal(real, h, buffer)

    notes: list[str] = []
    confidence = None
    if r is not None:
        confidence = confidence_zone(r, g_final)
        if confidence == "вне зоны":
            notes.append(
                "Спред r−g < 2,5 п.п.: оценка неоцениваема, точная цифра "
                "доходности не выдаётся (зона r≈g)."
            )
    if structural_mult == 0:
        notes.append("Структурный множитель 0 — эмитент вырождающийся (g обнулён).")

    return FullReturn(
        div_yield=div_yield,
        g_base=g_base,
        structural_mult=structural_mult,
        g_final=g_final,
        compression=compression,
        full_nominal=full_nominal,
        deflator=deflator,
        real=real,
        signal=signal,
        confidence=confidence,
        notes=notes,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Тест «аванс в цене» (оптимизм priced-in), INSTRUCTIONS §7
# ─────────────────────────────────────────────────────────────────────────────

NORMAL_PE = 6.0  # «нормальный» рыночный мультипликатор РФ (для обратного теста имплицированной прибыли)


@dataclass
class OptimismResult:
    """Обратный диагностический тест: какую прибыль имплицирует текущая капа
    при нормальном P/E, и насколько это выше текущей фактической прибыли."""
    flag: bool                       # True → оптимизм заложен в цену (двигает в «список ожидания»)
    implied_profit: float            # млрд: капа / нормальный P/E
    current_profit: Optional[float]  # млрд: фактическая чистая прибыль TTM
    ratio: Optional[float]           # implied / current (None при убытке/нуле)
    normal_pe: float


def optimism_priced_in(
    *,
    cap_bln: Optional[float],
    net_profit_bln: Optional[float],
    normal_pe: float = NORMAL_PE,
    threshold: float = 2.0,
) -> Optional[OptimismResult]:
    """Сколько годовой прибыли «зашито» в цену сверх текущей (§7, §13 ОЗОН).

    implied = капа / нормальный_P/E. Если implied кратно (≥ threshold) выше
    текущей прибыли — рынок авансом заложил будущий рост, апсайд возможен только
    при ПРЕВЫШЕНИИ заложенного → флаг. Убыток/околоноль → флаг горит всегда
    (любая положительная имплицированная прибыль кратно выше).
    """
    if cap_bln is None or cap_bln <= 0 or normal_pe <= 0:
        return None
    implied = cap_bln / normal_pe
    if net_profit_bln is None:
        return None
    if net_profit_bln <= 0:
        return OptimismResult(flag=True, implied_profit=implied,
                              current_profit=net_profit_bln, ratio=None, normal_pe=normal_pe)
    ratio = implied / net_profit_bln
    return OptimismResult(flag=ratio >= threshold, implied_profit=implied,
                          current_profit=net_profit_bln, ratio=ratio, normal_pe=normal_pe)


# ─────────────────────────────────────────────────────────────────────────────
# Зрелый режим: справедливая капитализация и implied-доходность
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class MatureValuation:
    roe: float
    g: float
    r: float
    payout: float
    equity: float
    fair_pb: float
    fair_cap: float
    fair_pe: float
    current_cap: Optional[float] = None
    current_pb: Optional[float] = None
    verdict: Optional[str] = None
    spread: float = 0.0
    confidence: str = ""
    implied_nominal: Optional[float] = None
    implied_real: Optional[float] = None
    max_price_cap: Optional[float] = None  # макс цена под hurdle
    needed_drawdown: Optional[float] = None


def mature_valuation(
    *,
    roe: float,
    g: float,
    r: float,
    payout: float,
    equity: float,
    current_cap: Optional[float] = None,
    deflator: Optional[float] = None,
    hurdle_real: Optional[float] = None,
) -> MatureValuation:
    """Зрелая оценка: P/B=(ROE−g)/(r−g), капа = B×P/B (лист «Зрелый режим»).

    Если задана current_cap — добавляет вердикт и implied-доходность
    (обратный режим, лист «Под инвестора»). Если задан deflator+hurdle_real —
    считает максимальную цену покупки под hurdle и нужную просадку.
    """
    fair_pb = justified_pb(roe, g, r)
    fair_cap = equity * fair_pb
    fair_pe = justified_pe(payout, g, r)
    spread = r - g
    conf = confidence_zone(r, g)

    res = MatureValuation(
        roe=roe, g=g, r=r, payout=payout, equity=equity,
        fair_pb=fair_pb, fair_cap=fair_cap, fair_pe=fair_pe,
        spread=spread, confidence=conf,
    )

    if current_cap is not None:
        res.current_cap = current_cap
        res.current_pb = current_cap / equity
        # вердикт с допуском ±10% (лист «X5 и МиД»)
        if current_cap < fair_cap * 0.9:
            res.verdict = "Недооценён"
        elif current_cap > fair_cap * 1.1:
            res.verdict = "Переоценён"
        else:
            res.verdict = "Справедливо"
        # implied номинальная: (ROE−g)/(P/B_текущий) + g
        res.implied_nominal = (roe - g) / res.current_pb + g
        if deflator is not None:
            res.implied_real = real_return(res.implied_nominal, deflator)

    if deflator is not None and hurdle_real is not None:
        # макс цена под hurdle: r_hurdle = (1+deflator)(1+hurdle_real)-1
        r_hurdle = fisher_nominal(deflator, hurdle_real)
        if r_hurdle - g > 0:
            res.max_price_cap = equity * (roe - g) / (r_hurdle - g)
            if current_cap is not None and current_cap > 0:
                res.needed_drawdown = res.max_price_cap / current_cap - 1.0

    return res
