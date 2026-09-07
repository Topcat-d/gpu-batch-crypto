# Public manifest API comparison

Question: does the fully validating installed hash-list API remain useful
after the benchmark prototype becomes a strict public interface?

Compare the public `seal_manifest` / `open_manifest` / `verify_record` path,
public Merkle receipts, and the prior individual-signature control. One cached
OpenSSL CPU signing key/thread, identical synthetic ordered record bytes and
expected indices, complete pre-sealing of each offline export. No GPU, network,
storage, real keys, funds, or rental. CPU only; at most five minutes per run.

Primary: 1024 records, five repeats. Holdout: 257 records, three repeats after
primary with no implementation changes. Scenarios: one record at a fresh
recipient; quarter at separate recipients; full at one shared recipient; full
at separate recipients. Seeded scheme order within every repeat, retained in
capture. One untimed warm-up per scheme before primary; warm-ups use 7 records.

Time producer hashing/signing (including all Merkle proofs), metadata encoding,
and consumer decoding/verification. A shared recipient receives the manifest
once. A fresh recipient gets a full signed manifest per record. All hash-list
digests are validated when opening, including unused entries. Timed checks use
`verify_record`; the new `verify_all` count/order check has separate unit tests.
The common benchmark adapter encodes indices in JSON. It owns transport framing,
not the public cryptographic library. Exclude fixture/key creation, the changed-
record rejection gate and the verification of measured counters from elapsed.

Capture 100 ms aggregate CPU utilization before each three-scheme comparison,
outside timing. It is background-load context, not CPU isolation or attribution.
Record source hashes, CPU model, runtime/OpenSSL, every accepted count, exact
metadata bytes and producer/encoding/consumer phases. Stop on correctness or
time-budget failure, retaining all completed rows and the attempted row/error.

Acceptance: all selected records verify, altered bytes reject, complete schedule,
source/work/byte verification, and a successful installed consumer. Performance
has no forced threshold. Report medians and min-baseline/max-candidate observed
ratios, with losses intact; do not transfer old prototype rates to this API.
