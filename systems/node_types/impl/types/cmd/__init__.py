import subprocess

from systems.node_types.spec.api import NodeContext, NodeRender


class Cmd:
    type = "cmd"

    def render(self, context: NodeContext) -> NodeRender:
        return NodeRender(
            title=context.properties.get("title", ""),
            border_style="solid",
        )

    def execute(self, context: NodeContext) -> None:
        context.nodes.set(context.node_id, "status", "progress")

        try:
            command = context.properties.get("param", "")

            if not command.strip():
                raise ValueError("Empty command")

            subprocess.run(
                command,
                shell=True,
                check=True,
            )

        except BaseException:
            context.nodes.set(context.node_id, "status", "failure")
            raise

        else:
            context.nodes.set(context.node_id, "status", "success")


node_type = Cmd()

__all__ = ["node_type"]
