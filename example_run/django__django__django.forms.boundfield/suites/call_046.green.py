from django.conf import settings
if not settings.configured:
    settings.configure(USE_I18N=False, SECRET_KEY='test', INSTALLED_APPS=[], TEMPLATES=[{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'APP_DIRS': True}])
import django
django.setup()
import pytest
from django.core.exceptions import ValidationError
from django.forms.boundfield import BoundField, BoundWidget
from django.forms.widgets import HiddenInput
from django.utils.safestring import SafeString

class DummyErrorList(list):
    pass

class RealRenderer:

    def render(self, template_name, context, request=None):
        widget = context['widget']
        attrs = widget.get('attrs', {})
        if template_name == 'django/forms/widgets/text.html':
            value = widget.get('value')
            value_attr = '' if value in (None, '') else f' value="{value}"'
            id_attr = f''' id="{attrs['id']}"''' if 'id' in attrs else ''
            return f'''<input type="text" name="{widget['name']}"{value_attr}{id_attr}>'''
        if template_name == 'django/forms/widgets/textarea.html':
            id_attr = f''' id="{attrs['id']}"''' if 'id' in attrs else ''
            return f'''<textarea name="{widget['name']}" cols="40" rows="10"{id_attr}>\n{widget.get('value') or ''}</textarea>'''
        if template_name == 'django/forms/widgets/hidden.html':
            value = widget.get('value')
            value_attr = '' if value in (None, '') else f' value="{value}"'
            id_attr = f''' id="{attrs['id']}"''' if 'id' in attrs else ''
            return f'''<input type="hidden" name="{widget['name']}"{value_attr}{id_attr}>'''
        raise AssertionError(f'Unexpected template: {template_name}')

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
        call = {'name': name, 'value': value, 'attrs': attrs, 'renderer': renderer}
        self.render_calls.append(call)
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

def test_init_and_default_metadata():
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

def test_label_pretty_name_and_help_text_falsey():
    bf, _, _ = make_boundfield(field=DummyField(label=None), name='user_name')
    assert bf.label == 'User name'
    bf2, _, _ = make_boundfield(field=DummyField(help_text=None))
    assert bf2.help_text == ''

def test_str_renders_widget_only():
    bf, _, field = make_boundfield()
    assert str(bf) == "render:prefix-first_name:prepared(initial-first_name):{'id': 'id_prefix-first_name'}"
    assert len(field.widget.render_calls) == 1

def test_str_renders_widget_and_hidden_initial():
    hidden = HiddenWidget()
    field = DummyField(show_hidden_initial=True, hidden_widget_factory=lambda: hidden)
    bf, _, _ = make_boundfield(field=field)
    assert str(bf) == "render:prefix-first_name:prepared(initial-first_name):{'id': 'id_prefix-first_name'}render:initial-first_name:prepared(initial-first_name):{'id': 'initial-id_prefix-first_name'}"

def test_subwidgets_cached_iteration_access_and_typeerror():
    bf, _, field = make_boundfield()
    first = bf.subwidgets
    second = bf.subwidgets
    assert first is second
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

def test_subwidgets_attrs_with_custom_id_required_disabled():
    widget = DummyWidget(attrs={'id': 'custom-id'})
    field = DummyField(widget=widget, required=True, disabled=True)
    bf, _, _ = make_boundfield(field=field)
    _ = bf.subwidgets
    assert widget.subwidgets_calls[0][2] == {'id': 'custom-id', 'required': True, 'disabled': True}

def test_subwidgets_without_any_id_passes_empty_attrs():
    widget = DummyWidget()
    bf, _, _ = make_boundfield(form=DummyForm(auto_id=False), field=DummyField(widget=widget))
    _ = bf.subwidgets
    assert widget.subwidgets_calls == [('prefix-first_name', 'prepared(initial-first_name)', {})]

def test_subwidgets_respect_cached_initial_and_custom_subwidget_data():
    subdata = [{'attrs': {'id': 'only'}, 'label': 'Solo'}]
    widget = DummyWidget(subwidgets_data=subdata)
    form = DummyForm(initials={'first_name': 'init'})
    bf, _, field = make_boundfield(form=form, field=DummyField(widget=widget))
    bf.__dict__['initial'] = 'cached-init'
    subwidgets = bf.subwidgets
    assert len(subwidgets) == 1
    assert isinstance(subwidgets[0], BoundWidget)
    assert field.prepare_value_calls == ['cached-init']
    assert widget.subwidgets_calls == [('prefix-first_name', 'prepared(cached-init)', {'id': 'id_prefix-first_name'})]

