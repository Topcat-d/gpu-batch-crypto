"""SPDX-License-Identifier: Apache-2.0. Prevent accidental promotion of busy-host runs."""

import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "run_pipeline", Path(__file__).resolve().parents[1] / "benchmarks/run_pipeline.py"
)
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


class CaptureTests(unittest.TestCase):
    def test_busy_other_gpu_blocks_shared_host_comparison(self):
        idle = {"gpus": [{"utilization.gpu": "0"}, {"utilization.gpu": "2"}]}
        busy = {"gpus": [{"utilization.gpu": "96"}, {"utilization.gpu": "0"}]}
        self.assertTrue(capture.quiet_gpus([idle, idle, idle]))
        self.assertFalse(capture.quiet_gpus([idle, busy, idle]))
        for bad in (
            [],
            [{"gpus": []}] * 3,
            [{"gpus": [{"utilization.gpu": "N/A"}]}] * 3,
        ):
            self.assertFalse(capture.quiet_gpus(bad))
