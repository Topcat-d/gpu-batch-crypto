"""SPDX-License-Identifier: Apache-2.0. Minimal guarded GPU signing consumer.

CPU prepares digests; one owned GPU runtime signs; every output is checked.
This example uses a fresh synthetic signing key and makes no timing claim.
"""

import argparse

from batchcrypto import Cpu, MAX_BATCH, generate_p256_key
from batchcrypto.verified import VerifiedSigner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--library", required=True, help="native DLL/shared-library path"
    )
    parser.add_argument(
        "--device", type=int, default=0, help="explicit CUDA device ordinal"
    )
    parser.add_argument("--count", type=int, default=256)
    args = parser.parse_args()
    if args.device < 0 or not 1 <= args.count <= MAX_BATCH:
        parser.error("device must be nonnegative; count must be 1..4096")
    digests = Cpu().sha256([f"gpu-example:v1:{i}".encode() for i in range(args.count)])
    with VerifiedSigner(args.library, device=args.device) as signer:
        epoch = signer.load_key(0, generate_p256_key())
        signatures = signer.sign(0, digests, expected_epoch=epoch)
        if len(signatures) != args.count:
            raise RuntimeError("incomplete signature batch")
        signer.retire_key(0, expected_epoch=epoch)
    print(
        f"PASS: {len(signatures)} GPU P-256 signatures independently verified; key retired"
    )


if __name__ == "__main__":
    main()
