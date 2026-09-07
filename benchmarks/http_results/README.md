# HTTP access captures

- `rtx3060-http-v1-interrupted.json`: 47 completed cells; the next GPU idle
  preflight stopped the run. `complete` remains false. Retained for transparency,
  excluded from the complete campaign report. Source `245065e20cdb44ecf713ea7426ade57d725520a7`.
- `rtx3060-http-v2.json`: complete rerun under the same shuffled workload schedule
  after adding a bounded ten-second wait for three consecutive idle observations.
  The measured transaction path and correctness requirements are unchanged.
  [Campaign and change record](../HTTP_ACCESS_CAMPAIGN.md).

Host: Windows 11, AMD Ryzen 7 7800X3D, 16 logical CPUs. Selected device:
RTX 3060 12 GB, `GPU-130bba5c-4480-7ba8-4ef5-c6789117f3e3`, runtime index 1.
NVIDIA driver 610.62 observed before the campaigns. The RTX 4070 Ti at index 0
was left available to unrelated work; all-GPU samples and host-wide CPU load
are retained in each capture. These are shared-host observations.

Native SHA-256: `970538e7711828afb165b0220e78a081bf417db591168261b6de073f286ebdb2`.
Fresh R01 build from `8f47e258165b25397877b265cc92265c3b7ca3f1`; Visual Studio
2022, CUDA 13.0.88, architecture 86. `git diff` confirmed no changes in `src/`,
`include/` or root `CMakeLists.txt` between that source and the HTTP campaign.
The complete 73-test suite passed with this DLL on the RTX 3060, including
the native crypto tests, guard/epoch tests and HTTP GPU integration.

Reproduce using your built native library and matching build metadata:

```sh
python -m pip install '.[interop]'
python benchmarks/run_http_access.py --output dist/http-capture.json --library PATH_TO_LIBRARY --gpu-uuid GPU_UUID --library-source-commit BUILD_COMMIT --library-build-note "Compiler; CUDA version; architecture"
```

No prices were guessed. Both hourly price inputs are null in the archived runs.
Synthetic account units are accounting fixtures, not GPU cost or actual revenue.
Each capture contains individual content/receipt-checked completion timings,
outcomes, counters and before/after ledger balances. Secret keys, bearer secrets
and generated credentials are not published.

## Overhead follow-up

- `overhead-diagnostic-v1.json`: three instrumented diagnostic waves. Phase
  timers overlap; their sums are not a serial wall-time breakdown.
- `overhead-comparison-v1.json`: incomplete, stopped after 56 cells on one
  client `OSError`, before publisher admission. All 8,383 delivered accesses
  reconcile; the failed intended access remains in its denominator. The exact
  OS error code was not recorded, so its underlying cause is unknown. Pool
  performance was worse in observed full waves; it was not promoted.
- `overhead-confirmation-v1.json`: complete 72-cell baseline/batch-cleanup
  confirmation on 32 eight-item books, two clients, three repeats. All 7,704
  accesses reconcile; 4,515 are late. Connection policy and per-access FULL
  commits are identical; both variants include final checkpoint cost.

[Generated report](../../docs/HTTP_OVERHEAD_RESULTS.md) and
[decision/campaign record](../HTTP_OVERHEAD_CAMPAIGN.md) retain failures,
rejected candidates, source hashes and interpretation limits. The confirmation
uses the same RTX 3060 DLL hash/build above, with host load and GPU observations
recorded per cell. No CPU/GPU dollar price is inferred.
