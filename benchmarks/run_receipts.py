"""SPDX-License-Identifier: Apache-2.0. CPU record-export comparison.

Reference alternatives are benchmark-only, not additional supported wire APIs.
See RECEIPT_CAMPAIGN.md for predeclared workloads and measurement boundaries.
"""

import argparse
import base64
from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import subprocess
import time

import cryptography
from cryptography.hazmat.backends.openssl.backend import backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

from batchcrypto import ORDER
from batchcrypto.jws import sign_es256
from batchcrypto.receipts import ReceiptVerifier, seal_records

ROOT = Path(__file__).resolve().parents[1]
CONTEXT, KEY_ID = "synthetic-export-1", "synthetic-key-1"
SOURCES = [
    "python/batchcrypto/__init__.py",
    "python/batchcrypto/jws.py",
    "python/batchcrypto/receipts.py",
    "benchmarks/run_receipts.py",
    "benchmarks/RECEIPT_CAMPAIGN.md",
]


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def decode64(value):
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def digest64(record):
    return (
        base64.urlsafe_b64encode(hashlib.sha256(record).digest()).rstrip(b"=").decode()
    )


def no_duplicates(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate field")
        value[key] = item
    return value


def parse(data):
    return json.loads(data, object_pairs_hook=no_duplicates)


class ReferenceBatch:
    def __init__(self, records, scheme, sign):
        self.scheme = scheme
        common = {"context": CONTEXT, "count": len(records), "profile": scheme}
        digests = [digest64(record) for record in records]
        payloads = (
            [
                encode({**common, "index": i, "sha256": digest})
                for i, digest in enumerate(digests)
            ]
            if scheme == "individual"
            else [encode({**common, "hashes": digests})]
        )
        self.tokens = sign_es256(payloads, key_id=KEY_ID, sign_digests=sign)
        self.manifest = self.tokens[0]

    def receipt(self, index, *, include_manifest=True):
        value = {"index": index}
        if include_manifest:
            value["manifest"] = self.tokens[index if self.scheme == "individual" else 0]
        return encode(value)


class ReferenceVerifier:
    """Independent CPU controls: same pinned key/context/index, bounded cache.

    Receives only this harness's synthetic outputs. It deliberately has no
    public entry point and is not an untrusted-input service implementation.
    """

    def __init__(self, public, scheme):
        self.key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), public)
        self.scheme = scheme
        self.cache = OrderedDict()

    def verify(self, record, receipt, *, expected_index, manifest=None):
        item = parse(receipt)
        fields = {"index"} if manifest is not None else {"manifest", "index"}
        if (
            set(item) != fields
            or type(item["index"]) is not int
            or item["index"] != expected_index
        ):
            return False
        token = manifest if manifest is not None else item["manifest"]
        if token in self.cache:
            self.cache.move_to_end(token)
            claims = self.cache[token]
        else:
            header, payload, signature = token.split(".")
            if parse(decode64(header)) != {"alg": "ES256", "kid": KEY_ID}:
                return False
            raw = decode64(signature)
            r, s = int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")
            if len(raw) != 64 or not 0 < r < ORDER or not 0 < s <= ORDER // 2:
                return False
            self.key.verify(
                utils.encode_dss_signature(r, s),
                (header + "." + payload).encode(),
                ec.ECDSA(hashes.SHA256()),
            )
            claims = parse(decode64(payload))
            required = {"context", "count", "profile"} | (
                {"index", "sha256"} if self.scheme == "individual" else {"hashes"}
            )
            if (
                set(claims) != required
                or claims["context"] != CONTEXT
                or claims["profile"] != self.scheme
                or type(claims["count"]) is not int
                or not 1 <= claims["count"] <= 4096
            ):
                return False
            self.cache[token] = claims
            if len(self.cache) > 8:
                self.cache.popitem(last=False)
        if not 0 <= expected_index < claims["count"]:
            return False
        digest = digest64(record)
        if self.scheme == "individual":
            return claims["index"] == expected_index and claims["sha256"] == digest
        return (
            len(claims["hashes"]) == claims["count"]
            and claims["hashes"][expected_index] == digest
        )


