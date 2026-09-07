"""SPDX-License-Identifier: Apache-2.0. Exercise an installed wheel outside its checkout.

Run with the Python environment that installed the wheel, from any directory:
python -I path/to/check_python_install.py
The check blocks native library loading and verifies optional dependencies and
application packages have not become requirements of CPU/JWS construction.
"""

import ctypes
import hashlib
from importlib import metadata
import importlib.util
from pathlib import Path
import secrets
from unittest.mock import patch


def main():
    distribution = metadata.distribution("gpu-batch-crypto")
    files = {str(p).replace("\\", "/") for p in distribution.files or []}
    forbidden = ("examples/", "benchmarks/", "access_book/", "tests/")
    if any(
        p.startswith(forbidden) or p.lower().endswith((".dll", ".so", ".lib", ".bin"))
        for p in files
    ):
        raise RuntimeError(
            "application code or native artifacts leaked into Python wheel"
        )
    if importlib.util.find_spec("jwt") is not None:
        raise RuntimeError("base-install check requires an environment without PyJWT")
    requirements = distribution.requires or []
    mandatory = [r for r in requirements if "extra ==" not in r]
    if len(mandatory) != 1 or not mandatory[0].startswith("cryptography"):
        raise RuntimeError("unexpected mandatory dependencies")
    with patch.object(
        ctypes, "CDLL", side_effect=RuntimeError("unexpected native load")
    ):
        from batchcrypto import Cpu, Record, generate_p256_key, public_key, verify_p256
        from batchcrypto.jws import sign_es256
        from batchcrypto.receipts import ReceiptVerifier, seal_records
        from batchcrypto.manifests import open_manifest, seal_manifest
        import batchcrypto

        installed = Path(distribution.locate_file("batchcrypto/__init__.py")).resolve()
        if Path(batchcrypto.__file__).resolve() != installed:
            raise RuntimeError("imports do not resolve to the installed wheel")
        cpu = Cpu()
        digest = cpu.sha256([b"standalone consumer"])[0]
        if digest != hashlib.sha256(b"standalone consumer").digest():
            raise RuntimeError("hash check failed")
        key = generate_p256_key()
        signature = cpu.sign(key, [digest])[0]
        if not verify_p256(public_key(key), digest, signature):
            raise RuntimeError("signature check failed")
        tokens = sign_es256(
            [b'{"example":true}'],
            key_id="consumer-1",
            sign_digests=lambda hs: cpu.sign(key, hs),
        )
        if len(tokens) != 1 or len(tokens[0].split(".")) != 3:
            raise RuntimeError("JWS construction failed")
        records = [b"installed export record", b"second record"]
        batch = seal_records(
            records,
            context="install-check",
            key_id="consumer-1",
            sign_digests=lambda hs: cpu.sign(key, hs),
        )
        consumer = ReceiptVerifier(
            public_key(key), key_id="consumer-1", context="install-check"
        )
        if not consumer.verify(
            records[1], batch.receipt(1), expected_index=1
        ) or consumer.verify(b"changed", batch.receipt(1), expected_index=1):
            raise RuntimeError("installed record receipt check failed")
        token = seal_manifest(
            records,
            context="install-check",
            key_id="consumer-1",
            sign_digests=lambda hs: cpu.sign(key, hs),
        )
        checked = open_manifest(
            token, public_key(key), context="install-check", key_id="consumer-1"
        )
        if (
            checked is None
            or not checked.verify_all(records)
            or checked.verify_all(records[:-1])
        ):
            raise RuntimeError("installed signed manifest check failed")
        aes_key = secrets.token_bytes(32)
        sealed = cpu.seal(aes_key, [Record(bytes(12), b"local fixture")])[0]
        if cpu.open(aes_key, [Record(bytes(12), sealed)]) != [b"local fixture"]:
            raise RuntimeError("AES check failed")
    print(
        "PASS: installed CPU/JWS/receipts/manifests package; no CUDA load, PyJWT or application dependency"
    )


if __name__ == "__main__":
    main()
