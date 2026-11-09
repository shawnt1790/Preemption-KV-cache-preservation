# Work Split and Plan: Preemption-Aware KV Cache Preservation (Group 3)

Nov 8, 2026 · @Grace

Person A owns the infrastructure and runs the experiments; Person B owns the workloads, preservation policies, and cost model. The midterm checkpoint on Wed Nov 11 covers proposal weeks 1–6: testbed, workloads, preemption emulator, and all four strategies tested. The three weeks to the final presentation on Wed Dec 2 cover weeks 7–10: full experiments, the cost model, figures, and the demo.

## Midterm checkpoint (Wed Nov 11): all four strategies tested

The midterm shows the full pipeline working end to end with all four strategies tested on the high-reuse workload. What remains after it is scale (all workloads, repeats), the cost model, and the final presentation.

No preservation and write-through don't depend on notice length, so the midterm needs 8 configurations: no preservation, write-through, reactive flush at 0 / 30 / 120 s, and hybrid at 0 / 30 / 120 s. Run each at least twice.

### Person A checklist (weeks 1–6): infrastructure and runs

**Weeks 1–2: Setup**

- [ ] Create the GCP GPU VM (L4 class) and pin vLLM and LMCache versions
- [ ] Serve a 7–8B model with automatic prefix caching and the LMCache connector
- [ ] Smoke test: a repeated long prompt shows lower TTFT on the second request
- [ ] Stand up the remote LMCache server on a separate VM as the durable store
- [ ] Measure remote store write and read bandwidth
- [ ] Set up the shared repo, run log, and budget alerts

**Weeks 3–4: Emulator and baselines**

- [ ] Preemption emulator: notice signal, 0 / 30 / 120 s grace, kill server, clear GPU memory, start replacement
- [ ] Timestamp every emulator step (notice, kill, restart, first request served)
- [ ] Measure replacement startup time (VM ready, model loaded, first request served)
- [ ] Configure write-through (LMCache remote backend)
- [ ] Run no preservation and write-through end to end on the high-reuse workload
- [ ] Logging: TTFT, throughput, bytes saved, storage used per run

**Weeks 5–6: Policies wired in and midterm runs**

- [ ] Save path for flush-on-notice: write the blocks Person B's policy ranks, in order, until the window ends
- [ ] Background replication path for the hybrid's hot set
- [ ] Run all 8 configurations on the high-reuse workload (at least 2 runs each)
- [ ] Steady-state runs for no preservation, write-through, and hybrid (throughput, p50/p99 latency, storage bytes)
- [ ] Midterm slides: system built, emulator, methodology

### Person B checklist (weeks 1–6): workloads, policies, analysis

**Weeks 1–2: Workloads**

- [ ] Workload generator: async streaming client logging time, prefix ID, TTFT, and latency per request
- [ ] High-reuse workload: shared long system prompts plus short questions
- [ ] ShareGPT multi-turn workload
- [ ] Agree on the policy interface with Person A (ranked list of block keys to save, plus the hot-set size N)

**Weeks 3–4: Hotness and analysis tools**

- [ ] Hotness tracking: reuse count × prefix length per block
- [ ] Check the hotness ranking on the baseline runs (do the top blocks get most of the reuse?)
- [ ] Plotting scripts: TTFT over time across a preemption, cache preserved vs. notice length, steady-state overhead
- [ ] First baseline plots: no preservation vs. write-through

**Weeks 5–6: Reactive and hybrid policies**

- [ ] Reactive flush: on notice, rank blocks by hotness and save in order until the window ends
- [ ] Hybrid: continuously replicate the top-N hot blocks, flush more on notice
- [ ] Small sweep to pick N (2–3 values)
- [ ] Midterm figures from Person A's runs
- [ ] Midterm slides: problem recap, policies, results, takeaways, remaining plan

**Results to show at the midterm:**

1. TTFT over time across a preemption, all four strategies (30 s notice)
2. Share of the hot cache preserved vs. notice length (0 / 30 / 120 s), reactive vs. hybrid
3. Steady-state overhead of write-through and hybrid vs. no preservation: throughput, p50/p99 latency, storage bytes
4. Replacement startup time and store bandwidth

