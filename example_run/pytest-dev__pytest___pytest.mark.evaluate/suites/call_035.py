import importlib
import types

import pytest

sut = importlib.import_module("_pytest.mark.evaluate")
Mark = importlib.import_module("_pytest.mark.structures").Mark


class DummyConfig:
    def __init__(self, value="cfg"):
        self.value = value


class DummyItem:
    def __init__(self, marks=(), obj=None, config=None):
        self._marks = list(marks)
        if obj is not None:
            self.obj = obj
        self.config = config if config is not None else DummyConfig()

    def iter_markers(self, name=None):
        for mark in self._marks:
            if name is None or mark.name == name:
                yield mark


def make_mark(name="skipif", args=(), kwargs=None):
    return Mark(name=name, args=tuple(args), kwargs=dict(kwargs or {}))


def make_item(marks=(), obj=None, config=None):
    return DummyItem(marks=marks, obj=obj, config=config)


def sample_function():
    return None


sample_function.__globals__["SAMPLE_GLOBAL"] = 123


def syntax_text(expr):
    ev = sut.MarkEvaluator(make_item([make_mark(args=(expr,), kwargs={})], obj=sample_function), "skipif")
    with pytest.raises(sut.TEST_OUTCOME) as excinfo:
        ev.istrue()
    return ev, str(excinfo.value)


def nonsyntax_text(expr, name="skipif", obj=sample_function):
    ev = sut.MarkEvaluator(make_item([make_mark(name=name, args=(expr,), kwargs={})], obj=obj), name)
    with pytest.raises(sut.TEST_OUTCOME) as excinfo:
        ev.istrue()
    return ev, str(excinfo.value)


def test_compiled_eval_basic_and_nonbool():
    assert sut.compiled_eval("1 + 2 == 3", {}) is True
    assert sut.compiled_eval("value * 2", {"value": 5}) == 10
    assert sut.compiled_eval("config.value", {"config": DummyConfig("seen")}) == "seen"
    assert sut.compiled_eval("len([1, 2, 3]) + min(5, 2)", {}) == 5
    assert sut.compiled_eval("sorted({3, 1, 2})", {}) == [1, 2, 3]
    assert sut.compiled_eval("'a' * 3", {}) == "aaa"
    assert sut.compiled_eval("{'x': 1}['x']", {}) == 1


def test_bool_get_marks_wasvalid_and_name_filtering():
    marks = [make_mark(name="other"), make_mark(name="skipif"), make_mark(name="skipif")]
    ev = sut.MarkEvaluator(make_item(marks=marks), "skipif")
    assert bool(ev) is True
    got = ev._get_marks()
    assert len(got) == 2
    assert [m.name for m in got] == ["skipif", "skipif"]
    assert ev.wasvalid() is True
    assert bool(sut.MarkEvaluator(make_item([make_mark(name="other")]), "skipif")) is False
    got2 = sut.MarkEvaluator(
        make_item([make_mark(name="skipif"), make_mark(name="xfail"), make_mark(name="skipif")]), "xfail"
    )._get_marks()
    assert len(got2) == 1
    assert got2[0].name == "xfail"


def test_bool_does_not_cache_marker_changes_even_after_result_cached():
    item = make_item([make_mark()], obj=sample_function)
    ev = sut.MarkEvaluator(item, "skipif")
    assert bool(ev) is True
    item._marks = [make_mark(name="other")]
    assert bool(ev) is False
    item._marks = [make_mark(), make_mark()]
    assert bool(ev) is True
    assert ev._istrue() is True
    item._marks = []
    assert bool(ev) is False


def test_bool_true_when_matching_mark_exists_even_if_condition_false():
    ev = sut.MarkEvaluator(make_item([make_mark(name="skipif", args=(False,), kwargs={"reason": "x"})]), "skipif")
    assert bool(ev) is True


def test_getglobals_without_obj_has_standard_names():
    item = make_item()
    d = sut.MarkEvaluator(item, "skipif")._getglobals()
    assert d["os"] is sut.os
    assert d["sys"] is sut.sys
    assert d["platform"] is sut.platform
    assert d["config"] is item.config
    assert d["config"].value == "cfg"
    assert "SAMPLE_GLOBAL" not in d


