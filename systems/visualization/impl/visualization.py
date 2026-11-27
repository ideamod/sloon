"""Textual rendering implementation for the Visualization contract."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Callable, Mapping

from rich.style import Style
from rich.text import Text
from rich.cells import cell_len, get_character_cell_size
from textual.app import App, ComposeResult
from textual.containers import ScrollableContainer
from textual.geometry import Region
from textual.widget import Widget

from systems.geometry import calculate_geometry
from systems.geometry.spec.api import GeometryAPI
from systems.geometry.spec.schema import Geometry, Rect, Size
from systems.graph_ui.spec.api import GraphUIAPI
from systems.logical_layout import calculate_layout
from systems.logical_layout.spec.api import LogicalLayoutAPI
from systems.logical_layout.spec.schema import ComponentLayout, LogicalLayout
from systems.nodes import Nodes
from systems.node_types.spec.api import NodeContext, NodeRender, NodeType
from systems.visible_graph import VisibleGraph, calculate_visible_graph


_THEME_PATH = Path(__file__).resolve().parents[1] / "config" / "theme.yaml"
_THEME_KEYS = frozenset(("background-color", "text-color-normal", "text-color-selected", "selection-color", "border-color-normal", "border-color-selected", "edge-color", *(f"status-icon-color-{status}" for status in ("none", "progress", "success", "warning", "failure"))))

_NODE_COLOR_KEYS = frozenset(
    f"node-color-{color}"
    for color in ("green", "red", "blue", "white", "gray", "orange", "yellow")
)
_OPTIONAL_THEME_KEYS = _NODE_COLOR_KEYS | {
    f"{key}-selected" for key in _NODE_COLOR_KEYS
}


def _load_theme(path: Path = _THEME_PATH) -> dict[str, str]:
    """Read the deliberately flat YAML theme without another dependency."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ValueError(f"cannot read Visualization theme {path}: {error}") from error
    theme: dict[str, str] = {}
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in line or line[0].isspace():
            raise ValueError(f"invalid Visualization theme line {number}: expected key: '#RRGGBB'")
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip()
        if key not in _THEME_KEYS and key not in _OPTIONAL_THEME_KEYS:
            raise ValueError(f"unknown Visualization theme key {key!r} on line {number}")
        if key in theme:
            raise ValueError(f"duplicate Visualization theme key {key!r} on line {number}")
        if value.startswith(("'", '"')) and value.endswith(value[:1]):
            value = value[1:-1]
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            raise ValueError(f"Visualization theme {key}: expected #RRGGBB, got {value!r}")
        theme[key] = value.upper()
    missing = _THEME_KEYS - theme.keys()
    if missing:
        raise ValueError(f"Visualization theme missing key {sorted(missing)[0]!r}")
    return theme
_LINE_BREAKS = re.compile(r"\r\n|\r|\n")
_TITLE_CONTROLS = re.compile(r"[\x00-\x09\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_BORDER_GLYPHS = {
    "solid": ("─", "│"),
    "dashed": ("╌", "╎"),
}
_STATUS_STYLES = frozenset(("none", "progress", "success", "warning", "failure"))
_PROPERTY_DEFAULTS = {
    "type": "void",
    "title": "",
    "param": "",
    "status": "none",
    "note": "",
    "tags": "",
    "weight": "0",
}


@dataclass(frozen=True, slots=True)
class _Snapshot:
    raw_nodes: tuple[int, ...]
    raw_edges: tuple[tuple[int, int], ...]
    nodes: tuple[int, ...]
    edges: tuple[tuple[int, int], ...]
    collapsed_node_ids: frozenset[int]
    indicator_nodes: frozenset[int]
    selected_node: int | None
    node_width: int
    node_height: int
    show_node_ids: bool
    titles: Mapping[int, str]
    border_styles: Mapping[int, str]
    statuses: Mapping[int, str]
    colors: Mapping[int, str]
    weights: Mapping[int, int]
    wrapped_titles: Mapping[int, tuple[str, ...]]
    rectangles: Mapping[int, Rect]
    width: int
    height: int
    logical_layout: LogicalLayoutAPI


