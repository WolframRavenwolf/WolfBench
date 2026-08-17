import importlib.util
import unittest
from pathlib import Path


CHART_PATH = Path(__file__).resolve().parents[1] / "wolfbench-chart.py"
SPEC = importlib.util.spec_from_file_location("wolfbench_chart", CHART_PATH)
chart = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(chart)


class CostRangeRenderingTests(unittest.TestCase):
    @staticmethod
    def _run(**overrides):
        run = {
            "score": 1.0,
            "passed_tasks": ["example-task"],
            "token_accounting_version": 2,
            "token_usage_complete": False,
        }
        run.update(overrides)
        return run

    def test_exact_and_bounded_costs_aggregate_without_fake_precision(self):
        metrics = chart.compute_metrics(
            [
                self._run(cost_usd=10.0),
                self._run(
                    cost_usd=0.0,
                    cost_usd_min=2.0,
                    cost_usd_max=4.0,
                    cost_usd_estimated=True,
                ),
            ]
        )

        self.assertEqual(metrics["cost_runs"], 2)
        self.assertEqual(metrics["cost_estimated_runs"], 1)
        self.assertEqual(metrics["cost_min_total_usd"], 12.0)
        self.assertEqual(metrics["cost_max_total_usd"], 14.0)
        self.assertEqual(metrics["cost_total_usd"], 13.0)
        self.assertEqual(
            chart._fmt_cost_range_usd(12.0, 14.0, estimated=True),
            "~$12.00–$14.00",
        )


if __name__ == "__main__":
    unittest.main()
