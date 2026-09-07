# HTTP service overhead: bounded experiment

Baseline source is the HTTP reference at `e30eff2`. The previous complete
48-cell capture is retained; fresh controls are required to compare changes.

Question: can reducing connection lifecycle and cleanup overhead improve
whole-wave latency/cost without changing authentication, required signatures,
per-access durable commits or receipt recovery? No GPU speedup is presumed.

Budget: one diagnostic pass, at most two implementation changes, one comparison
and one confirmation/holdout. At most 10 minutes of timed application work;
no rental, real funds, external traffic or changes to private projects. Stop
on correctness/accounting failure, unavailable GPU or gains within noise.

Before choosing the first change, profile one direct full-use wave, one CPU-book
full-use wave and one CPU-book quarter-use wave, with four clients/signing
workers. Optional phase timers cover SQLite open/begin/body/commit/close,
issuance signing, publisher verification and both HTTP request hops. Phase
sums overlap and can run concurrently: never add them into a serial wall-time
breakdown. This diagnostic is not a performance promotion comparison.

Candidate 1: reuse connections if the observations justify it. Select the
connection boundary from the diagnostic; preserve the one-authoritative-ledger
contract and `synchronous=FULL`. Any deferred final checkpoint/drain must be
included in the measured cost. Candidate 2: cancel a bounded set of unused
books through one authenticated RPC/transaction, retaining exact retry
results, all-or-nothing scope checks and zero outstanding reservations.

Measure the original connection/cleanup behavior, candidate 1, and candidate 1
plus candidate 2 with identical instrumentation and deterministic shuffled
order. Keep all outcome denominators from the original HTTP campaign: one-
second deadline from request readiness, all intended accesses, full wall time
including planning and cleanup, simulated ledger reconciliation and every
required GPU output/consumer check. CPU retains 1/4 signing-worker controls;
GPU runs only on the idle RTX 3060 UUID, with three <=5% preflight observations.

Promote only after recovery, concurrency, expiry, revocation, budget and rollback
tests pass and a three-repeat control/comparison shows a useful gain. Confirm
the baseline and selected candidate with a different batch size (32 books of
eight items) and two clients. Record individual timings, source and native
hashes, host load, observed GPU activity and final checkpoint/cleanup costs.
Prices remain explicit optional inputs; no provider quote is inferred.
