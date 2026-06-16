"""Клиент ЕМИСС (fedstat.ru) — официальная инфляция Росстата по категориям.

По образцу fedstatAPIr (github.com/DenchPokepon/fedstatAPIr). Ключевое:
ЕМИСС с апреля 2025 блокит дефолтные User-Agent (403) — нужен браузерный UA.
Данные отдаются в SDMX-ML через POST /indicator/data.do; метаданные фильтров —
через GET /indicator/dataGrid.do?id=<ID>.

ВАЖНО: ЕМИСС блокирует не-РФ IP (из облака/песочницы — 403/timeout). Работает с
РФ-адреса (локальная машина / сервер). Точные filterObjectIds видны только из
ответа dataGrid.do — запусти diagnose() на РФ-машине и пришли вывод для настройки.

Индикатор ИПЦ: 31074 (Индекс потребительских цен на товары и услуги).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

BASE = "https://www.fedstat.ru"
CPI_INDICATOR = "31074"

# Браузерный UA + Referer обязательны (обход блокировки дефолтных клиентов).
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
}


def _client() -> httpx.Client:
    # один клиент с cookie-сессией: dataGrid.do ставит cookie, нужные для data.do
    return httpx.Client(base_url=BASE, headers=HEADERS, timeout=40.0,
                        follow_redirects=True)


def fetch_metadata(indicator: str = CPI_INDICATOR, client: httpx.Client | None = None) -> str:
    """GET dataGrid.do — сырой ответ с метаданными фильтров (filterObjectIds).
    Возвращает текст для анализа (на РФ-машине). Бросает при сетевой ошибке.
    """
    own = client is None
    c = client or _client()
    try:
        r = c.get("/indicator/dataGrid.do", params={"id": indicator})
        r.raise_for_status()
        return r.text
    finally:
        if own:
            c.close()


def parse_filter_options(meta_text: str) -> dict[str, list[tuple[str, str]]]:
    """Грубое извлечение фильтров из dataGrid.do: имя поля → [(id, подпись)].

    ЕМИСС отдаёт filterObjectIds в JS-структуре. Парсер эвристический —
    уточним по реальному ответу с РФ-машины (структура может отличаться).
    """
    out: dict[str, list[tuple[str, str]]] = {}
    # частый паттерн: "filterObjectIds":{"<dimId>":{...,"values":{"<valId>":{"title":"..."}}}}
    for dim, val_id, title in re.findall(
        r'"(\d+)"\s*:\s*\{[^{}]*?"(\d+)"\s*:\s*\{[^{}]*?"title"\s*:\s*"([^"]+)"', meta_text):
        out.setdefault(dim, []).append((val_id, title))
    return out


def fetch_data(indicator: str, form: dict, client: httpx.Client | None = None) -> str:
    """POST data.do с выбранными фильтрами → SDMX-ML (сырой текст).

    form — словарь полей запроса (id, lineObjectIds, columnObjectIds,
    selectedFilterIds...). Конкретные значения зависят от метаданных индикатора.
    """
    own = client is None
    c = client or _client()
    try:
        body = {"id": indicator, **form}
        r = c.post("/indicator/data.do", data=body)
        r.raise_for_status()
        return r.text
    finally:
        if own:
            c.close()


# ЕМИСС отдаёт JSON: {"results": [{"dim57831": регион, "dim58273": категория,
#   "dim<YEAR>_<period>_<type>_d<cell>_i<x>": "знач"}, ...]}.
# Тип индекса (3-й код): 1704140 = к пред. году (г/г), 1704142 = к пред. месяцу,
# 1704143 = накопленным итогом. Значения вида "106,84" = индекс (106.84 → +6.84%).
REGION_DIM = "dim57831"
CATEGORY_DIM = "dim58273"
TYPE_YOY = "1704140"   # к соответствующему периоду предыдущего года


@dataclass
class CpiRow:
    region: str
    category: str
    yoy: list[float]      # значения г/г по месяцам (индекс, 106.84 = +6.84%)


def parse_results(data: dict, index_type: str = TYPE_YOY) -> list[CpiRow]:
    """Распарсить JSON ЕМИСС → строки (регион, категория, ряд г/г-значений)."""
    out: list[CpiRow] = []
    for row in data.get("results", []):
        region = row.get(REGION_DIM, "")
        category = row.get(CATEGORY_DIM, "")
        vals = []
        for k, v in row.items():
            m = re.match(r"dim\d{4}_\d+_(\d+)_", k)
            if m and m.group(1) == index_type:
                try:
                    vals.append(float(str(v).replace(",", ".")))
                except (ValueError, TypeError):
                    pass
        if vals:
            out.append(CpiRow(region, category, vals))
    return out


def category_inflation(data: dict, region: str | None = None) -> dict[str, float]:
    """{категория: годовая инфляция %} — берёт МАКС период (свежий) по г/г.
    region=None → первый доступный регион (для агрегата укажи 'Российская Федерация').
    """
    out: dict[str, float] = {}
    for r in parse_results(data, TYPE_YOY):
        if region and r.region != region:
            continue
        if r.yoy:
            out[r.category] = round(max(r.yoy) - 100, 2)  # свежий г/г как индекс−100
    return out


def diagnose() -> None:
    """Запусти на РФ-машине (локаль/сервер). Печатает доступность ЕМИСС,
    извлечённые фильтры и пробный кусок данных. Вывод пришли — доработаю парсер.
    """
    import io, sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    print("=== ЕМИСС диагностика (indicator 31074, ИПЦ) ===")
    try:
        with _client() as c:
            meta = fetch_metadata(CPI_INDICATOR, c)
            print(f"[1] dataGrid.do: OK, {len(meta)} байт")
            filters = parse_filter_options(meta)
            print(f"[2] извлечено измерений-фильтров: {len(filters)}")
            for dim, vals in list(filters.items())[:8]:
                print(f"    dim {dim}: {len(vals)} значений, напр. {vals[:3]}")
            # пробный запрос без фильтров (часто отдаёт всё/ошибку — увидим формат)
            try:
                data = fetch_data(CPI_INDICATOR, {"lineObjectIds": "", "columnObjectIds": ""}, c)
                print(f"[3] data.do: OK, {len(data)} байт")
                pts = parse_sdmx(data)
                print(f"[4] распознано наблюдений: {len(pts)}; последние: {pts[-3:]}")
                if not pts:
                    print("    SDMX не распознан — пришли первые 600 символов ответа:")
                    print("    " + data[:600].replace("\n", " "))
            except Exception as e:  # noqa: BLE001
                print(f"[3] data.do ОШИБКА: {type(e).__name__} {str(e)[:120]}")
    except Exception as e:  # noqa: BLE001
        print(f"[X] ЕМИСС недоступен: {type(e).__name__} {str(e)[:120]}")
        print("    (если это РФ-машина и всё равно блок — пришли ошибку, разберёмся)")


if __name__ == "__main__":
    diagnose()