def test_errors_property_existing_or_default():
    existing = DummyErrorList(['bad'])
    bf, _, _ = make_boundfield(form=DummyForm(errors={'first_name': existing}))
    assert bf.errors is existing
    bf2, _, _ = make_boundfield(form=DummyForm())
    errs = bf2.errors
    assert isinstance(errs, DummyErrorList)
    assert errs == []

def test_as_widget_default_localize_and_existing_widget_id_only_initial():
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

def test_as_widget_attrs_building_and_copy_semantics():
    field = DummyField(required=True, disabled=True)
    bf, _, _ = make_boundfield(field=field)
    bf.as_widget(attrs={'class': 'x'})
    assert field.widget.render_calls[-1]['attrs'] == {'class': 'x', 'required': True, 'disabled': True, 'id': 'id_prefix-first_name'}
    original = {'class': 'x'}
    built = bf.build_widget_attrs(original)
    assert built == {'class': 'x', 'required': True, 'disabled': True}
    assert original == {'class': 'x'}
    assert built is not original

def test_build_widget_attrs_skips_required_when_widget_or_form_disables_it():
    field2 = DummyField(required=True, disabled=False, widget=DummyWidget(use_required=False))
    bf2, _, _ = make_boundfield(form=DummyForm(use_required_attribute=True), field=field2)
    assert bf2.build_widget_attrs({}) == {}
    field3 = DummyField(required=True, disabled=False, widget=DummyWidget(use_required=True))
    bf3, _, _ = make_boundfield(form=DummyForm(use_required_attribute=False), field=field3)
    assert bf3.build_widget_attrs({}) == {}

def test_build_widget_attrs_disabled_only_and_custom_widget_argument():
    default_widget = DummyWidget()
    other_widget = DummyWidget(use_required=False)
    field = DummyField(widget=default_widget, required=True, disabled=True)
    bf, _, _ = make_boundfield(field=field)
    attrs = bf.build_widget_attrs({'x': 'y'}, widget=other_widget)
    assert attrs == {'x': 'y', 'disabled': True}
    assert default_widget is field.widget

def test_as_widget_custom_widget_only_initial_and_no_auto_id():
    default_widget = DummyWidget()
    other_widget = DummyWidget()
    bf, form, field = make_boundfield(field=DummyField(widget=default_widget))
    result = bf.as_widget(widget=other_widget, attrs={'class': 'z'})
    assert result == "render:prefix-first_name:prepared(initial-first_name):{'class': 'z', 'id': 'id_prefix-first_name'}"
    assert default_widget.render_calls == []
    assert other_widget.render_calls == [{'name': 'prefix-first_name', 'value': 'prepared(initial-first_name)', 'attrs': {'class': 'z', 'id': 'id_prefix-first_name'}, 'renderer': form.renderer}]
    assert field.widget is default_widget
    widget = DummyWidget()
    bf2, form2, _ = make_boundfield(field=DummyField(widget=widget))
    assert bf2.as_widget(only_initial=True) == "render:initial-first_name:prepared(initial-first_name):{'id': 'initial-id_prefix-first_name'}"
    assert widget.render_calls[-1] == {'name': 'initial-first_name', 'value': 'prepared(initial-first_name)', 'attrs': {'id': 'initial-id_prefix-first_name'}, 'renderer': form2.renderer}
    widget3 = DummyWidget()
    bf3, form3, _ = make_boundfield(form=DummyForm(auto_id=False), field=DummyField(widget=widget3))
    assert bf3.as_widget(attrs={'class': 'x'}) == "render:prefix-first_name:prepared(initial-first_name):{'class': 'x'}"
    assert widget3.render_calls[-1] == {'name': 'prefix-first_name', 'value': 'prepared(initial-first_name)', 'attrs': {'class': 'x'}, 'renderer': form3.renderer}

