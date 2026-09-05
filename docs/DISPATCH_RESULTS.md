# Output materialization and batch size

The Python wrappers previously accessed a `ctypes` output buffer's `.raw` property inside the per-record result comprehension. Each access copies the entire buffer. Returning `B` results therefore copied the full `B`-record buffer `B` times. Version 0.3 materializes that buffer once and slices the resulting bytes, removing this avoidable quadratic copying from signing and hashing output construction.

This explains a concrete part of the large-batch cost in the earlier measurements. It does not make every source of run-to-run variability disappear.

## Controlled before/after capture

September 5, 2026; same Windows host, driver, CUDA DLL and benchmark harness. One complete sweep before and one after per card; seven timed calls per cell. Every measured output was compared with deterministic OpenSSL output outside timing. Source commits distinguish the wrapper change; all four captures use the same native DLL SHA-256 `cc3d35c7ad4dcf11494be2d6615b222b82390f32235987742bb76ff58218d803`.

| GPU, full-window P-256, batch 4,096 | Before signatures/s | After signatures/s | Before mean call | After mean call | Paired rate change |
|---|---:|---:|---:|---:|---:|
| RTX 4070 Ti | 195,603 | 1,821,543 | 20.94 ms | 2.25 ms | 9.31× |
| RTX 3060 | 183,581 | 1,364,320 | 22.31 ms | 3.00 ms | 7.43× |

Before: `0a56cd1`; after: `9a87097`. Native binary and native source remain the v0.2 implementation. The new v0.3 epoch API build is separately fingerprinted in the pipeline results; it is not substituted into this controlled comparison.

The captures include batches 1, 8, 64, 256, 1,024 and 4,096 across CPU, reference, comb and full-window paths: **96 total rows**, preserving every timing sample and correctness/accounting counter. These short captures establish the observed change, not a sustained service capacity guarantee or an independently replicated speedup. [Raw records and checksums](../benchmarks/dispatch_results).

```sh
python benchmarks/verify_p256_results.py --directory dispatch_results
```

The original [v0.2 captures](P256_RESULTS.md) remain unchanged. Their batch-256 recommendation described the old wrapper and cannot be promoted to a universal hardware sweet spot. The faster batch-4,096 library call still excludes batch-fill wait and CPU signature verification. For an online request deadline, the **whole pipeline** can prefer a much smaller batch; see [pipeline results](PIPELINE_RESULTS.md).
