import importlib
import types
import pytest
sut = importlib.import_module('_pytest.mark.evaluate')
Mark = importlib.import_module('_pytest.mark.structures').Mark

class DummyConfig:

    def __init__(self, value='cfg'):
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

def make_mark(name='skipif', args=(), kwargs=None):
    return Mark(name=name, args=tuple(args), kwargs=dict(kwargs or {}))

def make_item(marks=(), obj=None, config=None):
    return DummyItem(marks=marks, obj=obj, config=config)

def sample_function():
    return None
sample_function.__globals__['SAMPLE_GLOBAL'] = 123

def test_compiled_eval_basic_and_globals():
    assert sut.compiled_eval('1 + 2 == 3', {}) is True
    assert sut.compiled_eval('value * 2', {'value': 5}) == 10
    assert sut.compiled_eval('config.value', {'config': DummyConfig('seen')}) == 'seen'

def test_compiled_eval_exposes_python_builtins():
    assert sut.compiled_eval('len([1, 2, 3]) + min(5, 2)', {}) == 5
    assert sut.compiled_eval('sorted({3, 1, 2})', {}) == [1, 2, 3]

def test_bool_get_marks_wasvalid_and_no_obj_getglobals():
    marks = [make_mark(name='other'), make_mark(name='skipif'), make_mark(name='skipif')]
    item = make_item(marks=marks)
    ev = sut.MarkEvaluator(item, 'skipif')
    assert bool(ev) is True
    got = ev._get_marks()
    assert len(got) == 2
    assert [m.name for m in got] == ['skipif', 'skipif']
    assert ev.wasvalid() is True
    d = ev._getglobals()
    assert d['os'] is sut.os
    assert d['sys'] is sut.sys
    assert d['platform'] is sut.platform
    assert d['config'] is item.config
    assert 'SAMPLE_GLOBAL' not in d
    assert bool(sut.MarkEvaluator(make_item([make_mark(name='other')]), 'skipif')) is False

def test_getglobals_includes_obj_globals_and_expression_uses_them():

    def f():
        return None
    f.__globals__['SPECIAL_NAME'] = 7
    item = make_item([make_mark(args=('SPECIAL_NAME == 7',), kwargs={'reason': 'global'})], obj=f)
    ev = sut.MarkEvaluator(item, 'skipif')
    d = ev._getglobals()
    assert d['SPECIAL_NAME'] == 7
    assert ev._istrue() is True
    assert ev.expr == 'SPECIAL_NAME == 7'
    assert ev.reason == 'global'

def test_getglobals_obj_overrides_base_names():

    def f():
        return None
    sentinel_os = object()
    sentinel_platform = object()
    f.__globals__['os'] = sentinel_os
    f.__globals__['platform'] = sentinel_platform
    ev = sut.MarkEvaluator(make_item(obj=f), 'skipif')
    d = ev._getglobals()
    assert d['os'] is sentinel_os
    assert d['platform'] is sentinel_platform
    assert d['sys'] is sut.sys

def test_istrue_string_true_and_cache():
    mark = make_mark(args=('1 == 1',), kwargs={'reason': 'because'})
    ev = sut.MarkEvaluator(make_item([mark], obj=sample_function), 'skipif')
    assert ev._istrue() is True
    assert ev.result is True
    assert ev.expr == '1 == 1'
    assert ev.reason == 'because'
    assert ev.getexplanation() == 'because'
    ev.item = make_item([], obj=sample_function)
    assert ev._istrue() is True
    assert ev.expr == '1 == 1'
    assert ev.reason == 'because'

def test_istrue_cached_false_short_circuits_later_true():
    mark = make_mark(args=('0',), kwargs={'reason': 'no'})
    ev = sut.MarkEvaluator(make_item([mark], obj=sample_function), 'skipif')
    assert ev._istrue() is False
    assert ev.result is False
    ev.item = make_item([make_mark(args=('1',), kwargs={'reason': 'yes'})], obj=sample_function)
    assert ev._istrue() is False
    assert ev.expr == '0'
    assert not hasattr(ev, 'reason')
    assert ev.getexplanation() == 'no'

