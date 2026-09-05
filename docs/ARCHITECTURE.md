# Public GPU cryptography engine

The reusable boundary is cryptographic operations, device execution, buffers, keys, and observable results. Application policy and commercial trust systems remain above that boundary.

For adoption, start with the [component contracts and dependency map](COMPONENTS.md)
and [runnable entry points](GETTING_STARTED.md). The Python wheel, installed native
SDK, public table data and source-only evaluation applications have distinct
delivery boundaries. The engine/ABI/runtime source layers below form one native
library; they are not independently packaged services.

This page describes the implemented library. The [CPU–GPU systems design](SYSTEMS_DESIGN.md) explains how an adopter could combine it with CPU preparation, explicit routing, timed queues and completion processing, and which of those service components remain to be built and measured.

## Layers

`C/Python caller → versioned C ABI → per-device runtime → independent CUDA records`

A runtime owns a CUDA stream, six reusable work buffers, up to two public P-256 table buffers, sixteen key slots, a mutex and operation counters. A call validates all public shapes, packs host buffers, executes a batch on its stream, obtains results, clears temporary device contents, and returns. Host staging copies are cleared on scope exit. Context destruction releases buffers and clears its resident host key slots.

The [ABI implementation](../src/abi/batchcrypto_abi.cpp), [execution engine](../src/engine/crypto_engine.cu), [device runtime](../src/engine/runtime.hpp), [CUDA kernels](../src/kernels/crypto_kernels.cuh) and [P-256 fixed-base backend](../src/p256/fixed_base.cuh) are separate source components. Applications consume the [public C header](../include/batchcrypto.h) or Python bindings.

Each key slot has a kind and monotonically increasing epoch. Import/replace/remove requires the caller's expected epoch. Removal retains the epoch tombstone. The context mutex prevents rotation in the middle of a call; a report binds a batch to the used epoch. These are local engine mechanics, not distributed key management, attestation, durable nonce allocation or proof of deletion.

Version 0.3 adds `bc_sign_at_epoch`, `bc_seal_at_epoch` and `bc_open_at_epoch`. The required epoch is checked under that same native mutex before execution. Mismatches leave outputs untouched and report zero submitted/completed items. `Runtime` exposes the optional `expected_epoch` keyword; legacy calls continue to use the slot's current generation. The additive functions retain ABI version 1.

The separate [VerifiedSigner](../python/batchcrypto/verified.py) owns a runtime, pins a CPU-derived public key and independently verifies every signature before returning a complete batch. Epochs are mandatory on its sign requests. This guard requires v0.3 and quarantines itself on backend/output faults. See [production security](PRODUCTION_READINESS.md).

## API contract

ABI version 1 uses fixed-width counts and status values plus opaque context pointers. C++ exceptions are translated to return codes. CUDA absence/failure never selects CPU. Python has separate `Cpu`, stateless `Cuda`, and owned `Runtime` interfaces.

`bc_create`/`bc_destroy` manage runtimes; `bc_key_put`/`bc_key_remove` manage key generations; `bc_hash`, `bc_seal`, `bc_open`, `bc_sign`, and `bc_export_public_key` operate on the context. Stateless convenience entry points accept caller-owned keys and allocate temporary runtimes.

`bc_set_p256_backend`/`bc_get_p256_backend` select or inspect reference, comb or full-window execution. Selection affects signing and public-key export, serializes on the context mutex, and does not change key epochs. These additive functions require native v0.2 while retaining ABI version 1; Python v0.2 requires that native version. See [table layouts and API selection](P256.md).

The native header is the source of truth. Callers must supply valid pointers, sufficient output capacity and non-overlapping buffers. Inputs and counts are bounded before packing/allocation. A batch-level error invalidates every output. On a successful call, inspect each item status; a failed tag returns zeroed plaintext for that item. Host results are only copied after stream work and explicit clearing succeed.

Counters cover calls and successful returned batches: `submitted == completed` for a successfully returned synchronous batch; `item_errors` includes authentication failures. Call-level failures increment `call_errors` but do not claim a precise number of GPU completions on an uncertain CUDA failure. Key import/export and retirement are not data-batch calls. A returned `bc_batch_report` gives counts and key epoch. Counters are diagnostics, not signed financial records.

Explicit batches are bounded at 4,096 operations. The caller chooses when enough work exists to dispatch. One runtime serializes its calls; independent contexts can execute independently on one or several devices. No cross-device load balancer or distributed rotation is included. GPU selection is by CUDA ordinal; applications should establish stable device mapping themselves.

## Memory behavior

Each call is limited to 64 MiB input/output/AAD working bytes, plus bounded metadata. Buffers retain their peak capacity until runtime destruction and are overwritten between calls. Across different shapes retained capacity may exceed one call's 64 MiB limit (at most roughly 193 MiB for the current six-buffer layout); `reserved_device_bytes` makes it visible. Returned output bytes belong to the caller. The library does not keep a plaintext cache.

Public table buffers add 16,320 bytes for comb and 270,336 bytes for full-window when first selected. Both allocations remain if both modes have been used, including after switching back to reference. They hold public constants and are reused without per-call clearing. Their memory is included in the same reserved-byte counter.

Memory clearing is best-effort on failed devices and cannot establish physical erasure, register clearing, driver-copy removal, or protection from a host administrator. Key slots contain native host copies. Caller keys and Python immutable byte strings have their own lifetimes.

## Extraction classification

| Category | Treatment |
|---|---|
| Generic AES block/key expansion, GCM field arithmetic, SHA-256 compression, scalar P-256 and deterministic nonce arithmetic | Selected source extracted, attributed and hash-recorded |
| P-256 table-generation arithmetic and full-window generator | Selected and adapted, with generic binary headers and independent verification of every public point |
| Fixed short-message framing, device dispatch assumptions, product namespaces | Replaced by bounded variable-length records, streamed GCM/AAD and generic names |
| Runtime/slot ownership, stream lifetime, buffer reuse, public reports | Independently scoped generic implementation; no private product format copied |
| Higher-level policy, attestation, evidence, gateway and commercial product systems | Excluded |

The signer assigns an independent signature to each GPU thread. Version 0.2 adds working comb and full-window multiplication around the same validated scalar arithmetic. All three modes pass the independent vectors and differential tests; reference remains the default. The earlier cooperative/persistent signing executor is not included. Historical persistent-engine throughput does not transfer to these synchronous paths, which require their own measurements.

The native build includes only local source files and CUDA. `EXTRACTION.json` records selected source provenance; there are no submodules or runtime references to the source repository.
