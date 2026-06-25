"""SQLite — хранилище эмитентов, финансов, структурных баллов, настроек.

Расчётные величины (доходность, сигнал) НЕ хранятся — считаются на лету из
ядра, чтобы смена настроек пользователя сразу отражалась (SPEC §5).
Кэшируется только тяжёлое (рыночные снимки, история).
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator

from app.config import DB_PATH, DEFAULTS

SCHEMA = """
CREATE TABLE IF NOT EXISTS issuers (
    secid       TEXT PRIMARY KEY,
    shortname   TEXT,
    latname     TEXT,
    sector      TEXT,
    board       TEXT DEFAULT 'TQBR',
    issuesize   REAL,
    is_pref     INTEGER DEFAULT 0
);

-- снимок рыночных данных (последний из MOEX), для верифицируемости — с датой
CREATE TABLE IF NOT EXISTS market_data (
    secid       TEXT PRIMARY KEY,
    price       REAL,
    cap         REAL,
    div_yield   REAL,
    div_typical REAL,           -- типичная годовая дивдох (медиана по годам)
    div_spike   INTEGER DEFAULT 0,  -- 1 = TTM аномально выше нормы (спецдив?)
    fetched_at  TEXT,
    FOREIGN KEY (secid) REFERENCES issuers(secid)
);

CREATE TABLE IF NOT EXISTS dividends (
    secid     TEXT,
    reg_date  TEXT,
    value     REAL,
    currency  TEXT,
    PRIMARY KEY (secid, reg_date)
);

-- уровень 2 + параметры модели (ручной ввод / seed из Excel)
CREATE TABLE IF NOT EXISTS financials (
    secid           TEXT PRIMARY KEY,
    period          TEXT,
    net_profit      REAL,
    equity          REAL,
    roe             REAL,
    payout          REAL,
    g_base          REAL,       -- базовый рост g
    compression     REAL,       -- сжатие мультипликатора (зрелый=1)
    revenue_growth  REAL,
    roic            REAL,
    wacc            REAL,
    body_trend      INTEGER,    -- 1/0/-1
    is_resource     INTEGER DEFAULT 0,
    is_rentier      INTEGER DEFAULT 0,
    etype           TEXT,       -- структурный тип-ярлык
    source          TEXT,
    updated_at      TEXT,
    FOREIGN KEY (secid) REFERENCES issuers(secid)
);

-- структурные баллы (экспертное суждение, не из API)
CREATE TABLE IF NOT EXISTS structural (
    secid       TEXT PRIMARY KEY,
    moat        INTEGER DEFAULT 0,
    disruption  INTEGER DEFAULT 0,
    tam         INTEGER DEFAULT 0,
    regulation  INTEGER DEFAULT 0,
    demo        INTEGER DEFAULT 0,
    gosnaves    INTEGER DEFAULT 0,
    mult_seed   REAL,        -- множитель из ТОП-25, когда детальных баллов нет
    note        TEXT,
    updated_by  TEXT,
    updated_at  TEXT,
    FOREIGN KEY (secid) REFERENCES issuers(secid)
);

-- история фундаментала по годам (снапшоты T-Invest вперёд + ручная ретроспектива).
-- База для roic_years (устойчивость ROIC ≥ N лет) в маркерах качества.
CREATE TABLE IF NOT EXISTS financials_history (
    secid        TEXT,
    year         INTEGER,
    roic         REAL,
    wacc         REAL,
    payout       REAL,
    net_profit   REAL,
    source       TEXT,
    snapshot_at  TEXT,
    PRIMARY KEY (secid, year),
    FOREIGN KEY (secid) REFERENCES issuers(secid)
);

-- черновик структурных баллов от LLM (класс B); человек подтверждает → structural
CREATE TABLE IF NOT EXISTS structural_draft (
    secid                TEXT PRIMARY KEY,
    moat                 INTEGER, disruption INTEGER, tam INTEGER,
    regulation           INTEGER, demo INTEGER, gosnaves INTEGER,
    monetization_proven  INTEGER,
    rationale            TEXT,
    model                TEXT,
    created_at           TEXT,
    FOREIGN KEY (secid) REFERENCES issuers(secid)
);

