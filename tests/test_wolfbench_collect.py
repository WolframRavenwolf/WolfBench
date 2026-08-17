import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import wolfbench_collect as collector


class ExtractMetricsSchemaTests(unittest.TestCase):
    @staticmethod
    def _config():
        return {
            "agents": [
                {
                    "name": "hermes",
                    "model_name": "openai/test/model",
                    "kwargs": {},
                }
            ],
            "environment": {},
            "orchestrator": {},
        }

    @staticmethod
    def _result(stats, *, n_total_trials=None):
        result = {
            "stats": {
                **stats,
                "evals": {
                    "hermes__test-model__terminal-bench": {
                        "n_trials": stats.get("eval_n_trials", 0),
                        "n_errors": stats.get("eval_n_errors", 0),
                        "metrics": [{"mean": 0.5}],
                        "reward_stats": {"reward": {"0.0": [], "1.0": []}},
                    }
                },
            }
        }
        result["stats"].pop("eval_n_trials", None)
        result["stats"].pop("eval_n_errors", None)
        if n_total_trials is not None:
            result["n_total_trials"] = n_total_trials
        return result

    @staticmethod
    def _codex_config():
        return {
            "agents": [
                {
                    "name": "codex",
                    "model_name": "openai/gpt-5.6-sol",
                    "kwargs": {
                        "model_info": {
                            "input_cost_per_token": 0.000005,
                            "cache_read_input_token_cost": 0.0000005,
                            "cache_creation_input_token_cost": 0.00000625,
                            "output_cost_per_token": 0.00003,
                        }
                    },
                }
            ],
            "environment": {},
            "orchestrator": {},
        }

    def _extract(self, result):
        return collector.extract_metrics(
            "test-vm",
            "/tmp/jobs/test/2026-07-14__00-00-00",
            result,
            self._config(),
        )

    def test_harbor_018_completed_and_errored_counters(self):
        record = self._extract(
            self._result(
                {
                    "n_completed_trials": 89,
                    "n_errored_trials": 3,
                    "eval_n_trials": 89,
                    "eval_n_errors": 3,
                },
                n_total_trials=89,
            )
        )

        self.assertEqual(record["n_trials"], 89)
        self.assertEqual(record["n_errors"], 3)
        self.assertIsNone(collector.classify_run(record))

    def test_harbor_018_partial_prefers_completed_over_planned_total(self):
        record = self._extract(
            self._result(
                {
                    "n_completed_trials": 42,
                    "n_errored_trials": 2,
                    "eval_n_trials": 42,
                    "eval_n_errors": 2,
                },
                n_total_trials=89,
            )
        )

        self.assertEqual(record["n_trials"], 42)
        self.assertEqual(record["n_errors"], 2)
        self.assertEqual(collector.classify_run(record), "partial run (42/89 tasks)")

    def test_legacy_counters_keep_precedence(self):
        record = self._extract(
            self._result(
                {
                    "n_trials": 89,
                    "n_errors": 5,
                    "n_completed_trials": 7,
                    "n_errored_trials": 1,
                    "eval_n_trials": 7,
                    "eval_n_errors": 1,
                },
                n_total_trials=7,
            )
        )

        self.assertEqual(record["n_trials"], 89)
        self.assertEqual(record["n_errors"], 5)

    def test_unknown_cache_write_split_produces_honest_cost_bounds(self):
        tokens = {
            "in": 10_000_000,
            "non_cached": 2_000_000,
            "uncached": None,
            "cache": 8_000_000,
            "cache_write": None,
            "out": 1_000_000,
            "usage_complete": True,
            "cache_write_complete": False,
            "tasks": 89,
        }
        pricing = collector._pricing_from_model_info(self._codex_config())

        self.assertIsNone(collector._calculate_token_cost_usd(tokens, pricing))
        self.assertEqual(
            collector._calculate_token_cost_bounds_usd(tokens, pricing),
            (44.0, 46.5),
        )

        record = collector.extract_metrics(
            "test-vm",
            "/tmp/jobs/test/2026-07-15__00-00-00",
            self._result(
                {
                    "n_completed_trials": 89,
                    "n_errored_trials": 0,
                    "eval_n_trials": 89,
                    "eval_n_errors": 0,
                },
                n_total_trials=89,
            ),
            self._codex_config(),
            tokens=tokens,
        )

        self.assertFalse(collector._positive_cost_usd(record["cost_usd"]))
        self.assertEqual(record["cost_usd_min"], 44.0)
        self.assertEqual(record["cost_usd_max"], 46.5)
        self.assertTrue(record["cost_usd_estimated"])
        self.assertEqual(
            record["cost_usd_basis"],
            "token_rate_bounds_missing_cache_write_split",
        )


if __name__ == "__main__":
    unittest.main()
