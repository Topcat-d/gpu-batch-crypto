# Ready-wave token service: measured results

Generated from the complete [raw capture](../benchmarks/ready_wave_results/rtx3060-2026-09-05.json). The [campaign plan](../benchmarks/READY_WAVE_CAMPAIGN.md), [standard-token compatibility](COMPATIBILITY.md) and [reproduction script](../benchmarks/run_ready_wave.py) define the experiment.

**84 cells; 7,888,793 timed tokens independently verified on CPU.** NVIDIA GeForce RTX 3060, 610.62, 12288 MiB, 00000000:06:00.0. CPU: AMD Ryzen 7 7800X3D 8-Core Processor. Four/eight workers, two repeats in opposite mode order, three seconds per cell. This is a shared host with an idle selected GPU at each preflight, not exclusive capacity.

The workload is a sequence of already-ready waves. Completion requires constructing claims, encoding the signing input, signing, compact token encoding/decoding and checking every output against a CPU public key. There is no arrival-driven fill delay. General JWT parsing/claim policy, network/TLS, identity, ledger, settlement, key setup and warm-up are excluded. PyJWT checks sampled native tokens outside the timer; live compatibility tests check expiry and issuer/audience separately.

## Cost ceiling against the stronger observed CPU setting

For each wave, CPU is the faster eligible four/eight-worker setting. Hybrid is the eligible setting with the faster *slower repeat*. Ratios divide that slower hybrid repeat by the faster CPU repeat, retaining run-order variability. Eligibility requires at least 99% of tokens within 50 ms in both repeats. A candidate also needs actual GPU use and a ratio above 1.05, as declared before measurement.

| Wave / keys | CPU / hybrid workers | CPU upper / hybrid lower goodput/s | Conservative ratio | Maximum extra GPU cost / CPU host cost | Candidate? |
|---|---|---:|---:|---:|---|
| 1 / 1 | 4 / 4 | 5,315 / 5,250 | 0.988 | No positive ceiling | No GPU used |
| 8 / 1 | 8 / 8 | 22,569 / 21,261 | 0.942 | No positive ceiling | No GPU used |
| 64 / 1 | 8 / 8 | 42,218 / 26,697 | 0.632 | No positive ceiling | No: below 1.05 ratio |
| 256 / 1 | 8 / 8 | 58,168 / 49,178 | 0.845 | No positive ceiling | No: below 1.05 ratio |
| 1024 / 1 | 8 / 8 | 59,989 / 63,084 | 1.052 | 5.2% | Yes, within measured scope |
| 4096 / 1 | — | — | — | — | No: missing quality pass |
| 4096 / 16 | — | — | — | — | No: missing quality pass |

**1 wave/key settings meet the candidate rule.** These are finite-run bounds for this cryptographic service. Cost savings require the full allocated hybrid/CPU hourly-price ratio to be below the reported throughput ratio. They are not measured electricity bills, cloud savings or publisher revenue.

If CPU host allocation costs C per hour and adding the GPU costs G, the break-even condition is `G/C < ratio - 1`. Count the CPU host once. Include device capital/rental, idle allocation, electricity and operational overhead in G; an unused owned card is not automatically free. For a mode with on-time goodput Q and total allocation H/hour, `cost per million = 1e6*H/(3600*Q)`. The [economics inventory](ECONOMICS.md) keeps provider scenarios and owned-hardware inputs separate.

## Ed25519 algorithm-choice comparison

This is a comparison between separately accepted protocols. An Ed25519-only consumer cannot accept the ES256 result without an explicit protocol change. Both sign the same claims; Ed25519 signs the complete JOSE input, while ES256 uses SHA-256. Both include all-output CPU verification.

| Wave / keys | Best eligible Ed25519 upper goodput/s | Eligible ES256 hybrid lower / Ed25519 ratio |
|---|---:|---:|
| 1 / 1 | 4,676 | 1.123 |
| 8 / 1 | 16,806 | 1.265 |
| 64 / 1 | 27,008 | 0.988 |
| 256 / 1 | 36,392 | 1.351 |
| 1024 / 1 | — | No matched quality pass |
| 4096 / 1 | — | No matched quality pass |
| 4096 / 16 | — | No matched quality pass |

## Adding an unchanged downstream stage

The following is a **model**, not another measurement. Add the same fixed serial delay to every recorded wave, add its time to the elapsed denominator, and re-evaluate the 50 ms quality gate. It assumes the added work does not change the measured crypto times through contention. A database, network or policy service must be measured to establish that assumption; variable latency and resource competition can make it fail.