def measure(records, selected, scheme, recipients, sign, public):
    start = time.perf_counter_ns()
    batch = (
        seal_records(records, context=CONTEXT, key_id=KEY_ID, sign_digests=sign)
        if scheme == "merkle"
        else ReferenceBatch(records, scheme, sign)
    )
    sealed = time.perf_counter_ns()
    share_manifest = recipients == "shared" and scheme != "individual"
    manifest_wire = encode(batch.manifest) if share_manifest else b""
    receipts = [batch.receipt(i, include_manifest=not share_manifest) for i in selected]
    serialized = time.perf_counter_ns()

    def consumer():
        return (
            ReceiptVerifier(public, key_id=KEY_ID, context=CONTEXT)
            if scheme == "merkle"
            else ReferenceVerifier(public, scheme)
        )

    verifier = consumer() if recipients == "shared" else None
    manifest = json.loads(manifest_wire) if share_manifest else None
    accepted = 0
    for index, receipt in zip(selected, receipts):
        current = verifier or consumer()
        accepted += int(
            current.verify(
                records[index], receipt, expected_index=index, manifest=manifest
            )
        )
    end = time.perf_counter_ns()
    changed_rejected = not consumer().verify(
        records[selected[0]] + b"changed",
        receipts[0],
        expected_index=selected[0],
        manifest=manifest,
    )
    if accepted != len(selected) or not changed_rejected:
        raise RuntimeError("correctness gate failed")
    return {
        "accepted": accepted,
        "changed_rejected": changed_rejected,
        "signatures": len(records) if scheme == "individual" else 1,
        "producer_ms": (sealed - start) / 1e6,
        "serialize_ms": (serialized - sealed) / 1e6,
        "consumer_ms": (end - serialized) / 1e6,
        "total_ms": (end - start) / 1e6,
        "metadata_bytes": len(manifest_wire) + sum(map(len, receipts)),
        "manifest_once_bytes": len(manifest_wire),
        "max_receipt_bytes": max(map(len, receipts)),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("capture already exists; choose a fresh path")
    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )

    def sign(digests):
        result = []
        for digest in digests:
            der = private.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
            r, s = utils.decode_dss_signature(der)
            result.append(r.to_bytes(32, "big") + min(s, ORDER - s).to_bytes(32, "big"))
        return result

    seed = 20260907
    rng = random.Random(seed)
    capture = {
        "schema": "record-receipt-campaign-v1",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "source_sha256": {
            path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            for path in SOURCES
        },
        "environment": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "logical_cpus": os.cpu_count(),
            "python": platform.python_version(),
            "cryptography": cryptography.__version__,
            "openssl": backend.openssl_version_text(),
        },
        "seed": seed,
        "smoke": args.smoke,
        "complete": False,
        "cells": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + 300
    campaigns = (
        [("smoke", 7, 1)]
        if args.smoke
        else [("primary", 64, 5), ("primary", 1024, 5), ("holdout", 257, 3)]
    )
    try:
        for phase, count, repeats in campaigns:
            records = [
                encode(
                    {
                        "id": i,
                        "source": "synthetic-export",
                        "value": hashlib.sha256(str(i).encode()).hexdigest(),
                        "text": "x" * 160,
                    }
                )
                for i in range(count)
            ]
            for consumption, consumed in (
                ("one", 1),
                ("quarter", max(1, count // 4)),
                ("full", count),
            ):
                selected = [i * count // consumed for i in range(consumed)]
                for recipients in ("shared", "fresh"):
                    for repeat in range(repeats):
                        schemes = ["individual", "hash_list", "merkle"]
                        rng.shuffle(schemes)
                        for scheme in schemes:
                            if time.monotonic() > deadline:
                                raise RuntimeError("five-minute budget exceeded")
                            row = {
                                "order": len(capture["cells"]),
                                "phase": phase,
                                "count": count,
                                "consumption": consumption,
                                "selected": consumed,
                                "recipients": recipients,
                                "repeat": repeat,
                                "scheme": scheme,
                                "record_bytes": sum(map(len, records)),
                            }
                            row.update(
                                measure(
                                    records, selected, scheme, recipients, sign, public
                                )
                            )
                            capture["cells"].append(row)
                print(f"{phase}: n={count} {consumption} complete", flush=True)
        capture["complete"] = True
    except Exception as exc:
        capture["failure"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "attempted_cell": locals().get("row"),
        }
        raise
    finally:
        capture["finished_utc"] = datetime.now(timezone.utc).isoformat()
        args.output.write_text(json.dumps(capture, indent=2) + "\n", encoding="utf-8")
    print(f"{len(capture['cells'])} cells saved to {args.output}")


if __name__ == "__main__":
    main()
