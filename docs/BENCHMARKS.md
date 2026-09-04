# Reproducible performance measurement

Use `benchmarks/run_matrix.py` after committing the source. It records an immutable source commit, source hashes, binary hash, GPU/driver, CUDA/compiler/build information, CPU and software versions, batch sizes, payload sizes, every timing sample, and correctness results.

Default AES seal/open and SHA-256 payloads: 16 B, 512 B, 1 KiB, 4 KiB, 16 KiB, 64 KiB, 256 KiB, and 1 MiB. Default batches: 1, 8, 64 and 256. P-256 adds batches 1,024 and 4,096. Cells exceeding the public 64 MiB working-data cap are recorded as unsupported instead of silently clamped. AES AAD is 12 bytes in this matrix; broader AAD shapes are covered by correctness tests.

Each cell has one untimed warmup and three measured iterations by default. CPU/GPU order alternates. Keys are imported before timing and runtime buffers are reused. Timings include the synchronous Python public call, record packing, host/device copies, CUDA execution, synchronization, result materialization and temporary-buffer clearing. Input generation and output comparison are outside timing. Every output is compared, and GPU batch accounting must be clean.

The current harness creates a separate runtime for each workload cell and reuses its buffers across warmup and measured iterations. This prevents a preceding large workload's retained buffer capacity from affecting a later small workload's clearing cost. Runtime creation, key import and initial warmup allocation are outside timing. The first shared-runtime matrices are retained as prior measurements, explicitly distinguished from the primary isolated-cell matrices in [results](RESULTS.md).

The CPU baseline is one Python thread calling cryptography/OpenSSL with cached AES/P-256 key objects and hashlib for SHA-256. It is a useful API-level baseline, not an optimized native multi-core engine or a complete server. AES/curve hardware acceleration depends on that library build and CPU. Results should not be generalized into a fleet comparison.

Rates use total operations divided by total elapsed measured time. AES reports both operations/s and useful plaintext bytes/s. SHA reports input bytes/s. Samples are batch completion latency under available work, not request p99 or a realistic arrival process. Three samples characterize a first local measurement, not confidence intervals or long-run reliability.

Fresh result JSON belongs under `benchmarks/results/`. Historical results from the source project are separate motivation only. Changes to the public execution path require new measurements. Do not claim a GPU speedup from a raw kernel number compared with an end-to-end CPU number, or from a historical binary that this repository does not build.

Standards used by the correctness suite: [NIST GCM specification](https://csrc.nist.gov/pubs/sp/800/38/d/final) and [RFC 6979, including the P-256 sample vector](https://www.rfc-editor.org/rfc/rfc6979). These references define algorithms; the project is not a NIST-certified implementation.