CREATE TABLE IF NOT EXISTS macro (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    key_rate        REAL,
    cpi_official    REAL,
    cpi_smoothed    REAL,
    ofz_long_yield  REAL,
    updated_at      TEXT
);

-- курируемый макро-брифинг (свежие факты для глубокого анализа Опусом перед публикацией)
CREATE TABLE IF NOT EXISTS macro_context (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    context_md  TEXT,
    source      TEXT,
    updated_at  TEXT
);

-- кеш анализа Опуса над макро-режимом (advisory; правила остаются костяком)
CREATE TABLE IF NOT EXISTS macro_analysis (
    id           INTEGER PRIMARY KEY CHECK (id = 1),
    regime_rule  TEXT,
    regime_opus  TEXT,
    confidence   TEXT,
    verdict      TEXT,
    nuances_json TEXT,
    note         TEXT,
    model        TEXT,
    created_at   TEXT
);

-- траектория ключевой ставки: градация Opus по пейсу решений + риторике ЦБ (кеш)
CREATE TABLE IF NOT EXISTS rate_trajectory (
    id             INTEGER PRIMARY KEY CHECK (id = 1),
    grade          TEXT,       -- агрессивное/обычное/медленное снижение|повышение | удержание
    terminal_ks    REAL,       -- терминальная КС (доля), куда сойдёт
    avg_step_pp    REAL,       -- средний шаг за заседание, пп (числовой пейс)
    confidence     TEXT,
    rationale      TEXT,
    signal_read    TEXT,       -- как Opus прочитал риторику ЦБ
    source         TEXT,       -- 'Opus + риторика' | 'пейс (без Opus)'
    decisions_json TEXT,       -- последние решения [[дата,ставка],...]
    model          TEXT,
    created_at     TEXT
);

