from django.conf import settings
if not settings.configured:
    settings.configure(USE_I18N=False, SECRET_KEY='test', INSTALLED_APPS=[])
import django
django.setup()
import pytest
from django.core.exceptions import ValidationError
from django.forms.boundfield import BoundField, BoundWidget
from django.forms.widgets import HiddenInput, TextInput, Textarea

class DummyErrorList(list):
    pass

class DummyRenderer:
    pass

class DummyWidget:
    is_hidden = False
    template_name = 'parent-template'

    def __init__(self, attrs=None, use_required=True, id_suffix='-label', subwidgets_data=None):
        self.attrs = attrs or {}
        self.is_localized = False
        self._use_required = use_required
        self.id_suffix = id_suffix
        self.subwidgets_data = subwidgets_data or [{'attrs': {'id': 'sub1'}, 'label': 'One'}, {'attrs': {'id': 'sub2'}, 'label': 'Two', 'template_name': 'child-template'}]
        self.render_calls = []
        self.subwidgets_calls = []
        self.rendered_templates = []

    def render(self, name, value, attrs=None, renderer=None):
        self.render_calls.append({'name': name, 'value': value, 'attrs': attrs, 'renderer': renderer})
        return f'render:{name}:{value}:{attrs}'

    def subwidgets(self, name, value, attrs=None):
        self.subwidgets_calls.append((name, value, attrs))
        return list(self.subwidgets_data)

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

class RecordingHiddenWidget(HiddenInput):

    def __init__(self):
        super().__init__()
        self.calls = []

    def render(self, name, value, attrs=None, renderer=None):
        self.calls.append({'name': name, 'value': value, 'attrs': attrs, 'renderer': renderer})
        return super().render(name, value, attrs=attrs, renderer=renderer)

class DummyFormRenderer:

    def render(self, template_name, context):
        widget = context['widget']
        attrs = widget.get('attrs', {})
        attr_text = ''.join((f' {k}="{v}"' for k, v in attrs.items()))
        value = widget.get('value')
        if template_name == 'django/forms/widgets/text.html':
            value_attr = f' value="{value}"' if value is not None else ''
            return f'''<input type="text" name="{widget['name']}"{value_attr}{attr_text}>'''
        if template_name == 'django/forms/widgets/textarea.html':
            return f'''<textarea name="{widget['name']}"{attr_text}>\n{value}</textarea>'''
        if template_name == 'django/forms/widgets/hidden.html':
            value_attr = f' value="{value}"' if value is not None else ''
            return f'''<input type="hidden" name="{widget['name']}"{value_attr}{attr_text}>'''
        return f'rendered:{template_name}:{widget}'

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
        self._bound_data_func = bound_data_func or (lambda data, initial: f'bound({data}|{initial})')
        self._prepare_value_func = prepare_value_func or (lambda data: f'prepared({data})')
        self._to_python_func = to_python_func or (lambda value: f'python({value})')
        self._has_changed_func = has_changed_func or (lambda initial, data: initial != data)
        self.bound_data_calls = []
        self.prepare_value_calls = []
        self.to_python_calls = []
        self.has_changed_calls = []

    def hidden_widget(self):
        return self._hidden_widget_factory()

    def bound_data(self, data, initial):
        self.bound_data_calls.append((data, initial))
        return self._bound_data_func(data, initial)

    def prepare_value(self, data):
        self.prepare_value_calls.append(data)
        return self._prepare_value_func(data)

    def to_python(self, value):
        self.to_python_calls.append(value)
        return self._to_python_func(value)

    def has_changed(self, initial, data):
        self.has_changed_calls.append((initial, data))
        return self._has_changed_func(initial, data)

class DummyForm:

    def __init__(self, *, auto_id='id_%s', is_bound=False, label_suffix=':', use_required_attribute=True, errors=None, renderer=None, initials=None, data_map=None):
        self.auto_id = auto_id
        self.is_bound = is_bound
        self.label_suffix = label_suffix
        self.use_required_attribute = use_required_attribute
        self.errors = errors or {}
        self.renderer = renderer or DummyRenderer()
        self._initials = initials or {}
        self._data_map = data_map or {}
        self.widget_data_calls = []
        self.initial_calls = []
    required_css_class = 'required'
    error_css_class = 'error'

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

