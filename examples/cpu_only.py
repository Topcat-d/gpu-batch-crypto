"""SPDX-License-Identifier: Apache-2.0. CPU-only use of the installed package.

Run: python -m pip install .
     python examples/cpu_only.py
No CUDA library, PyJWT, content service or ledger is required.
"""

import hashlib
import secrets

from batchcrypto import Cpu, Record, generate_p256_key, public_key, verify_p256


def main():
    cpu = Cpu()
    messages = [b"record one", b"record two"]
    digests = cpu.sha256(messages)
    if digests != [hashlib.sha256(m).digest() for m in messages]:
        raise RuntimeError("SHA-256 comparison failed")

    # A new key for this process; distinct counter nonces under that key.
    # Persistent applications must allocate nonces across all workers/restarts.
    aes_key = secrets.token_bytes(32)
    records = [
        Record(i.to_bytes(12, "big"), data, b"cpu-example:v1")
        for i, data in enumerate(messages)
    ]
    sealed = cpu.seal(aes_key, records)
    encrypted = [Record(r.nonce, data, r.aad) for r, data in zip(records, sealed)]
    if cpu.open(aes_key, encrypted) != messages:
        raise RuntimeError("AES-GCM round trip failed")
    changed = bytearray(sealed[0])
    changed[-1] ^= 1
    if cpu.open(
        aes_key, [Record(records[0].nonce, bytes(changed), records[0].aad)]
    ) != [None]:
        raise RuntimeError("altered authentication tag accepted")

    signing_key = generate_p256_key()
    signatures = cpu.sign(signing_key, digests)
    public = public_key(signing_key)
    if not all(verify_p256(public, h, s) for h, s in zip(digests, signatures)):
        raise RuntimeError("P-256 verification failed")
    print(
        "PASS: CPU SHA-256, AES-GCM with tag rejection, and P-256 signing/verification"
    )


if __name__ == "__main__":
    main()
