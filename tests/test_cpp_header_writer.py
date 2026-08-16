import unittest
from pathlib import Path

from cpp_header_parser import parse_header
from cpp_header_writer import render_optimized_header


FIXTURE = Path(__file__).parent / "fixtures" / "layout_cases.hpp"


class HeaderWriterTests(unittest.TestCase):
    def test_writes_optimized_field_order(self):
        output = render_optimized_header(parse_header(FIXTURE, "WordReorder"))
        self.assertLess(output.index("uint17 a;"), output.index("uint15 c;"))
        self.assertLess(output.index("uint15 c;"), output.index("uint8 b;"))
        self.assertIn("32-bit crossings: 1 -> 0", output)

    def test_writes_nested_arrays_unions_and_reserved_fragments(self):
        output = render_optimized_header(parse_header(FIXTURE, "TelemetryPacket"))
        self.assertIn("struct TelemetryPacket", output)
        self.assertIn("union {", output)
        self.assertIn("records[16]", output)
        self.assertIn("samples[4]", output)
        self.assertIn("rsvd_0", output)


if __name__ == "__main__":
    unittest.main()
