"""SPDX-License-Identifier: Apache-2.0. Check and report the public API comparison."""

import argparse
import base64
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import random
import re
import statistics
import subprocess

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "benchmarks/receipt_results/manifest-api-v1.json"
OUTPUT = ROOT / "docs/MANIFEST_API_RESULTS.md"
SOURCES = {
    "python/batchcrypto/__init__.py",
    "python/batchcrypto/jws.py",
    "python/batchcrypto/receipts.py",
    "python/batchcrypto/manifests.py",
    "benchmarks/run_receipts.py",
    "benchmarks/run_pipeline.py",
    "benchmarks/run_manifest_api.py",
    "benchmarks/MANIFEST_API_CAMPAIGN.md",
}
SCENARIOS = [
    ("one", "fresh"),
    ("quarter", "fresh"),
    ("full", "shared"),
    ("full", "fresh"),
]
SCHEDULE = [("primary", 1024, 5), ("holdout", 257, 3)]


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


@lru_cache(maxsize=32)
def wire_sizes(count, selected, scheme, recipients):
    """Reconstruct sizes independently using fixed-width dummy digest/signature."""
    digest = b64(bytes(32))
    common = {"context": "synthetic-export-1", "count": count}

    def token(payload):
        return (
            b64(encode({"alg": "ES256", "kid": "synthetic-key-1"}))
            + "."
            + b64(encode(payload))
            + "."
            + b64(bytes(64))
        )

    def depth(size, index):
        if size == 1:
            return 0
        split = 1 << ((size - 1).bit_length() - 1)
        return 1 + (
            depth(split, index) if index < split else depth(size - split, index - split)
        )

    manifest = None
    if scheme == "manifest":
        manifest = token(
            {
                **common,
                "profile": "batchcrypto-record-manifest-v1",
                "hashes": [digest] * count,
            }
        )
    elif scheme == "merkle":
        manifest = token(
            {**common, "profile": "batchcrypto-record-receipt-v1", "root": digest}
        )
    share = recipients == "shared" and scheme != "individual"
    once = len(encode(manifest)) if share else 0
    sizes = []
    for i in range(selected):
        index = i * count // selected
        item = {"index": index}
        if scheme == "merkle":
            item["path"] = [digest] * depth(count, index)
        if not share:
            item["manifest"] = (
                manifest
                if scheme != "individual"
                else token(
                    {
                        **common,
                        "profile": "individual",
                        "index": index,
                        "sha256": digest,
                    }
                )
            )
        sizes.append(len(encode(item)))
    return once + sum(sizes), once, max(sizes)


def check_measurement(row, count, selected, scheme, recipients):
    if (
        row["accepted"] != selected
        or row["changed_rejected"] is not True
        or row["signatures"] != (count if scheme == "individual" else 1)
    ):
        raise ValueError("verification/work count mismatch")
    phases = [row[key] for key in ("producer_ms", "serialize_ms", "consumer_ms")]
    if any(
        type(x) not in (float, int) or not math.isfinite(x) or x <= 0
        for x in phases + [row["total_ms"]]
    ) or not math.isclose(sum(phases), row["total_ms"], abs_tol=1e-8):
        raise ValueError("invalid timing or omitted phase")
    if tuple(
        row[key]
        for key in ("metadata_bytes", "manifest_once_bytes", "max_receipt_bytes")
    ) != wire_sizes(count, selected, scheme, recipients):
        raise ValueError("wire size mismatch")


