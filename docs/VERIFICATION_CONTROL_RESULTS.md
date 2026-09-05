# Separate issuer and consumer verification: measured control

**16 cells, 1,950,464 completed tokens, 752,896 additional issuer-side GPU output checks.** Each token also passed the independent consumer check. The [control plan](../benchmarks/VERIFICATION_CONTROL.md) was committed before this separate measurement, after the original [ready-wave screening](READY_WAVE_RESULTS.md).

CPU ES256 signs and performs one consumer verification. Hybrid ES256 additionally checks every GPU signature on CPU at the issuer before encoding, then performs the separate consumer verification. This represents the default guarded signer followed by a verifying recipient. CPU fallback needs no additional GPU fault guard. Both use the same claims and worker budgets.

The same RTX 3060 and Ryzen 7 7800X3D host were used, with idle selected-GPU preflights and shared-host telemetry. Two repeats use opposite mode order; three seconds per cell. General JWT parsing/claim policy, network/TLS, account/payout services, key setup and warm-up remain outside timing.

## Decision at the declared 50 ms budget

The conservative ratio is slower hybrid repeat / faster eligible CPU repeat, using the better eligible four/eight-worker setting for each. A candidate requires ≥99% of tokens within 50 ms in both repeats and ratio >1.05.

| Wave | CPU / hybrid workers | CPU upper / hybrid lower goodput/s | Ratio | Candidate? |
|---|---|---:|---:|---|
| 256 | 8 / 8 | 57,165 / 32,746 | 0.573 | No |
| 1024 | 8 / 8 | 68,057 / 41,633 | 0.612 | No |

**Candidate settings in this control: 0.** Use this result for the two-check cryptographic path, not the earlier one-check ceiling. Additional common application costs must also be included before sizing a service. These shared-host, finite-run observations are not an exclusive-host capacity certification.

## Every setting and both repeats

| Wave | Mode | Workers | Tokens/s | p99 ms | Within 50 ms | Process CPU s | Both pass? |
|---|---|---:|---:|---:|---:|---:|---|
| 256 | cpu-es256 | 4 | 37,652–38,061 | 10.67–11.69 | 100.00–100.00% | 10.03–10.14 | Yes |
| 256 | hybrid-es256 | 4 | 22,920–23,112 | 14.84–17.66 | 100.00–100.00% | 8.78–8.83 | Yes |
| 256 | cpu-es256 | 8 | 56,572–57,165 | 7.04–7.79 | 100.00–100.00% | 17.38–18.25 | Yes |
| 256 | hybrid-es256 | 8 | 32,746–33,447 | 12.13–13.33 | 100.00–100.00% | 13.86–14.08 | Yes |
| 1024 | cpu-es256 | 4 | 40,574–40,619 | 33.77–34.64 | 100.00–100.00% | 10.50–10.66 | Yes |
| 1024 | hybrid-es256 | 4 | 25,946–27,339 | 48.73–51.20 | 98.70–100.00% | 10.06–10.12 | No |
| 1024 | cpu-es256 | 8 | 59,525–68,057 | 18.97–26.84 | 100.00–100.00% | 17.72–20.50 | Yes |
| 1024 | hybrid-es256 | 8 | 41,633–42,790 | 30.18–38.71 | 100.00–100.00% | 18.88–19.64 | Yes |

A single-check acceptance design is a different application contract: the designated receiver checks every token before authorization or monetary accrual, and failed output must recover without creating a charge. This control does not validate that ledger, networking or fault-recovery implementation. The library's guarded example remains appropriate when a caller needs independently checked signatures before releasing them.

Existing Ed25519 consumers still require their own accepted protocol; ES256 interoperability does not change their contract. Both profiles retain the existing [GPU key-residency and side-channel constraints](PRODUCTION_READINESS.md).

Measured source commit: `39bd2ebfa7bba7875845397c238207a1a1380738`. [Raw capture](../benchmarks/ready_wave_results/rtx3060-verification-2026-09-05.json), [build fingerprints](../benchmarks/ready_wave_build.json), [checksum inventory](../benchmarks/ready_wave_results/SHA256SUMS). Run `python benchmarks/verify_ready_wave.py` and `python benchmarks/report_ready_wave.py --check` with the interop dependencies installed.
