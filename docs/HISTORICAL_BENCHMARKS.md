# Historical A100 and GPU benchmark evidence

The public library grows out of a substantial earlier GPU cryptography effort. This archive makes selected measurements inspectable alongside the new implementation: the A100 runs, L40S latency/throughput records, an experimental RTX signing path, and a large-batch sweep. It contains generic benchmark evidence, with private product code and unrelated diagnostic data omitted.

These are **historical execution paths**, not benchmark runs of the current `batchcrypto` binary. The new library's independently reproducible results are [here](RESULTS.md). Different kernels, host machines, submission paths, workload sizes and completion policies prevent a fair card ranking from these historical rows.

## A100: the recorded runs

July 16, 2026: NVIDIA A100-SXM4-40GB, driver 580.105.08, Ubuntu 22.04.5, CUDA compiler 12.8, Go 1.26.5. The experiment record identifies engine revision prefix `9b33b18` and an `sm_80` build. These are 30-second direct-cgo runs through a persistent engine, batch 1,500, **108 GPU blocks / 108 shards**. The GPU was recorded idle before each run. A short revision and a historical note are not a complete immutable build manifest.

| Operation | Recorded rate | Completed / submitted | Sampled CPU oracle | Capture |
|---|---:|---:|---:|---|
| P-256 signing, 32-byte digest | **110,200 signatures/s** | 3,306,000 / 3,306,000 | 256 / 256 passed | [P-256](../benchmarks/historical/a100-20260716-p256.txt) |
| AES-GCM seal, 16-byte plaintext | **399,446 operations/s** | 11,983,431 / 11,983,431 | 256 / 256 passed | [AES](../benchmarks/historical/a100-20260716-aes.txt) |

The AES figure is **6.39 MB/s of plaintext**, excluding nonce, tag and other overhead. The original run record attributes AES/SHA rates on this host to submission/polling limits. It does not establish the A100's cryptographic ceiling or whole-page encryption rate. P-256's `payload=16` header is a shared harness default; signing consumes a 32-byte digest.

**No request-latency distribution was captured in these two runs.** The mean interval between submit calls or poll calls is not request latency. Batch 1,500 is a tested setting, not an established A100 batch sweet spot. The two primitives also used different queue/drain settings, preserved in their capture headers.

### A100 execution-shape comparison, July 9

An earlier run used driver 610.43.02, CUDA 12.6, Ubuntu 24.04 and a 30-vCPU host. At batch 1,500 with a nominal ten-second window:

| Operation | GPU blocks / shards | Rate | Completion accounting |
|---|---:|---:|---|
| AES-GCM seal | 60 / 60 | 369,596/s | clean |
| AES-GCM seal | 108 / 108 | 456,575/s | clean |
| SHA-256 | 108 / 108 | 471,075/s | clean |
| P-256 sign | 60 / 60 | 96,134/s | **rejected: 12,224 uncompleted submissions** |
| P-256 sign | 108 / 108 | 155,049/s | **rejected: 95,424 uncompleted submissions** |

[Original selected rows](../benchmarks/historical/a100-20260709-shapes.txt). All runs reported 256/256 sampled oracle checks, illustrating why correctness sampling alone is insufficient: completion accounting must pass too. The two rejected rates are excluded from accepted performance claims. The AES shape change also changed the high-water setting; this is not a controlled batch-size sweep. The SHA record does not preserve its exact input length, so no byte-throughput figure is derived.

## L40S: keep throughput and latency from the same run

The July 7 diagnostic runs used an NVIDIA L40S, driver 580.159.04, CUDA 12.8, Ubuntu 24.04.3 and an AMD EPYC 7702 host. The later July 7/8 campaign records a different EPYC 9354 shared host and driver 550.127.05, with engine revision `6aac45c3d82a983d6e2c32c247a13b72354c845f`. These are separate captures; hardware and contention should not be assumed identical across them.

