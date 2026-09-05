# Amortized access: measured results and economics

The CPU implementation groups funded, exact-resource permissions into one
signed book. It verifies that book once, then retains **one atomic durable
accounting transaction per redeemed resource**. The on-demand single-item
baseline uses the same code, cached keys and signature policy and only
creates grants for consumed resources. Neither path invokes a GPU.

Source commit `95527b2218061a2a840e171639ffdbc4b9c90b18`. All 20 predeclared cells completed;
25,600 redemptions reconcile to buyer balances and publisher accruals.
Two opposite-order repeats on a shared local Windows host; one Python thread,
SQLite WAL with FULL synchronous commits. Rates include admission, redemption
and release of unused reservations. They exclude network, real payments,
content delivery, replicas and authentication. This is a complete local
example path, not a tuned multi-core service or a deployment capacity promise.

[Predeclared method](../benchmarks/ACCESS_BOOK_CAMPAIGN.md) ·
[Raw capture](../benchmarks/access_book_results/ryzen7800x3d-2026-09-05.json) ·
[Runnable design](ACCESS_BOOK_DESIGN.md)

## Stronger co-located CPU control

**Use this comparison when the issuer and consumer share an authority.**
The on-demand CPU path issues, independently verifies and redeems in one
durable commit. The book path also fuses its issue and admission into one
commit. Both retain every signature, scope and accounting check. The
larger ratios below against three separate commits are not the advantage
over this optimized baseline.

Control source `7876d1d86166b13a7552bec5981d04b1635e4e8f`; eight additional cells and
10,240 redemptions, all reconciled.
[Predeclared control](../benchmarks/ACCESS_BOOK_ATOMIC_CONTROL.md) ·
[Raw control](../benchmarks/access_book_results/ryzen7800x3d-atomic-2026-09-05.json)

| Plan used | Atomic CPU accesses/s | Fused 32-item book accesses/s | Conservative ratio | Atomic first-access p99 ms | Book first-access p99 ms |
|---|---:|---:|---:|---:|---:|
| 100% | 441.6–450.9 | 528.9–536.7 | 1.173× | 5.92–6.08 | 9.38–18.11 |
| 25% | 418.5–436.0 | 439.5–441.3 | 1.008× | 5.15–5.26 | 9.59–10.16 |

At full use, the book still performs 32 times fewer signatures and
verifications, but now requires 33 durable commits per 32 accesses
versus the atomic baseline's 32. At 25% use it requires ten commits
per eight accesses versus eight. The whole-path improvement is
therefore much smaller than the primitive work reduction. Use the
atomic CPU path for sparse or uncertain demand; evaluate books when
known reuse or delegation justifies the reservation and admission.

## Original comparison with separate commits

Each range includes both repeats. The ratio divides the slower book run by
the faster on-demand baseline at the same consumption fraction. This is a
conservative comparison of these observations, not a confidence interval.

| Plan used | Book size | Completed accesses/s | Conservative ratio | Transactions/access | Signatures/access | First-access p99 ms | Redemption-call p99 ms |
|---|---|---:|---:|---:|---:|---:|---:|
| 100% | on demand | 180.1–189.6 | 0.95× | 3.000 | 1.00000 | 10.13–11.09 | 3.26–3.32 |
| 100% | 8 | 411.9–456.4 | 2.17× | 1.250 | 0.12500 | 9.48–12.90 | 3.22–5.07 |
| 100% | 32 | 518.5–544.8 | 2.74× | 1.062 | 0.03125 | 11.14–12.36 | 3.16–3.44 |
| 100% | 128 | 557.0–570.0 | 2.94× | 1.016 | 0.00781 | 12.07–13.08 | 3.14–3.31 |
| 100% | 256 | 534.8–557.9 | 2.82× | 1.008 | 0.00391 | 10.89–15.16 | 3.51–5.47 |
| 25% | on demand | 185.8–187.1 | 0.99× | 3.000 | 1.00000 | 8.68–9.92 | 2.86–2.90 |
| 25% | 8 | 220.0–223.3 | 1.18× | 2.500 | 0.50000 | 8.90–9.46 | 3.27–4.44 |
| 25% | 32 | 396.5–400.1 | 2.12× | 1.375 | 0.12500 | 10.67–11.27 | 3.31–3.66 |
| 25% | 128 | 499.6–500.6 | 2.67× | 1.094 | 0.03125 | 7.81–9.79 | 3.27–4.49 |
| 25% | 256 | 535.7–538.1 | 2.86× | 1.047 | 0.01562 | 13.32–14.62 | 3.18–3.22 |

