# Ready-wave compatibility and cost campaign

Predeclared September 5, 2026, before this matrix is measured. Synthetic keys,
claims and content commitments; no publisher is contacted and no funds move.

Question: does the current GPU engine reduce the full measured cryptographic
service time for an already-ready group of standard signed access objects?
The distinct algorithm-choice question is how this compares with CPU Ed25519.

## Fixed experiment

- Device 1, observed NVIDIA GeForce RTX 3060 12 GB. Require three idle selected
  GPU observations (at most 5%) before every cell. Record shared-host CPU and
  both GPUs; leave other workloads under their owners' control.
- Native OpenSSL 3.5.8 and existing v0.3 GPU DLL. Reuse key/context state.
- Seven (wave, independent issuer keys) pairs: (1,1), (8,1), (64,1), (256,1),
  (1024,1), (4096,1), (4096,16). Four and eight CPU workers.
- Three modes: native CPU ES256 with normal randomized nonces; native CPU
  Ed25519/JOSE EdDSA; hybrid ES256 with deterministic GPU signing for compatible
  groups of at least 64 and the same randomized CPU fallback below that size.
  Both ECDSA paths produce standard low-s signatures. Deterministic nonces
  are not required by JWS; use the stronger ordinary CPU baseline.
- Two complete repeats, reversed mode order in the second: 84 cells, three
  timed seconds per cell plus three warm-up waves and key setup. No adaptive
  batch-size tuning or selective removal of outcomes.
- Each next wave becomes ready only after the previous entire wave has been
  checked. No arrivals are dropped. This is a closed-loop service-time test,
  not a constant-arrival capacity/SLO test or simulated agent reasoning.
- Timer includes constructing JSON claims, base64url signing inputs, hashing,
  native scheduling/barriers, signing, GPU transfers, compact token encoding,
  wire signature decoding and independent CPU verification of every output.
  General JWT parsing/claim validation is checked with PyJWT outside timing.
- Key creation/import, warm-up, network/TLS, buyer authorization, payment,
  persistence, settlement and idle time between jobs are outside timing.
  Signer keys stay synthetic because existing GPU side-channel limits apply.

## Acceptance and interpretation

Every timed token must pass the native public-key check; record all wave
latencies and one external-consumer token sample per key in every cell. Check
sample signatures and expected claims with unmodified PyJWT. Expiry is checked
in live compatibility tests; archive validation evaluates issuance-time claims
without applying the replay date as the token's original lifetime.

The primary observed quality gate is at least 99% of tokens completed within
50 ms in both repeats for each compared configuration. Also report 10 ms,
sample counts and p50/p95/p99. This is a finite-run observation, not a statistical
guarantee. All earlier 10 ms failures remain unchanged and visible.

For each wave/key pair, compare each eligible hybrid worker setting with the
faster eligible CPU worker setting (4 or 8) using the conservative throughput
ratio: slower hybrid repeat / faster CPU repeat. A GPU candidate needs actual
GPU use, both quality passes and a ratio greater than 1.05. Report failures,
CPU-only hybrid controls and the Ed25519 comparison as well as any candidates.
The best measured CPU setting is not a claim of globally optimal CPU tuning.

For fully allocated crypto-service hourly cost H, cost per million on-time
tokens is 1e6*H/(3600*goodput). If the hybrid host costs C+G and CPU host costs
C, the maximum incremental GPU/CPU price ratio is goodput_hybrid/goodput_cpu-1.
These are cost ceilings from this workload, not invoices or publisher ROI.
If an unchanged serial downstream stage takes L seconds per wave, the modeled
speedup becomes (T_cpu+L)/(T_hybrid+L); show how common work narrows the margin.
An Ed25519-only service cannot substitute ES256 without protocol agreement.

## Source and repeatability

Commit this plan, implementation and verifier before measurement. Capture
source/binary hashes, exact commands, CPU/GPU metadata, per-cell telemetry and
raw latency samples. Preserve incomplete captures and execution errors. Small
build/correctness smoke checks are excluded from reported performance evidence.

No cloud rental is required for this bounded campaign. Follow-up production
load and real payment economics require a representative application trace.
