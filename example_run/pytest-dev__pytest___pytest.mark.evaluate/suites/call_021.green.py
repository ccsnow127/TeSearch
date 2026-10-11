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

def test_compiled_eval_basic_cases():
    assert sut.compiled_eval('1 + 2 == 3', {}) is True
    assert sut.compiled_eval('value * 2', {'value': 5}) == 10
    assert sut.compiled_eval('config.value', {'config': DummyConfig('seen')}) == 'seen'
    assert sut.compiled_eval('len([1, 2, 3]) + min(5, 2)', {}) == 5
    assert sut.compiled_eval('sorted({3, 1, 2})', {}) == [1, 2, 3]
    assert sut.compiled_eval("'a' * 3", {}) == 'aaa'
    assert sut.compiled_eval("{'x': 1}['x']", {}) == 1

def test_compiled_eval_uses_provided_globals_exactly():
    assert sut.compiled_eval('A + B', {'A': 4, 'B': 9}) == 13
    assert sut.compiled_eval('flag and not other', {'flag': True, 'other': False}) is True

def test_bool_get_marks_and_wasvalid():
    marks = [make_mark(name='other'), make_mark(name='skipif'), make_mark(name='skipif')]
    ev = sut.MarkEvaluator(make_item(marks=marks), 'skipif')
    assert bool(ev) is True
    assert [m.name for m in ev._get_marks()] == ['skipif', 'skipif']
    assert ev.wasvalid() is True
    assert bool(sut.MarkEvaluator(make_item([make_mark(name='other')]), 'skipif')) is False

def test_bool_does_not_cache_marker_changes():
    item = make_item([make_mark()], obj=sample_function)
    ev = sut.MarkEvaluator(item, 'skipif')
    assert bool(ev) is True
    item._marks = [make_mark(name='other')]
    assert bool(ev) is False
    item._marks = [make_mark(), make_mark()]
    assert bool(ev) is True

def test_bool_true_when_matching_mark_exists_even_if_condition_false():
    ev = sut.MarkEvaluator(make_item([make_mark(args=(False,), kwargs={'reason': 'x'})]), 'skipif')
    assert bool(ev) is True

def test_getglobals_without_obj_has_standard_names():
    item = make_item()
    d = sut.MarkEvaluator(item, 'skipif')._getglobals()
    assert d['os'] is sut.os
    assert d['sys'] is sut.sys
    assert d['platform'] is sut.platform
    assert d['config'] is item.config
    assert 'SAMPLE_GLOBAL' not in d

def test_getglobals_with_obj_includes_and_overrides_globals():

    def f():
        return None
    sentinel_os = object()
    sentinel_platform = object()
    f.__globals__['SPECIAL_NAME'] = 7
    f.__globals__['os'] = sentinel_os
    f.__globals__['platform'] = sentinel_platform
    d = sut.MarkEvaluator(make_item(obj=f), 'skipif')._getglobals()
    assert d['SPECIAL_NAME'] == 7
    assert d['os'] is sentinel_os
    assert d['platform'] is sentinel_platform
    assert d['sys'] is sut.sys
    assert d['config'].value == 'cfg'

def test_getglobals_with_obj_can_override_config_name():

    def f():
        return None
    fake_config = object()
    f.__globals__['config'] = fake_config
    d = sut.MarkEvaluator(make_item(obj=f, config=DummyConfig('real')), 'skipif')._getglobals()
    assert d['config'] is fake_config

def test_invalidraise_none_single_tuple_and_falsey():
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
    ev._mark = make_mark(name='xfail', kwargs={'raises': ()})
    assert ev.invalidraise(ValueError()) is None

def test_invalidraise_uses_current_mark_set_by_istrue():
    mark = make_mark(name='xfail', args=('1',), kwargs={'reason': 'r', 'raises': LookupError})
    ev = sut.MarkEvaluator(make_item([mark], obj=sample_function), 'xfail')
    assert ev._istrue() is True
    assert ev.get('raises') is LookupError
    assert ev.invalidraise(IndexError()) is False
    assert ev.invalidraise(ValueError()) is True

def test_invalidraise_with_subclass_exception_and_tuple():
    ev = sut.MarkEvaluator(make_item(), 'xfail')
    ev._mark = make_mark(name='xfail', kwargs={'raises': (LookupError, RuntimeError)})
    assert ev.invalidraise(IndexError()) is False
    assert ev.invalidraise(KeyError()) is False
    assert ev.invalidraise(ValueError()) is True

