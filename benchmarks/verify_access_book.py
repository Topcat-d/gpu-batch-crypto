"""SPDX-License-Identifier: Apache-2.0. Check archived accounting and provenance."""

import hashlib
import json
import math
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "benchmarks/access_book_results"


def verify_row(row, campaign="books"):
    size, percent = row["book_size"], row["consumed_percent"]
    sizes = (1, 32) if campaign == "atomic-control" else (0, 8, 32, 128, 256)
    assert size in sizes and percent in (25, 100)
    assert row.get("fused", False) == (campaign == "atomic-control")
    assert row["planned"] == 2048 and row["repeat"] in (1, 2)
    completed = 2048 * percent // 100
    issued = completed if size in (0, 1) else 2048 // size
    releases = issued if size > 1 and percent < 100 else 0
    assert row["completed"] == completed
    assert row["issued"] == row["signatures"] == row["verifications"] == issued
    expected_transactions = (
        completed
        if size == 1
        else issued * (1 if campaign == "atomic-control" else 2) + completed + releases
    )
    assert row["transactions"] == expected_transactions
    assert issued * 400 <= row["token_bytes"] <= issued * 4096
    assert math.isfinite(row["elapsed_seconds"]) and row["elapsed_seconds"] > 0
    assert math.isfinite(row["process_cpu_seconds"]) and row["process_cpu_seconds"] >= 0
    for name, count in (
        ("completion_ms", completed),
        ("redemption_ms", completed),
        ("first_access_ms", issued),
    ):
        values = row[name]
        assert len(values) == count
        assert all(
            math.isfinite(x) and 0 < x <= row["elapsed_seconds"] * 1000 for x in values
        )
    assert all(a >= b for a, b in zip(row["completion_ms"], row["redemption_ms"]))
    per_book = 1 if size in (0, 1) else size * percent // 100
    assert row["completion_ms"][::per_book] == row["first_access_ms"]
    assert sum(row["redemption_ms"]) <= row["elapsed_seconds"] * 1000
    assert row["audit"] == {
        "accounts": [
            {
                "buyer": "buyer",
                "initial": 2048000,
                "available": 2048000 - completed * 1000,
                "reserved": 0,
                "redeemed": completed * 1000,
            }
        ],
        "publishers": [{"id": "publisher", "accrued": completed * 1000}],
        "books": issued,
        "redemptions": completed,
    }


def verify_capture(data):
    assert data["schema"] == 1 and data["complete"] is True and "failure" not in data
    campaign = data.get("campaign", "books")
    assert campaign in ("books", "atomic-control")
    sizes = (1, 32) if campaign == "atomic-control" else (0, 8, 32, 128, 256)
    assert len(data["rows"]) == len(sizes) * 4
    assert {
        (r["book_size"], r["consumed_percent"], r["repeat"]) for r in data["rows"]
    } == {(s, p, r) for s in sizes for p in (25, 100) for r in (1, 2)}
    for row in data["rows"]:
        verify_row(row, campaign)
    required = {
        "examples/access_book/engine.py",
        "python/batchcrypto/jws.py",
        "python/batchcrypto/__init__.py",
        "benchmarks/run_access_book.py",
        "benchmarks/ACCESS_BOOK_CAMPAIGN.md",
    }
    if "campaign" in data:
        required.add("benchmarks/ACCESS_BOOK_ATOMIC_CONTROL.md")
    assert set(data["sources"]) == required
    for path, expected in data["sources"].items():
        content = subprocess.check_output(
            ["git", "show", f"{data['commit']}:{path}"], cwd=ROOT
        )
        assert hashlib.sha256(content).hexdigest() == expected, path


def main():
    assert __debug__, "do not run the archive verifier with Python -O"
    files = {}
    for line in (DIRECTORY / "SHA256SUMS").read_text().splitlines():
        digest, filename = line.split()
        assert Path(filename).name == filename and filename not in files
        files[filename] = digest
    assert set(files) == {p.name for p in DIRECTORY.glob("*.json")}
    count = 0
    for filename, expected in files.items():
        raw = (DIRECTORY / filename).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == expected
        data = json.loads(raw)
        verify_capture(data)
        count += sum(r["completed"] for r in data["rows"])
    print(
        f"PASS: {len(files)} access-book captures; {count:,} completed redemptions reconciled"
    )


if __name__ == "__main__":
    main()
