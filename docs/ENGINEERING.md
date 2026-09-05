# GPU Batch Crypto: engine, ABI and batching

## Engineering note

GPU Batch Crypto is a general-purpose Apache-2.0 engine for applications with many independent hashing, authenticated-encryption and signature operations. Its public building blocks are a CUDA execution engine, device runtime, C ABI, Python bindings and P-256 precomputation tables. The project publishes code and measured evidence so infrastructure engineers can evaluate the engine for their own workloads.

Machine-authorized content is one application: publishers may need to earn from machine access that produces no advertising click, with content and access metadata cryptographically bound to a recipient. The same engine can support signed records, integrity checks and other batch workloads. A CDN or infrastructure provider, including Cloudflare, is a potential user or evaluator of this existing public project. The project has no provider-specific integration or product dependency.

## What is available

Start with the [execution engine](../src/engine/crypto_engine.cu), [runtime](../src/engine/runtime.hpp), [ABI implementation](../src/abi/batchcrypto_abi.cpp), and [public C header](../include/batchcrypto.h). The [P-256 backend](../src/p256/fixed_base.cuh) uses the [published tables](../data/p256); the [generator](../tools/generate_p256_tables.py) checks every public point against OpenSSL. These are working native library components, with [the C example](../examples/c_api.c) demonstrating direct use.

