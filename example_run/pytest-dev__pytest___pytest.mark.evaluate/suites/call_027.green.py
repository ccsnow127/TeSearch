import importlib
import types
import pytest
sut = importlib.import_module('_pytest.mark.evaluate')
Mark = importlib.import_module('_pytest.mark.structures').Mark

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

def make_mark(name='skipif', args=(), kwargs=None):
    return Mark(name=name, args=tuple(args), kwargs=dict(kwargs or {}))

def make_item(marks=(), obj=None, config=None):
    return DummyItem(marks=marks, obj=obj, config=config)

def sample_function():
    return None
sample_function.__globals__['SAMPLE_GLOBAL'] = 123

def special_function():
    return None
special_function.__globals__['SPECIAL_NAME'] = 7

def test_compiled_eval_getglobals_and_bool_marker_staleness():
    assert sut.compiled_eval('1 + 2 == 3', {}) is True
    assert sut.compiled_eval('value * 2', {'value': 5}) == 10
    marks = [make_mark(name='skipif', args=(False,), kwargs={'reason': 'x'}), make_mark(name='xfail'), make_mark(name='skipif')]
    item = make_item(marks=marks, obj=sample_function)
    ev = sut.MarkEvaluator(item, 'skipif')
    assert bool(ev) is True
    assert [m.name for m in ev._get_marks()] == ['skipif', 'skipif']
    d = ev._getglobals()
    assert d['os'] is sut.os
    assert d['sys'] is sut.sys
    assert d['platform'] is sut.platform
    assert d['config'] is item.config
    assert d['SAMPLE_GLOBAL'] == 123
    no_obj_item = make_item()
    d2 = sut.MarkEvaluator(no_obj_item, 'skipif')._getglobals()
    assert d2['os'] is sut.os
    assert d2['sys'] is sut.sys
    assert d2['platform'] is sut.platform
    assert d2['config'] is no_obj_item.config
    assert 'SAMPLE_GLOBAL' not in d2
    item._marks = [make_mark(name='other')]
    assert bool(ev) is False
    item._marks = [make_mark(name='skipif'), make_mark(name='skipif')]
    assert bool(ev) is True
    assert bool(sut.MarkEvaluator(make_item(), 'skipif')) is False
    assert sut.MarkEvaluator(make_item(), 'skipif').wasvalid() is True

@pytest.mark.parametrize('marks,obj,expected,expr,has_reason,explanation', [([make_mark(name='skipif', args=('1 == 1',), kwargs={'reason': 'because'})], sample_function, True, '1 == 1', True, 'because'), ([make_mark(name='skipif', args=('1 == 2',), kwargs={'reason': 'nope'})], sample_function, False, '1 == 2', False, 'nope'), ([make_mark(name='skipif', args=('0',), kwargs={'condition': '2 > 1', 'reason': 'kwcond'})], sample_function, True, '2 > 1', True, 'kwcond'), ([make_mark(name='skipif', args=(1,), kwargs={'reason': 'bool'})], None, True, 1, True, 'bool'), ([make_mark(name='skipif', args=(), kwargs={'reason': 'empty'})], None, True, None, True, 'empty'), ([make_mark(name='skipif', args=('0', '3 > 2'), kwargs={'reason': 'second'})], sample_function, True, '3 > 2', True, 'second'), ([make_mark(name='skipif', args=('config is not None',), kwargs={'reason': 'cfg'})], None, True, 'config is not None', True, 'cfg'), ([make_mark(name='skipif', args=('SPECIAL_NAME == 7',), kwargs={'reason': 'global'})], special_function, True, 'SPECIAL_NAME == 7', True, 'global'), ([make_mark(name='skipif', args=('0',), kwargs={'reason': 'first'}), make_mark(name='skipif', args=('1',), kwargs={'reason': 'second'})], sample_function, True, '1', True, 'second'), ([make_mark(name='skipif', args=('0',), kwargs={'reason': 'first'}), make_mark(name='skipif', args=('False',), kwargs={'reason': 'second'})], sample_function, False, 'False', False, 'second')])
def test_istrue_paths_and_cache(marks, obj, expected, expr, has_reason, explanation):
    ev = sut.MarkEvaluator(make_item(marks, obj=obj), 'skipif')
    assert ev._istrue() is expected
    assert ev.result is expected
    if expr is not None:
        assert ev.expr == expr
    if has_reason:
        assert ev.reason == explanation
    else:
        assert not hasattr(ev, 'reason')
    assert ev.getexplanation() == explanation
    ev.item = make_item([], obj=obj)
    assert ev._istrue() is expected

