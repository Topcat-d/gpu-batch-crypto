# RTX 3060 shared-host measurement plan — September 5, 2026

This plan is committed before the captures. The purpose is to measure useful
request goodput, latency and CPU demand on the locally available RTX 3060,
including verification of every signature before releasing a batch. This is
an owned-hardware experiment with no cloud rental or assumed purchase price.

## Conditions and hypothesis

Device 1 reports NVIDIA GeForce RTX 3060, 12 GB, display disabled. Device 0
(RTX 4070 Ti) has unrelated active work. Both share a Ryzen 7 7800X3D with
16 logical CPUs. Initial preflight observed roughly 53–60% aggregate CPU load.
No other work is stopped, and CPU cores are not reserved. These measurements
describe the recorded shared-host conditions, not exclusive-machine capacity.

Hypothesis: at a compatible-key arrival rate sufficient to form batches, GPU
signing can reduce CPU signing work; verification, scheduling and shared CPU
load may still dominate request latency and prevent an economic advantage.
The multi-threaded CPU baseline performs the same preparation, deterministic
low-s signing and all-output verification as the hybrid path.

Fixed settings: 512-byte synthetic records, full-window P-256 backend, maximum
batch 64, GPU minimum 64, 1 ms maximum intentional batch wait, caller dispatch,
queue capacity 8,192, and an **assumed 10 ms request budget**. This budget is an
experiment parameter, not a user-provided SLA. No kernel, dispatcher or key
policy changes are made during this campaign.

## Bounded runs

1. Repeat 1: 4 and 8 workers; 1 key; offered 10k, 20k and 40k requests/s;
   CPU then hybrid for each pair; 10 seconds/cell (12 cells).
2. Repeat 2: same matrix, hybrid then CPU (12 cells).
3. Longer check: 8 workers; 1 and 16 keys; offered 40k/s; CPU then hybrid;
   30 seconds/cell (4 cells). This checks duration and key fragmentation at
   a fixed offered load, rather than selecting only a favorable short cell.

Total native timed work: 360 seconds; allow up to 12 minutes including
preflight, warm-up and capture. One process runs at a time. No background
builds or test suites are started by this task during measurement. All cells,
including overload or unfavorable outcomes, are retained. A capture failure
is investigated before any bounded retry; partial data cannot be promoted.

Each cell requires three observations of device 1 at no more than 5% GPU
utilization before launch (`--preflight-scope target-gpu --device 1`). All GPU
telemetry and aggregate system CPU counters are recorded before and during
each cell. This explicitly permits the shared CPU and other GPU to be busy.
It does not weaken the default all-GPU preflight for other users.

## Acceptance and reporting

Correctness requires exact CPU/GPU warm-up agreement, CPU verification of
every completed signature, zero failed requests, exact outcome accounting,
consistent latency and batch histograms, and source/binary fingerprints.
Expired, rejected and late requests remain visible and reduce useful goodput.

A scenario qualifies for a tentative deadline comparison only if at least
99% of **all offered requests** finish within 10 ms in both short repeats.
The longer run is reported separately and must also pass for a sustained
claim at 40k/s. Two short repeats do not establish a confidence interval,
production SLA, hardware ranking, or causal isolation from background work.

Report each repeat and the observed range, actual GPU fraction, p99 among
verified requests, deadline success among all offered requests, process CPU
seconds, and host telemetry. Show CPU and hybrid cost-per-million coefficients
per dollar of fully allocated hourly system cost. A measured goodput ratio
is only conditional break-even arithmetic, not a savings claim when quality
fails or the shared-host conditions differ materially. GPU board power is
not wall-system power; purchase price, energy and allocation remain inputs.

Commands use `benchmarks/run_pipeline.py` with the existing pinned binaries:

```text
common: --device 1 --preflight-scope target-gpu --batch 64 --gpu-min 64
        --gpu-dispatch caller --slo-ms 10
r1: --seconds 10 --workers 4,8 --keys 1 --rates 10000,20000,40000 --modes cpu,hybrid
r2: --seconds 10 --workers 4,8 --keys 1 --rates 10000,20000,40000 --modes hybrid,cpu
long: --seconds 30 --workers 8 --keys 1,16 --rates 40000 --modes cpu,hybrid
```

Capture names: `rtx3060-target-20260905-r1.json`,
`rtx3060-target-20260905-r2.json`, and `rtx3060-target-20260905-long.json` in
`benchmarks/pipeline_results/`. Exact executable arguments, source commit,
hashes and timestamps are embedded in each JSON record.
