from pathlib import Path
import sqlite3

import pytest

from systems.nodes import NodeNotFoundError, Nodes, NodesError, PropertyNotFoundError


@pytest.fixture
def nodes(tmp_path: Path):
    connection = sqlite3.connect(tmp_path / "workspace.db")
    connection.execute("PRAGMA foreign_keys=ON")
    store = Nodes(connection)
    yield store
    connection.close()


def _open(path: Path) -> tuple[sqlite3.Connection, Nodes]:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys=ON")
    return connection, Nodes(connection)


def test_constructor_uses_borrowed_connection_and_requires_foreign_keys(
    tmp_path: Path,
) -> None:
    connection, store = _open(tmp_path / "workspace.db")
    store.create_node(title="kept")
    del store
    assert connection.execute("SELECT count(*) FROM graph_nodes").fetchone() == (1,)
    connection.close()

    disabled = sqlite3.connect(":memory:")
    try:
        with pytest.raises(sqlite3.DatabaseError, match="foreign-key"):
            Nodes(disabled)
    finally:
        disabled.close()


def test_constructor_creates_only_current_tables_and_ignores_other_tables(
    tmp_path: Path,
) -> None:
    connection = sqlite3.connect(tmp_path / "workspace.db")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("CREATE TABLE nodes_schema(marker TEXT NOT NULL)")
    connection.execute("INSERT INTO nodes_schema VALUES('leave untouched')")

    Nodes(connection)

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_schema WHERE type='table'"
        )
    }
    assert {"graph_nodes", "graph_edges", "node_properties"} <= tables
    assert connection.execute("SELECT marker FROM nodes_schema").fetchone() == (
        "leave untouched",
    )
    connection.close()


def test_new_node_has_no_properties_and_accepts_arbitrary_text(nodes: Nodes) -> None:
    empty = nodes.create_node()
    text = "  first\n😀 café\nlast  "
    populated = nodes.create_node(
        title="", weight="-42", source_code="print('hello')",
        metadata='{"source":"agent"}', note=text,
    )
    assert nodes.get_all(empty) == {}
    assert nodes.get_all(populated) == {
        "metadata": '{"source":"agent"}', "note": text,
        "source_code": "print('hello')", "title": "", "weight": "-42",
    }


def test_missing_empty_and_explicit_fallback_are_distinct(nodes: Nodes) -> None:
    node = nodes.create_node(empty="")
    assert nodes.get(node, "empty") == ""
    assert nodes.get(node, "missing", "fallback") == "fallback"
    with pytest.raises(PropertyNotFoundError):
        nodes.get(node, "missing")
    with pytest.raises(ValueError, match="string"):
        nodes.get(node, "missing", None)


@pytest.mark.parametrize("value", [None, 0, -1, True, {}, [], 2.5])
def test_non_string_values_are_rejected(nodes: Nodes, value: object) -> None:
    node = nodes.create_node()
    with pytest.raises(ValueError, match="string"):
        nodes.set(node, "key", value)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="string"):
        nodes.create_node(key=value)  # type: ignore[arg-type]
    assert nodes.get_all(node) == {}


def test_keys_must_be_nonempty_strings(nodes: Nodes) -> None:
    node = nodes.create_node()
    for key in ("", None, 3):
        with pytest.raises(ValueError, match="non-empty string"):
            nodes.set(node, key, "value")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="non-empty string"):
        nodes.get_many([node], [""])


@pytest.mark.parametrize("operation", ["get", "get_many", "set", "delete_property", "create_node"])
def test_non_utf8_keys_raise_nodes_error(nodes: Nodes, operation: str) -> None:
    node = nodes.create_node(title="original")
    key = "\ud800"
    calls = {
        "get": lambda: nodes.get(node, key),
        "get_many": lambda: nodes.get_many([node], ["title", key]),
        "set": lambda: nodes.set(node, key, "value"),
        "delete_property": lambda: nodes.delete_property(node, key),
        "create_node": lambda: nodes.create_node(title="partial", **{key: "value"}),
    }

    with pytest.raises(NodesError):
        calls[operation]()

    assert nodes.list_nodes() == [node]
    assert nodes.get_all(node) == {"title": "original"}


@pytest.mark.parametrize("operation", ["default", "existing_default", "set", "create_node"])
def test_non_utf8_values_raise_nodes_error(nodes: Nodes, operation: str) -> None:
    node = nodes.create_node(title="original")
    value = "\udfff"
    calls = {
        "default": lambda: nodes.get(node, "missing", value),
        "existing_default": lambda: nodes.get(node, "title", value),
        "set": lambda: nodes.set(node, "title", value),
        "create_node": lambda: nodes.create_node(title="partial", invalid=value),
    }

    with pytest.raises(NodesError):
        calls[operation]()

    assert nodes.list_nodes() == [node]
    assert nodes.get_all(node) == {"title": "original"}


