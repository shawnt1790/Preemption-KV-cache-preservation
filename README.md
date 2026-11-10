# Preemption-Aware KV Cache Preservation for LLM Serving on Spot Instances

CS 6111 Cloud Computing, Group 3.

When a spot GPU is preempted, its prefix KV cache is lost and every returning request has to recompute its context. This project compares four ways to preserve that cache: no preservation, always-on write-through, reactive flush on notice, and a hybrid that keeps the hottest prefixes copied in advance.

## Layout

| Folder | What's in it |
| --- | --- |
| `workload/` | `workload_gen.py`: sends requests to vLLM and logs TTFT per request |
| `policy/` | `policy.py`: hotness ranking and the reactive/hybrid policies; `test_policy.py` |
| `analysis/` | `plots.py`: the three midterm figures |
| `tools/` | `mock_vllm_server.py`: a fake vLLM server for testing without a GPU |
| `results/` | CSV logs from runs (not committed) |
| `figures/` | PNG figures and their CSV tables |

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install httpx numpy matplotlib
```

## 1. Workload generator

Sends streaming requests to a vLLM server and writes one CSV row per request (`prefix_id`, `send_wall`, `ttft_s`, `e2e_s`, `prompt_tokens`, `status`, ...). Failed requests (for example while the server is down) are logged as `error`, not crashed on.

```bash
python workload/workload_gen.py --workload high_reuse --num-prefixes 64 --num-requests 400 --rate 10 \
    --base-url http://localhost:8000 --model Qwen/Qwen2.5-7B-Instruct --out results/hr.csv
```

- `--model` must match the name the vLLM server loaded exactly (use an Instruct model).
- `--base-url` defaults to `http://localhost:8000`; run the generator on the VM, or point this at the VM.
- Workloads: `high_reuse` (shared long system prompts, skewed popularity), `sharegpt` (real multi-turn chats, below), `low_reuse` (control).

**Midterm settings (tentative):** `--workload high_reuse --num-prefixes 64`. Revisit once the store bandwidth is measured.

### ShareGPT workload

Real multi-turn conversations. Each turn resends the whole conversation so far, so a turn reuses the previous turn's prefix, and `prompt_tokens` grows within a session.

Download the dataset once (about 650 MB; `data/` and `.json` files are git-ignored, so it never gets committed):

```bash
mkdir -p data
curl -L -o data/sharegpt.json https://huggingface.co/datasets/anon8231489123/ShareGPT_Vicuna_unfiltered/resolve/main/ShareGPT_V3_unfiltered_cleaned_split.json
```

Run it:

```bash
python workload/workload_gen.py --workload sharegpt --sharegpt-path data/sharegpt.json \
    --num-sessions 50 --rate 0.5 --think-time 5 --out results/sharegpt.csv
```

- `--num-sessions`: how many conversations; `--rate`: new conversations per second; `--think-time`: average seconds between turns.
- `--max-turns` (default 8) and `--max-msg-chars` (default 4000) cap conversation length. If long conversations show up as `error` rows (too long for the server's `--max-model-len`), lower them.
- ShareGPT prompts are much shorter than `high_reuse` ones (hundreds of tokens vs. about 5,700), so there is less cache to preserve and the strategies will differ less.

## 2. Policies

`policy/policy.py` decides which prefixes survive a preemption. It works only from the generator's CSV, so it doesn't depend on the server.

```python
import sys; sys.path.insert(0, "policy")
from policy import rank_prefixes, select_prefixes, hot_set, KV_BYTES_PER_TOKEN

kv = KV_BYTES_PER_TOKEN["Qwen/Qwen2.5-7B-Instruct"]
ranked, sizes = rank_prefixes("results/hr.csv", t_notice, kv)   # hottest first, sizes in bytes

keep = select_prefixes(ranked, sizes, bandwidth_Bps, notice_s)                # reactive flush
keep = select_prefixes(ranked, sizes, bandwidth_Bps, notice_s, hot_set_n=8)  # hybrid
to_copy_in_background = hot_set(ranked, 8)                                    # hybrid, every ~30 s
```

- **Hotness** = requests in the last 300 s × prompt tokens. Ties go to the larger prefix.
- **Budget** = bandwidth × (notice − 2 s). Prefixes are kept hottest first while they fit.
- **No preservation** keeps nothing and **write-through** keeps everything, so neither calls these functions.
- **Midterm setting:** `hot_set_n=8`.

**How the emulator uses it at a preemption:** record `t_notice` → `rank_prefixes` → `select_prefixes` → delete every prefix not in `keep` from the remote store → kill and restart vLLM, with the generator still running.

Run the tests (expect `all tests passed`):

```bash
cd policy && python test_policy.py && cd ..
```

## 3. Figures

```bash
# How much of the hot cache survives vs. notice length (needs one log + measured bandwidth)
python analysis/plots.py preserved --log results/hr.csv --bandwidth-mbps 200 --hybrid-n 8 --out figures/preserved.png

# TTFT over time across a preemption, one line per strategy
python analysis/plots.py ttft \
    --run "No preservation=results/none.csv,results/none_events.json" \
    --run "Write-through=results/wt.csv,results/wt_events.json" \
    --run "Reactive flush=results/reactive30.csv,results/reactive30_events.json" \
    --run "Hybrid=results/hybrid30.csv,results/hybrid30_events.json" \
    --out figures/ttft_preemption.png

# Steady-state TTFT and throughput (runs with no preemption)
python analysis/plots.py overhead \
    --run "No preservation=results/ss_none.csv" --run "Write-through=results/ss_wt.csv" \
    --run "Hybrid=results/ss_hybrid.csv" --out figures/overhead.png
```

**The `ttft` figure needs an events file per run from the emulator**, wall-clock Unix seconds:

```json
{"t_notice": 1794268000.0, "t_kill": 1794268030.0, "t_ready": 1794268045.0}
```

## Testing without a GPU

```bash
python tools/mock_vllm_server.py          # terminal 1; leave running
python workload/workload_gen.py --workload high_reuse --num-requests 50 --rate 5 --out results/mock.csv   # terminal 2
```

The fake server speaks vLLM's API: a repeated prefix is about 10× faster, and restarting it (Ctrl+C, start again) clears its cache like a preemption. Its timings and token counts are made up, so use it to test code, never for results.