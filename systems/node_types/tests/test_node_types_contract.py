"""Contract tests for the extensible Node Types system."""

from __future__ import annotations

import importlib
import sys
import textwrap
from dataclasses import FrozenInstanceError, dataclass, fields
from pathlib import Path
from typing import Any

import pytest

from systems.node_types.impl import resolver as resolver_module
from systems.node_types.impl import types as types_package
from systems.node_types.spec.api import (
    NodeContext,
    NodePresentationError,
    NodeRender,
)


@dataclass(frozen=True)
class NodeAssignment:
    type: str
    param: str
    title: str = ""
    status: str = "none"
    note: str = ""
    tags: str = ""
    weight: int = 0


class MemoryGraph:
    """Minimal in-memory implementation of the public Graph contract."""

    def __init__(self, *node_ids: int) -> None:
        self.nodes = set(node_ids)
        self.edges: set[tuple[int, int]] = set()
        self.next_id = max(self.nodes, default=0) + 1

    def add_node(self) -> int:
        node_id = self.next_id
        self.next_id += 1
        self.nodes.add(node_id)
        return node_id

    def get_node(self, node_id: int) -> int | None:
        return node_id if node_id in self.nodes else None

    def get_nodes(self) -> list[int]:
        return sorted(self.nodes)

    def delete_node(self, node_id: int) -> None:
        self.nodes.discard(node_id)
        self.edges = {
            edge for edge in self.edges if node_id not in edge
        }

    def add_edge(self, source: int, target: int) -> None:
        if source not in self.nodes or target not in self.nodes:
            raise ValueError("graph node does not exist")
        self.edges.add((source, target))

    def delete_edge(self, source: int, target: int) -> None:
        self.edges.discard((source, target))

    def get_edges(self) -> list[tuple[int, int]]:
        return sorted(self.edges)

    def get_inputs(self, node_id: int) -> list[int]:
        return sorted(source for source, target in self.edges if target == node_id)

    def get_outputs(self, node_id: int) -> list[int]:
        return sorted(target for source, target in self.edges if source == node_id)

    def snapshot(self) -> tuple[set[int], set[tuple[int, int]], int]:
        return self.nodes.copy(), self.edges.copy(), self.next_id


class MemoryAssignments:
    """Minimal in-memory implementation of the Node Assignments contract."""

    def __init__(self, graph: MemoryGraph) -> None:
        self.graph = graph
        self.records: dict[int, NodeAssignment] = {}

    def get(self, node_id: int) -> NodeAssignment | None:
        if self.graph.get_node(node_id) is None:
            raise ValueError(f"graph node does not exist: {node_id!r}")
        return self.records.get(node_id)

    def set(
        self,
        node_id: int,
        type: str,
        param: str,
        title: str | None = None,
        status: str | None = None,
        note: str | None = None,
        tags: str | None = None,
        weight: int | None = None,
    ) -> None:
        if self.graph.get_node(node_id) is None:
            raise ValueError(f"graph node does not exist: {node_id!r}")
        if not isinstance(type, str) or not type:
            raise ValueError("type must be a non-empty string")
        if not isinstance(param, str):
            raise ValueError("param must be a string")
        if title is not None and not isinstance(title, str):
            raise ValueError("title must be a string")
        if status is not None and status not in {
            "none", "progress", "success", "warning", "failure"
        }:
            raise ValueError("status is invalid")
        if note is not None and not isinstance(note, str):
            raise ValueError("note must be a string")
        if tags is not None and not isinstance(tags, str):
            raise ValueError("tags must be a string")
        if weight is not None and (
            not isinstance(weight, int) or isinstance(weight, bool)
        ):
            raise ValueError("weight must be an integer")
        previous = self.records.get(node_id)
        stored_title = previous.title if title is None and previous else title or ""
        stored_status = (
            previous.status
            if status is None and previous
            else status or "none"
        )
        stored_note = previous.note if note is None and previous else note or ""
        stored_tags = previous.tags if tags is None and previous else tags or ""
        stored_weight = previous.weight if weight is None and previous else weight or 0
        self.records[node_id] = NodeAssignment(
            type, param, stored_title, stored_status, stored_note, stored_tags, stored_weight
        )

    def delete(self, node_id: int) -> None:
        self.records.pop(node_id, None)

    def snapshot(self) -> dict[int, NodeAssignment]:
        return self.records.copy()