def test_invalid_create_preserves_work_in_an_active_transaction(nodes: Nodes) -> None:
    with nodes.transaction():
        first = nodes.create_node(title="first")
        with pytest.raises(NodesError):
            nodes.create_node(title="partial", invalid="\ud800")
        assert nodes.list_nodes() == [first]
        second = nodes.create_node(title="second")

    assert nodes.list_nodes() == [first, second]


def test_unicode_keys_values_and_empty_strings_round_trip(nodes: Nodes) -> None:
    key = "日本語😀"
    value = "α café 🎉"
    node = nodes.create_node(**{key: value})
    assert nodes.get(node, key) == value
    assert nodes.get(node, "absent", value) == value

    nodes.set(node, key, "")
    assert nodes.get_many([node], [key, "absent"]) == {node: {key: ""}}
    assert nodes.get_all(node) == {key: ""}
    nodes.delete_property(node, key)
    assert nodes.get_all(node) == {}


def test_any_property_can_be_deleted_idempotently(nodes: Nodes) -> None:
    node = nodes.create_node(type="", status="anything")
    nodes.delete_property(node, "type")
    nodes.delete_property(node, "type")
    assert nodes.get_all(node) == {"status": "anything"}


def test_selective_many_returns_only_existing_requested_properties(nodes: Nodes) -> None:
    note = "αβγ\n" * 100_000
    first = nodes.create_node(title="A", note=note, hidden="large")
    second = nodes.create_node(title="B", weight="9")
    assert nodes.get(first, "note") == note
    assert nodes.get_many([first, second], ["title", "weight"]) == {
        first: {"title": "A"}, second: {"title": "B", "weight": "9"},
    }


def test_create_validation_is_atomic(nodes: Nodes) -> None:
    with pytest.raises(ValueError, match="string"):
        nodes.create_node(title="not inserted", invalid=3)  # type: ignore[arg-type]
    assert nodes.list_nodes() == []


def test_properties_persist_when_reopened(tmp_path: Path) -> None:
    path = tmp_path / "workspace.db"
    connection, store = _open(path)
    node = store.create_node(note=" exactly \n")
    connection.close()
    connection, reopened = _open(path)
    try:
        assert reopened.get_all(node) == {"note": " exactly \n"}
    finally:
        connection.close()

def test_node_ids_edges_and_deletion_preserve_graph_semantics(nodes: Nodes) -> None:
    first = nodes.create_node()
    second = nodes.create_node()
    nodes.connect(second, first)
    nodes.connect(first, first)
    nodes.connect(second, first)
    nodes.connect(first, second)
    assert nodes.list_edges() == [(first, first), (first, second), (second, first)]
    assert nodes.inputs(first) == [first, second]
    assert nodes.outputs(first) == [first, second]
    nodes.disconnect(first, second)
    nodes.disconnect(first, second)
    nodes.delete_node(first)
    assert nodes.list_edges() == []
    nodes.delete_node(first)
    third = nodes.create_node()
    assert third > second
    with pytest.raises(NodeNotFoundError):
        nodes.connect(first, second)


def test_transactions_commit_rollback_nest_and_may_reuse_rolled_back_id(
    nodes: Nodes,
) -> None:
    with nodes.transaction():
        first = nodes.create_node(title="A")
        with nodes.transaction():
            second = nodes.create_node(title="B")
            nodes.connect(first, second)
    assert nodes.list_edges() == [(first, second)]
    rolled_back: int | None = None
    with pytest.raises(RuntimeError):
        with nodes.transaction():
            rolled_back = nodes.create_node(title="rolled back")
            raise RuntimeError("rollback")
    replacement = nodes.create_node(title="replacement")
    assert nodes.list_nodes() == [first, second, replacement]
    assert replacement == rolled_back


def test_nodes_joins_external_transaction_without_committing(tmp_path: Path) -> None:
    connection, nodes = _open(tmp_path / "workspace.db")
    try:
        connection.execute("BEGIN")
        node = nodes.create_node(title="temporary")
        with nodes.transaction():
            nodes.set(node, "weight", "4")
        assert connection.in_transaction
        connection.rollback()
        assert nodes.list_nodes() == []
    finally:
        connection.close()
