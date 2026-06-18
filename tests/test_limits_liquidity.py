"""Лимиты позиций (§8) и флаг ликвидности (§9)."""
from app.core.portfolio import check_limits, liquidity_flag, loadings_by_sector


def test_issuer_limit_breach():
    w = {"SBER": 0.20, "T": 0.10, "X5": 0.10}  # SBER > 12%
    b = check_limits(w, {"SBER": "Банк", "T": "Банк", "X5": "Ритейл"})
    issuer = [x for x in b if x.kind == "issuer"]
    assert any(x.key == "SBER" for x in issuer)


def test_risk_regime_tightens_limits():
    w = {"A": 0.11, "B": 0.11, "C": 0.78}
    sectors = {"A": "Банк", "B": "Ритейл", "C": "IT"}
    normal = check_limits(w, sectors, regime="NORMAL")
    risk = check_limits(w, sectors, regime="RISK")
    # 11% не бьёт лимит 12% в NORMAL, но бьёт 9.6% в RISK
    assert not any(x.kind == "issuer" and x.key == "A" for x in normal)
    assert any(x.kind == "issuer" and x.key == "A" for x in risk)


def test_sector_limit_breach():
    w = {"SBER": 0.20, "VTBR": 0.20, "T": 0.10}  # Банк = 50% > 30%
    sectors = {"SBER": "Банк", "VTBR": "Банк", "T": "Банк"}
    b = check_limits(w, sectors)
    assert any(x.kind == "sector" and x.key == "Банк" for x in b)


def test_factor_limit_breach_via_loadings():
    w = {"SBER": 0.5, "VTBR": 0.5}
    sectors = {"SBER": "Банк", "VTBR": "Банк"}
    b = check_limits(w, sectors, loadings=loadings_by_sector(sectors))
    assert any(x.kind == "factor" for x in b)  # банки → РФ-бета/Ставка ЦБ зашкаливают


def test_liquidity_flag_illiquid_and_graceful():
    illiq = liquidity_flag(secid="SMOL", position_rub=1e8, adv_rub=1e6)  # огромная позиция, тонкий объём
    assert illiq.illiquid is True and illiq.days_to_exit > 10
    liquid = liquidity_flag(secid="SBER", position_rub=1e6, adv_rub=1e10)
    assert liquid.illiquid is False
    nodata = liquidity_flag(secid="X", position_rub=1e6, adv_rub=None)
    assert nodata.illiquid is False and "не оценена" in nodata.note
