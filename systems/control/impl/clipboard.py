"""Collection and validation of Control's graph fragment clipboard format."""

from collections import defaultdict
from dataclasses import dataclass
from graphlib import CycleError, TopologicalSorter
import json


_FORMAT = "sloon-graph-fragment"
_VERSION = 1


@dataclass(frozen=True)
class _Fragment:
    root: int
    properties: dict[int, dict[str, str]]
    edges: list[tuple[int, int]]
    parents: dict[int, int]


def collect_fragment(
    root: int,
    properties: dict[int, dict[str, str]],
    edges: list[tuple[int, int]],
    *,
    include_outputs: bool,
) -> tuple[set[int], list[tuple[int, int]]]:
    """Collect from the stored topology and membership."""
    membership = {
        node_id: values.get("container_id", "")
        for node_id, values in properties.items()
    }
    members: dict[str, list[int]] = defaultdict(list)
    for node_id, parent in membership.items():
        members[parent].append(node_id)

    internal_edges = [
        (source, target) for source, target in edges
        if membership[source] == membership[target]
    ]
    outgoing: dict[int, list[int]] = defaultdict(list)
    if include_outputs:
        for source, target in internal_edges:
            outgoing[source].append(target)

    included: set[int] = set()
    pending = [root]
    while pending:
        node_id = pending.pop()
        if node_id in included:
            continue
        included.add(node_id)
        pending.extend(outgoing.get(node_id, ()))
        if properties[node_id].get("type") == "container":
            pending.extend(members.get(str(node_id), ()))

    return included, [
        (source, target) for source, target in internal_edges
        if source in included and target in included
    ]


def encode_fragment(
    root: int,
    properties: dict[int, dict[str, str]],
    edges: list[tuple[int, int]],
) -> str:
    return json.dumps({
        "format": _FORMAT,
        "version": _VERSION,
        "root": root,
        "nodes": [
            {"id": node_id, "properties": properties[node_id]}
            for node_id in sorted(properties)
        ],
        "edges": edges,
    })


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    values = dict(pairs)
    if len(values) != len(pairs):
        raise ValueError("duplicate JSON key")
    return values


def decode_fragment(text: str) -> _Fragment | None:
    if not isinstance(text, str):
        return None
    try:
        payload = json.loads(text, object_pairs_hook=_unique_json_object)
    except (ValueError, RecursionError):
        return None
    if not isinstance(payload, dict) or payload.keys() != {
        "format", "version", "root", "nodes", "edges",
    }:
        return None
    version, root = payload["version"], payload["root"]
    if (
        payload["format"] != _FORMAT
        or type(version) is not int
        or version != _VERSION
        or type(root) is not int
        or not isinstance(payload["nodes"], list)
        or not isinstance(payload["edges"], list)
    ):
        return None

    properties: dict[int, dict[str, str]] = {}
    for record in payload["nodes"]:
        if not isinstance(record, dict) or record.keys() != {"id", "properties"}:
            return None
        node_id, values = record["id"], record["properties"]
        if (
            type(node_id) is not int
            or node_id <= 0
            or node_id in properties
            or not isinstance(values, dict)
            or not all(key and isinstance(value, str) for key, value in values.items())
        ):
            return None
        # The source membership is replaced on paste, so Nodes never validates it.
        try:
            values.get("container_id", "").encode("utf-8")
        except UnicodeEncodeError:
            return None
        properties[node_id] = values
    if root not in properties:
        return None

    membership = {
        node_id: values.get("container_id", "") for node_id, values in properties.items()
    }
    top_level = membership[root]
    if top_level in {str(node_id) for node_id in properties}:
        return None
    containers = {
        str(node_id): node_id for node_id, values in properties.items()
        if values.get("type") == "container"
    }
    # Graph edges stay within membership groups, and containment descends
    # across groups. Acyclicity of both relationships can be checked together.
    predecessors = TopologicalSorter()
    parents: dict[int, int] = {}
    for node_id, parent in membership.items():
        if parent != top_level:
            if parent not in containers:
                return None
            parents[node_id] = containers[parent]
            predecessors.add(node_id, parents[node_id])

    edges: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for edge in payload["edges"]:
        if not isinstance(edge, list) or len(edge) != 2:
            return None
        source, target = edge
        if (
            type(source) is not int or type(target) is not int
            or source not in membership or target not in membership
            or membership[source] != membership[target]
            or (source, target) in seen
        ):
            return None
        seen.add((source, target))
        edges.append((source, target))
        predecessors.add(target, source)

    try:
        predecessors.prepare()
    except CycleError:
        return None
    return _Fragment(root, properties, edges, parents)
