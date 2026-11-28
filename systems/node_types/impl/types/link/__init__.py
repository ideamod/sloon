"""Link node type implementation."""

from ....spec.api import NodeContext, NodeRender


class _LinkNodeType:
    type = "link"

    def render(self, context: NodeContext) -> NodeRender:
        return NodeRender(title=context.nodes.get(context.node_id, "title", ""), border_style="solid")

    def execute(self, context: NodeContext) -> None:
        raise NotImplementedError


node_type = _LinkNodeType()

__all__ = ["node_type"]
