"""Public entry point for persistent node and edge data."""

from .impl.sqlite import Nodes
from .spec.api import (
    NodeNotFoundError,
    NodesError,
    PropertyNotFoundError,
)

__all__ = [
    "NodeNotFoundError",
    "Nodes",
    "NodesError",
    "PropertyNotFoundError",
]
