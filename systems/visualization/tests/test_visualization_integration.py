"""Cross-system regressions for the Visualization startup boundary."""

import asyncio
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
import sqlite3

from textual.containers import ScrollableContainer
from textual.geometry import Region

from systems.control import open_control
from systems.geometry import calculate_geometry
from systems.graph_ui import open_graph_ui
from systems.logical_layout import calculate_layout
from systems.nodes import Nodes
from systems.node_types import resolve_node_type
from systems.visualization import measure_node_sizes, open_visualization
from systems.visualization import app
from systems.visualization.impl.visualization import (
    _GraphCanvas,
    _Visualization,
    _VisualizationApp,
    _render_snapshot,
)
from systems.visible_graph import calculate_visible_graph


@dataclass(frozen=True)
class Assignment:
    type: str
    param: str
    title: str = ""
    status: str = "none"
    note: str = ""
    tags: str = ""
    weight: int = 0


class Assignments:
    def __init__(self, nodes: Nodes) -> None:
        self.nodes = nodes

    def get(self, node_id: int) -> Assignment:
        values = {
            "type": "void", "param": "", "title": "", "status": "none",
            "note": "", "tags": "", "weight": "0",
            **self.nodes.get_all(node_id),
        }
        return Assignment(
            values["type"], values["param"], values["title"], values["status"],
            values["note"], values["tags"], int(values["weight"]),
        )

    def set(self, node_id, type, param, title=None, status=None, note=None, tags=None, weight=None):
        updates = {"type": type, "param": param}
        updates.update({key: value for key, value in {
            "title": title, "status": status, "note": note,
            "tags": tags, "weight": weight,
        }.items() if value is not None})
        with self.nodes.transaction():
            for key, value in updates.items():
                self.nodes.set(node_id, key, str(value))


def open_workspace(path: Path):
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    nodes = Nodes(connection)
    return nodes, connection


def test_weight_change_recalculates_vertical_placement(tmp_path: Path) -> None:
    nodes_api, connection = open_workspace(tmp_path / "weighted-workspace.db")
    try:
        graph_ui = open_graph_ui(connection)
        assignments = Assignments(nodes_api)
        upper = nodes_api.create_node()
        lower = nodes_api.create_node()
        target = nodes_api.create_node()
        nodes_api.connect(upper, target)
        nodes_api.connect(lower, target)
        assignments.set(upper, "void", "", weight=1)
        assignments.set(lower, "void", "", weight=0)
        nodes = nodes_api.list_nodes()
        edges = nodes_api.list_edges()
        weights = {
            node_id: assignment.weight if assignment is not None else 0
            for node_id in nodes
            for assignment in (assignments.get(node_id),)
        }
        layout = calculate_layout(nodes, edges, weights)
        sizes = measure_node_sizes(
            nodes,
            nodes_api,
            resolve_node_type,
            graph_ui.get_node_width(),
            graph_ui.get_node_height(),
            graph_ui.get_show_node_ids(),
        )
        geometry = calculate_geometry(
            layout.layout,
            sizes,
            node_width=next(iter(sizes.values())).width,
        )
        viewer = open_visualization(
            nodes_api, graph_ui, resolve_node_type, layout, geometry, workspace_path=tmp_path,
        )
        assert viewer._snapshot.rectangles[upper].y < viewer._snapshot.rectangles[lower].y

        assignments.set(lower, "void", "", weight=2)
        viewer.refresh()

        assert viewer._snapshot.rectangles[lower].y < viewer._snapshot.rectangles[upper].y
        assert nodes_api.list_edges() == edges
        assert graph_ui.get_selected_node() is None
    finally:
        connection.close()


