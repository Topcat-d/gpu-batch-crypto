# Optimization research

This is a queue of experiments, not a claim that their proposed changes are
faster. The objective is more verified work within a declared latency budget,
with lower total resource cost and unchanged cryptographic contracts. CPU wins,
negative results and inconclusive measurements are useful outcomes.

The tasks are deliberately small enough for one engineer or a smaller coding
model to complete one research step at a time. Start with R01, then use measured
bottlenecks to choose the next task. Do not run every possible matrix each day.

Current follow-up priority: R07's short-record SHA-256 measurements, after R01.
The published standalone hashing captures predate the wrapper materialization
fix. A fresh hashing comparison should establish today's behavior before
proposing identity-oriented performance claims.

## Starting evidence

- [Output materialization](DISPATCH_RESULTS.md): the repeated Python `.raw`
  copying problem has already been fixed. Do not rediscover it as a new change.
- [Guarded verification control](VERIFICATION_CONTROL_RESULTS.md): CPU wins in
  the measured issuer-check plus consumer-check path. Those two trust boundaries
  remain separate when comparing implementations of that contract.
- [Pipeline results](PIPELINE_RESULTS.md): batching, queueing, CPU verification,
  deadline misses and actual GPU use belong in the system comparison.
- [Ready waves](READY_WAVE_RESULTS.md): already-available batches have different
  economics from requests waiting in an arrival queue.
- [Hardware and costs](ECONOMICS.md): historical A100/L40S captures and current
  RTX captures describe different implementations and timing boundaries.

Read [CONTRIBUTING](../CONTRIBUTING.md), [benchmark methodology](BENCHMARKS.md)
and the selected task's existing campaign before changing its implementation.
The [agent-web research case](AGENT_WEB_RESEARCH.md) and
[dated protocol map](PROTOCOL_LANDSCAPE.md) provide the wider hypothesis and
integration boundaries. Use the [credential-workload model](../benchmarks/credential_workload_model.py)
to check workload assumptions; its scenario outputs are not measured baselines.

## One bounded research run

1. Read the previous result and choose one unblocked task below. State one
   falsifiable hypothesis and the exact files involved. Read only the relevant
   component and campaign, rather than repeatedly ingesting the entire repo.
2. Record the source commit, working-tree status, relevant source hashes,
   binary hashes, hardware, toolchain and workload. A binary's existence does
   not establish that it was built from current source.
3. Declare the baseline, metric, correctness gate, timing boundary and practical
   improvement threshold before trying variants. Use the best accepted baseline
   under the same workload, including a tuned native CPU comparison.
4. Default budget: 30 minutes wall time, at most two candidate variants,
   six minutes of timed GPU work, and four primary-source research pages.
   A build or unavailable tool can consume the budget: save the blocker and
   next action instead of silently extending it. No cloud rental is needed.
5. Measure a baseline first. Change one variable per candidate. For comparative
   performance, use at least two complete repeats with reversed run order and
   preserve every cell. Confirm a promising result on a predeclared held-out
   batch size or arrival/key distribution. Screening is not sustained capacity.
6. Save the result, exact commands, raw captures and candidate diff. Finish with
   `CANDIDATE`, `NO_GAIN`, `INCONCLUSIVE` or `BLOCKED`, and one concrete next step.
   A blocked GPU task can give way to independent CPU analysis or source research.

Local run state and scratch artifacts may live under the already ignored
`dist/optimization-research/`. Use a timestamped directory per run; preserve
unsuccessful variants. Keep research notes separate from published measurements.
Publishable results need durable raw captures and the applicable verifier, as
described in [CONTRIBUTING](../CONTRIBUTING.md).

## Task queue

### R01 — Reproducible baseline and bottleneck map

**Purpose:** make the next experiment comparable to current source rather than
an old DLL. **Scope:** build metadata, `benchmarks/native/`, relevant capture
scripts and a local baseline manifest. This task does not optimize production
code. Inventory existing executables and their source provenance, run the
relevant correctness checks, and select a small representative native CPU and
guarded GPU baseline. If source provenance is missing, rebuild before using
that binary for a current-source claim.

**Deliverable:** exact rerunnable commands, machine/tool versions, separate
primitive and complete verified timing boundaries, baseline captures and the
largest measured overhead. Distinguish unavailable profiler data from evidence.
**Done when:** another run can reproduce the selected baseline and choose R02–R07
using a stated observation. Unavailable tools are a specific blocker, not a
reason to treat historical measurements as a fresh baseline.

