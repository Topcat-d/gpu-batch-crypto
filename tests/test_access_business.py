"""SPDX-License-Identifier: Apache-2.0. Cost boundaries and archive tamper checks."""

import copy
from dataclasses import replace
import json
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))
from access_business_model import Assumptions, evaluate  # noqa: E402
from verify_access_book import verify_row  # noqa: E402


class BusinessTests(unittest.TestCase):
    def test_unspent_principal_is_not_revenue(self):
        full = evaluate(Assumptions(), 500)
        quarter = evaluate(replace(Assumptions(), funded_spend_fraction=0.25), 500)
        self.assertAlmostEqual(
            quarter["funding_cost_per_access_usd"],
            full["funding_cost_per_access_usd"] * 4,
        )
        self.assertEqual(
            quarter["publisher_accrual_per_access_usd"],
            full["publisher_accrual_per_access_usd"],
        )
        self.assertIsNone(quarter["whole_host_break_even_accesses_monthly"])

    def test_idle_cost_and_whole_host_floor(self):
        a = Assumptions()
        result = evaluate(a, 500)
        ideal = evaluate(replace(a, host_utilization=1), 500)
        self.assertAlmostEqual(
            result["compute_per_access_usd"], 4 * ideal["compute_per_access_usd"]
        )
        n = result["whole_host_break_even_accesses_monthly"]
        before_compute = (
            result["platform_contribution_per_access_usd"]
            + result["compute_per_access_usd"]
        )

        def profit(count):
            hosts = math.ceil(
                count / result["single_allocation_modeled_monthly_capacity"]
            )
            return (
                count * before_compute
                - result["fixed_monthly_usd"]
                - hosts * 730 * a.host_hourly_usd
            )

        self.assertGreaterEqual(profit(n), 0)
        self.assertLess(profit(n - 1), 0)
        self.assertGreater(n, result["modeled_break_even_accesses_monthly"])

    def test_invalid_inputs_and_bounded_proportions(self):
        for changes in (
            {"price_usd": 0},
            {"funded_spend_fraction": 0},
            {"host_hourly_usd": math.nan},
            {"publishers": True},
            {"publisher_share": 1.1},
        ):
            with self.assertRaises(ValueError):
                evaluate(replace(Assumptions(), **changes), 500)
        for rate in (0, -1, math.inf, math.nan):
            with self.assertRaises(ValueError):
                evaluate(Assumptions(), rate)

    def test_archive_rejects_changed_accounting_and_work_counts(self):
        data = json.loads(
            (
                ROOT / "benchmarks/access_book_results/ryzen7800x3d-2026-09-05.json"
            ).read_text()
        )
        original = data["rows"][0]
        verify_row(original)
        for field in ("completed", "transactions", "verifications"):
            row = copy.deepcopy(original)
            row[field] -= 1
            with self.assertRaises(AssertionError):
                verify_row(row)
        row = copy.deepcopy(original)
        row["audit"]["accounts"][0]["available"] += 1
        with self.assertRaises(AssertionError):
            verify_row(row)


if __name__ == "__main__":
    unittest.main()
