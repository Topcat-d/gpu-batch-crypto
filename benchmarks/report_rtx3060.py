"""SPDX-License-Identifier: Apache-2.0. Reproduce the RTX 3060 campaign tables."""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAMES = [f"rtx3060-target-20260905-{run}.json" for run in ("r1", "r2", "long")]
CONTROL_NAMES = [f"rtx3060-slo50-20260905-r{run}.json" for run in (1, 2)]


def captures():
    data = [
        json.loads((ROOT / "benchmarks/pipeline_results" / name).read_text())
        for name in NAMES
    ]
    if not all(d["complete"] for d in data):
        raise ValueError("campaign is incomplete")
    return data


def success(row):
    return 100 * row["within_slo"] / row["offered"]


def gpu_fraction(row):
    return 100 * row["gpu_items"] / row["verified"] if row["verified"] else 0


def span(values, places=1):
    return f"{min(values):,.{places}f}–{max(values):,.{places}f}"


def render():
    data = captures()
    control = [
        json.loads((ROOT / "benchmarks/pipeline_results" / name).read_text())
        for name in CONTROL_NAMES
    ]
    if not all(d["complete"] and len(d["rows"]) == 2 for d in control):
        raise ValueError("deadline control is incomplete")
    all_rows = [r for d in data + control for r in d["rows"]]
    preflight = [s for r in all_rows for s in r["preflight_telemetry"]]
    during = [s for r in all_rows for s in r["telemetry"]]
    pre_cpu = [
        s["system_cpu_percent"]
        for s in preflight
        if s["system_cpu_percent"] is not None
    ]
    during_cpu = [
        s["system_cpu_percent"] for s in during if s["system_cpu_percent"] is not None
    ]
    other_gpu = [
        int(g["utilization.gpu"])
        for s in preflight
        for g in s["gpus"]
        if g["index"] == "0"
    ]
    target_gpu = [
        int(g["utilization.gpu"])
        for r in all_rows
        for s in r["preflight_telemetry"][-3:]
        for g in s["gpus"]
        if g["index"] == "1"
    ]
    short_rows = [r for d in data[:2] for r in d["rows"]]
    pairs = []
    for workers in (4, 8):
        for rate in (10000, 20000, 40000):
            group = [
                r
                for r in short_rows
                if r["workers"] == workers and r["offered_rate"] == rate
            ]
            if len(group) != 4:
                raise ValueError("missing paired repeat")
            pairs.append((workers, rate, all(success(r) >= 99 for r in group)))
    passing = sum(ok for _, _, ok in pairs)
    lines = [
        "# RTX 3060: repeated request-pipeline measurements",
        "",
        f"**{passing} of {len(pairs)} paired short-run settings met the predeclared criterion:** at least 99% of all offered requests within 10 ms in both CPU and hybrid modes in both repeats. The selected RTX 3060 passed its idle preflight; the shared CPU and RTX 4070 Ti remained available to unrelated work. These are measurements of this shared host, not exclusive capacity or a production savings claim.",
        "",
        "This September 5, 2026 campaign follows a [plan committed before measurement](../benchmarks/RTX3060_CAMPAIGN.md). It uses the existing v0.3 native engine with atomic key epochs, full-window P-256 signing and independent CPU verification of every output before completing a batch. The CPU baseline uses cached native OpenSSL contexts, deterministic nonces and the same verification policy. No rental was provisioned.",
        "",
        "## What was measured",
        "",
        "- NVIDIA GeForce RTX 3060, 12 GB, device 1, display disabled; Ryzen 7 7800X3D, 16 logical CPUs; Windows, driver 610.62, CUDA 13.0.88, MSVC 19.44 and native OpenSSL 3.5.8.",
        "- 512-byte synthetic records; maximum batch 64; GPU minimum 64; 1 ms oldest-request fill wait; caller dispatch; 8,192 queued requests plus bounded in-flight batches. The 10 ms budget is an explicit experiment assumption.",
        "- Two 10-second sweeps at 4/8 workers, one key and 10k/20k/40k offered requests/s. CPU runs first in repeat 1; hybrid runs first in repeat 2. Four 30-second checks use 8 workers, 40k/s and one or sixteen keys.",
        "- After the 10 ms misses appeared, a separately predeclared 50 ms control repeats the one-key, 8-worker, 40k/s case twice in opposite mode order, 30 seconds/cell. Original 10 ms outcomes and criteria remain unchanged.",
        "- Latency starts at planned arrival and ends only after the entire output batch passes verification. Queueing, preparation, CPU hashing, signing, transfers and verification are included. Key setup, warm-up, network, TLS, authorization, payment, persistence and redundancy are excluded.",
        "",
        f"There are **{len(all_rows)} new rows**, **{sum(r['offered'] for r in all_rows):,} offered requests**, **{sum(r['verified'] for r in all_rows):,} independently verified completions**, and **{sum(r['failed'] for r in all_rows):,} verification/processing failures**. Timed workload totals {sum(r['duration_s'] for r in all_rows):g} seconds; setup and preflight add elapsed time. Rejection, expiry and late completion are separate outcomes retained in [raw captures](../benchmarks/pipeline_results) and the [CSV](../benchmarks/pipeline.csv). Counts and histograms are checked, not independently attested.",
        "",
        "## Host conditions",
        "",
        f"Before individual cells, sampled aggregate CPU utilization ranged **{span(pre_cpu)}%**; during cells it ranged **{span(during_cpu)}%**, including benchmark work. The other GPU's preflight utilization ranged **{span(other_gpu, 0)}%**. The final three selected-GPU observations before each cell ranged **{span(target_gpu, 0)}%**, within the 5% gate. These samples cannot prove that every interval was interference-free.",
        "",
        "Windows aggregate CPU utilization is calculated from successive GetSystemTimes counters: subtract idle time from kernel plus user time, then divide by total time. Kernel time already includes idle time. Process CPU seconds are recorded separately for the native benchmark; parent telemetry work is outside that process counter. GPU power readings are board telemetry, not wall-system energy. [Microsoft API semantics](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getsystemtimes).",
        "",
        "The harness requests a 1 ms Windows timer period and restores it at exit; that request is not a scheduling or deadline guarantee. Effective wake-up timing and host interference were not separately isolated in this campaign, so the missed deadlines cannot be attributed solely to cryptographic execution. [Windows timer-resolution behavior](https://learn.microsoft.com/en-us/windows/win32/api/timeapi/nf-timeapi-timebeginperiod).",
        "",
        "## Both short repeats",
        "",
        "Ranges below span the two observations; they are not confidence intervals. The pass criterion includes all offered requests, so dropping or expiring requests cannot improve it. p99 covers verified completions only and must be read together with the deadline-success fraction.",
        "",
        "| Workers | Offered/s | CPU / hybrid goodput/s | CPU / hybrid within 10 ms | CPU / hybrid p99 ms | Hybrid GPU share | Both repeats pass? |",
        "|---:|---:|---|---|---|---:|---|",
    ]
    for workers, rate, ok in pairs:
        modes = [
            [
                r
                for r in short_rows
                if r["workers"] == workers
                and r["offered_rate"] == rate
                and r["mode"] == mode
            ]
            for mode in ("cpu", "hybrid")
        ]
        good = " / ".join(span([r["goodput_rps"] for r in rows], 0) for rows in modes)
        fractions = " / ".join(
            span([success(r) for r in rows], 2) + "%" for rows in modes
        )
        p99 = " / ".join(span([r["latency_p99_ms"] for r in rows], 2) for rows in modes)
        share = span([gpu_fraction(r) for r in modes[1]], 1)
        lines.append(
            f"| {workers} | {rate:,} | {good} | {fractions} | {p99} | {share}% | {'Yes' if ok else 'No'} |"
        )
    lines += [
        "",
        "![RTX 3060 repeated deadline success and latency under shared-host conditions](assets/rtx3060-pipeline.svg)",
        "",
        "## Longer runs and key fragmentation",
        "",
        "Each row below is a single 30-second run at 40,000 offered requests/s with 8 CPU workers. It is a longer check, not long-duration production qualification. GPU share is the fraction of verified requests signed on the GPU; a hybrid row with little GPU work primarily measures CPU routing.",
        "",
        "Uniformly splitting 40,000 requests/s across sixteen keys gives 2,500 compatible arrivals/s per key. In an ideal evenly spaced stream, the first item would wait 63/2,500 = 25.2 ms to assemble 64 items without a timeout. The configured 1 ms flush therefore favors smaller CPU batches. This is a fill-time calculation; the measured GPU share below records what the actual scheduler did.",
        "",
        "| Keys | Mode | Goodput/s | Within 10 ms | p99 ms | GPU share | Process CPU seconds | Mean occupied CPU cores |",
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in data[2]["rows"]:
        lines.append(
            f"| {r['keys']} | {r['mode']} | {r['goodput_rps']:,.0f} | {success(r):.2f}% | {r['latency_p99_ms']:.2f} | {gpu_fraction(r):.2f}% | {r['process_cpu_s']:.3f} | {r['process_cpu_s'] / r['elapsed_s']:.2f} |"
        )
    fragmented = next(
        r for r in data[2]["rows"] if r["keys"] == 16 and r["mode"] == "hybrid"
    )
    if fragmented["gpu_items"] == 0:
        lines += [
            "",
            "**The sixteen-key hybrid run signed every completed request on CPU.** Its different goodput reflects CPU batching/routing behavior and recorded host conditions; it establishes no GPU acceleration. Compatible-key arrival rate, rather than total traffic alone, determines whether this GPU threshold is reached.",
        ]
    lines += [
        "",
        "The per-stage counters below sum worker wall time, which can overlap across workers and includes preemption/waiting. They are not a CPU-time or total-latency decomposition. In particular, GPU signing includes mutex/driver wait as well as execution; completion verification still consumes CPU work.",
        "",
        "| Keys | Mode | Prepare worker-s | Sign worker-s | Verify worker-s | Expired | Late | Rejected |",
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in data[2]["rows"]:
        lines.append(
            f"| {r['keys']} | {r['mode']} | {r['prepare_worker_s']:.3f} | {r['sign_worker_s']:.3f} | {r['verify_worker_s']:.3f} | {r['expired']:,} | {r['late']:,} | {r['rejected']:,} |"
        )
    lines += [
        "",
        "## Cost interpretation",
        "",
        "For fully allocated system cost **H dollars/hour**, multiply the coefficient below by H to obtain dollars per million requests completed within 10 ms under the recorded conditions. These are arithmetic coefficients, not measured electricity bills or recommended deployment prices. They preserve deadline misses in the denominator; quality must pass before using them for sizing.",
        "",
        "| 30-second setting | Cost per million per $1/hour | Deadline quality (≥99%) |",
        "|---|---:|---|",
    ]
    for r in data[2]["rows"]:
        coefficient = (
            1e6 / (3600 * r["goodput_rps"]) if r["goodput_rps"] else float("inf")
        )
        lines.append(
            f"| {r['keys']} keys, {r['mode']} | {coefficient:.6f} × H | {'Pass' if success(r) >= 99 else 'Fail'} |"
        )
    control_rows = [r for d in control for r in d["rows"]]
    control_pass = all(success(r) >= 99 for r in control_rows)
    ratios = []
    for d in control:
        by_mode = {r["mode"]: r for r in d["rows"]}
        ratios.append(by_mode["hybrid"]["goodput_rps"] / by_mode["cpu"]["goodput_rps"])
    lines += [
        "",
        "## 50 ms deadline control",
        "",
        "The [control plan](../benchmarks/RTX3060_DEADLINE_CONTROL.md) was committed before these four runs, after seeing the early 10 ms misses. The budget is changed to 50 ms with the same binaries, record size, worker count, key count, batch size and offered rate as the 8-worker, one-key, 40k/s scenario. New arrivals were generated: this is not a relabeling of earlier completions. The original deadline remains visible above.",
        "",
        "| Repeat | Mode | Goodput/s | All offered within 50 ms | p99 ms | GPU share | Process CPU seconds | Mean occupied CPU cores | Cost coefficient × H |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for repeat, d in enumerate(control, 1):
        for r in d["rows"]:
            coefficient = (
                1e6 / (3600 * r["goodput_rps"]) if r["goodput_rps"] else float("inf")
            )
            lines.append(
                f"| {repeat} | {r['mode']} | {r['goodput_rps']:,.0f} | {success(r):.2f}% | {r['latency_p99_ms']:.2f} | {gpu_fraction(r):.2f}% | {r['process_cpu_s']:.3f} | {r['process_cpu_s'] / r['elapsed_s']:.2f} | {coefficient:.6f} |"
            )
    lines += [
        "",
        f"The four 50 ms cells **{'pass' if control_pass else 'fail'}** the criterion that every cell complete at least 99% of all offered requests within budget. Matched hybrid/CPU goodput ratios are **{span(ratios, 4)}**. This ratio is also the arithmetic break-even ratio of total hybrid/CPU hourly costs at this traffic level; it is not a measured capacity ratio or savings claim. "
        + (
            "Both systems meeting the same offered load leaves little goodput-based room for an additional GPU cost."
            if control_pass
            else "The failed quality gate prevents using this ratio as an adoption case."
        ),
        "",
        "The longer budget allows more work to reach signing and verification before expiration, changing resource demand. Compare process CPU seconds and actual GPU share at the same budget. These sequential shared-host trials cannot establish that a CPU-use difference was caused solely by GPU offload.",
    ]
    lines += [
        "",
        "Actual RTX 3060 capital allocation, lifetime, wall-system energy, electricity rate and shared CPU/RAM costs remain inputs to the [owned-system model](ECONOMICS.md#owned-cards-and-utilization). Include the CPU host once. Process CPU savings do not automatically reduce the cost of an already provisioned machine. The dated A100/L40S provider-price scenarios remain separate from these local measurements.",
        "",
        "The useful engineering result is a measured CPU/GPU request path with explicit quality and resource accounting. Moving signing onto an available GPU does not by itself establish a 10 ms service or an economic gain. An exclusive host and representative traffic/deadlines are still needed to separate scheduling interference from application capacity; longer burst/skew/recovery tests and the [production security work](PRODUCTION_READINESS.md) also remain open.",
        "",
        "## Reproduce and inspect",
        "",
        "Use the [committed campaign plan](../benchmarks/RTX3060_CAMPAIGN.md) for matrix settings and the [native build instructions](PIPELINE_RESULTS.md#reproduce) for prerequisites. Select the actual device index; this host's device 1 reports an RTX 3060. `--preflight-scope target-gpu` requires that selected GPU to be idle and explicitly records the shared CPU host. Default preflight still checks all GPUs.",
        "",
        "```sh",
        "python benchmarks/verify_pipeline.py",
        "python benchmarks/report_pipeline.py --check",
        "python benchmarks/report_rtx3060.py --check",
        "# Optional chart regeneration requires matplotlib:",
        "python benchmarks/report_rtx3060.py --plot",
        "```",
        "",
        "Source commits, binary fingerprints, exact commands and timestamps are in each capture. The [build manifest](../benchmarks/pipeline_build.json) identifies the native/OpenSSL binaries. The earlier 84 diagnostic rows remain unchanged and separately qualified; this campaign adds selected-device preflight, per-cell CPU/GPU telemetry and reversed-order repeats.",
        "",
    ]
    return "\n".join(lines)


def plot(preview=False):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"svg.fonttype": "none", "svg.hashsalt": "rtx3060-pipeline"})
    data = captures()
    fig, axes = plt.subplots(2, 2, figsize=(11, 7), constrained_layout=True)
    for line, workers in enumerate((4, 8)):
        for repeat, d in enumerate(data[:2], 1):
            for mode, color in (("cpu", "#2563eb"), ("hybrid", "#d97706")):
                rows = sorted(
                    (
                        r
                        for r in d["rows"]
                        if r["workers"] == workers and r["mode"] == mode
                    ),
                    key=lambda r: r["offered_rate"],
                )
                x = [r["offered_rate"] / 1000 for r in rows]
                style = "o-" if repeat == 1 else "s--"
                label = f"{mode}, repeat {repeat}"
                axes[line, 0].plot(
                    x, [success(r) for r in rows], style, color=color, label=label
                )
                axes[line, 1].plot(
                    x,
                    [r["latency_p99_ms"] for r in rows],
                    style,
                    color=color,
                    label=label,
                )
        axes[line, 0].axhline(99, color="#6b7280", linestyle=":", label="99% criterion")
        axes[line, 1].axhline(10, color="#6b7280", linestyle=":", label="10 ms budget")
        axes[line, 0].set_ylim(0, 105)
        axes[line, 1].set_ylim(bottom=0)
        axes[line, 0].set_ylabel("All offered requests within 10 ms (%)")
        axes[line, 1].set_ylabel("p99 of verified completions (ms)")
        for axis in axes[line]:
            axis.set_title(f"{workers} CPU workers · one key · batch ≤64")
            axis.set_xlabel("Offered requests/s (thousands)")
            axis.grid(alpha=0.2)
            axis.legend(fontsize=8)
    fig.suptitle(
        "RTX 3060: idle selected GPU, busy shared CPU host\nTwo 10-second repeats in reversed CPU/hybrid order · all outputs CPU-verified",
        fontsize=12,
    )
    path = ROOT / "docs/assets/rtx3060-pipeline.svg"
    fig.savefig(path, metadata={"Date": None}, bbox_inches="tight")
    path.write_text(
        "\n".join(s.rstrip() for s in path.read_text(encoding="utf-8").splitlines())
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    if preview:
        fig.savefig(ROOT / "dist/rtx3060-pipeline.png", dpi=140, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--plot", action="store_true")
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    path = ROOT / "docs/RTX3060_PIPELINE.md"
    content = render()
    if args.check:
        if path.read_text(encoding="utf-8") != content:
            raise SystemExit("RTX 3060 report is stale")
        print("PASS: RTX 3060 report matches captures.")
    else:
        path.write_text(content, encoding="utf-8", newline="\n")
    if args.plot:
        plot(args.preview)