def test_istrue_string_false_and_all_false_marks_explanation():
    mark = make_mark(args=('1 == 2',), kwargs={'reason': 'nope'})
    ev = sut.MarkEvaluator(make_item([mark], obj=sample_function), 'skipif')
    assert ev._istrue() is False
    assert ev.result is False
    assert ev.expr == '1 == 2'
    assert not hasattr(ev, 'reason')
    assert ev.getexplanation() == 'nope'
    marks = [make_mark(args=('0',), kwargs={'reason': 'first'}), make_mark(args=('False',), kwargs={'reason': 'second'})]
    ev2 = sut.MarkEvaluator(make_item(marks, obj=sample_function), 'skipif')
    assert ev2._istrue() is False
    assert ev2.result is False
    assert ev2.expr == 'False'
    assert ev2.getexplanation() == 'second'

def test_istrue_condition_kwarg_true_and_false_paths():
    true_mark = make_mark(args=('0',), kwargs={'condition': '2 > 1', 'reason': 'kwcond'})
    ev = sut.MarkEvaluator(make_item([true_mark], obj=sample_function), 'skipif')
    assert ev._istrue() is True
    assert ev.result is True
    assert ev.expr == '2 > 1'
    assert ev.reason == 'kwcond'
    false_mark = make_mark(args=('1',), kwargs={'condition': '0', 'custom': 'v'})
    ev2 = sut.MarkEvaluator(make_item([false_mark], obj=sample_function), 'skipif')
    assert ev2._istrue() is False
    assert ev2.result is False
    assert ev2.expr == '0'
    assert ev2.get('custom') == 'v'
    assert ev2.get('missing', 'fallback') == 'fallback'
    assert ev2.getexplanation() == 'condition: 0'

def test_istrue_boolean_conditions_and_reason_requirement():
    bad = sut.MarkEvaluator(make_item([make_mark(args=(True,), kwargs={})]), 'skipif')
    with pytest.raises(sut.TEST_OUTCOME) as excinfo:
        bad._istrue()
    assert 'you need to specify reason=STRING when using booleans as conditions.' in str(excinfo.value)
    good = sut.MarkEvaluator(make_item([make_mark(args=(1,), kwargs={'reason': 'bool'})]), 'skipif')
    assert good._istrue() is True
    assert good.result is True
    assert good.expr == 1
    assert good.reason == 'bool'
    assert good.getexplanation() == 'bool'

def test_istrue_boolean_false_with_reason_stays_false_and_sets_expr():
    ev = sut.MarkEvaluator(make_item([make_mark(args=(0,), kwargs={'reason': 'zero'})]), 'skipif')
    assert ev._istrue() is False
    assert ev.result is False
    assert ev.expr == 0
    assert ev.getexplanation() == 'zero'

def test_istrue_empty_args_mark_true_and_no_marks_false():
    ev = sut.MarkEvaluator(make_item([make_mark(args=(), kwargs={'reason': 'empty'})]), 'skipif')
    assert ev._istrue() is True
    assert ev.result is True
    assert ev.reason == 'empty'
    assert ev.getexplanation() == 'empty'
    nonev = sut.MarkEvaluator(make_item(), 'skipif')
    assert nonev._istrue() is False
    assert not hasattr(nonev, 'result')
    assert nonev.getexplanation() == ''

def test_istrue_multiple_args_and_multiple_marks_later_true():
    mark = make_mark(args=('0', '3 > 2'), kwargs={'reason': 'second'})
    ev = sut.MarkEvaluator(make_item([mark], obj=sample_function), 'skipif')
    assert ev._istrue() is True
    assert ev.result is True
    assert ev.expr == '3 > 2'
    assert ev.reason == 'second'
    marks = [make_mark(args=('0',), kwargs={'reason': 'first'}), make_mark(args=('1',), kwargs={'reason': 'second'})]
    ev2 = sut.MarkEvaluator(make_item(marks, obj=sample_function), 'skipif')
    assert ev2._istrue() is True
    assert ev2.result is True
    assert ev2.expr == '1'
    assert ev2.reason == 'second'

