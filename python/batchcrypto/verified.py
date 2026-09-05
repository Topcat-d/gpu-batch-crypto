"""SPDX-License-Identifier: Apache-2.0.

Fail-closed GPU signing with a CPU-derived public-key pin and exact key epochs.
This checks output correctness; it does not address GPU key leakage or isolation.
"""

import threading

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

from . import ORDER, Runtime, _digests


class VerificationError(RuntimeError):
    """Backend output or execution could not be trusted; signer is quarantined."""


class VerifiedSigner:
    """Own a GPU runtime and verify every signature before returning a batch.

    Callers supply a required epoch on every signing request. Only public-key
    objects are cached in Python after import. Native key slots retain host keys.
    Any backend/output failure closes the runtime; recreate it after investigation.
    Use synthetic keys until the documented execution boundary is acceptable.
    """

    def __init__(self, library, device=0, p256_backend="full_window_w8"):
        self._lock = threading.RLock()
        self._keys = {}
        self._closed = False
        self._runtime = Runtime(library, device, p256_backend)
        if not hasattr(self._runtime._cuda.lib, "bc_sign_at_epoch"):
            self.close()
            raise RuntimeError("VerifiedSigner requires native library v0.3+")

    def _live(self):
        if self._closed:
            raise RuntimeError("verified signer is closed or quarantined")

    def _fault(self, message):
        self.close()
        raise VerificationError(message)

    def load_key(self, slot, key, *, expected_epoch=0):
        Runtime._slot(slot)
        Runtime._epoch(expected_epoch)
        _digests(key, [])
        public = ec.derive_private_key(
            int.from_bytes(key, "big"), ec.SECP256R1()
        ).public_key()
        encoded = public.public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        with self._lock:
            self._live()
            epoch = self._runtime.load_key(slot, key, "p256", expected_epoch)
            try:
                actual, used_epoch = self._runtime.public_key(slot)
                if actual != encoded or used_epoch != epoch:
                    self._fault("public-key export failed independent verification")
            except Exception as exc:
                self.close()
                raise VerificationError(
                    "public-key validation failed; signer closed"
                ) from exc
            self._keys[slot] = (epoch, public, encoded)
            return epoch

    def public_key(self, slot):
        Runtime._slot(slot)
        with self._lock:
            self._live()
            epoch, _, encoded = self._keys[slot]
            return encoded, epoch

    def retire_key(self, slot, *, expected_epoch):
        Runtime._slot(slot)
        Runtime._epoch(expected_epoch)
        with self._lock:
            self._live()
            epoch = self._runtime.retire_key(slot, expected_epoch)
            self._keys.pop(slot, None)
            return epoch

    def sign(self, slot, digests, *, expected_epoch):
        Runtime._slot(slot)
        Runtime._epoch(expected_epoch)
        digests = _digests((1).to_bytes(32, "big"), digests)
        with self._lock:
            self._live()
            entry = self._keys.get(slot)
            if entry is None or entry[0] != expected_epoch:
                raise RuntimeError("key slot or required epoch does not match")
            try:
                signatures = self._runtime.sign(
                    slot, digests, expected_epoch=expected_epoch
                )
                expected_report = {
                    "submitted": len(digests),
                    "completed": len(digests),
                    "errors": 0,
                    "key_epoch": expected_epoch,
                }
                if (
                    len(signatures) != len(digests)
                    or self._runtime.last_report != expected_report
                ):
                    self._fault("signing report failed verification")
                for digest, signature in zip(digests, signatures):
                    if not isinstance(signature, bytes) or len(signature) != 64:
                        self._fault("malformed signing output")
                    r = int.from_bytes(signature[:32], "big")
                    s = int.from_bytes(signature[32:], "big")
                    if not (0 < r < ORDER and 0 < s <= ORDER // 2):
                        self._fault("non-canonical signing output")
                    entry[1].verify(
                        utils.encode_dss_signature(r, s),
                        digest,
                        ec.ECDSA(utils.Prehashed(hashes.SHA256())),
                    )
            except Exception as exc:
                self.close()
                if isinstance(exc, VerificationError):
                    raise
                raise VerificationError(
                    "signing failed independent verification; signer closed"
                ) from exc
            return signatures

    def close(self):
        with self._lock:
            self._closed = True
            self._keys.clear()
            self._runtime.close()

    def __enter__(self):
        self._live()
        return self

    def __exit__(self, *exc):
        self.close()
