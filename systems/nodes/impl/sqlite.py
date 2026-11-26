"""SQLite implementation of the public Nodes API."""

from __future__ import annotations

from contextlib import contextmanager
import sqlite3
from typing import Any, Iterator

from ..spec.api import (
    NodeNotFoundError,
    NodesError,
    PropertyNotFoundError,
)
_MISSING = object()

_CREATE_NODES = """
CREATE TABLE IF NOT EXISTS graph_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT
)
"""
_CREATE_EDGES = """
CREATE TABLE IF NOT EXISTS graph_edges (
    source_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL,
    PRIMARY KEY (source_id, target_id),
    FOREIGN KEY (source_id) REFERENCES graph_nodes (id) ON DELETE CASCADE,
    FOREIGN KEY (target_id) REFERENCES graph_nodes (id) ON DELETE CASCADE
)
"""
_CREATE_PROPERTIES = """
CREATE TABLE IF NOT EXISTS node_properties (
    node_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (node_id, key),
    FOREIGN KEY (node_id) REFERENCES graph_nodes (id) ON DELETE CASCADE
)
"""


def _node_id(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise NodesError("node ID must be a positive integer")
    return value


def _require_utf8(value: str) -> str:
    try:
        str.encode(value, "utf-8")
    except UnicodeEncodeError:
        raise NodesError("property text must be UTF-8 encodable") from None
    return value


def _key(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise NodesError("property key must be a non-empty string")
    return _require_utf8(value)


def _value(value: object) -> str:
    if not isinstance(value, str):
        raise NodesError("property value must be a string")
    return _require_utf8(value)


class Nodes:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._transaction_depth = 0
        _configure_schema(connection)

    def _require_open(self) -> None:
        self._connection.execute("SELECT 1")

    def _commit(self, transaction_was_active: bool) -> None:
        if self._transaction_depth == 0 and not transaction_was_active:
            self._connection.commit()

    def _require_node(self, node_id: int) -> None:
        node_id = _node_id(node_id)
        row = self._connection.execute(
            "SELECT 1 FROM graph_nodes WHERE id = ?", (node_id,)
        ).fetchone()
        if row is None:
            raise NodeNotFoundError(f"node does not exist: {node_id}")

    def create_node(self, **fields: str) -> int:
        self._require_open()
        transaction_was_active = self._connection.in_transaction
        prepared = [(_key(key), _value(value)) for key, value in fields.items()]
        try:
            cursor = self._connection.execute("INSERT INTO graph_nodes DEFAULT VALUES")
            node_id = cursor.lastrowid
            if node_id is None:
                raise sqlite3.DatabaseError("SQLite did not generate a node ID")
            for key, value in prepared:
                self._set_existing(node_id, key, value)
            self._commit(transaction_was_active)
            return node_id
        except BaseException:
            if self._transaction_depth == 0 and not transaction_was_active:
                self._connection.rollback()
            raise

    def delete_node(self, node_id: int) -> None:
        self._require_open()
        transaction_was_active = self._connection.in_transaction
        self._connection.execute("DELETE FROM graph_nodes WHERE id = ?", (_node_id(node_id),))
        self._commit(transaction_was_active)

    def node_exists(self, node_id: int) -> bool:
        self._require_open()
        node_id = _node_id(node_id)
        return self._connection.execute(
            "SELECT 1 FROM graph_nodes WHERE id = ?", (node_id,)
        ).fetchone() is not None

    def list_nodes(self) -> list[int]:
        self._require_open()
        return [row[0] for row in self._connection.execute("SELECT id FROM graph_nodes ORDER BY id")]

    def get(self, node_id: int, key: str, default: Any = _MISSING) -> str:
        self._require_open()
        self._require_node(node_id)
        name = _key(key)
        if default is not _MISSING:
            _value(default)
        row = self._connection.execute(
            "SELECT value FROM node_properties WHERE node_id = ? AND key = ?",
            (node_id, name),
        ).fetchone()
        if row is None:
            if default is not _MISSING:
                return default
            raise PropertyNotFoundError(f"property does not exist: {name!r}")
        return row[0]

    def _set_existing(self, node_id: int, key: str, value: str) -> None:
        self._connection.execute(
            "INSERT INTO node_properties (node_id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT (node_id, key) DO UPDATE SET value = excluded.value",
            (node_id, key, value),
        )

    def set(self, node_id: int, key: str, value: str) -> None:
        self._require_open()
        self._require_node(node_id)
        transaction_was_active = self._connection.in_transaction
        self._set_existing(node_id, _key(key), _value(value))
        self._commit(transaction_was_active)

    def get_all(self, node_id: int) -> dict[str, str]:
        self._require_node(node_id)
        rows = self._connection.execute(
            "SELECT key, value FROM node_properties WHERE node_id = ? ORDER BY key",
            (node_id,),
        )
        return dict(rows)

    def get_many(
        self, node_ids: list[int], keys: list[str]
    ) -> dict[int, dict[str, str]]:
        self._require_open()
        ids = list(dict.fromkeys(_node_id(node_id) for node_id in node_ids))
        requested = list(dict.fromkeys(_key(key) for key in keys))
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        existing = {row[0] for row in self._connection.execute(
            f"SELECT id FROM graph_nodes WHERE id IN ({placeholders})", ids
        )}
        missing = next((node_id for node_id in ids if node_id not in existing), None)
        if missing is not None:
            raise NodeNotFoundError(f"node does not exist: {missing}")
        result: dict[int, dict[str, str]] = {node_id: {} for node_id in ids}
        if requested:
            key_marks = ",".join("?" for _ in requested)
            rows = self._connection.execute(
                f"SELECT node_id, key, value FROM node_properties "
                f"WHERE node_id IN ({placeholders}) AND key IN ({key_marks})",
                [*ids, *requested],
            )
            for node_id, name, value in rows:
                result[node_id][name] = value
        return result

    def delete_property(self, node_id: int, key: str) -> None:
        self._require_open()
        self._require_node(node_id)
        transaction_was_active = self._connection.in_transaction
        name = _key(key)
        self._connection.execute(
            "DELETE FROM node_properties WHERE node_id = ? AND key = ?", (node_id, name)
        )
        self._commit(transaction_was_active)

    def connect(self, source: int, target: int) -> None:
        self._require_open()
        self._require_node(source)
        self._require_node(target)
        transaction_was_active = self._connection.in_transaction
        self._connection.execute(
            "INSERT INTO graph_edges (source_id, target_id) VALUES (?, ?) "
            "ON CONFLICT (source_id, target_id) DO NOTHING", (source, target)
        )
        self._commit(transaction_was_active)

    def disconnect(self, source: int, target: int) -> None:
        self._require_open()
        transaction_was_active = self._connection.in_transaction
        self._connection.execute(
            "DELETE FROM graph_edges WHERE source_id = ? AND target_id = ?",
            (_node_id(source), _node_id(target)),
        )
        self._commit(transaction_was_active)

    def inputs(self, node_id: int) -> list[int]:
        self._require_open()
        node_id = _node_id(node_id)
        return [row[0] for row in self._connection.execute(
            "SELECT source_id FROM graph_edges WHERE target_id = ? ORDER BY source_id", (node_id,)
        )]

    def outputs(self, node_id: int) -> list[int]:
        self._require_open()
        node_id = _node_id(node_id)
        return [row[0] for row in self._connection.execute(
            "SELECT target_id FROM graph_edges WHERE source_id = ? ORDER BY target_id", (node_id,)
        )]

    def list_edges(self) -> list[tuple[int, int]]:
        self._require_open()
        return list(self._connection.execute(
            "SELECT source_id, target_id FROM graph_edges ORDER BY source_id, target_id"
        ))

    @contextmanager
    def transaction(self) -> Iterator["Nodes"]:
        self._require_open()
        depth = self._transaction_depth
        savepoint = f"nodes_transaction_{depth}"
        owns_transaction = depth == 0 and not self._connection.in_transaction
        if owns_transaction:
            self._connection.execute("BEGIN")
        else:
            self._connection.execute(f"SAVEPOINT {savepoint}")
        self._transaction_depth += 1
        try:
            yield self
        except BaseException:
            self._transaction_depth -= 1
            if owns_transaction:
                self._connection.rollback()
            else:
                self._connection.execute(f"ROLLBACK TO {savepoint}")
                self._connection.execute(f"RELEASE {savepoint}")
            raise
        else:
            self._transaction_depth -= 1
            if owns_transaction:
                self._connection.commit()
            else:
                self._connection.execute(f"RELEASE {savepoint}")


def _configure_schema(connection: sqlite3.Connection) -> None:
    enabled = connection.execute("PRAGMA foreign_keys").fetchone()
    if enabled is None or enabled[0] != 1:
        raise sqlite3.DatabaseError("SQLite foreign-key enforcement is unavailable")
    transaction_was_active = connection.in_transaction
    savepoint = "nodes_table_setup"
    try:
        if transaction_was_active:
            connection.execute(f"SAVEPOINT {savepoint}")
        else:
            connection.execute("BEGIN IMMEDIATE")
        connection.execute(_CREATE_NODES)
        connection.execute(_CREATE_EDGES)
        connection.execute(_CREATE_PROPERTIES)
        if transaction_was_active:
            connection.execute(f"RELEASE {savepoint}")
        else:
            connection.commit()
    except BaseException:
        if transaction_was_active:
            connection.execute(f"ROLLBACK TO {savepoint}")
            connection.execute(f"RELEASE {savepoint}")
        else:
            connection.rollback()
        raise
