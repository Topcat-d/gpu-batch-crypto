# Signature compatibility: a working ES256 path

The engine's P-256 output can be used in standard **ES256 compact JWS/JWT**.
The new [JWS encoder](../python/batchcrypto/jws.py) constructs the protected
header and payload signing input, hashes that input with SHA-256, submits a
batch to the chosen signer and encodes its raw `r || s` signatures. ES256 uses
that 64-byte signature representation. [RFC 7518, section 3.4](https://www.rfc-editor.org/rfc/rfc7518.html#section-3.4).

An unmodified **PyJWT 2.13.0** consumer accepted 256 tokens produced through
`VerifiedSigner` on the RTX 3060. The tests also reject altered payloads,
wrong public keys, wrong issuer/audience, expiration and algorithm mismatch;
stale issuer epochs fail before signing. This establishes a functioning ES256
wire-format path with independent consumer checks. It does not establish
acceptance by a particular deployed publisher service.

## Reproduce the integration

```sh
python -m pip install '.[interop]'
python examples/jws_grant.py
python examples/jws_grant.py --library build/Release/batchcrypto.dll --device 1
```

Select the device and library path for your host. The example creates
synthetic keys and access claims, issues a batch, then verifies every token
with a separately configured CPU public key, algorithm, issuer, audience and
expected scope/content claims. It performs no external access or payment.

```python
from batchcrypto import generate_p256_key
from batchcrypto.jws import sign_es256
from batchcrypto.verified import VerifiedSigner

with VerifiedSigner("build/Release/batchcrypto.dll", device=1) as signer:
    epoch = signer.load_key(0, generate_p256_key())
    tokens = sign_es256(
        [b'{"example":"synthetic access record"}'],
        key_id="issuer-epoch-1",
        sign_digests=lambda hashes: signer.sign(0, hashes, expected_epoch=epoch),
    )
```

This single-record snippet illustrates the interface, not a GPU routing
recommendation. A real grant must include the application's required fields.
The encoder preserves payload bytes and fixes `alg` to `ES256`; it is not a
JWT parser or permission service. Its callback owns signing and epoch policy.
The guarded GPU signer checks every output before release. A consumer still
pins the accepted algorithm and trusted issuer key and enforces expiration,
audience, scope and replay/redemption rules. A signed `jti` alone does not
prevent double spending. Never derive the allowed algorithm from an untrusted
token header or treat an arbitrary `kid` as authority to fetch a key.

## Existing Ed25519 protocols

Ed25519 and P-256 signatures require different keys and verification operations.
They cannot be converted by changing a header. HTTP Message Signatures defines
both algorithms, but a deployed profile can require one particular algorithm.
[RFC 9421, section 3.3](https://www.rfc-editor.org/rfc/rfc9421.html#section-3.3).
Cloudflare's [Pay per crawl announcement](https://blog.cloudflare.com/introducing-pay-per-crawl/)
describes Ed25519 crawler authentication. This release does not implement that
HTTP-signature profile or GPU Ed25519.

| Required application contract | Concrete integration choice |
|---|---|
| Issuer and consumer already accept ES256 JWS | Use the tested encoder and guarded GPU signer for eligible batches; retain a tuned CPU path |
| Consumer requires Ed25519 or an existing custom Ed25519 token format | Keep that CPU signing/verifying path; this P-256 backend cannot replace it |
| Participants control a new version of the access protocol | Explicitly agree the version, algorithm, issuer keys and claims; test both producers and consumers before selecting ES256 |
| Ed25519 request authentication and a separately required ES256 grant | Keep each in its own trusted protocol layer; measure both; an extra ES256 signature created only to use the GPU adds work |

The local KeyBook sandbox that informed the business thesis uses its own
Ed25519 token format. It would need an explicit protocol extension and matching
consumer changes to accept ES256. No private application code or wire schema
was moved into this library. The public interoperability example is generic.

## Compatibility and cost are separate decisions

The [ready-wave campaign](../benchmarks/READY_WAVE_CAMPAIGN.md) compares native
CPU ES256, hybrid ES256 and native CPU Ed25519 under the same synthetic claims,
batch shapes and public-key verification requirement. CPU ES256 uses normal
randomized nonces; GPU ES256 uses deterministic RFC6979 nonces. Both are valid
for ES256. OpenSSL Ed25519 signs the complete input without substituting an
external SHA-256 prehash. [OpenSSL Ed25519 interface](https://docs.openssl.org/3.5/man7/EVP_SIGNATURE-ED25519/).

The native timer includes construction and wire encoding but uses known
expected signing inputs for its cryptographic consumer. General PyJWT parsing
and claim-policy checks are exercised separately, outside that timing. A
positive ES256 result therefore establishes a candidate cryptographic service
path, not a payment-service capacity figure. The current GPU key-residency and
[secret-dependent execution limits](PRODUCTION_READINESS.md) still apply.
