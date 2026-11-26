"""Contract tests derived from the public Visualization specifications."""

from __future__ import annotations

import asyncio
from pathlib import Path
from dataclasses import dataclass, field
from typing import Callable

import pytest
from rich.style import Style
from rich.text import Text
from textual.containers import ScrollableContainer
from textual.color import Color
from textual.geometry import Region

from systems.geometry import calculate_geometry
from systems.geometry.spec.schema import NODE_WIDTH, Geometry, Rect, Size
from systems.logical_layout import calculate_layout
from systems.logical_layout.spec.schema import ComponentLayout, LogicalLayout
from systems.node_types.spec.api import NodeContext, NodeRender
from systems.visualization import (
    measure_node_sizes as measure_nodes_sizes,
    open_visualization as open_nodes_visualization,
)
from systems.visualization.impl import visualization as visualization_impl
from systems.visualization.impl.visualization import (
    _GraphCanvas,
    _VisualizationApp,
    _render_snapshot,
)
from systems.visible_graph import calculate_visible_graph


@dataclass(frozen=True)
class NodeAssignment:
    type: str
    param: str
    title: str = ""
    status: str = "none"
    note: str = ""
    tags: str = ""
    weight: int = 0


def test_theme_loads_relative_to_visualization_and_validates_values(monkeypatch, tmp_path) -> None:
    theme_path = Path(visualization_impl.__file__).resolve().parents[1] / "config/theme.yaml"
    monkeypatch.chdir(tmp_path)
    theme = visualization_impl._load_theme(theme_path)
    assert theme["selection-color"] == "#173B4A"
    invalid = tmp_path / "theme.yaml"
    invalid.write_text(
        theme_path.read_text().replace('"#173B4A"', '"cyan"')
    )
    with pytest.raises(ValueError, match="selection-color.*#RRGGBB"):
        visualization_impl._load_theme(invalid)


def test_configured_theme_styles_nodes_edges_and_status(monkeypatch) -> None:
    viewer, _, _, _, _ = open_styled_viewer(status="failure", show_node_ids=False)
    theme = dict(viewer._theme)
    theme.update({"selection-color": "#123456", "status-icon-color-failure": "#ABCDEF"})
    viewer._theme = theme
    rendered, width, _ = visualization_impl._render_snapshot(viewer._snapshot, viewer._theme)
    assert style_at(rendered, width, 0, 0).color == Style(color="#ABCDEF").color


def test_theme_rejects_missing_duplicate_and_unknown_keys(tmp_path) -> None:
    source = (Path(visualization_impl.__file__).resolve().parents[1] / "config/theme.yaml").read_text()
    cases = (
        (source.replace('edge-color: "#60758B"\n', ""), "missing key.*edge-color"),
        (source + '\nedge-color: "#010203"\n', "duplicate.*edge-color"),
        (source + '\nstray-color: "#010203"\n', "unknown.*stray-color"),
    )
    for content, message in cases:
        path = tmp_path / "theme.yaml"
        path.write_text(content)
        with pytest.raises(ValueError, match=message):
            visualization_impl._load_theme(path)


def test_background_color_requires_hexadecimal_rgb(tmp_path) -> None:
    source = (Path(visualization_impl.__file__).resolve().parents[1] / "config/theme.yaml").read_text()
    path = tmp_path / "theme.yaml"
    path.write_text(
        source.replace('background-color: "#101722"', "background-color: default")
    )
    with pytest.raises(ValueError, match="background-color.*#RRGGBB"):
        visualization_impl._load_theme(path)


def test_default_is_invalid_for_other_theme_colors(tmp_path) -> None:
    source = (Path(visualization_impl.__file__).resolve().parents[1] / "config/theme.yaml").read_text()
    path = tmp_path / "theme.yaml"
    path.write_text(
        source.replace(
            'text-color-normal: "#E2E8F0"',
            "text-color-normal: default",
        )
    )
    with pytest.raises(ValueError, match="text-color-normal.*#RRGGBB"):
        visualization_impl._load_theme(path)


def test_explicit_background_color_remains_supported(tmp_path) -> None:
    source = (Path(visualization_impl.__file__).resolve().parents[1] / "config/theme.yaml").read_text()
    path = tmp_path / "theme.yaml"
    path.write_text(
        source.replace(
            'background-color: "#101722"',
            'background-color: "#102030"',
        )
    )
    theme = visualization_impl._load_theme(path)
    viewer, _, _, _, _ = open_styled_viewer(show_node_ids=False)
    rendering, width, _ = _render_snapshot(viewer._snapshot, theme)
    expected = Style(bgcolor="#102030").bgcolor
    assert rendering.style.bgcolor == expected
    assert style_at(rendering, width, 1, 1).bgcolor == expected


@pytest.mark.parametrize("nodes", [[], [1], list(range(1, 25))])
def test_background_covers_full_viewport_before_and_after_resize(nodes) -> None:
    viewer, _, graph_ui, _, _, _ = open_projected_viewer(nodes, [])
    color = Color.parse(viewer._theme["background-color"])

    async def exercise() -> None:
        app = _VisualizationApp(viewer._snapshot, viewer._poll_snapshot, viewer._theme)
        async with app.run_test(size=(40, 12)) as pilot:
            viewport = app.query_one("#graph-viewport", ScrollableContainer)
            for width, height in ((40, 12), (65, 20)):
                assert app.screen.size == (width, height)
                assert viewport.size == (width, height)
                assert app.screen.styles.background == color
                assert viewport.styles.background == color
                if (width, height) == (40, 12):
                    await pilot.resize_terminal(65, 20)
            if nodes:
                graph_ui.collapsed_node_ids.add(nodes[0])
                app._poll()
                assert viewport.styles.background == color

    asyncio.run(exercise())


@dataclass
class FakeGraph:
    nodes: list[int]
    edges: list[tuple[int, int]]

    def get_nodes(self) -> list[int]:
        return list(self.nodes)

    def get_edges(self) -> list[tuple[int, int]]:
        return list(self.edges)

    def get_node(self, node_id: int) -> int | None:
        return node_id if node_id in self.nodes else None


@dataclass
class FakeGraphUI:
    selected_node: int | None = None
    node_width: int = NODE_WIDTH
    node_height: int = 1
    show_node_ids: bool = True
    collapsed_node_ids: set[int] = field(default_factory=set)
    get_selected_node_calls: int = 0

    def get_selected_node(self) -> int | None:
        self.get_selected_node_calls += 1
        return self.selected_node

    def select_node(self, node_id: int) -> None:
        self.selected_node = node_id

    def get_node_width(self) -> int:
        return self.node_width

    def set_node_width(self, width: int) -> None:
        self.node_width = width

    def get_node_height(self) -> int:
        return self.node_height

    def set_node_height(self, height: int) -> None:
        self.node_height = height

    def get_show_node_ids(self) -> bool:
        return self.show_node_ids

    def set_show_node_ids(self, show: bool) -> None:
        self.show_node_ids = show

    def get_collapsed_node_ids(self) -> set[int]:
        return set(self.collapsed_node_ids)

    def set_node_collapsed(self, node_id: int, collapsed: bool) -> None:
        if collapsed:
            self.collapsed_node_ids.add(node_id)
        else:
            self.collapsed_node_ids.discard(node_id)


@dataclass
class FakeNodeAssignments:
    assignments: dict[int, object]
    error: Exception | None = None

    def get(self, node_id: int) -> object:
        if self.error is not None:
            raise self.error
        return self.assignments.get(
            node_id,
            NodeAssignment(type="void", param="", title=""),
        )


@dataclass
class FakeNodes:
    graph: FakeGraph
    assignments: FakeNodeAssignments

    def list_nodes(self) -> list[int]:
        return self.graph.get_nodes()

    def list_edges(self) -> list[tuple[int, int]]:
        return self.graph.get_edges()

    def node_exists(self, node_id: int) -> bool:
        return self.graph.get_node(node_id) is not None

    def get_all(self, node_id: int):
        value = self.assignments.get(node_id)
        if not isinstance(value, NodeAssignment):
            return value
        weight = str(value.weight) if type(value.weight) is int else value.weight
        return {
            "type": value.type, "title": value.title, "param": value.param,
            "status": value.status, "note": value.note, "tags": value.tags,
            "weight": weight,
        }


def measure_node_sizes(node_ids, assignments, resolver, *args, **kwargs):
    return measure_nodes_sizes(
        node_ids, FakeNodes(FakeGraph(list(node_ids), []), assignments),
        resolver, *args, **kwargs,
    )


def open_visualization(graph, graph_ui, assignments, resolver, layout, geometry):
    return open_nodes_visualization(
        FakeNodes(graph, assignments), graph_ui, resolver, layout, geometry
    )


class FakeNodeType:
    def __init__(
        self,
        display: Callable[[NodeContext], object],
        border_style: str = "solid",
    ) -> None:
        self._display = display
        self._border_style = border_style
        self.type = "fake"
        self.render_calls: list[NodeContext] = []
        self.execute_calls: list[NodeContext] = []

    def render(self, context: NodeContext) -> NodeRender:
        self.render_calls.append(context)
        title = self._display(context)
        return NodeRender(title=str(title), border_style=self._border_style)

    def execute(self, context: NodeContext) -> None:
        self.execute_calls.append(context)


class FakeNodeTypeResolver:
    def __init__(self, node_types: dict[str, object] | None = None) -> None:
        self.node_types = node_types or {
            "void": FakeNodeType(lambda _context: ""),
            "text": FakeNodeType(lambda context: context.properties["title"]),
            "file": FakeNodeType(lambda context: context.properties["title"]),
            "link": FakeNodeType(lambda context: context.properties["title"]),
            "agent": FakeNodeType(lambda context: context.properties["title"]),
            "copy": FakeNodeType(
                lambda context: context.properties["title"],
                "dashed",
            ),
        }
        self.calls: list[str] = []

    def __call__(self, name: str) -> object:
        self.calls.append(name)
        try:
            return self.node_types[name]
        except KeyError:
            raise ValueError(f"unsupported node type: {name!r}") from None


