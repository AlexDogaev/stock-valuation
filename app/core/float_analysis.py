"""Структурный флоут платформенного финтеха (INSTRUCTIONS §5, NOTES §4).

Аномально высокая NIM/ROA финтеха платформы часто опёрта на БЕСПЛАТНЫЙ флоут:
деньги покупателей оседают как задолженность перед селлерами на срок выплаты —
бесплатный пассив под рыночную ставку. Невоспроизводимо для классического банка
(тот платит за депозиты). НО ресурс КОНЕЧЕН: флоут ∝ GMV → потолок GMV = потолок
флоут-преимущества; дальше фондирование на общих условиях.

Три приёма (чтобы не переоценить):
1. флоут = 3P-оборот × доля выплаты селлеру × (средняя отсрочка / 365), НЕ от полного GMV;
2. среднюю отсрочку выводить из графика выплат, не угадывать;
3. различать ограничение МАКСИМУМА и СРЕДНЕЙ отсрочки (лимит максимума сдвигает
   весь цикл, средняя падает сильнее — почти вдвое, не до лимита).

Валидация: флоут + платные депозиты + капитал ≈ процентные активы.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FloatResult:
    float_bln: float
    base_3p_bln: float          # 3P-оборот за вычетом доли, не выплачиваемой селлеру
    avg_delay_days: float
    balance_ok: Optional[bool]  # сходится ли флоут+депозиты+капитал ≈ проц. активы
    warnings: list[str] = field(default_factory=list)


def avg_delay_from_max_cap(max_cap_days: float, cycle_days: float = 7.0) -> float:
    """Средняя отсрочка при ЛИМИТЕ МАКСИМУМА (§5, приём 3).

    При недельном цикле выплат продажи равномерно «размазаны» по неделе, поэтому
    средняя ≈ максимум − полцикла. Лимит максимума M сдвигает ВЕСЬ цикл, и средняя
    падает сильнее, чем кажется (ОЗОН: max 14 дн → средняя 10.5, не 14).
    """
    return max(0.0, max_cap_days - cycle_days / 2.0)


def platform_float(
    *,
    gmv_bln: float,
    share_3p: float,
    seller_payout_share: float,
    avg_delay_days: float,
    paid_deposits_bln: Optional[float] = None,
    capital_bln: Optional[float] = None,
    interest_assets_bln: Optional[float] = None,
    balance_tol: float = 0.15,
) -> FloatResult:
    """Бесплатный флоут платформы и (опц.) проверка баланса.

    float = GMV × доля_3P × доля_выплаты_селлеру × (средняя_отсрочка / 365).
    """
    base = gmv_bln * share_3p * seller_payout_share
    float_bln = base * (avg_delay_days / 365.0)

    warnings: list[str] = []
    balance_ok: Optional[bool] = None
    if interest_assets_bln is not None and paid_deposits_bln is not None and capital_bln is not None:
        modelled = float_bln + paid_deposits_bln + capital_bln
        balance_ok = abs(modelled / interest_assets_bln - 1.0) <= balance_tol
        if not balance_ok:
            warnings.append(
                f"Баланс не сходится: флоут+депозиты+капитал ≈ {modelled:.0f} млрд против "
                f"процентных активов {interest_assets_bln:.0f} млрд — оценка флоута неверна "
                f"(пересмотреть долю 3P / отсрочку).")
    warnings.append("Флоут конечен: ∝ GMV → потолок GMV = потолок флоут-преимущества; "
                    "прирост сверхмаржи от этого источника прекращается на потолке оборота.")
    return FloatResult(float_bln=float_bln, base_3p_bln=base, avg_delay_days=avg_delay_days,
                       balance_ok=balance_ok, warnings=warnings)


def float_stress(
    *,
    base_result: FloatResult,
    new_avg_delay_days: float,
    fintech_profit_bln: Optional[float] = None,
    asset_yield: float = 0.18,
) -> dict:
    """Стресс «регулятор режет отсрочку»: новый флоут, сжатие, потеря дохода/год.

    Потеря ≈ Δфлоут × доходность размещения. Если задана прибыль финтеха — доля удара.
    """
    if base_result.avg_delay_days <= 0:
        new_float = 0.0
    else:
        new_float = base_result.float_bln * (new_avg_delay_days / base_result.avg_delay_days)
    delta_float = new_float - base_result.float_bln
    lost_income = -delta_float * asset_yield  # сжатие флоута → потеря дохода
    out = {
        "new_avg_delay_days": new_avg_delay_days,
        "new_float_bln": round(new_float, 0),
        "delta_float_bln": round(delta_float, 0),
        "shrink_pct": round((new_float / base_result.float_bln - 1.0) * 100, 0)
        if base_result.float_bln else None,
        "lost_income_bln_per_year": round(lost_income, 1),
    }
    if fintech_profit_bln:
        out["share_of_fintech_profit_pct"] = round(lost_income / fintech_profit_bln * 100, 0)
    return out
