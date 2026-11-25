"""Void node type scaffold."""

from ....spec.api import NodeContext, NodeRender


class _VoidNodeType:
    type = "void"

    def render(self, context: NodeContext) -> NodeRender:
        return NodeRender(title="", border_style="solid")

    def execute(self, context: NodeContext) -> None:
        return None


node_type = _VoidNodeType()

__all__ = ["node_type"]
