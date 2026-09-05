"""SPDX-License-Identifier: Apache-2.0.

Generate public P-256 fixed-base tables; independently verify every point.
Adapted from Smoke's gen_p256_fullwindow_table.py (see EXTRACTION.json).
Modified: dependency-free packing, generic typed format, both table layouts,
mandatory OpenSSL point verification, deterministic metadata, and --check.
Only public multiples of G are stored; no signing keys or nonces are inputs.
"""

import argparse
import hashlib
import json
import struct
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ec
from imported.p256_table_math import (
    Gx,
    Gy,
    N,
    point_add_affine,
    point_double_affine,
    to_montgomery,
)

ROOT = Path(__file__).resolve().parents[1]
MAGIC = b"GBCTBL01"


def generate(kind):
    windows, digits, type_id = (1, 255, 1) if kind == "comb_w8" else (33, 128, 2)
    blob = bytearray(MAGIC + struct.pack("<6I", type_id, 1, windows, digits, 64, 0))
    base = (Gx, Gy)
    checked = 0
    for window in range(windows):
        point = base
        for digit in range(1, digits + 1):
            scalar = (digit << (8 * window)) % N
            independent = (
                ec.derive_private_key(scalar, ec.SECP256R1())
                .public_key()
                .public_numbers()
            )
            if point != (independent.x, independent.y):
                raise RuntimeError(
                    f"point mismatch: {kind} window={window} digit={digit}"
                )
            for coordinate in point:
                blob.extend(to_montgomery(coordinate).to_bytes(32, "little"))
            checked += 1
            if digit != digits:
                point = point_add_affine(*point, *base)
        for _ in range(8):
            base = point_double_affine(*base)
    assert len(blob) == 32 + windows * digits * 64
    meta = {
        "format": "GBCTBL01",
        "version": 1,
        "kind": kind,
        "type": type_id,
        "windows": windows,
        "digits": digits,
        "entry_bytes": 64,
        "header_bytes": 32,
        "total_bytes": len(blob),
        "layout": "AoS; X[8 u32 LE] then Y[8 u32 LE]; index=window*digits+digit-1",
        "domain": "Montgomery x*2^256 mod p",
        "curve": "NIST P-256",
        "points_verified": checked,
        "independent_verifier": "cryptography/OpenSSL SECP256R1 public-key derivation",
        "sha256": hashlib.sha256(blob).hexdigest(),
    }
    return bytes(blob), meta


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="regenerate and compare checked-in files"
    )
    parser.add_argument("--outdir", type=Path, default=ROOT / "data/p256")
    args = parser.parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)
    for kind in ("comb_w8", "full_window_w8"):
        blob, meta = generate(kind)
        files = {
            f"{kind}.bin": blob,
            f"{kind}.sha256": (meta["sha256"] + "\n").encode(),
            f"{kind}.json": (json.dumps(meta, indent=2) + "\n").encode(),
        }
        for name, contents in files.items():
            path = args.outdir / name
            if args.check:
                if path.read_bytes() != contents:
                    raise RuntimeError(
                        f"table differs from independently regenerated data: {name}"
                    )
            else:
                path.write_bytes(contents)
        print(
            f"PASS: {kind}, {meta['points_verified']} independently verified points, {meta['sha256']}"
        )


if __name__ == "__main__":
    main()