The expected headline: at 0 s notice, reactive flush saves nothing and matches no preservation, while hybrid keeps its hot set warm at far lower overhead than write-through. If the numbers say otherwise, that's still a finding worth presenting.

**Suggested midterm slides (8):**

1. Recap: problem and research question
2. System built: diagram with every component working
3. Result: TTFT over time across a preemption, four strategies
4. Result: cache preserved vs. notice length
5. Result: steady-state overhead
6. Takeaways so far
7. Remaining plan: full experiments and cost model
8. Risks and open questions

## Two-day checklist (Mon Nov 9 evening – Wed Nov 11)

This compresses weeks 1–6 into about 25–30 hours of combined work. It's only feasible with the shortcuts below and runs left going overnight.

**Shortcuts that make two days possible:**

- **Emulate the replacement on the same VM.** Kill vLLM and restart it, which clears GPU memory and local cache. Measure real replacement startup time separately once, and state this in the slides.
- **Emulate what each policy saved.** Run write-through to the remote store, then at the moment of preemption delete every key the policy would not have saved within the notice window (bytes allowed = measured bandwidth × window). The restarted server then sees exactly what that policy would have preserved. Measure steady-state overhead separately with real write-through on vs. off. If the store can't delete keys, use a disk or GCS-backed store where each key is a file.
- **Track hotness at the request level** (hash of each 256-token prefix chunk, count × length) instead of hooking LMCache internals.
- One model, one GPU type, high-reuse workload first; ShareGPT only if time allows.

### Mon evening (\~3–4 h each)

- [ ] Both (15 min): Agree on the policy interface and the hotness definition
- [ ] Person A: Create the GCP GPU VM (L4 class) and a small CPU VM for the LMCache server
- [ ] Person A: Install pinned vLLM + LMCache; serve a 7–8B instruct model with prefix caching and the LMCache connector
- [ ] Person A: Smoke test: the same long prompt twice shows a lower TTFT the second time
- [ ] Person B: Workload generator: async streaming client that logs time, prefix ID, TTFT, and latency per request to CSV
- [ ] Person B: High-reuse workload: a few shared 4–8K-token system prompts plus short questions

### Tue (\~6–8 h each)

- [ ] Person A: Preemption emulator: notice, wait 0 / 30 / 120 s, kill vLLM, restart, timestamp each step
- [ ] Person A: Measure remote store write and read bandwidth, and replacement startup time once
- [ ] Person A: Run no preservation and write-through end to end; confirm the TTFT spike and the warm restart
- [ ] Person B: Hotness tracker over the request log
- [ ] Person B: Reactive flush: rank keys by hotness, keep what fits in the window, delete the rest
- [ ] Person B: Hybrid: top-N keys always kept, plus reactive flush on notice; try 2–3 values of N
- [ ] Person B: Plotting scripts for the three midterm figures
- [ ] Person A (Tue night): Script all 8 configurations × 2 runs plus steady-state runs; leave them running overnight

### Wed (before the checkpoint)

- [ ] Person A: Check overnight runs; rerun any failures; collect overhead, startup time, and bandwidth numbers
- [ ] Person B: Generate the figures: TTFT over time, cache preserved vs. notice length, steady-state overhead
- [ ] Both: Build the 8 slides and rehearse once

**If time runs short, cut in this order:** ShareGPT workload, the 120 s notice length, second runs, the N sweep (pick one N). Keep all four strategies at 0 and 30 s; that's the core result.

## Who does what

The split follows the system diagram: Person A owns everything that runs and moves bytes, Person B owns everything that decides what to send and what the results mean. Swap if it fits your strengths better.

| Area | Person A: Infrastructure and experiments | Person B: Workloads, policies, analysis |
| --- | --- | --- |
| System | GCP GPU VM, vLLM with prefix caching, LMCache connector, durable KV store | Workload generator: high reuse, ShareGPT multi-turn, low reuse |
| Preemption | Emulator: notice signal, 0 / 30 / 120 s Person A, kill, start replacement replica | Notice handler logic: what to flush, in what order |
| Policies | Save and load paths (write-through, replication, flush) wired into LMCache | Hotness score (reuse frequency × prefix length), reactive flush, hybrid policy |
| Measurement | Logging: TTFT, throughput, bytes saved, storage cost; replacement startup time | Plotting scripts; cost model ($ per 1M tokens vs. preemption rate) |
| Experiments | Runs every configuration; keeps the run log and GCP budget | Checks results, flags anomalies, decides reruns |
| Slides and report | System design, emulator, methodology | Motivation, policies, results, cost model |

