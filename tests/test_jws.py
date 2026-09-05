"""SPDX-License-Identifier: Apache-2.0. Independent JOSE-consumer checks."""

import base64
import json
import os
import time
import unittest

try:
    import jwt
except ImportError:
    jwt = None
from cryptography.hazmat.primitives.asymmetric import ec, ed25519

from batchcrypto import Cpu, MAX_BATCH, generate_p256_key
from batchcrypto.jws import sign_es256
from batchcrypto.verified import VerifiedSigner


@unittest.skipUnless(jwt is not None, "install .[interop] for independent JOSE tests")
class JwsTests(unittest.TestCase):
    def setUp(self):
        self.raw = generate_p256_key()
        self.public = ec.derive_private_key(
            int.from_bytes(self.raw, "big"), ec.SECP256R1()
        ).public_key()
        now = int(time.time())
        self.claims = {
            "iss": "issuer.example",
            "aud": "publisher.example",
            "sub": "buyer-1",
            "iat": now,
            "exp": now + 60,
            "jti": "transaction-1",
            "scope": "content:read",
            "content_sha256": "a" * 64,
        }
        self.payload = json.dumps(self.claims, separators=(",", ":")).encode()

    def decode(self, token, public=None, **options):
        return jwt.decode(
            token,
            public or self.public,
            algorithms=["ES256"],
            audience=options.pop("audience", "publisher.example"),
            issuer=options.pop("issuer", "issuer.example"),
            options={"require": ["iss", "aud", "sub", "iat", "exp", "jti"]},
            **options,
        )

    def tokens(self, payloads=None):
        return sign_es256(
            payloads or [self.payload],
            key_id="issuer-epoch-1",
            sign_digests=lambda h: Cpu().sign(self.raw, h),
        )

    def test_external_consumer_and_exact_payload(self):
        tokens = self.tokens([self.payload, self.payload + b" "])
        self.assertEqual([self.decode(t) for t in tokens], [self.claims] * 2)
        self.assertEqual(
            jwt.get_unverified_header(tokens[0]),
            {"alg": "ES256", "kid": "issuer-epoch-1"},
        )
        self.assertNotEqual(tokens[0], tokens[1])

    def test_wrong_identity_algorithm_key_and_tamper_rejected(self):
        token = self.tokens()[0]
        with self.assertRaises(jwt.InvalidAudienceError):
            self.decode(token, audience="other.example")
        with self.assertRaises(jwt.InvalidIssuerError):
            self.decode(token, issuer="other.example")
        with self.assertRaises(jwt.InvalidSignatureError):
            self.decode(token, ec.generate_private_key(ec.SECP256R1()).public_key())
        with self.assertRaises(jwt.InvalidAlgorithmError):
            jwt.decode(token, self.public, algorithms=["EdDSA"])
        header, payload, signature = token.split(".")
        replacement = (
            base64.urlsafe_b64encode(b'{"alg":"EdDSA","kid":"issuer-epoch-1"}')
            .rstrip(b"=")
            .decode()
        )
        with self.assertRaises(jwt.InvalidAlgorithmError):
            self.decode(".".join([replacement, payload, signature]))
        changed = (
            base64.urlsafe_b64encode(self.payload.replace(b"buyer-1", b"buyer-2"))
            .rstrip(b"=")
            .decode()
        )
        with self.assertRaises(jwt.InvalidSignatureError):
            self.decode(".".join([header, changed, signature]))

    def test_expiry_rejected(self):
        payload = json.dumps({**self.claims, "iat": 1, "exp": 2}).encode()
        with self.assertRaises(jwt.ExpiredSignatureError):
            self.decode(self.tokens([payload])[0])

    def test_bounded_inputs_and_failed_output(self):
        for kid in ("", "\n", "x" * 129, "é"):
            with self.assertRaises(ValueError):
                sign_es256([b"x"], key_id=kid, sign_digests=lambda _: [])
        with self.assertRaises(ValueError):
            self.tokens([b"x"] * (MAX_BATCH + 1))
        for output in ([], [b"x"], [bytes(64)]):
            with self.assertRaises(ValueError):
                sign_es256(
                    [b"x"], key_id="k", sign_digests=lambda _, output=output: output
                )

    def test_eddsa_remains_a_separate_explicit_profile(self):
        private = ed25519.Ed25519PrivateKey.generate()
        token = jwt.encode(self.claims, private, algorithm="EdDSA")
        decoded = jwt.decode(
            token,
            private.public_key(),
            algorithms=["EdDSA"],
            audience="publisher.example",
            issuer="issuer.example",
        )
        self.assertEqual(decoded, self.claims)
        with self.assertRaises(jwt.InvalidAlgorithmError):
            self.decode(token)

    @unittest.skipUnless(os.environ.get("BC_LIBRARY"), "set BC_LIBRARY for GPU interop")
    def test_gpu_batch_external_consumer_and_epoch(self):
        with VerifiedSigner(
            os.environ["BC_LIBRARY"],
            device=int(os.environ.get("BC_DEVICE", "0")),
        ) as signer:
            epoch = signer.load_key(0, self.raw)
            payloads = [
                json.dumps(
                    {**self.claims, "jti": f"transaction-{i}"}, separators=(",", ":")
                ).encode()
                for i in range(256)
            ]
            tokens = sign_es256(
                payloads,
                key_id="issuer-epoch-1",
                sign_digests=lambda h: signer.sign(0, h, expected_epoch=epoch),
            )
            self.assertEqual(
                [self.decode(t)["jti"] for t in tokens],
                [f"transaction-{i}" for i in range(256)],
            )
            signer.load_key(0, generate_p256_key(), expected_epoch=epoch)
            with self.assertRaises(RuntimeError):
                sign_es256(
                    payloads,
                    key_id="issuer-epoch-1",
                    sign_digests=lambda h: signer.sign(0, h, expected_epoch=epoch),
                )


if __name__ == "__main__":
    unittest.main()
