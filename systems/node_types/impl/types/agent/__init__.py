"""Agent node type implementation."""

from ....spec.api import NodeContext, NodeRender


class _AgentNodeType:
    type = "agent"

    def render(self, context: NodeContext) -> NodeRender:
        return NodeRender(title=context.nodes.get(context.node_id, "title", ""), border_style="solid")

    def execute(self, context: NodeContext) -> None:
        raise NotImplementedError


node_type = _AgentNodeType()

__all__ = ["node_type"]