@dataclass(frozen=True, slots=True)
class _ReadState:
    raw_nodes: list[int]
    raw_edges: list[tuple[int, int]]
    visible_graph: VisibleGraph
    collapsed_node_ids: set[int]
    indicator_nodes: frozenset[int]
    selected_node: int | None
    node_width: int
    node_height: int
    show_node_ids: bool
    titles: dict[int, str]
    border_styles: dict[int, str]
    statuses: dict[int, str]
    colors: dict[int, str]
    weights: dict[int, int]


def _validate_dimensions(node_width: object, node_height: object) -> tuple[int, int]:
    if type(node_width) is not int or node_width < 3:
        raise ValueError("node_width must be an integer of at least 3")
    if type(node_height) is not int or node_height < 1:
        raise ValueError("node_height must be an integer of at least 1")
    return node_width, node_height


def _validate_show_node_ids(show_node_ids: object) -> bool:
    if type(show_node_ids) is not bool:
        raise ValueError("show_node_ids must be a boolean")
    return show_node_ids


def _validate_node_ids(node_ids: object) -> list[int]:
    if not isinstance(node_ids, list):
        raise ValueError("nodes must be a list")
    if any(type(node_id) is not int for node_id in node_ids):
        raise ValueError("node IDs must be integers")
    if len(set(node_ids)) != len(node_ids):
        raise ValueError("node IDs must be unique")
    return node_ids


def _validate_edges(edges: object, nodes: list[int]) -> list[tuple[int, int]]:
    if not isinstance(edges, list):
        raise ValueError("edges must be a list")
    known = set(nodes)
    result: list[tuple[int, int]] = []
    for edge in edges:
        if (
            not isinstance(edge, tuple)
            or len(edge) != 2
            or any(type(endpoint) is not int for endpoint in edge)
        ):
            raise ValueError("each edge must be an integer pair")
        if edge[0] not in known or edge[1] not in known:
            raise ValueError("edge endpoint does not exist")
        result.append(edge)
    return result


def _effective_properties(properties: object) -> dict[str, str]:
    if not isinstance(properties, dict):
        raise ValueError("node properties must be a dict")
    if any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in properties.items()
    ):
        raise ValueError("node properties must contain text keys and values")
    return {**_PROPERTY_DEFAULTS, **properties}


def _properties_title(properties: object) -> str:
    return _effective_properties(properties)["title"]


