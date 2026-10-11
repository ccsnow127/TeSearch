import pytest

from django.core.exceptions import ValidationError
from django.forms.boundfield import BoundField, BoundWidget


class DummyWidget:
    is_hidden = False
    template_name = "parent-template"

    def __init__(self, attrs=None):
        self.attrs = attrs or {}
        self.is_localized = False
        self.render_calls = []
        self.subwidgets_calls = []
        self.id_for_label_calls = []
        self.use_required_attribute_calls = []
        self.render_return = "<rendered>"
        self.subwidgets_return = [
            {"attrs": {"id": "sub1"}, "label": "Choice 1"},
            {"attrs": {"id": "sub2"}, "label": "Choice 2", "template_name": "child-template"},
        ]
        self.hidden_widget_instance = None

    def render(self, name, value, attrs=None, renderer=None):
        self.render_calls.append(
            {"name": name, "value": value, "attrs": attrs, "renderer": renderer}
        )
        return self.render_return

    def subwidgets(self, name, value, attrs=None):
        self.subwidgets_calls.append({"name": name, "value": value, "attrs": attrs})
        return list(self.subwidgets_return)

    def id_for_label(self, id_):
        self.id_for_label_calls.append(id_)
        return f"label-{id_}" if id_ else ""

    def use_required_attribute(self, initial):
        self.use_required_attribute_calls.append(initial)
        return True

    def _render(self, template_name, context, renderer):
        return f"rendered:{template_name}:{context['widget']['wrap_label']}:{renderer}"


class HiddenWidget(DummyWidget):
    is_hidden = True
    template_name = "hidden-template"


class NoRequiredWidget(DummyWidget):
    def use_required_attribute(self, initial):
        self.use_required_attribute_calls.append(initial)
        return False


class DummyField:
    def __init__(
        self,
        widget=None,
        label=None,
        help_text="",
        show_hidden_initial=False,
        localize=False,
        required=False,
        disabled=False,
        label_suffix=None,
    ):
        self.widget = widget or DummyWidget()
        self.label = label
        self.help_text = help_text
        self.show_hidden_initial = show_hidden_initial
        self.localize = localize
        self.required = required
        self.disabled = disabled
        self.label_suffix = label_suffix
        self.bound_data_calls = []
        self.prepare_value_calls = []
        self.to_python_calls = []
        self.has_changed_calls = []
        self.hidden_widget_calls = 0
        self.hidden_widget_instance = HiddenWidget()

    def hidden_widget(self):
        self.hidden_widget_calls += 1
        return self.hidden_widget_instance

    def bound_data(self, data, initial):
        self.bound_data_calls.append((data, initial))
        return f"bound({data}|{initial})"

    def prepare_value(self, data):
        self.prepare_value_calls.append(data)
        return f"prepared({data})"

    def to_python(self, value):
        self.to_python_calls.append(value)
        return f"py({value})"

    def has_changed(self, initial, data):
        self.has_changed_calls.append((initial, data))
        return initial != data


class RaisingToPythonField(DummyField):
    def to_python(self, value):
        self.to_python_calls.append(value)
        raise ValidationError("bad")


