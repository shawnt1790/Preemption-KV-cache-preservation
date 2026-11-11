# Preemption-Aware KV Cache Preservation for LLM Serving on Spot Instances

CS 6111 Cloud Computing, Group 3.

When a spot GPU is preempted, its prefix KV cache is lost and every returning request has to recompute its context. This project compares four ways to preserve that cache in a durable store: no preservation, always-on write-through, reactive flush on notice, and a hybrid that keeps the hottest prefixes copied in advance.

**Midterm results (2026-11-10):** `docs/midterm.md`, with the figures in `figures/`. In short: losing the cache turns a ~220 ms median TTFT into 6–9 s for the first minute after a restart. Anything that keeps the hot set recovers at ~0.5 s. With 30 s of notice, reactive flush saves the whole 11.3 GB hot set, so it matches write-through. At 0 s notice only write-through helps. Write-through holds 5.3× more storage than hybrid, at no measurable latency cost.

## How the pieces fit

```
workload/workload_gen.py ──requests──▶ vLLM + LMCache (kv-gpu, L4) ──write-through──▶ Redis (kv-store)
        │ request log (CSV)                    ▲ kill / restart                          ▲ keep / delete
        ▼                                      │                                         │
emulator/preempt.py ── notice → policy/policy.py (which prefixes survive) → kill → delete the rest → restart
        │
        ▼
results/runs/<run_id>/ ──▶ emulator/summarize.py (tables)  ·  analysis/make_figures.sh (figures)
```

| Folder | What's in it |
| --- | --- |
| `infra/` | GPU VM setup (pinned vLLM 0.32.0 + LMCache 0.5.7), `serve.sh` / `stop.sh`, Redis store setup, LMCache configs, smoke / warm-restart / bandwidth tests, `TROUBLESHOOTING.md` |
| `workload/` | `workload_gen.py`: sends requests to vLLM and logs TTFT per request |
| `policy/` | `policy.py`: hotness ranking and the reactive/hybrid policies; `test_policy.py` |
| `emulator/` | `preempt.py`: one emulated preemption (or a steady-state run); the midterm run scripts; `summarize.py` |
| `analysis/` | `plots.py`: the three figure types; `make_figures.sh`: every midterm figure from `results/runs/` |
| `results/` | Every run's logs and events, the midterm tables, run and spend logs, one-off measurements (`results/README.md`) |
| `figures/` | Midterm figures (PNG) and the plotted numbers (CSV) |
| `tools/` | `mock_vllm_server.py`: a fake vLLM server for testing without a GPU |
| `docs/` | `plan.md` (plan, checklist, policy interface spec), `midterm.md` (results and slide content), `progress-log.md` (timeline and decisions) |

## Local setup (analysis, policy, mock server)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install httpx numpy matplotlib redis
```

Re-make every midterm figure and table from the committed runs, without a GPU:

```bash
bash analysis/make_figures.sh     # figures/*.png and *.csv
python emulator/summarize.py      # results/midterm_preemption.csv, results/midterm_steady.csv
cd policy && python test_policy.py && cd ..   # expect "all tests passed"
```

## 1. Serving stack (GCP)

Two VMs in us-central1-a: **kv-gpu** (g2-standard-8, 1× L4) runs vLLM; **kv-store** (n2-highmem-4) runs Redis as the durable KV store.

```bash
# on kv-store
bash infra/setup_store.sh                       # Redis, reachable only from the internal network
# on kv-gpu
bash infra/setup_gpu.sh                         # pinned env in ~/kv-env (see requirements-gpu.lock.txt)
bash infra/serve.sh infra/lmcache-remote.yaml   # vLLM + prefix caching + LMCache, write-through to Redis
python infra/smoke_test.py                      # a repeated long prompt is faster the second time
bash infra/warm_restart_test.sh                 # KV in Redis survives a restart and is loaded back
python infra/bench_store.py                     # store write/read bandwidth
bash infra/stop.sh
```

- `lmcache-local.yaml` is the CPU tier only; `lmcache-remote.yaml` adds Redis.
- **`PYTHONHASHSEED=0` is required** (`serve.sh` sets it): LMCache names chunks with Python's `hash()`, so without a fixed seed a restarted server can't find anything the old one saved.
- Stop both VMs after every session. Setup problems and fixes: `infra/TROUBLESHOOTING.md`.

## 2. Workload generator

Sends streaming requests to a vLLM server and writes one CSV row per request (`prefix_id`, `send_wall`, `ttft_s`, `e2e_s`, `prompt_tokens`, `status`, ...). Failed requests (for example while the server is down) are logged as `error`, not crashed on.

```bash
python workload/workload_gen.py --workload high_reuse --num-prefixes 64 --num-requests 400 --rate 4 \
    --base-url http://localhost:8000 --model Qwen/Qwen2.5-7B-Instruct --out results/hr.csv
