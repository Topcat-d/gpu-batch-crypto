"""Apache-2.0. Explicit CPU and CUDA backends; no automatic fallback.

Nonces must be unique per AES key over its entire lifetime. Random nonce
generation, durable counters, rotation, and key storage belong to the caller.
"""

import ctypes as C
import hashlib
import threading
from itertools import islice
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
MAX_BATCH, MAX_PAYLOAD, MAX_AAD = 4096, 1048576, 65536


@dataclass(frozen=True)
class Record:
    nonce: bytes
    data: bytes
    aad: bytes = b""


def _key(key):
    if not isinstance(key, bytes) or len(key) != 32:
        raise ValueError("key must be 32 bytes")


def _batch(items):
    """Bound consumption of arbitrary iterables before validation/allocation."""
    result = list(islice(items, MAX_BATCH + 1))
    if len(result) > MAX_BATCH:
        raise ValueError("batch exceeds 4096 items")
    return result


def _records(key, records, opening=False):
    _key(key)
    records = _batch(records)
    if len(records) > MAX_BATCH:
        raise ValueError("batch exceeds 4096 records")
    nonces = set()
    work = 0
    for r in records:
        if not isinstance(r, Record) or not all(
            isinstance(v, bytes) for v in (r.nonce, r.data, r.aad)
        ):
            raise ValueError("records require byte strings")
        if len(r.nonce) != 12 or len(r.aad) > MAX_AAD:
            raise ValueError("nonce/AAD length invalid")
        n = len(r.data) - (16 if opening else 0)
        if not 0 <= n <= MAX_PAYLOAD:
            raise ValueError("payload length invalid")
        if not opening and r.nonce in nonces:
            raise ValueError("duplicate nonce within seal batch")
        nonces.add(r.nonce)
        work += 2 * n + 16 + len(r.aad)
    if work > 64 * 1024 * 1024:
        raise ValueError("batch working data exceeds 64 MiB")
    return records


def _digests(key, digests):
    _key(key)
    if not 1 <= int.from_bytes(key, "big") < ORDER:
        raise ValueError("invalid P-256 private scalar")
    digests = _batch(digests)
    if len(digests) > MAX_BATCH or any(
        not isinstance(h, bytes) or len(h) != 32 for h in digests
    ):
        raise ValueError("expected at most 4096 SHA-256 digests")
    return digests


def _raw_signature(der):
    r, s = utils.decode_dss_signature(der)
    return r.to_bytes(32, "big") + min(s, ORDER - s).to_bytes(32, "big")


def generate_p256_key():
    """OS-backed CPU key generation; returns a private 32-byte scalar."""
    return (
        ec.generate_private_key(ec.SECP256R1())
        .private_numbers()
        .private_value.to_bytes(32, "big")
    )


def public_key(private_key):
    _digests(private_key, [])
    return (
        ec.derive_private_key(int.from_bytes(private_key, "big"), ec.SECP256R1())
        .public_key()
        .public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
    )


def verify_p256(public, digest, signature):
    """CPU verification of BE r||s over a SHA-256 digest; accepts either s form."""
    if (
        not all(isinstance(x, bytes) for x in (public, digest, signature))
        or len(digest) != 32
        or len(signature) != 64
    ):
        return False
    try:
        key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), public)
        r = int.from_bytes(signature[:32], "big")
        s = int.from_bytes(signature[32:], "big")
        if not (0 < r < ORDER and 0 < s < ORDER):
            return False
        key.verify(
            utils.encode_dss_signature(r, s),
            digest,
            ec.ECDSA(utils.Prehashed(hashes.SHA256())),
        )
        return True
    except (ValueError, InvalidSignature):
        return False


class Cpu:
    """Standard CPU reference backend from cryptography/OpenSSL."""

    def seal(self, key, records):
        return [
            AESGCM(key).encrypt(r.nonce, r.data, r.aad) for r in _records(key, records)
        ]

    def open(self, key, records):
        result = []
        for r in _records(key, records, True):
            try:
                result.append(AESGCM(key).decrypt(r.nonce, r.data, r.aad))
            except InvalidTag:
                result.append(None)
        return result

    def sign(self, key, digests):
        digests = _digests(key, digests)
        private = ec.derive_private_key(int.from_bytes(key, "big"), ec.SECP256R1())
        return [
            _raw_signature(
                private.sign(
                    h,
                    ec.ECDSA(
                        utils.Prehashed(hashes.SHA256()), deterministic_signing=True
                    ),
                )
            )
            for h in digests
        ]

    def sha256(self, messages):
        return [hashlib.sha256(m).digest() for m in _messages(messages)]

    def public_key(self, key):
        return public_key(key)