def test_istrue_multiple_args_all_false_keeps_last_expr():
    mark = make_mark(args=('0', '1 == 2', 'False'), kwargs={'reason': 'final reason'})
    ev = sut.MarkEvaluator(make_item([mark], obj=sample_function), 'skipif')
    assert ev._istrue() is False
    assert ev.result is False
    assert ev.expr == 'False'
    assert ev._mark is mark
    assert ev.getexplanation() == 'final reason'

def test_get_getexplanation_and_current_mark_custom_attr():
    ev = sut.MarkEvaluator(make_item(), 'skipif')
    assert ev.get('reason', 'default') == 'default'
    ev.expr = 'x > 1'
    assert ev.getexplanation() == 'condition: x > 1'
    ev.expr = 0
    assert ev.getexplanation() == 'condition: 0'
    ev.expr = ['a', 2]
    assert ev.getexplanation() == "condition: ['a', 2]"
    ev.reason = 'attr reason'
    ev._mark = make_mark(kwargs={'reason': 'mark reason'})
    assert ev.getexplanation() == 'attr reason'
    assert ev.get('reason') == 'mark reason'
    ev2 = sut.MarkEvaluator(make_item([make_mark(args=('1',), kwargs={'reason': 'r', 'custom': 42})], obj=sample_function), 'skipif')
    assert ev2._istrue() is True
    assert ev2._mark.args == ('1',)
    assert ev2.get('custom') == 42

def test_getexplanation_empty_reason_falls_back_to_expr_or_empty():
    ev = sut.MarkEvaluator(make_item(), 'skipif')
    ev.reason = ''
    ev._mark = make_mark(kwargs={'reason': ''})
    ev.expr = 'abc'
    assert ev.getexplanation() == 'condition: abc'
    ev2 = sut.MarkEvaluator(make_item(), 'skipif')
    ev2._mark = make_mark(kwargs={'reason': ''})
    assert ev2.getexplanation() == ''

def test_invalidraise_none_single_and_tuple():
    ev = sut.MarkEvaluator(make_item(), 'xfail')
    ev._mark = make_mark(name='xfail', kwargs={})
    assert ev.invalidraise(ValueError()) is None
    ev._mark = make_mark(name='xfail', kwargs={'raises': ValueError})
    assert ev.invalidraise(ValueError()) is False
    assert ev.invalidraise(TypeError()) is True
    ev._mark = make_mark(name='xfail', kwargs={'raises': (ValueError, TypeError)})
    assert ev.invalidraise(ValueError()) is False
    assert ev.invalidraise(TypeError()) is False
    assert ev.invalidraise(RuntimeError()) is True

def test_bool_does_not_cache_marker_changes():
    item = make_item([make_mark()], obj=sample_function)
    ev = sut.MarkEvaluator(item, 'skipif')
    assert bool(ev) is True
    item._marks = [make_mark(name='other')]
    assert bool(ev) is False
    item._marks = [make_mark(), make_mark()]
    assert bool(ev) is True

def test_istrue_rewraps_non_syntax_test_outcome_and_sets_exc():
    mark = make_mark(args=("pytest.fail('boom')",), kwargs={})
    item = make_item([mark], obj=types.SimpleNamespace(__globals__={'pytest': pytest}))
    ev = sut.MarkEvaluator(item, 'skipif')
    with pytest.raises(sut.TEST_OUTCOME) as excinfo:
        ev.istrue()
    assert ev.wasvalid() is False
    assert isinstance(ev.exc[1], BaseException)
    text = str(excinfo.value)
    assert "Error evaluating 'skipif' expression" in text
    assert "    pytest.fail('boom')" in text
    assert 'Failed: boom' in text
    assert 'Traceback' not in text

def test_istrue_cached_true_short_circuits_later_error():
    mark = make_mark(args=('1',), kwargs={'reason': 'cached'})
    ev = sut.MarkEvaluator(make_item([mark], obj=sample_function), 'skipif')
    assert ev._istrue() is True
    ev.item = make_item([make_mark(args=('(',), kwargs={})], obj=sample_function)
    assert ev._istrue() is True
    assert ev.reason == 'cached'
    assert ev.expr == '1'
