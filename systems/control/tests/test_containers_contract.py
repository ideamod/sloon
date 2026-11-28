import asyncio
import sqlite3

import pytest
from textual.widgets import Static

from systems.control import Direction, open_control
from systems.control.app import ControlApp
from systems.graph_ui import open_graph_ui
from systems.node_types import resolve_node_type
from systems.nodes import Nodes


@pytest.fixture
def graph(tmp_path):
    with sqlite3.connect(tmp_path / "workspace.db") as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        nodes = Nodes(connection)
        ui = open_graph_ui(connection)
        control = open_control(nodes, ui, resolve_node_type, workspace_path=tmp_path)
        yield nodes, ui, control
    connection.close()


def test_navigation_keys_enter_empty_container_and_leave_without_quitting(graph):
    nodes, ui, control = graph
    ordinary = nodes.create_node()
    container = nodes.create_node(type="container")
    assert control.select_node(ordinary)

    async def exercise():
        app = ControlApp(control)
        async with app.run_test() as pilot:
            await pilot.press("g", "q")
            assert ui.get_selected_node() == ordinary
            assert ui.get_active_container_id() == ""
            assert control.select_node(container)
            await pilot.press("g")
            assert ui.get_active_container_id() == str(container)
            assert ui.get_selected_node() is None
            assert control.move(Direction.RIGHT) is None
            await pilot.press("q")
            assert ui.get_active_container_id() == ""
            assert ui.get_selected_node() == container
            await pilot.press("t", "g", "q", "enter")
            assert nodes.get(container, "title") == "gq"

    asyncio.run(exercise())


def test_nested_navigation_and_selection_are_scoped_to_the_active_graph(graph):
    nodes, ui, control = graph
    outer = nodes.create_node(type="container")
    inner = nodes.create_node(type="container", container_id=str(outer))
    sibling = nodes.create_node(type="container", container_id=str(outer))
    leaf = nodes.create_node(container_id=str(inner), title="Match leaf")
    outside = nodes.create_node(container_id=str(sibling), title="Match sibling")
    assert not control.select_node(inner)
    assert control.select_node(outer)
    assert control.enter_container()
    assert ui.get_selected_node() is None
    assert control.select_node(inner)
    assert control.enter_container()
    assert ui.get_active_container_id() == str(inner)
    assert control.move(Direction.RIGHT) == leaf
    assert not control.select_node(outside)
    assert [result.node_id for result in control.search_titles("match")] == [leaf]
    assert control.leave_container()
    assert ui.get_active_container_id() == str(outer)
    assert ui.get_selected_node() == inner
    assert control.leave_container()
    assert ui.get_selected_node() == outer


def test_leaving_reveals_exited_container_if_parent_graph_changed(graph):
    nodes, ui, control = graph
    blocker = nodes.create_node()
    container = nodes.create_node(type="container")
    nodes.connect(blocker, container)
    assert control.select_node(container)
    assert control.enter_container()
    ui.set_node_collapsed(blocker, True)
    assert control.leave_container()
    assert ui.get_selected_node() == container
    assert ui.get_collapsed_node_ids() == set()


def test_creation_and_connections_respect_membership(graph):
    nodes, ui, control = graph
    left = nodes.create_node(type="container")
    right = nodes.create_node(type="container")
    sibling_member = nodes.create_node(container_id=str(right))
    root = nodes.create_node()
    assert control.select_node(left)
    assert control.enter_container()

    first = control.create_node()
    output = control.create_output()
    upstream = control.create_input()
    assert all(
        nodes.get(member, "container_id") == str(left)
        for member in (first, output, upstream)
    )
    assert ui.get_selected_node() == upstream
    assert not control.connect(sibling_member)
    assert not control.connect(root)
    assert control.connect(first)
    assert nodes.list_edges() == sorted([
        (first, output), (upstream, output), (upstream, first),
    ])
    ui.select_node(root)
    assert control.create_input() is None
    assert control.create_output() is None


def test_collapse_and_reveal_ignore_cross_container_edges(graph):
    nodes, ui, control = graph
    container = nodes.create_node(type="container")
    external = nodes.create_node()
    root = nodes.create_node(container_id=str(container))
    leaf = nodes.create_node(container_id=str(container))
    nodes.connect(root, leaf)
    nodes.connect(leaf, external)
    assert control.select_node(container)
    assert control.enter_container()
    assert control.select_node(root)
    assert control.toggle_selected_collapse() is True
    assert control.move(Direction.RIGHT) == root
    assert control.select_node(leaf)
    assert ui.get_collapsed_node_ids() == set()
    assert control.toggle_selected_collapse() is None