def _messages(messages):
    messages = _batch(messages)
    if len(messages) > MAX_BATCH or any(
        not isinstance(m, bytes) or len(m) > MAX_PAYLOAD for m in messages
    ):
        raise ValueError("invalid hash batch")
    if sum(map(len, messages)) + 32 * len(messages) > 64 * 1024 * 1024:
        raise ValueError("hash working data exceeds 64 MiB")
    return messages


class _Item(C.Structure):
    _fields_ = [
        ("input", C.c_void_p),
        ("input_size", C.c_uint32),
        ("aad", C.c_void_p),
        ("aad_size", C.c_uint32),
        ("nonce", C.c_ubyte * 12),
        ("output", C.c_void_p),
        ("output_capacity", C.c_uint32),
    ]


class _HashItem(C.Structure):
    _fields_ = [("input", C.c_void_p), ("input_size", C.c_uint32)]


class _Report(C.Structure):
    _fields_ = [
        ("submitted", C.c_uint32),
        ("completed", C.c_uint32),
        ("errors", C.c_uint32),
        ("key_epoch", C.c_uint64),
    ]


class _Stats(C.Structure):
    _fields_ = [
        (name, C.c_uint64)
        for name in (
            "calls",
            "submitted",
            "completed",
            "item_errors",
            "call_errors",
            "reserved_device_bytes",
        )
    ]


class Cuda:
    def __init__(self, library, device=0):
        if not isinstance(device, int) or not 0 <= device < 2**31:
            raise ValueError("invalid device index")
        self.device = device
        self.lib = C.CDLL(str(Path(library).resolve()))
        self.lib.bc_version.restype = C.c_char_p
        self.lib.bc_error_string.argtypes = [C.c_int]
        self.lib.bc_error_string.restype = C.c_char_p
        for name in ("bc_aes256gcm_seal", "bc_aes256gcm_open"):
            fn = getattr(self.lib, name)
            fn.argtypes = [
                C.c_int,
                C.c_void_p,
                C.POINTER(_Item),
                C.c_uint32,
                C.c_void_p,
            ]
            fn.restype = C.c_int
        self.lib.bc_p256_sign.argtypes = [
            C.c_int,
            C.c_void_p,
            C.c_void_p,
            C.c_uint32,
            C.c_void_p,
            C.c_void_p,
        ]
        self.lib.bc_p256_sign.restype = C.c_int
        self.lib.bc_sha256_batch.argtypes = [
            C.c_int,
            C.POINTER(_HashItem),
            C.c_uint32,
            C.c_void_p,
            C.c_void_p,
        ]
        self.lib.bc_p256_public_key.argtypes = [C.c_int, C.c_void_p, C.c_void_p]
        self.lib.bc_abi_version.restype = C.c_uint32
        if self.lib.bc_abi_version() != 1:
            raise RuntimeError("unsupported native ABI")

    @property
    def version(self):
        return self.lib.bc_version().decode()

    def _check(self, status):
        if status:
            raise RuntimeError(self.lib.bc_error_string(status).decode())

    def _aead(self, key, records, opening, invoke=None):
        records = _records(key, records, opening)
        if not records:
            return []
        items = (_Item * len(records))()
        keep = []
        outputs = []
        sizes = []
        for i, r in enumerate(records):
            inp = C.create_string_buffer(r.data)
            aad = C.create_string_buffer(r.aad)
            size = len(r.data) + (-16 if opening else 16)
            out = C.create_string_buffer(max(1, size))
            outputs.append(out)
            sizes.append(size)
            keep.extend((inp, aad))
            items[i] = _Item(
                C.addressof(inp),
                len(r.data),
                C.addressof(aad),
                len(r.aad),
                (C.c_ubyte * 12).from_buffer_copy(r.nonce),
                C.addressof(out),
                size,
            )
        status = (C.c_ubyte * len(records))()
        fn = self.lib.bc_aes256gcm_open if opening else self.lib.bc_aes256gcm_seal
        try:
            self._check(
                invoke(items, len(records), status)
                if invoke
                else fn(self.device, key, items, len(records), status)
            )
            result = []
            for i, s in enumerate(status):
                if opening and s == 3:
                    result.append(None)
                else:
                    self._check(s)
                    result.append(outputs[i].raw[: sizes[i]])
            return result
        finally:
            for buf in keep + outputs:
                C.memset(C.addressof(buf), 0, C.sizeof(buf))

    def seal(self, key, records):
        return self._aead(key, records, False)

    def open(self, key, records):
        return self._aead(key, records, True)

    def sign(self, key, digests):
        digests = _digests(key, digests)
        if not digests:
            return []
        output = C.create_string_buffer(len(digests) * 64)
        status = (C.c_ubyte * len(digests))()
        try:
            self._check(
                self.lib.bc_p256_sign(
                    self.device, key, b"".join(digests), len(digests), output, status
                )
            )
            for s in status:
                self._check(s)
            raw = output.raw
            return [raw[i * 64 : (i + 1) * 64] for i in range(len(digests))]
        finally:
            C.memset(C.addressof(output), 0, C.sizeof(output))

    def sha256(self, messages, invoke=None):
        messages = _messages(messages)
        if not messages:
            return []
        buffers = [C.create_string_buffer(m) for m in messages]
        items = (_HashItem * len(messages))(
            *[_HashItem(C.addressof(b), len(m)) for b, m in zip(buffers, messages)]
        )
        output = C.create_string_buffer(len(messages) * 32)
        status = (C.c_ubyte * len(messages))()
        try:
            self._check(
                invoke(items, len(messages), output, status)
                if invoke
                else self.lib.bc_sha256_batch(
                    self.device, items, len(messages), output, status
                )
            )
            for s in status:
                self._check(s)
            raw = output.raw
            return [raw[i * 32 : (i + 1) * 32] for i in range(len(messages))]
        finally:
            for b in buffers + [output]:
                C.memset(C.addressof(b), 0, C.sizeof(b))

    def public_key(self, key):
        _digests(key, [])
        out = C.create_string_buffer(65)
        self._check(self.lib.bc_p256_public_key(self.device, key, out))
        return out.raw


