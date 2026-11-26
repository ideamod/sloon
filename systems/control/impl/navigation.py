"""Graph control implementation."""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path

from systems.graph_ui.spec.api import GraphUIAPI
from systems.logical_layout import calculate_layout
from systems.nodes import NodeNotFoundError, Nodes, NodesError
from systems.node_types.spec.api import NodeContext, NodeType
from systems.visible_graph import (
    VisibleGraph,
    calculate_reveal_plan,
    calculate_visible_graph,
)

from ..spec.api import NODE_COLORS, ControlAPI, Direction, NodeInfo, TitleSearchResult

_PROPERTY_DEFAULTS = {
    "type": "void",
    "title": "",
    "param": "",
    "status": "none",
    "note": "",
    "tags": "",
    "weight": "0",
}


_CLIPBOARD_FORMAT = "sloon-node"
_CLIPBOARD_VERSION = 1


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    values = dict(pairs)
    if len(values) != len(pairs):
        raise ValueError("duplicate JSON key")
    return values


def _clipboard_properties(text: str) -> dict[str, str] | None:
    try:
        payload = json.loads(text, object_pairs_hook=_unique_json_object)
        if not isinstance(payload, dict) or payload.keys() != {
            "format", "version", "properties",
        }:
            return None
        version = payload["version"]
        if (
            payload["format"] != _CLIPBOARD_FORMAT
            or type(version) is not int
            or version != _CLIPBOARD_VERSION
        ):
            return None
        properties = payload["properties"]
        if not isinstance(properties, dict) or not all(
            isinstance(value, str) for value in properties.values()
        ):
            return None
        return properties
    except (ValueError, RecursionError):
        return None


def _effective_properties(properties: dict[str, str]) -> dict[str, str]:
    return {**_PROPERTY_DEFAULTS, **properties}


