"""Command-line interface for sloon."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

from sloon_skills import render_skill
from systems.graph_ui import open_graph_ui
from systems.nodes import Nodes, NodesError
from systems.storage import Storage


_COMMANDS = frozenset({
    "batch",
    "connect",
    "control",
    "disconnect",
    "edges",
    "graph",
    "init",
    "inputs",
    "node",
    "outputs",
    "skill",
    "visualize",
})


def _is_named_workspace(path: Path) -> bool:
    return path.name.endswith(".sloon") and not path.name.startswith(".")


def _workspace_path(explicit: Path | None) -> Path:
    if explicit is not None:
        if not _is_named_workspace(explicit):
            raise ValueError("workspace path must name a non-hidden .sloon directory")
        return explicit
    current = Path.cwd()
    if _is_named_workspace(current):
        return current
    raise ValueError(
        "no workspace selected; use --workspace PATH.sloon or run from inside "
        "a named .sloon directory"
    )


def _initialization_path(name: str) -> Path:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("workspace name must not be empty")
    if Path(name).name != name or name in {".", ".."}:
        raise ValueError("workspace name must be a single directory name")
    if name.startswith("."):
        raise ValueError("workspace name must not be hidden")
    directory_name = name if name.endswith(".sloon") else f"{name}.sloon"
    return Path.cwd() / directory_name


def _normalized_argv(argv: list[str] | None) -> list[str]:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        return ["control"]
    if arguments == ["--help"] or arguments == ["-h"]:
        return arguments
    if arguments[0] == "--workspace":
        if len(arguments) == 2:
            return [*arguments, "control"]
        return arguments
    if arguments[0] not in _COMMANDS and not arguments[0].startswith("-"):
        if len(arguments) == 1:
            return ["--workspace", arguments[0], "control"]
    return arguments


def _properties(items: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise ValueError("properties must use KEY=TEXT")
        key, value = item.split("=", 1)
        if not key:
            raise ValueError("property key must not be empty")
        result[key] = value
    return result


def _run_operation(nodes: Nodes, operation: dict[str, Any]) -> Any:
    if not isinstance(operation, dict) or not isinstance(operation.get("op"), str):
        raise ValueError("each batch item must be an object with string 'op'")
    op = operation["op"]
    if op == "create_node":
        fields = operation.get("fields", {})
        if not isinstance(fields, dict):
            raise ValueError("create_node fields must be an object")
        return nodes.create_node(**fields)
    if op == "delete_node":
        nodes.delete_node(operation["node_id"])
        return None
    if op == "set":
        nodes.set(operation["node_id"], operation["key"], operation.get("value"))
        return None
    if op == "delete_property":
        nodes.delete_property(operation["node_id"], operation["key"])
        return None
    if op == "connect":
        nodes.connect(operation["source"], operation["target"])
        return None
    if op == "disconnect":
        nodes.disconnect(operation["source"], operation["target"])
        return None
    raise ValueError(f"unknown batch operation: {op!r}")


def _graph(nodes: Nodes, root: int | None = None) -> dict[str, Any]:
    """Read a complete graph or an outgoing-reachable induced subgraph."""
    with nodes.transaction():
        node_ids = nodes.list_nodes()
        edges = nodes.list_edges()
        if root is None:
            included = set(node_ids)
        else:
            if root not in node_ids:
                # Use the public lookup operation for its standard error.
                nodes.get_all(root)
                raise AssertionError("unreachable")
            outputs: dict[int, list[int]] = {}
            for source, target in edges:
                outputs.setdefault(source, []).append(target)
            included = {root}
            pending = [root]
            while pending:
                for target in outputs.get(pending.pop(), []):
                    if target not in included:
                        included.add(target)
                        pending.append(target)

        selected_ids = [node_id for node_id in node_ids if node_id in included]
        return {
            "nodes": [
                {"id": node_id, "properties": nodes.get_all(node_id)}
                for node_id in selected_ids
            ],
            "edges": [
                edge for edge in edges
                if edge[0] in included and edge[1] in included
            ],
        }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sloon",
        description="Work with explicitly selected named .sloon workspaces.",
        epilog=(
            "Open Control with 'sloon WORKSPACE.sloon', or run 'sloon' from "
            "inside a named .sloon directory."
        ),
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        help="named .sloon directory for a workspace-dependent command",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    initialize = commands.add_parser("init", help="initialize NAME.sloon here")
    initialize.add_argument("name", help="workspace name, with optional .sloon suffix")
    skill = commands.add_parser("skill", help="print instructions for external agents")
    skill.add_argument("skill_name", nargs="?", metavar="{readonly,readwrite}")

    node = commands.add_parser("node")
    node_commands = node.add_subparsers(dest="node_command", required=True)
    create = node_commands.add_parser("create")
    for field in ("type", "title", "param", "status", "note", "tags"):
        create.add_argument(f"--{field}")
    create.add_argument("--weight")
    create.add_argument("--property", action="append", default=[], metavar="KEY=TEXT")
    node_commands.add_parser("list")
    delete = node_commands.add_parser("delete")
    delete.add_argument("node_id", type=int)
    get = node_commands.add_parser("get")
    get.add_argument("node_id", type=int)
    get.add_argument("key")
    get_all = node_commands.add_parser("get-all")
    get_all.add_argument("node_id", type=int)
    set_property = node_commands.add_parser("set")
    set_property.add_argument("node_id", type=int)
    set_property.add_argument("key")
    set_property.add_argument("value")
    remove = node_commands.add_parser("delete-property")
    remove.add_argument("node_id", type=int)
    remove.add_argument("key")

    for name in ("connect", "disconnect"):
        command = commands.add_parser(name)
        command.add_argument("source", type=int)
        command.add_argument("target", type=int)
    for name in ("inputs", "outputs"):
        command = commands.add_parser(name)
        command.add_argument("node_id", type=int)
    commands.add_parser("edges", help="list all directed edges")
    graph = commands.add_parser(
        "graph", help="retrieve the full graph or an outgoing-reachable subgraph"
    )
    graph.add_argument("node_id", nargs="?", type=int)
    batch = commands.add_parser("batch")
    batch.add_argument("json", nargs="?", help="JSON array; stdin when omitted")
    commands.add_parser("control")
    commands.add_parser("visualize")
    return parser


def _execute(arguments: argparse.Namespace) -> Any:
    if arguments.command == "skill":
        if arguments.workspace is not None:
            raise ValueError("--workspace is not used with skill commands")
        return render_skill(arguments.skill_name)

    if arguments.command == "init":
        if arguments.workspace is not None:
            raise ValueError("--workspace is not used with init")
        workspace = _initialization_path(arguments.name)
        storage = Storage.initialize(workspace)
        try:
            connection = storage.connection()
            Nodes(connection)
            open_graph_ui(connection)
            return {"initialized": str(workspace)}
        finally:
            storage.close()

    workspace = _workspace_path(arguments.workspace)
    storage = Storage.open(workspace)
    try:
        connection = storage.connection()
        nodes = Nodes(connection)
        if arguments.command in {"control", "visualize"}:
            graph_ui = open_graph_ui(connection)
            if arguments.command == "control":
                from systems.control.app import main
            else:
                from systems.visualization.app import main
            main(nodes, graph_ui, workspace.resolve())
            return None
        if arguments.command == "node":
            action = arguments.node_command
            if action == "create":
                fields = _properties(arguments.property)
                for field in ("type", "title", "param", "status", "note", "tags", "weight"):
                    value = getattr(arguments, field)
                    if value is not None:
                        fields[field] = value
                return {"node_id": nodes.create_node(**fields)}
            if action == "list":
                return nodes.list_nodes()
            if action == "delete":
                nodes.delete_node(arguments.node_id)
                return None
            if action == "get":
                return nodes.get(arguments.node_id, arguments.key)
            if action == "get-all":
                return nodes.get_all(arguments.node_id)
            if action == "set":
                nodes.set(arguments.node_id, arguments.key, arguments.value)
                return None
            if action == "delete-property":
                nodes.delete_property(arguments.node_id, arguments.key)
                return None
        if arguments.command == "connect":
            nodes.connect(arguments.source, arguments.target)
            return None
        if arguments.command == "disconnect":
            nodes.disconnect(arguments.source, arguments.target)
            return None
        if arguments.command == "inputs":
            return nodes.inputs(arguments.node_id)
        if arguments.command == "outputs":
            return nodes.outputs(arguments.node_id)
        if arguments.command == "edges":
            return nodes.list_edges()
        if arguments.command == "graph":
            return _graph(nodes, arguments.node_id)
        if arguments.command == "batch":
            raw = arguments.json if arguments.json is not None else sys.stdin.read()
            operations = json.loads(raw)
            if not isinstance(operations, list):
                raise ValueError("batch input must be a JSON array")
            with nodes.transaction():
                return [_run_operation(nodes, operation) for operation in operations]
        raise AssertionError("unhandled command")
    finally:
        storage.close()


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(_normalized_argv(argv))
    try:
        result = _execute(arguments)
    except (
        NodesError,
        OSError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
        sqlite3.Error,
    ) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    if arguments.command == "skill":
        print(result)
    elif arguments.command not in {"control", "visualize"}:
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
