"""Contract tests for pure visible graph projection."""

import unittest
from dataclasses import FrozenInstanceError

from systems.visible_graph import (
    VisibleGraph,
    calculate_reveal_plan,
    calculate_visible_graph,
)


class VisibleGraphContractTests(unittest.TestCase):
    def test_reveal_plan_is_empty_for_already_visible_target(self) -> None:
        self.assertEqual(
            calculate_reveal_plan(
                [1, 2, 3], [(1, 2), (2, 3)], {999}, 3
            ),
            (),
        )

    def test_reveal_plan_returns_none_for_missing_target(self) -> None:
        self.assertIsNone(calculate_reveal_plan([1, 2], [(1, 2)], {1}, 999))

    def test_reveal_plan_returns_single_collapsed_blocker(self) -> None:
        self.assertEqual(
            calculate_reveal_plan([1, 2, 3], [(1, 2), (2, 3)], {2}, 3),
            (2,),
        )

    def test_reveal_plan_returns_serial_blockers_in_root_order(self) -> None:
        self.assertEqual(
            calculate_reveal_plan(
                [1, 2, 3, 4],
                [(1, 2), (2, 3), (3, 4)],
                {1, 3},
                4,
            ),
            (1, 3),
        )

    def test_reveal_plan_chooses_path_with_fewer_expansions(self) -> None:
        self.assertEqual(
            calculate_reveal_plan(
                [1, 2, 3, 4, 6],
                [(1, 2), (2, 3), (3, 6), (1, 4), (4, 6)],
                {2, 3, 4},
                6,
            ),
            (4,),
        )

    def test_reveal_plan_breaks_equal_cost_ties_by_stable_edge_order(self) -> None:
        self.assertEqual(
            calculate_reveal_plan(
                [1, 2, 3, 4],
                [(1, 3), (1, 2), (3, 4), (2, 4)],
                {2, 3},
                4,
            ),
            (3,),
        )

    def test_reveal_plan_shared_downstream_uses_existing_open_path(self) -> None:
        self.assertEqual(
            calculate_reveal_plan(
                [1, 2, 3, 4, 5],
                [(1, 2), (1, 3), (2, 4), (3, 4), (4, 5)],
                {2},
                5,
            ),
            (),
        )

    def test_reveal_plan_excludes_collapsed_target_itself(self) -> None:
        self.assertEqual(
            calculate_reveal_plan([1, 2, 3], [(1, 2), (2, 3)], {3}, 3),
            (),
        )

    def test_reveal_plan_ignores_stale_collapsed_ids_and_preserves_inputs(self) -> None:
        nodes = [1, 2, 3]
        edges = [(1, 2), (2, 3)]
        collapsed = {2, 999}

        result = calculate_reveal_plan(nodes, edges, collapsed, 3)

        self.assertEqual(result, (2,))
        self.assertEqual(nodes, [1, 2, 3])
        self.assertEqual(edges, [(1, 2), (2, 3)])
        self.assertEqual(collapsed, {2, 999})

    def test_reveal_plan_rejects_cycles_and_self_loops(self) -> None:
        for nodes, edges, target in (
            ([1], [(1, 1)], 1),
            ([1, 2], [(1, 2), (2, 1)], 2),
        ):
            with self.subTest(edges=edges):
                with self.assertRaises(ValueError):
                    calculate_reveal_plan(nodes, edges, set(), target)

    def test_reveal_plan_rejects_invalid_target_id(self) -> None:
        for target in (True, 1.5, "1", None):
            with self.subTest(target=target):
                with self.assertRaises(ValueError):
                    calculate_reveal_plan([1], [], set(), target)

    def test_empty_graph(self) -> None:
        self.assertEqual(
            calculate_visible_graph([], [], set()),
            VisibleGraph(nodes=(), edges=()),
        )

    def test_graph_without_collapsed_nodes_is_unchanged(self) -> None:
        nodes = [4, 1, 3, 2]
        edges = [(4, 3), (1, 3), (3, 2)]

        result = calculate_visible_graph(nodes, edges, set())

        self.assertEqual(result, VisibleGraph(tuple(nodes), tuple(edges)))

    def test_collapsed_middle_of_single_chain_hides_descendants(self) -> None:
        result = calculate_visible_graph(
            [1, 2, 3, 4],
            [(1, 2), (2, 3), (3, 4)],
            {2},
        )

        self.assertEqual(result.nodes, (1, 2))
        self.assertEqual(result.edges, ((1, 2),))

    def test_collapse_recursively_hides_multiple_descendants(self) -> None:
        result = calculate_visible_graph(
            [1, 2, 3, 4, 5, 6],
            [(1, 2), (2, 3), (2, 4), (3, 5), (4, 6)],
            {2},
        )

        self.assertEqual(result, VisibleGraph((1, 2), ((1, 2),)))

    def test_multiple_independent_components_are_traversed(self) -> None:
        result = calculate_visible_graph(
            [10, 1, 11, 2, 20],
            [(10, 11), (1, 2)],
            {10},
        )

        self.assertEqual(result.nodes, (10, 1, 2, 20))
        self.assertEqual(result.edges, ((1, 2),))

    def test_shared_descendant_remains_visible_through_open_path(self) -> None:
        result = calculate_visible_graph(
            [1, 2, 3, 4, 5],
            [(1, 2), (1, 3), (2, 4), (3, 4), (4, 5)],
            {2},
        )

        self.assertEqual(result.nodes, (1, 2, 3, 4, 5))
        self.assertEqual(
            result.edges,
            ((1, 2), (1, 3), (3, 4), (4, 5)),
        )

    def test_nested_collapsed_nodes_behind_ancestor_remain_hidden(self) -> None:
        result = calculate_visible_graph(
            [1, 2, 3, 4, 5],
            [(1, 2), (2, 3), (3, 4), (4, 5)],
            {2, 4},
        )

        self.assertEqual(result, VisibleGraph((1, 2), ((1, 2),)))

    def test_collapsed_root_remains_visible_and_stops_its_component(self) -> None:
        result = calculate_visible_graph(
            [1, 2, 3, 4],
            [(1, 2), (3, 4)],
            {1},
        )

        self.assertEqual(result.nodes, (1, 3, 4))
        self.assertEqual(result.edges, ((3, 4),))

    def test_collapsed_leaf_has_no_effect(self) -> None:
        result = calculate_visible_graph(
            [1, 2, 3],
            [(1, 2), (2, 3)],
            {3},
        )

        self.assertEqual(
            result,
            VisibleGraph((1, 2, 3), ((1, 2), (2, 3))),
        )

    def test_unknown_collapsed_ids_are_ignored(self) -> None:
        collapsed = {999, -10}

        result = calculate_visible_graph([1, 2], [(1, 2)], collapsed)

        self.assertEqual(result, VisibleGraph((1, 2), ((1, 2),)))
        self.assertEqual(collapsed, {999, -10})

    def test_preserves_input_order_not_traversal_order(self) -> None:
        nodes = [20, 10, 40, 30, 50]
        edges = [(10, 30), (20, 40), (30, 50), (40, 50)]

        result = calculate_visible_graph(nodes, edges, {10})

        self.assertEqual(result.nodes, (20, 10, 40, 50))
        self.assertEqual(result.edges, ((20, 40), (40, 50)))

    def test_repeated_calculations_are_deterministic(self) -> None:
        nodes = [1, 2, 3, 4]
        edges = [(1, 2), (1, 3), (2, 4), (3, 4)]
        collapsed = {2}

        first = calculate_visible_graph(nodes, edges, collapsed)
        second = calculate_visible_graph(list(nodes), list(edges), set(collapsed))

        self.assertEqual(first, second)

    def test_inputs_are_not_modified(self) -> None:
        nodes = [1, 2, 3, 4]
        edges = [(1, 2), (1, 3), (2, 4), (3, 4)]
        collapsed = {2}
        original_nodes = list(nodes)
        original_edges = list(edges)
        original_collapsed = set(collapsed)

        calculate_visible_graph(nodes, edges, collapsed)

        self.assertEqual(nodes, original_nodes)
        self.assertEqual(edges, original_edges)
        self.assertEqual(collapsed, original_collapsed)

    def test_result_is_frozen(self) -> None:
        result = calculate_visible_graph([1], [], set())

        with self.assertRaises(FrozenInstanceError):
            result.nodes = ()

    def test_rejects_malformed_nodes(self) -> None:
        invalid_nodes = (
            (1, 2),
            [1, 1],
            [1, "2"],
            [True],
        )
        for nodes in invalid_nodes:
            with self.subTest(nodes=nodes):
                with self.assertRaises(ValueError):
                    calculate_visible_graph(nodes, [], set())

    def test_rejects_malformed_edges(self) -> None:
        invalid_edges = (
            ((1, 2),),
            [[1, 2]],
            [(1,)],
            [(1, 2, 3)],
            [(1, "2")],
            [(True, 2)],
        )
        for edges in invalid_edges:
            with self.subTest(edges=edges):
                with self.assertRaises(ValueError):
                    calculate_visible_graph([1, 2, 3], edges, set())

    def test_rejects_unknown_edge_endpoints(self) -> None:
        for edges in ([(1, 2)], [(2, 1)]):
            with self.subTest(edges=edges):
                with self.assertRaises(ValueError):
                    calculate_visible_graph([1], edges, set())

    def test_rejects_duplicate_edges(self) -> None:
        with self.assertRaises(ValueError):
            calculate_visible_graph([1, 2], [(1, 2), (1, 2)], set())

    def test_rejects_self_loops(self) -> None:
        with self.assertRaises(ValueError):
            calculate_visible_graph([1], [(1, 1)], set())

    def test_rejects_directed_cycles(self) -> None:
        invalid_edges = (
            [(1, 2), (2, 1)],
            [(1, 2), (2, 3), (3, 1)],
        )
        for edges in invalid_edges:
            with self.subTest(edges=edges):
                with self.assertRaises(ValueError):
                    calculate_visible_graph([1, 2, 3], edges, set())

    def test_rejects_malformed_collapsed_node_collections(self) -> None:
        invalid_collapsed = (
            [],
            (1,),
            frozenset({1}),
            {"1"},
            {True},
        )
        for collapsed in invalid_collapsed:
            with self.subTest(collapsed=collapsed):
                with self.assertRaises(ValueError):
                    calculate_visible_graph([1], [], collapsed)


if __name__ == "__main__":
    unittest.main()
