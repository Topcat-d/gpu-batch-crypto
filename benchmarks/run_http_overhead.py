"""SPDX-License-Identifier: Apache-2.0. Bounded storage/cleanup comparison."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import threading
import time

import cryptography
import jwt
from cryptography.hazmat.backends.openssl.backend import backend

from run_http_access import ROOT, SCENARIOS, git, gpu_snapshot, idle_preflight, measure

VARIANTS = {"baseline": (0, False), "pool": (4, False), "pool-batch": (4, True), "batch": (0, True)}
HOLDOUT = [
    {"name": "holdout-full", "books": 32, "size": 8, "consume": 8, "planning_ms": 0},
    {"name": "holdout-quarter", "books": 32, "size": 8, "consume": 2, "planning_ms": 0},
    {"name": "urgent", "books": 1, "size": 1, "consume": 1, "planning_ms": 0},
]


def schedule(stage, gpu, candidate="pool-batch"):
    scenarios = SCENARIOS[1:3] if stage == "comparison" else HOLDOUT
    variants = ("baseline", "pool", "pool-batch") if stage == "comparison" else ("baseline", candidate)
    modes = [("direct", 1), ("cpu-books", 1), ("cpu-books", 4)] + ([("gpu-books", 1)] if gpu else [])
    cells = [(repeat, scenario, variant, mode, workers) for repeat in range(3)
             for scenario in scenarios for variant in variants for mode, workers in modes]
    random.Random(20260907 if stage == "comparison" else 20260908).shuffle(cells)
    return cells


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stage", choices=("comparison", "confirmation"), default="comparison")
    parser.add_argument("--candidate", choices=("pool-batch", "batch"), default="batch")
    parser.add_argument("--library", type=Path)
    parser.add_argument("--gpu-uuid")
    parser.add_argument("--library-source-commit")
    parser.add_argument("--library-build-note")
    args = parser.parse_args()
    if args.output.exists() or git("status", "--porcelain", "--untracked-files=normal"):
        parser.error("commit the campaign and preserve existing captures")
    if bool(args.library) != bool(args.gpu_uuid):
        parser.error("specify both library and GPU UUID")
    if args.library and (not args.library_source_commit or not args.library_build_note):
        parser.error("record native source and build provenance")
    args.device = 0
    devices = gpu_snapshot()
    if args.library:
        args.library = args.library.resolve(strict=True)
        matches = [d for d in devices if d["uuid"] == args.gpu_uuid]
        if len(matches) != 1:
            parser.error("selected GPU unavailable")
        args.device = int(matches[0]["index"])
    args.clients = 4 if args.stage == "comparison" else 2
    args.slo_ms, args.profile, args.final_checkpoint = 1000, True, True
    args.host_hourly = args.gpu_hourly = None
    paths = ["benchmarks/run_http_overhead.py", "benchmarks/run_http_access.py", "benchmarks/HTTP_OVERHEAD_CAMPAIGN.md",
             "python/batchcrypto/__init__.py", "python/batchcrypto/verified.py", "python/batchcrypto/jws.py"]
    paths += [str(p.relative_to(ROOT)).replace("\\", "/") for p in sorted((ROOT / "examples/http_access").glob("*.py"))]
    result = {"schema": 1, "campaign": "http-overhead", "stage": args.stage, "complete": False,
              "commit": git("rev-parse", "HEAD"), "timestamp_utc": datetime.now(timezone.utc).isoformat(),
              "candidate": args.candidate if args.stage == "confirmation" else None,
              "sources": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths},
              "environment": {"platform": platform.platform(), "cpu": platform.processor(), "logical_cpus": os.cpu_count(),
                              "python": platform.python_version(), "cryptography": cryptography.__version__,
                              "pyjwt": jwt.__version__, "openssl": backend.openssl_version_text(),
                              "gpus": devices, "selected_gpu_uuid": args.gpu_uuid,
                              "library_sha256": hashlib.sha256(args.library.read_bytes()).hexdigest() if args.library else None,
                              "library_source_commit": args.library_source_commit, "library_build_note": args.library_build_note},
              "contract": {"deadline_ms": 1000, "final_checkpoint_in_cost": True, "per_access_commit": "WAL synchronous FULL",
                           "http": "new loopback TCP connection per RPC; one process, synthetic identities and funds",
                           "profiling": "enabled for every variant; overlapping scopes cannot be added into wall time",
                           "prices": "not supplied; compare allocated wall time and cost ratios only"}, "cells": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    def save():
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for repeat, scenario, variant, mode, workers in schedule(args.stage, bool(args.library), args.candidate):
        args.ledger_pool_size, args.batch_cancel = VARIANTS[variant]
        preflight, idle_history = [], []
        if mode == "gpu-books":
            preflight, idle_history = idle_preflight(args.gpu_uuid)
            if preflight is None:
                result["interruption"] = {"reason": "GPU not idle", "idle_history": idle_history}
                save()
                raise RuntimeError("selected GPU unavailable or busy")
        telemetry, stopped = [], threading.Event()
        def sample():
            while not stopped.is_set():
                telemetry.append({"timestamp_utc": datetime.now(timezone.utc).isoformat(), "gpus": gpu_snapshot()})
                stopped.wait(.5)
        monitor = threading.Thread(target=sample, daemon=True)
        monitor.start()
        try:
            cell = measure(scenario, mode, workers, args)
        except Exception as exc:
            result["interruption"] = {"reason": type(exc).__name__, "scenario": scenario, "variant": variant, "mode": mode,
                                      "repeat": repeat, "preflight": preflight}
            save()
            raise
        finally:
            stopped.set()
            monitor.join(timeout=6)
        cell.update({"variant": variant, "ledger_pool_size": args.ledger_pool_size, "batch_cancel": args.batch_cancel,
                     "repeat": repeat, "preflight": preflight, "idle_history": idle_history, "gpu_telemetry": telemetry})
        result["cells"].append(cell)
        save()
        print(f"{scenario['name']} {variant} {mode}/{workers}: {cell['completed']}/{cell['attempted_accesses']} "
              f"done, {cell['late']} late; wall {cell['elapsed_seconds']:.3f}s, cleanup {cell['cleanup_ms']:.1f}ms", flush=True)
        if cell["failed"] or not cell["reconciled"] or cell["server_errors"] or cell["cleanup_errors"]:
            raise RuntimeError("correctness gate failed; capture preserved")
        if sum(c["elapsed_seconds"] for c in result["cells"]) > 600:
            raise RuntimeError("timed-work budget reached; capture preserved")
    result["complete"] = True
    save()


if __name__ == "__main__":
    main()