def test_init_and_basic_properties():
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
    bf2, _, _ = make_boundfield(field=DummyField(label=None), name='user_name')
    assert bf2.label == 'User name'
    bf3, _, _ = make_boundfield(field=DummyField(help_text=''))
    assert bf3.help_text == ''

def test_str_rendering_with_and_without_hidden_initial():
    bf, _, field = make_boundfield()
    assert str(bf) == "render:prefix-first_name:prepared(initial-first_name):{'id': 'id_prefix-first_name'}"
    assert len(field.widget.render_calls) == 1
    hidden = HiddenWidget()
    field2 = DummyField(show_hidden_initial=True, hidden_widget_factory=lambda: hidden)
    bf2, _, _ = make_boundfield(field=field2)
    assert str(bf2) == "render:prefix-first_name:prepared(initial-first_name):{'id': 'id_prefix-first_name'}render:initial-first_name:prepared(initial-first_name):{'id': 'initial-id_prefix-first_name'}"

def test_subwidgets_cached_sequence_protocol_and_custom_id_attrs():
    bf, _, field = make_boundfield()
    first = bf.subwidgets
    assert first is bf.subwidgets
    assert len(first) == 2
    assert all((isinstance(w, BoundWidget) for w in first))
    assert field.widget.subwidgets_calls == [('prefix-first_name', 'prepared(initial-first_name)', {'id': 'id_prefix-first_name'})]
    assert bool(bf) is True
    assert list(iter(bf)) == bf.subwidgets
    assert len(bf) == 2
    assert bf[0] is bf.subwidgets[0]
    assert bf[:1] == bf.subwidgets[:1]
    with pytest.raises(TypeError) as exc:
        _ = bf['x']
    assert str(exc.value) == 'BoundField indices must be integers or slices, not str.'
    widget = DummyWidget(attrs={'id': 'custom-id'})
    field2 = DummyField(widget=widget, required=True, disabled=True)
    bf2, _, _ = make_boundfield(field=field2)
    _ = bf2.subwidgets
    assert widget.subwidgets_calls[0][2] == {'id': 'custom-id', 'required': True, 'disabled': True}

def test_errors_property_existing_or_default():
    existing = DummyErrorList(['bad'])
    bf, _, _ = make_boundfield(form=DummyForm(errors={'first_name': existing}))
    assert bf.errors is existing
    bf2, _, _ = make_boundfield(form=DummyForm())
    errs = bf2.errors
    assert isinstance(errs, DummyErrorList)
    assert errs == []

def test_as_widget_default_localize_only_initial_and_existing_widget_id():
    widget = DummyWidget()
    field = DummyField(widget=widget, localize=True)
    bf, form, _ = make_boundfield(field=field)
    assert bf.as_widget() == "render:prefix-first_name:prepared(initial-first_name):{'id': 'id_prefix-first_name'}"
    assert widget.is_localized is True
    assert widget.render_calls[-1]['renderer'] is form.renderer
    widget2 = DummyWidget(attrs={'id': 'already'})
    bf2, _, _ = make_boundfield(field=DummyField(widget=widget2))
    bf2.as_widget(only_initial=True)
    assert widget2.render_calls[-1]['name'] == 'initial-first_name'
    assert widget2.render_calls[-1]['attrs'] == {}

def test_build_widget_attrs_and_as_widget_attr_merging():
    field = DummyField(required=True, disabled=True)
    bf, _, _ = make_boundfield(field=field)
    bf.as_widget(attrs={'class': 'x'})
    assert field.widget.render_calls[-1]['attrs'] == {'class': 'x', 'required': True, 'disabled': True, 'id': 'id_prefix-first_name'}
    original = {'class': 'x'}
    built = bf.build_widget_attrs(original)
    assert built == {'class': 'x', 'required': True, 'disabled': True}
    assert original == {'class': 'x'}
    assert built is not original
    field2 = DummyField(required=True, disabled=False, widget=DummyWidget(use_required=False))
    bf2, _, _ = make_boundfield(form=DummyForm(use_required_attribute=True), field=field2)
    assert bf2.build_widget_attrs({}) == {}
    field3 = DummyField(required=True, disabled=False, widget=DummyWidget(use_required=True))
    bf3, _, _ = make_boundfield(form=DummyForm(use_required_attribute=False), field=field3)
    assert bf3.build_widget_attrs({}) == {}

