import unittest
from pathlib import Path

from cpp_header_parser import HeaderParseError, parse_header, parse_header_text
from struct_layout_optimizer import Struct, compare_layouts, size_bits


FIXTURE = Path(__file__).parent / "fixtures" / "layout_cases.hpp"


class HeaderParserTests(unittest.TestCase):
    def test_parses_nested_cpp_header(self):
        root = parse_header(FIXTURE, "TelemetryPacket")
        self.assertIsInstance(root, Struct)
        self.assertEqual(root.name, "TelemetryPacket")
        self.assertEqual(size_bits(root), 1433)
        comparison = compare_layouts(root)
        self.assertEqual(comparison.original.size_bits, comparison.optimized.size_bits)

    def test_last_definition_is_default_root(self):
        self.assertEqual(parse_header(FIXTURE).name, "TelemetryPacket")

    def test_rejects_unknown_root(self):
        with self.assertRaises(HeaderParseError):
            parse_header_text("struct A { uint7 x; };", "Missing")


if __name__ == "__main__":
    unittest.main()
