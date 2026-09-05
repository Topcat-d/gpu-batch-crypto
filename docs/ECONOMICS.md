# Costing the published benchmarks

The existing captures can support **cost per primitive operation at an explicit price**. A production decision additionally needs the complete system's goodput within a deadline, utilization and availability costs. These are different denominators; a fast signature alone is not a delivered authorization or a payment.

## Hardware and price inventory

The maintainer identifies Runpod, Phala and Lambda as providers used during development. The public captures do not establish a reliable provider-to-run mapping or historical invoice. The inventory therefore preserves the actual GPU and marks pricing as a separate scenario. No new rental is needed for this arithmetic.

| Documented hardware | Published evidence | Price input and missing information |
|---|---|---|
| A100-SXM4-40GB | July 9 and July 16 persistent-engine runs; July 16 P-256 110,200/s and AES-GCM 399,446/s | Actual provider, region, rental duration and invoice remain unconfirmed. Lambda's current **1-GPU A100 SXM 40 GB** listing is a model-matched scenario. |
| L40S 48 GB | July 7 EPYC 7702 diagnostics; later EPYC 9354 campaign; direct and scheduler captures kept separate | Actual bill and host allocation remain unconfirmed. Current Runpod L40S pricing is a model-matched scenario. |
| RTX 4070 Ti | Historical full-window/sweep and current standalone library measurements on the local Ryzen 7 7800X3D host | Owned-hardware model: actual capital cost, lifetime, operating hours and **wall-system power** are inputs. No rental rate is invented. |
| RTX 3060 | Historical full-window and current standalone library measurements on the same local host | Same owned-hardware inputs; assign shared CPU/RAM cost once. |
| Phala configuration | Provider usage reported; no matched configuration established in these published captures | Recover GPU model, CPU allocation, confidential-computing mode if any, date and bill before assigning a rate. |

