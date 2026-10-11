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

def test_compiled_eval_basic_and_namespace_identity():
    cfg = DummyConfig('special')
    ns = {'config': cfg, 'value': 4}
    assert sut.compiled_eval('1 + 2 == 3', {}) is True
    assert sut.compiled_eval('value * 2', {'value': 5}) == 10
    assert sut.compiled_eval('config.value', {'config': DummyConfig('seen')}) == 'seen'
    assert sut.compiled_eval('sorted({3, 1, 2})', {}) == [1, 2, 3]
    assert sut.compiled_eval('len([1, 2, 3]) + min(5, 2)', {}) == 5
    assert sut.compiled_eval("'a' * 3", {}) == 'aaa'
    assert sut.compiled_eval('tuple(reversed([1, 2]))', {}) == (2, 1)
    assert sut.compiled_eval('config is config and value + 1', ns) == 5
    assert sut.compiled_eval('config.value.upper()', ns) == 'SPECIAL'

def test_bool_get_marks_and_filtering_behaviors():
    marks = [make_mark(name='other'), make_mark(name='skipif'), make_mark(name='skipif')]
    item = make_item(marks=marks)
    ev = sut.MarkEvaluator(item, 'skipif')
    assert bool(ev) is True
    got = ev._get_marks()
    assert len(got) == 2
    assert [m.name for m in got] == ['skipif', 'skipif']
    assert ev.wasvalid() is True
    assert bool(sut.MarkEvaluator(make_item([make_mark(name='other')]), 'skipif')) is False
    ev2 = sut.MarkEvaluator(make_item([make_mark(name='skipif'), make_mark(name='xfail'), make_mark(name='skipif')]), 'xfail')
    got2 = ev2._get_marks()
    assert len(got2) == 1
    assert got2[0].name == 'xfail'
    item2 = make_item([make_mark()], obj=sample_function)
    ev3 = sut.MarkEvaluator(item2, 'skipif')
    assert bool(ev3) is True
    item2._marks = [make_mark(name='other')]
    assert bool(ev3) is False
    item2._marks = [make_mark(), make_mark()]
    assert bool(ev3) is True
    false_condition_item = make_item([make_mark(name='skipif', args=(False,), kwargs={'reason': 'x'})])
    assert bool(sut.MarkEvaluator(false_condition_item, 'skipif')) is True

def test_getglobals_without_obj_and_with_obj_overrides():
    ev = sut.MarkEvaluator(make_item(), 'skipif')
    d = ev._getglobals()
    assert d['os'] is sut.os
    assert d['sys'] is sut.sys
    assert d['platform'] is sut.platform
    assert d['config'] is ev.item.config
    assert 'SAMPLE_GLOBAL' not in d
    assert d['config'].value == 'cfg'

    def f():
        return None
    sentinel_os = object()
    sentinel_platform = object()
    custom_config = DummyConfig('from_obj_globals')
    f.__globals__['SPECIAL_NAME'] = 7
    f.__globals__['os'] = sentinel_os
    f.__globals__['platform'] = sentinel_platform
    f.__globals__['config'] = custom_config
    item = make_item([make_mark(args=("SPECIAL_NAME == 7 and config.value == 'from_obj_globals'",), kwargs={'reason': 'global'})], obj=f, config=DummyConfig('item_cfg'))
    ev2 = sut.MarkEvaluator(item, 'skipif')
    d2 = ev2._getglobals()
    assert d2['SPECIAL_NAME'] == 7
    assert d2['os'] is sentinel_os
    assert d2['platform'] is sentinel_platform
    assert d2['sys'] is sut.sys
    assert d2['config'] is custom_config
    assert d2['config'].value == 'from_obj_globals'
    assert ev2._istrue() is True
    assert ev2.expr == "SPECIAL_NAME == 7 and config.value == 'from_obj_globals'"
    assert ev2.reason == 'global'

def test_istrue_string_true_and_cached_result_branch():
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
    cached = sut.MarkEvaluator(make_item([make_mark(args=('0',), kwargs={'reason': 'x'})]), 'skipif')
    cached.result = True
    cached.expr = 'cached'
    cached.item = make_item([], obj=sample_function)
    assert cached._istrue() is True
    assert cached.expr == 'cached'
    assert cached.getexplanation() == 'condition: cached'

def test_istrue_false_paths_and_last_expr_explanation():
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
    mark3 = make_mark(args=('0', '1 == 2', 'False'), kwargs={'reason': 'final reason'})
    ev3 = sut.MarkEvaluator(make_item([mark3], obj=sample_function), 'skipif')
    assert ev3._istrue() is False
    assert ev3.result is False
    assert ev3.expr == 'False'
    assert ev3._mark is mark3
    assert ev3.getexplanation() == 'final reason'

