"""Copy node type implementation."""

from ....spec.api import NodeContext, NodePresentationError, NodeRender


class _CopyNodeType:
    type = "copy"

    def render(self, context: NodeContext) -> NodeRender:
        if not context.nodes.node_exists(context.node_id):
            raise NodePresentationError(
                f"graph node does not exist: {context.node_id!r}"
            )

        current_node_id = context.node_id
        properties = context.properties
        title = properties.get("title", "")
        visited = {context.node_id}

        while properties.get("type", "void") == "copy":
            try:
                target_node_id = self._target_node_id(
                    current_node_id, properties.get("param", "")
                )
            except NodePresentationError:
                return NodeRender(title=title, border_style="dashed")
            if target_node_id in visited:
                return NodeRender(title=title, border_style="dashed")
            if not context.nodes.node_exists(target_node_id):
                return NodeRender(title=title, border_style="dashed")

            visited.add(target_node_id)
            current_node_id = target_node_id
            properties = context.nodes.get_all(target_node_id)
            if not title:
                title = properties.get("title", "")

        return NodeRender(title=title, border_style="dashed")

    def execute(self, context: NodeContext) -> None:
        return None

    @staticmethod
    def _target_node_id(node_id: int, param: str) -> int:
        digits = param.lstrip("0")
        if digits.isascii() and digits.isdigit():
            try:
                return int(digits)
            except ValueError:
                pass
        raise NodePresentationError(
            f"copy assignment for node {node_id!r} has an invalid "
            f"target node ID: {param!r}"
        )


node_type = _CopyNodeType()

__all__ = ["node_type"]