### R02 — Transfer and synchronization overhead

**Hypothesis:** small synchronous transfers cost enough that reducing submission
and synchronization overhead improves a complete call. **Scope:**
`src/engine/runtime.hpp`, `src/engine/crypto_engine.cu` and a focused benchmark.
The current `copy()` helper synchronizes its stream after each copy. Measure
packing, transfers, kernel completion, output construction and clearing before
deciding what is redundant.

Compare one synchronization change or reusable staging-buffer change at a time.
The public ABI remains synchronous; success still requires completed work and
the promised clearing. Preserve buffer lifetimes, error propagation, device
selection, key epochs and per-item status. Treat pinned-memory limits and extra
host copies as costs. CUDA Graphs are a follow-up only if launch overhead is
measured to matter. **Gate:** affected GPU differential/failure tests, exact
current binary, repeated whole-call latency and reserved-memory measurements.

### R03 — CPU signing and verification cost

**Hypothesis:** avoidable key/context setup, encoding or worker coordination
limits verified goodput. **Scope:** `benchmarks/native/pipeline_crypto.hpp`,
`benchmarks/native/ready_wave.cpp`, `python/batchcrypto/verified.py` and their
tests. Profile the existing native CPU baseline before proposing a faster guard
or caching strategy. First determine what is already reused.

Use valid OpenSSL ownership/threading rules and cache only under explicit key
and epoch identity. Compare the same issuer and recipient verification contract;
do not obtain a speedup by dropping checks. Deterministic and randomized ECDSA
profiles must remain explicitly labeled. **Gate:** every output independently
verified, fault/epoch tests, CPU seconds, worker counts and guarded end-to-end
goodput. A faster benchmark baseline is evidence, not automatically a new library
interface. Label which component actually changed.

### R04 — Deadline-aware batching and CPU/GPU routing

**Hypothesis:** a policy using compatible queue depth and remaining time beats
a fixed GPU threshold for some arrival distributions. **Scope:**
`benchmarks/native/pipeline.cpp` and `benchmarks/run_pipeline.py`; routing remains
an experimental application policy outside the library ABI.

Predeclare sparse, bursty and sustained synthetic arrivals, at least one
multi-key case, and explicit 10/50 ms experimental budgets. Change either the
minimum batch or maximum wait first. Use a fixed trace/seed when applicable;
do not label an already-ready wave as a trace of online arrivals. **Gate:** exact
offered/completed/rejected/expired accounting, compatible-key isolation, bounded
queues and all-output verification. Report p50/p95/p99, actual GPU fraction,
batch-fill wait and verified on-time goodput. Keep low-load CPU wins visible.

### R05 — Python/ABI packing and allocation

**Hypothesis:** remaining descriptor construction, input packing or allocations
cost more than their useful work at some batch sizes. **Scope:**
`python/batchcrypto/__init__.py`, `python/batchcrypto/jws.py` and affected tests.
Profile allocation volume and native-vs-wrapper timing before editing. Keep the
completed `.raw` materialization fix as part of the baseline.

Test one reuse/packing strategy with both small and large payload batches.
Maintain Python ownership and thread behavior, bounded inputs, ABI semantics,
output clearing and CPU-only import independence. Do not move required work
outside the timer. **Gate:** relevant guards/JWS/crypto tests, affected GPU checks,
allocation/memory evidence and complete caller-visible latency.

### R06 — P-256 tables, occupancy and launch geometry

**Hypothesis:** a measured register, occupancy, cache or table-loading bottleneck
can be improved without changing signature semantics. **Scope:**
`src/p256/fixed_base.cuh`, `src/kernels/crypto_kernels.cuh` and P-256 benchmarks.
Start with compiler/profile evidence comparing existing reference, comb and
full-window backends. Change one launch or public-data layout parameter.

Keep secret-dependent memory/branch behavior in the security analysis: a faster
table lookup does not establish constant-time behavior. Do not change nonce
generation or field arithmetic as a routine tuning shortcut. Imported-source
changes require the existing modification/provenance process. **Gate:** public
table regeneration checks, independent signature/edge-case checks, memory and
register evidence, unprofiled repeat measurements and small-batch regressions.
If expertise or differential coverage is insufficient, deliver a reviewed
experiment proposal rather than calling an untested kernel an improvement.

