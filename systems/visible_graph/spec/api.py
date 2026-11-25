"""Public contract for calculating visible graph projections."""

from .schema import VisibleGraph


def calculate_visible_graph(
    nodes: list[int],
    edges: list[tuple[int, int]],
    collapsed_node_ids: set[int],
) -> VisibleGraph:
    """Return the graph visible through non-collapsed paths from its roots.

    Input:
        nodes: Unique integer node IDs in stable input order.
        edges: Unique directed ``(source_id, target_id)`` pairs in stable
            input order.
        collapsed_node_ids: Integer IDs at which traversal stops. Unknown IDs
            are ignored so persisted collapsed state may survive graph changes.

    Visibility:
        - Roots are nodes with no incoming edges.
        - Traversal starts from every root, so every independent component is
          considered.
        - Every reached node is visible.
        - A reached collapsed node remains visible, but none of its outgoing
          edges are traversed.
        - A descendant hidden behind one collapsed path remains visible when
          another path from a root reaches it without traversing outward from
          a collapsed node.
        - Output contains only input edges whose endpoints are visible and
          whose source is not collapsed.
        - Collapsing a leaf has no effect because it has no outgoing edges.
        - Node and edge ordering is preserved from the inputs.

    Validation:
        - ``nodes`` and ``edges`` must be lists.
        - Node IDs must be unique integers, excluding bool.
        - Every edge must be a two-integer tuple referencing existing nodes.
        - Duplicate edges, self-loops, and directed cycles are rejected.
        - ``collapsed_node_ids`` must be a set containing only integer IDs,
          excluding bool. Unknown integer IDs are valid and ignored.
        - Invalid input raises ``ValueError``.

    Scope:
        - This calculation is pure and stateless.
        - It does not mutate any supplied collection or graph data.
        - It has no persistence, UI, layout, geometry, or rendering concerns.
        - It depends on no other project system.
    """
    ...


def calculate_reveal_plan(
    nodes: list[int],
    edges: list[tuple[int, int]],
    collapsed_node_ids: set[int],
    target_node_id: int,
) -> tuple[int, ...] | None:
    """Return the minimal collapsed-node expansion plan for a target.

    Apply the same input and directed-acyclic-graph validation as
    :func:`calculate_visible_graph`. ``target_node_id`` must be an integer,
    excluding bool. Validate the graph before returning for a missing target.

    Return ``None`` when the target is not present in ``nodes``. Return an
    empty tuple when the target is already visible. Otherwise return the
    collapsed node IDs which must be expanded to make the target visible.

    Minimize the number of expanded nodes. When multiple equal-cost plans
    exist, choose deterministically by searching roots in node input order and
    outgoing edges in edge input order, retaining the first equal-cost route
    discovered. Return planned IDs in root-to-target order. The returned route
    is only a visibility witness and does not define parentage or hierarchy.

    A collapsed target is excluded because reaching it makes it visible;
    collapse only stops traversal of its outgoing edges. Unknown collapsed IDs
    are ignored. Do not mutate any supplied collection. This function is pure
    and has no persistence, selection, layout, or rendering responsibilities.
    """
    ...
