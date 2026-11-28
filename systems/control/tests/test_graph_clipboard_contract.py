import json
import sqlite3

import pytest

from systems.control import open_control
from systems.graph_ui import open_graph_ui
from systems.node_types import resolve_node_type
from systems.nodes import Nodes


@pytest.fixture
def open_workspace(tmp_path):
    connections = []

    def open_workspace(name):
        path = tmp_path / name
        path.mkdir()
        connection = sqlite3.connect(path / "workspace.db")
        connections.append(connection)
        connection.execute("PRAGMA foreign_keys = ON")
        nodes = Nodes(connection)
        ui = open_graph_ui(connection)
        control = open_control(nodes, ui, resolve_node_type, workspace_path=path)
        return nodes, ui, control

    yield open_workspace

    for connection in connections:
        connection.close()


def snapshot(nodes):
    return {node_id: nodes.get_all(node_id) for node_id in nodes.list_nodes()}, nodes.list_edges()


def test_single_node_copy_preserves_exact_properties_without_copying_edges(open_workspace):
    nodes, ui, control = open_workspace("single.sloon")
    source = nodes.create_node()
    properties = {
        "type": "copy",
        "param": "003",
        "note": "first line\n第二行",
        "custom.key": "",
        "self": "valid property name",
        " version ": "exact whitespace ",
    }
    for key, value in properties.items():
        nodes.set(source, key, value)
    upstream = nodes.create_node()
    downstream = nodes.create_node()
    nodes.connect(upstream, source)
    nodes.connect(source, downstream)
    ui.select_node(source)
    ui.set_node_collapsed(upstream, True)
    before = snapshot(nodes)

    clipboard = control.copy_selected()
    assert json.loads(clipboard) == {
        "format": "sloon-graph-fragment",
        "version": 1,
        "root": source,
        "nodes": [{"id": source, "properties": properties}],
        "edges": [],
    }
    assert snapshot(nodes) == before
    assert ui.get_selected_node() == source
    assert ui.get_collapsed_node_ids() == {upstream}

    ui.select_node(downstream)
    pasted = control.paste_selected(clipboard)
    assert nodes.get_all(pasted) == properties
    assert nodes.list_edges() == sorted([*before[1], (downstream, pasted)])
    assert ui.get_selected_node() == downstream


def test_tree_copies_hidden_shared_descendants_and_only_internal_edges(open_workspace):
    nodes, ui, control = open_workspace("tree.sloon")
    container = nodes.create_node(type="container")
    ui.set_active_container_id(str(container))
    blocker = nodes.create_node(container_id=str(container))
    left = nodes.create_node(container_id=str(container), title="Left")
    right = nodes.create_node(container_id=str(container), title="Right")
    shared = nodes.create_node(container_id=str(container), title="Shared")
    root = nodes.create_node(container_id=str(container))
    external = nodes.create_node()
    internal_edges = [(root, left), (root, right), (left, shared), (right, shared)]
    for source, target in [*internal_edges, (blocker, root), (left, external), (external, shared)]:
        nodes.connect(source, target)
    ui.select_node(root)
    ui.set_node_collapsed(blocker, True)
    ui.set_node_collapsed(left, True)
    before = snapshot(nodes)

    fragment = json.loads(control.copy_selected(include_outputs=True))

    assert fragment["root"] == root
    assert sorted(record["id"] for record in fragment["nodes"]) == [left, right, shared, root]
    assert {tuple(edge) for edge in fragment["edges"]} == set(internal_edges)
    assert snapshot(nodes) == before
    assert ui.get_collapsed_node_ids() == {blocker, left}
    assert ui.get_selected_node() == root

    clipboard = json.dumps(fragment)
    ui.set_active_container_id("")
    ui.select_node(external)
    pasted = control.paste_selected(clipboard)
    children = {nodes.get(node_id, "title"): node_id for node_id in nodes.outputs(pasted)}
    assert children.keys() == {"Left", "Right"}
    [new_shared] = nodes.outputs(children["Left"])
    assert nodes.outputs(children["Right"]) == [new_shared]
    assert nodes.get_all(new_shared) == {"title": "Shared"}
    assert nodes.get_all(pasted) == {}
    assert nodes.outputs(external) == sorted([shared, pasted])


def test_empty_container_uses_the_same_fragment_format(open_workspace):
    nodes, ui, control = open_workspace("empty.sloon")
    container = nodes.create_node(type="container")
    ui.select_node(container)
    clipboard = control.copy_selected()

    assert json.loads(clipboard)["nodes"] == [
        {"id": container, "properties": {"type": "container"}},
    ]
    pasted = control.paste_selected(clipboard)
    assert nodes.get_all(pasted) == {"type": "container"}
    assert nodes.list_nodes() == [container, pasted]
    assert nodes.list_edges() == [(container, pasted)]


