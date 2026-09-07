# Local HTTP access campaign, version 1

Question: can scoped reusable credentials, optionally signed in a guarded GPU
batch, improve completed synthetic publisher accesses under the same online
accounting contract? This measures an application reference implementation,
not an optimized HTTP server or a native CPU/GPU capacity ceiling.

Predeclare before captures: three repeats in seeded shuffled order; direct CPU
account purchases, CPU books with cached keys and 1/4 signing workers, guarded
GPU books on the explicitly selected idle device. Four buyer workers; no
cross-client batch collector. Each issue call supplies a ready batch under one
issuer key/epoch. Workloads: one urgent access; 64 four-resource books fully
consumed; the same books 25% consumed; full consumption with a controlled 50 ms
independent-work interval. Identical planning opportunity on CPU/GPU; direct
purchase starts only when access is needed and never prepares unused work.

The one-second access deadline starts when independent work ends and all
consumed accesses become ready together. Includes waiting for issuance, buyer
worker queueing, HTTP, recipient signature admission, online authorization,
durable spend, body delivery and buyer content/receipt checks. Report per-RPC
latency separately; never substitute it for ready-to-complete latency. Both
first-access and plan-to-complete observations are retained. A sleep models
an available overlap interval; it does not measure a real agent's reasoning.

All modes use buyer -> publisher -> authoritative issuer HTTP for spending.
Books also require buyer -> issuer issuance and cancellation. Direct account
access has no unnecessary signature; it shares the same authenticated online
authority but does not provide portable signed delegation. Books use ordinary
ES256 and a separate publisher signature check once per book. GPU additionally
checks every issued signature through VerifiedSigner. Key creation, listener
startup, one warmup transaction and shutdown are excluded. All other measured
work, including planning and reservation cleanup, enters the wall denominator.

Correctness gate: every returned payload and receipt matches the requested
content/terms/buyer; unique receipts equal completed accesses; simulated buyer
spend equals publisher accrual; zero reservation remains after cleanup. Stop
on an error, mismatch, unavailable/busy selected GPU or failed native guard.
Retain partial captures. Fault injection is tested separately, not in throughput
cells. Never replace a failed GPU batch with CPU signatures silently.

Keep source commit/hashes, binary SHA-256, driver/device telemetry and shared
host CPU load. Sample all GPUs every 500 ms, requiring three <=5% utilization
samples on the selected UUID before each GPU cell. The other GPU is untouched.
Very short kernels may fall between telemetry samples: this cannot establish
energy per operation. Process CPU time includes all roles; memory is process
lifetime peak, not a per-cell allocation delta. Library and CUDA build provenance
must be linked alongside a published capture. No rented GPU is needed.

Raw cells contain failures, late completions, unused planned accesses, signing
batch sizes, HTTP JSON body bytes, audit snapshots, and individual timings.
Nearest-rank p95/p99 with small samples are descriptive, not stable tail estimates.
Three repeat minima/maxima expose variation; no significance claim. These
finite ready waves do not establish steady-state arrival-rate capacity or SLOs.

Prices are explicit optional inputs: whole CPU host hourly cost plus incremental
GPU allocation hourly cost. Dollars per million on-time completions include all
measured wall time. Unknown inputs produce no dollar estimate. Deployment idle
time, minimum billing, payment fees, egress and labor remain separate inputs.
Report GPU/CPU repeat-median goodput ratio and conservative min-GPU/max-CPU
ratio against the best CPU worker setting, with the implied *maximum additional*
GPU/host cost ratio only where it is positive. A noisy ratio near one is not a
commercial advantage. More efficient service plumbing may change every result.

CPU reproduction: `python benchmarks/run_http_access.py --output dist/http-cpu.json`.
GPU: add `--library PATH --gpu-uuid GPU-...`. Requires `pip install '.[interop]'`.
`--smoke --repeats 1` validates wiring; smoke captures are not published evidence.
