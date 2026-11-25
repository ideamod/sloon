"""Automatic node type resolution."""

import importlib
import pkgutil

from ..spec.api import NodeType
from . import types as types_package


def _discover_node_types() -> dict[str, NodeType]:
    discovered: dict[str, NodeType] = {}

    for module_info in pkgutil.iter_modules(types_package.__path__):
        if not module_info.ispkg:
            continue
        module = importlib.import_module(
            f"{types_package.__name__}.{module_info.name}"
        )
        try:
            implementation = module.node_type
        except AttributeError as error:
            raise TypeError(
                f"node type package {module.__name__!r} does not export node_type"
            ) from error

        identifier = getattr(implementation, "type", None)
        if not isinstance(identifier, str) or not identifier:
            raise TypeError(
                f"invalid node type identifier in {module.__name__!r}: "
                f"{identifier!r}"
            )
        if not callable(getattr(implementation, "render", None)):
            raise TypeError(
                f"node type {identifier!r} does not implement render(context)"
            )
        if not callable(getattr(implementation, "execute", None)):
            raise TypeError(
                f"node type {identifier!r} does not implement execute(context)"
            )
        if identifier in discovered:
            raise ValueError(f"duplicate node type identifier: {identifier!r}")
        discovered[identifier] = implementation

    return discovered


def resolve_node_type(type_name: str) -> NodeType:
    """Resolve the node type with the requested identifier."""
    discovered = _discover_node_types()
    if type_name in discovered:
        return discovered[type_name]
    try:
        return discovered["void"]
    except KeyError as error:
        raise RuntimeError("Void node type is not available") from error
