"""SPDX-License-Identifier: Apache-2.0. Portable subset-verification demo.

Uses an ephemeral synthetic key. Trust in this key is demo configuration, not
an identity proof. --output creates a NEW directory containing public artifacts.
"""

import argparse
import json
from pathlib import Path

from batchcrypto import Cpu, generate_p256_key, public_key
from batchcrypto.manifests import open_manifest, seal_manifest
from batchcrypto.receipts import ReceiptVerifier, seal_records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--format", choices=("merkle", "manifest"), default="merkle")
    args = parser.parse_args()
    context, key_id, index = "demo-export-2026-09-07", "demo-key-1", 17
    records = [
        json.dumps(
            {
                "record_id": i,
                "source": "synthetic-catalog",
                "text": f"Example tool result {i}",
            },
            separators=(",", ":"),
        ).encode()
        for i in range(64)
    ]
    key = generate_p256_key()
    public = public_key(key)
    if args.format == "manifest":
        token = seal_manifest(
            records,
            context=context,
            key_id=key_id,
            sign_digests=lambda hs: Cpu().sign(key, hs),
        )
        receipt, filename = token.encode("ascii"), "manifest.jws"
        verified = open_manifest(token, public, context=context, key_id=key_id)
        if verified is None or not verified.verify_all(records):
            raise RuntimeError("complete export failed verification")
        verify = lambda record: verified.verify_record(record, expected_index=index)
    else:
        batch = seal_records(
            records,
            context=context,
            key_id=key_id,
            sign_digests=lambda hs: Cpu().sign(key, hs),
        )
        receipt, filename = batch.receipt(index), "receipt.json"
        verifier = ReceiptVerifier(public, key_id=key_id, context=context)
        verify = lambda record: verifier.verify(record, receipt, expected_index=index)
    if not verify(records[index]):
        raise RuntimeError("receipt failed")
    if verify(records[index] + b"changed"):
        raise RuntimeError("changed record accepted")
    if args.output:
        args.output.mkdir(parents=True, exist_ok=False)
        (args.output / "record.bin").write_bytes(records[index])
        (args.output / filename).write_bytes(receipt)
        (args.output / "public-key.hex").write_text(public.hex(), encoding="ascii")
    print(
        json.dumps(
            {
                "records_sealed": len(records),
                "format": args.format,
                "signatures": 1,
                "verified_index": index,
                "context": context,
                "key_id": key_id,
                "receipt_bytes": len(receipt),
                "changed_record_rejected": True,
                "output": str(args.output) if args.output else None,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