The first-access measurement includes issuing and admitting the book. Later
redemption-call measurements use its admitted database record. Serial completion
of every resource in a large book can take much longer; raw completion times
and the CSV retain this. The harness offers one book at a time, so these
latencies are not an arrival-load SLO comparison across different book sizes.

With full consumption, a 32-item book replaces 32 signatures and 32 admissions
with one of each, and reduces durable transactions from 96 to 34. With 25%
consumption, it uses one signature instead of eight, and 11 transactions
instead of 24, including the refund transaction. A larger plan still has to
reserve more budget and carry more scope. Preparing a book is not a purchase
of all its items: only committed redemptions accrue publisher proceeds.

## Editable economic scenarios

These are **assumptions**, not observed revenue, invoices or a pricing proposal.
The illustration uses the slower co-located full-consumption 32-item result, $1/hour
host allocation, 25% effective capacity utilization, 85% publisher share,
1% risk allowance, $0.0000025 other variable cost/access, ten publishers,
$2/month/publisher operating cost and $2,500/month platform fixed cost.
Payout modeling assumes $50 batches, $0.25 fixed + 0.25% per payout; these
payout and operating costs are user-editable placeholders, not provider quotes.

A $10 funding payment uses the illustrative US domestic card schedule of
2.9% + $0.30, as observed September 5, 2026. Other processor services,
jurisdictions, refunds, disputes and negotiated schedules can differ.
[Stripe payment pricing](https://stripe.com/pricing). Funded-spend fraction
is how much funded principal becomes purchased access; it is different from
the plan consumption fraction above. All unspent principal remains a liability.

| Access price | Funded principal spent | Publisher accrual/access | Platform contribution/access before fixed costs | Whole-host break-even accesses/month | Accesses per publisher $50 payout |
|---:|---:|---:|---:|---:|---:|
| $0.001 | 100% | $0.000850 | $0.000070 | 45,060,659 | 58,824 |
| $0.001 | 50% | $0.000850 | $0.000011 | 247,619,048 | 58,824 |
| $0.001 | 25% | $0.000850 | $-0.000107 | No break-even | 58,824 |
| $0.010 | 100% | $0.008500 | $0.000742 | 4,369,748 | 5,883 |
| $0.010 | 50% | $0.008500 | $0.000152 | 21,138,212 | 5,883 |
| $0.010 | 25% | $0.008500 | $-0.001028 | No break-even | 5,883 |
| $0.100 | 100% | $0.085000 | $0.007458 | 435,657 | 589 |
| $0.100 | 50% | $0.085000 | $0.001558 | 2,083,334 | 589 |
| $0.100 | 25% | $0.085000 | $-0.010242 | No break-even | 589 |

Contribution includes capacity-priced compute. Break-even separately charges
whole allocated hosts at $730/month each and the stated fixed costs, so small
traffic volumes do not receive fictitious fractional-instance savings. A faster
implementation may create headroom without reducing an existing monthly bill.
No horizontal-scaling result is implied by this arithmetic. Fixed costs must
be replaced by the actual staffing, operations, compliance and support budget.

A $10 funding payment costs $0.59 under the stated card assumption. At full
spend, this is 5.9% of access revenue; at only 25% spend, allocating the same
fee to purchased access costs 23.6%. That exceeds the assumed 15% platform
share before compute. Reducing signatures cannot fix that case. Expired
reservations released back to a still-used account do not themselves cause
this loss: the funded-spend fraction concerns the eventual funding lifecycle.

```sh
python benchmarks/verify_access_book.py
python benchmarks/report_access_book.py --check
python benchmarks/access_business_model.py --rate 528.917110
# Override any assumptions using --assumptions path/to/cost-inputs.json
```

[Machine-readable assumptions/results](../benchmarks/access_business_scenarios.json)
and [measured CSV](../benchmarks/access_book.csv) are generated with this note.
A positive modeled contribution is a technical feasibility condition. Paid
buyer demand, content rights, publisher acceptance and settlement need a pilot.
