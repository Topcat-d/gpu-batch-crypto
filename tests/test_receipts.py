"""SPDX-License-Identifier: Apache-2.0. Record receipt contract/oracle checks."""

import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import itertools
import json
import unittest
from unittest.mock import Mock

from batchcrypto import Cpu, MAX_BATCH, MAX_PAYLOAD, generate_p256_key, public_key
from batchcrypto.jws import sign_es256
from batchcrypto.receipts import PROFILE, ReceiptVerifier, seal_records


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64(data):
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def encode(obj):
    return json.dumps(obj).encode()


def oracle_root(records):
    # Independent stack construction, RFC 9162 section 2.1.2.
    stack = []
    for index, record in enumerate(records):
        stack.append(hashlib.sha256(b"\0" + record).digest())
        value = index
        while value & 1:
            right, left = stack.pop(), stack.pop()
            stack.append(hashlib.sha256(b"\1" + left + right).digest())
            value >>= 1
    while len(stack) > 1:
        right, left = stack.pop(), stack.pop()
        stack.append(hashlib.sha256(b"\1" + left + right).digest())
    return stack[0]


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.key = generate_p256_key()
        self.public = public_key(self.key)
        self.sign = lambda digests: Cpu().sign(self.key, digests)

    def seal(self, records, **kw):
        return seal_records(
            records,
            context="export-1",
            key_id="key-1",
            sign_digests=kw.get("sign", self.sign),
        )

    def verifier(self, **kw):
        return ReceiptVerifier(
            kw.get("public", self.public),
            key_id=kw.get("key_id", "key-1"),
            context=kw.get("context", "export-1"),
        )

    def test_all_positions_uneven_trees_and_independent_root(self):
        for count in list(range(1, 66)) + [127, 129, 257, 4095, 4096]:
            records = [f"record:{index}".encode() for index in range(count)]
            batch = self.seal(records)
            payload = json.loads(unb64(batch.manifest.split(".")[1]))
            self.assertEqual(unb64(payload["root"]), oracle_root(records), count)
            verifier = self.verifier()
            for index, record in enumerate(records):
                self.assertTrue(
                    verifier.verify(record, batch.receipt(index), expected_index=index),
                    (count, index),
                )
        # Known SHA-256 of a zero byte: RFC leaf hashing of the empty record.
        empty = self.seal([b""])
        root = json.loads(unb64(empty.manifest.split(".")[1]))["root"]
        self.assertEqual(
            unb64(root).hex(),
            "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d",
        )
        self.assertTrue(self.verifier().verify(b"", empty.receipt(0), expected_index=0))

    def test_independent_jose_consumer(self):
        try:
            import jwt
        except ImportError:
            self.skipTest("install .[interop] for the independent JOSE consumer")
        batch = self.seal([b"one", b"two", b"three"])
        claims = jwt.decode(batch.manifest, self.verifier()._key, algorithms=["ES256"])
        self.assertEqual(
            claims,
            {
                "context": "export-1",
                "count": 3,
                "profile": PROFILE,
                "root": b64(oracle_root([b"one", b"two", b"three"])),
            },
        )

    def test_bytes_position_proof_and_trust_are_all_required(self):
        records = [b"same", b"same", b"three", b"four", b"five"]
        batch = self.seal(records)
        receipt = batch.receipt(1)
        verifier = self.verifier()
        self.assertTrue(verifier.verify(b"same", receipt, expected_index=1))
        for data, index in (
            (b"same ", 1),
            (b"same", 0),
            (b"same", -1),
            (b"same", True),
        ):
            self.assertFalse(verifier.verify(data, receipt, expected_index=index))
        for other in (
            self.verifier(public=public_key(generate_p256_key())),
            self.verifier(key_id="other"),
            self.verifier(context="other"),
        ):
            self.assertFalse(other.verify(b"same", receipt, expected_index=1))
        item = json.loads(receipt)
        for path in (
            [],
            item["path"][:-1],
            item["path"] + [b64(bytes(32))],
            list(reversed(item["path"])),
            [b64(bytes(32))] + item["path"][1:],
        ):
            self.assertFalse(
                verifier.verify(
                    b"same", encode({**item, "path": path}), expected_index=1
                )
            )
        # Identical bytes really ARE included at either identical leaf. An
        # application requiring distinct identities must encode an ID in bytes.
        self.assertTrue(
            verifier.verify(b"same", encode({**item, "index": 0}), expected_index=0)
        )
        self.assertFalse(
            verifier.verify(b"same", encode({**item, "index": 2}), expected_index=2)
        )

    def test_signed_but_invalid_manifest_policy_rejected(self):
        batch = self.seal([b"x"])
        payload = json.loads(unb64(batch.manifest.split(".")[1]))
        item = json.loads(batch.receipt(0))
        variants = [{**payload, "count": v} for v in (0, -1, True, 1.0, MAX_BATCH + 1)]
        variants += [
            {**payload, "profile": "another"},
            {**payload, "extra": 1},
            {**payload, "root": b64(b"short")},
            {**payload, "context": "another"},
        ]
        for variant in variants:
            token = sign_es256(
                [encode(variant)], key_id="key-1", sign_digests=self.sign
            )[0]
            self.assertFalse(
                self.verifier().verify(
                    b"x", encode({**item, "manifest": token}), expected_index=0
                )
            )
        duplicate = encode(payload)[:-1] + b',"count":1}'
        token = sign_es256([duplicate], key_id="key-1", sign_digests=self.sign)[0]
        self.assertFalse(
            self.verifier().verify(
                b"x", encode({**item, "manifest": token}), expected_index=0
            )
        )
        # Another tree shape signed by the right key must not reuse this proof.
        token = sign_es256(
            [encode({**payload, "count": 2})], key_id="key-1", sign_digests=self.sign
        )[0]
        self.assertFalse(
            self.verifier().verify(
                b"x", encode({**item, "manifest": token}), expected_index=0
            )
        )

    def test_malformed_and_oversized_inputs_fail_closed(self):
        item = json.loads(self.seal([b"x", b"y"]).receipt(0))
        variants = [
            None,
            [],
            b"",
            b"\xff",
            b"x" * 4097,
            b"[" * 1500,
            b'{"index":0,"index":0}',
            encode({**item, "extra": 0}),
        ]
        for value in (None, True, "0", -1, 4096):
            variants.append(encode({**item, "index": value}))
        for value in (
            None,
            {},
            [None],
            ["!"],
            [b64(bytes(31))],
            [b64(bytes(32)) + "="],
            [b64(bytes(32))] * 13,
        ):
            variants.append(encode({**item, "path": value}))
        for value in (None, [], "a.b.c.d", ".", "x" * 2049):
            variants.append(encode({**item, "manifest": value}))
        header, payload, signature = item["manifest"].split(".")
        for token in (
            header + "." + payload + "." + b64(bytes(64)),
            header + "." + payload + "." + signature + "=",
            b64(b'{"alg":"none","kid":"key-1"}') + "." + payload + "." + signature,
        ):
            variants.append(encode({**item, "manifest": token}))
        verifier = self.verifier()
        for value in variants:
            self.assertFalse(
                verifier.verify(b"x", value, expected_index=0), repr(value)[:100]
            )
        self.assertFalse(
            verifier.verify(b"x" * (MAX_PAYLOAD + 1), encode(item), expected_index=0)
        )
        self.assertFalse(verifier.verify("x", encode(item), expected_index=0))

    def test_seal_bounds_and_callback_failure_return_nothing(self):
        for records in (
            [],
            ["x"],
            [b"x" * (MAX_PAYLOAD + 1)],
            itertools.repeat(b"x"),
            [bytes(MAX_PAYLOAD)] * 65,
        ):
            with self.assertRaises(ValueError):
                self.seal(records)
        for output in ([], [bytes(64)], [b"x"], [bytes(64)] * 2):
            with self.assertRaises(ValueError):
                self.seal([b"x"], sign=lambda _, output=output: output)
        with self.assertRaises(RuntimeError):
            self.seal([b"x"], sign=Mock(side_effect=RuntimeError("signer failed")))
        for context in ("", "\n", "x" * 129, None):
            with self.assertRaises(ValueError):
                seal_records(
                    [b"x"], context=context, key_id="k", sign_digests=self.sign
                )
        batch = self.seal([b"x"])
        for index in (-1, 1, True, 0.0):
            with self.assertRaises(ValueError):
                batch.receipt(index)

    def test_bounded_cache_reuse_concurrency_and_eviction(self):
        verifier = self.verifier()
        verifier._key = Mock(wraps=verifier._key)
        records = [f"r{i}".encode() for i in range(32)]
        batch = self.seal(records)
        with ThreadPoolExecutor(max_workers=4) as executor:
            accepted = list(
                executor.map(
                    lambda i: verifier.verify(
                        records[i], batch.receipt(i), expected_index=i
                    ),
                    range(32),
                )
            )
        self.assertTrue(all(accepted))
        self.assertEqual(verifier._key.verify.call_count, 1)
        # Warm signature cache must never bypass checking record bytes.
        self.assertFalse(
            verifier.verify(b"changed", batch.receipt(0), expected_index=0)
        )
        for i in range(8):
            record = str(i).encode()
            self.assertTrue(
                verifier.verify(
                    record, self.seal([record]).receipt(0), expected_index=0
                )
            )
        self.assertEqual(len(verifier._cache), 8)
        self.assertTrue(verifier.verify(records[0], batch.receipt(0), expected_index=0))
        self.assertEqual(verifier._key.verify.call_count, 10)

    def test_shared_manifest_is_verified_and_cannot_conflict(self):
        batch = self.seal([b"one", b"two"])
        proof = batch.receipt(1, include_manifest=False)
        verifier = self.verifier()
        self.assertTrue(
            verifier.verify(b"two", proof, expected_index=1, manifest=batch.manifest)
        )
        self.assertFalse(
            verifier.verify(
                b"changed", proof, expected_index=1, manifest=batch.manifest
            )
        )
        self.assertFalse(verifier.verify(b"two", proof, expected_index=1))
        self.assertFalse(
            verifier.verify(
                b"two", batch.receipt(1), expected_index=1, manifest=batch.manifest
            )
        )
        for wrong in ("a.b.c", self.seal([b"one", b"other"]).manifest, "x" * 2049):
            self.assertFalse(
                verifier.verify(b"two", proof, expected_index=1, manifest=wrong)
            )
        self.assertFalse(
            self.verifier(context="wrong").verify(
                b"two", proof, expected_index=1, manifest=batch.manifest
            )
        )


if __name__ == "__main__":
    unittest.main()
