"""SPDX-License-Identifier: Apache-2.0. Resource and key-generation guards."""

import unittest

from batchcrypto import Cpu, MAX_BATCH, Record


class IterableBoundsTests(unittest.TestCase):
    def test_large_iterables_stop_at_the_public_bound(self):
        cpu = Cpu()
        key = (1).to_bytes(32, "big")
        for call, item in (
            (cpu.sha256, b"message"),
            (lambda values: cpu.sign(key, values), bytes(32)),
            (lambda values: cpu.seal(key, values), Record(bytes(12), b"message")),
        ):
            consumed = []

            def values():
                for i in range(MAX_BATCH + 100):
                    consumed.append(i)
                    if len(consumed) > MAX_BATCH + 1:
                        self.fail("input consumed beyond the bounded batch budget")
                    yield item

            with self.assertRaises(ValueError):
                call(values())
            self.assertLessEqual(len(consumed), MAX_BATCH + 1)


if __name__ == "__main__":
    unittest.main()