@dataclass(frozen=True)
class FakeLogicalLayout:
    layout: LogicalLayout


@dataclass(frozen=True)
class FakeGeometry:
    geometry: Geometry

    def get_rect(self, node_id: int) -> Rect:
        try:
            return self.geometry.nodes[node_id]
        except KeyError:
            raise KeyError(node_id) from None


def logical_layout(*columns: tuple[int, ...]) -> FakeLogicalLayout:
    if not columns:
        layout = LogicalLayout(components=())
    else:
        layout = LogicalLayout(
            components=(ComponentLayout(columns=tuple(columns)),)
        )
    return FakeLogicalLayout(layout)


def display_dependencies() -> tuple[
    FakeNodeAssignments,
    FakeNodeTypeResolver,
]:
    return FakeNodeAssignments({}), FakeNodeTypeResolver()


def geometry_for(
    *columns: tuple[int, ...],
    node_assignments: FakeNodeAssignments | None = None,
    node_type_resolver: FakeNodeTypeResolver | None = None,
    node_width: int = NODE_WIDTH,
    node_height: int = 1,
    show_node_ids: bool = True,
) -> FakeGeometry:
    if node_assignments is None or node_type_resolver is None:
        default_assignments, default_resolver = display_dependencies()
        node_assignments = node_assignments or default_assignments
        node_type_resolver = node_type_resolver or default_resolver
    node_ids = [node_id for column in columns for node_id in column]
    sizes = measure_node_sizes(
        node_ids,
        node_assignments,
        node_type_resolver,
        node_width,
        node_height,
        show_node_ids,
    )

    column_widths = [
        max((sizes[node].width for node in column), default=0)
        for column in columns
    ]
    row_count = max((len(column) for column in columns), default=0)
    row_heights = [
        max(
            sizes[column[position]].height
            for column in columns
            if position < len(column)
        )
        for position in range(row_count)
    ]

    column_x: list[int] = []
    x = 0
    for width in column_widths:
        column_x.append(x)
        x += width + 4

    row_y: list[int] = []
    y = 0
    for height in row_heights:
        row_y.append(y)
        y += height + 1

    rectangles = {
        node_id: Rect(
            x=column_x[column_index],
            y=row_y[position],
            width=sizes[node_id].width,
            height=sizes[node_id].height,
        )
        for column_index, column in enumerate(columns)
        for position, node_id in enumerate(column)
    }
    width = max((rect.x + rect.width for rect in rectangles.values()), default=0)
    height = max((rect.y + rect.height for rect in rectangles.values()), default=0)
    return FakeGeometry(Geometry(nodes=rectangles, width=width, height=height))


def geometry_with_rect(
    geometry: FakeGeometry,
    node_id: int,
    replacement: Rect,
) -> FakeGeometry:
    rectangles = dict(geometry.geometry.nodes)
    rectangles[node_id] = replacement
    width = max((rect.x + rect.width for rect in rectangles.values()), default=0)
    height = max((rect.y + rect.height for rect in rectangles.values()), default=0)
    return FakeGeometry(Geometry(nodes=rectangles, width=width, height=height))


def open_two_node_viewer(
    *,
    node_width: int = NODE_WIDTH,
    node_height: int = 1,
    show_node_ids: bool = True,
) -> tuple[
    object,
    FakeGraph,
    FakeGraphUI,
    FakeNodeAssignments,
    FakeNodeTypeResolver,
    FakeLogicalLayout,
    FakeGeometry,
]:
    graph = FakeGraph(nodes=[1, 2], edges=[(1, 2)])
    graph_ui = FakeGraphUI(
        selected_node=1,
        node_width=node_width,
        node_height=node_height,
        show_node_ids=show_node_ids,
    )
    node_assignments, node_type_resolver = display_dependencies()
    layout = logical_layout((1,), (2,))
    geometry = geometry_for(
        (1,),
        (2,),
        node_assignments=node_assignments,
        node_type_resolver=node_type_resolver,
        node_width=node_width,
        node_height=node_height,
        show_node_ids=show_node_ids,
    )
    viewer = open_visualization(
        graph,
        graph_ui,
        node_assignments,
        node_type_resolver,
        layout,
        geometry,
    )
    return (
        viewer,
        graph,
        graph_ui,
        node_assignments,
        node_type_resolver,
        layout,
        geometry,
    )


def open_single_node_viewer(
    display_text: str | None = None,
    node_width: int = NODE_WIDTH,
    node_height: int = 1,
    node_id: int = 1,
    selected: bool = False,
    show_node_ids: bool = True,
) -> tuple[
    object,
    FakeGraphUI,
    FakeNodeAssignments,
    FakeNodeTypeResolver,
    FakeGeometry,
]:
    graph = FakeGraph(nodes=[node_id], edges=[])
    graph_ui = FakeGraphUI(
        selected_node=node_id if selected else None,
        node_width=node_width,
        node_height=node_height,
        show_node_ids=show_node_ids,
    )
    assignments = (
        {}
        if display_text is None
        else {
            node_id: NodeAssignment(
                type="text",
                param="type-specific parameter",
                title=display_text,
            )
        }
    )
    node_assignments = FakeNodeAssignments(assignments)
    node_type_resolver = FakeNodeTypeResolver()
    layout = logical_layout((node_id,),)
    geometry = geometry_for(
        (node_id,),
        node_assignments=node_assignments,
        node_type_resolver=node_type_resolver,
        node_width=node_width,
        node_height=node_height,
        show_node_ids=show_node_ids,
    )
    viewer = open_visualization(
        graph,
        graph_ui,
        node_assignments,
        node_type_resolver,
        layout,
        geometry,
    )
    return viewer, graph_ui, node_assignments, node_type_resolver, geometry


def open_projected_viewer(
    nodes: list[int],
    edges: list[tuple[int, int]],
    *,
    collapsed_node_ids: set[int] | None = None,
    titles: dict[int, str] | None = None,
    selected_node: int | None = None,
    node_width: int = NODE_WIDTH,
    node_height: int = 1,
    show_node_ids: bool = True,
) -> tuple[
    object,
    FakeGraph,
    FakeGraphUI,
    FakeNodeAssignments,
    object,
    object,
]:
    graph = FakeGraph(nodes=list(nodes), edges=list(edges))
    graph_ui = FakeGraphUI(
        selected_node=selected_node,
        node_width=node_width,
        node_height=node_height,
        show_node_ids=show_node_ids,
        collapsed_node_ids=set(collapsed_node_ids or set()),
    )
    assignments = FakeNodeAssignments(
        {
            node_id: NodeAssignment("text", "", title)
            for node_id, title in (titles or {}).items()
        }
    )
    resolver = FakeNodeTypeResolver()
    visible = calculate_visible_graph(
        graph.get_nodes(),
        graph.get_edges(),
        graph_ui.get_collapsed_node_ids(),
    )
    layout = calculate_layout(list(visible.nodes), list(visible.edges))
    sizes = measure_node_sizes(
        list(visible.nodes),
        assignments,
        resolver,
        node_width,
        node_height,
        show_node_ids,
    )
    occupied_width = next(iter(sizes.values())).width if sizes else node_width
    geometry = calculate_geometry(
        layout.layout,
        sizes,
        node_width=occupied_width,
    )
    viewer = open_visualization(
        graph,
        graph_ui,
        assignments,
        resolver,
        layout,
        geometry,
    )
    return viewer, graph, graph_ui, assignments, layout, geometry


def open_styled_viewer(
    *,
    node_type_name: str = "copy",
    border_style: str = "dashed",
    collapsed: bool = False,
    selected: bool = False,
    show_node_ids: bool = True,
    status: str = "none",
) -> tuple[object, FakeGraphUI, FakeNodeAssignments, FakeNodeType, FakeGeometry]:
    graph = FakeGraph(nodes=[1, 2], edges=[(1, 2)])
    graph_ui = FakeGraphUI(
        selected_node=1 if selected else None,
        show_node_ids=show_node_ids,
        collapsed_node_ids={1} if collapsed else set(),
    )
    assignments = FakeNodeAssignments(
        {
            1: NodeAssignment(node_type_name, "2", "Copy title", status),
            2: NodeAssignment("text", "", "Target"),
        }
    )
    node_type = FakeNodeType(
        lambda _context: "render title must not replace assignment title",
        border_style,
    )
    resolver = FakeNodeTypeResolver(
        {
            node_type_name: node_type,
            "text": FakeNodeType(
                lambda context: context.properties["title"],
                "solid",
            ),
        }
    )
    visible = calculate_visible_graph(
        graph.get_nodes(),
        graph.get_edges(),
        graph_ui.get_collapsed_node_ids(),
    )
    nodes, edges = list(visible.nodes), list(visible.edges)
    layout = calculate_layout(nodes, edges)
    sizes = measure_node_sizes(
        nodes,
        assignments,
        resolver,
        graph_ui.node_width,
        graph_ui.node_height,
        show_node_ids,
    )
    occupied_width = next(iter(sizes.values())).width if sizes else NODE_WIDTH
    geometry = calculate_geometry(
        layout.layout,
        sizes,
        node_width=occupied_width,
    )
    viewer = open_visualization(
        graph,
        graph_ui,
        assignments,
        resolver,
        layout,
        geometry,
    )
    return viewer, graph_ui, assignments, node_type, geometry


def assert_public_viewer(viewer: object) -> None:
    assert callable(getattr(viewer, "run"))
    assert callable(getattr(viewer, "refresh"))


