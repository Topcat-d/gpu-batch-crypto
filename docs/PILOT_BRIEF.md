# Pilot brief: useful content within a controlled buyer budget

**Proposition:** Make useful publisher content easy for AI services to purchase
within a controlled budget, with auditable accounting. The open library supplies
reusable cryptography; the access-book example evaluates authorization and
accounting choices. GPU acceleration is an optional implementation decision.

This is a reviewable evaluation brief. No buyer/publisher participation, content
license, payment-provider agreement, paid demand or settlement is claimed here.
The example's balances and publisher accruals are simulated.

## Who pays and what they receive

Choose one specific AI service with recurring tasks where rights-cleared,
current or specialist content improves an outcome its users value. The buyer
sets a spending ceiling and accepts the stated content/use terms. The publisher
sets a rate card and delivery/recovery obligations. Identify the person who owns
the buyer budget and the publisher's authority to license the selected material.

| Required pilot input | Decision it supports | Current status |
|---|---|---|
| Named buyer, task and budget owner | Is there an actual purchasing decision? | To be supplied by a willing participant |
| Licensed corpus, publisher and rate card | Is access useful and commercially permitted? | To be agreed |
| Free/subscription/direct-account alternatives | Does this integration add value beyond existing access? | To be compared on the same tasks |
| Accepted identity, authorization and payment profiles | Can both systems interoperate? | ES256 demonstrated; live partner adapter not implemented |
| Funding, refunds, fee split, settlement and support obligations | Can both parties receive sustainable net value? | Editable model; actual agreements/adapters pending |
| Latency, volume, cancellation and availability targets | Which technical path should be adopted? | Workload-specific inputs still required |

## Why choose these components

The candidate advantages are reusable scoped permissions, explicit buyer
budgets, exact resource/terms binding, atomic accounting and recoverable
redemptions. Each advantage must be measured against a simpler implementation
that offers the same required behavior.

| Alternative | Fair question for the pilot |
|---|---|
| Existing subscription or license | Does it already cover the buyer's use at lower total cost? |
| Direct authenticated prepaid account | Is a separately signed/delegated credential actually necessary? |
| Atomic CPU purchase with one durable commit | Does book preparation/reuse justify its added reservation and first-access latency? |
| Existing paid-access provider | Does an adapter reduce integration/support burden enough to adopt this component? |
| GPU-assisted signing | After removing reusable/cached work, is fresh signing still a material whole-service bottleneck? |

The [local co-located comparison](ACCESS_BOOK_RESULTS.md) found 1.173x conservative
throughput for fully used 32-resource books against atomic CPU purchases, with
book first-access p99 up to 18.11 ms versus 6.08 ms. At 25% use, the ratio was
1.008x. This is evidence for a workload-dependent tradeoff, not paid demand,
protocol adoption or a general GPU cost advantage.

## Bounded evaluation sequence

1. **Technical integration.** Choose the minimum [components](COMPONENTS.md),
   run their [entry-point examples](GETTING_STARTED.md), identify the existing
   identity/billing systems and document the remaining adapters. Record engineer
   hours to integrate and operate them. Use synthetic data/funds initially.
2. **Buyer-value comparison.** Predeclare representative tasks, a free or
   already-licensed baseline, spending ceilings and a blinded answer comparison.
   A starting study could use 100 tasks; that is a proposed size, not statistical
   validation. Record declines, failed tasks and ties as well as favorable answers.
3. **Agreed paid pilot.** After rights, business terms and the payment arrangement
   are established, use a bounded real budget and explicit refund/recovery policy.
   Measure actual consent, completed purchases and repeat purchases. Simulated
   authorization is not a paid conversion.
4. **Joint economic decision.** Reconcile provider statements, buyer charges,
   platform fee/risk costs and publisher payouts. Compare the deployed service
   against the agreed baseline at the required latency and availability target.

## Measure benefits and costs for both sides

| Measure | Definition / denominator |
|---|---|
| Paid conversion | Actual authorized purchases divided by all eligible priced offers shown; include declines |
| Buyer value | Task quality and cost per successful task versus the same baseline; retain failures |
| Repeat demand | Returning paying buyers within a predeclared window, with the cohort denominator reported |
| Publisher benefit | Reconciled net proceeds, payout delay and incremental serving/support cost; unpaid accrual remains a liability |
| Platform contribution | Revenue less publisher share, funding/payout fees, refunds/risk, serving costs and capacity allocation |
| Whole-service quality | End-to-end p95/p99, failures, retries and recovery under actual arrivals; include preparation and network work |
| Integration burden | Initial engineering hours, ongoing support/onboarding cost and operational incidents |

Use [access_business_model.py](../benchmarks/access_business_model.py) with actual
inputs. Keep unspent principal as a liability and charge whole allocated hosts
where appropriate. The example ledger credits gross publisher receivables;
the model's illustrative fee split requires real ledger accounts before use
with money. The published $1/hour and operating/payment assumptions are scenarios,
not a quote for running the deployed service.

## Decide before widening the pilot

Agree acceptance thresholds with the participants before outcomes are available.
Continue when recurring buyers value the access, publishers receive worthwhile
net proceeds, actual contribution supports the operating budget, and service
quality meets the agreed target. Narrow or stop the experiment if free/existing
access performs as well, recurring purchases do not materialize, payment/support
costs overwhelm margin or recovery/settlement cannot be reconciled.

Adoption can be limited to a useful component: CPU cryptography, a guarded GPU
signer, token construction, public data or an accounting pattern. The public
project remains generic and Apache-2.0 regardless of a particular pilot's outcome.
