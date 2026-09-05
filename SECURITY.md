# Security scope

This is experimental cryptographic software. Correctness tests are necessary but do not establish resistance to side channels or production suitability. The current imported implementations use secret-dependent branches/table lookups. Use the standard CPU backend where its established library and deployment properties are required.

The API requires a trusted host process, driver and GPU environment. It does not protect keys against the host administrator, a compromised process/driver, physical access, or another actor able to read device memory. It is not an HSM or confidential-computing service.

Use separate AES and signing keys. Generate keys with an operating-system-backed cryptographic library. Never reuse a nonce under an AES key; uniqueness must cover every worker, retry, restart and call. Within-batch duplicate rejection is only a local check. A production application should use a well-defined durable nonce allocation and key-lifetime policy.

AAD authenticates bytes supplied by the caller; it does not validate their business meaning. A signature authenticates a message relative to a public key; the application must establish whose key it is and validate audience, expiry, scope, content version and replay rules for any authorization format.

On authentication failure no plaintext is released for that item. On any native call-level error, discard all outputs. The C interface requires valid host pointers and non-overlapping caller buffers; it cannot validate arbitrary pointer ownership. Input counts and lengths are bounded before GPU allocation.

The library attempts to clear its own temporary host/device buffers during cleanup. Compiler registers, driver copies, failed-device cleanup, the caller's buffers and Python immutable byte objects are outside that guarantee. No secure-erasure claim is made.

P-256 output is deterministic ECDSA over SHA-256 digests with low-s normalization. A signer failure is returned as an error, never as a usable all-zero signature. CPU verification should remain a separate trust check when integrating the experimental CUDA signer.

The comb and full-window tables contain only public multiples of the standard generator. Their generation is checked independently against OpenSSL, but the lookup addresses and control flow depend on secret scalars or signing nonces. These backends are not constant time. Selecting a table backend changes the multiplication method, not the host/GPU trust boundary or key-protection properties.

Version 0.3 adds `bc_sign_at_epoch`, `bc_seal_at_epoch` and `bc_open_at_epoch`. They check the required key generation while holding the same native mutex used for key rotation, before executing the operation. An epoch mismatch returns `BC_KEY_CONFLICT`, reports no submitted/completed items and leaves caller output buffers untouched. Discard all outputs on error. Legacy entry points continue to operate on the current slot generation; they do not bind previously queued work to a required epoch.

For signing integrations, `batchcrypto.verified.VerifiedSigner` pins a CPU-derived public key at import, requires an explicit epoch, checks output shape/accounting/low-s encoding and verifies every signature with the CPU library before returning any batch. Backend or output-verification failures close that signer. This is a correctness and failure-containment layer, not side-channel resistance, GPU attestation or hardware key isolation. Verification itself adds CPU work that must be included in capacity and cost measurements.

Report suspected vulnerabilities privately through [GitHub private vulnerability reporting](https://github.com/Topcat-d/gpu-batch-crypto/security/advisories/new). The repository has this channel enabled. Do not include private keys, user content or payment details; provide a minimal synthetic example and affected version. Do not use public issues for sensitive incident material. No response-time SLA or independent audit is currently established. See the [production readiness evidence and open work](docs/PRODUCTION_READINESS.md).