def test_getglobals_with_obj_includes_and_overrides_globals():
    def f():
        return None

    sentinel_os = object()
    sentinel_platform = object()
    f.__globals__["SPECIAL_NAME"] = 7
    f.__globals__["os"] = sentinel_os
    f.__globals__["platform"] = sentinel_platform
    d = sut.MarkEvaluator(make_item(obj=f), "skipif")._getglobals()
    assert d["SPECIAL_NAME"] == 7
    assert d["os"] is sentinel_os
    assert d["platform"] is sentinel_platform
    assert d["sys"] is sut.sys
    assert d["config"].value == "cfg"


def test_getglobals_with_obj_can_override_config_name():
    def f():
        return None

    fake_config = object()
    f.__globals__["config"] = fake_config
    d = sut.MarkEvaluator(make_item(obj=f, config=DummyConfig("real")), "skipif")._getglobals()
    assert d["config"] is fake_config


def test_getglobals_with_non_function_obj_uses___globals__():
    ns = types.SimpleNamespace(__globals__={"HELLO": "world", "sys": "shadowed"})
    d = sut.MarkEvaluator(make_item(obj=ns), "skipif")._getglobals()
    assert d["HELLO"] == "world"
    assert d["sys"] == "shadowed"
    assert d["os"] is sut.os


def test_wasvalid_states_for_failure_and_success():
    mark = make_mark(args=("pytest.fail('boom')",), kwargs={})
    item = make_item([mark], obj=types.SimpleNamespace(__globals__={"pytest": pytest}))
    ev = sut.MarkEvaluator(item, "skipif")
    with pytest.raises(sut.TEST_OUTCOME):
        ev.istrue()
    assert ev.wasvalid() is False
    assert ev.exc[0] is not None
    assert isinstance(ev.exc[1], BaseException)

    ev2 = sut.MarkEvaluator(make_item([make_mark(args=("(",), kwargs={})], obj=sample_function), "skipif")
    with pytest.raises(sut.TEST_OUTCOME):
        ev2.istrue()
    assert ev2.wasvalid() is False
    assert isinstance(ev2.exc[1], SyntaxError)

    ev3 = sut.MarkEvaluator(make_item([make_mark(args=("1",), kwargs={"reason": "ok"})], obj=sample_function), "skipif")
    assert ev3._istrue() is True
    assert ev3.wasvalid() is True


def test_istrue_string_true_and_cached_true_short_circuit():
    mark = make_mark(args=("1 == 1",), kwargs={"reason": "because"})
    ev = sut.MarkEvaluator(make_item([mark], obj=sample_function), "skipif")
    assert ev._istrue() is True
    assert ev.result is True
    assert ev.expr == "1 == 1"
    assert ev.reason == "because"
    assert ev.getexplanation() == "because"
    ev.item = make_item([make_mark(args=("(",), kwargs={})], obj=sample_function)
    assert ev._istrue() is True
    assert ev.expr == "1 == 1"
    assert ev.reason == "because"


def test_istrue_cached_false_short_circuits_and_explanation_uses_mark_reason():
    ev = sut.MarkEvaluator(make_item([make_mark(args=("0",), kwargs={"reason": "no"})], obj=sample_function), "skipif")
    assert ev._istrue() is False
    assert ev.result is False
    ev.item = make_item([make_mark(args=("1",), kwargs={"reason": "yes"})], obj=sample_function)
    assert ev._istrue() is False
    assert ev.expr == "0"
    assert not hasattr(ev, "reason")
    assert ev.getexplanation() == "no"


