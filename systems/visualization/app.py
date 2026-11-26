"""Application startup for the terminal graph viewer."""

from pathlib import Path

from systems.geometry import calculate_geometry
from systems.graph_ui.spec.api import GraphUIAPI
from systems.logical_layout import calculate_layout
from systems.nodes import Nodes
from systems.node_types import resolve_node_type
from systems.visualization import measure_node_sizes, open_visualization
from systems.visible_graph import calculate_visible_graph


def main(nodes_api: Nodes, graph_ui: GraphUIAPI, workspace_path: Path) -> None:
    visible_graph = calculate_visible_graph(
        nodes_api.list_nodes(),
        nodes_api.list_edges(),
        graph_ui.get_collapsed_node_ids(),
    )
    nodes = list(visible_graph.nodes)
    edges = list(visible_graph.edges)
    node_width = graph_ui.get_node_width()
    node_height = graph_ui.get_node_height()
    show_node_ids = graph_ui.get_show_node_ids()
    weights = {
        node_id: int(properties.get("weight", "0"))
        for node_id, properties in nodes_api.get_many(nodes, ["weight"]).items()
    }
    logical_layout = calculate_layout(nodes, edges, weights)
    node_sizes = measure_node_sizes(
        nodes,
        nodes_api,
        resolve_node_type,
        node_width,
        node_height,
        show_node_ids,
    )
    occupied_width = (
        next(iter(node_sizes.values())).width if node_sizes else node_width
    )
    geometry = calculate_geometry(
        logical_layout.layout,
        node_sizes,
        node_width=occupied_width,
    )
    open_visualization(
        nodes_api,
        graph_ui,
        resolve_node_type,
        logical_layout,
        geometry,
        workspace_path=workspace_path,
    ).run()
