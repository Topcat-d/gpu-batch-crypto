"""SPDX-License-Identifier: Apache-2.0. Controlled backend failures, not hardware fault injection."""

import hashlib
import os
import types
import unittest
from unittest.mock import patch

from batchcrypto import Cpu, ORDER, Runtime, Record, public_key
from batchcrypto.verified import VerifiedSigner, VerificationError


class FakeRuntime:
    _slot = staticmethod(Runtime._slot)
    _epoch = staticmethod(Runtime._epoch)

    def __init__(self, *args):
        self._cuda = types.SimpleNamespace(
            lib=types.SimpleNamespace(bc_sign_at_epoch=True)
        )
        self.closed = False
        self.epoch = 0
        self.fault = None

    def close(self):
        self.closed = True

    def load_key(self, slot, key, kind, expected_epoch):
        if self.epoch != expected_epoch:
            raise RuntimeError("epoch conflict")
        self.key = key
        self.epoch += 1
        return self.epoch

    def public_key(self, slot):
        return public_key(self.key), self.epoch

    def retire_key(self, slot, expected_epoch):
        if self.epoch != expected_epoch:
            raise RuntimeError("epoch conflict")
        self.epoch += 1
        return self.epoch

    def sign(self, slot, digests, *, expected_epoch):
        result = Cpu().sign(self.key, digests)
        self.last_report = dict(
            submitted=len(digests),
            completed=len(digests),
            errors=0,
            key_epoch=self.epoch,
        )
        if self.fault == "error":
            raise RuntimeError("device error")
        if self.fault == "epoch":
            self.last_report["key_epoch"] += 1
        if self.fault == "short":
            return result[:-1]
        if self.fault == "reorder":
            return list(reversed(result))
        if self.fault == "corrupt":
            result[-1] = bytes(64)
        if self.fault == "high_s":
            s = int.from_bytes(result[-1][32:], "big")
            result[-1] = result[-1][:32] + (ORDER - s).to_bytes(32, "big")
        return result


class VerifiedTests(unittest.TestCase):
    key = (1).to_bytes(32, "big")
    digests = [hashlib.sha256(x).digest() for x in (b"a", b"b")]

    def test_faults_release_no_batch_and_quarantine(self):
        for fault in ("error", "epoch", "short", "reorder", "corrupt", "high_s"):
            with (
                self.subTest(fault=fault),
                patch("batchcrypto.verified.Runtime", FakeRuntime),
            ):
                signer = VerifiedSigner(None)
                signer.load_key(0, self.key)
                signer._runtime.fault = fault
                with self.assertRaises(VerificationError):
                    signer.sign(0, self.digests, expected_epoch=1)
                self.assertTrue(signer._runtime.closed)
                with self.assertRaises(RuntimeError):
                    signer.sign(0, self.digests, expected_epoch=1)

    def test_public_key_pin_failure_quarantines(self):
        with patch("batchcrypto.verified.Runtime", FakeRuntime):
            signer = VerifiedSigner(None)
            with patch.object(
                signer._runtime, "public_key", return_value=(bytes(65), 1)
            ):
                with self.assertRaises(VerificationError):
                    signer.load_key(0, self.key)
            self.assertTrue(signer._runtime.closed)

    def test_success_rotation_retirement_and_empty(self):
        with (
            patch("batchcrypto.verified.Runtime", FakeRuntime),
            VerifiedSigner(None) as signer,
        ):
            self.assertEqual(signer.load_key(0, self.key), 1)
            self.assertEqual(signer.sign(0, [], expected_epoch=1), [])
            self.assertEqual(
                signer.sign(0, self.digests, expected_epoch=1),
                Cpu().sign(self.key, self.digests),
            )
            key2 = (2).to_bytes(32, "big")
            self.assertEqual(signer.load_key(0, key2, expected_epoch=1), 2)
            with self.assertRaises(RuntimeError):
                signer.sign(0, self.digests, expected_epoch=1)
            self.assertFalse(signer._runtime.closed)
            self.assertEqual(
                signer.sign(0, self.digests, expected_epoch=2),
                Cpu().sign(key2, self.digests),
            )
            self.assertEqual(signer.retire_key(0, expected_epoch=2), 3)
            with self.assertRaises(RuntimeError):
                signer.sign(0, self.digests, expected_epoch=3)

    @unittest.skipUnless(os.environ.get("BC_LIBRARY"), "native runtime only")
    def test_real_guarded_signer(self):
        with VerifiedSigner(
            os.environ["BC_LIBRARY"], int(os.environ.get("BC_DEVICE", "0"))
        ) as signer:
            epoch = signer.load_key(0, self.key)
            self.assertEqual(
                signer.sign(0, self.digests, expected_epoch=epoch),
                Cpu().sign(self.key, self.digests),
            )

    @unittest.skipUnless(os.environ.get("BC_LIBRARY"), "native runtime only")
    def test_native_required_epoch_all_operations(self):
        with Runtime(
            os.environ["BC_LIBRARY"], int(os.environ.get("BC_DEVICE", "0"))
        ) as rt:
            rt.load_key(0, self.key, "p256")
            rt.load_key(0, (2).to_bytes(32, "big"), "p256", expected_epoch=1)
            for values in ([], self.digests):
                with self.assertRaises(RuntimeError):
                    rt.sign(0, values, expected_epoch=1)
                self.assertEqual(
                    rt.last_report,
                    dict(submitted=0, completed=0, errors=0, key_epoch=2),
                )
            self.assertEqual(
                rt.sign(0, self.digests, expected_epoch=2),
                Cpu().sign((2).to_bytes(32, "big"), self.digests),
            )
            rt.load_key(1, bytes(32))
            record = Record(bytes(12), b"test", b"aad")
            sealed = rt.seal(1, [record], expected_epoch=1)[0]
            self.assertEqual(
                rt.open(
                    1, [Record(record.nonce, sealed, record.aad)], expected_epoch=1
                ),
                [record.data],
            )
            rt.retire_key(1, 1)
            for call, records in (
                (rt.seal, [record]),
                (rt.open, [Record(record.nonce, sealed, record.aad)]),
                (rt.seal, []),
                (rt.open, []),
            ):
                with self.assertRaises(RuntimeError):
                    call(1, records, expected_epoch=1)
                self.assertEqual(rt.last_report["submitted"], 0)
                self.assertEqual(rt.last_report["key_epoch"], 2)


if __name__ == "__main__":
    unittest.main()
