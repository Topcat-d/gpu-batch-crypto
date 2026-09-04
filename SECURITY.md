# Security scope

This is experimental cryptographic software. Correctness tests are necessary but do not establish resistance to side channels or production suitability. The current imported implementations use secret-dependent branches/table lookups. Use the standard CPU backend where its established library and deployment properties are required.

The API requires a trusted host process, driver and GPU environment. It does not protect keys against the host administrator, a compromised process/driver, physical access, or another actor able to read device memory. It is not an HSM or confidential-computing service.

Use separate AES and signing keys. Generate keys with an operating-system-backed cryptographic library. Never reuse a nonce under an AES key; uniqueness must cover every worker, retry, restart and call. Within-batch duplicate rejection is only a local check. A production application should use a well-defined durable nonce allocation and key-lifetime policy.

AAD authenticates bytes supplied by the caller; it does not validate their business meaning. A signature authenticates a message relative to a public key; the application must establish whose key it is and validate audience, expiry, scope, content version and replay rules for any authorization format.

On authentication failure no plaintext is released for that item. On any native call-level error, discard all outputs. The C interface requires valid host pointers and non-overlapping caller buffers; it cannot validate arbitrary pointer ownership. Input counts and lengths are bounded before GPU allocation.

The library attempts to clear its own temporary host/device buffers during cleanup. Compiler registers, driver copies, failed-device cleanup, the caller's buffers and Python immutable byte objects are outside that guarantee. No secure-erasure claim is made.

P-256 output is deterministic ECDSA over SHA-256 digests with low-s normalization. A signer failure is returned as an error, never as a usable all-zero signature. CPU verification should remain a separate trust check when integrating the experimental CUDA signer.

Do not use the GitHub public issue tracker for private keys, user content or sensitive incident material. Until a private reporting channel is established, contact the repository owner through an already trusted channel.
