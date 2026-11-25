"""Public API contract for persistent graph UI state."""

from __future__ import annotations

import sqlite3
from typing import Protocol


class GraphUIAPI(Protocol):
    """Public interface for graph UI state."""

    def get_selected_node(self) -> int | None:
        """Return the selected node ID, or None if none has been selected."""
        ...

    def select_node(self, node_id: int) -> None:
        """Select node_id, replacing the previous selection.

        The node does not need to exist in the graph.
        The change is committed before the method returns unless the caller
        supplied an active transaction.
        """
        ...

    def get_node_width(self) -> int:
        """Return the persisted node width, defaulting to 12."""
        ...

    def set_node_width(self, width: int) -> None:
        """Persist a node width of at least three terminal cells.

        Raise ValueError for invalid widths. The change is committed before
        the method returns unless the caller supplied an active transaction.
        """
        ...

    def get_node_height(self) -> int:
        """Return the persisted number of interior node text rows.

        Return 1 when no node height has been persisted.
        """
        ...

    def set_node_height(self, height: int) -> None:
        """Persist a global node text height of at least one row.

        ``height`` is the exact number of interior text rows in every node.
        Raise ValueError for values that are not integers of at least 1,
        without changing the current value. The change is committed before
        the method returns unless the caller supplied an active transaction.
        """
        ...

    def get_show_node_ids(self) -> bool:
        """Return whether Visualization should display node IDs.

        Return True when no value has been persisted.
        """
        ...

    def set_show_node_ids(self, show: bool) -> None:
        """Persist global node-ID visibility.

        ``show`` must be a bool. Raise ValueError without changing the current
        value for any other input. The change is committed before returning
        unless the caller supplied an active transaction.
        """
        ...

    def get_collapsed_node_ids(self) -> set[int]:
        """Return a defensive copy of all persisted collapsed node IDs.

        Return an empty set when no nodes have been collapsed. IDs are UI
        state and do not need to identify nodes currently present in Graph.
        Reading does not create or modify records.
        """
        ...

    def set_node_collapsed(self, node_id: int, collapsed: bool) -> None:
        """Persist whether ``node_id`` is collapsed.

        ``node_id`` must be an integer, excluding bool, and ``collapsed`` must
        be a bool. Invalid values raise ``ValueError`` without changing state.
        Setting the current state again is accepted and idempotent. The node
        does not need to exist in Graph. The change is committed before this
        method returns unless the caller supplied an active transaction.
        """
        ...


def open_graph_ui(connection: sqlite3.Connection) -> GraphUIAPI:
    """Open persistent graph UI state using an existing connection.

    Create the graph UI tables if they do not exist and preserve existing
    state. The graph UI borrows the supplied connection but does not own or
    close it. It uses its own tables and does not inspect or modify graph data.
    Mutations commit when no transaction was active on entry; otherwise they
    join the caller's transaction without committing or rolling it back.
    """
    ...
