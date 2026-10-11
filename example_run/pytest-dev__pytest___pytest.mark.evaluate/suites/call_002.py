import sys
import types

import pytest

import _pytest.mark.evaluate as evaluate
from _pytest.mark.structures import Mark
from _pytest.outcomes import Failed


class DummyConfig:
    pass


class DummyItem:
    def __init__(self, marks=(), obj=None, config=None):
        self._marks = list(marks)
        self.obj = obj
        self.config = config if config is not None else DummyConfig()

    def iter_markers(self, name=None):
        for mark in self._marks:
            if name is None or mark.name == name:
                yield mark


def make_mark(name="skipif", args=(), kwargs=None):
    return Mark(name=name, args=tuple(args), kwargs=dict(kwargs or {}))


def make_item(marks=(), obj=None):
    return DummyItem(marks=marks, obj=obj)


def make_function_with_globals():
    external_value = 42

    def f():
        return external_value

    return f


def test_compiled_eval_basic_expression():
    result = evaluate.compiled_eval("1 + 2 * 3", {})
    assert result == 7


def test_compiled_eval_uses_provided_globals():
    ns = {"x": 10, "y": 5}
    assert evaluate.compiled_eval("x - y", ns) == 5


def test_bool_reflects_presence_of_matching_marks():
    item = make_item([make_mark(name="other")])
    ev = evaluate.MarkEvaluator(item, "skipif")
    assert bool(ev) is False

    item2 = make_item([make_mark(name="skipif")])
    ev2 = evaluate.MarkEvaluator(item2, "skipif")
    assert bool(ev2) is True


def test_wasvalid_true_before_any_error():
    ev = evaluate.MarkEvaluator(make_item(), "skipif")
    assert ev.wasvalid() is True


def test_get_marks_filters_by_name():
    marks = [
        make_mark(name="skipif"),
        make_mark(name="xfail"),
        make_mark(name="skipif"),
    ]
    ev = evaluate.MarkEvaluator(make_item(marks), "skipif")
    got = ev._get_marks()
    assert len(got) == 2
    assert all(m.name == "skipif" for m in got)


def test_invalidraise_none_when_no_raises_kwarg():
    mark = make_mark(name="xfail", kwargs={"reason": "r"})
    ev = evaluate.MarkEvaluator(make_item([mark]), "xfail")
    ev._mark = mark
    assert ev.invalidraise(ValueError()) is None


def test_invalidraise_false_when_exception_matches():
    mark = make_mark(name="xfail", kwargs={"raises": ValueError})
    ev = evaluate.MarkEvaluator(make_item([mark]), "xfail")
    ev._mark = mark
    assert ev.invalidraise(ValueError()) is False


def test_invalidraise_true_when_exception_does_not_match():
    mark = make_mark(name="xfail", kwargs={"raises": ValueError})
    ev = evaluate.MarkEvaluator(make_item([mark]), "xfail")
    ev._mark = mark
    assert ev.invalidraise(TypeError()) is True


def test_getglobals_contains_standard_names_and_config():
    item = make_item()
    ev = evaluate.MarkEvaluator(item, "skipif")
    d = ev._getglobals()
    assert d["os"] is evaluate.os
    assert d["sys"] is evaluate.sys
    assert d["platform"] is evaluate.platform
    assert d["config"] is item.config


def test_getglobals_includes_test_function_globals():
    func = make_function_with_globals()
    item = make_item(obj=func)
    ev = evaluate.MarkEvaluator(item, "skipif")
    d = ev._getglobals()
    assert "__name__" in d
    assert "make_function_with_globals" in d


def test_istrue_no_marks_is_false():
    ev = evaluate.MarkEvaluator(make_item(), "skipif")
    assert ev._istrue() is False


def test_istrue_empty_args_mark_is_true_and_sets_reason():
    mark = make_mark(name="skipif", kwargs={"reason": "empty means true"})
    ev = evaluate.MarkEvaluator(make_item([mark]), "skipif")
    assert ev._istrue() is True
    assert ev.reason == "empty means true"


def test_istrue_string_condition_true_sets_reason_and_expr():
    mark = make_mark(name="skipif", args=("1 == 1",), kwargs={"reason": "yes"})
    ev = evaluate.MarkEvaluator(make_item([mark]), "skipif")
    assert ev._istrue() is True
    assert ev.reason == "yes"
    assert ev.expr == "1 == 1"


def test_istrue_string_condition_false_returns_false():
    mark = make_mark(name="skipif", args=("1 == 2",), kwargs={"reason": "no"})
    ev = evaluate.MarkEvaluator(make_item([mark]), "skipif")
    assert ev._istrue() is False
    assert ev.result is False


def test_istrue_uses_condition_kwarg_instead_of_args():
    mark = make_mark(
        name="skipif",
        args=("1 == 2",),
        kwargs={"condition": "2 == 2", "reason": "kwarg wins"},
    )
    ev = evaluate.MarkEvaluator(make_item([mark]), "skipif")
    assert ev._istrue() is True
    assert ev.expr == "2 == 2"
    assert ev.reason == "kwarg wins"