def test_revealed_selection_relayouts_and_scrolls_into_view(tmp_path: Path) -> None:
    nodes_api, connection = open_workspace(tmp_path / "reveal-workspace.db")
    try:
        graph_ui = open_graph_ui(connection)
        graph_ui.set_show_node_ids(False)
        assignments = Assignments(nodes_api)
        nodes = [nodes_api.create_node() for _ in range(10)]
        for source, target in zip(nodes, nodes[1:]):
            nodes_api.connect(source, target)
        graph_ui.set_node_collapsed(nodes[0], True)
        graph_ui.set_node_collapsed(nodes[4], True)
        graph_ui.select_node(nodes[0])

        visible = calculate_visible_graph(
            nodes_api.list_nodes(),
            nodes_api.list_edges(),
            graph_ui.get_collapsed_node_ids(),
        )
        visible_nodes, visible_edges = list(visible.nodes), list(visible.edges)
        layout = calculate_layout(visible_nodes, visible_edges)
        sizes = measure_node_sizes(
            visible_nodes,
            nodes_api,
            resolve_node_type,
            graph_ui.get_node_width(),
            graph_ui.get_node_height(),
            graph_ui.get_show_node_ids(),
        )
        geometry = calculate_geometry(
            layout.layout,
            sizes,
            node_width=next(iter(sizes.values())).width,
        )
        viewer = open_visualization(
            nodes_api, graph_ui,
            resolve_node_type,
            layout,
            geometry,
            workspace_path=tmp_path,
        )
        control = open_control(
            nodes_api,
            graph_ui,
            resolve_node_type,
            workspace_path=tmp_path,
        )

        async def exercise_reveal() -> None:
            app = _VisualizationApp(viewer._snapshot, viewer._poll_snapshot)
            async with app.run_test(size=(40, 10)) as pilot:
                assert control.select_node(nodes[-1])
                await pilot.pause(0.25)

                canvas = app.query_one(_GraphCanvas)
                viewport = app.query_one(
                    "#graph-viewport", ScrollableContainer
                )
                assert canvas._snapshot.nodes == tuple(nodes)
                assert canvas._snapshot.selected_node == nodes[-1]
                selected = canvas._snapshot.rectangles[nodes[-1]]
                selected_region = Region(
                    selected.x,
                    selected.y,
                    selected.width,
                    selected.height,
                )
                visible_region = viewport.scrollable_content_region.at_offset(
                    viewport.scroll_offset
                )
                assert viewport.scroll_x > 0
                assert selected_region in visible_region

        asyncio.run(exercise_reveal())
        assert graph_ui.get_collapsed_node_ids() == set()
    finally:
        connection.close()


def test_new_node_with_standard_defaults_opens_and_renders(tmp_path: Path) -> None:
    nodes_api, connection = open_workspace(tmp_path / "workspace.db")
    try:
        graph_ui = open_graph_ui(connection)
        assignments = Assignments(nodes_api)
        node_id = nodes_api.create_node()
        nodes = nodes_api.list_nodes()
        layout = calculate_layout(nodes, nodes_api.list_edges())

        sizes = measure_node_sizes(
            nodes,
            nodes_api,
            resolve_node_type,
            graph_ui.get_node_width(),
            graph_ui.get_node_height(),
            graph_ui.get_show_node_ids(),
        )
        geometry = calculate_geometry(
            layout.layout,
            sizes,
            node_width=next(iter(sizes.values())).width,
        )
        viewer = open_visualization(
            nodes_api, graph_ui,
            resolve_node_type,
            layout,
            geometry,
            workspace_path=tmp_path,
        )

        rendering, _, _ = _render_snapshot(viewer._snapshot)
        assert assignments.get(node_id) == Assignment("void", "")
        assert rendering.plain.splitlines()[-1].strip() == str(node_id)
    finally:
        connection.close()


def test_copy_without_target_opens_and_renders(tmp_path: Path) -> None:
    nodes_api, connection = open_workspace(tmp_path / "broken-copy-workspace.db")
    try:
        graph_ui = open_graph_ui(connection)
        graph_ui.set_show_node_ids(False)
        assignments = Assignments(nodes_api)
        node_id = nodes_api.create_node()
        assignments.set(node_id, "copy", "", "Copy")
        nodes = nodes_api.list_nodes()
        layout = calculate_layout(nodes, nodes_api.list_edges())
        sizes = measure_node_sizes(
            nodes,
            nodes_api,
            resolve_node_type,
            graph_ui.get_node_width(),
            graph_ui.get_node_height(),
            graph_ui.get_show_node_ids(),
        )
        geometry = calculate_geometry(
            layout.layout,
            sizes,
            node_width=next(iter(sizes.values())).width,
        )

        viewer = open_visualization(
            nodes_api, graph_ui,
            resolve_node_type,
            layout,
            geometry,
            workspace_path=tmp_path,
        )

        rendering, _, _ = _render_snapshot(viewer._snapshot)
        rows = rendering.plain.splitlines()
        assert rows[0] == "■╌╌╌╌╌╌╌╌╌╌┐"
        assert rows[1] == "╎Copy      ╎"
    finally:
        connection.close()


