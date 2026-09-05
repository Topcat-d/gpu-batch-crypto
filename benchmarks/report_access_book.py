"""SPDX-License-Identifier: Apache-2.0. Generate the measured and modeled report."""

import argparse
import csv
import io
import json
import math
from pathlib import Path

from access_business_model import scenarios

ROOT = Path(__file__).resolve().parents[1]


def q99(values):
    return sorted(values)[math.ceil(len(values) * 0.99) - 1]


def generate(data):
    rows = data["rows"]
    lines = [
        "# Amortized access: measured results and economics",
        "",
        "The CPU implementation groups funded, exact-resource permissions into one",
        "signed book. It verifies that book once, then retains **one atomic durable",
        "accounting transaction per redeemed resource**. The on-demand single-item",
        "baseline uses the same code, cached keys and signature policy and only",
        "creates grants for consumed resources. Neither path invokes a GPU.",
        "",
        f"Source commit `{data['commit']}`. All 20 predeclared cells completed;",
        f"{sum(r['completed'] for r in rows):,} redemptions reconcile to buyer balances and publisher accruals.",
        "Two opposite-order repeats on a shared local Windows host; one Python thread,",
        "SQLite WAL with FULL synchronous commits. Rates include admission, redemption",
        "and release of unused reservations. They exclude network, real payments,",
        "content delivery, replicas and authentication. This is a complete local",
        "example path, not a tuned multi-core service or a deployment capacity promise.",
        "",
        "[Predeclared method](../benchmarks/ACCESS_BOOK_CAMPAIGN.md) ·",
        "[Raw capture](../benchmarks/access_book_results/ryzen7800x3d-2026-09-05.json) ·",
        "[Runnable design](ACCESS_BOOK_DESIGN.md)",
        "",
        "## Durable CPU comparison",
        "",
        "Each range includes both repeats. The ratio divides the slower book run by",
        "the faster on-demand baseline at the same consumption fraction. This is a",
        "conservative comparison of these observations, not a confidence interval.",
        "",
        "| Plan used | Book size | Completed accesses/s | Conservative ratio | Transactions/access | Signatures/access | First-access p99 ms | Redemption-call p99 ms |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    csv_out = io.StringIO(newline="")
    writer = csv.writer(csv_out, lineterminator="\n")
    writer.writerow(
        [
            "consumed_percent",
            "book_size",
            "repeat",
            "completed",
            "accesses_per_second",
            "transactions_per_access",
            "signatures_per_access",
            "first_access_p99_ms",
            "redemption_p99_ms",
            "whole_book_completion_p99_ms",
        ]
    )
    for percent in (100, 25):
        baseline = max(
            r["completed"] / r["elapsed_seconds"]
            for r in rows
            if r["book_size"] == 0 and r["consumed_percent"] == percent
        )
        for size in (0, 8, 32, 128, 256):
            pair = [
                r
                for r in rows
                if r["book_size"] == size and r["consumed_percent"] == percent
            ]
            rates = [r["completed"] / r["elapsed_seconds"] for r in pair]
            first = [q99(r["first_access_ms"]) for r in pair]
            redemption = [q99(r["redemption_ms"]) for r in pair]
            r = pair[0]
            lines.append(
                f"| {percent}% | {size or 'on demand'} | {min(rates):,.1f}–{max(rates):,.1f} | {min(rates) / baseline:.2f}× | {r['transactions'] / r['completed']:.3f} | {r['signatures'] / r['completed']:.5f} | {min(first):.2f}–{max(first):.2f} | {min(redemption):.2f}–{max(redemption):.2f} |"
            )
            for r in pair:
                writer.writerow(
                    [
                        percent,
                        size,
                        r["repeat"],
                        r["completed"],
                        f"{r['completed'] / r['elapsed_seconds']:.6f}",
                        f"{r['transactions'] / r['completed']:.6f}",
                        f"{r['signatures'] / r['completed']:.6f}",
                        f"{q99(r['first_access_ms']):.6f}",
                        f"{q99(r['redemption_ms']):.6f}",
                        f"{q99(r['completion_ms']):.6f}",
                    ]
                )
    lines += [
        "",
        "The first-access measurement includes issuing and admitting the book. Later",
        "redemption-call measurements use its admitted database record. Serial completion",
        "of every resource in a large book can take much longer; raw completion times",
        "and the CSV retain this. The harness offers one book at a time, so these",
        "latencies are not an arrival-load SLO comparison across different book sizes.",
        "",
        "With full consumption, a 32-item book replaces 32 signatures and 32 admissions",
        "with one of each, and reduces durable transactions from 96 to 34. With 25%",
        "consumption, it uses one signature instead of eight, and 11 transactions",
        "instead of 24, including the refund transaction. A larger plan still has to",
        "reserve more budget and carry more scope. Preparing a book is not a purchase",
        "of all its items: only committed redemptions accrue publisher proceeds.",
        "",
        "## Editable economic scenarios",
        "",
        "These are **assumptions**, not observed revenue, invoices or a pricing proposal.",
        "The illustration uses the slower full-consumption 32-item result, $1/hour",
        "host allocation, 25% effective capacity utilization, 85% publisher share,",
        "1% risk allowance, $0.0000025 other variable cost/access, ten publishers,",
        "$2/month/publisher operating cost and $2,500/month platform fixed cost.",
        "Payout modeling assumes $50 batches, $0.25 fixed + 0.25% per payout; these",
        "payout and operating costs are user-editable placeholders, not provider quotes.",
        "",
        "A $10 funding payment uses the illustrative US domestic card schedule of",
        "2.9% + $0.30, as observed September 5, 2026. Other processor services,",
        "jurisdictions, refunds, disputes and negotiated schedules can differ.",
        "[Stripe payment pricing](https://stripe.com/pricing). Funded-spend fraction",
        "is how much funded principal becomes purchased access; it is different from",
        "the plan consumption fraction above. All unspent principal remains a liability.",
        "",
        "| Access price | Funded principal spent | Publisher accrual/access | Platform contribution/access before fixed costs | Whole-host break-even accesses/month | Accesses per publisher $50 payout |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    rate = min(
        r["completed"] / r["elapsed_seconds"]
        for r in rows
        if r["book_size"] == 32 and r["consumed_percent"] == 100
    )
    business = scenarios(rate)
    for result in business:
        a = result["assumptions"]
        count = result["whole_host_break_even_accesses_monthly"]
        lines.append(
            f"| ${a['price_usd']:.3f} | {a['funded_spend_fraction']:.0%} | ${result['publisher_accrual_per_access_usd']:.6f} | ${result['platform_contribution_per_access_usd']:.6f} | {f'{count:,}' if count is not None else 'No break-even'} | {result['accesses_per_publisher_payout']:,} |"
        )
    lines += [
        "",
        "Contribution includes capacity-priced compute. Break-even separately charges",
        "whole allocated hosts at $730/month each and the stated fixed costs, so small",
        "traffic volumes do not receive fictitious fractional-instance savings. A faster",
        "implementation may create headroom without reducing an existing monthly bill.",
        "No horizontal-scaling result is implied by this arithmetic. Fixed costs must",
        "be replaced by the actual staffing, operations, compliance and support budget.",
        "",
        "A $10 funding payment costs $0.59 under the stated card assumption. At full",
        "spend, this is 5.9% of access revenue; at only 25% spend, allocating the same",
        "fee to purchased access costs 23.6%. That exceeds the assumed 15% platform",
        "share before compute. Reducing signatures cannot fix that case. Expired",
        "reservations released back to a still-used account do not themselves cause",
        "this loss: the funded-spend fraction concerns the eventual funding lifecycle.",
        "",
        "```sh",
        "python benchmarks/verify_access_book.py",
        "python benchmarks/report_access_book.py --check",
        f"python benchmarks/access_business_model.py --rate {rate:.6f}",
        "# Override any assumptions using --assumptions path/to/cost-inputs.json",
        "```",
        "",
        "[Machine-readable assumptions/results](../benchmarks/access_business_scenarios.json)",
        "and [measured CSV](../benchmarks/access_book.csv) are generated with this note.",
        "A positive modeled contribution is a technical feasibility condition. Paid",
        "buyer demand, content rights, publisher acceptance and settlement need a pilot.",
        "",
    ]
    return (
        "\n".join(lines),
        csv_out.getvalue(),
        json.dumps(business, indent=2, allow_nan=False) + "\n",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    data = json.loads(
        (
            ROOT / "benchmarks/access_book_results/ryzen7800x3d-2026-09-05.json"
        ).read_text()
    )
    if not data["complete"]:
        raise RuntimeError("capture incomplete")
    outputs = generate(data)
    for path, value in zip(
        (
            "docs/ACCESS_BOOK_RESULTS.md",
            "benchmarks/access_book.csv",
            "benchmarks/access_business_scenarios.json",
        ),
        outputs,
    ):
        target = ROOT / path
        if args.check:
            if target.read_bytes() != value.encode():
                raise RuntimeError(f"stale generated report: {path}")
        else:
            target.write_text(value, encoding="utf-8", newline="\n")
    print("PASS: access-book reports current")


if __name__ == "__main__":
    main()
