"""Real workspace tests for the Visualization startup and polling boundaries."""

import asyncio
from contextlib import closing
import sqlite3

import pytest
from textual.containers import ScrollableContainer
from textual.geometry import Region

from systems.control import open_control
from systems.graph_ui import open_graph_ui
from systems.node_types import resolve_node_type
from systems.nodes import Nodes
from systems.visualization import app as visualization_app
from systems.visualization.impl.visualization import _GraphCanvas, _VisualizationApp


def open_database(path):
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@pytest.fixture
def start_viewer(monkeypatch, tmp_path):
    viewers = []
    monkeypatch.setattr(_VisualizationApp, "run", lambda app: viewers.append(app))

    def start(nodes, graph_ui):
        visualization_app.main(nodes, graph_ui, tmp_path)
        return viewers.pop()

    return start


def test_weight_change_recalculates_vertical_placement(start_viewer, tmp_path):
    with closing(open_database(tmp_path / "weights.db")) as connection:
        nodes = Nodes(connection)
        graph_ui = open_graph_ui(connection)
        upper = nodes.create_node(title="Upper", weight="1")
        middle = nodes.create_node(title="Middle")
        lower = nodes.create_node(title="Lower", weight="-1")
        target = nodes.create_node()
        for source in (upper, middle, lower):
            nodes.connect(source, target)
        edges = nodes.list_edges()
        app = start_viewer(nodes, graph_ui)

        async def exercise():
            async with app.run_test() as pilot:
                canvas = app.query_one(_GraphCanvas)
                before = canvas.render().plain
                assert before.index("Upper") < before.index("Middle") < before.index("Lower")
                nodes.set(middle, "weight", "2")
                await pilot.pause(0.25)
                after = canvas.render().plain
                assert after.index("Middle") < after.index("Upper") < after.index("Lower")

        asyncio.run(exercise())
        assert nodes.list_edges() == edges
        assert graph_ui.get_selected_node() is None


def test_revealed_selection_relayouts_and_scrolls_into_view(start_viewer, tmp_path):
    with closing(open_database(tmp_path / "reveal.db")) as connection:
        nodes = Nodes(connection)
        graph_ui = open_graph_ui(connection)
        graph_ui.set_show_node_ids(False)
        chain = [nodes.create_node(title=f"Step {index}") for index in range(10)]
        for source, target in zip(chain, chain[1:]):
            nodes.connect(source, target)
        graph_ui.set_node_collapsed(chain[0], True)
        graph_ui.set_node_collapsed(chain[4], True)
        graph_ui.select_node(chain[0])
        app = start_viewer(nodes, graph_ui)
        control = open_control(nodes, graph_ui, resolve_node_type, workspace_path=tmp_path)

        async def exercise():
            async with app.run_test(size=(40, 10)) as pilot:
                canvas = app.query_one(_GraphCanvas)
                viewport = app.query_one("#graph-viewport", ScrollableContainer)
                assert "Step 9" not in canvas.render().plain
                assert control.select_node(chain[-1])
                await pilot.pause(0.25)

                rows = canvas.render().plain.splitlines()
                assert all(f"Step {index}" in rows[1] for index in range(10))
                last_x = rows[1].index("Step 9") - 1
                selected_region = Region(last_x, 0, graph_ui.get_node_width(), 3)
                visible_region = viewport.scrollable_content_region.at_offset(viewport.scroll_offset)
                assert viewport.scroll_x > 0
                assert selected_region in visible_region

        asyncio.run(exercise())
        assert graph_ui.get_selected_node() == chain[-1]
        assert graph_ui.get_collapsed_node_ids() == set()


def test_builtin_titles_and_copy_borders_render_with_real_nodes(start_viewer, tmp_path):
    with closing(open_database(tmp_path / "presentations.db")) as connection:
        nodes = Nodes(connection)
        graph_ui = open_graph_ui(connection)
        blank = nodes.create_node()
        titled = nodes.create_node(type="void", title="Visible")
        nodes.create_node(type="copy", title="Broken")
        nodes.create_node(type="copy", param=str(titled))
        app = start_viewer(nodes, graph_ui)

        async def exercise():
            async with app.run_test():
                rows = app.query_one(_GraphCanvas).render().plain.splitlines()
                assert rows[1] == "│          │"
                assert rows[3].strip() == str(blank)
                assert "│Visible   │" in rows
                assert "╎Broken    ╎" in rows
                assert "╎Visible   ╎" in rows

        asyncio.run(exercise())
        assert nodes.get_all(blank) == {}


def test_compact_geometry_renders_adjacent_borders_and_edges(start_viewer, tmp_path):
    with closing(open_database(tmp_path / "compact.db")) as connection:
        nodes = Nodes(connection)
        graph_ui = open_graph_ui(connection)
        graph_ui.set_node_width(8)
        graph_ui.set_show_node_ids(False)
        root = nodes.create_node()
        upper = nodes.create_node(title="Upper")
        lower = nodes.create_node(title="Lower")
        nodes.connect(root, upper)
        nodes.connect(root, lower)
        app = start_viewer(nodes, graph_ui)

        async def exercise():
            async with app.run_test():
                rows = app.query_one(_GraphCanvas).render().plain.splitlines()
                upper_y, upper_row = next((y, row) for y, row in enumerate(rows) if "Upper" in row)
                lower_y, lower_row = next((y, row) for y, row in enumerate(rows) if "Lower" in row)
                upper_x = upper_row.index("Upper") - 1
                lower_x = lower_row.index("Lower") - 1
                assert upper_x == lower_x
                assert lower_y == upper_y + 3
                assert rows[upper_y + 1][upper_x:upper_x + 8] == "└──────┘"
                assert rows[lower_y - 1][lower_x:lower_x + 8] == "■──────┐"
                assert any("▶" in row for row in rows)

        asyncio.run(exercise())


def test_startup_and_polling_display_the_active_container(start_viewer, tmp_path):
    path = tmp_path / "containers.db"
    with closing(open_database(path)) as connection, closing(open_database(path)) as control_connection:
        nodes = Nodes(connection)
        graph_ui = open_graph_ui(connection)
        container = nodes.create_node(type="container", title="Outer")
        nested = nodes.create_node(type="container", title="Inner", container_id=str(container))
        member = nodes.create_node(title="Member", container_id=str(container))
        root = nodes.create_node(title="Root")
        nodes.connect(member, root)
        graph_ui.set_node_collapsed(member, True)
        graph_ui.set_active_container_id(str(container))
        app = start_viewer(nodes, graph_ui)
        control_ui = open_graph_ui(control_connection)
        control = open_control(
            Nodes(control_connection), control_ui, resolve_node_type, workspace_path=tmp_path,
        )

        async def exercise():
            async with app.run_test() as pilot:
                canvas = app.query_one(_GraphCanvas)
                contents = canvas.render().plain
                assert "Inner" in contents and "Member" in contents
                assert "Outer" not in contents and "Root" not in contents
                assert "+" not in contents and "▶" not in contents
                assert control.select_node(nested)
                assert control.enter_container()
                await pilot.pause(0.25)
                assert not canvas.render().plain.strip()

                assert control.leave_container()
                await pilot.pause(0.25)
                contents = canvas.render().plain
                assert "Inner" in contents and "Member" in contents
                assert graph_ui.get_selected_node() == nested

                assert control.leave_container()
                await pilot.pause(0.25)
                contents = canvas.render().plain
                assert "Outer" in contents and "Root" in contents
                assert "Inner" not in contents and "Member" not in contents
                assert graph_ui.get_selected_node() == container

        asyncio.run(exercise())
