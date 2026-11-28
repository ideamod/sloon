from systems.visible_graph import calculate_reveal_plan, calculate_visible_graph
from systems.visible_graph import filter_container_graph


def test_visibility_filters_membership_before_collapse_and_reveal():
    nodes = [1, 2, 3, 4, 5, 6, 7, 8, 9]
    edges = [(1, 3), (2, 3), (3, 4), (3, 5), (4, 2), (6, 7), (8, 4)]
    properties = {
        1: {"type": "container"},
        2: {"type": "container", "container_id": ""},
        3: {"container_id": "1"},
        4: {"container_id": "1"},
        5: {"type": "container", "container_id": "1"},
        6: {"container_id": "5"},
        7: {"container_id": "5"},
        8: {"container_id": "2"},
    }

    def project(active):
        members, internal_edges, effective = filter_container_graph(
            nodes, edges, properties, active,
        )
        assert effective == active
        return calculate_visible_graph(members, internal_edges, {3, 6})

    assert project("").nodes == (1, 2, 9)
    assert project("1").nodes == (3,)
    assert project("2").nodes == (8,)
    assert project("5").nodes == (6,)
    assert project("1").edges == ()

    members, internal_edges, _ = filter_container_graph(nodes, edges, properties, "1")
    assert calculate_reveal_plan(members, internal_edges, {3, 6}, 4) == (3,)
    assert calculate_reveal_plan(members, internal_edges, {3, 6}, 8) is None
    assert calculate_visible_graph(members, internal_edges, set()).edges == ((3, 4), (3, 5))


def test_invalid_active_ids_and_ancestry_fall_back_to_root():
    properties = {
        2: {"container_id": "99"},
        3: {"type": "container", "container_id": "4"},
        4: {"type": "container", "container_id": "3"},
        5: {"type": "container", "container_id": "2"},
        6: {"type": "container", "container_id": "99"},
        7: {"type": "container", "container_id": "7"},
    }
    for invalid in ("unknown", "99", "2", "3", "4", "5", "6", "7", "01"):
        assert filter_container_graph(list(range(1, 8)), [], properties, invalid) == (
            [1], [], "",
        )