def test_titled_void_assignment_keeps_its_visible_title(tmp_path: Path) -> None:
    """Void rendering must not erase the assignment title."""
    nodes_api, connection = open_workspace(tmp_path / "titled-void-workspace.db")
    try:
        graph_ui = open_graph_ui(connection)
        graph_ui.set_show_node_ids(False)
        assignments = Assignments(nodes_api)
        node_id = nodes_api.create_node()
        assignments.set(node_id, "void", "", "Visible")
        nodes = nodes_api.list_nodes()
        layout = calculate_layout(nodes, nodes_api.list_edges())
        sizes = measure_node_sizes(
            nodes,
            nodes_api,
            resolve_node_type,
            graph_ui.get_node_width(),
            graph_ui.get_node_height(),
            graph_ui.get_show_node_ids(),
        )
        geometry = calculate_geometry(
            layout.layout,
            sizes,
            node_width=next(iter(sizes.values())).width,
        )

        viewer = open_visualization(
            nodes_api, graph_ui,
            resolve_node_type,
            layout,
            geometry,
            workspace_path=tmp_path,
        )

        rendering, _, _ = _render_snapshot(viewer._snapshot)
        assert rendering.plain.splitlines()[1] == "│Visible   │"
    finally:
        connection.close()


def test_compact_geometry_renders_adjacent_borders_and_edges(
    tmp_path: Path,
) -> None:
    nodes_api, connection = open_workspace(tmp_path / "compact-workspace.db")
    try:
        graph_ui = open_graph_ui(connection)
        graph_ui.set_node_width(8)
        graph_ui.set_node_height(1)
        graph_ui.set_show_node_ids(False)
        assignments = Assignments(nodes_api)
        root = nodes_api.create_node()
        upper = nodes_api.create_node()
        lower = nodes_api.create_node()
        nodes_api.connect(root, upper)
        nodes_api.connect(root, lower)
        nodes = nodes_api.list_nodes()
        layout = calculate_layout(nodes, nodes_api.list_edges())
        sizes = measure_node_sizes(
            nodes,
            nodes_api,
            resolve_node_type,
            graph_ui.get_node_width(),
            graph_ui.get_node_height(),
            graph_ui.get_show_node_ids(),
        )
        geometry = calculate_geometry(
            layout.layout,
            sizes,
            node_width=next(iter(sizes.values())).width,
        )
        viewer = open_visualization(
            nodes_api, graph_ui,
            resolve_node_type,
            layout,
            geometry,
            workspace_path=tmp_path,
        )

        upper_rect = geometry.get_rect(upper)
        lower_rect = geometry.get_rect(lower)
        rendering, _, _ = _render_snapshot(viewer._snapshot)
        rows = rendering.plain.splitlines()

        assert upper_rect.y + upper_rect.height == lower_rect.y
        assert rows[upper_rect.y + upper_rect.height - 1][
            upper_rect.x : upper_rect.x + upper_rect.width
        ] == "└──────┘"
        assert rows[lower_rect.y][
            lower_rect.x : lower_rect.x + lower_rect.width
        ] == "■──────┐"
        assert "▶" in rendering.plain
    finally:
        connection.close()