@pytest.mark.parametrize(("include_outputs", "nested_destination"), [(False, False), (True, True)])
def test_container_fragment_pastes_independent_copies_in_another_workspace(
    open_workspace, include_outputs, nested_destination,
):
    source, source_ui, source_control = open_workspace("source.sloon")
    source_parent = source.create_node(type="container")
    source_ui.set_active_container_id(str(source_parent))
    outer = source.create_node(type="container", container_id=str(source_parent), title="Outer")
    nested = source.create_node(type="container", container_id=str(outer), title="Nested")
    copy = source.create_node(
        type="copy", container_id=str(nested), param=str(nested), note="  雪\n",
    )
    nested_peer = source.create_node(container_id=str(nested), title="Peer")
    disconnected = source.create_node(container_id=str(outer), title="Disconnected")
    neighbor = source.create_node(container_id=str(source_parent), title="Next")
    unrelated = source.create_node(container_id=str(source_parent), title="Referenced only")
    source.set(copy, "reference", str(unrelated))
    source.connect(copy, nested_peer)
    source.connect(outer, neighbor)
    source.connect(disconnected, neighbor)
    source_ui.select_node(outer)
    clipboard = source_control.copy_selected(include_outputs=include_outputs)
    fragment = json.loads(clipboard)
    expected_ids = {outer, nested, copy, nested_peer, disconnected}
    expected_edges = {(copy, nested_peer)}
    if include_outputs:
        expected_ids.add(neighbor)
        expected_edges.add((outer, neighbor))
    assert {record["id"] for record in fragment["nodes"]} == expected_ids
    assert {tuple(edge) for edge in fragment["edges"]} == expected_edges
    assert source_control.delete_selected() == outer

    target, target_ui, target_control = open_workspace("target.sloon")
    parent = target.create_node(type="container")
    destination_container = target.create_node(type="container", container_id=str(parent))
    destination_properties = {"title": "Destination"}
    if nested_destination:
        destination_properties["container_id"] = str(destination_container)
        target_ui.set_active_container_id(str(destination_container))
    destination = target.create_node(**destination_properties)
    target_ui.select_node(destination)
    target_ui.set_node_collapsed(destination, True)
    top_membership = {"container_id": str(destination_container)} if nested_destination else {}
    copied_roots = []

    for _ in range(2):
        existing, edges = snapshot(target)
        pasted = target_control.paste_selected(clipboard)
        records, updated_edges = snapshot(target)
        new = {node_id: props for node_id, props in records.items() if node_id not in existing}
        assert len(new) == len(expected_ids)
        assert {node_id: records[node_id] for node_id in existing} == existing
        assert new[pasted] == {"type": "container", "title": "Outer", **top_membership}
        by_title = {props.get("title"): node_id for node_id, props in new.items()}
        pasted_nested = by_title["Nested"]
        pasted_copy = by_title[None]
        pasted_peer = by_title["Peer"]
        assert pasted_nested != nested
        assert new[pasted_nested] == {
            "type": "container", "title": "Nested", "container_id": str(pasted),
        }
        assert new[pasted_copy] == {
            "type": "copy", "param": str(nested), "note": "  雪\n",
            "reference": str(unrelated), "container_id": str(pasted_nested),
        }
        assert new[pasted_peer] == {"title": "Peer", "container_id": str(pasted_nested)}
        assert new[by_title["Disconnected"]] == {
            "title": "Disconnected", "container_id": str(pasted),
        }
        new_edges = [(destination, pasted), (pasted_copy, pasted_peer)]
        if include_outputs:
            pasted_neighbor = by_title["Next"]
            assert new[pasted_neighbor] == {"title": "Next", **top_membership}
            new_edges.append((pasted, pasted_neighbor))
        assert updated_edges == sorted([*edges, *new_edges])
        assert target_ui.get_selected_node() == destination
        assert target_ui.get_collapsed_node_ids() == {destination}
        copied_roots.append(pasted)
    assert target.outputs(destination) == copied_roots


@pytest.mark.parametrize("containment_cycle", [False, True])
def test_copy_terminates_on_cyclic_source_and_paste_rejects_it(open_workspace, containment_cycle):
    nodes, ui, control = open_workspace("cycle.sloon")
    if containment_cycle:
        root = nodes.create_node(type="container")
        child = nodes.create_node(type="container", container_id=str(root))
        nodes.set(root, "container_id", str(child))
    else:
        root = nodes.create_node()
        child = nodes.create_node()
        nodes.connect(root, child)
        nodes.connect(child, root)
    destination = nodes.create_node()
    ui.select_node(root)

    clipboard = control.copy_selected(include_outputs=not containment_cycle)
    fragment = json.loads(clipboard)
    assert sorted(record["id"] for record in fragment["nodes"]) == [root, child]
    assert fragment["edges"] == ([] if containment_cycle else [[root, child], [child, root]])
    before = snapshot(nodes)
    ui.select_node(destination)
    assert control.paste_selected(clipboard) is None
    assert snapshot(nodes) == before


