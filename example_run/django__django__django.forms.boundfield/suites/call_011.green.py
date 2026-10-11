import pytest
from django.conf import settings
if not settings.configured:
    settings.configure(USE_I18N=False, SECRET_KEY='test', FORM_RENDERER='django.forms.renderers.DjangoTemplates', TEMPLATES=[{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'APP_DIRS': True}])
import django
django.setup()
from django.core.exceptions import ValidationError
from django.forms.boundfield import BoundField, BoundWidget
from django.forms.widgets import HiddenInput
from django.utils.safestring import SafeString

class DummyErrorList(list):
    pass

class TemplateRenderer:

    def render(self, template_name, context, request=None):
        widget = context['widget']
        attrs = widget.get('attrs', {})
        attr_text = ''.join((f' {k}="{v}"' for k, v in attrs.items()))
        value = widget.get('value')
        name = widget.get('name')
        if template_name.endswith('/input.html'):
            input_type = widget.get('type', 'text')
            value_attr = '' if value in (None, '') else f' value="{value}"'
            return f'<input type="{input_type}" name="{name}"{value_attr}{attr_text}>'
        if template_name.endswith('/textarea.html'):
            return f'<textarea name="{name}"{attr_text}>\n{value}</textarea>'
        return f'{template_name}:{name}:{value}:{attrs}'

class DummyWidget:
    is_hidden = False
    template_name = 'parent-template'

    def __init__(self, attrs=None, use_required=True, id_suffix='-label', subwidgets_data=None):
        self.attrs = attrs or {}
        self.is_localized = False
        self._use_required = use_required
        self.id_suffix = id_suffix
        self.subwidgets_data = subwidgets_data
        self.render_calls = []
        self.subwidgets_calls = []
        self.rendered_templates = []

    def render(self, name, value, attrs=None, renderer=None):
        call = {'name': name, 'value': value, 'attrs': attrs, 'renderer': renderer}
        self.render_calls.append(call)
        return f'render:{name}:{value}:{attrs}'

    def subwidgets(self, name, value, attrs=None):
        self.subwidgets_calls.append((name, value, attrs))
        return self.subwidgets_data or [{'attrs': {'id': 'sub1'}, 'label': 'One'}, {'attrs': {'id': 'sub2'}, 'label': 'Two', 'template_name': 'child-template'}]

    def use_required_attribute(self, initial):
        return self._use_required

    def id_for_label(self, id_):
        if not id_:
            return ''
        return f'{id_}{self.id_suffix}'

    def _render(self, template_name, context, renderer):
        self.rendered_templates.append((template_name, context, renderer))
        wrap = context['widget']['wrap_label']
        label = context['widget'].get('label')
        return f'tmpl:{template_name}:wrap={wrap}:label={label}'

class HiddenWidget(DummyWidget):
    is_hidden = True
    template_name = 'hidden-template'

class DummyField:

    def __init__(self, widget=None, label='Field Label', help_text='help', show_hidden_initial=False, localize=False, required=False, disabled=False, label_suffix=None, hidden_widget_factory=None, bound_data_func=None, prepare_value_func=None, to_python_func=None, has_changed_func=None):
        self.widget = widget or DummyWidget()
        self.label = label
        self.help_text = help_text
        self.show_hidden_initial = show_hidden_initial
        self.localize = localize
        self.required = required
        self.disabled = disabled
        self.label_suffix = label_suffix
        self._hidden_widget_factory = hidden_widget_factory or (lambda: HiddenWidget())
        self._bound_data_func = bound_data_func
        self._prepare_value_func = prepare_value_func
        self._to_python_func = to_python_func
        self._has_changed_func = has_changed_func
        self.bound_data_calls = []
        self.prepare_value_calls = []
        self.to_python_calls = []
        self.has_changed_calls = []

    def hidden_widget(self):
        return self._hidden_widget_factory()

    def bound_data(self, data, initial):
        self.bound_data_calls.append((data, initial))
        if self._bound_data_func:
            return self._bound_data_func(data, initial)
        return f'bound({data}|{initial})'

    def prepare_value(self, data):
        self.prepare_value_calls.append(data)
        if self._prepare_value_func:
            return self._prepare_value_func(data)
        return f'prepared({data})'

    def to_python(self, value):
        self.to_python_calls.append(value)
        if self._to_python_func:
            return self._to_python_func(value)
        if value == 'RAISE':
            raise ValidationError('bad')
        return f'python({value})'

    def has_changed(self, initial, data):
        self.has_changed_calls.append((initial, data))
        if self._has_changed_func:
            return self._has_changed_func(initial, data)
        return initial != data