**The one interface to agree on by Thu Nov 12:** Person B's policy returns a ranked list of prefix block hashes to save (plus how many to replicate continuously); Person A's save path writes those blocks to the durable store. Agree on this format first so you can work in parallel.

## After the midterm

Each phase ends with a joint check that its milestone actually works before moving on.

### Weeks 7–8 (Nov 12–25): Full experiments and cost model

**Milestone:** Complete results table for every configuration, and a working cost model.

- [ ] Person B: Address midterm feedback in the policies or experiment design
- [ ] Person B: Low-reuse (unique prompts) control workload
- [ ] Person A: Full runs: 4 strategies × 3 workloads × 3 notice lengths, 3 repeats each
- [ ] Person A: SpotLake-timed preemptions, only if the full runs are done
- [ ] Person B: Check results, flag anomalies, decide reruns
- [ ] Person B: Cost model: $ per 1M tokens vs. preemption rate for each strategy, using GCP spot and on-demand prices, storage and egress costs

### Weeks 9–10 (Nov 26 – Dec 1): Figures, report, demo

**Milestone:** Final slides done by Sun Nov 30; dry run Mon Dec 1.

- [ ] Person B: Final figures for all four comparisons
- [ ] Person A: Record a demo video of a preemption and warm restart as a backup for the live demo
- [ ] Person A: System design and methodology slides and report sections
- [ ] Person B: Motivation, policies, results, and cost model slides and report sections
- [ ] Both: Final slides (Nov 30) and dry run (Dec 1)

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
| Hooking custom policies into LMCache takes too long | Track hotness at the request level outside LMCache and call its store API for the chosen prefixes |
| No spot GPU capacity or budget runs short | Run on an on-demand or university GPU; the emulator already fakes preemptions |
| Cache is small enough to flush fully in 30 s, so ordering doesn't matter | Use longer contexts and a larger CPU tier, or report it as a finding and focus on write-through overhead |
| A sprint slips | Drop SpotLake timing first, then the low-reuse workload; keep the four strategies on high reuse and ShareGPT |
| Live demo fails on Dec 2 | Use the recorded demo from Sprint 3 |

## How you'll work together

- Two short syncs a week (e.g., Monday to plan, Friday to check the milestone), since three weeks leaves no slack for a missed week.
- One shared repo with separate folders for infra and policies, and one results sheet with a row per run (config, date, TTFT, overhead, cost).
- Shut the GPU VM down after every session and log spend in the run log.

## Spec: hotness score and policy interface

This is the agreement between Person B's decision code and Person A's save-and-restore code. Both sides build against it so the pieces connect on Tuesday without changes.

| Decision | Choice |
| --- | --- |
| Unit that gets a score | A whole prefix, identified by `prefix_id` from the workload CSV (e.g., `hr-0`, `sg-c12`) |
| Reuse frequency | Successful requests for that prefix in the last 300 s before the notice |
| Prefix length | Tokens |
| Hotness | frequency × length in tokens |
| Ties | Larger prefix first (costlier to recompute) |
| Size in bytes | tokens × KV bytes per token |
| Policy output | A plain list of `prefix_id`s to keep |
| Bandwidth | Measured once by Person A, in bytes per second |

### Hotness score

**Inputs:** the workload generator's CSV log (`prefix_id`, `send_wall`, `prompt_chars`, `status`), the notice time `t_notice`, and the model's KV bytes per token.

**Steps:**

