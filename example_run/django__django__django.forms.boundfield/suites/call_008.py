from django.conf import settings

if not settings.configured:
    settings.configure(USE_I18N=False, SECRET_KEY="test", INSTALLED_APPS=[])

import django
django.setup()

import pytest

from django.core.exceptions import ValidationError
from django.forms.boundfield import BoundField, BoundWidget
from django.forms.widgets import HiddenInput
from django.utils.safestring import SafeString


class DummyErrorList(list):
    pass


class DummyRenderer:
    pass


class DummyWidget:
    is_hidden = False
    template_name = "parent-template"

    def __init__(self, attrs=None, use_required=True, id_suffix="-label", subwidgets_data=None):
        self.attrs = attrs or {}
        self.is_localized = False
        self._use_required = use_required
        self.id_suffix = id_suffix
        self.subwidgets_data = subwidgets_data or [
            {"attrs": {"id": "sub1"}, "label": "One"},
            {"attrs": {"id": "sub2"}, "label": "Two", "template_name": "child-template"},
        ]
        self.render_calls = []
        self.subwidgets_calls = []
        self.rendered_templates = []

    def render(self, name, value, attrs=None, renderer=None):
        call = {"name": name, "value": value, "attrs": attrs, "renderer": renderer}
        self.render_calls.append(call)
        return f"render:{name}:{value}:{attrs}"

    def subwidgets(self, name, value, attrs=None):
        self.subwidgets_calls.append((name, value, attrs))
        return list(self.subwidgets_data)

    def use_required_attribute(self, initial):
        return self._use_required

    def id_for_label(self, id_):
        if not id_:
            return ""
        return f"{id_}{self.id_suffix}"

    def _render(self, template_name, context, renderer):
        self.rendered_templates.append((template_name, context, renderer))
        wrap = context["widget"]["wrap_label"]
        label = context["widget"].get("label")
        return f"tmpl:{template_name}:wrap={wrap}:label={label}"


class HiddenWidget(DummyWidget):
    is_hidden = True
    template_name = "hidden-template"


class RecordingHiddenWidget(HiddenInput):
    def __init__(self):
        super().__init__()
        self.calls = []

    def render(self, name, value, attrs=None, renderer=None):
        self.calls.append({"name": name, "value": value, "attrs": attrs, "renderer": renderer})
        return super().render(name, value, attrs=attrs, renderer=renderer)


class DummyField:
    def __init__(
        self,
        widget=None,
        label="Field Label",
        help_text="help",
        show_hidden_initial=False,
        localize=False,
        required=False,
        disabled=False,
        label_suffix=None,
        hidden_widget_factory=None,
        bound_data_func=None,
        prepare_value_func=None,
        to_python_func=None,
        has_changed_func=None,
    ):
        self.widget = widget or DummyWidget()
        self.label = label
        self.help_text = help_text
        self.show_hidden_initial = show_hidden_initial
        self.localize = localize
        self.required = required
        self.disabled = disabled
        self.label_suffix = label_suffix
        self._hidden_widget_factory = hidden_widget_factory or (lambda: HiddenWidget())
        self._bound_data_func = bound_data_func or (lambda data, initial: f"bound({data}|{initial})")
        self._prepare_value_func = prepare_value_func or (lambda data: f"prepared({data})")
        self._to_python_func = to_python_func or (lambda value: f"python({value})")
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
    def __init__(
        self,
        *,
        auto_id="id_%s",
        is_bound=False,
        label_suffix=":",
        use_required_attribute=True,
        errors=None,
        renderer=None,
        initials=None,
        data_map=None,
    ):
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

    required_css_class = "required"
    error_css_class = "error"

    def add_prefix(self, name):
        return f"prefix-{name}"

    def add_initial_prefix(self, name):
        return f"initial-{name}"

    def error_class(self):
        return DummyErrorList()

    def _widget_data_value(self, widget, html_name):
        self.widget_data_calls.append((widget, html_name))
        return self._data_map.get(html_name)

    def get_initial_for_field(self, field, name):
        self.initial_calls.append((field, name))
        return self._initials.get(name, f"initial-{name}")


def make_boundfield(**kwargs):
    form = kwargs.pop("form", DummyForm())
    field = kwargs.pop("field", DummyField())
    name = kwargs.pop("name", "first_name")
    return BoundField(form, field, name), form, field


def test_init_and_pretty_name_and_help_text():
    bf, form, field = make_boundfield()
    assert bf.form is form
    assert bf.field is field
    assert bf.name == "first_name"
    assert bf.html_name == "prefix-first_name"
    assert bf.auto_id == "id_prefix-first_name"
    assert bf.html_initial_name == "initial-first_name"
    assert bf.html_initial_id == "initial-id_prefix-first_name"
    assert bf.label == "Field Label"
    assert bf.help_text == "help"
    bf2, _, _ = make_boundfield(field=DummyField(label=None), name="user_name")
    assert bf2.label == "User name"


