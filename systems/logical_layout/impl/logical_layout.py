from bisect import bisect_left
from collections.abc import Mapping as MappingABC
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from ..spec.api import LogicalLayoutAPI
from ..spec.schema import ComponentLayout, LogicalLayout


@dataclass(frozen=True, slots=True)
class _LogicalLayoutResult:
    layout: LogicalLayout
    _components: Mapping[int, int]
    _columns: Mapping[int, int]
    _positions: Mapping[int, int]
    _left: Mapping[int, int | None]
    _right: Mapping[int, int | None]
    _up: Mapping[int, int | None]
    _down: Mapping[int, int | None]

    def get_component(self, node_id: int) -> int:
        return self._components[node_id]

    def get_column(self, node_id: int) -> int:
        return self._columns[node_id]

    def get_position(self, node_id: int) -> int:
        return self._positions[node_id]

    def left(self, node_id: int) -> int | None:
        return self._left[node_id]

    def right(self, node_id: int) -> int | None:
        return self._right[node_id]

    def up(self, node_id: int) -> int | None:
        return self._up[node_id]

    def down(self, node_id: int) -> int | None:
        return self._down[node_id]


def _validate_input(
    nodes: list[int],
    edges: list[tuple[int, int]],
    weights: Mapping[int, int] | None,
) -> dict[int, int]:
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError("nodes and edges must be lists")
    if any(type(node_id) is not int for node_id in nodes):
        raise ValueError("node IDs must be integers")
    if len(set(nodes)) != len(nodes):
        raise ValueError("node IDs must be unique")

    known_nodes = set(nodes)
    for edge in edges:
        if not isinstance(edge, tuple) or len(edge) != 2:
            raise ValueError("each edge must be a pair")
        source, target = edge
        if type(source) is not int or type(target) is not int:
            raise ValueError("edge endpoints must be integers")
        if source not in known_nodes or target not in known_nodes:
            raise ValueError("edge endpoint does not exist")
        if source == target:
            raise ValueError("self-loops are not allowed")

    if weights is None:
        return {node_id: 0 for node_id in nodes}
    if not isinstance(weights, MappingABC):
        raise ValueError("weights must be a mapping")
    if any(
        type(node_id) is not int or node_id not in known_nodes
        for node_id in weights
    ):
        raise ValueError("weight node IDs must identify existing nodes")
    if any(type(weight) is not int for weight in weights.values()):
        raise ValueError("weights must be integers")
    return {node_id: weights.get(node_id, 0) for node_id in nodes}


def _closest_node(
    target_row: int,
    candidate_nodes: list[int],
    candidate_rows: list[int],
) -> int:
    insertion_index = bisect_left(candidate_rows, target_row)
    candidate_indexes = range(
        max(0, insertion_index - 1),
        min(len(candidate_nodes), insertion_index + 1),
    )
    best_index = min(
        candidate_indexes,
        key=lambda index: (
            abs(candidate_rows[index] - target_row),
            candidate_rows[index],
        ),
    )
    return candidate_nodes[best_index]


