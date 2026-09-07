"""SPDX-License-Identifier: Apache-2.0. Experimental signed record hash lists.

Choose this profile explicitly for recipients who can receive the entire hash
list. Open the manifest once, then check individual records or the exact export.
Key trust, unique context, revocation, persistence and record meaning are caller
policy. Successful inclusion is not identity, payment, freshness or factual proof.
"""

from dataclasses import dataclass
import hashlib
import hmac

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from . import MAX_BATCH, MAX_PAYLOAD, ORDER, _messages
from .jws import sign_es256
from .receipts import _b64, _decode, _encode, _label, _unb64

PROFILE = "batchcrypto-record-manifest-v1"
MAX_MANIFEST_BYTES = 256 * 1024


def seal_manifest(records, *, context, key_id, sign_digests):
    """Return one ES256 JWS committing the ordered SHA-256 hashes of all records.

    Same input bounds and trusted signer callback as seal_records. No files,
    keys or GPU runtime are created. Callback failure returns no manifest.
    """
    _label(context)
    _label(key_id)
    records = _messages(records)
    if not records:
        raise ValueError("cannot seal an empty export")
    payload = _encode(
        {
            "profile": PROFILE,
            "context": context,
            "count": len(records),
            "hashes": [_b64(hashlib.sha256(record).digest()) for record in records],
        }
    )
    manifest = sign_es256([payload], key_id=key_id, sign_digests=sign_digests)[0]
    if len(manifest) > MAX_MANIFEST_BYTES:
        raise ValueError("manifest exceeds profile limit")
    return manifest


@dataclass(frozen=True)
class VerifiedManifest:
    """Local verification handle returned by open_manifest; never a wire format.

    Stores only immutable digest bytes and scope labels. Construct through
    open_manifest. Do not deserialize a Python object as evidence of verification.
    """

    context: str
    key_id: str
    _digests: tuple

    @property
    def count(self):
        return len(self._digests)

    def verify_record(self, record, *, expected_index):
        """Check exact bytes at a caller-supplied zero-based position."""
        if (
            not isinstance(record, bytes)
            or len(record) > MAX_PAYLOAD
            or type(expected_index) is not int
            or not 0 <= expected_index < self.count
        ):
            return False
        return hmac.compare_digest(
            hashlib.sha256(record).digest(), self._digests[expected_index]
        )

    def verify_all(self, records):
        """Check the complete ordered export, including exact count.

        Input-shape failures return False. Exceptions raised by caller-provided
        iterators propagate; no partial success is returned.
        """
        try:
            records = _messages(records)
        except (TypeError, ValueError):
            return False
        return len(records) == self.count and all(
            self.verify_record(record, expected_index=index)
            for index, record in enumerate(records)
        )


def open_manifest(manifest, public_key, *, key_id, context):
    """Verify a signed hash list once and return VerifiedManifest, or None.

    Caller independently configures a trusted P-256 public key, key id and
    export context. Invalid trusted configuration raises. Malformed/untrusted
    signed input returns None. No manifest/profile/key is fetched from a network.
    Reopen or discard the returned handle when your trust policy changes.
    """
    _label(context)
    _label(key_id)
    if not isinstance(public_key, bytes):
        raise ValueError("public_key must be encoded P-256 point bytes")
    key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), public_key)
    if (
        not isinstance(manifest, str)
        or not manifest.isascii()
        or len(manifest) > MAX_MANIFEST_BYTES
    ):
        return None
    try:
        header_part, payload_part, signature_part = manifest.split(".")
        if _decode(_unb64(header_part)) != {"alg": "ES256", "kid": key_id}:
            return None
        signature = _unb64(signature_part)
        if len(signature) != 64:
            return None
        r = int.from_bytes(signature[:32], "big")
        s = int.from_bytes(signature[32:], "big")
        if not 0 < r < ORDER or not 0 < s <= ORDER // 2:
            return None
        key.verify(
            utils.encode_dss_signature(r, s),
            (header_part + "." + payload_part).encode("ascii"),
            ec.ECDSA(hashes.SHA256()),
        )
        payload = _decode(_unb64(payload_part))
        if (
            set(payload) != {"profile", "context", "count", "hashes"}
            or payload["profile"] != PROFILE
            or payload["context"] != context
        ):
            return None
        count, digests = payload["count"], payload["hashes"]
        if (
            type(count) is not int
            or not 1 <= count <= MAX_BATCH
            or not isinstance(digests, list)
            or len(digests) != count
        ):
            return None
        decoded = tuple(_unb64(value) for value in digests)
        if any(len(value) != 32 for value in decoded):
            return None
        return VerifiedManifest(context, key_id, decoded)
    except (ValueError, TypeError, UnicodeError, RecursionError, InvalidSignature):
        return None
