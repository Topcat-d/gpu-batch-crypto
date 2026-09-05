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
        cpus = {
            (r["workers"], r["keys"], r["offered_rate"], r["max_batch"]): r
            for r in data["rows"]
            if r["mode"] == "cpu"
        }
        for r in data["rows"]:
            row = {k: r[k] for k in fields if k in r}
            row.update(
                capture=path.name,
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


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--check", action="store_true")
    a = p.parse_args()
    path = ROOT / "benchmarks/pipeline.csv"
    text = render()
    if a.check:
        if path.read_text() != text:
            raise SystemExit("pipeline CSV is stale")
        print("PASS: pipeline CSV matches captures.")
    else:
        path.write_text(text, encoding="utf-8")
