# Plan: Preemption-Aware KV Cache Preservation (Group 3)

Started Nov 8, 2026; updated Nov 10, 2026.

The midterm checkpoint on Wed Nov 11 covers proposal weeks 1–6: testbed, workloads, preemption emulator, and all four strategies tested. The three weeks to the final presentation on Wed Dec 2 cover weeks 7–10: full experiments, the cost model, figures, and the demo.

Progress, decisions and deviations from this plan: `docs/progress-log.md`. Midterm results and slide content: `docs/midterm.md`.

## Midterm checkpoint (Wed Nov 11): all four strategies tested

The midterm shows the full pipeline working end to end with all four strategies tested on the high-reuse workload. What remains after it is scale (all workloads, repeats), the cost model, and the final presentation.

No preservation and write-through don't depend on notice length, so the midterm needs 8 configurations: no preservation, write-through, reactive flush at 0 / 30 / 120 s, and hybrid at 0 / 30 / 120 s. Run each at least twice. (No preservation and write-through were also run at 0 s notice so every 0 s comparison kills at the same point in the request stream; see `docs/progress-log.md`, decision 7.)

### Weeks 1–2: setup and workloads

- [x] GCP GPU VM (L4) with pinned vLLM and LMCache versions
- [x] Serve a 7–8B model with automatic prefix caching and the LMCache connector
- [x] Smoke test: a repeated long prompt shows lower TTFT on the second request
- [x] Durable store on a separate VM (Redis; LMCache 0.5 has no `lm://` server)
- [x] Measure remote store write and read bandwidth
- [x] Shared repo, run log, and budget alerts
- [x] Workload generator: async streaming client logging time, prefix ID, TTFT, latency and exact prompt tokens per request
- [x] High-reuse workload: shared long system prompts plus short questions
- [x] ShareGPT multi-turn workload (implemented; runs are after the midterm)
- [x] Agree on the policy interface (spec below)

### Weeks 3–4: emulator, baselines, hotness and analysis tools

- [x] Preemption emulator: notice signal, 0 / 30 / 120 s grace, kill server, clear GPU memory, start replacement
- [x] Timestamp every emulator step (notice, kill, restart, first request served)
- [x] Measure replacement startup time (VM ready, model loaded, first request served)
- [x] Configure write-through (LMCache remote backend)
- [x] Run no preservation and write-through end to end on the high-reuse workload
- [x] Logging: TTFT, throughput, bytes saved, storage used per run
- [x] Hotness tracking: reuse count × prefix length per prefix
- [x] Check the hotness ranking on real runs: the top 8 of 64 prefixes cover 63% of recent requests (hybrid at 0 s)
- [x] Plotting scripts: TTFT over time across a preemption, cache preserved vs. notice length, steady-state overhead

### Weeks 5–6: policies wired in and midterm runs

- [x] Reactive flush: on notice, rank prefixes by hotness and keep what fits in the window
- [x] Hybrid: top-N hot prefixes replicated continuously, plus reactive flush on notice
- [x] Save path for flush-on-notice: keep the prefixes the policy ranks, in order, until the window's budget runs out
- [x] Background replication path for the hybrid's hot set
- [x] Run all 8 configurations on the high-reuse workload (2 runs each), plus none and write-through at 0 s
- [x] Steady-state runs for no preservation, write-through, and hybrid
- [x] Small sweep to pick N: N = 4 / 8 / 16 in the preserved-vs-notice figure; runs use N = 8
- [x] Midterm figures from the runs (`bash analysis/make_figures.sh`)
- [ ] Midterm slides (content in `docs/midterm.md`) and one rehearsal

**Results shown at the midterm** (all in `docs/midterm.md`):

1. TTFT over time across a preemption, all four strategies (0 s and 30 s notice)
2. Share of the hot cache preserved vs. notice length, reactive vs. hybrid
3. Steady-state overhead of write-through and hybrid vs. no preservation: throughput, p50/p99 latency, storage bytes
4. Replacement startup time and store bandwidth

The expected headline was: at 0 s notice, reactive flush saves nothing and matches no preservation, while hybrid keeps its hot set warm at far lower overhead than write-through. The first half held. The second half held for storage (2.4 GB vs. 12.9 GB) but not for TTFT at 4 req/s, because of head-of-line blocking on the replacement; see the takeaways in `docs/midterm.md`.

**Midterm slides (8):**

1. Recap: problem and research question
2. System built: diagram with every component working
3. Result: TTFT over time across a preemption, four strategies
4. Result: cache preserved vs. notice length
5. Result: steady-state overhead
6. Takeaways so far
7. Remaining plan: full experiments and cost model
8. Risks and open questions

