import pytest

from django.core.exceptions import ValidationError
from django.forms.boundfield import BoundField, BoundWidget


class DummyWidget:
    is_hidden = False
    template_name = "parent-template"

    def __init__(self, attrs=None, subwidgets_data=None, id_for_label_suffix=""):
        self.attrs = attrs or {}
        self.subwidgets_data = list(subwidgets_data or [])
        self.id_for_label_suffix = id_for_label_suffix
        self.render_calls = []
        self.subwidgets_calls = []
        self.is_localized = False
        self.last_render = None

    def render(self, name, value, attrs=None, renderer=None):
        self.last_render = {
            "name": name,
            "value": value,
            "attrs": attrs,
            "renderer": renderer,
        }
        self.render_calls.append(self.last_render)
        return f"render:{name}:{value}:{attrs}"

    def subwidgets(self, name, value, attrs=None):
        self.subwidgets_calls.append({"name": name, "value": value, "attrs": attrs})
        if self.subwidgets_data:
            return self.subwidgets_data
        return [{"attrs": attrs or {}, "label": "default"}]

    def id_for_label(self, id_):
        if not id_:
            return id_
        return f"{id_}{self.id_for_label_suffix}"

    def use_required_attribute(self, initial):
        return True

    def _render(self, template_name, context, renderer):
        return f"tmpl={template_name}|wrap={context['widget']['wrap_label']}|renderer={renderer}"


class HiddenWidget(DummyWidget):
    is_hidden = True


class NoRequiredWidget(DummyWidget):
    def use_required_attribute(self, initial):
        return False


class FancyInput:
    is_hidden = False
    template_name = "fancy"

    def __init__(self):
        self.attrs = {}

    def id_for_label(self, id_):
        return id_

    def use_required_attribute(self, initial):
        return False

    def render(self, name, value, attrs=None, renderer=None):
        return "ok"


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
        self._bound_data_func = bound_data_func or (lambda data, initial: data)
        self._prepare_value_func = prepare_value_func or (lambda value: f"prepared:{value}")
        self._to_python_func = to_python_func or (lambda value: f"py:{value}")
        self._has_changed_func = has_changed_func or (lambda initial, data: (initial, data))

    def hidden_widget(self):
        return self._hidden_widget_factory()

    def bound_data(self, data, initial):
        return self._bound_data_func(data, initial)

    def prepare_value(self, data):
        return self._prepare_value_func(data)

    def to_python(self, value):
        return self._to_python_func(value)

    def has_changed(self, initial, data):
        return self._has_changed_func(initial, data)


