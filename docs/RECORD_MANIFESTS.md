# Verify a complete export with one signed hash list

Use `batchcrypto.manifests` when one recipient can receive the entire list of
record hashes. It signs once, opens/verifies once, and checks records against
the validated list. `verify_all` also enforces the complete export's count and
order. The [Merkle receipt API](RECORD_RECEIPTS.md) remains useful when recipients
need small standalone subset proofs.

Both profiles are experimental and work with the base Python installation:
Python 3.10+ and `cryptography`. No CUDA, PyJWT, database or access service is
required. The [public API comparison](MANIFEST_API_RESULTS.md) measures this
implementation; the older hash-list benchmark was a separate prototype.

## Choose based on delivery

| Requirement | Starting point | Tradeoff |
|---|---|---|
| One recipient reads most/all records | Signed hash list | Receive all hashes once; simple record checks |
| Separate recipients retrieve a few records each | Merkle receipts | Bounded inclusion proofs; extra hashing and proof metadata |
| Independent/urgent records or an online issuer signs only what is requested | Individual ES256 signatures | No export assembly; no batch commitment |

These are evaluation choices, not universal performance rules. A hash list
reveals the hashes of unrequested records too; neither profile provides a
privacy guarantee for guessable records. Identity, time, payment and access
authorization require separate application policy.

## Smallest complete use

```sh
python -m pip install .
```

```python
from batchcrypto import Cpu, generate_p256_key, public_key
from batchcrypto.manifests import seal_manifest, open_manifest

key = generate_p256_key()  # Synthetic demo; key custody belongs to your app.
records = [b'{"id":1,"value":"one"}', b'{"id":2,"value":"two"}']
token = seal_manifest(
    records, context="export-123", key_id="source-key-1",
    sign_digests=lambda digests: Cpu().sign(key, digests),
)

# This public key/context must come from the recipient's trusted configuration.
checked = open_manifest(
    token, public_key(key), context="export-123", key_id="source-key-1"
)
assert checked is not None
assert checked.verify_record(records[1], expected_index=1)
assert checked.verify_all(records)
assert not checked.verify_all(records[:-1])
assert not checked.verify_all(list(reversed(records)))
```

`open_manifest` checks the signature and validates all hash entries, including
unrequested entries. Its immutable handle retains only digest bytes and scope
labels. Reusing the handle avoids reparsing the list or verifying its signature
for each record. Each `verify_record` still hashes and compares the supplied bytes.
Reopen/discard the handle when your trust policy changes. The local Python
handle is not a wire proof; never deserialize an object as evidence of validation.

## Detached-file example

The existing examples now accept an explicit format. Their default remains
`merkle`. The following creates a new output directory with a synthetic signed
manifest, public key and one record, then verifies it in another process:

```sh
python examples/record_receipts.py --format manifest --output dist/manifest-demo
python examples/verify_record_receipt.py --format manifest --record dist/manifest-demo/record.bin --receipt dist/manifest-demo/manifest.jws --public-key dist/manifest-demo/public-key.hex --key-id demo-key-1 --context demo-export-2026-09-07 --index 17
```

The producer also verifies all 64 demo records. Success exits 0; rejection exits
1. The private demo key is never written. A real recipient must establish public
key trust independently instead of trusting whichever key accompanies a file.

## Contract

- `seal_manifest(records, *, context, key_id, sign_digests) -> str`: 1..4096 byte
  records, <=1 MiB each, core 64 MiB working-input budget. Context/key id are
  1..128 printable ASCII characters. A trusted signing callback receives one
  SHA-256 digest and returns one low-s raw P-256 signature; GPU callbacks must
  use `VerifiedSigner`. Failure raises and returns no manifest.
- `open_manifest(token, public_key, *, context, key_id)`: independently pinned
  P-256 key and labels; malformed/untrusted wire input returns `None`, invalid
  trusted configuration raises. Token is ASCII compact JWS, <=256 KiB. Extra or
  duplicate fields, wrong algorithms/profiles, noncanonical base64url, invalid
  counts/hash lengths and non-low-s signatures are rejected.
- `checked.count`, `checked.verify_record(record, *, expected_index)` and
  `checked.verify_all(records)`: explicit caller position, exact bytes, no JSON
  normalization. Full checking rejects missing, extra or reordered distinct
  records. Identical bytes remain indistinguishable; embed record IDs if needed.
  Bad input shapes return false; exceptions from caller iterators may propagate.

The protected header is exactly `{"alg":"ES256","kid":key_id}`. Its payload
has exactly `profile`, `context`, `count`, and `hashes`. The profile identifier is
`batchcrypto-record-manifest-v1`; `hashes` is an ordered array of unpadded
base64url SHA-256 digests. This profile is distinct from Merkle receipts and
the old benchmark-only `hash_list` envelope. Cross-profile acceptance is rejected.

The application owns unique export contexts, key trust/rotation/revocation,
retention of exact bytes, receipt persistence/retries, and record semantics.
Full verification establishes equality to this signed export, not completeness
of the source's database or query. Neither signature proves factual truth,
freshness, payment, authorization, delivery or a consistent append-only history.

Evidence: [tests](../tests/test_manifests.py), [public synthetic conformance
vector](../tests/vectors/record-manifest-v1.json), [measurements](MANIFEST_API_RESULTS.md),
and installed-wheel checks without CUDA or PyJWT. Public scalar 1 in the vector
is test material only. Production security review and support commitments remain open.