def test_real_widget_rendering_text_textarea_and_only_initial():
    bf, _, _ = make_boundfield(form=DummyForm(renderer=RealRenderer()))
    assert bf.as_text() == '<input type="text" name="prefix-first_name" value="prepared(initial-first_name)" id="id_prefix-first_name">'
    assert bf.as_textarea() == '<textarea name="prefix-first_name" cols="40" rows="10" id="id_prefix-first_name">\nprepared(initial-first_name)</textarea>'
    assert bf.as_text(only_initial=True) == '<input type="text" name="initial-first_name" value="prepared(initial-first_name)" id="initial-id_prefix-first_name">'
    assert bf.as_textarea(only_initial=True) == '<textarea name="initial-first_name" cols="40" rows="10" id="initial-id_prefix-first_name">\nprepared(initial-first_name)</textarea>'

def test_as_hidden_uses_hidden_widget_factory():
    hidden_widget = RecordingHiddenWidget()
    field = DummyField(hidden_widget_factory=lambda: hidden_widget)
    bf, form, _ = make_boundfield(field=field, form=DummyForm(renderer=RealRenderer()))
    hidden = bf.as_hidden()
    assert hidden == '<input type="hidden" name="prefix-first_name" value="prepared(initial-first_name)" id="id_prefix-first_name">'
    assert hidden_widget.calls == [{'name': 'prefix-first_name', 'value': 'prepared(initial-first_name)', 'attrs': {'id': 'id_prefix-first_name'}, 'renderer': form.renderer}]

def test_data_property_and_value_unbound_bound_and_none():
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
    form4 = DummyForm(is_bound=True, data_map={})
    field4 = DummyField()
    bf4, _, _ = make_boundfield(form=form4, field=field4)
    assert bf4.value() == 'prepared(bound(None|initial-first_name))'
    assert field4.bound_data_calls == [(None, 'initial-first_name')]
    assert field4.prepare_value_calls == ['bound(None|initial-first_name)']

def test_value_uses_cached_initial_when_bound():
    form = DummyForm(is_bound=True, data_map={'prefix-first_name': 'posted'})
    field = DummyField()
    bf, _, _ = make_boundfield(form=form, field=field)
    bf.__dict__['initial'] = 'manual-initial'
    assert bf.value() == 'prepared(bound(posted|manual-initial))'
    assert field.bound_data_calls == [('posted', 'manual-initial')]
    assert field.prepare_value_calls == ['bound(posted|manual-initial)']

def test_has_changed_without_hidden_initial_true_and_false():
    form = DummyForm(data_map={'prefix-first_name': 'x'})
    field = DummyField()
    bf, _, _ = make_boundfield(form=form, field=field)
    assert bf._has_changed() is True
    assert field.has_changed_calls == [('initial-first_name', 'x')]
    form2 = DummyForm(data_map={'prefix-first_name': 'same'})
    field2 = DummyField(has_changed_func=lambda initial, data: initial != data)
    bf2, _, _ = make_boundfield(form=form2, field=field2)
    bf2.__dict__['initial'] = 'same'
    assert bf2._has_changed() is False
    assert field2.has_changed_calls == [('same', 'same')]

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

def test_has_changed_with_hidden_initial_false_result_and_hidden_widget_used():
    hidden_widget = HiddenWidget()
    form = DummyForm(data_map={'initial-first_name': 'same', 'prefix-first_name': 'same'})
    field = DummyField(show_hidden_initial=True, hidden_widget_factory=lambda: hidden_widget, to_python_func=lambda value: value, has_changed_func=lambda initial, data: initial != data)
    bf, _, _ = make_boundfield(form=form, field=field)
    assert bf._has_changed() is False
    assert form.widget_data_calls[0] == (hidden_widget, 'initial-first_name')
    assert form.widget_data_calls[1] == (field.widget, 'prefix-first_name')
    assert field.to_python_calls == ['same']
    assert field.has_changed_calls == [('same', 'same')]

def test_label_tag_with_empty_id_for_label_omits_for_attribute_and_escapes_attrs():
    widget = DummyWidget(id_suffix='')
    widget.id_for_label = lambda id_: ''
    bf, _, _ = make_boundfield(field=DummyField(widget=widget, required=True))
    assert bf.label_tag() == '<label class="required">Field Label:</label>'
    bf2, _, _ = make_boundfield()
    html = bf2.label_tag(contents='Name', attrs={'data-x': '"quoted"'})
    assert html == '<label data-x="&quot;quoted&quot;" for="id_prefix-first_name-label">Name:</label>'