class Runtime:
    """Owned CUDA context/stream, reusable buffers and versioned key slots.
    Use as a context manager or call close(). Python methods serialize per object.
    Keys remain native-host-resident until rotation, retirement, or close.
    """

    def __init__(self, library, device=0, p256_backend="reference"):
        self._cuda = Cuda(library, device)
        self._lock = threading.RLock()
        self._handle = C.c_void_p()
        lib = self._cuda.lib
        lib.bc_create.argtypes = [C.c_int, C.POINTER(C.c_void_p)]
        lib.bc_destroy.argtypes = [C.c_void_p]
        lib.bc_destroy.restype = None
        lib.bc_get_stats.argtypes = [C.c_void_p, C.POINTER(_Stats)]
        lib.bc_set_p256_backend.argtypes = [C.c_void_p, C.c_uint32]
        lib.bc_get_p256_backend.argtypes = [C.c_void_p, C.POINTER(C.c_uint32)]
        lib.bc_key_put.argtypes = [
            C.c_void_p,
            C.c_uint32,
            C.c_uint32,
            C.c_void_p,
            C.c_uint64,
            C.POINTER(C.c_uint64),
        ]
        lib.bc_key_remove.argtypes = [
            C.c_void_p,
            C.c_uint32,
            C.c_uint64,
            C.POINTER(C.c_uint64),
        ]
        for name in ("bc_seal", "bc_open"):
            getattr(lib, name).argtypes = [
                C.c_void_p,
                C.c_uint32,
                C.POINTER(_Item),
                C.c_uint32,
                C.c_void_p,
                C.POINTER(_Report),
            ]
        lib.bc_sign.argtypes = [
            C.c_void_p,
            C.c_uint32,
            C.c_void_p,
            C.c_uint32,
            C.c_void_p,
            C.c_void_p,
            C.POINTER(_Report),
        ]
        for name in ("bc_seal", "bc_open", "bc_sign"):
            if hasattr(lib, name + "_at_epoch"):
                getattr(lib, name + "_at_epoch").argtypes = (
                    getattr(lib, name).argtypes[:2]
                    + [C.c_uint64]
                    + getattr(lib, name).argtypes[2:]
                )
        lib.bc_hash.argtypes = [
            C.c_void_p,
            C.POINTER(_HashItem),
            C.c_uint32,
            C.c_void_p,
            C.c_void_p,
            C.POINTER(_Report),
        ]
        lib.bc_export_public_key.argtypes = [
            C.c_void_p,
            C.c_uint32,
            C.c_void_p,
            C.POINTER(C.c_uint64),
        ]
        self._cuda._check(lib.bc_create(device, C.byref(self._handle)))
        try:
            self.set_p256_backend(p256_backend)
        except Exception:
            self.close()
            raise
        self.last_report = {}

    def _live(self):
        if not self._handle.value:
            raise RuntimeError("runtime is closed")

    @staticmethod
    def _slot(slot):
        if not isinstance(slot, int) or not 0 <= slot < 16:
            raise ValueError("slot must be 0..15")

    @staticmethod
    def _epoch(epoch):
        if not isinstance(epoch, int) or not 0 <= epoch < 2**64:
            raise ValueError("epoch must be uint64")

    def set_p256_backend(self, backend):
        """Select reference, comb_w8 or full_window_w8; keys/epochs are preserved."""
        choices = ("reference", "comb_w8", "full_window_w8")
        if backend not in choices:
            raise ValueError("unknown P-256 backend")
        with self._lock:
            self._live()
            self._cuda._check(
                self._cuda.lib.bc_set_p256_backend(self._handle, choices.index(backend))
            )

    @property
    def p256_backend(self):
        with self._lock:
            self._live()
            mode = C.c_uint32()
            self._cuda._check(
                self._cuda.lib.bc_get_p256_backend(self._handle, C.byref(mode))
            )
            return ("reference", "comb_w8", "full_window_w8")[mode.value]

    def _report(self, r):
        self.last_report = {name: getattr(r, name) for name, _ in r._fields_}

    def close(self):
        with self._lock:
            if self._handle.value:
                self._cuda.lib.bc_destroy(self._handle)
                self._handle = C.c_void_p()

    def __enter__(self):
        self._live()
        return self

    def __exit__(self, *exc):
        self.close()

    def __del__(self):
        if hasattr(self, "_lock"):
            self.close()

    def load_key(self, slot, key, kind="aes", expected_epoch=0):
        self._slot(slot)
        self._epoch(expected_epoch)
        _key(key)
        if kind not in ("aes", "p256"):
            raise ValueError("kind must be aes or p256")
        with self._lock:
            self._live()
            epoch = C.c_uint64()
            self._cuda._check(
                self._cuda.lib.bc_key_put(
                    self._handle,
                    slot,
                    1 if kind == "aes" else 2,
                    key,
                    expected_epoch,
                    C.byref(epoch),
                )
            )
            return epoch.value

    def retire_key(self, slot, expected_epoch):
        self._slot(slot)
        self._epoch(expected_epoch)
        with self._lock:
            self._live()
            epoch = C.c_uint64()
            self._cuda._check(
                self._cuda.lib.bc_key_remove(
                    self._handle, slot, expected_epoch, C.byref(epoch)
                )
            )
            return epoch.value

    def stats(self):
        with self._lock:
            self._live()
            s = _Stats()
            self._cuda._check(self._cuda.lib.bc_get_stats(self._handle, C.byref(s)))
            return {name: getattr(s, name) for name, _ in s._fields_}

    def _keyed_call(self, name, slot, expected_epoch, *args):
        if expected_epoch is None:
            return getattr(self._cuda.lib, name)(self._handle, slot, *args)
        self._epoch(expected_epoch)
        fn = getattr(self._cuda.lib, name + "_at_epoch", None)
        if fn is None:
            raise RuntimeError("epoch-bound operations require native library v0.3+")
        return fn(self._handle, slot, expected_epoch, *args)

    def _aead(self, slot, records, opening, expected_epoch=None):
        self._slot(slot)
        with self._lock:
            self._live()
            r = _Report()

            def invoke(items, n, status):
                rc = self._keyed_call(
                    "bc_open" if opening else "bc_seal",
                    slot,
                    expected_epoch,
                    items,
                    n,
                    status,
                    C.byref(r),
                )
                self._report(r)
                return rc

            # Shape validation uses a dummy key; real key never leaves native slot.
            result = self._cuda._aead(bytes(32), records, opening, invoke)
            if not result:
                self._cuda._check(invoke(None, 0, None))
            return result

    def seal(self, slot, records, *, expected_epoch=None):
        return self._aead(slot, records, False, expected_epoch)

    def open(self, slot, records, *, expected_epoch=None):
        return self._aead(slot, records, True, expected_epoch)

    def sign(self, slot, digests, *, expected_epoch=None):
        self._slot(slot)
        digests = _digests((1).to_bytes(32, "big"), digests)
        with self._lock:
            self._live()
            out = C.create_string_buffer(max(1, len(digests) * 64))
            status = (C.c_ubyte * len(digests))()
            r = _Report()
            rc = self._keyed_call(
                "bc_sign",
                slot,
                expected_epoch,
                b"".join(digests),
                len(digests),
                out,
                status,
                C.byref(r),
            )
            self._report(r)
            self._cuda._check(rc)
            for s in status:
                self._cuda._check(s)
            raw = out.raw
            return [raw[i * 64 : (i + 1) * 64] for i in range(len(digests))]

    def sha256(self, messages):
        with self._lock:
            self._live()
            r = _Report()

            def invoke(items, n, out, status):
                rc = self._cuda.lib.bc_hash(
                    self._handle, items, n, out, status, C.byref(r)
                )
                self._report(r)
                return rc

            result = self._cuda.sha256(messages, invoke)
            if not result:
                self._cuda._check(invoke(None, 0, None, None))
            return result

    def public_key(self, slot):
        self._slot(slot)
        with self._lock:
            self._live()
            out = C.create_string_buffer(65)
            epoch = C.c_uint64()
            self._cuda._check(
                self._cuda.lib.bc_export_public_key(
                    self._handle, slot, out, C.byref(epoch)
                )
            )
            return out.raw, epoch.value
