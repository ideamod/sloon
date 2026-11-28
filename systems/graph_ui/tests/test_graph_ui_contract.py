"""Contract tests for persistent graph UI state."""

from contextlib import closing
import tempfile
import sqlite3
import unittest
from pathlib import Path

from systems.graph_ui import open_graph_ui
from systems.nodes import Nodes


def open_storage(path):
    connection = sqlite3.connect(Path(path))
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


class GraphUIContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "graph-ui.sqlite3"
        self.connection = open_storage(self.database_path)

    def tearDown(self) -> None:
        self.connection.close()
        self.temporary_directory.cleanup()

    def test_select_replaces_the_previous_selection(self) -> None:
        graph_ui = open_graph_ui(self.connection)

        graph_ui.select_node(10)
        self.assertEqual(graph_ui.get_selected_node(), 10)

        graph_ui.select_node(20)
        self.assertEqual(graph_ui.get_selected_node(), 20)

    def test_selection_does_not_require_an_existing_graph_node(self) -> None:
        nodes = Nodes(self.connection)
        existing = nodes.create_node()
        graph_ui = open_graph_ui(self.connection)

        graph_ui.select_node(existing + 1000)

        self.assertEqual(graph_ui.get_selected_node(), existing + 1000)
        self.assertEqual(nodes.list_nodes(), [existing])

    def test_settings_default_commit_and_survive_reopening(self) -> None:
        graph_ui = open_graph_ui(self.connection)

        def collapse_two_nodes():
            graph_ui.set_node_collapsed(20, True)
            graph_ui.set_node_collapsed(10, True)

        cases = (
            ("get_selected_node", None, graph_ui.select_node, (42,), 42),
            ("get_node_width", 12, graph_ui.set_node_width, (50,), 50),
            ("get_node_height", 1, graph_ui.set_node_height, (6,), 6),
            ("get_show_node_ids", True, graph_ui.set_show_node_ids, (False,), False),
            ("get_collapsed_node_ids", set(), collapse_two_nodes, (), {10, 20}),
        )
        with closing(open_storage(self.database_path)) as observer_connection:
            observer = open_graph_ui(observer_connection)
            for getter, default, setter, args, expected in cases:
                with self.subTest(setting=getter):
                    initial = getattr(graph_ui, getter)()
                    self.assertEqual((initial, type(initial)), (default, type(default)))
                    setter(*args)
                    observed = getattr(observer, getter)()
                    self.assertEqual((observed, type(observed)), (expected, type(expected)))

        self.connection.close()
        self.connection = open_storage(self.database_path)
        reopened = open_graph_ui(self.connection)
        for getter, _, _, _, expected in cases:
            with self.subTest(reopened=getter):
                actual = getattr(reopened, getter)()
                self.assertEqual((actual, type(actual)), (expected, type(expected)))

    def test_invalid_node_widths_preserve_state(self) -> None:
        graph_ui = open_graph_ui(self.connection)
        graph_ui.set_node_width(20)
        for width in (2, 0, -1, 3.5, "12", True):
            with self.subTest(width=width):
                with self.assertRaises(ValueError):
                    graph_ui.set_node_width(width)
                self.assertEqual(graph_ui.get_node_width(), 20)

    def test_invalid_node_heights_do_not_change_persisted_state(self) -> None:
        graph_ui = open_graph_ui(self.connection)
        graph_ui.set_node_height(3)

        for height in (0, -1, 1.5, "2", True, None):
            with self.subTest(height=height):
                with self.assertRaises(ValueError):
                    graph_ui.set_node_height(height)
                self.assertEqual(graph_ui.get_node_height(), 3)

        self.connection.close()
        self.connection = open_storage(self.database_path)
        reopened = open_graph_ui(self.connection)
        self.assertEqual(reopened.get_node_height(), 3)

    def test_existing_database_without_node_height_uses_default(self) -> None:
        self.connection.execute(
            "CREATE TABLE graph_ui_params ("
            "parameter TEXT PRIMARY KEY, value INTEGER NOT NULL)"
        )
        self.connection.execute(
            "INSERT INTO graph_ui_params (parameter, value) VALUES (?, ?)",
            ("NODE_WIDTH", 24),
        )
        self.connection.execute(
            "INSERT INTO graph_ui_params (parameter, value) VALUES (?, ?)",
            ("SELECTED_NODE", 17),
        )
        self.connection.commit()

        graph_ui = open_graph_ui(self.connection)

        self.assertEqual(graph_ui.get_node_height(), 1)
        self.assertEqual(graph_ui.get_node_width(), 24)
        self.assertEqual(graph_ui.get_selected_node(), 17)

    def test_show_node_ids_rejects_non_boolean_without_changes(self) -> None:
        graph_ui = open_graph_ui(self.connection)
        graph_ui.set_show_node_ids(False)

        for value in (0, 1, None, "true", 1.0):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    graph_ui.set_show_node_ids(value)
                self.assertIs(graph_ui.get_show_node_ids(), False)

    def test_collapsed_node_ids_default_to_empty_defensive_set(self) -> None:
        graph_ui = open_graph_ui(self.connection)

        first = graph_ui.get_collapsed_node_ids()
        first.add(99)

        self.assertEqual(graph_ui.get_collapsed_node_ids(), set())
        self.assertIsNot(first, graph_ui.get_collapsed_node_ids())

    def test_setting_collapsed_state_is_idempotent(self) -> None:
        graph_ui = open_graph_ui(self.connection)

        graph_ui.set_node_collapsed(7, True)
        graph_ui.set_node_collapsed(7, True)
        self.assertEqual(graph_ui.get_collapsed_node_ids(), {7})

        graph_ui.set_node_collapsed(7, False)
        graph_ui.set_node_collapsed(7, False)
        self.assertEqual(graph_ui.get_collapsed_node_ids(), set())

    def test_nested_collapsed_states_are_independent(self) -> None:
        graph_ui = open_graph_ui(self.connection)
        graph_ui.set_node_collapsed(1, True)
        graph_ui.set_node_collapsed(2, True)

        graph_ui.set_node_collapsed(1, False)

        self.assertEqual(graph_ui.get_collapsed_node_ids(), {2})

    def test_invalid_collapsed_arguments_preserve_state(self) -> None:
        graph_ui = open_graph_ui(self.connection)
        graph_ui.set_node_collapsed(5, True)

        for node_id, collapsed in (
            (True, True),
            (1.5, True),
            ("1", True),
            (None, True),
            (1, 1),
            (1, 0),
            (1, "true"),
            (1, None),
        ):
            with self.subTest(node_id=node_id, collapsed=collapsed):
                with self.assertRaises(ValueError):
                    graph_ui.set_node_collapsed(node_id, collapsed)
                self.assertEqual(graph_ui.get_collapsed_node_ids(), {5})

    def test_unrelated_tables_and_connection_are_preserved(self) -> None:
        self.connection.execute("CREATE TABLE unrelated (value TEXT NOT NULL)")
        self.connection.execute("INSERT INTO unrelated VALUES ('kept')")
        self.connection.commit()

        graph_ui = open_graph_ui(self.connection)
        graph_ui.select_node(3)

        self.assertEqual(
            self.connection.execute("SELECT value FROM unrelated").fetchall(),
            [("kept",)],
        )
        self.connection.execute("INSERT INTO unrelated VALUES ('still open')")
        self.connection.commit()


if __name__ == "__main__":
    unittest.main()


def test_active_container_persists_exact_text_and_joins_rollback(tmp_path):
    path = tmp_path / "graph-ui.db"
    with sqlite3.connect(path) as connection:
        graph_ui = open_graph_ui(connection)
        assert graph_ui.get_active_container_id() == ""
        graph_ui.set_active_container_id("001")
        graph_ui.select_node(20)
        connection.execute("BEGIN")
        graph_ui.set_active_container_id("invalid active ID")
        graph_ui.select_node(None)
        assert graph_ui.get_selected_node() is None
        assert graph_ui.get_active_container_id() == "invalid active ID"
        connection.rollback()
    connection.close()

    with sqlite3.connect(path) as reopened:
        graph_ui = open_graph_ui(reopened)
        assert graph_ui.get_active_container_id() == "001"
        assert graph_ui.get_selected_node() == 20
        graph_ui.set_active_container_id("")
        graph_ui.select_node(None)
        assert graph_ui.get_active_container_id() == ""
        assert graph_ui.get_selected_node() is None
    reopened.close()
