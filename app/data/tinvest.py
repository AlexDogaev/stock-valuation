"""Клиент T-Invest API (Тинькофф/Т-Банк) — фундаментал уровня 2.

Метод GetAssetFundamentals отдаёт чистую прибыль, ROE, ROA, ROIC, P/B,
payout, капитализацию по эмитентам MOEX (то, что MOEX ISS не даёт). REST —
gRPC-gateway, поля в JSON camelCase.

ТОКЕН: читается из env TINVEST_TOKEN или файла .tinvest_token в корне проекта.
Сервис его НЕ хранит в коде и не коммитит. Получить токен:
T-Банк Инвестиции → Настройки → Токены для Invest API (нужен брокерский счёт).

Ограничение: API отдаёт ТЕКУЩИЙ срез (TTM/MRQ), без истории по годам.
Дополняет ручной seed из Excel, не заменяет его.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

from app.config import BASE_DIR

REST_BASE = "https://invest-public-api.tinkoff.ru/rest"
INSTRUMENTS = "tinkoff.public.invest.api.contract.v1.InstrumentsService"
TOKEN_FILE = BASE_DIR / ".tinvest_token"


def get_token() -> str | None:
    """Токен из env TINVEST_TOKEN или файла .tinvest_token (не в репозитории).
    Терпим к .txt-суффиксу, который Windows/блокнот дописывает к имени.
    """
    tok = os.environ.get("TINVEST_TOKEN")
    if tok:
        return tok.strip()
    for f in (TOKEN_FILE, TOKEN_FILE.with_suffix(".token.txt"),
              BASE_DIR / ".tinvest_token.txt"):
        if f.exists():
            t = f.read_text(encoding="utf-8").strip()
            if t:
                return t
    return None


def norm_pct(v) -> float | None:
    """T-Invest отдаёт проценты как число (roe=22.7). Приводим к доле (0.227).
    Эвристика: значения |v|>1.5 считаем процентами.
    """
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x / 100.0 if abs(x) > 1.5 else x


@dataclass
class Fundamentals:
    secid: str
    asset_uid: str
    net_profit_bln: float | None    # чистая прибыль TTM, млрд ₽
    roe: float | None
    roa: float | None
    roic: float | None
    payout: float | None
    pb: float | None
    cap_bln: float | None
    equity_bln: float | None        # выведено из cap / P/B
    revenue_bln: float | None


class TinvestClient:
    def __init__(self, token: str):
        self._client = httpx.Client(
            base_url=REST_BASE, timeout=30.0,
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
        )

    def _post(self, method: str, body: dict) -> dict:
        r = self._client.post(f"/{INSTRUMENTS}/{method}", json=body)
        r.raise_for_status()
        return r.json()

    def asset_uid(self, ticker: str, class_code: str = "TQBR") -> str | None:
        """asset_uid по тикеру через GetInstrumentBy."""
        d = self._post("GetInstrumentBy", {
            "idType": "INSTRUMENT_ID_TYPE_TICKER",
            "classCode": class_code, "id": ticker.upper(),
        })
        instr = d.get("instrument", {})
        return instr.get("assetUid")

    def get_fundamentals(self, asset_uids: list[str]) -> list[dict]:
        """GetAssetFundamentals по списку asset_uid (макс 100)."""
        if not asset_uids:
            return []
        d = self._post("GetAssetFundamentals", {"assets": asset_uids[:100]})
        return d.get("fundamentals", [])

    @staticmethod
    def parse(secid: str, f: dict) -> Fundamentals:
        cap = f.get("marketCapitalization")
        pb = f.get("priceToBookTtm")
        net = f.get("netIncomeTtm")
        rev = f.get("revenueTtm")
        equity = (cap / pb) if (cap and pb) else None
        bln = lambda x: (x / 1e9) if x else None
        return Fundamentals(
            secid=secid, asset_uid=f.get("assetUid", ""),
            net_profit_bln=bln(net),
            roe=norm_pct(f.get("roe")), roa=norm_pct(f.get("roa")),
            roic=norm_pct(f.get("roic")),
            payout=norm_pct(f.get("dividendPayoutRatioFy")),
            pb=pb, cap_bln=bln(cap), equity_bln=bln(equity),
            revenue_bln=bln(rev),
        )

    def close(self):
        self._client.close()
