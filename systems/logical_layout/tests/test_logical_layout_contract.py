"""Contract tests for deterministic logical graph layout."""

import unittest

from systems.logical_layout import calculate_layout


def _columns(layout: object) -> tuple[tuple[tuple[int, ...], ...], ...]:
    return tuple(component.columns for component in layout.components)


def _navigation_fixture():
    return calculate_layout(
        list(range(1, 11)),
        [
            (1, 3),
            (1, 4),
            (2, 4),
            (5, 7),
            (6, 7),
            (8, 9),
            (9, 10),
        ],
    )


class LogicalLayoutContractTests(unittest.TestCase):
    def test_empty_graph_has_no_components(self) -> None:
        result = calculate_layout([], [])

        self.assertEqual(result.layout.components, ())

    def test_isolated_nodes_are_ordered_components(self) -> None:
        result = calculate_layout([30, 10, 20], [])

        self.assertEqual(
            _columns(result.layout),
            (((30,),), ((10,),), ((20,),)),
        )
        self.assertEqual(result.get_component(30), 0)
        self.assertEqual(result.get_component(10), 1)
        self.assertEqual(result.get_component(20), 2)
        for node_id in (30, 10, 20):
            self.assertEqual(result.get_column(node_id), 0)
            self.assertEqual(result.get_position(node_id), 0)

    def test_orders_disconnected_root_nodes_by_descending_weight(self) -> None:
        result = calculate_layout(
            [30, 10, 20],
            [],
            {30: 0, 10: -4, 20: 7},
        )

        self.assertEqual(_columns(result.layout), (((20,),), ((30,),), ((10,),)))

    def test_reorders_disconnected_roots_after_weight_changes(self) -> None:
        nodes = [1, 2, 3]

        first = calculate_layout(nodes, [], {1: 3, 2: 2, 3: 1})
        second = calculate_layout(nodes, [], {1: -1, 2: 2, 3: 5})

        self.assertEqual(_columns(first.layout), (((1,),), ((2,),), ((3,),)))
        self.assertEqual(_columns(second.layout), (((3,),), ((2,),), ((1,),)))

    def test_equal_weight_roots_preserve_deterministic_input_order(self) -> None:
        result = calculate_layout(
            [30, 10, 20],
            [],
            {30: 5, 10: 5, 20: 5},
        )

        self.assertEqual(_columns(result.layout), (((30,),), ((10,),), ((20,),)))

    def test_uses_longest_path_columns_for_branching_graphs(self) -> None:
        result = calculate_layout(
            [1, 2, 3, 4, 5, 6],
            [
                (1, 3),
                (1, 4),
                (2, 4),
                (3, 5),
                (4, 5),
                (1, 5),
                (3, 6),
            ],
        )

        self.assertEqual(
            _columns(result.layout),
            (((1, 2), (3, 4), (5, 6)),),
        )
        self.assertEqual(result.get_column(1), 0)
        self.assertEqual(result.get_column(4), 1)
        self.assertEqual(result.get_column(5), 2)
        self.assertEqual(result.get_position(2), 1)
        self.assertEqual(result.get_position(4), 1)
        self.assertEqual(result.get_position(6), 1)

    def test_shifts_root_next_to_a_deep_target_when_possible(self) -> None:
        result = calculate_layout(
            [19, 20, 21, 25, 26],
            [
                (19, 20),
                (20, 25),
                (21, 19),
                (26, 25),
            ],
        )

        self.assertEqual(
            _columns(result.layout),
            (((21,), (19,), (20, 26), (25,)),),
        )
        self.assertEqual(result.get_column(26), 2)

    def test_orders_weak_components_by_first_input_occurrence(self) -> None:
        result = calculate_layout(
            [20, 99, 10, 30, 40],
            [(10, 20), (30, 40)],
        )

        self.assertEqual(
            _columns(result.layout),
            (
                ((10,), (20,)),
                ((99,), ()),
                ((30,), (40,)),
            ),
        )
        self.assertEqual(result.get_component(20), 0)
        self.assertEqual(result.get_component(10), 0)
        self.assertEqual(result.get_component(99), 1)
        self.assertEqual(result.get_component(30), 2)
        self.assertEqual(result.get_component(40), 2)

    def test_orders_multiple_disconnected_components_by_root_weight(self) -> None:
        result = calculate_layout(
            [1, 3, 5, 2, 4],
            [(1, 2), (3, 4)],
            {1: -2, 2: 100, 3: 8, 4: -100, 5: 3},
        )

        self.assertEqual(
            _columns(result.layout),
            (
                ((3,), (4,)),
                ((5,), ()),
                ((1,), (2,)),
            ),
        )

    def test_preserves_input_order_within_each_column(self) -> None:
        result = calculate_layout(
            [30, 10, 20, 50, 40],
            [
                (30, 50),
                (10, 50),
                (20, 50),
                (30, 40),
                (10, 40),
                (20, 40),
            ],
        )

        self.assertEqual(
            _columns(result.layout),
            (((30, 10, 20), (50, 40)),),
        )

    def test_orders_each_column_by_descending_weight_with_stable_ties(self) -> None:
        result = calculate_layout(
            [30, 10, 20, 50, 40],
            [
                (30, 50), (10, 50), (20, 50),
                (30, 40), (10, 40), (20, 40),
            ],
            {30: -2, 10: 7, 20: 7, 50: 0, 40: 3},
        )

        self.assertEqual(_columns(result.layout), (((10, 20, 30), (40, 50)),))

    def test_component_ordering_preserves_internal_node_weight_order(self) -> None:
        result = calculate_layout(
            [1, 2, 3, 4, 5, 6],
            [(1, 3), (2, 3), (4, 6), (5, 6)],
            {1: 2, 2: 7, 3: 0, 4: 10, 5: 4, 6: 0},
        )

        self.assertEqual(
            _columns(result.layout),
            (
                ((4, 5), (6,)),
                ((2, 1), (3,)),
            ),
        )

    def test_weight_does_not_change_columns_or_topology(self) -> None:
        nodes = [1, 2, 3, 4]
        edges = [(1, 3), (2, 3), (3, 4)]
        unweighted = calculate_layout(nodes, edges)
        weighted = calculate_layout(nodes, edges, {1: -100, 2: 100, 3: 5, 4: 9})

        for node_id in nodes:
            self.assertEqual(weighted.get_column(node_id), unweighted.get_column(node_id))
        self.assertEqual({node for component in weighted.layout.components for column in component.columns for node in column}, set(nodes))

    def test_rejects_invalid_weight_mapping(self) -> None:
        for weights in ({2: 1}, {1: True}, {1: 1.5}, {1: "2"}, [(1, 2)]):
            with self.subTest(weights=weights):
                with self.assertRaises(ValueError):
                    calculate_layout([1], [], weights)  # type: ignore[arg-type]

    def test_preserves_empty_columns_in_shallower_components(self) -> None:
        result = calculate_layout(
            [90, 1, 2, 3],
            [(1, 2), (2, 3)],
        )

        self.assertEqual(
            _columns(result.layout),
            (
                ((90,), (), ()),
                ((1,), (2,), (3,)),
            ),
        )

    def test_navigates_left_and_right_by_global_logical_row(self) -> None:
        result = _navigation_fixture()

        self.assertEqual(result.right(1), 3)
        self.assertEqual(result.left(3), 1)
        self.assertEqual(result.right(2), 4)
        self.assertEqual(result.left(7), 5)
        self.assertEqual(result.right(6), 7)  # Equal distance prefers upper.
        self.assertEqual(result.right(4), 10)  # Crosses component boundaries.

    def test_navigates_up_and_down_across_components(self) -> None:
        result = _navigation_fixture()

        self.assertEqual(result.down(1), 2)
        self.assertEqual(result.up(2), 1)
        self.assertEqual(result.down(4), 7)
        self.assertEqual(result.up(7), 4)
        self.assertEqual(result.down(7), 9)
        self.assertEqual(result.up(9), 7)

    def test_navigation_returns_none_at_boundaries(self) -> None:
        result = _navigation_fixture()

        self.assertIsNone(result.left(1))
        self.assertIsNone(result.right(10))
        self.assertIsNone(result.up(1))
        self.assertIsNone(result.down(8))
        self.assertIsNone(result.up(10))
        self.assertIsNone(result.down(10))

    def test_all_queries_reject_unknown_node_ids(self) -> None:
        result = calculate_layout([1], [])

        queries = (
            result.get_component,
            result.get_column,
            result.get_position,
            result.left,
            result.right,
            result.up,
            result.down,
        )
        for query in queries:
            with self.subTest(query=query.__name__):
                with self.assertRaises(KeyError):
                    query(999)

    def test_rejects_duplicate_nodes(self) -> None:
        with self.assertRaises(ValueError):
            calculate_layout([1, 2, 1], [])

    def test_rejects_missing_edge_endpoints(self) -> None:
        for edges in ([(1, 2)], [(2, 1)]):
            with self.subTest(edges=edges):
                with self.assertRaises(ValueError):
                    calculate_layout([1], edges)

    def test_rejects_self_loops(self) -> None:
        with self.assertRaises(ValueError):
            calculate_layout([1], [(1, 1)])

    def test_rejects_cycles(self) -> None:
        with self.assertRaises(ValueError):
            calculate_layout([1, 2, 3], [(1, 2), (2, 3), (3, 1)])

    def test_rejects_malformed_input_structures(self) -> None:
        malformed_inputs = (
            ((1, 2), []),
            ([1, 2], ((1, 2),)),
            ([1, "two"], []),
            ([1, 2], [[1, 2]]),
            ([1, 2], [(1,)]),
            ([1, 2], [(1, 2, 3)]),
            ([1, 2], [(1, "two")]),
        )
        for nodes, edges in malformed_inputs:
            with self.subTest(nodes=nodes, edges=edges):
                with self.assertRaises(ValueError):
                    calculate_layout(nodes, edges)

    def test_repeated_calculations_are_deterministic(self) -> None:
        nodes = [1, 2, 3, 4, 5]
        edges = [(1, 3), (2, 3), (3, 4), (3, 5)]

        first = calculate_layout(nodes, edges)
        second = calculate_layout(list(nodes), list(edges))

        self.assertEqual(first.layout, second.layout)
        for node_id in nodes:
            first_queries = (
                first.get_component(node_id),
                first.get_column(node_id),
                first.get_position(node_id),
                first.left(node_id),
                first.right(node_id),
                first.up(node_id),
                first.down(node_id),
            )
            second_queries = (
                second.get_component(node_id),
                second.get_column(node_id),
                second.get_position(node_id),
                second.left(node_id),
                second.right(node_id),
                second.up(node_id),
                second.down(node_id),
            )
            self.assertEqual(first_queries, second_queries)


if __name__ == "__main__":
    unittest.main()
