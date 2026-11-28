"""Contract tests for the public resolver and built-in node types."""

from contextlib import closing
from dataclasses import FrozenInstanceError
from pathlib import Path
import sqlite3
import sys
import textwrap
from unittest.mock import Mock

import pytest

from systems.node_types import NodeContext, NodePresentationError, NodeRender, resolve_node_type
from systems.nodes import Nodes


@pytest.fixture
def context(tmp_path):
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        nodes = Nodes(connection)
        yield NodeContext(nodes.create_node(), tmp_path, nodes)


def test_node_context_exposes_nodes_and_is_immutable(context, tmp_path):
    nodes = context.nodes
    assert context.workspace_path == tmp_path
    with pytest.raises(FrozenInstanceError):
        context.node_id = 2

    added = nodes.create_node(title="Created")
    nodes.connect(context.node_id, added)
    assert nodes.outputs(context.node_id) == [added]
    assert nodes.get(added, "title") == "Created"


def test_node_render_is_immutable_and_defaults_to_solid():
    render = NodeRender("Title")
    assert render.title == "Title"
    assert render.border_style == "solid"
    with pytest.raises(FrozenInstanceError):
        render.title = "Changed"


@pytest.mark.parametrize(
    "identifier",
    ["void", "text", "file", "link", "agent", "copy"],
)
def test_resolver_automatically_discovers_builtin_identifiers(identifier: str) -> None:
    assert resolve_node_type(identifier).type == identifier


@pytest.mark.parametrize("inexact", ["Void", "TEXT", " text", "copy "])
def test_resolver_matching_is_exact_and_case_sensitive(inexact: str) -> None:
    assert resolve_node_type(inexact).type == "void"


def test_unknown_identifier_resolves_to_void() -> None:
    assert resolve_node_type("not-installed").type == "void"


def test_import_failures_are_not_converted_to_void(user_type_packages) -> None:
    user_type_packages(
        "broken",
        'raise RuntimeError("sentinel import failure")',
    )

    with pytest.raises(RuntimeError, match="sentinel import failure"):
        resolve_node_type("unknown")


def test_resolution_does_not_invoke_behavior(user_type_packages) -> None:
    user_type_packages(
        "probe",
        """
        class Probe:
            type = "probe"
            def render(self, context):
                raise AssertionError("render invoked during resolution")
            def execute(self, context):
                raise AssertionError("execute invoked during resolution")
        node_type = Probe()
        """,
    )

    assert resolve_node_type("probe").type == "probe"


@pytest.fixture
def user_type_packages(isolated_home):
    root = isolated_home / ".sloon" / "types"
    # Restore the import table after each test that loads user packages.
    previous_modules = set(sys.modules)

    def create(name: str, source: str) -> Path:
        package = root / name
        package.mkdir(parents=True)
        (package / "__init__.py").write_text(textwrap.dedent(source), encoding="utf-8")
        return package

    yield create

    for name, module in list(sys.modules.items()):
        filename = getattr(module, "__file__", None)
        if name not in previous_modules and filename and Path(filename).is_relative_to(root):
            del sys.modules[name]


CUSTOM_TYPE = """
    class Custom:
        type = "Custom"
        def render(self, context):
            raise NotImplementedError
        def execute(self, context):
            raise NotImplementedError
    node_type = Custom()
"""


def test_user_package_and_builtin_resolve_through_same_api(user_type_packages) -> None:
    package = user_type_packages("text", "from .behavior import node_type")
    (package / "behavior.py").write_text(textwrap.dedent(CUSTOM_TYPE), encoding="utf-8")

    assert resolve_node_type("Custom").type == "Custom"
    assert resolve_node_type("text").type == "text"
    assert resolve_node_type("custom") is resolve_node_type("void")
    assert resolve_node_type("unknown") is resolve_node_type("void")


def test_missing_user_directory_is_allowed(isolated_home) -> None:
    assert not (isolated_home / ".sloon" / "types").exists()
    assert resolve_node_type("text").type == "text"
    assert resolve_node_type("unknown") is resolve_node_type("void")


@pytest.mark.parametrize("across_locations", [False, True])
def test_duplicate_user_identifiers_are_rejected(
    user_type_packages, across_locations: bool,
) -> None:
    if across_locations:
        user_type_packages("custom", CUSTOM_TYPE.replace('"Custom"', '"text"'))
        identifier = "text"
    else:
        user_type_packages("first", CUSTOM_TYPE)
        user_type_packages("second", CUSTOM_TYPE)
        identifier = "Custom"

    with pytest.raises(ValueError, match=f"duplicate node type identifier: '{identifier}'"):
        resolve_node_type("unknown")


@pytest.mark.parametrize(
    "source",
    [
        "",
        "node_type = object()",
        CUSTOM_TYPE.replace("def execute", "def other"),
        CUSTOM_TYPE.replace('"Custom"', "42"),
    ],
)
def test_invalid_user_implementation_is_rejected(user_type_packages, source: str) -> None:
    user_type_packages("invalid", source)

    with pytest.raises(TypeError):
        resolve_node_type("unknown")


@pytest.mark.parametrize("type_name", ["void", "future-type"])
def test_void_presentation_and_default_resolution_leave_nodes_unchanged(context, type_name):
    nodes = context.nodes
    nodes.set(context.node_id, "type", type_name)
    nodes.set(context.node_id, "title", "Ignored")

    node_type = resolve_node_type(type_name)
    assert node_type.type == "void"
    assert node_type.render(context) == NodeRender("", "solid")
    assert node_type.execute(context) is None
    assert nodes.list_nodes() == [context.node_id]
    assert nodes.list_edges() == []
    assert nodes.get_all(context.node_id) == {"type": type_name, "title": "Ignored"}


