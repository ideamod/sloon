"""Automatic node type resolution."""

from collections.abc import Iterator
import importlib
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import pkgutil
import sys
from types import ModuleType

from ..spec.api import NodeType
from . import types as types_package


def _load_user_package(directory: Path) -> ModuleType:
    # Keep user packages separate from built-ins even when directory names match.
    name = f"{__package__}._user_type_{directory.name}"
    if name in sys.modules:
        return sys.modules[name]

    spec = spec_from_file_location(name, directory / "__init__.py")
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load node type package {directory}")
    module = module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[name]
        raise
    return module


def _type_packages() -> Iterator[ModuleType]:
    for module_info in pkgutil.iter_modules(types_package.__path__):
        if module_info.ispkg:
            yield importlib.import_module(f"{types_package.__name__}.{module_info.name}")

    user_types = Path.home() / ".sloon" / "types"
    for module_info in pkgutil.iter_modules([str(user_types)]):
        if module_info.ispkg:
            yield _load_user_package(user_types / module_info.name)


def _discover_node_types() -> dict[str, NodeType]:
    discovered: dict[str, NodeType] = {}

    for module in _type_packages():
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
