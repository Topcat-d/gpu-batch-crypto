"""SPDX-License-Identifier: Apache-2.0. Compare public P-256 execution backends.

All outputs are compared with deterministic OpenSSL signatures outside timing.
Table selection/import, key import, generation and one warmup are excluded.
Timed synchronous calls include packing, transfers, execution and cleanup.
"""

import argparse
import hashlib
import json
import platform
import re
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import cryptography
from cryptography.hazmat.backends.openssl.backend import backend as openssl
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from batchcrypto import ORDER, Runtime, generate_p256_key
from run_matrix import ROOT, command, cpu_model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", required=True)
    parser.add_argument("--build-dir", default="build")
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--iterations", type=int, default=7)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.iterations < 3:
        parser.error("at least three samples required")
    if command(["git", "diff", "--name-only", "HEAD"]):
        raise RuntimeError("commit source before benchmarking")
    commit = command(["git", "rev-parse", "HEAD"])
    sources = {
        f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest()
        for f in command(["git", "ls-files"]).splitlines()
        if f.endswith(
            (".py", ".cu", ".cuh", ".h", ".hpp", ".cpp", ".c", ".cmake", ".bin")
        )
        or f in ("CMakeLists.txt", "pyproject.toml")
    }
    compiler_configuration = []
    for path in Path(args.build_dir, "CMakeFiles").glob("*/CMake*Compiler.cmake"):
        compiler_configuration.extend(
            re.findall(
                r"set\(CMAKE_(?:CXX|CUDA)_COMPILER_(?:ID|VERSION) [^\n]+",
                path.read_text(),
            )
        )
    cache = Path(args.build_dir, "CMakeCache.txt").read_text()
    architectures = re.findall(r"CMAKE_CUDA_ARCHITECTURES:[^=]+=(.+)", cache)
    key = generate_p256_key()
    private = ec.derive_private_key(int.from_bytes(key, "big"), ec.SECP256R1())

    def cpu_sign(digests):
        output = []
        for digest in digests:
            r, s = utils.decode_dss_signature(
                private.sign(
                    digest,
                    ec.ECDSA(
                        utils.Prehashed(hashes.SHA256()), deterministic_signing=True
                    ),
                )
            )
            output.append(r.to_bytes(32, "big") + min(s, ORDER - s).to_bytes(32, "big"))
        return output

    rows = []
    for size in (1, 8, 64, 256, 1024, 4096):
        digests = [hashlib.sha256(i.to_bytes(4, "big")).digest() for i in range(size)]
        expected = cpu_sign(digests)
        with (
            Runtime(args.library, args.device) as reference,
            Runtime(args.library, args.device, "comb_w8") as comb,
            Runtime(args.library, args.device, "full_window_w8") as full,
        ):
            runtimes = {"reference": reference, "comb_w8": comb, "full_window_w8": full}
            for rt in runtimes.values():
                rt.load_key(0, key, "p256")
                assert rt.sign(0, digests) == expected
            calls = [("cpu", lambda: cpu_sign(digests))] + [
                (name, lambda rt=rt: rt.sign(0, digests))
                for name, rt in runtimes.items()
            ]
            samples = {name: [] for name, _ in calls}
            for iteration in range(args.iterations):
                # Rotate timing order rather than consistently favoring one backend.
                order = iteration % len(calls)
                for name, call in calls[order:] + calls[:order]:
                    start = time.perf_counter()
                    actual = call()
                    seconds = time.perf_counter() - start
                    assert actual == expected, name
                    samples[name].append(seconds)
                    if name != "cpu":
                        report = runtimes[name].last_report
                        assert report == {
                            "submitted": size,
                            "completed": size,
                            "errors": 0,
                            "key_epoch": 1,
                        }
            for name, times in samples.items():
                stats = runtimes[name].stats() if name != "cpu" else None
                if stats:
                    assert (
                        stats["submitted"]
                        == stats["completed"]
                        == size * (args.iterations + 1)
                    )
                    assert stats["call_errors"] == stats["item_errors"] == 0
                rows.append(
                    {
                        "backend": name,
                        "batch": size,
                        "iterations": args.iterations,
                        "batch_seconds": times,
                        "total_operations": size * args.iterations,
                        "outputs_checked": size * args.iterations,
                        "ops_per_second": size * args.iterations / sum(times),
                        "mean_batch_ms": statistics.mean(times) * 1000,
                        "runtime_stats": stats,
                    }
                )
            version = reference._cuda.version
    result = {
        "metadata": {
            "commit": commit,
            "source_sha256": sources,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "gpu": command(
                [
                    "nvidia-smi",
                    "--query-gpu=name,driver_version",
                    "--format=csv,noheader",
                    "-i",
                    str(args.device),
                ]
            ),
            "device": args.device,
            "compiler_configuration": compiler_configuration,
            "architectures": architectures,
            "build_configuration": "Release",
            "cpu": cpu_model(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cryptography": cryptography.__version__,
            "openssl": openssl.openssl_version_text(),
            "library_version": version,
            "library_sha256": hashlib.sha256(
                Path(args.library).read_bytes()
            ).hexdigest(),
            "timing_scope": "Synchronous Python API, warmed buffers; includes copies and clearing; excludes table/key import, batch formation and oracle checks.",
            "cpu_scope": "Single Python thread, cached OpenSSL private key, deterministic ECDSA and low-s encoding.",
            "comparison": "Identical key/digests within each run. Backend order rotates each iteration. Separate context per backend and batch size.",
        },
        "rows": rows,
    }
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"PASS: {len(rows)} rows, every signature matches OpenSSL. {path}")


if __name__ == "__main__":
    main()
