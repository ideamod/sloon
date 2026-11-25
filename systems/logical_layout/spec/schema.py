from dataclasses import dataclass


@dataclass(frozen=True)
class ComponentLayout:
    """Columns of one weakly connected component.

    Column indices are global. Empty columns are preserved.
    Node IDs within each column are ordered top to bottom.
    """

    columns: tuple[tuple[int, ...], ...]


@dataclass(frozen=True)
class LogicalLayout:
    """Logical arrangement of a directed graph.

    Components are ordered top to bottom.
    Columns are ordered left to right, starting at zero.
    Every input node appears exactly once.
    """

    components: tuple[ComponentLayout, ...]
