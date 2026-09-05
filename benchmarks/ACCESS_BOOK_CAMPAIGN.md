# Funded access book experiment

Predeclared comparison: CPU ES256 signing with cached OpenSSL keys, PyJWT
acceptance, and a local SQLite WAL ledger with `synchronous=FULL`. No GPU is
needed to test whether removing repeated work improves this application.

Compare an **on-demand single-item grant** with planned books of 8, 32, 128
and 256 exact resources. All use the same engine, buyer, publisher, prices,
signature policy, per-resource accounting and durable commit settings. The
single-item baseline only issues grants that will be consumed. Books reserve
their full plan, including unused items, then release unused funds. This
penalizes speculative books rather than charging the baseline for work it
can avoid. Two consumption fractions (100%, 25%), two opposite-order
repeats, 2,048 planned resources per cell: **20 cells**. A deterministic
25% subset takes every fourth resource. The trusted catalog has 256 entries;
independent accesses reuse these fixtures across books. One synthetic buyer,
one publisher, one process/thread, no offered-load/concurrency claim.

Measure issue, admission, all redemptions and unused-reservation release.
Include JSON, signing, verification, SQL, durable commits and Python overhead.
Record every completed redemption's elapsed time from its book becoming ready,
its individual redemption-call time, first-access latency, process CPU time,
signature/verification/transaction counts, token bytes and final conservation
audit. A fixed 256-resource warmup on a separate database precedes each cell.
Key/catalog/database setup, audit, connection teardown and file cleanup are
outside timing. Keep all repeats and failures; do not select a favorable run.

Use a fresh local temporary SQLite file for every cell. Record source hashes,
commit, Python/OpenSSL/PyJWT/SQLite versions, platform, CPU and logical CPUs.
Storage is the local temporary directory on the maintainer's shared Windows
host. WAL/FULL is a configuration, not proof of power-loss durability on this
hardware. Concurrency and transaction rollback/restart have separate tests.

No HTTP, TLS, identity authentication, content transfer, actual money, payment
fees, expiry daemon, settlement, replicas, publisher onboarding or buyer
willingness to pay are measured. Results characterize this original evaluation
example, not a tuned database service or the maximum capacity of the CPU.
No multiplication of this result by GPU primitive rates is valid.