def test_as_text_and_as_textarea_delegate_to_as_widget():
    bf, _, _ = make_boundfield()
    calls = []

    def fake_as_widget(widget=None, attrs=None, only_initial=False):
        calls.append((widget, attrs, only_initial))
        return f'used:{widget.__class__.__name__}:{attrs}:{only_initial}'
    bf.as_widget = fake_as_widget
    assert bf.as_text(attrs={'class': 't'}, only_initial=True) == "used:TextInput:{'class': 't'}:True"
    assert bf.as_textarea(attrs={'rows': 5}) == "used:Textarea:{'rows': 5}:False"
    assert isinstance(calls[0][0], TextInput)
    assert calls[0][1] == {'class': 't'}
    assert calls[0][2] is True
    assert isinstance(calls[1][0], Textarea)
    assert calls[1][1] == {'rows': 5}
    assert calls[1][2] is False

def test_as_hidden_uses_hidden_widget_factory_and_real_rendering():
    form = DummyForm(renderer=DummyFormRenderer())
    hidden = RecordingHiddenWidget()
    field = DummyField(hidden_widget_factory=lambda: hidden)
    bf, _, _ = make_boundfield(form=form, field=field)
    result = bf.as_hidden()
    assert result == '<input type="hidden" name="prefix-first_name" value="prepared(initial-first_name)" id="id_prefix-first_name">'
    assert hidden.calls == [{'name': 'prefix-first_name', 'value': 'prepared(initial-first_name)', 'attrs': {'id': 'id_prefix-first_name'}, 'renderer': form.renderer}]

def test_data_property_and_value_for_unbound_and_bound_forms():
    form = DummyForm(data_map={'prefix-first_name': 'submitted'})
    bf, _, field = make_boundfield(form=form, field=DummyField(widget=DummyWidget()))
    assert bf.data == 'submitted'
    assert form.widget_data_calls == [(field.widget, 'prefix-first_name')]
    bf2, _, field2 = make_boundfield(form=DummyForm(is_bound=False))
    assert bf2.value() == 'prepared(initial-first_name)'
    assert field2.bound_data_calls == []
    assert field2.prepare_value_calls == ['initial-first_name']
    form3 = DummyForm(is_bound=True, data_map={'prefix-first_name': 'posted'})
    field3 = DummyField()
    bf3, _, _ = make_boundfield(form=form3, field=field3)
    assert bf3.value() == 'prepared(bound(posted|initial-first_name))'
    assert field3.bound_data_calls == [('posted', 'initial-first_name')]

def test_has_changed_without_hidden_initial_true_and_false():
    form = DummyForm(data_map={'prefix-first_name': 'same'})
    field = DummyField(has_changed_func=lambda initial, data: initial != data)
    bf, _, _ = make_boundfield(form=form, field=field)
    assert bf._has_changed() is True
    assert field.has_changed_calls == [('initial-first_name', 'same')]
    form2 = DummyForm(data_map={'prefix-first_name': 'initial-first_name'})
    field2 = DummyField(has_changed_func=lambda initial, data: initial != data)
    bf2, _, _ = make_boundfield(form=form2, field=field2)
    assert bf2._has_changed() is False
    assert field2.has_changed_calls == [('initial-first_name', 'initial-first_name')]

def test_has_changed_with_hidden_initial_and_validation_error():
    form = DummyForm(data_map={'initial-first_name': 'raw', 'prefix-first_name': 'posted'})
    field = DummyField(show_hidden_initial=True)
    bf, _, _ = make_boundfield(form=form, field=field)
    assert bf._has_changed() is True
    assert field.to_python_calls == ['raw']
    assert field.has_changed_calls == [('python(raw)', 'posted')]
    field2 = DummyField(show_hidden_initial=True, to_python_func=lambda value: (_ for _ in ()).throw(ValidationError('bad')))
    form2 = DummyForm(data_map={'initial-first_name': 'RAISE', 'prefix-first_name': 'posted'})
    bf2, _, _ = make_boundfield(form=form2, field=field2)
    assert bf2._has_changed() is True
    assert field2.has_changed_calls == []