class DummyForm:
    required_css_class = 'required'
    error_css_class = 'error'

    def __init__(self, *, auto_id='id_%s', is_bound=False, label_suffix=':', use_required_attribute=True, errors=None, renderer=None, initials=None, data_map=None):
        self.auto_id = auto_id
        self.is_bound = is_bound
        self.label_suffix = label_suffix
        self.use_required_attribute = use_required_attribute
        self.errors = errors or {}
        self.renderer = renderer or TemplateRenderer()
        self._initials = initials or {}
        self._data_map = data_map or {}
        self.widget_data_calls = []
        self.initial_calls = []
        self.error_class_calls = 0

    def add_prefix(self, name):
        return f'prefix-{name}'

    def add_initial_prefix(self, name):
        return f'initial-{name}'

    def error_class(self):
        self.error_class_calls += 1
        return DummyErrorList()

    def _widget_data_value(self, widget, html_name):
        self.widget_data_calls.append((widget, html_name))
        return self._data_map.get(html_name)

    def get_initial_for_field(self, field, name):
        self.initial_calls.append((field, name))
        return self._initials.get(name, f'initial-{name}')

class NoCssForm(DummyForm):

    @property
    def required_css_class(self):
        raise AttributeError('required_css_class')

    @property
    def error_css_class(self):
        raise AttributeError('error_css_class')

def make_boundfield(**kwargs):
    form = kwargs.pop('form', DummyForm())
    field = kwargs.pop('field', DummyField())
    name = kwargs.pop('name', 'first_name')
    return (BoundField(form, field, name), form, field)

def test_init_sets_names_default_label_and_help_text():
    bf, form, field = make_boundfield()
    assert bf.form is form
    assert bf.field is field
    assert bf.name == 'first_name'
    assert bf.html_name == 'prefix-first_name'
    assert bf.auto_id == 'id_prefix-first_name'
    assert bf.html_initial_name == 'initial-first_name'
    assert bf.html_initial_id == 'initial-id_prefix-first_name'
    assert bf.label == 'Field Label'
    assert bf.help_text == 'help'

def test_init_uses_pretty_name_when_label_is_none():
    bf, _, _ = make_boundfield(field=DummyField(label=None), name='user_name')
    assert bf.label == 'User name'

def test_init_uses_empty_help_text_when_field_help_text_falsey():
    bf, _, _ = make_boundfield(field=DummyField(help_text=None))
    assert bf.help_text == ''

def test_str_renders_widget_only_by_default():
    bf, _, field = make_boundfield()
    assert str(bf) == "render:prefix-first_name:prepared(initial-first_name):{'id': 'id_prefix-first_name'}"
    assert len(field.widget.render_calls) == 1

def test_str_renders_widget_and_hidden_initial_when_enabled():
    hidden = HiddenWidget()
    field = DummyField(show_hidden_initial=True, hidden_widget_factory=lambda: hidden)
    bf, _, _ = make_boundfield(field=field)
    result = str(bf)
    assert result == "render:prefix-first_name:prepared(initial-first_name):{'id': 'id_prefix-first_name'}render:initial-first_name:prepared(initial-first_name):{'id': 'initial-id_prefix-first_name'}"
    assert len(hidden.render_calls) == 1