def rendered(viewer: object) -> tuple[Text, int, int]:
    return _render_snapshot(viewer._snapshot)


def rendered_plain(viewer: object) -> str:
    return rendered(viewer)[0].plain


def rendered_rows(viewer: object) -> list[str]:
    return rendered_plain(viewer).splitlines()


def interior_rows(viewer: object, node_id: int) -> list[str]:
    snapshot = viewer._snapshot
    rect = snapshot.rectangles[node_id]
    main_x = rect.x + rect.width - snapshot.node_width
    interior_width = snapshot.node_width - 2
    node_height = snapshot.node_height
    rows = rendered_rows(viewer)
    return [
        rows[y][main_x + 1 : main_x + 1 + interior_width]
        for y in range(rect.y + 1, rect.y + 1 + node_height)
    ]


def style_at(rendered_text: Text, width: int, x: int, y: int) -> object:
    offset = y * (width + 1) + x
    for span in reversed(rendered_text.spans):
        if span.start <= offset < span.end:
            return span.style
    return None


def viewer_with_rectangles(
    nodes: list[int],
    edges: list[tuple[int, int]],
    rectangles: dict[int, Rect],
    *,
    node_width: int = NODE_WIDTH,
    node_height: int = 1,
) -> object:
    node_assignments, node_type_resolver = display_dependencies()
    width = max((rect.x + rect.width for rect in rectangles.values()), default=0)
    height = max((rect.y + rect.height for rect in rectangles.values()), default=0)
    return open_visualization(
        FakeGraph(nodes=nodes, edges=edges),
        FakeGraphUI(node_width=node_width, node_height=node_height),
        node_assignments,
        node_type_resolver,
        logical_layout(*((node_id,) for node_id in nodes)),
        FakeGeometry(Geometry(rectangles, width, height)),
    )


def test_measure_node_sizes_has_exact_node_coverage() -> None:
    node_assignments, node_type_resolver = display_dependencies()

    sizes = measure_node_sizes(
        [7, 42, 1000],
        node_assignments,
        node_type_resolver,
    )

    assert set(sizes) == {7, 42, 1000}


@pytest.mark.parametrize("node_height", [1, 2, 5])
def test_measure_node_sizes_use_fixed_configured_height(node_height: int) -> None:
    node_assignments = FakeNodeAssignments(
        {
            2: NodeAssignment(type="text", param="short"),
            3: NodeAssignment(type="text", param="content that overflows"),
        }
    )
    node_type_resolver = FakeNodeTypeResolver()

    sizes = measure_node_sizes(
        [1, 2, 3],
        node_assignments,
        node_type_resolver,
        node_width=9,
        node_height=node_height,
    )

    assert set(sizes.values()) == {Size(width=9, height=node_height + 3)}


@pytest.mark.parametrize(
    ("node_width", "node_height"),
    [(3, 1), (12, 4), (50, 2)],
)
def test_measure_node_sizes_uses_configured_dimensions(
    node_width: int,
    node_height: int,
) -> None:
    node_assignments, node_type_resolver = display_dependencies()

    sizes = measure_node_sizes(
        [1, 2],
        node_assignments,
        node_type_resolver,
        node_width,
        node_height,
    )

    assert set(sizes.values()) == {
        Size(width=node_width, height=node_height + 3)
    }


def test_measure_node_sizes_uses_complete_widest_id_as_shared_width() -> None:
    widest_id = -1234567890123
    node_assignments, node_type_resolver = display_dependencies()

    sizes = measure_node_sizes(
        [1, widest_id],
        node_assignments,
        node_type_resolver,
    )

    expected_width = len(str(widest_id))
    assert expected_width > NODE_WIDTH
    assert set(sizes.values()) == {Size(expected_width, 4)}


def test_measure_node_sizes_without_ids_uses_only_main_rectangle() -> None:
    widest_id = -1234567890123
    node_assignments, resolver = display_dependencies()

    sizes = measure_node_sizes(
        [1, widest_id],
        node_assignments,
        resolver,
        node_width=8,
        node_height=4,
        show_node_ids=False,
    )

    assert set(sizes.values()) == {Size(width=8, height=6)}


@pytest.mark.parametrize("show_node_ids", [0, 1, None, "yes"])
def test_measure_node_sizes_rejects_non_boolean_id_visibility(
    show_node_ids: object,
) -> None:
    node_assignments, resolver = display_dependencies()

    with pytest.raises(ValueError):
        measure_node_sizes(
            [1], node_assignments, resolver, show_node_ids=show_node_ids
        )


def test_measure_node_sizes_is_deterministic() -> None:
    node_assignments, node_type_resolver = display_dependencies()

    assert measure_node_sizes(
        [5, 123, 9], node_assignments, node_type_resolver, 18, 3
    ) == measure_node_sizes(
        [5, 123, 9], node_assignments, node_type_resolver, 18, 3
    )


def test_measure_node_sizes_rejects_duplicate_ids() -> None:
    node_assignments, node_type_resolver = display_dependencies()

    with pytest.raises(ValueError):
        measure_node_sizes([1, 2, 1], node_assignments, node_type_resolver)


@pytest.mark.parametrize(
    ("node_width", "node_height"),
    [(2, 1), (3.5, 1), (True, 1), (12, 0), (12, 1.5), (12, True)],
)
def test_measure_node_sizes_rejects_invalid_dimensions(
    node_width: object,
    node_height: object,
) -> None:
    node_assignments, node_type_resolver = display_dependencies()

    with pytest.raises(ValueError):
        measure_node_sizes(
            [1],
            node_assignments,
            node_type_resolver,
            node_width,
            node_height,
        )


def test_measure_node_sizes_accepts_empty_input() -> None:
    node_assignments, node_type_resolver = display_dependencies()

    assert measure_node_sizes(
        [], node_assignments, node_type_resolver, 3, 7
    ) == {}


def test_measure_node_sizes_does_not_call_node_type_resolver() -> None:
    node_assignments = FakeNodeAssignments(
        {1: NodeAssignment(type="custom", param="parameter", title="shown")}
    )
    node_type = FakeNodeType(lambda context: context.properties["param"].upper())
    node_type_resolver = FakeNodeTypeResolver({"custom": node_type})

    sizes = measure_node_sizes([1], node_assignments, node_type_resolver, 12, 3)

    assert sizes == {1: Size(12, 6)}
    assert node_type_resolver.calls == []
    assert node_type.render_calls == []
    assert node_type.execute_calls == []


@pytest.mark.parametrize(
    ("node_assignments", "node_type_resolver"),
    [
        (FakeNodeAssignments({1: object()}), FakeNodeTypeResolver()),
        (
            FakeNodeAssignments(
                {1: NodeAssignment(type="text", param="value", title=object())}
            ),
            FakeNodeTypeResolver(),
        ),
        (
            FakeNodeAssignments(
                {
                    1: NodeAssignment(
                        type="text", param="value", note=object()
                    )
                }
            ),
            FakeNodeTypeResolver(),
        ),
        (
            FakeNodeAssignments(
                {
                    1: NodeAssignment(
                        type="text", param="value", tags=object()
                    )
                }
            ),
            FakeNodeTypeResolver(),
        ),
        (
            FakeNodeAssignments(
                {1: NodeAssignment(type="text", param="value", weight=True)}
            ),
            FakeNodeTypeResolver(),
        ),
    ],
    ids=["assignment", "title", "note", "tags", "weight"],
)
def test_measure_node_sizes_rejects_invalid_assignments(
    node_assignments: FakeNodeAssignments,
    node_type_resolver: FakeNodeTypeResolver,
) -> None:
    with pytest.raises(ValueError):
        measure_node_sizes([1], node_assignments, node_type_resolver)


def test_measure_node_sizes_propagates_assignment_lookup_errors() -> None:
    node_assignments = FakeNodeAssignments({}, error=LookupError("unavailable"))

    with pytest.raises(LookupError, match="unavailable"):
        measure_node_sizes([1], node_assignments, FakeNodeTypeResolver())


def test_open_visualization_accepts_valid_graph_layout_and_geometry() -> None:
    viewer, _, _, _, _, _, _ = open_two_node_viewer(node_height=3)

    assert_public_viewer(viewer)


def test_open_visualization_accepts_empty_graph() -> None:
    graph = FakeGraph(nodes=[], edges=[])
    graph_ui = FakeGraphUI(node_width=20, node_height=4)
    node_assignments, node_type_resolver = display_dependencies()

    viewer = open_visualization(
        graph,
        graph_ui,
        node_assignments,
        node_type_resolver,
        logical_layout(),
        geometry_for(
            node_assignments=node_assignments,
            node_type_resolver=node_type_resolver,
            node_width=20,
            node_height=4,
        ),
    )

    assert_public_viewer(viewer)


@pytest.mark.parametrize(
    "bad_layout",
    [logical_layout((1,),), logical_layout((1,), (2,), (3,))],
    ids=["missing-node", "extra-node"],
)
def test_open_visualization_rejects_inexact_layout_node_coverage(
    bad_layout: FakeLogicalLayout,
) -> None:
    graph = FakeGraph(nodes=[1, 2], edges=[(1, 2)])
    node_assignments, node_type_resolver = display_dependencies()

    with pytest.raises(ValueError):
        open_visualization(
            graph,
            FakeGraphUI(),
            node_assignments,
            node_type_resolver,
            bad_layout,
            geometry_for(
                (1,),
                (2,),
                node_assignments=node_assignments,
                node_type_resolver=node_type_resolver,
            ),
        )