1. Keep rows with `status == ok` and `t_notice − 300 s ≤ send_wall < t_notice`.
2. **Frequency:** count rows per `prefix_id`.
3. **Length in tokens:** for each `prefix_id`, take the largest `prompt_chars` in the window and divide by 4 (about 4 characters per token in English). For ShareGPT this is the latest turn's history, which is what the next turn reuses. Swap in the model's tokenizer later for exact counts.
4. **Hotness** = frequency × tokens.
5. Sort hottest first; break ties by larger tokens, then by `prefix_id` so runs are repeatable.
6. Drop prefixes with no requests in the window.

**Size in bytes** = tokens × KV bytes per token, where KV bytes per token = layers × KV heads × head dim × 2 (K and V) × 2 bytes (fp16/bf16). Read the first three from the model's `config.json`.

| Model | Layers | KV heads | Head dim | KV bytes per token |
| --- | --- | --- | --- | --- |
| Qwen2.5-7B-Instruct | 28 | 4 | 128 | 57,344 (56 KiB) |
| Llama-3.1-8B-Instruct | 32 | 8 | 128 | 131,072 (128 KiB) |

Person A should check this estimate once against the bytes LMCache actually stores for one prefix, and give Person B a correction factor if they differ.

**Why frequency × length:** a long prefix saves more recomputation when it's reused, so it matches the proposal. It also costs more of the save budget, so per byte saved, length roughly cancels out. If time allows, run "frequency only" as a one-line ablation and report which ranks better.

### Policy interface

Person B owns two functions in `policy.py`; Person A calls them and never needs to know how they decide.

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

1. **Hybrid only:** the top `hot_set_n` prefixes survive regardless of notice, because Person A's background replicator has already copied them.
2. Walk the rest of `ranked` hottest first. Add a prefix if it fits in the remaining budget; if it doesn't fit, skip it and try the next (a smaller one may still fit).
3. Return the surviving list in rank order.

`safety_s` reserves 2 s of the window for killing the server cleanly; at 0 s notice the budget is 0.

**No-preservation and write-through need no policy:** no preservation keeps nothing, and write-through keeps everything. Person A handles both without calling `select_prefixes`.

### Where Person A calls it

1. Emulator sends the notice and records `t_notice`.
2. `ranked, sizes = rank_prefixes(log_csv, t_notice, KV_BYTES_PER_TOKEN)`
3. `keep = select_prefixes(ranked, sizes, BANDWIDTH_BPS, notice_s, hot_set_n)`
4. Delete from the remote store every prefix not in `keep`.
5. Kill vLLM, restart it, and keep the workload generator running.

**Hybrid steady state:** every 30 s, Person A calls `rank_prefixes` with the current time and replicates the top `hot_set_n` prefixes to the remote store in the background. That replication traffic is the hybrid's steady-state overhead.

**Person A's open task:** map each `prefix_id` to the LMCache keys it produces, so "delete everything not in `keep`" is possible. The simplest option is to record which keys appear in the store after each new prefix's first request.

### Test cases Person B's code must pass

Bandwidth 200 MB/s, `safety_s` = 2. Prefixes in rank order: hr-0 (2 GB), hr-2 (3 GB), hr-1 (1 GB), hr-5 (2 GB).

| Case | Notice | hot\_set\_n | Budget | Expected `keep` |
| --- | --- | --- | --- | --- |
| Reactive | 0 s | 0 | 0 | `[]` |
| Reactive | 32 s | 0 | 6 GB | `[hr-0, hr-2, hr-1]` |
| Reactive, skip-and-continue | 22 s | 0 | 4 GB | `[hr-0, hr-1]` (hr-2 doesn't fit; hr-1 does) |
| Hybrid | 0 s | 2 | 0 | `[hr-0, hr-2]` |
| Hybrid | 12 s | 2 | 2 GB | `[hr-0, hr-2, hr-1]` (hr-1 fits; hr-5 would make 3 GB) |
| Reactive | 122 s | 0 | 24 GB | all four |

Use 1 GB = 10^9 bytes for these tests.

### Handoff

- [ ] Both (today): agree on this spec and the CSV columns
- [ ] Person A (today): stub `select_prefixes` that returns `ranked` unchanged, to build the emulator against
- [ ] Person B (by Tue 2 pm): `policy.py` with both functions, passing the test cases above, plus a short README
- [ ] Person A (Tue): swap the stub for the real `policy.py` and run one preemption end to end
