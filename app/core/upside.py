"""Разложение апсайда — анти-романтика роста (INSTRUCTIONS §4, NOTES §4).

Модель НЕ принимает «растущий рынок → кратный апсайд». Апсайд раскладывается на
источники, КАЖДЫЙ проверяется на потолок. Кратность засчитывается ТОЛЬКО если
хотя бы один источник не упёрт. Все упёрты (ОЗОН: проникновение ~×2, юзеры
насыщены, реклама near-saturation, флоут конечен) → кратного апсайда нет.

Класс B: упёртость и headroom каждого источника — суждение (LLM-черновик + человек).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class UpsideSource:
    """Источник апсайда. headroom — остаточная кратность (1.0 = потолок достигнут)."""
    name: str
    capped: bool
    headroom: float = 1.0   # ×к текущему, что ещё не выбрано (1.0 → упёрт)
    note: str = ""


@dataclass
class UpsideResult:
    sources: list[UpsideSource]
    has_uncapped: bool
    combined_headroom: float   # произведение headroom незапёртых источников
    multiple_warranted: bool   # засчитывать ли кратный апсайд
    verdict: str
    warnings: list[str] = field(default_factory=list)


def decompose_upside(sources: list[UpsideSource]) -> UpsideResult:
    """Кратный апсайд оправдан ⇔ хотя бы один источник не упёрт (§4)."""
    uncapped = [s for s in sources if not s.capped]
    has_uncapped = bool(uncapped)
    combined = 1.0
    for s in uncapped:
        combined *= max(1.0, s.headroom)

    warnings: list[str] = []
    if not has_uncapped:
        verdict = ("все источники апсайда упёрты — кратного бизнес-апсайда нет "
                   "(апсайд возможен только из недозаложенной нормализации/переоценки)")
        warnings.append(
            "Кратный апсайд НЕ оправдан: каждый источник у потолка. Маркер не должен "
            "подниматься до полноценного перспективного качества на «растущем рынке».")
    elif combined < 1.2:
        verdict = "незапёртые источники есть, но headroom скромный (< ×1.2)"
    else:
        verdict = f"есть незапёртый апсайд (совокупный headroom ≈ ×{combined:.1f})"
    return UpsideResult(sources=sources, has_uncapped=has_uncapped,
                        combined_headroom=combined, multiple_warranted=has_uncapped,
                        verdict=verdict, warnings=warnings)
