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

def test_compiled_eval_getglobals_and_bool_staleness():
    assert sut.compiled_eval('1 + 2 == 3', {}) is True
    assert sut.compiled_eval('value * 2', {'value': 5}) == 10
    marks = [make_mark('skipif', args=(False,), kwargs={'reason': 'x'}), make_mark('xfail'), make_mark('skipif')]
    item = make_item(marks=marks, obj=sample_function)
    ev = sut.MarkEvaluator(item, 'skipif')
    assert ev._get_marks() == [marks[0], marks[2]]
    d = ev._getglobals()
    assert d['os'] is sut.os
    assert d['sys'] is sut.sys
    assert d['platform'] is sut.platform
    assert d['config'] is item.config
    assert d['SAMPLE_GLOBAL'] == 123
    d2 = sut.MarkEvaluator(make_item(), 'skipif')._getglobals()
    assert d2['os'] is sut.os and d2['sys'] is sut.sys and (d2['platform'] is sut.platform)
    assert 'SAMPLE_GLOBAL' not in d2
    assert bool(ev) is True
    item._marks = [make_mark('other')]
    assert bool(ev) is False
    item._marks = [make_mark('skipif'), make_mark('skipif')]
    assert bool(ev) is True
    assert sut.MarkEvaluator(make_item(), 'skipif').wasvalid() is True

@pytest.mark.parametrize('marks,obj,expected,expr,has_reason,explanation', [([make_mark('skipif', args=('1 == 1',), kwargs={'reason': 'because'})], sample_function, True, '1 == 1', True, 'because'), ([make_mark('skipif', args=('1 == 2',), kwargs={'reason': 'nope'})], sample_function, False, '1 == 2', False, 'nope'), ([make_mark('skipif', args=('0',), kwargs={'condition': '2 > 1', 'reason': 'kwcond'})], sample_function, True, '2 > 1', True, 'kwcond'), ([make_mark('skipif', args=(1,), kwargs={'reason': 'bool'})], None, True, 1, True, 'bool'), ([make_mark('skipif', args=(), kwargs={'reason': 'empty'})], None, True, None, True, 'empty'), ([make_mark('skipif', args=('0', '3 > 2'), kwargs={'reason': 'second'})], sample_function, True, '3 > 2', True, 'second'), ([make_mark('skipif', args=('config is not None',), kwargs={'reason': 'cfg'})], None, True, 'config is not None', True, 'cfg'), ([make_mark('skipif', args=('SPECIAL_NAME == 7',), kwargs={'reason': 'global'})], special_function, True, 'SPECIAL_NAME == 7', True, 'global'), ([make_mark('skipif', args=('0',), kwargs={'reason': 'first'}), make_mark('skipif', args=('1',), kwargs={'reason': 'second'})], sample_function, True, '1', True, 'second'), ([make_mark('skipif', args=('0',), kwargs={'reason': 'first'}), make_mark('skipif', args=('False',), kwargs={'reason': 'second'})], sample_function, False, 'False', False, 'second')])
def test_istrue_various_paths_and_cache(marks, obj, expected, expr, has_reason, explanation):
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

def test_no_marks_and_get_getexplanation_variants():
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
    ev._mark = make_mark('skipif', kwargs={'reason': 'mark reason', 'other': 'x'})
    assert ev.getexplanation() == 'attr reason'
    assert ev.get('reason') == 'mark reason'
    assert ev.get('other') == 'x'
    assert ev.get('missing', 99) == 99
    ev2 = sut.MarkEvaluator(make_item(), 'skipif')
    ev2._mark = make_mark('skipif', kwargs={'reason': 'mark reason'})
    assert ev2.getexplanation() == 'mark reason'
    ev3 = sut.MarkEvaluator(make_item(), 'skipif')
    assert ev3.getexplanation() == ''