```

- `--model` must match the name the vLLM server loaded exactly (use an Instruct model).
- Workloads: `high_reuse` (shared long system prompts, skewed popularity), `sharegpt` (real multi-turn chats, below), `low_reuse` (control).
- **Midterm settings:** `high_reuse`, 64 prefixes of ~3,140 tokens each (11.3 GB hot set), **4 req/s**. At 10 req/s the server is saturated (median TTFT ~29 s from queueing alone).

### ShareGPT workload

Real multi-turn conversations. Each turn resends the whole conversation so far, so a turn reuses the previous turn's prefix, and `prompt_tokens` grows within a session.

Download the dataset once (about 650 MB; `data/` is git-ignored, so it never gets committed):

```bash
mkdir -p data
curl -L -o data/sharegpt.json https://huggingface.co/datasets/anon8231489123/ShareGPT_Vicuna_unfiltered/resolve/main/ShareGPT_V3_unfiltered_cleaned_split.json
python workload/workload_gen.py --workload sharegpt --sharegpt-path data/sharegpt.json \
    --num-sessions 50 --rate 0.5 --think-time 5 --out results/sharegpt.csv
```

- `--num-sessions`: how many conversations; `--rate`: new conversations per second; `--think-time`: average seconds between turns.
- `--max-turns` (default 8) and `--max-msg-chars` (default 4000) cap conversation length. If long conversations show up as `error` rows (too long for the server's `--max-model-len`), lower them.
- ShareGPT prompts are much shorter than `high_reuse` ones (hundreds of tokens vs. about 3,100), so there is less cache to preserve and the strategies will differ less.

## 3. Policies

`policy/policy.py` decides which prefixes survive a preemption. It works only from the generator's CSV, so it doesn't depend on the server. The interface spec is in `docs/plan.md`.

```python
import sys; sys.path.insert(0, "policy")
from policy import rank_prefixes, select_prefixes, hot_set, KV_BYTES_PER_TOKEN

kv = KV_BYTES_PER_TOKEN["Qwen/Qwen2.5-7B-Instruct"]
ranked, sizes = rank_prefixes("results/hr.csv", t_notice, kv)   # hottest first, sizes in bytes

keep = select_prefixes(ranked, sizes, bandwidth_Bps, notice_s)                # reactive flush
keep = select_prefixes(ranked, sizes, bandwidth_Bps, notice_s, hot_set_n=8)  # hybrid
to_copy_in_background = hot_set(ranked, 8)                                    # hybrid, every 30 s
```

- **Hotness** = requests in the last 300 s × prompt tokens. Ties go to the larger prefix.
- **Budget** = bandwidth × (notice − 2 s), with the measured `BANDWIDTH_BPS = 7.1e8` (Redis write, 1 connection). Prefixes are kept hottest first while they fit.
- **No preservation** keeps nothing and **write-through** keeps everything, so neither calls these functions.
- **Midterm setting:** `hot_set_n=8` (N = 4 / 8 / 16 compared in `figures/preserved.png`).

## 4. Preemption emulator

`emulator/preempt.py` runs on kv-gpu next to vLLM, from the repo root:

```bash
python emulator/preempt.py register --rate 4          # once: map each prefix_id to its Redis keys (results/keymap.json)
python emulator/preempt.py run --strategy hybrid --notice-s 30 --rate 4 --seed 1 --run-id hybrid30-r1
python emulator/preempt.py steady --strategy write-through --rate 4 --seed 1 --run-id steady-write-through-r1
```

A `run` starts a fresh write-through server, serves the workload for 180 s, sends the notice, asks the policy what to keep, waits the notice length, kills vLLM, deletes from Redis every prefix the strategy wouldn't have saved, restarts vLLM, and serves 180 s more. The workload never stops. Every step is timestamped in `events.json`.

- **The midterm set:** `bash emulator/run_midterm.sh --rate 4` (8 configurations × 2 seeds + 3 steady-state runs), then `bash emulator/run_extra.sh --rate 4` (none and write-through at 0 s, and a 2 req/s diagnostic). Both are resumable: finished runs are skipped.
- Output per run: `results/runs/<run_id>/{requests.csv, events.json, summary.json, *.log}`, plus a row in `results/run_log.csv`.
- **Emulation shortcuts** (state them when presenting): the replacement is a restart on the same VM, and what reactive/hybrid saved comes from deleting keys in a write-through store at the measured bandwidth. Real replacement startup (~230 s) and store bandwidth were measured separately; see `results/README.md`.

## 5. Tables and figures

```bash
python emulator/summarize.py      # repeat-averaged tables, grouped by strategy and notice
bash analysis/make_figures.sh     # all five midterm figures
```

| Figure | What it shows |
| --- | --- |
| `figures/ttft_30s.png`, `ttft_0s.png`, `ttft_120s.png` | Median TTFT over time across a preemption, one line per strategy, both repeats pooled |
| `figures/preserved.png` | Share of recent prefill work preserved vs. notice length, reactive vs. hybrid N = 4 / 8 / 16 |
| `figures/overhead.png` | Steady-state TTFT, throughput and store size for none, write-through and hybrid |

`analysis/plots.py` makes each figure type from any runs. See its `--help`, or the commands in `make_figures.sh`. Every figure is written with a CSV of the plotted numbers next to it.

## Testing without a GPU

```bash
python tools/mock_vllm_server.py          # terminal 1; leave running
python workload/workload_gen.py --workload high_reuse --num-requests 50 --rate 5 --out results/mock.csv   # terminal 2
```

The fake server speaks vLLM's API: a repeated prefix is about 10× faster, and restarting it (Ctrl+C, start again) clears its cache like a preemption. Its timings and token counts are made up, so use it to test code, never for results.
