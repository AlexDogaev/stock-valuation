"""Причинный граф (§10): затухание, конвергенция, механическая независимость."""
from app.core.causal_graph import run_node, _backward_paths


def test_convergence_independent_mechanisms():
    # девелопмент: гор_жилищный_спрос (+) И автономный_транспорт (+) — 2 НЕЗАВИСИМЫХ механизма
    r = run_node("девелопмент_агломерации")
    assert r["convergence"] >= 2
    mechs = {c["mechanism"] for c in r["contributions"]}
    assert "гор_жилищный_спрос" in mechs and "автономный_транспорт" in mechs


def test_mechanism_dedup_atomization_agglomeration_counted_once():
    # атомизация + агломерация = ОДИН механизм (гор_жилищный_спрос) → не два сигнала (правило 3)
    r = run_node("девелопмент_агломерации")
    hs = [c for c in r["contributions"] if c["mechanism"] == "гор_жилищный_спрос"]
    assert len(hs) == 1


def test_decay_by_length():
    # длинный путь (беспилотники→парковки→земля→девелопмент, 3 ребра) слабее прямого
    paths = _backward_paths("девелопмент_агломерации")
    direct = max(p.strength for p in paths if p.mechanism == "гор_жилищный_спрос")
    chain = max(p.strength for p in paths if p.mechanism == "автономный_транспорт")
    assert chain < direct        # затухание ∏ весов (правило 1)


def test_offsetting_signs_child_retail():
    # детский ритейл: рождаемость(−) vs окрашенные пособия(+) + премиум(+) — разные механизмы, складываются
    r = run_node("детский_ритейл")
    pos = [c for c in r["contributions"] if c["sign"] > 0]
    neg = [c for c in r["contributions"] if c["sign"] < 0]
    assert len(pos) == 2 and len(neg) == 1


def test_unknown_node_empty():
    r = run_node("несуществующий_узел")
    assert r["convergence"] == 0 and not r["contributions"]
