"""SPDX-License-Identifier: Apache-2.0. Preserve measured outcomes and costs."""

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))
try:
    from report_http_access import DEFAULT_INPUT, validate
except ModuleNotFoundError as exc:
    if exc.name != "jwt":
        raise
    validate = None


@unittest.skipIf(validate is None, "install the interop extra")
class HTTPEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.capture = json.loads(DEFAULT_INPUT.read_text())

    def test_complete_archive_passes(self):
        validate(self.capture)

    def test_changed_deadline_outcome_money_or_security_checks_fail(self):
        for field, change in (
            ("on_time", lambda n: n - 1),
            ("cost_usd", lambda _: 0),
            ("publisher_verifications", lambda n: n + 1),
        ):
            with self.subTest(field=field):
                modified = copy.deepcopy(self.capture)
                modified["cells"][0][field] = change(modified["cells"][0][field])
                with self.assertRaises(ValueError):
                    validate(modified)
        modified = copy.deepcopy(self.capture)
        modified["cells"][0]["audit_after"]["publisher_accrued"] += 1000
        with self.assertRaises(ValueError):
            validate(modified)

    def test_incomplete_capture_and_changed_source_are_rejected(self):
        modified = copy.deepcopy(self.capture)
        modified["complete"] = False
        with self.assertRaises(ValueError):
            validate(modified)
        modified = copy.deepcopy(self.capture)
        modified["sources"]["examples/http_access/ledger.py"] = "0" * 64
        with self.assertRaises(ValueError):
            validate(modified)


if __name__ == "__main__":
    unittest.main()
