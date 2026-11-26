from types import SimpleNamespace
from unittest.mock import Mock

from systems.visualization import app


def test_main_defaults_missing_weight_to_zero(monkeypatch, tmp_path):
    nodes = Mock()
    nodes.list_nodes.return_value = [1]
    nodes.list_edges.return_value = []
    nodes.get_many.return_value = {1: {}}
    graph_ui = Mock()
    graph_ui.get_collapsed_node_ids.return_value = set()
    graph_ui.get_node_width.return_value = 10
    graph_ui.get_node_height.return_value = 3
    graph_ui.get_show_node_ids.return_value = False

    monkeypatch.setattr(
        app,
        "calculate_visible_graph",
        lambda node_ids, edges, collapsed: SimpleNamespace(nodes=(1,), edges=()),
    )
    calculate_layout = Mock(return_value=SimpleNamespace(layout={}))
    monkeypatch.setattr(app, "calculate_layout", calculate_layout)
    monkeypatch.setattr(app, "measure_node_sizes", Mock(return_value={}))
    monkeypatch.setattr(app, "calculate_geometry", Mock(return_value={}))
    viewer = Mock()
    monkeypatch.setattr(app, "open_visualization", Mock(return_value=viewer))

    app.main(nodes, graph_ui, tmp_path)

    calculate_layout.assert_called_once_with([1], [], {1: 0})
    viewer.run.assert_called_once_with()
