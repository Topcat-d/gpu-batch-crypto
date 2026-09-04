# GPU batch cryptography for machine-authorized content

## Engineering note

Publishers need ways to earn from machine access to their work even when that access never produces an advertising click. Our contribution is a small, independent Apache-2.0 cryptography engine that lets others experiment with the cryptographic costs of that model: hash content, encrypt it with authenticated metadata, and sign grants or records in batches.

Cloudflare already documents [Pay per crawl](https://developers.cloudflare.com/ai-crawl-control/features/pay-per-crawl/what-is-pay-per-crawl/), including an HTTP 402 payment flow. The question here is narrower: where a machine-access design requires many independently verifiable signed records, can batching reduce the signing cost enough to be useful within its latency budget?

## What is available

[GPU Batch Crypto](https://github.com/Topcat-d/gpu-batch-crypto) includes an independently buildable CUDA library with a versioned C ABI, Python bindings, reusable device buffers, streams, key slots and key epochs. It supports variable-length SHA-256, AES-256-GCM encryption/decryption with associated data, and deterministic P-256 ECDSA signing. Standard-library-backed CPU paths supply verification, key generation, interoperability checks and a comparison baseline.

P-256 is the curve used by ECDSA. Those signatures authenticate a manifest or grant; AES-GCM protects the content and associated metadata. RSA would be an alternative for a protocol that specifically requires it and is outside this release.

The [content-grant example](../examples/content_grant.py) binds synthetic content to publisher, principal, content identity/version and validity times. It demonstrates GPU generation and independent CPU consumption, including signature, content-hash and authenticated-decryption checks. It is a working cryptographic example; payment settlement, identity enrollment, trusted key distribution, revocation, key release and network enforcement remain application responsibilities. A recipient who receives plaintext can still copy it.

## Fresh measurements

On an AMD Ryzen 7 7800X3D host, the current public implementation achieved:

| P-256 signing, batch 4,096 | GPU signatures/s | CPU reference signatures/s | GPU/CPU |
|---|---:|---:|---:|
| RTX 4070 Ti | 160,455 | 40,543 | 3.96× |
| RTX 3060 | 153,452 | 39,079 | 3.93× |

The GPU first exceeded the CPU reference at the sampled batch size 1,024 on both cards; it lost at batch 256 and below. Average measured batch-4,096 call duration was approximately 25.5 ms on the 4070 Ti and 26.7 ms on the 3060, excluding time spent collecting a batch. These are aggregate throughput measurements over three timed calls after warmup, with transfers and buffer clearing included. The CPU reference uses cached cryptography/OpenSSL keys on one Python thread. An optimized native multi-core baseline remains necessary for a deployment comparison.

AES-GCM and SHA-256 were slower than the CPU reference in every measured cell. This release therefore supports an experiment around high-volume signing; it does not establish that moving an entire content-delivery pipeline to a GPU is beneficial. Raw samples, exact source and binary provenance, unsupported cells and the earlier shared-buffer runs are in the [results](RESULTS.md).

## A useful next evaluation

A representative integration would establish whether an individual request needs a fresh signature, whether a signed object can be cached and reused, and whether a CPU or existing key-management service already meets the requirement. For work that really does require independent signatures at volume, the next experiment should replay realistic arrival rates and payload distributions, include batch wait time and transport, compare optimized multi-core CPU execution, and measure p50/p95/p99 latency plus resource cost.

The engine accepts one key per batch. Work from many publishers or principals may fragment batches; queueing by key could add latency. Signing prehashed records can avoid transferring full content to the signer, but that requires the application's trust boundary to permit it. Neither deployment at the edge nor GPU availability there is assumed.

We would welcome engineering feedback on representative signing workloads, acceptable delay, per-publisher key requirements, and whether signed manifests, grants or aggregated records fit a real machine-access flow. That feedback would decide whether the next work should be a scheduler/integration experiment, native CPU comparison, or changes to the cryptographic execution path.

## Readiness

This is a technical preview. Fourteen Python tests passed on each of the two GPUs; the C API consumer passed and a limited Compute Sanitizer check reported no errors. It is not independently audited. The inherited arithmetic has secret-dependent behavior, so it is not presented as a constant-time signer or an HSM replacement. Details are in [validation](VALIDATION.md) and [security scope](../SECURITY.md).

The public repository contains selected generic primitives and the new standalone integration. It carries no private Smoke service architecture or Git history. Cloudflare has not endorsed this project. This note is a draft for discussion, not a claim of integration or partnership.
