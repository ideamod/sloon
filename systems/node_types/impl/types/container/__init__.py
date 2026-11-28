"""Container node presentation."""

from ....spec.api import NodeContext, NodeRender


class _ContainerNodeType:
    type = "container"

    def render(self, context: NodeContext) -> NodeRender:
        return NodeRender(title="Container", border_style="double")

    def execute(self, context: NodeContext) -> None:
        return None


node_type = _ContainerNodeType()

__all__ = ["node_type"]
