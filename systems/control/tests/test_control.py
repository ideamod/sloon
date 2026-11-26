"""Tests for graph controls."""

from contextlib import nullcontext
from dataclasses import dataclass
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from textual.containers import VerticalScroll
from textual.widgets import Input, Static

from systems.control import (
    Direction,
    NodeInfo,
    TitleSearchResult,
    open_control as open_nodes_control,
)
from systems.control.app import ControlApp
from systems.graph_ui import open_graph_ui
from systems.node_types import NodeContext, resolve_node_type
from systems.nodes import Nodes


@dataclass(frozen=True)
class NodeAssignment:
    type: str
    param: str
    title: str = ""
    status: str = "none"
    note: str = ""
    tags: str = ""
    weight: int = 0


class LegacyGraph:
    def __init__(self, nodes: Nodes) -> None:
        self.nodes = nodes

    add_node = lambda self: self.nodes.create_node()
    get_node = lambda self, node_id: node_id if self.nodes.node_exists(node_id) else None
    get_nodes = lambda self: self.nodes.list_nodes()
    delete_node = lambda self, node_id: self.nodes.delete_node(node_id)
    add_edge = lambda self, source, target: self.nodes.connect(source, target)
    delete_edge = lambda self, source, target: self.nodes.disconnect(source, target)
    get_edges = lambda self: self.nodes.list_edges()
    get_inputs = lambda self, node_id: self.nodes.inputs(node_id)
    get_outputs = lambda self, node_id: self.nodes.outputs(node_id)


