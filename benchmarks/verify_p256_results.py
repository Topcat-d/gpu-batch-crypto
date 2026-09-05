"""SPDX-License-Identifier: Apache-2.0. Verify recorded P-256 backend comparisons.

Checks published bytes, measured-commit source hashes, timing and accounting.
Does not execute GPU work or independently attest the measurements.
"""

import hashlib
import json
import math
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
directory = ROOT / "benchmarks/p256_results"
files = sorted(directory.glob("*.json"))
checksums = {}
for line in (directory / "SHA256SUMS").read_text().splitlines():
    digest, name = line.split("  ", 1)
    if name in checksums:
        raise RuntimeError("duplicate checksum entry")
    checksums[name] = digest
if not files or set(checksums) != {path.name for path in files}:
    raise RuntimeError("checksum inventory mismatch")
cells = 0
for path in files:
    if hashlib.sha256(path.read_bytes()).hexdigest() != checksums[path.name]:
        raise RuntimeError(f"{path.name}: checksum mismatch")
    data = json.loads(path.read_text())
    meta = data["metadata"]
    for file, digest in meta["source_sha256"].items():
        blob = subprocess.check_output(
            ["git", "show", meta["commit"] + ":" + file], cwd=ROOT
        )
        if hashlib.sha256(blob).hexdigest() != digest:
            raise RuntimeError(f"{path.name}: measured-source mismatch: {file}")
    required_sources = {
        "src/p256/fixed_base.cuh",
        "src/engine/crypto_engine.cu",
        "src/abi/batchcrypto_abi.cpp",
        "data/p256/comb_w8.bin",
        "data/p256/full_window_w8.bin",
        "benchmarks/run_p256_backends.py",
    }
    if not required_sources <= meta["source_sha256"].keys():
        raise RuntimeError("incomplete source inventory")
    seen = set()
    for row in data["rows"]:
        key = row["backend"], row["batch"]
        if key in seen:
            raise RuntimeError("duplicate row")
        seen.add(key)
        samples = row["batch_seconds"]
        iterations = row["iterations"]
        batch = row["batch"]
        n = batch * iterations
        if (
            iterations < 3
            or len(samples) != iterations
            or not all(math.isfinite(t) and t > 0 for t in samples)
        ):
            raise RuntimeError("invalid timing samples")
        if row["total_operations"] != n or row["outputs_checked"] != n:
            raise RuntimeError("incomplete correctness accounting")
        if not math.isclose(n / sum(samples), row["ops_per_second"], rel_tol=1e-10):
            raise RuntimeError("operation rate mismatch")
        if not math.isclose(
            sum(samples) * 1000 / iterations, row["mean_batch_ms"], rel_tol=1e-10
        ):
            raise RuntimeError("latency arithmetic mismatch")
        stats = row["runtime_stats"]
        if row["backend"] == "cpu":
            if stats is not None:
                raise RuntimeError("CPU row has GPU accounting")
        elif (
            stats["calls"] != iterations + 1
            or stats["submitted"] != batch * (iterations + 1)
            or stats["completed"] != stats["submitted"]
            or stats["item_errors"]
            or stats["call_errors"]
        ):
            raise RuntimeError("GPU accounting mismatch")
        cells += 1
    expected = {
        (backend, batch)
        for backend in ("cpu", "reference", "comb_w8", "full_window_w8")
        for batch in (1, 8, 64, 256, 1024, 4096)
    }
    if seen != expected:
        raise RuntimeError("incomplete backend/batch sweep")
print(
    f"PASS: {len(files)} P-256 comparisons, {cells} rows, source hashes and accounting."
)
