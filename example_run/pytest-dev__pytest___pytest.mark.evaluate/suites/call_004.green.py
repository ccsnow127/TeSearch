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

def test_compiled_eval_and_getglobals_and_bool_and_marks():
    assert sut.compiled_eval('1 + 2 == 3', {}) is True
    assert sut.compiled_eval('value * 2', {'value': 5}) == 10
    marks = [make_mark(name='skipif', args=(False,), kwargs={'reason': 'x'}), make_mark(name='xfail'), make_mark(name='skipif')]
    item = make_item(marks=marks, obj=sample_function)
    ev = sut.MarkEvaluator(item, 'skipif')
    assert bool(ev) is True
    got = ev._get_marks()
    assert len(got) == 2
    assert all((m.name == 'skipif' for m in got))
    d = ev._getglobals()
    assert d['os'] is sut.os
    assert d['sys'] is sut.sys
    assert d['platform'] is sut.platform
    assert d['config'] is item.config
    assert d['SAMPLE_GLOBAL'] == 123
    assert bool(sut.MarkEvaluator(make_item([make_mark(name='other')]), 'skipif')) is False
    assert sut.MarkEvaluator(make_item(), 'skipif').wasvalid() is True

@pytest.mark.parametrize('marks,obj,expected,result_attr,expr,reason,explanation', [([make_mark(name='skipif', args=('1 == 1',), kwargs={'reason': 'because'})], sample_function, True, True, '1 == 1', 'because', 'because'), ([make_mark(name='skipif', args=('1 == 2',), kwargs={'reason': 'nope'})], sample_function, False, False, '1 == 2', None, 'nope'), ([make_mark(name='skipif', args=('0',), kwargs={'condition': '2 > 1', 'reason': 'kwcond'})], sample_function, True, True, '2 > 1', 'kwcond', 'kwcond'), ([make_mark(name='skipif', args=(1,), kwargs={'reason': 'bool'})], None, True, True, 1, 'bool', 'bool'), ([make_mark(name='skipif', args=(), kwargs={'reason': 'empty'})], None, True, True, None, 'empty', 'empty'), ([make_mark(name='skipif', args=('0', '3 > 2'), kwargs={'reason': 'second'})], sample_function, True, True, '3 > 2', 'second', 'second'), ([make_mark(name='skipif', args=('config is not None',), kwargs={'reason': 'cfg'})], None, True, True, 'config is not None', 'cfg', 'cfg'), ([make_mark(name='skipif', args=('0',), kwargs={'reason': 'first'}), make_mark(name='skipif', args=('1',), kwargs={'reason': 'second'})], sample_function, True, True, '1', 'second', 'second'), ([make_mark(name='skipif', args=('0',), kwargs={'reason': 'first'}), make_mark(name='skipif', args=('False',), kwargs={'reason': 'second'})], sample_function, False, False, 'False', None, 'second'), ([make_mark(name='skipif', args=('SPECIAL_NAME == 7',), kwargs={'reason': 'global'})], None, True, True, 'SPECIAL_NAME == 7', 'global', 'global')])
def test_istrue_success_and_false_paths(marks, obj, expected, result_attr, expr, reason, explanation):
    if expr == 'SPECIAL_NAME == 7':

        def f():
            return None
        f.__globals__['SPECIAL_NAME'] = 7
        obj = f
    ev = sut.MarkEvaluator(make_item(marks, obj=obj), 'skipif')
    assert ev._istrue() is expected
    assert ev.result is result_attr
    if expr is not None:
        assert ev.expr == expr
    if reason is not None:
        assert ev.reason == reason
    assert ev.getexplanation() == explanation
    if expected is True:
        assert ev._istrue() is True
    if marks and expected is True:
        ev.item = make_item([])
        assert ev._istrue() is True

def test_boolean_reason_requirement_get_getexplanation_and_invalidraise():
    mark = make_mark(name='skipif', args=(True,), kwargs={})
    ev = sut.MarkEvaluator(make_item([mark]), 'skipif')
    with pytest.raises(sut.TEST_OUTCOME) as excinfo:
        ev._istrue()
    assert 'you need to specify reason=STRING when using booleans as conditions.' in str(excinfo.value)
    ev2 = sut.MarkEvaluator(make_item(), 'skipif')
    assert ev2.get('reason', 'default') == 'default'
    ev2.expr = 'x > 1'
    assert ev2.getexplanation() == 'condition: x > 1'
    ev3 = sut.MarkEvaluator(make_item(), 'skipif')
    ev3.reason = 'attr reason'
    ev3._mark = make_mark(name='skipif', kwargs={'reason': 'mark reason'})
    assert ev3.getexplanation() == 'attr reason'
    ev4 = sut.MarkEvaluator(make_item(), 'skipif')
    ev4._mark = make_mark(name='skipif', kwargs={'reason': 'mark reason'})
    assert ev4.getexplanation() == 'mark reason'
    ev5 = sut.MarkEvaluator(make_item(), 'skipif')
    assert ev5.getexplanation() == ''
    ev6 = sut.MarkEvaluator(make_item(), 'xfail')
    ev6._mark = make_mark(name='xfail', kwargs={})
    assert ev6.invalidraise(ValueError()) is None
    ev6._mark = make_mark(name='xfail', kwargs={'raises': ValueError})
    assert ev6.invalidraise(ValueError()) is False
    assert ev6.invalidraise(TypeError()) is True
    ev7 = sut.MarkEvaluator(make_item(), 'skipif')
    ev7._mark = make_mark(name='skipif', kwargs={'reason': 'abc'})
    assert ev7.get('reason') == 'abc'

def test_istrue_sets_current_mark_and_cached_result_attribute_branch():
    mark = make_mark(name='skipif', args=('1',), kwargs={'reason': 'r', 'custom': 42})
    ev = sut.MarkEvaluator(make_item([mark], obj=sample_function), 'skipif')
    assert ev._istrue() is True
    assert ev.get('custom') == 42
    ev.result = False
    assert ev._istrue() is False

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
