from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, cast

from systems.logical_layout.spec.schema import ComponentLayout, LogicalLayout

from ..spec.api import GeometryAPI
from ..spec.schema import NODE_WIDTH, Geometry, Rect, Size


@dataclass(frozen=True, slots=True)
class _GeometryResult:
    geometry: Geometry

    def get_rect(self, node_id: int) -> Rect:
        return self.geometry.nodes[node_id]


def _validate_gap(name: str, value: int) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _layout_nodes(layout: LogicalLayout) -> list[int]:
    if not isinstance(layout, LogicalLayout):
        raise ValueError("layout must be a LogicalLayout")
    if not isinstance(layout.components, tuple):
        raise ValueError("layout components must be a tuple")

    nodes: list[int] = []
    seen: set[int] = set()
    for component in layout.components:
        if not isinstance(component, ComponentLayout):
            raise ValueError("layout components must be ComponentLayout values")
        if not isinstance(component.columns, tuple):
            raise ValueError("component columns must be a tuple")
        for column in component.columns:
            if not isinstance(column, tuple):
                raise ValueError("component columns must contain tuples")
            for node_id in column:
                if type(node_id) is not int:
                    raise ValueError("node IDs must be integers")
                if node_id in seen:
                    raise ValueError("each node must occur exactly once")
                seen.add(node_id)
                nodes.append(node_id)
    return nodes


def _validate_sizes(nodes: list[int], sizes: dict[int, Size]) -> None:
    if not isinstance(sizes, dict):
        raise ValueError("sizes must be a dictionary")
    if any(type(node_id) is not int for node_id in sizes):
        raise ValueError("size keys must be integer node IDs")
    if set(sizes) != set(nodes):
        raise ValueError("sizes must contain exactly the layout nodes")
    for size in sizes.values():
        if not isinstance(size, Size):
            raise ValueError("every node size must be a Size")
        if (
            type(size.width) is not int
            or type(size.height) is not int
            or size.width <= 0
            or size.height <= 0
        ):
            raise ValueError("size dimensions must be positive integers")


def calculate_geometry(
    layout: LogicalLayout,
    sizes: dict[int, Size],
    column_gap: int = 4,
    row_gap: int = 0,
    component_gap: int = 1,
    node_width: int = NODE_WIDTH,
) -> GeometryAPI:
    _validate_gap("column_gap", column_gap)
    _validate_gap("row_gap", row_gap)
    _validate_gap("component_gap", component_gap)
    if type(node_width) is not int or node_width < 3:
        raise ValueError("node_width must be an integer of at least 3")
    nodes = _layout_nodes(layout)
    _validate_sizes(nodes, sizes)

    column_count = max(
        (len(component.columns) for component in layout.components),
        default=0,
    )
    column_widths = [0] * column_count
    for component in layout.components:
        for column_index, column in enumerate(component.columns):
            if column:
                column_widths[column_index] = node_width

    column_x: list[int] = []
    next_x = 0
    found_occupied_column = False
    for width in column_widths:
        column_x.append(next_x)
        if found_occupied_column or width:
            found_occupied_column = True
            next_x += width + column_gap

    rectangles: dict[int, Rect] = {}
    component_y = 0
    for component in layout.components:
        row_count = max((len(column) for column in component.columns), default=0)
        row_heights = [0] * row_count
        for column in component.columns:
            for row_index, node_id in enumerate(column):
                row_heights[row_index] = max(
                    row_heights[row_index], sizes[node_id].height
                )

        row_y: list[int] = []
        next_y = component_y
        for height in row_heights:
            row_y.append(next_y)
            next_y += height + row_gap

        for column_index, column in enumerate(component.columns):
            for row_index, node_id in enumerate(column):
                size = sizes[node_id]
                rectangles[node_id] = Rect(
                    x=column_x[column_index],
                    y=row_y[row_index],
                    width=node_width,
                    height=size.height,
                )

        component_height = (
            sum(row_heights) + row_gap * (row_count - 1)
            if row_count
            else 0
        )
        component_y += component_height + component_gap

    width = max((rect.x + rect.width for rect in rectangles.values()), default=0)
    height = max((rect.y + rect.height for rect in rectangles.values()), default=0)
    immutable_nodes: Mapping[int, Rect] = MappingProxyType(rectangles)
    geometry = Geometry(
        nodes=cast(dict[int, Rect], immutable_nodes),
        width=width,
        height=height,
    )
    return _GeometryResult(geometry)
