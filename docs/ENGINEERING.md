# Engineering note: evaluating GPU Batch Crypto

[GPU Batch Crypto](https://github.com/Topcat-d/gpu-batch-crypto) is an independent Apache-2.0 library for processing many cryptographic operations together on an NVIDIA GPU. It includes a native execution engine, C ABI, Python bindings, reusable device runtimes and public P-256 precomputation tables. Its strongest measured use case is signing many independent records with P-256 ECDSA when enough compatible work is available to form a useful batch.

The project is a technical preview with buildable code, interoperability tests and published measurements. It is ready for independent engineering evaluation. Production adoption still depends on workload fit, system-level performance and security review.

Version 0.3 adds [atomic epoch binding and independently verified signing](PRODUCTION_READINESS.md), a substantial [output-copy fix with measured evidence](DISPATCH_RESULTS.md), [native CPU/hybrid pipeline measurements](PIPELINE_RESULTS.md), and [cost scenarios for the existing A100/L40S captures](ECONOMICS.md). The pipeline results include verification, queueing and missed deadlines; they do not yet establish a reliable hybrid cost advantage at a 10 ms target. The security record identifies remaining key-isolation, secret-dependent execution and independent-review requirements.

## The opportunity and the decision

The [keys instead of clicks thesis](KEYS_INSTEAD_OF_CLICKS.md) connects machine consumption to publisher compensation: an approved buyer budget funds scoped access, a signed credential supports authorization, and a ledger records publisher accrual for settlement. It sets out the transaction, protocol compatibility requirements and falsifiable tests for demand, security and economics. The commercial hypothesis and the GPU performance hypothesis each need their own evidence.

Applications may need large numbers of signed manifests, authorization grants, receipts or other records. If fresh signatures consume a meaningful share of their CPU budget, GPU assistance could increase available signing capacity or leave CPU resources for other work. That value depends on arrivals, key distribution, deadlines and the rest of the request path; the repository does not yet demonstrate a deployment cost saving.

Machine-authorized content is one application. A publisher could bind licensed access terms and content identity to a signed grant, supporting machine consumption that produces no advertising click. The [content-grant example](MACHINE_AUTHORIZED_CONTENT.md) demonstrates those cryptographic bindings. Identity, payment accounting, enforcement, key release and distribution remain application responsibilities. The business case must also account for caching: content or a grant that can be signed once and reused does not need a new signature for every request.

Publishers, CDNs, storage systems and other infrastructure teams can evaluate the same public engine. Cloudflare is one potential adopter or evaluator; the project has no provider-specific interface or dependency.

| Reader | Decision to make | Evidence available now |
|---|---|---|
| CEO / business leadership | Will buyers pay for useful access, will publishers receive sustainable proceeds, and is acceleration worth its integration cost? | A scoped access thesis and validation plan, primitive and within-SLO pipeline evidence, hardware inventory and cost models; actual demand, payouts and deployment savings remain unproven. |
| CTO / engineering | Does the code fit our stack, traffic, latency budget and CPU–GPU design? | C ABI, Python API, source-level architecture, per-backend batch sweeps and a [heterogeneous systems design](SYSTEMS_DESIGN.md). |
| CSO / security leadership | Can we permit this key residency and execution model, and what assurance is still required? | Documented trust boundary, independent CPU comparisons and validation; secret-dependent GPU behavior and no independent audit. |

The [ES256 compatibility demonstration](COMPATIBILITY.md) supplies a standard token format around the native signatures, with independent PyJWT verification and negative policy tests. This closes a concrete wire-format gap for ES256 consumers. Existing Ed25519 deployments require their current CPU path or an explicitly agreed protocol extension.

## Workload fit

The best current evaluation candidate is a trusted-host service with many independent P-256 signatures, compatible keys and formats, an available NVIDIA GPU, and enough latency budget to collect work. Offline signing and already assembled batches avoid some online fill delay. Bursty online workloads need a bounded wait policy.

An agent's planned access calls offer another evaluation shape: prepare authorized proofs or grants while independent planning continues, serve sparse/urgent work on CPU, and evaluate GPU execution for larger ready groups under the same permitted signer and epoch. Established signing keys are reused according to policy; the optimization is usually preparing signed objects, rather than generating keys for every website. The [agent access design](AGENT_ACCESS_DESIGN.md) separates client proofs from publisher grants, explains dependency and freshness limits, and specifies a fair CPU/hybrid comparison. Several tool calls can also be efficient through ordinary concurrency and credential reuse without GPU signing.

Sparse or urgent signing should begin with the CPU path. CPU also won every sampled AES-GCM and SHA-256 cell in the initial matrix; those GPU implementations are available, but there is no measured case here for moving all cryptography onto the GPU. A requirement that signing keys stay inside an HSM or another hardware-isolated boundary is incompatible with this native host/device key model. RSA and a complete TLS stack are outside this release.

## The numbers that matter

At **batch 256**, the public v0.2 full-window signer recorded the following. Ranges span two runs, each with seven timed calls. Ratios compare each GPU run with its paired CPU baseline, not opposite ends of independent ranges.

| GPU | GPU signatures/s | Mean GPU call completion | CPU signatures/s | Paired GPU/CPU rate |
|---|---:|---:|---:|---:|
| RTX 4070 Ti | 224,742–229,039 | 1.12–1.14 ms | 41,218–44,130 | 5.09–5.56× |
| RTX 3060 | 177,810–194,276 | 1.32–1.44 ms | 40,689–43,358 | 4.10–4.77× |

The host was a Ryzen 7 7800X3D running Windows, CUDA 13.0.88 and MSVC 19.44. The CPU baseline uses one Python thread with cached OpenSSL keys. GPU timing covers the synchronous Python call, packing, transfers, execution, result construction and clearing. Key/table import, batch formation, queueing and independent oracle checks are excluded. This is an API-level comparison; an optimized native multi-core CPU baseline and a complete request-path comparison remain necessary.

Full-window first beat CPU at sampled batch 64 on both cards in both runs; batches 1 and 8 lost. Batch 256 was the most consistent mid-size point in these captures. At 1,024 and 4,096, variability changed the apparent optimum between repeats. The cause has not been isolated. The [full results](P256_RESULTS.md) preserve every run, raw samples, CPU/reference/comb/full-window comparisons, source commits, binary fingerprints and completion accounting.

Earlier work is also published: A100 at **110,200 P-256 signatures/s** and **399,446 AES-GCM seals/s** on 16-byte records in clean 30-second runs, plus L40S scheduler latency and earlier RTX results. These use different executors. The [historical archive](HISTORICAL_BENCHMARKS.md) records settings, sampled correctness and rejected runs. It establishes prior work, not an A100 measurement of this new binary or a ranking against the current RTX results.

## Why CPU and GPU belong in the same design

The CPU handles authorization, message encoding, hashing, key policy, routing and completion processing. Work that is small or urgent can stay on CPU. Compatible signatures can share a GPU call, with the CPU sending 32-byte digests and receiving 64-byte signatures. Reused buffers and public tables avoid rebuilding that state for every batch. Independent verification has its own CPU cost and must be included wherever the application requires it.

Batching shares submission and synchronization costs and exposes independent work to the GPU. CPUs can also benefit from batching and cached keys. The useful comparison is therefore a tuned CPU service against a measured CPU–GPU service with the same semantics and checks.

The collection delay can reverse an attractive library result. At 100,000 compatible arrivals/s, filling 256 items adds approximately **1.275 ms average wait** in a simple evenly spaced, no-timeout model. At 1,000 compatible arrivals/s, it adds **127.5 ms**, before the roughly 1.1 ms call. Aggregate traffic is insufficient: 100,000 requests/s spread evenly across 100 incompatible keys gives the latter rate per key. These are calculated illustrations, not measured request latency.

The [systems design](SYSTEMS_DESIGN.md) lays out CPU and GPU responsibilities, size/timeout routing, key epochs, bounded queues, multi-device dispatch, bottleneck accounting and cost per successful operation. The separate native benchmark executes a bounded in-process CPU/hybrid pipeline. Its first three captures are qualified as shared-host diagnostic data after background GPU work was discovered. The [RTX 3060 follow-up](RTX3060_PIPELINE.md) adds explicit selected-device preflight, host telemetry, reversed-order repeats, longer key-distribution checks and a 50 ms deadline control. Its sixteen-key hybrid run signed entirely on CPU, an example of why actual routing and compatible traffic matter. A production network service remains outside this release.

## Code and assurance an evaluator can inspect

Start at the [execution engine](../src/engine/crypto_engine.cu), [device runtime](../src/engine/runtime.hpp), [C ABI implementation](../src/abi/batchcrypto_abi.cpp) and [public header](../include/batchcrypto.h). The [P-256 backend](P256.md) includes working reference, comb and full-window paths, checked-in tables and a generator. The [C consumer](../examples/c_api.c) exercises the exported ABI directly. The repo builds independently of its selected private origins; [EXTRACTION.json](../EXTRACTION.json) and [NOTICE](../NOTICE) record attribution.

The v0.3 regression suite passed independently on RTX 4070 Ti and RTX 3060, including required epochs and fail-closed verification. All 4,479 table points matched OpenSSL; the preserved v0.2 campaign checked 523,104 GPU signatures across timed and warm-up calls. The C consumer passed a limited Compute Sanitizer check. Hosted CI verifies CPU behavior, native CPU compilation, tables and recorded evidence; it does not run CUDA tests. [Validation](VALIDATION.md) describes the exact coverage.

Keys are present in host and device memory, and GPU arithmetic/table accesses have secret-dependent behavior. Correct outputs do not establish side-channel resistance or hardware key isolation. There is no independent audit or production-security certification. The [security scope](../SECURITY.md) makes these constraints explicit for review.

## A bounded next evaluation

Choose a representative workload, latency target, required verification policy and success criteria first. Compare an optimized native multi-core CPU service with the hybrid design under the same arrivals and key distribution. Measure correctly completed requests within the target, p50/p95/p99 latency, CPU/GPU resource use, rejected and late work, and total allocated cost. Exercise rotation, overload and failure handling.

A positive decision requires an acceptable security model and a whole-system benefit at the required latency and cost. The current repository gives engineers code and evidence to investigate that decision; application economics and deployment readiness remain outcomes to establish.
