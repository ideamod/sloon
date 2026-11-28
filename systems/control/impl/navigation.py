"""Graph control implementation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

from systems.graph_ui.spec.api import GraphUIAPI
from systems.logical_layout import calculate_layout
from systems.nodes import NodeNotFoundError, Nodes, NodesError
from systems.node_types.spec.api import NodeContext, NodeType
from systems.visible_graph import (
    VisibleGraph,
    calculate_reveal_plan,
    calculate_visible_graph,
    filter_container_graph,
)

from ..spec.api import NODE_COLORS, ControlAPI, Direction, NodeInfo, TitleSearchResult
from .clipboard import collect_fragment, decode_fragment, encode_fragment

_PROPERTY_DEFAULTS = {
    "type": "void",
    "title": "",
    "param": "",
    "status": "none",
    "note": "",
    "tags": "",
    "weight": "0",
}


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

    def enter_container(self) -> bool:
        with self._nodes.transaction():
            selected = self._existing_selection()
            if selected is None or self._nodes.get(selected, "type", "") != "container":
                return False
            self._graph_ui.set_active_container_id(str(selected))
            self._graph_ui.select_node(None)
        return True

    def leave_container(self) -> bool:
        with self._nodes.transaction():
            if not self._graph_ui.get_active_container_id():
                return False
            _, _, active_id = self._active_graph()
            if not active_id:
                self._graph_ui.set_active_container_id("")
                self._graph_ui.select_node(None)
                return True
            exited = int(active_id)
            parent_id = self._nodes.get(exited, "container_id", "")
            self._graph_ui.set_active_container_id(parent_id)
            self.select_node(exited)
        return True

    def select_node(self, node_id: int) -> bool:
        if not self.reveal_node(node_id):
            return False
        self._graph_ui.select_node(node_id)
        return True

    def reveal_node(self, node_id: int) -> bool:
        if type(node_id) is not int or not self._nodes.node_exists(node_id):
            return False
        nodes, edges, _ = self._active_graph()
        if node_id not in nodes:
            return False
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

        active_id = self._graph_ui.get_active_container_id()
        if active_id:
            _, _, active_id = self._active_graph()
        results: list[TitleSearchResult] = []
        for node_id in self._nodes.list_nodes():
            try:
                properties = self._nodes.get_many(
                    [node_id], ["title", "type", "status", "container_id"]
                )[node_id]
            except ValueError:
                # The graph may change between listing nodes and reading an
                # assignment. A deleted node is no longer a search result.
                continue
            if properties.get("container_id", "") != active_id:
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
        members, edges, _ = self._active_graph()
        visible_graph = self._visible_graph(members, edges)
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
        with self._nodes.transaction():
            members, edges, active_id = self._active_graph()
            selected = self._existing_selection(self._visible_graph(members, edges))
            if selected is None:
                return None
            new_node = self._create_node(active_id)
            self._nodes.connect(selected, new_node)
            self._graph_ui.select_node(new_node)
        return new_node

    def create_input(self) -> int | None:
        with self._nodes.transaction():
            members, edges, active_id = self._active_graph()
            selected = self._existing_selection(self._visible_graph(members, edges))
            if selected is None:
                return None
            new_node = self._create_node(active_id)
            self._nodes.connect(new_node, selected)
            self._graph_ui.select_node(new_node)
        return new_node

    def create_node(self) -> int:
        with self._nodes.transaction():
            _, _, active_id = self._active_graph()
            new_node = self._create_node(active_id)
            self._graph_ui.select_node(new_node)
        return new_node

    def _create_node(self, container_id: str) -> int:
        if container_id:
            return self._nodes.create_node(container_id=container_id)
        return self._nodes.create_node()

    def delete_selected(self) -> int | None:
        with self._nodes.transaction():
            members, edges, _ = self._active_graph()
            selected = self._existing_selection(self._visible_graph(members, edges))
            if selected is None:
                return None
            is_container = self._nodes.get(selected, "type", "") == "container"
            if is_container:
                deleted = self._delete_container(selected)
            else:
                self._nodes.delete_node(selected)
                deleted = {selected}
            first_input = next(
                (
                    source for source, target in edges
                    if target == selected and source not in deleted
                ),
                None,
            )
            if first_input is not None or is_container:
                self._graph_ui.select_node(first_input)
        return selected

    def _delete_container(self, container_id: int) -> set[int]:
        properties = self._nodes.get_many(
            self._nodes.list_nodes(), ["type", "container_id"],
        )
        children: dict[str, list[int]] = defaultdict(list)
        for node_id, values in properties.items():
            children[values.get("container_id", "")].append(node_id)

        pending = [container_id]
        visited: set[int] = set()
        while pending:
            node_id = pending.pop()
            if node_id in visited:
                continue
            visited.add(node_id)
            if properties[node_id].get("type") == "container":
                pending.extend(children.get(str(node_id), ()))
            self._nodes.delete_node(node_id)
        return visited

    def connect(self, target_id: int) -> bool:
        with self._nodes.transaction():
            members, internal_edges, _ = self._active_graph()
            selected = self._existing_selection(self._visible_graph(members, internal_edges))
            if (
                selected is None
                or type(target_id) is not int
                or target_id == selected
                or target_id not in members
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
        members, edges, _ = self._active_graph()
        selected = self._existing_selection(self._visible_graph(members, edges))
        if selected is None or not any(source == selected for source, _ in edges):
            return None
        collapsed_node_ids = self._graph_ui.get_collapsed_node_ids()
        collapsed = selected not in collapsed_node_ids
        self._graph_ui.set_node_collapsed(selected, collapsed)
        return collapsed

    def set_selected_type(self, type: str) -> bool:
        if not isinstance(type, str) or not type:
            return False
        with self._nodes.transaction():
            selected = self._existing_selection()
            if selected is None:
                return False
            if type != "container" and self._nodes.get(selected, "type", "") == "container":
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

    def copy_selected(self, *, include_outputs: bool = False) -> str | None:
        try:
            with self._nodes.transaction():
                selected = self._graph_ui.get_selected_node()
                if selected is None:
                    return None
                root_properties = self._nodes.get_all(selected)
                properties = {selected: root_properties}
                edges: list[tuple[int, int]] = []
                if include_outputs or root_properties.get("type") == "container":
                    node_ids = self._nodes.list_nodes()
                    membership = self._nodes.get_many(node_ids, ["type", "container_id"])
                    if include_outputs:
                        requested = self._graph_ui.get_active_container_id()
                        if requested:
                            # Resolve stale UI state without using the projection for copying.
                            _, _, requested = filter_container_graph(
                                node_ids, [], membership, requested,
                            )
                        if root_properties.get("container_id", "") != requested:
                            return None
                    included, edges = collect_fragment(
                        selected, membership, self._nodes.list_edges(),
                        include_outputs=include_outputs,
                    )
                    for node_id in included - properties.keys():
                        properties[node_id] = self._nodes.get_all(node_id)
        except NodeNotFoundError:
            return None
        return encode_fragment(selected, properties, edges)

    def paste_selected(self, clipboard_text: str) -> int | None:
        fragment = decode_fragment(clipboard_text)
        if fragment is None:
            return None

        try:
            with self._nodes.transaction():
                selected = self._graph_ui.get_selected_node()
                if selected is None:
                    return None
                members, _, active_id = self._active_graph()
                if selected not in members:
                    return None

                new_ids = {
                    original_id: self._nodes.create_node()
                    for original_id in fragment.properties
                }
                for original_id, properties in fragment.properties.items():
                    node_id = new_ids[original_id]
                    parent = fragment.parents.get(original_id)
                    container_id = active_id if parent is None else str(new_ids[parent])
                    if container_id:
                        self._nodes.set(node_id, "container_id", container_id)
                    for key, value in properties.items():
                        if key != "container_id":
                            self._nodes.set(node_id, key, value)
                for source, target in fragment.edges:
                    self._nodes.connect(new_ids[source], new_ids[target])
                new_root = new_ids[fragment.root]
                self._nodes.connect(selected, new_root)
        except NodesError:
            return None
        return new_root

    def execute_selected(self) -> bool:
        selected = self._existing_selection()
        if selected is None:
            return False
        node_type = self._resolve_node_type(self._nodes.get(selected, "type", "void"))
        node_type.execute(
            NodeContext(
                node_id=selected,
                workspace_path=self._workspace_path,
                nodes=self._nodes,
            )
        )
        return True

    def _active_graph(self) -> tuple[list[int], list[tuple[int, int]], str]:
        nodes = self._nodes.list_nodes()
        return filter_container_graph(
            nodes,
            self._nodes.list_edges(),
            self._nodes.get_many(nodes, ["type", "container_id"]),
            self._graph_ui.get_active_container_id(),
        )

    def _visible_graph(self, nodes: list[int], edges: list[tuple[int, int]]) -> VisibleGraph:
        return calculate_visible_graph(
            nodes, edges, self._graph_ui.get_collapsed_node_ids(),
        )

    def _existing_selection(
        self,
        visible_graph: VisibleGraph | None = None,
    ) -> int | None:
        selected = self._graph_ui.get_selected_node()
        if selected is None:
            return None
        if visible_graph is None:
            members, edges, _ = self._active_graph()
            visible_graph = self._visible_graph(members, edges)
        if selected not in visible_graph.nodes:
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