@pytest.mark.parametrize(
    "bad_geometry_columns",
    [((1,),), ((1,), (2,), (3,))],
    ids=["missing-node", "extra-node"],
)
def test_open_visualization_rejects_inexact_geometry_node_coverage(
    bad_geometry_columns: tuple[tuple[int, ...], ...],
) -> None:
    graph = FakeGraph(nodes=[1, 2], edges=[(1, 2)])
    node_assignments, node_type_resolver = display_dependencies()

    with pytest.raises(ValueError):
        open_visualization(
            graph,
            FakeGraphUI(),
            node_assignments,
            node_type_resolver,
            logical_layout((1,), (2,)),
            geometry_for(
                *bad_geometry_columns,
                node_assignments=node_assignments,
                node_type_resolver=node_type_resolver,
            ),
        )


@pytest.mark.parametrize("dimension", ["width", "height"])
def test_open_visualization_rejects_incorrect_rectangle_dimensions(
    dimension: str,
) -> None:
    graph = FakeGraph(nodes=[1], edges=[])
    graph_ui = FakeGraphUI(node_height=3)
    node_assignments, node_type_resolver = display_dependencies()
    correct_geometry = geometry_for(
        (1,),
        node_assignments=node_assignments,
        node_type_resolver=node_type_resolver,
        node_height=3,
    )
    correct_rect = correct_geometry.get_rect(1)
    wrong_rect = Rect(
        x=correct_rect.x,
        y=correct_rect.y,
        width=correct_rect.width + (dimension == "width"),
        height=correct_rect.height + (dimension == "height"),
    )

    with pytest.raises(ValueError):
        open_visualization(
            graph,
            graph_ui,
            node_assignments,
            node_type_resolver,
            logical_layout((1,),),
            geometry_with_rect(correct_geometry, 1, wrong_rect),
        )


def test_open_visualization_rejects_main_rectangle_without_id_row() -> None:
    graph = FakeGraph(nodes=[1], edges=[])
    node_assignments, node_type_resolver = display_dependencies()
    main_only = FakeGeometry(
        Geometry(
            nodes={1: Rect(0, 0, NODE_WIDTH, 3)},
            width=NODE_WIDTH,
            height=3,
        )
    )

    with pytest.raises(ValueError):
        open_visualization(
            graph,
            FakeGraphUI(),
            node_assignments,
            node_type_resolver,
            logical_layout((1,),),
            main_only,
        )


def test_open_visualization_accepts_selection_for_nonexistent_node() -> None:
    graph_ui = FakeGraphUI(selected_node=999, node_height=2)
    node_assignments, node_type_resolver = display_dependencies()

    viewer = open_visualization(
        FakeGraph(nodes=[1], edges=[]),
        graph_ui,
        node_assignments,
        node_type_resolver,
        logical_layout((1,),),
        geometry_for(
            (1,),
            node_assignments=node_assignments,
            node_type_resolver=node_type_resolver,
            node_height=2,
        ),
    )

    assert_public_viewer(viewer)
    assert graph_ui.get_selected_node_calls > 0


@pytest.mark.parametrize(
    ("node_assignments", "node_type_resolver"),
    [
        (FakeNodeAssignments({1: object()}), FakeNodeTypeResolver()),
        (
            FakeNodeAssignments(
                {1: NodeAssignment(type="text", param="value", title=object())}
            ),
            FakeNodeTypeResolver(),
        ),
    ],
    ids=["assignment", "title"],
)
def test_open_visualization_rejects_invalid_assignments(
    node_assignments: FakeNodeAssignments,
    node_type_resolver: FakeNodeTypeResolver,
) -> None:
    with pytest.raises(ValueError):
        open_visualization(
            FakeGraph(nodes=[1], edges=[]),
            FakeGraphUI(),
            node_assignments,
            node_type_resolver,
            logical_layout((1,),),
            FakeGeometry(
                Geometry(
                    nodes={1: Rect(0, 0, NODE_WIDTH, 4)},
                    width=NODE_WIDTH,
                    height=4,
                )
            ),
        )


def test_every_node_has_exact_configured_main_and_occupied_height() -> None:
    viewer, _, _, _, geometry = open_single_node_viewer(
        "short", node_width=10, node_height=4
    )

    rect = geometry.get_rect(1)
    rows = rendered_rows(viewer)

    assert rect == Rect(0, 0, 10, 7)
    assert len(interior_rows(viewer, 1)) == 4
    assert rows[0][0:10] == "■────────┐"
    assert rows[5][0:10] == "└────────┘"
    assert rows[6][9] == "1"


def test_all_nodes_render_same_dimensions_regardless_of_content() -> None:
    graph = FakeGraph(nodes=[1, 2, 3], edges=[])
    graph_ui = FakeGraphUI(node_width=9, node_height=2)
    assignments = FakeNodeAssignments(
        {
            2: NodeAssignment(type="text", param="ignored", title="short"),
            3: NodeAssignment(
                type="text",
                param="also ignored",
                title="far too much content to fit",
            ),
        }
    )
    resolver = FakeNodeTypeResolver()
    layout = logical_layout((1, 2, 3),)
    geometry = geometry_for(
        (1, 2, 3),
        node_assignments=assignments,
        node_type_resolver=resolver,
        node_width=9,
        node_height=2,
    )

    viewer = open_visualization(
        graph, graph_ui, assignments, resolver, layout, geometry
    )

    assert {rect.width for rect in viewer._snapshot.rectangles.values()} == {9}
    assert {rect.height for rect in viewer._snapshot.rectangles.values()} == {5}
    assert all(len(interior_rows(viewer, node_id)) == 2 for node_id in graph.nodes)


def test_normal_node_uses_solid_border_from_node_type_render() -> None:
    viewer, _, _, node_type, _ = open_styled_viewer(
        node_type_name="normal",
        border_style="solid",
        show_node_ids=False,
    )

    assert rendered_rows(viewer)[0][:12] == "■──────────┐"
    assert rendered_rows(viewer)[1][:12] == "│Copy title│"
    assert rendered_rows(viewer)[2][:12] == "└──────────┘"
    assert len(node_type.render_calls) == 1
    assert node_type.render_calls[0].node_id == 1
    assert node_type.render_calls[0].properties["type"] == "normal"


@pytest.mark.parametrize("show_node_ids", [False, True])
def test_expanded_copy_node_uses_dashed_border_with_ids_in_either_mode(
    show_node_ids: bool,
) -> None:
    viewer, _, _, _, geometry = open_styled_viewer(
        show_node_ids=show_node_ids,
    )

    rows = rendered_rows(viewer)

    assert rows[0][:12] == "■╌╌╌╌╌╌╌╌╌╌┐"
    assert rows[1][:12] == "╎Copy title╎"
    assert rows[2][:12] == "└╌╌╌╌╌╌╌╌╌╌┘"
    assert geometry.get_rect(1).width == 12
    assert geometry.get_rect(1).height == (4 if show_node_ids else 3)
    if show_node_ids:
        assert rows[3][:12].strip() == "1"
    else:
        assert len(rows) == 3


def test_dashed_style_is_consumed_without_checking_node_type_name() -> None:
    viewer, _, _, _, _ = open_styled_viewer(
        node_type_name="custom-dashed",
        border_style="dashed",
        show_node_ids=False,
    )

    assert rendered_rows(viewer)[0][:12] == "■╌╌╌╌╌╌╌╌╌╌┐"


def test_selected_copy_node_preserves_dashed_border_and_selection_style() -> None:
    selected, _, _, _, _ = open_styled_viewer(
        selected=True,
        show_node_ids=False,
    )
    unselected, _, _, _, _ = open_styled_viewer(show_node_ids=False)
    selected_rendering, width, _ = rendered(selected)
    unselected_rendering, _, _ = rendered(unselected)

    assert selected_rendering.plain == unselected_rendering.plain
    assert selected_rendering.plain.splitlines()[0][:12] == "■╌╌╌╌╌╌╌╌╌╌┐"
    for x, y in ((0, 0), (5, 0), (0, 1), (11, 2)):
        assert style_at(selected_rendering, width, x, y) != style_at(
            unselected_rendering, width, x, y
        )


@pytest.mark.parametrize(
    ("status", "color"),
    [
        ("none", "bright_black"),
        ("progress", "blue"),
        ("success", "green"),
        ("warning", "yellow"),
        ("failure", "red"),
    ],
)
@pytest.mark.parametrize("border_style", ["solid", "dashed"])
def test_status_replaces_top_left_junction_with_colored_square(
    status: str,
    color: str,
    border_style: str,
) -> None:
    viewer, _, _, _, _ = open_styled_viewer(
        node_type_name=f"custom-{border_style}",
        border_style=border_style,
        status=status,
        show_node_ids=False,
    )

    rendering, width, _ = rendered(viewer)

    assert rendering.plain[0] == "■"
    assert style_at(rendering, width, 0, 0).color == Style(color=viewer._theme[f"status-icon-color-{status}"]).color


def test_assignment_tags_are_not_rendered_or_used_for_geometry() -> None:
    without_tags, _, _, _, _, without_geometry = open_projected_viewer(
        [1],
        [],
        titles={1: "Title"},
    )
    with_tags, _, _, assignments, _, with_geometry = open_projected_viewer(
        [1],
        [],
        titles={1: "Title"},
    )
    original = assignments.assignments[1]
    assignments.assignments[1] = NodeAssignment(
        original.type,
        original.param,
        original.title,
        original.status,
        original.note,
        "python, development, agent 😀",
    )
    with_tags.refresh()

    assert rendered(with_tags) == rendered(without_tags)
    assert with_geometry.get_rect(1) == without_geometry.get_rect(1)