def _weight(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return 0


class _Control:
    def __init__(
        self,
        nodes: Nodes,
        graph_ui: GraphUIAPI,
        resolve_node_type: Callable[[str], NodeType],
        workspace_path: Path,
    ) -> None:
        self._nodes = nodes
        self._graph_ui = graph_ui
        self._resolve_node_type = resolve_node_type
        self._workspace_path = workspace_path

    def select_node(self, node_id: int) -> bool:
        if not self.reveal_node(node_id):
            return False
        self._graph_ui.select_node(node_id)
        return True

    def reveal_node(self, node_id: int) -> bool:
        if type(node_id) is not int or not self._nodes.node_exists(node_id):
            return False
        nodes = self._nodes.list_nodes()
        edges = self._nodes.list_edges()
        collapsed = self._graph_ui.get_collapsed_node_ids()
        plan = calculate_reveal_plan(nodes, edges, collapsed, node_id)
        if plan is None:
            return False
        for collapsed_node_id in plan:
            self._graph_ui.set_node_collapsed(collapsed_node_id, False)
        return True

    def get_selected_info(self) -> NodeInfo | None:
        selected = self._existing_selection()
        if selected is None:
            return None
        properties = _effective_properties(self._nodes.get_all(selected))
        return NodeInfo(
            node_id=selected,
            properties={**properties, "weight": _weight(properties["weight"])},
        )

    def search_titles(self, query: str) -> tuple[TitleSearchResult, ...]:
        if not isinstance(query, str):
            raise ValueError("query must be a string")
        needle = query.strip().casefold()
        if not needle:
            return ()

        results: list[TitleSearchResult] = []
        for node_id in self._nodes.list_nodes():
            try:
                properties = self._nodes.get_many(
                    [node_id], ["title", "type", "status"]
                )[node_id]
            except ValueError:
                # The graph may change between listing nodes and reading an
                # assignment. A deleted node is no longer a search result.
                continue
            properties = _effective_properties(properties)
            if not properties["title"] or needle not in properties["title"].casefold():
                continue
            results.append(
                TitleSearchResult(
                    node_id=node_id,
                    title=properties["title"],
                    type=properties["type"],
                    status=properties["status"],
                )
            )
        return tuple(results)

    def move(self, direction: Direction) -> int | None:
        visible_graph = self._visible_graph()
        selected = self._existing_selection(visible_graph)
        if selected is None:
            if not visible_graph.nodes:
                return None
            selected = visible_graph.nodes[0]
            self._graph_ui.select_node(selected)
            return selected

        layout = calculate_layout(
            list(visible_graph.nodes),
            list(visible_graph.edges),
            {
                node_id: _weight(properties.get("weight", "0"))
                for node_id, properties in self._nodes.get_many(
                    list(visible_graph.nodes), ["weight"]
                ).items()
            },
        )
        lookup = {
            Direction.LEFT: layout.left,
            Direction.RIGHT: layout.right,
            Direction.UP: layout.up,
            Direction.DOWN: layout.down,
        }
        if not isinstance(direction, Direction):
            raise ValueError("direction must be a Direction")
        target = lookup[direction](selected)
        if target is None:
            return selected
        self._graph_ui.select_node(target)
        return target

    def create_output(self) -> int | None:
        selected = self._existing_selection()
        if selected is None:
            return None

        with self._nodes.transaction():
            new_node = self._nodes.create_node()
            self._nodes.connect(selected, new_node)
        self._graph_ui.select_node(new_node)
        return new_node

    def create_input(self) -> int | None:
        selected = self._existing_selection()
        if selected is None:
            return None

        with self._nodes.transaction():
            new_node = self._nodes.create_node()
            self._nodes.connect(new_node, selected)
        self._graph_ui.select_node(new_node)
        return new_node

    def create_node(self) -> int:
        new_node = self._nodes.create_node()
        self._graph_ui.select_node(new_node)
        return new_node

    def delete_selected(self) -> int | None:
        selected = self._existing_selection()
        if selected is None:
            return None
        inputs = self._nodes.inputs(selected)
        self._nodes.delete_node(selected)
        if inputs:
            self._graph_ui.select_node(inputs[0])
        return selected

    def connect(self, target_id: int) -> bool:
        selected = self._existing_selection()
        if (
            selected is None
            or type(target_id) is not int
            or target_id == selected
            or not self._nodes.node_exists(target_id)
        ):
            return False

        edge = (selected, target_id)
        edges = self._nodes.list_edges()
        if edge not in edges:
            try:
                calculate_layout(self._nodes.list_nodes(), [*edges, edge])
            except ValueError:
                return False
        self._nodes.connect(*edge)
        return True

    def disconnect(self, other_id: int) -> bool:
        selected = self._existing_selection()
        if (
            selected is None
            or type(other_id) is not int
            or other_id == selected
            or not self._nodes.node_exists(other_id)
        ):
            return False
        self._nodes.disconnect(selected, other_id)
        self._nodes.disconnect(other_id, selected)
        return True

    def disconnect_all(self) -> int | None:
        selected = self._existing_selection()
        if selected is None:
            return None
        connected_edges = {
            (source, selected) for source in self._nodes.inputs(selected)
        }
        connected_edges.update(
            (selected, target) for target in self._nodes.outputs(selected)
        )
        for source, target in connected_edges:
            self._nodes.disconnect(source, target)
        return len(connected_edges)

    def set_node_width(self, width: int) -> bool:
        if type(width) is not int or width < 3:
            return False
        self._graph_ui.set_node_width(width)
        return True

    def set_node_height(self, height: int) -> bool:
        if type(height) is not int or height < 1:
            return False
        self._graph_ui.set_node_height(height)
        return True

    def toggle_node_ids(self) -> bool:
        show = not self._graph_ui.get_show_node_ids()
        self._graph_ui.set_show_node_ids(show)
        return show

    def toggle_selected_collapse(self) -> bool | None:
        selected = self._existing_selection()
        if selected is None or not self._nodes.outputs(selected):
            return None
        collapsed_node_ids = self._graph_ui.get_collapsed_node_ids()
        collapsed = selected not in collapsed_node_ids
        self._graph_ui.set_node_collapsed(selected, collapsed)
        return collapsed

    def set_selected_type(self, type: str) -> bool:
        if not isinstance(type, str) or not type:
            return False
        selected = self._existing_selection()
        if selected is None:
            return False
        self._nodes.set(selected, "type", type)
        return True

    def set_selected_param(self, param: str) -> bool:
        if not isinstance(param, str):
            return False
        selected = self._existing_selection()
        if selected is None:
            return False
        self._nodes.set(selected, "param", param)
        return True

    def set_selected_color(self, color: str) -> bool:
        if color not in (*NODE_COLORS, ""):
            return False
        selected = self._existing_selection()
        if selected is None:
            return False
        if color:
            self._nodes.set(selected, "color", color)
        else:
            self._nodes.delete_property(selected, "color")
        return True

    def set_selected_title(self, title: str) -> bool:
        if not isinstance(title, str):
            return False
        selected = self._existing_selection()
        if selected is None:
            return False
        self._nodes.set(selected, "title", title)
        return True

    def set_selected_status(self, status: str) -> bool:
        if status not in {
            "none",
            "progress",
            "success",
            "warning",
            "failure",
        }:
            return False
        selected = self._existing_selection()
        if selected is None:
            return False
        self._nodes.set(selected, "status", status)
        return True

    def set_selected_note(self, note: str) -> bool:
        if not isinstance(note, str):
            return False
        selected = self._existing_selection()
        if selected is None:
            return False
        self._nodes.set(selected, "note", note)
        return True

    def set_selected_tags(self, tags: str) -> bool:
        if not isinstance(tags, str):
            return False
        selected = self._existing_selection()
        if selected is None:
            return False
        self._nodes.set(selected, "tags", tags)
        return True

    def set_selected_weight(self, weight: int) -> bool:
        if type(weight) is not int:
            return False
        selected = self._existing_selection()
        if selected is None:
            return False
        self._nodes.set(selected, "weight", str(weight))
        return True

    def copy_selected(self) -> str | None:
        selected = self._graph_ui.get_selected_node()
        if selected is None:
            return None
        try:
            with self._nodes.transaction():
                properties = self._nodes.get_all(selected)
        except NodeNotFoundError:
            return None
        return json.dumps({
            "format": _CLIPBOARD_FORMAT,
            "version": _CLIPBOARD_VERSION,
            "properties": properties,
        })

    def paste_selected(self, clipboard_text: str) -> int | None:
        selected = self._graph_ui.get_selected_node()
        if selected is None:
            return None
        properties = _clipboard_properties(clipboard_text)
        if properties is None:
            return None

        try:
            with self._nodes.transaction():
                if not self._nodes.node_exists(selected):
                    return None
                node_id = self._nodes.create_node()
                # Property names such as "self" must be passed as data.
                for key, value in properties.items():
                    self._nodes.set(node_id, key, value)
                self._nodes.connect(selected, node_id)
        except NodesError:
            return None
        return node_id

    def execute_selected(self) -> bool:
        selected = self._existing_selection()
        if selected is None:
            return False
        properties = _effective_properties(self._nodes.get_all(selected))
        node_type = self._resolve_node_type(properties["type"])
        node_type.execute(
            NodeContext(
                node_id=selected,
                workspace_path=self._workspace_path,
                properties=properties,
                nodes=self._nodes,
            )
        )
        return True

    def _visible_graph(self) -> VisibleGraph:
        return calculate_visible_graph(
            self._nodes.list_nodes(),
            self._nodes.list_edges(),
            self._graph_ui.get_collapsed_node_ids(),
        )

    def _existing_selection(
        self,
        visible_graph: VisibleGraph | None = None,
    ) -> int | None:
        selected = self._graph_ui.get_selected_node()
        visible = visible_graph or self._visible_graph()
        if selected is None or selected not in visible.nodes:
            return None
        return selected


def open_control(
    nodes: Nodes,
    graph_ui: GraphUIAPI,
    resolve_node_type: Callable[[str], NodeType],
    *,
    workspace_path: Path,
) -> ControlAPI:
    return _Control(nodes, graph_ui, resolve_node_type, workspace_path)
