"""Public API contract for the Node Types system.

Node Types provides extensible node behavior through independently
implemented node types.

Each type implements a common protocol and is discovered automatically
by the resolver.

Node Types does not own node, edge, or property persistence.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from systems.nodes import Nodes


@dataclass(frozen=True)
class NodeRender:
    """Presentation parameters independent of the UI framework.

    Attributes:
        title:
            Text displayed as the node title.

        border_style:
            Visual border style. Supported values:
            "solid" and "dashed".
    """

    title: str
    border_style: str = "solid"


@dataclass(frozen=True)
class NodeContext:
    """Context passed to node type operations.

    Attributes:
        node_id:
            Identifier of the current graph node.

        workspace_path:
            Absolute path to the current workspace selected by the application.

        properties:
            Snapshot of the textual properties supplied by the application.

        nodes:
            Full public Nodes API. Node types may perform explicit mutations
            during execution. Rendering remains read-only; execution does not
            implicitly change status.

    The context is immutable as a container, but the APIs referenced
    by it may perform mutations.

    Node Types does not create or own these API instances.
    """

    node_id: int
    workspace_path: Path
    properties: dict[str, str]
    nodes: Nodes


class NodeType(Protocol):
    """Protocol implemented by every node type."""

    type: str

    def render(self, context: NodeContext) -> NodeRender:
        """Return presentation parameters for the current node.

        Must not modify Nodes.

        Must not execute node behavior.

        May read Nodes through context.
        """
        ...

    def execute(self, context: NodeContext) -> None:
        """Execute type-specific behavior.

        May read or modify Nodes through context.

        Execution is explicitly initiated by the caller.
        """
        ...


class NodePresentationError(ValueError):
    """Raised when a node cannot be presented correctly."""


# Built-in Copy presentation
#
# Copy interprets param as a positive ASCII decimal node ID. Leading zeroes
# are allowed. Copy delegates existence checks to Nodes for every converted
# positive ID, independent of the storage backend. An absent, malformed,
# unconvertible, nonexistent, or cyclic target ends traversal. Copy returns a
# dashed border and the first non-empty title found, starting with its own
# title, or an empty title if none was found.


def resolve_node_type(type_name: str) -> NodeType:
    """Resolve a node type by its string identifier.

    Discovery:
        Discover immediate Python packages in systems/node_types/impl/types/
        and ~/.sloon/types/. A missing user directory is allowed.

        Each package exports an object named `node_type` from its __init__.py.
        The object implements the NodeType protocol and its `type` attribute
        determines its identifier independently of the package name. Packages
        can contain supporting modules and resources and use relative imports.

        User packages require no registration, repository changes, or
        reinstallation. Changes take effect on the next application launch.

    Matching:
        Compare type identifiers exactly, case-sensitively.

    Fallback:
        If no matching implementation exists, return the Void type.

    Errors:
        Duplicate identifiers within or across discovery locations and
        invalid implementations are configuration errors.

    Side effects:
        Resolution must not call render() or execute().
        Resolution must not modify Nodes.

    Caching:
        Implementations may be discovered once and cached for
        subsequent resolutions.
    """
    ...


"""Public API contract for the Node Types system.

Node Types provides extensible node behavior through independently
implemented node types.

Testing Contract
----------------
The Node Types contract test suite must:

- Test shared infrastructure: resolver, discovery, protocol,
  context, fallback, and error handling.
- Test the behavior of only three built-in types:
  void, text, and copy.
- Not require dedicated behavioral tests for file, link,
  agent, or any future custom types.
- Allow custom types to maintain independent test suites.
"""