As observed September 5, 2026, Lambda lists one A100 SXM 40 GB with 30 vCPUs, 220 GiB RAM and 512 GiB SSD at **$1.99/hour**, excluding tax. This does not prove the old benchmark ran on that instance. [Lambda instance pricing](https://lambda.ai/instances).

Runpod's displayed L40S configuration has 48 GB GPU memory, 16 vCPUs and 94 GB RAM at **$0.99/hour**. Confirm cloud tier, region, availability and separately billed storage when using the estimate. Its A100 SXM listing is **80 GB**, so that listing is not applied to the archived 40 GB result. [Runpod GPU configurations](https://www.runpod.io/product/cloud-gpus).

Phala's price is left unset because a matching historical instance and billing scope are not established. A provider's confidential-computing product does not make this library an attested or isolated signer. [Phala pricing](https://phala.com/pricing). Machine-readable assumptions are in [pricing-20260905.json](../benchmarks/pricing-20260905.json).

## Reuse the historical results without overstating them

For a measured primitive rate `R` and an allocated compute price `H` dollars/hour:

```text
continuous-work cost per million = H × 1,000,000 / (3,600 × R)
```

| Capture and operation | Recorded operations/s | Cost per million for each $1/hour | Current model-matched price scenario | Estimated compute $/million |
|---|---:|---:|---:|---:|
| A100 July 16, P-256 | 110,200 | 0.002521 | $1.99/h | 0.005016 |
| A100 July 16, AES-GCM, 16-byte plaintext | 399,446 | 0.000695 | $1.99/h | 0.001384 |
| L40S later campaign, direct P-256 | 101,024 | 0.002750 | $0.99/h | 0.002722 |
| L40S July 7, direct AES-GCM run 1, 16 bytes | 384,836 | 0.000722 | $0.99/h | 0.000715 |
| L40S July 7, scheduled AES-GCM, pack 64 | 190,293 | 0.001460 | $0.99/h | 0.001445 |
| L40S July 7, scheduled P-256, pack 64 | 13,362 | 0.020789 | $0.99/h | 0.020581 |

These are calculations from [historical accepted captures](HISTORICAL_BENCHMARKS.md), assuming continuous work at the recorded rate. They are **not historical charges, new cloud measurements, an SLO guarantee, or whole-service prices**. The historical oracle sampled 256 outputs rather than verifying every output inside the timed workload. The A100 captures do not contain request-latency distributions. L40S pack-64 P-256 recorded p99 56.311 ms; its throughput cannot be called 10 ms goodput. Rejected accounting runs remain excluded.

For example, the recorded A100 signing interval lasted 30 seconds. At an assumed $1.99/hour that interval costs $0.01658 and covers 3,306,000 recorded signatures. If the rental actually stayed alive for 30 minutes to provision, build, test and run, the compute bill at that assumed rate would be $0.995. Dividing only the 30-second slice into the whole invoice would misstate the experiment's cost.

```sh
python benchmarks/economics.py --scope primitive --hourly 1.99 --rate 110200
python benchmarks/economics.py --scope primitive --hourly 1.99 --rate 110200 --billing-seconds 1800 --successful-operations 3306000
```

## Whole-system comparison

Use the [native pipeline measurements](PIPELINE_RESULTS.md) for the additional cost of CPU preparation, batching, signing and **verification of every signature before completion**. The harness records offered, rejected, expired, failed, late and within-SLO requests. Its denominator is `within_slo / elapsed_seconds`, including drain time, not raw signatures/s.

The [RTX 3060 follow-up](RTX3060_PIPELINE.md) adds repeated 10 ms trials, longer one/sixteen-key checks and a separate 50 ms control on the owned card. It publishes cost coefficients per dollar of allocated hourly system cost, process CPU demand and observed host load. None of the six paired short-run settings met the 10 ms quality criterion in both modes and repeats. The sixteen-key hybrid run used CPU for every signature, showing why a hybrid label alone cannot justify paying for a GPU. Actual hardware allocation and wall-power inputs remain necessary to turn the coefficients into owned-system costs.

```text
cost per million within-SLO requests = total hourly system cost × 1e6 / (3600 × goodput)
break-even total hybrid/CPU hourly cost ratio = hybrid goodput / CPU goodput
```

Compare the same workload, SLO, key distribution, security checks and provisioned CPU budget. Require an acceptable fraction of offered requests to meet the SLO before using a goodput ratio for sizing; an overloaded system that loses almost every deadline is not a viable deployment. At light load both paths may serve all arrivals, so their goodput ratio is approximately one even if one has spare capacity. CPU-seconds and capacity headroom inform sizing but do not automatically reduce a billed instance's price.

Include the allocated CPU/GPU host, RAM, disk, networking, idle capacity, replicas and support/operations costs. Do not add CPU cost a second time when the instance price already includes those CPUs. Do not scale throughput linearly across eight GPUs from a single-GPU result. No network, TLS, authentication, payment settlement or multi-host redundancy is implemented in this benchmark.

## Owned cards and utilization

```text
owned system $/hour = (purchase − residual value) / (years × annual operating hours)
                      + wall-system kW × electricity $/kWh
                      + allocated cooling, hosting and operations $/hour
```

`owned_hourly` in [economics.py](../benchmarks/economics.py) implements this model. GPU TDP is not measured wall power. For the two local RTX cards, purchase price, lifetime and power remain user inputs; zero rental charge is not zero economic cost.

If a permanently allocated machine works at the benchmark rate only 25% of its paid lifetime and is otherwise idle, the simple duty-factor estimate is four times the continuous-work cost. This assumes busy intervals retain the measured rate; it does not predict low-arrival batching behavior. When goodput already measures the actual traffic and idle interval, use utilization 1 to avoid counting idle time twice.

To turn the scenarios into actual historical costs, attach a redacted price/billing record containing provider, exact GPU variant/count, CPU/RAM allocation, region, start/stop time, compute rate, storage and other charges. Keep private account IDs and payment details out of the public repo. A fresh A100/L40S rental becomes useful for measuring the current guarded pipeline on that specific host; it is not needed to preserve or price the earlier primitive evidence.
