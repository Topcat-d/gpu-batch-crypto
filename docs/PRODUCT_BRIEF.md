# Product experiment: verifiable data exports

The next capability to evaluate is **a record that a recipient can verify after
it leaves the original service**. The initial engineering persona is a data API
or agent-tool developer shipping immutable export batches, with recipients who
retrieve subsets. This is a product hypothesis inferred from the engine and the
access experiments, not evidence of customer demand.

## Why this experiment

The HTTP measurements found transport/storage work dominating fresh signing;
they did not establish a GPU business advantage. Offline exports remove batch
fill from the critical request path and permit a stronger optimization: sign
one commitment instead of signing every record. A returned record carries a
small inclusion proof. CPU-only adoption can be useful even if GPU use never
becomes justified. This also fits content snapshots, dataset samples and agent
tool-result exports, without requiring a payment system.

Alternatives determine the experiment. Individual signatures are simple and
fit unrelated or urgent records. One signed list of all hashes uses one
signature too and may be simpler/faster when everyone gets the whole list.
Merkle receipts should earn their place through subset delivery and bounded
proof size. This is established cryptographic design, not a new invention.
[RFC 9162](https://www.rfc-editor.org/rfc/rfc9162.html#section-2.1) defines the
tree/inclusion construction. The envelope here is our experimental profile;
it is not Certificate Transparency. For software-release authenticity,
[Sigstore/Cosign](https://docs.sigstore.dev/quickstart/quickstart-cosign/) already
provides artifact signing, verification and transparency integration; we do
not propose replacing that ecosystem.

## Capability and implementation contract

- **Promise:** verify exact bytes at an expected index in a batch committed by
  a trusted P-256 key, without the other records or a live issuer.
- **Surfaces:** installed Python `batchcrypto.receipts`, detached JSON receipt,
  a source demo and a separate-process verifier; CPU-only base install.
- **Inputs:** ordered byte records, trusted key id and unique export context;
  a signing callback that owns the key. Consumer independently pins public
  key, key id, context and expected index.
- **Outputs:** immutable signed manifest and per-record proofs. A verifier
  returns a boolean and never returns partly verified data.
- **Lifecycle:** ready immutable records -> sealed batch -> detached receipt
  -> accepted/rejected inclusion. Changing records requires a new signed root.
- **Bounds:** 1..4096 records, 1 MiB each, core 64 MiB aggregate input budget,
  receipt <=4096 bytes, manifest <=2048 bytes, <=12 proof nodes. Decoder rejects
  duplicate keys, extra fields, wrong algorithms and noncanonical base64url.
- **Trust/cache:** at most eight checked manifests in a verifier bound to one
  trusted key/context. Every record's hash/path/index is always checked.
- **Ownership:** caller retains exact bytes and receipt, establishes key trust,
  chooses unique contexts, manages rotation/revocation, persistence and retries.
  Persist and resend the original receipt for exact retry identity. Randomized
  signer callbacks can produce different valid signatures on repeated sealing.
- **Failure:** issuer input/callback failures raise; untrusted receipt failures
  return false. No I/O, key generation, automatic GPU loading or fallback in
  this module. GPU callbacks must use the existing output-verifying guard.
- **Maturity:** experimental receipt profile within the preview Python package;
  core/native interfaces and publisher examples remain independently usable.

An inclusion result does not prove factual correctness, a real-world identity,
creation time, payment, permission, non-replay, availability, completeness of a
query, or an append-only history. The signer could issue conflicting roots.
Identical records can legitimately appear at multiple indices; include a
record identifier in the bytes when distinct application identities matter.
Hashes/proofs are not encryption or a confidentiality guarantee; low-entropy
undisclosed records may be guessable. A caller must not treat a receipt as an
access token. Production key custody and independent review remain open.

## Acceptance and next decision

Ship an independently runnable consumer and meaningful format/crypto tests.
Measure producer + serialization + consumer cost, record all proof bytes, and
compare fresh recipients with a recipient reusing a verified manifest. Include
individual signatures and the signed-hash-list control. Keep losing cases.
No GPU win is needed to accept this CPU capability.

Commercial go/no-go remains unknown: does a developer need portable subset
verification, will this save integration work over existing libraries, and
does the recipient accept the trust/profile contract? The next external signal
is one engineer integrating a real export and independently checking a record.
Do not claim sales, standards interoperability beyond the stated primitives,
or total operating savings from a local CPU measurement.

## Implemented decision

The [installed API and separate consumer](RECORD_RECEIPTS.md) are implemented.
The [234-cell comparison](RECEIPT_RESULTS.md) accepted 46,656 record checks.
It supports a narrower evaluation: separate recipients taking a subset of an
offline export. At 1,024 records/quarter consumption, Merkle receipts reduced
median producer-through-consumer CPU wall time by 30.5% versus pre-signing each
record. That does not establish savings versus an online issuer signing only
requested records. Shared full consumption favored the simpler signed hash list;
full consumption by separate recipients favored individual signatures.

Go for an engineering evaluation of portable subset verification. No-go for
positioning Merkle receipts as universally cheaper, for introducing GPU cost
into a one-signature export, or for declaring commercial demand proven. The
next product evidence is a real adopter's export/recipient pattern and integration
time, using these controls rather than requiring the surrounding access system.

## Next increment: make the simpler alternative adoptable

The prior comparison's hash-list alternative was benchmark-only. Promote a
separate experimental `batchcrypto.manifests` profile for a recipient receiving
many records: `seal_manifest` signs the complete ordered list; `open_manifest`
checks the configured key/context once and returns an immutable local handle.
Its `verify_record` checks a caller-specified index; `verify_all` additionally
requires the exact count and ordering of the complete export.

Keep selection explicit. The new opener rejects Merkle receipts, and the old
receipt verifier rejects hash lists. Existing receipt vectors and wire bounds
must remain unchanged. Hash-list manifests have a separate 256 KiB bound and
at most 4096 SHA-256 digests; the handle retains only digests/scope, never records
or keys. Invalid wire input returns no handle; bad trusted configuration raises.
The handle is a local object, not a serializable proof or authorization token.

Acceptance: independent JWS verification, immutable handles, strict bounds and
profile separation, complete-export rejection tests, frozen vectors, both
formats through the detached-file examples and an installed wheel. Remeasure
the actual public API against Merkle and individual-signature controls before
claiming it inherits the benchmark prototype's performance.