def test_istrue_string_true_and_cached_true_short_circuit():
    mark = make_mark(args=('1 == 1',), kwargs={'reason': 'because'})
    ev = sut.MarkEvaluator(make_item([mark], obj=sample_function), 'skipif')
    assert ev._istrue() is True
    assert ev.result is True
    assert ev.expr == '1 == 1'
    assert ev.reason == 'because'
    assert ev.getexplanation() == 'because'
    ev.item = make_item([make_mark(args=('(',), kwargs={})], obj=sample_function)
    assert ev._istrue() is True
    assert ev.expr == '1 == 1'
    assert ev.reason == 'because'

def test_istrue_cached_false_short_circuits_and_explanation_uses_mark_reason():
    mark = make_mark(args=('0',), kwargs={'reason': 'no'})
    ev = sut.MarkEvaluator(make_item([mark], obj=sample_function), 'skipif')
    assert ev._istrue() is False
    assert ev.result is False
    ev.item = make_item([make_mark(args=('1',), kwargs={'reason': 'yes'})], obj=sample_function)
    assert ev._istrue() is False
    assert ev.expr == '0'
    assert not hasattr(ev, 'reason')
    assert ev.getexplanation() == 'no'

def test_istrue_false_paths_and_last_expr_across_marks():
    ev = sut.MarkEvaluator(make_item([make_mark(args=('1 == 2',), kwargs={'reason': 'nope'})], obj=sample_function), 'skipif')
    assert ev._istrue() is False
    assert ev.result is False
    assert ev.expr == '1 == 2'
    assert ev.getexplanation() == 'nope'
    marks = [make_mark(args=('0',), kwargs={'reason': 'first'}), make_mark(args=('False',), kwargs={'reason': 'second'})]
    ev2 = sut.MarkEvaluator(make_item(marks, obj=sample_function), 'skipif')
    assert ev2._istrue() is False
    assert ev2.result is False
    assert ev2.expr == 'False'
    assert ev2._mark is marks[-1]
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

def test_istrue_condition_kwarg_with_non_string_boolean_true():
    ev = sut.MarkEvaluator(make_item([make_mark(args=('unused',), kwargs={'condition': True, 'reason': 'kw-bool'})]), 'skipif')
    assert ev._istrue() is True
    assert ev.result is True
    assert ev.expr is True
    assert ev.reason == 'kw-bool'

def test_istrue_condition_kwarg_with_non_string_boolean_false():
    ev = sut.MarkEvaluator(make_item([make_mark(args=('unused',), kwargs={'condition': False, 'reason': 'kw-bool-false'})]), 'skipif')
    assert ev._istrue() is False
    assert ev.result is False
    assert ev.expr is False
    assert ev.getexplanation() == 'kw-bool-false'

def test_istrue_boolean_conditions_require_reason_and_truthy_boolean_with_reason():
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

def test_istrue_boolean_false_with_reason():
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
    ev = sut.MarkEvaluator(make_item([make_mark(args=('0', '3 > 2'), kwargs={'reason': 'second'})], obj=sample_function), 'skipif')
    assert ev._istrue() is True
    assert ev.result is True
    assert ev.expr == '3 > 2'
    assert ev.reason == 'second'
    marks = [make_mark(args=('0',), kwargs={'reason': 'first'}), make_mark(args=('1',), kwargs={'reason': 'second', 'custom': 9})]
    ev2 = sut.MarkEvaluator(make_item(marks, obj=sample_function), 'skipif')
    assert ev2._istrue() is True
    assert ev2.result is True
    assert ev2.expr == '1'
    assert ev2.reason == 'second'
    assert ev2._mark is marks[1]
    assert ev2.get('custom') == 9

def test_istrue_multiple_args_all_false_keeps_last_expr_and_mark():
    mark = make_mark(args=('0', '1 == 2', 'False'), kwargs={'reason': 'final reason'})
    ev = sut.MarkEvaluator(make_item([mark], obj=sample_function), 'skipif')
    assert ev._istrue() is False
    assert ev.result is False
    assert ev.expr == 'False'
    assert ev._mark is mark
    assert ev.getexplanation() == 'final reason'

def test_istrue_can_use_obj_globals_in_expression():

    def f():
        return None
    f.__globals__['SPECIAL_NAME'] = 7
    ev = sut.MarkEvaluator(make_item([make_mark(args=('SPECIAL_NAME == 7',), kwargs={'reason': 'global'})], obj=f), 'skipif')
    assert ev._istrue() is True
    assert ev.expr == 'SPECIAL_NAME == 7'
    assert ev.reason == 'global'

