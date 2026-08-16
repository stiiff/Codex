import unittest
from pathlib import Path

from cpp_header_parser import parse_header
from cpp_header_writer import render_optimized_header
from struct_layout_optimizer import (
    OptimizationConfig,
    comparison_from_outcome,
    solve_layout,
)


FIXTURE = Path(__file__).parent / "fixtures" / "large_layout.hpp"


class LargeOptimizerTests(unittest.TestCase):
    def test_auto_mode_handles_120_direct_fields_within_budget(self):
        root = parse_header(FIXTURE, "LargeLayout")
        config = OptimizationConfig(
            mode="auto",
            exact_threshold=10,
            beam_width=32,
            branch_width=8,
            local_iterations=30,
            time_limit=2.0,
            random_seed=7,
        )
        outcome = solve_layout(root, config=config)
        comparison = comparison_from_outcome(root, outcome)
        self.assertEqual(comparison.mode, "heuristic")
        self.assertFalse(comparison.optimality_guaranteed)
        self.assertEqual(comparison.original.size_bits, comparison.optimized.size_bits)
        self.assertLessEqual(comparison.optimized.cost, comparison.original.cost)
        self.assertLess(comparison.optimized.cost.cross32, comparison.original.cost.cross32)
        self.assertLess(comparison.elapsed_seconds, 3.0)

        output = render_optimized_header(root, config=config, outcome=outcome)
        self.assertIn("Search mode: heuristic", output)
        self.assertIn("Globally optimal: no", output)

    def test_timeout_fallback_never_worsens_declared_layout(self):
        root = parse_header(FIXTURE, "LargeLayout")
        config = OptimizationConfig(
            mode="heuristic",
            beam_width=8,
            branch_width=4,
            local_iterations=0,
            time_limit=0.001,
        )
        outcome = solve_layout(root, config=config)
        comparison = comparison_from_outcome(root, outcome)
        self.assertLessEqual(comparison.optimized.cost, comparison.original.cost)


if __name__ == "__main__":
    unittest.main()
