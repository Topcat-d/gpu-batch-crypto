"""SPDX-License-Identifier: Apache-2.0. Cost models with explicit boundaries.

No automatic price lookup or infrastructure provisioning. Currency is USD.
Costs are scenario estimates unless backed by a matched billing record.
"""

import argparse
import json
import math


def per_million(hourly, rate, utilization=1.0):
    if not all(math.isfinite(x) for x in (hourly, rate, utilization)):
        raise ValueError("inputs must be finite")
    if hourly < 0 or rate <= 0 or not 0 < utilization <= 1:
        raise ValueError("cost >= 0, rate > 0, utilization in (0,1] required")
    return hourly * 1_000_000 / (3600 * rate * utilization)


def owned_hourly(
    capital, residual, years, annual_hours, wall_watts, kwh_price, other_hourly=0
):
    values = (
        capital,
        residual,
        years,
        annual_hours,
        wall_watts,
        kwh_price,
        other_hourly,
    )
    if (
        not all(math.isfinite(x) and x >= 0 for x in values)
        or residual > capital
        or years <= 0
        or not 0 < annual_hours <= 8784
    ):
        raise ValueError("invalid owned-system assumptions")
    return (
        (capital - residual) / (years * annual_hours)
        + wall_watts / 1000 * kwh_price
        + other_hourly
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--hourly",
        type=float,
        required=True,
        help="fully allocated USD/hour, not GPU price plus already-included CPU",
    )
    p.add_argument(
        "--rate",
        type=float,
        required=True,
        help="primitive rate or measured within-SLO goodput",
    )
    p.add_argument(
        "--utilization",
        type=float,
        default=1,
        help="scenario duty factor; use 1 for already measured load/idle goodput",
    )
    p.add_argument("--scope", choices=("primitive", "within-slo"), required=True)
    p.add_argument(
        "--billing-seconds",
        type=float,
        help="actual billable instance lifetime, including setup and idle",
    )
    p.add_argument(
        "--successful-operations",
        type=int,
        help="actual accepted operations over that same lifetime",
    )
    a = p.parse_args()
    output = {
        "scope": a.scope,
        "hourly_usd": a.hourly,
        "rate_per_s": a.rate,
        "utilization_assumption": a.utilization,
        "estimated_usd_per_million": per_million(a.hourly, a.rate, a.utilization),
    }
    if (a.billing_seconds is None) != (a.successful_operations is None):
        p.error("provide both billing seconds and successful operations")
    if a.billing_seconds is not None:
        if (
            not math.isfinite(a.billing_seconds)
            or a.billing_seconds <= 0
            or a.successful_operations <= 0
        ):
            p.error("billing lifetime and successful operation count must be positive")
        cost = a.hourly * a.billing_seconds / 3600
        output.update(
            billable_compute_usd=cost,
            lifetime_usd_per_million=cost * 1_000_000 / a.successful_operations,
        )
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
