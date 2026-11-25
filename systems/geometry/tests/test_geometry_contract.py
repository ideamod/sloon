"""Contract tests for physical graph geometry."""

import unittest
from itertools import combinations

from systems.geometry import Geometry, Rect, Size, calculate_geometry
from systems.logical_layout.spec.schema import ComponentLayout, LogicalLayout


def _layout(
    *components: tuple[tuple[int, ...], ...],
) -> LogicalLayout:
    return LogicalLayout(
        tuple(ComponentLayout(columns) for columns in components)
    )


def _overlap(first: Rect, second: Rect) -> bool:
    return (
        first.x < second.x + second.width
        and second.x < first.x + first.width
        and first.y < second.y + second.height
        and second.y < first.y + first.height
    )


class GeometryContractTests(unittest.TestCase):
    def test_empty_layout_produces_empty_geometry(self) -> None:
        result = calculate_geometry(LogicalLayout(components=()), {})

        self.assertEqual(result.geometry, Geometry(nodes={}, width=0, height=0))

    def test_single_node_is_positioned_at_origin(self) -> None:
        result = calculate_geometry(
            _layout(((1,),)),
            {1: Size(width=3, height=2)},
        )

        self.assertEqual(result.geometry.nodes, {1: Rect(0, 0, 12, 2)})
        self.assertEqual(result.geometry.width, 12)
        self.assertEqual(result.geometry.height, 2)

    def test_custom_node_width_applies_to_every_node(self) -> None:
        result = calculate_geometry(
            _layout(((1,), (2,))),
            {1: Size(1, 1), 2: Size(99, 1)},
            node_width=50,
        )

        self.assertEqual(result.get_rect(1), Rect(0, 0, 50, 1))
        self.assertEqual(result.get_rect(2), Rect(54, 0, 50, 1))
        self.assertEqual(result.geometry.width, 104)

    def test_rejects_invalid_node_width(self) -> None:
        layout = _layout(((1,),))
        for width in (2, 0, -1, 3.5, "12", True):
            with self.subTest(width=width):
                with self.assertRaises(ValueError):
                    calculate_geometry(
                        layout,
                        {1: Size(1, 1)},
                        node_width=width,
                    )

    def test_default_row_gap_is_zero(self) -> None:
        result = calculate_geometry(
            _layout(((1, 2, 3),)),
            {
                1: Size(width=2, height=2),
                2: Size(width=3, height=4),
                3: Size(width=1, height=1),
            },
        )

        self.assertEqual(result.get_rect(1), Rect(0, 0, 12, 2))
        self.assertEqual(result.get_rect(2), Rect(0, 2, 12, 4))
        self.assertEqual(result.get_rect(3), Rect(0, 6, 12, 1))
        self.assertEqual(result.geometry.height, 7)

    def test_same_logical_positions_share_y_coordinates(self) -> None:
        result = calculate_geometry(
            _layout(((1, 2), (3, 4))),
            {
                1: Size(width=2, height=2),
                2: Size(width=2, height=3),
                3: Size(width=2, height=5),
                4: Size(width=2, height=1),
            },
        )

        self.assertEqual(result.get_rect(1).y, result.get_rect(3).y)
        self.assertEqual(result.get_rect(2).y, result.get_rect(4).y)
        self.assertEqual(result.get_rect(1).y, 0)
        self.assertEqual(result.get_rect(2).y, 5)

    def test_node_width_is_fixed_across_components(self) -> None:
        result = calculate_geometry(
            _layout(((1,), (2,)), ((3,), (4,))),
            {
                1: Size(width=2, height=1),
                2: Size(width=3, height=1),
                3: Size(width=7, height=1),
                4: Size(width=5, height=1),
            },
        )

        self.assertEqual(result.get_rect(1).x, 0)
        self.assertEqual(result.get_rect(3).x, 0)
        self.assertEqual(result.get_rect(1).width, 12)
        self.assertEqual(result.get_rect(2).width, 12)
        self.assertEqual(result.get_rect(3).width, 12)
        self.assertEqual(result.get_rect(4).width, 12)
        self.assertEqual(result.get_rect(2).x, 16)
        self.assertEqual(result.get_rect(4).x, 16)
        self.assertEqual(result.geometry.width, 28)

    def test_row_height_uses_tallest_node_at_each_position(self) -> None:
        result = calculate_geometry(
            _layout(((1, 2), (3, 4))),
            {
                1: Size(width=1, height=2),
                2: Size(width=1, height=7),
                3: Size(width=1, height=5),
                4: Size(width=1, height=3),
            },
        )

        self.assertEqual(result.get_rect(2).y, 5)
        self.assertEqual(result.get_rect(4).y, 5)
        self.assertEqual(result.geometry.height, 12)

    def test_default_component_gap_leaves_exactly_one_empty_row(self) -> None:
        result = calculate_geometry(
            _layout(((1,),), ((2,),)),
            {
                1: Size(width=2, height=3),
                2: Size(width=2, height=4),
            },
        )

        self.assertEqual(result.get_rect(1), Rect(0, 0, 12, 3))
        self.assertEqual(result.get_rect(2), Rect(0, 4, 12, 4))
        self.assertEqual(result.geometry.height, 8)

    def test_previous_default_gaps_remain_available_explicitly(self) -> None:
        result = calculate_geometry(
            _layout(((1, 2),), ((3,),)),
            {
                1: Size(width=2, height=2),
                2: Size(width=2, height=4),
                3: Size(width=2, height=3),
            },
            column_gap=4,
            row_gap=1,
            component_gap=2,
        )

        self.assertEqual(result.get_rect(1), Rect(0, 0, 12, 2))
        self.assertEqual(result.get_rect(2), Rect(0, 3, 12, 4))
        self.assertEqual(result.get_rect(3), Rect(0, 9, 12, 3))
        self.assertEqual(result.geometry, Geometry(result.geometry.nodes, 12, 12))

    def test_empty_component_columns_preserve_global_column_positions(self) -> None:
        result = calculate_geometry(
            _layout(((1,), (), ()), ((2,), (3,), (4,))),
            {
                1: Size(width=2, height=2),
                2: Size(width=3, height=1),
                3: Size(width=4, height=1),
                4: Size(width=5, height=1),
            },
        )

        self.assertEqual(result.get_rect(1).x, 0)
        self.assertEqual(result.get_rect(2).x, 0)
        self.assertEqual(result.get_rect(3).x, 16)
        self.assertEqual(result.get_rect(4).x, 32)
        self.assertEqual(result.geometry.width, 44)

    def test_custom_gaps_are_respected(self) -> None:
        result = calculate_geometry(
            _layout(((1, 2), (3, 4)), ((5,), (6,))),
            {
                1: Size(width=2, height=2),
                2: Size(width=2, height=1),
                3: Size(width=3, height=1),
                4: Size(width=3, height=4),
                5: Size(width=2, height=2),
                6: Size(width=2, height=3),
            },
            column_gap=7,
            row_gap=5,
            component_gap=9,
        )

        self.assertEqual(result.get_rect(3).x, 19)
        self.assertEqual(result.get_rect(4), Rect(19, 7, 12, 4))
        self.assertEqual(result.get_rect(5).y, 20)
        self.assertEqual(result.get_rect(6).y, 20)
        self.assertEqual(result.geometry, Geometry(result.geometry.nodes, 31, 23))

    def test_zero_gaps_are_supported(self) -> None:
        result = calculate_geometry(
            _layout(((1, 2), (3, 4)), ((5,), ())),
            {
                1: Size(width=2, height=2),
                2: Size(width=2, height=2),
                3: Size(width=2, height=2),
                4: Size(width=2, height=2),
                5: Size(width=2, height=1),
            },
            column_gap=0,
            row_gap=0,
            component_gap=0,
        )

        self.assertEqual(result.get_rect(3).x, 12)
        self.assertEqual(result.get_rect(2).y, 2)
        self.assertEqual(result.get_rect(5).y, 4)
        self.assertEqual(result.geometry.width, 24)
        self.assertEqual(result.geometry.height, 5)

    def test_bounding_dimensions_exclude_trailing_gaps(self) -> None:
        result = calculate_geometry(
            _layout(((1,), (2,))),
            {
                1: Size(width=2, height=3),
                2: Size(width=4, height=1),
            },
            column_gap=5,
            row_gap=20,
            component_gap=30,
        )

        self.assertEqual(result.geometry.width, 29)
        self.assertEqual(result.geometry.height, 3)

    def test_every_node_has_one_non_overlapping_rectangle(self) -> None:
        layout = _layout(
            ((1, 2), (3, 4), (5,)),
            ((6,), (), (7, 8)),
        )
        sizes = {
            1: Size(2, 2),
            2: Size(3, 1),
            3: Size(4, 1),
            4: Size(1, 3),
            5: Size(2, 2),
            6: Size(3, 2),
            7: Size(5, 1),
            8: Size(2, 4),
        }

        result = calculate_geometry(layout, sizes)

        self.assertEqual(set(result.geometry.nodes), set(sizes))
        self.assertEqual(len(result.geometry.nodes), len(sizes))
        for node_id, rect in result.geometry.nodes.items():
            with self.subTest(node_id=node_id):
                self.assertEqual((rect.width, rect.height), (
                    12,
                    sizes[node_id].height,
                ))
                self.assertTrue(all(type(value) is int and value >= 0 for value in (
                    rect.x,
                    rect.y,
                    rect.width,
                    rect.height,
                )))

        for first_id, second_id in combinations(sizes, 2):
            with self.subTest(first_id=first_id, second_id=second_id):
                self.assertFalse(
                    _overlap(result.get_rect(first_id), result.get_rect(second_id))
                )

    def test_get_rect_returns_geometry_rectangle(self) -> None:
        result = calculate_geometry(
            _layout(((10,),)),
            {10: Size(width=4, height=3)},
        )

        self.assertEqual(result.get_rect(10), Rect(0, 0, 12, 3))
        self.assertEqual(result.get_rect(10), result.geometry.nodes[10])

    def test_get_rect_rejects_unknown_node_id(self) -> None:
        result = calculate_geometry(
            _layout(((1,),)),
            {1: Size(width=1, height=1)},
        )

        with self.assertRaises(KeyError):
            result.get_rect(999)

    def test_rejects_missing_or_extra_node_sizes(self) -> None:
        layout = _layout(((1,), (2,)))

        invalid_sizes = (
            {1: Size(1, 1)},
            {1: Size(1, 1), 2: Size(1, 1), 3: Size(1, 1)},
        )
        for sizes in invalid_sizes:
            with self.subTest(sizes=sizes):
                with self.assertRaises(ValueError):
                    calculate_geometry(layout, sizes)

    def test_rejects_zero_or_negative_dimensions(self) -> None:
        layout = _layout(((1,),))

        for size in (Size(0, 1), Size(-1, 1), Size(1, 0), Size(1, -1)):
            with self.subTest(size=size):
                with self.assertRaises(ValueError):
                    calculate_geometry(layout, {1: size})

    def test_rejects_invalid_size_values(self) -> None:
        layout = _layout(((1,),))
        invalid_sizes = (
            None,
            (1, 1),
            Size(1.5, 1),
            Size(1, 1.5),
            Size("1", 1),
            Size(1, "1"),
            Size(True, 1),
            Size(1, True),
        )

        for size in invalid_sizes:
            with self.subTest(size=size):
                with self.assertRaises(ValueError):
                    calculate_geometry(layout, {1: size})

    def test_rejects_negative_gaps(self) -> None:
        layout = _layout(((1,),))
        sizes = {1: Size(1, 1)}

        for gap_name in ("column_gap", "row_gap", "component_gap"):
            with self.subTest(gap_name=gap_name):
                with self.assertRaises(ValueError):
                    calculate_geometry(layout, sizes, **{gap_name: -1})

    def test_rejects_non_integer_gaps(self) -> None:
        layout = _layout(((1,),))
        sizes = {1: Size(1, 1)}

        for gap_name in ("column_gap", "row_gap", "component_gap"):
            for value in (1.5, "1", None, True):
                with self.subTest(gap_name=gap_name, value=value):
                    with self.assertRaises(ValueError):
                        calculate_geometry(layout, sizes, **{gap_name: value})

    def test_repeated_calculations_are_deterministic(self) -> None:
        layout = _layout(((1, 2), (3,)), ((4,), (5,)))
        sizes = {
            1: Size(2, 1),
            2: Size(3, 2),
            3: Size(4, 3),
            4: Size(1, 2),
            5: Size(2, 1),
        }

        first = calculate_geometry(layout, sizes, 6, 2, 4)
        second = calculate_geometry(layout, dict(sizes), 6, 2, 4)

        self.assertEqual(first.geometry, second.geometry)
        for node_id in sizes:
            self.assertEqual(first.get_rect(node_id), second.get_rect(node_id))


if __name__ == "__main__":
    unittest.main()
