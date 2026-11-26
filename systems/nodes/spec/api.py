"""Public contract for the Nodes system.

Nodes is the sole authority for persistent node records, directed edges, and
node properties.  It deliberately has no knowledge of layout, rendering,
selection, collapse state, node execution, or other application workflows.

Every property has a non-empty string key and a string value. Both strings
must be UTF-8 encodable. Nodes treats their contents as uninterpreted text.
An absent property and a property containing an empty string are distinct.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
import sqlite3


class NodesError(ValueError):
    """Base class for public Nodes validation and lookup errors.

    Invalid IDs, invalid property keys or values, and invalid explicit
    defaults raise this error. Lookup-specific subclasses identify missing
    nodes and properties.
    """


class NodeNotFoundError(NodesError):
    """The requested node ID does not exist."""


class PropertyNotFoundError(NodesError):
    """The requested property is absent."""


class Nodes:
    """Procedural persistent graph API.

    Construction receives a caller-owned SQLite connection with foreign-key
    enforcement enabled. Nodes creates its three current tables when necessary
    and does not inspect, version, repair, or migrate historical schemas. It
    never opens or closes the connection. Instances are intended for use in
    the connection's thread.

    IDs are positive, monotonically allocated SQLite AUTOINCREMENT values.
    IDs belonging to committed nodes are never reused, including after node
    deletion. An allocation made only inside a rolled-back transaction may be
    allocated again because it was never committed. Edges are unique pairs;
    duplicate connects and missing disconnects/deletes are idempotent.
    Self-loops and cycles are allowed.
    Lists are deterministic: node IDs and neighbor IDs are ascending, and
    edges are ordered by source then target.

    ``get`` raises ``PropertyNotFoundError`` when no property or explicit
    string default exists. ``get_many`` includes every requested existing node
    but omits absent properties. Node deletion, property deletion, disconnect,
    and duplicate connect are idempotent. Operations which must read or mutate
    an existing node raise ``NodeNotFoundError`` when it is absent.

    Every operation that takes property keys or values applies the same
    validation, including the explicit default supplied to get. Invalid
    property input raises NodesError without partially applying that
    operation. Storage-specific encoding exceptions do not escape the API.

    Mutations commit when no transaction was active on entry. If the shared
    connection already has an active transaction, they join it without
    committing or rolling it back. ``transaction()`` owns a new transaction
    when possible and otherwise isolates its work with a savepoint.
    """

    def __init__(self, connection: sqlite3.Connection) -> None: ...

    def create_node(self, **fields: str) -> int: ...
    def delete_node(self, node_id: int) -> None: ...
    def node_exists(self, node_id: int) -> bool: ...
    def list_nodes(self) -> list[int]: ...

    def get(self, node_id: int, key: str, default=...) -> str: ...
    def set(self, node_id: int, key: str, value: str) -> None: ...
    def get_all(self, node_id: int) -> dict[str, str]: ...
    def get_many(
        self, node_ids: list[int], keys: list[str]
    ) -> dict[int, dict[str, str]]: ...
    def delete_property(self, node_id: int, key: str) -> None: ...

    def connect(self, source: int, target: int) -> None: ...
    def disconnect(self, source: int, target: int) -> None: ...
    def inputs(self, node_id: int) -> list[int]: ...
    def outputs(self, node_id: int) -> list[int]: ...
    def list_edges(self) -> list[tuple[int, int]]: ...

    def transaction(self) -> AbstractContextManager["Nodes"]: ...