def test_istrue_condition_kwarg_true_false_and_ignores_args():
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
    mark = make_mark(args=('(',), kwargs={'condition': '1', 'reason': 'chosen'})
    ev3 = sut.MarkEvaluator(make_item([mark], obj=sample_function), 'skipif')
    assert ev3._istrue() is True
    assert ev3.result is True
    assert ev3.expr == '1'
    assert ev3.reason == 'chosen'

def test_istrue_boolean_true_requires_reason_and_good_true_case():
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

def test_istrue_boolean_false_with_reason_and_explanation():
    ev = sut.MarkEvaluator(make_item([make_mark(args=(0,), kwargs={'reason': 'zero'})]), 'skipif')
    assert ev._istrue() is False
    assert ev.result is False
    assert ev.expr == 0
    assert not hasattr(ev, 'reason')
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

def test_istrue_empty_args_first_mark_stops_before_later_marks():
    marks = [make_mark(args=(), kwargs={'reason': 'empty-first'}), make_mark(args=('1',), kwargs={'reason': 'later'})]
    ev = sut.MarkEvaluator(make_item(marks, obj=sample_function), 'skipif')
    assert ev._istrue() is True
    assert ev.reason == 'empty-first'
    assert not hasattr(ev, 'expr')
    assert ev._mark is marks[0]

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

def test_get_and_getexplanation_combinations():
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

def test_getexplanation_prefers_expr_when_reason_missing_or_empty():
    ev = sut.MarkEvaluator(make_item(), 'skipif')
    ev.expr = 'abc'
    assert ev.getexplanation() == 'condition: abc'
    ev.reason = ''
    ev._mark = make_mark(kwargs={'reason': ''})
    assert ev.getexplanation() == 'condition: abc'
    ev2 = sut.MarkEvaluator(make_item(), 'skipif')
    ev2._mark = make_mark(kwargs={'reason': ''})
    assert ev2.getexplanation() == ''

def test_invalidraise_none_single_tuple_and_current_mark():
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
    mark = make_mark(name='xfail', args=('1',), kwargs={'reason': 'r', 'raises': LookupError})
    ev2 = sut.MarkEvaluator(make_item([mark], obj=sample_function), 'xfail')
    assert ev2._istrue() is True
    assert ev2.get('raises') is LookupError
    assert ev2.invalidraise(IndexError()) is False
    assert ev2.invalidraise(ValueError()) is True

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

def test_syntax_error_message_has_only_pointer_and_error_lines_after_expression():
    ev = sut.MarkEvaluator(make_item([make_mark(args=('(',), kwargs={})], obj=sample_function), 'skipif')
    with pytest.raises(sut.TEST_OUTCOME) as excinfo:
        ev.istrue()
    assert str(excinfo.value).splitlines() == ["Error evaluating 'skipif' expression", '    (', '      ^', 'SyntaxError: invalid syntax']

def test_non_syntax_error_uses_format_exception_only_for_name_error():
    ev = sut.MarkEvaluator(make_item([make_mark(args=('unknown_name',), kwargs={})], obj=sample_function), 'skipif')
    with pytest.raises(sut.TEST_OUTCOME) as excinfo:
        ev.istrue()
    assert ev.wasvalid() is False
    assert isinstance(ev.exc[1], NameError)
    text = str(excinfo.value)
    assert text.startswith("Error evaluating 'skipif' expression\n    unknown_name\n")
    assert "NameError: name 'unknown_name' is not defined" in text
    assert 'SyntaxError: invalid syntax' not in text

@pytest.mark.parametrize('expr, expected', [('0', False), ('1', True), ('1 == 2', False), ('3 > 2', True)])
def test_parametrized_string_expression_truth_values(expr, expected):
    ev = sut.MarkEvaluator(make_item([make_mark(args=(expr,), kwargs={'reason': 'r'})], obj=sample_function), 'skipif')
    assert ev._istrue() is expected
    assert ev.result is expected
    assert ev.expr == expr

@pytest.mark.parametrize('raises_spec, exc, expected', [(ValueError, ValueError(), False), (ValueError, TypeError(), True), ((ValueError, TypeError), RuntimeError(), True)])
def test_parametrized_invalidraise_cases(raises_spec, exc, expected):
    ev = sut.MarkEvaluator(make_item(), 'xfail')
    ev._mark = make_mark(name='xfail', kwargs={'raises': raises_spec})
    assert ev.invalidraise(exc) is expected

def test_get_returns_default_when_no_current_mark():
    ev = sut.MarkEvaluator(make_item(), 'skipif')
    assert ev.get('missing') is None
    assert ev.get('missing', 99) == 99

def test_wasvalid_false_after_name_error_via_istrue():
    ev = sut.MarkEvaluator(make_item([make_mark(args=('unknown_name',), kwargs={})], obj=sample_function), 'skipif')
    with pytest.raises(sut.TEST_OUTCOME):
        ev.istrue()
    assert ev.wasvalid() is False
