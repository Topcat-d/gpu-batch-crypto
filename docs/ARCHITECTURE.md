# Public GPU cryptography engine

The reusable boundary is cryptographic operations, device execution, buffers, keys, and observable results. Application policy and commercial trust systems remain above that boundary.

## Layers

`C/Python caller → versioned C ABI → per-device runtime → independent CUDA records`

A runtime owns a CUDA stream, six reusable device buffers, sixteen key slots, a mutex and operation counters. A call validates all public shapes, packs host buffers, executes a batch on its stream, obtains results, clears temporary device contents, and returns. Host staging copies are cleared on scope exit. Context destruction releases buffers and clears its resident host key slots.

Each key slot has a kind and monotonically increasing epoch. Import/replace/remove requires the caller's expected epoch. Removal retains the epoch tombstone. The context mutex prevents rotation in the middle of a call; a report binds a batch to the used epoch. These are local engine mechanics, not distributed key management, attestation, durable nonce allocation or proof of deletion.

## API contract

ABI version 1 uses fixed-width counts and status values plus opaque context pointers. C++ exceptions are translated to return codes. CUDA absence/failure never selects CPU. Python has separate `Cpu`, stateless `Cuda`, and owned `Runtime` interfaces.

`bc_create`/`bc_destroy` manage runtimes; `bc_key_put`/`bc_key_remove` manage key generations; `bc_hash`, `bc_seal`, `bc_open`, `bc_sign`, and `bc_export_public_key` operate on the context. Stateless convenience entry points accept caller-owned keys and allocate temporary runtimes.

The native header is the source of truth. Callers must supply valid pointers, sufficient output capacity and non-overlapping buffers. Inputs and counts are bounded before packing/allocation. A batch-level error invalidates every output. On a successful call, inspect each item status; a failed tag returns zeroed plaintext for that item. Host results are only copied after stream work and explicit clearing succeed.

Counters cover calls and successful returned batches: `submitted == completed` for a successfully returned synchronous batch; `item_errors` includes authentication failures. Call-level failures increment `call_errors` but do not claim a precise number of GPU completions on an uncertain CUDA failure. Key import/export and retirement are not data-batch calls. A returned `bc_batch_report` gives counts and key epoch. Counters are diagnostics, not signed financial records.

Explicit batches are bounded at 4,096 operations. The caller chooses when enough work exists to dispatch. One runtime serializes its calls; independent contexts can execute independently on one or several devices. No cross-device load balancer or distributed rotation is included. GPU selection is by CUDA ordinal; applications should establish stable device mapping themselves.

## Memory behavior

Each call is limited to 64 MiB input/output/AAD working bytes, plus bounded metadata. Buffers retain their peak capacity until runtime destruction and are overwritten between calls. Across different shapes retained capacity may exceed one call's 64 MiB limit (at most roughly 193 MiB for the current six-buffer layout); `reserved_device_bytes` makes it visible. Returned output bytes belong to the caller. The library does not keep a plaintext cache.

Memory clearing is best-effort on failed devices and cannot establish physical erasure, register clearing, driver-copy removal, or protection from a host administrator. Key slots contain native host copies. Caller keys and Python immutable byte strings have their own lifetimes.

## Extraction classification

| Category | Treatment |
|---|---|
| Generic AES block/key expansion, GCM field arithmetic, SHA-256 compression, scalar P-256 and deterministic nonce arithmetic | Selected source extracted, attributed and hash-recorded |
| Fixed short-message framing, device dispatch assumptions, product namespaces | Replaced by bounded variable-length records, streamed GCM/AAD and generic names |
| Runtime/slot ownership, stream lifetime, buffer reuse, public reports | Independently scoped generic implementation; no private product format copied |
| Higher-level policy, attestation, evidence, gateway and commercial product systems | Excluded |

The initial signer assigns one scalar implementation to each GPU thread. A more complex signing path did not pass standalone validation and is not included. Historical persistent-engine throughput does not transfer to this execution path. Future optimized paths must pass the same independent vectors and differential tests before they replace it.

The native build includes only local source files and CUDA. `EXTRACTION.json` records selected source provenance; there are no submodules or runtime references to the source repository.
