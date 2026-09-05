"""SPDX-License-Identifier: Apache-2.0. Reproduce ready-wave tables and cost bounds."""

import argparse
import csv
from io import StringIO
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def groups(rows):
    result = {}
    for row in rows:
        key = tuple(row[k] for k in ("mode", "wave", "keys", "workers"))
        result.setdefault(key, []).append(row)
    if any(len(values) != 2 for values in result.values()):
        raise ValueError("two repeats required")
    return result


def quality(rows, added_ms=0):
    return all(
        sum(t + added_ms <= 50 for t in r["wave_latencies_ms"]) / r["waves"] >= 0.99
        for r in rows
    )


def rate(row, added_ms=0):
    count = sum(t + added_ms <= 50 for t in row["wave_latencies_ms"])
    return count * row["wave"] / (row["elapsed_s"] + added_ms * row["waves"] / 1000)


def select(grouped, mode, wave, keys, *, hybrid=False, added_ms=0):
    choices = [
        (w, values)
        for (m, n, k, w), values in grouped.items()
        if (m, n, k) == (mode, wave, keys) and quality(values, added_ms)
    ]
    if not choices:
        return None
    selector = min if hybrid else max
    return max(choices, key=lambda item: selector(rate(r, added_ms) for r in item[1]))


def span(rows, field, scale=1, digits=0):
    values = [r[field] * scale for r in rows]
    return f"{min(values):,.{digits}f}–{max(values):,.{digits}f}"


