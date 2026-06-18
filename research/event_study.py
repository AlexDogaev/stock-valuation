#!/usr/bin/env python
"""Event study (#13): эмпирические лаги реакции на нефтяные шоки → калибровка окна #9.

Идея: после резкого движения Urals (|Δ| > порога) измеряем реакцию IMOEX и USDRUB в окнах
T+1д / +1нед / +1мес / +3мес. Если ранняя реакция откатывает (overshoot) — режим надо вести
по СГЛАЖЕННОЙ нефти (длиннее окно MA в nwf_regime); если дрейф устойчив — окно короче.

Данные: IMOEX и USDRUB — MOEX (history_close). Urals — из таблицы urals_history (ручные
помесячные точки) ИЛИ CSV через --urals-csv (date,urals). Без ряда Urals скрипт честно
сообщает, что калибровать не на чем (нужны помесячные точки нефти).

Запуск на dev:  python research/event_study.py [--threshold 0.12] [--urals-csv path]
Это research-инструмент, не часть рантайма (в Docker-образ не входит).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:  # Windows-консоль по умолчанию cp1251 — падает на Δ/Cyrillic
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

HORIZONS = {"+1д": 1, "+1нед": 7, "+1мес": 30, "+3мес": 91}


def _to_map(series: list[tuple[str, float]]) -> dict[str, float]:
    return {d: v for d, v in series}


def _nearest_on_or_after(dates: list[str], target: str) -> str | None:
    return next((d for d in dates if d >= target), None)


def load_urals(csv_path: str | None) -> list[tuple[str, float]]:
    if csv_path:
        rows = []
        for line in Path(csv_path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.lower().startswith("date"):
                continue
            d, v = line.split(",")[:2]
            rows.append((d.strip(), float(v)))
        return sorted(rows)
    from app.data.db import get_db
    with get_db() as db:
        return [(r["month"], r["urals"]) for r in db.execute(
            "SELECT month, urals FROM urals_history WHERE urals IS NOT NULL ORDER BY month")]


def find_oil_shocks(urals: list[tuple[str, float]], threshold: float) -> list[tuple[str, float]]:
    """Даты, где Urals изменилась более чем на threshold (доля) к предыдущей точке."""
    shocks = []
    for (d0, v0), (d1, v1) in zip(urals, urals[1:]):
        if v0 and abs(v1 / v0 - 1.0) >= threshold:
            shocks.append((d1, v1 / v0 - 1.0))
    return shocks


def reaction(series_map: dict[str, float], dates: list[str], shock_date: str) -> dict[str, float | None]:
    from datetime import date, timedelta
    base_d = _nearest_on_or_after(dates, shock_date)
    if base_d is None:
        return {h: None for h in HORIZONS}
    base = series_map[base_d]
    out: dict[str, float | None] = {}
    for h, days in HORIZONS.items():
        t = (date.fromisoformat(base_d) + timedelta(days=days)).isoformat()
        fd = _nearest_on_or_after(dates, t)
        out[h] = round(series_map[fd] / base - 1.0, 4) if fd and base else None
    return out


def median(xs: list[float]) -> float | None:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=0.12)
    ap.add_argument("--urals-csv", default=None)
    args = ap.parse_args()

    urals = load_urals(args.urals_csv)
    if len(urals) < 4:
        print(f"⚠ Ряд Urals слишком короткий ({len(urals)} точек). Калибровать не на чем.")
        print("  Добавь помесячные точки: PUT /api/regime/urals_point {month,urals} или --urals-csv.")
        return
    shocks = find_oil_shocks(urals, args.threshold)
    print(f"Urals: {len(urals)} точек, нефтяных шоков (|Δ|≥{args.threshold:.0%}): {len(shocks)}")
    if not shocks:
        print("  Шоков по порогу не найдено — снизь --threshold или пополни ряд.")
        return

    from app.data.moex import MoexClient
    cl = MoexClient()
    try:
        imoex = cl.history_close("IMOEX", days=1500)
        try:
            usdrub = cl.history_close("USD000UTSTOM", days=1500)
        except Exception:  # noqa: BLE001 — валютный инструмент может не отдаться этим методом
            usdrub = []
    finally:
        cl.close()

    for label, series in (("IMOEX", imoex), ("USDRUB", usdrub)):
        if not series:
            print(f"\n{label}: нет данных (MOEX не отдал ряд).")
            continue
        smap, dts = _to_map(series), sorted(d for d, _ in series)
        per_h = {h: [] for h in HORIZONS}
        for sd, _ in shocks:
            r = reaction(smap, dts, sd)
            for h in HORIZONS:
                per_h[h].append(r[h])
        print(f"\n{label} — медианная реакция после нефтяных шоков:")
        for h in HORIZONS:
            m = median(per_h[h])
            print(f"  {h:>6}: {('%+.1f%%' % (m*100)) if m is not None else 'н/д'}")
        print("  Вывод: если ранние окна сильнее поздних и знак меняется — overshoot (вести режим по"
              " сглаженной нефти, длиннее MA); если дрейф устойчив — окно короче.")


if __name__ == "__main__":
    main()
