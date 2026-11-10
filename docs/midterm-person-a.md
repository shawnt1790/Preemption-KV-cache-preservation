# Midterm material: system, emulator, methodology (Person A)

Slide-ready content for plan slide 2 (system built), the emulator and methodology, and result 4
(replacement startup time and store bandwidth). Numbers come from `results/README.md`,
`results/run_log.csv` and `results/midterm_*.csv`.

## Slide: System built

```
                    kv-gpu  (GCP g2-standard-8, 1x NVIDIA L4 24 GB, us-central1-a)
  workload_gen.py ──HTTP──▶ vLLM 0.32  ─ GPU prefix cache (~3.9 GB KV, ~23 prefixes)
  (high-reuse,              │
   4 req/s)                 └─ LMCache 0.5.7 connector ─ CPU tier (10 GB host RAM)
       ▲                                │  write-through, 256-token chunks
       │ request log (CSV)              ▼
  emulator/preempt.py ──────────▶ Redis 6 on kv-store (n2-highmem-4, same zone)
   notice · policy · kill ·        durable KV store, 24 GB, internal network only
   delete · restart                       ▲
       │                                  │ keep/delete by prefix
       └── policy/policy.py (Person B): rank_prefixes → select_prefixes
```

- Model: Qwen2.5-7B-Instruct, bf16. KV is 57,344 B/token; checked against LMCache's stored bytes
  (176 MB stored vs. 180 MB estimated per prefix, ratio 0.98).
- Everything works end to end:
  - prefix caching on the GPU;
  - LMCache saving KV to CPU memory and to Redis;
  - a restarted server loading KV back from Redis (8,448 of 8,448 tokens, TTFT 2.6 s → 1.5 s).
- Pinned versions and every setup fix: `infra/requirements-gpu.lock.txt`, `infra/TROUBLESHOOTING.md`.

## Slide: Preemption emulator

One run (`emulator/preempt.py run`), every step timestamped into `events.json`:

1. **Fresh start:** stop vLLM, empty Redis, start vLLM with write-through to Redis.
2. **Serve** the high-reuse workload for 180 s.
3. **Notice** (`t_notice`): the policy ranks prefixes from the request log and picks what to keep.
4. **Grace window:** 0 / 30 / 120 s; vLLM keeps serving.
5. **Kill** (`t_kill`): stop vLLM. Process exit frees GPU memory and LMCache's CPU tier.
6. **Keep what the strategy saved:** delete from Redis every chunk of the prefixes the strategy
   wouldn't have saved.
7. **Replacement** (`t_restart` → `t_ready`): start vLLM; the workload keeps sending throughout.
8. **Serve 180 s more**; record `t_first_served` and the TTFT recovery.

| Strategy | What survives in the store |
|---|---|
| No preservation | nothing |
| Write-through | everything written so far |
| Reactive flush | `select_prefixes(..., hot_set_n=0)`: hottest prefixes that fit in bandwidth × (notice − 2 s) |
| Hybrid (N = 8) | top 8 always (replicated in advance), plus what fits in the window |

**Emulated, and the slides should say so:**
- The replacement is a vLLM restart on the same VM. A real VM start adds about 54 s (allocation)
  plus 12 s (boot), and loads weights from a cold disk.
- Reactive and hybrid get "what they would have saved" by deleting from a write-through store,
  using the measured 0.71 GB/s. The flush itself isn't timed live.
- Steady-state hybrid replicates the hot set as same-sized values: real traffic and storage, but not
  LMCache's own chunks.

## Slide: Methodology

