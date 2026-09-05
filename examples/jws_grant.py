"""SPDX-License-Identifier: Apache-2.0. Synthetic ES256 grant interoperability."""

import argparse
import json
import time

import jwt
from cryptography.hazmat.primitives.asymmetric import ec

from batchcrypto import Cpu, MAX_BATCH, generate_p256_key
from batchcrypto.jws import sign_es256
from batchcrypto.verified import VerifiedSigner


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--library", help="optional native GPU library; otherwise CPU")
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--count", type=int, default=256)
    args = parser.parse_args()
    if not 1 <= args.count <= MAX_BATCH or args.device < 0:
        parser.error("count must be 1..4096 and device nonnegative")
    private = generate_p256_key()
    public = ec.derive_private_key(
        int.from_bytes(private, "big"), ec.SECP256R1()
    ).public_key()
    now = int(time.time())
    claims = [
        {
            "iss": "issuer.example",
            "aud": "publisher.example",
            "sub": "synthetic-buyer",
            "iat": now,
            "exp": now + 300,
            "jti": f"synthetic-{i}",
            "scope": "content:read",
            "content_sha256": "a" * 64,
            "terms_sha256": "b" * 64,
        }
        for i in range(args.count)
    ]
    payloads = [json.dumps(c, separators=(",", ":")).encode() for c in claims]
    if args.library:
        with VerifiedSigner(args.library, device=args.device) as signer:
            epoch = signer.load_key(0, private)
            tokens = sign_es256(
                payloads,
                key_id="issuer-epoch-1",
                sign_digests=lambda h: signer.sign(0, h, expected_epoch=epoch),
            )
    else:
        tokens = sign_es256(
            payloads,
            key_id="issuer-epoch-1",
            sign_digests=lambda h: Cpu().sign(private, h),
        )
    for token, expected in zip(tokens, claims):
        # Trusted key/algorithm and policy are configured independently of token headers.
        actual = jwt.decode(
            token,
            public,
            algorithms=["ES256"],
            issuer="issuer.example",
            audience="publisher.example",
            options={"require": ["iss", "aud", "sub", "iat", "exp", "jti"]},
        )
        if actual != expected or jwt.get_unverified_header(token) != {
            "alg": "ES256",
            "kid": "issuer-epoch-1",
        }:
            raise ValueError("grant does not match the expected access")
    print(
        f"PASS: {len(tokens)} {'GPU' if args.library else 'CPU'} ES256 grants accepted by PyJWT {jwt.__version__}; synthetic permissions, no funds or redemption ledger."
    )


if __name__ == "__main__":
    main()
