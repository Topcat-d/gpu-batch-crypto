"""SPDX-License-Identifier: Apache-2.0.
Reference machine-authorized content, not a protocol standard or payment system.
The consumer uses independent CPU crypto and pre-established trust/key delivery.
"""

import argparse
import hashlib
import json
import os
import time
from batchcrypto import Cpu, Runtime, Record, generate_p256_key, public_key, verify_p256


def canonical(value):
    # This example's restricted schema uses objects, strings and integers only.
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")


def grant_digest(grant):
    return hashlib.sha256(
        b"gpu-crypto-content-grant-v1\x00" + canonical(grant)
    ).digest()


def metadata(grant):
    return {
        k: grant[k]
        for k in (
            "version",
            "publisher_id",
            "content_id",
            "content_length",
            "content_type",
            "key_id",
        )
    }


def publish(content, aes_key, signing_key, now, runtime=None):
    cpu = Cpu()
    nonce = os.urandom(12)
    content_id = (runtime.sha256([content]) if runtime else cpu.sha256([content]))[
        0
    ].hex()
    grant = {
        "version": 1,
        "publisher_id": "publisher.example",
        "content_id": content_id,
        "content_length": len(content),
        "content_type": "text/plain; charset=utf-8",
        "principal": "reader.example",
        "issued_at": now,
        "expires_at": now + 300,
        "key_id": "publisher-signing-1",
        "encryption": {
            "algorithm": "AES-256-GCM",
            "content_key_id": "content-key-1",
            "nonce": nonce.hex(),
        },
        "terms_hash": hashlib.sha256(
            b"Example access terms; no payment implemented."
        ).hexdigest(),
    }
    record = Record(nonce, content, canonical(metadata(grant)))
    ciphertext = (
        runtime.seal(0, [record]) if runtime else cpu.seal(aes_key, [record])
    )[0]
    grant["ciphertext_sha256"] = (
        runtime.sha256([ciphertext]) if runtime else cpu.sha256([ciphertext])
    )[0].hex()
    # Domain separation is identical to grant_digest used by the CPU verifier.
    encoded = b"gpu-crypto-content-grant-v1\x00" + canonical(grant)
    digest = (runtime.sha256([encoded]) if runtime else cpu.sha256([encoded]))[0]
    signature = (
        runtime.sign(1, [digest]) if runtime else cpu.sign(signing_key, [digest])
    )[0]
    return grant, ciphertext, signature


def consume(
    grant,
    ciphertext,
    signature,
    aes_key,
    trusted_public,
    expected_content_id,
    now,
    principal="reader.example",
):
    if not verify_p256(trusted_public, grant_digest(grant), signature):
        raise ValueError("invalid publisher signature")
    if (
        grant["version"] != 1
        or grant["publisher_id"] != "publisher.example"
        or grant["key_id"] != "publisher-signing-1"
    ):
        raise ValueError("unexpected issuer or format")
    if grant["principal"] != principal or grant["content_id"] != expected_content_id:
        raise ValueError("wrong principal or content")
    if (
        type(grant["issued_at"]) is not int
        or type(grant["expires_at"]) is not int
        or not grant["issued_at"] <= now < grant["expires_at"]
    ):
        raise ValueError("grant not currently valid")
    if (
        grant["encryption"]["algorithm"] != "AES-256-GCM"
        or grant["encryption"]["content_key_id"] != "content-key-1"
    ):
        raise ValueError("unknown encryption key or algorithm")
    if hashlib.sha256(ciphertext).hexdigest() != grant["ciphertext_sha256"]:
        raise ValueError("ciphertext identity mismatch")
    nonce = bytes.fromhex(grant["encryption"]["nonce"])
    content = Cpu().open(
        aes_key, [Record(nonce, ciphertext, canonical(metadata(grant)))]
    )[0]
    if content is None:
        raise ValueError("ciphertext authentication failed")
    if (
        type(grant["content_length"]) is not int
        or len(content) != grant["content_length"]
        or hashlib.sha256(content).hexdigest() != expected_content_id
    ):
        raise ValueError("content identity mismatch")
    return content


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--library")
    p.add_argument("--device", type=int, default=0)
    a = p.parse_args()
    content = b"Independent publishers can authorize machine access to their content."
    aes_key = os.urandom(32)
    sk = generate_p256_key()
    now = int(time.time())
    if a.library:
        with Runtime(a.library, a.device) as rt:
            rt.load_key(0, aes_key)
            rt.load_key(1, sk, "p256")
            grant, ciphertext, sig = publish(content, aes_key, sk, now, rt)
            stats = rt.stats()
    else:
        grant, ciphertext, sig = publish(content, aes_key, sk, now)
        stats = None
    # Trust and AES key delivery are supplied externally in a real deployment.
    result = consume(
        grant,
        ciphertext,
        sig,
        aes_key,
        public_key(sk),
        hashlib.sha256(content).hexdigest(),
        now,
    )
    if result != content:
        raise RuntimeError("example failed")
    print(
        json.dumps(
            {
                "backend": "cuda" if a.library else "cpu",
                "grant": grant,
                "independent_cpu_verification": True,
                "content_recovered": True,
                "stats": stats,
                "payment_and_key_release": "outside this example",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