def test_str_renders_widget_only_or_with_hidden_initial():
    bf, _, field = make_boundfield()
    assert str(bf) == "render:prefix-first_name:prepared(initial-first_name):{'id': 'id_prefix-first_name'}"
    assert len(field.widget.render_calls) == 1

    hidden = HiddenWidget()
    field2 = DummyField(show_hidden_initial=True, hidden_widget_factory=lambda: hidden)
    bf2, _, _ = make_boundfield(field=field2)
    result = str(bf2)
    assert result == (
        "render:prefix-first_name:prepared(initial-first_name):{'id': 'id_prefix-first_name'}"
        "render:initial-first_name:prepared(initial-first_name):{'id': 'initial-id_prefix-first_name'}"
    )


def test_subwidgets_cached_iteration_length_getitem_and_typeerror():
    bf, _, field = make_boundfield()
    first = bf.subwidgets
    second = bf.subwidgets
    assert first is second
    assert len(first) == 2
    assert all(isinstance(w, BoundWidget) for w in first)
    assert field.widget.subwidgets_calls == [
        ("prefix-first_name", "prepared(initial-first_name)", {"id": "id_prefix-first_name"})
    ]
    assert bool(bf) is True
    assert list(iter(bf)) == bf.subwidgets
    assert len(bf) == 2
    assert bf[0] is bf.subwidgets[0]
    assert bf[:1] == bf.subwidgets[:1]
    with pytest.raises(TypeError) as exc:
        _ = bf["x"]
    assert str(exc.value) == "BoundField indices must be integers or slices, not str."


def test_subwidgets_use_widget_id_and_build_attrs():
    widget = DummyWidget(attrs={"id": "custom-id"})
    field = DummyField(widget=widget, required=True, disabled=True)
    bf, _, _ = make_boundfield(field=field)
    _ = bf.subwidgets
    assert widget.subwidgets_calls[0][2] == {"id": "custom-id", "required": True, "disabled": True}


def test_subwidgets_without_any_id_passes_empty_attrs():
    widget = DummyWidget()
    field = DummyField(widget=widget)
    form = DummyForm(auto_id=False)
    bf, _, _ = make_boundfield(form=form, field=field)
    _ = bf.subwidgets
    assert widget.subwidgets_calls == [("prefix-first_name", "prepared(initial-first_name)", {})]


def test_errors_property_existing_or_default():
    existing = DummyErrorList(["bad"])
    bf, _, _ = make_boundfield(form=DummyForm(errors={"first_name": existing}))
    assert bf.errors is existing
    bf2, _, _ = make_boundfield(form=DummyForm())
    errs = bf2.errors
    assert isinstance(errs, DummyErrorList)
    assert errs == []


def test_as_widget_default_only_initial_existing_id_and_localize():
    widget = DummyWidget()
    field = DummyField(widget=widget, localize=True)
    bf, form, _ = make_boundfield(field=field)
    assert bf.as_widget() == "render:prefix-first_name:prepared(initial-first_name):{'id': 'id_prefix-first_name'}"
    assert widget.is_localized is True
    assert widget.render_calls[-1]["renderer"] is form.renderer

    widget2 = DummyWidget(attrs={"id": "already"})
    bf2, _, _ = make_boundfield(field=DummyField(widget=widget2))
    bf2.as_widget(only_initial=True)
    assert widget2.render_calls[-1]["name"] == "initial-first_name"
    assert widget2.render_calls[-1]["attrs"] == {}


def test_as_widget_merges_attrs_and_build_widget_attrs_variants():
    field = DummyField(required=True, disabled=True)
    bf, _, _ = make_boundfield(field=field)
    bf.as_widget(attrs={"class": "x"})
    assert field.widget.render_calls[-1]["attrs"] == {
        "class": "x",
        "required": True,
        "disabled": True,
        "id": "id_prefix-first_name",
    }

    original = {"class": "x"}
    built = bf.build_widget_attrs(original)
    assert built == {"class": "x", "required": True, "disabled": True}
    assert original == {"class": "x"}
    assert built is not original

    field2 = DummyField(required=True, disabled=False, widget=DummyWidget(use_required=False))
    bf2, _, _ = make_boundfield(form=DummyForm(use_required_attribute=True), field=field2)
    assert bf2.build_widget_attrs({}) == {}

    field3 = DummyField(required=True, disabled=False, widget=DummyWidget(use_required=True))
    bf3, _, _ = make_boundfield(form=DummyForm(use_required_attribute=False), field=field3)
    assert bf3.build_widget_attrs({}) == {}


