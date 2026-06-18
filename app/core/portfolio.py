"""Портфельный риск — Aladdin-слой (лист «Портфельный риск (Aladdin)», SPEC §4.5).

Факторное разложение, концентрация, стресс. Несколько имён одного сектора =
не диверсификация, а одна ставка с общим бета (иллюзия диверсификации).
Загрузки — КАЧЕСТВЕННЫЕ оценки (0…1); точные беты — регрессия на истории MOEX.
"""
from __future__ import annotations

from dataclasses import dataclass, field

FACTORS = ("РФ-бета", "Ставка ЦБ", "Потребитель", "Рента/гос", "Growth-стиль")
CONCENTRATION_THRESHOLD = 0.45

# Качественные факторные загрузки по сектору (каркас; точные беты — регрессия
# на истории MOEX). Лист «Портфельный риск (Aladdin)».
SECTOR_LOADINGS = {
    "Банк":         {"РФ-бета": 0.95, "Ставка ЦБ": 0.85, "Потребитель": 0.2, "Рента/гос": 0.05, "Growth-стиль": 0.3},
    "Финансы":      {"РФ-бета": 0.9, "Ставка ЦБ": 0.6, "Потребитель": 0.3, "Рента/гос": 0.0, "Growth-стиль": 0.4},
    "Ритейл":       {"РФ-бета": 0.7, "Ставка ЦБ": 0.2, "Потребитель": 1.0, "Рента/гос": 0.0, "Growth-стиль": 0.4},
    "Медицина":     {"РФ-бета": 0.6, "Ставка ЦБ": 0.2, "Потребитель": 0.6, "Рента/гос": 0.0, "Growth-стиль": 0.6},
    "Фарма":        {"РФ-бета": 0.6, "Ставка ЦБ": 0.2, "Потребитель": 0.5, "Рента/гос": 0.0, "Growth-стиль": 0.6},
    "IT":           {"РФ-бета": 0.85, "Ставка ЦБ": 0.4, "Потребитель": 0.4, "Рента/гос": 0.0, "Growth-стиль": 0.8},
    "IT/e-com":     {"РФ-бета": 0.85, "Ставка ЦБ": 0.4, "Потребитель": 0.6, "Рента/гос": 0.1, "Growth-стиль": 0.8},
    "Нефтегаз":     {"РФ-бета": 0.8, "Ставка ЦБ": 0.3, "Потребитель": 0.0, "Рента/гос": 1.0, "Growth-стиль": 0.0},
    "Металл":       {"РФ-бета": 0.8, "Ставка ЦБ": 0.3, "Потребитель": 0.0, "Рента/гос": 0.8, "Growth-стиль": 0.1},
    "Золото":       {"РФ-бета": 0.5, "Ставка ЦБ": 0.2, "Потребитель": 0.0, "Рента/гос": 0.4, "Growth-стиль": 0.2},
    "Удобрения":    {"РФ-бета": 0.7, "Ставка ЦБ": 0.3, "Потребитель": 0.0, "Рента/гос": 0.6, "Growth-стиль": 0.1},
    "Телеком":      {"РФ-бета": 0.6, "Ставка ЦБ": 0.5, "Потребитель": 0.5, "Рента/гос": 0.2, "Growth-стиль": 0.1},
    "Инфраструк.":  {"РФ-бета": 0.7, "Ставка ЦБ": 0.3, "Потребитель": 0.0, "Рента/гос": 1.0, "Growth-стиль": 0.0},
}
DEFAULT_LOADING = {"РФ-бета": 0.8, "Ставка ЦБ": 0.4, "Потребитель": 0.3, "Рента/гос": 0.3, "Growth-стиль": 0.3}


def loadings_by_sector(sectors: dict[str, str]) -> dict[str, dict[str, float]]:
    """{secid: сектор} → {secid: загрузки}, по справочнику секторов."""
    return {sec: dict(SECTOR_LOADINGS.get(s, DEFAULT_LOADING)) for sec, s in sectors.items()}


@dataclass
class FactorDecomposition:
    concentration: dict[str, float]      # средняя загрузка по портфелю на фактор
    dominant_factor: str
    dominant_value: float
    flags: list[str] = field(default_factory=list)


def factor_decomposition(
    loadings: dict[str, dict[str, float]],
    *,
    weights: dict[str, float] | None = None,
) -> FactorDecomposition:
    """Концентрация по фактору = средняя (или взвешенная) загрузка по портфелю.

    loadings: {secid: {factor: 0..1}}. weights: {secid: вес} (по умолч. равные).
    """
    names = list(loadings.keys())
    if not names:
        raise ValueError("Пустой портфель")
    if weights is None:
        weights = {n: 1.0 / len(names) for n in names}
    wsum = sum(weights.values())

    conc: dict[str, float] = {}
    for f in FACTORS:
        conc[f] = sum(loadings[n].get(f, 0.0) * weights[n] for n in names) / wsum

    dom = max(conc, key=conc.get)
    flags: list[str] = []
    if conc[dom] > CONCENTRATION_THRESHOLD:
        flags.append(
            f"Доминирует фактор «{dom}» ({conc[dom]:.2f} > {CONCENTRATION_THRESHOLD}): "
            f"скрытая ставка на одну макрогипотезу."
        )
    return FactorDecomposition(
        concentration=conc, dominant_factor=dom,
        dominant_value=conc[dom], flags=flags,
    )


