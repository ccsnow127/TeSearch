import types
import pytest
import _pytest.mark.evaluate as evaluate
from _pytest.mark.structures import Mark
from _pytest.outcomes import Failed

class DummyConfig:
    pass

class DummyItem:

    def __init__(self, marks=None, obj=None, config=None):
        self._marks = list(marks or [])
        self.obj = obj
        self.config = config if config is not None else DummyConfig()

    def iter_markers(self, name=None):
        for mark in self._marks:
            if name is None or mark.name == name:
                yield mark

def make_mark(name='skipif', args=(), kwargs=None):
    return Mark(name=name, args=tuple(args), kwargs=dict(kwargs or {}))

def make_item(marks=None, obj=None):
    return DummyItem(marks=marks, obj=obj)

def test_compiled_eval_simple_expression():
    assert evaluate.compiled_eval('1 + 2 == 3', {}) is True

def test_compiled_eval_uses_provided_globals():
    d = {'x': 10}
    assert evaluate.compiled_eval('x * 2', d) == 20

def test_bool_false_when_no_matching_marks():
    item = make_item(marks=[make_mark(name='other')])
    ev = evaluate.MarkEvaluator(item, 'skipif')
    assert bool(ev) is False

def test_bool_true_when_matching_marks_exist():
    item = make_item(marks=[make_mark(name='skipif')])
    ev = evaluate.MarkEvaluator(item, 'skipif')
    assert bool(ev) is True

def test_wasvalid_initially_true():
    ev = evaluate.MarkEvaluator(make_item(), 'skipif')
    assert ev.wasvalid() is True

def test_get_marks_filters_by_name():
    marks = [make_mark(name='skipif'), make_mark(name='xfail'), make_mark(name='skipif')]
    ev = evaluate.MarkEvaluator(make_item(marks=marks), 'skipif')
    got = ev._get_marks()
    assert got == [marks[0], marks[2]]

def test_invalidraise_without_raises_returns_none():
    mark = make_mark(name='xfail', kwargs={'reason': 'x'})
    ev = evaluate.MarkEvaluator(make_item(marks=[mark]), 'xfail')
    ev._mark = mark
    assert ev.invalidraise(ValueError()) is None

def test_invalidraise_with_matching_exception_returns_false():
    mark = make_mark(name='xfail', kwargs={'raises': ValueError})
    ev = evaluate.MarkEvaluator(make_item(marks=[mark]), 'xfail')
    ev._mark = mark
    assert ev.invalidraise(ValueError()) is False

def test_invalidraise_with_non_matching_exception_returns_true():
    mark = make_mark(name='xfail', kwargs={'raises': ValueError})
    ev = evaluate.MarkEvaluator(make_item(marks=[mark]), 'xfail')
    ev._mark = mark
    assert ev.invalidraise(TypeError()) is True

def test_getglobals_includes_test_function_globals_when_obj_present():
    sentinel = object()

    def func():
        return None
    func.__globals__['SENTINEL_FOR_EVAL_TEST'] = sentinel
    try:
        item = make_item(obj=func)
        ev = evaluate.MarkEvaluator(item, 'skipif')
        g = ev._getglobals()
        assert g['SENTINEL_FOR_EVAL_TEST'] is sentinel
    finally:
        del func.__globals__['SENTINEL_FOR_EVAL_TEST']

def test_istrue_returns_cached_result_without_recomputing():
    ev = evaluate.MarkEvaluator(make_item(), 'skipif')
    ev.result = True
    assert ev._istrue() is True

def test_istrue_empty_args_mark_is_true_and_sets_reason():
    mark = make_mark(name='skipif', kwargs={'reason': 'because'})
    ev = evaluate.MarkEvaluator(make_item(marks=[mark]), 'skipif')
    assert ev._istrue() is True
    assert ev.reason == 'because'

def test_istrue_boolean_condition_requires_reason():
    mark = make_mark(name='skipif', args=(True,))
    ev = evaluate.MarkEvaluator(make_item(marks=[mark]), 'skipif')
    with pytest.raises(Failed) as excinfo:
        ev._istrue()
    assert 'you need to specify reason=STRING when using booleans as conditions.' in str(excinfo.value)

def test_istrue_boolean_condition_with_reason_true():
    mark = make_mark(name='skipif', args=(1,), kwargs={'reason': 'bool reason'})
    ev = evaluate.MarkEvaluator(make_item(marks=[mark]), 'skipif')
    assert ev._istrue() is True
    assert ev.reason == 'bool reason'
    assert ev.expr == 1

def test_istrue_boolean_condition_with_reason_false():
    mark = make_mark(name='skipif', args=(0,), kwargs={'reason': 'bool reason'})
    ev = evaluate.MarkEvaluator(make_item(marks=[mark]), 'skipif')
    assert ev._istrue() is False
    assert ev.result is False
    assert ev.expr == 0

def test_get_returns_default_when_no_current_mark():
    ev = evaluate.MarkEvaluator(make_item(), 'skipif')
    assert ev.get('reason', 'default') == 'default'

def test_get_returns_mark_kwarg_value():
    mark = make_mark(name='skipif', kwargs={'reason': 'abc'})
    ev = evaluate.MarkEvaluator(make_item(marks=[mark]), 'skipif')
    ev._mark = mark
    assert ev.get('reason') == 'abc'

def test_getexplanation_prefers_reason_attribute():
    mark = make_mark(name='skipif', kwargs={'reason': 'from mark'})
    ev = evaluate.MarkEvaluator(make_item(marks=[mark]), 'skipif')
    ev._mark = mark
    ev.reason = 'from attr'
    assert ev.getexplanation() == 'from attr'

def test_getexplanation_uses_mark_reason_when_no_reason_attr():
    mark = make_mark(name='skipif', kwargs={'reason': 'from mark'})
    ev = evaluate.MarkEvaluator(make_item(marks=[mark]), 'skipif')
    ev._mark = mark
    assert ev.getexplanation() == 'from mark'

def test_getexplanation_empty_when_no_reason_and_no_expr():
    ev = evaluate.MarkEvaluator(make_item(), 'skipif')
    assert ev.getexplanation() == ''

def test_getexplanation_condition_prefix_when_only_expr():
    ev = evaluate.MarkEvaluator(make_item(), 'skipif')
    ev.expr = 'x > 1'
    assert ev.getexplanation() == 'condition: x > 1'

def test_istrue_string_expression_can_access_function_globals():

    def func():
        return None
    func.__globals__['VISIBLE_NAME_FOR_EVAL_TEST'] = 42
    try:
        mark = make_mark(name='skipif', args=('VISIBLE_NAME_FOR_EVAL_TEST == 42',))
        ev = evaluate.MarkEvaluator(make_item(marks=[mark], obj=func), 'skipif')
        assert ev._istrue() is True
    finally:
        del func.__globals__['VISIBLE_NAME_FOR_EVAL_TEST']
