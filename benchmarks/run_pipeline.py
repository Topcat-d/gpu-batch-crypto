"""SPDX-License-Identifier: Apache-2.0. Capture a bounded native pipeline comparison.

All signature verification is inside native elapsed time. Runs are sequential.
The default matrix takes about four minutes plus warm-up; no cloud provisioning.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def command(args):
    return subprocess.check_output(
        args, cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--executable", required=True)
    p.add_argument("--library", required=True)
    p.add_argument("--openssl-library", required=True)
    p.add_argument("--device", type=int, default=0)
    p.add_argument("--seconds", type=float, default=5)
    p.add_argument("--rates", default="10000,40000,80000")
    p.add_argument("--workers", default="1,4,8")
    p.add_argument("--keys", default="1,16")
    p.add_argument("--modes", default="cpu,hybrid")
    p.add_argument("--slo-ms", type=float, default=10)
    p.add_argument("--batch", type=int, default=256)
    p.add_argument("--gpu-min", type=int, default=64)
    p.add_argument("--gpu-dispatch", choices=("caller", "owner"), default="caller")
    p.add_argument("--output", required=True)
    a = p.parse_args()
    target = Path(a.output)
    if target.exists():
        p.error("output exists; preserve earlier captures")
    if command(["git", "diff", "--name-only", "HEAD"]):
        p.error("commit tracked changes before measurement")
    paths = [Path(x).resolve() for x in (a.executable, a.library, a.openssl_library)]
    env = os.environ.copy()
    env["PATH"] = (
        os.pathsep.join(str(x.parent) for x in paths) + os.pathsep + env["PATH"]
    )
    tracked = command(["git", "ls-files"]).splitlines()
    relevant = [
        f
        for f in tracked
        if f.startswith(
            ("src/", "include/", "data/p256/", "cmake/", "benchmarks/native/")
        )
        or f in ("CMakeLists.txt", "benchmarks/run_pipeline.py")
    ]
    meta = dict(
        commit=command(["git", "rev-parse", "HEAD"]),
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        source_sha256={f: digest(ROOT / f) for f in relevant},
        binaries={
            name: {"file": path.name, "sha256": digest(path)}
            for name, path in zip(("pipeline", "batchcrypto", "openssl"), paths)
        },
        platform=platform.platform(),
        cpu=platform.processor(),
        logical_cpus=os.cpu_count(),
        gpu=command(
            [
                "nvidia-smi",
                "-i",
                str(a.device),
                "--query-gpu=name,driver_version,memory.total,pci.bus_id",
                "--format=csv,noheader",
            ]
        ),
        windows_timer_request_ms=1 if os.name == "nt" else None,
        scope="in-process open-loop record generation + SHA256 + deterministic low-s signing + all-signature CPU verification; excludes network, TLS, authorization, payment, key setup and warm-up",
        workload=f"uniform round-robin key distribution; synthetic 512-byte records; random ephemeral keys; 8192 queued requests plus at most workers*{a.batch} in flight",
    )
    if os.name == "nt":
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        ) as key:
            meta["cpu"] = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
    # Validate every cell before launching any work.
    cells = [
        (w, k, r, mode)
        for w in map(int, a.workers.split(","))
        for k in map(int, a.keys.split(","))
        for r in map(int, a.rates.split(","))
        for mode in a.modes.split(",")
    ]
    if (
        len(cells) > 100
        or not 1 <= a.gpu_min <= a.batch <= 4096
        or not 0.01 <= a.seconds <= 120
        or any(
            not 1 <= w <= 64
            or not 1 <= k <= 16
            or not 1 <= r <= 2000000
            or r * a.seconds > 5000000
            or mode not in ("cpu", "gpu", "hybrid")
            for w, k, r, mode in cells
        )
    ):
        p.error("matrix outside bounded run budget")
    rows = []
    target.parent.mkdir(parents=True, exist_ok=True)
    for workers, keys, rate, mode in cells:
        args = [
            str(paths[0]),
            "--mode",
            mode,
            "--workers",
            str(workers),
            "--keys",
            str(keys),
            "--rate",
            str(rate),
            "--seconds",
            str(a.seconds),
            "--slo-ms",
            str(a.slo_ms),
            "--device",
            str(a.device),
            "--batch",
            str(a.batch),
            "--gpu-min",
            str(a.gpu_min),
            "--gpu-dispatch",
            a.gpu_dispatch,
        ]
        started = datetime.now(timezone.utc).isoformat()
        result = subprocess.run(
            args,
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=a.seconds + 90,
        )
        if result.returncode:
            target.with_suffix(".failure.txt").write_text(
                result.stdout + result.stderr, encoding="utf-8"
            )
            raise RuntimeError("native benchmark failed; no performance claim accepted")
        row = json.loads(result.stdout)
        row["command"] = [paths[0].name] + args[1:]
        row["timestamp_utc"] = started
        rows.append(row)
        target.write_text(
            json.dumps(
                {"metadata": meta, "rows": rows, "complete": len(rows) == len(cells)},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(
            f"{mode} workers={workers} keys={keys} offered={rate}: {row['goodput_rps']:.0f} within-SLO/s; p99={row['latency_p99_ms']:.2f}ms; late={row['late']} expired={row['expired']}",
            flush=True,
        )


if __name__ == "__main__":
    main()
