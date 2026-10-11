import pytest
from django.core.exceptions import ValidationError
from django.forms.boundfield import BoundField, BoundWidget

class DummyErrorList(list):
    pass

class DummyRenderer:
    pass

class DummyWidget:
    is_hidden = False
    template_name = 'parent-template'

    def __init__(self, attrs=None, use_required=True, id_suffix='-label'):
        self.attrs = attrs or {}
        self.is_localized = False
        self._use_required = use_required
        self.id_suffix = id_suffix
        self.render_calls = []
        self.subwidgets_calls = []
        self.rendered_templates = []

    def render(self, name, value, attrs=None, renderer=None):
        call = {'name': name, 'value': value, 'attrs': attrs, 'renderer': renderer}
        self.render_calls.append(call)
        return f'render:{name}:{value}:{attrs}'

    def subwidgets(self, name, value, attrs=None):
        self.subwidgets_calls.append((name, value, attrs))
        return [{'attrs': {'id': 'sub1'}, 'label': 'One'}, {'attrs': {'id': 'sub2'}, 'label': 'Two', 'template_name': 'child-template'}]

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

    def __init__(self, widget=None, label='Field Label', help_text='help', show_hidden_initial=False, localize=False, required=False, disabled=False, label_suffix=None, hidden_widget_factory=None):
        self.widget = widget or DummyWidget()
        self.label = label
        self.help_text = help_text
        self.show_hidden_initial = show_hidden_initial
        self.localize = localize
        self.required = required
        self.disabled = disabled
        self.label_suffix = label_suffix
        self._hidden_widget_factory = hidden_widget_factory or (lambda: HiddenWidget())
        self.bound_data_calls = []
        self.prepare_value_calls = []
        self.to_python_calls = []
        self.has_changed_calls = []

    def hidden_widget(self):
        return self._hidden_widget_factory()

    def bound_data(self, data, initial):
        self.bound_data_calls.append((data, initial))
        return f'bound({data}|{initial})'

    def prepare_value(self, data):
        self.prepare_value_calls.append(data)
        return f'prepared({data})'

    def to_python(self, value):
        self.to_python_calls.append(value)
        if value == 'RAISE':
            raise ValidationError('bad')
        return f'python({value})'

    def has_changed(self, initial, data):
        self.has_changed_calls.append((initial, data))
        return initial != data

class DummyForm:

    def __init__(self, *, auto_id='id_%s', is_bound=False, label_suffix=':', use_required_attribute=True, errors=None, required_css_class='required', error_css_class='error', renderer=None, initials=None, data_map=None):
        self.auto_id = auto_id
        self.is_bound = is_bound
        self.label_suffix = label_suffix
        self.use_required_attribute = use_required_attribute
        self.errors = errors or {}
        self.required_css_class = required_css_class
        self.error_css_class = error_css_class
        self.renderer = renderer or DummyRenderer()
        self._initials = initials or {}
        self._data_map = data_map or {}
        self.widget_data_calls = []
        self.initial_calls = []

    def add_prefix(self, name):
        return f'prefix-{name}'

    def add_initial_prefix(self, name):
        return f'initial-{name}'

    def error_class(self):
        return DummyErrorList()

    def _widget_data_value(self, widget, html_name):
        self.widget_data_calls.append((widget, html_name))
        return self._data_map.get(html_name)

    def get_initial_for_field(self, field, name):
        self.initial_calls.append((field, name))
        return self._initials.get(name, f'initial-{name}')

def make_boundfield(**kwargs):
    form = kwargs.pop('form', DummyForm())
    field = kwargs.pop('field', DummyField())
    name = kwargs.pop('name', 'first_name')
    return (BoundField(form, field, name), form, field)

def test_init_sets_names_label_and_help_text_from_field():
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
    field = DummyField(label=None)
    bf, _, _ = make_boundfield(field=field, name='user_name')
    assert bf.label == 'User name'

def test_str_renders_widget_only_by_default():
    bf, _, field = make_boundfield()
    result = str(bf)
    assert result == "render:prefix-first_name:prepared(initial-first_name):{'id': 'id_prefix-first_name'}"
    assert len(field.widget.render_calls) == 1

