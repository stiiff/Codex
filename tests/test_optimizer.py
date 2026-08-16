import unittest
from pathlib import Path

from cpp_header_parser import parse_header, parse_header_text
from struct_layout_optimizer import compare_layouts, optimize, size_bits


HEADER = Path(__file__).parent / "fixtures" / "layout_cases.hpp"


def case(name):
    return parse_header(HEADER, name)


class OptimizerTests(unittest.TestCase):
    def test_byte_crossing_is_only_scored_for_sub_byte_fields(self):
        self.assertEqual(compare_layouts(case("Wide")).original.cost.cross8, 0)
        self.assertEqual(compare_layouts(case("Narrow")).original.cost.cross8, 1)

    def test_exactly_one_byte_does_not_contribute_byte_cost(self):
        self.assertEqual(compare_layouts(case("ExactByte")).original.cost.cross8, 0)

    def test_reorders_fields_to_avoid_word_crossing(self):
        result = optimize(case("WordReorder"))
        self.assertEqual(
            tuple(p.path for p in result.placements),
            ("WordReorder.a", "WordReorder.c", "WordReorder.b"),
        )
        self.assertEqual((result.cost.cross32, result.cost.cross8, result.size_bits), (0, 0, 40))

    def test_reserved_is_split_without_changing_total_size(self):
        result = optimize(case("ReservedSplit"))
        reserved = [p for p in result.placements if p.reserved]
        self.assertEqual(sum(p.bits for p in reserved), 7)
        self.assertEqual((result.size_bits, result.cost.cross32), (36, 0))

    def test_nested_struct_is_jointly_optimized_at_parent_phase(self):
        result = optimize(case("NestedParent"))
        self.assertEqual((result.size_bits, result.cost.cross32), (40, 0))
        self.assertIn("NestedParent.child.wide", {p.path for p in result.placements})

    def test_array_reuses_one_element_layout(self):
        result = optimize(case("ArrayCase"))
        self.assertEqual(result.size_bits, 48)
        orders = [
            [
                p.path.rsplit(".", 1)[-1]
                for p in result.placements
                if p.path.startswith(f"ArrayCase.items[{i}]")
            ]
            for i in range(3)
        ]
        self.assertEqual(orders[0], orders[1])
        self.assertEqual(orders[1], orders[2])

    def test_union_members_overlap_and_all_are_scored(self):
        result = optimize(case("TestUnion"), start=24)
        self.assertEqual(result.size_bits, 17)
        self.assertTrue(all(p.offset == 24 for p in result.placements))
        self.assertEqual(result.cost.cross32, 2)

    def test_nested_reserved_cannot_escape_its_struct(self):
        value = case("ReservedParent")
        result = optimize(value)
        child_rsvd = [p for p in result.placements if p.reserved]
        self.assertEqual(len(child_rsvd), 1)
        self.assertTrue(child_rsvd[0].path.startswith("ReservedParent.child."))
        self.assertEqual(size_bits(value), 16)

    def test_invalid_widths_are_rejected_from_header(self):
        with self.assertRaises(ValueError):
            parse_header_text("struct Invalid { uint0 value; };")

    def test_comparison_reports_original_and_optimized_layouts(self):
        comparison = compare_layouts(case("Comparison"))
        self.assertEqual(comparison.original.size_bits, comparison.optimized.size_bits)
        self.assertGreaterEqual(comparison.saved_cross32, 0)
        self.assertGreaterEqual(comparison.saved_cross8, 0)


if __name__ == "__main__":
    unittest.main()
