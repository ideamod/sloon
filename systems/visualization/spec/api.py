"""Public contract for terminal graph visualization.

Visualization is a read-only presentation system. It projects complete Graph
and Graph UI collapse state through Visible Graph, then renders property set
state with Textual using placement calculated by Logical Layout and Geometry.
It does not own visibility rules, route edges, handle navigation, edit graph or
property set state, persist selection, execute node commands, or own a database
connection.
"""

from pathlib import Path
from typing import Callable, Protocol

from systems.geometry.spec.api import GeometryAPI
from systems.geometry.spec.schema import Size
from systems.graph_ui.spec.api import GraphUIAPI
from systems.logical_layout.spec.api import LogicalLayoutAPI
from systems.nodes import Nodes
from systems.node_types.spec.api import NodeType


class VisualizationAPI(Protocol):
    """A terminal viewer over application-owned graph interfaces.

    Colors come from ``config/theme.yaml`` in the Visualization system
    directory. The file is loaded once when the viewer opens, regardless of
    working directory. It is a flat mapping of the documented semantic color
    keys to ``#RRGGBB`` values. The configured background fills the entire
    terminal screen and viewport, including empty space outside graph content,
    with empty, small, or oversized graphs and after terminal resizing or
    collapse changes. Selection retains its explicit configured background.
    Missing required keys, unknown keys, duplicate keys, or malformed
    entries raise ``ValueError`` naming the offending key. The loaded theme
    remains fixed for the viewer lifetime.

    Keys: background-color, text-color-normal, text-color-selected,
    selection-color, border-color-normal, border-color-selected, edge-color,
    status-icon-color-none, status-icon-color-progress,
    status-icon-color-success, status-icon-color-warning, and
    status-icon-color-failure. Background color applies to the screen, viewport,
    and canvas; selected
    node cells use selection-color. Node borders use the optional
    node-color-green, node-color-red, node-color-blue, node-color-white,
    node-color-gray, node-color-orange, or node-color-yellow entry matching
    their stored color property. Selected nodes use the corresponding
    ``-selected`` variant, such as node-color-green-selected. A missing color
    or theme entry falls back to border-color-normal or border-color-selected
    according to selection. Node text uses its normal or selected foreground.
    Edges use edge-color. Status squares use
    their status foreground even when selected, with selection-color behind
    them. Colors do not alter glyphs, geometry, or navigation.

    The viewer retains the interfaces supplied to :func:`open_visualization`,
    but does not own, close, or modify them. Unless documented otherwise,
    methods are intended to be called from the same application/UI thread;
    thread-safe refresh is not part of this contract.
    """

    def run(self) -> None:
        """Launch the Textual viewer and block until it exits.

        Every graph node is rendered as a bordered main rectangle. When Graph
        UI's global ID-visibility setting is enabled, the rectangle is followed
        by one reserved row for its plain decimal ID. For each node, the viewer
        gets its property set from the retained ``Nodes``. It
        resolves the property set's type and calls ``NodeType.render()`` with a
        ``NodeContext`` containing the visible node ID, the absolute workspace
        path, its effective properties, and the Nodes API. Visualization interprets missing application properties
        with its presentation defaults (including ``void``, ``none``, empty
        text, and weight zero). Nodes itself does not define those defaults.
        Visualization never calls ``NodeType.execute()`` and neither
        Visualization nor a conforming ``render()`` call modifies Graph or
        Nodes.

        The main rectangle contains the property set title using Visualization's
        existing wrapping and truncation behavior. When that title is empty,
        it uses ``NodeRender.title`` instead, allowing a copy node to inherit
        the title supplied by the node it copies. ``NodeRender.border_style``
        selects the border.
        The top-left border junction is replaced by the single-cell square
        ``■`` for every node. Its foreground color is determined by the
        property set status through the corresponding ``status-icon-color-*``
        theme key. The default values are gray, blue, green, yellow, and red
        for ``none``, ``progress``, ``success``, ``warning``, and ``failure``.
        Selection styling applies the same selection background to the square
        as to the rest of the node while its foreground remains determined
        exclusively by status. Selecting or deselecting a node does not
        modify its status. The square is used with both solid and dashed
        borders and occupies the existing corner cell, so it does not change
        node or envelope dimensions.
        Assignment notes, tags, and weights are not displayed inside node
        rectangles. Notes and tags do not affect wrapping, node dimensions,
        geometry, layout, border style, or execution behavior. Weight is passed
        to Logical Layout and affects only vertical ordering and resulting
        geometry.
        The supported styles and exact terminal translations are::

            solid:  horizontal ``─`` and vertical ``│``
            dashed: horizontal ``╌`` and vertical ``╎``

        The remaining corners use ``┐``, ``└``, and ``┘`` for both styles
        because Unicode provides no corresponding light dashed corner set. An
        unsupported border style or invalid ``NodeRender`` raises
        ``ValueError`` during opening or explicit refresh; polling retains the
        last valid snapshot. Visualization does not infer style from a type
        name.

        The visible main rectangle is exactly ``node_width`` terminal cells
        wide and ``node_height + 2`` rows high: one top border, exactly
        ``node_height`` interior text rows, and one bottom border. All nodes in
        a snapshot use the same main-rectangle dimensions regardless of
        whether their title is empty, short, or truncated.

        A visible collapsed node displays an internal indicator only when it
        has at least one outgoing edge in the complete Graph. The indicator
        occupies the rightmost three columns of the existing main rectangle.
        A style-matched vertical separator precedes two indicator-content
        cells, containing ``+`` centered as ``"+ "``. The top separator is
        ``┬`` and the bottom separator is ``┴``. For ``node_width=12`` the
        exact structure is::

            ■───────┬──┐
            │ title │+ │
            └───────┴──┘

        A dashed collapsed node uses the same junction characters with dashed
        horizontal and vertical segments::

            ■╌╌╌╌╌╌╌┬╌╌┐
            ╎ title ╎+ ╎
            └╌╌╌╌╌╌╌┴╌╌┘

        Its external width and height are unchanged. Expanded nodes and
        collapsed leaves use the ordinary rectangle without a separator. A
        collapsed indicator requires ``node_width >= 6`` so at least one title
        cell remains. A smaller width is invalid for that display snapshot and
        raises ``ValueError`` during opening or explicit refresh; polling keeps
        the last valid snapshot. Visualization never widens the node.

        Title text is rendered literally; Rich markup has no special
        meaning. Before wrapping, every explicit line-break sequence is
        replaced with one space. Text is then greedily wrapped across the
        ``node_width - 2`` interior terminal cells for an ordinary node, or
        ``node_width - 5`` title cells for a collapsed node with an indicator,
        and exactly ``node_height`` rows. A line uses the greatest prefix that fits,
        preferring the last available whitespace boundary; whitespace used as
        the wrap boundary is not rendered at either edge. A word that cannot
        fit on an otherwise empty line is split at the available width. If all
        normalized text fits, no ellipsis is added and any unused interior rows
        are blank. If normalized text remains after the final available row,
        that row ends with the single-cell, single-character ellipsis ``…``:
        append it when space remains, or replace the final visible cell with it
        when the row is full. Thus a one-cell interior renders only ``…`` when
        truncation is required. An empty title leaves every interior row
        blank.

        When ID visibility is enabled, the node ID is rendered independently
        of property set, node type, and title content. It is the complete
        untruncated decimal form
        of the ID, including a minus sign for a negative ID. It has no border
        and no background rectangle. It occupies the row immediately below
        the main rectangle and is right-aligned with the main rectangle: the
        ID's final character is directly below the main rectangle's right
        border. The selected-node styling covers both the main rectangle and
        the plain ID, so selection remains visible in both regions. When ID
        visibility is disabled, no ID or ID row is rendered and selection
        styling covers only the visible main rectangle.

        Each rectangle supplied by Geometry is the complete occupied envelope
        reserved for a node, not merely the visible main rectangle. For an
        envelope ``rect``, main width ``node_width``, main height
        ``node_height + 2``, and ID text ``str(node_id)``, the exact top-left
        coordinates are::

            main_x = rect.x + rect.width - node_width
            main_y = rect.y
            id_x = rect.x + rect.width - len(str(node_id))
            id_y = rect.y + node_height + 2

        With IDs enabled, the occupied envelope is ``node_height + 3`` rows high. Its width is
        shared by all nodes and is large enough for both the main rectangle and
        every complete ID. Consequently, an ID wider than the main rectangle
        extends to its left while retaining the common right edge, entirely
        within the envelope. Geometry places only these envelopes; it has no
        responsibility for title wrapping, main-rectangle layout, or ID
        layout. Visualization introduces no separate text-layout or ID-layout
        subsystem. With IDs disabled, the occupied envelope is exactly
        ``node_width`` cells wide and ``node_height + 2`` rows high. It is the
        visible main rectangle itself, and ID length has no effect on geometry.

        Directed graph edges are rendered with terminal lines, rounded
        corners, directional junctions, and arrowheads. Edges attach to the
        visible main rectangles, never to the external-ID row or unused cells
        of an envelope. The complete occupied envelope takes visual precedence:
        edge cells that would overlap it are clipped or omitted, so an edge can
        never obscure a main rectangle or ID. Edge routing beyond this
        best-effort rendering is not part of the contract.

        The content area is scrollable horizontally and vertically when the
        geometry exceeds the terminal viewport. Empty graphs launch as a
        usable empty viewer.

        On every accepted snapshot, Visualization reads complete nodes and
        edges from Graph and collapsed IDs from Graph UI, then calls Visible
        Graph. Only the returned nodes and edges are assigned titles, supplied
        to Logical Layout and Geometry, and rendered. Hidden nodes and edges
        never appear. Visibility traversal and filtering remain exclusively
        owned by Visible Graph. Collapse does not change occupied node sizes;
        collapsed and expanded nodes with the same ID-visibility setting have
        identical Geometry dimensions.

        While running, the viewer polls its retained graph, graph-UI, and node
        property set dependencies every 100 milliseconds.
        Selection changes are redrawn using the current placement and
        automatically scrolled into view. When collapse expansion reveals a
        newly selected node, its visible projection and placement are updated
        before its complete envelope is scrolled into view. Graph topology changes trigger fresh
        logical layout, size, and geometry calculations before being redrawn;
        a topology change can also change the widest ID and shared occupied
        width. A collapse change that affects visible topology or indicator
        appearance triggers fresh Visible Graph, Logical Layout, size, and
        Geometry calculation. Hidden nested-state changes with no display
        effect do not recalculate placement. A node-width, node-height, or
        ID-visibility change triggers fresh wrapping, sizes, and geometry.
        Assignment changes trigger fresh type resolution, presentation,
        status-indicator and border rendering, and title wrapping;
        because title content does not affect the fixed node dimensions, those
        changes alone do not require new geometry. If the selected node moves, its complete occupied
        envelope is scrolled into view again. If any polled state is
        temporarily invalid or cannot produce a display snapshot, the last
        valid snapshot remains displayed and polling continues.

        The method returns normally when the viewer exits. Textual startup or
        runtime failures are not converted to visualization-specific exception
        types. Calling ``run`` again after the viewer has exited is not
        guaranteed to be supported.
        """
        ...

    def refresh(
        self,
        logical_layout: LogicalLayoutAPI | None = None,
        geometry: GeometryAPI | None = None,
    ) -> None:
        """Replace the displayed snapshot after an external state change.

        On every call, the viewer rereads complete nodes and edges from the
        retained ``Nodes`` API; collapsed IDs, selected node ID, width, height,
        and ID visibility from the retained ``GraphUIAPI``; projects them with
        Visible Graph; reads each visible property set; resolves its node type;
        and calls ``NodeType.render()`` for its border style. It never calls
        ``NodeType.execute()``. Text is rewrapped from the property set title, or
        from ``NodeRender.title`` when the property set title is empty, on every
        successful refresh, including after width, height, or property set
        changes.

        With no arguments, the complete graph's nodes and edges must be
        unchanged from the graph snapshot associated with the accepted
        placement. If graph
        topology has changed, ``ValueError`` is raised rather than silently
        displaying it with stale logical placement. Otherwise the viewer
        retains or recalculates placement after collapse or property set-weight
        changes as needed and
        redraws current selection, border style, status indicator,
        collapsed-node indicator, and title text. It retains
        geometry when visible topology, indicator nodes, current node width,
        node height, shared occupied width, and ID visibility are unchanged. If
        any of those has changed, it recalculates geometry from the retained logical layout
        before redrawing. Title changes alone never change the fixed
        occupied size.

        When both ``logical_layout`` and ``geometry`` are supplied, the viewer
        accepts them as updated placement for the graph state read by this
        call, rereads all graph-UI and property set state, and schedules the
        display to be redrawn. Supplying only one of the two placement
        arguments raises ``ValueError``. The method does not mutate any
        supplied system.

        Newly supplied layout and geometry must each contain exactly the nodes
        currently returned by Visible Graph. Every geometry rectangle
        represents one node's complete occupied envelope and must have the exact
        dimensions returned for that node by :func:`measure_node_sizes` using
        the same property set state and current graph-UI width and
        height and ID visibility. Any dependency, argument, topology, or placement validation
        failure raises ``ValueError`` and preserves the complete last
        successfully accepted display snapshot, including its selection,
        title text, wrapping, and dimensions.

        A selected ID that is ``None`` or is absent from the visible graph is
        valid: no node is highlighted, and the stored selection is left
        unchanged. When the ID exists, its main rectangle and, when visible,
        external ID must remain visually distinct from those of unselected nodes.

        The caller must supply successfully recalculated visible layout and
        geometry after complete Graph topology changes. Collapse-only changes
        are recalculated by a no-argument refresh. ``refresh`` may be called before
        :meth:`run`; a successful call updates the snapshot that the viewer
        will display when launched.
        """
        ...


