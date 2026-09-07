"""SPDX-License-Identifier: Apache-2.0. Public API evidence gates."""

import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "manifest_report", ROOT / "benchmarks/report_manifest_api.py"
)
REPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPORT)


class ManifestEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(REPORT.INPUT.read_text(encoding="utf-8"))

    def test_complete_capture_and_wire_reconstruction(self):
        REPORT.validate(self.data)

    def test_changed_work_source_metadata_and_load_fail(self):
        variants = []
        for field, value in (
            ("accepted", 0),
            ("signatures", 0),
            ("total_ms", 0),
            ("metadata_bytes", 1),
            ("cpu_sample", 999),
            ("changed_rejected", False),
        ):
            changed = copy.deepcopy(self.data)
            changed["cells"][0][field] = value
            variants.append(changed)
        for field in ("cells", "warmups", "cpu_samples"):
            changed = copy.deepcopy(self.data)
            changed[field].pop()
            variants.append(changed)
        changed = copy.deepcopy(self.data)
        changed["sources"]["python/batchcrypto/manifests.py"] = "0" * 64
        variants.append(changed)
        changed = copy.deepcopy(self.data)
        changed["cpu_samples"][0]["percent"] = -1
        variants.append(changed)
        for changed in variants:
            with self.assertRaises(ValueError):
                REPORT.validate(changed)


if __name__ == "__main__":
    unittest.main()
