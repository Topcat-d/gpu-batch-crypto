"""SPDX-License-Identifier: Apache-2.0. Experimental offline record receipts.

RFC 9162 SHA-256 inclusion trees, with a project-specific ES256 signed root.
This proves exact-byte inclusion under a caller-pinned key/context/index. It
does not establish truth, identity, freshness, payment, or log consistency.
"""

import base64
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import hmac
import json
import threading

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from . import MAX_BATCH, MAX_PAYLOAD, ORDER, _messages
from .jws import sign_es256

PROFILE = "batchcrypto-record-receipt-v1"
MAX_RECEIPT_BYTES = 4096
MAX_MANIFEST_BYTES = 2048
MAX_PROOF_NODES = 12  # ceil(log2(MAX_BATCH=4096))


def _encode(value):
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("ascii")


def _b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value):
    if not isinstance(value, str) or not value or not value.isascii():
        raise ValueError("invalid base64url")
    data = base64.b64decode(
        value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
    )
    if _b64(data) != value:
        raise ValueError("non-canonical base64url")
    return data


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _decode(data):
    value = json.loads(data.decode("utf-8"), object_pairs_hook=_object)
    if not isinstance(value, dict):
        raise ValueError("expected JSON object")
    return value


def _label(value):
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 128
        or not value.isascii()
        or not value.isprintable()
    ):
        raise ValueError("context and key_id require 1..128 printable ASCII characters")


def _leaf(record):
    return hashlib.sha256(b"\x00" + record).digest()


def _node(left, right):
    return hashlib.sha256(b"\x01" + left + right).digest()


def _tree(records):
    # Uneven trees split at the largest power of two strictly below the size.
    # Build each node once, appending siblings from leaf to root to each proof.
    paths = [[] for _ in records]

    def build(start, size):
        if size == 1:
            return _leaf(records[start])
        split = 1 << ((size - 1).bit_length() - 1)
        left = build(start, split)
        right = build(start + split, size - split)
        for index in range(start, start + split):
            paths[index].append(right)
        for index in range(start + split, start + size):
            paths[index].append(left)
        return _node(left, right)

    return build(0, len(records)), tuple(tuple(path) for path in paths)


def _included(record, index, size, path, root):
    # RFC 9162 section 2.1.3.2; no sorting, padding, or duplicated odd leaves.
    fn, sn = index, size - 1
    value = _leaf(record)
    for sibling in path:
        if sn == 0:
            return False
        if fn & 1 or fn == sn:
            value = _node(sibling, value)
            while fn and not fn & 1:
                fn >>= 1
                sn >>= 1
        else:
            value = _node(value, sibling)
        fn >>= 1
        sn >>= 1
    return sn == 0 and hmac.compare_digest(value, root)


@dataclass(frozen=True)
class SealedBatch:
    """Immutable signed root and inclusion paths; retains no record bytes/keys."""

    manifest: str
    paths: tuple

    def receipt(self, index, *, include_manifest=True):
        """Return UTF-8 JSON proof; include signed manifest for standalone use.

        A recipient processing many records may receive self.manifest once and
        use include_manifest=False, passing manifest= to its verifier.
        """
        if type(index) is not int or not 0 <= index < len(self.paths):
            raise ValueError("index outside sealed batch")
        value = {"index": index, "path": [_b64(x) for x in self.paths[index]]}
        if include_manifest:
            value["manifest"] = self.manifest
        return _encode(value)


def seal_records(records, *, context, key_id, sign_digests):
    """Sign one root for 1..4096 exact byte records with a trusted callback.

    Records: <=1 MiB each, <=64 MiB aggregate working input (core bounds).
    Caller owns serialization, unique export context, key custody and retention.
    Callback receives one SHA-256 digest and returns one low-s raw P-256 r||s.
    Use VerifiedSigner for any GPU callback. Failures return no SealedBatch.
    """
    _label(context)
    _label(key_id)
    records = _messages(records)
    if not records:
        raise ValueError("cannot seal an empty export")
    root, paths = _tree(records)
    payload = _encode(
        {
            "profile": PROFILE,
            "context": context,
            "count": len(records),
            "root": _b64(root),
        }
    )
    manifest = sign_es256([payload], key_id=key_id, sign_digests=sign_digests)[0]
    return SealedBatch(manifest, paths)