def fragment_text(**overrides):
    return json.dumps({
        "format": "sloon-graph-fragment", "version": 1, "root": 1,
        "nodes": [{"id": 1, "properties": {}}], "edges": [], **overrides,
    })


@pytest.mark.parametrize("clipboard", [
    "", "free text", "{", "null", "{}", "[]",
    fragment_text(format="other"),
    fragment_text(version=2),
    fragment_text(version=True),
    fragment_text(version=1.0),
    fragment_text(root=2),
    fragment_text(root=True),
    fragment_text(nodes={}),
    fragment_text(nodes=[{"id": 1, "properties": {}}, {"id": 1, "properties": {}}]),
    fragment_text(nodes=[{"id": True, "properties": {}}]),
    fragment_text(nodes=[{"id": 0, "properties": {}}], root=0),
    fragment_text(nodes=[{"id": 1, "properties": {"count": 1}}]),
    fragment_text(nodes=[{"id": 1, "properties": {"": "value"}}]),
    fragment_text(nodes=[{"id": 1, "properties": {"bad": "\ud800"}}]),
    fragment_text(nodes=[{"id": 1, "properties": {"container_id": "\ud800"}}]),
    fragment_text(edges=[[1, 1, 1]]),
    fragment_text(edges=[[1, 2]]),
    fragment_text(edges=[[True, 1]]),
    fragment_text(nodes=[{"id": 1, "properties": {}}, {"id": 2, "properties": {}}],
                  edges=[[1, 2], [1, 2]]),
    fragment_text(nodes=[{"id": 1, "properties": {}},
                         {"id": 2, "properties": {"container_id": "99"}}]),
    fragment_text(nodes=[{"id": 1, "properties": {}},
                         {"id": 2, "properties": {"container_id": "1"}}]),
    fragment_text(nodes=[{"id": 1, "properties": {"type": "container"}},
                         {"id": 2, "properties": {"container_id": "1"}}], edges=[[1, 2]]),
    fragment_text(extra="field"),
    fragment_text().replace('"edges": []', '"edges": [], "edges": []'),
])
def test_invalid_fragments_leave_graph_and_selection_unchanged(open_workspace, clipboard):
    nodes, ui, control = open_workspace("invalid.sloon")
    selected = nodes.create_node(title="Destination")
    ui.select_node(selected)
    before = snapshot(nodes)

    assert control.paste_selected(clipboard) is None
    assert snapshot(nodes) == before
    assert ui.get_selected_node() == selected


def test_copy_and_paste_require_existing_selection_and_paste_requires_active_membership(
    open_workspace,
):
    nodes, ui, control = open_workspace("selection.sloon")
    node = nodes.create_node()
    container = nodes.create_node(type="container")
    outside = nodes.create_node(container_id=str(container))
    ui.select_node(node)
    clipboard = control.copy_selected()
    nodes.delete_node(node)
    before = snapshot(nodes)

    for selection in (None, node):
        ui.select_node(selection)
        assert control.copy_selected() is None
        assert control.copy_selected(include_outputs=True) is None
        assert control.paste_selected(clipboard) is None
    ui.select_node(outside)
    assert control.copy_selected(include_outputs=True) is None
    assert control.paste_selected(clipboard) is None
    assert snapshot(nodes) == before


def test_fragment_paste_rolls_back_nodes_and_edges_on_final_connection_failure(
    open_workspace, monkeypatch,
):
    nodes, ui, control = open_workspace("atomic.sloon")
    root = nodes.create_node()
    child = nodes.create_node(title="Child")
    destination = nodes.create_node()
    nodes.connect(root, child)
    ui.select_node(root)
    clipboard = control.copy_selected(include_outputs=True)
    ui.select_node(destination)
    before = snapshot(nodes)
    connect = nodes.connect

    def fail_after_root_connection(source, target):
        connect(source, target)
        if source == destination:
            assert len(nodes.list_nodes()) == len(before[0]) + 2
            assert len(nodes.list_edges()) == len(before[1]) + 2
            raise RuntimeError("simulated edge failure")

    with monkeypatch.context() as patch:
        patch.setattr(nodes, "connect", fail_after_root_connection)
        with pytest.raises(RuntimeError, match="simulated edge failure"):
            control.paste_selected(clipboard)
    assert snapshot(nodes) == before
    assert ui.get_selected_node() == destination

    pasted = control.paste_selected(clipboard)
    assert nodes.outputs(destination) == [pasted]
    [pasted_child] = nodes.outputs(pasted)
    assert nodes.get(pasted_child, "title") == "Child"
