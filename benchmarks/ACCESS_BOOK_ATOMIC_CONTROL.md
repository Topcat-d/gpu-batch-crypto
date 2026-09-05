# Co-located commit control

The original 20-cell campaign measured distinct issue, admission and redemption
commits. Its 32-item books achieved a 2.74x conservative throughput ratio at
full use and 2.12x at 25% use. Before attributing those gains to book reuse,
test the stronger **co-located single-commit CPU baseline**.

Add `Clearing.purchase`: same ES256 signature, independent CPU verification,
budget, catalog, scope, receipt and conservation rules, but issue/admit/redeem
commit once. Nested steps use SQLite savepoints; any outer failure rolls back
all steps. Do not weaken the baseline's cryptographic or accounting checks.

Give the 32-item book the same optimization: issue/admit commit together, then
one commit per resource, plus one unused-reservation release if needed. Both
paths use the same authority and database. Comparison applies when co-location
is architecturally available; independent issuer/publisher services require an
explicit different transaction boundary and measured network cost.

Two modes (atomic on-demand and fused 32-item book), 100%/25% plan consumption,
two opposite-order repeats, 2,048 planned resources per cell: **8 cells**.
Reuse the previous capture method, exact subset, fresh database, warmup and
boundaries. Preserve the first campaign. No GPU, rentals or real transactions.
In this control the atomic baseline's redemption-call time includes all steps;
book redemption-call time excludes preparation, which appears in first-access
latency. Whole-run throughput includes all work for both modes.