[GPU Batch Crypto](https://github.com/Topcat-d/gpu-batch-crypto) includes an independently buildable CUDA library with a versioned C ABI, Python bindings, reusable device buffers, streams, key slots and key epochs. It supports variable-length SHA-256, AES-256-GCM encryption/decryption with associated data, and deterministic P-256 ECDSA signing. CPU paths using cryptography/OpenSSL and hashlib supply verification, key generation, interoperability checks and comparison baselines.

P-256 is the curve used by ECDSA. Those signatures authenticate a manifest or grant; AES-GCM protects the content and associated metadata. RSA would be an alternative for a protocol that specifically requires it and is outside this release.

The [content-grant example](../examples/content_grant.py) binds synthetic content to publisher, principal, content identity/version and validity times. It demonstrates GPU generation and independent CPU consumption, including signature, content-hash and authenticated-decryption checks. It is a working cryptographic example; payment settlement, identity enrollment, trusted key distribution, revocation, key release and network enforcement remain application responsibilities. A recipient who receives plaintext can still copy it.

## Why batching matters

One call per small operation repeatedly pays submission, copying and synchronization overhead and can leave most of the GPU idle. Batching shares those costs and exposes parallel work. It also consumes latency: time collecting a batch, queueing behind other batches, and waiting for the whole call to finish. The right setting depends on the primitive, payload, signing-key distribution, host and GPU.

The public v0.2 full-window signer illustrates this tradeoff: batches 1 and 8 lose to the CPU baseline, batch 64 first wins in the sampled sweep, and batch 256 supplies roughly 225–229K signatures/s on RTX 4070 Ti at about 1.1 ms mean batch completion. Larger batches vary substantially between repeat runs. More work per call does not automatically improve the result. The [comb and full-window implementations](P256.md) are available for inspection and reproduction.

The [batching guide](BATCHING.md) gives per-card and per-payload tables, observed timing ranges, charts and a batch-fill model. It also shows a historical sweep where throughput peaked at 4,096 and fell at larger logical batch sizes. Filling the queue further can cost latency without buying throughput.

## Earlier GPU evidence

| Historical execution path | Recorded result | Evidence boundary |
|---|---|---|
| A100-SXM4-40GB, persistent direct-cgo engine, batch 1,500 | **110,200 P-256 signatures/s** | 30 s; all 3,306,000 submissions completed; sampled oracle 256/256 |
| Same A100, AES-GCM seal | **399,446 operations/s**, 16-byte plaintext | 30 s; 11,983,431 completed; sampled oracle 256/256; host-feed limit reported |
| RTX 4070 Ti / RTX 3060, experimental full-window signer, batch 1,500 | **260,998 / 120,150 signatures/s** | 10 s each; clean counts; sampled oracle 4,096/4,096; different signer from the public release |
| L40S, in-process scheduler, P-256 pack 64 | **13,362/s**, **56.31 ms p99** | Timing includes scheduler queueing; sampled oracle 256/256 |
| L40S, in-process scheduler, P-256 pack 1,500 | **47,972/s**, **214.24 ms p99** | Client/pipeline settings also differ; cannot attribute the whole change to batch size |

The [historical archive](HISTORICAL_BENCHMARKS.md) contains the selected captures, hardware/settings, hash provenance, full latency percentiles and rejected runs. Those paths are not identical to each other or to the current library, so the table is evidence of prior work rather than a GPU ranking. It does not establish an A100 batch optimum: the clean A100 captures lack a batch-size/latency sweep. The AES rate corresponds to 6.39 MB/s of small-record plaintext, not article delivery or payment throughput.

## Public-library measurements

On an AMD Ryzen 7 7800X3D host, the v0.2 full-window implementation recorded the following at batch 256. Ranges span two run means, with seven timed calls per run:

| GPU | Signatures/s | Mean batch completion | CPU reference signatures/s |
|---|---:|---:|---:|
| RTX 4070 Ti | 224,742–229,039 | 1.12–1.14 ms | 41,218–44,130 |
| RTX 3060 | 177,810–194,276 | 1.32–1.44 ms | 40,689–43,358 |

These synchronous Python API timings include packing, transfers, CUDA execution, result construction and clearing, with table/key import and warmup excluded. They also exclude time collecting and queueing a batch. The CPU reference uses cached cryptography/OpenSSL keys on one Python thread. An optimized native multi-core baseline remains necessary for a deployment comparison.

The [full comparison](P256_RESULTS.md) includes reference, comb, full-window and CPU results, both runs' raw samples, and source/binary provenance. Batches 1,024 and 4,096 varied widely and did not produce a consistent optimum. The cause has not been isolated; these local Windows captures do not establish sustained throughput or request p99.

The [initial v0.1 matrix](RESULTS.md) is preserved, including AES-GCM and SHA-256 cells where CPU won throughout. The v0.2 measurements focus on P-256 and establish no new AES/hash speedup. The evidence supports further signing evaluation; it does not establish that an entire content-delivery pipeline benefits from GPU execution.

## A useful next evaluation

A representative integration would establish whether an individual request needs a fresh signature, whether a signed object can be cached and reused, and whether a CPU or existing key-management service already meets the requirement. For work that really does require independent signatures at volume, the next experiment should replay realistic arrival rates and payload distributions, include batch wait time and transport, compare optimized multi-core CPU execution, and measure p50/p95/p99 latency plus resource cost.

The engine accepts one key per batch. Work from many publishers or principals may fragment batches; queueing by key could add latency. Signing prehashed records can avoid transferring full content to the signer, but that requires the application's trust boundary to permit it. Neither deployment at the edge nor GPU availability there is assumed.

We would welcome engineering feedback on representative signing workloads, acceptable delay, per-publisher key requirements, and whether signed manifests, grants or aggregated records fit a real machine-access flow. That feedback would decide whether the next work should be a scheduler/integration experiment, native CPU comparison, or changes to the cryptographic execution path.

## Readiness

This is a technical preview. Seventeen Python tests passed on each of the two GPUs, including all three P-256 backends; all 4,479 public table points matched OpenSSL. The C API consumer passed and a limited Compute Sanitizer check reported no errors. It is not independently audited. The arithmetic and table accesses have secret-dependent behavior, so it is not presented as a constant-time signer or an HSM replacement. Details are in [validation](VALIDATION.md) and [security scope](../SECURITY.md).

The public repository contains selected generic primitives, benchmark evidence and the new standalone integration. It carries no private Smoke service architecture or Git history. This note is for engineering discussion and does not imply endorsement, integration or partnership with a named provider.
