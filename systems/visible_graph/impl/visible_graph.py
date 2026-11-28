"""Pure visible graph projection implementation."""

from __future__ import annotations

import heapq

from systems.visible_graph.spec.schema import VisibleGraph


def filter_container_graph(
    nodes: list[int],
    edges: list[tuple[int, int]],
    properties: dict[int, dict[str, str]],
    active_container_id: str,
) -> tuple[list[int], list[tuple[int, int]], str]:
    effective_id = active_container_id
    if effective_id:
        parents = {
            str(node_id): properties[node_id].get("container_id", "")
            for node_id in nodes
            if properties.get(node_id, {}).get("type") == "container"
        }
        visited = set()
        current = effective_id
        while current:
            if current in visited or current not in parents:
                effective_id = ""
                break
            visited.add(current)
            current = parents[current]

    members = [
        node_id for node_id in nodes
        if properties.get(node_id, {}).get("container_id", "") == effective_id
    ]
    member_ids = set(members)
    internal_edges = [
        (source, target) for source, target in edges
        if source in member_ids and target in member_ids
    ]
    return members, internal_edges, effective_id


def _validate_inputs(
    nodes: object,
    edges: object,
    collapsed_node_ids: object,
) -> tuple[list[int], list[tuple[int, int]], set[int]]:
    if not isinstance(nodes, list):
        raise ValueError("nodes must be a list")
    if any(type(node_id) is not int for node_id in nodes):
        raise ValueError("node IDs must be integers")
    if len(set(nodes)) != len(nodes):
        raise ValueError("node IDs must be unique")

    if not isinstance(edges, list):
        raise ValueError("edges must be a list")
    known_nodes = set(nodes)
    validated_edges: list[tuple[int, int]] = []
    seen_edges: set[tuple[int, int]] = set()
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
        if edge in seen_edges:
            raise ValueError("edges must be unique")
        seen_edges.add(edge)
        validated_edges.append(edge)

    if type(collapsed_node_ids) is not set:
        raise ValueError("collapsed_node_ids must be a set")
    if any(type(node_id) is not int for node_id in collapsed_node_ids):
        raise ValueError("collapsed node IDs must be integers")

    return nodes, validated_edges, collapsed_node_ids


def _graph_indexes(
    nodes: list[int],
    edges: list[tuple[int, int]],
) -> tuple[dict[int, list[int]], dict[int, int]]:
    children = {node_id: [] for node_id in nodes}
    incoming_counts = {node_id: 0 for node_id in nodes}
    for source, target in edges:
        children[source].append(target)
        incoming_counts[target] += 1
    return children, incoming_counts


def _validate_acyclic(
    nodes: list[int],
    children: dict[int, list[int]],
    incoming_counts: dict[int, int],
) -> None:
    remaining_incoming = dict(incoming_counts)
    ready = [node_id for node_id in nodes if remaining_incoming[node_id] == 0]
    ready_index = 0
    processed = 0
    while ready_index < len(ready):
        source = ready[ready_index]
        ready_index += 1
        processed += 1
        for target in children[source]:
            remaining_incoming[target] -= 1
            if remaining_incoming[target] == 0:
                ready.append(target)
    if processed != len(nodes):
        raise ValueError("graph must be acyclic")


def calculate_visible_graph(
    nodes: list[int],
    edges: list[tuple[int, int]],
    collapsed_node_ids: set[int],
) -> VisibleGraph:
    """Return the ordered projection reachable through non-collapsed paths."""
    validated_nodes, validated_edges, collapsed = _validate_inputs(
        nodes,
        edges,
        collapsed_node_ids,
    )
    children, incoming_counts = _graph_indexes(
        validated_nodes,
        validated_edges,
    )
    _validate_acyclic(validated_nodes, children, incoming_counts)

    visible: set[int] = set()
    pending = [
        node_id for node_id in validated_nodes if incoming_counts[node_id] == 0
    ]
    pending_index = 0
    while pending_index < len(pending):
        source = pending[pending_index]
        pending_index += 1
        if source in visible:
            continue
        visible.add(source)
        if source not in collapsed:
            pending.extend(children[source])

    return VisibleGraph(
        nodes=tuple(node_id for node_id in validated_nodes if node_id in visible),
        edges=tuple(
            edge
            for edge in validated_edges
            if edge[0] in visible
            and edge[1] in visible
            and edge[0] not in collapsed
        ),
    )


def calculate_reveal_plan(
    nodes: list[int],
    edges: list[tuple[int, int]],
    collapsed_node_ids: set[int],
    target_node_id: int,
) -> tuple[int, ...] | None:
    """Return the minimum-cost stable visibility route to a target."""
    validated_nodes, validated_edges, collapsed = _validate_inputs(
        nodes,
        edges,
        collapsed_node_ids,
    )
    children, incoming_counts = _graph_indexes(
        validated_nodes,
        validated_edges,
    )
    _validate_acyclic(validated_nodes, children, incoming_counts)
    if type(target_node_id) is not int:
        raise ValueError("target node ID must be an integer")
    if target_node_id not in set(validated_nodes):
        return None

    best_cost: dict[int, int] = {}
    predecessor: dict[int, int | None] = {}
    pending: list[tuple[int, int, int]] = []
    discovery_order = 0
    for root in validated_nodes:
        if incoming_counts[root] != 0:
            continue
        best_cost[root] = 0
        predecessor[root] = None
        heapq.heappush(pending, (0, discovery_order, root))
        discovery_order += 1

    while pending:
        cost, _order, node_id = heapq.heappop(pending)
        if cost != best_cost.get(node_id):
            continue
        if node_id == target_node_id:
            planned: list[int] = []
            current = node_id
            while predecessor[current] is not None:
                current = predecessor[current]
                if current in collapsed:
                    planned.append(current)
            planned.reverse()
            return tuple(planned)

        node_is_collapsed = node_id in collapsed
        next_cost = cost + int(node_is_collapsed)
        for child in children[node_id]:
            previous_cost = best_cost.get(child)
            if previous_cost is not None and previous_cost <= next_cost:
                continue
            best_cost[child] = next_cost
            predecessor[child] = node_id
            heapq.heappush(
                pending,
                (next_cost, discovery_order, child),
            )
            discovery_order += 1

    return None