def test_istrue_boolean_condition_requires_reason():
    mark = make_mark(name="skipif", args=(True,), kwargs={})
    ev = evaluate.MarkEvaluator(make_item([mark]), "skipif")
    with pytest.raises(Failed) as excinfo:
        ev._istrue()
    assert "you need to specify reason=STRING when using booleans as conditions." in str(excinfo.value)


def test_istrue_boolean_condition_with_reason_true():
    mark = make_mark(name="skipif", args=(1,), kwargs={"reason": "truthy"})
    ev = evaluate.MarkEvaluator(make_item([mark]), "skipif")
    assert ev._istrue() is True
    assert ev.reason == "truthy"
    assert ev.expr == 1


def test_istrue_boolean_condition_with_reason_false():
    mark = make_mark(name="skipif", args=(0,), kwargs={"reason": "falsy"})
    ev = evaluate.MarkEvaluator(make_item([mark]), "skipif")
    assert ev._istrue() is False
    assert ev.result is False


def test_istrue_multiple_expressions_stops_on_first_true():
    mark = make_mark(
        name="skipif",
        args=("0", "1", "2"),
        kwargs={"reason": "second one true"},
    )
    ev = evaluate.MarkEvaluator(make_item([mark]), "skipif")
    assert ev._istrue() is True
    assert ev.expr == "1"
    assert ev.reason == "second one true"


def test_istrue_multiple_marks_uses_later_true_mark():
    marks = [
        make_mark(name="skipif", args=("0",), kwargs={"reason": "first"}),
        make_mark(name="skipif", args=("1",), kwargs={"reason": "second"}),
    ]
    ev = evaluate.MarkEvaluator(make_item(marks), "skipif")
    assert ev._istrue() is True
    assert ev.reason == "second"
    assert ev._mark is marks[1]


def test_istrue_caches_result():
    mark = make_mark(name="skipif", args=("1",), kwargs={"reason": "cached"})
    item = make_item([mark])
    ev = evaluate.MarkEvaluator(item, "skipif")
    assert ev._istrue() is True
    item._marks = []
    assert ev._istrue() is True


def test_get_returns_default_without_current_mark():
    ev = evaluate.MarkEvaluator(make_item(), "skipif")
    assert ev.get("reason", "default") == "default"


def test_get_returns_kwarg_from_current_mark():
    mark = make_mark(name="skipif", kwargs={"reason": "hello", "x": 3})
    ev = evaluate.MarkEvaluator(make_item([mark]), "skipif")
    ev._mark = mark
    assert ev.get("x") == 3
    assert ev.get("missing", "d") == "d"


def test_getexplanation_returns_reason_attribute_when_present():
    ev = evaluate.MarkEvaluator(make_item(), "skipif")
    ev.reason = "because"
    assert ev.getexplanation() == "because"


def test_getexplanation_returns_mark_reason_when_no_reason_attribute():
    mark = make_mark(name="skipif", kwargs={"reason": "from mark"})
    ev = evaluate.MarkEvaluator(make_item([mark]), "skipif")
    ev._mark = mark
    assert ev.getexplanation() == "from mark"


def test_getexplanation_returns_empty_string_without_reason_or_expr():
    ev = evaluate.MarkEvaluator(make_item(), "skipif")
    assert ev.getexplanation() == ""


def test_getexplanation_returns_condition_prefix_for_expr():
    ev = evaluate.MarkEvaluator(make_item(), "skipif")
    ev.expr = "x > 1"
    assert ev.getexplanation() == "condition: x > 1"


def test_istrue_can_evaluate_against_item_obj_globals():
    sentinel = object()

    def func():
        return sentinel

    mark = make_mark(name="skipif", args=("sentinel is not None",), kwargs={"reason": "global"})
    ev = evaluate.MarkEvaluator(make_item([mark], obj=func), "skipif")
    assert ev._istrue() is True
    assert ev.reason == "global"


def test_istrue_expression_can_use_config_from_globals():
    item = make_item([make_mark(name="skipif", args=("config is not None",), kwargs={"reason": "cfg"})])
    ev = evaluate.MarkEvaluator(item, "skipif")
    assert ev._istrue() is True
    assert ev.reason == "cfg"


def test_istrue_syntax_error_becomes_failed_with_formatted_message():
    mark = make_mark(name="skipif", args=("(",), kwargs={})
    ev = evaluate.MarkEvaluator(make_item([mark]), "skipif")
    with pytest.raises(Failed) as excinfo:
        ev.istrue()
    msg = str(excinfo.value)
    assert "Error evaluating 'skipif' expression" in msg
    assert "    (" in msg
    assert "SyntaxError: invalid syntax" in msg
    assert ev.wasvalid() is False


def test_istrue_name_error_becomes_failed_with_exception_text():
    mark = make_mark(name="skipif", args=("unknown_name",), kwargs={})
    ev = evaluate.MarkEvaluator(make_item([mark]), "skipif")
    with pytest.raises(Failed) as excinfo:
        ev.istrue()
    msg = str(excinfo.value)
    assert "Error evaluating 'skipif' expression" in msg
    assert "    unknown_name" in msg
    assert "NameError" in msg
    assert ev.wasvalid() is False
