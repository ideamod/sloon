"""File node type implementation."""

from pathlib import Path
import shlex
import subprocess

from ....spec.api import NodeContext, NodeRender


_EDITABLE_SUFFIXES = {".md", ".py", ".txt"}
_OPEN_IN_TERMINAL_SCRIPT = """
on run argv
    tell application "Terminal"
        activate
        do script (item 1 of argv)
    end tell
end run
"""


class _FileNodeType:
    type = "file"

    def render(self, context: NodeContext) -> NodeRender:
        return NodeRender(title=context.nodes.get(context.node_id, "title", ""), border_style="solid")

    def execute(self, context: NodeContext) -> None:
        path = Path(context.nodes.get(context.node_id, "param", ""))
        if not path.is_file():
            raise ValueError(f"file does not exist: {str(path)!r}")
        if path.suffix.lower() not in _EDITABLE_SUFFIXES:
            raise ValueError(f"unsupported file type: {path.suffix!r}")

        command = f"vim -- {shlex.quote(str(path.resolve()))}"
        subprocess.run(
            ["osascript", "-e", _OPEN_IN_TERMINAL_SCRIPT, command],
            check=True,
        )


node_type = _FileNodeType()

__all__ = ["node_type"]