def test_str_renders_widget_and_hidden_initial_when_enabled():
    hidden = HiddenWidget()
    field = DummyField(show_hidden_initial=True, hidden_widget_factory=lambda: hidden)
    bf, _, _ = make_boundfield(field=field)
    result = str(bf)
    assert "render:prefix-first_name:prepared(initial-first_name):{'id': 'id_prefix-first_name'}" in result
    assert "render:initial-first_name:prepared(initial-first_name):{'id': 'initial-id_prefix-first_name'}" in result

def test_subwidgets_cached_and_wraps_each_result_in_boundwidget():
    bf, _, field = make_boundfield()
    subwidgets1 = bf.subwidgets
    subwidgets2 = bf.subwidgets
    assert subwidgets1 is subwidgets2
    assert len(subwidgets1) == 2
    assert all((isinstance(w, BoundWidget) for w in subwidgets1))
    assert field.widget.subwidgets_calls == [('prefix-first_name', 'prepared(initial-first_name)', {'id': 'id_prefix-first_name'})]

def test_subwidgets_uses_widget_attr_id_over_auto_id_and_builds_attrs():
    widget = DummyWidget(attrs={'id': 'custom-id'})
    field = DummyField(widget=widget, required=True, disabled=True)
    bf, _, _ = make_boundfield(field=field)
    _ = bf.subwidgets
    assert widget.subwidgets_calls[0][2] == {'id': 'custom-id', 'required': True, 'disabled': True}

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

def test_errors_returns_existing_error_list_or_new_error_class():
    existing = DummyErrorList(['bad'])
    form = DummyForm(errors={'first_name': existing})
    bf, _, _ = make_boundfield(form=form)
    assert bf.errors is existing
    bf2, _, _ = make_boundfield(form=DummyForm())
    errs = bf2.errors
    assert isinstance(errs, DummyErrorList)
    assert errs == []

def test_as_widget_uses_default_widget_sets_localized_and_auto_id():
    widget = DummyWidget()
    field = DummyField(widget=widget, localize=True)
    bf, form, _ = make_boundfield(field=field)
    result = bf.as_widget()
    assert widget.is_localized is True
    assert result == "render:prefix-first_name:prepared(initial-first_name):{'id': 'id_prefix-first_name'}"
    call = widget.render_calls[-1]
    assert call['renderer'] is form.renderer

def test_as_widget_respects_only_initial_and_existing_widget_id():
    widget = DummyWidget(attrs={'id': 'already'})
    bf, _, _ = make_boundfield(field=DummyField(widget=widget))
    bf.as_widget(only_initial=True)
    call = widget.render_calls[-1]
    assert call['name'] == 'initial-first_name'
    assert call['attrs'] == {}

def test_as_widget_merges_attrs_with_required_and_disabled():
    field = DummyField(required=True, disabled=True)
    bf, _, _ = make_boundfield(field=field)
    bf.as_widget(attrs={'class': 'x'})
    call = field.widget.render_calls[-1]
    assert call['attrs'] == {'class': 'x', 'required': True, 'disabled': True, 'id': 'id_prefix-first_name'}

def test_data_property_reads_form_widget_data():
    form = DummyForm(data_map={'prefix-first_name': 'submitted'})
    bf, _, field = make_boundfield(form=form, field=DummyField(widget=DummyWidget()))
    assert bf.data == 'submitted'
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
    field = DummyField(show_hidden_initial=True)
    bf, _, _ = make_boundfield(form=form, field=field)
    assert bf._has_changed() is True
    assert field.has_changed_calls == []

def test_css_classes_accepts_string_and_adds_error_and_required_classes():
    form = DummyForm(errors={'first_name': DummyErrorList(['e'])})
    field = DummyField(required=True)
    bf, _, _ = make_boundfield(form=form, field=field)
    classes = set(bf.css_classes('extra one').split())
    assert classes == {'extra', 'one', 'error', 'required'}