def test_istrue_expression_can_use_standard_globals_without_obj():
    expr = "sys is not None and os is not None and platform is not None and config.value == 'cfg'"
    ev = sut.MarkEvaluator(make_item([make_mark(args=(expr,), kwargs={'reason': 'std'})]), 'skipif')
    assert ev._istrue() is True
    assert ev.expr == expr
    assert ev.reason == 'std'

def test_istrue_empty_args_first_mark_stops_before_later_marks():
    marks = [make_mark(args=(), kwargs={'reason': 'empty-first'}), make_mark(args=('1',), kwargs={'reason': 'later'})]
    ev = sut.MarkEvaluator(make_item(marks, obj=sample_function), 'skipif')
    assert ev._istrue() is True
    assert ev.reason == 'empty-first'
    assert not hasattr(ev, 'expr')
    assert ev._mark is marks[0]

def test_istrue_condition_kwarg_ignores_args_expression_that_would_error():
    ev = sut.MarkEvaluator(make_item([make_mark(args=('(',), kwargs={'condition': '1', 'reason': 'chosen'})], obj=sample_function), 'skipif')
    assert ev._istrue() is True
    assert ev.expr == '1'
    assert ev.reason == 'chosen'

def test_istrue_returns_cached_result_attribute_when_present_true():
    ev = sut.MarkEvaluator(make_item([make_mark(args=('0',), kwargs={'reason': 'x'})]), 'skipif')
    ev.result = True
    ev.expr = 'cached'
    ev.item = make_item([], obj=sample_function)
    assert ev._istrue() is True
    assert ev.expr == 'cached'
    assert ev._marks is None

def test_istrue_returns_cached_result_attribute_when_present_false():
    ev = sut.MarkEvaluator(make_item([make_mark(args=('1',), kwargs={'reason': 'x'})]), 'skipif')
    ev.result = False
    ev.expr = 'cached-false'
    ev.item = make_item([make_mark(args=('1',), kwargs={'reason': 'y'})], obj=sample_function)
    assert ev._istrue() is False
    assert ev.expr == 'cached-false'

def test_get_and_getexplanation_variants():
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
    ev2 = sut.MarkEvaluator(make_item(), 'skipif')
    ev2.reason = ''
    ev2._mark = make_mark(kwargs={'reason': ''})
    ev2.expr = 'abc'
    assert ev2.getexplanation() == 'condition: abc'
    ev3 = sut.MarkEvaluator(make_item(), 'skipif')
    ev3._mark = make_mark(kwargs={'reason': ''})
    assert ev3.getexplanation() == ''
    ev4 = sut.MarkEvaluator(make_item(), 'skipif')
    ev4.expr = ''
    assert ev4.getexplanation() == 'condition: '
    ev5 = sut.MarkEvaluator(make_item(), 'skipif')
    ev5.reason = None
    ev5._mark = make_mark(kwargs={'reason': 'from-mark'})
    assert ev5.getexplanation() == 'from-mark'

def test_getexplanation_condition_prefix_exact_string():
    ev = sut.MarkEvaluator(make_item(), 'skipif')
    ev.expr = 'alpha'
    assert ev.getexplanation() == 'condition: alpha'
    assert ev.getexplanation() != 'condition^ alpha'

def test_get_returns_default_for_missing_attr_on_current_mark():
    ev = sut.MarkEvaluator(make_item(), 'skipif')
    ev._mark = make_mark(kwargs={'reason': 'r'})
    assert ev.get('missing', 123) == 123

def test_get_marks_filters_exact_name_independently():
    marks = [make_mark(name='skipif'), make_mark(name='xfail'), make_mark(name='skipif')]
    got = sut.MarkEvaluator(make_item(marks), 'xfail')._get_marks()
    assert len(got) == 1
    assert got[0].name == 'xfail'

def test_istrue_rewraps_non_syntax_test_outcome_and_sets_exc():
    mark = make_mark(args=("pytest.fail('boom')",), kwargs={})
    item = make_item([mark], obj=types.SimpleNamespace(__globals__={'pytest': pytest}))
    ev = sut.MarkEvaluator(item, 'skipif')
    with pytest.raises(sut.TEST_OUTCOME) as excinfo:
        ev.istrue()
    text = str(excinfo.value)
    assert ev.wasvalid() is False
    assert isinstance(ev.exc[1], BaseException)
    assert "Error evaluating 'skipif' expression" in text
    assert "    pytest.fail('boom')" in text
    assert 'Failed: boom' in text
    assert 'Traceback' not in text