def sector_concentration(
    sectors: dict[str, str], *, weights: dict[str, float] | None = None,
    limit: float = 0.30,
) -> list[str]:
    """Флаг секторной концентрации (правило: банки ≤ ~25-30% портфеля)."""
    names = list(sectors.keys())
    if weights is None:
        weights = {n: 1.0 / len(names) for n in names}
    wsum = sum(weights.values())
    by_sector: dict[str, float] = {}
    for n in names:
        by_sector[sectors[n]] = by_sector.get(sectors[n], 0.0) + weights[n] / wsum
    flags = []
    for sec, share in by_sector.items():
        if share > limit:
            flags.append(
                f"Сектор «{sec}» = {share:.0%} портфеля (> {limit:.0%}): "
                f"несколько имён одного сектора — одна ставка с общим бета, "
                f"не диверсификация."
            )
    return flags


# Стресс-сценарии: грубая количественная реакция через РФ-бету + качественный драйвер
STRESS_SCENARIOS = [
    ("Шок −50% рынка", "market", -0.50,
     "высокий РФ-бета у всех; банки глубже, защитные мягче — момент докупки"),
    ("Снижение КС −5 п.п.", "rate_down", None,
     "классич. банки: маржа − но переоценка +; финтех устойчив; чистый лёгкий +"),
    ("Рост КС +5 п.п.", "rate_up", None,
     "вытеснение в ОФЗ, рынок вниз; маржа банков краткосрочно не спасает"),
    ("Падение нефти −30%", "oil", None,
     "только рента слабо −; не-нефтяной портфель устойчив (плюс не-рентности)"),
    ("Банковский кризис", "bank", None,
     "концентрация в ставочно-банковском факторе бьёт по всем банкам разом"),
]


@dataclass
class StressResult:
    scenario: str
    quant_reaction: float | None
    driver: str


def stress_test(decomp: FactorDecomposition) -> list[StressResult]:
    """Грубая количественная реакция для рыночного шока через РФ-бету;
    остальные сценарии — качественные (для частного портфеля достаточно).
    """
    rf_beta = decomp.concentration.get("РФ-бета", 0.0)
    out: list[StressResult] = []
    for name, kind, shock, driver in STRESS_SCENARIOS:
        if kind == "market" and shock is not None:
            out.append(StressResult(name, round(shock * rf_beta, 3), driver))
        else:
            out.append(StressResult(name, None, driver))
    return out


# ── Лимиты позиций (INSTRUCTION §8): эмитент / сектор / фактор, жёстче в RISK ──
ISSUER_LIMIT = 0.12          # потолок на одного эмитента (~12%)
RISK_TIGHTEN = 0.8           # в RISK лимиты ×0.8 (концентрацию режем в напряжении)


@dataclass
class LimitBreach:
    kind: str        # issuer | sector | factor
    key: str
    weight: float
    limit: float


def check_limits(
    weights: dict[str, float], sectors: dict[str, str], *,
    regime: str = "NORMAL", loadings: dict[str, dict[str, float]] | None = None,
    issuer_limit: float = ISSUER_LIMIT, sector_limit: float = 0.30,
    factor_limit: float = CONCENTRATION_THRESHOLD,
) -> list[LimitBreach]:
    """Нарушения лимитов: эмитент / сектор / фактор. В RISK лимиты ужесточаются.
    Лимит не снимать даже под лучшее имя — дисциплина важнее одной идеи (§8)."""
    scale = RISK_TIGHTEN if regime.upper() == "RISK" else 1.0
    il, sl, fl = issuer_limit * scale, sector_limit * scale, factor_limit * scale
    wsum = sum(weights.values()) or 1.0
    breaches: list[LimitBreach] = []
    for secid, w in weights.items():
        wn = w / wsum
        if wn > il:
            breaches.append(LimitBreach("issuer", secid, round(wn, 4), round(il, 4)))
    by_sector: dict[str, float] = {}
    for secid, w in weights.items():
        by_sector[sectors.get(secid, "—")] = by_sector.get(sectors.get(secid, "—"), 0.0) + w / wsum
    for s, w in by_sector.items():
        if w > sl:
            breaches.append(LimitBreach("sector", s, round(w, 4), round(sl, 4)))
    if loadings:
        decomp = factor_decomposition(loadings, weights=weights)
        for f, v in decomp.concentration.items():
            if v > fl:
                breaches.append(LimitBreach("factor", f, round(v, 4), round(fl, 4)))
    return breaches


@dataclass
class LiquidityFlag:
    secid: str
    days_to_exit: float | None
    illiquid: bool
    note: str


def liquidity_flag(
    *, secid: str, position_rub: float, adv_rub: float | None,
    free_float: float | None = None, max_adv_share: float = 0.20, max_days: float = 10.0,
) -> LiquidityFlag:
    """Можно ли выйти из позиции без просадки: дни на выход при ≤max_adv_share объёма/день.
    ADV/free-float — из MOEX (когда подключены); без них — graceful «не оценено»."""
    if not adv_rub or adv_rub <= 0:
        return LiquidityFlag(secid, None, False, "нет данных по среднедн. объёму (ADV) — ликвидность не оценена")
    days = position_rub / (adv_rub * max_adv_share)
    illiquid = days > max_days or (free_float is not None and free_float < 0.10)
    note = f"~{days:.1f} дн на выход (≤{int(max_adv_share*100)}% ADV/день)"
    if free_float is not None:
        note += f", free-float {free_float:.0%}"
    return LiquidityFlag(secid, round(days, 1), illiquid, note)