def test_as_text_and_as_textarea_render_real_widgets():
    bf, _, _ = make_boundfield()
    text = bf.as_text()
    textarea = bf.as_textarea()
    assert text == '<input type="text" name="prefix-first_name" value="prepared(initial-first_name)" id="id_prefix-first_name">'
    assert textarea == '<textarea name="prefix-first_name" cols="40" rows="10" id="id_prefix-first_name">\nprepared(initial-first_name)</textarea>'


def test_as_hidden_uses_hidden_widget_factory():
    hidden_widget = RecordingHiddenWidget()
    field = DummyField(hidden_widget_factory=lambda: hidden_widget)
    bf, form, _ = make_boundfield(field=field)
    hidden = bf.as_hidden()
    assert hidden == '<input type="hidden" name="prefix-first_name" value="prepared(initial-first_name)" id="id_prefix-first_name">'
    assert hidden_widget.calls == [{
        "name": "prefix-first_name",
        "value": "prepared(initial-first_name)",
        "attrs": {"id": "id_prefix-first_name"},
        "renderer": form.renderer,
    }]


def test_data_and_value_unbound_and_bound():
    form = DummyForm(data_map={"prefix-first_name": "submitted"})
    bf, _, field = make_boundfield(form=form, field=DummyField(widget=DummyWidget()))
    assert bf.data == "submitted"
    assert form.widget_data_calls == [(field.widget, "prefix-first_name")]

    bf2, _, field2 = make_boundfield(form=DummyForm(is_bound=False))
    assert bf2.value() == "prepared(initial-first_name)"
    assert field2.bound_data_calls == []
    assert field2.prepare_value_calls == ["initial-first_name"]

    form3 = DummyForm(is_bound=True, data_map={"prefix-first_name": "posted"})
    field3 = DummyField()
    bf3, _, _ = make_boundfield(form=form3, field=field3)
    assert bf3.value() == "prepared(bound(posted|initial-first_name))"
    assert field3.bound_data_calls == [("posted", "initial-first_name")]


def test_has_changed_without_hidden_initial():
    form = DummyForm(data_map={"prefix-first_name": "x"})
    field = DummyField()
    bf, _, _ = make_boundfield(form=form, field=field)
    assert bf._has_changed() is True
    assert field.has_changed_calls == [("initial-first_name", "x")]


def test_has_changed_with_hidden_initial_and_validation_error():
    form = DummyForm(data_map={"initial-first_name": "raw", "prefix-first_name": "posted"})
    field = DummyField(show_hidden_initial=True)
    bf, _, _ = make_boundfield(form=form, field=field)
    assert bf._has_changed() is True
    assert field.to_python_calls == ["raw"]
    assert field.has_changed_calls == [("python(raw)", "posted")]

    field2 = DummyField(
        show_hidden_initial=True,
        to_python_func=lambda value: (_ for _ in ()).throw(ValidationError("bad")),
    )
    form2 = DummyForm(data_map={"initial-first_name": "RAISE", "prefix-first_name": "posted"})
    bf2, _, _ = make_boundfield(form=form2, field=field2)
    assert bf2._has_changed() is True
    assert field2.has_changed_calls == []


def test_label_tag_default_required_and_existing_class():
    widget = DummyWidget()
    field = DummyField(widget=widget, required=True)
    bf, _, _ = make_boundfield(field=field)
    assert bf.label_tag() == '<label class="required" for="id_prefix-first_name-label">Field Label:</label>'

    field2 = DummyField(widget=DummyWidget(), required=True, label_suffix="!")
    bf2, _, _ = make_boundfield(field=field2)
    assert bf2.label_tag(attrs={"class": "base"}) == (
        '<label class="base required" for="id_prefix-first_name-label">Field Label!</label>'
    )


def test_label_tag_custom_contents_suffix_sources_and_punctuation():
    bf, _, _ = make_boundfield()
    assert bf.label_tag(contents="Name", attrs={"class": "c"}, label_suffix="!") == (
        '<label class="c" for="id_prefix-first_name-label">Name!</label>'
    )
    assert bf.label_tag(contents="Name?") == '<label for="id_prefix-first_name-label">Name?</label>'

    field = DummyField(label_suffix="~")
    form = DummyForm(label_suffix=":")
    bf2, _, _ = make_boundfield(form=form, field=field)
    assert bf2.label_tag(contents="X") == '<label for="id_prefix-first_name-label">X~</label>'


