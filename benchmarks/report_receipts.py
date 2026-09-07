"""SPDX-License-Identifier: Apache-2.0. Validate and render record-export evidence."""

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
INPUT = ROOT / "benchmarks/receipt_results/cpu-record-exports-v1.json"
OUTPUT = ROOT / "docs/RECEIPT_RESULTS.md"
PUBLISHED_SHA256_LF = "82bdf9b07e618652bf448e789f0fadd71bb8695964b47cb9c32fb6caa26f5e90"
SOURCES = {
    "python/batchcrypto/__init__.py",
    "python/batchcrypto/jws.py",
    "python/batchcrypto/receipts.py",
    "benchmarks/run_receipts.py",
    "benchmarks/RECEIPT_CAMPAIGN.md",
}
SCHEDULE = [("primary", 64, 5), ("primary", 1024, 5), ("holdout", 257, 3)]


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


@lru_cache(maxsize=54)
def wire_sizes(count, selected, recipients, scheme):
    """Reconstruct exact serialized lengths with fixed-width dummy hashes/signature.

    No cryptography dependency; hashes/signatures change bytes, not wire length.
    Shape/profile constants refer to the frozen v1 campaign, not future APIs.
    """
    indexes = [i * count // selected for i in range(selected)]
    digest = b64(bytes(32))
    common = {"context": "synthetic-export-1", "count": count, "profile": scheme}

    def token(payload):
        return (
            b64(encoded({"alg": "ES256", "kid": "synthetic-key-1"}))
            + "."
            + b64(encoded(payload))
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

    if scheme == "merkle":
        manifest = token(
            {**common, "profile": "batchcrypto-record-receipt-v1", "root": digest}
        )
    elif scheme == "hash_list":
        manifest = token({**common, "hashes": [digest] * count})
    else:
        manifest = None
    share = recipients == "shared" and scheme != "individual"
    manifest_size = len(encoded(manifest)) if share else 0
    sizes = []
    for index in indexes:
        value = {"index": index}
        if scheme == "merkle":
            value["path"] = [digest] * depth(count, index)
        if not share:
            value["manifest"] = (
                manifest
                if scheme != "individual"
                else token({**common, "index": index, "sha256": digest})
            )
        sizes.append(len(encoded(value)))
    return manifest_size + sum(sizes), manifest_size, max(sizes)


def validate(data):
    if (
        data["schema"] != "record-receipt-campaign-v1"
        or data["complete"] is not True
        or data["smoke"] is not False
        or "failure" in data
    ):
        raise ValueError("requires a complete nonsmoke campaign")
    commit = data["source_commit"]
    if (
        not re.fullmatch(r"[0-9a-f]{40}", commit)
        or set(data["source_sha256"]) != SOURCES
    ):
        raise ValueError("missing source provenance")
    for path, expected in data["source_sha256"].items():
        blob = subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=ROOT)
        variants = (blob, blob.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
        if expected not in {hashlib.sha256(value).hexdigest() for value in variants}:
            raise ValueError("source fingerprint mismatch")
    if data["seed"] != 20260907:
        raise ValueError("unexpected run order seed")
    rng = random.Random(data["seed"])
    expected_rows = []
    for phase, count, repeats in SCHEDULE:
        for consumption, selected in (
            ("one", 1),
            ("quarter", count // 4),
            ("full", count),
        ):
            for recipients in ("shared", "fresh"):
                for repeat in range(repeats):
                    schemes = ["individual", "hash_list", "merkle"]
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
                        )
                        for scheme in schemes
                    )
    if len(data["cells"]) != len(expected_rows):
        raise ValueError("missing or extra measured cells")
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
                )
            )
            != expected
        ):
            raise ValueError("changed scenario or run order")
        if (
            row["accepted"] != row["selected"]
            or row["changed_rejected"] is not True
            or row["signatures"]
            != (row["count"] if row["scheme"] == "individual" else 1)
        ):
            raise ValueError("correctness or work-count failure")
        phases = [row[name] for name in ("producer_ms", "serialize_ms", "consumer_ms")]
        if any(
            type(value) not in (float, int) or not math.isfinite(value) or value <= 0
            for value in phases + [row["total_ms"]]
        ) or not math.isclose(sum(phases), row["total_ms"], abs_tol=1e-8):
            raise ValueError("invalid phase/total timing")
        sizes = wire_sizes(
            row["count"], row["selected"], row["recipients"], row["scheme"]
        )
        if (
            tuple(
                row[key]
                for key in (
                    "metadata_bytes",
                    "manifest_once_bytes",
                    "max_receipt_bytes",
                )
            )
            != sizes
        ):
            raise ValueError("serialized metadata size mismatch")
    return data


