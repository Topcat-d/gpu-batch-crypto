"""SPDX-License-Identifier: Apache-2.0. Signed hash-list contracts and consumers."""

import base64
from dataclasses import FrozenInstanceError
import hashlib
import itertools
import json
from pathlib import Path
import unittest
from unittest.mock import Mock

from batchcrypto import (
    Cpu,
    MAX_BATCH,
    MAX_PAYLOAD,
    ORDER,
    generate_p256_key,
    public_key,
)
from batchcrypto.jws import sign_es256
from batchcrypto.manifests import (
    MAX_MANIFEST_BYTES,
    PROFILE,
    open_manifest,
    seal_manifest,
)
from batchcrypto.receipts import ReceiptVerifier, seal_records


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.key = generate_p256_key()
        self.public = public_key(self.key)
        self.records = [b"", b"record-1", b"\x00\xff"]
        self.sign = lambda hs: Cpu().sign(self.key, hs)

    def seal(self, records=None):
        return seal_manifest(
            self.records if records is None else records,
            context="export-1",
            key_id="key-1",
            sign_digests=self.sign,
        )

    def open(self, token, **options):
        return open_manifest(
            token,
            options.get("public", self.public),
            context=options.get("context", "export-1"),
            key_id=options.get("key_id", "key-1"),
        )

    def signed_claims(self, claims):
        return sign_es256(
            [json.dumps(claims).encode()], key_id="key-1", sign_digests=self.sign
        )[0]

    def test_complete_export_and_individual_exact_bytes(self):
        verified = self.open(self.seal())
        self.assertIsNotNone(verified)
        self.assertEqual(
            (verified.count, verified.context, verified.key_id),
            (3, "export-1", "key-1"),
        )
        self.assertTrue(verified.verify_all(iter(self.records)))
        for index, record in enumerate(self.records):
            self.assertTrue(verified.verify_record(record, expected_index=index))
            self.assertFalse(
                verified.verify_record(record + b"changed", expected_index=index)
            )
        for records in (
            [],
            self.records[:-1],
            self.records + [b"extra"],
            list(reversed(self.records)),
            [self.records[0]] * 3,
            ["wrong type"],
            itertools.repeat(b"x"),
        ):
            self.assertFalse(verified.verify_all(records))
        for index in (-1, 3, True, 1.0, "1"):
            self.assertFalse(verified.verify_record(b"record-1", expected_index=index))
        self.assertFalse(
            verified.verify_record(b"x" * (MAX_PAYLOAD + 1), expected_index=1)
        )
        with self.assertRaises(FrozenInstanceError):
            verified.context = "changed"

    def test_duplicate_bytes_require_embedded_ids_for_distinct_identity(self):
        checked = self.open(self.seal([b"same", b"same"]))
        self.assertTrue(checked.verify_record(b"same", expected_index=0))
        self.assertTrue(checked.verify_record(b"same", expected_index=1))
        self.assertFalse(checked.verify_all([b"same"]))

    def test_independent_jose_hashes_and_one_signature(self):
        signer = Mock(wraps=self.sign)
        token = seal_manifest(
            self.records, context="export-1", key_id="key-1", sign_digests=signer
        )
        self.assertEqual(signer.call_count, 1)
        self.assertEqual(len(signer.call_args.args[0]), 1)
        try:
            import jwt
        except ImportError:
            self.skipTest("install .[interop] for independent JWS verification")
        from cryptography.hazmat.primitives.asymmetric import ec

        key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), self.public)
        self.assertEqual(
            jwt.decode(token, key, algorithms=["ES256"]),
            {
                "profile": PROFILE,
                "context": "export-1",
                "count": 3,
                "hashes": [b64(hashlib.sha256(r).digest()) for r in self.records],
            },
        )

    def test_profile_key_context_and_signature_separation(self):
        token = self.seal()
        for options in (
            {"public": public_key(generate_p256_key())},
            {"key_id": "other"},
            {"context": "other"},
        ):
            self.assertIsNone(self.open(token, **options))
        merkle = seal_records(
            self.records, context="export-1", key_id="key-1", sign_digests=self.sign
        )
        self.assertIsNone(self.open(merkle.manifest))
        receipt = json.dumps({"manifest": token, "index": 0, "path": []}).encode()
        self.assertFalse(
            ReceiptVerifier(self.public, key_id="key-1", context="export-1").verify(
                self.records[0], receipt, expected_index=0
            )
        )
        head, payload, signature = token.split(".")
        raw = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        high_s = raw[:32] + (ORDER - int.from_bytes(raw[32:], "big")).to_bytes(
            32, "big"
        )
        for changed in (
            head + "." + payload + "." + b64(high_s),
            head + "." + payload + "." + b64(bytes(64)),
            head + "." + payload + "." + signature + "=",
            b64(b'{"alg":"none","kid":"key-1"}') + "." + payload + "." + signature,
        ):
            self.assertIsNone(self.open(changed))

    def test_signed_malformed_lists_and_duplicate_fields_rejected(self):
        valid = {
            "profile": PROFILE,
            "context": "export-1",
            "count": 1,
            "hashes": [b64(bytes(32))],
        }
        invalid = [{**valid, "count": n} for n in (0, True, 1.0, MAX_BATCH + 1, 2)]
        invalid += [
            {**valid, "hashes": hs}
            for hs in (
                None,
                {},
                [],
                [None],
                ["!"],
                [b64(bytes(31))],
                [b64(bytes(32)) + "="],
                [b64(bytes(32)), b64(bytes(32))],
            )
        ]
        invalid += [{**valid, "profile": "unknown"}, {**valid, "extra": True}]
        for claims in invalid:
            self.assertIsNone(self.open(self.signed_claims(claims)))
        duplicate = json.dumps(valid).encode()[:-1] + b',"count":1}'
        token = sign_es256([duplicate], key_id="key-1", sign_digests=self.sign)[0]
        self.assertIsNone(self.open(token))

    def test_wire_and_configuration_bounds(self):
        for token in (
            None,
            b"token",
            [],
            "",
            "a.b.c.d",
            "x" * (MAX_MANIFEST_BYTES + 1),
            "\u2603",
        ):
            self.assertIsNone(self.open(token))
        for options in (
            {"context": ""},
            {"key_id": "\n"},
            {"public": "key"},
            {"public": bytes(65)},
        ):
            with self.assertRaises(ValueError):
                self.open(self.seal(), **options)
        for records in (
            [],
            ["x"],
            [bytes(MAX_PAYLOAD + 1)],
            itertools.repeat(b"x"),
            [bytes(MAX_PAYLOAD)] * 65,
        ):
            with self.assertRaises(ValueError):
                self.seal(records)
        for output in ([], [bytes(64)]):
            with self.assertRaises(ValueError):
                seal_manifest(
                    [b"x"],
                    context="x",
                    key_id="x",
                    sign_digests=lambda _, output=output: output,
                )

    def test_maximum_export_and_labels_fit_profile(self):
        records = [str(index).encode() for index in range(MAX_BATCH)]
        token = seal_manifest(
            records, context='"' * 128, key_id="\\" * 128, sign_digests=self.sign
        )
        self.assertLessEqual(len(token), MAX_MANIFEST_BYTES)
        checked = open_manifest(
            token, self.public, context='"' * 128, key_id="\\" * 128
        )
        self.assertTrue(checked.verify_all(records))
        self.assertFalse(checked.verify_all(records[:-1]))

    def test_frozen_conformance_vector(self):
        fixture = json.loads(
            (Path(__file__).parent / "vectors/record-manifest-v1.json").read_text(
                encoding="utf-8"
            )
        )
        records = [bytes.fromhex(value) for value in fixture["records_hex"]]
        key = fixture["synthetic_private_scalar"].to_bytes(32, "big")
        token = seal_manifest(
            records,
            context=fixture["context"],
            key_id=fixture["key_id"],
            sign_digests=lambda hs: Cpu().sign(key, hs),
        )
        self.assertEqual(token, fixture["manifest"])
        checked = open_manifest(
            token,
            bytes.fromhex(fixture["public_key_hex"]),
            context=fixture["context"],
            key_id=fixture["key_id"],
        )
        self.assertTrue(checked.verify_all(records))


if __name__ == "__main__":
    unittest.main()