def test_label_tag_without_contents_or_id_escapes_and_marks_safe():
    form = DummyForm(auto_id="")
    bf, _, _ = make_boundfield(form=form)
    result1 = bf.label_tag(contents="<b>X</b>")
    result2 = bf.label_tag(contents="")
    assert result1 == "&lt;b&gt;X&lt;/b&gt;:"
    assert result2 == "Field Label:"
    assert isinstance(result1, SafeString)
    assert isinstance(result2, SafeString)


def test_label_tag_with_empty_id_for_label_omits_for_attribute():
    widget = DummyWidget(id_suffix="")
    widget.id_for_label = lambda id_: ""
    bf, _, _ = make_boundfield(field=DummyField(widget=widget, required=True))
    assert bf.label_tag() == '<label class="required">Field Label:</label>'


def test_label_tag_without_suffix_when_override_empty_string():
    bf, _, _ = make_boundfield()
    assert bf.label_tag(contents="Name", label_suffix="") == '<label for="id_prefix-first_name-label">Name</label>'


def test_css_classes_with_string_and_none():
    form = DummyForm(errors={"first_name": DummyErrorList(["e"])})
    field = DummyField(required=True)
    bf, _, _ = make_boundfield(form=form, field=field)
    assert set(bf.css_classes("extra one").split()) == {"extra", "one", "error", "required"}

    bf2, _, _ = make_boundfield(form=DummyForm(errors={}), field=DummyField(required=False))
    assert bf2.css_classes() == ""


def test_css_classes_accepts_iterable_and_deduplicates():
    form = DummyForm(errors={"first_name": DummyErrorList(["e"])})
    field = DummyField(required=True)
    bf, _, _ = make_boundfield(form=form, field=field)
    classes = bf.css_classes(["error", "extra", "required", "extra"]).split()
    assert set(classes) == {"error", "required", "extra"}
    assert len(classes) == 3


def test_hidden_auto_id_and_id_for_label_properties():
    bf1, _, _ = make_boundfield(field=DummyField(widget=DummyWidget()))
    bf2, _, _ = make_boundfield(field=DummyField(widget=HiddenWidget()))
    assert bf1.is_hidden is False
    assert bf2.is_hidden is True

    bf3, _, _ = make_boundfield(form=DummyForm(auto_id="id_%s"))
    bf4, _, _ = make_boundfield(form=DummyForm(auto_id=True))
    bf5, _, _ = make_boundfield(form=DummyForm(auto_id=False))
    assert bf3.auto_id == "id_prefix-first_name"
    assert bf4.auto_id == "prefix-first_name"
    assert bf5.auto_id == ""

    widget1 = DummyWidget(attrs={"id": "custom"})
    bf6, _, _ = make_boundfield(field=DummyField(widget=widget1))
    assert bf6.id_for_label == "custom-label"
    widget2 = DummyWidget()
    bf7, _, _ = make_boundfield(field=DummyField(widget=widget2))
    assert bf7.id_for_label == "id_prefix-first_name-label"


def test_initial_is_cached_property():
    form = DummyForm(initials={"first_name": "init"})
    bf, _, _ = make_boundfield(form=form)
    assert bf.initial == "init"
    assert bf.initial == "init"
    assert len(form.initial_calls) == 1


def test_widget_type_strips_widget_and_input_suffixes():
    class FancyWidget(DummyWidget):
        pass

    class EmailInput(DummyWidget):
        pass

    bf1, _, _ = make_boundfield(field=DummyField(widget=FancyWidget()))
    bf2, _, _ = make_boundfield(field=DummyField(widget=EmailInput()))
    assert bf1.widget_type == "fancy"
    assert bf2.widget_type == "email"


def test_boundwidget_str_tag_template_name_id_and_choice_label():
    parent = DummyWidget()
    data = {"attrs": {"id": "x1"}, "label": "Choice"}
    bw = BoundWidget(parent, data, DummyRenderer())
    assert bw.template_name == "parent-template"
    assert bw.id_for_label == "x1"
    assert bw.choice_label == "Choice"
    assert bw.tag() == "tmpl:parent-template:wrap=False:label=Choice"
    assert str(bw) == "tmpl:parent-template:wrap=True:label=Choice"


def test_boundwidget_uses_data_template_name_when_present():
    parent = DummyWidget()
    data = {"attrs": {"id": "x2"}, "label": "Alt", "template_name": "override-template"}
    bw = BoundWidget(parent, data, DummyRenderer())
    assert bw.template_name == "override-template"
    assert bw.tag(wrap_label=True) == "tmpl:override-template:wrap=True:label=Alt"


def test_html_safe_decorator_exposes_html_method_on_classes():
    assert hasattr(BoundField, "__html__")
    assert hasattr(BoundWidget, "__html__")
