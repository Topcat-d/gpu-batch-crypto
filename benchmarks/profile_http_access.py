"""SPDX-License-Identifier: Apache-2.0. One diagnostic pass before optimization."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
from types import SimpleNamespace

from run_http_access import ROOT, SCENARIOS, git, gpu_snapshot, measure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or git("status", "--porcelain", "--untracked-files=normal"):
        parser.error("commit the diagnostic; preserve prior captures")
    source_paths = ["benchmarks/HTTP_OVERHEAD_CAMPAIGN.md", "benchmarks/profile_http_access.py",
                    "benchmarks/run_http_access.py"] + [str(p.relative_to(ROOT)).replace("\\", "/") for p in sorted((ROOT / "examples/http_access").glob("*.py"))]
    result = {"schema": 1, "purpose": "diagnostic only; overlapping phase scopes", "complete": False,
              "commit": git("rev-parse", "HEAD"), "timestamp_utc": datetime.now(timezone.utc).isoformat(),
              "platform": platform.platform(), "gpus_before": gpu_snapshot(),
              "sources": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in source_paths}, "cells": []}
    options = SimpleNamespace(library=None, device=0, clients=4, slo_ms=1000,
                              host_hourly=None, gpu_hourly=None, profile=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for scenario, mode in ((SCENARIOS[1], "direct"), (SCENARIOS[1], "cpu-books"), (SCENARIOS[2], "cpu-books")):
        cell = measure(scenario, mode, 4, options)
        result["cells"].append(cell)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"scenario": scenario["name"], "mode": mode, "wall_s": cell["elapsed_seconds"],
                          "timings": cell["service_timings"]}, indent=2), flush=True)
        if cell["failed"] or not cell["reconciled"] or cell["server_errors"] or cell["cleanup_errors"]:
            raise RuntimeError("diagnostic correctness gate failed")
    result["complete"] = True
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
