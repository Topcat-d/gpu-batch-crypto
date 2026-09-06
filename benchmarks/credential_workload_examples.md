# Credential workload scenarios

Generated analytic examples; these are not measured GPU results.
JSON output records the complete assumptions for every scenario.

| Scenario | Batch | Credentials/s | Credentials/group/s | First-item fill ms | Fill budget ms | Result |
|---|---:|---:|---:|---:|---:|---|
| One authorized issuer, fresh credentials | 64 | 100,000.000 | 100,000.000 | 0.630 | 1.000 | FILL_BUDGET_PASSES |
| Same traffic across 100 trust/key groups | 64 | 100,000.000 | 1,000.000 | 63.000 | 1.000 | FILL_BUDGET_FAILS |
| 90% credential reuse, one issuer | 64 | 10,000.000 | 10,000.000 | 6.300 | 1.000 | FILL_BUDGET_FAILS |
| 32-access books, fully consumed | 64 | 3,125.000 | 3,125.000 | 20.160 | 1.000 | FILL_BUDGET_FAILS |
| 32-access books, quarter consumed | 64 | 12,500.000 | 12,500.000 | 5.040 | 1.000 | FILL_BUDGET_FAILS |
| 64 ready jobs per group, 100 groups | 64 | 100,000.000 | 1,000.000 | 0.000 | 1.000 | READY_BATCH_FOR_EVALUATION |
| All access covered by reusable credentials | 64 | 0.000 | 0.000 | n/a | 1.000 | NO_FRESH_CREDENTIAL_WORK |

Access rates, reuse, bundle utilization and group counts are scenario
assumptions. JSON output includes the complete inputs for every row.

More reuse or bundling can reduce total signing work while making GPU
batches slower to fill. Lower utilization creates unused entries, not
additional useful accesses. Already-ready waves assume all required
quotes/challenges/permissions exist before the remaining fill budget starts.

No device queue, cryptographic execution, verification, network or payment
cost is modeled. A passing fill condition only identifies a candidate
workload for measurement; it is not a throughput, SLO or savings claim.
