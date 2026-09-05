"""SPDX-License-Identifier: Apache-2.0. Editable contribution model, not revenue evidence."""

import argparse
from dataclasses import asdict, dataclass, replace
import json
import math


@dataclass(frozen=True)
class Assumptions:
    price_usd: float = 0.001
    funding_usd: float = 10.0
    funded_spend_fraction: float = 1.0
    funding_fixed_usd: float = 0.30
    funding_rate: float = 0.029
    publisher_share: float = 0.85
    risk_fraction: float = 0.01
    external_usd_per_access: float = 0.0000025
    host_hourly_usd: float = 1.0
    host_utilization: float = 0.25
    payout_threshold_usd: float = 50.0
    payout_fixed_usd: float = 0.25
    payout_rate: float = 0.0025
    publishers: int = 10
    publisher_monthly_cost_usd: float = 2.0
    platform_monthly_fixed_usd: float = 2500.0

    def validate(self):
        for name, value in asdict(self).items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(f"invalid {name}")
        for name in ("price_usd", "funding_usd", "payout_threshold_usd"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        for name in ("funded_spend_fraction", "host_utilization"):
            if not 0 < getattr(self, name) <= 1:
                raise ValueError(f"invalid {name}")
        for name in ("publisher_share", "funding_rate", "risk_fraction", "payout_rate"):
            if getattr(self, name) > 1:
                raise ValueError(f"invalid {name}")
        if type(self.publishers) is not int or self.publishers < 1:
            raise ValueError("publishers must be a positive integer")


def evaluate(assumptions, completed_per_second):
    a = assumptions
    a.validate()
    if not math.isfinite(completed_per_second) or completed_per_second <= 0:
        raise ValueError("completed_per_second must be positive")
    # Unspent balances are liabilities, not revenue. Conservatively allocate the
    # whole funding fee to the redeemed fraction of the funded principal.
    funding_fee_per_redeemed_dollar = (
        a.funding_rate + a.funding_fixed_usd / a.funding_usd
    ) / a.funded_spend_fraction
    publisher = a.price_usd * a.publisher_share
    compute = a.host_hourly_usd / (3600 * completed_per_second * a.host_utilization)
    funding = a.price_usd * funding_fee_per_redeemed_dollar
    risk = a.price_usd * a.risk_fraction
    payout = publisher * (a.payout_rate + a.payout_fixed_usd / a.payout_threshold_usd)
    contribution = (
        a.price_usd
        - publisher
        - funding
        - risk
        - payout
        - a.external_usd_per_access
        - compute
    )
    fixed = a.platform_monthly_fixed_usd + a.publishers * a.publisher_monthly_cost_usd
    denominator = (
        1
        - a.publisher_share
        - funding_fee_per_redeemed_dollar
        - a.risk_fraction
        - a.publisher_share
        * (a.payout_rate + a.payout_fixed_usd / a.payout_threshold_usd)
    )
    capacity = completed_per_second * 3600 * 730 * a.host_utilization
    host_monthly = a.host_hourly_usd * 730
    before_compute = contribution + compute
    capacity_surplus = before_compute * capacity - host_monthly
    whole_host_break_even = None
    allocations = None
    if capacity_surplus > 0:
        allocations = max(1, math.ceil(fixed / capacity_surplus))
        whole_host_break_even = math.ceil(
            (fixed + allocations * host_monthly) / before_compute
        )
        # Integer request counts at a capacity boundary can need one more host.
        if whole_host_break_even > math.floor(allocations * capacity):
            allocations += 1
            whole_host_break_even = math.ceil(
                (fixed + allocations * host_monthly) / before_compute
            )
    return {
        "assumptions": asdict(a),
        "measured_completed_per_second": completed_per_second,
        "publisher_accrual_per_access_usd": publisher,
        "funding_cost_per_access_usd": funding,
        "compute_per_access_usd": compute,
        "risk_per_access_usd": risk,
        "payout_cost_per_access_usd": payout,
        "external_per_access_usd": a.external_usd_per_access,
        "platform_contribution_per_access_usd": contribution,
        "fixed_monthly_usd": fixed,
        "modeled_break_even_accesses_monthly": math.ceil(fixed / contribution)
        if contribution > 0
        else None,
        "whole_host_break_even_accesses_monthly": whole_host_break_even,
        "whole_host_allocations_at_break_even": allocations,
        "variable_cost_price_floor_usd": (compute + a.external_usd_per_access)
        / denominator
        if denominator > 0
        else None,
        "accesses_per_publisher_payout": math.ceil(a.payout_threshold_usd / publisher)
        if publisher > 0
        else None,
        "minimum_monthly_compute_allocation_usd": host_monthly,
        "single_allocation_modeled_monthly_capacity": capacity,
    }


def scenarios(rate):
    return [
        evaluate(
            replace(Assumptions(), price_usd=price, funded_spend_fraction=spend), rate
        )
        for price in (0.001, 0.01, 0.10)
        for spend in (1.0, 0.5, 0.25)
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--rate", type=float, required=True, help="measured completed accesses/s"
    )
    parser.add_argument(
        "--assumptions", help="JSON file overriding named Assumptions fields"
    )
    args = parser.parse_args()
    if args.assumptions:
        with open(args.assumptions, encoding="utf-8") as source:
            result = evaluate(Assumptions(**json.load(source)), args.rate)
    else:
        result = scenarios(args.rate)
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
