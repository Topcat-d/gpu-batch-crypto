# Verify one record from a signed export

`batchcrypto.receipts` signs one root for a batch of exact byte records. Each
record can travel with a small proof and be checked offline. Evaluate this when
a data API, publisher or agent tool exports immutable records and recipients
retrieve subsets. The [product brief](PRODUCT_BRIEF.md) explains the hypothesis
and alternatives; the [comparison](RECEIPT_RESULTS.md) measures them.

**Experimental profile, CPU-only base install.** Python 3.10+ and the existing
`cryptography` dependency are sufficient. CUDA, PyJWT, databases and the access
applications are not required. No real identity or payment integration is implied.

## Smallest complete use

Install this checkout with `python -m pip install .`, then:

```python
from batchcrypto import Cpu, generate_p256_key, public_key
from batchcrypto.receipts import ReceiptVerifier, seal_records

key = generate_p256_key()  # Synthetic demo key; applications own key custody.
records = [b'{"id":1,"result":"one"}', b'{"id":2,"result":"two"}']
batch = seal_records(
    records,
    context="catalog/export-123",
    key_id="publisher-key-1",
    sign_digests=lambda digests: Cpu().sign(key, digests),
)
receipt = batch.receipt(1)

# Configure this public key through your own trusted channel.
consumer = ReceiptVerifier(
    public_key(key), key_id="publisher-key-1", context="catalog/export-123"
)
assert consumer.verify(records[1], receipt, expected_index=1)
assert not consumer.verify(b"changed", receipt, expected_index=1)
```

The recipient needs only this record, its receipt, and trusted configuration.
For many records at one recipient, send `batch.manifest` once, use
`batch.receipt(index, include_manifest=False)`, and call
`consumer.verify(record, proof, expected_index=index, manifest=batch.manifest)`.
The supplied manifest is verified. Passing both an embedded and separate manifest
is rejected. Its bounded cache avoids repeated signature verification; every
record's exact bytes and inclusion path are always checked.

An existing signer can supply the callback. Use `VerifiedSigner` with its
required epoch for a GPU callback. Sealing one batch requires one signature,
so start on CPU. Batching many signed roots needs separate performance evidence.

## Try detached files and a separate consumer

These source examples use a fresh synthetic key and 64 synthetic tool results.
The output directory must not exist. It receives one record, its receipt and
the public key; the private demo key is not written.

```sh
python examples/record_receipts.py --output dist/record-receipt-demo
python examples/verify_record_receipt.py --record dist/record-receipt-demo/record.bin --receipt dist/record-receipt-demo/receipt.json --public-key dist/record-receipt-demo/public-key.hex --key-id demo-key-1 --context demo-export-2026-09-07 --index 17
```

Expected: 64 records sealed with one signature; consumer prints `VERIFIED` and
exits 0. Changed bytes, wrong context/key/index or malformed receipt prints
`REJECTED` and exits 1. In this demo you trust the key because you just created
it. Accepting a key from an untrusted sender lets that sender choose its authority.

## Wire and failure contract

`seal_records` accepts 1..4096 byte strings, <=1 MiB each, within the core's
64 MiB working-input budget. Context and key id require 1..128 printable ASCII
characters. Exact record bytes matter; JSON records are not canonicalized.
It returns a frozen `SealedBatch(manifest, paths)` retaining hashes/signature,
but no records/keys. Invalid producer inputs or callback failures raise and
return no batch. The caller must provide a trusted signer callback.

The manifest is compact JWS with exactly `{"alg":"ES256","kid":key_id}` in
its protected header. The payload has exactly these fields:

```json
{"profile":"batchcrypto-record-receipt-v1","context":"catalog/export-123","count":2,"root":"<base64url SHA-256 root>"}
```

The UTF-8 JSON receipt has `manifest` (complete JWS), `index` (integer) and
`path` (base64url 32-byte siblings from leaf toward root). The shared form
omits `manifest`. Receipt <=4096 bytes, manifest <=2048 ASCII bytes, path <=12
nodes. Only canonical unpadded base64url is accepted. Duplicate/extra fields,
unknown profiles, wrong keys/algorithms and invalid/non-low-s signatures are
rejected. `verify` returns false for malformed/oversized wire input. Invalid
trusted constructor configuration raises instead.

Tree hashing uses SHA-256 leaf prefix `0x00` and node prefix `0x01`. Ordered
uneven trees split at the largest power of two smaller than the subtree size;
odd leaves are not duplicated and hashes are not sorted. Construction and
inclusion follow [RFC 9162 §2.1](https://www.rfc-editor.org/rfc/rfc9162.html#section-2.1).
This envelope is our own profile, not a CT message or JWT access token. The
expected index is caller policy. Identical bytes can occur at multiple positions;
embed distinct record IDs when the application needs distinct identity.

## Ownership and maturity

Callers establish trust, assign unique export contexts, retain exact bytes and
original receipts for retries, and manage rotation, revocation, deletion and
access policy. Recreate a verifier when its trust policy changes. It caches at
most eight checked manifests under a lock, bound to one trusted key/context.

Inclusion does not prove factual accuracy, person/business identity, creation
time, payment, permission, delivery, non-replay, query completeness or append-only
history. Signers can issue conflicting roots. Hashes/proofs provide no encryption
or privacy guarantee for guessable records.

The format/API are experimental, with no support SLA or independent audit.
Tests cover all positions in uneven/power-of-two trees, an independent stack
root oracle, PyJWT verification, tamper/scope rejection, bounds, duplicate
fields, cache eviction/concurrency and shared manifests. The installed-wheel
check runs with CUDA loading blocked and no PyJWT installed.