def validate(data):
    if (
        data["schema"] != "manifest-api-v1"
        or data["complete"] is not True
        or data["smoke"] is not False
        or "failure" in data
    ):
        raise ValueError("requires a complete nonsmoke capture")
    if (
        not re.fullmatch(r"[0-9a-f]{40}", data["source_commit"])
        or set(data["sources"]) != SOURCES
    ):
        raise ValueError("missing source provenance")
    for path, expected in data["sources"].items():
        blob = subprocess.check_output(
            ["git", "show", f"{data['source_commit']}:{path}"], cwd=ROOT
        )
        candidates = (blob, blob.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
        if expected not in {hashlib.sha256(value).hexdigest() for value in candidates}:
            raise ValueError("source fingerprint mismatch")
    if data["seed"] != 20260908 or len(data["warmups"]) != 3:
        raise ValueError("wrong schedule or missing warmup")
    for row, scheme in zip(data["warmups"], ("individual", "manifest", "merkle")):
        if row["scheme"] != scheme:
            raise ValueError("wrong warmup order")
        check_measurement(row, 7, 7, scheme, "shared")
    rng = random.Random(data["seed"])
    expected_rows = []
    sample_index = 0
    for phase, count, repeats in SCHEDULE:
        for consumption, recipients in SCENARIOS:
            selected = {"one": 1, "quarter": count // 4, "full": count}[consumption]
            for repeat in range(repeats):
                schemes = ["individual", "manifest", "merkle"]
                rng.shuffle(schemes)
                expected_rows.extend(
                    (
                        phase,
                        count,
                        consumption,
                        selected,
                        recipients,
                        repeat,
                        scheme,
                        sample_index,
                    )
                    for scheme in schemes
                )
                sample_index += 1
    if (
        len(data["cells"]) != len(expected_rows)
        or len(data["cpu_samples"]) != sample_index
    ):
        raise ValueError("incomplete comparison or CPU sampling")
    for order, (row, expected) in enumerate(zip(data["cells"], expected_rows)):
        if (
            row["order"] != order
            or tuple(
                row[key]
                for key in (
                    "phase",
                    "count",
                    "consumption",
                    "selected",
                    "recipients",
                    "repeat",
                    "scheme",
                    "cpu_sample",
                )
            )
            != expected
        ):
            raise ValueError("changed scenario/order/sample")
        check_measurement(
            row, row["count"], row["selected"], row["scheme"], row["recipients"]
        )
    for sample in data["cpu_samples"]:
        before, after = sample["before"], sample["after"]
        percent = None
        if before and after:
            if any(
                type(x) not in (int, float) or not math.isfinite(x) or x < 0
                for counter in (before, after)
                for x in counter.values()
            ):
                raise ValueError("invalid CPU counter")
            total, idle = (
                after["total_s"] - before["total_s"],
                after["idle_s"] - before["idle_s"],
            )
            if total > 0 and 0 <= idle <= total:
                percent = 100 * (total - idle) / total
        if percent != sample["percent"]:
            raise ValueError("CPU sample/counter mismatch")
    return data


def groups(data, count, consumption, recipients):
    return {
        scheme: [
            row
            for row in data["cells"]
            if (row["count"], row["consumption"], row["recipients"], row["scheme"])
            == (count, consumption, recipients, scheme)
        ]
        for scheme in ("individual", "manifest", "merkle")
    }


def median(rows):
    return statistics.median(row["total_ms"] for row in rows)


def render(data):
    full = groups(data, 1024, "full", "shared")
    holdout = groups(data, 257, "full", "shared")
    fresh = groups(data, 1024, "full", "fresh")
    conservative = lambda g: min(row["total_ms"] for row in g["merkle"]) / max(
        row["total_ms"] for row in g["manifest"]
    )
    cpu = [
        sample["percent"]
        for sample in data["cpu_samples"]
        if sample["percent"] is not None
    ]
    lines = [
        "# Signed-manifest public API measurements",
        "",
        f"**{len(data['cells'])} measured cells, {sum(row['accepted'] for row in data['cells']):,} accepted record checks.** Every measured cell also rejected changed bytes. Three seven-record warm-ups are retained separately.",
        "",
        "## Decision",
        "",
        "Use the signed hash-list API as an option for one recipient consuming a large",
        "part of an immutable export. Open it once and reuse the verified digest list.",
        "",
        f"At 1,024 records with full/shared consumption, total median time was **{median(full['manifest']):.3f} ms** for the public manifest API, **{median(full['merkle']):.3f} ms** for Merkle receipts and **{median(full['individual']):.3f} ms** for individually pre-signed records. The manifest used **{full['manifest'][0]['metadata_bytes']:,} metadata bytes**, versus **{full['merkle'][0]['metadata_bytes']:,}** for Merkle receipts.",
        "",
        f"The observed min-Merkle/max-manifest throughput ratio was **{conservative(full):.3f}×**; the unchanged 257-record holdout gave **{conservative(holdout):.3f}×**. These ratios compare observed extremes, not statistical confidence intervals.",
        "",
        f"Separate recipients cannot share the validation work. At 1,024/full/fresh the manifest took **{median(fresh['manifest']):.3f} ms**, Merkle **{median(fresh['merkle']):.3f} ms**, and individual signatures **{median(fresh['individual']):.3f} ms**. Do not distribute a full hash list with every independent record by default.",
        "",
        "## All scenarios",
        "",
        "Total includes producer hashing/signing, metadata encoding, and consumer",
        "decoding/verification. Medians in milliseconds; each producer seals the entire",
        "export, including unused records. Fresh means one separately initialized",
        "recipient per record; shared means one recipient and one manifest transfer.",
        "",
        "| Batch / phase | Consumed / recipient | Individual | Public manifest | Merkle |",
        "|---|---|---:|---:|---:|",
    ]
    for phase, count, _ in SCHEDULE:
        for consumption, recipients in SCENARIOS:
            g = groups(data, count, consumption, recipients)
            lines.append(
                f"| {count} / {phase} | {g['manifest'][0]['selected']} / {recipients} | {median(g['individual']):.3f} | {median(g['manifest']):.3f} | {median(g['merkle']):.3f} |"
            )
    lines += [
        "",
        "## What changed from the prototype",
        "",
        "The [previous comparison](RECEIPT_RESULTS.md) used a benchmark-only hash-list",
        "consumer. This capture calls the public `seal_manifest`, `open_manifest` and",
        "`verify_record` APIs. Opening validates every hash entry, including entries a",
        "recipient never requests. The format has its own profile and strict bounds.",
        "Its performance must not be inferred from the earlier prototype's numbers.",
        "",
        "The adapter uses the same JSON index framing as the controls. Shared delivery",
        "actually sends/parses the manifest once; fresh delivery includes it each time.",
        "Raw captures retain producer, encoding and consumer phases and exact byte",
        "counts. The new `verify_all` count/order contract is tested separately; these",
        "timings use per-record verification with the caller's expected indices.",
        "",
        "## Scope and reproduction",
        "",
        "The [campaign](../benchmarks/MANIFEST_API_CAMPAIGN.md) was committed before",
        "primary measurement: 1,024 records/five repeats, then 257/three repeats without",
        "changes. Same cached OpenSSL CPU signing key, one thread, already-ready records,",
        "low-s ES256 and expected context/count/index. No GPU work or external service.",
        "",
        f"Environment: **{data['environment']['cpu']}**, {data['environment']['logical_cpus']} logical CPUs, {data['environment']['platform']}; Python {data['environment']['python']}, cryptography {data['environment']['cryptography']}, {data['environment']['openssl']}.",
        "",
        (
            f"Before each three-scheme comparison, 100 ms aggregate CPU samples ranged **{min(cpu):.1f}–{max(cpu):.1f}%** across the campaign. "
            if cpu
            else "Aggregate CPU counters were unavailable. "
        )
        + "This is background-load context, not CPU isolation or continuous attribution. Retain the observed ranges; do not treat this short shared-host run as a deployment guarantee.",
        "",
        "Excluded: key/fixture creation, record arrival/batch-fill delay, network/disk",
        "I/O, transport headers, identity/permission/accounting policy and hardware cost.",
        "Metadata sizes exclude record bodies. An online issuer signing only requested",
        "records is a different, potentially cheaper baseline. No customer demand or",
        "whole-system ROI is established.",
        "",
        f"Source: `{data['source_commit']}`. [Raw capture](../benchmarks/receipt_results/manifest-api-v1.json) includes all cells, CPU counters, warm-ups and source fingerprints.",
        "",
        "```sh",
        "python benchmarks/run_manifest_api.py --output dist/my-manifest-run.json",
        "python benchmarks/report_manifest_api.py --check",
        "python benchmarks/report_manifest_api.py --input dist/my-manifest-run.json --validate-only",
        "```",
        "",
        "The standard-library verifier checks source history, the complete schedule,",
        "work counts, phase sums, independent wire-size reconstruction and CPU samples.",
        "",
        "[Use the API and choose a format](RECORD_MANIFESTS.md) · [Product contract](PRODUCT_BRIEF.md)",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    data = validate(json.loads(args.input.read_text(encoding="utf-8")))
    if not args.validate_only:
        if args.input.resolve() != INPUT.resolve():
            raise ValueError(
                "use --validate-only for a new run, then review its interpretation"
            )
        text = render(data)
        if args.check:
            if OUTPUT.read_text(encoding="utf-8") != text:
                raise ValueError("stale public API report")
        else:
            OUTPUT.write_text(text, encoding="utf-8")
    print(
        f"PASS: {len(data['cells'])} complete API cells, source/work/bytes and CPU counters"
    )


if __name__ == "__main__":
    main()
