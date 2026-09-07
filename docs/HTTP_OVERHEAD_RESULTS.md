# HTTP overhead: promote atomic cleanup, retain CPU-first controls

This follow-up isolates application overhead with simulated funds. A bounded
atomic cancellation call replaces one cancellation RPC/commit per unused book.
Per-access authorization, signature checks, durable spends and recovery remain
unchanged. Database pooling is an experimental option, not the default.

[Design and commands](HTTP_REFERENCE.md) · [Predeclared campaign and decision record](../benchmarks/HTTP_OVERHEAD_CAMPAIGN.md).

## What was kept and rejected

The [diagnostic](../benchmarks/http_results/overhead-diagnostic-v1.json) measured
a 5.12 ms median SQLite setup and a 35.40 ms p95 begin/lock wait in the CPU-book
full wave. Issuing its complete 64-signature CPU batch took 2.78 ms. Phase
scopes overlap and execute concurrently; those totals are not wall-time shares.

The [comparison](../benchmarks/http_results/overhead-comparison-v1.json) stopped after 56 cells:
8,383 accesses completed and reconciled; 1 client OSError occurred before publisher admission.
The OS cause was not captured. Port exhaustion is an unproven possibility,
not a finding. The incomplete capture, failed request and late work are retained
and excluded from promotion evidence. Later captures record OS error codes.

The pool reduced opens but increased observed transaction lock-wait tails and
full-wave elapsed time. These partial CPU-one-worker observations explain its
rejection; they are not a completed performance acceptance comparison:

| Workload | Variant | Available repeats | Median wall s | Median cleanup ms |
|---|---|---:|---:|---:|
| ready-full | baseline | 3 | 2.140 | 1.6 |
| ready-full | pool | 3 | 2.675 | 2.8 |
| ready-full | pool-batch | 1 | 2.918 | 3.3 |
| ready-quarter | baseline | 3 | 1.724 | 1229.0 |
| ready-quarter | pool | 3 | 1.343 | 616.2 |
| ready-quarter | pool-batch | 3 | 0.690 | 6.4 |

## Independent cleanup confirmation

[Complete holdout capture](../benchmarks/http_results/overhead-confirmation-v1.json):
**72 cells, 7,704 delivered accesses, 0 failures, 4,515 late completions.** Every cell reconciles.

Three repeats per cell; 32 eight-resource books; two buyer clients; one-second
deadline from readiness. Quarter use consumes two resources/book (64 accesses).
The baseline and candidate use the original per-operation database connections
and the same HTTP transport. Only unused-book cleanup is combined. Final WAL
checkpoint time is included in **both** wall costs, alongside preparation,
delivery and cleanup. Timers remain enabled for both paths.

| Workload | Path / signing workers | Baseline wall s | Batch wall s | Conservative complete-throughput ratio | Cleanup ms, baseline -> batch | Batch p99 ready ms |
|---|---|---:|---:|---:|---:|---:|
| holdout-quarter | cpu-books / 1 | 1.425 | 0.938 | 1.295 | 541.7 -> 21.6 | 917.26 |
| holdout-quarter | cpu-books / 4 | 1.452 | 0.976 | 1.448 | 636.7 -> 12.1 | 962.79 |
| holdout-quarter | direct / 1 | 0.869 | 0.868 | 0.955 | 1.6 -> 1.8 | 865.72 |
| holdout-quarter | gpu-books / 1 | 1.545 | 0.978 | 1.243 | 504.1 -> 21.9 | 955.93 |
| holdout-full | cpu-books / 1 | 3.840 | 3.587 | 0.956 | 1.6 -> 1.6 | 3535.15 |
| holdout-full | cpu-books / 4 | 3.904 | 3.598 | 0.956 | 1.7 -> 1.7 | 3548.41 |
| holdout-full | direct / 1 | 3.868 | 3.698 | 0.519 | 1.7 -> 1.7 | 3650.53 |
| holdout-full | gpu-books / 1 | 3.762 | 3.632 | 0.843 | 1.6 -> 1.8 | 3586.50 |
| urgent | cpu-books / 1 | 0.023 | 0.046 | 0.304 | 1.9 -> 1.6 | 44.01 |
| urgent | cpu-books / 4 | 0.046 | 0.047 | 0.380 | 1.8 -> 1.7 | 45.16 |
| urgent | direct / 1 | 0.031 | 0.031 | 0.882 | 1.7 -> 1.9 | 28.55 |
| urgent | gpu-books / 1 | 0.061 | 0.052 | 0.437 | 1.6 -> 1.7 | 49.73 |

The conservative ratio is minimum baseline wall time divided by maximum
candidate wall time at identical completed work. Values above one indicate
a repeated improvement in these three observations. At a fixed whole-host
hourly allocation, measured work cost scales with wall time; real billing
minimums, idle deployment, egress, payment fees and labor are not included.

Full-use and urgent controls need no cancellation and execute the same work
in both configurations. Their variation is not a cleanup acceleration. The
candidate does not move delivery earlier: cleanup happens after delivery.
Deadline misses remain visible; a cleanup gain is not an improved serving SLO.

## GPU adoption remains a separate decision

Both issuer CPU output verification and independent publisher admission remain
on the GPU path. Compare GPU to the CPU worker setting with best median
on-time goodput within the same batch-cleanup workload:

| Workload | CPU workers | Median GPU/CPU goodput | Conservative GPU/CPU goodput |
|---|---:|---:|---:|
| holdout-quarter | 1 | 0.959 | 0.876 |
| holdout-full | 1 | 0.923 | 0.615 |
| urgent | 1 | 0.888 | 0.331 |

Three finite waves on a shared host are not steady-state capacity or a
deployment-profitability estimate. The direct account control remains essential:
a book should provide needed scoped delegation or reusable permission, not
create signature work merely to keep a GPU busy. No GPU price was guessed.

## Reproduce and inspect

Comparison source: `87c4835e9bcb1406a3f0f6b10d7a210e5d30d2d5`. Confirmation source: `18f3e02bdb76ed7923b65c016829e4354f2f881d`.
Native SHA-256: `970538e7711828afb165b0220e78a081bf417db591168261b6de073f286ebdb2`.
Native source: `8f47e258165b25397877b265cc92265c3b7ca3f1`.
Build: Visual Studio 2022; CUDA 13.0.88; architecture 86; fresh R01 binary; native sources unchanged.
Each archive retains source hashes, host/GPU observations, per-phase timing,
request counts, all per-access observations and accounting snapshots.

```sh
python benchmarks/run_http_overhead.py --stage confirmation --candidate batch --output dist/http-confirmation.json
python benchmarks/report_http_overhead.py --check
```

The first command runs CPU controls; GPU flags are in the campaign. The second
validates published outcome, source, transaction and cost boundaries and
regenerates this table. Full Git history is required for source verification.
