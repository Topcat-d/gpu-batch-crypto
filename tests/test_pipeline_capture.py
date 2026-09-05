"""SPDX-License-Identifier: Apache-2.0. Prevent accidental promotion of busy-host runs."""

import importlib.util
import copy
from pathlib import Path
import sys
import unittest

spec = importlib.util.spec_from_file_location(
    "run_pipeline", Path(__file__).resolve().parents[1] / "benchmarks/run_pipeline.py"
)
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)
sys.modules["run_pipeline"] = capture
spec = importlib.util.spec_from_file_location(
    "verify_pipeline",
    Path(__file__).resolve().parents[1] / "benchmarks/verify_pipeline.py",
)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class CaptureTests(unittest.TestCase):
    def test_verifier_rejects_changed_scope_and_cpu_telemetry(self):
        samples = [
            {
                "system_cpu_times": {"total_s": 10 + i * 4, "idle_s": 5 + i},
                "system_cpu_percent": None if i == 0 else 75,
                "gpus": [
                    {"index": "0", "utilization.gpu": "98"},
                    {"index": "1", "utilization.gpu": "0"},
                ],
            }
            for i in range(3)
        ]
        data = {
            "metadata": {
                "preflight_scope": "target-gpu",
                "selected_device": 1,
                "contention_policy": "idle target GPU; shared CPU host with background activity recorded",
                "preflight_telemetry": samples,
                "preflight_quiet": True,
            },
            "rows": [
                {
                    "device": 1,
                    "preflight_telemetry": samples,
                    "preflight_quiet": True,
                    "telemetry": samples,
                }
            ],
        }
        verifier.verify_conditions(data)
        wrong_scope = copy.deepcopy(data)
        wrong_scope["metadata"]["preflight_scope"] = "all-gpus"
        with self.assertRaisesRegex(ValueError, "preflight result"):
            verifier.verify_conditions(wrong_scope)
        wrong_cpu = copy.deepcopy(samples)
        wrong_cpu[1]["system_cpu_percent"] = 0
        with self.assertRaisesRegex(ValueError, "CPU utilization"):
            verifier.verify_telemetry(wrong_cpu)
        with self.assertRaisesRegex(ValueError, "telemetry failed"):
            verifier.verify_telemetry([{"error": "counter unavailable"}])

    def test_target_scope_requires_the_named_gpu_to_be_idle(self):
        sample = {
            "gpus": [
                {"index": "0", "utilization.gpu": "98"},
                {"index": "1", "utilization.gpu": "0"},
            ]
        }
        self.assertTrue(capture.quiet_gpus([sample] * 3, device=1))
        self.assertFalse(capture.quiet_gpus([sample] * 3))
        self.assertFalse(capture.quiet_gpus([sample] * 3, device=0))
        self.assertFalse(capture.quiet_gpus([sample] * 3, device=2))

    def test_cpu_utilization_subtracts_idle_and_rejects_bad_intervals(self):
        self.assertAlmostEqual(
            capture.system_cpu_percent(
                {"total_s": 10, "idle_s": 5}, {"total_s": 14, "idle_s": 6}
            ),
            75,
        )
        self.assertIsNone(capture.system_cpu_percent(None, {}))
        self.assertIsNone(
            capture.system_cpu_percent(
                {"total_s": 10, "idle_s": 5}, {"total_s": 10, "idle_s": 5}
            )
        )

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