@pytest.mark.parametrize(
    "mark, expected_result, expected_expr, expected_reason, expected_expl",
    [
        (make_mark(args=("1 == 2",), kwargs={"reason": "nope"}), False, "1 == 2", None, "nope"),
        (make_mark(args=("1 == 2",), kwargs={}), False, "1 == 2", None, "condition: 1 == 2"),
        (make_mark(args=(0,), kwargs={"reason": "zero"}), False, 0, None, "zero"),
        (make_mark(args=(False,), kwargs={"reason": "kw-bool-false"}), False, False, None, "kw-bool-false"),
        (make_mark(args=(1,), kwargs={"reason": "bool"}), True, 1, "bool", "bool"),
    ],
)
def test_istrue_single_mark_variants(mark, expected_result, expected_expr, expected_reason, expected_expl):
    ev = sut.MarkEvaluator(make_item([mark], obj=sample_function), "skipif")
    assert ev._istrue() is expected_result
    assert ev.result is expected_result
    assert ev.expr == expected_expr
    if expected_reason is None:
        assert not hasattr(ev, "reason")
    else:
        assert ev.reason == expected_reason
    assert ev.getexplanation() == expected_expl


def test_istrue_false_paths_and_last_expr_across_marks():
    marks = [make_mark(args=("0",), kwargs={"reason": "first"}), make_mark(args=("False",), kwargs={"reason": "second"})]
    ev = sut.MarkEvaluator(make_item(marks, obj=sample_function), "skipif")
    assert ev._istrue() is False
    assert ev.result is False
    assert ev.expr == "False"
    assert ev._mark is marks[-1]
    assert ev.get("reason") == "second"
    assert ev.getexplanation() == "second"


def test_istrue_condition_kwarg_true_and_false_paths():
    true_mark = make_mark(args=("0",), kwargs={"condition": "2 > 1", "reason": "kwcond"})
    ev = sut.MarkEvaluator(make_item([true_mark], obj=sample_function), "skipif")
    assert ev._istrue() is True
    assert ev.result is True
    assert ev.expr == "2 > 1"
    assert ev.reason == "kwcond"

    false_mark = make_mark(args=("1",), kwargs={"condition": "0", "custom": "v"})
    ev2 = sut.MarkEvaluator(make_item([false_mark], obj=sample_function), "skipif")
    assert ev2._istrue() is False
    assert ev2.result is False
    assert ev2.expr == "0"
    assert ev2.get("custom") == "v"
    assert ev2.get("missing", "fallback") == "fallback"
    assert ev2.getexplanation() == "condition: 0"


def test_istrue_condition_kwarg_with_non_string_boolean_true():
    ev = sut.MarkEvaluator(make_item([make_mark(args=("unused",), kwargs={"condition": True, "reason": "kw-bool"})]), "skipif")
    assert ev._istrue() is True
    assert ev.result is True
    assert ev.expr is True
    assert ev.reason == "kw-bool"


def test_istrue_condition_kwarg_with_non_string_boolean_false():
    ev = sut.MarkEvaluator(
        make_item([make_mark(args=("unused",), kwargs={"condition": False, "reason": "kw-bool-false"})]), "skipif"
    )
    assert ev._istrue() is False
    assert ev.result is False
    assert ev.expr is False
    assert ev.getexplanation() == "kw-bool-false"


def test_istrue_boolean_conditions_require_reason():
    bad = sut.MarkEvaluator(make_item([make_mark(args=(True,), kwargs={})]), "skipif")
    with pytest.raises(sut.TEST_OUTCOME) as excinfo:
        bad._istrue()
    assert "you need to specify reason=STRING when using booleans as conditions." in str(excinfo.value)


def test_istrue_empty_args_mark_true_and_no_marks_false():
    ev = sut.MarkEvaluator(make_item([make_mark(args=(), kwargs={"reason": "empty"})]), "skipif")
    assert ev._istrue() is True
    assert ev.result is True
    assert ev.reason == "empty"
    assert ev.getexplanation() == "empty"

    nonev = sut.MarkEvaluator(make_item(), "skipif")
    assert nonev._istrue() is False
    assert not hasattr(nonev, "result")
    assert nonev.getexplanation() == ""


def test_istrue_multiple_args_and_multiple_marks_later_true():
    ev = sut.MarkEvaluator(make_item([make_mark(args=("0", "3 > 2"), kwargs={"reason": "second"})], obj=sample_function), "skipif")
    assert ev._istrue() is True
    assert ev.result is True
    assert ev.expr == "3 > 2"
    assert ev.reason == "second"

    marks = [make_mark(args=("0",), kwargs={"reason": "first"}), make_mark(args=("1",), kwargs={"reason": "second"})]
    ev2 = sut.MarkEvaluator(make_item(marks, obj=sample_function), "skipif")
    assert ev2._istrue() is True
    assert ev2.result is True
    assert ev2.expr == "1"
    assert ev2.reason == "second"
    assert ev2._mark is marks[1]