def test_boundfield_str_is_safe_string_due_to_html_safe_decorator():
    bf, _, _ = make_boundfield()
    result = str(bf)
    assert isinstance(result, SafeString)

def test_boundfield_class_exposes_html_safe_str_method():
    assert '__html__' in BoundField.__dict__
    bf, _, _ = make_boundfield()
    assert bf.__html__() == str(bf)

def test_subwidgets_cached_and_wraps_each_result_in_boundwidget():
    bf, _, field = make_boundfield()
    first = bf.subwidgets
    second = bf.subwidgets
    assert first is second
    assert len(first) == 2
    assert all((isinstance(w, BoundWidget) for w in first))
    assert [w.choice_label for w in first] == ['One', 'Two']
    assert field.widget.subwidgets_calls == [('prefix-first_name', 'prepared(initial-first_name)', {'id': 'id_prefix-first_name'})]

def test_subwidgets_uses_widget_attr_id_and_builds_required_disabled_attrs():
    widget = DummyWidget(attrs={'id': 'custom-id'})
    bf, _, _ = make_boundfield(field=DummyField(widget=widget, required=True, disabled=True))
    _ = bf.subwidgets
    assert widget.subwidgets_calls[0][2] == {'id': 'custom-id', 'required': True, 'disabled': True}

def test_subwidgets_without_any_id_passes_empty_attrs():
    bf, _, field = make_boundfield(form=DummyForm(auto_id=''), field=DummyField(widget=DummyWidget()))
    _ = bf.subwidgets
    assert field.widget.subwidgets_calls == [('prefix-first_name', 'prepared(initial-first_name)', {})]

def test_subwidgets_respects_custom_subwidget_data_and_renderer():
    renderer = object()
    form = DummyForm(renderer=renderer)
    widget = DummyWidget(subwidgets_data=[{'attrs': {'id': 'a'}, 'label': 'A'}])
    bf, _, _ = make_boundfield(form=form, field=DummyField(widget=widget))
    assert len(bf.subwidgets) == 1
    assert bf.subwidgets[0].renderer is renderer
    assert bf.subwidgets[0].choice_label == 'A'

def test_boundfield_bool_iter_len_getitem_and_slice():
    bf, _, _ = make_boundfield()
    assert bool(bf) is True
    assert len(bf) == 2
    assert list(iter(bf)) == bf.subwidgets
    assert bf[0] is bf.subwidgets[0]
    assert bf[:1] == bf.subwidgets[:1]

def test_getitem_rejects_non_integer_or_slice():
    bf, _, _ = make_boundfield()
    with pytest.raises(TypeError) as exc:
        _ = bf['x']
    assert str(exc.value) == 'BoundField indices must be integers or slices, not str.'

def test_errors_returns_existing_error_list_and_still_calls_error_class_once():
    existing = DummyErrorList(['bad'])
    form = DummyForm(errors={'first_name': existing})
    bf, _, _ = make_boundfield(form=form)
    assert bf.errors is existing
    assert form.error_class_calls == 1

def test_errors_returns_new_error_class_when_missing():
    bf, form, _ = make_boundfield(form=DummyForm())
    errs = bf.errors
    assert isinstance(errs, DummyErrorList)
    assert errs == []
    assert form.error_class_calls == 1

def test_as_widget_uses_default_widget_sets_localized_and_auto_id():
    widget = DummyWidget()
    bf, form, _ = make_boundfield(field=DummyField(widget=widget, localize=True))
    result = bf.as_widget()
    assert widget.is_localized is True
    assert result == "render:prefix-first_name:prepared(initial-first_name):{'id': 'id_prefix-first_name'}"
    assert widget.render_calls[-1]['renderer'] is form.renderer

