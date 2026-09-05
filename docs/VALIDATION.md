# Validation record

Local validation on September 4, 2026:

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
