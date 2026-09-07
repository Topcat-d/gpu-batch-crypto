"""SPDX-License-Identifier: Apache-2.0. Verify overhead evidence, including failures."""

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import subprocess

from run_http_access import ROOT, percentile
from run_http_overhead import VARIANTS, schedule

DIRECTORY = ROOT / "benchmarks/http_results"
OUTPUT = ROOT / "docs/HTTP_OVERHEAD_RESULTS.md"


def validate(data, *, allow_incomplete=False):
    if data["schema"] != 1 or data["campaign"] != "http-overhead":
        raise ValueError("unknown campaign")
    if not data["complete"] and not allow_incomplete:
        raise ValueError("incomplete campaign cannot be accepted")
    if data["stage"] not in ("comparison", "confirmation"):
        raise ValueError("unknown stage")
    if not re.fullmatch("[a-f0-9]{40}", data["commit"]):
        raise ValueError("invalid commit")
    required = {"benchmarks/run_http_access.py", "benchmarks/run_http_overhead.py", "benchmarks/HTTP_OVERHEAD_CAMPAIGN.md",
                "python/batchcrypto/verified.py", "python/batchcrypto/jws.py", "python/batchcrypto/__init__.py",
                "examples/http_access/__init__.py", "examples/http_access/ledger.py", "examples/http_access/service.py",
                "examples/http_access/signing.py", "examples/http_access/timings.py"}
    if set(data["sources"]) != required:
        raise ValueError("incomplete source manifest")
    for path, expected in data["sources"].items():
        blob = subprocess.check_output(["git", "show", f"{data['commit']}:{path}"], cwd=ROOT)
        if expected not in {hashlib.sha256(v).hexdigest() for v in (blob, blob.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))}:
            raise ValueError("source mismatch")
    if data["contract"]["deadline_ms"] != 1000 or data["contract"]["final_checkpoint_in_cost"] is not True:
        raise ValueError("changed measurement contract")
    expected_schedule = schedule(data["stage"], bool(data["environment"]["library_sha256"]), data.get("candidate") or "pool-batch")
    if len(data["cells"]) > len(expected_schedule) or (data["complete"] and len(data["cells"]) != len(expected_schedule)):
        raise ValueError("missing or extra cells")
    for c, expected in zip(data["cells"], expected_schedule):
        if (c["repeat"], c["scenario"], c["variant"], c["mode"], c["cpu_signing_workers"]) != expected:
            raise ValueError("undeclared or reordered cell")
        if (c["ledger_pool_size"], c["batch_cancel"]) != VARIANTS[c["variant"]]:
            raise ValueError("changed candidate")
        if c["clients"] != (4 if data["stage"] == "comparison" else 2) or c["slo_ms"] != 1000:
            raise ValueError("changed load or deadline")
        n = c["scenario"]["books"] * c["scenario"]["consume"]
        records = c["records"]
        good = [r for r in records if r["status"] == "ok"]
        timely = sum(r["ready_to_complete_ms"] <= c["slo_ms"] for r in good)
        if len(records) != n or c["attempted_accesses"] != n or c["completed"] != len(good) or c["on_time"] != timely:
            raise ValueError("work or outcome mismatch")
        if c["failed"] != n - len(good) or c["late"] != len(good) - timely:
            raise ValueError("dropped failed/late observations")
        if data["complete"] and (c["failed"] or c["error"] or c["server_errors"] or c["cleanup_errors"]):
            raise ValueError("complete campaign contains an execution failure")
        if len({r["receipt_id"] for r in good}) != len(good):
            raise ValueError("duplicate receipt")
        for r in records:
            if not 0 < r["request_ms"] <= r["ready_to_complete_ms"] <= r["plan_to_complete_ms"]:
                raise ValueError("invalid timing")
        before, after = c["audit_before"], c["audit_after"]
        if not c["reconciled"] or after["receipts"] - before["receipts"] != len(good):
            raise ValueError("receipt mismatch")
        if after["publisher_accrued"] - before["publisher_accrued"] != len(good) * 1000:
            raise ValueError("publisher mismatch")
        if sum(a["spent"] for a in after["accounts"]) != after["publisher_accrued"]:
            raise ValueError("spend mismatch")
        if any(a["reserved"] != 0 or a["initial"] != a["available"] + a["spent"] for a in after["accounts"]):
            raise ValueError("unreconciled balance")
        sigs = c["scenario"]["books"] if c["mode"] != "direct" else 0
        if c["signatures"] != sigs or c["signing_batches"] != ([sigs] if sigs else []):
            raise ValueError("changed signing work")
        if not 0 <= c["publisher_verifications"] <= sigs or (not c["failed"] and c["publisher_verifications"] != sigs):
            raise ValueError("consumer check mismatch")
        if c["checkpoint"] != {"busy": 0, "log_frames": 0, "checkpointed_frames": 0}:
            raise ValueError("missing final checkpoint")
        if not 0 < c["checkpoint_ms"] <= c["cleanup_ms"] <= c["elapsed_seconds"] * 1000:
            raise ValueError("checkpoint excluded from cost")
        if not math.isclose(c["cleanup_ms"], (c["elapsed_seconds"] - c["delivery_seconds"]) * 1000, abs_tol=1e-5):
            raise ValueError("cleanup boundary mismatch")
        for key, count in (("completed_per_second", len(good)), ("on_time_per_second", timely)):
            if not math.isclose(c[key], count / c["elapsed_seconds"], rel_tol=1e-10):
                raise ValueError("rate mismatch")
        for key, p in (("p95_ready_ms", .95), ("p99_ready_ms", .99)):
            if c[key] != percentile([r["ready_to_complete_ms"] for r in good], p):
                raise ValueError("latency mismatch")
        if c["cost_usd"] is not None or c["cost_per_million_on_time"] is not None:
            raise ValueError("unsourced price")
        if not c["failed"]:
            cleanups = (1 if c["batch_cancel"] else sigs) if sigs and c["scenario"]["consume"] < c["scenario"]["size"] else 0
            if c["http"]["requests"] != 2 * n + bool(sigs) + cleanups:
                raise ValueError("HTTP work changed")
            if c["service_timings"]["db.commit"]["count"] != n + 2 * bool(sigs) + cleanups:
                raise ValueError("durable transaction count changed")
        if c["mode"] == "gpu-books":
            if len(c["preflight"]) != 3:
                raise ValueError("missing GPU preflight")
            for sample in c["preflight"]:
                matches = [d for d in sample if d["uuid"] == data["environment"]["selected_gpu_uuid"]]
                if len(matches) != 1 or float(matches[0]["utilization_percent"]) > 5:
                    raise ValueError("GPU was not idle")


