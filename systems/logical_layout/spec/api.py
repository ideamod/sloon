from collections.abc import Mapping
from typing import Protocol

from .schema import LogicalLayout


class LogicalLayoutAPI(Protocol):
    @property
    def layout(self) -> LogicalLayout:
        """Return the calculated logical layout."""
        ...

    def get_component(self, node_id: int) -> int:
        """Return the zero-based component index.

        Raise KeyError if the node does not exist.
        """
        ...

    def get_column(self, node_id: int) -> int:
        """Return the zero-based global column index.

        Raise KeyError if the node does not exist.
        """
        ...

    def get_position(self, node_id: int) -> int:
        """Return the zero-based position within its component column.

        Raise KeyError if the node does not exist.
        """
        ...

    def left(self, node_id: int) -> int | None:
        """Return the closest node in the nearest nonempty column
        to the left, or None.

        Prefer the closest global logical row; on ties,
        prefer the upper node.
        Raise KeyError for an unknown node.
        """
        ...

    def right(self, node_id: int) -> int | None:
        """Return the closest node in the nearest nonempty column
        to the right, or None.

        Prefer the closest global logical row; on ties,
        prefer the upper node.
        Raise KeyError for an unknown node.
        """
        ...

    def up(self, node_id: int) -> int | None:
        """Return the previous node in the same global column.

        Navigation crosses component boundaries.
        Return None at the top.
        Raise KeyError for an unknown node.
        """
        ...

    def down(self, node_id: int) -> int | None:
        """Return the next node in the same global column.

        Navigation crosses component boundaries.
        Return None at the bottom.
        Raise KeyError for an unknown node.
        """
        ...


def calculate_layout(
    nodes: list[int],
    edges: list[tuple[int, int]],
    weights: Mapping[int, int] | None = None,
) -> LogicalLayoutAPI:
    """Calculate a deterministic logical layout.

    Input:
        nodes: Unique node IDs in stable input order.
        edges: Directed (source_id, target_id) pairs.
        weights: Optional node-ID-to-integer vertical ordering priorities.
            Missing entries have weight zero. Unknown node IDs, non-integer
            values, and bool values are invalid.

    Rules:
        - Input must be a directed acyclic graph (DAG).
        - Reject duplicate nodes, unknown edge endpoints,
          self-loops, cycles, and malformed input with ValueError.
        - Each node belongs to exactly one weakly connected component.
        - Components are ordered by descending weight of their highest-weight
          root node. Components with equal root priority preserve the order of
          the earliest occurrence of their nodes in the input.
        - Components are vertically independent and never interleaved.
        - Initial columns use longest-path layering, with roots in column 0.
        - Sinks retain their initial longest-path columns.
        - Other nodes shift right as far as possible while remaining at least
          one column left of every child:
          column(node) = min(column(child)) - 1.
        - All components share global column indices.
        - Empty columns within components are preserved.
        - Within each component column, nodes are ordered by descending weight.
          Equal weights preserve their existing stable input order.
        - Weights do not affect component membership, columns, edges, or node
          inclusion.
        - Recalculate from scratch on each invocation.
        - No physical coordinates, rendering, or edge routing.

    Navigation:
        - Each component has logical height equal to its maximum
          column length.
        - Components are stacked in their returned order,
          without gaps in logical row space.
        - A node's global logical row is the sum of preceding
          component heights plus its position within its
          component column.
        - Up/down traverse all nodes in the same global column.
        - Left/right search the nearest nonempty global column
          in the requested direction, selecting the node with
          the smallest absolute global-row difference.
          Ties select the upper node.
        - Navigation results are precomputed so each directional
          lookup is O(1).

    Returns:
        An immutable layout snapshot with navigation methods.

    Raises:
        ValueError: Invalid graph input.
    """
    ...