def test_delete_container_recursively_and_roll_back_on_failure(graph, monkeypatch):
    nodes, ui, control = graph
    predecessor = nodes.create_node()
    container = nodes.create_node(type="container")
    nested = nodes.create_node(type="container", container_id=str(container))
    leaf = nodes.create_node(container_id=str(nested))
    orphan = nodes.create_node(container_id=str(leaf))
    sibling = nodes.create_node(type="container")
    sibling_member = nodes.create_node(container_id=str(sibling))
    nodes.connect(predecessor, container)
    nodes.connect(leaf, sibling_member)
    before_nodes, before_edges = nodes.list_nodes(), nodes.list_edges()

    assert control.select_node(container)
    delete_node = nodes.delete_node
    deleted = []

    def fail_after_second_delete(node_id):
        delete_node(node_id)
        deleted.append(node_id)
        if len(deleted) == 2:
            raise RuntimeError("injected failure")

    with monkeypatch.context() as patch:
        patch.setattr(nodes, "delete_node", fail_after_second_delete)
        with pytest.raises(RuntimeError, match="injected failure"):
            control.delete_selected()
    assert len(deleted) == 2
    assert nodes.list_nodes() == before_nodes
    assert nodes.list_edges() == before_edges
    assert nodes.get(leaf, "container_id") == str(nested)
    assert ui.get_selected_node() == container

    assert control.delete_selected() == container
    assert nodes.list_nodes() == [predecessor, orphan, sibling, sibling_member]
    assert nodes.get(orphan, "container_id") == str(leaf)
    assert ui.get_selected_node() == predecessor
    assert nodes.list_edges() == []


@pytest.mark.parametrize("has_contents", [False, True])
def test_container_type_change_is_rejected_with_feedback(graph, has_contents):
    nodes, _, control = graph
    container = nodes.create_node(type="container", title="Original")
    if has_contents:
        nested = nodes.create_node(type="container", container_id=str(container))
        nodes.create_node(container_id=str(nested), title="Content")
        sibling = nodes.create_node(container_id=str(container))
        nodes.connect(nested, sibling)
    before = {node_id: nodes.get_all(node_id) for node_id in nodes.list_nodes()}
    before_edges = nodes.list_edges()
    assert control.select_node(container)
    assert not control.set_selected_type("text")

    async def exercise():
        app = ControlApp(control)
        async with app.run_test() as pilot:
            await pilot.press(":", *"type text", "enter")
            assert app.query_one("#status", Static).render().plain == (
                "Cannot change a container to another type"
            )

    asyncio.run(exercise())
    assert {node_id: nodes.get_all(node_id) for node_id in nodes.list_nodes()} == before
    assert nodes.list_edges() == before_edges


def test_ordinary_node_can_become_a_container_and_keep_editing_properties(graph):
    nodes, _, control = graph
    node = nodes.create_node(type="text", title="Original", note="Keep this")
    assert control.select_node(node)
    assert control.set_selected_type("container")
    assert control.set_selected_type("container")
    assert nodes.get_all(node) == {
        "type": "container", "title": "Original", "note": "Keep this",
    }
    assert control.set_selected_title("Updated")
    assert nodes.get_all(node) == {
        "type": "container", "title": "Updated", "note": "Keep this",
    }


def test_deep_containment_has_no_recursive_call_limit(graph):
    nodes, ui, control = graph
    with nodes.transaction():
        outermost = nodes.create_node(type="container")
        parent = outermost
        for _ in range(1100):
            parent = nodes.create_node(type="container", container_id=str(parent))
        leaf = nodes.create_node(container_id=str(parent))
    ui.set_active_container_id(str(parent))
    assert control.select_node(leaf)
    assert control.leave_container()
    assert ui.get_selected_node() == parent
    ui.set_active_container_id("")
    assert control.select_node(outermost)
    assert control.delete_selected() == outermost
    assert nodes.list_nodes() == []


def test_malformed_membership_does_not_rewrite_or_delete_nodes(graph):
    nodes, ui, control = graph
    root = nodes.create_node()
    orphan = nodes.create_node(type="container", container_id="missing")
    cyclic = nodes.create_node(type="container")
    nested = nodes.create_node(type="container", container_id=str(cyclic))
    nodes.set(cyclic, "container_id", str(nested))
    before = {node_id: nodes.get_all(node_id) for node_id in nodes.list_nodes()}

    for invalid in ("not an ID", str(root), str(orphan), str(cyclic)):
        ui.set_active_container_id(invalid)
        ui.select_node(cyclic)
        assert control.delete_selected() is None
        assert control.move(Direction.RIGHT) == root
        assert ui.get_active_container_id() == invalid
        assert control.leave_container()
        assert ui.get_active_container_id() == ""
        assert ui.get_selected_node() is None
    assert {node_id: nodes.get_all(node_id) for node_id in nodes.list_nodes()} == before
