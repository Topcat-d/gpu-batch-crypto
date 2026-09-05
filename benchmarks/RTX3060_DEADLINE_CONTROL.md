# RTX 3060 deadline control — September 5, 2026

This bounded extension was selected after the first 10 ms sweep and early
reverse-order cells missed the deadline in both modes. It is committed before
any 50 ms capture. The original [campaign](RTX3060_CAMPAIGN.md) remains intact;
its unfavorable cells are retained and its criterion is not changed.

Question: can this shared host deliver the same 40,000 requests/s with a
50 ms request budget, and what CPU demand and cost coefficients result?
Both 10 ms and 50 ms are experimental assumptions, not a user-provided SLA.
Only `--slo-ms` changes relative to the one-key, 8-worker, batch-64 case.
Expiration naturally changes with the budget; this is a pipeline-policy
experiment, not a post-hoc relabeling of the earlier latency samples.

Fixed: device 1, target-GPU preflight, 8 workers, one key, offered 40k/s,
maximum/minimum GPU batch 64, 1 ms fill wait, caller dispatch, same binaries,
synthetic 512-byte records and all-output CPU verification. Shared CPU and
other-GPU activity remain recorded; no exclusive-host assumption is added.

- Repeat 1: CPU then hybrid, 30 seconds each.
- Repeat 2: hybrid then CPU, 30 seconds each.
- Timed budget: 120 seconds; allow up to four minutes including preflight
  and setup. No rental, extra GPU or parameter search.
- Deadline quality requires at least 99% of all offered requests within
  50 ms in each mode in both repeats, with the original correctness and
  accounting gates. Report every row regardless of outcome.

Use `benchmarks/run_pipeline.py` with the standard pinned executable and DLL
arguments plus:

```text
--device 1 --preflight-scope target-gpu --workers 8 --keys 1 --rates 40000
--batch 64 --gpu-min 64 --gpu-dispatch caller --slo-ms 50 --seconds 30
```

Repeat 1 uses `--modes cpu,hybrid` and
`benchmarks/pipeline_results/rtx3060-slo50-20260905-r1.json`.
Repeat 2 uses `--modes hybrid,cpu` and
`benchmarks/pipeline_results/rtx3060-slo50-20260905-r2.json`.

Do not infer savings from more relaxed deadlines alone. Compare CPU and
hybrid at the same 50 ms budget, show the actual GPU share and process CPU
seconds, and keep total hourly cost as an explicit input. Two short repeats
under background load do not establish deployment capacity or an SLA.
