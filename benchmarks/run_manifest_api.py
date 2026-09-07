"""SPDX-License-Identifier: Apache-2.0. Actual public manifest/receipt API costs."""

import argparse
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
from batchcrypto.manifests import open_manifest, seal_manifest
from batchcrypto.receipts import ReceiptVerifier, seal_records
from run_pipeline import system_cpu_times, system_cpu_percent
from run_receipts import (
    CONTEXT,
    KEY_ID,
    ReferenceBatch,
    ReferenceVerifier,
    encode,
    parse,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [
    "python/batchcrypto/__init__.py",
    "python/batchcrypto/jws.py",
    "python/batchcrypto/receipts.py",
    "python/batchcrypto/manifests.py",
    "benchmarks/run_receipts.py",
    "benchmarks/run_pipeline.py",
    "benchmarks/run_manifest_api.py",
    "benchmarks/MANIFEST_API_CAMPAIGN.md",
]
SCENARIOS = [
    ("one", "fresh"),
    ("quarter", "fresh"),
    ("full", "shared"),
    ("full", "fresh"),
]


def cpu_name():
    if os.name == "nt":
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        ) as key:
            return winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
    return platform.processor()


class ManifestBatch:
    def __init__(self, records, sign):
        self.manifest = seal_manifest(
            records, context=CONTEXT, key_id=KEY_ID, sign_digests=sign
        )

    def receipt(self, index, *, include_manifest):
        item = {"index": index}
        if include_manifest:
            item["manifest"] = self.manifest
        return encode(item)


class ManifestConsumer:
    """Benchmark-only framing adapter; open once per shared recipient/export."""

    def __init__(self, public):
        self.public = public
        self.token = None
        self.checked = None

    def verify(self, record, receipt, *, expected_index, manifest=None):
        item = parse(receipt)
        fields = {"index"} if manifest is not None else {"index", "manifest"}
        if (
            set(item) != fields
            or type(item["index"]) is not int
            or item["index"] != expected_index
        ):
            return False
        token = manifest if manifest is not None else item["manifest"]
        if self.token != token:
            self.checked = open_manifest(
                token, self.public, context=CONTEXT, key_id=KEY_ID
            )
            self.token = token
        return self.checked is not None and self.checked.verify_record(
            record, expected_index=expected_index
        )


def measure(records, selected, scheme, recipients, sign, public):
    start = time.perf_counter_ns()
    if scheme == "manifest":
        batch = ManifestBatch(records, sign)
    elif scheme == "merkle":
        batch = seal_records(records, context=CONTEXT, key_id=KEY_ID, sign_digests=sign)
    else:
        batch = ReferenceBatch(records, "individual", sign)
    sealed = time.perf_counter_ns()
    share = recipients == "shared" and scheme != "individual"
    manifest_wire = encode(batch.manifest) if share else b""
    receipts = [batch.receipt(index, include_manifest=not share) for index in selected]
    serialized = time.perf_counter_ns()

    def consumer():
        if scheme == "manifest":
            return ManifestConsumer(public)
        if scheme == "merkle":
            return ReceiptVerifier(public, key_id=KEY_ID, context=CONTEXT)
        return ReferenceVerifier(public, "individual")

    verifier = consumer() if recipients == "shared" else None
    manifest = json.loads(manifest_wire) if share else None
    accepted = sum(
        int(
            (verifier or consumer()).verify(
                records[index], receipt, expected_index=index, manifest=manifest
            )
        )
        for index, receipt in zip(selected, receipts)
    )
    end = time.perf_counter_ns()
    rejected = not consumer().verify(
        records[selected[0]] + b"changed",
        receipts[0],
        expected_index=selected[0],
        manifest=manifest,
    )
    if accepted != len(selected) or not rejected:
        raise RuntimeError("public API verification gate failed")
    return {
        "accepted": accepted,
        "changed_rejected": rejected,
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
        raise ValueError("choose a fresh capture path")
    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )

    def sign(digests):
        signatures = []
        for digest in digests:
            der = private.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
            r, s = utils.decode_dss_signature(der)
            signatures.append(
                r.to_bytes(32, "big") + min(s, ORDER - s).to_bytes(32, "big")
            )
        return signatures

    data = {
        "schema": "manifest-api-v1",
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "sources": {
            path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            for path in SOURCES
        },
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "cpu": cpu_name(),
            "logical_cpus": os.cpu_count(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cryptography": cryptography.__version__,
            "openssl": backend.openssl_version_text(),
        },
        "seed": 20260908,
        "smoke": args.smoke,
        "complete": False,
        "warmups": [],
        "cpu_samples": [],
        "cells": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(data["seed"])
    deadline = time.monotonic() + 300
    row = None
    try:
        for scheme in ("individual", "manifest", "merkle"):
            data["warmups"].append(
                {
                    "scheme": scheme,
                    **measure(
                        [str(i).encode() for i in range(7)],
                        list(range(7)),
                        scheme,
                        "shared",
                        sign,
                        public,
                    ),
                }
            )
        for phase, count, repeats in (
            [("smoke", 7, 1)]
            if args.smoke
            else [("primary", 1024, 5), ("holdout", 257, 3)]
        ):
            records = [
                encode(
                    {
                        "id": i,
                        "source": "synthetic-export",
                        "text": "x" * 160,
                        "value": hashlib.sha256(str(i).encode()).hexdigest(),
                    }
                )
                for i in range(count)
            ]
            for consumption, recipients in SCENARIOS:
                consumed = {"one": 1, "quarter": count // 4, "full": count}[consumption]
                selected = [i * count // consumed for i in range(consumed)]
                for repeat in range(repeats):
                    before = system_cpu_times()
                    time.sleep(0.1)
                    after = system_cpu_times()
                    sample = {
                        "before": before,
                        "after": after,
                        "percent": system_cpu_percent(before, after),
                    }
                    sample_id = len(data["cpu_samples"])
                    data["cpu_samples"].append(sample)
                    schemes = ["individual", "manifest", "merkle"]
                    rng.shuffle(schemes)
                    for scheme in schemes:
                        row = {
                            "order": len(data["cells"]),
                            "phase": phase,
                            "count": count,
                            "consumption": consumption,
                            "selected": consumed,
                            "recipients": recipients,
                            "repeat": repeat,
                            "scheme": scheme,
                            "cpu_sample": sample_id,
                        }
                        if time.monotonic() > deadline:
                            raise RuntimeError("five-minute budget exceeded")
                        row.update(
                            measure(records, selected, scheme, recipients, sign, public)
                        )
                        data["cells"].append(row)
                print(
                    f"{phase}: {count} {consumption}/{recipients} complete", flush=True
                )
        data["complete"] = True
    except Exception as exc:
        data["failure"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "attempted": row,
        }
        raise
    finally:
        data["finished_utc"] = datetime.now(timezone.utc).isoformat()
        args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {len(data['cells'])} cells")


if __name__ == "__main__":
    main()
