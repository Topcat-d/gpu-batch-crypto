"""SPDX-License-Identifier: Apache-2.0. CSV includes overload outcomes and matched cost ratios."""

import argparse
import csv
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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
        "prepare_worker_s",
        "sign_worker_s",
        "verify_worker_s",
        "usd_per_million_per_hourly_dollar",
        "paired_hybrid_cpu_goodput_ratio",
    ]
    writer = csv.DictWriter(output, fields, lineterminator="\n")
    writer.writeheader()
    for path in sorted((ROOT / "benchmarks/pipeline_results").glob("*.json")):
        data = json.loads(path.read_text())
        conditions = json.loads(
            (ROOT / "benchmarks/pipeline_conditions.json").read_text()
        )
        cpus = {
            (r["workers"], r["keys"], r["offered_rate"], r["max_batch"]): r
            for r in data["rows"]
            if r["mode"] == "cpu"
        }
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
                usd_per_million_per_hourly_dollar=1e6 / (3600 * r["goodput_rps"])
                if r["goodput_rps"]
                else "undefined",
            )
            cpu = cpus.get((r["workers"], r["keys"], r["offered_rate"], r["max_batch"]))
            row["paired_hybrid_cpu_goodput_ratio"] = (
                r["goodput_rps"] / cpu["goodput_rps"]
                if r["mode"] == "hybrid" and cpu and cpu["goodput_rps"]
                else ""
            )
            writer.writerow(row)
    return output.getvalue()


def plot():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

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
    plt.close(figure)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--check", action="store_true")
    p.add_argument("--plot", action="store_true")
    a = p.parse_args()
    path = ROOT / "benchmarks/pipeline.csv"
    text = render()
    if a.check:
        if path.read_text() != text:
            raise SystemExit("pipeline CSV is stale")
        print("PASS: pipeline CSV matches captures.")
    else:
        path.write_text(text, encoding="utf-8")
    if a.plot:
        plot()
