"""SPDX-License-Identifier: Apache-2.0. Synthetic issuer keys and pinned consumer."""

from concurrent.futures import ThreadPoolExecutor
import json
import threading

import jwt
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from batchcrypto import ORDER
from batchcrypto.jws import sign_es256
from batchcrypto.verified import VerifiedSigner


class Keys:
    """One issuer, one current epoch; retained public pins for old credentials.

    CPU caches its private key and uses OpenSSL's randomized ECDSA. GPU signs a
    ready batch with VerifiedSigner, including its independent output check.
    Rotation is a trusted in-process operation. Keys are ephemeral test keys.
    """

    def __init__(self, mode="cpu", *, workers=4, library=None, device=0):
        if mode not in ("cpu", "gpu") or not 1 <= workers <= 32:
            raise ValueError("invalid signer configuration")
        self.mode = mode
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=workers)
        self.gpu = VerifiedSigner(library, device) if mode == "gpu" else None
        self.pins = {}
        self.epoch = 0
        self.signatures = 0
        self.batches = []
        self.rotate()

    def rotate(self):
        with self.lock:
            private = ec.generate_private_key(ec.SECP256R1())
            if self.gpu:
                self.epoch = self.gpu.load_key(
                    0, private.private_numbers().private_value.to_bytes(32, "big"),
                    expected_epoch=self.epoch,
                )
            else:
                self.epoch += 1
            self.private = private
            self.kid = f"synthetic-epoch-{self.epoch}"
            self.pins[self.kid] = private.public_key()
            return self.kid

    def sign(self, claims):
        with self.lock:
            def cpu(digest):
                der = self.private.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
                r, s = utils.decode_dss_signature(der)
                return r.to_bytes(32, "big") + min(s, ORDER - s).to_bytes(32, "big")

            def batch(digests):
                if self.gpu:
                    return self.gpu.sign(0, digests, expected_epoch=self.epoch)
                return list(self.pool.map(cpu, digests))

            tokens = sign_es256(
                [json.dumps(c, sort_keys=True, separators=(",", ":")).encode() for c in claims],
                key_id=self.kid, sign_digests=batch,
            )
            self.signatures += len(tokens)
            self.batches.append(len(tokens))
            return self.kid, tokens

    def close(self):
        self.pool.shutdown(wait=True)
        if self.gpu:
            self.gpu.close()


class Consumer:
    """Independently verifies each immutable token once, then checks exact scope.

    Online clearing still checks expiry, revocation, ownership and spent state
    on every new access. This cache never grants offline redemption rights.
    """

    def __init__(self, pins):
        self.pins = pins
        self.cache = {}
        self.lock = threading.Lock()
        self.verifications = 0

    def verify(self, token, *, buyer, book):
        from .ledger import Denied

        if not isinstance(token, str) or not 1 <= len(token) <= 4096:
            raise Denied("invalid token")
        with self.lock:
            claims = self.cache.get(token)
            if claims is None:
                try:
                    header = jwt.get_unverified_header(token)
                    kid = header.get("kid")
                    if header != {"alg": "ES256", "kid": kid} or kid not in self.pins:
                        raise Denied("untrusted key or header")
                    claims = jwt.decode(
                        token, self.pins[kid], algorithms=["ES256"],
                        issuer="local-reference", audience="publisher",
                        options={"require": ["iss", "aud", "sub", "iat", "exp", "jti"],
                                 "verify_exp": False, "verify_iat": False},
                    )
                except (jwt.PyJWTError, ValueError, TypeError) as exc:
                    raise Denied("invalid signature or claims") from exc
                if len(self.cache) >= 4096:
                    self.cache.clear()
                self.cache[token] = claims
                self.verifications += 1
            if claims.get("sub") != buyer or claims.get("jti") != book:
                raise Denied("wrong buyer or book")
            if claims.get("scope") != "content:read" or claims.get("profile") != "local-http-v1":
                raise Denied("wrong profile")
            return claims