def assignment_properties(value: NodeAssignment) -> dict[str, object]:
    return {
        "type": value.type, "title": value.title, "param": value.param,
        "status": value.status, "note": value.note, "tags": value.tags,
        "weight": value.weight,
    }


class MemoryNodes:
    def __init__(self, graph: MemoryGraph, assignments: MemoryAssignments) -> None:
        self.graph = graph
        self.assignments = assignments

    def create_node(self, **fields) -> int:
        node_id = self.graph.add_node()
        if fields:
            current = NodeAssignment("void", "")
            values = assignment_properties(current) | fields
            self.assignments.set(node_id, values["type"], values["param"], values["title"], values["status"], values["note"], values["tags"], values["weight"])
        return node_id

    def node_exists(self, node_id: int) -> bool:
        return self.graph.get_node(node_id) is not None

    def list_nodes(self) -> list[int]:
        return self.graph.get_nodes()

    def connect(self, source: int, target: int) -> None:
        self.graph.add_edge(source, target)

    def outputs(self, node_id: int) -> list[int]:
        return self.graph.get_outputs(node_id)

    def get_all(self, node_id: int) -> dict[str, object]:
        value = self.assignments.get(node_id) or NodeAssignment("void", "")
        return assignment_properties(value)

    def set(self, node_id: int, key: str, value: object) -> None:
        values = self.get_all(node_id)
        values[key] = value
        self.assignments.set(node_id, values["type"], values["param"], values["title"], values["status"], values["note"], values["tags"], values["weight"])


def resolve(type_name: str) -> Any:
    return resolver_module.resolve_node_type(type_name)


def make_context(
    assignment: NodeAssignment,
    *,
    node_id: int = 1,
    other_nodes: tuple[int, ...] = (),
) -> tuple[NodeContext, MemoryGraph, MemoryAssignments]:
    graph = MemoryGraph(node_id, *other_nodes)
    assignments = MemoryAssignments(graph)
    assignments.set(
        node_id,
        assignment.type,
        assignment.param,
        assignment.title,
        assignment.status,
        assignment.note,
        assignment.tags,
        assignment.weight,
    )
    context = NodeContext(
        node_id, Path("/test.sloon"), assignment_properties(assignment),
        MemoryNodes(graph, assignments),
    )
    return context, graph, assignments


def unload_discovered_types() -> None:
    prefix = "systems.node_types.impl.types."
    for module_name in list(sys.modules):
        if module_name.startswith(prefix):
            del sys.modules[module_name]


@pytest.fixture
def isolated_type_packages(tmp_path: Path):
    """Discover only packages created below a temporary types directory."""

    original_path = list(types_package.__path__)
    types_package.__path__ = [str(tmp_path)]
    unload_discovered_types()
    importlib.invalidate_caches()
    importlib.reload(resolver_module)

    def create(name: str, source: str = "") -> None:
        package = tmp_path / name
        package.mkdir()
        (package / "__init__.py").write_text(
            textwrap.dedent(source),
            encoding="utf-8",
        )
        importlib.invalidate_caches()

    yield create

    types_package.__path__ = original_path
    unload_discovered_types()
    importlib.invalidate_caches()
    importlib.reload(resolver_module)


def test_node_context_has_required_immutable_fields() -> None:
    assignment = NodeAssignment("text", "body", "Title")
    context, graph, assignments = make_context(assignment)

    assert [field.name for field in fields(NodeContext)] == [
        "node_id",
        "workspace_path",
        "properties",
        "nodes",
    ]
    assert context.node_id == 1
    assert context.workspace_path == Path("/test.sloon")
    assert context.workspace_path.is_absolute()
    assert context.properties == assignment_properties(assignment)
    assert isinstance(context.nodes, MemoryNodes)
    with pytest.raises(FrozenInstanceError):
        context.node_id = 2  # type: ignore[misc]


def test_node_context_exposes_full_public_apis() -> None:
    context, _, _ = make_context(NodeAssignment("text", "", "Title"))

    added = context.nodes.create_node(type="custom", param="parameter", title="Custom")
    context.nodes.connect(context.node_id, added)

    assert context.nodes.list_nodes() == [1, added]
    assert context.nodes.outputs(1) == [added]
    assert context.nodes.get_all(added)["type"] == "custom"


