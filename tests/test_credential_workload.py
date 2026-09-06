"""SPDX-License-Identifier: Apache-2.0. Workload conservation and fill units."""

import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))
from credential_workload_model import evaluate, evaluate_scenarios, markdown  # noqa: E402

BASE = dict(
    accesses_per_second=100000, fresh_fraction=1.0, accesses_per_credential=1,
    credential_use_fraction=1.0, compatible_groups=1, batch_size=64,
    fill_budget_ms=1.0,
)


class CredentialWorkloadTests(unittest.TestCase):
    def test_units_and_group_fragmentation(self):
        one = evaluate(**BASE)
        fragmented = evaluate(**dict(BASE, compatible_groups=100))
        self.assertAlmostEqual(one["first_item_fill_ms"], 0.63)
        self.assertAlmostEqual(fragmented["first_item_fill_ms"], 63)
        self.assertEqual(one["issued_credentials_per_second"], fragmented["issued_credentials_per_second"])
        self.assertEqual(fragmented["disposition"], "FILL_BUDGET_FAILS")

    def test_reuse_reduces_work_but_increases_fill(self):
        result = evaluate(**dict(BASE, fresh_fraction=0.1))
        self.assertEqual(result["issued_credentials_per_second"], 10000)
        self.assertAlmostEqual(result["first_item_fill_ms"], 6.3)

    def test_unused_book_entries_are_not_useful_accesses(self):
        result = evaluate(**dict(BASE, accesses_per_credential=32, credential_use_fraction=0.25))
        self.assertEqual(result["issued_credentials_per_second"], 12500)
        self.assertEqual(result["useful_fresh_accesses_per_second"], 100000)
        self.assertEqual(result["unused_access_entries_per_second"], 300000)

    def test_ready_wave_does_not_merge_keys(self):
        result = evaluate(**dict(BASE, compatible_groups=100, ready_jobs_per_group=64))
        self.assertEqual(result["credentials_per_group_per_second"], 1000)
        self.assertEqual(result["first_item_fill_ms"], 0)
        with self.assertRaises(ValueError):
            evaluate(**dict(BASE, ready_jobs_per_group=63))

    def test_no_fresh_work_is_not_a_gpu_win(self):
        for overrides in ({"fresh_fraction": 0}, {"accesses_per_second": 0}):
            result = evaluate(**dict(BASE, **overrides))
            self.assertEqual(result["disposition"], "NO_FRESH_CREDENTIAL_WORK")
            self.assertIsNone(result["first_item_fill_ms"])
            json.dumps(result, allow_nan=False)
        with self.assertRaises(ValueError):
            evaluate(**dict(BASE, fresh_fraction=0, ready_jobs_per_group=64))

    def test_invalid_assumptions_fail(self):
        for overrides in (
            {"accesses_per_second": math.inf}, {"fresh_fraction": math.nan},
            {"fresh_fraction": 1.01}, {"credential_use_fraction": 0},
            {"compatible_groups": 0}, {"batch_size": True},
            {"batch_size": 2.5}, {"fill_budget_ms": -1},
            {"ready_jobs_per_group": -1}, {"accesses_per_credential": 0},
            {"accesses_per_second": 1e308, "credential_use_fraction": 1e-308},
            {"compatible_groups": 10**500},
            {"accesses_per_second": 1e-308, "fresh_fraction": 1e-308},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                evaluate(**dict(BASE, **overrides))

    def test_scenarios_are_explicit_and_unique(self):
        path = ROOT / "benchmarks/credential_workload_scenarios.json"
        rows = evaluate_scenarios(path)
        self.assertEqual(len(rows), 7)
        self.assertIn("not measured", markdown(rows))
        data = json.loads(path.read_text())
        data["scenarios"].append(data["scenarios"][0])
        with tempfile.TemporaryDirectory() as tmp:
            duplicate = Path(tmp) / "duplicate.json"
            duplicate.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                evaluate_scenarios(duplicate)

    def test_published_example_matches_its_inputs(self):
        rows = evaluate_scenarios(ROOT / "benchmarks/credential_workload_scenarios.json")
        report = ROOT / "benchmarks/credential_workload_examples.md"
        self.assertEqual(report.read_text(encoding="utf-8").strip(), markdown(rows).strip())


if __name__ == "__main__":
    unittest.main()
