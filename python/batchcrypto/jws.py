"""SPDX-License-Identifier: Apache-2.0. Bounded ES256 compact-JWS construction.

This module encodes and signs; it does not parse JWTs or authorize access.
The trusted callback receives SHA-256 digests and returns raw P-256 r||s.
Use VerifiedSigner for GPU callbacks. Consumers must pin their algorithm/key
and enforce issuer, audience, lifetime, scope and redemption policy separately.
"""

import base64
import hashlib
import json

from . import ORDER, _batch, _messages


def _b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=")


def sign_es256(payloads, *, key_id, sign_digests):
    """Sign a bounded batch of byte payloads using JWS ES256 (RFC 7515/7518).

    key_id is trusted issuer configuration, never an algorithm/key selector
    supplied by a token consumer. The callback owns key/epoch policy. No token
    is returned if the callback fails or returns malformed/non-low-s output.
    Payload bytes are preserved exactly; JSON serialization belongs to callers.
    """
    if (
        not isinstance(key_id, str)
        or not 1 <= len(key_id) <= 128
        or not key_id.isascii()
        or not key_id.isprintable()
    ):
        raise ValueError("key_id must be 1..128 printable ASCII characters")
    payloads = _messages(payloads)
    header = _b64(
        json.dumps({"alg": "ES256", "kid": key_id}, separators=(",", ":")).encode()
    )
    inputs = [header + b"." + _b64(payload) for payload in payloads]
    signatures = _batch(sign_digests([hashlib.sha256(x).digest() for x in inputs]))
    if len(signatures) != len(inputs):
        raise ValueError("signature count mismatch")
    for signature in signatures:
        if not isinstance(signature, bytes) or len(signature) != 64:
            raise ValueError("ES256 requires a 64-byte raw signature")
        r, s = (
            int.from_bytes(signature[:32], "big"),
            int.from_bytes(signature[32:], "big"),
        )
        if not 0 < r < ORDER or not 0 < s <= ORDER // 2:
            raise ValueError("signer must return valid low-s P-256 scalars")
    return [
        (value + b"." + _b64(sig)).decode("ascii")
        for value, sig in zip(inputs, signatures)
    ]