| Candidate wave / keys | +0 ms ratio | +1 ms ratio | +5 ms ratio | +20 ms ratio |
|---|---:|---:|---:|---:|
| 1024 / 1 | 1.052 | 1.049 | 1.039 | Quality fails |

## Both repeats, including failed settings

Ranges are two observations, not confidence intervals. Each token in a wave shares its completion time because the complete wave is verified before release. CPU time includes the native main thread and workers; parent telemetry is outside that counter. A hybrid cell with 0% GPU share is a CPU routing control. Configurations, synthetic records, stage barriers and lack of overlapping waves constrain transfer to other services.

| Wave / keys | Mode | Workers | Tokens/s | p99 ms | Within 50 ms | GPU share | Process CPU s | Both pass? |
|---|---|---:|---:|---:|---:|---:|---:|---|
| 1 / 1 | cpu-eddsa | 4 | 3,856–4,454 | 0.67–0.94 | 100.00–100.00% | 0% | 2.30–2.38 | Yes |
| 1 / 1 | cpu-es256 | 4 | 4,994–5,315 | 0.57–0.78 | 100.00–100.00% | 0% | 2.06–2.38 | Yes |
| 1 / 1 | hybrid-es256 | 4 | 5,250–5,759 | 0.55–0.68 | 100.00–100.00% | 0% | 2.47–2.50 | Yes |
| 1 / 1 | cpu-eddsa | 8 | 4,237–4,676 | 0.49–0.67 | 100.00–100.00% | 0% | 2.53–2.61 | Yes |
| 1 / 1 | cpu-es256 | 8 | 5,133–5,293 | 0.61–0.71 | 100.00–100.00% | 0% | 2.19–2.38 | Yes |
| 1 / 1 | hybrid-es256 | 8 | 5,088–5,348 | 0.48–0.56 | 100.00–100.00% | 0% | 2.23–2.42 | Yes |
| 8 / 1 | cpu-eddsa | 4 | 14,455–16,437 | 0.89–1.33 | 100.00–100.00% | 0% | 7.62–7.73 | Yes |
| 8 / 1 | cpu-es256 | 4 | 19,812–20,739 | 0.94–0.98 | 100.00–100.00% | 0% | 7.22–7.70 | Yes |
| 8 / 1 | hybrid-es256 | 4 | 18,232–21,034 | 0.93–1.34 | 100.00–100.00% | 0% | 6.64–7.41 | Yes |
| 8 / 1 | cpu-eddsa | 8 | 14,132–16,806 | 1.23–1.80 | 100.00–100.00% | 0% | 9.28–12.98 | Yes |
| 8 / 1 | cpu-es256 | 8 | 20,536–22,569 | 0.90–1.09 | 100.00–100.00% | 0% | 10.19–10.44 | Yes |
| 8 / 1 | hybrid-es256 | 8 | 21,261–21,865 | 0.93–1.18 | 100.00–100.00% | 0% | 9.78–10.45 | Yes |
| 64 / 1 | cpu-eddsa | 4 | 17,819–20,759 | 8.32–8.42 | 100.00–100.00% | 0% | 8.38–9.17 | Yes |
| 64 / 1 | cpu-es256 | 4 | 32,165–32,641 | 3.33–3.62 | 100.00–100.00% | 0% | 8.88–9.77 | Yes |
| 64 / 1 | hybrid-es256 | 4 | 22,718–23,832 | 3.69–4.00 | 100.00–100.00% | 100% | 5.95–6.55 | Yes |
| 64 / 1 | cpu-eddsa | 8 | 26,226–27,008 | 4.83–5.11 | 100.00–100.00% | 0% | 13.89–15.56 | Yes |
| 64 / 1 | cpu-es256 | 8 | 41,615–42,218 | 3.34–3.85 | 100.00–100.00% | 0% | 13.77–14.97 | Yes |
| 64 / 1 | hybrid-es256 | 8 | 26,697–27,667 | 3.22–3.84 | 100.00–100.00% | 100% | 6.94–7.97 | Yes |
| 256 / 1 | cpu-eddsa | 4 | 22,461–23,701 | 15.36–16.66 | 100.00–100.00% | 0% | 10.17–10.39 | Yes |
| 256 / 1 | cpu-es256 | 4 | 32,595–37,800 | 9.74–13.48 | 100.00–100.00% | 0% | 9.69–9.84 | Yes |
| 256 / 1 | hybrid-es256 | 4 | 37,566–39,397 | 8.20–11.20 | 100.00–100.00% | 100% | 8.52–8.53 | Yes |
| 256 / 1 | cpu-eddsa | 8 | 30,988–36,392 | 10.29–13.52 | 100.00–100.00% | 0% | 14.95–18.78 | Yes |
| 256 / 1 | cpu-es256 | 8 | 53,013–58,168 | 7.15–9.55 | 100.00–100.00% | 0% | 16.73–18.00 | Yes |
| 256 / 1 | hybrid-es256 | 8 | 49,178–53,051 | 7.77–10.92 | 100.00–100.00% | 100% | 12.47–14.05 | Yes |
| 1024 / 1 | cpu-eddsa | 4 | 23,006–23,088 | 62.48–65.87 | 85.29–88.24% | 0% | 10.45–10.55 | No |
| 1024 / 1 | cpu-es256 | 4 | 35,614–40,162 | 33.83–46.91 | 99.05–100.00% | 0% | 10.31–10.84 | Yes |
| 1024 / 1 | hybrid-es256 | 4 | 43,613–48,194 | 33.05–38.49 | 99.22–100.00% | 100% | 9.59–10.55 | Yes |
| 1024 / 1 | cpu-eddsa | 8 | 30,545–34,876 | 50.29–56.79 | 97.09–98.89% | 0% | 17.09–18.23 | No |
| 1024 / 1 | cpu-es256 | 8 | 56,728–59,989 | 27.12–33.49 | 100.00–100.00% | 0% | 17.91–18.77 | Yes |
| 1024 / 1 | hybrid-es256 | 8 | 63,084–65,349 | 23.88–33.29 | 100.00–100.00% | 100% | 14.88–16.81 | Yes |
| 4096 / 1 | cpu-eddsa | 4 | 19,462–22,356 | 258.02–288.68 | 0.00–0.00% | 0% | 10.22–11.05 | No |
| 4096 / 1 | cpu-es256 | 4 | 36,137–40,854 | 117.17–139.39 | 0.00–0.00% | 0% | 10.30–10.77 | No |
| 4096 / 1 | hybrid-es256 | 4 | 47,176–51,834 | 93.92–97.00 | 0.00–0.00% | 100% | 10.25–10.72 | No |
| 4096 / 1 | cpu-eddsa | 8 | 28,301–37,033 | 172.09–224.61 | 0.00–0.00% | 0% | 16.69–20.17 | No |
| 4096 / 1 | cpu-es256 | 8 | 47,417–67,498 | 88.86–100.63 | 0.00–0.00% | 0% | 16.09–20.33 | No |
| 4096 / 1 | hybrid-es256 | 8 | 66,821–81,549 | 77.00–100.99 | 0.00–71.67% | 100% | 15.92–19.69 | No |
| 4096 / 16 | cpu-eddsa | 4 | 19,503–23,581 | 238.92–252.48 | 0.00–0.00% | 0% | 10.14–11.25 | No |
| 4096 / 16 | cpu-es256 | 4 | 30,037–31,361 | 160.36–228.49 | 0.00–0.00% | 0% | 9.47–9.52 | No |
| 4096 / 16 | hybrid-es256 | 4 | 37,266–43,004 | 113.83–138.88 | 0.00–0.00% | 100% | 8.55–9.42 | No |
| 4096 / 16 | cpu-eddsa | 8 | 27,701–28,193 | 221.72–226.51 | 0.00–0.00% | 0% | 15.70–15.89 | No |
| 4096 / 16 | cpu-es256 | 8 | 47,780–51,352 | 104.20–179.20 | 0.00–0.00% | 0% | 16.38–16.64 | No |
| 4096 / 16 | hybrid-es256 | 8 | 43,779–53,477 | 95.03–137.41 | 0.00–0.00% | 100% | 11.28–13.98 | No |

These ready-wave measurements do not replace the earlier [constant-arrival pipeline results](RTX3060_PIPELINE.md). No real AI planning, independent model work, requests over a network, or account settlement was timed. Deployment requires accepted protocol/keys, representative traffic, allocation prices and the [documented security boundary](PRODUCTION_READINESS.md). The GPU arithmetic remains secret-dependent.

## Reproduce and audit

Measured source commit: `d02ee913356ed5bbfa70524cd498264ba4f444c1`. [Build fingerprints](../benchmarks/ready_wave_build.json), [raw checksums](../benchmarks/ready_wave_results/SHA256SUMS), [CSV](../benchmarks/ready_wave.csv).

```sh
python -m pip install '.[interop]'
python benchmarks/verify_ready_wave.py
python benchmarks/report_ready_wave.py --check
```