def test_no_marks_cached_result_get_and_explanation_variants():
    ev = sut.MarkEvaluator(make_item(), 'skipif')
    assert ev._istrue() is False
    assert not hasattr(ev, 'result')
    ev.result = False
    assert ev._istrue() is False
    assert ev.get('reason', 'default') == 'default'
    ev.expr = 'x > 1'
    assert ev.getexplanation() == 'condition: x > 1'
    ev.expr = 0
    assert ev.getexplanation() == 'condition: 0'
    ev.expr = ['a', 2]
    assert ev.getexplanation() == "condition: ['a', 2]"
    ev.reason = 'attr reason'
    ev._mark = make_mark(name='skipif', kwargs={'reason': 'mark reason'})
    assert ev.getexplanation() == 'attr reason'
    assert ev.get('reason') == 'mark reason'
    ev2 = sut.MarkEvaluator(make_item(), 'skipif')
    ev2._mark = make_mark(name='skipif', kwargs={'reason': 'mark reason'})
    assert ev2.getexplanation() == 'mark reason'
    ev3 = sut.MarkEvaluator(make_item(), 'skipif')
    assert ev3.getexplanation() == ''

def test_boolean_reason_requirement_and_invalidraise_cases():
    ev = sut.MarkEvaluator(make_item([make_mark(name='skipif', args=(True,), kwargs={})]), 'skipif')
    with pytest.raises(sut.TEST_OUTCOME) as excinfo:
        ev._istrue()
    assert 'you need to specify reason=STRING when using booleans as conditions.' in str(excinfo.value)
    ev2 = sut.MarkEvaluator(make_item(), 'xfail')
    ev2._mark = make_mark(name='xfail', kwargs={})
    assert ev2.invalidraise(ValueError()) is None
    ev2._mark = make_mark(name='xfail', kwargs={'raises': ValueError, 'other': 'x'})
    assert ev2.invalidraise(ValueError()) is False
    assert ev2.invalidraise(TypeError()) is True
    assert ev2.get('other') == 'x'
    assert ev2.get('missing', 99) == 99
    ev2._mark = make_mark(name='xfail', kwargs={'raises': (ValueError, TypeError)})
    assert ev2.invalidraise(ValueError()) is False
    assert ev2.invalidraise(TypeError()) is False
    assert ev2.invalidraise(RuntimeError()) is True
    ev2._mark = None
    assert ev2.get('other', 'fallback') == 'fallback'

def test_current_mark_custom_get_and_condition_kwarg_false():
    mark = make_mark(name='skipif', args=('1',), kwargs={'reason': 'r', 'custom': 42})
    ev = sut.MarkEvaluator(make_item([mark], obj=sample_function), 'skipif')
    assert ev._istrue() is True
    assert ev.get('custom') == 42
    assert ev._mark is mark
    assert ev.expr == '1'
    assert ev.reason == 'r'
    mark2 = make_mark(name='skipif', args=('1',), kwargs={'condition': '0', 'custom': 'v'})
    ev2 = sut.MarkEvaluator(make_item([mark2], obj=sample_function), 'skipif')
    assert ev2._istrue() is False
    assert ev2.result is False
    assert ev2.expr == '0'
    assert ev2.get('custom') == 'v'
    assert ev2.get('missing', 'fallback') == 'fallback'
    assert ev2.getexplanation() == 'condition: 0'

def test_istrue_rewraps_non_syntax_test_outcome():
    mark = make_mark(name='skipif', args=("pytest.fail('boom')",), kwargs={})
    item = make_item([mark], obj=types.SimpleNamespace(__globals__={'pytest': pytest}))
    ev = sut.MarkEvaluator(item, 'skipif')
    with pytest.raises(sut.TEST_OUTCOME) as excinfo:
        ev.istrue()
    assert ev.wasvalid() is False
    text = str(excinfo.value)
    assert "Error evaluating 'skipif' expression" in text
    assert "pytest.fail('boom')" in text
    assert 'Failed: boom' in text
    assert 'Traceback' not in text

def test_cached_true_short_circuits_later_errors():
    mark = make_mark(name='skipif', args=('1',), kwargs={'reason': 'cached'})
    ev = sut.MarkEvaluator(make_item([mark], obj=sample_function), 'skipif')
    assert ev._istrue() is True
    assert ev.result is True
    ev.item = make_item([make_mark(name='skipif', args=('(',), kwargs={})], obj=sample_function)
    assert ev._istrue() is True
    assert ev.reason == 'cached'
    assert ev.expr == '1'

def test_get_marks_empty_and_bool_false_for_other_name():
    ev = sut.MarkEvaluator(make_item(), 'xfail')
    assert ev._get_marks() == []
    assert bool(ev) is False
    assert bool(sut.MarkEvaluator(make_item([make_mark(name='other')]), 'skipif')) is False

def test_getexplanation_prefers_reason_over_expr_and_empty_without_expr():
    ev = sut.MarkEvaluator(make_item(), 'skipif')
    ev.expr = 5
    assert ev.getexplanation() == 'condition: 5'
    ev._mark = make_mark(name='skipif', kwargs={'reason': 'mark reason'})
    assert ev.getexplanation() == 'mark reason'
    ev.reason = 'attr reason'
    assert ev.getexplanation() == 'attr reason'
    ev2 = sut.MarkEvaluator(make_item(), 'skipif')
    assert ev2.getexplanation() == ''
