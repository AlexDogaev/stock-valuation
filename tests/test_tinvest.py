"""Парсинг ответа T-Invest GetAssetFundamentals → поля financials."""
import math
import os

from app.data.tinvest import norm_pct, TinvestClient, get_token


def approx(a, b, tol=0.01):
    return a is not None and math.isclose(a, b, abs_tol=tol)


def test_norm_pct_percent_to_fraction():
    assert approx(norm_pct(22.7), 0.227)   # пришло как процент
    assert approx(norm_pct(50), 0.5)
    assert approx(norm_pct(0.227), 0.227)  # уже доля — не трогаем
    assert norm_pct(None) is None
    assert norm_pct("") is None


def test_parse_sber_like():
    # мок ответа T-Invest (REST camelCase) для Сбер-подобного эмитента
    f = {
        "assetUid": "abc-uid",
        "netIncomeTtm": 1700e9,           # 1700 млрд
        "roe": 22.7, "roa": 2.75, "roic": 20.0,
        "dividendPayoutRatioFy": 50.0,
        "marketCapitalization": 6987e9,   # 6987 млрд
        "priceToBookTtm": 0.93,
        "revenueTtm": 3000e9,
    }
    d = TinvestClient.parse("SBER", f)
    assert d.secid == "SBER" and d.asset_uid == "abc-uid"
    assert approx(d.net_profit_bln, 1700, tol=1)
    assert approx(d.roe, 0.227)
    assert approx(d.payout, 0.5)
    assert approx(d.roic, 0.20)
    assert approx(d.cap_bln, 6987, tol=1)
    # капитал = капа / P/B = 6987 / 0.93 ≈ 7513 млрд
    assert approx(d.equity_bln, 7513, tol=2)


def test_parse_missing_fields():
    d = TinvestClient.parse("X", {"assetUid": "u"})
    assert d.net_profit_bln is None and d.equity_bln is None and d.roe is None


def test_get_token_absent(monkeypatch, tmp_path):
    # без env и без файла токена → None (graceful)
    monkeypatch.delenv("TINVEST_TOKEN", raising=False)
    monkeypatch.setattr("app.data.tinvest.TOKEN_FILE", tmp_path / "nope")
    assert get_token() is None