**Shortcuts used for the midterm (state them on the slides):**

- **The replacement is a restart on the same VM.** Killing vLLM clears GPU memory and the local cache. Real replacement startup time was measured separately once.
- **What each policy saved is emulated.** Every run writes through to the remote store; at the preemption, the emulator deletes every prefix the policy would not have saved within the notice window (bytes allowed = measured bandwidth × window). The restarted server then sees exactly what that policy would have preserved. Steady-state overhead is measured separately with real write-through on vs. off.
- **Hotness is tracked at the request level** from the workload log instead of inside LMCache.
- One model, one GPU type, high-reuse workload.

## After the midterm

Each phase ends with a check that its milestone actually works before moving on.

### Weeks 7–8 (Nov 12–25): full experiments and cost model

**Milestone:** complete results table for every configuration, and a working cost model.

- [ ] Address midterm feedback in the policies or experiment design
- [ ] Test whether the replacement can serve cache hits first (scheduler priority or spare capacity), since head-of-line blocking hides the hybrid's benefit at 0 s notice
- [ ] Low-reuse (unique prompts) control workload runs
- [ ] Full runs: 4 strategies × 3 workloads × 3 notice lengths, 3 repeats each
- [ ] A larger hot set or lower bandwidth, so that 30 s of notice is not enough to save everything and ordering matters
- [ ] SpotLake-timed preemptions, only if the full runs are done
- [ ] Check results, flag anomalies, decide reruns
- [ ] Cost model: $ per 1M tokens vs. preemption rate for each strategy, using GCP spot and on-demand prices, storage and egress costs

### Weeks 9–10 (Nov 26 – Dec 1): figures, report, demo

**Milestone:** final slides done by Sun Nov 30; dry run Mon Dec 1.

- [ ] Final figures for all four comparisons
- [ ] Record a demo video of a preemption and warm restart as a backup for the live demo
- [ ] Report: motivation, system design, policies, methodology, results, cost model
- [ ] Final slides (Nov 30) and dry run (Dec 1)

## Final presentation deliverables (Dec 2)

These are the four comparisons promised in the proposal, plus the demo.

- [ ] TTFT over time after a preemption, all four strategies
- [ ] Steady-state overhead: throughput, latency, storage cost
- [ ] Cache preserved vs. notice length (0 / 30 / 120 s)
- [ ] Cost per 1M tokens vs. preemption rate: which strategy is cheapest
- [ ] Demo of a preemption and warm restart (live, with a recorded backup)

## Risks and fallbacks

| Risk | Fallback |
| --- | --- |
| Hooking custom policies into LMCache takes too long | Done this way already: hotness is tracked at the request level outside LMCache, and the emulator keeps or deletes the chosen prefixes' keys in the store |
| No spot GPU capacity or budget runs short | Run on an on-demand or university GPU; the emulator already fakes preemptions. A disk snapshot `kv-gpu-snap` exists for a zone move |
| Cache is small enough to flush fully in 30 s, so ordering doesn't matter | **This happened** (0.71 GB/s × 28 s ≈ 20 GB > 11.3 GB hot set). Report it as a finding, and use longer contexts, more prefixes or a lower bandwidth after the midterm |
| A sprint slips | Drop SpotLake timing first, then the low-reuse workload; keep the four strategies on high reuse and ShareGPT |
| Live demo fails on Dec 2 | Use the recorded demo |

## How we work

- Two short syncs a week (e.g., Monday to plan, Friday to check the milestone), since three weeks leaves no slack for a missed week.
- One shared repo; one run log with a row per run (`results/run_log.csv`) and a spend log (`results/spend_log.csv`).
- Shut the GPU VM down after every session and log spend.

## Spec: hotness score and policy interface

This is the agreement between the policy code (`policy/policy.py`) and the emulator's save-and-restore code (`emulator/preempt.py`). It is implemented as written, except where noted.

| Decision | Choice |
| --- | --- |
| Unit that gets a score | A whole prefix, identified by `prefix_id` from the workload CSV (e.g., `hr-0`, `sg-c12`) |
| Reuse frequency | Successful requests for that prefix in the last 300 s before the notice |
| Prefix length | Tokens |
| Hotness | frequency × length in tokens |
| Ties | Larger prefix first (costlier to recompute) |
| Size in bytes | tokens × KV bytes per token |
| Policy output | A plain list of `prefix_id`s to keep |
| Bandwidth | Measured once: `BANDWIDTH_BPS = 7.1e8` (Redis write, 1 connection) |

### Hotness score

**Inputs:** the workload generator's CSV log (`prefix_id`, `send_wall`, `prompt_tokens`, `prompt_chars`, `status`), the notice time `t_notice`, and the model's KV bytes per token.

