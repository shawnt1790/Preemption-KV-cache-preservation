# Results

- `run_log.csv`: one row per experiment run. Add a row for failed runs too (`status=fail`, with the reason in `notes`).
- `spend_log.csv`: one row per session. Fill in the stop time when the VMs are stopped, and copy the real cost
  from GCP Billing > Reports (it lags by about a day).
- Budget alert: "kv-c-p class project", $15, emails at 50%, 90%, 100% and forecast-100%. Alerts only; nothing is shut down.
  Raise it with `gcloud billing budgets update` (billing account 01B8CD-C346B3-8CEC92).

## run_log.csv columns

| Column | Meaning |
|---|---|
| strategy | `none`, `write-through`, `reactive`, `hybrid` |
| workload | `high-reuse`, `sharegpt`, `low-reuse`, or a test name |
| notice_s | preemption notice: 0, 30 or 120 |
| hot_set_n | hybrid's N (empty for other strategies) |
| lmcache_config | `infra/` config the server ran with |
| ttft_p50_ms, ttft_p99_ms | over the whole run |
| first_ttft_after_restart_ms | first request the replacement server answers |
| bytes_saved | KV bytes in the store at the moment of preemption (after deleting keys the policy wouldn't keep) |
| storage_bytes | Redis `used_memory` at the end of the run |
| steady_overhead_pct | throughput loss vs. no preservation, for steady-state runs |

## One-off measurements

### Store bandwidth (2026-11-10)

kv-gpu (g2-standard-8) to kv-store (n2-highmem-4, Redis 6.0), same zone. Script: `infra/bench_store.py`.
Values are one LMCache chunk each: 256 tokens × 57,344 B = 14,680,064 B. Each figure is the median of 3 passes of 3 GB.

| Path | Write (gpu → store) | Read (store → gpu) |
|---|---|---|
| Raw network (iperf3, 4 streams) | 1.7 GB/s (13.8 Gbit/s) | 1.2 GB/s (9.5 Gbit/s) |
| Redis, 1 connection | **0.71 GB/s** | **0.37 GB/s** |
| Redis, 8 connections | 1.00 GB/s | 0.26 GB/s |

- Redis is the bottleneck, not the network: it runs commands on one thread, and the Python client copies every value.
- **`BANDWIDTH_BPS = 7.1e8`** for `select_prefixes`: the one-connection write rate, chosen as the conservative number.
  With `safety_s=2`, that saves about 20 GB in a 30 s notice and about 84 GB in a 120 s notice
  (the store holds at most 24 GB).
- The read rate sets the cost of a warm restart. The warm-restart test loaded 0.46 GB at about 0.35 GB/s,
  which matches the one-connection read.

### Replacement startup time (2026-11-10)

Measured on a real start of the stopped kv-gpu (g2-standard-8, L4) after an L4 stockout cleared.

| Phase | Time | Source |
|---|---|---|
| GCP start: capacity allocated, VM powered on | 54 s | `gcloud compute operations list` (start op, insert → end) |
| OS boot to userspace | 12 s | `systemd-analyze` |
| vLLM ready, cold disk (`serve.sh lmcache-remote.yaml`) | 160 s | 74 s loading weights, 34 s engine init (profile, KV alloc, warmup), ~50 s imports + LMCache |
| **VM start → serving** | **~230 s** | plus the first request, which each emulator run measures (`t_first_served`) |

- The emulator restarts vLLM on the same VM, with weights in the page cache: 75–130 s to ready. So **emulated
  downtime is ~100–150 s shorter than a real replacement**; state this in the slides.
- A truly new VM would also need the weights on its disk: either a pre-built image or snapshot (we have
  `kv-gpu-snap`), or a ~15 GB Hugging Face download. Disks restored from a snapshot load lazily, so the
  first weight read may be slower still.
- Capacity is the biggest real-world risk: this restart waited **69 min** (14:02 → 15:11 local) for an L4 in
  us-central1-a. On spot, that time comes on top of the startup above.

## Midterm runs (2026-11-10)

- `runs/<run_id>/`: one folder per run (requests.csv, events.json, summary.json). Made by `emulator/preempt.py`.
- `midterm_preemption.csv`, `midterm_steady.csv`: repeat-averaged tables (`python emulator/summarize.py`).
- `keymap.json`: prefix_id → Redis keys (12 chunks per prefix). Rebuild with `preempt.py register` if the workload changes.
- Settings: high-reuse with 64 prefixes (~3,140 tokens each, hot set 11.3 GB), **4 req/s**, hybrid N = 8,
  `BANDWIDTH_BPS = 7.1e8`, seeds 1 and 2. Why 4 req/s and every other decision: `docs/person-a-progress.md`.
- KV-bytes check (plan): LMCache stores 176 MB per prefix vs. 180 MB from `prompt_tokens` × 57,344.
  Correction factor 0.98 (the partial last chunk isn't stored).
- Results and takeaways: `docs/midterm-person-a.md`.
