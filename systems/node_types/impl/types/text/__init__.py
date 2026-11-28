"""Text node type scaffold."""

from ....spec.api import NodeContext, NodeRender


class _TextNodeType:
    type = "text"

    def render(self, context: NodeContext) -> NodeRender:
        return NodeRender(title=context.nodes.get(context.node_id, "title", ""), border_style="solid")

    def execute(self, context: NodeContext) -> None:
        return None


node_type = _TextNodeType()

__all__ = ["node_type"]
