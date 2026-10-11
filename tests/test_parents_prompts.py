from tesearch import prompts
from tesearch.archive import Suite
from tesearch.parents import COMPRESS, EXPAND, annotations, comparison_note, mode, order, select_parents


def S(uid, size, cov, mut, src="", failing=None):
    return Suite(uid=uid, src=src, size=size, cov=cov, mut=mut, pass_rate=1.0,
                 green_size=size - len(failing or {}), loc=10, failing=failing or {})


def test_one_parent_per_side():
    pool = [S(0, 5, .5, .5), S(1, 9, .6, .6), S(2, 12, .7, .7), S(3, 30, .9, .9)]
    got = select_parents(pool, tau=10.0)
    assert {p.uid for p in got} == {1, 2}


def test_one_sided_pool_takes_two_nearest():
    pool = [S(0, 5, .5, .5), S(1, 9, .6, .6), S(2, 3, .7, .7)]
    assert {p.uid for p in select_parents(pool, tau=20.0)} == {0, 1}


def test_hv_breaks_distance_ties():
    pool = [S(0, 8, .5, .5), S(1, 8, .9, .9)]
    assert select_parents(pool, tau=10.0)[0].uid == 1


def test_order_and_mode():
    small_strong, large_weak = S(0, 13, .982, .933), S(1, 24, .9, .9)
    ordered = order([small_strong, large_weak])
    assert [p.uid for p in ordered] == [1, 0]
    assert mode(ordered[-1], tau=10.0) == COMPRESS
    assert mode(ordered[-1], tau=16.0) == EXPAND


def test_table3_notes():
    prev = S(0, 24, 0.9466, 0.9)    # hv ≈ 0.852
    curr = S(1, 13, 0.982, 0.9328)  # hv ≈ 0.916
    note = comparison_note(prev, curr)
    assert note == "perfect improved version of prev (hypervolume grow 0.852->0.916, size decline 24->13)"
    grow = comparison_note(S(0, 10, .5, .5), S(1, 20, .8, .8))
    assert grow == "improved version of prev (hypervolume grow 0.250->0.640, size grow 10->20)"
    assert annotations([prev, curr])[0] is None


def test_size_ask_is_verbatim():
    assert prompts.size_ask(13) == (
        "[TARGET SIZE] exactly 13 test functions. This is a HARD REQUIREMENT: the suite MUST "
        "contain exactly 13 functions whose name starts with `test_`. Count them before you "
        "finish and adjust until the count is 13")


def test_module_marks_and_failing_marks():
    src = "a = 1\nb = 2\nc = 3"
    marked = prompts.mark_module(src, [2], [{"line": 3, "operator": "core/NumberReplacer"}])
    assert marked.splitlines() == ["a = 1", "b = 2  # <-- NOT COVERED YET",
                                   "c = 3  # <-- SURVIVING MUTANT: NumberReplacer"]
    suite = "def test_a(\n    x=1,\n):\n    assert x\n\ndef test_b():\n    pass\n"
    out = prompts.mark_failing(suite, {"test_a": "AssertionError"}).splitlines()
    assert out[2] == "):  # <-- FAILING: AssertionError"
    assert "FAILING" not in out[5]


def test_breed_prompt_layout():
    weak = S(0, 24, .9, .9, src="def test_w():\n    pass", failing={"test_w": "KeyError"})
    strong = S(1, 13, .98, .93, src="def test_s():\n    pass")
    strong.uncovered = [1]
    parents = order([strong, weak])
    user = prompts.breed_user("pkg.mod", "x = 1", 13, parents, annotations(parents))
    i_mod, i_ask = user.index("[MODULE SOURCE - annotated"), user.index("[TARGET SIZE]")
    i_v0, i_v1 = user.index("[test_suite_v0"), user.index("[test_suite_v1")
    assert user.startswith("[TARGET MODULE] pkg.mod")
    assert i_mod < i_ask < i_v0 < i_v1
    assert "x = 1  # <-- NOT COVERED YET" in user
    assert "(1 of its 24 tests FAIL" in user
    assert "def test_w():  # <-- FAILING: KeyError" in user
    assert "(perfect improved version of prev" in user
    assert user.rstrip().endswith("Write test_suite_v2 now: the next, improved complete suite. "
                                  "Complete file, no prose, no fences.")
    assert "COMPRESSION" in prompts.breed_system(COMPRESS)
    assert "EXTENSION" in prompts.breed_system(EXPAND)


def test_extract_code():
    assert prompts.extract_code("```python\nx = 1\n```") == "x = 1\n"
    assert prompts.extract_code("x = 1") == "x = 1\n"