def test_as_widget_respects_only_initial_and_existing_widget_id():
    widget = DummyWidget(attrs={'id': 'already'})
    bf, _, _ = make_boundfield(field=DummyField(widget=widget))
    bf.as_widget(only_initial=True)
    call = widget.render_calls[-1]
    assert call['name'] == 'initial-first_name'
    assert call['attrs'] == {}

def test_as_widget_merges_attrs_with_required_and_disabled():
    bf, _, field = make_boundfield(field=DummyField(required=True, disabled=True))
    bf.as_widget(attrs={'class': 'x'})
    assert field.widget.render_calls[-1]['attrs'] == {'class': 'x', 'required': True, 'disabled': True, 'id': 'id_prefix-first_name'}

def test_as_widget_with_auto_id_false_and_passed_attrs_keeps_only_passed_attrs():
    bf, _, field = make_boundfield(form=DummyForm(auto_id=False), field=DummyField())
    result = bf.as_widget(attrs={'class': 'x'})
    assert result == "render:prefix-first_name:prepared(initial-first_name):{'class': 'x'}"
    assert field.widget.render_calls[-1]['attrs'] == {'class': 'x'}

def test_as_widget_only_initial_uses_html_initial_id_when_widget_has_no_id():
    bf, _, field = make_boundfield()
    result = bf.as_widget(only_initial=True)
    assert result == "render:initial-first_name:prepared(initial-first_name):{'id': 'initial-id_prefix-first_name'}"
    assert field.widget.render_calls[-1]['name'] == 'initial-first_name'

def test_as_widget_uses_supplied_widget_instead_of_field_widget():
    supplied = DummyWidget()
    field_widget = DummyWidget()
    bf, form, _ = make_boundfield(field=DummyField(widget=field_widget))
    result = bf.as_widget(widget=supplied, attrs={'data-x': '1'})
    assert result == "render:prefix-first_name:prepared(initial-first_name):{'data-x': '1', 'id': 'id_prefix-first_name'}"
    assert field_widget.render_calls == []
    assert supplied.render_calls[-1]['renderer'] is form.renderer

def test_as_textarea_uses_textarea_widget():
    bf, _, field = make_boundfield()
    result = bf.as_textarea()
    assert result == '<textarea name="prefix-first_name" cols="40" rows="10" id="id_prefix-first_name">\nprepared(initial-first_name)</textarea>'
    assert field.widget.render_calls == []

def test_as_textarea_with_custom_attrs():
    bf, _, _ = make_boundfield()
    result = bf.as_textarea(attrs={'class': 'memo'})
    assert result == '<textarea name="prefix-first_name" cols="40" rows="10" class="memo" id="id_prefix-first_name">\nprepared(initial-first_name)</textarea>'

def test_as_hidden_uses_hidden_widget():
    hidden = HiddenWidget()
    bf, _, _ = make_boundfield(field=DummyField(hidden_widget_factory=lambda: hidden))
    result = bf.as_hidden()
    assert result == "render:prefix-first_name:prepared(initial-first_name):{'id': 'id_prefix-first_name'}"
    assert hidden.render_calls[-1]['name'] == 'prefix-first_name'

def test_data_property_reads_form_widget_data():
    form = DummyForm(data_map={'prefix-first_name': 'submitted'})
    bf, _, field = make_boundfield(form=form, field=DummyField(widget=DummyWidget()))
    assert bf.data == 'submitted'
    assert form.widget_data_calls == [(field.widget, 'prefix-first_name')]

def test_data_property_returns_none_when_missing():
    bf, form, field = make_boundfield(form=DummyForm(data_map={}), field=DummyField(widget=DummyWidget()))
    assert bf.data is None
    assert form.widget_data_calls == [(field.widget, 'prefix-first_name')]

def test_value_uses_initial_when_unbound():
    bf, _, field = make_boundfield(form=DummyForm(is_bound=False))
    assert bf.value() == 'prepared(initial-first_name)'
    assert field.bound_data_calls == []
    assert field.prepare_value_calls == ['initial-first_name']

