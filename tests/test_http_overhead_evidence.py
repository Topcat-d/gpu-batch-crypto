"""SPDX-License-Identifier: Apache-2.0. Preserve cleanup and failure evidence."""

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))
try:
    from report_http_overhead import DIRECTORY, validate
except ModuleNotFoundError as exc:
    if exc.name != "jwt":
        raise
    validate = None


@unittest.skipIf(validate is None, "install the interop extra")
class OverheadEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((DIRECTORY / "overhead-confirmation-v1.json").read_text())

    def test_complete_confirmation_and_retained_failure(self):
        validate(self.data)
        incomplete = json.loads((DIRECTORY / "overhead-comparison-v1.json").read_text())
        validate(incomplete, allow_incomplete=True)
        with self.assertRaises(ValueError):
            validate(incomplete)
        incomplete["cells"][-1]["failed"] = 0
        with self.assertRaises(ValueError):
            validate(incomplete, allow_incomplete=True)

    def test_checkpoint_commit_and_work_counts_cannot_be_omitted(self):
        for change in (
            lambda c: c.update(checkpoint=None),
            lambda c: c.update(cleanup_ms=0),
            lambda c: c["service_timings"]["db.commit"].update(count=0),
            lambda c: c["http"].update(requests=0),
            lambda c: c.update(on_time=c["on_time"] - 1),
        ):
            modified = copy.deepcopy(self.data)
            change(modified["cells"][0])
            with self.assertRaises(ValueError):
                validate(modified)


if __name__ == "__main__":
    unittest.main()
