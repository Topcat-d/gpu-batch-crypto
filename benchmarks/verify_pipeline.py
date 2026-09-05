"""SPDX-License-Identifier: Apache-2.0. Verify capture integrity and accounting, not independent attestation."""

import hashlib
import json
import math
from pathlib import Path
import subprocess

from run_pipeline import quiet_gpus, system_cpu_percent

ROOT = Path(__file__).resolve().parents[1]


def verify_telemetry(samples):
    if not samples:
        raise ValueError("missing telemetry")
    previous = None
    for sample in samples:
        if "error" in sample:
            raise ValueError("telemetry failed; measurement conditions incomplete")
        counters = sample.get("system_cpu_times")
        if counters is not None and (
            not all(math.isfinite(counters[k]) for k in ("total_s", "idle_s"))
            or not 0 <= counters["idle_s"] <= counters["total_s"]
        ):
            raise ValueError("invalid aggregate CPU counters")
        expected = system_cpu_percent(previous, counters)
        actual = sample.get("system_cpu_percent")
        if (expected is None) != (actual is None) or (
            expected is not None
            and (
                not math.isfinite(actual)
                or not math.isclose(actual, expected, abs_tol=1e-7)
            )
        ):
            raise ValueError("aggregate CPU utilization mismatch")
        if not sample.get("gpus"):
            raise ValueError("missing GPU observations")
        previous = counters


def verify_conditions(data):
    meta = data["metadata"]
    # Earlier diagnostic captures predate per-trial preflight and CPU counters.
    if "preflight_scope" not in meta:
        return
    scope = meta["preflight_scope"]
    if scope not in ("all-gpus", "target-gpu"):
        raise ValueError("unknown preflight scope")
    selected = meta["selected_device"]
    if type(selected) is not int or selected < 0:
        raise ValueError("invalid selected device")
    device = selected if scope == "target-gpu" else None
    if (
        scope == "target-gpu"
        and meta["contention_policy"] != "diagnostic"
        and "shared CPU host" not in meta["contention_policy"]
    ):
        raise ValueError("target-GPU preflight must disclose shared CPU host")
    for record in [meta, *data["rows"]]:
        samples = record["preflight_telemetry"]
        verify_telemetry(samples)
        quiet = quiet_gpus(samples[-3:], device)
        if record["preflight_quiet"] is not quiet:
            raise ValueError("preflight result mismatch")
        if not quiet and meta["contention_policy"] != "diagnostic":
            raise ValueError("busy preflight without diagnostic qualification")
    for row in data["rows"]:
        if row["device"] != selected:
            raise ValueError("capture device mismatch")
        verify_telemetry(row["telemetry"])