**Steps:**

1. Keep rows with `status == ok` and `t_notice − 300 s ≤ send_wall < t_notice`.
2. **Frequency:** count rows per `prefix_id`.
3. **Length in tokens:** for each `prefix_id`, the largest `prompt_tokens` in the window (the exact count from vLLM's usage stats; `prompt_chars ÷ 4` only if a row has none). For ShareGPT this is the latest turn's history, which is what the next turn reuses.
4. **Hotness** = frequency × tokens.
5. Sort hottest first; break ties by larger tokens, then by `prefix_id` so runs are repeatable.
6. Drop prefixes with no requests in the window.

**Size in bytes** = tokens × KV bytes per token, where KV bytes per token = layers × KV heads × head dim × 2 (K and V) × 2 bytes (fp16/bf16).

| Model | Layers | KV heads | Head dim | KV bytes per token |
| --- | --- | --- | --- | --- |
| Qwen2.5-7B-Instruct | 28 | 4 | 128 | 57,344 (56 KiB) |
| Llama-3.1-8B-Instruct | 32 | 8 | 128 | 131,072 (128 KiB) |

Checked against LMCache: 176 MB stored vs. 180 MB estimated per prefix, a correction factor of 0.98 (the partial last chunk isn't stored). No change to the policy was needed.

**Why frequency × length:** a long prefix saves more recomputation when it's reused, so it matches the proposal. It also costs more of the save budget, so per byte saved, length roughly cancels out. If time allows, run "frequency only" as a one-line ablation and report which ranks better.

### Policy interface

```python
def rank_prefixes(log_csv, t_notice, kv_bytes_per_token, window_s=300):
    """Returns (ranked, sizes_bytes):
       ranked      list of prefix_ids, hottest first
       sizes_bytes {prefix_id: estimated KV size in bytes}"""

def select_prefixes(ranked, sizes_bytes, bandwidth_Bps, notice_s,
                    hot_set_n=0, safety_s=2.0):
    """Returns the list of prefix_ids that survive the preemption.
       hot_set_n = 0  -> reactive flush
       hot_set_n = N  -> hybrid: top N always survive (already replicated)
       budget = bandwidth_Bps * max(notice_s - safety_s, 0)"""
```

**Selection rule:**

1. **Hybrid only:** the top `hot_set_n` prefixes survive regardless of notice, because the background replicator has already copied them.
2. Walk the rest of `ranked` hottest first. Add a prefix if it fits in the remaining budget; if it doesn't fit, skip it and try the next (a smaller one may still fit).
3. Return the surviving list in rank order.

`safety_s` reserves 2 s of the window for killing the server cleanly; at 0 s notice the budget is 0.

**No preservation and write-through need no policy:** no preservation keeps nothing, and write-through keeps everything. The emulator handles both without calling `select_prefixes`.

### Where the emulator calls it

1. Send the notice and record `t_notice`.
2. `ranked, sizes = rank_prefixes(log_csv, t_notice, KV_BYTES_PER_TOKEN)`
3. `keep = select_prefixes(ranked, sizes, BANDWIDTH_BPS, notice_s, hot_set_n)`
4. Delete from the remote store every prefix not in `keep`, using `results/keymap.json` (each `prefix_id` → the Redis keys of its 12 LMCache chunks, recorded by `preempt.py register`).
5. Kill vLLM, restart it, and keep the workload generator running.

**Hybrid steady state:** every 30 s, the emulator calls `rank_prefixes` with the current time and replicates the top `hot_set_n` prefixes to the remote store in the background. That replication traffic is the hybrid's steady-state overhead.

### Test cases (`policy/test_policy.py`, all passing)

Bandwidth 200 MB/s, `safety_s` = 2. Prefixes in rank order: hr-0 (2 GB), hr-2 (3 GB), hr-1 (1 GB), hr-5 (2 GB). 1 GB = 10^9 bytes.

| Case | Notice | hot\_set\_n | Budget | Expected `keep` |
| --- | --- | --- | --- | --- |
| Reactive | 0 s | 0 | 0 | `[]` |
| Reactive | 32 s | 0 | 6 GB | `[hr-0, hr-2, hr-1]` |
| Reactive, skip-and-continue | 22 s | 0 | 4 GB | `[hr-0, hr-1]` (hr-2 doesn't fit; hr-1 does) |
| Hybrid | 0 s | 2 | 0 | `[hr-0, hr-2]` |
| Hybrid | 12 s | 2 | 2 GB | `[hr-0, hr-2, hr-1]` (hr-1 fits; hr-5 would make 3 GB) |
| Reactive | 122 s | 0 | 24 GB | all four |
