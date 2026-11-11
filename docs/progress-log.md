# Progress log

What was built and run for the midterm, decisions that differ from the plan (`docs/plan.md`), and where everything
lives. Results and slide content: `docs/midterm.md`. Setup problems and fixes:
`infra/TROUBLESHOOTING.md`. Measurements: `results/README.md`.

## Timeline

| When | What |
|---|---|
| Mon 11-09 evening | GCP VMs (L4 quota raised, zone stockouts worked around). Pinned vLLM 0.32.0 + LMCache 0.5.7 + torch 2.13. Served Qwen2.5-7B with prefix caching + LMCache. Smoke test 2.6 s → 0.18 s TTFT. |
| Mon night | Durable store: Redis on kv-store. Warm restart verified (8,448/8,448 tokens loaded from Redis, TTFT 2.6 → 1.5 s). Store bandwidth measured. Run log, spend log, $15 budget alert. |
| Tue 11-10 14:02–15:11 | L4 stockout on restart (69 min). In-zone retry won; a disk snapshot `kv-gpu-snap` is kept as a fallback. Real replacement startup time measured on that boot. |
| Tue afternoon | Merged the policy, plots and workload code. Built the emulator, the prefix → Redis key map, and a pilot run. Rate probe → 4 req/s. |
| Tue 15:43–18:35 local | All 8 configurations × 2 runs + 3 steady-state runs, no failures. |
| Tue 18:35–19:31 local | Follow-ups: none and write-through at notice 0 s (kill-time-matched, both seeds), plus the 2 req/s diagnostic, which confirmed head-of-line blocking. VMs stopped at 20:09. |

## What exists

| Path | What it is |
|---|---|
| `infra/` | setup_gpu.sh (pinned env), serve.sh / stop.sh, setup_store.sh (Redis), lmcache-local.yaml / lmcache-remote.yaml, smoke / warm-restart / bandwidth tests, TROUBLESHOOTING.md |
| `emulator/preempt.py` | Preemption emulator: `register` (prefix → Redis keys), `run` (one preemption), `steady` (no preemption) |
| `emulator/run_midterm.sh`, `run_extra.sh` | The midterm run set and the follow-ups. Resumable: finished runs are skipped. |
| `emulator/summarize.py` | Builds `results/midterm_preemption.csv` and `results/midterm_steady.csv` (+ markdown tables) from every run's summary |
| `results/runs/<run_id>/` | Per run: requests.csv (the workload log), events.json (t_notice, t_kill, t_ready, …), summary.json, logs |
| `results/run_log.csv`, `spend_log.csv` | One row per run / per session |
| `results/keymap.json` | prefix_id → the Redis keys of its 12 chunks (valid with PYTHONHASHSEED=0) |
| `analysis/make_figures.sh` → `figures/` | Every midterm figure (PNG + CSV of the plotted numbers) from `results/runs/`, both repeats pooled |

## Decisions and deviations from the plan

1. **The "remote LMCache server" is Redis.** LMCache 0.5.x has no `lm://` server; remote storage goes
   through adapters for external stores. Redis also lets the emulator list and delete keys.
2. **`PYTHONHASHSEED=0` is required.** LMCache names chunks with Python's `hash()`; without a fixed seed a
   replacement server can't find anything the old one saved.
3. **Rate 4 req/s, not the tentative 10.** At 10 req/s the median TTFT is about 29 s (pure queueing).
   Probe: 2 / 4 / 6 req/s → 193 / 261 / 395 ms.
4. **Prefixes are about 3,140 tokens, not about 5,700.** The README used chars ÷ 4, but these filler words
   are about 1 token each. Hot set: 64 × 12 chunks × 14.7 MB = **11.3 GB**. KV-bytes check: 176 MB
   stored vs. 180 MB estimated per prefix → correction factor **0.98**. The policy uses the exact
   `prompt_tokens`, so no change is needed there.
5. **Emulation shortcuts** (from the plan; the slides should say so):
   - The replacement is a vLLM restart on the same VM.
   - What reactive and hybrid "saved" comes from deleting keys in a write-through store, with the
     budget at the measured 0.71 GB/s. The flush isn't timed live.
   - Steady-state hybrid replicates its hot set as same-sized values, every 30 s.
6. **Hybrid N = 8** (the midterm setting). The preserved-vs-notice figure sweeps N = 4 / 8 / 16 on a real log.
7. **The kill-timing confound, and how it was fixed.** In the main set, none and write-through ran
   with the default 30 s wait. So in the 0 s comparison they were killed 30 s later in the request
   stream than reactive0 and hybrid0, and the post-restart transient depends strongly on which
   requests arrive first. `run_extra.sh` adds none0 and write-through0 runs for both seeds;
   `summarize.py` groups runs by strategy *and* notice. **Use none@0 for the 0 s comparison and
   none@30 for the 30 s one.**

## Open items

- [x] Follow-ups folded into `results/midterm_*.csv` and `docs/midterm.md` (2026-11-10).
- [x] Final midterm figures from `results/runs/`, both repeats pooled, none@0 for the 0 s figure (2026-11-10).
- [x] One README, plan, midterm doc and progress log for the whole project (2026-11-10).
- [ ] Build the 8 midterm slides from `docs/midterm.md` and rehearse once.
- [ ] After the midterm: ShareGPT and low-reuse runs, 3 repeats each, SpotLake-timed preemptions (`docs/plan.md`, weeks 7–8).
- [ ] Stop both VMs after each session (done 2026-11-10); the $15 budget alert will likely fire (≈ $1/h).
