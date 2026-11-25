from typing import Protocol

from systems.logical_layout.spec.schema import LogicalLayout
from .schema import Geometry, Size, Rect


class GeometryAPI(Protocol):
    @property
    def geometry(self) -> Geometry:
        """Return the calculated geometry snapshot."""
        ...

    def get_rect(self, node_id: int) -> Rect:
        """Return the rectangle of a node.

        Raise KeyError if the node does not exist.
        """
        ...


def calculate_geometry(
    layout: LogicalLayout,
    sizes: dict[int, Size],
    column_gap: int = 4,
    row_gap: int = 0,
    component_gap: int = 1,
    node_width: int = 12,
) -> GeometryAPI:
    """Calculate physical geometry from a logical layout.

    Rules:
        - Use the component, column, and node order from LogicalLayout.
        - All coordinates and dimensions are non-negative integers.
        - Every node must have a Size with positive width and height.
        - Reject missing or extra node sizes.
        - Every node rectangle has the configured node_width, defaulting to
          12 characters.
          Supplied widths are validated but do not affect placement.
        - All components share the same column X positions.
        - Within each component, nodes at the same position in
          different columns share the same Y coordinate.
        - Row height is the maximum node height at that position
          across all columns of the component.
        - Components are stacked vertically in layout order.
        - Apply column_gap between columns, row_gap between rows,
          and component_gap between components. Defaults are 4 horizontal
          cells, zero unused rows within a component, and one empty row
          between separate components.
        - The first occupied column starts at X = 0.
        - The first component starts at Y = 0.
        - Rectangles must not overlap.
        - Geometry width and height describe the bounding area
          occupied by the nodes, excluding trailing gaps.
        - Empty layouts produce empty geometry with width=0,
          height=0.

    Validation:
        - Gaps must be non-negative integers.
        - node_width must be an integer of at least 3.
        - Sizes must contain exactly the nodes in the layout.
        - Every size must have positive integer dimensions.
        - Invalid input raises ValueError.

    Scope:
        - No edge routing.
        - No ports.
        - No rendering.
        - No knowledge of node types.
        - No dependencies on SQLite or UI frameworks.

    Returns:
        An immutable geometry snapshot with node rectangle lookups.
    """
    ...