def test_css_classes_with_none_and_without_errors():
    form = DummyForm(errors={})
    field = DummyField(required=False)
    bf, _, _ = make_boundfield(form=form, field=field)
    assert bf.css_classes() == ''

def test_is_hidden_property_reflects_widget():
    bf1, _, _ = make_boundfield(field=DummyField(widget=DummyWidget()))
    bf2, _, _ = make_boundfield(field=DummyField(widget=HiddenWidget()))
    assert bf1.is_hidden is False
    assert bf2.is_hidden is True

def test_auto_id_variants():
    bf1, _, _ = make_boundfield(form=DummyForm(auto_id='id_%s'))
    bf2, _, _ = make_boundfield(form=DummyForm(auto_id=True))
    bf3, _, _ = make_boundfield(form=DummyForm(auto_id=False))
    assert bf1.auto_id == 'id_prefix-first_name'
    assert bf2.auto_id == 'prefix-first_name'
    assert bf3.auto_id == ''

def test_id_for_label_uses_widget_attr_id_or_auto_id():
    widget1 = DummyWidget(attrs={'id': 'custom'})
    bf1, _, _ = make_boundfield(field=DummyField(widget=widget1))
    assert bf1.id_for_label == 'custom-label'
    widget2 = DummyWidget()
    bf2, _, _ = make_boundfield(field=DummyField(widget=widget2))
    assert bf2.id_for_label == 'id_prefix-first_name-label'

def test_initial_is_cached_property():
    form = DummyForm(initials={'first_name': 'init'})
    bf, _, _ = make_boundfield(form=form)
    assert bf.initial == 'init'
    assert bf.initial == 'init'
    assert len(form.initial_calls) == 1

def test_build_widget_attrs_copies_input_and_applies_required_and_disabled():
    field = DummyField(required=True, disabled=True)
    form = DummyForm(use_required_attribute=True)
    bf, _, _ = make_boundfield(form=form, field=field)
    original = {'class': 'x'}
    built = bf.build_widget_attrs(original)
    assert built == {'class': 'x', 'required': True, 'disabled': True}
    assert original == {'class': 'x'}

def test_build_widget_attrs_skips_required_when_widget_or_form_disallows():
    field = DummyField(required=True, disabled=False, widget=DummyWidget(use_required=False))
    bf, _, _ = make_boundfield(form=DummyForm(use_required_attribute=True), field=field)
    assert bf.build_widget_attrs({}) == {}
    field2 = DummyField(required=True, disabled=False, widget=DummyWidget(use_required=True))
    bf2, _, _ = make_boundfield(form=DummyForm(use_required_attribute=False), field=field2)
    assert bf2.build_widget_attrs({}) == {}

def test_widget_type_strips_widget_and_input_suffixes():

    class FancyWidget(DummyWidget):
        pass

    class EmailInput(DummyWidget):
        pass
    bf1, _, _ = make_boundfield(field=DummyField(widget=FancyWidget()))
    bf2, _, _ = make_boundfield(field=DummyField(widget=EmailInput()))
    assert bf1.widget_type == 'fancy'
    assert bf2.widget_type == 'email'

def test_boundwidget_str_tag_template_name_id_and_choice_label():
    parent = DummyWidget()
    data = {'attrs': {'id': 'x1'}, 'label': 'Choice'}
    bw = BoundWidget(parent, data, DummyRenderer())
    assert bw.template_name == 'parent-template'
    assert bw.id_for_label == 'x1'
    assert bw.choice_label == 'Choice'
    assert bw.tag() == 'tmpl:parent-template:wrap=False:label=Choice'
    assert str(bw) == 'tmpl:parent-template:wrap=True:label=Choice'

def test_boundwidget_uses_data_template_name_when_present():
    parent = DummyWidget()
    data = {'attrs': {'id': 'x2'}, 'label': 'Alt', 'template_name': 'override-template'}
    bw = BoundWidget(parent, data, DummyRenderer())
    assert bw.template_name == 'override-template'
    assert bw.tag(wrap_label=True) == 'tmpl:override-template:wrap=True:label=Alt'