class ErrorMap(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class DummyForm:
    def __init__(
        self,
        *,
        auto_id="id_%s",
        label_suffix=":",
        use_required_attribute=True,
        is_bound=False,
        data_map=None,
        initial_map=None,
        errors=None,
        renderer="RENDERER",
    ):
        self.auto_id = auto_id
        self.label_suffix = label_suffix
        self.use_required_attribute = use_required_attribute
        self.is_bound = is_bound
        self.data_map = data_map or {}
        self.initial_map = initial_map or {}
        self.errors = ErrorMap(errors or {})
        self.renderer = renderer
        self.error_class_calls = 0
        self.initial_calls = []

    required_css_class = "required"
    error_css_class = "error"

    def add_prefix(self, name):
        return f"prefix-{name}"

    def add_initial_prefix(self, name):
        return f"initial-{name}"

    def _widget_data_value(self, widget, html_name):
        return self.data_map.get(html_name)

    def get_initial_for_field(self, field, name):
        self.initial_calls.append((field, name))
        return self.initial_map.get(name, f"initial:{name}")

    def error_class(self):
        self.error_class_calls += 1
        return ["default-error"]


def make_boundfield(name="first_name", **kwargs):
    form = kwargs.pop("form", DummyForm())
    field = kwargs.pop("field", DummyField())
    return BoundField(form, field, name), form, field


def test_init_sets_names_label_and_help_text_with_pretty_name():
    bf, form, field = make_boundfield(name="first_name", field=DummyField(label=None, help_text="assist"))
    assert bf.name == "first_name"
    assert bf.html_name == "prefix-first_name"
    assert bf.html_initial_name == "initial-first_name"
    assert bf.auto_id == "id_prefix-first_name"
    assert bf.html_initial_id == "initial-id_prefix-first_name"
    assert bf.label == "First name"
    assert bf.help_text == "assist"


def test_str_renders_widget_only_by_default():
    widget = DummyWidget()
    bf, _, _ = make_boundfield(field=DummyField(widget=widget))
    result = str(bf)
    assert result.startswith("render:prefix-first_name:")
    assert len(widget.render_calls) == 1


def test_str_renders_widget_and_hidden_initial_when_enabled():
    widget = DummyWidget()
    hidden = HiddenWidget()

    field = DummyField(
        widget=widget,
        show_hidden_initial=True,
        hidden_widget_factory=lambda: hidden,
    )
    bf, _, _ = make_boundfield(field=field)
    result = str(bf)
    assert "render:prefix-first_name:" in result
    assert "render:initial-first_name:" in result
    assert len(widget.render_calls) == 1
    assert len(hidden.render_calls) == 1


def test_subwidgets_cached_and_builds_attrs_with_auto_id():
    subdata = [
        {"attrs": {"id": "a"}, "label": "A"},
        {"attrs": {"id": "b"}, "label": "B"},
    ]
    widget = DummyWidget(subwidgets_data=subdata)
    bf, form, field = make_boundfield(field=DummyField(widget=widget))
    first = bf.subwidgets
    second = bf.subwidgets
    assert first is second
    assert len(widget.subwidgets_calls) == 1
    call = widget.subwidgets_calls[0]
    assert call["name"] == "prefix-first_name"
    assert call["value"] == "prepared:initial:first_name"
    assert call["attrs"]["id"] == "id_prefix-first_name"
    assert all(isinstance(w, BoundWidget) for w in first)
    assert [w.choice_label for w in first] == ["A", "B"]


def test_bool_iter_len_and_getitem_behaviors():
    subdata = [
        {"attrs": {"id": "x"}, "label": "X"},
        {"attrs": {"id": "y"}, "label": "Y"},
    ]
    bf, _, _ = make_boundfield(field=DummyField(widget=DummyWidget(subwidgets_data=subdata)))
    assert bool(bf) is True
    assert len(bf) == 2
    assert [w.choice_label for w in bf] == ["X", "Y"]
    assert bf[0].choice_label == "X"
    assert bf[1:].__class__ is list


def test_getitem_rejects_non_int_and_non_slice():
    bf, _, _ = make_boundfield()
    with pytest.raises(TypeError) as exc:
        _ = bf["bad"]
    assert "BoundField indices must be integers or slices, not str." == str(exc.value)


def test_errors_returns_existing_errors_or_default_error_class():
    form = DummyForm(errors={"first_name": ["e1"]})
    bf, _, _ = make_boundfield(form=form)
    assert bf.errors == ["e1"]
    assert form.error_class_calls == 0

    bf2, form2, _ = make_boundfield(form=DummyForm())
    assert bf2.errors == ["default-error"]
    assert form2.error_class_calls == 1


def test_as_widget_uses_default_widget_and_sets_localized_and_id():
    widget = DummyWidget()
    field = DummyField(widget=widget, localize=True)
    bf, form, _ = make_boundfield(field=field)
    result = bf.as_widget(attrs={"class": "x"})
    assert result.startswith("render:prefix-first_name:")
    call = widget.render_calls[-1]
    assert call["name"] == "prefix-first_name"
    assert call["value"] == "prepared:initial:first_name"
    assert call["attrs"]["class"] == "x"
    assert call["attrs"]["id"] == "id_prefix-first_name"
    assert call["renderer"] == form.renderer
    assert widget.is_localized is True


def test_as_widget_only_initial_uses_initial_name_and_initial_id():
    widget = DummyWidget()
    bf, _, _ = make_boundfield(field=DummyField(widget=widget))
    bf.as_widget(only_initial=True)
    call = widget.render_calls[-1]
    assert call["name"] == "initial-first_name"
    assert call["attrs"]["id"] == "initial-id_prefix-first_name"


def test_as_widget_does_not_set_id_when_widget_has_own_id():
    widget = DummyWidget(attrs={"id": "custom"})
    bf, _, _ = make_boundfield(field=DummyField(widget=widget))
    bf.as_widget()
    call = widget.render_calls[-1]
    assert "id" not in call["attrs"]


def test_as_text_as_textarea_and_as_hidden():
    bf, _, field = make_boundfield(field=DummyField())
    assert bf.as_text() == "ok"
    assert bf.as_textarea() == "ok"
    hidden_result = bf.as_hidden()
    assert hidden_result.startswith("render:prefix-first_name:")


def test_data_property_reads_from_form_widget_data_value():
    form = DummyForm(data_map={"prefix-first_name": "posted"})
    bf, _, _ = make_boundfield(form=form)
    assert bf.data == "posted"


def test_value_uses_initial_when_unbound():
    bf, _, _ = make_boundfield(form=DummyForm(is_bound=False, initial_map={"first_name": "INIT"}))
    assert bf.value() == "prepared:INIT"


def test_value_uses_bound_data_when_bound():
    field = DummyField(bound_data_func=lambda data, initial: f"{data}|{initial}", prepare_value_func=lambda v: f"PV:{v}")
    form = DummyForm(is_bound=True, data_map={"prefix-first_name": "DATA"}, initial_map={"first_name": "INIT"})
    bf, _, _ = make_boundfield(form=form, field=field)
    assert bf.value() == "PV:DATA|INIT"


def test_has_changed_uses_initial_when_no_hidden_initial():
    field = DummyField(has_changed_func=lambda initial, data: (initial, data), prepare_value_func=lambda v: v)
    form = DummyForm(data_map={"prefix-first_name": "DATA"}, initial_map={"first_name": "INIT"})
    bf, _, _ = make_boundfield(form=form, field=field)
    assert bf._has_changed() == ("INIT", "DATA")


def test_has_changed_with_hidden_initial_converts_initial():
    field = DummyField(
        show_hidden_initial=True,
        to_python_func=lambda value: f"TP:{value}",
        has_changed_func=lambda initial, data: (initial, data),
    )
    form = DummyForm(data_map={"initial-first_name": "RAWINIT", "prefix-first_name": "DATA"})
    bf, _, _ = make_boundfield(form=form, field=field)
    assert bf._has_changed() == ("TP:RAWINIT", "DATA")


def test_has_changed_with_hidden_initial_validation_error_returns_true():
    field = DummyField(
        show_hidden_initial=True,
        to_python_func=lambda value: (_ for _ in ()).throw(ValidationError("bad")),
    )
    form = DummyForm(data_map={"initial-first_name": "RAWINIT", "prefix-first_name": "DATA"})
    bf, _, _ = make_boundfield(form=form, field=field)
    assert bf._has_changed() is True


def test_label_tag_builds_label_with_suffix_for_and_required_class():
    widget = DummyWidget()
    field = DummyField(widget=widget, required=True)
    bf, _, _ = make_boundfield(field=field)
    html = bf.label_tag()
    assert html == '<label class="required" for="id_prefix-first_name">Field Label:</label>'


def test_label_tag_uses_field_label_suffix_over_form_suffix_and_preserves_existing_class():
    widget = DummyWidget()
    field = DummyField(widget=widget, required=True, label_suffix="!")
    bf, _, _ = make_boundfield(field=field)
    html = bf.label_tag(attrs={"class": "base"})
    assert html == '<label class="base required" for="id_prefix-first_name">Field Label!</label>'


def test_label_tag_does_not_append_suffix_after_punctuation():
    bf, _, _ = make_boundfield(field=DummyField(label="Name?"))
    html = bf.label_tag()
    assert html == '<label for="id_prefix-first_name">Name?</label>'


def test_label_tag_without_id_returns_escaped_contents_only():
    form = DummyForm(auto_id="")
    bf, _, _ = make_boundfield(form=form, field=DummyField())
    html = bf.label_tag(contents="<b>X</b>")
    assert html == "&lt;b&gt;X&lt;/b&gt;"


def test_css_classes_accepts_string_and_adds_error_and_required():
    form = DummyForm(errors={"first_name": ["err"]})
    field = DummyField(required=True)
    bf, _, _ = make_boundfield(form=form, field=field)
    classes = set(bf.css_classes("extra alpha").split())
    assert classes == {"extra", "alpha", "error", "required"}


def test_css_classes_with_no_extra_and_no_flags():
    class PlainForm(DummyForm):
        pass

    del PlainForm.required_css_class
    del PlainForm.error_css_class
    bf, _, _ = make_boundfield(form=PlainForm(), field=DummyField(required=False))
    assert bf.css_classes() == ""


def test_is_hidden_auto_id_and_id_for_label_properties():
    widget = HiddenWidget(attrs={"id": "manual"}, id_for_label_suffix="-lbl")
    bf, form, _ = make_boundfield(form=DummyForm(auto_id="AUTO"), field=DummyField(widget=widget))
    assert bf.is_hidden is True
    assert bf.auto_id == "prefix-first_name"
    assert bf.id_for_label == "manual-lbl"

    bf2, _, _ = make_boundfield(form=DummyForm(auto_id=False))
    assert bf2.auto_id == ""


def test_initial_is_cached_property():
    form = DummyForm(initial_map={"first_name": "INIT"})
    bf, _, _ = make_boundfield(form=form)
    assert bf.initial == "INIT"
    assert bf.initial == "INIT"
    assert len(form.initial_calls) == 1


def test_build_widget_attrs_copies_input_and_sets_required_and_disabled():
    field = DummyField(required=True, disabled=True)
    bf, form, _ = make_boundfield(form=DummyForm(use_required_attribute=True), field=field)
    attrs = {"class": "x"}
    built = bf.build_widget_attrs(attrs)
    assert built == {"class": "x", "required": True, "disabled": True}
    assert attrs == {"class": "x"}
    assert built is not attrs


def test_build_widget_attrs_respects_widget_and_form_required_flags():
    field = DummyField(required=True, disabled=False)
    bf, _, _ = make_boundfield(form=DummyForm(use_required_attribute=False), field=field)
    assert bf.build_widget_attrs({}) == {}

    bf2, _, _ = make_boundfield(field=DummyField(widget=NoRequiredWidget(), required=True))
    assert bf2.build_widget_attrs({}) == {}


def test_widget_type_strips_widget_and_input_suffixes():
    bf1, _, _ = make_boundfield(field=DummyField(widget=FancyInput()))
    assert bf1.widget_type == "fancy"

    bf2, _, _ = make_boundfield(field=DummyField(widget=DummyWidget()))
    assert bf2.widget_type == "dummy"


def test_boundwidget_string_tag_template_name_id_and_choice_label():
    parent = DummyWidget()
    data = {"attrs": {"id": "wid1"}, "label": "Choice 1", "template_name": "child-template"}
    bw = BoundWidget(parent, data, "R")
    assert str(bw) == "tmpl=child-template|wrap=True|renderer=R"
    assert bw.tag(wrap_label=False) == "tmpl=child-template|wrap=False|renderer=R"
    assert bw.template_name == "child-template"
    assert bw.id_for_label == "wid1"
    assert bw.choice_label == "Choice 1"


def test_boundwidget_falls_back_to_parent_template_name():
    parent = DummyWidget()
    data = {"attrs": {}, "label": "Choice 2"}
    bw = BoundWidget(parent, data, "R")
    assert bw.template_name == "parent-template"