class ErrorMap(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class DummyForm:
    def __init__(
        self,
        *,
        auto_id="id_%s",
        is_bound=False,
        label_suffix=":",
        use_required_attribute=True,
        required_css_class="required",
        error_css_class="error",
        errors=None,
        widget_data=None,
        initial_map=None,
        renderer="RENDERER",
    ):
        self.auto_id = auto_id
        self.is_bound = is_bound
        self.label_suffix = label_suffix
        self.use_required_attribute = use_required_attribute
        self.required_css_class = required_css_class
        self.error_css_class = error_css_class
        self.errors = ErrorMap(errors or {})
        self._widget_data = widget_data or {}
        self._initial_map = initial_map or {}
        self.renderer = renderer
        self.error_class_calls = 0
        self.add_prefix_calls = []
        self.add_initial_prefix_calls = []
        self.widget_data_calls = []
        self.initial_calls = []

    def add_prefix(self, name):
        self.add_prefix_calls.append(name)
        return f"prefix-{name}"

    def add_initial_prefix(self, name):
        self.add_initial_prefix_calls.append(name)
        return f"initial-{name}"

    def _widget_data_value(self, widget, html_name):
        self.widget_data_calls.append((widget, html_name))
        return self._widget_data.get(html_name)

    def get_initial_for_field(self, field, name):
        self.initial_calls.append((field, name))
        return self._initial_map.get(name, f"initial-{name}")

    def error_class(self):
        self.error_class_calls += 1
        return ["default-error"]


def make_boundfield(**kwargs):
    form = kwargs.pop("form", DummyForm())
    field = kwargs.pop("field", DummyField())
    name = kwargs.pop("name", "first_name")
    return BoundField(form, field, name), form, field


def test_init_sets_names_label_and_help_text():
    form = DummyForm()
    field = DummyField(label=None, help_text="")
    bf = BoundField(form, field, "first_name")
    assert bf.name == "first_name"
    assert bf.html_name == "prefix-first_name"
    assert bf.auto_id == "id_prefix-first_name"
    assert bf.html_initial_name == "initial-first_name"
    assert bf.html_initial_id == "initial-id_prefix-first_name"
    assert bf.label == "First name"
    assert bf.help_text == ""


def test_init_uses_explicit_label_and_help_text():
    bf, _, _ = make_boundfield(field=DummyField(label="Explicit", help_text="Help"))
    assert bf.label == "Explicit"
    assert bf.help_text == "Help"


def test_str_renders_widget_only_by_default():
    widget = DummyWidget()
    widget.render_return = "W"
    bf, _, _ = make_boundfield(field=DummyField(widget=widget))
    assert str(bf) == "W"


def test_str_renders_widget_and_hidden_initial_when_enabled():
    widget = DummyWidget()
    widget.render_return = "VISIBLE"
    field = DummyField(widget=widget, show_hidden_initial=True)
    field.hidden_widget_instance.render_return = "HIDDEN"
    bf, _, _ = make_boundfield(field=field)
    assert str(bf) == "VISIBLEHIDDEN"


def test_subwidgets_cached_and_wraps_boundwidgets():
    widget = DummyWidget()
    bf, form, field = make_boundfield(field=DummyField(widget=widget))
    subs1 = bf.subwidgets
    subs2 = bf.subwidgets
    assert subs1 is subs2
    assert len(subs1) == 2
    assert all(isinstance(s, BoundWidget) for s in subs1)
    assert len(widget.subwidgets_calls) == 1
    call = widget.subwidgets_calls[0]
    assert call["name"] == "prefix-first_name"
    assert call["value"] == "prepared(initial-first_name)"
    assert call["attrs"]["id"] == "id_prefix-first_name"


def test_subwidgets_uses_widget_attr_id_over_auto_id_and_build_attrs():
    widget = DummyWidget(attrs={"id": "custom-id"})
    field = DummyField(widget=widget, required=True, disabled=True)
    bf, _, _ = make_boundfield(field=field)
    _ = bf.subwidgets
    call = widget.subwidgets_calls[0]
    assert call["attrs"] == {"id": "custom-id", "required": True, "disabled": True}


def test_bool_iter_len_getitem():
    bf, _, _ = make_boundfield()
    assert bool(bf) is True
    assert len(bf) == 2
    assert list(iter(bf)) == bf.subwidgets
    assert bf[0] is bf.subwidgets[0]
    assert bf[0:1] == bf.subwidgets[0:1]


def test_getitem_rejects_non_int_or_slice():
    bf, _, _ = make_boundfield()
    with pytest.raises(TypeError) as exc:
        _ = bf["x"]
    assert str(exc.value) == "BoundField indices must be integers or slices, not str."


def test_errors_returns_existing_errors():
    bf, _, _ = make_boundfield(form=DummyForm(errors={"first_name": ["e1"]}))
    assert bf.errors == ["e1"]


def test_errors_returns_default_error_class_when_missing():
    form = DummyForm()
    bf = BoundField(form, DummyField(), "first_name")
    assert bf.errors == ["default-error"]
    assert form.error_class_calls == 1


def test_as_widget_uses_default_widget_and_sets_auto_id():
    widget = DummyWidget()
    widget.render_return = "OK"
    bf, form, field = make_boundfield(field=DummyField(widget=widget))
    result = bf.as_widget()
    assert result == "OK"
    call = widget.render_calls[-1]
    assert call["name"] == "prefix-first_name"
    assert call["value"] == "prepared(initial-first_name)"
    assert call["attrs"]["id"] == "id_prefix-first_name"
    assert call["renderer"] == form.renderer


def test_as_widget_only_initial_uses_initial_name_and_id():
    widget = DummyWidget()
    bf, _, field = make_boundfield(field=DummyField(widget=widget))
    bf.as_widget(only_initial=True)
    call = widget.render_calls[-1]
    assert call["name"] == "initial-first_name"
    assert call["attrs"]["id"] == "initial-id_prefix-first_name"


def test_as_widget_does_not_override_existing_widget_id():
    widget = DummyWidget(attrs={"id": "present"})
    bf, _, _ = make_boundfield(field=DummyField(widget=widget))
    bf.as_widget()
    call = widget.render_calls[-1]
    assert "id" not in call["attrs"]


def test_as_widget_localizes_widget():
    widget = DummyWidget()
    field = DummyField(widget=widget, localize=True)
    bf, _, _ = make_boundfield(field=field)
    bf.as_widget()
    assert widget.is_localized is True


def test_as_text_and_as_textarea_render():
    bf, _, _ = make_boundfield()
    text = bf.as_text()
    area = bf.as_textarea()
    assert 'type="text"' in text
    assert "<textarea" in area


def test_as_hidden_uses_hidden_widget():
    field = DummyField()
    field.hidden_widget_instance.render_return = "H"
    bf, _, _ = make_boundfield(field=field)
    assert bf.as_hidden() == "H"
    assert field.hidden_widget_calls == 1


def test_data_reads_from_form_widget_data():
    widget = DummyWidget()
    form = DummyForm(widget_data={"prefix-first_name": "posted"})
    bf = BoundField(form, DummyField(widget=widget), "first_name")
    assert bf.data == "posted"
    assert form.widget_data_calls[-1] == (widget, "prefix-first_name")


def test_value_uses_initial_when_unbound():
    bf, form, field = make_boundfield(form=DummyForm(is_bound=False))
    assert bf.value() == "prepared(initial-first_name)"
    assert field.bound_data_calls == []


def test_value_uses_bound_data_when_bound():
    form = DummyForm(is_bound=True, widget_data={"prefix-first_name": "posted"})
    field = DummyField()
    bf = BoundField(form, field, "first_name")
    assert bf.value() == "prepared(bound(posted|initial-first_name))"
    assert field.bound_data_calls == [("posted", "initial-first_name")]


def test_has_changed_without_hidden_initial_uses_initial():
    form = DummyForm(widget_data={"prefix-first_name": "x"})
    field = DummyField()
    bf = BoundField(form, field, "first_name")
    assert bf._has_changed() is True
    assert field.has_changed_calls == [("initial-first_name", "x")]


def test_has_changed_with_hidden_initial_converts_initial():
    form = DummyForm(
        widget_data={
            "prefix-first_name": "data",
            "initial-first_name": "hidden-val",
        }
    )
    field = DummyField(show_hidden_initial=True)
    bf = BoundField(form, field, "first_name")
    assert bf._has_changed() is True
    assert field.to_python_calls == ["hidden-val"]
    assert field.has_changed_calls == [("py(hidden-val)", "data")]


def test_has_changed_with_hidden_initial_validation_error_returns_true():
    form = DummyForm(widget_data={"initial-first_name": "bad", "prefix-first_name": "x"})
    field = RaisingToPythonField(show_hidden_initial=True)
    bf = BoundField(form, field, "first_name")
    assert bf._has_changed() is True
    assert field.has_changed_calls == []


def test_label_tag_builds_label_with_for_suffix_and_required_class():
    field = DummyField(required=True)
    bf, form, _ = make_boundfield(field=field)
    html = bf.label_tag()
    assert html == '<label class="required" for="label-id_prefix-first_name">First name:</label>'


def test_label_tag_uses_custom_contents_and_attrs_and_suffix_override():
    bf, _, _ = make_boundfield(field=DummyField(required=True))
    html = bf.label_tag(contents="Name", attrs={"class": "x", "data-a": "1"}, label_suffix="!")
    assert html == '<label class="x required" data-a="1" for="label-id_prefix-first_name">Name!</label>'


def test_label_tag_does_not_append_suffix_if_contents_end_with_punctuation():
    bf, _, _ = make_boundfield()
    html = bf.label_tag(contents="Name?")
    assert html == '<label for="label-id_prefix-first_name">Name?</label>'


def test_label_tag_uses_field_label_suffix_over_form_suffix():
    field = DummyField(label_suffix=";")
    bf, _, _ = make_boundfield(field=field)
    html = bf.label_tag(contents="Name")
    assert html == '<label for="label-id_prefix-first_name">Name;</label>'


def test_label_tag_without_id_escapes_contents_and_no_label():
    form = DummyForm(auto_id="")
    bf = BoundField(form, DummyField(), "first_name")
    html = bf.label_tag(contents="<b>X</b>")
    assert html == "&lt;b&gt;X&lt;/b&gt;:"


def test_css_classes_from_string_errors_and_required():
    form = DummyForm(errors={"first_name": ["e"]})
    field = DummyField(required=True)
    bf = BoundField(form, field, "first_name")
    classes = set(bf.css_classes("a b").split())
    assert classes == {"a", "b", "error", "required"}


def test_css_classes_from_iterable_and_without_form_attrs():
    form = DummyForm()
    delattr(form, "error_css_class")
    delattr(form, "required_css_class")
    bf = BoundField(form, DummyField(required=True), "first_name")
    classes = set(bf.css_classes(["x", "y"]).split())
    assert classes == {"x", "y"}


def test_is_hidden_property():
    bf, _, _ = make_boundfield(field=DummyField(widget=HiddenWidget()))
    assert bf.is_hidden is True


def test_auto_id_with_pattern_plain_and_disabled():
    bf1 = BoundField(DummyForm(auto_id="id_%s"), DummyField(), "first_name")
    bf2 = BoundField(DummyForm(auto_id=True), DummyField(), "first_name")
    bf3 = BoundField(DummyForm(auto_id=False), DummyField(), "first_name")
    assert bf1.auto_id == "id_prefix-first_name"
    assert bf2.auto_id == "prefix-first_name"
    assert bf3.auto_id == ""


def test_id_for_label_uses_widget_attr_id_or_auto_id():
    widget1 = DummyWidget(attrs={"id": "custom"})
    bf1 = BoundField(DummyForm(), DummyField(widget=widget1), "first_name")
    assert bf1.id_for_label == "label-custom"

    widget2 = DummyWidget()
    bf2 = BoundField(DummyForm(), DummyField(widget=widget2), "first_name")
    assert bf2.id_for_label == "label-id_prefix-first_name"


def test_initial_is_cached_property():
    form = DummyForm(initial_map={"first_name": "init"})
    bf = BoundField(form, DummyField(), "first_name")
    assert bf.initial == "init"
    assert bf.initial == "init"
    assert len(form.initial_calls) == 1


def test_build_widget_attrs_copies_attrs_and_adds_required_disabled():
    field = DummyField(required=True, disabled=True)
    bf, form, _ = make_boundfield(field=field, form=DummyForm(use_required_attribute=True))
    attrs = {"a": 1}
    out = bf.build_widget_attrs(attrs)
    assert out == {"a": 1, "required": True, "disabled": True}
    assert attrs == {"a": 1}


def test_build_widget_attrs_skips_required_when_widget_disallows_or_form_disallows():
    widget = NoRequiredWidget()
    bf1 = BoundField(DummyForm(use_required_attribute=True), DummyField(widget=widget, required=True), "first_name")
    assert bf1.build_widget_attrs({}) == {}

    widget2 = DummyWidget()
    bf2 = BoundField(DummyForm(use_required_attribute=False), DummyField(widget=widget2, required=True), "first_name")
    assert bf2.build_widget_attrs({}) == {}


def test_widget_type_strips_widget_and_input_suffixes():
    class FancyWidget:
        attrs = {}
        is_hidden = False

        def id_for_label(self, id_):
            return id_

        def use_required_attribute(self, initial):
            return False

    class EmailInput:
        attrs = {}
        is_hidden = False

        def id_for_label(self, id_):
            return id_

        def use_required_attribute(self, initial):
            return False

    bf1 = BoundField(DummyForm(), DummyField(widget=FancyWidget()), "first_name")
    bf2 = BoundField(DummyForm(), DummyField(widget=EmailInput()), "first_name")
    assert bf1.widget_type == "fancy"
    assert bf2.widget_type == "email"


def test_boundwidget_str_tag_template_name_id_and_choice_label():
    parent = DummyWidget()
    data1 = {"attrs": {"id": "x1"}, "label": "LBL"}
    bw1 = BoundWidget(parent, data1, "R")
    assert bw1.template_name == "parent-template"
    assert bw1.id_for_label == "x1"
    assert bw1.choice_label == "LBL"
    assert bw1.tag() == "rendered:parent-template:False:R"
    assert str(bw1) == "rendered:parent-template:True:R"

    data2 = {"attrs": {"id": "x2"}, "label": "LBL2", "template_name": "override"}
    bw2 = BoundWidget(parent, data2, "R2")
    assert bw2.template_name == "override"
