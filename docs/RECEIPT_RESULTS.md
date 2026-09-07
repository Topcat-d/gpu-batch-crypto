# Record-export measurements

A CPU-only experiment found a specific use for portable subset verification.
Merkle receipts reduce producer signing work and keep individual proofs small,
but the simplest signed hash list wins when one recipient consumes a whole
export. Independent recipients still each verify a signature.

**234 measured cells; 46,656 accepted record checks; every cell rejected changed bytes.**

## What to choose

- For a recipient consuming most/all of an export, evaluate one signed hash
  list first. At 1,024 records, shared full consumption took median **7.27 ms**
  and 76,278 metadata bytes, versus Merkle **31.88 ms** and 493,811 bytes.
- For isolated record delivery, a Merkle proof avoids sending all hashes:
  one record from 1,024 used **821 bytes**, versus 63,075 for a signed hash
  list. Individual signing used only 343 bytes. Smaller proofs do not imply
  lower CPU time: the hash list was faster to produce in that one-record case.
- With a quarter of 1,024 records consumed by independent recipients, Merkle
  total time was median **32.73 ms**, versus **47.11 ms** for pre-signing each
  record: 30.5% lower. The conservative throughput ratio was **1.213×**.
  This includes signing the entire export, including unused records.
- At full consumption by independent recipients, Merkle was slower than
  individual signatures (137.63 versus 123.18 ms at 1,024). The full signed
  hash list was larger and slower still. Do not generalize the quarter-use win.
- The untouched 257-record holdout retained a **1.059×** conservative advantage
  over pre-signing each record at quarter/fresh consumption. It did not retain
  an advantage over the signed hash list on that conservative measure (**0.981×**).

## Complete measured totals

Times below are medians in milliseconds for producer + serialization + consumer.
`shared` sends the batch manifest once and reuses a verifier; `fresh` creates
a verifier and supplies the full signed manifest for each record. These are
different recipient workloads, not interchangeable timing modes.

| Batch / phase | Recipient | Consumed | Individual ms | Hash list ms | Merkle ms | Individual / Merkle conservative |
|---|---|---|---:|---:|---:|---:|
| 64 / primary | shared | 1 | 1.699 | 0.268 | 0.306 | 4.755× |
| 64 / primary | shared | 16 | 2.866 | 0.352 | 0.622 | 4.444× |
| 64 / primary | shared | 64 | 6.065 | 0.608 | 1.536 | 3.637× |
| 64 / primary | fresh | 1 | 1.748 | 0.241 | 0.323 | 4.172× |
| 64 / primary | fresh | 16 | 3.061 | 1.844 | 1.870 | 1.074× |
| 64 / primary | fresh | 64 | 6.971 | 6.960 | 6.926 | 0.866× |
| 1024 / primary | shared | 1 | 25.432 | 1.706 | 2.398 | 10.350× |
| 1024 / primary | shared | 256 | 43.200 | 3.256 | 9.717 | 3.858× |
| 1024 / primary | shared | 1024 | 97.603 | 7.274 | 31.883 | 2.539× |
| 1024 / primary | fresh | 1 | 29.455 | 2.524 | 3.302 | 7.032× |
| 1024 / primary | fresh | 256 | 47.106 | 110.109 | 32.734 | 1.213× |
| 1024 / primary | fresh | 1024 | 123.178 | 463.196 | 137.633 | 0.778× |
| 257 / holdout | shared | 1 | 9.945 | 0.969 | 1.285 | 7.203× |
| 257 / holdout | shared | 64 | 13.495 | 1.272 | 3.679 | 2.702× |
| 257 / holdout | shared | 257 | 29.050 | 2.350 | 11.741 | 1.957× |
| 257 / holdout | fresh | 1 | 8.716 | 0.595 | 0.882 | 2.932× |
| 257 / holdout | fresh | 64 | 12.121 | 12.397 | 8.105 | 1.059× |
| 257 / holdout | fresh | 257 | 29.461 | 46.155 | 32.776 | 0.848× |

Conservative = fastest individual-baseline time / slowest Merkle time across
the scenario's repeats. It is a cautious observed-range comparison, not a
statistical confidence interval or population guarantee.

## Scope and reproduction

The [campaign](../benchmarks/RECEIPT_CAMPAIGN.md) was committed before primary
measurement. Sizes 64/1,024 used five repeats; 257 was a three-repeat holdout
with no implementation change in between. All three schemes used the same
cached OpenSSL CPU key and one signing thread, low-s ES256, context/count/index
binding and exact byte hashing. Merkle builds all proofs. No GPU was loaded.

These are already-assembled immutable exports. Pre-signing every record is
an offline-distribution baseline, not the cheapest answer to one live request:
an online issuer could sign just the requested record. Reusable credentials,
trusted transport, signing a whole file and existing provenance systems may
also remove the need for this profile.

Excluded: key generation, fixture creation, waiting to fill a batch, network
and disk I/O, publisher accounting, policy/identity checks and hardware billing.
Metadata bytes are actual serialized test envelopes, excluding record bodies
and transport framing. This was a short shared-host Windows run without CPU
isolation or continuous load telemetry; the ranges do not establish deployment
latency, a tuned multicore baseline, customer demand or whole-system ROI.

Source commit: `94503be0da1c7ae8c4f689d7237dcf31818e3fd7`. Environment: Python 3.12.14, cryptography 50.0.1, OpenSSL 4.0.2 25 Aug 2026; 16 logical CPUs; AMD64 Family 25 Model 97 Stepping 2, AuthenticAMD; Windows-11-10.0.26200-SP0.

[Raw capture and provenance](../benchmarks/receipt_results/README.md) retains
every cell, phase duration, metadata size and execution order. The standard
library verifier checks historical source fingerprints, the complete declared
schedule, work counts, phase sums and independently reconstructed wire sizes.

```sh
python benchmarks/run_receipts.py --output dist/my-record-export-run.json
python benchmarks/report_receipts.py --check
```

The committed report describes the committed capture. A new capture's row
validation can be run with `--input`; do not apply the narrative's measured
values to another capture without reviewing and updating the interpretation.

[Try the API and detached-file consumer](RECORD_RECEIPTS.md) · [Product hypothesis and ownership](PRODUCT_BRIEF.md)