def measure_node_sizes(
    node_ids: list[int],
    nodes: Nodes,
    node_type_resolver: Callable[[str], NodeType],
    node_width: int = 12,
    node_height: int = 1,
    show_node_ids: bool = True,
) -> dict[int, Size]:
    """Return the exact occupied-envelope size required for each node.

    This is the visualization system's sizing step, not a placement, text-
    wrapping, or layout calculation. The result contains one ``Size`` for
    every supplied node ID and is suitable for the ``sizes`` argument of
    ``geometry.calculate_geometry``. To preserve display-snapshot validation,
    the function gets each property set and validates its string fields. Title
    content and collapse state do not affect the returned size. The retained
    node-type resolver, ``display``, and ``command`` are never called, and
    neither dependency is modified.

    ``node_width``, defaulting to 12 terminal cells, is the visible main
    rectangle's width. ``node_height``, defaulting to 1, is the exact number of
    its interior text rows. The shared occupied width is::

        max(node_width, max(len(str(node_id)) for node_id in node_ids))

    With ``show_node_ids=True``, every returned ``Size`` uses that shared width and a height of
    ``node_height + 3``: ``node_height + 2`` rows for the bordered main
    rectangle and one additional row for the plain external ID. All node sizes
    are therefore identical within a snapshot. No border or background space
    is added to the ID width, and neither empty nor overflowing title text
    changes the size. With ``show_node_ids=False``, every size is exactly
    ``Size(node_width, node_height + 2)``. No ID row is reserved and even an ID
    wider than ``node_width`` does not increase the occupied width.

    When these sizes are passed to ``geometry.calculate_geometry``, that
    call's ``node_width`` must be the shared occupied width returned here,
    rather than the visible main-rectangle width supplied to this function.
    This is needed because Geometry validates per-node widths but uses its
    global ``node_width`` argument for every output rectangle. For a non-empty
    result, the shared value can be read from any returned ``Size.width``.
    Geometry remains responsible only for placing the occupied envelopes and
    remains unaware of the main rectangle, wrapped text, and external ID.

    ``node_width`` must be an integer of at least 3, ``node_height`` must be an
    integer of at least 1, and ``show_node_ids`` must be a bool. ``node_ids``
    is normally the visible-node snapshot returned by Visible Graph and must
    contain unique integers.
    ``ValueError`` is raised for duplicate IDs, invalid dimensions, an invalid
    property set result; dependency lookup errors otherwise propagate. No
    visualization-specific public size type is introduced; the existing
    geometry ``Size`` is returned directly. For an empty ``node_ids`` list,
    the result is empty and no shared occupied width is needed. Logical Layout
    and Geometry receive only these sizes and remain independent of property set
    titles, node types, and the meaning of the reserved external-ID row.
    """
    ...


