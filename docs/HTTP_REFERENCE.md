# HTTP reference: from permission to recovered delivery

This experimental source example connects a synthetic buyer, issuer and
publisher over actual loopback HTTP. It demonstrates simulated budget controls,
scoped credentials, recoverable content delivery and reconciled accounting.
It is a generic local ES256 profile, not a payment service or a Cloudflare,
Persona, x402, AP2 or Web Bot Auth adapter.

From a checkout, install the optional token consumer and run:

```sh
python -m pip install '.[interop]'
python examples/http_access_demo.py
```

That command starts two loopback listeners, issues a two-item book, simulates a
lost delivery response, recovers the same receipt and body, cancels the unused
reservation and prints the reconciled ledger. There are no real funds, external
requests, accounts to create or GPU requirements. The fixture deletes its
temporary database after the example completes.

## Components and ownership

| Component | Purpose and interface | Dependencies and ownership |
|---|---|---|
| [Keys / Consumer](../examples/http_access/signing.py) | Ready claim batches -> ES256 tokens; independently pinned publisher verification; trusted key rotation | Core encoder, cryptography, PyJWT; optional VerifiedSigner + native GPU library. Issuer owns synthetic keys/epochs; publisher owns public pins and admission cache. |
| [Ledger](../examples/http_access/ledger.py) | Atomic reserve, spend, cancel, receipt recovery and conservation audit | SQLite WAL/FULL and immutable fixture catalog. Issuer owns prices, budgets, revocation, trusted clock and one authoritative spent set. Signing occurs outside the database write transaction. |
| [HTTP fixture / buyer](../examples/http_access/service.py) | Authenticated local JSON RPC, bounded exact retries, publisher body delivery, buyer hash/receipt validation | Python standard library. Issuer and publisher have different credentials and endpoints. Buyer owns retry IDs and requested content/terms. |
| [Campaign](../benchmarks/run_http_access.py) | Reproducible CPU/direct/book/GPU comparison with individual observations | Source checkout plus above; native GPU library optional. Operator supplies hardware and price assumptions. |

These are experimental application interfaces outside the Python wheel. They
do not change the cryptographic engine or require adopters to use this ledger.
The earlier [access-book example](ACCESS_BOOK_DESIGN.md) remains a separate
co-located accounting experiment; its benchmark numbers do not describe HTTP.

## Transaction and failure contract

```mermaid
sequenceDiagram
    participant B as Synthetic buyer
    participant I as Issuer / online ledger
    participant P as Publisher
    B->>I: Issue ready books, approved maximum, retry ID
    I->>I: Prepare claims; CPU or guarded GPU sign
    I->>I: Recheck balance, expiry and revocation; reserve atomically
    I-->>B: Immutable ES256 credentials and manifests
    B->>P: Authenticated access, content/terms, book, retry ID
    P->>P: Verify issuer signature and buyer/book binding
    P->>I: Authenticated spend for that buyer
    I->>I: Check scope, expiry, revocation and spent state; commit receipt
    I-->>P: Recoverable entitlement receipt
    P-->>B: Entitled content version and receipt
    B->>B: Check returned bytes and receipt
```

The direct CPU account path uses only the access/spend/delivery portion. It
does not sign anything because both parties already trust the online issuer.
It provides the same budget, content, terms, one-commit accounting and recovery
checks. It does **not** provide signed delegation to a separately operated
consumer; no benchmark should treat that feature difference as a free benefit.

The book path signs once per book, not per resource. GPU batch size counts
books sharing the current issuer key, not websites or resource entries. A
64-book/four-resource wave signs 64 tokens for 256 planned accesses. Caller-
assembled batches avoid arrival fill delay; this example has no automatic
cross-client collector or universal CPU/GPU routing threshold.

