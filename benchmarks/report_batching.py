"""SPDX-License-Identifier: Apache-2.0. Derive profiles from recorded measurements.

No GPU execution. --check verifies the CSV; --plot also needs matplotlib.
"""

import argparse
import csv
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASETS = [
    ("RTX 4070 Ti", "rtx4070ti-isolated-2026-09-04.json"),
    ("RTX 3060", "rtx3060-isolated-2026-09-04.json"),
]


def datasets():
    return [
        (name, json.loads((ROOT / "benchmarks/results" / file).read_text()))
        for name, file in DATASETS
    ]


def profiles():
    output = []
    for name, data in datasets():
        rows = [r for r in data["rows"] if r["status"] == "ok"]
        for operation, size in [
            ("p256_sign", 32),
            *[
                (op, size)
                for op in ("aes256gcm_seal", "sha256")
                for size in (1024, 65536, 1048576)
            ],
        ]:
            gpu = sorted(
                [
                    r
                    for r in rows
                    if r["operation"] == operation
                    and r["payload_bytes"] == size
                    and r["backend"] == "cuda"
                ],
                key=lambda r: r["batch"],
            )
            cpu = {
                r["batch"]: r
                for r in rows
                if r["operation"] == operation
                and r["payload_bytes"] == size
                and r["backend"] == "cpu"
            }
            peak = max(gpu, key=lambda r: r["ops_per_second"])
            chosen = [("highest_sampled_rate", peak)]
            if operation == "p256_sign":
                winners = [
                    r
                    for r in gpu
                    if r["ops_per_second"] > cpu[r["batch"]]["ops_per_second"]
                ]
                if winners:
                    chosen.insert(0, ("first_sampled_cpu_crossover", winners[0]))
            for profile, r in chosen:
                output.append(
                    {
                        "gpu": name,
                        "operation": operation,
                        "payload_bytes": size,
                        "profile": profile,
                        "batch": r["batch"],
                        "ops_per_second": f"{r['ops_per_second']:.3f}",
                        "input_MB_per_second": f"{r['input_bytes_per_second'] / 1e6:.3f}",
                        "mean_batch_ms": f"{r['total_seconds'] / r['iterations'] * 1000:.3f}",
                        "min_batch_ms": f"{min(r['batch_seconds']) * 1000:.3f}",
                        "max_batch_ms": f"{max(r['batch_seconds']) * 1000:.3f}",
                        "gpu_cpu_ratio": f"{r['ops_per_second'] / cpu[r['batch']]['ops_per_second']:.4f}",
                    }
                )
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(output[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(output)
    return stream.getvalue()


def plot():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    plt.rcParams.update(
        {"font.size": 10, "svg.fonttype": "none", "svg.hashsalt": "batchcrypto"}
    )
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), layout="constrained")
    colors = ("#1967b3", "#c45c16")
    for (name, data), color in zip(datasets(), colors):
        rows = sorted(
            [
                r
                for r in data["rows"]
                if r["status"] == "ok"
                and r["operation"] == "p256_sign"
                and r["backend"] == "cuda"
            ],
            key=lambda r: r["batch"],
        )
        x = [r["batch"] for r in rows]
        axes[0, 0].plot(
            x, [r["ops_per_second"] / 1000 for r in rows], "o-", label=name, color=color
        )
        axes[0, 1].plot(
            x,
            [r["total_seconds"] / r["iterations"] * 1000 for r in rows],
            "o-",
            label=name,
            color=color,
        )
    axes[0, 0].set(
        title="Initial v0.1: P-256 throughput",
        ylabel="Thousands of signatures / second",
    )
    axes[0, 1].set(
        title="Initial v0.1: mean batch completion", ylabel="Milliseconds per batch"
    )
    old = json.loads(
        (ROOT / "benchmarks/historical/rtx4070ti-20260317-envelope.json").read_text()
    )
    rows = old["summaries"]
    x = [r["batch_size"] for r in rows]
    axes[1, 0].plot(
        x, [r["avg_sig_per_sec"] / 1000 for r in rows], "o-", color="#596579"
    )
    axes[1, 1].plot(x, [r["avg_wall_ms"] for r in rows], "o-", color="#596579")
    axes[1, 0].set(
        title="Historical 4070 Ti: larger is not always faster",
        ylabel="Thousands of signatures / second",
    )
    axes[1, 1].set(
        title="Historical 4070 Ti: completion cost grows",
        ylabel="Milliseconds per logical batch",
    )
    axes[1, 1].set_yscale("log")
    for ax in axes.flat:
        ax.set_xscale("log", base=2)
        ax.set_xlabel("Batch size (log scale)")
        ax.grid(alpha=0.2)
        ax.spines[["top", "right"]].set_visible(False)
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    for ax in axes[0]:
        ax.legend(loc="upper left", frameon=False)
        ax.set_xticks([1, 8, 64, 256, 1024, 4096])
    for ax in axes[1]:
        ax.set_xticks([64, 256, 1024, 4096, 16384, 131072])
    fig.suptitle("Batching: throughput gained, latency spent", fontsize=17)
    fig.supxlabel(
        "Top: September 4, 2026 • 3 timed calls, warmed buffers, copies + clearing included.\n"
        "Bottom: March 17, 2026 • different execution path; timing archive, status checks only.\n"
        "Neither includes request arrival / batch-fill delay. Different rows are not a GPU ranking.",
        fontsize=9,
    )
    target = ROOT / "docs/assets"
    target.mkdir(exist_ok=True)
    fig.savefig(target / "batching.svg", metadata={"Date": None})
    svg = target / "batching.svg"
    svg.write_text(
        "\n".join(
            line.rstrip() for line in svg.read_text(encoding="utf-8").splitlines()
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    fig.savefig(ROOT / "dist/batching-preview.png", dpi=130)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--plot", action="store_true")
    args = parser.parse_args()
    path = ROOT / "benchmarks/batch_profiles.csv"
    generated = profiles()
    if args.check:
        if path.read_text() != generated:
            raise SystemExit("batch profiles differ from recorded data")
        print("PASS: batch profiles match recorded measurements.")
    else:
        path.write_text(generated, encoding="utf-8", newline="\n")
    if args.plot:
        plot()
