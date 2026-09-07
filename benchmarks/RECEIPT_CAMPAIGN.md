# Predeclared record-receipt comparison

Scope: synthetic immutable records already available together, one producer
key/context. Compare per-record ES256 signatures, one ES256 signed hash list,
and one ES256 signed Merkle root with detached inclusion receipts. Same cached
OpenSSL CPU signer, public-key construction and record bytes for all modes.

Primary sizes: 64 and 1024 records, five repeats. Held-out size: 257 records,
three repeats, run after primary with no implementation selection in between.
Consumption: one record, one quarter, all. Recipient modes: one verifier with
within-cell cache reuse, or independently constructed verifier for every
record. Shuffle approaches per scenario with a fixed recorded seed.

Time producer hashing/sealing (including all Merkle proof construction),
selected receipt serialization, and independent consumer parsing/signature/
inclusion verification. Total is their sum; key generation, fixture creation,
network/disk, batch formation and application policy are excluded. Verification
must accept every selected record and reject changed bytes. Baselines bind the
same context, record count and expected index. Producer always seals the entire
batch, including unused records. Cache starts empty for each measured cell.

For shared recipients, actually serialize/parse the batch manifest once and
send proof/index envelopes for Merkle and hash-list modes. Individual signatures
remain separate. For fresh recipients, include the full signed manifest in each
receipt. Use compact base64url hashes in both reference alternatives. Record
exact metadata bytes for the timed serialization, excluding record bodies and
transport headers. These are not measured network traffic. Do not mix cached
consumer timing with a claim about distinct recipients. Signed lists commit all hashes and can reveal
more metadata; proofs still do not guarantee confidentiality.

Budget: CPU only, no external service, no GPU or spend; <=5 minutes timed work.
Stop on correctness failure and preserve partial output. No speed threshold is
an acceptance criterion for the interface. Report medians and conservative
min-baseline/max-candidate total-time ratios; retain individual cells, source
hashes, platform/runtime/OpenSSL and run order. No hardware-cost/ROI claim.