def calculate_layout(
    nodes: list[int],
    edges: list[tuple[int, int]],
    weights: Mapping[int, int] | None = None,
) -> LogicalLayoutAPI:
    node_weights = _validate_input(nodes, edges, weights)

    children: dict[int, list[int]] = {node_id: [] for node_id in nodes}
    undirected: dict[int, set[int]] = {node_id: set() for node_id in nodes}
    indegrees = {node_id: 0 for node_id in nodes}
    for source, target in edges:
        children[source].append(target)
        undirected[source].add(target)
        undirected[target].add(source)
        indegrees[target] += 1
    root_nodes = {node_id for node_id in nodes if indegrees[node_id] == 0}

    # Stable Kahn traversal calculates longest-path columns while also
    # validating that the directed graph is acyclic.
    ready = [node_id for node_id in nodes if indegrees[node_id] == 0]
    columns = {node_id: 0 for node_id in nodes}
    processed = 0
    ready_index = 0
    topological_order: list[int] = []
    while ready_index < len(ready):
        source = ready[ready_index]
        ready_index += 1
        processed += 1
        topological_order.append(source)
        for target in children[source]:
            columns[target] = max(columns[target], columns[source] + 1)
            indegrees[target] -= 1
            if indegrees[target] == 0:
                ready.append(target)

    if processed != len(nodes):
        raise ValueError("graph must be acyclic")

    # Keep sinks at their longest-path columns, then move every predecessor
    # right as far as possible without placing it beside or beyond a child.
    # This removes avoidable long edges such as a late-added root feeding a
    # node several columns into an otherwise deeper graph.
    for source in reversed(topological_order):
        if children[source]:
            columns[source] = min(columns[target] for target in children[source]) - 1

    # Discovering components in input order establishes the stable fallback
    # used when their root priorities are equal.
    component_nodes: list[set[int]] = []
    visited: set[int] = set()
    for first_node in nodes:
        if first_node in visited:
            continue
        component: set[int] = set()
        pending = [first_node]
        visited.add(first_node)
        while pending:
            node_id = pending.pop()
            component.add(node_id)
            for neighbor in undirected[node_id]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    pending.append(neighbor)
        component_nodes.append(component)

    component_nodes.sort(
        key=lambda component: -max(
            node_weights[node_id]
            for node_id in component
            if node_id in root_nodes
        )
    )

    width = max(columns.values(), default=-1) + 1
    component_indexes = {
        node_id: component_index
        for component_index, component in enumerate(component_nodes)
        for node_id in component
    }
    positions: dict[int, int] = {}
    component_layouts: list[ComponentLayout] = []
    global_rows: dict[int, int] = {}
    row_offset = 0

    columns_by_component = [
        [[] for _ in range(width)] for _ in range(len(component_nodes))
    ]
    for node_id in nodes:
        component_index = component_indexes[node_id]
        columns_by_component[component_index][columns[node_id]].append(node_id)

    for column_lists in columns_by_component:
        for column in column_lists:
            column.sort(key=lambda node_id: -node_weights[node_id])

    for column_lists in columns_by_component:
        component_height = max((len(column) for column in column_lists), default=0)
        for column in column_lists:
            for position, node_id in enumerate(column):
                positions[node_id] = position
                global_rows[node_id] = row_offset + position
        row_offset += component_height
        component_layouts.append(
            ComponentLayout(tuple(tuple(column) for column in column_lists))
        )

    layout = LogicalLayout(tuple(component_layouts))

    # Concatenating component columns produces global top-to-bottom order,
    # including the logical gaps caused by shorter component columns.
    nodes_by_column: list[list[int]] = [[] for _ in range(width)]
    for component in layout.components:
        for column_index, column in enumerate(component.columns):
            nodes_by_column[column_index].extend(column)
    rows_by_column = [
        [global_rows[node_id] for node_id in column] for column in nodes_by_column
    ]

    up: dict[int, int | None] = {}
    down: dict[int, int | None] = {}
    for column in nodes_by_column:
        for index, node_id in enumerate(column):
            up[node_id] = column[index - 1] if index else None
            down[node_id] = column[index + 1] if index + 1 < len(column) else None

    nearest_left: list[int | None] = []
    last_nonempty: int | None = None
    for column_index, column in enumerate(nodes_by_column):
        nearest_left.append(last_nonempty)
        if column:
            last_nonempty = column_index

    nearest_right: list[int | None] = [None] * width
    last_nonempty = None
    for column_index in range(width - 1, -1, -1):
        nearest_right[column_index] = last_nonempty
        if nodes_by_column[column_index]:
            last_nonempty = column_index

    left: dict[int, int | None] = {}
    right: dict[int, int | None] = {}
    for node_id in nodes:
        column_index = columns[node_id]
        left_column = nearest_left[column_index]
        right_column = nearest_right[column_index]
        left[node_id] = (
            _closest_node(
                global_rows[node_id],
                nodes_by_column[left_column],
                rows_by_column[left_column],
            )
            if left_column is not None
            else None
        )
        right[node_id] = (
            _closest_node(
                global_rows[node_id],
                nodes_by_column[right_column],
                rows_by_column[right_column],
            )
            if right_column is not None
            else None
        )

    immutable = MappingProxyType
    return _LogicalLayoutResult(
        layout=layout,
        _components=immutable(component_indexes),
        _columns=immutable(columns),
        _positions=immutable(positions),
        _left=immutable(left),
        _right=immutable(right),
        _up=immutable(up),
        _down=immutable(down),
    )
