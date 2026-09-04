"""SPDX-License-Identifier: Apache-2.0. Validate the curated historical archive.

Checks published bytes, excerpt counters and invalid-run labels, not old binaries.
"""

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "historical"
manifest = json.loads((ROOT / "manifest.json").read_text())
inventory = {"manifest.json"}
valid_runs = invalid_runs = 0
for record in manifest["records"]:
    name = record["excerpt"]
    if Path(name).name != name or name in inventory:
        raise RuntimeError("invalid or duplicate archive path")
    inventory.add(name)
    path = ROOT / name
    if hashlib.sha256(path.read_bytes()).hexdigest() != record["excerpt_sha256"]:
        raise RuntimeError(f"modified excerpt: {name}")
    if not re.fullmatch(r"[a-f0-9]{64}", record["source_sha256"]):
        raise RuntimeError("invalid original hash")
    if path.suffix == ".json":
        data = json.loads(path.read_text())
        for row in data["summaries"]:
            if (
                row["total_ok"] != row["batch_size"] * row["iterations"]
                or row["total_errors"]
            ):
                raise RuntimeError("historical envelope count error")
        continue
    parts = re.split(r"^===== .* =====$", path.read_text(), flags=re.M)
    for part in parts:
        if "accounting_ok:" not in part:
            continue
        values = dict(re.findall(r"^\s+(\w+):\s+(\d+)\b", part, re.M))
        accepted = bool(re.search(r"accounting_ok:\s+true", part))
        if accepted:
            valid_runs += 1
            if "submitted" in values:
                assert values["submitted"] == values["completed"], name
            else:
                assert values["chunks_submitted"] == values["chunks_completed"], name
                assert values["ops_completed"] == values["resps_routed"], name
                assert int(values["frames_err"]) == 0, name
            assert values["oracle_passed"] == values["oracle_total"], name
            assert int(values["oracle_failed"]) == int(values["oracle_skipped"]) == 0, (
                name
            )
        else:
            invalid_runs += 1
            assert name == "a100-20260709-shapes.txt", name
            assert values["submitted"] != values["completed"], name
if inventory != {path.name for path in ROOT.iterdir() if path.is_file()}:
    raise RuntimeError("unmanifested archive file")
assert invalid_runs == 2
print(
    f"PASS: historical checksums; {valid_runs} clean captures; {invalid_runs} explicitly rejected captures."
)
