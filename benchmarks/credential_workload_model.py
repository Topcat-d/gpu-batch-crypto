"""SPDX-License-Identifier: Apache-2.0.

Analytic credential-workload model, not a performance benchmark or scheduler.
Assumes one signature per issued credential and uniformly spaced arrivals per
compatible group. A ready-wave scenario explicitly assumes its inputs are ready.
"""

import argparse
import json
import math
from pathlib import Path


def _number(name, value, *, minimum=0, maximum=None, positive=False):
    try:
        finite = math.isfinite(value)
    except (TypeError, OverflowError):
        finite = False
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not finite
        or value < minimum
        or (positive and value == 0)
        or (maximum is not None and value > maximum)
    ):
        raise ValueError(f"invalid {name}")


def evaluate(
    *,
    accesses_per_second,
    fresh_fraction,
    accesses_per_credential,
    credential_use_fraction,
    compatible_groups,
    batch_size,
    fill_budget_ms,
    ready_jobs_per_group=0,
):
    """Return necessary batch-fill conditions, never GPU capacity or savings."""
    _number("accesses_per_second", accesses_per_second)
    _number("fresh_fraction", fresh_fraction, maximum=1)
    _number("credential_use_fraction", credential_use_fraction, positive=True, maximum=1)
    _number("fill_budget_ms", fill_budget_ms)
    for name, value, minimum in (
        ("accesses_per_credential", accesses_per_credential, 1),
        ("compatible_groups", compatible_groups, 1),
        ("batch_size", batch_size, 1),
        ("ready_jobs_per_group", ready_jobs_per_group, 0),
    ):
        if type(value) is not int or value < minimum:
            raise ValueError(f"invalid {name}")
        _number(name, value, minimum=minimum)
    if 0 < ready_jobs_per_group < batch_size:
        raise ValueError("ready-wave scenario must supply a full compatible batch")

    useful_fresh_accesses = accesses_per_second * fresh_fraction
    useful_accesses_per_credential = accesses_per_credential * credential_use_fraction
    credentials = useful_fresh_accesses / useful_accesses_per_credential
    per_group = credentials / compatible_groups
    issued_entries = credentials * accesses_per_credential
    if not all(math.isfinite(n) for n in (credentials, per_group, issued_entries)):
        raise ValueError("derived rate overflow")
    if accesses_per_second > 0 and fresh_fraction > 0 and credentials == 0:
        raise ValueError("derived credential rate underflow")
    if credentials > 0 and per_group == 0:
        raise ValueError("derived per-group rate underflow")

    if credentials == 0:
        if ready_jobs_per_group:
            raise ValueError("ready jobs conflict with zero required credential work")
        first_wait = mean_wait = None
        disposition = "NO_FRESH_CREDENTIAL_WORK"
    elif ready_jobs_per_group >= batch_size:
        first_wait = mean_wait = 0.0
        disposition = "READY_BATCH_FOR_EVALUATION"
    else:
        first_wait = (batch_size - 1) / per_group * 1000
        mean_wait = first_wait / 2
        if not math.isfinite(first_wait):
            raise ValueError("derived wait overflow")
        disposition = (
            "FILL_BUDGET_PASSES"
            if first_wait <= fill_budget_ms
            else "FILL_BUDGET_FAILS"
        )
    return {
        "kind": "analytic_scenario_not_measurement",
        "arrival_assumption": (
            "already_ready_compatible_wave"
            if ready_jobs_per_group
            else "uniform_evenly_spaced_arrivals"
        ),
        "useful_fresh_accesses_per_second": useful_fresh_accesses,
        "issued_credentials_per_second": credentials,
        "credentials_per_group_per_second": per_group,
        "issued_access_entries_per_second": issued_entries,
        "unused_access_entries_per_second": max(0.0, issued_entries - useful_fresh_accesses),
        "first_item_fill_ms": first_wait,
        "mean_fill_ms": mean_wait,
        "disposition": disposition,
        "limitations": (
            "No signing, verification, transport, device queue, authorization, "
            "revocation, settlement, cost or stochastic tail-latency model. "
            "Passing the fill budget does not establish a GPU advantage."
        ),
    }


def evaluate_scenarios(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("kind") != "illustrative_assumptions_not_measurements":
        raise ValueError("scenario file must identify its illustrative assumptions")
    names = set()
    rows = []
    for scenario in data["scenarios"]:
        name = scenario["name"]
        if not isinstance(name, str) or not name or name in names:
            raise ValueError("scenario names must be nonempty and unique")
        names.add(name)
        assumptions = dict(data["defaults"], **scenario["overrides"])
        rows.append({"name": name, "assumptions": assumptions, **evaluate(**assumptions)})
    return rows


def markdown(rows):
    lines = [
        "# Credential workload scenarios",
        "",
        "Generated analytic examples; these are not measured GPU results.",
        "JSON output records the complete assumptions for every scenario.",
        "",
        "| Scenario | Batch | Credentials/s | Credentials/group/s | First-item fill ms | Fill budget ms | Result |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        wait = row["first_item_fill_ms"]
        wait_text = "n/a" if wait is None else f"{wait:,.3f}"
        name = row["name"].replace("|", "\\|").replace("\n", " ").replace("\r", " ")
        lines.append(
            f"| {name} | {row['assumptions']['batch_size']} | {row['issued_credentials_per_second']:,.3f} | "
            f"{row['credentials_per_group_per_second']:,.3f} | {wait_text} | "
            f"{row['assumptions']['fill_budget_ms']:.3f} | {row['disposition']} |"
        )
    lines += [
        "",
        "Access rates, reuse, bundle utilization and group counts are scenario",
        "assumptions. JSON output includes the complete inputs for every row.",
        "",
        "More reuse or bundling can reduce total signing work while making GPU",
        "batches slower to fill. Lower utilization creates unused entries, not",
        "additional useful accesses. Already-ready waves assume all required",
        "quotes/challenges/permissions exist before the remaining fill budget starts.",
        "",
        "No device queue, cryptographic execution, verification, network or payment",
        "cost is modeled. A passing fill condition only identifies a candidate",
        "workload for measurement; it is not a throughput, SLO or savings claim.",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenarios", type=Path,
        default=Path(__file__).with_name("credential_workload_scenarios.json"),
    )
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args()
    rows = evaluate_scenarios(args.scenarios)
    if args.format == "markdown":
        print(markdown(rows), end="")
    else:
        print(json.dumps(rows, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