Issuance validates the complete batch, signs without a database write lock,
then atomically rechecks current time, key revocation and funds before reserving.
Any signing failure returns no credentials and reserves nothing. An exact
issuance retry returns stored credentials; concurrent retries may perform extra
signatures before one transaction wins, but reserve only once. The manifest
commitment is signed; online clearing retains authoritative resource entries
and requires the exact stored token. Publisher signature admission can be
cached, but every fresh spend still checks current revocation and expiry online.

Every committed spend purchases an **entitlement to recover the same immutable
content**, not proof of successful delivery or AI consumption. A lost spend or
delivery response is retried with the same ID and inputs. The original receipt
and content can be returned after expiry or revocation; fresh spend is denied.
Changing the input under an old ID fails. A different ID cannot redeem the same
book item twice. Unused reservation cancellation is idempotent and needs the
authenticated buyer. No autonomous expiry worker is included: callers must
cancel unused books, or an operator must build that lifecycle service.

The conservation rule is `initial = available + reserved + spent`. Receipt
totals equal buyer spend and 100% simulated publisher accrual. No processor
fee, payout, revenue share or money movement is implemented. Content bytes are
synthetic fixture data retained for the fixture lifetime. Production recovery
requires durable version retention, an agreed recovery period and backups.

## Reproduce measurements

```sh
python benchmarks/run_http_access.py --output dist/http-cpu.json
python benchmarks/run_http_access.py --output dist/http-gpu.json --library PATH_TO_LIBRARY --gpu-uuid GPU_UUID --library-source-commit BUILD_COMMIT --library-build-note "Compiler, CUDA version and architecture"
```

Commit the source before a measured campaign. For a quick wiring check during
development, add `--smoke --repeats 1`; those captures are explicitly excluded
from evidence. CPU is always included with cached keys and 1/4 signing workers.
The GPU option requires native v0.3+, synthetic keys and an idle selected UUID;
it fails rather than silently substituting CPU. Use `--host-hourly` and
`--gpu-hourly` only for explicit whole-host and additional GPU cost scenarios.
Omitted prices produce no claimed dollar estimate.

The [predeclared campaign](../benchmarks/HTTP_ACCESS_CAMPAIGN.md) defines four
finite ready-wave workloads, three repeats and a one-second ready-to-delivery
deadline. It counts preparation, queueing, delivery, verification, signing,
unused work and cleanup. The 50 ms overlap interval models independent work;
it does not establish how much useful preparation a real agent can hide.
The [published results](HTTP_RESULTS.md) reconcile 6,924 delivered accesses but
retain 3,218 late completions. No positive additional GPU cost allowance survives
the conservative comparison in these four workloads.

## Limits and security boundary

Only loopback addresses can be bound or contacted. Per-run random bearer
secrets represent preauthenticated synthetic identities; no real identity
proofing is implemented. Issuer spending is restricted to the publisher role.
Buyer fields cannot override authenticated identity. Bodies, token sizes,
manifest sizes, timeouts and retry attempts are bounded. Maximum batch: 256
books, 32 resources/book, 2,048 total entries, with a one-MiB HTTP body limit.

The development HTTP server uses a new TCP connection per RPC, no TLS, and
threads per connection. It is unsuitable for public deployment or hostile
traffic. Two listeners and all benchmark clients share one process and host;
the public-key pin is passed in trusted memory, not discovered over a network.
SQLite is the single authoritative clearing boundary. No replication,
distributed transaction, production backpressure or tamper-evident audit log
is claimed. Test key rotation retains old public pins; durable key management,
multi-process rotation coordination and HSM isolation remain application work.

GPU keys inherit the [documented native security limits](PRODUCTION_READINESS.md).
The issuer verifies every GPU signature before release; the publisher separately
verifies the credential. Removing either check changes this campaign's contract.
This example is covered by [HTTP integration tests](../tests/test_http_access.py),
including lost responses, atomic rollback, retries, wrong scope, expiry and
revocation after cached admission. Tests reopen the durable ledger to check
receipt recovery; they do not simulate power loss or a whole-machine crash.