def generate(data):
    rows, meta = data["rows"], data["metadata"]
    grouped = groups(rows)
    text = [
        "# Ready-wave token service: measured results",
        "",
        "Generated from the complete [raw capture](../benchmarks/ready_wave_results/rtx3060-2026-09-05.json). The [campaign plan](../benchmarks/READY_WAVE_CAMPAIGN.md), [standard-token compatibility](COMPATIBILITY.md) and [reproduction script](../benchmarks/run_ready_wave.py) define the experiment.",
        "",
        f"**{len(rows)} cells; {sum(r['verified'] for r in rows):,} timed tokens independently verified on CPU.** {meta['gpu']}. CPU: {meta['cpu']}. Four/eight workers, two repeats in opposite mode order, three seconds per cell. This is a shared host with an idle selected GPU at each preflight, not exclusive capacity.",
        "",
        "The workload is a sequence of already-ready waves. Completion requires constructing claims, encoding the signing input, signing, compact token encoding/decoding and checking every output against a CPU public key. There is no arrival-driven fill delay. General JWT parsing/claim policy, network/TLS, identity, ledger, settlement, key setup and warm-up are excluded. PyJWT checks sampled native tokens outside the timer; live compatibility tests check expiry and issuer/audience separately.",
        "",
        "## Cost ceiling against the stronger observed CPU setting",
        "",
        "For each wave, CPU is the faster eligible four/eight-worker setting. Hybrid is the eligible setting with the faster *slower repeat*. Ratios divide that slower hybrid repeat by the faster CPU repeat, retaining run-order variability. Eligibility requires at least 99% of tokens within 50 ms in both repeats. A candidate also needs actual GPU use and a ratio above 1.05, as declared before measurement.",
        "",
        "| Wave / keys | CPU / hybrid workers | CPU upper / hybrid lower goodput/s | Conservative ratio | Maximum extra GPU cost / CPU host cost | Candidate? |",
        "|---|---|---:|---:|---:|---|",
    ]
    candidates = []
    for wave, keys in [
        (1, 1),
        (8, 1),
        (64, 1),
        (256, 1),
        (1024, 1),
        (4096, 1),
        (4096, 16),
    ]:
        c = select(grouped, "cpu-es256", wave, keys)
        h = select(grouped, "hybrid-es256", wave, keys, hybrid=True)
        if not c or not h:
            text.append(
                f"| {wave} / {keys} | — | — | — | — | No: missing quality pass |"
            )
            continue
        cr, hr = max(rate(r) for r in c[1]), min(rate(r) for r in h[1])
        ratio = hr / cr
        gpu = all(r["gpu_items"] > 0 for r in h[1])
        candidate = gpu and ratio > 1.05
        if candidate:
            candidates.append((wave, keys, c, h, ratio))
        reason = (
            "Yes, within measured scope"
            if candidate
            else "No GPU used"
            if not gpu
            else "No: below 1.05 ratio"
        )
        ceiling = (
            f"{(ratio - 1) * 100:.1f}%" if gpu and ratio > 1 else "No positive ceiling"
        )
        text.append(
            f"| {wave} / {keys} | {c[0]} / {h[0]} | {cr:,.0f} / {hr:,.0f} | {ratio:.3f} | {ceiling} | {reason} |"
        )
    text += [
        "",
        f"**Candidate wave/key settings: {len(candidates)}.** These are finite-run bounds for this cryptographic service. Cost savings require the full allocated hybrid/CPU hourly-price ratio to be below the reported throughput ratio. They are not measured electricity bills, cloud savings or publisher revenue.",
        "",
        "If CPU host allocation costs C per hour and adding the GPU costs G, the break-even condition is `G/C < ratio - 1`. Count the CPU host once. Include device capital/rental, idle allocation, electricity and operational overhead in G; an unused owned card is not automatically free. For a mode with on-time goodput Q and total allocation H/hour, `cost per million = 1e6*H/(3600*Q)`. The [economics inventory](ECONOMICS.md) keeps provider scenarios and owned-hardware inputs separate.",
        "",
        "## Ed25519 algorithm-choice comparison",
        "",
        "This is a comparison between separately accepted protocols. An Ed25519-only consumer cannot accept the ES256 result without an explicit protocol change. Both sign the same claims; Ed25519 signs the complete JOSE input, while ES256 uses SHA-256. Both include all-output CPU verification.",
        "",
        "| Wave / keys | Best eligible Ed25519 upper goodput/s | Eligible ES256 hybrid lower / Ed25519 ratio |",
        "|---|---:|---:|",
    ]
    for wave, keys in [
        (1, 1),
        (8, 1),
        (64, 1),
        (256, 1),
        (1024, 1),
        (4096, 1),
        (4096, 16),
    ]:
        e = select(grouped, "cpu-eddsa", wave, keys)
        h = select(grouped, "hybrid-es256", wave, keys, hybrid=True)
        if not e or not h:
            text.append(f"| {wave} / {keys} | — | No matched quality pass |")
        else:
            er, hr = max(rate(r) for r in e[1]), min(rate(r) for r in h[1])
            text.append(f"| {wave} / {keys} | {er:,.0f} | {hr / er:.3f} |")
    text += [
        "",
        "## Adding an unchanged downstream stage",
        "",
        "The following is a **model**, not another measurement. Add the same fixed serial delay to every recorded wave, add its time to the elapsed denominator, and re-evaluate the 50 ms quality gate. It assumes the added work does not change the measured crypto times through contention. A database, network or policy service must be measured to establish that assumption; variable latency and resource competition can make it fail.",
        "",
        "| Candidate wave / keys | +0 ms ratio | +1 ms ratio | +5 ms ratio | +20 ms ratio |",
        "|---|---:|---:|---:|---:|",
    ]
    for wave, keys, c, h, _ in candidates:
        values = []
        for added in (0, 1, 5, 20):
            if not quality(c[1], added) or not quality(h[1], added):
                values.append("Quality fails")
            else:
                values.append(
                    f"{min(rate(r, added) for r in h[1]) / max(rate(r, added) for r in c[1]):.3f}"
                )
        text.append(f"| {wave} / {keys} | " + " | ".join(values) + " |")
    if not candidates:
        text.append("| No candidate in this capture | — | — | — | — |")
    text += [
        "",
        "## Verification placement and stage costs",
        "",
        "This campaign performs one authoritative CPU signature check per token. A transaction service must finish that check before accepting access or accruing a charge. If the issuer uses the default `VerifiedSigner` and a separate recipient verifies again, both checks cost resources. The [separate-verification control](VERIFICATION_CONTROL_RESULTS.md) measures that deployment choice; do not apply the one-check cost ceiling to a two-check path.",
        "",
        "For the 1,024-token, eight-worker setting, the following means combine both repeats. Finish includes token encoding/decoding and CPU verification; these are serial phase wall times, including scheduling, not a pure cryptographic-operation breakdown.",
        "",
        "| Mode | Prepare ms/wave | Sign ms/wave | Finish ms/wave |",
        "|---|---:|---:|---:|",
    ]
    for mode in ("cpu-es256", "hybrid-es256"):
        selected = grouped[(mode, 1024, 1, 8)]
        count = sum(r["waves"] for r in selected)
        values = [
            1000 * sum(r[field] for r in selected) / count
            for field in ("prepare_s", "sign_s", "finish_s")
        ]
        text.append(
            f"| {mode} | " + " | ".join(f"{value:.3f}" for value in values) + " |"
        )
    text += [
        "",
        "## Both repeats, including failed settings",
        "",
        "Ranges are two observations, not confidence intervals. Each token in a wave shares its completion time because the complete wave is verified before release. CPU time includes the native main thread and workers; parent telemetry is outside that counter. A hybrid cell with 0% GPU share is a CPU routing control. Configurations, synthetic records, stage barriers and lack of overlapping waves constrain transfer to other services.",
        "",
        "| Wave / keys | Mode | Workers | Tokens/s | p99 ms | Within 50 ms | GPU share | Process CPU s | Both pass? |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for (mode, wave, keys, workers), values in sorted(
        grouped.items(),
        key=lambda item: (item[0][1], item[0][2], item[0][3], item[0][0]),
    ):
        quality_range = [100 * r["within_50ms"] / r["verified"] for r in values]
        share = 100 * values[0]["gpu_items"] / values[0]["verified"]
        text.append(
            f"| {wave} / {keys} | {mode} | {workers} | {span(values, 'throughput_rps')} | {span(values, 'p99_ms', digits=2)} | {min(quality_range):.2f}–{max(quality_range):.2f}% | {share:.0f}% | {span(values, 'process_cpu_s', digits=2)} | {'Yes' if quality(values) else 'No'} |"
        )
    text += [
        "",
        "These ready-wave measurements do not replace the earlier [constant-arrival pipeline results](RTX3060_PIPELINE.md). No real AI planning, independent model work, requests over a network, or account settlement was timed. Deployment requires accepted protocol/keys, representative traffic, allocation prices and the [documented security boundary](PRODUCTION_READINESS.md). The GPU arithmetic remains secret-dependent.",
        "",
        "## Reproduce and audit",
        "",
        f"Measured source commit: `{meta['commit']}`. [Build fingerprints](../benchmarks/ready_wave_build.json), [raw checksums](../benchmarks/ready_wave_results/SHA256SUMS), [CSV](../benchmarks/ready_wave.csv).",
        "",
        "```sh",
        "python -m pip install '.[interop]'",
        "python benchmarks/verify_ready_wave.py",
        "python benchmarks/report_ready_wave.py --check",
        "```",
        "",
    ]
    buffer = StringIO(newline="")
    fields = [
        "repeat",
        "mode",
        "wave",
        "keys",
        "workers",
        "waves",
        "verified",
        "gpu_items",
        "within_10ms",
        "within_50ms",
        "elapsed_s",
        "process_cpu_s",
        "throughput_rps",
        "goodput_50ms",
        "p50_ms",
        "p95_ms",
        "p99_ms",
        "max_ms",
        "prepare_s",
        "sign_s",
        "finish_s",
    ]
    writer = csv.DictWriter(
        buffer, fieldnames=fields, lineterminator="\n", extrasaction="ignore"
    )
    writer.writeheader()
    writer.writerows(rows)
    return {
        ROOT / "docs/READY_WAVE_RESULTS.md": "\n".join(text),
        ROOT / "benchmarks/ready_wave.csv": buffer.getvalue(),
    }