def test_istrue_rewraps_syntax_error_with_exact_pointer_message():
    mark = make_mark(args=('(',), kwargs={})
    ev = sut.MarkEvaluator(make_item([mark], obj=sample_function), 'skipif')
    with pytest.raises(sut.TEST_OUTCOME) as excinfo:
        ev.istrue()
    text = str(excinfo.value)
    assert ev.wasvalid() is False
    assert isinstance(ev.exc[1], SyntaxError)
    assert ev.exc[1].offset is not None
    assert '\n    (\n' in text
    assert 'SyntaxError: invalid syntax' in text
    pointer_line = [line for line in text.splitlines() if '^' in line][0]
    assert pointer_line == ' ' * (ev.exc[1].offset + 4) + '^'
    assert pointer_line.endswith('^')
    assert pointer_line.count('^') == 1

def test_istrue_non_syntax_error_message_preserves_trailing_newline_from_format_exception_only():
    ev = sut.MarkEvaluator(make_item([make_mark(args=('unknown_name',), kwargs={})], obj=sample_function), 'skipif')
    with pytest.raises(sut.TEST_OUTCOME) as excinfo:
        ev.istrue()
    text = str(excinfo.value)
    assert ev.wasvalid() is False
    assert isinstance(ev.exc[1], NameError)
    assert text.startswith("Error evaluating 'skipif' expression\n    unknown_name\n")
    assert "NameError: name 'unknown_name' is not defined" in text
    assert text.endswith('is not defined\n')

def test_istrue_non_syntax_error_with_runtimeerror_exact_message():
    expr = "(_ for _ in ()).throw(RuntimeError('ouch'))"
    ev = sut.MarkEvaluator(make_item([make_mark(args=(expr,), kwargs={})], obj=sample_function), 'skipif')
    with pytest.raises(sut.TEST_OUTCOME) as excinfo:
        ev.istrue()
    assert str(excinfo.value) == "Error evaluating 'skipif' expression\n    (_ for _ in ()).throw(RuntimeError('ouch'))\nRuntimeError: ouch\n"

def test_istrue_failure_message_uses_mark_name_xfail():
    ev = sut.MarkEvaluator(make_item([make_mark(name='xfail', args=('unknown_name',), kwargs={})], obj=sample_function), 'xfail')
    with pytest.raises(sut.TEST_OUTCOME) as excinfo:
        ev.istrue()
    text = str(excinfo.value)
    assert text.startswith("Error evaluating 'xfail' expression\n    unknown_name\n")
    assert "NameError: name 'unknown_name' is not defined" in text

def test_istrue_sets_marks_list_after_evaluation():
    marks = [make_mark(args=('0',), kwargs={'reason': 'r1'}), make_mark(args=('1',), kwargs={'reason': 'r2'})]
    ev = sut.MarkEvaluator(make_item(marks, obj=sample_function), 'skipif')
    assert ev._marks is None
    assert ev._istrue() is True
    assert ev._marks == marks

def test_istrue_result_false_when_mark_name_does_not_match():
    item = make_item([make_mark(name='xfail', args=('1',), kwargs={'reason': 'x'})], obj=sample_function)
    ev = sut.MarkEvaluator(item, 'skipif')
    assert ev._istrue() is False
    assert bool(ev) is False

def test_istrue_current_mark_is_set_on_true_single_mark():
    mark = make_mark(args=('1',), kwargs={'reason': 'r', 'custom': 42})
    ev = sut.MarkEvaluator(make_item([mark], obj=sample_function), 'skipif')
    assert ev._istrue() is True
    assert ev._mark is mark
    assert ev.get('custom') == 42

def test_get_default_when_no_mark_even_with_default_arg():
    ev = sut.MarkEvaluator(make_item(), 'xfail')
    assert ev.get('raises', 'fallback') == 'fallback'

def test_wasvalid_false_after_syntax_and_non_syntax_failures():
    ev1 = sut.MarkEvaluator(make_item([make_mark(args=("pytest.fail('kapow')",), kwargs={})], obj=types.SimpleNamespace(__globals__={'pytest': pytest})), 'skipif')
    with pytest.raises(sut.TEST_OUTCOME):
        ev1.istrue()
    assert ev1.wasvalid() is False
    assert ev1.exc[0] is not None
    ev2 = sut.MarkEvaluator(make_item([make_mark(args=('(',), kwargs={})], obj=sample_function), 'skipif')
    with pytest.raises(sut.TEST_OUTCOME):
        ev2.istrue()
    assert ev2.wasvalid() is False
    assert isinstance(ev2.exc[1], SyntaxError)