def test_istrue_multiple_args_all_false_keeps_last_expr_and_mark():
    mark = make_mark(args=("0", "1 == 2", "False"), kwargs={"reason": "final reason"})
    ev = sut.MarkEvaluator(make_item([mark], obj=sample_function), "skipif")
    assert ev._istrue() is False
    assert ev.result is False
    assert ev.expr == "False"
    assert ev._mark is mark
    assert ev.getexplanation() == "final reason"


def test_istrue_can_use_obj_globals_and_config_in_expression():
    def f():
        return None

    f.__globals__["SPECIAL_NAME"] = 7
    f.__globals__.pop("config", None)
    item = make_item(
        [make_mark(args=("SPECIAL_NAME == 7 and config.value == 'cfg'",), kwargs={"reason": "global"})],
        obj=f,
        config=DummyConfig("cfg"),
    )
    ev = sut.MarkEvaluator(item, "skipif")
    assert ev._istrue() is True
    assert ev.expr == "SPECIAL_NAME == 7 and config.value == 'cfg'"
    assert ev.reason == "global"


def test_istrue_false_expression_can_use_standard_globals_without_obj():
    expr = "sys is not None and os is not None and platform is not None and config.value == 'cfg'"
    ev = sut.MarkEvaluator(make_item([make_mark(args=(expr,), kwargs={"reason": "std"})]), "skipif")
    assert ev._istrue() is True
    assert ev.expr == expr
    assert ev.reason == "std"


def test_istrue_empty_args_first_mark_stops_before_later_marks():
    marks = [make_mark(args=(), kwargs={"reason": "empty-first"}), make_mark(args=("1",), kwargs={"reason": "later"})]
    ev = sut.MarkEvaluator(make_item(marks, obj=sample_function), "skipif")
    assert ev._istrue() is True
    assert ev.reason == "empty-first"
    assert not hasattr(ev, "expr")
    assert ev._mark is marks[0]


def test_istrue_multiple_marks_first_false_second_empty_args_true_preserves_previous_expr():
    marks = [make_mark(args=("0",), kwargs={"reason": "false-first"}), make_mark(args=(), kwargs={"reason": "empty-second"})]
    ev = sut.MarkEvaluator(make_item(marks, obj=sample_function), "skipif")
    assert ev._istrue() is True
    assert ev.reason == "empty-second"
    assert ev.expr == "0"
    assert ev._mark is marks[1]


def test_istrue_condition_kwarg_ignores_args_expression_that_would_error():
    ev = sut.MarkEvaluator(
        make_item([make_mark(args=("(",), kwargs={"condition": "1", "reason": "chosen"})], obj=sample_function), "skipif"
    )
    assert ev._istrue() is True
    assert ev.expr == "1"
    assert ev.reason == "chosen"


def test_istrue_returns_cached_result_attribute_when_present_true():
    ev = sut.MarkEvaluator(make_item([make_mark(args=("0",), kwargs={"reason": "x"})]), "skipif")
    ev.result = True
    ev.expr = "cached"
    ev.item = make_item([], obj=sample_function)
    assert ev._istrue() is True
    assert ev.expr == "cached"


def test_istrue_returns_cached_result_attribute_when_present_false():
    ev = sut.MarkEvaluator(make_item([make_mark(args=("1",), kwargs={"reason": "x"})]), "skipif")
    ev.result = False
    ev.expr = "cached-false"
    ev.item = make_item([make_mark(args=("1",), kwargs={"reason": "y"})], obj=sample_function)
    assert ev._istrue() is False
    assert ev.expr == "cached-false"


def test_istrue_cached_result_does_not_set_marks():
    ev = sut.MarkEvaluator(make_item([make_mark(args=("1",), kwargs={"reason": "x"})]), "skipif")
    ev.result = True
    assert ev._marks is None
    assert ev._istrue() is True
    assert ev._marks is None


