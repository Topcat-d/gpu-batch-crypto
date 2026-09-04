"""SPDX-License-Identifier: Apache-2.0. Check arithmetic and source provenance.
Requires local Git history for each measured commit. Does not rerun GPU work.
"""

import hashlib
import json
import math
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
files = sorted((ROOT / "benchmarks/results").glob("*.json"))
if not files:
    raise RuntimeError("no recorded matrices")
checksums = {}
for line in (ROOT / "benchmarks/results/SHA256SUMS").read_text().splitlines():
    digest, name = line.split("  ", 1)
    if name in checksums:
        raise RuntimeError("duplicate checksum entry")
    checksums[name] = digest
if set(checksums) != {path.name for path in files}:
    raise RuntimeError("checksum inventory mismatch")
cells = 0
for path in files:
    if hashlib.sha256(path.read_bytes()).hexdigest() != checksums[path.name]:
        raise RuntimeError(f"{path.name}: published checksum mismatch")
    data = json.loads(path.read_text())
    meta = data["metadata"]
    for file, digest in meta["source_sha256"].items():
        blob = subprocess.check_output(
            ["git", "show", meta["commit"] + ":" + file], cwd=ROOT
        )
        if hashlib.sha256(blob).hexdigest() != digest:
            raise RuntimeError(f"{path.name}: source mismatch: {file}")
    seen = set()
    for row in data["rows"]:
        key = (row["operation"], row["payload_bytes"], row["batch"], row.get("backend"))
        if key in seen:
            raise RuntimeError("duplicate matrix row")
        seen.add(key)
        if row["status"] == "unsupported":
            if not row.get("reason"):
                raise RuntimeError("unexplained unsupported cell")
            continue
        samples = row["batch_seconds"]
        n = row["batch"] * row["iterations"]
        if len(samples) != row["iterations"] or not all(
            math.isfinite(t) and t > 0 for t in samples
        ):
            raise RuntimeError("invalid timing samples")
        if row["total_operations"] != n or row["outputs_checked"] != n:
            raise RuntimeError("incomplete correctness/accounting")
        if not math.isclose(sum(samples), row["total_seconds"], rel_tol=1e-10):
            raise RuntimeError("duration mismatch")
        if not math.isclose(n / sum(samples), row["ops_per_second"], rel_tol=1e-10):
            raise RuntimeError("operation rate mismatch")
        if not math.isclose(
            n * row["payload_bytes"] / sum(samples),
            row["input_bytes_per_second"],
            rel_tol=1e-10,
        ):
            raise RuntimeError("byte rate mismatch")
        cells += 1
    stats = meta["runtime_stats"]
    if (
        stats["submitted"] != stats["completed"]
        or stats["item_errors"]
        or stats["call_errors"]
    ):
        raise RuntimeError("runtime accounting is not clean")
print(
    f"PASS: {len(files)} matrices, {cells} measured rows, timing arithmetic and measured-commit source hashes."
)
