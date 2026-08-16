"""Test fixture declarations, equivalent to a test-case header."""

from struct_layout_optimizer import Array, Field, Reserved, Struct, UInt, Union

SUB_BYTE_CROSSING_CASE = Struct("Narrow", [Field("head", UInt(7)), Field("value", UInt(7))])
WIDE_BYTE_CROSSING_CASE = Struct("Wide", [Field("head", UInt(7)), Field("value", UInt(12))])
EXACT_BYTE_CROSSING_CASE = Struct("ExactByte", [Field("prefix", UInt(3)), Field("byte", UInt(8))])

WORD_REORDER_CASE = Struct(
    "WordReorder",
    [Field("a", UInt(17)), Field("b", UInt(8)), Field("c", UInt(15))],
)
WORD_REORDER_EXPECTED_PATHS = ("WordReorder.a", "WordReorder.c", "WordReorder.b")

RESERVED_SPLIT_CASE = Struct(
    "ReservedSplit",
    [Field("a", UInt(17)), Field("b", UInt(12)), Field("spare", Reserved(7))],
)
RESERVED_SPLIT_TOTAL_BITS = 7

NESTED_CHILD = Struct("NestedChild", [Field("wide", UInt(17)), Field("small", UInt(8))])
NESTED_PARENT_CASE = Struct(
    "NestedParent",
    [Field("head", UInt(7)), Field("child", NESTED_CHILD), Field("r", Reserved(8))],
)

ARRAY_ELEMENT = Struct("ArrayElement", [Field("a", UInt(9)), Field("b", UInt(7))])
ARRAY_CASE = Array(ARRAY_ELEMENT, 3)

UNION_CASE = Union("TestUnion", [Field("a", UInt(12)), Field("b", UInt(17))])
UNION_START_BIT = 24

NESTED_RESERVED_CHILD = Struct(
    "ReservedChild", [Field("x", UInt(5)), Field("r", Reserved(3))]
)
NESTED_RESERVED_CASE = Struct(
    "ReservedParent",
    [Field("child", NESTED_RESERVED_CHILD), Field("y", UInt(8))],
)

COMPARISON_CASE = Struct(
    "Comparison",
    [Field("a", UInt(17)), Field("b", UInt(12)), Field("r", Reserved(3))],
)

INVALID_UINT_WIDTH = 0
INVALID_RESERVED_WIDTH = -1
