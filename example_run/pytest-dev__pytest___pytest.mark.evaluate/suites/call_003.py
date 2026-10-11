import importlib
import types

import pytest

sut = importlib.import_module("_pytest.mark.evaluate")
Mark = importlib.import_module("_pytest.mark.structures").Mark


class DummyConfig:
    pass


class DummyItem:
    def __init__(self, marks=(), obj=None, config=None):
        self._marks = list(marks)
        self.obj = obj if obj is not None else None
        self.config = config if config is not None else DummyConfig()

    def iter_markers(self, name=None):
        for mark in self._marks:
            if name is None or mark.name == name:
                yield mark


def make_mark(name="skipif", args=(), kwargs=None):
    return Mark(name=name, args=tuple(args), kwargs=dict(kwargs or {}))


def make_item(marks=(), obj=None):
    return DummyItem(marks=marks, obj=obj, config=DummyConfig())


def sample_function():
    return None


sample_function.__globals__["SAMPLE_GLOBAL"] = 123


def test_compiled_eval_basic_expression():
    result = sut.compiled_eval("1 + 2 == 3", {})
    assert result is True


def test_compiled_eval_uses_provided_globals():
    result = sut.compiled_eval("value * 2", {"value": 5})
    assert result == 10


def test_bool_false_when_no_matching_marks():
    item = make_item([make_mark(name="other")])
    ev = sut.MarkEvaluator(item, "skipif")
    assert bool(ev) is False


def test_bool_true_when_matching_marks_exist_even_before_evaluation():
    item = make_item([make_mark(name="skipif", args=(False,), kwargs={"reason": "x"})])
    ev = sut.MarkEvaluator(item, "skipif")
    assert bool(ev) is True


def test_wasvalid_true_initially():
    ev = sut.MarkEvaluator(make_item(), "skipif")
    assert ev.wasvalid() is True


def test_get_marks_filters_by_name():
    marks = [
        make_mark(name="skipif"),
        make_mark(name="xfail"),
        make_mark(name="skipif"),
    ]
    ev = sut.MarkEvaluator(make_item(marks), "skipif")
    got = ev._get_marks()
    assert len(got) == 2
    assert all(m.name == "skipif" for m in got)


def test_invalidraise_returns_none_without_raises():
    ev = sut.MarkEvaluator(make_item(), "xfail")
    ev._mark = make_mark(name="xfail", kwargs={})
    assert ev.invalidraise(ValueError()) is None


def test_invalidraise_false_when_exception_matches():
    ev = sut.MarkEvaluator(make_item(), "xfail")
    ev._mark = make_mark(name="xfail", kwargs={"raises": ValueError})
    assert ev.invalidraise(ValueError()) is False


def test_invalidraise_true_when_exception_does_not_match():
    ev = sut.MarkEvaluator(make_item(), "xfail")
    ev._mark = make_mark(name="xfail", kwargs={"raises": ValueError})
    assert ev.invalidraise(TypeError()) is True


def test_getglobals_contains_standard_names_and_config():
    item = make_item()
    ev = sut.MarkEvaluator(item, "skipif")
    d = ev._getglobals()
    assert d["os"] is sut.os
    assert d["sys"] is sut.sys
    assert d["platform"] is sut.platform
    assert d["config"] is item.config


def test_getglobals_includes_test_object_globals():
    item = make_item(obj=sample_function)
    ev = sut.MarkEvaluator(item, "skipif")
    d = ev._getglobals()
    assert d["SAMPLE_GLOBAL"] == 123


def test_istrue_no_marks_is_false():
    ev = sut.MarkEvaluator(make_item(), "skipif")
    assert ev._istrue() is False
    assert ev.result is False


def test_istrue_string_expression_true_sets_reason_and_expr():
    mark = make_mark(name="skipif", args=("1 == 1",), kwargs={"reason": "because"})
    ev = sut.MarkEvaluator(make_item([mark]), "skipif")
    assert ev._istrue() is True
    assert ev.result is True
    assert ev.reason == "because"
    assert ev.expr == "1 == 1"


def test_istrue_string_expression_false_returns_false_and_keeps_expr():
    mark = make_mark(name="skipif", args=("1 == 2",), kwargs={"reason": "nope"})
    ev = sut.MarkEvaluator(make_item([mark]), "skipif")
    assert ev._istrue() is False
    assert ev.result is False
    assert ev.expr == "1 == 2"
    assert ev.getexplanation() == "nope"


def test_istrue_uses_condition_kwarg_instead_of_args():
    mark = make_mark(
        name="skipif",
        args=("0",),
        kwargs={"condition": "2 > 1", "reason": "kwcond"},
    )
    ev = sut.MarkEvaluator(make_item([mark]), "skipif")
    assert ev._istrue() is True
    assert ev.expr == "2 > 1"
    assert ev.reason == "kwcond"


def test_istrue_boolean_condition_requires_reason():
    mark = make_mark(name="skipif", args=(True,), kwargs={})
    ev = sut.MarkEvaluator(make_item([mark]), "skipif")
    with pytest.raises(sut.TEST_OUTCOME) as excinfo:
        ev._istrue()
    assert "you need to specify reason=STRING when using booleans as conditions." in str(excinfo.value)


def test_istrue_boolean_condition_with_reason_true():
    mark = make_mark(name="skipif", args=(1,), kwargs={"reason": "bool"})
    ev = sut.MarkEvaluator(make_item([mark]), "skipif")
    assert ev._istrue() is True
    assert ev.reason == "bool"
    assert ev.expr == 1


