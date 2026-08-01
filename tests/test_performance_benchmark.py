import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.benchmark_large_library import (
    PerformanceBudget,
    ScanMeasurement,
    evaluate_budget,
)


class PerformanceBudgetTests(unittest.TestCase):
    def test_budget_loads_valid_bounded_values(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "budget.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "file_count": 10_000,
                        "max_cold_scan_seconds": 180,
                        "max_warm_scan_seconds": 60,
                        "max_warm_to_cold_ratio": 0.75,
                        "max_cancel_latency_seconds": 2,
                        "max_peak_working_set_mib": 768,
                        "min_warm_cache_reuse_ratio": 0.99,
                    }
                ),
                encoding="utf-8",
            )

            budget = PerformanceBudget.load(path)

        self.assertEqual(budget.file_count, 10_000)
        self.assertEqual(budget.max_warm_scan_seconds, 60)
        self.assertEqual(budget.min_warm_cache_reuse_ratio, 0.99)

    def test_budget_rejects_boolean_and_out_of_range_ratio(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "budget.json"
            base = {
                "schema_version": 1,
                "file_count": 10_000,
                "max_cold_scan_seconds": 180,
                "max_warm_scan_seconds": 60,
                "max_warm_to_cold_ratio": 0.75,
                "max_cancel_latency_seconds": 2,
                "max_peak_working_set_mib": 768,
                "min_warm_cache_reuse_ratio": 0.99,
            }
            path.write_text(
                json.dumps({**base, "file_count": True}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "正整数"):
                PerformanceBudget.load(path)

            path.write_text(
                json.dumps({**base, "min_warm_cache_reuse_ratio": 1.1}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "0 到 1"):
                PerformanceBudget.load(path)

            path.write_text(
                json.dumps({**base, "max_warm_to_cold_ratio": 1.1}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "0 到 1"):
                PerformanceBudget.load(path)

    def test_evaluator_covers_time_memory_cache_and_plan_counts(self) -> None:
        budget = PerformanceBudget(
            file_count=10_000,
            max_cold_scan_seconds=180,
            max_warm_scan_seconds=60,
            max_warm_to_cold_ratio=0.75,
            max_cancel_latency_seconds=2,
            max_peak_working_set_mib=768,
            min_warm_cache_reuse_ratio=0.99,
        )
        cold = ScanMeasurement(
            seconds=50,
            plan_count=10_000,
            peak_working_set_mib=300,
            working_set_growth_mib=200,
            cache_stats={"reused_files": 0},
        )
        warm = ScanMeasurement(
            seconds=8,
            plan_count=10_000,
            peak_working_set_mib=350,
            working_set_growth_mib=100,
            cache_stats={"reused_files": 10_000},
        )

        checks = evaluate_budget(
            budget,
            file_count=10_000,
            cancellation_seconds=0.01,
            cold=cold,
            warm=warm,
        )

        self.assertTrue(all(check.passed for check in checks))
        self.assertEqual(
            {check.metric for check in checks},
            {
                "file_count",
                "cold_scan_seconds",
                "warm_scan_seconds",
                "warm_to_cold_ratio",
                "cancel_latency_seconds",
                "peak_working_set_mib",
                "warm_cache_reuse_ratio",
                "cold_plan_count",
                "warm_plan_count",
            },
        )

    def test_evaluator_keeps_a_meaningful_warm_scan_speedup(self) -> None:
        budget = PerformanceBudget(
            file_count=10_000,
            max_cold_scan_seconds=180,
            max_warm_scan_seconds=60,
            max_warm_to_cold_ratio=0.9,
            max_cancel_latency_seconds=2,
            max_peak_working_set_mib=768,
            min_warm_cache_reuse_ratio=0.99,
        )
        cold = ScanMeasurement(20, 10_000, 100, 20, {"reused_files": 0})
        warm = ScanMeasurement(19, 10_000, 100, 10, {"reused_files": 10_000})

        checks = evaluate_budget(
            budget,
            file_count=10_000,
            cancellation_seconds=0.01,
            cold=cold,
            warm=warm,
        )

        ratio_check = next(check for check in checks if check.metric == "warm_to_cold_ratio")
        self.assertFalse(ratio_check.passed)
        self.assertAlmostEqual(ratio_check.value, 0.95)


if __name__ == "__main__":
    unittest.main()