class ReceiptVerifier:
    """Consumer with fixed trusted P-256 key, key id and export context.

    Caches up to 8 successfully verified signed roots, under a lock. Every
    record still has its exact bytes, expected index and full proof checked.
    Recreate for a new key/context or changed trust policy. No network/storage.
    """

    def __init__(self, public_key, *, key_id, context):
        _label(key_id)
        _label(context)
        if not isinstance(public_key, bytes):
            raise ValueError("public_key must be encoded P-256 point bytes")
        self._key = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), public_key
        )
        self._key_id, self._context = key_id, context
        self._cache = OrderedDict()
        self._lock = threading.Lock()

    def _manifest(self, token):
        if (
            not isinstance(token, str)
            or not token.isascii()
            or len(token) > MAX_MANIFEST_BYTES
        ):
            raise ValueError("invalid manifest")
        with self._lock:
            if token in self._cache:
                self._cache.move_to_end(token)
                return self._cache[token]
            header_part, payload_part, signature_part = token.split(".")
            header = _decode(_unb64(header_part))
            if header != {"alg": "ES256", "kid": self._key_id}:
                raise ValueError("unexpected signature profile or key id")
            payload = _decode(_unb64(payload_part))
            if (
                set(payload) != {"profile", "context", "count", "root"}
                or payload["profile"] != PROFILE
                or payload["context"] != self._context
            ):
                raise ValueError("unexpected record profile or context")
            count = payload["count"]
            if type(count) is not int or not 1 <= count <= MAX_BATCH:
                raise ValueError("invalid signed record count")
            root = _unb64(payload["root"])
            signature = _unb64(signature_part)
            if len(root) != 32 or len(signature) != 64:
                raise ValueError("invalid root or signature size")
            r, s = int.from_bytes(signature[:32], "big"), int.from_bytes(
                signature[32:], "big"
            )
            if not 0 < r < ORDER or not 0 < s <= ORDER // 2:
                raise ValueError("invalid or non-low-s signature")
            signed = (header_part + "." + payload_part).encode("ascii")
            self._key.verify(
                utils.encode_dss_signature(r, s), signed, ec.ECDSA(hashes.SHA256())
            )
            self._cache[token] = (root, count)
            if len(self._cache) > 8:
                self._cache.popitem(last=False)
            return root, count

    def verify(self, record, receipt, *, expected_index, manifest=None):
        """Return bool; reject malformed, oversized or untrusted wire inputs.

        expected_index is caller policy, never copied blindly from the receipt.
        A True result only attests inclusion, not permission or record semantics.
        Pass manifest= only for a proof produced with include_manifest=False;
        it is verified under the same fixed key/context, never blindly trusted.
        """
        if (
            not isinstance(record, bytes)
            or len(record) > MAX_PAYLOAD
            or not isinstance(receipt, bytes)
            or len(receipt) > MAX_RECEIPT_BYTES
            or type(expected_index) is not int
            or not 0 <= expected_index < MAX_BATCH
        ):
            return False
        try:
            item = _decode(receipt)
            fields = (
                {"index", "path"}
                if manifest is not None
                else {"manifest", "index", "path"}
            )
            if (
                set(item) != fields
                or type(item["index"]) is not int
                or item["index"] != expected_index
            ):
                return False
            proof = item["path"]
            if not isinstance(proof, list) or len(proof) > MAX_PROOF_NODES:
                return False
            path = [_unb64(value) for value in proof]
            if any(len(node) != 32 for node in path):
                return False
            root, count = self._manifest(
                manifest if manifest is not None else item["manifest"]
            )
            return expected_index < count and _included(
                record, expected_index, count, path, root
            )
        except (ValueError, TypeError, UnicodeError, RecursionError, InvalidSignature):
            return False