def _presentation_weight(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return 0


def _read_titles(
    node_ids: list[int], nodes: Nodes
) -> dict[int, str]:
    return {
        node_id: _properties_title(nodes.get_all(node_id))
        for node_id in node_ids
    }


def _read_presentations(
    node_ids: list[int],
    nodes: Nodes,
    node_type_resolver: Callable[[str], NodeType],
    workspace_path: Path,
) -> tuple[dict[int, str], dict[int, str], dict[int, str], dict[int, str], dict[int, int]]:
    titles: dict[int, str] = {}
    border_styles: dict[int, str] = {}
    statuses: dict[int, str] = {}
    colors: dict[int, str] = {}
    weights: dict[int, int] = {}
    for node_id in node_ids:
        properties = _effective_properties(nodes.get_all(node_id))
        title = _TITLE_CONTROLS.sub("", properties["title"])
        status = properties["status"]
        node_type = node_type_resolver(properties["type"])
        try:
            presentation = node_type.render(
                NodeContext(
                    node_id=node_id,
                    workspace_path=workspace_path,
                    properties=properties,
                    nodes=nodes,
                )
            )
        except ValueError:
            raise
        except Exception as error:
            raise ValueError("unable to render node type") from error
        if not isinstance(presentation, NodeRender):
            raise ValueError("node type render must return NodeRender")
        if not isinstance(presentation.title, str):
            raise ValueError("node render title must be a string")
        if presentation.border_style not in _BORDER_GLYPHS:
            raise ValueError(
                f"unsupported node border style: {presentation.border_style!r}"
            )
        titles[node_id] = title or _TITLE_CONTROLS.sub("", presentation.title)
        border_styles[node_id] = presentation.border_style
        statuses[node_id] = status if status in _STATUS_STYLES else "none"
        colors[node_id] = properties.get("color", "")
        weights[node_id] = _presentation_weight(properties["weight"])
    return titles, border_styles, statuses, colors, weights


def _project_visible_graph(
    raw_nodes: list[int],
    raw_edges: list[tuple[int, int]],
    collapsed_node_ids: set[int],
) -> tuple[VisibleGraph, frozenset[int]]:
    visible = calculate_visible_graph(
        raw_nodes,
        raw_edges,
        collapsed_node_ids,
    )
    sources_with_outputs = {source for source, _target in raw_edges}
    indicator_nodes = frozenset(
        node_id
        for node_id in visible.nodes
        if node_id in collapsed_node_ids and node_id in sources_with_outputs
    )
    return visible, indicator_nodes


def _read_dependency_state(
    nodes: Nodes,
    graph_ui: GraphUIAPI,
    node_type_resolver: Callable[[str], NodeType],
    workspace_path: Path,
) -> _ReadState:
    try:
        raw_nodes = _validate_node_ids(nodes.list_nodes())
        raw_edges = _validate_edges(nodes.list_edges(), raw_nodes)
        collapsed_node_ids = graph_ui.get_collapsed_node_ids()
        visible, indicator_nodes = _project_visible_graph(
            raw_nodes,
            raw_edges,
            collapsed_node_ids,
        )
        selected_node = graph_ui.get_selected_node()
        node_width, node_height = _validate_dimensions(
            graph_ui.get_node_width(),
            graph_ui.get_node_height(),
        )
        show_node_ids = _validate_show_node_ids(graph_ui.get_show_node_ids())
        titles, border_styles, statuses, colors, weights = _read_presentations(
            list(visible.nodes),
            nodes,
            node_type_resolver,
            workspace_path,
        )
    except ValueError:
        raise
    except Exception as error:
        raise ValueError("unable to read visualization dependencies") from error
    return _ReadState(
        raw_nodes=raw_nodes,
        raw_edges=raw_edges,
        visible_graph=visible,
        collapsed_node_ids=set(collapsed_node_ids),
        indicator_nodes=indicator_nodes,
        selected_node=selected_node,
        node_width=node_width,
        node_height=node_height,
        show_node_ids=show_node_ids,
        titles=titles,
        border_styles=border_styles,
        statuses=statuses,
        colors=colors,
        weights=weights,
    )


def measure_node_sizes(
    node_ids: list[int],
    nodes_api: Nodes,
    node_type_resolver: Callable[[str], NodeType],
    node_width: int = 12,
    node_height: int = 1,
    show_node_ids: bool = True,
) -> dict[int, Size]:
    """Measure the fixed occupied envelope for every supplied node."""
    del node_type_resolver
    nodes = _validate_node_ids(node_ids)
    width, height = _validate_dimensions(node_width, node_height)
    show_ids = _validate_show_node_ids(show_node_ids)
    _read_titles(nodes, nodes_api)
    if not nodes:
        return {}
    occupied_width = (
        max(width, *(len(str(node_id)) for node_id in nodes))
        if show_ids
        else width
    )
    size = Size(occupied_width, height + (3 if show_ids else 2))
    return {node_id: size for node_id in nodes}


def _fixed_sizes(
    nodes: list[int],
    node_width: int,
    node_height: int,
    show_node_ids: bool,
) -> dict[int, Size]:
    if not nodes:
        return {}
    occupied_width = (
        max(node_width, *(len(str(node)) for node in nodes))
        if show_node_ids
        else node_width
    )
    size = Size(occupied_width, node_height + (3 if show_node_ids else 2))
    return {node: size for node in nodes}


def _layout_nodes(logical_layout: LogicalLayoutAPI) -> list[int]:
    try:
        layout = logical_layout.layout
    except Exception as error:
        raise ValueError("invalid logical layout") from error
    if not isinstance(layout, LogicalLayout) or not isinstance(layout.components, tuple):
        raise ValueError("invalid logical layout")
    nodes: list[int] = []
    for component in layout.components:
        if not isinstance(component, ComponentLayout) or not isinstance(
            component.columns, tuple
        ):
            raise ValueError("invalid logical layout")
        for column in component.columns:
            if not isinstance(column, tuple):
                raise ValueError("invalid logical layout")
            nodes.extend(column)
    if any(type(node) is not int for node in nodes) or len(set(nodes)) != len(nodes):
        raise ValueError("invalid logical layout")
    return nodes


def _geometry_state(geometry_api: GeometryAPI) -> Geometry:
    try:
        geometry = geometry_api.geometry
    except Exception as error:
        raise ValueError("invalid geometry") from error
    if not isinstance(geometry, Geometry) or not isinstance(geometry.nodes, Mapping):
        raise ValueError("invalid geometry")
    return geometry


def _validated_rectangles(
    geometry_api: GeometryAPI,
    nodes: list[int],
    sizes: Mapping[int, Size],
) -> tuple[dict[int, Rect], int, int]:
    geometry = _geometry_state(geometry_api)
    if set(geometry.nodes) != set(nodes):
        raise ValueError("geometry must contain exactly the graph nodes")
    rectangles: dict[int, Rect] = {}
    for node_id in nodes:
        rect = geometry.nodes[node_id]
        expected = sizes[node_id]
        if (
            not isinstance(rect, Rect)
            or any(type(v) is not int for v in (rect.x, rect.y, rect.width, rect.height))
            or rect.x < 0
            or rect.y < 0
            or rect.width != expected.width
            or rect.height != expected.height
        ):
            raise ValueError("geometry rectangle has invalid dimensions")
        rectangles[node_id] = rect
    width = max((rect.x + rect.width for rect in rectangles.values()), default=0)
    height = max((rect.y + rect.height for rect in rectangles.values()), default=0)
    if (
        type(geometry.width) is not int
        or type(geometry.height) is not int
        or geometry.width != width
        or geometry.height != height
    ):
        raise ValueError("geometry bounds are invalid")
    return rectangles, width, height


def _fitting_prefix(text: str, cell_width: int) -> int:
    used = 0
    for index, character in enumerate(text):
        width = get_character_cell_size(character)
        if used + width > cell_width:
            return index
        used += width
    return len(text)


def _pad_cells(text: str, width: int) -> str:
    return text + " " * max(0, width - cell_len(text))


def _truncate_cells(text: str, width: int) -> str:
    return text[: _fitting_prefix(text, width)]


def _wrap_title(title: str, width: int, height: int) -> tuple[str, ...]:
    remaining = _LINE_BREAKS.sub(" ", title)
    rows: list[str] = []
    for _ in range(height):
        if not remaining:
            rows.append(" " * width)
            continue
        fit = _fitting_prefix(remaining, width)
        if fit == len(remaining):
            line, remaining = remaining, ""
        else:
            boundary = fit if remaining[fit].isspace() else -1
            if boundary < 0:
                for index in range(fit - 1, -1, -1):
                    if remaining[index].isspace():
                        boundary = index
                        break
            if boundary > 0:
                line = remaining[:boundary].rstrip()
                remaining = remaining[boundary:].lstrip()
            else:
                split = max(1, fit)
                line, remaining = remaining[:split], remaining[split:]
        rows.append(_pad_cells(line, width))
    if remaining and rows:
        visible = rows[-1].rstrip()
        if cell_len(visible) >= width:
            visible = _truncate_cells(visible, width - 1)
        rows[-1] = _pad_cells(visible + "…", width)
    return tuple(rows)


def _make_snapshot(
    *,
    raw_nodes: list[int],
    raw_edges: list[tuple[int, int]],
    nodes: list[int],
    edges: list[tuple[int, int]],
    collapsed_node_ids: set[int],
    indicator_nodes: frozenset[int],
    selected_node: int | None,
    node_width: int,
    node_height: int,
    show_node_ids: bool,
    titles: dict[int, str],
    border_styles: dict[int, str],
    statuses: dict[int, str],
    colors: dict[int, str],
    weights: dict[int, int],
    logical_layout: LogicalLayoutAPI,
    geometry: GeometryAPI,
) -> _Snapshot:
    if type(selected_node) is not int and selected_node is not None:
        raise ValueError("selected node must be an integer or None")
    if indicator_nodes and node_width < 6:
        raise ValueError(
            "node_width must be at least 6 for a collapsed-node indicator"
        )
    layout_nodes = _layout_nodes(logical_layout)
    if set(layout_nodes) != set(nodes) or len(layout_nodes) != len(nodes):
        raise ValueError("layout must contain exactly the graph nodes")
    show_ids = _validate_show_node_ids(show_node_ids)
    sizes = _fixed_sizes(nodes, node_width, node_height, show_ids)
    rectangles, width, height = _validated_rectangles(geometry, nodes, sizes)
    wrapped = {
        node: _wrap_title(
            titles[node],
            node_width - (5 if node in indicator_nodes else 2),
            node_height,
        )
        for node in nodes
    }
    return _Snapshot(
        tuple(raw_nodes),
        tuple(raw_edges),
        tuple(nodes),
        tuple(edges),
        frozenset(collapsed_node_ids),
        indicator_nodes,
        selected_node if selected_node in set(nodes) else None,
        node_width,
        node_height,
        show_ids,
        dict(titles),
        dict(border_styles),
        dict(statuses),
        dict(colors),
        dict(weights),
        wrapped,
        rectangles,
        width,
        height,
        logical_layout,
    )


def _edge_character(mask: int) -> str:
    left, right, up, down = 1, 2, 4, 8
    return {
        left | right: "─",
        up | down: "│",
        right | down: "╭",
        left | down: "╮",
        right | up: "╰",
        left | up: "╯",
        left | up | down: "┤",
        right | up | down: "├",
        left | right | up: "┴",
        left | right | down: "┬",
        left | right | up | down: "┼",
    }.get(mask, "─" if mask & 3 else "│")


def _render_snapshot(snapshot: _Snapshot, theme: Mapping[str, str] | None = None) -> tuple[Text, int, int]:
    theme = _load_theme() if theme is None else theme
    normal_background = theme["background-color"]
    edge_style = Style(color=theme["edge-color"], bgcolor=normal_background)
    width, height = max(1, snapshot.width), max(1, snapshot.height)
    cells = [[" " for _ in range(width)] for _ in range(height)]
    styles: list[list[Style | None]] = [[None for _ in range(width)] for _ in range(height)]
    occupied = {
        (x, y)
        for rect in snapshot.rectangles.values()
        for y in range(rect.y, rect.y + rect.height)
        for x in range(rect.x, rect.x + rect.width)
    }
    masks: dict[tuple[int, int], int] = {}
    arrows: dict[tuple[int, int], str] = {}
    left, right, up, down = 1, 2, 4, 8

    def connect(first: tuple[int, int], second: tuple[int, int]) -> None:
        if first in occupied or second in occupied:
            return
        x1, y1 = first
        x2, y2 = second
        if x2 == x1 + 1:
            masks[first] = masks.get(first, 0) | right
            masks[second] = masks.get(second, 0) | left
        elif x2 == x1 - 1:
            masks[first] = masks.get(first, 0) | left
            masks[second] = masks.get(second, 0) | right
        elif y2 == y1 + 1:
            masks[first] = masks.get(first, 0) | down
            masks[second] = masks.get(second, 0) | up
        elif y2 == y1 - 1:
            masks[first] = masks.get(first, 0) | up
            masks[second] = masks.get(second, 0) | down

    def path(points: list[tuple[int, int]]) -> None:
        for start, end in zip(points, points[1:]):
            x, y = start
            dx, dy = (end[0] > x) - (end[0] < x), (end[1] > y) - (end[1] < y)
            while (x, y) != end:
                following = (x + dx, y + dy)
                connect((x, y), following)
                x, y = following

    for source, target in snapshot.edges:
        source_rect, target_rect = snapshot.rectangles[source], snapshot.rectangles[target]
        source_x = source_rect.x + source_rect.width - snapshot.node_width
        target_x = target_rect.x + target_rect.width - snapshot.node_width
        source_y = source_rect.y + 1 + (snapshot.node_height - 1) // 2
        target_y = target_rect.y + 1 + (snapshot.node_height - 1) // 2
        if target_x > source_x:
            start_x, arrow_x = source_x + snapshot.node_width, target_x - 1
            if arrow_x < start_x:
                continue
            arrows[(arrow_x, target_y)] = "▶"
            if source_y == target_y:
                path([(start_x, source_y), (arrow_x - 1, target_y)])
            else:
                route_x = min(start_x + 1, arrow_x - 1)
                path([(start_x, source_y), (route_x, source_y), (route_x, target_y), (arrow_x - 1, target_y)])
        elif target_x + snapshot.node_width <= source_x:
            start_x, arrow_x = source_x - 1, target_x + snapshot.node_width
            if arrow_x > start_x:
                continue
            arrows[(arrow_x, target_y)] = "◀"
            route_x = max(start_x - 1, arrow_x + 1)
            path([(start_x, source_y), (route_x, source_y), (route_x, target_y), (arrow_x + 1, target_y)])

    for (x, y), mask in masks.items():
        if 0 <= x < width and 0 <= y < height and (x, y) not in occupied:
            cells[y][x], styles[y][x] = _edge_character(mask), edge_style
    for (x, y), arrow in arrows.items():
        if 0 <= x < width and 0 <= y < height and (x, y) not in occupied:
            cells[y][x], styles[y][x] = arrow, edge_style

    def put(x: int, y: int, value: str, style: Style) -> None:
        cursor = x
        for character in value:
            cell_width = get_character_cell_size(character)
            if cell_width == 0:
                if cursor > x:
                    cells[y][cursor - 1] += character
                continue
            if cursor + cell_width > width:
                break
            cells[y][cursor], styles[y][cursor] = character, style
            for extra in range(1, cell_width):
                cells[y][cursor + extra], styles[y][cursor + extra] = "", style
            cursor += cell_width

    for node in snapshot.nodes:
        rect = snapshot.rectangles[node]
        main_x, main_y = rect.x + rect.width - snapshot.node_width, rect.y
        selected = node == snapshot.selected_node
        background = theme["selection-color"] if selected else normal_background
        border_color = theme["border-color-selected" if selected else "border-color-normal"]
        color_key = f"node-color-{snapshot.colors[node]}"
        if color_key in _NODE_COLOR_KEYS:
            if selected:
                color_key += "-selected"
            border_color = theme.get(color_key, border_color)
        style = Style(color=theme["text-color-selected" if selected else "text-color-normal"], bgcolor=background, bold=selected)
        border_style = Style(color=border_color, bgcolor=background, bold=selected)
        horizontal, vertical = _BORDER_GLYPHS[snapshot.border_styles[node]]
        if node in snapshot.indicator_nodes:
            title_width = snapshot.node_width - 5
            put(
                main_x,
                main_y,
                "■" + horizontal * title_width + "┬" + horizontal * 2 + "┐",
                border_style,
            )
            for index, row in enumerate(snapshot.wrapped_titles[node]):
                y = main_y + 1 + index
                put(main_x, y, vertical, border_style)
                put(main_x + 1, y, row, style)
                separator_x = main_x + snapshot.node_width - 4
                put(separator_x, y, vertical, border_style)
                put(separator_x + 1, y, "+".center(2), style)
                put(main_x + snapshot.node_width - 1, y, vertical, border_style)
            put(
                main_x,
                main_y + snapshot.node_height + 1,
                "└" + horizontal * title_width + "┴" + horizontal * 2 + "┘",
                border_style,
            )
        else:
            put(
                main_x,
                main_y,
                "■" + horizontal * (snapshot.node_width - 2) + "┐",
                border_style,
            )
            for index, row in enumerate(snapshot.wrapped_titles[node]):
                y = main_y + 1 + index
                put(main_x, y, vertical, border_style)
                put(main_x + 1, y, row, style)
                put(main_x + snapshot.node_width - 1, y, vertical, border_style)
            put(
                main_x,
                main_y + snapshot.node_height + 1,
                "└" + horizontal * (snapshot.node_width - 2) + "┘",
                border_style,
            )
        indicator_style = Style(color=theme[f"status-icon-color-{snapshot.statuses[node]}"], bgcolor=background, bold=selected)
        put(main_x, main_y, "■", indicator_style)
        if snapshot.show_node_ids:
            node_text = str(node)
            put(rect.x + rect.width - len(node_text), main_y + snapshot.node_height + 2, node_text, style)

    rendered = Text(style=Style(bgcolor=normal_background))
    for y, row in enumerate(cells):
        for x, character in enumerate(row):
            if character:
                rendered.append(character, style=styles[y][x])
        if y + 1 < height:
            rendered.append("\n")
    return rendered, width, height


class _GraphCanvas(Widget):
    def __init__(self, snapshot: _Snapshot, theme: Mapping[str, str] | None = None) -> None:
        super().__init__()
        self._snapshot = snapshot
        self._theme = _load_theme() if theme is None else theme
        self._apply_size()

    def _apply_size(self) -> None:
        self.styles.width = max(1, self._snapshot.width)
        self.styles.height = max(1, self._snapshot.height)

    def update_snapshot(self, snapshot: _Snapshot) -> None:
        self._snapshot = snapshot
        self._apply_size()
        self.refresh(layout=True)

    def render(self) -> Text:
        return _render_snapshot(self._snapshot, self._theme)[0]


class _VisualizationApp(App[None]):
    CSS = """
    Screen { overflow: hidden; background: transparent; }
    #graph-viewport { width: 100%; height: 100%; overflow: auto; background: transparent; }
    _GraphCanvas { padding: 0; margin: 0; background: transparent; }
    """

    def __init__(self, snapshot: _Snapshot, poll_snapshot: Callable[[], _Snapshot], theme: Mapping[str, str] | None = None) -> None:
        super().__init__()
        self._initial_snapshot = snapshot
        self._poll_snapshot = poll_snapshot
        self._theme = _load_theme() if theme is None else theme

    def compose(self) -> ComposeResult:
        with ScrollableContainer(id="graph-viewport"):
            yield _GraphCanvas(self._initial_snapshot, self._theme)

    def on_mount(self) -> None:
        background = self._theme["background-color"]
        self.screen.styles.background = background
        self.query_one("#graph-viewport", ScrollableContainer).styles.background = background
        self.query_one(_GraphCanvas).styles.background = background
        self.set_interval(0.1, self._poll)
        self.call_after_refresh(self._scroll_selected)

    def _poll(self) -> None:
        canvas = self.query_one(_GraphCanvas)
        snapshot = self._poll_snapshot()
        if snapshot != canvas._snapshot:
            canvas.update_snapshot(snapshot)
            self.call_after_refresh(self._scroll_selected)

    def _scroll_selected(self) -> None:
        canvas = self.query_one(_GraphCanvas)
        selected = canvas._snapshot.selected_node
        if selected is None:
            return
        rect = canvas._snapshot.rectangles[selected]
        self.query_one("#graph-viewport", ScrollableContainer).scroll_to_region(
            Region(rect.x, rect.y, rect.width, rect.height),
            animate=False,
            force=True,
            immediate=True,
        )


@dataclass(frozen=True, slots=True)
class _StaticGeometry:
    geometry: Geometry

    def get_rect(self, node_id: int) -> Rect:
        return self.geometry.nodes[node_id]


class _Visualization:
    def __init__(
        self,
        nodes: Nodes,
        graph_ui: GraphUIAPI,
        node_type_resolver: Callable[[str], NodeType],
        workspace_path: Path,
        snapshot: _Snapshot,
        theme: Mapping[str, str],
    ) -> None:
        self._nodes = nodes
        self._graph_ui = graph_ui
        self._node_type_resolver = node_type_resolver
        self._workspace_path = workspace_path
        self._snapshot = snapshot
        self._theme = theme

    def run(self) -> None:
        _VisualizationApp(self._snapshot, self._poll_snapshot, self._theme).run()

    def _read_state(self) -> _ReadState:
        return _read_dependency_state(
            self._nodes,
            self._graph_ui,
            self._node_type_resolver,
            self._workspace_path,
        )

    def refresh(self, logical_layout: LogicalLayoutAPI | None = None, geometry: GeometryAPI | None = None) -> None:
        if (logical_layout is None) != (geometry is None):
            raise ValueError("logical_layout and geometry must be supplied together")
        state = self._read_state()
        nodes = list(state.visible_graph.nodes)
        edges = list(state.visible_graph.edges)
        if logical_layout is None:
            if (tuple(state.raw_nodes), tuple(state.raw_edges)) != (
                self._snapshot.raw_nodes,
                self._snapshot.raw_edges,
            ):
                raise ValueError("graph topology changed without updated placement")
            display_changed = (
                tuple(nodes) != self._snapshot.nodes
                or tuple(edges) != self._snapshot.edges
                or state.indicator_nodes != self._snapshot.indicator_nodes
                or state.weights != self._snapshot.weights
            )
            sizes = _fixed_sizes(
                nodes,
                state.node_width,
                state.node_height,
                state.show_node_ids,
            )
            occupied_width = (
                next(iter(sizes.values())).width
                if sizes
                else state.node_width
            )
            if display_changed:
                logical_layout = calculate_layout(nodes, edges, state.weights)
                geometry = calculate_geometry(
                    logical_layout.layout,
                    sizes,
                    node_width=occupied_width,
                )
            else:
                logical_layout = self._snapshot.logical_layout
                old_occupied = (
                    next(iter(self._snapshot.rectangles.values())).width
                    if self._snapshot.rectangles
                    else self._snapshot.node_width
                )
                if (
                    state.node_width != self._snapshot.node_width
                    or state.node_height != self._snapshot.node_height
                    or state.show_node_ids != self._snapshot.show_node_ids
                    or old_occupied != occupied_width
                ):
                    geometry = calculate_geometry(
                        logical_layout.layout,
                        sizes,
                        node_width=occupied_width,
                    )
                else:
                    geometry = _StaticGeometry(
                        Geometry(
                            dict(self._snapshot.rectangles),
                            self._snapshot.width,
                            self._snapshot.height,
                        )
                    )
        assert logical_layout is not None and geometry is not None
        candidate = _make_snapshot(
            raw_nodes=state.raw_nodes,
            raw_edges=state.raw_edges,
            nodes=nodes,
            edges=edges,
            collapsed_node_ids=state.collapsed_node_ids,
            indicator_nodes=state.indicator_nodes,
            selected_node=state.selected_node,
            node_width=state.node_width,
            node_height=state.node_height,
            show_node_ids=state.show_node_ids,
            titles=state.titles,
            border_styles=state.border_styles,
            statuses=state.statuses,
            colors=state.colors,
            weights=state.weights,
            logical_layout=logical_layout,
            geometry=geometry,
        )
        self._snapshot = candidate

    def _poll_snapshot(self) -> _Snapshot:
        try:
            state = self._read_state()
            if (tuple(state.raw_nodes), tuple(state.raw_edges)) != (
                self._snapshot.raw_nodes,
                self._snapshot.raw_edges,
            ):
                nodes = list(state.visible_graph.nodes)
                edges = list(state.visible_graph.edges)
                layout = calculate_layout(nodes, edges, state.weights)
                sizes = _fixed_sizes(
                    nodes,
                    state.node_width,
                    state.node_height,
                    state.show_node_ids,
                )
                occupied_width = (
                    next(iter(sizes.values())).width
                    if sizes
                    else state.node_width
                )
                geometry = calculate_geometry(
                    layout.layout,
                    sizes,
                    node_width=occupied_width,
                )
                self.refresh(layout, geometry)
            else:
                self.refresh()
        except Exception:
            pass
        return self._snapshot


def open_visualization(
    nodes_api: Nodes,
    graph_ui: GraphUIAPI,
    node_type_resolver: Callable[[str], NodeType],
    logical_layout: LogicalLayoutAPI,
    geometry: GeometryAPI,
    *,
    workspace_path: Path,
) -> _Visualization:
    """Create a viewer over application-owned graph and placement APIs."""
    theme = _load_theme()
    try:
        state = _read_dependency_state(
            nodes_api,
            graph_ui,
            node_type_resolver,
            workspace_path,
        )
        nodes = list(state.visible_graph.nodes)
        edges = list(state.visible_graph.edges)
        snapshot = _make_snapshot(
            raw_nodes=state.raw_nodes,
            raw_edges=state.raw_edges,
            nodes=nodes,
            edges=edges,
            collapsed_node_ids=state.collapsed_node_ids,
            indicator_nodes=state.indicator_nodes,
            selected_node=state.selected_node,
            node_width=state.node_width,
            node_height=state.node_height,
            show_node_ids=state.show_node_ids,
            titles=state.titles,
            border_styles=state.border_styles,
            statuses=state.statuses,
            colors=state.colors,
            weights=state.weights,
            logical_layout=logical_layout,
            geometry=geometry,
        )
    except ValueError:
        raise
    except Exception as error:
        raise ValueError("invalid visualization dependencies") from error
    return _Visualization(nodes_api, graph_ui, node_type_resolver, workspace_path, snapshot, theme)
