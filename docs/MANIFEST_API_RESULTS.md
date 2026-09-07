# Signed-manifest public API measurements

**96 measured cells, 39,786 accepted record checks.** Every measured cell also rejected changed bytes. Three seven-record warm-ups are retained separately.

## Decision

Use the signed hash-list API as an option for one recipient consuming a large
part of an immutable export. Open it once and reuse the verified digest list.

At 1,024 records with full/shared consumption, total median time was **9.543 ms** for the public manifest API, **32.670 ms** for Merkle receipts and **95.115 ms** for individually pre-signed records. The manifest used **76,306 metadata bytes**, versus **493,811** for Merkle receipts.

The observed min-Merkle/max-manifest throughput ratio was **2.679×**; the unchanged 257-record holdout gave **2.782×**. These ratios compare observed extremes, not statistical confidence intervals.

Separate recipients cannot share the validation work. At 1,024/full/fresh the manifest took **1693.842 ms**, Merkle **122.702 ms**, and individual signatures **110.962 ms**. Do not distribute a full hash list with every independent record by default.

## All scenarios

Total includes producer hashing/signing, metadata encoding, and consumer
decoding/verification. Medians in milliseconds; each producer seals the entire
export, including unused records. Fresh means one separately initialized
recipient per record; shared means one recipient and one manifest transfer.

| Batch / phase | Consumed / recipient | Individual | Public manifest | Merkle |
|---|---|---:|---:|---:|
| 1024 / primary | 1 / fresh | 25.315 | 3.294 | 2.635 |
| 1024 / primary | 256 / fresh | 46.301 | 423.147 | 31.230 |
| 1024 / primary | 1024 / shared | 95.115 | 9.543 | 32.670 |
| 1024 / primary | 1024 / fresh | 110.962 | 1693.842 | 122.702 |
| 257 / holdout | 1 / fresh | 6.407 | 0.980 | 0.930 |
| 257 / holdout | 64 / fresh | 11.508 | 31.961 | 7.613 |
| 257 / holdout | 257 / shared | 25.160 | 2.310 | 7.961 |
| 257 / holdout | 257 / fresh | 27.423 | 123.074 | 28.856 |

## What changed from the prototype

The [previous comparison](RECEIPT_RESULTS.md) used a benchmark-only hash-list
consumer. This capture calls the public `seal_manifest`, `open_manifest` and
`verify_record` APIs. Opening validates every hash entry, including entries a
recipient never requests. The format has its own profile and strict bounds.
Its performance must not be inferred from the earlier prototype's numbers.

The adapter uses the same JSON index framing as the controls. Shared delivery
actually sends/parses the manifest once; fresh delivery includes it each time.
Raw captures retain producer, encoding and consumer phases and exact byte
counts. The new `verify_all` count/order contract is tested separately; these
timings use per-record verification with the caller's expected indices.

## Scope and reproduction

The [campaign](../benchmarks/MANIFEST_API_CAMPAIGN.md) was committed before
primary measurement: 1,024 records/five repeats, then 257/three repeats without
changes. Same cached OpenSSL CPU signing key, one thread, already-ready records,
low-s ES256 and expected context/count/index. No GPU work or external service.

Environment: **AMD Ryzen 7 7800X3D 8-Core Processor**, 16 logical CPUs, Windows-11-10.0.26200-SP0; Python 3.12.14, cryptography 50.0.1, OpenSSL 4.0.2 25 Aug 2026.

Before each three-scheme comparison, 100 ms aggregate CPU samples ranged **0.9–65.6%** across the campaign. This is background-load context, not CPU isolation or continuous attribution. Retain the observed ranges; do not treat this short shared-host run as a deployment guarantee.

Excluded: key/fixture creation, record arrival/batch-fill delay, network/disk
I/O, transport headers, identity/permission/accounting policy and hardware cost.
Metadata sizes exclude record bodies. An online issuer signing only requested
records is a different, potentially cheaper baseline. No customer demand or
whole-system ROI is established.

Source: `f09f4708941f16a3fa577a5fd1877b514d84924e`. [Raw capture](../benchmarks/receipt_results/manifest-api-v1.json) includes all cells, CPU counters, warm-ups and source fingerprints.

```sh
python benchmarks/run_manifest_api.py --output dist/my-manifest-run.json
python benchmarks/report_manifest_api.py --check
python benchmarks/report_manifest_api.py --input dist/my-manifest-run.json --validate-only
```

The standard-library verifier checks source history, the complete schedule,
work counts, phase sums, independent wire-size reconstruction and CPU samples.

[Use the API and choose a format](RECORD_MANIFESTS.md) · [Product contract](PRODUCT_BRIEF.md)