- **Workload** (Person B's `workload_gen.py`, high-reuse):
  - 64 shared system prompts of about 3,140 tokens each, with Zipf(1.1) popularity;
  - one short question per request, 64 output tokens, Poisson arrivals at **4 req/s**.
- **Why 4 req/s:** a rate probe on a warm server gave a median TTFT of 193 / 261 / 395 ms at
  2 / 4 / 6 req/s, and about 29 s at 10 req/s (just queueing). 4 req/s leaves headroom, so a
  preemption's spike is visible.
- **Hot set:** 64 × 12 chunks × 14.7 MB = **11.3 GB**. It exceeds the GPU cache (~3.9 GB) and the
  CPU tier (10 GB); the Redis store holds all of it.
- **Configurations** (plan): no preservation, write-through, reactive at 0/30/120 s, hybrid (N = 8)
  at 0/30/120 s. Each runs twice, with workload seeds 1 and 2.
- **Steady state:** no preemption, 60 s warmup plus 240 s measured, for none (CPU tier only),
  write-through (CPU tier + Redis) and hybrid (CPU tier + background replication every 30 s).
- **Metrics:**
  - TTFT p50/p99 before the notice and in the first 60 s after the replacement is ready;
  - kill → first request served;
  - share of the hot set kept, by bytes and by recent requests (the last 300 s);
  - GB kept, store bytes, throughput.

## Slide: Replacement startup time and store bandwidth (result 4)

| Measurement | Value |
|---|---|
| Redis write, 1 connection (`BANDWIDTH_BPS`) | **0.71 GB/s** |
| Redis read, 1 connection | **0.37 GB/s** |
| Raw network, kv-gpu ↔ kv-store | 1.7 GB/s write, 1.2 GB/s read |
| GCP start (capacity + power on) | 54 s |
| OS boot | 12 s |
| vLLM ready, cold disk | 160 s (74 s weights, 34 s engine init) |
| **Real VM start → serving** | **~230 s** |
| Emulated restart (warm page cache) → ready | ~70 s (`downtime_s` ≈ 98 s from kill, including shutdown) |
| L4 capacity wait on restart (2026-11-10) | **69 min** stockout in us-central1-a |

- At 0.71 GB/s, a 30 s notice can save about 20 GB, more than the 11.3 GB hot set. So in this
  setup **reactive at 30 s and 120 s preserves everything**, and the strategies differ at 0 s.
- Redis is the bottleneck, not the network: it handles commands on one thread.

## Results (2026-11-10, high-reuse, 4 req/s, 2 repeats each)

Source: `results/midterm_preemption.csv` and `results/midterm_steady.csv` (`python emulator/summarize.py`).
"After" is the first 60 s once the replacement is ready. Kill → ready is about 98 s in every run (emulated restart).

### Preemption runs

| Strategy | Notice | Runs | Hot-set bytes kept | Recent requests covered | GB kept | TTFT p50 before | TTFT p50 after | TTFT p99 after | Kill → first served |
|---|---|---|---|---|---|---|---|---|---|
| No preservation | 0 s | 1* | 0% | 0% | 0 | 219 ms | 8,971 ms | 15,774 ms | 104 s |
| No preservation | 30 s | 2 | 0% | 0% | 0 | 218 ms | 5,918 ms | 9,727 ms | 105 s |
| Write-through | 30 s | 2 | 100% | 100% | 11.0 | 219 ms | 541 ms | 2,200 ms | 100 s |
| Reactive flush | 0 s | 2 | 0% | 0% | 0 | 220 ms | 12,073 ms | 17,808 ms | 105 s |
| Reactive flush | 30 s | 2 | 100% | 100% | 11.0 | 221 ms | 524 ms | 2,489 ms | 101 s |
| Reactive flush | 120 s | 2 | 100% | 100% | 11.0 | 222 ms | 538 ms | 3,009 ms | 106 s |
| Hybrid (N=8) | 0 s | 2 | 13% | 63% | 1.4 | 218 ms | 9,843 ms | 14,542 ms | 111 s |
| Hybrid (N=8) | 30 s | 2 | 100% | 100% | 11.0 | 218 ms | 534 ms | 1,874 ms | 101 s |
| Hybrid (N=8) | 120 s | 2 | 100% | 100% | 11.0 | 220 ms | 513 ms | 1,898 ms | 101 s |

\* The notice-0 runs for none and write-through were still running at the time of writing (`run_extra.sh`).
Update the table from `summarize.py` once they finish.

Hybrid at 0 s, after the restart, split by whether a request's prefix was kept: **kept 9,790 ms vs.
lost 9,956 ms** (median, first 60 s).

### Steady state (no preemption, 240 s measured, 1 run each)

| Strategy | TTFT p50 / p99 | E2E p50 / p99 | Throughput | Store used |
|---|---|---|---|---|
| No preservation (CPU tier only) | 217 / 1,202 ms | 2,543 / 6,256 ms | 3.79 req/s, 120 tok/s | 0 GB |
| Write-through (CPU tier + Redis) | 215 / 1,195 ms | 2,441 / 6,404 ms | 3.74 req/s, 114 tok/s | **12.9 GB** |
| Hybrid N=8 (CPU tier + replication) | 214 / 1,182 ms | 2,507 / 5,924 ms | 3.83 req/s, 115 tok/s | **2.4 GB** (2.2 GB replicated, 12 prefixes over time) |

### Takeaways

1. **A preemption with nothing preserved costs a long TTFT spike.** The median goes from about 220 ms to
   6–9 s in the first minute, and recovery takes about 45 s after the replacement is ready.
2. **Anything that keeps the hot set recovers almost at once:** about 0.5 s median in the first minute.
   - With 30 s of notice, reactive flush keeps everything, because 0.71 GB/s × 28 s ≈ 20 GB is more
     than the 11.3 GB hot set.
   - So at 30 s and 120 s notice, **reactive, hybrid and write-through are equivalent here.** The
     differences come at 0 s notice and in steady-state cost.
3. **At 0 s notice, reactive saves nothing** and behaves like no preservation, as expected.
4. **Hybrid at 0 s keeps the prefixes of 63% of recent requests (13% of the bytes), but TTFT barely
   improves**, even for the requests whose prefix was kept (9.8 s vs. 10.0 s).
   - The cause is head-of-line blocking: the replacement is swamped recomputing the 56 lost
     prefixes, and requests are served first come, first served.
   - So the hybrid's benefit depends on load and scheduling, not just on what it saved. The
     2 req/s diagnostic run (`diag-*-rate2`) tests this.
5. **The steady-state latency and throughput overhead of write-through is too small to measure at
   this load.** LMCache writes asynchronously, and Redis absorbs about 1 MB/s of new chunks. **The cost
   difference is storage: write-through holds 12.9 GB vs. hybrid's 2.4 GB (5.3× less).** That's the
   input for Person B's cost model.

### Caveats

- The emulated downtime (about 98 s) is shorter than a real replacement (about 230 s from VM start),
  and much shorter than a capacity wait (69 min measured).
- The post-restart transient is noisy: identical setups differed by up to about 2× in their
  first-minute median. Two repeats is the minimum; compare strategies killed at the same notice.
- One model, one GPU type, one workload; steady state has 1 run per strategy.