def test_istrue_empty_args_mark_is_true():
    mark = make_mark(name="skipif", args=(), kwargs={"reason": "empty"})
    ev = sut.MarkEvaluator(make_item([mark]), "skipif")
    assert ev._istrue() is True
    assert ev.reason == "empty"


def test_istrue_multiple_args_stops_on_first_truthy():
    mark = make_mark(name="skipif", args=("0", "3 > 2"), kwargs={"reason": "second"})
    ev = sut.MarkEvaluator(make_item([mark]), "skipif")
    assert ev._istrue() is True
    assert ev.expr == "3 > 2"
    assert ev.reason == "second"


def test_istrue_caches_result_after_first_call():
    mark = make_mark(name="skipif", args=("1 == 1",), kwargs={"reason": "cached"})
    ev = sut.MarkEvaluator(make_item([mark]), "skipif")
    assert ev._istrue() is True
    ev.item = make_item([])
    assert ev._istrue() is True


def test_get_returns_default_when_no_current_mark():
    ev = sut.MarkEvaluator(make_item(), "skipif")
    assert ev.get("reason", "default") == "default"


def test_get_returns_mark_kwarg_when_current_mark_set():
    mark = make_mark(name="skipif", kwargs={"reason": "abc"})
    ev = sut.MarkEvaluator(make_item(), "skipif")
    ev._mark = mark
    assert ev.get("reason") == "abc"


def test_getexplanation_prefers_reason_attribute():
    ev = sut.MarkEvaluator(make_item(), "skipif")
    ev.reason = "attr reason"
    ev._mark = make_mark(name="skipif", kwargs={"reason": "mark reason"})
    assert ev.getexplanation() == "attr reason"


def test_getexplanation_uses_mark_reason_when_no_reason_attr():
    ev = sut.MarkEvaluator(make_item(), "skipif")
    ev._mark = make_mark(name="skipif", kwargs={"reason": "mark reason"})
    assert ev.getexplanation() == "mark reason"


def test_getexplanation_empty_when_no_reason_or_expr():
    ev = sut.MarkEvaluator(make_item(), "skipif")
    assert ev.getexplanation() == ""


def test_getexplanation_condition_when_only_expr_available():
    ev = sut.MarkEvaluator(make_item(), "skipif")
    ev.expr = "x > 1"
    assert ev.getexplanation() == "condition: x > 1"


def test_istrue_expression_can_use_item_object_globals():
    def f():
        return None

    f.__globals__["SPECIAL_NAME"] = 7
    mark = make_mark(name="skipif", args=("SPECIAL_NAME == 7",), kwargs={"reason": "global"})
    ev = sut.MarkEvaluator(make_item([mark], obj=f), "skipif")
    assert ev._istrue() is True


def test_istrue_expression_can_use_config_global():
    mark = make_mark(name="skipif", args=("config is not None",), kwargs={"reason": "cfg"})
    ev = sut.MarkEvaluator(make_item([mark]), "skipif")
    assert ev._istrue() is True


def test_istrue_across_multiple_marks_finds_later_true_mark():
    marks = [
        make_mark(name="skipif", args=("0",), kwargs={"reason": "first"}),
        make_mark(name="skipif", args=("1",), kwargs={"reason": "second"}),
    ]
    ev = sut.MarkEvaluator(make_item(marks), "skipif")
    assert ev._istrue() is True
    assert ev.reason == "second"


def test_istrue_all_false_marks_returns_false_and_last_expr():
    marks = [
        make_mark(name="skipif", args=("0",), kwargs={"reason": "first"}),
        make_mark(name="skipif", args=("False",), kwargs={"reason": "second"}),
    ]
    ev = sut.MarkEvaluator(make_item(marks), "skipif")
    assert ev._istrue() is False
    assert ev.expr == "False"
    assert ev.getexplanation() == "second"


def test_istrue_sets_current_mark_for_get():
    mark = make_mark(name="skipif", args=("1",), kwargs={"reason": "r", "custom": 42})
    ev = sut.MarkEvaluator(make_item([mark]), "skipif")
    assert ev._istrue() is True
    assert ev.get("custom") == 42


def test_istrue_test_outcome_from_expression_is_captured_and_re_failed():
    mark = make_mark(name="skipif", args=("pytest.fail('boom')",), kwargs={})
    item = make_item([mark], obj=types.SimpleNamespace(__globals__={"pytest": pytest}))
    ev = sut.MarkEvaluator(item, "skipif")
    with pytest.raises(sut.TEST_OUTCOME) as excinfo:
        ev.istrue()
    assert ev.wasvalid() is False
    assert "Error evaluating 'skipif' expression" in str(excinfo.value)
    assert "pytest.fail('boom')" in str(excinfo.value)


def test_istrue_syntax_error_is_captured_and_re_failed():
    mark = make_mark(name="skipif", args=("(",), kwargs={})
    ev = sut.MarkEvaluator(make_item([mark]), "skipif")
    with pytest.raises(sut.TEST_OUTCOME) as excinfo:
        ev.istrue()
    assert ev.wasvalid() is False
    text = str(excinfo.value)
    assert "Error evaluating 'skipif' expression" in text
    assert "SyntaxError: invalid syntax" in text
    assert "\n    (\n" in text
