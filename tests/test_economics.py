"""SPDX-License-Identifier: Apache-2.0."""

import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "economics", Path(__file__).resolve().parents[1] / "benchmarks/economics.py"
)
economics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(economics)


class EconomicsTests(unittest.TestCase):
    def test_units_and_idle_allocation(self):
        self.assertAlmostEqual(economics.per_million(3.6, 1000), 1)
        self.assertAlmostEqual(economics.per_million(3.6, 1000, 0.25), 4)
        # $1000 amortized over 1000 hours, plus 1000 W at $1/kWh.
        self.assertAlmostEqual(economics.owned_hourly(1000, 0, 1, 1000, 1000, 1), 2)

    def test_invalid_inputs_fail(self):
        for args in (
            (1, 0, 1),
            (1, 1, 0),
            (1, 1, 1.01),
            (-1, 1, 1),
            (float("nan"), 1, 1),
            (1, float("inf"), 1),
        ):
            with self.assertRaises(ValueError):
                economics.per_million(*args)
