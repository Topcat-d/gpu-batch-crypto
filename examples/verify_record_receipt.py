"""SPDX-License-Identifier: Apache-2.0. Offline consumer of a detached receipt.

Supply public key, key id, context and index from trusted configuration.
Never establish key trust by accepting a public key alongside untrusted data.
"""

import argparse
from pathlib import Path

from batchcrypto import MAX_PAYLOAD
from batchcrypto.manifests import MAX_MANIFEST_BYTES, open_manifest
from batchcrypto.receipts import MAX_RECEIPT_BYTES, ReceiptVerifier


def read_bounded(path, limit):
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("input file exceeds profile limit")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--index", type=int, required=True)
    parser.add_argument("--format", choices=("merkle", "manifest"), default="merkle")
    args = parser.parse_args()
    try:
        public = bytes.fromhex(
            read_bounded(args.public_key, 132).decode("ascii").strip()
        )
        record = read_bounded(args.record, MAX_PAYLOAD)
        if args.format == "manifest":
            token = read_bounded(args.receipt, MAX_MANIFEST_BYTES).decode("ascii")
            checked = open_manifest(
                token, public, key_id=args.key_id, context=args.context
            )
            accepted = checked is not None and checked.verify_record(
                record, expected_index=args.index
            )
        else:
            verifier = ReceiptVerifier(public, key_id=args.key_id, context=args.context)
            accepted = verifier.verify(
                record,
                read_bounded(args.receipt, MAX_RECEIPT_BYTES),
                expected_index=args.index,
            )
    except (OSError, ValueError):
        accepted = False
    print(
        "VERIFIED: exact record included under configured key/context/index"
        if accepted
        else "REJECTED"
    )
    raise SystemExit(0 if accepted else 1)


if __name__ == "__main__":
    main()