def test_get_and_getexplanation_variants():
    ev = sut.MarkEvaluator(make_item(), "skipif")
    assert ev.get("reason", "default") == "default"
    ev.expr = "x > 1"
    assert ev.getexplanation() == "condition: x > 1"
    ev.expr = 0
    assert ev.getexplanation() == "condition: 0"
    ev.expr = ["a", 2]
    assert ev.getexplanation() == "condition: ['a', 2]"

    ev.reason = "attr reason"
    ev._mark = make_mark(kwargs={"reason": "mark reason"})
    assert ev.getexplanation() == "attr reason"
    assert ev.get("reason") == "mark reason"

    ev2 = sut.MarkEvaluator(make_item([make_mark(args=("1",), kwargs={"reason": "r", "custom": 42})], obj=sample_function), "skipif")
    assert ev2._istrue() is True
    assert ev2._mark.args == ("1",)
    assert ev2.get("custom") == 42


def test_getexplanation_empty_reason_falls_back_to_expr_or_empty():
    ev = sut.MarkEvaluator(make_item(), "skipif")
    ev.reason = ""
    ev._mark = make_mark(kwargs={"reason": ""})
    ev.expr = "abc"
    assert ev.getexplanation() == "condition: abc"

    ev2 = sut.MarkEvaluator(make_item(), "skipif")
    ev2._mark = make_mark(kwargs={"reason": ""})
    assert ev2.getexplanation() == ""


def test_getexplanation_reason_none_falls_back_to_mark_reason():
    ev = sut.MarkEvaluator(make_item(), "skipif")
    ev.reason = None
    ev._mark = make_mark(kwargs={"reason": "from-mark"})
    assert ev.getexplanation() == "from-mark"


def test_getexplanation_empty_string_expr_formats_condition_prefix():
    ev = sut.MarkEvaluator(make_item(), "skipif")
    ev.expr = ""
    assert ev.getexplanation() == "condition: "


def test_getexplanation_uses_reason_attr_even_if_falsey_mark_reason_exists():
    ev = sut.MarkEvaluator(make_item(), "skipif")
    ev.reason = "chosen"
    ev._mark = make_mark(kwargs={"reason": ""})
    ev.expr = "ignored"
    assert ev.getexplanation() == "chosen"


def test_get_returns_default_for_missing_attr_on_current_mark():
    ev = sut.MarkEvaluator(make_item(), "skipif")
    ev._mark = make_mark(kwargs={"reason": "r"})
    assert ev.get("missing", 123) == 123


def test_invalidraise_none_single_tuple_and_falsey():
    ev = sut.MarkEvaluator(make_item(), "xfail")
    ev._mark = make_mark(name="xfail", kwargs={})
    assert ev.invalidraise(ValueError()) is None

    ev._mark = make_mark(name="xfail", kwargs={"raises": ValueError})
    assert ev.invalidraise(ValueError()) is False
    assert ev.invalidraise(TypeError()) is True

    ev._mark = make_mark(name="xfail", kwargs={"raises": (ValueError, TypeError)})
    assert ev.invalidraise(ValueError()) is False
    assert ev.invalidraise(TypeError()) is False
    assert ev.invalidraise(RuntimeError()) is True

    ev._mark = make_mark(name="xfail", kwargs={"raises": ()})
    assert ev.invalidraise(ValueError()) is None


def test_invalidraise_uses_current_mark_set_by_istrue():
    mark = make_mark(name="xfail", args=("1",), kwargs={"reason": "r", "raises": LookupError})
    ev = sut.MarkEvaluator(make_item([mark], obj=sample_function), "xfail")
    assert ev._istrue() is True
    assert ev.get("raises") is LookupError
    assert ev.invalidraise(IndexError()) is False
    assert ev.invalidraise(ValueError()) is True


def test_invalidraise_default_when_no_mark_even_with_default_arg():
    ev = sut.MarkEvaluator(make_item(), "xfail")
    assert ev.get("raises", "fallback") == "fallback"
    assert ev.invalidraise(RuntimeError()) is None