def test_boolean_reason_requirement_and_invalidraise_cases():
    ev = sut.MarkEvaluator(make_item([make_mark('skipif', args=(True,), kwargs={})]), 'skipif')
    with pytest.raises(sut.TEST_OUTCOME) as excinfo:
        ev._istrue()
    assert 'you need to specify reason=STRING when using booleans as conditions.' in str(excinfo.value)
    xev = sut.MarkEvaluator(make_item(), 'xfail')
    xev._mark = make_mark('xfail', kwargs={})
    assert xev.invalidraise(ValueError()) is None
    xev._mark = make_mark('xfail', kwargs={'raises': ValueError})
    assert xev.invalidraise(ValueError()) is False
    assert xev.invalidraise(TypeError()) is True
    xev._mark = make_mark('xfail', kwargs={'raises': (ValueError, TypeError)})
    assert xev.invalidraise(ValueError()) is False
    assert xev.invalidraise(TypeError()) is False
    assert xev.invalidraise(RuntimeError()) is True
    xev._mark = None
    assert xev.get('other', 'fallback') == 'fallback'

def test_current_mark_custom_get_and_condition_kwarg_false():
    mark = make_mark('skipif', args=('1',), kwargs={'reason': 'r', 'custom': 42})
    ev = sut.MarkEvaluator(make_item([mark], obj=sample_function), 'skipif')
    assert ev._istrue() is True
    assert ev._mark is mark
    assert ev.expr == '1'
    assert ev.reason == 'r'
    assert ev.get('custom') == 42
    mark2 = make_mark('skipif', args=('1',), kwargs={'condition': '0', 'custom': 'v'})
    ev2 = sut.MarkEvaluator(make_item([mark2], obj=sample_function), 'skipif')
    assert ev2._istrue() is False
    assert ev2.result is False
    assert ev2.expr == '0'
    assert ev2.get('custom') == 'v'
    assert ev2.get('missing', 'fallback') == 'fallback'
    assert ev2.getexplanation() == 'condition: 0'

def test_istrue_rewraps_non_syntax_test_outcome():
    mark = make_mark('skipif', args=("pytest.fail('boom')",), kwargs={})
    item = make_item([mark], obj=types.SimpleNamespace(__globals__={'pytest': pytest}))
    ev = sut.MarkEvaluator(item, 'skipif')
    with pytest.raises(sut.TEST_OUTCOME) as excinfo:
        ev.istrue()
    assert ev.wasvalid() is False
    text = str(excinfo.value)
    assert "Error evaluating 'skipif' expression" in text
    assert "    pytest.fail('boom')" in text
    assert 'Failed: boom' in text
    assert 'Traceback' not in text

def test_cached_true_short_circuits_later_evaluation_errors():
    ev = sut.MarkEvaluator(make_item([make_mark('skipif', args=('1',), kwargs={'reason': 'cached'})], obj=sample_function), 'skipif')
    assert ev._istrue() is True
    ev.item = make_item([make_mark('skipif', args=('(',), kwargs={})], obj=sample_function)
    assert ev._istrue() is True
    assert ev.result is True
    assert ev.reason == 'cached'
    assert ev.expr == '1'

def test_cached_false_short_circuits_later_true_and_preserves_state():
    ev = sut.MarkEvaluator(make_item([make_mark('skipif', args=('0',), kwargs={'reason': 'first false'})], obj=sample_function), 'skipif')
    assert ev._istrue() is False
    assert ev.result is False
    assert ev.expr == '0'
    assert not hasattr(ev, 'reason')
    assert ev.getexplanation() == 'first false'
    ev.item = make_item([make_mark('skipif', args=('1',), kwargs={'reason': 'later true'})], obj=sample_function)
    assert ev._istrue() is False
    assert ev.expr == '0'
    assert not hasattr(ev, 'reason')
    assert ev.getexplanation() == 'first false'

def test_empty_get_marks_and_bool_false_for_other_name():
    assert sut.MarkEvaluator(make_item(), 'xfail')._get_marks() == []
    assert bool(sut.MarkEvaluator(make_item([make_mark('other')]), 'skipif')) is False
