import json
import sqlite3
from unittest.mock import Mock

import pytest

from systems.control import open_control
from systems.graph_ui import open_graph_ui
from systems.nodes import Nodes


PROPERTIES = {
    "type": "custom-type",
    "title": "",
    "note": "first line\n第二行",
    "custom.key": "",
    "self": "valid property name",
    " version ": "exact whitespace ",
}


@pytest.fixture
def open_workspace(tmp_path):
    connections = []

    def open_workspace(name: str):
        path = tmp_path / name
        path.mkdir()
        connection = sqlite3.connect(path / "workspace.db")
        connections.append(connection)
        connection.execute("PRAGMA foreign_keys = ON")
        nodes = Nodes(connection)
        graph_ui = open_graph_ui(connection)
        control = open_control(nodes, graph_ui, Mock(), workspace_path=path)
        return nodes, graph_ui, control

    yield open_workspace

    for connection in connections:
        connection.close()


def snapshot(nodes):
    return {node_id: nodes.get_all(node_id) for node_id in nodes.list_nodes()}, nodes.list_edges()


def test_copy_serializes_exact_properties_without_changes(open_workspace):
    nodes, graph_ui, control = open_workspace("source.sloon")
    upstream = nodes.create_node()
    source = nodes.create_node()
    downstream = nodes.create_node()
    for key, value in PROPERTIES.items():
        nodes.set(source, key, value)
    nodes.connect(upstream, source)
    nodes.connect(source, downstream)
    graph_ui.select_node(source)
    graph_ui.set_node_collapsed(source, True)
    before = snapshot(nodes)

    assert json.loads(control.copy_selected()) == {
        "format": "sloon-node",
        "version": 1,
        "properties": PROPERTIES,
    }
    assert snapshot(nodes) == before
    assert graph_ui.get_selected_node() == source
    assert graph_ui.get_collapsed_node_ids() == {source}


def test_paste_adds_one_output_and_preserves_graph_selection_and_clipboard(open_workspace):
    nodes, graph_ui, control = open_workspace("same.sloon")
    source = nodes.create_node(title="Example")
    parent = nodes.create_node(title="Destination")
    neighbor = nodes.create_node(title="Neighbor")
    nodes.connect(neighbor, source)
    nodes.connect(source, neighbor)
    nodes.connect(parent, neighbor)
    graph_ui.select_node(source)
    clipboard = control.copy_selected()
    graph_ui.select_node(parent)
    original_nodes, original_edges = snapshot(nodes)

    for _ in range(2):
        new_id = control.paste_selected(clipboard)
        assert new_id not in original_nodes
        original_nodes[new_id] = {"title": "Example"}
        original_edges = sorted([*original_edges, (parent, new_id)])
        assert snapshot(nodes) == (original_nodes, original_edges)
        assert graph_ui.get_selected_node() == parent


def test_paste_into_another_workspace_after_source_changes_and_is_deleted(open_workspace):
    source_nodes, source_ui, source_control = open_workspace("source.sloon")
    target_nodes, target_ui, target_control = open_workspace("target.sloon")
    source = source_nodes.create_node()
    for key, value in PROPERTIES.items():
        source_nodes.set(source, key, value)
    source_ui.select_node(source)
    target = target_nodes.create_node(title="Target")
    target_ui.select_node(target)

    clipboard = source_control.copy_selected()
    source_nodes.set(source, "note", "changed")
    first_copy = target_control.paste_selected(clipboard)
    source_nodes.delete_node(source)
    second_copy = target_control.paste_selected(clipboard)

    assert target_nodes.get_all(first_copy) == PROPERTIES
    assert target_nodes.get_all(second_copy) == PROPERTIES
    assert snapshot(target_nodes) == (
        {target: {"title": "Target"}, first_copy: PROPERTIES, second_copy: PROPERTIES},
        [(target, first_copy), (target, second_copy)],
    )
    assert source_nodes.list_nodes() == []


def test_empty_properties_are_a_valid_copy_and_paste(open_workspace):
    nodes, graph_ui, control = open_workspace("empty.sloon")
    selected = nodes.create_node()
    graph_ui.select_node(selected)

    new_id = control.paste_selected(control.copy_selected())

    assert nodes.get_all(new_id) == {}
    assert nodes.list_edges() == [(selected, new_id)]


@pytest.mark.parametrize("clipboard", [
    "", "free text", "{", "null", "{}", "[]",
    '{"format":"other","version":1,"properties":{}}',
    '{"format":"sloon-node","version":2,"properties":{}}',
    '{"format":"sloon-node","version":true,"properties":{}}',
    '{"format":"sloon-node","version":1.0,"properties":{}}',
    '{"format":"sloon-node","version":1,"properties":[]}',
    '{"format":"sloon-node","version":1,"properties":{"":"value"}}',
    '{"format":"sloon-node","version":1,"properties":{"count":1}}',
    '{"format":"sloon-node","version":1,"properties":{"key":"a","key":"b"}}',
    '{"format":"sloon-node","version":1,"properties":{},"node_id":1}',
    r'{"format":"sloon-node","version":1,"properties":{"key":"\ud800"}}',
])
def test_invalid_clipboard_contents_leave_graph_unchanged(open_workspace, clipboard):
    nodes, graph_ui, control = open_workspace("invalid.sloon")
    selected = nodes.create_node(title="Destination")
    graph_ui.select_node(selected)
    before = snapshot(nodes)

    assert control.paste_selected(clipboard) is None

    assert snapshot(nodes) == before
    assert graph_ui.get_selected_node() == selected


@pytest.mark.parametrize("stale_selection", [False, True])
def test_copy_and_paste_require_an_existing_selection(open_workspace, stale_selection):
    nodes, graph_ui, control = open_workspace("missing-selection.sloon")
    node = nodes.create_node(title="Example")
    clipboard = '{"format":"sloon-node","version":1,"properties":{}}'
    if stale_selection:
        graph_ui.select_node(node)
        nodes.delete_node(node)
    before = snapshot(nodes)

    assert control.copy_selected() is None
    assert control.paste_selected(clipboard) is None
    assert snapshot(nodes) == before


def test_paste_rolls_back_new_node_properties_and_edge_after_failure(open_workspace, monkeypatch):
    nodes, graph_ui, control = open_workspace("atomic.sloon")
    selected = nodes.create_node(title="Example")
    graph_ui.select_node(selected)
    clipboard = control.copy_selected()
    before = snapshot(nodes)
    connect = nodes.connect

    def fail_after_connect(source, target):
        connect(source, target)
        raise RuntimeError("simulated edge failure")

    with monkeypatch.context() as patch:
        patch.setattr(nodes, "connect", fail_after_connect)
        with pytest.raises(RuntimeError, match="simulated edge failure"):
            control.paste_selected(clipboard)
        assert snapshot(nodes) == before

    new_id = control.paste_selected(clipboard)
    assert nodes.get_all(new_id) == {"title": "Example"}
    assert nodes.list_edges() == [(selected, new_id)]
