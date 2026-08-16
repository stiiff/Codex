import unittest

from struct_layout_optimizer import (
    Array,
    Field,
    Reserved,
    Struct,
    UInt,
    Union,
    compare_layouts,
    optimize,
    size_bits,
)


class OptimizerTests(unittest.TestCase):
    def test_byte_crossing_is_only_scored_for_sub_byte_fields(self):
        wide = Struct("Wide", [Field("head", UInt(7)), Field("value", UInt(12))])
        narrow = Struct("Narrow", [Field("head", UInt(7)), Field("value", UInt(7))])

        wide_original = compare_layouts(wide).original
        narrow_original = compare_layouts(narrow).original

        # uint12 starts at bit 7 and crosses BYTE boundaries, but BYTE cost is
        # intentionally ignored because its width is greater than one BYTE.
        self.assertEqual(wide_original.cost.cross8, 0)
        # The second uint7 starts at bit 7 and crosses the bit-8 boundary.
        self.assertEqual(narrow_original.cost.cross8, 1)

    def test_exactly_one_byte_does_not_contribute_byte_cost(self):
        value = Struct("S", [Field("prefix", UInt(3)), Field("byte", UInt(8))])
        self.assertEqual(compare_layouts(value).original.cost.cross8, 0)

    def test_reorders_fields_to_avoid_word_crossing(self):
        value = Struct(
            "S",
            [Field("a", UInt(17)), Field("b", UInt(8)), Field("c", UInt(15))],
        )
        result = optimize(value)
        fields = [p.path for p in result.placements]
        self.assertEqual(fields, ["S.a", "S.c", "S.b"])
        self.assertEqual(result.cost.cross32, 0)
        self.assertEqual(result.cost.cross8, 0)
        self.assertEqual(result.size_bits, 40)

    def test_reserved_is_split_without_changing_total_size(self):
        value = Struct(
            "S",
            [Field("a", UInt(17)), Field("b", UInt(12)), Field("spare", Reserved(7))],
        )
        result = optimize(value)
        reserved = [p for p in result.placements if p.reserved]
        self.assertEqual(sum(p.bits for p in reserved), 7)
        self.assertEqual(result.size_bits, 36)
        self.assertEqual(result.cost.cross32, 0)

    def test_nested_struct_is_jointly_optimized_at_parent_phase(self):
        child = Struct("Child", [Field("wide", UInt(17)), Field("small", UInt(8))])
        parent = Struct(
            "Parent",
            [Field("head", UInt(7)), Field("child", child), Field("r", Reserved(8))],
        )
        result = optimize(parent)
        self.assertEqual(result.size_bits, 40)
        self.assertEqual(result.cost.cross32, 0)
        self.assertIn("Parent.child.wide", {p.path for p in result.placements})

    def test_array_reuses_one_element_layout(self):
        element = Struct("E", [Field("a", UInt(9)), Field("b", UInt(7))])
        result = optimize(Array(element, 3))
        self.assertEqual(result.size_bits, 48)
        orders = []
        for i in range(3):
            names = [p.path.rsplit(".", 1)[-1] for p in result.placements if p.path.startswith(f"[{i}]")]
            orders.append(names)
        self.assertEqual(orders[0], orders[1])
        self.assertEqual(orders[1], orders[2])

    def test_union_members_overlap_and_all_are_scored(self):
        union = Union("U", [Field("a", UInt(12)), Field("b", UInt(17))])
        result = optimize(union, start=24)
        self.assertEqual(result.size_bits, 17)
        self.assertTrue(all(p.offset == 24 for p in result.placements))
        self.assertEqual(result.cost.cross32, 2)

    def test_nested_reserved_cannot_escape_its_struct(self):
        child = Struct("C", [Field("x", UInt(5)), Field("r", Reserved(3))])
        parent = Struct("P", [Field("child", child), Field("y", UInt(8))])
        result = optimize(parent)
        child_rsvd = [p for p in result.placements if p.reserved]
        self.assertEqual(len(child_rsvd), 1)
        self.assertTrue(child_rsvd[0].path.startswith("P.child."))
        self.assertEqual(size_bits(parent), 16)

    def test_invalid_widths_are_rejected(self):
        with self.assertRaises(ValueError):
            UInt(0)
        with self.assertRaises(ValueError):
            Reserved(-1)

    def test_comparison_reports_original_and_optimized_layouts(self):
        value = Struct(
            "S",
            [Field("a", UInt(17)), Field("b", UInt(12)), Field("r", Reserved(3))],
        )
        comparison = compare_layouts(value)
        self.assertEqual(comparison.original.size_bits, comparison.optimized.size_bits)
        self.assertGreaterEqual(comparison.saved_cross32, 0)
        self.assertGreaterEqual(comparison.saved_cross8, 0)


if __name__ == "__main__":
    unittest.main()
