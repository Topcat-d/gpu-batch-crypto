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

## Diagnostic and fixed comparison

The [diagnostic capture](http_results/overhead-diagnostic-v1.json), source
`cd29e4c`, observed median SQLite setup of 5.12 ms per operation in the CPU-book
full wave, versus 2.78 ms for its entire 64-signature issuance batch. Begin/lock
wait p95 was 35.40 ms. These are overlapping observations, not percentages of
wall time. They justify testing the database boundary first; HTTP transport
reuse is deferred in this bounded pass.

The fixed variants are `baseline` (one connection/operation, individual cleanup),
`pool` (four exclusively leased connections, individual cleanup), and
`pool-batch` (the same four connections, one atomic cancellation RPC). HTTP
connections remain unchanged. Initial pool/key/listener creation and warmup
are excluded for all variants; the final WAL checkpoint/drain is included for
every variant before stopping the cost clock. FULL durable commits remain
per access. No spend transactions are batched or moved outside timing.

Comparison: two workloads (64 books x four resources, full and quarter use),
all three variants, direct / CPU 1 worker / CPU 4 workers / guarded GPU,
three repeats with shuffled seed 20260907, four buyer clients: 72 cells with
GPU, 54 without. All variants run with phase timing enabled. Promote only if
the gain repeats, large-wave deadline misses do not increase, and scope/recovery
tests pass. Compare both complete throughput and deadline goodput; the latter
can grow more sharply because late completions move inside the deadline.

Confirmation after selection: baseline versus `pool-batch`, 32 books x eight
resources at full and quarter use plus a one-access urgent control; two clients,
the same four crypto paths and three repeats with seed 20260908. This is a
72-cell holdout when GPU is available. Do not describe single-access p99 as a
stable tail estimate or select CPU worker count from just one favorable repeat.

Commands: `python benchmarks/run_http_overhead.py --stage comparison --output dist/http-overhead.json`
and the same command with `--stage confirmation` and a new output file. To
include GPU, add `--library PATH --gpu-uuid UUID --library-source-commit COMMIT
--library-build-note "compiler; CUDA; architecture"`. No cloud spend is needed.

## Stop and confirmation decision

The comparison stopped after 56 cells on one failed client `OSError` before
publisher admission, with balanced accounting. The capture remains incomplete
and includes the failed observation. It retained only the exception class, so
the OS cause is unknown; a post-run dynamic-port query is not proof of port
exhaustion. Subsequent captures retain errno/winerror/HTTP status too. Transport
and retry policy are unchanged. No failed observation is converted to success.

The pool is **rejected for promotion**: available full-use comparisons were
slower, with larger SQLite begin/lock-wait tails. The incomplete campaign is
diagnostic evidence, not a completed performance acceptance test. Batched
cleanup reduced cleanup work within the same pool configuration, so confirmation
now isolates that existing change with original per-operation connections:
`--stage confirmation --candidate batch`. No new optimization is introduced.
The held-out workload, two clients, three repeats, deadline, checkpoint cost
and seed remain as declared. Baseline and batch-only full/urgent paths execute
the same operations; their observed variation must not be described as a
full-use acceleration. Keep this decision recorded before confirmation.