def verify_row(r):
    if not all(math.isfinite(v) for v in r.values() if isinstance(v, (float, int))):
        raise ValueError("nonfinite metric")
    for k in (
        "offered",
        "rejected",
        "expired",
        "failed",
        "verified",
        "within_slo",
        "late",
        "cpu_items",
        "gpu_items",
        "cpu_batches",
        "gpu_batches",
    ):
        if type(r[k]) is not int or r[k] < 0:
            raise ValueError("invalid counter")
    if (
        r["offered"] != r["rejected"] + r["expired"] + r["failed"] + r["verified"]
        or r["verified"] != r["within_slo"] + r["late"]
    ):
        raise ValueError("request accounting mismatch")
    if r["failed"] or r["cpu_items"] + r["gpu_items"] != r["verified"]:
        raise ValueError("failed or unaccounted execution")
    if not math.isclose(r["offered"], r["offered_rate"] * r["duration_s"], abs_tol=0.5):
        raise ValueError("offered trace mismatch")
    if r["elapsed_s"] < r["duration_s"] or not math.isclose(
        r["goodput_rps"], r["within_slo"] / r["elapsed_s"], rel_tol=1e-9
    ):
        raise ValueError("goodput mismatch")
    if r["queue_high_water"] > r["queue_capacity"] or r["queue_high_water"] < 0:
        raise ValueError("queue bound violated")
    if sum(r["latency_histogram_100us"].values()) != r["verified"]:
        raise ValueError("latency sample count mismatch")
    if (
        sum(int(n) * count for n, count in r["batch_histogram"].items())
        != r["verified"]
        or sum(r["batch_histogram"].values()) != r["cpu_batches"] + r["gpu_batches"]
    ):
        raise ValueError("batch sample mismatch")
    if any(
        not 1 <= int(n) <= r["max_batch"] or count <= 0
        for n, count in r["batch_histogram"].items()
    ):
        raise ValueError("batch outside bounds")
    if r["mode"] == "cpu" and r["gpu_items"]:
        raise ValueError("CPU row used GPU")
    if r["process_cpu_s"] < 0 or any(
        r[k] < 0
        for k in (
            "prepare_worker_s",
            "sign_worker_s",
            "verify_worker_s",
            "queue_request_s",
        )
    ):
        raise ValueError("negative time")
    previous = 0
    for label, fraction in (
        ("latency_p50_ms", 0.5),
        ("latency_p95_ms", 0.95),
        ("latency_p99_ms", 0.99),
        ("latency_max_ms", 1),
    ):
        value = r[label]
        if value < previous:
            raise ValueError("unordered quantiles")
        previous = value
        if r["verified"]:
            rank = math.ceil(fraction * r["verified"])
            count = 0
            for bucket, n in sorted(
                r["latency_histogram_100us"].items(), key=lambda item: int(item[0])
            ):
                count += n
                if count >= rank:
                    if (
                        not int(bucket) / 10 - 1e-7
                        <= value
                        <= (int(bucket) + 1) / 10 + 1e-7
                    ):
                        raise ValueError("quantile outside recorded histogram bucket")
                    break
    definite_good = sum(
        n
        for bucket, n in r["latency_histogram_100us"].items()
        if (int(bucket) + 1) / 10 <= r["slo_ms"]
    )
    possible_good = sum(
        n
        for bucket, n in r["latency_histogram_100us"].items()
        if int(bucket) / 10 <= r["slo_ms"]
    )
    if not definite_good <= r["within_slo"] <= possible_good:
        raise ValueError("SLO/histogram mismatch")


def main():
    directory = ROOT / "benchmarks/pipeline_results"
    hashes = {}
    for line in (directory / "SHA256SUMS").read_text().splitlines():
        sha, name = line.split("  ", 1)
        if name in hashes:
            raise ValueError("duplicate checksum")
        hashes[name] = sha
    files = sorted(directory.glob("*.json"))
    if not files or set(hashes) != {p.name for p in files}:
        raise ValueError("capture inventory mismatch")
    blobs = {}
    count = 0
    build = json.loads((ROOT / "benchmarks/pipeline_build.json").read_text())
    for path in files:
        if hashlib.sha256(path.read_bytes()).hexdigest() != hashes[path.name]:
            raise ValueError("capture checksum mismatch")
        data = json.loads(path.read_text())
        meta = data["metadata"]
        if data["complete"] is not True:
            raise ValueError("partial capture")
        verify_conditions(data)
        for file, sha in meta["source_sha256"].items():
            key = meta["commit"], file
            if key not in blobs:
                blobs[key] = hashlib.sha256(
                    subprocess.check_output(
                        ["git", "show", f"{key[0]}:{key[1]}"], cwd=ROOT
                    )
                ).hexdigest()
            if blobs[key] != sha:
                raise ValueError("measured-source hash mismatch")
        if (
            not {
                "benchmarks/native/pipeline.cpp",
                "benchmarks/run_pipeline.py",
                "src/abi/batchcrypto_abi.cpp",
            }
            <= meta["source_sha256"].keys()
        ):
            raise ValueError("missing source provenance")
        for name, value in meta["binaries"].items():
            allowed = {build["binaries"][name]["sha256"]}
            if name == "pipeline":
                allowed.update(
                    item["sha256"] for item in build.get("alternate_pipelines", [])
                )
            if value["sha256"] not in allowed:
                raise ValueError("build fingerprint mismatch")
        cells = set()
        for row in data["rows"]:
            verify_row(row)
            cell = tuple(
                row[k] for k in ("mode", "workers", "keys", "offered_rate", "max_batch")
            )
            cell += (row.get("gpu_dispatch", "caller"),)
            if cell in cells:
                raise ValueError("duplicate cell")
            cells.add(cell)
            count += 1
    print(
        f"PASS: {len(files)} pipeline captures, {count} rows; source/build fingerprints, timing, histograms and overload accounting."
    )


if __name__ == "__main__":
    main()
