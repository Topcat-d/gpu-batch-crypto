"""SPDX-License-Identifier: Apache-2.0. Capture a bounded native pipeline comparison.

All signature verification is inside native elapsed time. Runs are sequential.
The default matrix takes about four minutes plus warm-up; no cloud provisioning.
"""

import argparse
import csv
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parents[1]


def command(args, timeout=30):
    return subprocess.check_output(
        args, cwd=ROOT, text=True, stderr=subprocess.STDOUT, timeout=timeout
    ).strip()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def system_cpu_times():
    """Aggregate CPU counters, with Windows kernel time including idle time."""
    if os.name == "nt":
        from ctypes import wintypes

        idle, kernel, user = (wintypes.FILETIME() for _ in range(3))
        fn = ctypes.WinDLL("kernel32", use_last_error=True).GetSystemTimes
        fn.argtypes = [ctypes.POINTER(wintypes.FILETIME)] * 3
        fn.restype = wintypes.BOOL
        if not fn(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            raise ctypes.WinError(ctypes.get_last_error())

        def value(t):
            return (t.dwHighDateTime << 32 | t.dwLowDateTime) / 10_000_000

        return {"total_s": value(kernel) + value(user), "idle_s": value(idle)}
    if Path("/proc/stat").exists():
        values = list(
            map(int, Path("/proc/stat").read_text().splitlines()[0].split()[1:9])
        )
        scale = os.sysconf("SC_CLK_TCK")
        return {
            "total_s": sum(values) / scale,
            "idle_s": (values[3] + values[4]) / scale,
        }
    return None


def system_cpu_percent(before, after):
    if not before or not after:
        return None
    total = after["total_s"] - before["total_s"]
    idle = after["idle_s"] - before["idle_s"]
    if total <= 0 or not 0 <= idle <= total:
        return None
    return 100 * (total - idle) / total


def telemetry():
    fields = [
        "index",
        "name",
        "display_active",
        "pstate",
        "utilization.gpu",
        "memory.used",
        "power.draw",
        "clocks.gr",
        "temperature.gpu",
    ]
    raw = command(
        [
            "nvidia-smi",
            "--query-gpu=" + ",".join(fields),
            "--format=csv,noheader,nounits",
        ],
        timeout=5,
    )
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "system_cpu_times": system_cpu_times(),
        "gpus": [
            dict(zip(fields, (value.strip() for value in row)))
            for row in csv.reader(raw.splitlines())
        ],
    }


def quiet_gpus(samples, device=None):
    def selected(sample):
        gpus = sample.get("gpus", [])
        if device is not None:
            gpus = [gpu for gpu in gpus if gpu.get("index") == str(device)]
            if len(gpus) != 1:
                return []
        return gpus

    return len(samples) == 3 and all(
        selected(sample)
        and all(
            gpu.get("utilization.gpu", "").isdigit()
            and int(gpu["utilization.gpu"]) <= 5
            for gpu in selected(sample)
        )
        for sample in samples
    )


def preflight(device=None):
    samples = []
    # Up to six observations allow prior benchmark utilization to age out.
    for _ in range(6):
        if samples:
            time.sleep(1)
        sample = telemetry()
        sample["system_cpu_percent"] = system_cpu_percent(
            samples[-1].get("system_cpu_times") if samples else None,
            sample["system_cpu_times"],
        )
        samples.append(sample)
        if quiet_gpus(samples[-3:], device):
            return samples, True
    return samples, False


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
    p.add_argument(
        "--preflight-scope",
        choices=("all-gpus", "target-gpu"),
        default="all-gpus",
        help="target-gpu requires an idle selected device and records the shared host explicitly",
    )
    p.add_argument(
        "--allow-contended",
        action="store_true",
        help="explicitly label a diagnostic run when another GPU workload is active",
    )
    p.add_argument("--output", required=True)
    a = p.parse_args()
    target = Path(a.output)
    if target.exists():
        p.error("output exists; preserve earlier captures")
    if command(["git", "diff", "--name-only", "HEAD"]):
        p.error("commit tracked changes before measurement")
    required_device = a.device if a.preflight_scope == "target-gpu" else None
    initial_preflight, quiet = preflight(required_device)
    if not quiet and not a.allow_contended:
        p.error(
            "Required GPU activity exceeds 5% or is unavailable in preflight; pause work on the selected scope or explicitly use --allow-contended for diagnostic data"
        )
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
        preflight_telemetry=initial_preflight,
        preflight_quiet=quiet,
        preflight_scope=a.preflight_scope,
        selected_device=a.device,
        contention_policy="diagnostic"
        if a.allow_contended
        else "idle target GPU; shared CPU host with background activity recorded"
        if required_device is not None
        else "quiet GPU preflight; not an exclusive-host guarantee",
        monitoring="nvidia-smi and aggregate system CPU counters sampled by the parent process each second; monitoring CPU cost is outside child process_cpu_s; utilization is not exclusive-host proof or wall-system energy",
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
        trial_preflight, trial_quiet = preflight(required_device)
        if not trial_quiet and not a.allow_contended:
            raise RuntimeError(
                "GPU became busy before a trial; incomplete capture retained without a performance claim"
            )
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
        samples = []
        stop = threading.Event()

        def monitor():
            while not stop.is_set():
                try:
                    sample = telemetry()
                    sample["system_cpu_percent"] = system_cpu_percent(
                        samples[-1].get("system_cpu_times") if samples else None,
                        sample["system_cpu_times"],
                    )
                    samples.append(sample)
                except Exception as exc:
                    samples.append({"error": str(exc)})
                stop.wait(1)

        observer = threading.Thread(target=monitor, daemon=True)
        observer.start()
        try:
            result = subprocess.run(
                args,
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                timeout=a.seconds + 90,
            )
        finally:
            stop.set()
            observer.join(timeout=10)
        if result.returncode:
            target.with_suffix(".failure.txt").write_text(
                result.stdout + result.stderr, encoding="utf-8"
            )
            raise RuntimeError("native benchmark failed; no performance claim accepted")
        row = json.loads(result.stdout)
        row["command"] = [paths[0].name] + args[1:]
        row["timestamp_utc"] = started
        row["telemetry"] = samples
        row["preflight_telemetry"] = trial_preflight
        row["preflight_quiet"] = trial_quiet
        rows.append(row)
        target.write_text(
            json.dumps(
                {"metadata": meta, "rows": rows, "complete": len(rows) == len(cells)},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(
            f"{mode} workers={workers} keys={keys} offered={rate}: {row['goodput_rps']:.0f} within-SLO/s; p99={row['latency_p99_ms']:.2f}ms; late={row['late']} expired={row['expired']}",
            flush=True,
        )


if __name__ == "__main__":
    main()
