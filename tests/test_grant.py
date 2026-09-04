"""SPDX-License-Identifier: Apache-2.0."""

import copy
import hashlib
import importlib.util
import os
from pathlib import Path
import unittest
from batchcrypto import Runtime, generate_p256_key, public_key

spec = importlib.util.spec_from_file_location(
    "content_grant", Path(__file__).resolve().parents[1] / "examples/content_grant.py"
)
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)


class GrantTests(unittest.TestCase):
    def test_interoperability_and_tamper(self):
        aes = os.urandom(32)
        sk = generate_p256_key()
        content = b"licensed article"
        now = 1700000000
        rt = (
            Runtime(os.environ["BC_LIBRARY"], int(os.environ.get("BC_DEVICE", "0")))
            if os.environ.get("BC_LIBRARY")
            else None
        )
        try:
            if rt:
                rt.load_key(0, aes)
                rt.load_key(1, sk, "p256")
            grant, ct, sig = example.publish(content, aes, sk, now, rt)
        finally:
            if rt:
                rt.close()
        pub = public_key(sk)
        cid = hashlib.sha256(content).hexdigest()
        self.assertEqual(example.consume(grant, ct, sig, aes, pub, cid, now), content)
        for field in (
            "principal",
            "content_id",
            "content_length",
            "publisher_id",
            "content_type",
            "key_id",
            "issued_at",
            "expires_at",
            "terms_hash",
        ):
            bad = copy.deepcopy(grant)
            bad[field] = str(bad[field]) + "tampered"
            with self.assertRaises(ValueError):
                example.consume(bad, ct, sig, aes, pub, cid, now)
        for changed_ct, changed_sig, changed_key in (
            (ct[:-1] + bytes([ct[-1] ^ 1]), sig, aes),
            (ct, sig[:-1] + bytes([sig[-1] ^ 1]), aes),
            (ct, sig, os.urandom(32)),
        ):
            with self.assertRaises(ValueError):
                example.consume(
                    grant, changed_ct, changed_sig, changed_key, pub, cid, now
                )
        with self.assertRaises(ValueError):
            example.consume(grant, ct, sig, aes, pub, cid, now + 301)
        with self.assertRaises(ValueError):
            example.consume(grant, ct, sig, aes, pub, cid, now - 1)
        with self.assertRaises(ValueError):
            example.consume(
                grant, ct, sig, aes, pub, cid, now, principal="someone-else"
            )
        with self.assertRaises(ValueError):
            example.consume(
                grant, ct, sig, aes, public_key(generate_p256_key()), cid, now
            )
