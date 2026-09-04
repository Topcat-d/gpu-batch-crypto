"""SPDX-License-Identifier: Apache-2.0. Verify the public source boundary."""

import hashlib
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / "EXTRACTION.json").read_text(encoding="utf-8-sig"))
expected = set()
for row in manifest:
    p = (root / row["destination"]).resolve()
    if not p.is_relative_to(root):
        raise RuntimeError("extraction escapes repository")
    expected.add(p)
    if hashlib.sha256(p.read_bytes()).hexdigest() != row["extracted_sha256"]:
        raise RuntimeError(f"changed extract: {row['destination']}")
if expected != {p.resolve() for p in (root / "src/imported").rglob("*") if p.is_file()}:
    raise RuntimeError("unrecorded or missing imported source")
for p in list((root / "src").rglob("*.cu")) + list((root / "src").rglob("*.cuh")):
    for inc in re.findall(r'^\s*#include\s+"([^"]+)"', p.read_text(), re.M):
        found = next(
            (
                q.resolve()
                for q in (p.parent / inc, root / "include" / inc)
                if q.is_file()
            ),
            None,
        )
        if found is None or not found.is_relative_to(root):
            raise RuntimeError(f"external/missing include: {p.name}: {inc}")
if (root / ".gitmodules").exists():
    raise RuntimeError("submodule dependency found")
print(
    f"PASS: {len(expected)} attributed extracts; all local includes resolve inside this repository."
)
