"""SPDX-License-Identifier: Apache-2.0. Predeclared loopback access experiment."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time

import cryptography
import jwt
from cryptography.hazmat.backends.openssl.backend import backend

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples"))
from http_access.service import Fixture, rpc  # noqa: E402

SCENARIOS = [
    {"name": "urgent", "books": 1, "size": 1, "consume": 1, "planning_ms": 0},
    {"name": "ready-full", "books": 64, "size": 4, "consume": 4, "planning_ms": 0},
    {"name": "ready-quarter", "books": 64, "size": 4, "consume": 1, "planning_ms": 0},
    {"name": "overlap-full", "books": 64, "size": 4, "consume": 4, "planning_ms": 50},
]


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def percentile(values, p):
    return sorted(values)[max(0, math.ceil(p * len(values)) - 1)] if values else None


def gpu_snapshot():
    try:
        value = subprocess.check_output([
            "nvidia-smi", "--query-gpu=index,uuid,name,utilization.gpu,memory.used,power.draw",
            "--format=csv,noheader,nounits"], text=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return [dict(zip(("index", "uuid", "name", "utilization_percent", "memory_mib", "power_w"),
                         [p.strip() for p in line.split(",")])) for line in value.strip().splitlines()]
    except (OSError, subprocess.SubprocessError):
        return []


def peak_rss():
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in ("peak", "working", "peak_paged", "paged", "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile")]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        current = ctypes.windll.kernel32.GetCurrentProcess
        current.restype = wintypes.HANDLE
        get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
        get_memory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        if get_memory(current(), ctypes.byref(counters), counters.cb):
            return counters.peak
        return None
    import resource
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value if sys.platform == "darwin" else value * 1024


def host_cpu_ticks():
    """Host-wide counters, distinct from this process's measured CPU time."""
    if os.name == "nt":
        import ctypes
        idle, kernel, user = (ctypes.c_ulonglong() for _ in range(3))
        if ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return idle.value, kernel.value + user.value
    elif Path("/proc/stat").exists():
        ticks = [int(x) for x in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
        return ticks[3] + ticks[4], sum(ticks[:8])
    return None


def measure(scenario, mode, workers, args):
    with tempfile.TemporaryDirectory(prefix="http-bench-") as directory:
        with Fixture(directory, mode="gpu" if mode == "gpu-books" else "cpu", workers=workers,
                     library=args.library, device=args.device) as app:
            # Excluded warm-up exercises the selected signer, HTTP and ledger.
            warm = app.issue([["r31"]], request_id="warm")[0] if mode != "direct" else None
            app.access("r31", "warm-access", warm)
            before = app.ledger.audit()
            app.keys.signatures, app.keys.batches, app.consumer.verifications = 0, [], 0
            app.counts = dict.fromkeys(app.counts, 0)
            groups = [[f"r{j}" for j in range(scenario["size"])] for _ in range(scenario["books"])]
            jobs = [(i, resource) for i, group in enumerate(groups) for resource in group[:scenario["consume"]]]
            records = []
            error = None
            cpu_start, start = time.process_time(), time.perf_counter()
            host_start = host_cpu_ticks()
            with ThreadPoolExecutor(max_workers=1) as prep:
                future = prep.submit(app.issue, groups, request_id="measured") if mode != "direct" else None
                # A controlled independent-work interval, not an AI model timing.
                if scenario["planning_ms"]:
                    time.sleep(scenario["planning_ms"] / 1000)
                ready = time.perf_counter()
                try:
                    books = future.result() if future else None
                except Exception as exc:
                    books, error = None, type(exc).__name__
                prepared = time.perf_counter()

                def access(job):
                    i, resource = job
                    submitted = time.perf_counter()
                    try:
                        result = app.access(resource, f"read-{i}-{resource}", books[i] if books else None)
                        status = "ok"
                        receipt_id = result["receipt"]["id"]
                    except Exception as exc:
                        status, receipt_id = type(exc).__name__, None
                    end = time.perf_counter()
                    return {"status": status, "receipt_id": receipt_id,
                            "ready_to_complete_ms": (end - ready) * 1000,
                            "plan_to_complete_ms": (end - start) * 1000,
                            "request_ms": (end - submitted) * 1000}

                if error is None:
                    with ThreadPoolExecutor(max_workers=args.clients) as clients:
                        records = list(clients.map(access, jobs))
            delivery_end = time.perf_counter()
            # Cancel unused reservations on every signed path; count cleanup in
            # wall cost/goodput denominator, separately from delivery latency.
            cleanup_errors = []
            if books and scenario["consume"] < scenario["size"]:
                for book in books:
                    try:
                        rpc(app.issuer_port, "/cancel", {"book": book["book"]}, app.buyer_secret)
                    except Exception as exc:
                        cleanup_errors.append(type(exc).__name__)
            end = time.perf_counter()
            cpu_seconds = time.process_time() - cpu_start
            host_end = host_cpu_ticks()
            elapsed = end - start
            audit = app.ledger.audit()
            okay = [r for r in records if r["status"] == "ok"]
            on_time = sum(r["ready_to_complete_ms"] <= args.slo_ms for r in okay)
            reconciliation = (audit["receipts"] - before["receipts"] == len(okay)
                              and audit["publisher_accrued"] - before["publisher_accrued"] == len(okay) * 1000
                              and audit["accounts"][0]["reserved"] == 0
                              and len({r["receipt_id"] for r in okay}) == len(okay))
            # Unrecovered committed entitlements would fail reconciliation and
            # remain visible in the capture instead of becoming successful work.
            hourly = args.host_hourly
            if hourly is not None and mode == "gpu-books":
                hourly = hourly + args.gpu_hourly if args.gpu_hourly is not None else None
            cost = hourly * elapsed / 3600 if hourly is not None else None
            return {"scenario": scenario, "mode": mode, "cpu_signing_workers": workers,
                    "clients": args.clients, "slo_ms": args.slo_ms,
                    "attempted_accesses": len(jobs), "completed": len(okay), "on_time": on_time,
                    "late": len(okay) - on_time, "failed": len(jobs) - len(okay),
                    "unused_planned_accesses": scenario["books"] * (scenario["size"] - scenario["consume"]),
                    "elapsed_seconds": elapsed, "delivery_seconds": delivery_end - start,
                    "preparation_wait_after_ready_ms": (prepared - ready) * 1000,
                    "cleanup_ms": (end - delivery_end) * 1000, "process_cpu_seconds": cpu_seconds,
                    "process_peak_rss_bytes_cumulative": peak_rss(),
                    "host_cpu_busy_percent": (100 * (1 - (host_end[0] - host_start[0]) / (host_end[1] - host_start[1]))
                                               if host_start and host_end and host_end[1] > host_start[1] else None),
                    "completed_per_second": len(okay) / elapsed, "on_time_per_second": on_time / elapsed,
                    "first_access_ready_ms": min((r["ready_to_complete_ms"] for r in okay), default=None),
                    "p95_ready_ms": percentile([r["ready_to_complete_ms"] for r in okay], .95),
                    "p99_ready_ms": percentile([r["ready_to_complete_ms"] for r in okay], .99),
                    "p99_request_ms": percentile([r["request_ms"] for r in okay], .99),
                    "signatures": app.keys.signatures, "signing_batches": app.keys.batches,
                    "publisher_verifications": app.consumer.verifications, "http": app.counts,
                    "audit_before": before, "audit_after": audit, "reconciled": reconciliation,
                    "error": error, "server_errors": app.errors, "cleanup_errors": cleanup_errors,
                    "cost_usd": cost, "cost_per_million_on_time": cost * 1e6 / on_time if cost is not None and on_time else None,
                    "records": records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--library", type=Path)
    parser.add_argument("--gpu-uuid")
    parser.add_argument("--library-source-commit", help="source commit used to build the supplied native binary")
    parser.add_argument("--library-build-note", help="compiler, CUDA version and GPU architecture for that binary")
    parser.add_argument("--cpu-workers", default="1,4")
    parser.add_argument("--clients", type=int, default=4)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--slo-ms", type=float, default=1000)
    parser.add_argument("--host-hourly", type=float)
    parser.add_argument("--gpu-hourly", type=float)
    parser.add_argument("--smoke", action="store_true", help="urgent cell only; permit uncommitted source; not published evidence")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("preserve captures: output exists")
    if not 1 <= args.clients <= 16 or not 1 <= args.repeats <= 5 or not math.isfinite(args.slo_ms) or args.slo_ms <= 0:
        parser.error("invalid bounded campaign parameters")
    for price in (args.host_hourly, args.gpu_hourly):
        if price is not None and (not math.isfinite(price) or price < 0):
            parser.error("hourly costs must be finite and nonnegative")
    workers = [int(w) for w in args.cpu_workers.split(",")]
    if not workers or len(workers) > 4 or any(not 1 <= w <= 32 for w in workers) or len(set(workers)) != len(workers):
        parser.error("invalid CPU worker sweep")
    dirty = git("status", "--porcelain", "--untracked-files=normal")
    if dirty and not args.smoke:
        parser.error("commit campaign and harness before measurement")
    if bool(args.library) != bool(args.gpu_uuid):
        parser.error("GPU mode needs both --library and --gpu-uuid")
    if args.library and not args.smoke and (not args.library_source_commit or not args.library_build_note):
        parser.error("published GPU runs require native source commit and build note")
    args.device = 0
    devices = gpu_snapshot()
    if args.library:
        matches = [d for d in devices if d["uuid"] == args.gpu_uuid]
        if len(matches) != 1:
            parser.error("requested GPU UUID not available")
        args.device = int(matches[0]["index"])
        args.library = args.library.resolve(strict=True)
    sources = ["benchmarks/run_http_access.py", "benchmarks/HTTP_ACCESS_CAMPAIGN.md",
               "python/batchcrypto/verified.py", "python/batchcrypto/jws.py", "python/batchcrypto/__init__.py"]
    sources += [str(p.relative_to(ROOT)).replace("\\", "/") for p in sorted((ROOT / "examples/http_access").glob("*.py"))]
    result = {"schema": 1, "complete": False, "smoke": args.smoke,
              "commit": git("rev-parse", "HEAD"), "dirty": bool(dirty),
              "timestamp_utc": datetime.now(timezone.utc).isoformat(),
              "sources": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sources},
              "environment": {"platform": platform.platform(), "cpu": platform.processor(), "logical_cpus": os.cpu_count(),
                              "python": platform.python_version(), "cryptography": cryptography.__version__, "pyjwt": jwt.__version__,
                              "openssl": backend.openssl_version_text(), "sqlite": sqlite3.sqlite_version,
                              "storage": "local temporary directory; WAL; synchronous FULL; connection per operation",
                              "http": "two loopback listeners, one process, new TCP connection per RPC; no TLS",
                              "initial_gpus": devices, "selected_gpu_uuid": args.gpu_uuid,
                              "library_source_commit": args.library_source_commit, "library_build_note": args.library_build_note,
                              "library_sha256": hashlib.sha256(args.library.read_bytes()).hexdigest() if args.library else None},
              "cost_assumptions": {"host_hourly_usd": args.host_hourly, "additional_gpu_hourly_usd": args.gpu_hourly,
                                   "boundary": "whole measured wall interval including planning and cleanup; excludes startup, shutdown and warmup",
                                   "not_included": "deployment idle periods, billing minimums, network egress, real payment fees, labor"},
              "cells": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    schedule = [(repeat, scenario, mode, w) for repeat in range(args.repeats)
                for scenario in (SCENARIOS[:1] if args.smoke else SCENARIOS)
                for mode, w in [("direct", 1)] + [("cpu-books", w) for w in workers] + ([("gpu-books", 1)] if args.library else [])]
    random.Random(20260906).shuffle(schedule)
    for repeat, scenario, mode, w in schedule:
        preflight = []
        if mode == "gpu-books":
            for _ in range(3):
                snapshot = gpu_snapshot()
                selected = next((d for d in snapshot if d["uuid"] == args.gpu_uuid), None)
                if not selected or float(selected["utilization_percent"]) > 5:
                    raise RuntimeError("selected GPU is busy; stop without interrupting other work")
                preflight.append(snapshot)
                time.sleep(.1)
        telemetry, stop = [], threading.Event()
        def sample():
            while not stop.is_set():
                telemetry.append({"at_utc": datetime.now(timezone.utc).isoformat(), "gpus": gpu_snapshot()})
                stop.wait(.5)
        monitor = threading.Thread(target=sample, daemon=True)
        monitor.start()
        try:
            cell = measure(scenario, mode, w, args)
        finally:
            stop.set()
            monitor.join(timeout=6)
        cell.update({"repeat": repeat, "preflight": preflight, "gpu_telemetry": telemetry})
        result["cells"].append(cell)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
        print(f"{scenario['name']} {mode}/{w}: {cell['completed']}/{cell['attempted_accesses']} completed, "
              f"{cell['on_time']} on time; reconciled={cell['reconciled']}", flush=True)
        if not cell["reconciled"] or cell["failed"] or cell["server_errors"] or cell["cleanup_errors"]:
            raise RuntimeError("correctness gate failed; preserve capture and investigate")
    result["complete"] = True
    args.output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
