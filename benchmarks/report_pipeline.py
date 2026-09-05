"""SPDX-License-Identifier: Apache-2.0. CSV includes overload outcomes and matched cost ratios."""

import argparse
import csv
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def pair_key(row):
    return tuple(
        row.get(k, "caller" if k == "gpu_dispatch" else None)
        for k in (
            "workers",
            "keys",
            "offered_rate",
            "max_batch",
            "gpu_min_batch",
            "max_wait_ms",
            "slo_ms",
            "duration_s",
            "payload_bytes",
            "device",
            "gpu_dispatch",
        )
    )


def cpu_samples(row, field):
    return [
        s["system_cpu_percent"]
        for s in row.get(field, [])
        if s.get("system_cpu_percent") is not None
    ]


def render():
    output = io.StringIO(newline="")
    fields = [
        "capture",
        "qualification",
        "gpu",
        "mode",
        "workers",
        "keys",
        "max_batch",
        "gpu_min_batch",
        "gpu_dispatch",
        "max_wait_ms",
        "duration_s",
        "slo_ms",
        "offered_rate",
        "goodput_rps",
        "within_slo_fraction",
        "latency_p99_ms",
        "rejected",
        "expired",
        "late",
        "failed",
        "process_cpu_s",
        "elapsed_s",
        "mean_cpu_cores",
        "gpu_items",
        "cpu_items",
        "gpu_fraction_of_verified",
        "mean_batch_size",
        "preflight_system_cpu_min_percent",
        "preflight_system_cpu_max_percent",
        "during_system_cpu_min_percent",
        "during_system_cpu_max_percent",
        "prepare_worker_s",
        "sign_worker_s",
        "verify_worker_s",
        "usd_per_million_per_hourly_dollar",
        "paired_hybrid_cpu_goodput_ratio",
        "paired_deadline_quality_pass",
    ]
    writer = csv.DictWriter(output, fields, lineterminator="\n")
    writer.writeheader()
    for path in sorted((ROOT / "benchmarks/pipeline_results").glob("*.json")):
        data = json.loads(path.read_text())
        conditions = json.loads(
            (ROOT / "benchmarks/pipeline_conditions.json").read_text()
        )
        cpus = {pair_key(r): r for r in data["rows"] if r["mode"] == "cpu"}
        for r in data["rows"]:
            row = {k: r[k] for k in fields if k in r}
            row.update(
                capture=path.name,
                qualification=conditions["qualification"]
                if path.name in conditions["captures"]
                else data["metadata"].get("contention_policy", "unqualified"),
                gpu=data["metadata"]["gpu"].split(",")[0],
                within_slo_fraction=r["within_slo"] / r["offered"],
                mean_cpu_cores=r["process_cpu_s"] / r["elapsed_s"],
                gpu_fraction_of_verified=r["gpu_items"] / r["verified"]
                if r["verified"]
                else 0,
                mean_batch_size=r["verified"] / (r["cpu_batches"] + r["gpu_batches"])
                if r["verified"]
                else 0,
                usd_per_million_per_hourly_dollar=1e6 / (3600 * r["goodput_rps"])
                if r["goodput_rps"]
                else "undefined",
            )
            for label, field in (
                ("preflight", "preflight_telemetry"),
                ("during", "telemetry"),
            ):
                samples = cpu_samples(r, field)
                row[f"{label}_system_cpu_min_percent"] = min(samples) if samples else ""
                row[f"{label}_system_cpu_max_percent"] = max(samples) if samples else ""
            cpu = cpus.get(pair_key(r))
            row["paired_hybrid_cpu_goodput_ratio"] = (
                r["goodput_rps"] / cpu["goodput_rps"]
                if r["mode"] == "hybrid" and cpu and cpu["goodput_rps"]
                else ""
            )
            row["paired_deadline_quality_pass"] = (
                r["within_slo"] / r["offered"] >= 0.99
                and cpu["within_slo"] / cpu["offered"] >= 0.99
                if r["mode"] == "hybrid" and cpu
                else ""
            )
            writer.writerow(row)
    return output.getvalue()


def plot(preview=False):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {"svg.fonttype": "none", "svg.hashsalt": "batchcrypto-pipeline-diagnostic"}
    )

    figure, axes = plt.subplots(2, 2, figsize=(11, 7), constrained_layout=True)
    for line, (card, filename) in enumerate(
        (
            ("RTX 4070 Ti", "rtx4070ti-b64-20260905-r1.json"),
            ("RTX 3060", "rtx3060-b64-20260905-r1.json"),
        )
    ):
        data = json.loads((ROOT / "benchmarks/pipeline_results" / filename).read_text())
        for mode, color in (("cpu", "#2563eb"), ("hybrid", "#d97706")):
            rows = sorted(
                (
                    r
                    for r in data["rows"]
                    if r["workers"] == 8 and r["keys"] == 1 and r["mode"] == mode
                ),
                key=lambda r: r["offered_rate"],
            )
            x = [r["offered_rate"] / 1000 for r in rows]
            axes[line, 0].plot(
                x,
                [r["goodput_rps"] / 1000 for r in rows],
                "o-",
                color=color,
                label=mode,
            )
            axes[line, 1].plot(
                x, [r["latency_p99_ms"] for r in rows], "o-", color=color, label=mode
            )
        axes[line, 0].plot(
            [20, 60], [20, 60], "--", color="#6b7280", label="all offered work"
        )
        axes[line, 1].axhline(10, linestyle="--", color="#6b7280", label="10 ms target")
        axes[line, 0].set_ylabel("Within-deadline requests/s (thousands)")
        axes[line, 1].set_ylabel("p99 of verified requests (ms)")
        for axis in axes[line]:
            axis.set_title(card + " campaign — shared host")
            axis.set_xlabel("Offered requests/s (thousands)")
            axis.grid(alpha=0.2)
            axis.legend(fontsize=8)
            axis.set_ylim(bottom=0)
    figure.suptitle(
        "Diagnostic data: background GPU activity discovered after campaign\n8 CPU workers · 1 key · maximum batch 64 · 5 seconds/cell",
        fontsize=12,
    )
    destination = ROOT / "docs/assets/pipeline-diagnostic.svg"
    figure.savefig(destination, metadata={"Date": None}, bbox_inches="tight")
    destination.write_text(
        "\n".join(line.rstrip() for line in destination.read_text().splitlines())
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    if preview:
        preview_path = ROOT / "dist/pipeline-diagnostic.png"
        preview_path.parent.mkdir(exist_ok=True)
        figure.savefig(preview_path, dpi=140, bbox_inches="tight")
    plt.close(figure)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--check", action="store_true")
    p.add_argument("--plot", action="store_true")
    p.add_argument("--preview", action="store_true")
    a = p.parse_args()
    path = ROOT / "benchmarks/pipeline.csv"
    text = render()
    if a.check:
        if path.read_text() != text:
            raise SystemExit("pipeline CSV is stale")
        print("PASS: pipeline CSV matches captures.")
    else:
        path.write_text(text, encoding="utf-8", newline="\n")
    if a.plot:
        plot(a.preview)