-- помесячные точки Urals для сглаживания режима (#9): MA 1-3 мес фильтрует overshoot
CREATE TABLE IF NOT EXISTS urals_history (
    month       TEXT PRIMARY KEY,   -- YYYY-MM
    urals       REAL,
    updated_at  TEXT
);

-- ручной ввод риторики ЦБ (override авто-фетча keypr) для градации траектории
CREATE TABLE IF NOT EXISTS rate_signal (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    text        TEXT,
    updated_at  TEXT
);

-- форвардная вероятность ШОКА по сценариям (субъективная оценка Opus, кеш)
CREATE TABLE IF NOT EXISTS shock_risk (
    id             INTEGER PRIMARY KEY CHECK (id = 1),
    aggregate_pct  REAL,
    horizon        TEXT,
    scenarios_json TEXT,
    note           TEXT,
    model          TEXT,
    created_at     TEXT
);

CREATE TABLE IF NOT EXISTS user_settings (
    id                INTEGER PRIMARY KEY CHECK (id = 1),
    hurdle            REAL,
    buffer            REAL,
    regime            TEXT,
    risk_premium      REAL,
    deflator_preset   TEXT,
    rosstat_current   REAL,
    rosstat_smoothed  REAL,
    basket_json       TEXT     -- корзина личной инфляции (JSON)
);

-- события (лог изменений маркеров/режима/сигналов) — проактивность, §7 плана
CREATE TABLE IF NOT EXISTS events (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT,
    kind     TEXT,      -- signal | quality | regime
    secid    TEXT,
    message  TEXT,
    notified INTEGER DEFAULT 0
);

-- сохранённое предыдущее состояние эмитента (для детекции изменений)
CREATE TABLE IF NOT EXISTS issuer_state (
    secid           TEXT PRIMARY KEY,
    signal          TEXT,
    quality_marker  TEXT,
    updated_at      TEXT,
    FOREIGN KEY (secid) REFERENCES issuers(secid)
);

CREATE TABLE IF NOT EXISTS portfolio (
    secid   TEXT PRIMARY KEY,
    weight  REAL,
    FOREIGN KEY (secid) REFERENCES issuers(secid)
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL: одновременная запись (планировщик) и чтение (веб) без блокировок
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _ensure_column(db, table: str, col: str, decl: str) -> None:
    """Лёгкая миграция: добавить колонку, если её ещё нет."""
    cols = {r["name"] for r in db.execute(f"PRAGMA table_info({table})")}
    if col not in cols:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def init_db() -> None:
    with get_db() as db:
        db.executescript(SCHEMA)
        # миграции для БД, созданных более ранней схемой
        _ensure_column(db, "market_data", "div_typical", "REAL")
        _ensure_column(db, "market_data", "div_spike", "INTEGER DEFAULT 0")
        _ensure_column(db, "user_settings", "forecast_years", "INTEGER DEFAULT 3")
        _ensure_column(db, "user_settings", "felt_inflation", "REAL DEFAULT 0.14")  # ощущаемая инфляция год 1 (дефлятор)
        _ensure_column(db, "user_settings", "inflation_terminal", "REAL DEFAULT 0.08")  # терминальная инфляция (траектория КС)
        _ensure_column(db, "user_settings", "tax_rate", "REAL DEFAULT 0.13")     # НДФЛ (посленалоговый слой)
        _ensure_column(db, "user_settings", "tax_aware", "INTEGER DEFAULT 1")    # сигнал на посленалоговой основе
        _ensure_column(db, "user_settings", "iis3", "INTEGER DEFAULT 0")         # обёртка ИИС-3
        _ensure_column(db, "user_settings", "normal_pe", "REAL DEFAULT 6.0")     # «нормальный» P/E РФ для теста оптимизма (#3, вынесен из хардкода)
        _ensure_column(db, "user_settings", "ewi_json", "TEXT")              # EWI движка hazard (нефть/спреды/дефолты/сенсор)
        _ensure_column(db, "user_settings", "integration_json", "TEXT")      # индекс интеграции (фин/торг/валют/тех × Запад/Восток)
        _ensure_column(db, "user_settings", "shock_weights_json", "TEXT")    # веса типологии шока (geo/commodity/global/financial/lstag)
        _ensure_column(db, "user_settings", "key_rate_override", "REAL")     # ручная КС (объявленная ЦБ до публикации в SOAP)
        _ensure_column(db, "user_settings", "inflation_terminal_override", "REAL")  # ручной терминал инфляции (стресс: залипание инфл выше)
        _ensure_column(db, "financials", "currency_profile", "TEXT DEFAULT 'MIXED'")  # EXPORTER|DOMESTIC|MIXED (#11)
        _ensure_column(db, "structural", "moat_risk", "INTEGER DEFAULT 0")    # уязвимость рва к дизрупции 0/1/2 (§4,9)
        _ensure_column(db, "structural", "is_enabler", "INTEGER DEFAULT 0")   # ENABLER-рельса (рента устойчивее) (§4)
        # обнуляющие РФ-риски (red-team #5): 0 нет / 1 повышенный / 2 острый — гейт сигнала
        _ensure_column(db, "structural", "minority_risk", "INTEGER DEFAULT 0")       # корп.упр / миноритарий
        _ensure_column(db, "structural", "expropriation_risk", "INTEGER DEFAULT 0")  # экспроприация/национализация
        _ensure_column(db, "structural", "delisting_risk", "INTEGER DEFAULT 0")      # делистинг
        _ensure_column(db, "structural", "sanctions_risk", "INTEGER DEFAULT 0")      # санкц.заморозка
        _ensure_column(db, "structural", "liquidity_risk", "INTEGER DEFAULT 0")      # неликвидность выхода
        # v6 фаза 2: порода происхождения (0.4) + ценопрессинг (3-й канал изъятия 0.3, бьёт по марже)
        _ensure_column(db, "structural", "breed", "TEXT")              # privatization|state|oligarch|venture|debt
        _ensure_column(db, "structural", "pricing_pressure", "INTEGER DEFAULT 0")  # ценопрессинг 0/1/2 (соц-базовое благо)
        _ensure_column(db, "structural", "nd_ebitda", "REAL")          # Долг/EBITDA — для профиля предперехвата (Гл.7)
        _ensure_column(db, "structural", "renovation_node", "INTEGER DEFAULT 0")  # узел реновации Триады (Гл.16, поставщик)
        _ensure_column(db, "shock_risk", "expected_damage_pct", "REAL")  # Σ P×severity (#15)
        _ensure_column(db, "shock_risk", "independent_pct", "REAL")      # наивная 1−∏(1−p)
        _ensure_column(db, "shock_risk", "p_horizon3_pct", "REAL")       # P за 3 года (горизонт решения)
        # шок-ВЕКТОР по факторам (макро-прогноз: шок влияет на ВСЕ классы, не только IMOEX)
        _ensure_column(db, "shock_risk", "shock_infl_pp", "REAL")        # +пп к инфляции в шоке
        _ensure_column(db, "shock_risk", "shock_fx_pct", "REAL")         # девальвация рубля в шоке, %
        _ensure_column(db, "shock_risk", "shock_ks_pp", "REAL")          # +пп к КС в шоке
        _ensure_column(db, "shock_risk", "imoex_drawdown_pct", "REAL")   # УСЛОВНАЯ просадка IMOEX (2014/2022)
        _ensure_column(db, "shock_risk", "recovery_1y", "REAL")          # доля просадки, отыгранная за год
        _ensure_column(db, "shock_risk", "sectoral_json", "TEXT")        # секторальные просадки в шоке
        _ensure_column(db, "rate_trajectory", "disinflation_months", "REAL")  # окно выхода инфл. на терминал (Opus/траектория)
        # для маркеров качества (§2-4 плана автономности)
        _ensure_column(db, "financials", "proven_roic_years", "INTEGER")  # экспертная ретроспектива
        _ensure_column(db, "financials", "needs_review", "INTEGER DEFAULT 0")  # авто-флаг пересмотра
        _ensure_column(db, "structural", "monetization_proven", "INTEGER DEFAULT 0")  # класс B
        _ensure_column(db, "structural", "is_platform", "INTEGER DEFAULT 0")  # класс B (§3): платформенный критерий
        # ФНБ / бюджетное правило для режима (ручной ввод, §3 плана)
        _ensure_column(db, "macro", "nwf_liquid_pct", "REAL DEFAULT 2.0")       # ликвидный ФНБ, % ВВП
        _ensure_column(db, "macro", "nwf_months_to_zero", "REAL DEFAULT 24")    # мес до исчерпания
        _ensure_column(db, "macro", "urals", "REAL DEFAULT 60")                 # факт Urals, $/барр
        _ensure_column(db, "macro", "oil_cutoff", "REAL DEFAULT 60")            # цена отсечения, $/барр
        _ensure_column(db, "macro", "last_regime", "TEXT")                      # для детекции смены режима
        # фискальное доминирование (§2): дисконт пылесоса. Ручной ввод Минфина (как ФНБ).
        _ensure_column(db, "macro", "fiscal_deficit_trln", "REAL DEFAULT 7.5")   # дефицит-прогноз/run-rate, трлн ₽/год
        _ensure_column(db, "macro", "fiscal_plan_trln", "REAL DEFAULT 3.786")    # плановый дефицит года, трлн ₽
        _ensure_column(db, "macro", "gdp_trln", "REAL DEFAULT 200.0")            # номинальный ВВП, трлн ₽ (знаменатель)
        # дефолтные настройки (single user, id=1)
        row = db.execute("SELECT id FROM user_settings WHERE id = 1").fetchone()
        if row is None:
            db.execute(
                """INSERT INTO user_settings
                   (id, hurdle, buffer, regime, risk_premium, deflator_preset,
                    rosstat_current, rosstat_smoothed, basket_json)
                   VALUES (1, ?, ?, ?, ?, ?, ?, ?, NULL)""",
                (DEFAULTS["hurdle"], DEFAULTS["buffer"], DEFAULTS["regime"],
                 DEFAULTS["risk_premium"], DEFAULTS["deflator_preset"],
                 DEFAULTS["rosstat_current"], DEFAULTS["rosstat_smoothed"]),
            )
        if db.execute("SELECT id FROM macro WHERE id = 1").fetchone() is None:
            db.execute(
                """INSERT INTO macro (id, key_rate, cpi_official, cpi_smoothed,
                   ofz_long_yield, updated_at)
                   VALUES (1, 0.145, ?, ?, 0.14, datetime('now'))""",
                (DEFAULTS["rosstat_current"], DEFAULTS["rosstat_smoothed"]),
            )


# ── helpers ───────────────────────────────────────────────────────────────────
def upsert(db: sqlite3.Connection, table: str, data: dict[str, Any], pk: str) -> None:
    cols = ", ".join(data.keys())
    ph = ", ".join("?" for _ in data)
    updates = ", ".join(f"{k}=excluded.{k}" for k in data if k != pk)
    sql = (f"INSERT INTO {table} ({cols}) VALUES ({ph}) "
           f"ON CONFLICT({pk}) DO UPDATE SET {updates}")
    db.execute(sql, tuple(data.values()))


def get_settings(db: sqlite3.Connection) -> dict:
    return dict(db.execute("SELECT * FROM user_settings WHERE id = 1").fetchone())


def get_macro(db: sqlite3.Connection) -> dict:
    return dict(db.execute("SELECT * FROM macro WHERE id = 1").fetchone())


def effective_key_rate(db: sqlite3.Connection) -> float | None:
    """Действующая КС: ручной override (объявленная ЦБ до публикации в SOAP) приоритетнее
    фетченной из macro. Кормит carry/дефлятор/траекторию (current_ks)."""
    ov = get_settings(db).get("key_rate_override")
    if ov is not None:
        return ov
    return get_macro(db).get("key_rate")


def roic_years(db: sqlite3.Connection, secid: str) -> int:
    """Сколько лет устойчивого ROIC (≥ WACC) у эмитента.

    Берёт максимум из: (а) экспертной ретроспективы financials.proven_roic_years
    (seed для голубых фишек, пока история не накопилась) и (б) фактической серии
    подряд лет с roic ≥ wacc из financials_history (накапливается снапшотами).
    """
    frow = db.execute(
        "SELECT proven_roic_years FROM financials WHERE secid = ?", (secid,)
    ).fetchone()
    seed = (frow["proven_roic_years"] or 0) if frow else 0
    streak = 0
    for h in db.execute(
        "SELECT roic, wacc FROM financials_history WHERE secid = ? ORDER BY year DESC",
        (secid,),
    ):
        if h["roic"] is not None and h["wacc"] is not None and h["roic"] >= h["wacc"]:
            streak += 1
        else:
            break
    return max(seed, streak)


def snapshot_financials(db: sqlite3.Connection, year: int, snapshot_at: str) -> int:
    """Записать текущий срез financials в историю под указанный год (накопление вперёд)."""
    n = 0
    for r in db.execute("SELECT secid, roic, wacc, payout, net_profit, source FROM financials"):
        if r["roic"] is None:
            continue
        upsert(db, "financials_history", dict(
            secid=r["secid"], year=year, roic=r["roic"], wacc=r["wacc"],
            payout=r["payout"], net_profit=r["net_profit"],
            source=r["source"], snapshot_at=snapshot_at,
        ), pk="secid, year")
        n += 1
    return n
