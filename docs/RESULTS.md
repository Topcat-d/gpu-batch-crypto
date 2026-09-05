# Initial v0.1 results — September 4, 2026

This page preserves the initial v0.1 standalone library measurements using the reference signer. Version 0.2 adds [selectable P-256 table backends](P256.md) with [their own measurements](P256_RESULTS.md). See [historical A100, L40S and RTX benchmarks](HISTORICAL_BENCHMARKS.md) for the earlier engine work, and [batch sizes and latency](BATCHING.md) for interpretation across cards and payloads.

Large P-256 signing batches outperform this single-thread CPU reference. AES-GCM, SHA-256 and small signing batches do not. These results describe the recorded v0.1 standalone public implementation, not historical Smoke binaries or a complete machine-access service.

## Primary measurements

Each workload uses its own runtime, warmed once and reused for three measured calls. The host is an AMD Ryzen 7 7800X3D, running Windows, CUDA 13.0.88, MSVC 19.44.35217, NVIDIA driver 610.62, Python 3.12.14, cryptography 50.0.1 and OpenSSL 4.0.2. Native architectures are 86 and 89.

Measured source commit: `5be20d805f406e2808ae93ddcb2147167bf6ec28`. The compiler version comes from the CMake compiler record; the optional `nvcc` PATH probe was unavailable. Each JSON includes source hashes and the native binary hash.

| Dataset | Measured rows | Unsupported cells | Checked GPU items including warmup | Errors |
|---|---:|---:|---:|---:|
| [RTX 4070 Ti](../benchmarks/results/rtx4070ti-isolated-2026-09-04.json) | 186 | 9 | 46,468 | 0 |
| [RTX 3060](../benchmarks/results/rtx3060-isolated-2026-09-04.json) | 186 | 9 | 46,468 | 0 |

Each dataset has 93 matched CPU/GPU workload pairs. Unsupported cells exceed the documented 64 MiB per-call working-data cap. Every measured output was checked outside timing.

## P-256 ECDSA signing

Rates count 32-byte digest signatures. GPU/CPU is the ratio of operation rates, using the CPU measurement from the same run.

| GPU | Batch | GPU signatures/s | CPU signatures/s | GPU/CPU | Mean GPU batch duration |
|---|---:|---:|---:|---:|---:|
| RTX 4070 Ti | 1 | 205 | 27,523 | 0.01× | 4.87 ms |
| RTX 4070 Ti | 8 | 1,049 | 30,872 | 0.03× | 7.63 ms |
| RTX 4070 Ti | 64 | 8,182 | 43,521 | 0.19× | 7.82 ms |
| RTX 4070 Ti | 256 | 32,177 | 37,377 | 0.86× | 7.96 ms |
| RTX 4070 Ti | 1,024 | 110,956 | 42,300 | 2.62× | 9.23 ms |
| RTX 4070 Ti | 4,096 | 160,455 | 40,543 | 3.96× | 25.53 ms |
| RTX 3060 | 1 | 189 | 27,726 | 0.01× | 5.30 ms |
| RTX 3060 | 8 | 969 | 33,642 | 0.03× | 8.26 ms |
| RTX 3060 | 64 | 7,632 | 40,119 | 0.19× | 8.39 ms |
| RTX 3060 | 256 | 28,920 | 34,901 | 0.83× | 8.85 ms |
| RTX 3060 | 1,024 | 100,741 | 41,866 | 2.41× | 10.16 ms |
| RTX 3060 | 4,096 | 153,452 | 39,079 | 3.93× | 26.69 ms |

The first winning sampled batch is 1,024 on both cards. The exact crossover was not measured. Batch collection and network delay are absent; throughput at batch 4,096 is not a promise of low per-request latency.

## Content operations

The CPU reference won every AES seal/open and SHA-256 cell on both GPUs. As one representative larger-content comparison, below are 64 KiB records at batch 256. MB/s uses decimal bytes; AES counts plaintext bytes, excluding AAD and tags.

| GPU | Operation | GPU MB/s | CPU MB/s | GPU/CPU |
|---|---|---:|---:|---:|
| RTX 4070 Ti | aes256gcm_seal | 105.35 | 2,629.26 | 0.04× |
| RTX 4070 Ti | aes256gcm_open | 104.17 | 2,816.81 | 0.04× |
| RTX 4070 Ti | sha256 | 1,121.45 | 2,384.89 | 0.47× |
| RTX 3060 | aes256gcm_seal | 78.28 | 2,552.38 | 0.03× |
| RTX 3060 | aes256gcm_open | 77.04 | 2,678.70 | 0.03× |
| RTX 3060 | sha256 | 845.96 | 2,349.97 | 0.36× |

This implementation uses a generic per-record GPU execution path. These numbers do not establish the limit of GPU AES or hashing; they do establish that this release provides no measured advantage for those operations against the stated baseline.

## Prior shared-runtime measurements

The first runs reused a single runtime across different workload sizes. Retained large buffers increased clearing work for later smaller cells. They are preserved for transparency, but are not pooled with the primary isolated-cell results:

- [RTX 4070 Ti, shared runtime](../benchmarks/results/rtx4070ti-2026-09-04.json)
- [RTX 3060, shared runtime](../benchmarks/results/rtx3060-2026-09-04.json)

Those runs used source commit `0964f2f213c60a9e3e056a9d518126c13bf0522d`. Native library and Python API code are unchanged between the two measured commits; the harness context policy changed. Retained capacity is relevant for mixed-size application workloads, so neither condition substitutes for testing actual traffic.

## Reproduce and interpret

See [methodology](BENCHMARKS.md) for the command, exact timing boundaries and CPU baseline. Source commits are retained in this repository history. `python benchmarks/verify_results.py` checks measured-source hashes, row uniqueness, timing arithmetic and accounting. [SHA256SUMS](../benchmarks/results/SHA256SUMS) identifies the published JSON bytes. This check validates records; it does not rerun the benchmark.

These are three-sample local measurements with warmed buffers, not confidence intervals, independent replication, p99 service latency, power/cost measurements, an optimized multi-core CPU comparison or a side-channel assessment. GPU results have been validated locally on two cards; hosted CI checks CPU behavior and record integrity.
