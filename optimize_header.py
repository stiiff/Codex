"""Command-line entry point for optimizing a C/C++ header declaration."""

import argparse
import sys

from cpp_header_parser import parse_header
from struct_layout_optimizer import compare_layouts, format_comparison


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Optimize bit-field layout from a C/C++ header")
    parser.add_argument("header", help="input .h/.hpp file")
    parser.add_argument("--root", help="root struct/union name; defaults to the last definition")
    parser.add_argument("--start", type=int, default=0, help="absolute starting bit offset")
    args = parser.parse_args()
    type_ = parse_header(args.header, args.root)
    print(format_comparison(compare_layouts(type_, args.start)))


if __name__ == "__main__":
    main()