def grouped(cells):
    result = defaultdict(list)
    for cell in cells:
        result[(cell["scenario"]["name"], cell["variant"], cell["mode"], cell["cpu_signing_workers"])].append(cell)
    return result


def med(rows, key):
    return statistics.median(r[key] for r in rows)


def render(comparison, confirmation):
    validate(comparison, allow_incomplete=True)
    validate(confirmation)
    groups = grouped(confirmation["cells"])
    lines = ["# HTTP overhead: promote atomic cleanup, retain CPU-first controls", "",
             "This follow-up isolates application overhead with simulated funds. A bounded",
             "atomic cancellation call replaces one cancellation RPC/commit per unused book.",
             "Per-access authorization, signature checks, durable spends and recovery remain",
             "unchanged. Database pooling is an experimental option, not the default.", "",
             "[Design and commands](HTTP_REFERENCE.md) · [Predeclared campaign and decision record](../benchmarks/HTTP_OVERHEAD_CAMPAIGN.md).", "",
             "## What was kept and rejected", "",
             "The [diagnostic](../benchmarks/http_results/overhead-diagnostic-v1.json) measured",
             "a 5.12 ms median SQLite setup and a 35.40 ms p95 begin/lock wait in the CPU-book",
             "full wave. Issuing its complete 64-signature CPU batch took 2.78 ms. Phase",
             "scopes overlap and execute concurrently; those totals are not wall-time shares.", "",
             f"The [comparison](../benchmarks/http_results/overhead-comparison-v1.json) stopped after {len(comparison['cells'])} cells:",
             f"{sum(c['completed'] for c in comparison['cells']):,} accesses completed and reconciled; "
             f"{sum(c['failed'] for c in comparison['cells'])} client OSError occurred before publisher admission.",
             "The OS cause was not captured. Port exhaustion is an unproven possibility,",
             "not a finding. The incomplete capture, failed request and late work are retained",
             "and excluded from promotion evidence. Later captures record OS error codes.", "",
             "The pool reduced opens but increased observed transaction lock-wait tails and",
             "full-wave elapsed time. These partial CPU-one-worker observations explain its",
             "rejection; they are not a completed performance acceptance comparison:", "",
             "| Workload | Variant | Available repeats | Median wall s | Median cleanup ms |",
             "|---|---|---:|---:|---:|"]
    partial = grouped(comparison["cells"])
    for scenario in ("ready-full", "ready-quarter"):
        for variant in ("baseline", "pool", "pool-batch"):
            rows = partial.get((scenario, variant, "cpu-books", 1), [])
            if rows:
                lines.append(f"| {scenario} | {variant} | {len(rows)} | {med(rows, 'elapsed_seconds'):.3f} | {med(rows, 'cleanup_ms'):.1f} |")
    lines += ["", "## Independent cleanup confirmation", "",
              "[Complete holdout capture](../benchmarks/http_results/overhead-confirmation-v1.json):",
              f"**{len(confirmation['cells'])} cells, {sum(c['completed'] for c in confirmation['cells']):,} delivered accesses, "
              f"{sum(c['failed'] for c in confirmation['cells'])} failures, "
              f"{sum(c['late'] for c in confirmation['cells']):,} late completions.** Every cell reconciles.", "",
              "Three repeats per cell; 32 eight-resource books; two buyer clients; one-second",
              "deadline from readiness. Quarter use consumes two resources/book (64 accesses).",
              "The baseline and candidate use the original per-operation database connections",
              "and the same HTTP transport. Only unused-book cleanup is combined. Final WAL",
              "checkpoint time is included in **both** wall costs, alongside preparation,",
              "delivery and cleanup. Timers remain enabled for both paths.", "",
              "| Workload | Path / signing workers | Baseline wall s | Batch wall s | Conservative complete-throughput ratio | Cleanup ms, baseline -> batch | Batch p99 ready ms |",
              "|---|---|---:|---:|---:|---:|---:|"]
    for scenario in ("holdout-quarter", "holdout-full", "urgent"):
        for key in sorted(k for k in groups if k[0] == scenario and k[1] == "batch"):
            batch = groups[key]
            base = groups[(scenario, "baseline", key[2], key[3])]
            ratio = min(r["elapsed_seconds"] for r in base) / max(r["elapsed_seconds"] for r in batch)
            lines.append(f"| {scenario} | {key[2]} / {key[3]} | {med(base, 'elapsed_seconds'):.3f} | {med(batch, 'elapsed_seconds'):.3f} | "
                         f"{ratio:.3f} | {med(base, 'cleanup_ms'):.1f} -> {med(batch, 'cleanup_ms'):.1f} | {med(batch, 'p99_ready_ms'):.2f} |")
    lines += ["", "The conservative ratio is minimum baseline wall time divided by maximum",
              "candidate wall time at identical completed work. Values above one indicate",
              "a repeated improvement in these three observations. At a fixed whole-host",
              "hourly allocation, measured work cost scales with wall time; real billing",
              "minimums, idle deployment, egress, payment fees and labor are not included.", "",
              "Full-use and urgent controls need no cancellation and execute the same work",
              "in both configurations. Their variation is not a cleanup acceleration. The",
              "candidate does not move delivery earlier: cleanup happens after delivery.",
              "Deadline misses remain visible; a cleanup gain is not an improved serving SLO.", "",
              "## GPU adoption remains a separate decision", "",
              "Both issuer CPU output verification and independent publisher admission remain",
              "on the GPU path. Compare GPU to the CPU worker setting with best median",
              "on-time goodput within the same batch-cleanup workload:", "",
              "| Workload | CPU workers | Median GPU/CPU goodput | Conservative GPU/CPU goodput |",
              "|---|---:|---:|---:|"]
    for scenario in ("holdout-quarter", "holdout-full", "urgent"):
        gpu = groups.get((scenario, "batch", "gpu-books", 1))
        if not gpu:
            continue
        keys = [k for k in groups if k[0] == scenario and k[1] == "batch" and k[2] == "cpu-books"]
        best = max(keys, key=lambda k: med(groups[k], "on_time_per_second"))
        cpu = groups[best]
        typical = med(gpu, "on_time_per_second") / med(cpu, "on_time_per_second")
        conservative = min(r["on_time_per_second"] for r in gpu) / max(r["on_time_per_second"] for r in cpu)
        lines.append(f"| {scenario} | {best[3]} | {typical:.3f} | {conservative:.3f} |")
    lines += ["", "Three finite waves on a shared host are not steady-state capacity or a",
              "deployment-profitability estimate. The direct account control remains essential:",
              "a book should provide needed scoped delegation or reusable permission, not",
              "create signature work merely to keep a GPU busy. No GPU price was guessed.", "",
              "## Reproduce and inspect", "",
              f"Comparison source: `{comparison['commit']}`. Confirmation source: `{confirmation['commit']}`.",
              f"Native SHA-256: `{confirmation['environment']['library_sha256']}`.",
              f"Native source: `{confirmation['environment']['library_source_commit']}`.",
              f"Build: {confirmation['environment']['library_build_note']}.",
              "Each archive retains source hashes, host/GPU observations, per-phase timing,",
              "request counts, all per-access observations and accounting snapshots.", "",
              "```sh", "python benchmarks/run_http_overhead.py --stage confirmation --candidate batch --output dist/http-confirmation.json",
              "python benchmarks/report_http_overhead.py --check", "```", "",
              "The first command runs CPU controls; GPU flags are in the campaign. The second",
              "validates published outcome, source, transaction and cost boundaries and",
              "regenerates this table. Full Git history is required for source verification.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    text = render(json.loads((DIRECTORY / "overhead-comparison-v1.json").read_text()),
                  json.loads((DIRECTORY / "overhead-confirmation-v1.json").read_text()))
    if args.check:
        if OUTPUT.read_text(encoding="utf-8") != text:
            raise SystemExit("overhead report differs from evidence")
        print("HTTP overhead evidence and report verified")
    else:
        OUTPUT.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
