"""SQLite implementation of the graph UI API."""

from __future__ import annotations

import sqlite3

from ..spec.api import GraphUIAPI


_SELECTED_NODE = "SELECTED_NODE"
_ACTIVE_CONTAINER_ID = "ACTIVE_CONTAINER_ID"
_NODE_WIDTH = "NODE_WIDTH"
_DEFAULT_NODE_WIDTH = 12
_NODE_HEIGHT = "NODE_HEIGHT"
_DEFAULT_NODE_HEIGHT = 1
_SHOW_NODE_IDS = "SHOW_NODE_IDS"
_DEFAULT_SHOW_NODE_IDS = True

_CREATE_PARAMS = """
CREATE TABLE IF NOT EXISTS graph_ui_params (
    parameter TEXT PRIMARY KEY,
    value INTEGER NOT NULL
)
"""

_CREATE_COLLAPSED_NODES = """
CREATE TABLE IF NOT EXISTS graph_ui_collapsed_nodes (
    node_id INTEGER PRIMARY KEY
)
"""


class _GraphUI:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get_selected_node(self) -> int | None:
        row = self._connection.execute(
            "SELECT value FROM graph_ui_params WHERE parameter = ?",
            (_SELECTED_NODE,),
        ).fetchone()
        return None if row is None else row[0]

    def select_node(self, node_id: int | None) -> None:
        transaction_was_active = self._connection.in_transaction
        if node_id is None:
            self._connection.execute(
                "DELETE FROM graph_ui_params WHERE parameter = ?",
                (_SELECTED_NODE,),
            )
        else:
            self._connection.execute(
                "INSERT INTO graph_ui_params (parameter, value) VALUES (?, ?) "
                "ON CONFLICT (parameter) DO UPDATE SET value = excluded.value",
                (_SELECTED_NODE, node_id),
            )
        if not transaction_was_active:
            self._connection.commit()

    def get_active_container_id(self) -> str:
        row = self._connection.execute(
            "SELECT value FROM graph_ui_params WHERE parameter = ?",
            (_ACTIVE_CONTAINER_ID,),
        ).fetchone()
        return "" if row is None else row[0].decode("utf-8")

    def set_active_container_id(self, container_id: str) -> None:
        if not isinstance(container_id, str):
            raise ValueError("active container ID must be a string")
        encoded = container_id.encode("utf-8")
        transaction_was_active = self._connection.in_transaction
        self._connection.execute(
            "INSERT INTO graph_ui_params (parameter, value) VALUES (?, ?) "
            "ON CONFLICT (parameter) DO UPDATE SET value = excluded.value",
            (_ACTIVE_CONTAINER_ID, encoded),
        )
        if not transaction_was_active:
            self._connection.commit()

    def get_node_width(self) -> int:
        row = self._connection.execute(
            "SELECT value FROM graph_ui_params WHERE parameter = ?",
            (_NODE_WIDTH,),
        ).fetchone()
        return _DEFAULT_NODE_WIDTH if row is None else row[0]

    def set_node_width(self, width: int) -> None:
        if type(width) is not int or width < 3:
            raise ValueError("node width must be an integer of at least 3")
        transaction_was_active = self._connection.in_transaction
        self._connection.execute(
            "INSERT INTO graph_ui_params (parameter, value) VALUES (?, ?) "
            "ON CONFLICT (parameter) DO UPDATE SET value = excluded.value",
            (_NODE_WIDTH, width),
        )
        if not transaction_was_active:
            self._connection.commit()

    def get_node_height(self) -> int:
        row = self._connection.execute(
            "SELECT value FROM graph_ui_params WHERE parameter = ?",
            (_NODE_HEIGHT,),
        ).fetchone()
        return _DEFAULT_NODE_HEIGHT if row is None else row[0]

    def set_node_height(self, height: int) -> None:
        if type(height) is not int or height < 1:
            raise ValueError("node height must be an integer of at least 1")
        transaction_was_active = self._connection.in_transaction
        self._connection.execute(
            "INSERT INTO graph_ui_params (parameter, value) VALUES (?, ?) "
            "ON CONFLICT (parameter) DO UPDATE SET value = excluded.value",
            (_NODE_HEIGHT, height),
        )
        if not transaction_was_active:
            self._connection.commit()

    def get_show_node_ids(self) -> bool:
        row = self._connection.execute(
            "SELECT value FROM graph_ui_params WHERE parameter = ?",
            (_SHOW_NODE_IDS,),
        ).fetchone()
        return _DEFAULT_SHOW_NODE_IDS if row is None else bool(row[0])

    def set_show_node_ids(self, show: bool) -> None:
        if type(show) is not bool:
            raise ValueError("show node IDs must be a boolean")
        transaction_was_active = self._connection.in_transaction
        self._connection.execute(
            "INSERT INTO graph_ui_params (parameter, value) VALUES (?, ?) "
            "ON CONFLICT (parameter) DO UPDATE SET value = excluded.value",
            (_SHOW_NODE_IDS, int(show)),
        )
        if not transaction_was_active:
            self._connection.commit()

    def get_collapsed_node_ids(self) -> set[int]:
        rows = self._connection.execute(
            "SELECT node_id FROM graph_ui_collapsed_nodes"
        ).fetchall()
        return {row[0] for row in rows}

    def set_node_collapsed(self, node_id: int, collapsed: bool) -> None:
        if type(node_id) is not int:
            raise ValueError("node ID must be an integer")
        if type(collapsed) is not bool:
            raise ValueError("collapsed must be a boolean")
        transaction_was_active = self._connection.in_transaction
        if collapsed:
            self._connection.execute(
                "INSERT OR IGNORE INTO graph_ui_collapsed_nodes (node_id) "
                "VALUES (?)",
                (node_id,),
            )
        else:
            self._connection.execute(
                "DELETE FROM graph_ui_collapsed_nodes WHERE node_id = ?",
                (node_id,),
            )
        if not transaction_was_active:
            self._connection.commit()


def open_graph_ui(connection: sqlite3.Connection) -> GraphUIAPI:
    transaction_was_active = connection.in_transaction
    connection.execute(_CREATE_PARAMS)
    connection.execute(_CREATE_COLLAPSED_NODES)
    if not transaction_was_active:
        connection.commit()
    return _GraphUI(connection)