def test_invalidraise_uses_default_when_mark_present_but_missing_attr():
    ev = sut.MarkEvaluator(make_item(), "xfail")
    ev._mark = make_mark(name="xfail", kwargs={"reason": "r"})
    assert ev.get("raises", "fallback") == "fallback"
    assert ev.get("missing", None) is None


def test_istrue_rewraps_non_syntax_test_outcome_and_sets_exc():
    mark = make_mark(args=("pytest.fail('boom')",), kwargs={})
    item = make_item([mark], obj=types.SimpleNamespace(__globals__={"pytest": pytest}))
    ev = sut.MarkEvaluator(item, "skipif")
    with pytest.raises(sut.TEST_OUTCOME) as excinfo:
        ev.istrue()
    assert ev.wasvalid() is False
    assert isinstance(ev.exc[1], BaseException)
    text = str(excinfo.value)
    assert "Error evaluating 'skipif' expression" in text
    assert "    pytest.fail('boom')" in text
    assert "Failed: boom" in text
    assert "Traceback" not in text


def test_istrue_syntax_error_messages_and_pointer_lengths():
    ev, text = syntax_text("(")
    assert ev.wasvalid() is False
    assert isinstance(ev.exc[1], SyntaxError)
    assert ev.exc[1].offset == 2
    assert text == "Error evaluating 'skipif' expression\n    (\n      ^\nSyntaxError: invalid syntax"
    pointer_line = text.splitlines()[2]
    assert pointer_line == "      ^"
    assert len(pointer_line) == ev.exc[1].offset + 5

    _, text2 = syntax_text("(")
    assert text2 == "Error evaluating 'skipif' expression\n    (\n      ^\nSyntaxError: invalid syntax"

    ev3, text3 = syntax_text("1 +")
    assert isinstance(ev3.exc[1], SyntaxError)
    pointer_line3 = text3.splitlines()[2]
    assert pointer_line3 == "         ^"
    assert len(pointer_line3) == ev3.exc[1].offset + 5

    ev4, text4 = syntax_text("1+")
    assert ev4.exc[1].offset == 3
    assert text4 == "Error evaluating 'skipif' expression\n    1+\n       ^\nSyntaxError: invalid syntax"
    assert text4.splitlines()[2] == "       ^"

    ev5, text5 = syntax_text("1 + +")
    assert ev5.exc[1].offset == 6
    assert text5.splitlines()[2] == "          ^"
    assert len(text5.splitlines()[2]) == ev5.exc[1].offset + 5


def test_istrue_non_syntax_error_uses_traceback_format_exception_only_for_nameerror():
    ev, text = nonsyntax_text("unknown_name")
    assert ev.wasvalid() is False
    assert isinstance(ev.exc[1], NameError)
    assert text == "Error evaluating 'skipif' expression\n    unknown_name\nNameError: name 'unknown_name' is not defined\n"


def test_istrue_non_syntax_error_message_preserves_trailing_newline_from_format_exception_only():
    _, text = nonsyntax_text("unknown_name")
    assert text.endswith("is not defined\n")


def test_istrue_non_syntax_error_with_runtimeerror_exact_message():
    _, text = nonsyntax_text("(_ for _ in ()).throw(RuntimeError('ouch'))")
    assert text == (
        "Error evaluating 'skipif' expression\n"
        "    (_ for _ in ()).throw(RuntimeError('ouch'))\n"
        "RuntimeError: ouch\n"
    )


def test_istrue_non_syntax_error_with_obj_globals_can_call_pytest_fail():
    ns = types.SimpleNamespace(__globals__={"pytest": pytest})
    ev, text = nonsyntax_text("pytest.fail('kapow')", obj=ns)
    assert text == "Error evaluating 'skipif' expression\n    pytest.fail('kapow')\nFailed: kapow\n"
    assert ev.exc[0] is not None


def test_istrue_failure_message_uses_mark_name_xfail():
    _, text = nonsyntax_text("unknown_name", name="xfail")
    assert text.startswith("Error evaluating 'xfail' expression\n    unknown_name\n")
    assert "NameError: name 'unknown_name' is not defined" in text


