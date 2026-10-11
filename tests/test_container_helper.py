import ast
import importlib.util

from tesearch.harness.executor import HELPER


def _load():
    spec = importlib.util.spec_from_file_location("tp_container", HELPER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_helper_parses_as_python36():
    ast.parse(HELPER.read_text(encoding="utf-8"), feature_version=(3, 6))


def test_search_fold_is_stratified_by_region():
    tp = _load()
    src = "\n".join(["def f():"] + ["    x = 1"] * 20 + ["def g():"] + ["    y = 2"] * 20)
    pool = [{"id": f"op{i}", "line": 2 + i, "family": "number" if i % 2 else "binary"}
            for i in range(20)]
    pool += [{"id": f"g{i}", "line": 23 + i, "family": "comparison"} for i in range(3)]
    chosen = tp.stratified_search_fold(pool, src, 6, seed=0)
    assert len(chosen) == 6
    assert any(c.startswith("g") for c in chosen)          # the small region is not starved
    assert chosen == tp.stratified_search_fold(pool, src, 6, seed=0)


def test_family_of():
    tp = _load()
    assert tp.family_of("core/ReplaceComparisonOperator_Eq_Gt") == "comparison"
    assert tp.family_of("core/ZeroIterationForLoop") == "loopflow"


def test_verdicts_parse_ids_with_spaces_and_summary_only_errors():
    tp = _load()
    out = "\n".join([
        "testing/t.py::test_a PASSED                                      [ 33%]",
        "testing/t.py::test_kw[not or-at column 5: expected not] ERROR     [ 66%]",
        "testing/t.py::TestC::test_m[x] FAILED                            [100%]",
        "=========================== short test summary info ============================",
        "FAILED testing/t.py::TestC::test_m[x] - assert 0",
        "ERROR testing/t.py::test_kw[not or-at column 5: expected not] - Syntax...",
        "ERROR testing/t.py::test_fixture_only - fixture 'pytester' not found",
    ])
    tests = {t["name"]: t["verdict"] for t in tp._parse_verbose(out)}
    assert tests["testing/t.py::test_a"] == "PASSED"
    assert tests["testing/t.py::test_kw[not or-at column 5: expected not]"] == "ERROR"
    assert tests["testing/t.py::TestC::test_m[x]"] == "FAILED"
    assert tests["testing/t.py::test_fixture_only"] == "ERROR"
