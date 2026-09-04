# Machine-authorized content example

The engine provides three distinct capabilities: SHA-256 names bytes, AES-GCM protects and authenticates content plus metadata, and P-256 ECDSA authenticates a grant relative to a trusted publisher key.

`examples/content_grant.py` creates a content ID, encrypts content with associated metadata, and signs a grant containing version, publisher, content ID/length/type, intended principal, issue/expiry times, signing key ID, encryption algorithm/content-key ID/nonce, a terms hash and ciphertext hash. The signature covers a domain-separated encoding of all fields.

The encoding is sorted compact ASCII JSON over a fixed example schema of strings, integers and nested objects. It is an example-specific convention, not a general canonical-JSON standard. A deployed format needs a precise interoperable serialization specification and version negotiation.

The consumer uses an independent CPU implementation. It verifies the signature against an already trusted public key, checks issuer/key identity, principal, expected content, validity period and encryption parameters, then checks ciphertext identity and authenticated decryption. Finally it checks the plaintext hash and length. Tamper tests cover these bindings and wrong keys.

The expected publisher public key, expected content ID, trusted time, and content decryption key are inputs established outside the engine. A principal string is not an authentication system. The example neither sells access nor implements key release. A signed expiry does not erase a key or plaintext already delivered. Decryption rights cannot prevent a legitimate recipient from copying the result.

## Infrastructure hypothesis

Fine-grained licensed machine access might generate large populations of independent content/grant operations. Those populations could offer batching opportunities. This hypothesis depends on actual traffic shape, the fraction of objects/grants that require fresh cryptographic work, and latency requirements; it does not follow merely from high crawler request counts.

The competing designs matter:

- Immutable content may be hashed, encrypted and signed once, then cached for many requests.
- One grant may authorize a collection or session instead of requiring a signature per request.
- Existing authenticated HTTPS and CPU AES acceleration may already be sufficient.
- Access lookups, key management, payment accounting, object storage and network transfer may dominate the budget.
- Edge locations may not accumulate useful batches within the response deadline, or may not have GPUs near the data.

The current benchmark measures the cryptographic engine with explicit batches. It does not establish request-level economics, p99 under realistic arrivals, CDN placement, or the cost of authorization/key release. Those are the next measurements needed to connect primitive throughput to publisher revenue.
