"""Вероятность дефолта (PD) корпоративных бондов — кредитное ядро (REVIEW мультиассет).

ОФЗ безрисковы; вся сложность — PD корпоратов/ВДО. PD НЕЛИНЕЙНА по рейтингу (BB- ~12%, B ~27%,
CCC ~71% годовых). 4 слоя → КОНВЕРГЕНЦИЯ (тот же принцип, что причинный граф):
1. PD_rating — матрица дефолтов агентства (ЗАПАЗДЫВАЕТ → не единственный).
2. PD_market — имплицит из спреда: (spread − премия_ликв) / LGD. Опережающий сигнал.
3. PD_fundamental — скоринг отчётности (Долг/EBITDA, покрытие, refinancing wall).
4. context_modifier — отрасль/госнавес/implicit support (системообразующий → ↓, одинокий ВДО → ↑).

Синтез: сходятся → надёжно (среднее); РАСХОДЯТСЯ → red flag, берём КОНСЕРВАТИВНО (max) + требовать
больше MoS / Воздержись. Паттерн «рейтинг низкий PD, рынок+фундаментал высокий → Воздержись».
"""
from __future__ import annotations

from dataclasses import dataclass

LGD_DEFAULT = 0.65          # loss given default (РФ-корпораты)
LIQ_PREMIUM = 0.005         # премия за неликвидность в спреде
DIVERGENCE_PP = 0.10        # расхождение слоёв PD > 10пп → red flag


def pd_market(spread: float, *, lgd: float = LGD_DEFAULT, liq_premium: float = LIQ_PREMIUM) -> float:
    """Имплицитная PD из кредитного спреда: (spread − премия_ликв) / LGD, не ниже 0."""
    return max(0.0, (spread - liq_premium) / lgd)


@dataclass
class PDSynthesis:
    pd: float                 # итоговая (синтез)
    base: float               # среднее по известным слоям
    diverge: bool             # слои расходятся (red flag)
    layers: dict[str, float]
    verdict: str


def pd_synthesis(*, pd_rating: float | None, pd_market_: float | None,
                 pd_fundamental: float | None, context_modifier: float = 1.0) -> PDSynthesis:
    """Конвергенция 3 независимых PD × контекст. Расходятся → консервативно (max), red flag."""
    layers = {k: v for k, v in {"rating": pd_rating, "market": pd_market_,
                                "fundamental": pd_fundamental}.items() if v is not None}
    vals = list(layers.values())
    if not vals:
        return PDSynthesis(0.0, 0.0, False, {}, "нет данных PD")
    base = sum(vals) / len(vals)
    diverge = (max(vals) - min(vals)) > DIVERGENCE_PP if len(vals) > 1 else False
    synth = max(vals) if diverge else base          # расхождение → консервативный
    synth = min(1.0, max(0.0, synth * context_modifier))
    if diverge:
        verdict = ("слои PD РАСХОДЯТСЯ (red flag) — берём консервативную max; вероятно рейтинг "
                   "запаздывает (рынок/фундаментал тревожнее) → больше MoS / Воздержись")
    else:
        verdict = "слои PD сходятся — оценка надёжна"
    return PDSynthesis(round(synth, 4), round(base, 4), diverge,
                       {k: round(v, 4) for k, v in layers.items()}, verdict)


def credit_ok(*, spread: float, pd: float, lgd: float = LGD_DEFAULT,
              risk_premium: float = 0.01) -> bool:
    """Кредитный фильтр: спред должен покрывать ожидаемые потери + премию за риск."""
    return spread >= pd * lgd + risk_premium
