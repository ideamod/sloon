"""Public immutable result type for Visible Graph."""

from dataclasses import dataclass


@dataclass(frozen=True)
class VisibleGraph:
    """The visible projection of a validated directed acyclic graph.

    Nodes and edges retain their relative order from the supplied graph.
    """

    nodes: tuple[int, ...]
    edges: tuple[tuple[int, int], ...]