def test_value_uses_bound_data_when_form_is_bound():
    form = DummyForm(is_bound=True, data_map={'prefix-first_name': 'posted'})
    field = DummyField()
    bf, _, _ = make_boundfield(form=form, field=field)
    assert bf.value() == 'prepared(bound(posted|initial-first_name))'
    assert field.bound_data_calls == [('posted', 'initial-first_name')]

def test_value_bound_uses_none_data_exactly():
    form = DummyForm(is_bound=True, data_map={})
    field = DummyField()
    bf, _, _ = make_boundfield(form=form, field=field)
    assert bf.value() == 'prepared(bound(None|initial-first_name))'
    assert field.bound_data_calls == [(None, 'initial-first_name')]

def test_value_with_custom_prepare_value_function():
    form = DummyForm(is_bound=False, initials={'first_name': 3})
    field = DummyField(prepare_value_func=lambda data: data * 10)
    bf, _, _ = make_boundfield(form=form, field=field)
    assert bf.value() == 30
    assert field.prepare_value_calls == [3]

def test_has_changed_without_hidden_initial_uses_initial_and_data():
    form = DummyForm(data_map={'prefix-first_name': 'x'})
    field = DummyField()
    bf, _, _ = make_boundfield(form=form, field=field)
    assert bf._has_changed() is True
    assert field.has_changed_calls == [('initial-first_name', 'x')]

def test_has_changed_with_hidden_initial_converts_initial_value():
    form = DummyForm(data_map={'initial-first_name': 'raw', 'prefix-first_name': 'posted'})
    field = DummyField(show_hidden_initial=True)
    bf, _, _ = make_boundfield(form=form, field=field)
    assert bf._has_changed() is True
    assert field.to_python_calls == ['raw']
    assert field.has_changed_calls == [('python(raw)', 'posted')]

def test_has_changed_with_hidden_initial_validation_error_returns_true():
    form = DummyForm(data_map={'initial-first_name': 'RAISE', 'prefix-first_name': 'posted'})
    bf, _, field = make_boundfield(form=form, field=DummyField(show_hidden_initial=True))
    assert bf._has_changed() is True
    assert field.has_changed_calls == []

def test_has_changed_without_hidden_initial_can_return_false():
    form = DummyForm(data_map={'prefix-first_name': 'same'})
    field = DummyField(has_changed_func=lambda initial, data: False)
    bf, _, _ = make_boundfield(form=form, field=field)
    assert bf._has_changed() is False
    assert field.has_changed_calls == [('initial-first_name', 'same')]

def test_has_changed_with_hidden_initial_can_return_false_after_conversion():
    form = DummyForm(data_map={'initial-first_name': 'raw', 'prefix-first_name': 'posted'})
    field = DummyField(show_hidden_initial=True, to_python_func=lambda value: 'posted', has_changed_func=lambda initial, data: False)
    bf, _, _ = make_boundfield(form=form, field=field)
    assert bf._has_changed() is False
    assert field.to_python_calls == ['raw']
    assert field.has_changed_calls == [('posted', 'posted')]

def test_label_tag_builds_label_with_defaults_required_class_and_suffix():
    widget = DummyWidget()
    bf, _, _ = make_boundfield(field=DummyField(widget=widget, required=True))
    result = bf.label_tag()
    assert result == '<label class="required" for="id_prefix-first_name-label">Field Label:</label>'
    assert isinstance(result, SafeString)

def test_label_tag_uses_custom_contents_attrs_and_label_suffix_override():
    bf, _, _ = make_boundfield()
    assert bf.label_tag(contents='Name', attrs={'class': 'c'}, label_suffix='!') == '<label class="c" for="id_prefix-first_name-label">Name!</label>'