@pytest.mark.parametrize(
    ("properties", "theme_key", "selected_key"),
    [
        ({"color": "green"}, "node-color-green", "node-color-green-selected"),
        ({}, "border-color-normal", "border-color-selected"),
        ({"color": "green-selected"}, "border-color-normal", "border-color-selected"),
    ],
)
def test_node_border_uses_saved_color_for_each_selection_state(
    properties, theme_key, selected_key
) -> None:
    viewer, graph_ui, assignments, _, _ = open_styled_viewer(show_node_ids=False)
    assignments.assignments[1] = {"type": "copy", "title": "Copy title", **properties}
    viewer.refresh()
    text, width, _ = rendered(viewer)
    assert style_at(text, width, 1, 0) == Style(
        color=viewer._theme[theme_key],
        bgcolor=viewer._theme["background-color"],
        bold=False,
    )
    assert style_at(text, width, 1, 1).bgcolor == Style(
        bgcolor=viewer._theme["background-color"]
    ).bgcolor

    graph_ui.selected_node = 1
    viewer.refresh()
    text, width, _ = rendered(viewer)
    assert style_at(text, width, 1, 0) == Style(
        color=viewer._theme[selected_key],
        bgcolor=viewer._theme["selection-color"],
        bold=True,
    )


def test_selection_applies_background_and_preserves_status_foreground() -> None:
    viewer, graph_ui, assignments, _, _ = open_styled_viewer(
        status="failure",
        show_node_ids=False,
    )
    unselected_rendering, width, _ = rendered(viewer)

    graph_ui.selected_node = 1
    viewer.refresh()
    selected_rendering, _, _ = rendered(viewer)

    unselected_indicator = style_at(unselected_rendering, width, 0, 0)
    selected_indicator = style_at(selected_rendering, width, 0, 0)
    assert unselected_indicator.color == Style(color=viewer._theme["status-icon-color-failure"]).color
    assert selected_indicator == Style(
        color=viewer._theme["status-icon-color-failure"], bgcolor=viewer._theme["selection-color"], bold=True
    )
    assert selected_indicator.color == unselected_indicator.color
    assert assignments.assignments[1].status == "failure"

    graph_ui.selected_node = None
    viewer.refresh()
    deselected_rendering, _, _ = rendered(viewer)

    assert style_at(deselected_rendering, width, 0, 0) == unselected_indicator
    assert assignments.assignments[1].status == "failure"


def test_unsupported_node_border_style_is_rejected() -> None:
    with pytest.raises(ValueError, match="border style"):
        open_styled_viewer(border_style="double")


def test_collapsed_node_renders_exact_internal_indicator_structure() -> None:
    viewer, _, _, _, _, geometry = open_projected_viewer(
        [1, 2],
        [(1, 2)],
        collapsed_node_ids={1},
        titles={1: "title"},
    )

    rows = rendered_rows(viewer)

    assert geometry.get_rect(1) == Rect(0, 0, 12, 4)
    assert rows[0][:12] == "■───────┬──┐"
    assert rows[1][:12] == "│title  │+ │"
    assert rows[2][:12] == "└───────┴──┘"
    assert rows[3][:12] == "           1"


@pytest.mark.parametrize("show_node_ids", [False, True])
def test_collapsed_copy_node_uses_dashed_border_around_internal_indicator(
    show_node_ids: bool,
) -> None:
    viewer, _, _, _, geometry = open_styled_viewer(
        collapsed=True,
        selected=True,
        show_node_ids=show_node_ids,
    )

    rows = rendered_rows(viewer)

    assert rows[0][:12] == "■╌╌╌╌╌╌╌┬╌╌┐"
    assert rows[1][:12] == "╎Copy…  ╎+ ╎"
    assert rows[2][:12] == "└╌╌╌╌╌╌╌┴╌╌┘"
    assert geometry.get_rect(1).width == 12
    assert geometry.get_rect(1).height == (4 if show_node_ids else 3)
    if show_node_ids:
        assert rows[3].strip() == "1"
    else:
        assert len(rows) == 3


def test_expanded_and_collapsed_nodes_have_identical_external_dimensions() -> None:
    expanded, _, _, _, _, _ = open_projected_viewer(
        [1, 2], [(1, 2)], titles={1: "title"}
    )
    collapsed, _, _, _, _, _ = open_projected_viewer(
        [1, 2], [(1, 2)], collapsed_node_ids={1}, titles={1: "title"}
    )

    assert expanded._snapshot.rectangles[1].width == 12
    assert collapsed._snapshot.rectangles[1].width == 12
    assert expanded._snapshot.rectangles[1].height == 4
    assert collapsed._snapshot.rectangles[1].height == 4
    assert rendered_rows(expanded)[0][:12] == "■──────────┐"


def test_collapsed_title_wraps_in_reduced_title_area() -> None:
    viewer, _, _, _, _, _ = open_projected_viewer(
        [1, 2],
        [(1, 2)],
        collapsed_node_ids={1},
        titles={1: "abcdefgh"},
        node_width=12,
    )

    assert rendered_rows(viewer)[1][:12] == "│abcdef…│+ │"


def test_collapsed_indicator_rejects_width_below_six_without_expansion() -> None:
    with pytest.raises(ValueError):
        open_projected_viewer(
            [1, 2],
            [(1, 2)],
            collapsed_node_ids={1},
            node_width=5,
        )


def test_collapsed_leaf_uses_ordinary_node_rendering() -> None:
    viewer, _, _, _, _, _ = open_projected_viewer(
        [1], [], collapsed_node_ids={1}, titles={1: "leaf"}, node_width=8
    )

    assert rendered_rows(viewer)[0][:8] == "■──────┐"
    assert "+" not in rendered_plain(viewer)


def test_collapsed_indicator_with_hidden_ids_uses_main_dimensions_only() -> None:
    viewer, _, _, _, _, geometry = open_projected_viewer(
        [1234567890123, 2],
        [(1234567890123, 2)],
        collapsed_node_ids={1234567890123},
        node_width=8,
        show_node_ids=False,
    )

    assert geometry.get_rect(1234567890123) == Rect(0, 0, 8, 3)
    assert rendered_rows(viewer)[0][:8] == "■───┬──┐"
    assert rendered_rows(viewer)[1][:8] == "│   │+ │"
    assert str(1234567890123) not in rendered_plain(viewer)


def test_selection_styles_entire_collapsed_rectangle_and_id() -> None:
    selected, _, _, _, _, _ = open_projected_viewer(
        [1, 2], [(1, 2)], collapsed_node_ids={1}, selected_node=1
    )
    unselected, _, _, _, _, _ = open_projected_viewer(
        [1, 2], [(1, 2)], collapsed_node_ids={1}
    )
    selected_rendering, width, _ = rendered(selected)
    unselected_rendering, _, _ = rendered(unselected)

    assert selected_rendering.plain == unselected_rendering.plain
    for x, y in ((8, 0), (9, 1), (11, 2), (11, 3)):
        assert style_at(selected_rendering, width, x, y) != style_at(
            unselected_rendering, width, x, y
        )


def test_selection_styles_entire_collapsed_rectangle_with_ids_hidden() -> None:
    selected, _, _, _, _, _ = open_projected_viewer(
        [1, 2],
        [(1, 2)],
        collapsed_node_ids={1},
        selected_node=1,
        show_node_ids=False,
    )
    unselected, _, _, _, _, _ = open_projected_viewer(
        [1, 2],
        [(1, 2)],
        collapsed_node_ids={1},
        show_node_ids=False,
    )
    selected_rendering, width, _ = rendered(selected)
    unselected_rendering, _, _ = rendered(unselected)

    assert selected_rendering.plain == unselected_rendering.plain
    for x, y in ((8, 0), (9, 1), (11, 2)):
        assert style_at(selected_rendering, width, x, y) != style_at(
            unselected_rendering, width, x, y
        )


def test_node_id_is_plain_external_right_aligned_and_untruncated() -> None:
    node_id = -1234567890123
    viewer, _, _, _, geometry = open_single_node_viewer(
        "body", node_width=8, node_height=2, node_id=node_id
    )

    rect = geometry.get_rect(node_id)
    rows = rendered_rows(viewer)
    main_x = rect.x + rect.width - 8
    id_x = rect.x + rect.width - len(str(node_id))
    id_y = rect.y + 4

    assert rect == Rect(0, 0, len(str(node_id)), 5)
    assert rows[0][main_x] == "■"
    assert rows[3][main_x] == "└"
    assert rows[id_y][id_x : rect.x + rect.width] == str(node_id)
    assert rows[id_y].strip() == str(node_id)
    assert not any(character in rows[id_y] for character in "■┌┐└┘│─")
    assert str(node_id) not in "\n".join(rows[:id_y])


def test_plain_id_has_no_border_or_background_rectangle() -> None:
    viewer, _, _, _, _ = open_single_node_viewer(node_id=42)
    rendering, width, _ = rendered(viewer)
    rows = rendering.plain.splitlines()
    id_x = NODE_WIDTH - len("42")
    id_y = 3

    assert rows[id_y][:id_x] == " " * id_x
    assert rows[id_y][id_x:NODE_WIDTH] == "42"
    assert style_at(rendering, width, id_x - 1, id_y) is None
    assert not any(character in rows[id_y] for character in "■┌┐└┘│─")


def test_selection_highlights_main_rectangle_and_plain_id() -> None:
    selected, _, _, _, _ = open_single_node_viewer(
        node_id=42, node_height=2, selected=True
    )
    unselected, _, _, _, _ = open_single_node_viewer(node_id=42, node_height=2)
    selected_rendering, width, _ = rendered(selected)
    unselected_rendering, unselected_width, _ = rendered(unselected)
    id_x = NODE_WIDTH - len("42")
    id_y = 4

    assert width == unselected_width
    assert selected_rendering.plain == unselected_rendering.plain
    assert selected_rendering.plain.splitlines()[id_y][id_x:NODE_WIDTH] == "42"
    selected_indicator = style_at(selected_rendering, width, 0, 0)
    unselected_indicator = style_at(unselected_rendering, width, 0, 0)
    assert selected_indicator != unselected_indicator
    assert selected_indicator.color == unselected_indicator.color
    assert selected_indicator.bgcolor == Style(bgcolor=selected._theme["selection-color"]).bgcolor
    assert style_at(selected_rendering, width, 1, 0) != style_at(
        unselected_rendering, width, 1, 0
    )
    assert style_at(selected_rendering, width, id_x, id_y) != style_at(
        unselected_rendering, width, id_x, id_y
    )