def test_node_context_assignments_can_read_and_update_status() -> None:
    context, _, assignments = make_context(
        NodeAssignment(
            "text", "", "Title", "progress", "Keep note", "keep, tags"
        )
    )

    assert context.nodes.get_all(context.node_id)["status"] == "progress"
    context.nodes.set(context.node_id, "status", "success")

    assert assignments.get(context.node_id) == NodeAssignment(
        "text", "", "Title", "success", "Keep note", "keep, tags"
    )


def test_node_context_assignments_can_read_and_update_note() -> None:
    context, _, assignments = make_context(
        NodeAssignment(
            "text", "", "Title", "progress", "Before", "keep, tags"
        )
    )

    assert context.properties["note"] == "Before"
    context.nodes.set(context.node_id, "note", "  After\n😀  ")

    assert assignments.get(context.node_id) == NodeAssignment(
        "text", "", "Title", "progress", "  After\n😀  ", "keep, tags"
    )


def test_node_context_assignments_can_read_and_update_tags() -> None:
    context, _, assignments = make_context(
        NodeAssignment("text", "", "Title", "progress", "Note", "before")
    )

    assert context.properties["tags"] == "before"
    context.nodes.set(context.node_id, "tags", "  python, café, 😀  ")

    assert assignments.get(context.node_id) == NodeAssignment(
        "text", "", "Title", "progress", "Note", "  python, café, 😀  "
    )


def test_node_context_assignments_expose_and_preserve_weight() -> None:
    context, _, assignments = make_context(
        NodeAssignment("text", "", "Title", weight=-7)
    )

    assert context.properties["weight"] == -7
    context.nodes.set(context.node_id, "param", "changed")

    assert assignments.get(context.node_id) == NodeAssignment(
        "text", "changed", "Title", weight=-7
    )


def test_node_render_has_required_immutable_fields_and_solid_default() -> None:
    render = NodeRender("Title")

    assert [field.name for field in fields(NodeRender)] == [
        "title",
        "border_style",
    ]
    assert render.title == "Title"
    assert render.border_style == "solid"
    with pytest.raises(FrozenInstanceError):
        render.title = "Changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "identifier",
    ["void", "text", "file", "link", "agent", "copy"],
)
def test_resolver_automatically_discovers_builtin_identifiers(identifier: str) -> None:
    assert resolve(identifier).type == identifier


@pytest.mark.parametrize("inexact", ["Void", "TEXT", " text", "copy "])
def test_resolver_matching_is_exact_and_case_sensitive(inexact: str) -> None:
    assert resolve(inexact).type == "void"


def test_unknown_identifier_resolves_to_void() -> None:
    assert resolve("not-installed").type == "void"


def test_duplicate_identifiers_are_rejected(isolated_type_packages) -> None:
    source = """
        class Duplicate:
            type = "duplicate"
            def render(self, context):
                raise NotImplementedError
            def execute(self, context):
                raise NotImplementedError
        node_type = Duplicate()
    """
    isolated_type_packages("first", source)
    isolated_type_packages("second", source)

    with pytest.raises(Exception):
        resolve("duplicate")


@pytest.mark.parametrize(
    "source",
    [
        "",
        "node_type = object()",
        """
        class MissingExecute:
            type = "invalid"
            def render(self, context):
                raise NotImplementedError
        node_type = MissingExecute()
        """,
        """
        class Invalid:
            type = 42
            def render(self, context):
                raise NotImplementedError
            def execute(self, context):
                raise NotImplementedError
        node_type = Invalid()
        """,
    ],
)
def test_invalid_implementations_are_rejected(
    isolated_type_packages,
    source: str,
) -> None:
    isolated_type_packages("invalid", source)

    with pytest.raises(Exception):
        resolve("invalid")


def test_import_failures_are_not_converted_to_void(isolated_type_packages) -> None:
    isolated_type_packages(
        "broken",
        'raise RuntimeError("sentinel import failure")',
    )

    with pytest.raises(RuntimeError, match="sentinel import failure"):
        resolve("unknown")


