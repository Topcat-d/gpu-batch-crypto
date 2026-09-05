# Production security: evidence and remaining work

Version 0.3 strengthens key-generation binding and output verification. It remains a technical preview. The current GPU arithmetic and table accesses depend on secrets; output verification does not repair that confidentiality boundary. A deployment requiring constant-time cryptography, HSM-held keys or independently reviewed GPU key isolation cannot approve this implementation on the basis of throughput tests.

## Changes that are implemented

| Concern | Implemented protection | Evidence |
|---|---|---|
| Queued requests accidentally use a rotated key | Additive C entry points require an exact epoch under the native context mutex, shared with rotation and retirement | [ABI implementation](../src/abi/batchcrypto_abi.cpp), [header](../include/batchcrypto.h), stale/retired/empty-batch tests and C consumer output sentinels |
| Incorrect GPU signing output reaches a caller | `VerifiedSigner` checks a CPU-derived public-key pin, exact epoch/report, count/order, raw encoding, low-s and every signature before returning the batch; failures close the signer | [Implementation](../python/batchcrypto/verified.py), [controlled backend-failure tests](../tests/test_verified.py) and real GPU differential checks |
| An unbounded iterable consumes arbitrary host memory before rejection | Consume at most `MAX_BATCH + 1` items before rejecting excessive input | [Bounded-input regression](../tests/test_guards.py) |
| Large result batches create avoidable CPU/memory pressure | Materialize each contiguous output once before slicing records | [Before/after evidence](DISPATCH_RESULTS.md); deterministic results match OpenSSL |
| Mutable CI action tags or excess token permissions | Pin action commits; read-only contents permission; disable checkout credential persistence | [CI workflow](../.github/workflows/ci.yml) |
| Vulnerabilities have no private reporting route | GitHub private vulnerability reporting enabled | [Private report form](https://github.com/Topcat-d/gpu-batch-crypto/security/advisories/new) |

The fault tests substitute a controlled backend that corrupts, truncates or reorders output, reports another epoch, exports the wrong public key or raises an error. They establish the wrapper's behavior under those injected conditions. They are not physical GPU fault experiments or an independent assessment.

## Use the guarded signing boundary

The separate [funded-access example](ACCESS_BOOK_DESIGN.md) exercises application
controls with simulated funds: authoritative pricing, bounded budgets, pinned
ES256 admission, exact scope, key revocation, replay protection, cancellation,
concurrent spending, transaction rollback and restart recovery. Its CPU-only
accounting tests do not change the GPU key-isolation or timing assessment.
Network authentication, distributed recovery, actual funding/payout adapters,
expiry scheduling and independent review remain deployment work.

```python
from batchcrypto import Cpu, generate_p256_key
from batchcrypto.verified import VerifiedSigner

digests = Cpu().sha256([b"example-domain:v1:record-1", b"example-domain:v1:record-2"])
with VerifiedSigner("build/Release/batchcrypto.dll", device=0) as signer:
    epoch = signer.load_key(0, generate_p256_key())
    signatures = signer.sign(0, digests, expected_epoch=epoch)
    # Every signature passed CPU verification before this list became available.
    signer.retire_key(0, expected_epoch=epoch)
```

The wrapper owns and serializes access to its runtime. Keep that runtime private; do not mutate its internals. Each slot caches only the pinned public key in Python after import, while the native slot retains its host copy of the private key. Python input byte strings, registers and driver copies remain outside a secure-erasure guarantee. `VerifiedSigner` requires the native v0.3 symbols and defaults to full-window signing; the general `Runtime` retains the reference default.

Native integrations can use the same epoch-bound API and perform verification with their independently selected CPU cryptographic library. `Runtime.sign(..., expected_epoch=epoch)` binds the epoch but does not independently verify output. Likewise, the AES epoch APIs do not allocate nonces or establish the business meaning of AAD.

## Decisions still required before production approval

| Open item | Required completion evidence | Responsibility |
|---|---|---|
| Secret-dependent execution | Review all field/scalar arithmetic, branches and table access; either deliver and independently evaluate a suitable execution design or explicitly reject this GPU path for the deployment's key policy | Cryptography/security maintainers and independent reviewers |
| Key isolation and lifecycle | Define trusted host/driver/device boundary, tenant separation, crash/restart policy, import/rotation/revocation and exposure response; validate deployment controls | Operator/security owner |
| AES nonce uniqueness across retries/restarts/workers | Durable allocation/key-lifetime design and concurrency/recovery tests; local duplicate detection is insufficient | Application/key-management owner |
| Authorization and replay protection | Authenticated caller, domain-separated canonical messages, audience/scope/expiry/content version and replay rules; the signer must not be an unrestricted signing oracle | Application owner |
| Overload and availability | Workload-specific queue limits/deadlines, permitted CPU routing, failure quarantine/recovery, redundancy and long-run SLO measurements | Service owner |
| Broader validation | Independent cryptographic review; larger randomized differential corpus; sanitizer coverage beyond the C smoke path; Linux CUDA and additional GPU/toolchain coverage | Maintainers/reviewers |
| Release and dependency lifecycle | [Artifact checks and release/rollback procedure](RELEASING.md) now cover distribution scope, notices, version pairing and state ownership; repeatable GPU release builds, broader dependency/platform coverage and published release evidence remain required | Maintainers |

Current hosted CI exercises CPU correctness, the native CPU benchmark and evidence integrity. Local CUDA acceptance covers the two RTX cards and documented Windows toolchain. Neither check certifies production security. The [validation record](VALIDATION.md) distinguishes executed checks from these open items.

The practical approval today is a scoped engineering evaluation with acceptable synthetic/development keys and measured traffic assumptions. A production approval requires resolving the relevant open items for the intended deployment; these are not made complete by a generic checklist or a faster benchmark.
