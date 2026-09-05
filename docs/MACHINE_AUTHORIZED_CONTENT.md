# Machine-authorized content example

The engine provides three distinct capabilities: SHA-256 names bytes, AES-GCM protects and authenticates content plus metadata, and P-256 ECDSA authenticates a grant relative to a trusted publisher key.

`examples/content_grant.py` creates a content ID, encrypts content with associated metadata, and signs a grant containing version, publisher, content ID/length/type, intended principal, issue/expiry times, signing key ID, encryption algorithm/content-key ID/nonce, a terms hash and ciphertext hash. The signature covers a domain-separated encoding of all fields.

The encoding is sorted compact ASCII JSON over a fixed example schema of strings, integers and nested objects. It is an example-specific convention, not a general canonical-JSON standard. A deployed format needs a precise interoperable serialization specification and version negotiation.

The consumer uses an independent CPU implementation. It verifies the signature against an already trusted public key, checks issuer/key identity, principal, expected content, validity period and encryption parameters, then checks ciphertext identity and authenticated decryption. Finally it checks the plaintext hash and length. Tamper tests cover these bindings and wrong keys.

The expected publisher public key, expected content ID, trusted time, and content decryption key are inputs established outside the engine. A principal string is not an authentication system. The example neither sells access nor implements key release. A signed expiry does not erase a key or plaintext already delivered. Decryption rights cannot prevent a legitimate recipient from copying the result.

For a standard token encoding, the separate [ES256 JWS example](COMPATIBILITY.md) issues synthetic grants that PyJWT verifies. It complements this encrypted-content example; it does not implement the ledger or content-key delivery service.

## Infrastructure hypothesis

The [keys instead of clicks thesis](KEYS_INSTEAD_OF_CLICKS.md) explains how an
approved buyer budget, scoped credential, delivery receipt and publisher ledger
could support compensation without a referral click. It distinguishes access
rights, signing keys and encryption keys, and defines the economic tests that
this cryptographic example alone cannot answer.

The [agent access design](AGENT_ACCESS_DESIGN.md) describes how an agent's ready
planning waves and a publisher's grant service could use the CPU–GPU engine.
It distinguishes established keys, fresh proofs, issuer authorization and
concurrent network calls, and keeps speculative preparation separate from
purchase or billable delivery. This is a proposed integration around the
example, not a payment protocol implemented by it.

Fine-grained licensed machine access might generate large populations of independent content/grant operations. Those populations could offer batching opportunities. This hypothesis depends on actual traffic shape, the fraction of objects/grants that require fresh cryptographic work, and latency requirements; it does not follow merely from high crawler request counts.

The competing designs matter:

- Immutable content may be hashed, encrypted and signed once, then cached for many requests.
- One grant may authorize a collection or session instead of requiring a signature per request.
- Existing authenticated HTTPS and CPU AES acceleration may already be sufficient.
- Access lookups, key management, payment accounting, object storage and network transfer may dominate the budget.
- Edge locations may not accumulate useful batches within the response deadline, or may not have GPUs near the data.

The library benchmarks measure the cryptographic engine with explicit batches.
The [native pipeline](PIPELINE_RESULTS.md) adds queueing, CPU preparation,
all-output verification and deadline accounting under its recorded host
conditions. Neither campaign measures an agent's planning overlap, production
traffic, CDN placement or authorization/key-release costs. The proposed access
design identifies those measurements for connecting the engine to a publisher
service and its economics.
