"""SPDX-License-Identifier: Apache-2.0. Native fixed-base backend interoperability."""

import hashlib
import os
import unittest

from batchcrypto import Cpu, ORDER, Runtime, public_key, verify_p256


@unittest.skipUnless(os.environ.get("BC_LIBRARY"), "CUDA table backends only")
class TableBackendTests(unittest.TestCase):
    def runtime(self, backend="reference"):
        rt = Runtime(
            os.environ["BC_LIBRARY"], int(os.environ.get("BC_DEVICE", "0")), backend
        )
        self.addCleanup(rt.close)
        return rt

    def test_points_across_windows_and_final_carry(self):
        rt = self.runtime()
        scalars = {1, 2, 127, 128, 255, 256, ORDER - 1, (1 << 255) - 1, 1 << 255}
        for window in range(32):
            for digit in (0x7F, 0x80, 0xFF):
                scalars.add((digit << (8 * window)) % ORDER)
        scalars.update(
            int.from_bytes(os.urandom(32), "big") % (ORDER - 1) + 1 for _ in range(16)
        )
        for backend in ("comb_w8", "full_window_w8"):
            rt.set_p256_backend(backend)
            epoch = 0
            for scalar in sorted(scalars):
                key = scalar.to_bytes(32, "big")
                epoch = rt.load_key(0, key, "p256", epoch)
                actual, used = rt.public_key(0)
                self.assertEqual(actual, public_key(key), (backend, hex(scalar)))
                self.assertEqual(used, epoch)
            rt.retire_key(0, epoch)
            # A tombstone epoch persists; use a fresh slot in the next round.
            if backend == "comb_w8":
                rt.close()
                rt = self.runtime()

    def test_signatures_match_cpu_and_reference(self):
        rt = self.runtime()
        cpu = Cpu()
        keys = [
            bytes.fromhex(
                "c9afa9d845ba75166b5c215767b1d6934e50c3db36e89b127b8a622b120f6721"
            ),
            (ORDER - 1).to_bytes(32, "big"),
            (1).to_bytes(32, "big"),
        ]
        epoch = 0
        for key in keys:
            epoch = rt.load_key(0, key, "p256", epoch)
            digests = [
                hashlib.sha256(b"sample").digest(),
                bytes(32),
                bytes([255]) * 32,
                ORDER.to_bytes(32, "big"),
            ] + [os.urandom(32) for _ in range(64)]
            expected = cpu.sign(key, digests)
            for backend in ("reference", "comb_w8", "full_window_w8"):
                rt.set_p256_backend(backend)
                actual = rt.sign(0, digests)
                self.assertEqual(actual, expected, backend)
                self.assertEqual(rt.last_report["key_epoch"], epoch)
                self.assertEqual(rt.last_report["errors"], 0)
                self.assertTrue(
                    all(
                        verify_p256(public_key(key), h, sig)
                        for h, sig in zip(digests, actual)
                    )
                )
                changed = bytes([actual[0][0] ^ 1]) + actual[0][1:]
                self.assertFalse(verify_p256(public_key(key), digests[0], changed))

    def test_reuse_switching_invalid_selection_and_max_batch(self):
        rt = self.runtime("full_window_w8")
        rt.load_key(0, bytes([1]) * 32, "p256")
        self.assertEqual(rt.p256_backend, "full_window_w8")
        reserved = rt.stats()["reserved_device_bytes"]
        self.assertGreaterEqual(reserved, 33 * 128 * 64)
        self.assertEqual(rt._cuda.lib.bc_set_p256_backend(rt._handle, 99), 1)
        self.assertEqual(rt.p256_backend, "full_window_w8")
        with self.assertRaises(ValueError):
            rt.set_p256_backend("automatic")
        digests = [hashlib.sha256(i.to_bytes(4, "big")).digest() for i in range(4096)]
        expected = Cpu().sign(bytes([1]) * 32, digests)
        for backend in ("full_window_w8", "comb_w8"):
            rt.set_p256_backend(backend)
            self.assertEqual(rt.sign(0, digests), expected)
            after = rt.stats()["reserved_device_bytes"]
            rt.sign(0, digests[:8])
            self.assertEqual(rt.stats()["reserved_device_bytes"], after)
        other = self.runtime()
        self.assertEqual(other.p256_backend, "reference")
        self.assertEqual(other.stats()["reserved_device_bytes"], 0)