def test_css_classes_string_iterable_and_empty():
    form = DummyForm(errors={'first_name': DummyErrorList(['e'])})
    field = DummyField(required=True)
    bf, _, _ = make_boundfield(form=form, field=field)
    assert set(bf.css_classes('extra one').split()) == {'extra', 'one', 'error', 'required'}
    classes = bf.css_classes(['error', 'extra', 'required', 'extra']).split()
    assert set(classes) == {'error', 'required', 'extra'}
    assert len(classes) == 3
    bf2, _, _ = make_boundfield(form=DummyForm(errors={}), field=DummyField(required=False))
    assert bf2.css_classes() == ''

def test_is_hidden_auto_id_and_id_for_label_properties():
    bf1, _, _ = make_boundfield(field=DummyField(widget=DummyWidget()))
    bf2, _, _ = make_boundfield(field=DummyField(widget=HiddenWidget()))
    assert bf1.is_hidden is False
    assert bf2.is_hidden is True
    bf3, _, _ = make_boundfield(form=DummyForm(auto_id='id_%s'))
    bf4, _, _ = make_boundfield(form=DummyForm(auto_id=True))
    bf5, _, _ = make_boundfield(form=DummyForm(auto_id=False))
    bf6, _, _ = make_boundfield(form=DummyForm(auto_id='plain-id'))
    assert bf3.auto_id == 'id_prefix-first_name'
    assert bf4.auto_id == 'prefix-first_name'
    assert bf5.auto_id == ''
    assert bf6.auto_id == 'prefix-first_name'
    widget1 = DummyWidget(attrs={'id': 'custom'})
    bf7, _, _ = make_boundfield(field=DummyField(widget=widget1))
    assert bf7.id_for_label == 'custom-label'
    widget2 = DummyWidget()
    bf8, _, _ = make_boundfield(field=DummyField(widget=widget2))
    assert bf8.id_for_label == 'id_prefix-first_name-label'

def test_initial_is_cached_property():
    form = DummyForm(initials={'first_name': 'init'})
    bf, _, _ = make_boundfield(form=form)
    assert bf.initial == 'init'
    assert bf.initial == 'init'
    assert len(form.initial_calls) == 1

def test_widget_type_strips_widget_and_input_suffixes():

    class FancyWidget(DummyWidget):
        pass

    class EmailInput(DummyWidget):
        pass

    class Widget(DummyWidget):
        pass
    bf1, _, _ = make_boundfield(field=DummyField(widget=FancyWidget()))
    bf2, _, _ = make_boundfield(field=DummyField(widget=EmailInput()))
    bf3, _, _ = make_boundfield(field=DummyField(widget=Widget()))
    assert bf1.widget_type == 'fancy'
    assert bf2.widget_type == 'email'
    assert bf3.widget_type == ''

def test_boundwidget_properties_and_string_rendering():
    parent = DummyWidget()
    data = {'attrs': {'id': 'x1'}, 'label': 'Choice'}
    bw = BoundWidget(parent, data, DummyRenderer())
    assert bw.template_name == 'parent-template'
    assert bw.id_for_label == 'x1'
    assert bw.choice_label == 'Choice'
    assert bw.tag() == 'tmpl:parent-template:wrap=False:label=Choice'
    assert str(bw) == 'tmpl:parent-template:wrap=True:label=Choice'

def test_boundwidget_override_template_and_context_renderer():
    parent = DummyWidget()
    renderer = DummyRenderer()
    data = {'attrs': {'id': 'x2'}, 'label': 'Alt', 'template_name': 'override-template'}
    bw = BoundWidget(parent, data, renderer)
    assert bw.template_name == 'override-template'
    assert bw.tag(wrap_label=True) == 'tmpl:override-template:wrap=True:label=Alt'
    assert parent.rendered_templates[-1] == ('override-template', {'widget': {'attrs': {'id': 'x2'}, 'label': 'Alt', 'template_name': 'override-template', 'wrap_label': True}}, renderer)

def test_html_safe_decorator_exposes_html_method_on_classes():
    assert hasattr(BoundField, '__html__')
    assert hasattr(BoundWidget, '__html__')
