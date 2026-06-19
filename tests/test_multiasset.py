"""Мультиассет: carry (единый hurdle по КС), bonds (троичный), credit_pd, fx."""
from app.core.carry import carry_rate
from app.core.credit_pd import pd_market, pd_synthesis, credit_ok
from app.core.bonds import assess_bond, rate_signal_for
from app.core.fx import assess_fx
from app.core.valuation import inflation_to_maturity


# ── carry ────────────────────────────────────────────────────────────────────
def test_carry_flat_short_horizon():
    assert carry_rate(0.16, 0.10, 1) == 0.16        # горизонт 1 → спот


def test_carry_average_over_glide():
    # 3 года 0.16→0.10: годы 0.16/0.13/0.10 → среднее 0.13
    assert abs(carry_rate(0.16, 0.10, 3) - 0.13) < 1e-9


# ── PD ───────────────────────────────────────────────────────────────────────
def test_pd_market_from_spread():
    assert abs(pd_market(0.07) - (0.065 / 0.65)) < 1e-9    # (0.07−0.005)/0.65 = 0.10


def test_pd_synthesis_converge_vs_diverge():
    conv = pd_synthesis(pd_rating=0.10, pd_market_=0.11, pd_fundamental=0.12)
    assert not conv.diverge and abs(conv.pd - 0.11) < 0.01
    div = pd_synthesis(pd_rating=0.05, pd_market_=0.25, pd_fundamental=0.22)  # рейтинг отстаёт
    assert div.diverge and div.pd == 0.25                  # консервативно (max)


def test_context_modifier_gov_support():
    base = pd_synthesis(pd_rating=0.10, pd_market_=0.10, pd_fundamental=0.10).pd
    gov = pd_synthesis(pd_rating=0.10, pd_market_=0.10, pd_fundamental=0.10, context_modifier=0.5).pd
    assert gov < base                                       # системообразующий → ниже PD


# ── bonds ────────────────────────────────────────────────────────────────────
def test_ofz_long_fixed_rate_cut_buy():
    b = assess_bond(ytm=0.20, e_inflation=0.10, hurdle_real=0.07, buffer=0.02,
                    rate_direction="cut", floater=False, is_ofz=True)
    assert b.signal == "ПОКУПАЙ" and b.rate_signal == "благоприятен" and b.credit_ok


def test_corporate_thin_spread_credit_fail():
    b = assess_bond(ytm=0.17, e_inflation=0.10, hurdle_real=0.07, buffer=0.02,
                    rate_direction="hold", kbd_at_duration=0.16, pd=0.10)  # spread 1пп << PD×LGD
    assert b.credit_ok is False and b.signal == "ВОЗДЕРЖИСЬ"


def test_floater_signal_inverted():
    assert rate_signal_for(rate_direction="cut", floater=True) == "встречный"
    assert rate_signal_for(rate_direction="hike", floater=True) == "благоприятен"


# ── fx ───────────────────────────────────────────────────────────────────────
def test_fx_coupon_beats_carry():
    # E[курс] 0.09 + купон 0.12 − carry 0.14 = 0.07 ≥ hurdle 0 + MoS 0.04 → Покупай
    r = assess_fx(scenarios=[(0.6, 0.15), (0.4, 0.0)], carry=0.14, hurdle=0.0, buffer=0.02, coupon=0.12)
    assert r.e_return > 0.04 and r.signal == "ПОКУПАЙ"


def test_bare_currency_dominated_downgraded():
    r = assess_fx(scenarios=[(0.6, 0.25), (0.4, 0.0)], carry=0.14, hurdle=0.0, buffer=0.02,
                  coupon=0.0, has_coupon_analog=True)
    assert r.dominated and r.signal != "ПОКУПАЙ"            # доминируема → не покупка


def test_fx_left_tail_captured():
    r = assess_fx(scenarios=[(0.5, 0.2), (0.5, -0.15)], carry=0.14, hurdle=0.0, buffer=0.02)
    assert r.left_tail == -0.15


# ── срочная структура инфляции (реал. YTM к погашению) ────────────────────────
def test_inflation_to_maturity_glides_to_terminal():
    felt, term = 0.145, 0.09
    short = inflation_to_maturity(felt, term, 0.5)
    long = inflation_to_maturity(felt, term, 15)
    assert felt > short > long > term            # короткая ближе к felt, длинная — к terminal
    # монотонно убывает со сроком
    seq = [inflation_to_maturity(felt, term, m) for m in (1, 2, 3, 5, 10)]
    assert all(a > b for a, b in zip(seq, seq[1:]))


def test_inflation_to_maturity_flat_when_no_terminal():
    assert inflation_to_maturity(0.145, None, 10) == 0.145    # нет терминала → плоско = felt


# ── макро-прогноз (верхний слой: инфляция + шок, дерево) ───────────────────────
def _outlook(p=0.2):
    from app.core.macro_outlook import MacroOutlook, ShockVector
    sv = ShockVector(p=p, infl_pp=0.10, fx_pct=0.25, ks_pp=0.07, equity_dd=-0.30)
    return MacroOutlook(horizon_years=3, felt=0.14, terminal=0.06, shock=sv)


def test_outlook_shock_lifts_inflation_more_for_short():
    o = _outlook()
    assert o.e_inflation(1) > o.base_inflation(1)             # шок поднимает E[инфляцию]
    short_add = o.e_inflation(1) - o.base_inflation(1)
    long_add = o.e_inflation(10) - o.base_inflation(10)
    assert short_add > long_add                              # короткая бумага полнее в окне шока


def test_outlook_fx_scenarios_tree():
    o = _outlook()
    sc = o.fx_scenarios()
    assert len(sc) == 2 and abs(sum(p for p, _ in sc) - 1.0) < 1e-9   # дерево база+шок, веса=1
    assert sc[1][1] > sc[0][1]                               # девальвация в шоке > базового дрейфа
    assert sc[0][1] < o.e_fx() < sc[1][1]                    # E между ветками