def test_resolution_does_not_invoke_behavior(isolated_type_packages) -> None:
    isolated_type_packages(
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

    assert resolve("probe").type == "probe"


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

    assert resolve("Custom").type == "Custom"
    assert resolve("text").type == "text"
    assert resolve("custom") is resolve("void")
    assert resolve("unknown") is resolve("void")


def test_missing_user_directory_is_allowed(isolated_home) -> None:
    assert not (isolated_home / ".sloon" / "types").exists()
    assert resolve("text").type == "text"
    assert resolve("unknown") is resolve("void")


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
        resolve("unknown")


@pytest.mark.parametrize(
    "source", ["", "node_type = object()", CUSTOM_TYPE.replace("def execute", "def other")],
)
def test_invalid_user_implementation_is_rejected(user_type_packages, source: str) -> None:
    user_type_packages("invalid", source)

    with pytest.raises(TypeError):
        resolve("unknown")



class MutatingTestType:
    type = "test-mutation"

    def render(self, context: NodeContext) -> NodeRender:
        return NodeRender(str(context.properties["title"]))

    def execute(self, context: NodeContext) -> None:
        context.nodes.create_node(type="created-by-test", param="parameter", title="Created")


def test_execution_occurs_only_when_explicitly_invoked() -> None:
    context, graph, assignments = make_context(
        NodeAssignment("test-mutation", "", "Test")
    )
    node_type = MutatingTestType()

    node_type.render(context)

    assert graph.get_nodes() == [1]
    assert assignment_properties(assignments.get(1)) == context.properties


def test_execution_can_mutate_graph_and_assignments_through_context() -> None:
    context, graph, assignments = make_context(
        NodeAssignment("test-mutation", "", "Test")
    )

    MutatingTestType().execute(context)

    assert graph.get_nodes() == [1, 2]
    assert assignments.get(2) == NodeAssignment(
        "created-by-test", "parameter", "Created"
    )


def test_execution_errors_propagate() -> None:
    class FailingTestType:
        type = "test-failure"

        def render(self, context: NodeContext) -> NodeRender:
            return NodeRender("")

        def execute(self, context: NodeContext) -> None:
            raise RuntimeError("execution failed")

    context, _, _ = make_context(NodeAssignment("test-failure", "", ""))

    with pytest.raises(RuntimeError, match="execution failed"):
        FailingTestType().execute(context)


def test_void_resolves_and_renders_empty_solid() -> None:
    context, _, _ = make_context(NodeAssignment("void", "ignored", "Ignored"))

    assert resolve("void").render(context) == NodeRender("", "solid")


def test_void_execute_is_no_op() -> None:
    context, graph, assignments = make_context(NodeAssignment("void", "", ""))
    graph_before = graph.snapshot()
    assignments_before = assignments.snapshot()

    result = resolve("void").execute(context)

    assert result is None
    assert graph.snapshot() == graph_before
    assert assignments.snapshot() == assignments_before


def test_unknown_falls_back_to_void_without_changing_assignment() -> None:
    assignment = NodeAssignment("future-type", "opaque", "Future")
    context, _, assignments = make_context(assignment)

    render = resolve(assignment.type).render(context)

    assert render == NodeRender("", "solid")
    assert context.properties == assignment_properties(assignment)
    assert assignments.get(1) == assignment


def test_text_resolves_and_renders_assignment_title_solid() -> None:
    assignment = NodeAssignment("text", "ignored body", "Text title")
    context, _, _ = make_context(assignment)

    assert resolve("text").render(context) == NodeRender("Text title", "solid")


def test_text_render_does_not_mutate_persistent_apis() -> None:
    context, graph, assignments = make_context(
        NodeAssignment("text", "body", "Text title")
    )
    graph_before = graph.snapshot()
    assignments_before = assignments.snapshot()

    resolve("text").render(context)

    assert graph.snapshot() == graph_before
    assert assignments.snapshot() == assignments_before


def copy_context(
    target_assignment: NodeAssignment | None,
    copy_title: str = "",
) -> tuple[NodeContext, MemoryGraph, MemoryAssignments]:
    copy = NodeAssignment("copy", "2", copy_title)
    context, graph, assignments = make_context(copy, other_nodes=(2,))
    if target_assignment is not None:
        assignments.set(
            2,
            target_assignment.type,
            target_assignment.param,
            target_assignment.title,
        )
    return context, graph, assignments


def test_copy_renders_direct_target_title_with_dashed_border() -> None:
    context, _, _ = copy_context(NodeAssignment("text", "body", "Target"))

    assert resolve("copy").render(context) == NodeRender("Target", "dashed")


def test_copy_inherits_title_for_large_id_reported_present_by_nodes() -> None:
    target = 2**63
    context, _, assignments = make_context(
        NodeAssignment("copy", str(target)), other_nodes=(target,)
    )
    assignments.set(target, "text", "", "Large target")

    assert resolve("copy").render(context) == NodeRender("Large target", "dashed")


def test_copy_falls_back_when_decimal_conversion_fails() -> None:
    previous_limit = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(640)
    try:
        context, _, _ = make_context(NodeAssignment("copy", "9" * 641, "Copy"))
        assert resolve("copy").render(context) == NodeRender("Copy", "dashed")
    finally:
        sys.set_int_max_str_digits(previous_limit)


def test_copy_preserves_its_own_title() -> None:
    context, _, _ = copy_context(
        NodeAssignment("text", "body", "Target"),
        copy_title="Copy title",
    )

    assert resolve("copy").render(context) == NodeRender("Copy title", "dashed")


def test_copy_follows_multiple_copy_levels() -> None:
    context, graph, assignments = copy_context(NodeAssignment("copy", "3", "Middle"))
    graph.nodes.add(3)
    assignments.set(3, "text", "body", "Final")

    assert resolve("copy").render(context) == NodeRender("Middle", "dashed")


def test_copy_reflects_updated_target_title() -> None:
    context, _, assignments = copy_context(
        NodeAssignment("text", "body", "Before")
    )
    assert resolve("copy").render(context) == NodeRender("Before", "dashed")

    assignments.set(2, "text", "body", "After")

    assert resolve("copy").render(context) == NodeRender("After", "dashed")


def test_copy_to_existing_unassigned_target_uses_void_presentation() -> None:
    context, _, _ = copy_context(None)

    assert resolve("copy").render(context) == NodeRender("", "dashed")


def test_copy_with_missing_target_node_renders_its_own_presentation() -> None:
    assignment = NodeAssignment("copy", "2", "Copy")
    context, _, _ = make_context(assignment)

    assert resolve("copy").render(context) == NodeRender("Copy", "dashed")


@pytest.mark.parametrize("param", ["", "not-an-id", "0", "-1"])
def test_copy_with_invalid_target_id_renders_its_own_presentation(
    param: str,
) -> None:
    context, _, _ = make_context(NodeAssignment("copy", param, "Copy"))

    assert resolve("copy").render(context) == NodeRender("Copy", "dashed")


def test_copy_with_self_reference_renders_its_own_presentation() -> None:
    context, _, _ = make_context(NodeAssignment("copy", "1", "Copy"))

    assert resolve("copy").render(context) == NodeRender("Copy", "dashed")


def test_copy_with_multi_node_cycle_renders_best_available_title() -> None:
    context, _, assignments = copy_context(NodeAssignment("copy", "3", "Second"))
    assignments.graph.nodes.add(3)
    assignments.set(3, "copy", "1", "Third")

    assert resolve("copy").render(context) == NodeRender("Second", "dashed")


def test_copy_rejects_missing_current_graph_node() -> None:
    graph = MemoryGraph(2)
    assignments = MemoryAssignments(graph)
    current = NodeAssignment("copy", "2", "Copy")
    assignments.set(2, "text", "body", "Target")
    context = NodeContext(
        1, Path("/test.sloon"), assignment_properties(current),
        MemoryNodes(graph, assignments),
    )

    with pytest.raises(NodePresentationError):
        resolve("copy").render(context)


def test_copy_render_does_not_mutate_graph_or_assignments() -> None:
    context, graph, assignments = copy_context(
        NodeAssignment("text", "body", "Target")
    )
    graph_before = graph.snapshot()
    assignments_before = assignments.snapshot()

    resolve("copy").render(context)

    assert graph.snapshot() == graph_before
    assert assignments.snapshot() == assignments_before


def test_copy_does_not_inherit_target_graph_edges() -> None:
    context, graph, assignments = copy_context(
        NodeAssignment("text", "body", "Target")
    )
    unrelated = graph.add_node()
    graph.add_edge(unrelated, 2)
    graph.add_edge(2, unrelated)
    graph_before = graph.snapshot()
    assignments_before = assignments.snapshot()

    render = resolve("copy").render(context)

    assert render == NodeRender("Target", "dashed")
    assert graph.get_inputs(1) == []
    assert graph.get_outputs(1) == []
    assert graph.snapshot() == graph_before
    assert assignments.snapshot() == assignments_before