def render(data):
    lines = [
        "# Record-export measurements",
        "",
        "A CPU-only experiment found a specific use for portable subset verification.",
        "Merkle receipts reduce producer signing work and keep individual proofs small,",
        "but the simplest signed hash list wins when one recipient consumes a whole",
        "export. Independent recipients still each verify a signature.",
        "",
        f"**{len(data['cells'])} measured cells; {sum(row['accepted'] for row in data['cells']):,} accepted record checks; every cell rejected changed bytes.**",
        "",
        "## What to choose",
        "",
        "- For a recipient consuming most/all of an export, evaluate one signed hash",
        "  list first. At 1,024 records, shared full consumption took median **7.27 ms**",
        "  and 76,278 metadata bytes, versus Merkle **31.88 ms** and 493,811 bytes.",
        "- For isolated record delivery, a Merkle proof avoids sending all hashes:",
        "  one record from 1,024 used **821 bytes**, versus 63,075 for a signed hash",
        "  list. Individual signing used only 343 bytes. Smaller proofs do not imply",
        "  lower CPU time: the hash list was faster to produce in that one-record case.",
        "- With a quarter of 1,024 records consumed by independent recipients, Merkle",
        "  total time was median **32.73 ms**, versus **47.11 ms** for pre-signing each",
        "  record: 30.5% lower. The conservative throughput ratio was **1.213×**.",
        "  This includes signing the entire export, including unused records.",
        "- At full consumption by independent recipients, Merkle was slower than",
        "  individual signatures (137.63 versus 123.18 ms at 1,024). The full signed",
        "  hash list was larger and slower still. Do not generalize the quarter-use win.",
        "- The untouched 257-record holdout retained a **1.059×** conservative advantage",
        "  over pre-signing each record at quarter/fresh consumption. It did not retain",
        "  an advantage over the signed hash list on that conservative measure (**0.981×**).",
        "",
        "## Complete measured totals",
        "",
        "Times below are medians in milliseconds for producer + serialization + consumer.",
        "`shared` sends the batch manifest once and reuses a verifier; `fresh` creates",
        "a verifier and supplies the full signed manifest for each record. These are",
        "different recipient workloads, not interchangeable timing modes.",
        "",
        "| Batch / phase | Recipient | Consumed | Individual ms | Hash list ms | Merkle ms | Individual / Merkle conservative |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for phase, count, _ in SCHEDULE:
        for recipients in ("shared", "fresh"):
            for consumption in ("one", "quarter", "full"):
                groups = {
                    scheme: [
                        row
                        for row in data["cells"]
                        if (
                            row["count"],
                            row["recipients"],
                            row["consumption"],
                            row["scheme"],
                        )
                        == (count, recipients, consumption, scheme)
                    ]
                    for scheme in ("individual", "hash_list", "merkle")
                }
                medians = [
                    statistics.median(row["total_ms"] for row in group)
                    for group in groups.values()
                ]
                conservative = min(
                    row["total_ms"] for row in groups["individual"]
                ) / max(row["total_ms"] for row in groups["merkle"])
                lines.append(
                    f"| {count} / {phase} | {recipients} | {groups['merkle'][0]['selected']} | {medians[0]:.3f} | {medians[1]:.3f} | {medians[2]:.3f} | {conservative:.3f}× |"
                )
    lines += [
        "",
        "Conservative = fastest individual-baseline time / slowest Merkle time across",
        "the scenario's repeats. It is a cautious observed-range comparison, not a",
        "statistical confidence interval or population guarantee.",
        "",
        "## Scope and reproduction",
        "",
        "The [campaign](../benchmarks/RECEIPT_CAMPAIGN.md) was committed before primary",
        "measurement. Sizes 64/1,024 used five repeats; 257 was a three-repeat holdout",
        "with no implementation change in between. All three schemes used the same",
        "cached OpenSSL CPU key and one signing thread, low-s ES256, context/count/index",
        "binding and exact byte hashing. Merkle builds all proofs. No GPU was loaded.",
        "",
        "These are already-assembled immutable exports. Pre-signing every record is",
        "an offline-distribution baseline, not the cheapest answer to one live request:",
        "an online issuer could sign just the requested record. Reusable credentials,",
        "trusted transport, signing a whole file and existing provenance systems may",
        "also remove the need for this profile.",
        "",
        "Excluded: key generation, fixture creation, waiting to fill a batch, network",
        "and disk I/O, publisher accounting, policy/identity checks and hardware billing.",
        "Metadata bytes are actual serialized test envelopes, excluding record bodies",
        "and transport framing. This was a short shared-host Windows run without CPU",
        "isolation or continuous load telemetry; the ranges do not establish deployment",
        "latency, a tuned multicore baseline, customer demand or whole-system ROI.",
        "",
        f"Source commit: `{data['source_commit']}`. Environment: Python {data['environment']['python']}, cryptography {data['environment']['cryptography']}, {data['environment']['openssl']}; {data['environment']['logical_cpus']} logical CPUs; {data['environment']['processor']}; {data['environment']['platform']}.",
        "",
        "[Raw capture and provenance](../benchmarks/receipt_results/README.md) retains",
        "every cell, phase duration, metadata size and execution order. The standard",
        "library verifier checks historical source fingerprints, the complete declared",
        "schedule, work counts, phase sums and independently reconstructed wire sizes.",
        "",
        "```sh",
        "python benchmarks/run_receipts.py --output dist/my-record-export-run.json",
        "python benchmarks/report_receipts.py --check",
        "```",
        "",
        "The committed report describes the committed capture. A new capture's row",
        "validation can be run with `--input`; do not apply the narrative's measured",
        "values to another capture without reviewing and updating the interpretation.",
        "",
        "[Try the API and detached-file consumer](RECORD_RECEIPTS.md) · [Product hypothesis and ownership](PRODUCT_BRIEF.md)",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    raw = args.input.read_bytes().replace(b"\r\n", b"\n")
    data = validate(json.loads(raw.decode("utf-8")))
    if not args.validate_only:
        if args.input.resolve() != INPUT.resolve():
            raise ValueError(
                "use --validate-only for a new capture; narrative describes the committed experiment"
            )
        if hashlib.sha256(raw).hexdigest() != PUBLISHED_SHA256_LF:
            raise ValueError(
                "published interpretation requires its exact frozen capture"
            )
        text = render(data)
        if args.check:
            if args.output.read_text(encoding="utf-8") != text:
                raise ValueError("receipt report is stale")
        else:
            args.output.write_text(text, encoding="utf-8")
    print(
        f"PASS: {len(data['cells'])} complete cells, source provenance, outcomes and exact wire sizes"
    )


if __name__ == "__main__":
    main()
