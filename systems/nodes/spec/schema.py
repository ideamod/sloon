"""SQLite schema owned by Nodes.

Tables owned by Nodes:

- ``graph_nodes(id INTEGER PRIMARY KEY AUTOINCREMENT)``
- ``graph_edges(source_id, target_id)`` with a unique pair and cascading
  foreign keys to ``graph_nodes``
- ``node_properties(node_id, key TEXT, value TEXT)`` with a unique node/key
  pair and a cascading foreign key to ``graph_nodes``

All properties use the same table and textual representation. Nodes creates
these tables when absent and uses them directly. It has no schema version table
and performs no historical schema detection or migration. Graph UI and
unrelated tables remain independently owned and are ignored.
"""
