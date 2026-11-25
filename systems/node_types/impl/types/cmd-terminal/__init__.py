import subprocess

from systems.node_types.spec.api import NodeContext, NodeRender


_RUN_IN_TERMINAL_SCRIPT = """
on run argv
    tell application "Terminal"
        activate
        do script (item 1 of argv)
    end tell
end run
"""


class CmdTerminal:
    type = "cmd-terminal"

    def render(self, context: NodeContext) -> NodeRender:
        return NodeRender(
            title=context.properties.get("title", ""),
            border_style="solid",
        )

    def execute(self, context: NodeContext) -> None:
        command = context.properties.get("param", "")

        if not command.strip():
            raise ValueError("Empty command")

        subprocess.run(
            ["osascript", "-e", _RUN_IN_TERMINAL_SCRIPT, command],
            check=True,
        )


node_type = CmdTerminal()

__all__ = ["node_type"]
