from dataclasses import dataclass


NODE_WIDTH = 12


@dataclass(frozen=True)
class Size:
    """Dimensions of a node in terminal cells or other units."""

    width: int
    height: int


@dataclass(frozen=True)
class Rect:
    """Position and dimensions of a node.

    X increases to the right.
    Y increases downward.
    Coordinates refer to the top-left corner.
    """

    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class Geometry:
    """Calculated geometry of a logical graph.

    nodes maps each node ID to its rectangle.
    width and height describe the bounding area
    occupied by all nodes, excluding trailing gaps.
    """

    nodes: dict[int, Rect]
    width: int
    height: int
