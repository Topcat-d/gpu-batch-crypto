"""SPDX-License-Identifier: Apache-2.0. Retain complete comparison evidence."""

import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "receipt_report", ROOT / "benchmarks/report_receipts.py"
)
REPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPORT)


class ReceiptEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(REPORT.INPUT.read_text(encoding="utf-8"))

    def test_complete_capture_and_reconstructed_wire_sizes(self):
        REPORT.validate(self.data)

    def test_missing_work_changed_sources_and_wire_cost_rejected(self):
        variants = []
        for field, value in (
            ("accepted", 0),
            ("changed_rejected", False),
            ("signatures", 0),
            ("total_ms", 0),
            ("metadata_bytes", 1),
            ("manifest_once_bytes", 999),
            ("order", 1),
        ):
            changed = copy.deepcopy(self.data)
            changed["cells"][0][field] = value
            variants.append(changed)
        changed = copy.deepcopy(self.data)
        changed["cells"].pop()
        variants.append(changed)
        changed = copy.deepcopy(self.data)
        changed["source_sha256"]["python/batchcrypto/receipts.py"] = "0" * 64
        variants.append(changed)
        for changed in variants:
            with self.assertRaises(ValueError):
                REPORT.validate(changed)


if __name__ == "__main__":
    unittest.main()
