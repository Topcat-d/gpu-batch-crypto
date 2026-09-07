# Record-export capture

The newer [`manifest-api-v1.json`](manifest-api-v1.json) measures the actual
public signed-manifest API against public Merkle receipts and individual
signatures. It contains **96 cells and 39,786 accepted record checks**, plus
separate warm-ups and 100 ms background CPU samples. Measured source commit:
`f09f4708941f16a3fa577a5fd1877b514d84924e`. See its
[predeclared campaign](../MANIFEST_API_CAMPAIGN.md) and
[interpretation](../../docs/MANIFEST_API_RESULTS.md). Validate with
`python benchmarks/report_manifest_api.py --check`.

The older capture below remains unchanged; its hash-list consumer was a
benchmark prototype and has a different profile and validation cost.

[`cpu-record-exports-v1.json`](cpu-record-exports-v1.json) is the complete CPU
campaign at source commit `94503be0da1c7ae8c4f689d7237dcf31818e3fd7`:
234 cells, 46,656 accepted record checks, changed-record rejection in every
cell. Source fingerprints, environment, execution order, per-phase time and
actual serialized metadata size are in the capture.

SHA-256 after normalizing Windows CRLF to LF:
`82bdf9b07e618652bf448e789f0fadd71bb8695964b47cb9c32fb6caa26f5e90`.
This digest identifies the report's input; it is not independent attestation
that the experiment ran or a reproducible-performance guarantee.

The [committed campaign](../RECEIPT_CAMPAIGN.md) declares the three alternatives,
all workloads and boundaries. The 257-record holdout followed the primary sizes
without implementation changes. This was a short shared-host Windows run,
without CPU isolation/load telemetry, network traffic, GPU work or real funds.

```sh
python benchmarks/report_receipts.py --check
python benchmarks/report_receipts.py --input dist/my-record-export-run.json --validate-only
```

The verifier checks historical source blobs, exact schedule, outcomes, signature
counts, phase sums, and separately reconstructed serialized sizes. It also pins
this exact capture before generating the interpreted report. Keep this capture
unchanged; put future runs in new files. See [interpretation and all scenario
medians](../../docs/RECEIPT_RESULTS.md).