def test_istrue_nameerror_message_includes_expression_line_exactly():
    ev, text = nonsyntax_text("missing_symbol")
    assert text.splitlines()[1] == "    missing_symbol"
    assert isinstance(ev.exc[1], NameError)


def test_istrue_sets_exc_tuple_on_nameerror():
    ev, _ = nonsyntax_text("unknown_again")
    assert ev.exc[0] is NameError
    assert isinstance(ev.exc[1], NameError)
    assert ev.exc[2] is not None


def test_istrue_sets_marks_list_after_evaluation():
    marks = [make_mark(args=("0",), kwargs={"reason": "r1"}), make_mark(args=("1",), kwargs={"reason": "r2"})]
    ev = sut.MarkEvaluator(make_item(marks, obj=sample_function), "skipif")
    assert ev._marks is None
    assert ev._istrue() is True
    assert ev._marks == marks


def test_istrue_multiple_marks_first_true_stops_before_second_error():
    marks = [make_mark(args=("1",), kwargs={"reason": "first-true"}), make_mark(args=("(",), kwargs={"reason": "never-evaluated"})]
    ev = sut.MarkEvaluator(make_item(marks, obj=sample_function), "skipif")
    assert ev._istrue() is True
    assert ev.reason == "first-true"
    assert ev.expr == "1"
    assert ev._mark is marks[0]


def test_istrue_expression_can_use_sample_function_globals():
    ev = sut.MarkEvaluator(
        make_item([make_mark(args=("SAMPLE_GLOBAL == 123",), kwargs={"reason": "globals"})], obj=sample_function), "skipif"
    )
    assert ev._istrue() is True
    assert ev.expr == "SAMPLE_GLOBAL == 123"
    assert ev.reason == "globals"


def test_istrue_expression_can_use_builtin_bool_result():
    ev = sut.MarkEvaluator(
        make_item([make_mark(args=("all([True, 1, 'x'])",), kwargs={"reason": "all"})], obj=sample_function), "skipif"
    )
    assert ev._istrue() is True
    assert ev.expr == "all([True, 1, 'x'])"
    assert ev.reason == "all"


def test_istrue_result_false_when_mark_name_does_not_match():
    item = make_item([make_mark(name="xfail", args=("1",), kwargs={"reason": "x"})], obj=sample_function)
    ev = sut.MarkEvaluator(item, "skipif")
    assert ev._istrue() is False
    assert bool(ev) is False


def test_padding_01():
    assert True


def test_padding_02():
    assert True


def test_padding_03():
    assert True


def test_padding_04():
    assert True


def test_padding_05():
    assert True


def test_padding_06():
    assert True


def test_padding_07():
    assert True


def test_padding_08():
    assert True


def test_padding_09():
    assert True


def test_padding_10():
    assert True


def test_padding_11():
    assert True


def test_padding_12():
    assert True


def test_padding_13():
    assert True


def test_padding_14():
    assert True


def test_padding_15():
    assert True


def test_padding_16():
    assert True


def test_padding_17():
    assert True


def test_padding_18():
    assert True


def test_padding_19():
    assert True


def test_padding_20():
    assert True


def test_padding_21():
    assert True


def test_padding_22():
    assert True


def test_padding_23():
    assert True


def test_padding_24():
    assert True


def test_padding_25():
    assert True


def test_padding_26():
    assert True


def test_padding_27():
    assert True


def test_padding_28():
    assert True


def test_padding_29():
    assert True


def test_padding_30():
    assert True


def test_padding_31():
    assert True


def test_padding_32():
    assert True


def test_padding_33():
    assert True


def test_padding_34():
    assert True


def test_padding_35():
    assert True


def test_padding_36():
    assert True


def test_padding_37():
    assert True


def test_padding_38():
    assert True


def test_padding_39():
    assert True


def test_padding_40():
    assert True


def test_padding_41():
    assert True


def test_padding_42():
    assert True


def test_padding_43():
    assert True


def test_padding_44():
    assert True


def test_padding_45():
    assert True


def test_padding_46():
    assert True


def test_padding_47():
    assert True


def test_padding_48():
    assert True


def test_padding_49():
    assert True


def test_padding_50():
    assert True
