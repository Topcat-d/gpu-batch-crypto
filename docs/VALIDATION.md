# Validation record

Version 0.3, September 5, 2026:

- The component-adoption pass adds [CPU/GPU/token/access-book entry points](GETTING_STARTED.md)
  and [per-component contracts](COMPONENTS.md). A freshly built Python wheel was
  installed into a separate Windows Python 3.12 environment using the bundled
  CPU cryptography dependency. `python -I` ran the copied consumer outside the
  checkout with native library loading blocked and PyJWT absent; CPU hashing,
  AES, signing/verification and ES256 construction passed. Wheel contents and
  mandatory dependencies were checked. The CI packaging jobs exercise clean
  Python 3.10/3.12 environments before and after adding the optional `interop` extra.
- A C-only consumer was copied outside the repository, configured through the
  installed `batchcrypto::batchcrypto` target, compiled with MSVC 19.44 and passed
  its SHA-256 known-answer/accounting check on RTX 3060 (device 1). This confirms
  the tested Windows SDK consumption path without a CUDA-language consumer
  project; it is not validation of a Linux CUDA build.
- The minimal guarded GPU example returned 256 independently verified signatures
  and retired its synthetic key. CPU, ES256 and access-book entry points passed,
  along with all **56 local regression tests** with the RTX 3060 selected. These
  are adoption/correctness checks, not new performance measurements or an audit.

- The RTX 3060 follow-up passed **29 tests** on device 1, including the four capture/preflight checks and all native CUDA tests. Its **32 new pipeline rows** offered 15,200,000 requests and independently verified 12,167,746 completions with zero verification/processing failures. Expired and late requests remain separate and prevent a blanket success claim. [Repeat results, telemetry and deadline quality](RTX3060_PIPELINE.md).

- Twenty-three tests passed on each RTX GPU after adding bounded-iterable consumption, epoch-bound sign/seal/open (including empty and retired slots), independently verified signing and controlled corrupt/truncated/reordered/wrong-epoch output cases. Two additional CPU cost-model tests check unit conversion, idle allocation and invalid inputs.
- The updated C consumer passed, including stale-epoch output sentinels and successful use of a replacement generation. CUDA Compute Sanitizer memcheck reported **0 errors** for that C consumer. This remains limited coverage.
- Hosted Linux CI passed the Python CPU suite and a native C++ OpenSSL 3.5.8 build/self-test and small CPU pipeline run at source `b1ae0d8`. Subsequent CI also checks the new published capture arithmetic and provenance; CI never claims GPU execution.
- The native pipeline validates every warm-up GPU signature against deterministic OpenSSL output, then independently verifies every completed signature inside timed execution. The first three captures are qualified as **shared-host diagnostic evidence** after background GPU work was discovered. Correctness and accounting checks do not turn them into isolated capacity or cost evidence.
- [Production readiness](PRODUCTION_READINESS.md) records implemented protections and the remaining security work. [Build fingerprints](../benchmarks/pipeline_build.json), [pipeline conditions](../benchmarks/pipeline_conditions.json) and [results](PIPELINE_RESULTS.md) preserve the distinction between executed validation and deployment claims.

Earlier v0.2 validation on September 4, 2026:

- CUDA 13.0.88, MSVC 19.44.35217, Release build, native architectures 86 and 89.
- NVIDIA RTX 4070 Ti and RTX 3060, driver 610.62, Windows.
- Python 3.12.14, cryptography 50.0.1. Benchmark JSON records the actual runtime/toolchain metadata for the measured runs.
- Seventeen Python tests passed independently on each GPU. Coverage includes all three primitives, empty and boundary sizes, 1 MiB content, 64 KiB AAD, altered ciphertext/tag/AAD, wrong keys, invalid lengths, explicit zeroed native output after failed authentication, unavailable devices, independent contexts, compare-and-swap rotation, retirement tombstones, standard signatures and the content-grant flow.
- Reference, comb and full-window signing match deterministic OpenSSL output. Table-backend tests also cover high scalars, signed-digit boundaries in every byte window, the final carry, random scalars/digests, public-key equivalence, backend switching, memory reuse and 4,096-item batches.
- All 4,479 public table points were regenerated and independently compared with OpenSSL public-key derivation; binary, metadata and fingerprint comparisons pass.
- The C consumer compiles as C and passes through the exported ABI, including backend selection, public-key export and equivalent signatures in all three modes.
- NVIDIA Compute Sanitizer memcheck reported zero errors for the C API smoke test. This is a limited smoke check, not a complete sanitizer run over every shape or concurrency condition.
- The Python wheel and native install layout build successfully.
- Source-boundary checks confirm every local native include resolves within this repo and every attributed extract matches its manifest hash.

The CPU-only suite skips CUDA-specific checks. Hosted CI is labeled accordingly; it does not establish a Linux CUDA build or GPU acceptance. Linux packaging and CUDA execution on other toolchains remain unverified locally.

Test commands are in README.md. Known vectors, randomized differential comparisons and interoperability tests are correctness evidence, not a side-channel audit or production-security certification.