def test_hidden_ids_are_not_rendered_and_selection_highlights_only_main() -> None:
    node_id = 1234567890123
    selected, _, _, _, geometry = open_single_node_viewer(
        "body",
        node_width=8,
        node_height=2,
        node_id=node_id,
        selected=True,
        show_node_ids=False,
    )
    unselected, _, _, _, _ = open_single_node_viewer(
        "body",
        node_width=8,
        node_height=2,
        node_id=node_id,
        show_node_ids=False,
    )
    selected_rendering, width, height = rendered(selected)
    unselected_rendering, _, _ = rendered(unselected)

    assert geometry.get_rect(node_id) == Rect(0, 0, 8, 4)
    assert (width, height) == (8, 4)
    assert str(node_id) not in selected_rendering.plain
    assert selected_rendering.plain == unselected_rendering.plain
    selected_indicator = style_at(selected_rendering, width, 0, 0)
    unselected_indicator = style_at(unselected_rendering, width, 0, 0)
    assert selected_indicator != unselected_indicator
    assert selected_indicator.color == unselected_indicator.color
    assert selected_indicator.bgcolor == Style(bgcolor=selected._theme["selection-color"]).bgcolor
    assert style_at(selected_rendering, width, 1, 0) != style_at(
        unselected_rendering, width, 1, 0
    )


@pytest.mark.parametrize(
    ("display_text", "node_width", "node_height", "expected"),
    [
        ("alpha beta gamma", 8, 3, ["alpha ", "beta  ", "gamma "]),
        ("abcdefgh", 6, 2, ["abcd", "efgh"]),
        ("abcdefghij", 6, 2, ["abcd", "efg…"]),
        ("abcdefgh", 6, 3, ["abcd", "efgh", "    "]),
        ("", 7, 3, ["     ", "     ", "     "]),
        ("a", 3, 1, ["a"]),
        ("abc", 3, 2, ["a", "…"]),
    ],
    ids=[
        "word-boundaries",
        "long-word-exact-fit",
        "overflow-ellipsis",
        "unused-row",
        "empty",
        "one-cell-exact-fit",
        "one-cell-truncation",
    ],
)
def test_display_text_wraps_into_exact_interior_rows(
    display_text: str,
    node_width: int,
    node_height: int,
    expected: list[str],
) -> None:
    viewer, _, _, _, _ = open_single_node_viewer(
        display_text,
        node_width=node_width,
        node_height=node_height,
    )

    assert interior_rows(viewer, 1) == expected


def test_line_break_sequences_become_spaces_before_wrapping() -> None:
    viewer, _, _, _, _ = open_single_node_viewer(
        "ab\r\ncd\ref\ngh", node_width=16, node_height=2
    )

    assert interior_rows(viewer, 1) == ["ab cd ef gh   ", "              "]


def test_rich_markup_is_rendered_literally() -> None:
    markup = "[bold]x[/bold]"
    viewer, _, _, _, _ = open_single_node_viewer(
        markup, node_width=20, node_height=1
    )

    assert interior_rows(viewer, 1) == [markup.ljust(18)]


@pytest.mark.parametrize(
    "node_type_name",
    ["void", "text", "file", "link", "agent", "copy"],
)
def test_assignment_title_is_wrapped_for_every_type(
    node_type_name: str,
) -> None:
    graph = FakeGraph(nodes=[1], edges=[])
    graph_ui = FakeGraphUI(node_height=2)
    assignments = FakeNodeAssignments(
        {
            1: NodeAssignment(
                type=node_type_name,
                param="must not be displayed",
                title="Universal title",
            )
        }
    )
    node_type = FakeNodeType(lambda _context: "type-rendered title")
    resolver = FakeNodeTypeResolver({node_type_name: node_type})
    geometry = geometry_for(
        (1,),
        node_assignments=assignments,
        node_type_resolver=resolver,
        node_height=2,
    )

    viewer = open_visualization(
        graph,
        graph_ui,
        assignments,
        resolver,
        logical_layout((1,),),
        geometry,
    )
    viewer.refresh()

    assert interior_rows(viewer, 1) == ["Universal ", "title     "]
    assert "type-rendered" not in rendered_plain(viewer)
    assert "must not" not in rendered_plain(viewer)
    assert resolver.calls == [node_type_name, node_type_name]
    assert len(node_type.render_calls) == 2
    assert all(
        context.properties["type"] == node_type_name
        for context in node_type.render_calls
    )
    assert node_type.execute_calls == []


def test_empty_assignment_title_uses_node_render_title() -> None:
    graph = FakeGraph(nodes=[1], edges=[])
    graph_ui = FakeGraphUI(show_node_ids=False)
    assignments = FakeNodeAssignments(
        {1: NodeAssignment(type="copy", param="2", title="")}
    )
    node_type = FakeNodeType(lambda _context: "Inherited title", "dashed")
    resolver = FakeNodeTypeResolver({"copy": node_type})
    geometry = geometry_for(
        (1,),
        node_assignments=assignments,
        node_type_resolver=resolver,
        show_node_ids=False,
    )

    viewer = open_visualization(
        graph,
        graph_ui,
        assignments,
        resolver,
        logical_layout((1,),),
        geometry,
    )

    assert interior_rows(viewer, 1) == ["Inherited…"]
    assert rendered_rows(viewer)[0][:12] == "■╌╌╌╌╌╌╌╌╌╌┐"


def test_visible_projection_recursively_hides_descendants_and_edges() -> None:
    viewer, _, _, _, _, _ = open_projected_viewer(
        [1, 2, 3, 4],
        [(1, 2), (2, 3), (3, 4)],
        collapsed_node_ids={2},
    )

    assert viewer._snapshot.nodes == (1, 2)
    assert viewer._snapshot.edges == ((1, 2),)
    assert set(viewer._snapshot.rectangles) == {1, 2}
    assert "3" not in rendered_plain(viewer)
    assert "4" not in rendered_plain(viewer)


def test_shared_descendant_remains_visible_through_alternate_path() -> None:
    viewer, _, _, _, _, _ = open_projected_viewer(
        [1, 2, 3, 4, 5],
        [(1, 2), (1, 3), (2, 4), (3, 4), (4, 5)],
        collapsed_node_ids={2},
    )

    assert viewer._snapshot.nodes == (1, 2, 3, 4, 5)
    assert viewer._snapshot.edges == ((1, 2), (1, 3), (3, 4), (4, 5))
    assert set(viewer._snapshot.rectangles) == {1, 2, 3, 4, 5}


def test_hidden_node_assignments_are_not_read_or_rendered() -> None:
    viewer, _, _, assignments, _, _ = open_projected_viewer(
        [1, 2, 3],
        [(1, 2), (2, 3)],
        collapsed_node_ids={1},
        titles={1: "visible"},
    )
    assignments.assignments[3] = object()

    viewer.refresh()

    assert viewer._snapshot.nodes == (1,)
    assert "visible" in rendered_plain(viewer)


def test_refresh_without_arguments_rereads_selection() -> None:
    viewer, _, graph_ui, _, _, _, _ = open_two_node_viewer()
    calls_before_refresh = graph_ui.get_selected_node_calls
    graph_ui.selected_node = 2

    viewer.refresh()

    assert graph_ui.get_selected_node_calls > calls_before_refresh
    assert viewer._snapshot.selected_node == 2


def test_refresh_accepts_new_layout_and_geometry_after_topology_change() -> None:
    graph = FakeGraph(nodes=[1], edges=[])
    graph_ui = FakeGraphUI(selected_node=1, node_height=2)
    node_assignments, node_type_resolver = display_dependencies()
    viewer = open_visualization(
        graph,
        graph_ui,
        node_assignments,
        node_type_resolver,
        logical_layout((1,),),
        geometry_for(
            (1,),
            node_assignments=node_assignments,
            node_type_resolver=node_type_resolver,
            node_height=2,
        ),
    )
    graph.nodes = [1, 2]
    graph.edges = [(1, 2)]
    graph_ui.selected_node = 2

    viewer.refresh(
        logical_layout((1,), (2,)),
        geometry_for(
            (1,),
            (2,),
            node_assignments=node_assignments,
            node_type_resolver=node_type_resolver,
            node_height=2,
        ),
    )

    assert viewer._snapshot.nodes == (1, 2)
    assert viewer._snapshot.edges == ((1, 2),)
    assert viewer._snapshot.selected_node == 2
    viewer.refresh()


def test_refresh_rejects_supplying_only_one_placement_dependency() -> None:
    viewer, _, _, _, _, layout, geometry = open_two_node_viewer()

    with pytest.raises(ValueError):
        viewer.refresh(logical_layout=layout)
    with pytest.raises(ValueError):
        viewer.refresh(geometry=geometry)


def test_refresh_without_placement_rejects_graph_topology_change() -> None:
    viewer, graph, _, _, _, _, _ = open_two_node_viewer()
    graph.edges = []

    with pytest.raises(ValueError):
        viewer.refresh()


def test_changing_node_height_updates_geometry_and_rendering() -> None:
    viewer, graph_ui, _, _, _ = open_single_node_viewer(
        "one two three four", node_width=8, node_height=1
    )
    assert viewer._snapshot.rectangles[1] == Rect(0, 0, 8, 4)

    graph_ui.node_height = 3
    viewer.refresh()

    assert viewer._snapshot.rectangles[1] == Rect(0, 0, 8, 6)
    assert interior_rows(viewer, 1) == ["one   ", "two   ", "three…"]
    assert rendered_rows(viewer)[4][0:8] == "└──────┘"
    assert rendered_rows(viewer)[5][7] == "1"