def test_text_renders_current_title_without_mutating_nodes(context):
    nodes = context.nodes
    nodes.set(context.node_id, "param", "Ignored")
    text = resolve_node_type("text")
    assert text.render(context) == NodeRender("")

    for title in ("Before", "After"):
        nodes.set(context.node_id, "title", title)
        assert text.render(context) == NodeRender(title)
        assert nodes.get_all(context.node_id) == {"param": "Ignored", "title": title}
        assert nodes.list_nodes() == [context.node_id]
        assert nodes.list_edges() == []


def test_copy_inherits_current_target_title_without_copying_edges(context):
    nodes = context.nodes
    target = nodes.create_node(type="text", title="Before", note="Keep")
    unrelated = nodes.create_node()
    nodes.connect(unrelated, target)
    nodes.connect(target, unrelated)
    param = "0" * 5000 + str(target)
    nodes.set(context.node_id, "type", "copy")
    nodes.set(context.node_id, "param", param)
    copy = resolve_node_type("copy")

    assert copy.render(context) == NodeRender("Before", "dashed")
    nodes.set(target, "title", "After")
    assert copy.render(context) == NodeRender("After", "dashed")
    assert nodes.list_nodes() == [context.node_id, target, unrelated]
    assert nodes.list_edges() == [(target, unrelated), (unrelated, target)]
    assert nodes.get_all(context.node_id) == {"type": "copy", "param": param}
    assert nodes.get_all(target) == {"type": "text", "title": "After", "note": "Keep"}
    assert nodes.get_all(unrelated) == {}


def test_copy_inherits_title_for_large_id_reported_present_by_nodes(tmp_path):
    target = 2**63
    properties = {
        1: {"type": "copy", "param": str(target)},
        target: {"type": "text", "title": "Large target"},
    }
    nodes = Mock(spec=Nodes, **{
        "node_exists.side_effect": properties.__contains__,
        "get_all.side_effect": properties.__getitem__,
    })

    assert resolve_node_type("copy").render(NodeContext(1, tmp_path, nodes)) == (
        NodeRender("Large target", "dashed")
    )


def test_copy_uses_first_nonempty_title_along_a_chain(context):
    nodes = context.nodes
    target = nodes.create_node(title="Final")
    middle = nodes.create_node(type="copy", param=str(target), title="Middle")
    nodes.set(context.node_id, "type", "copy")
    nodes.set(context.node_id, "param", str(middle))
    copy = resolve_node_type("copy")

    nodes.set(context.node_id, "title", "Own")
    assert copy.render(context) == NodeRender("Own", "dashed")
    nodes.delete_property(context.node_id, "title")
    assert copy.render(context) == NodeRender("Middle", "dashed")
    nodes.delete_property(middle, "title")
    assert copy.render(context) == NodeRender("Final", "dashed")


def test_copy_to_existing_target_without_properties_has_empty_title(context):
    target = context.nodes.create_node()
    context.nodes.set(context.node_id, "type", "copy")
    context.nodes.set(context.node_id, "param", str(target))

    assert resolve_node_type("copy").render(context) == NodeRender("", "dashed")


@pytest.mark.parametrize("param", [None, "", "not-an-id", "0", "-1", "2", str(2**63)],
                         ids=["absent", "empty", "text", "zero", "negative", "missing", "large"])
def test_copy_with_unusable_target_renders_its_own_title(context, param):
    nodes = context.nodes
    nodes.set(context.node_id, "type", "copy")
    nodes.set(context.node_id, "title", "Copy")
    if param is not None:
        nodes.set(context.node_id, "param", param)

    assert resolve_node_type("copy").render(context) == NodeRender("Copy", "dashed")


def test_copy_falls_back_when_decimal_conversion_fails(context):
    nodes = context.nodes
    nodes.set(context.node_id, "type", "copy")
    malformed = "9" * 641
    middle = nodes.create_node(type="copy", param=malformed, title="Inherited")
    nodes.set(context.node_id, "param", str(middle))

    previous_limit = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(640)
    try:
        assert resolve_node_type("copy").render(context) == NodeRender("Inherited", "dashed")
    finally:
        sys.set_int_max_str_digits(previous_limit)
    assert nodes.get(middle, "param") == malformed


def test_copy_stops_at_self_reference(context):
    nodes = context.nodes
    nodes.set(context.node_id, "type", "copy")
    nodes.set(context.node_id, "param", str(context.node_id))

    assert resolve_node_type("copy").render(context) == NodeRender("", "dashed")


def test_copy_stops_at_multi_node_cycle_with_best_available_title(context):
    nodes = context.nodes
    middle = nodes.create_node(type="copy", param=str(context.node_id), title="Middle")
    nodes.set(context.node_id, "type", "copy")
    nodes.set(context.node_id, "param", str(middle))

    assert resolve_node_type("copy").render(context) == NodeRender("Middle", "dashed")


def test_copy_rejects_missing_current_node(context):
    context.nodes.delete_node(context.node_id)
    with pytest.raises(NodePresentationError):
        resolve_node_type("copy").render(context)


def test_container_renders_double_border_and_executes_nothing(context):
    nodes = context.nodes
    nodes.set(context.node_id, "type", "container")
    container = resolve_node_type("container")

    assert container.type == "container"
    assert container.render(context) == NodeRender(title="Container", border_style="double")
    assert container.execute(context) is None
    assert nodes.get_all(context.node_id) == {"type": "container"}
    assert nodes.list_nodes() == [context.node_id]
    assert nodes.list_edges() == []
