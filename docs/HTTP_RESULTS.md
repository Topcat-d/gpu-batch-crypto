# Local HTTP reference results

A complete synthetic access path was measured: issuer preparation, publisher
admission, online durable spending, content delivery, buyer checks and unused
reservation cleanup. These finite loopback waves do not establish production
capacity, Internet latency, commercial demand or a GPU deployment cost advantage.

Capture: [raw observations](../benchmarks/http_results/rtx3060-http-v2.json);
source `24e89f19a6e810cab5317ca3a8bde8b92813869a`; `2026-09-07T01:12:51.322001+00:00`.
[Design and reproduction](HTTP_REFERENCE.md) · [Predeclared campaign](../benchmarks/HTTP_ACCESS_CAMPAIGN.md).

**48 cells; 6,924 delivered accesses reconciled; 0 failures; 3,218 completions after the deadline.** Warmup transactions are excluded from these totals.

The conservative GPU/CPU comparison establishes **no positive additional GPU cost allowance in any tested workload**.

## Observed service behavior

Median of three repeats. Goodput counts ready-to-complete deadline successes;
its denominator includes the entire measured wave, planning and cleanup. The
one-second deadline starts when all consumed accesses are ready. p99 includes
buyer worker queueing. An urgent cell contains only one access, so its p99
is just that single observation. Four buyer workers in every cell.

| Workload | Path / signing workers | On-time accesses/s | First access ms | p99 ready ms | CPU seconds | Cleanup ms |
|---|---|---:|---:|---:|---:|---:|
| urgent | cpu-books / 1 | 22.0 | 45.06 | 45.06 | 0.000 | 0.00 |
| urgent | cpu-books / 4 | 22.3 | 44.47 | 44.47 | 0.031 | 0.00 |
| urgent | direct / 1 | 27.8 | 35.79 | 35.79 | 0.000 | 0.00 |
| urgent | gpu-books / 1 | 17.5 | 56.63 | 56.63 | 0.016 | 0.00 |
| ready-full | cpu-books / 1 | 47.8 | 27.22 | 2270.46 | 0.984 | 0.00 |
| ready-full | cpu-books / 4 | 60.2 | 30.92 | 1999.65 | 1.078 | 0.00 |
| ready-full | direct / 1 | 67.1 | 9.79 | 1941.61 | 0.922 | 0.00 |
| ready-full | gpu-books / 1 | 54.6 | 42.77 | 2106.48 | 1.078 | 0.00 |
| ready-quarter | cpu-books / 1 | 35.5 | 47.76 | 567.53 | 0.312 | 1158.58 |
| ready-quarter | cpu-books / 4 | 35.3 | 36.46 | 571.45 | 0.438 | 1228.14 |
| ready-quarter | direct / 1 | 133.7 | 9.37 | 478.57 | 0.203 | 0.00 |
| ready-quarter | gpu-books / 1 | 38.4 | 54.66 | 522.05 | 0.531 | 1151.35 |
| overlap-full | cpu-books / 1 | 58.0 | 11.51 | 2057.62 | 0.891 | 0.00 |
| overlap-full | cpu-books / 4 | 51.0 | 11.81 | 2260.02 | 0.984 | 0.00 |
| overlap-full | direct / 1 | 50.9 | 13.10 | 2258.77 | 1.062 | 0.00 |
| overlap-full | gpu-books / 1 | 65.5 | 11.49 | 1940.65 | 0.828 | 0.00 |

CPU books use cached OpenSSL keys with both 1 and 4 signing workers. Direct
account purchases require no signatures. GPU books include VerifiedSigner's
CPU output check **and** the publisher's independent signature admission.

The [earlier interrupted capture](../benchmarks/http_results/rtx3060-http-v1-interrupted.json)
is retained: 47 cells completed before the GPU idle preflight stopped the
final cell. It is excluded from this complete campaign. The second campaign
adds a bounded wait for three consecutive idle samples; measured work and
the shuffled schedule are unchanged. No unfavorable cell was discarded.

## GPU economics gate

For each workload, choose the CPU-book worker setting with the highest median
on-time goodput. The conservative ratio is minimum GPU repeat divided by
maximum repeat for that CPU setting. A ratio above one is only a measured
allocation-cost ceiling under equal utilized wall-time assumptions; three
observations on a shared host are not a stable profitability estimate.

| Workload | Best CPU workers | Median GPU/CPU | Conservative GPU/CPU | Positive additional GPU/host cost ceiling |
|---|---:|---:|---:|---:|
| urgent | 4 | 0.785 | 0.692 | None established |
| ready-full | 4 | 0.907 | 0.652 | None established |
| ready-quarter | 1 | 1.081 | 0.944 | None established |
| overlap-full | 1 | 1.130 | 0.703 | None established |

No cloud invoice or GPU rental price was inferred. Raw captures retain optional
whole-host/additional-GPU prices and dollars per million on-time completions;
missing prices are null. Billing minimums, idle allocation, payment fees,
egress and labor are not measured. Compare the unsigned direct path as well
as CPU books before proposing a GPU purchase.

## Interpretation and reproduction limits

- Fully used books amortize one signature over four accesses. Quarter-use
  books still prepare all four entries but deliver only one; cancellation
  releases the remainder. Direct purchases prepare only consumed accesses.
- The 50 ms independent-work interval gives both signing paths the same
  preparation opportunity. Individual plan-to-complete and ready-to-complete
  timings remain in the capture; hiding preparation does not erase its cost.
- Two HTTP listeners and all clients run in one Python process, with a new
  TCP connection per RPC and a SQLite connection per operation. This baseline
  deliberately remains an inspectable reference, not a tuned network stack.
- GPU batches contain 64 signatures in larger waves. They do not represent
  saturation-sized native batches or a cross-tenant routing experiment.
- Process CPU time includes all roles; peak memory is cumulative for the
  process. Per-cell host CPU load and all-GPU telemetry disclose shared load.
  Sampled GPU power cannot resolve short kernels or establish energy savings.
  Windows CPU-time resolution can report zero for a short urgent cell;
  that does not mean the request used no CPU.

A follow-up should first measure how much persistent connections, a durable
database connection pool and admission/spend RPC grouping reduce service
overhead. Preserve the same authorization and recovery contracts.

## Binary provenance

Native library SHA-256: `970538e7711828afb165b0220e78a081bf417db591168261b6de073f286ebdb2`.
Native source commit: `8f47e258165b25397877b265cc92265c3b7ca3f1`.
Recorded build: Visual Studio 2022; CUDA 13.0.88; CUDA architecture 86; fresh R01 build; native source unchanged in HTTP campaign.
Host, Python/OpenSSL versions and observed GPU load are in the raw capture.
Only the selected GPU UUID is used for cryptography; other devices are
observed for shared-load disclosure and never modified.

Regenerate and validate: `python benchmarks/report_http_access.py --check`.