def test_changing_node_width_rewraps_text_and_updates_geometry() -> None:
    viewer, graph_ui, _, _, _ = open_single_node_viewer(
        "alpha beta", node_width=12, node_height=2
    )
    assert interior_rows(viewer, 1) == ["alpha beta", "          "]

    graph_ui.node_width = 7
    viewer.refresh()

    assert viewer._snapshot.rectangles[1] == Rect(0, 0, 7, 5)
    assert interior_rows(viewer, 1) == ["alpha", "beta "]


def test_toggling_id_visibility_recalculates_geometry_both_directions() -> None:
    node_id = 1234567890123
    viewer, graph_ui, _, _, _ = open_single_node_viewer(
        "body", node_width=8, node_height=2, node_id=node_id, selected=True
    )
    assert viewer._snapshot.rectangles[node_id] == Rect(0, 0, 13, 5)

    graph_ui.show_node_ids = False
    viewer.refresh()

    assert viewer._snapshot.rectangles[node_id] == Rect(0, 0, 8, 4)
    assert str(node_id) not in rendered_plain(viewer)

    graph_ui.show_node_ids = True
    viewer.refresh()

    assert viewer._snapshot.rectangles[node_id] == Rect(0, 0, 13, 5)
    assert rendered_rows(viewer)[4].strip() == str(node_id)


def test_assignment_type_change_updates_border_without_changing_geometry() -> None:
    graph = FakeGraph(nodes=[1], edges=[])
    graph_ui = FakeGraphUI(show_node_ids=False)
    assignments = FakeNodeAssignments(
        {1: NodeAssignment("normal", "", "Live title")}
    )
    normal_type = FakeNodeType(
        lambda context: context.properties["title"],
        "solid",
    )
    copy_type = FakeNodeType(
        lambda context: context.properties["title"],
        "dashed",
    )
    resolver = FakeNodeTypeResolver(
        {"normal": normal_type, "copy": copy_type}
    )
    layout = logical_layout((1,),)
    geometry = geometry_for(
        (1,),
        node_assignments=assignments,
        node_type_resolver=resolver,
        show_node_ids=False,
    )
    viewer = open_visualization(
        graph,
        graph_ui,
        assignments,
        resolver,
        layout,
        geometry,
    )
    accepted_rectangles = dict(viewer._snapshot.rectangles)

    assert rendered_rows(viewer)[0][:12] == "■──────────┐"

    assignments.assignments[1] = NodeAssignment("copy", "2", "Live title")
    viewer.refresh()

    assert rendered_rows(viewer)[0][:12] == "■╌╌╌╌╌╌╌╌╌╌┐"
    assert viewer._snapshot.rectangles == accepted_rectangles
    assert len(normal_type.render_calls) == 1
    assert len(copy_type.render_calls) == 1


def test_status_change_updates_next_render_without_changing_geometry() -> None:
    viewer, _, assignments, _, _ = open_single_node_viewer(
        "Live title", show_node_ids=False
    )
    accepted_rectangles = dict(viewer._snapshot.rectangles)
    before, width, _ = rendered(viewer)
    assert style_at(before, width, 0, 0).color == Style(color=viewer._theme["status-icon-color-none"]).color

    assignments.assignments[1] = NodeAssignment(
        "text", "", "Live title", "success"
    )
    viewer.refresh()

    after, width, _ = rendered(viewer)
    assert style_at(after, width, 0, 0).color == Style(color=viewer._theme["status-icon-color-success"]).color
    assert viewer._snapshot.rectangles == accepted_rectangles


def test_note_change_is_not_displayed_and_does_not_change_geometry() -> None:
    viewer, _, assignments, _, _ = open_single_node_viewer(
        "Visible title", show_node_ids=False
    )
    accepted_rendering = rendered_plain(viewer)
    accepted_rectangles = dict(viewer._snapshot.rectangles)

    assignments.assignments[1] = NodeAssignment(
        "text",
        "",
        "Visible title",
        "none",
        "SECRET NOTE\nwith Unicode 😀",
    )
    viewer.refresh()

    assert rendered_plain(viewer) == accepted_rendering
    assert "SECRET NOTE" not in rendered_plain(viewer)
    assert viewer._snapshot.rectangles == accepted_rectangles


def test_invalid_assignment_status_is_rejected() -> None:
    graph = FakeGraph(nodes=[1], edges=[])
    graph_ui = FakeGraphUI(show_node_ids=False)
    assignments = FakeNodeAssignments(
        {1: NodeAssignment("text", "", "Title", "complete")}
    )

    with pytest.raises(ValueError, match="node status is invalid"):
        open_visualization(
            graph,
            graph_ui,
            assignments,
            FakeNodeTypeResolver(),
            logical_layout((1,),),
            FakeGeometry(Geometry({1: Rect(0, 0, 12, 3)}, 12, 3)),
        )


def test_collapse_refresh_recalculates_layout_geometry_and_nested_state() -> None:
    viewer, _, graph_ui, _, _, _ = open_projected_viewer(
        [1, 2, 3, 4],
        [(1, 2), (2, 3), (3, 4)],
        collapsed_node_ids={2, 3},
    )
    assert viewer._snapshot.nodes == (1, 2)

    graph_ui.set_node_collapsed(2, False)
    viewer.refresh()

    assert viewer._snapshot.nodes == (1, 2, 3)
    assert viewer._snapshot.edges == ((1, 2), (2, 3))
    assert set(viewer._snapshot.rectangles) == {1, 2, 3}
    assert "┬──┐" in rendered_plain(viewer)

    graph_ui.set_node_collapsed(3, False)
    viewer.refresh()

    assert viewer._snapshot.nodes == (1, 2, 3, 4)
    assert viewer._snapshot.edges == ((1, 2), (2, 3), (3, 4))
    assert "┬──┐" not in rendered_plain(viewer)


def test_collapsing_branch_repositions_remaining_nodes_compactly() -> None:
    viewer, _, graph_ui, _, _, _ = open_projected_viewer(
        [1, 2, 3, 4],
        [(1, 2), (1, 3), (2, 4)],
    )
    expanded_width = viewer._snapshot.width

    graph_ui.set_node_collapsed(2, True)
    viewer.refresh()

    assert viewer._snapshot.nodes == (1, 2, 3)
    assert viewer._snapshot.edges == ((1, 2), (1, 3))
    assert viewer._snapshot.width < expanded_width


