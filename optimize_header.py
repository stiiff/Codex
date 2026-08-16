"""Command-line entry point for optimizing a C/C++ header declaration."""

import argparse
import sys
from pathlib import Path

from cpp_header_parser import parse_header
from cpp_header_writer import render_optimized_header
from struct_layout_optimizer import (
    OptimizationConfig,
    comparison_from_outcome,
    format_comparison,
    solve_layout,
)


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Optimize bit-field layout from a C/C++ header")
    parser.add_argument("header", help="input .h/.hpp file")
    parser.add_argument("--root", help="root struct/union name; defaults to the last definition")
    parser.add_argument("--start", type=int, default=0, help="absolute starting bit offset")
    parser.add_argument("-o", "--output", help="optimized .h/.hpp output path")
    parser.add_argument("--mode", choices=("auto", "exact", "heuristic"), default="auto")
    parser.add_argument("--exact-threshold", type=int, default=10)
    parser.add_argument("--beam-width", type=int, default=128)
    parser.add_argument("--branch-width", type=int, default=12)
    parser.add_argument("--local-iterations", type=int, default=300)
    parser.add_argument("--time-limit", type=float, default=10.0)
    parser.add_argument("--random-seed", type=int, default=0)
    args = parser.parse_args()
    type_ = parse_header(args.header, args.root)
    config = OptimizationConfig(
        mode=args.mode,
        exact_threshold=args.exact_threshold,
        beam_width=args.beam_width,
        branch_width=args.branch_width,
        local_iterations=args.local_iterations,
        time_limit=args.time_limit,
        random_seed=args.random_seed,
    )
    outcome = solve_layout(type_, args.start, config)
    comparison = comparison_from_outcome(type_, outcome, args.start)
    output = Path(args.output) if args.output else Path(args.header).with_suffix(".optimized.hpp")
    output.write_text(
        render_optimized_header(type_, args.start, config, outcome=outcome),
        encoding="utf-8",
    )
    print(format_comparison(comparison))
    print(f"\n优化后头文件：{output}")


if __name__ == "__main__":
    main()
