"""Public API contract for graph controls.

Terminal interaction contract:
- In normal mode, pressing ``t`` opens text input prefilled with the selected
  node's current title, or an empty value when it has no property set/title.
- The title input cursor starts immediately after the prefilled value.
- Submitting that input passes its exact text to ``set_selected_title``.
- While title input is open, typed keys are text and do not trigger normal-mode
  shortcuts.
- In normal mode, pressing ``c`` opens an empty input for a target node ID.
- Submitting a valid integer target attempts to connect the selected node to that
  target through ``connect``; invalid input does not modify the graph.
- Node dimensions use compact colon commands: ``:w<cells>`` and ``:h<rows>``
  with no whitespace between the command letter and decimal integer. Spaced
  forms such as ``:w 20`` and ``:h 2`` are invalid.
- ``:status <value>`` submits the value directly through
  ``set_selected_status``. The value must be one of ``none``, ``progress``,
  ``success``, ``warning``, or ``failure``. ``:status`` without a value and
  invalid values do not modify properties. No ``:s`` alias is provided.
- The exact command ``:tags`` opens a single-line input prefilled with the
  selected node's exact tags string, or an empty value when no property set is
  stored. Enter passes the exact input through ``set_selected_tags`` and Escape
  cancels without modifying the property set. While open, typed keys do not
  trigger normal-mode shortcuts.
- In normal mode, Up Arrow increases the selected node's property set weight by
  one and Down Arrow decreases it by one. These operations keep selection on
  the same node and immediately affect subsequent logical-layout calculation.
- The exact command ``:weight`` opens a single-line input prefilled with the
  selected node's decimal weight. Enter stores a valid signed integer through
  ``set_selected_weight``; invalid input changes nothing. Escape cancels.
- ``/`` opens live node selection. An all-decimal query retains direct node-ID
  navigation within the active graph. Any other non-blank query searches
  active graph titles by case-insensitive substring, including nodes hidden
  by collapse.
  Search results temporarily replace selected-node information and show the
  query, match count, title, node ID, type, and status. Duplicate titles remain
  separate results in Graph node order. Up and Down change the active result,
  Enter selects it through ``select_node``, and Escape cancels without changing
  selection. Empty or whitespace-only queries never list every node.
- The terminal interface continuously displays a compact, read-only panel. Its
  first region is the latest Control status message, visually separated from
  selected-node information. Use restrained semantic styling for successful,
  warning, and error results.
- Selected-node information starts with ``SELECTED NODE`` and its ID, followed
  by a prominent title, then type and status. Style property set status as:
  ``none`` gray, ``progress`` blue, ``success`` green, ``warning`` yellow, and
  ``failure`` red.
- Display the current integer weight with the selected-node metadata. Display
  param, note, and tags in separate, compact sections. Display all
  param and tags text.
  Display at most the first three note lines and append an ellipsis when more
  lines exist. This truncation is presentation-only and must not modify note
  data. Render empty title, param, note, and tags values unobtrusively.
- Use one thin, dim horizontal rule after the Control status message, one after
  the selected-node header metadata, one between PARAM and NOTE, and one
  between NOTE and TAGS. Each rule spans the currently available content
  width, updates after terminal resize, and remains at least one cell wide in
  a narrow terminal. Do not render adjacent duplicate rules or add blank lines
  around them.
- Refresh the panel after Control status changes and periodically read
  ``get_selected_info`` so selection and property set changes appear without a
  command. Preserve Unicode and multiline content. The layout must wrap and
  reflow at narrow widths and after terminal resize without fixed-width boxes.
- With no selection, display ``No node selected``. For a selected node without
  an property set, display empty title, param, note, and tags, effective type
  ``void``, and status ``none``. Displaying the panel must not modify data.
- The terminal interface does not support an ``:info`` command because selected
  node information is always visible.
- The exact command ``:note`` edits the selected node's note in Vim. Initialize
  a temporary UTF-8 file with the exact current note, suspend the terminal app,
  and run ``vim`` with that file. Always restore and refresh the app and remove
  the temporary file afterward.
- When Vim exits with status zero and the temporary file contents changed,
  decode them as UTF-8 and pass the exact text to ``set_selected_note``. Preserve
  Unicode, whitespace, newlines, and trailing newlines. An unchanged file
  (including ``:q!``), missing selection, launch/suspension/read failure, invalid
  UTF-8, or nonzero exit must not modify the property set and must be reported in
  the Control status message.
- The exact command ``:param`` uses the same temporary UTF-8 file, terminal
  suspension, Vim execution, unchanged-file handling, failure handling, cleanup,
  and refresh behavior as ``:note``, using the current parameter text and
  persisting changed contents through ``set_selected_param``. ``:param <value>``
  remains the direct inline parameter update command.
- In normal mode, ``y`` copies the selected node to the system clipboard
  and ``p`` pastes a copy as an output of the selected node. In Control
  inputs these keys enter text. Native terminal paste remains a text editing
  action. Use Ctrl+C to quit from normal mode.
- In normal mode, ``g`` enters the selected container and ``q`` leaves the
  active container. Within an input these keys enter text. At root, ``q``
  has no effect.
- A ``:type`` command that would change a container to another type reports
  the rejection in the Control status panel.
- Copy and paste report the result in the Control status panel. Missing
  selection, invalid clipboard data, and clipboard I/O failures do not change
  the graph. Paste does not write to the clipboard.
- The command ``:color`` opens an input prefilled with the selected node's
  color. ``:color <value>`` sets it inline. Use ``none`` or submit an empty
  color input to restore the default.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Protocol

from systems.graph_ui.spec.api import GraphUIAPI
from systems.nodes import Nodes
from systems.node_types.spec.api import NodeType

NODE_COLORS = ("green", "red", "blue", "white", "gray", "orange", "yellow")


class Direction(Enum):
    LEFT = auto()
    RIGHT = auto()
    UP = auto()
    DOWN = auto()


@dataclass(frozen=True)
class NodeInfo:
    """Effective application properties for an existing node.

    Control supplies its UI defaults for missing textual Nodes properties and
    parses the decimal ``weight`` property to an integer.
    """

    node_id: int
    properties: dict[str, str | int]


@dataclass(frozen=True)
class TitleSearchResult:
    """Read-only property set metadata for one node-title match."""

    node_id: int
    title: str
    type: str
    status: str


class ControlAPI(Protocol):
    """Coordinate graph editing, selection, and node execution."""

    def enter_container(self) -> bool:
        """Enter the selected visible container, clear selection, and return True.

        A container is a node whose type property is exactly "container".
        Persist its decimal node ID as the active container ID. Empty
        containers are enterable. Return False with no changes when the
        selected node is absent, hidden, or has any other type.
        """
        ...

    def leave_container(self) -> bool:
        """Leave the active container and return True.

        Read the container's immediate parent from its container_id property,
        defaulting to root. Persist that active ID and reveal and select the
        exited container in the parent graph. An invalid persisted active ID
        or ancestry is recovered by persisting root and clearing selection.
        At root return False without changes. There is no navigation stack.
        """
        ...

    def select_node(self, node_id: int) -> bool:
        """Reveal and select an existing node in the active graph.

        First call :meth:`reveal_node`. If revealing succeeds, select the node
        through Graph UI and return True.

        If ``node_id`` is invalid, missing, or outside the active graph, return
        False without changing collapse state or selection. Propagate graph
        validation errors without changing selection.
        """
        ...

    def reveal_node(self, node_id: int) -> bool:
        """Expand only the collapsed nodes needed to reveal ``node_id``.

        Return False without modifying state when ``node_id`` is not an
        integer (excluding bool) or is outside the active graph. Return True
        without modifying state when it is already visible.

        Project active graph membership and read collapsed state, then
        calculate the entire reveal plan through Visible Graph before changing
        persistence. Expand only IDs in that plan using
        ``GraphUIAPI.set_node_collapsed(id,
        False)``. Preserve unrelated collapsed nodes.

        Do not change selection, graph topology, node properties, dimensions,
        or other Graph UI state. Propagate graph validation errors; validation
        failures occur before any collapse state is changed.
        """
        ...

    def get_selected_info(self) -> NodeInfo | None:
        """Return information about the selected existing node.

        Return None if no existing graph node is selected.

        Do not create or modify properties.
        Do not execute or render the node.
        """
        ...

    def search_titles(self, query: str) -> tuple[TitleSearchResult, ...]:
        """Return deterministic case-insensitive partial title matches.

        ``query`` must be a string. Raise ``ValueError`` for any other value.
        Strip leading and trailing query whitespace, then compare with
        ``str.casefold``. Return an empty tuple for an empty or whitespace-only
        query rather than matching every node.

        Search the active graph's nodes in Graph order, including nodes hidden
        by collapse. Read properties only through
        ``Nodes``. Nodes without properties, properties with an
        empty title, and nodes deleted before their property set can be read are
        skipped. Preserve duplicate titles as distinct results.

        Each result contains the title exactly as stored plus its node ID,
        property set type, and status. Do not modify Graph, Graph UI, collapse or
        selection state, Nodes, or node execution state.
        """
        ...

    def move(self, direction: Direction) -> int | None:
        """Move selection using the current logical layout.

        Recalculate Visible Graph from current graph and collapsed state, then
        calculate Logical Layout from that visible projection.

        If no visible graph node is selected, select and return the first
        visible node in Graph input order.

        If there is no node in the requested direction,
        keep and return the current selection.

        Return None if the visible graph is empty.
        """
        ...

    def create_node(self) -> int:
        """Create and select a disconnected graph node.

        Return its ID.

        Store the effective active container ID as container_id for all nodes
        created through Control. At root, omit the property. Membership is
        assigned at creation and is unavailable for editing through Control.
        An invalid active ID or ancestry uses root for graph operations.
        Do not materialize other standard defaults unnecessarily.
        """
        ...

    def create_output(self) -> int | None:
        """Create a node connected from the selected node.

        Create an edge:
            selected -> new

        Select and return the new node.

        If no existing node is selected, return None
        without changing anything.
        """
        ...

    def create_input(self) -> int | None:
        """Create a node connected to the selected node.

        Create an edge:
            new -> selected

        Select and return the new node.

        If no existing node is selected, return None
        without changing anything.
        """
        ...

    def delete_selected(self) -> int | None:
        """Delete the selected graph node.

        Return the deleted node ID.

        Connected edges are removed by Graph.

        Before deletion, read the selected node's inputs in the active graph
        in Graph order. After deletion, select the first surviving input when
        one exists. If an ordinary node has no input, do not make another
        selection.

        For a container, delete all its immediate members and descend through
        nested containers in one Nodes transaction. Visit each node at most
        once. Follow only exact membership references to containers. Clear
        selection if no input survives. Do not repair malformed properties.

        If no existing node is selected, return None
        without changing anything.

        Copy-chain reproperty set is not part of this contract.
        """
        ...

    def connect(self, target_id: int) -> bool:
        """Connect the selected node to target_id.

        Create:
            selected -> target

        Return True if both nodes belong to the active graph and the connection
        preserves a directed acyclic graph.

        Reject self-loops and cycles.

        Invalid operations must not modify the graph.
        """
        ...

    def disconnect(self, other_id: int) -> bool:
        """Remove edges between the selected node and other_id.

        Remove edges in either direction.

        Return True if both distinct nodes exist.
        Missing edges are accepted.

        Otherwise return False without changing the graph.
        """
        ...

    def disconnect_all(self) -> int | None:
        """Remove all incoming and outgoing edges of the selected node.

        Return the number of removed edges.

        Return None without changes if there is no
        existing selected node.
        """
        ...

    def set_node_width(self, width: int) -> bool:
        """Set the global node width.

        Accept only integers >= 3, excluding bool.

        Persist through GraphUIAPI.

        Return True on success, False for invalid input.
        Invalid input must not change the current width.
        """
        ...

    def set_node_height(self, height: int) -> bool:
        """Set the global number of interior node text rows.

        Accept only integers >= 1, excluding bool.

        Persist through GraphUIAPI.

        Return True on success, False for invalid input.
        Invalid input must not change the current height.
        """
        ...

    def toggle_node_ids(self) -> bool:
        """Toggle global node-ID visibility and return the new value.

        Read and persist the setting through ``GraphUIAPI``. Do not modify the
        graph, node properties, selection, or node dimensions.

        This operation implements the argument-free ``:id`` command.
        """
        ...

    def toggle_selected_collapse(self) -> bool | None:
        """Toggle collapse state for the selected visible non-leaf node.

        Persist the new state through ``GraphUIAPI`` and keep selection on the
        toggled node. Return True when newly collapsed and False when newly
        expanded. Return None without changes when there is no selected
        visible node or the selected node has no outgoing edges in the active graph.

        Do not modify Graph nodes or edges, node properties, selection, node
        dimensions, or collapsed state belonging to any other node.
        """
        ...

    def set_selected_type(self, type: str) -> bool:
        """Change the selected node's application ``type`` property.

        Require a non-empty string.
        Persist only this property; preserve every other stored property.
        Missing application properties retain their effective Control defaults
        without being materialized in Nodes.

        Do not require the type to be registered in Node Types.

        Return False without changes if:
        - no existing node is selected;
        - type is not a string;
        - type is empty;
        - the selected node is a container and the requested type is different.

        Any ordinary node can become a container. Reapplying the current
        container type is accepted. Other property edits keep their usual
        behavior. Persist successful type assignments through Nodes and
        return True.
        """
        ...

    def set_selected_param(self, param: str) -> bool:
        """Change the selected node's application ``param`` property.

        Require a string, including an empty string.

        Persist only this property and preserve every other stored property.

        Preserve whitespace, punctuation, and case exactly.

        Return False without changes if:
        - no existing node is selected;
        - param is not a string.

        Otherwise persist and return True.
        """
        ...

    def set_selected_color(self, color: str) -> bool:
        """Set the selected node's color, or clear it with an empty string.

        Return False if the color is invalid or no existing node is selected.
        """
        ...

    def set_selected_title(self, title: str) -> bool:
        """Change the selected node's application ``title`` property.

        Require a string, including an empty string.

        Persist only this property and preserve every other stored property.

        Preserve whitespace, punctuation, and case exactly.

        Return False without changes if:
        - no existing node is selected;
        - title is not a string.

        Otherwise persist and return True.
        """
        ...

    def set_selected_status(self, status: str) -> bool:
        """Change the selected node's application ``status`` property.

        Accept exactly one of: ``none``, ``progress``, ``success``,
        ``warning``, or ``failure``.

        Persist only this property and preserve every other stored property.

        Return False without changes if there is no existing selected node or
        status is not one of the allowed strings. Otherwise persist through
        Nodes and return True.
        """
        ...

    def set_selected_note(self, note: str) -> bool:
        """Change the selected node's application ``note`` property.

        Require a string, including an empty string. Preserve the exact value,
        including Unicode text, whitespace, and line breaks, without trimming
        or normalization.

        Persist only this property and preserve every other stored property.

        Return False without changes if there is no existing selected node or
        note is not a string. Otherwise persist through Nodes and
        return True. Do not modify Graph UI.
        """
        ...

    def set_selected_tags(self, tags: str) -> bool:
        """Change the selected node's application ``tags`` property.

        Require a string, including an empty string. Preserve the exact value,
        including Unicode, whitespace, commas, and repeated tag names, without
        parsing, trimming, normalization, per-tag validation, or deduplication.

        Persist only this property and preserve every other stored property.

        Return False without changes if there is no existing selected node or
        tags is not a string. Otherwise persist through Nodes and
        return True. Do not modify Graph UI.
        """
        ...

    def set_selected_weight(self, weight: int) -> bool:
        """Change the selected node's application ``weight`` property.

        Accept integers, excluding bool, including positive, negative, and
        zero. Store its decimal text representation through Nodes and preserve
        every other stored property.

        Return False without changes for an invalid value or when no existing
        node is selected. Otherwise persist through Nodes, keep the
        same selection, and return True.
        """
        ...

    def copy_selected(self) -> str | None:
        """Serialize the selected node's stored properties as clipboard text.

        Read every key and value through Nodes.get_all(), preserving arbitrary
        keys and empty values. Return None if there is no existing selected
        node. Copy never changes graph or UI state.

        The clipboard format is a JSON object with exactly three fields:
        ``"format": "sloon-node"``, ``"version": 1``, and ``"properties"``
        containing an object of non-empty string keys and string values. An
        empty properties object is valid. The payload is a snapshot with no
        workspace identity, node ID, edges, or UI state. The terminal
        interface writes the returned text to the system clipboard.
        """
        ...

    def paste_selected(self, clipboard_text: str) -> int | None:
        """Paste clipboard properties as a new output of the selected node.

        Return the new node's ID. Copy properties except for container_id,
        which is determined by the active graph. Connect the selected node
        in the active graph to the new node in one Nodes transaction.
        Preserve existing nodes, edges, selection, and UI state.
        If Nodes rejects the pasted properties, roll back the transaction
        and return None. Other storage failures roll back and propagate.

        Return None without changing the graph when there is no existing
        selected node in the active graph or the text is empty, malformed,
        or has an unsupported format or version. Reject duplicate JSON keys
        and require a string value for each property. Nodes validates the
        keys and values.
        Pasting is repeatable and independent of the original node and
        workspace. The terminal interface reads the system clipboard and
        leaves its contents intact.
        """
        ...

    def execute_selected(self) -> bool:
        """Execute the currently selected existing node.

        Return False if no existing graph node is selected.

        Otherwise:
        1. Read the selected node's stored type, using "void" when absent.
        2. Resolve its Node Type.
        3. Build NodeContext with the selected node ID, the absolute workspace
           path, and the Nodes API. The Node Type reads any required
           properties through Nodes.
        4. Call NodeType.execute(context).
        5. Return True if execute returns normally.

        If ``type`` is missing, resolve as type "void" without persisting it.

        Propagate exceptions raised during execution.

        Do not change selection automatically.
        """
        ...


def open_control(
    nodes: Nodes,
    graph_ui: GraphUIAPI,
    resolve_node_type: Callable[[str], NodeType],
    *,
    workspace_path: Path,
) -> ControlAPI:
    """Open graph controls over existing system APIs.

    Dependencies:
        Graph:
            Graph structure and mutations.

        Graph UI:
            Active container ID, selection, global node dimensions, and
            collapsed node IDs.

        Nodes:
            Persisted node type, parameter, and title.

        Node Type resolver:
            Resolve and execute node behavior through the public
            ``resolve_node_type`` interface.

    The caller supplies the absolute path of the workspace backing Nodes.
    Control passes it to every node execution context.

    Control does not own the dependencies or their connections.

    Selection validation and directional movement use Visible Graph as the
    single source of visible nodes and edges. Directional movement recalculates
    Logical Layout from that projection.

    Control does not render nodes, calculate physical
    geometry, or route edges.
    """
    ...
