"""SPDX-License-Identifier: Apache-2.0. Evidence-policy regression checks."""

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))
from report_ready_wave import quality, rate  # noqa: E402


class CostPolicyTests(unittest.TestCase):
    def test_common_work_retains_deadline_failures(self):
        rows = [
            {
                "wave": 256,
                "waves": 100,
                "elapsed_s": 3,
                "wave_latencies_ms": [29.0] * 99 + [31.0],
            }
        ] * 2
        self.assertTrue(quality(rows, 20))
        self.assertFalse(quality(rows, 22))
        self.assertAlmostEqual(rate(rows[0], 20), 99 * 256 / 5)
        self.assertEqual(rate(rows[0], 22), 0)

    def test_missed_work_is_not_removed_from_the_denominator(self):
        row = {
            "wave": 64,
            "waves": 100,
            "elapsed_s": 5,
            "wave_latencies_ms": [1.0] * 90 + [80.0] * 10,
        }
        self.assertFalse(quality([row, row]))
        self.assertEqual(rate(row), 90 * 64 / 5)


try:
    from verify_ready_wave import check_row
except ImportError:
    check_row = None


@unittest.skipUnless(check_row is not None, "install .[interop]")
class EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = ROOT / "benchmarks/ready_wave_results/rtx3060-2026-09-05.json"
        if not path.exists():
            raise unittest.SkipTest("capture not yet present")
        cls.row = json.loads(path.read_text(encoding="utf-8"))["rows"][0]

    def test_original_row_passes(self):
        check_row(self.row)

    def test_changed_counts_gpu_share_latency_or_token_fail(self):
        for field in ("verified", "within_50ms", "gpu_items", "p99_ms"):
            row = copy.deepcopy(self.row)
            row[field] += 1
            with self.assertRaises(AssertionError):
                check_row(row)
        row = copy.deepcopy(self.row)
        row["samples"][0]["token"] = row["samples"][0]["token"].replace(".", "x", 1)
        with self.assertRaises(Exception):
            check_row(row)

    def test_extra_guard_cannot_be_inferred_from_single_check_capture(self):
        with self.assertRaises(KeyError):
            check_row(self.row, separate=True)