### R07 — AES-GCM/SHA-256 workload crossover

Start with short synthetic identifier-sized records for SHA-256: a bounded
selection from 16, 32, 64, 128, 256, 512 and 1,024 bytes, including a SHA-256
padding-boundary control when relevant. Compare a few predeclared batches from
1 through 4,096 while respecting the run budget. Capture whole-call latency
and hashes/second, including packing, transfers, output materialization and
clearing; keep independent oracle checks explicitly inside or outside the
stated timing boundary. Compare the current wrapper with the current native
CPU/GPU paths, rather than reusing old numbers as current measurements.

These synthetic records do not reproduce a specific identity vendor's private
scheme. Raw SHA-256, HMAC, signed identity assertions and identity verification
are different operations; benchmark and label them separately if added.
Hashes/second must not be presented as verified people/second. Larger-content
hashing and AES-GCM follow as separate hypotheses rather than expanding the
first short-record run into an unbounded matrix.

**Hypothesis:** useful GPU regimes may depend on payload size and batch layout,
even though the initial public small-record matrix favored CPU. **Scope:**
`benchmarks/run_matrix.py`, the relevant engine/kernel paths and crypto tests.
Choose a bounded payload/batch matrix and compare a realistic native CPU path;
Python overhead alone must not become the GPU's advantage.

Include transfers, associated data, tag handling and caller-visible output.
Check variable/empty records and invalid-tag behavior. First measure crossover;
propose a kernel or packing variant only after identifying the bottleneck.
**Gate:** every digest/ciphertext independently checked, failed authentication
releases no plaintext, and throughput, latency, memory and transfer bytes are
reported. No crossover within the measured range is a valid finding.

### R08 — Whole-system economics and workload suitability

**Hypothesis:** measured changes either improve useful capacity per total cost
or identify workloads where CPU is the economical default. **Scope:**
`benchmarks/economics.py`, `benchmarks/access_business_model.py`, their tests and
new local scenario inputs. Use comparable accepted measurements from other
tasks; preserve historical inputs and findings.

Report break-even ratios and cost per million verified on-time operations, with
utilization and whole-host allocation explicit. Model queue wait, unused work
and common downstream overhead separately from measured crypto time. GPU board
power is not host wall power. Current rental prices require dated provider
sources and a matching instance configuration; leave unknown prices as inputs.
**Gate:** unit/denominator checks and sensitivity analysis. Access-book results
use simulated balances and do not establish payments, publisher revenue or a
deployed paid-access service. A primitive gain does not prove business ROI.

## Candidate acceptance and record

A candidate must retain the relevant tests and security/ABI contract and improve
the predeclared metric beyond observed noise. A practical screening threshold
of 5% is a default, not a statistical guarantee. Report uncertainty and any
latency, memory, CPU or power tradeoff. A throughput win that fails the declared
deadline is not a win for that workload. Include a repeat/holdout confirmation
and an obvious rollback before proposing a new default.

Record: task ID; hypothesis; baseline commit and diff hashes; candidate diff;
sources with retrieval dates; hardware/toolchain and binary hashes; exact
commands; timing boundary; correctness outcomes and skips; all variants and
raw captures; latency/goodput/resource comparison; limitations; disposition;
next action. Never rewrite a historical capture or relabel its source hash.

## Primary references for targeted research

Use current official documentation and original papers to investigate a specific
bottleneck. Check support in the installed toolchain before adopting a feature.
References inspected September 6, 2026:

- [NVIDIA CUDA Best Practices Guide](https://docs.nvidia.com/cuda/cuda-c-best-practices-guide/index.html):
  transfer batching, pinned-memory costs and measurement methodology.
- [CUDA asynchronous execution](https://docs.nvidia.com/cuda/cuda-programming-guide/02-basics/asynchronous-execution.html):
  stream ordering and host-memory requirements.
- [Nsight Systems User Guide](https://docs.nvidia.com/nsight-systems/UserGuide/):
  profiling controls and overhead; final comparisons should run without tracing.

If the queue stops producing actionable experiments, perform a bounded primary
source search tied to one unresolved bottleneck. Record the date, applicability,
license where code reuse is proposed, and cheapest falsifiable next experiment.
Do not append generic papers or reopen a rejected idea without new evidence.