| Capture | Path and batch | Throughput | p50 | p95 | p99 |
|---|---|---:|---:|---:|---:|
| [AES seal, July 7 run 1](../benchmarks/historical/l40s-20260707-aes-r1.txt) | direct cgo, 1,500 | 384,836/s | — | — | — |
| [AES seal, July 7 run 2](../benchmarks/historical/l40s-20260707-aes-r2.txt) | direct cgo, 1,500 | 384,678/s | — | — | — |
| [P-256, later campaign](../benchmarks/historical/l40s-20260708-p256.txt) | direct cgo, 1,500 | 101,024/s | — | — | — |
| [AES seal, July 7](../benchmarks/historical/l40s-20260707-aes-latency.txt) | in-process scheduler, pack 64 | 190,293/s | 2.089 ms | 5.960 ms | 7.341 ms |
| [P-256, July 7](../benchmarks/historical/l40s-20260707-p256-latency.txt) | in-process scheduler, pack 64 | 13,362/s | 39.958 ms | 53.915 ms | 56.311 ms |
| [P-256, later campaign](../benchmarks/historical/l40s-20260708-p256-scheduler.txt) | in-process scheduler, pack 1,500 | 47,972/s | 131.852 ms | 151.905 ms | 214.241 ms |

All six captures report clean accounting and 256/256 sampled oracle checks. AES plaintext is 16 bytes; P-256 digests are 32 bytes. All use 60 blocks / 60 shards. The pack-64 scheduler cases use two clients, pipeline 2 and depth 8; the pack-1,500 case uses four clients, pipeline 1 and depth 60. The throughput gain cannot be attributed to batch size alone.

Scheduler latency measures a frame from submission to observed completion, including queueing in that harness. It excludes network traffic and waiting to collect the frame's inputs. A later summary mixed the 47,972/s throughput with approximately 40/54/56 ms latency from another run. This table follows each original log: **47,972/s belongs with 132/152/214 ms**.

## RTX: experimental full-window signing

| GPU | Batch | Blocks / shards | Duration | Recorded signatures/s | Completed / submitted | Oracle |
|---|---:|---:|---:|---:|---:|---:|
| [RTX 4070 Ti](../benchmarks/historical/rtx4070ti-fullwindow.txt) | 1,500 | 60 / 60 | 10.00 s | **260,998** | 2,610,000 / 2,610,000 | 4,096/4,096 |
| [RTX 3060](../benchmarks/historical/rtx3060-fullwindow.txt) | 1,500 | 28 / 28 | 10.00 s | **120,150** | 1,201,500 / 1,201,500 | 4,096/4,096 |

These captures use an experimental full-window P-256 variant with a dedicated drain thread. The campaign record identifies Windows, CUDA 12.4 and driver 610.62; individual captures lack a timestamp and complete immutable build provenance. The variant was recorded as pending promotion, not the default implementation. These rates show useful prior optimization work, not performance delivered by the new public library. No p50/p95/p99 was recorded for these runs, and batch 1,500 alone does not establish a sweet spot.

## Larger batches can pass the useful point

The [March 17 RTX 4070 Ti sweep](../benchmarks/historical/rtx4070ti-20260317-envelope.json) used a Python submit/poll path, 60 blocks / 60 shards and three iterations. Logical batches above 4,096 were internally chunked.

| Logical batch | Reported mean signatures/s | Mean batch wall time |
|---:|---:|---:|
| 64 | 16,764 | 3.83 ms |
| 256 | 32,469 | 7.92 ms |
| 1,024 | 50,470 | 20.97 ms |
| **4,096** | **73,001** | **58.29 ms** |
| 16,384 | 64,427 | 255.9 ms |
| 65,536 | 65,061 | 1,009.7 ms |
| 131,072 | 65,469 | 2,002.4 ms |

In this sweep, batch 4,096 was the best measured throughput/latency point among the larger batches; increasing to 131,072 added roughly 34× wall time while reducing throughput. It is a historical timing result: the harness checked completion statuses/counts, **not an independent signature oracle**. It is not included among correctness-verified throughput captures. Unvalidated GPU timestamp fields were omitted from the curated JSON; wall-clock fields are retained. Reported means are preserved rather than recomputed as a ratio of means.

## Provenance and limits

The [manifest](../benchmarks/historical/manifest.json) hashes each original source and each public excerpt. Text excerpts retain selected source lines in order; source line numbers identify the selection. Hashes identify bytes, not a trusted timestamp or independent replication. Historical private sources and binaries are not required to build or check the current public library, and are not bundled here.

`python benchmarks/verify_history.py` verifies published hashes, the clean completion/oracle counters, and the two explicitly rejected A100 runs. Some earlier notes reported additional peaks or newer A100 integration results without a matching complete raw capture in the material gathered here. They are not substituted for the captured data. This archive can grow as those records are recovered with their settings and timing boundaries.
