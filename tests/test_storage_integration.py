from pathlib import Path
import sqlite3

import pytest

from systems.graph_ui import open_graph_ui
from systems.nodes import Nodes
from systems.storage import Storage


def test_consumers_own_independent_schemas_on_one_storage_connection(
    tmp_path: Path,
) -> None:
    storage = Storage.initialize(tmp_path / "workspace")
    try:
        connection = storage.connection()
        nodes = Nodes(connection)
        node_tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type='table'"
            )
        }
        assert "graph_nodes" in node_tables
        assert "graph_ui_params" not in node_tables

        open_graph_ui(connection)
        all_tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type='table'"
            )
        }
        assert {"graph_ui_params", "graph_ui_collapsed_nodes"} <= all_tables
    finally:
        storage.close()


def test_nodes_and_graph_ui_do_not_commit_an_active_shared_transaction(
    tmp_path: Path,
) -> None:
    storage = Storage.initialize(tmp_path / "workspace")
    try:
        connection = storage.connection()
        nodes = Nodes(connection)
        graph_ui = open_graph_ui(connection)
        with pytest.raises(RuntimeError):
            with nodes.transaction():
                node_id = nodes.create_node(title="temporary")
                graph_ui.select_node(node_id)
                raise RuntimeError("roll back both systems")
        assert nodes.list_nodes() == []
        assert graph_ui.get_selected_node() is None
    finally:
        storage.close()


def test_sqlite_backup_conversion_preserves_existing_workspace_data(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "standalone.db"
    source = sqlite3.connect(source_path)
    source.execute("PRAGMA foreign_keys=ON")
    source_nodes = Nodes(source)
    source_ui = open_graph_ui(source)
    first = source_nodes.create_node(title="First", custom='{"kept":true}')
    second = source_nodes.create_node(title="Second", weight="-4")
    source_nodes.connect(first, second)
    source_ui.select_node(second)
    source_ui.set_node_collapsed(first, True)

    workspace = tmp_path / "project" / "example.sloon"
    workspace.parent.mkdir()
    destination_storage = Storage.initialize(workspace)
    source.backup(destination_storage.connection())
    destination_storage.close()
    source.close()

    converted = Storage.open(workspace)
    try:
        converted_nodes = Nodes(converted.connection())
        converted_ui = open_graph_ui(converted.connection())
        assert converted_nodes.list_nodes() == [first, second]
        assert converted_nodes.list_edges() == [(first, second)]
        assert converted_nodes.get(first, "custom") == '{"kept":true}'
        assert converted_nodes.get(second, "weight") == "-4"
        assert converted_ui.get_selected_node() == second
        assert converted_ui.get_collapsed_node_ids() == {first}
    finally:
        converted.close()