def test_copy_border_style_integrates_with_collapse_and_id_visibility(
    tmp_path: Path,
) -> None:
    nodes_api, connection = open_workspace(tmp_path / "copy-workspace.db")
    try:
        graph_ui = open_graph_ui(connection)
        graph_ui.set_node_width(12)
        graph_ui.set_show_node_ids(False)
        assignments = Assignments(nodes_api)
        copy_node = nodes_api.create_node()
        target = nodes_api.create_node()
        nodes_api.connect(copy_node, target)
        assignments.set(copy_node, "copy", str(target), "Copy title")
        assignments.set(target, "text", "", "Target")
        graph_ui.select_node(copy_node)

        visible = calculate_visible_graph(
            nodes_api.list_nodes(),
            nodes_api.list_edges(),
            graph_ui.get_collapsed_node_ids(),
        )
        nodes, edges = list(visible.nodes), list(visible.edges)
        layout = calculate_layout(nodes, edges)
        sizes = measure_node_sizes(
            nodes,
            nodes_api,
            resolve_node_type,
            graph_ui.get_node_width(),
            graph_ui.get_node_height(),
            graph_ui.get_show_node_ids(),
        )
        geometry = calculate_geometry(
            layout.layout,
            sizes,
            node_width=next(iter(sizes.values())).width,
        )
        graph_before = (nodes_api.list_nodes(), nodes_api.list_edges())
        assignments_before = {
            node_id: assignments.get(node_id) for node_id in nodes_api.list_nodes()
        }
        viewer = open_visualization(
            nodes_api, graph_ui,
            resolve_node_type,
            layout,
            geometry,
            workspace_path=tmp_path,
        )

        expanded, _, _ = _render_snapshot(viewer._snapshot)
        assert expanded.plain.splitlines()[0][:12] == "■╌╌╌╌╌╌╌╌╌╌┐"
        assert expanded.plain.splitlines()[1][:12] == "╎Copy title╎"
        assert viewer._snapshot.rectangles[copy_node].height == 3

        graph_ui.set_show_node_ids(True)
        viewer.refresh()
        with_ids, _, _ = _render_snapshot(viewer._snapshot)
        assert with_ids.plain.splitlines()[0][:12] == "■╌╌╌╌╌╌╌╌╌╌┐"
        assert viewer._snapshot.rectangles[copy_node].height == 4

        assignments.set(copy_node, "copy", str(target), "")
        viewer.refresh()
        inherited, _, _ = _render_snapshot(viewer._snapshot)
        assert inherited.plain.splitlines()[1][:12] == "╎Target    ╎"

        assignments.set(copy_node, "copy", str(target), "Copy title")
        viewer.refresh()
        graph_ui.set_node_collapsed(copy_node, True)
        viewer.refresh()
        collapsed, _, _ = _render_snapshot(viewer._snapshot)
        rows = collapsed.plain.splitlines()
        assert viewer._snapshot.nodes == (copy_node,)
        assert rows[0][:12] == "■╌╌╌╌╌╌╌┬╌╌┐"
        assert rows[1][:12] == "╎Copy…  ╎+ ╎"
        assert rows[2][:12] == "└╌╌╌╌╌╌╌┴╌╌┘"
        assert str(copy_node) in rows[3]
        assert (nodes_api.list_nodes(), nodes_api.list_edges()) == graph_before
        assert {
            node_id: assignments.get(node_id) for node_id in nodes_api.list_nodes()
        } == assignments_before
    finally:
        connection.close()


def test_startup_and_polling_display_the_active_container(tmp_path, monkeypatch):
    path = tmp_path / "containers.db"
    nodes, connection = open_workspace(path)
    control_nodes, control_connection = open_workspace(path)
    with closing(connection), closing(control_connection):
        graph_ui = open_graph_ui(connection)
        container = nodes.create_node(type="container")
        nested = nodes.create_node(type="container", container_id=str(container))
        member = nodes.create_node(container_id=str(container))
        root = nodes.create_node()
        nodes.connect(member, root)
        graph_ui.set_node_collapsed(member, True)
        graph_ui.set_active_container_id(str(container))

        viewers = []
        monkeypatch.setattr(_Visualization, "run", lambda viewer: viewers.append(viewer))
        app.main(nodes, graph_ui, tmp_path)
        viewer = viewers[0]
        assert viewer._snapshot.nodes == (nested, member)
        assert viewer._snapshot.indicator_nodes == frozenset()
        assert viewer._snapshot.edges == ()

        control_ui = open_graph_ui(control_connection)
        control = open_control(
            control_nodes, control_ui, resolve_node_type, workspace_path=tmp_path,
        )
        assert control.select_node(nested)
        assert control.enter_container()
        assert viewer._poll_snapshot().nodes == ()
        assert control.leave_container()
        snapshot = viewer._poll_snapshot()
        assert snapshot.nodes == (nested, member)
        assert snapshot.selected_node == nested
        assert control.leave_container()
        snapshot = viewer._poll_snapshot()
        assert snapshot.nodes == (container, root)
        assert snapshot.selected_node == container
