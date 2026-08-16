import unittest

from struct_layout_optimizer import Reserved, UInt, compare_layouts, optimize, size_bits
from tests.cases import (
    ARRAY_CASE, COMPARISON_CASE, EXACT_BYTE_CROSSING_CASE,
    INVALID_RESERVED_WIDTH, INVALID_UINT_WIDTH, NESTED_PARENT_CASE,
    NESTED_RESERVED_CASE, RESERVED_SPLIT_CASE, RESERVED_SPLIT_TOTAL_BITS,
    SUB_BYTE_CROSSING_CASE, UNION_CASE, UNION_START_BIT,
    WIDE_BYTE_CROSSING_CASE, WORD_REORDER_CASE, WORD_REORDER_EXPECTED_PATHS,
)


class OptimizerTests(unittest.TestCase):
    def test_byte_crossing_is_only_scored_for_sub_byte_fields(self):
        wide = compare_layouts(WIDE_BYTE_CROSSING_CASE).original
        narrow = compare_layouts(SUB_BYTE_CROSSING_CASE).original
        self.assertEqual(wide.cost.cross8, 0)
        self.assertEqual(narrow.cost.cross8, 1)

    def test_exactly_one_byte_does_not_contribute_byte_cost(self):
        self.assertEqual(compare_layouts(EXACT_BYTE_CROSSING_CASE).original.cost.cross8, 0)

    def test_reorders_fields_to_avoid_word_crossing(self):
        result = optimize(WORD_REORDER_CASE)
        self.assertEqual(tuple(p.path for p in result.placements), WORD_REORDER_EXPECTED_PATHS)
        self.assertEqual((result.cost.cross32, result.cost.cross8, result.size_bits), (0, 0, 40))

    def test_reserved_is_split_without_changing_total_size(self):
        result = optimize(RESERVED_SPLIT_CASE)
        reserved = [p for p in result.placements if p.reserved]
        self.assertEqual(sum(p.bits for p in reserved), RESERVED_SPLIT_TOTAL_BITS)
        self.assertEqual((result.size_bits, result.cost.cross32), (36, 0))

    def test_nested_struct_is_jointly_optimized_at_parent_phase(self):
        result = optimize(NESTED_PARENT_CASE)
        self.assertEqual((result.size_bits, result.cost.cross32), (40, 0))
        self.assertIn("NestedParent.child.wide", {p.path for p in result.placements})

    def test_array_reuses_one_element_layout(self):
        result = optimize(ARRAY_CASE)
        self.assertEqual(result.size_bits, 48)
        orders = [
            [p.path.rsplit(".", 1)[-1] for p in result.placements if p.path.startswith(f"[{i}]")]
            for i in range(3)
        ]
        self.assertEqual(orders[0], orders[1])
        self.assertEqual(orders[1], orders[2])

    def test_union_members_overlap_and_all_are_scored(self):
        result = optimize(UNION_CASE, start=UNION_START_BIT)
        self.assertEqual(result.size_bits, 17)
        self.assertTrue(all(p.offset == UNION_START_BIT for p in result.placements))
        self.assertEqual(result.cost.cross32, 2)

    def test_nested_reserved_cannot_escape_its_struct(self):
        result = optimize(NESTED_RESERVED_CASE)
        child_rsvd = [p for p in result.placements if p.reserved]
        self.assertEqual(len(child_rsvd), 1)
        self.assertTrue(child_rsvd[0].path.startswith("ReservedParent.child."))
        self.assertEqual(size_bits(NESTED_RESERVED_CASE), 16)

    def test_invalid_widths_are_rejected(self):
        with self.assertRaises(ValueError):
            UInt(INVALID_UINT_WIDTH)
        with self.assertRaises(ValueError):
            Reserved(INVALID_RESERVED_WIDTH)

    def test_comparison_reports_original_and_optimized_layouts(self):
        comparison = compare_layouts(COMPARISON_CASE)
        self.assertEqual(comparison.original.size_bits, comparison.optimized.size_bits)
        self.assertGreaterEqual(comparison.saved_cross32, 0)
        self.assertGreaterEqual(comparison.saved_cross8, 0)


if __name__ == "__main__":
    unittest.main()
