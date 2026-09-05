"""SPDX-License-Identifier: Apache-2.0. Derive P-256 profiles and optional chart."""

import argparse
import csv
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def records():
    rows = []
    for path in sorted((ROOT / "benchmarks/p256_results").glob("*.json")):
        data = json.loads(path.read_text())
        gpu = data["metadata"]["gpu"].split(",")[0].replace("NVIDIA GeForce ", "")
        cpu = {
            r["batch"]: r["ops_per_second"]
            for r in data["rows"]
            if r["backend"] == "cpu"
        }
        for row in data["rows"]:
            rows.append(
                {
                    "capture": path.name,
                    "gpu": gpu,
                    "backend": row["backend"],
                    "batch": row["batch"],
                    "signatures_per_second": row["ops_per_second"],
                    "mean_batch_ms": row["mean_batch_ms"],
                    "min_batch_ms": min(row["batch_seconds"]) * 1000,
                    "max_batch_ms": max(row["batch_seconds"]) * 1000,
                    "ratio_to_cpu": row["ops_per_second"] / cpu[row["batch"]],
                }
            )
    return rows


def plot(rows):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    matplotlib.rcParams.update({"svg.fonttype": "none", "font.size": 10})
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), layout="constrained")
    batches = (1, 8, 64, 256, 1024, 4096)
    colors = {
        "cpu": "#bd5700",
        "reference": "#737b86",
        "comb_w8": "#18978f",
        "full_window_w8": "#2455cb",
    }
    for column, gpu in enumerate(("RTX 4070 Ti", "RTX 3060")):
        for backend, color in colors.items():
            for chart_row, metric, scale in (
                (0, "signatures_per_second", 1000),
                (1, "mean_batch_ms", 1),
            ):
                ax = axes[chart_row, column]
                low, high, pooled = [], [], []
                for batch in batches:
                    selected = [
                        r
                        for r in rows
                        if r["gpu"] == gpu
                        and r["backend"] == backend
                        and r["batch"] == batch
                    ]
                    values = [r[metric] / scale for r in selected]
                    low.append(min(values))
                    high.append(max(values))
                    # Equal iteration counts: pooled rate uses total measured time.
                    value = (
                        len(values) / sum(1 / v for v in values)
                        if chart_row == 0
                        else sum(values) / len(values)
                    )
                    pooled.append(value)
                ax.fill_between(batches, low, high, color=color, alpha=0.16)
                ax.plot(batches, pooled, marker="o", color=color, label=backend)
                ax.set_xscale("log", base=2)
                ax.set_xticks(batches, [str(b) for b in batches])
                ax.grid(alpha=0.2)
        axes[0, column].set_title(gpu)
        axes[0, column].set_ylabel("Thousand signatures / second")
        axes[0, column].legend(fontsize=8, loc="upper left")
        axes[1, column].set_ylabel("Mean batch completion (ms, log scale)")
        axes[1, column].set_yscale("log")
        axes[1, column].set_xlabel("Items per synchronous call")
    fig.suptitle(
        "Public v0.2 P-256 backends · two runs per GPU, seven calls per cell\n"
        "Line: pooled timing. Band: range of individual run means, not confidence intervals."
    )
    svg = ROOT / "docs/assets/p256-backends.svg"
    fig.savefig(svg, metadata={"Date": None})
    svg.write_text(
        "\n".join(
            line.rstrip() for line in svg.read_text(encoding="utf-8").splitlines()
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (ROOT / "dist").mkdir(exist_ok=True)
    fig.savefig(ROOT / "dist/p256-backends.png", dpi=130)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--plot", action="store_true")
    args = parser.parse_args()
    rows = records()
    if not rows:
        raise RuntimeError("no P-256 records")
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    path = ROOT / "benchmarks/p256_profiles.csv"
    if args.check:
        if path.read_bytes() != output.getvalue().encode():
            raise RuntimeError("derived P-256 profiles differ")
    else:
        path.write_bytes(output.getvalue().encode())
    if args.plot:
        plot(rows)
    print(f"PASS: {len(rows)} derived P-256 profiles")


if __name__ == "__main__":
    main()
