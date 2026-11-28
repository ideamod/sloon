"""Persistent graph UI schema.

SQLite table:
- graph_ui_params
    - parameter TEXT PRIMARY KEY
    - value INTEGER NOT NULL

- graph_ui_collapsed_nodes
    - node_id INTEGER PRIMARY KEY

Parameters:
- SELECTED_NODE stores the currently selected node ID.
- ACTIVE_CONTAINER_ID stores the exact UTF-8 bytes of the active container ID
  as a SQLite BLOB to preserve text under the existing integer affinity.
  An absent parameter or an empty string represents the root graph.
- NODE_WIDTH stores the global main-node width. If absent, the public API
  returns the existing default of 12.
- NODE_HEIGHT stores the global number of interior node text rows. If absent,
  the public API returns the default of 1.
- SHOW_NODE_IDS stores global node-ID visibility as 1 or 0. If absent, the
  public API returns the default of True.

The NODE_HEIGHT value follows the same persistence model as NODE_WIDTH: it is
stored as an integer row in graph_ui_params, survives reopening the API, and is
committed by its setter. An absent parameter has its documented default.

SHOW_NODE_IDS follows the same persistence model. It is owned by Graph UI;
Visualization reads it and Control changes it through the public Graph UI API.

Each row in graph_ui_collapsed_nodes represents one collapsed node ID. The
table is an independent persisted set: there is deliberately no foreign key to
Graph, so temporarily hidden or deleted nodes retain their UI state. An absent
row means expanded. Repeating an insert or delete is idempotent.

Neither Graph UI table has a foreign key to the graph's node table.
"""