def test_css_classes_with_string_none_and_iterable_input():
    form = DummyForm(errors={'first_name': DummyErrorList(['e'])})
    field = DummyField(required=True)
    bf, _, _ = make_boundfield(form=form, field=field)
    assert set(bf.css_classes('extra one').split()) == {'extra', 'one', 'error', 'required'}
    bf2, _, _ = make_boundfield(form=DummyForm(errors={}), field=DummyField(required=False))
    assert bf2.css_classes() == ''
    bf3, _, _ = make_boundfield(form=DummyForm(errors={'first_name': DummyErrorList(['e'])}), field=DummyField(required=True))
    assert set(bf3.css_classes(['x', 'x', 'y']).split()) == {'x', 'y', 'error', 'required'}

def test_hidden_auto_id_id_for_label_and_initial_cached():
    bf1, _, _ = make_boundfield(field=DummyField(widget=DummyWidget()))
    bf2, _, _ = make_boundfield(field=DummyField(widget=HiddenWidget()))
    assert bf1.is_hidden is False
    assert bf2.is_hidden is True
    bf3, _, _ = make_boundfield(form=DummyForm(auto_id='id_%s'))
    bf4, _, _ = make_boundfield(form=DummyForm(auto_id=True))
    bf5, _, _ = make_boundfield(form=DummyForm(auto_id=False))
    assert bf3.auto_id == 'id_prefix-first_name'
    assert bf4.auto_id == 'prefix-first_name'
    assert bf5.auto_id == ''
    widget1 = DummyWidget(attrs={'id': 'custom'})
    bf6, _, _ = make_boundfield(field=DummyField(widget=widget1))
    assert bf6.id_for_label == 'custom-label'
    widget2 = DummyWidget()
    bf7, _, _ = make_boundfield(field=DummyField(widget=widget2))
    assert bf7.id_for_label == 'id_prefix-first_name-label'
    form = DummyForm(initials={'first_name': 'init'})
    bf8, _, _ = make_boundfield(form=form)
    assert bf8.initial == 'init'
    assert bf8.initial == 'init'
    assert len(form.initial_calls) == 1

def test_widget_type_strips_widget_and_input_suffixes_and_preserves_other_names():

    class FancyWidget(DummyWidget):
        pass

    class EmailInput(DummyWidget):
        pass

    class Slider(DummyWidget):
        pass
    bf1, _, _ = make_boundfield(field=DummyField(widget=FancyWidget()))
    assert bf1.widget_type == 'fancy'
    bf2, _, _ = make_boundfield(field=DummyField(widget=EmailInput()))
    assert bf2.widget_type == 'email'
    bf3, _, _ = make_boundfield(field=DummyField(widget=Slider()))
    assert bf3.widget_type == 'slider'

def test_boundwidget_behaviors_and_html_safe():
    parent = DummyWidget()
    bw = BoundWidget(parent, {'attrs': {'id': 'x1'}, 'label': 'Choice'}, DummyRenderer())
    assert bw.template_name == 'parent-template'
    assert bw.id_for_label == 'x1'
    assert bw.choice_label == 'Choice'
    assert bw.tag() == 'tmpl:parent-template:wrap=False:label=Choice'
    assert str(bw) == 'tmpl:parent-template:wrap=True:label=Choice'
    bw2 = BoundWidget(parent, {'attrs': {'id': 'x2'}, 'label': 'Alt', 'template_name': 'override-template'}, DummyRenderer())
    assert bw2.template_name == 'override-template'
    assert bw2.tag(wrap_label=True) == 'tmpl:override-template:wrap=True:label=Alt'
    assert hasattr(BoundField, '__html__')
    assert hasattr(BoundWidget, '__html__')