def test_label_tag_without_id_returns_escaped_contents_only():
    bf, _, _ = make_boundfield(form=DummyForm(auto_id=''))
    assert bf.label_tag(contents='<b>X</b>') == '&lt;b&gt;X&lt;/b&gt;:'

def test_label_tag_with_empty_contents_uses_field_label():
    bf, _, _ = make_boundfield()
    assert bf.label_tag(contents='') == '<label for="id_prefix-first_name-label">Field Label:</label>'

def test_label_tag_with_none_label_suffix_uses_empty_when_form_suffix_empty():
    bf, _, _ = make_boundfield(form=DummyForm(label_suffix=''))
    assert bf.label_tag(contents='Name') == '<label for="id_prefix-first_name-label">Name</label>'

def test_label_tag_when_widget_id_for_label_empty_returns_label_without_for():
    widget = DummyWidget()
    widget.id_for_label = lambda id_: ''
    bf, _, _ = make_boundfield(field=DummyField(widget=widget))
    assert bf.label_tag(contents='Name') == '<label>Name:</label>'

def test_label_tag_appends_required_class_to_existing_class():
    bf, _, _ = make_boundfield(field=DummyField(required=True))
    assert bf.label_tag(contents='Req', attrs={'class': 'a b', 'data-x': '1'}) == '<label class="a b required" data-x="1" for="id_prefix-first_name-label">Req:</label>'

def test_label_tag_does_not_append_suffix_when_contents_empty_and_label_empty():
    bf, _, _ = make_boundfield(field=DummyField(label=''))
    assert bf.label_tag(contents='') == '<label for="id_prefix-first_name-label"></label>'

def test_label_tag_uses_form_suffix_when_field_suffix_is_none():
    bf, _, _ = make_boundfield(form=DummyForm(label_suffix='>'), field=DummyField(label_suffix=None))
    assert bf.label_tag(contents='Go') == '<label for="id_prefix-first_name-label">Go&gt;</label>'

def test_css_classes_accepts_string_and_adds_error_and_required_classes():
    form = DummyForm(errors={'first_name': DummyErrorList(['e'])})
    bf, _, _ = make_boundfield(form=form, field=DummyField(required=True))
    assert set(bf.css_classes('extra one').split()) == {'extra', 'one', 'error', 'required'}

def test_css_classes_with_none_and_without_errors():
    bf, _, _ = make_boundfield(form=DummyForm(errors={}), field=DummyField(required=False))
    assert bf.css_classes() == ''

def test_css_classes_with_iterable_extra_classes_and_missing_form_attrs():
    bf, _, _ = make_boundfield(form=NoCssForm(), field=DummyField(required=True))
    assert set(bf.css_classes(['a', 'b']).split()) == {'a', 'b'}

def test_css_classes_deduplicates_classes():
    form = DummyForm(errors={'first_name': DummyErrorList(['e'])})
    bf, _, _ = make_boundfield(form=form, field=DummyField(required=True))
    assert set(bf.css_classes('required extra error extra').split()) == {'required', 'extra', 'error'}

def test_css_classes_accepts_tuple_extra_classes():
    bf, _, _ = make_boundfield(form=DummyForm(errors={}), field=DummyField(required=False))
    assert set(bf.css_classes(('x', 'y')).split()) == {'x', 'y'}

def test_is_hidden_property_reflects_widget():
    assert make_boundfield(field=DummyField(widget=DummyWidget()))[0].is_hidden is False
    assert make_boundfield(field=DummyField(widget=HiddenWidget()))[0].is_hidden is True

def test_auto_id_variants():
    assert make_boundfield(form=DummyForm(auto_id='id_%s'))[0].auto_id == 'id_prefix-first_name'
    assert make_boundfield(form=DummyForm(auto_id=True))[0].auto_id == 'prefix-first_name'
    assert make_boundfield(form=DummyForm(auto_id=False))[0].auto_id == ''

def test_auto_id_with_non_format_string_returns_html_name():
    assert make_boundfield(form=DummyForm(auto_id='plain-id'))[0].auto_id == 'prefix-first_name'