def test_hidden_nested_state_change_does_not_recalculate_geometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    viewer, _, graph_ui, _, _, _ = open_projected_viewer(
        [1, 2, 3],
        [(1, 2), (2, 3)],
        collapsed_node_ids={1},
    )
    accepted_rectangles = dict(viewer._snapshot.rectangles)

    def unexpected_geometry_call(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("hidden nested state recalculated geometry")

    monkeypatch.setattr(
        visualization_impl, "calculate_geometry", unexpected_geometry_call
    )
    graph_ui.set_node_collapsed(2, True)
    viewer.refresh()

    assert viewer._snapshot.rectangles == accepted_rectangles


def test_assignment_change_rewraps_without_recalculating_geometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    viewer, _, node_assignments, _, _ = open_single_node_viewer(
        "before", node_width=8, node_height=2
    )
    accepted_rectangles = dict(viewer._snapshot.rectangles)
    node_assignments.assignments[1] = NodeAssignment(
        type="agent", param="changed parameter", title="after content"
    )

    def unexpected_geometry_call(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("display-only refresh recalculated geometry")

    monkeypatch.setattr(
        visualization_impl, "calculate_geometry", unexpected_geometry_call
    )
    viewer.refresh()

    assert viewer._snapshot.rectangles == accepted_rectangles
    assert interior_rows(viewer, 1) == ["after ", "conte…"]


def test_invalid_refresh_preserves_complete_last_accepted_snapshot() -> None:
    viewer, graph_ui, node_assignments, _, _ = open_single_node_viewer(
        "accepted", node_width=12, node_height=2, selected=True
    )
    accepted_rendering = rendered_plain(viewer)
    accepted_rectangles = dict(viewer._snapshot.rectangles)
    accepted_selection = viewer._snapshot.selected_node
    accepted_width = viewer._snapshot.node_width
    node_assignments.assignments[1] = NodeAssignment(
        type="text", param="rejected", title=object()
    )
    graph_ui.selected_node = None
    graph_ui.node_width = 20
    graph_ui.node_height = 5

    with pytest.raises(ValueError):
        viewer.refresh()

    assert rendered_plain(viewer) == accepted_rendering
    assert viewer._snapshot.rectangles == accepted_rectangles
    assert viewer._snapshot.selected_node == accepted_selection
    assert viewer._snapshot.node_width == accepted_width


def test_refresh_validation_failure_preserves_previous_placement() -> None:
    viewer, _, _, node_assignments, resolver, layout, _ = open_two_node_viewer()
    accepted_rectangles = dict(viewer._snapshot.rectangles)
    geometry_missing_node = geometry_for(
        (1,),
        node_assignments=node_assignments,
        node_type_resolver=resolver,
    )

    with pytest.raises(ValueError):
        viewer.refresh(layout, geometry_missing_node)

    assert viewer._snapshot.rectangles == accepted_rectangles
    viewer.refresh()


def test_refresh_is_allowed_before_run() -> None:
    viewer, graph, _, node_assignments, resolver, _, _ = open_two_node_viewer()
    graph.nodes.append(3)
    graph.edges.append((2, 3))

    viewer.refresh(
        logical_layout((1,), (2,), (3,)),
        geometry_for(
            (1,),
            (2,),
            (3,),
            node_assignments=node_assignments,
            node_type_resolver=resolver,
        ),
    )

    assert viewer._snapshot.nodes == (1, 2, 3)
    viewer.refresh()


def test_running_viewer_polls_selection_and_graph_changes() -> None:
    viewer, graph, graph_ui, _, _, _, _ = open_two_node_viewer(node_height=2)
    wide_id = 1234567890123
    shared_width = len(str(wide_id))

    async def exercise_polling() -> None:
        app = _VisualizationApp(viewer._snapshot, viewer._poll_snapshot)
        async with app.run_test() as pilot:
            graph_ui.selected_node = 2
            await pilot.pause(0.15)

            canvas = app.query_one(_GraphCanvas)
            assert canvas._snapshot.selected_node == 2

            graph.nodes.append(wide_id)
            graph.edges.append((2, wide_id))
            graph_ui.selected_node = wide_id
            await pilot.pause(0.15)

            assert canvas._snapshot.nodes == (1, 2, wide_id)
            assert canvas._snapshot.edges == ((1, 2), (2, wide_id))
            assert canvas._snapshot.selected_node == wide_id
            assert set(canvas._snapshot.rectangles) == {1, 2, wide_id}
            assert {
                rect.width for rect in canvas._snapshot.rectangles.values()
            } == {shared_width}
            assert {
                rect.height for rect in canvas._snapshot.rectangles.values()
            } == {5}

    asyncio.run(exercise_polling())


def test_running_viewer_polls_node_dimension_changes() -> None:
    viewer, _, graph_ui, _, _, _, _ = open_two_node_viewer()

    async def exercise_dimension_change() -> None:
        app = _VisualizationApp(viewer._snapshot, viewer._poll_snapshot)
        async with app.run_test() as pilot:
            graph_ui.node_width = 20
            graph_ui.node_height = 4
            await pilot.pause(0.15)

            canvas = app.query_one(_GraphCanvas)
            assert {
                (rect.width, rect.height)
                for rect in canvas._snapshot.rectangles.values()
            } == {(20, 7)}

    asyncio.run(exercise_dimension_change())


def test_running_viewer_polls_id_visibility_and_compacts_geometry() -> None:
    node_id = 1234567890123
    viewer, graph_ui, _, _, _ = open_single_node_viewer(
        node_width=8, node_height=2, node_id=node_id
    )

    async def exercise_visibility_change() -> None:
        app = _VisualizationApp(viewer._snapshot, viewer._poll_snapshot)
        async with app.run_test() as pilot:
            graph_ui.show_node_ids = False
            await pilot.pause(0.15)

            canvas = app.query_one(_GraphCanvas)
            assert canvas._snapshot.rectangles[node_id] == Rect(0, 0, 8, 4)
            rendering, width, height = _render_snapshot(canvas._snapshot)
            assert (width, height) == (8, 4)
            assert str(node_id) not in rendering.plain

            graph_ui.show_node_ids = True
            await pilot.pause(0.15)
            assert canvas._snapshot.rectangles[node_id] == Rect(0, 0, 13, 5)
            assert str(node_id) in _render_snapshot(canvas._snapshot)[0].plain

    asyncio.run(exercise_visibility_change())


def test_running_viewer_polls_collapse_and_expansion_without_restart() -> None:
    viewer, _, graph_ui, _, _, _ = open_projected_viewer(
        [1, 2, 3, 4],
        [(1, 2), (1, 3), (2, 4)],
        selected_node=2,
    )

    async def exercise_collapse_change() -> None:
        app = _VisualizationApp(viewer._snapshot, viewer._poll_snapshot)
        async with app.run_test() as pilot:
            canvas = app.query_one(_GraphCanvas)
            original_rect = canvas._snapshot.rectangles[2]
            expanded_width = canvas._snapshot.width

            graph_ui.set_node_collapsed(2, True)
            await pilot.pause(0.15)

            assert canvas._snapshot.nodes == (1, 2, 3)
            assert canvas._snapshot.edges == ((1, 2), (1, 3))
            assert canvas._snapshot.selected_node == 2
            assert canvas._snapshot.rectangles[2].width == original_rect.width
            assert canvas._snapshot.rectangles[2].height == original_rect.height
            assert canvas._snapshot.width < expanded_width
            assert "┬──┐" in _render_snapshot(canvas._snapshot)[0].plain

            graph_ui.set_node_collapsed(2, False)
            await pilot.pause(0.15)

            assert canvas._snapshot.nodes == (1, 2, 3, 4)
            assert canvas._snapshot.edges == ((1, 2), (1, 3), (2, 4))
            assert "┬──┐" not in _render_snapshot(canvas._snapshot)[0].plain

    asyncio.run(exercise_collapse_change())


def test_running_viewer_polls_assignment_changes_without_geometry_change() -> None:
    viewer, _, node_assignments, _, _ = open_single_node_viewer(
        node_width=8, node_height=2
    )
    original_rectangles = dict(viewer._snapshot.rectangles)

    async def exercise_assignment_change() -> None:
        app = _VisualizationApp(viewer._snapshot, viewer._poll_snapshot)
        async with app.run_test() as pilot:
            node_assignments.assignments[1] = NodeAssignment(
                type="agent", param="unrelated", title="updated content"
            )
            await pilot.pause(0.15)

            canvas = app.query_one(_GraphCanvas)
            assert canvas._snapshot.rectangles == original_rectangles
            rendering, _, _ = _render_snapshot(canvas._snapshot)
            assert "updat" in rendering.plain

    asyncio.run(exercise_assignment_change())


def test_running_viewer_keeps_snapshot_and_recovers_after_invalid_assignment() -> None:
    viewer, _, node_assignments, _, _ = open_single_node_viewer(
        "accepted", node_height=2
    )

    async def exercise_invalid_assignment() -> None:
        app = _VisualizationApp(viewer._snapshot, viewer._poll_snapshot)
        async with app.run_test() as pilot:
            canvas = app.query_one(_GraphCanvas)
            accepted_rendering, _, _ = _render_snapshot(canvas._snapshot)
            node_assignments.assignments[1] = NodeAssignment(
                type="text", param="rejected", title=object()
            )
            await pilot.pause(0.15)

            retained_rendering, _, _ = _render_snapshot(canvas._snapshot)
            assert retained_rendering.plain == accepted_rendering.plain

            node_assignments.assignments[1] = NodeAssignment(
                type="file", param="not displayed", title="recovered"
            )
            await pilot.pause(0.15)

            recovered_rendering, _, _ = _render_snapshot(canvas._snapshot)
            assert "recovered" in recovered_rendering.plain

    asyncio.run(exercise_invalid_assignment())


def test_running_viewer_scrolls_complete_selected_envelope_into_view() -> None:
    columns = tuple(
        tuple(range(column * 8 + 1, column * 8 + 9))
        for column in range(8)
    )
    nodes = [node_id for column in columns for node_id in column]
    graph = FakeGraph(nodes=nodes, edges=[])
    graph_ui = FakeGraphUI(selected_node=1, node_height=4)
    node_assignments, node_type_resolver = display_dependencies()
    layout = logical_layout(*columns)
    geometry = geometry_for(
        *columns,
        node_assignments=node_assignments,
        node_type_resolver=node_type_resolver,
        node_height=4,
    )
    viewer = open_visualization(
        graph,
        graph_ui,
        node_assignments,
        node_type_resolver,
        layout,
        geometry,
    )

    async def exercise_scrolling() -> None:
        app = _VisualizationApp(viewer._snapshot, viewer._poll_snapshot)
        async with app.run_test(size=(40, 12)) as pilot:
            graph_ui.selected_node = 64
            await pilot.pause(0.15)

            viewport = app.query_one(
                "#graph-viewport",
                ScrollableContainer,
            )
            selected = geometry.get_rect(64)
            assert selected.height == 7
            selected_region = Region(
                selected.x,
                selected.y,
                selected.width,
                selected.height,
            )
            visible_region = viewport.scrollable_content_region.at_offset(
                viewport.scroll_offset
            )
            assert viewport.scroll_x > 0
            assert viewport.scroll_y > 0
            assert selected_region in visible_region

    asyncio.run(exercise_scrolling())


def test_edges_connect_to_main_rectangles_without_overwriting_ids() -> None:
    viewer = viewer_with_rectangles(
        nodes=[1, 2],
        edges=[(1, 2)],
        rectangles={
            1: Rect(0, 0, NODE_WIDTH, 4),
            2: Rect(16, 0, NODE_WIDTH, 4),
        },
    )

    rows = rendered_rows(viewer)

    assert rows[1][15] == "▶"
    assert rows[3][NODE_WIDTH - 1] == "1"
    assert rows[3][16 + NODE_WIDTH - 1] == "2"
    assert rows[3][0:NODE_WIDTH].strip() == "1"
    assert rows[3][16 : 16 + NODE_WIDTH].strip() == "2"


def test_edge_bends_use_rounded_corner_characters() -> None:
    viewer = viewer_with_rectangles(
        nodes=[1, 2],
        edges=[(1, 2)],
        rectangles={
            1: Rect(0, 0, 12, 4),
            2: Rect(16, 4, 12, 4),
        },
    )

    rows = rendered_rows(viewer)

    assert rows[1][13] == "╮"
    assert rows[5][13] == "╰"


def test_edge_branches_use_directional_t_junctions() -> None:
    viewer = viewer_with_rectangles(
        nodes=[1, 2, 3],
        edges=[(1, 2), (1, 3)],
        rectangles={
            1: Rect(0, 4, 12, 4),
            2: Rect(16, 0, 12, 4),
            3: Rect(16, 8, 12, 4),
        },
    )

    rows = rendered_rows(viewer)

    assert rows[5][13] == "┤"
