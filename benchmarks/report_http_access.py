"""SPDX-License-Identifier: Apache-2.0. Validate and summarize HTTP captures."""

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import subprocess

from run_http_access import SCENARIOS, percentile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "benchmarks/http_results/rtx3060-http-v2.json"
DEFAULT_OUTPUT = ROOT / "docs/HTTP_RESULTS.md"


def validate(data):
    if data["schema"] != 1 or not data["complete"] or data["smoke"] or data["dirty"]:
        raise ValueError("capture must be complete, committed and nonsmoke")
    if not re.fullmatch("[0-9a-f]{40}", data["commit"]):
        raise ValueError("invalid source commit")
    for path, expected in data["sources"].items():
        if Path(path).is_absolute() or ".." in Path(path).parts:
            raise ValueError("invalid source path")
        blob = subprocess.check_output(["git", "show", f"{data['commit']}:{path}"], cwd=ROOT)
        # Windows checkout CRLF conversion changes bytes, not source identity.
        candidates = [blob, blob.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")]
        if expected not in [hashlib.sha256(value).hexdigest() for value in candidates]:
            raise ValueError(f"source fingerprint mismatch: {path}")
    seen = set()
    for c in data["cells"]:
        key = (c["scenario"]["name"], c["mode"], c["cpu_signing_workers"], c["repeat"])
        if key in seen or c["scenario"] not in SCENARIOS:
            raise ValueError("duplicate or undeclared cell")
        seen.add(key)
        if c["mode"] not in ("direct", "cpu-books", "gpu-books"):
            raise ValueError("unknown mode")
        expected = c["scenario"]["books"] * c["scenario"]["consume"]
        records = c["records"]
        okay = [r for r in records if r["status"] == "ok"]
        on_time = sum(r["ready_to_complete_ms"] <= c["slo_ms"] for r in okay)
        if (c["attempted_accesses"] != expected or len(okay) != expected or c["completed"] != expected
                or c["on_time"] != on_time or c["late"] != expected - on_time or c["failed"] != 0
                or c["error"] or c["cleanup_errors"] or c["server_errors"] or not c["reconciled"]):
            raise ValueError("outcome gate failed")
        if len({r["receipt_id"] for r in okay}) != expected:
            raise ValueError("duplicate receipt")
        for r in okay:
            if not 0 < r["request_ms"] <= r["ready_to_complete_ms"] <= r["plan_to_complete_ms"]:
                raise ValueError("invalid timing order")
        a, b = c["audit_after"], c["audit_before"]
        if a["receipts"] - b["receipts"] != expected or a["publisher_accrued"] - b["publisher_accrued"] != expected * 1000:
            raise ValueError("receipt accounting mismatch")
        for account in a["accounts"]:
            if account["reserved"] or account["initial"] != account["available"] + account["spent"]:
                raise ValueError("balance mismatch")
        if sum(account["spent"] for account in a["accounts"]) != a["publisher_accrued"]:
            raise ValueError("publisher mismatch")
        signatures = c["scenario"]["books"] if c["mode"] != "direct" else 0
        if c["signatures"] != signatures or c["publisher_verifications"] != signatures:
            raise ValueError("signing or consumer verification count mismatch")
        if c["signing_batches"] != ([signatures] if signatures else []):
            raise ValueError("unexpected batch grouping")
        if c["elapsed_seconds"] < c["delivery_seconds"] or c["process_cpu_seconds"] < 0:
            raise ValueError("invalid wall/CPU cost")
        for key, numerator in (("completed_per_second", expected), ("on_time_per_second", on_time)):
            if not math.isclose(c[key], numerator / c["elapsed_seconds"], rel_tol=1e-10):
                raise ValueError("rate mismatch")
        for key, p in (("p95_ready_ms", .95), ("p99_ready_ms", .99)):
            if c[key] != percentile([r["ready_to_complete_ms"] for r in okay], p):
                raise ValueError("latency percentile mismatch")
        price = data["cost_assumptions"]["host_hourly_usd"]
        if c["mode"] == "gpu-books":
            extra = data["cost_assumptions"]["additional_gpu_hourly_usd"]
            price = price + extra if price is not None and extra is not None else None
            if not data["environment"]["library_sha256"] or len(c["preflight"]) != 3:
                raise ValueError("missing GPU provenance or preflight")
            uuid = data["environment"]["selected_gpu_uuid"]
            for sample in c["preflight"]:
                matches = [d for d in sample if d["uuid"] == uuid]
                if len(matches) != 1 or float(matches[0]["utilization_percent"]) > 5:
                    raise ValueError("invalid idle GPU preflight")
        expected_cost = price * c["elapsed_seconds"] / 3600 if price is not None else None
        if expected_cost != c["cost_usd"]:
            raise ValueError("cost assumption mismatch")
        expected_million = expected_cost * 1e6 / on_time if expected_cost is not None and on_time else None
        if expected_million != c["cost_per_million_on_time"]:
            raise ValueError("unit cost mismatch")
    groups = defaultdict(set)
    for name, mode, workers, repeat in seen:
        groups[(name, mode, workers)].add(repeat)
    variants = {(mode, workers) for _, mode, workers in groups}
    if len(groups) != len(SCENARIOS) * len(variants) or any(repeats != {0, 1, 2} for repeats in groups.values()):
        raise ValueError("published campaign needs all four scenarios and three repeats per variant")
    if not {("direct", 1), ("cpu-books", 1), ("cpu-books", 4)} <= variants:
        raise ValueError("missing CPU controls")


def render(data, source_name=DEFAULT_INPUT.name):
    validate(data)
    cells = data["cells"]
    groups = defaultdict(list)
    for c in cells:
        groups[(c["scenario"]["name"], c["mode"], c["cpu_signing_workers"])].append(c)
    med = lambda rows, field: statistics.median(r[field] for r in rows)
    comparisons = {}
    for scenario in SCENARIOS:
        name = scenario["name"]
        gpu = groups.get((name, "gpu-books", 1))
        if gpu:
            cpu_key = max((k for k in groups if k[0] == name and k[1] == "cpu-books"), key=lambda k: med(groups[k], "on_time_per_second"))
            cpu = groups[cpu_key]
            denominator = med(cpu, "on_time_per_second")
            ratio = med(gpu, "on_time_per_second") / denominator if denominator else 0
            conservative_denominator = max(r["on_time_per_second"] for r in cpu)
            conservative = min(r["on_time_per_second"] for r in gpu) / conservative_denominator if conservative_denominator else 0
            comparisons[name] = cpu_key[2], ratio, conservative
    no_ceiling = bool(comparisons) and all(row[2] <= 1 for row in comparisons.values())
    lines = ["# Local HTTP reference results", "",
             "A complete synthetic access path was measured: issuer preparation, publisher",
             "admission, online durable spending, content delivery, buyer checks and unused",
             "reservation cleanup. These finite loopback waves do not establish production",
             "capacity, Internet latency, commercial demand or a GPU deployment cost advantage.", "",
             f"Capture: [raw observations](../benchmarks/http_results/{source_name});",
             f"source `{data['commit']}`; `{data['timestamp_utc']}`.",
             "[Design and reproduction](HTTP_REFERENCE.md) · [Predeclared campaign](../benchmarks/HTTP_ACCESS_CAMPAIGN.md).", "",
             f"**{len(cells)} cells; {sum(c['completed'] for c in cells):,} delivered accesses reconciled; "
             f"{sum(c['failed'] for c in cells)} failures; {sum(c['late'] for c in cells):,} completions after the deadline.** "
             "Warmup transactions are excluded from these totals.", "",
             ("The conservative GPU/CPU comparison establishes **no positive additional GPU "
              "cost allowance in any tested workload**." if no_ceiling else
              "Inspect the conservative comparison below before inferring a GPU cost allowance."), "",
             "## Observed service behavior", "",
             "Median of three repeats. Goodput counts ready-to-complete deadline successes;",
             "its denominator includes the entire measured wave, planning and cleanup. The",
             "one-second deadline starts when all consumed accesses are ready. p99 includes",
             "buyer worker queueing. An urgent cell contains only one access, so its p99",
             "is just that single observation. Four buyer workers in every cell.", "",
             "| Workload | Path / signing workers | On-time accesses/s | First access ms | p99 ready ms | CPU seconds | Cleanup ms |",
             "|---|---|---:|---:|---:|---:|---:|"]
    for scenario in SCENARIOS:
        for key in sorted(k for k in groups if k[0] == scenario["name"]):
            rows = groups[key]
            lines.append(f"| {key[0]} | {key[1]} / {key[2]} | {med(rows, 'on_time_per_second'):.1f} | "
                         f"{med(rows, 'first_access_ready_ms'):.2f} | {med(rows, 'p99_ready_ms'):.2f} | "
                         f"{med(rows, 'process_cpu_seconds'):.3f} | {med(rows, 'cleanup_ms'):.2f} |")
    lines += ["", "CPU books use cached OpenSSL keys with both 1 and 4 signing workers. Direct",
              "account purchases require no signatures. GPU books include VerifiedSigner's",
              "CPU output check **and** the publisher's independent signature admission.", "",
              "The [earlier interrupted capture](../benchmarks/http_results/rtx3060-http-v1-interrupted.json)",
              "is retained: 47 cells completed before the GPU idle preflight stopped the",
              "final cell. It is excluded from this complete campaign. The second campaign",
              "adds a bounded wait for three consecutive idle samples; measured work and",
              "the shuffled schedule are unchanged. No unfavorable cell was discarded.", "",
              "## GPU economics gate", "",
              "For each workload, choose the CPU-book worker setting with the highest median",
              "on-time goodput. The conservative ratio is minimum GPU repeat divided by",
              "maximum repeat for that CPU setting. A ratio above one is only a measured",
              "allocation-cost ceiling under equal utilized wall-time assumptions; three",
              "observations on a shared host are not a stable profitability estimate.", "",
              "| Workload | Best CPU workers | Median GPU/CPU | Conservative GPU/CPU | Positive additional GPU/host cost ceiling |",
              "|---|---:|---:|---:|---:|"]
    for scenario in SCENARIOS:
        name = scenario["name"]
        if name not in comparisons:
            continue
        workers, ratio, conservative = comparisons[name]
        lines.append(f"| {name} | {workers} | {ratio:.3f} | {conservative:.3f} | "
                     f"{f'{(conservative - 1) * 100:.1f}%' if conservative > 1 else 'None established'} |")
    lines += ["", "No cloud invoice or GPU rental price was inferred. Raw captures retain optional",
              "whole-host/additional-GPU prices and dollars per million on-time completions;",
              "missing prices are null. Billing minimums, idle allocation, payment fees,",
              "egress and labor are not measured. Compare the unsigned direct path as well",
              "as CPU books before proposing a GPU purchase.", "",
              "## Interpretation and reproduction limits", "",
              "- Fully used books amortize one signature over four accesses. Quarter-use",
              "  books still prepare all four entries but deliver only one; cancellation",
              "  releases the remainder. Direct purchases prepare only consumed accesses.",
              "- The 50 ms independent-work interval gives both signing paths the same",
              "  preparation opportunity. Individual plan-to-complete and ready-to-complete",
              "  timings remain in the capture; hiding preparation does not erase its cost.",
              "- Two HTTP listeners and all clients run in one Python process, with a new",
              "  TCP connection per RPC and a SQLite connection per operation. This baseline",
              "  deliberately remains an inspectable reference, not a tuned network stack.",
              "- GPU batches contain 64 signatures in larger waves. They do not represent",
              "  saturation-sized native batches or a cross-tenant routing experiment.",
              "- Process CPU time includes all roles; peak memory is cumulative for the",
              "  process. Per-cell host CPU load and all-GPU telemetry disclose shared load.",
              "  Sampled GPU power cannot resolve short kernels or establish energy savings.",
              "  Windows CPU-time resolution can report zero for a short urgent cell;",
              "  that does not mean the request used no CPU.", "",
              "A follow-up should first measure how much persistent connections, a durable",
              "database connection pool and admission/spend RPC grouping reduce service",
              "overhead. Preserve the same authorization and recovery contracts.", "",
              "## Binary provenance", "",
              f"Native library SHA-256: `{data['environment']['library_sha256']}`.",
              f"Native source commit: `{data['environment']['library_source_commit']}`.",
              f"Recorded build: {data['environment']['library_build_note'] or 'CPU only; no native binary loaded'}.",
              "Host, Python/OpenSSL versions and observed GPU load are in the raw capture.",
              "Only the selected GPU UUID is used for cryptography; other devices are",
              "observed for shared-load disclosure and never modified.", "",
              "Regenerate and validate: `python benchmarks/report_http_access.py --check`.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = render(json.loads(args.input.read_text()), args.input.name)
    if args.check:
        if args.output.read_text(encoding="utf-8") != result:
            raise SystemExit("HTTP report differs from capture")
        print("HTTP capture and report verified")
    else:
        args.output.write_text(result, encoding="utf-8")


if __name__ == "__main__":
    main()
