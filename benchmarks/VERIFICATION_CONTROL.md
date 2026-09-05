# Separate issuer guard and consumer verification control

Declared September 5, 2026 after observing part of the first ready-wave
campaign, before running this control. Preserve the original 84-cell campaign.

The original benchmark includes one authoritative CPU verification per token.
That represents a service that accepts/bills a transaction only after that
check. It can also represent the cryptographic portion of a downstream
acceptance boundary, with network/policy/ledger still excluded. It does not
price the additional issuer check performed by the default `VerifiedSigner`
when a separate recipient also verifies the issued token.

This control measures that conservative deployment choice explicitly:

- Native CPU ES256: signing, encoding and one consumer verification.
- Hybrid ES256: GPU signing, independent issuer-side CPU verification before
  encoding, then a separate consumer verification. CPU fallback has only the
  consumer check, because its standard CPU signer needs no GPU fault guard.
- New native option `--guard separate`. The default one-check experiment is
  retained. No existing signature verification is skipped in either profile.
- Fixed 256- and 1,024-item ready waves, one key, four/eight workers, two
  repeats in reversed mode order, three seconds per cell: **16 cells**.
- Same selected-GPU idle preflight, shared-host telemetry, OpenSSL SDK, GPU
  DLL, claim contents and bounds. Only the native harness gains this guard.
- Every GPU token receives two CPU signature checks before successful
  completion; record the extra-check count and all latencies. No funds move.
- Compare slower hybrid / faster eligible CPU repeat, including both worker
  settings. Require ≥99% within 50 ms in both repeats and ratio >1.05, as in
  the original screening. Keep all negative results.

This isolates verification policy and is not a full network/payment-service
benchmark. A one-check design requires that the authoritative receiver verify
every token before acceptance or accrual and that invalid output recover
without double charging. That transaction architecture needs application
validation; the library's guarded signer remains the default example.