def generate_control(data):
    if not data["complete"]:
        raise ValueError("complete verification control required")
    rows, meta = data["rows"], data["metadata"]
    grouped = groups(rows)
    total = sum(r["verified"] for r in rows)
    extra = sum(r["gpu_guard_checks"] for r in rows)
    text = [
        "# Separate issuer and consumer verification: measured control",
        "",
        f"**{len(rows)} cells, {total:,} completed tokens, {extra:,} additional issuer-side GPU output checks.** Each token also passed the independent consumer check. The [control plan](../benchmarks/VERIFICATION_CONTROL.md) was committed before this separate measurement, after the original [ready-wave screening](READY_WAVE_RESULTS.md).",
        "",
        "CPU ES256 signs and performs one consumer verification. Hybrid ES256 additionally checks every GPU signature on CPU at the issuer before encoding, then performs the separate consumer verification. This represents the default guarded signer followed by a verifying recipient. CPU fallback needs no additional GPU fault guard. Both use the same claims and worker budgets.",
        "",
        "The same RTX 3060 and Ryzen 7 7800X3D host were used, with idle selected-GPU preflights and shared-host telemetry. Two repeats use opposite mode order; three seconds per cell. General JWT parsing/claim policy, network/TLS, account/payout services, key setup and warm-up remain outside timing.",
        "",
        "## Decision at the declared 50 ms budget",
        "",
        "The conservative ratio is slower hybrid repeat / faster eligible CPU repeat, using the better eligible four/eight-worker setting for each. A candidate requires ≥99% of tokens within 50 ms in both repeats and ratio >1.05.",
        "",
        "| Wave | CPU / hybrid workers | CPU upper / hybrid lower goodput/s | Ratio | Candidate? |",
        "|---|---|---:|---:|---|",
    ]
    passed = 0
    for wave in (256, 1024):
        c = select(grouped, "cpu-es256", wave, 1)
        h = select(grouped, "hybrid-es256", wave, 1, hybrid=True)
        if not c or not h:
            text.append(f"| {wave} | — | — | — | No matched quality pass |")
        else:
            cr, hr = max(rate(r) for r in c[1]), min(rate(r) for r in h[1])
            ratio = hr / cr
            passed += ratio > 1.05
            text.append(
                f"| {wave} | {c[0]} / {h[0]} | {cr:,.0f} / {hr:,.0f} | {ratio:.3f} | {'Yes, within measured scope' if ratio > 1.05 else 'No'} |"
            )
    text += [
        "",
        f"**Candidate settings in this control: {passed}.** Use this result for the two-check cryptographic path, not the earlier one-check ceiling. Additional common application costs must also be included before sizing a service. These shared-host, finite-run observations are not an exclusive-host capacity certification.",
        "",
        "## Every setting and both repeats",
        "",
        "| Wave | Mode | Workers | Tokens/s | p99 ms | Within 50 ms | Process CPU s | Both pass? |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for (mode, wave, _, workers), values in sorted(
        grouped.items(), key=lambda item: (item[0][1], item[0][3], item[0][0])
    ):
        percentages = [100 * r["within_50ms"] / r["verified"] for r in values]
        text.append(
            f"| {wave} | {mode} | {workers} | {span(values, 'throughput_rps')} | {span(values, 'p99_ms', digits=2)} | {min(percentages):.2f}–{max(percentages):.2f}% | {span(values, 'process_cpu_s', digits=2)} | {'Yes' if quality(values) else 'No'} |"
        )
    text += [
        "",
        "A single-check acceptance design is a different application contract: the designated receiver checks every token before authorization or monetary accrual, and failed output must recover without creating a charge. This control does not validate that ledger, networking or fault-recovery implementation. The library's guarded example remains appropriate when a caller needs independently checked signatures before releasing them.",
        "",
        "Existing Ed25519 consumers still require their own accepted protocol; ES256 interoperability does not change their contract. Both profiles retain the existing [GPU key-residency and side-channel constraints](PRODUCTION_READINESS.md).",
        "",
        f"Measured source commit: `{meta['commit']}`. [Raw capture](../benchmarks/ready_wave_results/rtx3060-verification-2026-09-05.json), [build fingerprints](../benchmarks/ready_wave_build.json), [checksum inventory](../benchmarks/ready_wave_results/SHA256SUMS). Run `python benchmarks/verify_ready_wave.py` and `python benchmarks/report_ready_wave.py --check` with the interop dependencies installed.",
        "",
    ]
    return {ROOT / "docs/VERIFICATION_CONTROL_RESULTS.md": "\n".join(text)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    data = json.loads(
        (ROOT / "benchmarks/ready_wave_results/rtx3060-2026-09-05.json").read_text(
            encoding="utf-8"
        )
    )
    if not data["complete"]:
        raise ValueError("complete campaign required")
    outputs = generate(data)
    control_path = (
        ROOT / "benchmarks/ready_wave_results/rtx3060-verification-2026-09-05.json"
    )
    if control_path.exists():
        outputs.update(
            generate_control(json.loads(control_path.read_text(encoding="utf-8")))
        )
    for path, content in outputs.items():
        if args.check:
            if path.read_text(encoding="utf-8") != content:
                raise ValueError(f"stale generated result: {path.name}")
        else:
            path.write_text(content, encoding="utf-8", newline="\n")
    print(
        "PASS: ready-wave report and CSV "
        + ("match capture" if args.check else "generated")
    )


if __name__ == "__main__":
    main()