class LegacyAssignments:
    def __init__(self, nodes: Nodes) -> None:
        self.nodes = nodes

    def get(self, node_id):
        if not self.nodes.node_exists(node_id):
            raise ValueError(f"node does not exist: {node_id}")
        values = self.nodes.get_all(node_id)
        assignment_keys = {"type", "param", "title", "status", "note", "tags", "weight"}
        if not assignment_keys.intersection(values):
            return None
        effective = {
            "type": "void", "param": "", "title": "", "status": "none",
            "note": "", "tags": "", "weight": "0", **values,
        }
        return NodeAssignment(
            effective["type"], effective["param"], effective["title"],
            effective["status"], effective["note"], effective["tags"],
            int(effective["weight"]),
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

    def delete(self, node_id):
        for key in ("type", "param", "title", "status", "note", "tags", "weight"):
            self.nodes.delete_property(node_id, key)


def open_storage(path):
    connection = sqlite3.connect(Path(path))
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _nodes_for(connection):
    return Nodes(connection)


def open_graph(connection):
    return LegacyGraph(_nodes_for(connection))


def open_node_assignments(connection):
    return LegacyAssignments(_nodes_for(connection))


def open_control(
    graph, graph_ui, node_assignments, resolver, *, workspace_path=Path("/test.sloon"),
):
    """Adapt the legacy fixture vocabulary to the unified dependency."""
    return open_nodes_control(graph.nodes, graph_ui, resolver, workspace_path=workspace_path)


def legacy_node_info(node_id, value=None, properties=None):
    if properties is not None:
        value = properties
    if isinstance(value, dict):
        properties = value
    elif value is None:
        properties = {
            "type": "void", "title": "", "param": "", "status": "none",
            "note": "", "tags": "", "weight": 0,
        }
    else:
        properties = {
            key: getattr(value, key)
            for key in ("type", "title", "param", "status", "note", "tags", "weight")
        }
    return NodeInfo(node_id, properties)


class ControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = (
            Path(self.temporary_directory.name) / "control.sqlite3"
        )
        self.connection = open_storage(self.database_path)
        self.graph = open_graph(self.connection)
        self.graph_ui = open_graph_ui(self.connection)
        self.node_assignments = open_node_assignments(self.connection)
        self.control = open_control(
            self.graph,
            self.graph_ui,
            self.node_assignments,
            resolve_node_type,
        )

    def tearDown(self) -> None:
        self.connection.close()
        self.temporary_directory.cleanup()

    def test_cannot_select_a_node_in_an_empty_graph(self) -> None:
        self.assertFalse(self.control.select_node(1))
        self.assertIsNone(self.graph_ui.get_selected_node())

    def test_selects_an_existing_node_by_id(self) -> None:
        first = self.graph.add_node()
        second = self.graph.add_node()

        self.assertTrue(self.control.select_node(second))
        self.assertEqual(self.graph_ui.get_selected_node(), second)

    def test_nonexistent_id_keeps_the_current_selection(self) -> None:
        first = self.graph.add_node()
        self.graph_ui.select_node(first)

        self.assertFalse(self.control.select_node(999))
        self.assertEqual(self.graph_ui.get_selected_node(), first)

    def test_reveal_already_visible_node_changes_nothing(self) -> None:
        target = self.graph.add_node()
        unrelated = self.graph.add_node()
        child = self.graph.add_node()
        self.graph.add_edge(unrelated, child)
        self.graph_ui.set_node_collapsed(unrelated, True)
        self.graph_ui.select_node(unrelated)

        self.assertTrue(self.control.reveal_node(target))

        self.assertEqual(self.graph_ui.get_collapsed_node_ids(), {unrelated})
        self.assertEqual(self.graph_ui.get_selected_node(), unrelated)

    def test_reveal_invalid_or_missing_node_preserves_state(self) -> None:
        selected = self.graph.add_node()
        collapsed = self.graph.add_node()
        child = self.graph.add_node()
        self.graph.add_edge(collapsed, child)
        self.graph_ui.select_node(selected)
        self.graph_ui.set_node_collapsed(collapsed, True)

        for node_id in (999, True, "1", None):
            with self.subTest(node_id=node_id):
                self.assertFalse(self.control.reveal_node(node_id))
                self.assertEqual(self.graph_ui.get_selected_node(), selected)
                self.assertEqual(
                    self.graph_ui.get_collapsed_node_ids(), {collapsed}
                )

    def test_reveal_expands_serial_blockers_and_preserves_unrelated_state(self) -> None:
        root = self.graph.add_node()
        middle = self.graph.add_node()
        target = self.graph.add_node()
        unrelated = self.graph.add_node()
        unrelated_child = self.graph.add_node()
        self.graph.add_edge(root, middle)
        self.graph.add_edge(middle, target)
        self.graph.add_edge(unrelated, unrelated_child)
        for node_id in (root, middle, unrelated):
            self.graph_ui.set_node_collapsed(node_id, True)
        self.graph_ui.select_node(unrelated)

        self.assertTrue(self.control.reveal_node(target))

        self.assertEqual(self.graph_ui.get_collapsed_node_ids(), {unrelated})
        self.assertEqual(self.graph_ui.get_selected_node(), unrelated)

    def test_select_node_reveals_hidden_target_before_selecting(self) -> None:
        root = self.graph.add_node()
        middle = self.graph.add_node()
        target = self.graph.add_node()
        self.graph.add_edge(root, middle)
        self.graph.add_edge(middle, target)
        self.graph_ui.set_node_collapsed(middle, True)
        self.graph_ui.select_node(root)

        self.assertTrue(self.control.select_node(target))

        self.assertEqual(self.graph_ui.get_collapsed_node_ids(), set())
        self.assertEqual(self.graph_ui.get_selected_node(), target)

    def test_reveal_propagates_cycle_error_before_changing_state(self) -> None:
        first = self.graph.add_node()
        second = self.graph.add_node()
        self.graph.add_edge(first, second)
        self.graph.add_edge(second, first)
        self.graph_ui.set_node_collapsed(first, True)
        self.graph_ui.select_node(first)

        with self.assertRaises(ValueError):
            self.control.reveal_node(second)

        self.assertEqual(self.graph_ui.get_collapsed_node_ids(), {first})
        self.assertEqual(self.graph_ui.get_selected_node(), first)

    def test_reveal_propagates_self_loop_error_before_changing_state(self) -> None:
        target = self.graph.add_node()
        self.graph.add_edge(target, target)
        self.graph_ui.set_node_collapsed(target, True)

        with self.assertRaises(ValueError):
            self.control.reveal_node(target)

        self.assertEqual(self.graph_ui.get_collapsed_node_ids(), {target})
        self.assertIsNone(self.graph_ui.get_selected_node())

    def test_get_selected_info_returns_the_stored_assignment(self) -> None:
        selected = self.graph.add_node()
        assignment = NodeAssignment(
            "cmd", "open https://google.com", "Open Google"
        )
        self.node_assignments.set(
            selected, assignment.type, assignment.param, assignment.title
        )
        self.graph_ui.select_node(selected)

        self.assertEqual(
            self.control.get_selected_info(),
            legacy_node_info(node_id=selected, properties={
                "type": "cmd", "title": "Open Google",
                "param": "open https://google.com", "status": "none",
                "note": "", "tags": "", "weight": 0,
            }),
        )

    def test_get_selected_info_does_not_create_a_missing_assignment(self) -> None:
        selected = self.graph.add_node()
        self.graph_ui.select_node(selected)

        self.assertEqual(
            self.control.get_selected_info(),
            legacy_node_info(node_id=selected, properties={
                "type": "void", "title": "", "param": "",
                "status": "none", "note": "", "tags": "", "weight": 0,
            }),
        )
        self.assertIsNone(self.node_assignments.get(selected))

    def test_get_selected_info_rejects_missing_and_invalid_selection(self) -> None:
        self.assertIsNone(self.control.get_selected_info())

        self.graph_ui.select_node(999)

        self.assertIsNone(self.control.get_selected_info())
        self.assertEqual(self.graph_ui.get_selected_node(), 999)

    def test_search_titles_matches_case_insensitive_partial_text_and_spaces(
        self,
    ) -> None:
        first = self.graph.add_node()
        second = self.graph.add_node()
        other = self.graph.add_node()
        self.node_assignments.set(first, "text", "", "Control Center")
        self.node_assignments.set(second, "cmd", "", "Remote CONTROL plane")
        self.node_assignments.set(other, "text", "", "Unrelated")

        self.assertEqual(
            self.control.search_titles(" control "),
            (
                TitleSearchResult(first, "Control Center", "text", "none"),
                TitleSearchResult(
                    second, "Remote CONTROL plane", "cmd", "none"
                ),
            ),
        )
        self.assertEqual(
            self.control.search_titles("control plane"),
            (
                TitleSearchResult(
                    second, "Remote CONTROL plane", "cmd", "none"
                ),
            ),
        )

    def test_search_titles_preserves_duplicate_titles_in_node_order(self) -> None:
        first = self.graph.add_node()
        second = self.graph.add_node()
        self.node_assignments.set(first, "text", "", "Duplicate", "progress")
        self.node_assignments.set(second, "cmd", "", "Duplicate", "success")

        self.assertEqual(
            self.control.search_titles("PLIC"),
            (
                TitleSearchResult(first, "Duplicate", "text", "progress"),
                TitleSearchResult(second, "Duplicate", "cmd", "success"),
            ),
        )

    def test_search_titles_includes_hidden_nodes_without_revealing_them(self) -> None:
        root = self.graph.add_node()
        hidden = self.graph.add_node()
        self.graph.add_edge(root, hidden)
        self.graph_ui.set_node_collapsed(root, True)
        self.node_assignments.set(hidden, "text", "", "Hidden Control")

        self.assertEqual(
            self.control.search_titles("hidden"),
            (
                TitleSearchResult(
                    hidden, "Hidden Control", "text", "none"
                ),
            ),
        )
        self.assertEqual(self.graph_ui.get_collapsed_node_ids(), {root})
        self.assertIsNone(self.graph_ui.get_selected_node())

    def test_search_titles_empty_whitespace_and_missing_assignments(self) -> None:
        unassigned = self.graph.add_node()

        self.assertEqual(self.control.search_titles(""), ())
        self.assertEqual(self.control.search_titles("  \t\n "), ())
        self.assertEqual(self.control.search_titles("anything"), ())
        self.assertIsNone(self.node_assignments.get(unassigned))

    def test_search_titles_skips_nodes_deleted_during_assignment_lookup(self) -> None:
        nodes = Mock(spec=Nodes)
        nodes.list_nodes.return_value = [1, 2, 3]
        nodes.get_many.side_effect = (
            {1: {"title": "Match One", "type": "text", "status": "none"}},
            ValueError("node deleted"),
            {3: {"title": "Match Three", "type": "text", "status": "warning"}},
        )
        control = open_nodes_control(nodes, Mock(), Mock(), workspace_path=Path("/test.sloon"))

        self.assertEqual(
            control.search_titles("match"),
            (
                TitleSearchResult(1, "Match One", "text", "none"),
                TitleSearchResult(3, "Match Three", "text", "warning"),
            ),
        )

    def test_search_titles_rejects_non_string_query(self) -> None:
        with self.assertRaises(ValueError):
            self.control.search_titles(None)

    def test_moves_using_layout_directional_lookup(self) -> None:
        root = self.graph.add_node()
        upper = self.graph.add_node()
        middle = self.graph.add_node()
        lower = self.graph.add_node()
        for child in (upper, middle, lower):
            self.graph.add_edge(root, child)

        self.graph_ui.select_node(root)
        self.assertEqual(self.control.move(Direction.RIGHT), upper)
        self.assertEqual(self.control.move(Direction.UP), upper)
        self.assertEqual(self.control.move(Direction.DOWN), middle)
        self.assertEqual(self.control.move(Direction.DOWN), lower)
        self.assertEqual(self.control.move(Direction.LEFT), root)

    def test_create_output_links_current_to_new_node_and_selects_new(self) -> None:
        current = self.graph.add_node()
        self.graph_ui.select_node(current)

        new_node = self.control.create_output()

        self.assertIsNotNone(new_node)
        self.assertEqual(self.graph.get_edges(), [(current, new_node)])
        self.assertEqual(self.graph_ui.get_selected_node(), new_node)

    def test_create_input_links_new_node_to_current_and_selects_new(self) -> None:
        current = self.graph.add_node()
        self.graph_ui.select_node(current)

        new_node = self.control.create_input()

        self.assertIsNotNone(new_node)
        self.assertEqual(self.graph.get_edges(), [(new_node, current)])
        self.assertEqual(self.graph_ui.get_selected_node(), new_node)

    def test_create_standalone_node_selects_it(self) -> None:
        new_node = self.control.create_node()

        self.assertEqual(self.graph.get_nodes(), [new_node])
        self.assertEqual(self.graph.get_edges(), [])
        self.assertEqual(self.graph_ui.get_selected_node(), new_node)

    def test_movement_recalculates_layout_after_creation(self) -> None:
        current = self.graph.add_node()
        self.graph_ui.select_node(current)
        new_node = self.control.create_output()

        self.assertIsNotNone(new_node)
        self.assertEqual(self.control.move(Direction.LEFT), current)

    def test_create_does_nothing_without_an_existing_selected_node(self) -> None:
        self.assertIsNone(self.control.create_output())
        self.assertIsNone(self.control.create_input())
        self.assertEqual(self.graph.get_nodes(), [])

        self.graph_ui.select_node(999)
        self.assertIsNone(self.control.create_output())
        self.assertIsNone(self.control.create_input())
        self.assertEqual(self.graph.get_nodes(), [])

    def test_delete_selected_node(self) -> None:
        selected = self.graph.add_node()
        connected = self.graph.add_node()
        self.graph.add_edge(selected, connected)
        self.graph_ui.select_node(selected)

        self.assertEqual(self.control.delete_selected(), selected)
        self.assertIsNone(self.graph.get_node(selected))
        self.assertEqual(self.graph.get_edges(), [])

    def test_delete_selects_the_first_input_when_available(self) -> None:
        first_input = self.graph.add_node()
        second_input = self.graph.add_node()
        selected = self.graph.add_node()
        self.graph.add_edge(second_input, selected)
        self.graph.add_edge(first_input, selected)
        self.graph_ui.select_node(selected)

        self.assertEqual(self.control.delete_selected(), selected)
        self.assertEqual(self.graph_ui.get_selected_node(), first_input)

    def test_connect_selected_node_to_existing_target(self) -> None:
        selected = self.graph.add_node()
        target = self.graph.add_node()
        self.graph_ui.select_node(selected)

        self.assertTrue(self.control.connect(target))
        self.assertEqual(self.graph.get_edges(), [(selected, target)])

    def test_connect_rejects_self_loops_and_cycles(self) -> None:
        first = self.graph.add_node()
        second = self.graph.add_node()
        self.graph.add_edge(first, second)
        self.graph_ui.select_node(second)

        self.assertFalse(self.control.connect(second))
        self.assertFalse(self.control.connect(first))
        self.assertEqual(self.graph.get_edges(), [(first, second)])

    def test_disconnect_removes_edges_in_both_directions(self) -> None:
        selected = self.graph.add_node()
        other = self.graph.add_node()
        self.graph.add_edge(other, selected)
        self.graph_ui.select_node(selected)

        self.assertTrue(self.control.disconnect(other))
        self.assertEqual(self.graph.get_edges(), [])

    def test_disconnect_all_removes_every_incident_edge(self) -> None:
        selected = self.graph.add_node()
        incoming = self.graph.add_node()
        outgoing = self.graph.add_node()
        unrelated_source = self.graph.add_node()
        unrelated_target = self.graph.add_node()
        self.graph.add_edge(incoming, selected)
        self.graph.add_edge(selected, outgoing)
        self.graph.add_edge(unrelated_source, unrelated_target)
        self.graph_ui.select_node(selected)

        self.assertEqual(self.control.disconnect_all(), 2)
        self.assertEqual(
            self.graph.get_edges(),
            [(unrelated_source, unrelated_target)],
        )

    def test_set_node_width_persists_valid_width(self) -> None:
        self.assertTrue(self.control.set_node_width(50))
        self.assertEqual(self.graph_ui.get_node_width(), 50)
        self.assertFalse(self.control.set_node_width(2))
        self.assertEqual(self.graph_ui.get_node_width(), 50)

    def test_set_node_height_delegates_valid_values_to_graph_ui(self) -> None:
        graph_ui = Mock()
        control = open_control(
            self.graph,
            graph_ui,
            self.node_assignments,
            resolve_node_type,
        )

        self.assertTrue(control.set_node_height(1))
        self.assertTrue(control.set_node_height(7))

        self.assertEqual(
            graph_ui.set_node_height.call_args_list,
            [call(1), call(7)],
        )

    def test_set_node_height_rejects_invalid_values_without_delegating(self) -> None:
        graph_ui = Mock()
        control = open_control(
            self.graph,
            graph_ui,
            self.node_assignments,
            resolve_node_type,
        )

        for height in (0, -1, 1.5, "2", True, None):
            with self.subTest(height=height):
                self.assertFalse(control.set_node_height(height))

        graph_ui.set_node_height.assert_not_called()

    def test_toggle_node_ids_off_and_on_without_other_mutations(self) -> None:
        node = self.graph.add_node()
        self.graph_ui.select_node(node)
        self.node_assignments.set(node, "text", "body", "Title")
        before = (
            self.graph.get_nodes(),
            self.graph.get_edges(),
            self.graph_ui.get_selected_node(),
            self.graph_ui.get_node_width(),
            self.graph_ui.get_node_height(),
            self.node_assignments.get(node),
        )

        self.assertIs(self.control.toggle_node_ids(), False)
        self.assertIs(self.graph_ui.get_show_node_ids(), False)
        self.assertIs(self.control.toggle_node_ids(), True)
        self.assertIs(self.graph_ui.get_show_node_ids(), True)
        self.assertEqual(
            (
                self.graph.get_nodes(),
                self.graph.get_edges(),
                self.graph_ui.get_selected_node(),
                self.graph_ui.get_node_width(),
                self.graph_ui.get_node_height(),
                self.node_assignments.get(node),
            ),
            before,
        )

    def test_toggle_selected_collapse_both_directions_preserves_state(self) -> None:
        selected = self.graph.add_node()
        child = self.graph.add_node()
        self.graph.add_edge(selected, child)
        self.graph_ui.select_node(selected)
        self.node_assignments.set(selected, "text", "body", "Title")
        before = (
            self.graph.get_nodes(),
            self.graph.get_edges(),
            self.node_assignments.get(selected),
            self.graph_ui.get_node_width(),
            self.graph_ui.get_node_height(),
        )

        self.assertIs(self.control.toggle_selected_collapse(), True)
        self.assertEqual(self.graph_ui.get_collapsed_node_ids(), {selected})
        self.assertEqual(self.graph_ui.get_selected_node(), selected)

        self.assertIs(self.control.toggle_selected_collapse(), False)
        self.assertEqual(self.graph_ui.get_collapsed_node_ids(), set())
        self.assertEqual(self.graph_ui.get_selected_node(), selected)
        self.assertEqual(
            (
                self.graph.get_nodes(),
                self.graph.get_edges(),
                self.node_assignments.get(selected),
                self.graph_ui.get_node_width(),
                self.graph_ui.get_node_height(),
            ),
            before,
        )

    def test_toggle_selected_collapse_is_noop_for_leaf_or_missing_selection(
        self,
    ) -> None:
        leaf = self.graph.add_node()

        self.assertIsNone(self.control.toggle_selected_collapse())
        self.graph_ui.select_node(leaf)
        self.assertIsNone(self.control.toggle_selected_collapse())

        self.assertEqual(self.graph_ui.get_collapsed_node_ids(), set())
        self.assertEqual(self.graph_ui.get_selected_node(), leaf)

    def test_nested_collapsed_state_survives_parent_toggle(self) -> None:
        root = self.graph.add_node()
        child = self.graph.add_node()
        grandchild = self.graph.add_node()
        self.graph.add_edge(root, child)
        self.graph.add_edge(child, grandchild)
        self.graph_ui.set_node_collapsed(child, True)
        self.graph_ui.select_node(root)

        self.assertIs(self.control.toggle_selected_collapse(), True)
        self.assertEqual(
            self.graph_ui.get_collapsed_node_ids(),
            {root, child},
        )
        self.assertIs(self.control.toggle_selected_collapse(), False)
        self.assertEqual(self.graph_ui.get_collapsed_node_ids(), {child})

    def test_selection_reveals_then_navigation_uses_updated_projection(self) -> None:
        root = self.graph.add_node()
        middle = self.graph.add_node()
        leaf = self.graph.add_node()
        self.graph.add_edge(root, middle)
        self.graph.add_edge(middle, leaf)
        self.graph_ui.set_node_collapsed(middle, True)

        self.assertTrue(self.control.select_node(leaf))
        self.assertEqual(self.graph_ui.get_collapsed_node_ids(), set())
        self.assertEqual(self.graph_ui.get_selected_node(), leaf)
        self.assertTrue(self.control.select_node(root))
        self.assertEqual(self.control.move(Direction.RIGHT), middle)
        self.assertEqual(self.control.move(Direction.RIGHT), leaf)
        self.assertEqual(self.graph_ui.get_selected_node(), leaf)

    def test_move_recovers_hidden_selection_to_first_visible_node(self) -> None:
        root = self.graph.add_node()
        middle = self.graph.add_node()
        leaf = self.graph.add_node()
        self.graph.add_edge(root, middle)
        self.graph.add_edge(middle, leaf)
        self.graph_ui.set_node_collapsed(middle, True)
        self.graph_ui.select_node(leaf)

        self.assertEqual(self.control.move(Direction.LEFT), root)
        self.assertEqual(self.graph_ui.get_selected_node(), root)

    def test_set_selected_type_preserves_all_other_fields(self) -> None:
        selected = self.graph.add_node()
        self.node_assignments.set(
            selected,
            "text",
            "body",
            "Title",
            "progress",
            "Exact note",
            "python, agent",
        )
        self.graph_ui.select_node(selected)

        self.assertTrue(self.control.set_selected_type("custom type"))
        self.assertEqual(
            self.node_assignments.get(selected),
            NodeAssignment(
                "custom type",
                "body",
                "Title",
                "progress",
                "Exact note",
                "python, agent",
            ),
        )

    def test_set_selected_param_preserves_all_other_fields(self) -> None:
        selected = self.graph.add_node()
        self.node_assignments.set(
            selected,
            "custom",
            "before",
            "Title",
            "warning",
            "Exact note",
            "python, agent",
        )
        self.graph_ui.select_node(selected)

        self.assertTrue(self.control.set_selected_param("  Exact, CASE!  "))
        self.assertEqual(
            self.node_assignments.get(selected),
            NodeAssignment(
                "custom",
                "  Exact, CASE!  ",
                "Title",
                "warning",
                "Exact note",
                "python, agent",
            ),
        )

    def test_set_selected_title_preserves_all_other_fields(self) -> None:
        selected = self.graph.add_node()
        self.node_assignments.set(
            selected,
            "custom",
            "parameter",
            "Before",
            "failure",
            "Exact note",
            "python, agent",
        )
        self.graph_ui.select_node(selected)

        self.assertTrue(self.control.set_selected_title("  Exact Title!  "))
        self.assertEqual(
            self.node_assignments.get(selected),
            NodeAssignment(
                "custom",
                "parameter",
                "  Exact Title!  ",
                "failure",
                "Exact note",
                "python, agent",
            ),
        )

    def test_set_selected_status_accepts_allowed_values_and_preserves_fields(
        self,
    ) -> None:
        selected = self.graph.add_node()
        self.node_assignments.set(
            selected,
            "custom",
            "body",
            "Title",
            "none",
            "Exact note",
            "python, agent",
        )
        self.graph_ui.select_node(selected)

        for status in ("none", "progress", "success", "warning", "failure"):
            with self.subTest(status=status):
                self.assertTrue(self.control.set_selected_status(status))
                self.assertEqual(
                    self.node_assignments.get(selected),
                    NodeAssignment(
                        "custom",
                        "body",
                        "Title",
                        status,
                        "Exact note",
                        "python, agent",
                    ),
                )

    def test_set_selected_status_rejects_invalid_values_without_changes(
        self,
    ) -> None:
        selected = self.graph.add_node()
        original = NodeAssignment("custom", "body", "Title", "progress")
        self.node_assignments.set(
            selected,
            original.type,
            original.param,
            original.title,
            original.status,
        )
        self.graph_ui.select_node(selected)

        for status in ("", "Progress", "unknown", None, True):
            with self.subTest(status=status):
                self.assertFalse(self.control.set_selected_status(status))
                self.assertEqual(self.node_assignments.get(selected), original)

        self.graph_ui.select_node(999)
        self.assertFalse(self.control.set_selected_status("success"))
        self.assertEqual(self.node_assignments.get(selected), original)

    def test_set_selected_status_creates_default_assignment_when_missing(
        self,
    ) -> None:
        selected = self.graph.add_node()
        self.graph_ui.select_node(selected)

        self.assertTrue(self.control.set_selected_status("warning"))
        self.assertEqual(
            self.node_assignments.get(selected),
            NodeAssignment("void", "", "", "warning"),
        )

    def test_set_selected_note_preserves_other_fields_and_exact_text(self) -> None:
        selected = self.graph.add_node()
        self.node_assignments.set(
            selected,
            "custom",
            "body",
            "Title",
            "success",
            "Before",
            "python, agent",
        )
        self.graph_ui.select_node(selected)

        for note in ("", "  whitespace  ", "first\nsecond", "Unicode 😀 café"):
            with self.subTest(note=note):
                self.assertTrue(self.control.set_selected_note(note))
                self.assertEqual(
                    self.node_assignments.get(selected),
                    NodeAssignment(
                        "custom",
                        "body",
                        "Title",
                        "success",
                        note,
                        "python, agent",
                    ),
                )

    def test_set_selected_tags_preserves_other_fields_and_exact_text(self) -> None:
        selected = self.graph.add_node()
        self.node_assignments.set(
            selected, "custom", "body", "Title", "success", "Exact note"
        )
        self.graph_ui.select_node(selected)

        for tags in (
            "",
            "python, development, agent",
            "  whitespace , repeated, repeated  ",
            "Unicode 😀, café, 日本語",
        ):
            with self.subTest(tags=tags):
                self.assertTrue(self.control.set_selected_tags(tags))
                self.assertEqual(
                    self.node_assignments.get(selected),
                    NodeAssignment(
                        "custom", "body", "Title", "success", "Exact note", tags
                    ),
                )

    def test_set_selected_tags_rejects_invalid_values_and_missing_selection(
        self,
    ) -> None:
        selected = self.graph.add_node()
        original = NodeAssignment(
            "custom", "body", "Title", "progress", "Keep note", "keep, tags"
        )
        self.node_assignments.set(
            selected,
            original.type,
            original.param,
            original.title,
            original.status,
            original.note,
            original.tags,
        )
        self.graph_ui.select_node(selected)

        for tags in (None, 42, True):
            with self.subTest(tags=tags):
                self.assertFalse(self.control.set_selected_tags(tags))
                self.assertEqual(self.node_assignments.get(selected), original)

        self.graph_ui.select_node(999)
        self.assertFalse(self.control.set_selected_tags("Changed"))
        self.assertEqual(self.node_assignments.get(selected), original)

    def test_set_selected_weight_accepts_all_integers_and_preserves_fields(self) -> None:
        selected = self.graph.add_node()
        original = NodeAssignment(
            "custom", "body", "Title", "progress", "Note", "tags", 3
        )
        self.node_assignments.set(
            selected,
            original.type,
            original.param,
            original.title,
            original.status,
            original.note,
            original.tags,
            original.weight,
        )
        self.graph_ui.select_node(selected)

        for weight in (0, 10, -4):
            with self.subTest(weight=weight):
                self.assertTrue(self.control.set_selected_weight(weight))
                self.assertEqual(
                    self.node_assignments.get(selected),
                    NodeAssignment(
                        "custom", "body", "Title", "progress", "Note", "tags", weight
                    ),
                )
                self.assertEqual(self.graph_ui.get_selected_node(), selected)

    def test_set_selected_weight_rejects_invalid_value_or_selection(self) -> None:
        selected = self.graph.add_node()
        original = NodeAssignment("custom", "body", weight=2)
        self.node_assignments.set(selected, "custom", "body", weight=2)
        self.graph_ui.select_node(selected)

        for weight in (True, 1.5, "3", None):
            with self.subTest(weight=weight):
                self.assertFalse(self.control.set_selected_weight(weight))
                self.assertEqual(self.node_assignments.get(selected), original)

        self.graph_ui.select_node(999)
        self.assertFalse(self.control.set_selected_weight(5))
        self.assertEqual(self.node_assignments.get(selected), original)

    def test_set_selected_note_rejects_invalid_values_and_missing_selection(
        self,
    ) -> None:
        selected = self.graph.add_node()
        original = NodeAssignment(
            "custom", "body", "Title", "progress", "Keep note"
        )
        self.node_assignments.set(
            selected,
            original.type,
            original.param,
            original.title,
            original.status,
            original.note,
        )
        self.graph_ui.select_node(selected)

        for note in (None, 42, True):
            with self.subTest(note=note):
                self.assertFalse(self.control.set_selected_note(note))
                self.assertEqual(self.node_assignments.get(selected), original)

        self.graph_ui.select_node(999)
        self.assertFalse(self.control.set_selected_note("Changed"))
        self.assertEqual(self.node_assignments.get(selected), original)

    def test_set_selected_note_creates_default_assignment_when_missing(self) -> None:
        selected = self.graph.add_node()
        self.graph_ui.select_node(selected)

        self.assertTrue(self.control.set_selected_note("New note"))
        self.assertEqual(
            self.node_assignments.get(selected),
            NodeAssignment("void", "", "", "none", "New note"),
        )

    def test_assignment_field_updates_initialize_missing_assignment(self) -> None:
        operations = (
            ("type", "future", NodeAssignment("future", "", "")),
            ("param", "value", NodeAssignment("void", "value", "")),
            ("title", "Title", NodeAssignment("void", "", "Title")),
            ("note", "Note", NodeAssignment("void", "", "", "none", "Note")),
            (
                "tags",
                "python, agent",
                NodeAssignment("void", "", "", "none", "", "python, agent"),
            ),
            ("weight", -5, NodeAssignment("void", "", weight=-5)),
        )

        for field, value, expected in operations:
            with self.subTest(field=field):
                selected = self.graph.add_node()
                self.graph_ui.select_node(selected)
                setter = getattr(self.control, f"set_selected_{field}")

                self.assertTrue(setter(value))
                self.assertEqual(self.node_assignments.get(selected), expected)

    def test_empty_param_and_title_are_accepted(self) -> None:
        selected = self.graph.add_node()
        self.node_assignments.set(selected, "custom", "before", "Before")
        self.graph_ui.select_node(selected)

        self.assertTrue(self.control.set_selected_param(""))
        self.assertTrue(self.control.set_selected_title(""))
        self.assertEqual(
            self.node_assignments.get(selected),
            NodeAssignment("custom", "", ""),
        )

    def test_invalid_assignment_values_are_rejected_without_changes(self) -> None:
        selected = self.graph.add_node()
        original = NodeAssignment("custom", "parameter", "Title")
        self.node_assignments.set(
            selected, original.type, original.param, original.title
        )
        self.graph_ui.select_node(selected)

        for setter, value in (
            (self.control.set_selected_type, ""),
            (self.control.set_selected_type, None),
            (self.control.set_selected_param, None),
            (self.control.set_selected_title, None),
            (self.control.set_selected_tags, None),
            (self.control.set_selected_weight, True),
        ):
            with self.subTest(setter=setter, value=value):
                self.assertFalse(setter(value))  # type: ignore[arg-type]
                self.assertEqual(self.node_assignments.get(selected), original)

    def test_assignment_updates_reject_missing_selection_without_changes(self) -> None:
        existing = self.graph.add_node()
        original = NodeAssignment("custom", "parameter", "Title")
        self.node_assignments.set(
            existing, original.type, original.param, original.title
        )

        self.assertFalse(self.control.set_selected_type("changed"))
        self.assertFalse(self.control.set_selected_param("changed"))
        self.assertFalse(self.control.set_selected_title("changed"))
        self.assertFalse(self.control.set_selected_tags("changed"))
        self.assertFalse(self.control.set_selected_weight(1))
        self.assertEqual(self.node_assignments.get(existing), original)

    def test_execute_selected_delegates_with_public_node_context(self) -> None:
        selected = self.graph.add_node()
        assignment = NodeAssignment("custom", "parameter", "Title")
        self.node_assignments.set(
            selected, assignment.type, assignment.param, assignment.title
        )
        self.graph_ui.select_node(selected)
        node_type = Mock()
        resolver = Mock(return_value=node_type)
        workspace_path = Path(self.temporary_directory.name) / "test.sloon"
        control = open_control(
            self.graph,
            self.graph_ui,
            self.node_assignments,
            resolver,
            workspace_path=workspace_path,
        )

        self.assertTrue(control.execute_selected())

        resolver.assert_called_once_with("custom")
        context = node_type.execute.call_args.args[0]
        self.assertIsInstance(context, NodeContext)
        self.assertEqual(context.node_id, selected)
        self.assertEqual(context.workspace_path, workspace_path)
        self.assertTrue(context.workspace_path.is_absolute())
        self.assertEqual(context.properties["type"], assignment.type)
        self.assertEqual(context.properties["param"], assignment.param)
        self.assertEqual(context.properties["title"], assignment.title)
        self.assertIsInstance(context.nodes, Nodes)
        self.assertEqual(self.graph_ui.get_selected_node(), selected)

    def test_execute_unassigned_node_uses_void_without_persisting(self) -> None:
        selected = self.graph.add_node()
        self.graph_ui.select_node(selected)
        node_type = Mock()
        resolver = Mock(return_value=node_type)
        control = open_control(
            self.graph,
            self.graph_ui,
            self.node_assignments,
            resolver,
        )

        self.assertTrue(control.execute_selected())

        resolver.assert_called_once_with("void")
        context = node_type.execute.call_args.args[0]
        self.assertEqual(context.properties["type"], "void")
        self.assertEqual(context.properties["param"], "")
        self.assertIsNone(self.node_assignments.get(selected))

    def test_execute_rejects_missing_selection_without_resolving(self) -> None:
        resolver = Mock()
        control = open_control(
            self.graph,
            self.graph_ui,
            self.node_assignments,
            resolver,
        )

        self.assertFalse(control.execute_selected())
        resolver.assert_not_called()

    def test_execute_propagates_node_type_exceptions(self) -> None:
        selected = self.graph.add_node()
        self.graph_ui.select_node(selected)
        node_type = Mock()
        node_type.execute.side_effect = RuntimeError("execution failed")
        control = open_control(
            self.graph,
            self.graph_ui,
            self.node_assignments,
            Mock(return_value=node_type),
        )

        with self.assertRaisesRegex(RuntimeError, "execution failed"):
            control.execute_selected()


class ControlAppTests(unittest.IsolatedAsyncioTestCase):
    async def test_param_command_edits_exact_utf8_text_in_vim(self) -> None:
        original = "  Existing 😀 param\nsecond line\n"
        edited = " Changed café  \nsecond line\nfinal line\n\n"
        control = Mock()
        control.get_selected_info.return_value = legacy_node_info(
            12, NodeAssignment("text", original, "Title", "none", "Note")
        )
        control.set_selected_param.return_value = True
        app = ControlApp(control)
        app.suspend = Mock(return_value=nullcontext())
        temporary_path: Path | None = None

        def edit_param(
            command: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess:
            nonlocal temporary_path
            temporary_path = Path(command[1])
            self.assertEqual(command[0], "vim")
            self.assertEqual(temporary_path.read_bytes(), original.encode("utf-8"))
            temporary_path.write_bytes(edited.encode("utf-8"))
            return subprocess.CompletedProcess(command, 0)

        with patch("systems.control.app.subprocess.run", side_effect=edit_param):
            async with app.run_test() as pilot:
                await pilot.press(":", *"param", "enter")
                status = str(app.query_one("#status", Static).render())

        control.set_selected_param.assert_called_once_with(edited)
        control.set_selected_note.assert_not_called()
        app.suspend.assert_called_once_with()
        self.assertEqual(status, "Parameter updated")
        self.assertIsNotNone(temporary_path)
        self.assertFalse(temporary_path.exists())

    async def test_param_command_q_bang_leaves_parameter_unchanged(self) -> None:
        original = "Keep this parameter\n"
        control = Mock()
        control.get_selected_info.return_value = legacy_node_info(
            12, NodeAssignment("text", original, "Title", "none", "Note")
        )
        app = ControlApp(control)
        app.suspend = Mock(return_value=nullcontext())

        with patch(
            "systems.control.app.subprocess.run",
            return_value=subprocess.CompletedProcess(["vim"], 0),
        ):
            async with app.run_test() as pilot:
                await pilot.press(":", *"param", "enter")
                status = str(app.query_one("#status", Static).render())

        control.set_selected_param.assert_not_called()
        self.assertEqual(status, "Parameter unchanged")

    async def test_title_search_updates_live_and_shows_assignment_metadata(
        self,
    ) -> None:
        control = Mock()
        control.get_selected_info.return_value = legacy_node_info(
            9, NodeAssignment("text", "", "Selected")
        )
        control.search_titles.return_value = (
            TitleSearchResult(2, "Control Center", "text", "progress"),
            TitleSearchResult(7, "Remote Control", "cmd", "success"),
        )
        app = ControlApp(control)

        async with app.run_test() as pilot:
            await pilot.press("/", *"control center")
            await pilot.pause()
            panel = app.query_one("#search-results", Static)
            content = str(panel.render())
            selected_display = app.query_one(
                "#selected-node-info", Static
            ).styles.display

        self.assertEqual(control.search_titles.call_args, call("control center"))
        self.assertIn("SEARCH  /control center  2 matches", content)
        self.assertIn("Control Center  #2  text  ● progress", content)
        self.assertIn("Remote Control  #7  cmd  ● success", content)
        self.assertEqual(selected_display, "none")
        control.select_node.assert_not_called()

    async def test_search_navigation_selects_active_result(self) -> None:
        control = Mock()
        control.get_selected_info.return_value = None
        control.select_node.return_value = True
        control.search_titles.return_value = (
            TitleSearchResult(2, "First", "text", "none"),
            TitleSearchResult(7, "Second", "cmd", "warning"),
        )
        app = ControlApp(control)

        async with app.run_test() as pilot:
            await pilot.press("/", "x", "down")
            await pilot.pause()
            self.assertEqual(app._active_search_index, 1)
            await pilot.press("enter")

        control.select_node.assert_called_once_with(7)
        self.assertEqual(app._input_mode, None)

    async def test_search_cancel_restores_information_without_selecting(
        self,
    ) -> None:
        control = Mock()
        control.get_selected_info.return_value = legacy_node_info(4, None)
        control.search_titles.return_value = (
            TitleSearchResult(2, "Match", "text", "none"),
        )
        app = ControlApp(control)

        async with app.run_test() as pilot:
            await pilot.press("/", "m", "escape")
            await pilot.pause()
            search_display = app.query_one(
                "#search-results-scroll", VerticalScroll
            ).styles.display
            selected = app.query_one("#selected-node-info", Static)
            selected_display = selected.styles.display
            selected_content = str(selected.render())

        control.select_node.assert_not_called()
        self.assertEqual(search_display, "none")
        self.assertEqual(selected_display, "block")
        self.assertIn("SELECTED NODE  #4", selected_content)

    async def test_search_keeps_active_node_when_query_changes(self) -> None:
        control = Mock()
        control.get_selected_info.return_value = None

        def matches(query: str) -> tuple[TitleSearchResult, ...]:
            if query == "ab":
                return (
                    TitleSearchResult(1, "About", "text", "none"),
                    TitleSearchResult(2, "Abstract", "cmd", "none"),
                )
            return (TitleSearchResult(2, "Abstract", "cmd", "none"),)

        control.search_titles.side_effect = matches
        app = ControlApp(control)

        async with app.run_test() as pilot:
            await pilot.press("/", "a", "b", "down", "s")
            await pilot.pause()

        self.assertEqual(app._active_search_index, 0)
        self.assertEqual(app._search_results[0].node_id, 2)

    async def test_empty_numeric_and_no_match_search_presentations(self) -> None:
        control = Mock()
        control.get_selected_info.return_value = None
        control.search_titles.return_value = ()
        app = ControlApp(control)

        async with app.run_test() as pilot:
            await pilot.press("/")
            empty = str(app.query_one("#search-results", Static).render())
            await pilot.press("space")
            whitespace = str(
                app.query_one("#search-results", Static).render()
            )
            await pilot.press("backspace", "1", "2", "3")
            numeric = str(app.query_one("#search-results", Static).render())
            await pilot.press("backspace", "backspace", "backspace", "z")
            no_match = str(
                app.query_one("#search-results", Static).render()
            )

        self.assertIn("Type a node title or numeric ID", empty)
        self.assertIn("Type a node title or numeric ID", whitespace)
        self.assertIn("Press Enter to select node #123", numeric)
        self.assertIn("0 matches\nNo matching node titles", no_match)
        control.search_titles.assert_called_once_with("z")

    async def test_numeric_id_navigation_does_not_run_title_search(self) -> None:
        control = Mock()
        control.get_selected_info.return_value = None
        control.select_node.return_value = True
        app = ControlApp(control)

        async with app.run_test() as pilot:
            await pilot.press("/", "4", "2", "enter")

        control.select_node.assert_called_once_with(42)
        control.search_titles.assert_not_called()

    async def test_missing_result_at_selection_is_reported(self) -> None:
        control = Mock()
        control.get_selected_info.return_value = None
        control.search_titles.return_value = (
            TitleSearchResult(8, "Deleted", "text", "none"),
        )
        control.select_node.return_value = False
        app = ControlApp(control)

        async with app.run_test() as pilot:
            await pilot.press("/", "d", "enter")
            status = str(app.query_one("#status", Static).render())

        control.select_node.assert_called_once_with(8)
        self.assertEqual(status, "Node 8 does not exist")

    async def test_long_search_results_scroll_in_narrow_terminal(self) -> None:
        control = Mock()
        control.get_selected_info.return_value = None
        control.search_titles.return_value = tuple(
            TitleSearchResult(
                node_id,
                f"Long result title {node_id}",
                "text",
                "none",
            )
            for node_id in range(1, 31)
        )
        app = ControlApp(control)

        async with app.run_test(size=(24, 8)) as pilot:
            await pilot.press("/", "x")
            await pilot.press(*(["down"] * 20))
            await pilot.pause()
            panel = app.query_one("#search-results", Static)
            content = str(panel.render())
            scroll_y = app.query_one(
                "#search-results-scroll", VerticalScroll
            ).scroll_y

        self.assertEqual(app._active_search_index, 20)
        self.assertIn("30 matches", content)
        self.assertIn("Long result title 21", content)
        self.assertGreater(scroll_y, 0)

    async def test_title_search_selects_and_reveals_hidden_node(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            connection = open_storage(Path(directory) / "workspace.db")
            try:
                graph = open_graph(connection)
                graph_ui = open_graph_ui(connection)
                assignments = open_node_assignments(connection)
                root = graph.add_node()
                blocker = graph.add_node()
                target = graph.add_node()
                graph.add_edge(root, blocker)
                graph.add_edge(blocker, target)
                assignments.set(target, "text", "", "Hidden Control")
                graph_ui.set_node_collapsed(blocker, True)
                control = open_control(
                    graph,
                    graph_ui,
                    assignments,
                    resolve_node_type,
                )
                app = ControlApp(control)

                async with app.run_test() as pilot:
                    await pilot.press("/", *"hidden control", "enter")

                self.assertEqual(graph_ui.get_collapsed_node_ids(), set())
                self.assertEqual(graph_ui.get_selected_node(), target)
            finally:
                connection.close()

    async def test_id_navigation_reveals_and_selects_hidden_node(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            connection = open_storage(Path(directory) / "workspace.db")
            try:
                graph = open_graph(connection)
                graph_ui = open_graph_ui(connection)
                assignments = open_node_assignments(connection)
                root = graph.add_node()
                blocker = graph.add_node()
                target = graph.add_node()
                graph.add_edge(root, blocker)
                graph.add_edge(blocker, target)
                graph_ui.set_node_collapsed(blocker, True)
                control = open_control(
                    graph,
                    graph_ui,
                    assignments,
                    resolve_node_type,
                )
                app = ControlApp(control)

                async with app.run_test() as pilot:
                    await pilot.press("/", *str(target), "enter")

                self.assertEqual(graph_ui.get_collapsed_node_ids(), set())
                self.assertEqual(graph_ui.get_selected_node(), target)
            finally:
                connection.close()

    async def test_note_command_edits_exact_utf8_text_and_cleans_up(self) -> None:
        original = "  Existing 😀 note\nsecond line\n"
        edited = " Changed café  \nsecond line\nfinal line\n\n"
        control = Mock()
        control.get_selected_info.return_value = legacy_node_info(
            12, NodeAssignment("text", "body", "Title", "none", original)
        )
        control.set_selected_note.return_value = True
        app = ControlApp(control)
        app.suspend = Mock(return_value=nullcontext())
        temporary_path: Path | None = None

        def edit_note(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            nonlocal temporary_path
            temporary_path = Path(command[1])
            self.assertEqual(command[0], "vim")
            self.assertEqual(temporary_path.read_bytes(), original.encode("utf-8"))
            temporary_path.write_bytes(edited.encode("utf-8"))
            return subprocess.CompletedProcess(command, 0)

        with patch("systems.control.app.subprocess.run", side_effect=edit_note):
            async with app.run_test() as pilot:
                await pilot.press(":", *"note", "enter")
                status = str(app.query_one("#status", Static).render())

        control.set_selected_note.assert_called_once_with(edited)
        app.suspend.assert_called_once_with()
        self.assertEqual(status, "Note updated")
        self.assertIsNotNone(temporary_path)
        self.assertFalse(temporary_path.exists())

    async def test_note_command_q_bang_leaves_note_unchanged(self) -> None:
        original = "Keep this note\n"
        control = Mock()
        control.get_selected_info.return_value = legacy_node_info(
            12, NodeAssignment("text", "body", "Title", "none", original)
        )
        app = ControlApp(control)
        app.suspend = Mock(return_value=nullcontext())
        temporary_path: Path | None = None

        def quit_without_save(
            command: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess:
            nonlocal temporary_path
            temporary_path = Path(command[1])
            return subprocess.CompletedProcess(command, 0)

        with patch(
            "systems.control.app.subprocess.run", side_effect=quit_without_save
        ):
            async with app.run_test() as pilot:
                await pilot.press(":", *"note", "enter")
                status = str(app.query_one("#status", Static).render())

        control.set_selected_note.assert_not_called()
        app.suspend.assert_called_once_with()
        self.assertEqual(status, "Note unchanged")
        self.assertIsNotNone(temporary_path)
        self.assertFalse(temporary_path.exists())

    async def test_note_command_handles_missing_selection_without_vim(self) -> None:
        control = Mock()
        control.get_selected_info.return_value = None
        app = ControlApp(control)

        with patch("systems.control.app.subprocess.run") as run_vim:
            async with app.run_test() as pilot:
                await pilot.press(":", *"note", "enter")
                status = str(app.query_one("#status", Static).render())

        run_vim.assert_not_called()
        control.set_selected_note.assert_not_called()
        self.assertEqual(status, "No existing node is selected")

    async def test_note_command_handles_launch_and_abnormal_exit(self) -> None:
        control = Mock()
        control.get_selected_info.return_value = legacy_node_info(
            12, NodeAssignment("text", "body", "Title", "none", "Original")
        )
        app = ControlApp(control)
        app.suspend = Mock(return_value=nullcontext())

        with patch(
            "systems.control.app.subprocess.run",
            side_effect=FileNotFoundError("vim missing"),
        ):
            async with app.run_test() as pilot:
                await pilot.press(":", *"note", "enter")
                launch_status = str(app.query_one("#status", Static).render())

        abnormal_app = ControlApp(control)
        abnormal_app.suspend = Mock(return_value=nullcontext())
        with patch(
            "systems.control.app.subprocess.run",
            return_value=subprocess.CompletedProcess(["vim"], 2),
        ):
            async with abnormal_app.run_test() as pilot:
                await pilot.press(":", *"note", "enter")
                exit_status = str(
                    abnormal_app.query_one("#status", Static).render()
                )

        control.set_selected_note.assert_not_called()
        self.assertIn("Could not open Vim", launch_status)
        self.assertEqual(exit_status, "Vim exited with status 2")

    async def test_status_command_saves_selected_status_directly(self) -> None:
        control = Mock()
        control.set_selected_status.return_value = True
        app = ControlApp(control)

        async with app.run_test() as pilot:
            await pilot.press(":", *"status success", "enter")

        control.set_selected_status.assert_called_once_with("success")

    async def test_invalid_status_commands_and_s_alias_do_not_set_status(
        self,
    ) -> None:
        control = Mock()
        app = ControlApp(control)

        async with app.run_test() as pilot:
            await pilot.press(":", *"status", "enter")
            await pilot.press(":", *"status invalid", "enter")
            await pilot.press(":", "s", "enter")

        control.set_selected_status.assert_not_called()

    async def test_tags_command_prefills_and_saves_single_line_input(self) -> None:
        control = Mock()
        control.get_selected_info.return_value = legacy_node_info(
            12,
            NodeAssignment(
                "text", "body", "Title", "none", "Note", "python, café"
            ),
        )
        control.set_selected_tags.return_value = True
        app = ControlApp(control)

        async with app.run_test() as pilot:
            await pilot.press(":", *"tags", "enter")
            tags_input = app.query_one("#node-command", Input)
            self.assertEqual(app._input_mode, "tags")
            self.assertFalse(tags_input.disabled)
            self.assertEqual(tags_input.placeholder, "comma-separated tags")
            self.assertEqual(tags_input.value, "python, café")
            self.assertEqual(tags_input.cursor_position, len("python, café"))
            await pilot.press(*", agent", "enter")

        control.set_selected_tags.assert_called_once_with(
            "python, café, agent"
        )

    async def test_tags_command_escape_cancels_without_changes(self) -> None:
        control = Mock()
        control.get_selected_info.return_value = legacy_node_info(
            12, NodeAssignment("text", "", "", tags="keep, tags")
        )
        app = ControlApp(control)

        async with app.run_test() as pilot:
            await pilot.press(":", *"tags", "enter")
            await pilot.press(*", changed", "escape")

        control.set_selected_tags.assert_not_called()
        self.assertIsNone(app._input_mode)

    async def test_tags_command_requires_existing_selection(self) -> None:
        control = Mock()
        control.get_selected_info.return_value = None
        app = ControlApp(control)

        async with app.run_test() as pilot:
            await pilot.press(":", *"tags", "enter")
            status = str(app.query_one("#status", Static).render())

        self.assertEqual(status, "No existing node is selected")
        control.set_selected_tags.assert_not_called()

    async def test_weight_command_prefills_and_saves_signed_integer(self) -> None:
        control = Mock()
        control.get_selected_info.return_value = legacy_node_info(
            12, NodeAssignment("text", "", weight=-3)
        )
        control.set_selected_weight.return_value = True
        app = ControlApp(control)

        async with app.run_test() as pilot:
            await pilot.press(":", *"weight", "enter")
            weight_input = app.query_one("#node-command", Input)
            self.assertEqual(app._input_mode, "weight")
            self.assertEqual(weight_input.value, "-3")
            weight_input.value = "14"
            await pilot.press("enter")

        control.set_selected_weight.assert_called_once_with(14)

    async def test_weight_command_rejects_invalid_input_and_escape_cancels(self) -> None:
        control = Mock()
        control.get_selected_info.return_value = legacy_node_info(
            12, NodeAssignment("text", "", weight=6)
        )
        app = ControlApp(control)

        async with app.run_test() as pilot:
            await pilot.press(":", *"weight", "enter")
            weight_input = app.query_one("#node-command", Input)
            weight_input.value = "1.5"
            await pilot.press("enter")
            self.assertIn("Invalid weight", str(app.query_one("#status", Static).render()))
            await pilot.press(":", *"weight", "enter")
            await pilot.press("escape")

        control.set_selected_weight.assert_not_called()

    async def test_arrow_keys_change_weight_and_keep_selection(self) -> None:
        control = Mock()
        state = {"weight": 2}
        control.get_selected_info.side_effect = lambda: legacy_node_info(
            12, NodeAssignment("text", "", weight=state["weight"])
        )
        control.set_selected_weight.side_effect = (
            lambda weight: state.__setitem__("weight", weight) or True
        )
        app = ControlApp(control)

        async with app.run_test() as pilot:
            await pilot.press("up", "down")

        self.assertEqual(
            control.set_selected_weight.call_args_list,
            [call(3), call(2)],
        )
        control.select_node.assert_not_called()

    async def test_c_starts_connect_entry_with_empty_input(self) -> None:
        control = Mock()
        control.connect.return_value = True
        app = ControlApp(control)

        async with app.run_test() as pilot:
            await pilot.press("c")
            connect_input = app.query_one("#node-command", Input)
            self.assertFalse(connect_input.disabled)
            self.assertEqual(connect_input.placeholder, "target node ID")
            self.assertEqual(connect_input.value, "")
            self.assertEqual(connect_input.cursor_position, 0)
            await pilot.press("4", "2", "enter")

        control.connect.assert_called_once_with(42)

    async def test_t_starts_direct_title_entry_for_selected_node(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            connection = open_storage(Path(directory) / "control-app.sqlite3")
            try:
                graph = open_graph(connection)
                graph_ui = open_graph_ui(connection)
                assignments = open_node_assignments(connection)
                selected = graph.add_node()
                assignments.set(selected, "text", "body", "Old title")
                graph_ui.select_node(selected)
                app = ControlApp(
                    open_control(graph, graph_ui, assignments, resolve_node_type)
                )

                async with app.run_test() as pilot:
                    await pilot.press("t")
                    title_input = app.query_one("#node-command", Input)
                    self.assertFalse(title_input.disabled)
                    self.assertEqual(title_input.placeholder, "node title")
                    self.assertEqual(title_input.value, "Old title")
                    self.assertEqual(
                        title_input.cursor_position,
                        len("Old title"),
                    )
                    await pilot.press(*" extended", "enter")

                self.assertEqual(
                    assignments.get(selected),
                    NodeAssignment("text", "body", "Old title extended"),
                )
            finally:
                connection.close()

    async def test_panel_displays_all_selected_node_fields_and_multiline_text(
        self,
    ) -> None:
        param = "first param line\nsecond param line"
        note = "first note line\nsecond note line\nthird note line\nhidden line"
        tags = "python, development, agent 😀"
        control = Mock()
        control.get_selected_info.return_value = legacy_node_info(
            12,
            NodeAssignment(
                "cmd",
                param,
                "Open Google",
                "success",
                note,
                tags,
            ),
        )
        app = ControlApp(control)

        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            status = str(app.query_one("#status", Static).render())
            panel = app.query_one("#selected-node-info", Static)
            content = str(panel.render())
            formatted = app._format_selected_node(
                control.get_selected_info.return_value
            )
            await pilot.resize_terminal(24, 30)
            await pilot.pause(0.1)
            narrow_width = panel.size.width

        self.assertEqual(status, "Ready")
        self.assertIn("SELECTED NODE  #12", content)
        self.assertIn("Open Google", content)
        self.assertIn("cmd  ● success", content)
        self.assertIn(f"PARAM\n{param}", content)
        self.assertIn(
            "NOTE\nfirst note line\nsecond note line\nthird note line\n…",
            content,
        )
        self.assertNotIn("hidden line", content)
        self.assertIn(f"TAGS\n{tags}", content)
        self.assertIn("WEIGHT  0", content)
        self.assertLessEqual(narrow_width, 24)
        control.set_selected_note.assert_not_called()
        status_offset = formatted.plain.index("success")
        status_style = formatted.get_style_at_offset(app.console, status_offset)
        self.assertEqual(status_style.color.name, "green")

    async def test_node_status_indicator_uses_status_color_mapping(self) -> None:
        control = Mock()
        control.get_selected_info.return_value = None
        app = ControlApp(control)
        expected_colors = {
            "none": "grey50",
            "progress": "blue",
            "success": "green",
            "warning": "yellow",
            "failure": "red",
        }

        async with app.run_test():
            for status, color in expected_colors.items():
                with self.subTest(status=status):
                    formatted = app._format_selected_node(
                        legacy_node_info(
                            1,
                            NodeAssignment("text", "", "", status, ""),
                        )
                    )
                    offset = formatted.plain.index(status)
                    style = formatted.get_style_at_offset(app.console, offset)
                    self.assertEqual(style.color.name, color)

    async def test_panel_refreshes_selection_and_assignment_automatically(
        self,
    ) -> None:
        control = Mock()
        control.get_selected_info.return_value = None
        app = ControlApp(control)

        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            self.assertEqual(
                str(app.query_one("#selected-node-info", Static).render()),
                "SELECTED NODE\nNo node selected",
            )
            control.get_selected_info.return_value = legacy_node_info(
                7, NodeAssignment("text", "body", "Title", "progress", "Note")
            )
            await pilot.pause(0.2)
            content = str(app.query_one("#selected-node-info", Static).render())

        self.assertIn("SELECTED NODE  #7", content)
        self.assertIn("Title", content)
        self.assertIn("text  ● progress", content)

    async def test_panel_uses_effective_defaults_for_missing_assignment(
        self,
    ) -> None:
        control = Mock()
        control.get_selected_info.return_value = legacy_node_info(12, None)
        app = ControlApp(control)

        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            content = str(app.query_one("#selected-node-info", Static).render())

        rules = [
            line for line in content.splitlines() if line and set(line) == {"─"}
        ]
        content_without_rules = "\n".join(
            line for line in content.splitlines() if set(line) != {"─"}
        )
        self.assertEqual(len(rules), 3)
        self.assertEqual(
            content_without_rules,
            "SELECTED NODE  #12\n—\nvoid  ● none  WEIGHT  0\nPARAM\n—\nNOTE\n—\nTAGS\n—",
        )

    async def test_section_separators_follow_terminal_width(self) -> None:
        control = Mock()
        control.get_selected_info.return_value = legacy_node_info(
            4, NodeAssignment("text", "body", "Title", "none", "Note")
        )
        app = ControlApp(control)

        async with app.run_test() as pilot:
            await pilot.resize_terminal(18, 30)
            await pilot.pause(0.2)
            narrow_status_rule = str(
                app.query_one("#status-separator", Static).render()
            )
            narrow_content = str(
                app.query_one("#selected-node-info", Static).render()
            )
            narrow_node_rules = [
                line
                for line in narrow_content.splitlines()
                if line and set(line) == {"─"}
            ]

            await pilot.resize_terminal(38, 30)
            await pilot.pause(0.2)
            wide_status_rule = str(
                app.query_one("#status-separator", Static).render()
            )
            wide_content = str(
                app.query_one("#selected-node-info", Static).render()
            )
            wide_node_rules = [
                line
                for line in wide_content.splitlines()
                if line and set(line) == {"─"}
            ]

        self.assertEqual(len(narrow_node_rules), 3)
        self.assertEqual(len(wide_node_rules), 3)
        self.assertTrue(narrow_status_rule)
        self.assertEqual(
            narrow_node_rules,
            [narrow_status_rule, narrow_status_rule, narrow_status_rule],
        )
        self.assertEqual(
            wide_node_rules,
            [wide_status_rule, wide_status_rule, wide_status_rule],
        )
        self.assertGreater(len(wide_status_rule), len(narrow_status_rule))

    async def test_status_message_uses_semantic_presentation(self) -> None:
        control = Mock()
        control.get_selected_info.return_value = None
        control.set_selected_status.return_value = True
        app = ControlApp(control)

        async with app.run_test() as pilot:
            status = app.query_one("#status", Static)
            await pilot.press(":", *"status success", "enter")
            self.assertTrue(status.has_class("status-success"))
            await pilot.press(":", *"bogus", "enter")
            self.assertTrue(status.has_class("status-error"))
            await pilot.press(":", *"note", "enter")
            self.assertTrue(status.has_class("status-warning"))

    async def test_info_command_is_removed(self) -> None:
        control = Mock()
        control.get_selected_info.return_value = None
        app = ControlApp(control)

        async with app.run_test() as pilot:
            await pilot.press(":", *"info", "enter")
            status = str(app.query_one("#status", Static).render())

        self.assertEqual(status, "Invalid command")

    async def test_colon_height_command_updates_global_node_height(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            connection = open_storage(Path(directory) / "control-app.sqlite3")
            try:
                graph = open_graph(connection)
                graph_ui = open_graph_ui(connection)
                node_assignments = open_node_assignments(connection)
                app = ControlApp(
                    open_control(
                        graph,
                        graph_ui,
                        node_assignments,
                        resolve_node_type,
                    )
                )

                async with app.run_test() as pilot:
                    await pilot.press(":")
                    await pilot.press(*"h4", "enter")

                self.assertEqual(graph_ui.get_node_height(), 4)
            finally:
                connection.close()

    async def test_colon_id_command_toggles_visibility_off_and_on(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            connection = open_storage(Path(directory) / "control-app.sqlite3")
            try:
                graph = open_graph(connection)
                graph_ui = open_graph_ui(connection)
                assignments = open_node_assignments(connection)
                node = graph.add_node()
                assignments.set(node, "text", "body", "Title")
                before = (graph.get_nodes(), graph.get_edges(), assignments.get(node))
                app = ControlApp(
                    open_control(graph, graph_ui, assignments, resolve_node_type)
                )

                async with app.run_test() as pilot:
                    await pilot.press(":", *"id", "enter")
                    self.assertIs(graph_ui.get_show_node_ids(), False)
                    await pilot.press(":", *"id", "enter")
                    self.assertIs(graph_ui.get_show_node_ids(), True)

                self.assertEqual(
                    (graph.get_nodes(), graph.get_edges(), assignments.get(node)),
                    before,
                )
            finally:
                connection.close()

    async def test_space_toggles_selected_collapse_both_directions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            connection = open_storage(Path(directory) / "control-app.sqlite3")
            try:
                graph = open_graph(connection)
                graph_ui = open_graph_ui(connection)
                assignments = open_node_assignments(connection)
                selected = graph.add_node()
                child = graph.add_node()
                graph.add_edge(selected, child)
                graph_ui.select_node(selected)
                assignment = NodeAssignment("text", "body", "Title")
                assignments.set(
                    selected,
                    assignment.type,
                    assignment.param,
                    assignment.title,
                )
                before = (
                    graph.get_nodes(),
                    graph.get_edges(),
                    assignments.get(selected),
                )
                app = ControlApp(
                    open_control(graph, graph_ui, assignments, resolve_node_type)
                )

                async with app.run_test() as pilot:
                    await pilot.press("space")
                    self.assertEqual(
                        graph_ui.get_collapsed_node_ids(), {selected}
                    )
                    self.assertEqual(graph_ui.get_selected_node(), selected)
                    await pilot.press("space")
                    self.assertEqual(graph_ui.get_collapsed_node_ids(), set())

                self.assertEqual(
                    (
                        graph.get_nodes(),
                        graph.get_edges(),
                        assignments.get(selected),
                    ),
                    before,
                )
            finally:
                connection.close()

    async def test_space_remains_text_input_in_command_mode(self) -> None:
        control = Mock()
        control.set_selected_title.return_value = True
        app = ControlApp(control)

        async with app.run_test() as pilot:
            await pilot.press(":")
            await pilot.press(*"title Hello world", "enter")

        control.set_selected_title.assert_called_once_with("Hello world")
        control.toggle_selected_collapse.assert_not_called()

    async def test_invalid_height_commands_preserve_current_height(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            connection = open_storage(Path(directory) / "control-app.sqlite3")
            try:
                graph = open_graph(connection)
                graph_ui = open_graph_ui(connection)
                node_assignments = open_node_assignments(connection)
                graph_ui.set_node_height(3)
                app = ControlApp(
                    open_control(
                        graph,
                        graph_ui,
                        node_assignments,
                        resolve_node_type,
                    )
                )

                async with app.run_test() as pilot:
                    for command in (
                        "h",
                        "h 2",
                        "h 0",
                        "h -1",
                        "h 1.5",
                        "height 2",
                        "h 2 extra",
                    ):
                        await pilot.press(":")
                        await pilot.press(*command, "enter")
                        self.assertEqual(graph_ui.get_node_height(), 3)
            finally:
                connection.close()

    async def test_unprefixed_h_still_navigates_left(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            connection = open_storage(Path(directory) / "control-app.sqlite3")
            try:
                graph = open_graph(connection)
                graph_ui = open_graph_ui(connection)
                node_assignments = open_node_assignments(connection)
                control = open_control(
                    graph, graph_ui, node_assignments, resolve_node_type
                )
                left = graph.add_node()
                right = graph.add_node()
                graph.add_edge(left, right)
                graph_ui.select_node(right)
                app = ControlApp(control)

                async with app.run_test() as pilot:
                    await pilot.press("h")

                self.assertEqual(graph_ui.get_selected_node(), left)
                self.assertEqual(graph_ui.get_node_width(), 12)
            finally:
                connection.close()

    async def test_slash_command_selects_node_by_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            connection = open_storage(Path(directory) / "control-app.sqlite3")
            try:
                graph = open_graph(connection)
                graph_ui = open_graph_ui(connection)
                node_assignments = open_node_assignments(connection)
                control = open_control(
                    graph, graph_ui, node_assignments, resolve_node_type
                )
                root = graph.add_node()
                selected = graph.add_node()
                graph.add_edge(root, selected)
                app = ControlApp(control)

                async with app.run_test() as pilot:
                    self.assertIsNone(app.focused)
                    await pilot.press("/")
                    command = app.query_one("#node-command", Input)
                    self.assertEqual(command.value, "")
                    await pilot.press(str(selected), "enter")
                    self.assertEqual(graph_ui.get_selected_node(), selected)
                    await pilot.press("h")
                    self.assertEqual(graph_ui.get_selected_node(), root)
                    self.assertTrue(control.select_node(selected))
                    await pilot.press("/", "9", "9", "9", "enter")
                    self.assertEqual(graph_ui.get_selected_node(), selected)
                    await pilot.press("o")
                    output = graph_ui.get_selected_node()
                    self.assertIn((selected, output), graph.get_edges())
                    await pilot.press("i")
                    new_input = graph_ui.get_selected_node()
                    self.assertIn((new_input, output), graph.get_edges())
            finally:
                connection.close()

    async def test_colon_commands_modify_the_selected_node(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            connection = open_storage(Path(directory) / "control-app.sqlite3")
            try:
                graph = open_graph(connection)
                graph_ui = open_graph_ui(connection)
                node_assignments = open_node_assignments(connection)
                control = open_control(
                    graph, graph_ui, node_assignments, resolve_node_type
                )
                selected = graph.add_node()
                other = graph.add_node()
                graph_ui.select_node(selected)
                app = ControlApp(control)

                async with app.run_test() as pilot:
                    await pilot.press(":")
                    await pilot.press(*"w50", "enter")
                    self.assertEqual(graph_ui.get_node_width(), 50)

                    await pilot.press(":")
                    await pilot.press(*"w 20", "enter")
                    self.assertEqual(graph_ui.get_node_width(), 50)

                    await pilot.press("a")
                    standalone = graph_ui.get_selected_node()
                    self.assertIsNotNone(standalone)
                    self.assertEqual(graph.get_edges(), [])
                    self.assertTrue(control.select_node(selected))

                    await pilot.press(":")
                    await pilot.press(*f"connect {other}", "enter")
                    self.assertIn((selected, other), graph.get_edges())

                    await pilot.press(":")
                    await pilot.press(*f"disconnect {other}", "enter")
                    self.assertEqual(graph.get_edges(), [])

                    graph.add_edge(other, selected)
                    await pilot.press(":")
                    await pilot.press(*"disconnect", "enter")
                    self.assertEqual(graph.get_edges(), [])

                    await pilot.press(":")
                    await pilot.press("d", "enter")
                    self.assertIsNone(graph.get_node(selected))
            finally:
                connection.close()

    async def test_colon_type_and_param_commands_update_independent_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            connection = open_storage(Path(directory) / "control-app.sqlite3")
            try:
                graph = open_graph(connection)
                graph_ui = open_graph_ui(connection)
                node_assignments = open_node_assignments(connection)
                control = open_control(
                    graph, graph_ui, node_assignments, resolve_node_type
                )
                selected = graph.add_node()
                node_assignments.set(selected, "text", "body", "Title")
                graph_ui.select_node(selected)
                app = ControlApp(control)

                async with app.run_test() as pilot:
                    await pilot.press(":")
                    await pilot.press(*"type future type", "enter")
                    self.assertEqual(
                        node_assignments.get(selected),
                        NodeAssignment("future type", "body", "Title"),
                    )

                    await pilot.press(":")
                    await pilot.press(*"param Hello,   world!", "enter")
                    self.assertEqual(
                        node_assignments.get(selected),
                        NodeAssignment(
                            "future type", "Hello,   world!", "Title"
                        ),
                    )

                    await pilot.press(":")
                    await pilot.press(*"param ", "enter")

                self.assertEqual(
                    node_assignments.get(selected),
                    NodeAssignment("future type", "", "Title"),
                )
            finally:
                connection.close()

    async def test_colon_type_rejects_empty_and_missing_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            connection = open_storage(Path(directory) / "control-app.sqlite3")
            try:
                graph = open_graph(connection)
                graph_ui = open_graph_ui(connection)
                node_assignments = open_node_assignments(connection)
                existing = graph.add_node()
                node_assignments.set(existing, "text", "unchanged")
                app = ControlApp(
                    open_control(
                        graph,
                        graph_ui,
                        node_assignments,
                        resolve_node_type,
                    )
                )

                async with app.run_test() as pilot:
                    await pilot.press(":")
                    await pilot.press(*"type discarded", "enter")

                    graph_ui.select_node(existing)
                    await pilot.press(":")
                    await pilot.press(*"type", "enter")

                self.assertEqual(
                    node_assignments.get(existing),
                    NodeAssignment(type="text", param="unchanged"),
                )
            finally:
                connection.close()

    async def test_colon_title_commands_preserve_title_and_accept_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            connection = open_storage(Path(directory) / "control-app.sqlite3")
            try:
                graph = open_graph(connection)
                graph_ui = open_graph_ui(connection)
                node_assignments = open_node_assignments(connection)
                control = open_control(
                    graph, graph_ui, node_assignments, resolve_node_type
                )
                selected = graph.add_node()
                node_assignments.set(selected, "text", "body")
                graph_ui.select_node(selected)
                app = ControlApp(control)

                async with app.run_test() as pilot:
                    await pilot.press(":")
                    await pilot.press(*"title   Mixed CASE, punctuation!  ", "enter")
                    self.assertEqual(
                        node_assignments.get(selected),
                        NodeAssignment(
                            type="text",
                            param="body",
                            title="  Mixed CASE, punctuation!  ",
                        ),
                    )

                    await pilot.press(":")
                    await pilot.press(*"title", "enter")

                self.assertEqual(
                    node_assignments.get(selected),
                    NodeAssignment(type="text", param="body", title=""),
                )
            finally:
                connection.close()

    async def test_colon_title_rejects_no_selection_without_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            connection = open_storage(Path(directory) / "control-app.sqlite3")
            try:
                graph = open_graph(connection)
                graph_ui = open_graph_ui(connection)
                node_assignments = open_node_assignments(connection)
                existing = graph.add_node()
                expected = NodeAssignment(
                    type="file", param="notes.txt", title="Unchanged"
                )
                node_assignments.set(
                    existing,
                    expected.type,
                    expected.param,
                    expected.title,
                )
                app = ControlApp(
                    open_control(
                        graph,
                        graph_ui,
                        node_assignments,
                        resolve_node_type,
                    )
                )

                async with app.run_test() as pilot:
                    await pilot.press(":")
                    await pilot.press(*"title Discarded", "enter")

                self.assertEqual(node_assignments.get(existing), expected)
            finally:
                connection.close()

    async def test_enter_executes_selected_node_in_normal_mode(self) -> None:
        control = Mock()
        control.execute_selected.return_value = True
        app = ControlApp(control)

        async with app.run_test() as pilot:
            await pilot.press("enter")

        control.execute_selected.assert_called_once_with()

    async def test_enter_only_submits_command_and_selection_inputs(self) -> None:
        control = Mock()
        control.set_selected_param.return_value = True
        control.select_node.return_value = True
        app = ControlApp(control)

        async with app.run_test() as pilot:
            await pilot.press(":")
            await pilot.press(*"param value", "enter")
            await pilot.press("/", "1", "enter")

        control.set_selected_param.assert_called_once_with("value")
        control.select_node.assert_called_once_with(1)
        control.execute_selected.assert_not_called()

    async def test_execution_errors_are_shown_without_crashing_app(self) -> None:
        control = Mock()
        control.execute_selected.side_effect = RuntimeError("broken execution")
        app = ControlApp(control)

        async with app.run_test() as pilot:
            await pilot.press("enter")
            status = str(app.query_one("#status", Static).render())

        self.assertIn("Execution failed: broken execution", status)


if __name__ == "__main__":
    unittest.main()
