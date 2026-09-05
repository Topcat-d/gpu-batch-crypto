"""SPDX-License-Identifier: Apache-2.0. Fixed ready-wave campaign with provenance."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import subprocess
import threading

from run_pipeline import ROOT, command, digest, preflight, system_cpu_percent, telemetry


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", required=True)
    parser.add_argument("--library", required=True)
    parser.add_argument("--openssl-library", required=True)
    parser.add_argument("--device", type=int, required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        parser.error("preserve previous captures: output already exists")
    if command(["git", "status", "--porcelain", "--untracked-files=normal"]):
        parser.error("commit the experiment before measurement")
    paths = [
        Path(p).resolve() for p in (args.executable, args.library, args.openssl_library)
    ]
    if args.device < 0 or any(not p.is_file() for p in paths):
        parser.error("invalid device or missing executable/library")
    env = os.environ.copy()
    env["PATH"] = (
        os.pathsep.join(str(p.parent) for p in paths) + os.pathsep + env["PATH"]
    )
    source = command(["git", "ls-files"]).splitlines()
    metadata = {
        "commit": command(["git", "rev-parse", "HEAD"]),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "source_sha256": {
            f: digest(ROOT / f)
            for f in source
            if f.startswith(("src/", "include/", "data/p256/", "benchmarks/native/"))
            or f
            in (
                "benchmarks/run_ready_wave.py",
                "benchmarks/verify_ready_wave.py",
                "benchmarks/READY_WAVE_CAMPAIGN.md",
                "benchmarks/run_pipeline.py",
                "benchmarks/verify_pipeline.py",
            )
        },
        "binaries": {
            name: {"file": p.name, "sha256": digest(p)}
            for name, p in zip(("ready_wave", "batchcrypto", "openssl"), paths)
        },
        "platform": platform.platform(),
        "cpu": platform.processor(),
        "logical_cpus": os.cpu_count(),
        "selected_device": args.device,
        "gpu": command(
            [
                "nvidia-smi",
                "-i",
                str(args.device),
                "--query-gpu=name,driver_version,memory.total,pci.bus_id",
                "--format=csv,noheader",
            ]
        ),
        "conditions": "idle selected GPU; shared CPU host; parent telemetry outside child process CPU time; GPU board power is not wall-system energy",
        "scope": "closed-loop ready waves: claim creation, JOSE wire encoding, signing and all-output public-key verification; excludes general claim parsing, policy, ledger, network, settlement, key setup and warm-up",
        "cpu_es256_nonce": "randomized",
        "gpu_es256_nonce": "deterministic RFC6979",
        "independent_verifier": "PyJWT 2.13.0; sampled wire tokens outside native timing",
    }
    if os.name == "nt":
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        ) as key:
            metadata["cpu"] = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
    cells = []
    for repeat in (1, 2):
        modes = ["cpu-es256", "cpu-eddsa", "hybrid-es256"]
        if repeat == 2:
            modes.reverse()
        for wave, keys in [
            (1, 1),
            (8, 1),
            (64, 1),
            (256, 1),
            (1024, 1),
            (4096, 1),
            (4096, 16),
        ]:
            for workers in (4, 8):
                cells.extend((repeat, mode, wave, keys, workers) for mode in modes)
    rows = []
    output.parent.mkdir(parents=True, exist_ok=True)

    def save(complete=False, failure=None):
        output.write_text(
            json.dumps(
                {
                    "metadata": metadata,
                    "complete": complete,
                    "failure": failure,
                    "rows": rows,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )

    save()
    for repeat, mode, wave, keys, workers in cells:
        before, quiet = preflight(args.device)
        if not quiet:
            save(failure="selected GPU failed idle preflight")
            raise RuntimeError("selected GPU is busy; partial capture preserved")
        samples, stop = [], threading.Event()

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

        cmd = [
            str(paths[0]),
            "--mode",
            mode,
            "--wave",
            str(wave),
            "--keys",
            str(keys),
            "--workers",
            str(workers),
            "--device",
            str(args.device),
            "--seconds",
            "3",
        ]
        observer = threading.Thread(target=monitor, daemon=True)
        observer.start()
        try:
            result = subprocess.run(
                cmd, cwd=ROOT, env=env, text=True, capture_output=True, timeout=60
            )
        except Exception as exc:
            save(failure=str(exc))
            raise
        finally:
            stop.set()
            observer.join(timeout=10)
        if result.returncode:
            save(failure=result.stderr)
            raise RuntimeError("native wave failed; partial capture preserved")
        row = json.loads(result.stdout)
        row.update(
            repeat=repeat,
            command=[paths[0].name] + cmd[1:],
            preflight_telemetry=before,
            preflight_quiet=quiet,
            telemetry=samples,
        )
        rows.append(row)
        save(complete=len(rows) == len(cells))
        print(
            f"{len(rows)}/{len(cells)} r{repeat} {mode} wave={wave} keys={keys} workers={workers}: {row['throughput_rps']:.0f}/s; p99={row['p99_ms']:.2f}ms; within50={row['within_50ms'] / row['verified']:.2%}",
            flush=True,
        )


if __name__ == "__main__":
    main()