def open_visualization(
    nodes: Nodes,
    graph_ui: GraphUIAPI,
    node_type_resolver: Callable[[str], NodeType],
    logical_layout: LogicalLayoutAPI,
    geometry: GeometryAPI,
    *,
    workspace_path: Path,
) -> VisualizationAPI:
    """Create a viewer over existing graph, display, and placement APIs.

    The caller supplies the absolute path of the workspace backing Nodes.
    The viewer passes it to every render context, including during refresh.

    Opening reads complete graph nodes and edges; collapsed IDs, the current
    selected node, width, height, and ID visibility; calculates Visible Graph;
    reads visible properties, resolves their node types, and calls
    ``NodeType.render()``. It then accepts the supplied layout and geometry as
    the initial visible display snapshot. The property set title is the primary
    source of text inside each node, with ``NodeRender.title`` as the fallback
    when it is empty; ``NodeRender.border_style`` is the source of its border
    style. The viewer retains the stateful supplied dependencies for refresh,
    but creates no persistence, opens no SQLite connection, and takes
    ownership of none of them.

    The layout and geometry must each contain exactly the nodes currently
    returned by Visible Graph. Geometry rectangles are occupied envelopes
    rather than main-node rectangles, and their dimensions must match
    :func:`measure_node_sizes` for those node IDs using the supplied property set
    API and current graph-UI width, height, and ID visibility. A mismatch or
    invalid property set result raises ``ValueError`` and no viewer is returned.
    An empty visible graph, empty layout, and empty geometry form a valid
    initial snapshot and require no property set lookups.

    A caller using ``geometry.calculate_geometry`` must configure that call
    with the shared occupied width returned by :func:`measure_node_sizes`, not
    the graph-UI width that controls the visible main rectangle. Visualization
    derives the right-aligned main rectangle, wrapped text, and plain ID from
    each accepted occupied envelope. Geometry remains unaware of all three.

    Initial Visible Graph, Logical Layout, and Geometry calculation deliberately
    occurs outside this API. If
    ``logical_layout.calculate_layout`` rejects a cyclic, self-looping, or
    otherwise invalid graph, the caller must not open the viewer with invented
    placement. If recalculation fails for an already open viewer, the caller
    must not call :meth:`VisualizationAPI.refresh`; the viewer retains its last
    successful snapshot and can remain open or be exited by the application.
    Visualization neither catches that upstream ``ValueError`` nor calculates
    a fallback layout.

    This factory only constructs the public viewer. Application startup,
    dependency construction, error reporting, and the intended ``make show``
    entry point remain outside the visualization contract.
    """
    ...