def test_id_for_label_uses_widget_attr_id_or_auto_id():
    bf1, _, _ = make_boundfield(field=DummyField(widget=DummyWidget(attrs={'id': 'custom'})))
    bf2, _, _ = make_boundfield(field=DummyField(widget=DummyWidget()))
    assert bf1.id_for_label == 'custom-label'
    assert bf2.id_for_label == 'id_prefix-first_name-label'

def test_id_for_label_returns_empty_when_no_auto_id_and_no_widget_id():
    bf, _, _ = make_boundfield(form=DummyForm(auto_id=''), field=DummyField(widget=DummyWidget()))
    assert bf.id_for_label == ''

def test_initial_is_cached_property():
    form = DummyForm(initials={'first_name': 'init'})
    bf, _, _ = make_boundfield(form=form)
    assert bf.initial == 'init'
    assert bf.initial == 'init'
    assert len(form.initial_calls) == 1

def test_build_widget_attrs_copies_input_and_applies_required_and_disabled():
    bf, _, _ = make_boundfield(form=DummyForm(use_required_attribute=True), field=DummyField(required=True, disabled=True))
    original = {'class': 'x'}
    built = bf.build_widget_attrs(original)
    assert built == {'class': 'x', 'required': True, 'disabled': True}
    assert original == {'class': 'x'}
    assert built is not original

def test_build_widget_attrs_skips_required_when_widget_or_form_disallows():
    bf1, _, _ = make_boundfield(form=DummyForm(use_required_attribute=True), field=DummyField(required=True, widget=DummyWidget(use_required=False)))
    bf2, _, _ = make_boundfield(form=DummyForm(use_required_attribute=False), field=DummyField(required=True, widget=DummyWidget(use_required=True)))
    assert bf1.build_widget_attrs({}) == {}
    assert bf2.build_widget_attrs({}) == {}

def test_build_widget_attrs_uses_explicit_widget_argument():
    other = DummyWidget(use_required=False)
    bf, _, _ = make_boundfield(field=DummyField(required=True, disabled=True))
    assert bf.build_widget_attrs({'a': 'b'}, widget=other) == {'a': 'b', 'disabled': True}

def test_widget_type_strips_widget_and_input_suffixes():

    class FancyWidget(DummyWidget):
        pass

    class EmailInput(DummyWidget):
        pass
    assert make_boundfield(field=DummyField(widget=FancyWidget()))[0].widget_type == 'fancy'
    assert make_boundfield(field=DummyField(widget=EmailInput()))[0].widget_type == 'email'

def test_boundwidget_str_tag_template_name_id_and_choice_label():
    parent = DummyWidget()
    bw = BoundWidget(parent, {'attrs': {'id': 'x1'}, 'label': 'Choice'}, TemplateRenderer())
    assert bw.template_name == 'parent-template'
    assert bw.id_for_label == 'x1'
    assert bw.choice_label == 'Choice'
    assert bw.tag() == 'tmpl:parent-template:wrap=False:label=Choice'
    assert str(bw) == 'tmpl:parent-template:wrap=True:label=Choice'

def test_boundwidget_uses_data_template_name_when_present():
    parent = DummyWidget()
    bw = BoundWidget(parent, {'attrs': {'id': 'x2'}, 'label': 'Alt', 'template_name': 'override-template'}, TemplateRenderer())
    assert bw.template_name == 'override-template'
    assert bw.tag(wrap_label=True) == 'tmpl:override-template:wrap=True:label=Alt'

def test_boundwidget_class_exposes_html_safe_str_method():
    assert '__html__' in BoundWidget.__dict__
    parent = DummyWidget()
    bw = BoundWidget(parent, {'attrs': {'id': 'z'}, 'label': 'Zed'}, TemplateRenderer())
    assert bw.__html__() == str(bw)
