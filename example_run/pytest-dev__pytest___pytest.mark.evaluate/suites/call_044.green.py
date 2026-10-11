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


def test_compiled_eval_marks_bool_and_getglobals():
    assert sut.compiled_eval("1 + 2 == 3", {}) is True
    assert sut.compiled_eval("value * 2", {"value": 5}) == 10

    marks = [
        make_mark(name="skipif", args=(False,), kwargs={"reason": "x"}),
        make_mark(name="xfail"),
        make_mark(name="skipif"),
    ]
    item = make_item(marks=marks, obj=sample_function)
    ev = sut.MarkEvaluator(item, "skipif")

    assert bool(ev) is True
    got = ev._get_marks()
    assert len(got) == 2
    assert [m.name for m in got] == ["skipif", "skipif"]

    d = ev._getglobals()
    assert d["os"] is sut.os
    assert d["sys"] is sut.sys
    assert d["platform"] is sut.platform
    assert d["config"] is item.config
    assert d["SAMPLE_GLOBAL"] == 123

    no_obj_item = make_item()
    d2 = sut.MarkEvaluator(no_obj_item, "skipif")._getglobals()
    assert d2["os"] is sut.os
    assert d2["sys"] is sut.sys
    assert d2["platform"] is sut.platform
    assert d2["config"] is no_obj_item.config
    assert "SAMPLE_GLOBAL" not in d2

    assert bool(sut.MarkEvaluator(make_item([make_mark(name="other")]), "skipif")) is False
    assert sut.MarkEvaluator(make_item(), "skipif").wasvalid() is True


@pytest.mark.parametrize(
    "marks,obj,expected,result_attr,expr,reason,explanation",
    [
        ([make_mark(name="skipif", args=("1 == 1",), kwargs={"reason": "because"})], sample_function, True, True, "1 == 1", "because", "because"),
        ([make_mark(name="skipif", args=("1 == 2",), kwargs={"reason": "nope"})], sample_function, False, False, "1 == 2", None, "nope"),
        ([make_mark(name="skipif", args=("0",), kwargs={"condition": "2 > 1", "reason": "kwcond"})], sample_function, True, True, "2 > 1", "kwcond", "kwcond"),
        ([make_mark(name="skipif", args=(1,), kwargs={"reason": "bool"})], None, True, True, 1, "bool", "bool"),
        ([make_mark(name="skipif", args=(), kwargs={"reason": "empty"})], None, True, True, None, "empty", "empty"),
        ([make_mark(name="skipif", args=("0", "3 > 2"), kwargs={"reason": "second"})], sample_function, True, True, "3 > 2", "second", "second"),
        ([make_mark(name="skipif", args=("config is not None",), kwargs={"reason": "cfg"})], None, True, True, "config is not None", "cfg", "cfg"),
        (
            [
                make_mark(name="skipif", args=("0",), kwargs={"reason": "first"}),
                make_mark(name="skipif", args=("1",), kwargs={"reason": "second"}),
            ],
            sample_function,
            True,
            True,
            "1",
            "second",
            "second",
        ),
        (
            [
                make_mark(name="skipif", args=("0",), kwargs={"reason": "first"}),
                make_mark(name="skipif", args=("False",), kwargs={"reason": "second"}),
            ],
            sample_function,
            False,
            False,
            "False",
            None,
            "second",
        ),
        ([make_mark(name="skipif", args=("SPECIAL_NAME == 7",), kwargs={"reason": "global"})], "special", True, True, "SPECIAL_NAME == 7", "global", "global"),
    ],
)
def test_istrue_success_false_paths_cache_and_current_mark(marks, obj, expected, result_attr, expr, reason, explanation):
    if obj == "special":
        def f():
            return None
        f.__globals__["SPECIAL_NAME"] = 7
        obj = f

    ev = sut.MarkEvaluator(make_item(marks, obj=obj), "skipif")
    assert ev._istrue() is expected
    assert ev.result is result_attr
    if expr is not None:
        assert ev.expr == expr
    if reason is not None:
        assert ev.reason == reason
    assert ev.getexplanation() == explanation

    original_item = ev.item
    ev.item = make_item([])
    assert ev._istrue() is expected
    ev.item = original_item

    if expected:
        assert ev._mark is not None

    custom_mark = make_mark(name="skipif", args=("1",), kwargs={"reason": "r", "custom": 42})
    custom_ev = sut.MarkEvaluator(make_item([custom_mark], obj=sample_function), "skipif")
    assert custom_ev._istrue() is True
    assert custom_ev.get("custom") == 42
    assert custom_ev._mark is custom_mark
    assert custom_ev.expr == "1"
    assert custom_ev.reason == "r"


def test_no_marks_get_explanations_and_invalidraise():
    ev = sut.MarkEvaluator(make_item(), "skipif")
    assert ev._istrue() is False
    assert not hasattr(ev, "result")

    ev.result = False
    assert ev._istrue() is False

    assert ev.get("reason", "default") == "default"
    ev.expr = "x > 1"
    assert ev.getexplanation() == "condition: x > 1"

    ev.reason = "attr reason"
    ev._mark = make_mark(name="skipif", kwargs={"reason": "mark reason"})
    assert ev.getexplanation() == "attr reason"
    assert ev.get("reason") == "mark reason"

    ev2 = sut.MarkEvaluator(make_item(), "skipif")
    ev2._mark = make_mark(name="skipif", kwargs={"reason": "mark reason"})
    assert ev2.getexplanation() == "mark reason"

    ev3 = sut.MarkEvaluator(make_item(), "skipif")
    assert ev3.getexplanation() == ""

    ev4 = sut.MarkEvaluator(make_item(), "xfail")
    ev4._mark = make_mark(name="xfail", kwargs={})
    assert ev4.invalidraise(ValueError()) is None
    ev4._mark = make_mark(name="xfail", kwargs={"raises": ValueError})
    assert ev4.invalidraise(ValueError()) is False
    assert ev4.invalidraise(TypeError()) is True


@pytest.mark.parametrize(
    "mark,obj,expected_parts,syntax",
    [
        (
            make_mark(name="skipif", args=("pytest.fail('boom')",), kwargs={}),
            types.SimpleNamespace(__globals__={"pytest": pytest}),
            ["Error evaluating 'skipif' expression", "pytest.fail('boom')", "Failed: boom"],
            False,
        ),
        (
            make_mark(name="skipif", args=("(",), kwargs={}),
            sample_function,
            ["Error evaluating 'skipif' expression", "\n    (\n", "\n      ^\nSyntaxError: invalid syntax"],
            True,
        ),
    ],
)
def test_istrue_rewraps_test_outcomes(mark, obj, expected_parts, syntax):
    ev = sut.MarkEvaluator(make_item([mark], obj=obj), "skipif")
    with pytest.raises(sut.TEST_OUTCOME) as excinfo:
        ev.istrue()
    assert ev.wasvalid() is False
    text = str(excinfo.value)
    for part in expected_parts:
        assert part in text
    if syntax:
        assert isinstance(ev.exc[1], SyntaxError)
        assert ev.exc[1].offset is not None
    else:
        assert "Traceback" not in text


def test_boolean_reason_requirement():
    mark = make_mark(name="skipif", args=(True,), kwargs={})
    ev = sut.MarkEvaluator(make_item([mark]), "skipif")
    with pytest.raises(sut.TEST_OUTCOME) as excinfo:
        ev._istrue()
    assert "you need to specify reason=STRING when using booleans as conditions." in str(excinfo.value)
