#!/usr/bin/env python3
"""Workload generator for the spot KV-cache preservation project (Person B).

Sends streaming chat requests to a vLLM OpenAI-compatible server and logs
per-request TTFT and end-to-end latency to a CSV file.

Workloads
  high_reuse  a few long shared system prompts, Zipf-skewed popularity
  low_reuse   every prompt unique (control: prefix caching can't help)
  sharegpt    multi-turn ShareGPT conversations; full history resent each turn

Examples
  python workload_gen.py --workload high_reuse --num-requests 300 --rate 2 --out hr.csv
  python workload_gen.py --workload low_reuse  --num-requests 100 --rate 1 --out lr.csv
  python workload_gen.py --workload sharegpt --sharegpt-path ShareGPT_V3_unfiltered_cleaned_split.json \
      --num-sessions 50 --rate 0.5 --out sg.csv

Requires: pip install httpx numpy
"""
import argparse
import asyncio
import csv
import itertools
import json
import random
import time

import httpx
import numpy as np

FIELDS = ["req_id", "workload", "prefix_id", "session_id", "turn", "send_wall",
          "ttft_s", "e2e_s", "output_chunks", "prompt_chars", "prompt_tokens", "status"]

WORDS = ("cloud spot instance cache prefix token model server memory gpu request "
         "latency storage policy notice window block replica throughput cost "
         "preemption replication bandwidth eviction serving context").split()


def filler(n_words, rng):
    return " ".join(rng.choice(WORDS) for _ in range(n_words))


async def send(client, args, messages, meta, writer, fh):
    """Send one streaming request; record TTFT (first content token) and latency."""
    payload = {"model": args.model, "messages": messages, "max_tokens": args.max_tokens,
               "temperature": 0, "stream": True,
               # ask vLLM to report exact token counts in the final chunk
               "stream_options": {"include_usage": True}}
    wall = time.time()
    t0 = time.perf_counter()
    ttft, chunks, status, prompt_tokens = None, 0, "ok", None
    try:
        async with client.stream("POST", f"{args.base_url}/v1/chat/completions",
                                 json=payload) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    break
                obj = json.loads(data)
                usage = obj.get("usage")
                if usage and usage.get("prompt_tokens") is not None:
                    prompt_tokens = usage["prompt_tokens"]
                choices = obj.get("choices") or [{}]
                if choices[0].get("delta", {}).get("content"):
                    if ttft is None:
                        ttft = time.perf_counter() - t0
                    chunks += 1
    except Exception as e:  # server killed mid-request during a preemption, etc.
        status = f"error:{type(e).__name__}"
    e2e = time.perf_counter() - t0
    writer.writerow({**meta,
                     "send_wall": f"{wall:.3f}",
                     "ttft_s": f"{ttft:.4f}" if ttft is not None else "",
                     "e2e_s": f"{e2e:.4f}",
                     "output_chunks": chunks,
                     "prompt_chars": sum(len(m["content"]) for m in messages),
                     "prompt_tokens": prompt_tokens if prompt_tokens is not None else "",
                     "status": status})
    fh.flush()


# ---------- independent-request workloads (high_reuse, low_reuse) ----------

def high_reuse_requests(args, rng):
    prefixes = [filler(args.prefix_words, random.Random(1000 + k))
                for k in range(args.num_prefixes)]
    ranks = np.arange(1, args.num_prefixes + 1, dtype=float)
    p = ranks ** -args.zipf_s
    p /= p.sum()
    nprng = np.random.default_rng(args.seed)
    for i in range(args.num_requests):
        k = int(nprng.choice(args.num_prefixes, p=p))
        system = f"[shared prefix {k}] {prefixes[k]}"
        user = f"Request {i}: answer in one sentence. {filler(12, rng)}"
        yield ([{"role": "system", "content": system}, {"role": "user", "content": user}],
               {"prefix_id": f"hr-{k}", "session_id": "", "turn": 0})


def low_reuse_requests(args, rng):
    for i in range(args.num_requests):
        system = f"[unique prompt {i}] {filler(args.prefix_words, random.Random(10**6 + i))}"
        user = f"Request {i}: answer in one sentence."
        yield ([{"role": "system", "content": system}, {"role": "user", "content": user}],
               {"prefix_id": f"lr-{i}", "session_id": "", "turn": 0})


async def run_independent(args, gen, client, writer, fh):
    rng = random.Random(args.seed)
    tasks = []
    for i, (msgs, meta) in enumerate(gen):
        meta = {"req_id": i, "workload": args.workload, **meta}
        tasks.append(asyncio.create_task(send(client, args, msgs, meta, writer, fh)))
        await asyncio.sleep(rng.expovariate(args.rate))  # Poisson arrivals
    await asyncio.gather(*tasks)


# ---------- multi-turn ShareGPT sessions ----------

def load_sharegpt(args, rng):
    with open(args.sharegpt_path) as f:
        data = json.load(f)
    sessions = []
    for c in data:
        turns = c.get("conversations", [])
        pairs = []
        for a, b in zip(turns[::2], turns[1::2]):
            if a.get("from") != "human" or b.get("from") != "gpt":
                break
            pairs.append((a["value"][:args.max_msg_chars], b["value"][:args.max_msg_chars]))
        if len(pairs) >= args.min_turns:
            sessions.append((str(c.get("id", len(sessions))), pairs[:args.max_turns]))
    rng.shuffle(sessions)
    return sessions[:args.num_sessions]


async def run_session(args, sid, pairs, client, writer, fh, counter, rng):
    # Recorded assistant replies are used as history, so every turn's prefix is
    # deterministic and turn t+1 reuses turn t's prefix exactly.
    history = [{"role": "system", "content": args.system_prompt}]
    for t, (user, assistant) in enumerate(pairs):
        msgs = history + [{"role": "user", "content": user}]
        meta = {"req_id": next(counter), "workload": "sharegpt",
                "prefix_id": f"sg-{sid}", "session_id": sid, "turn": t}
        await send(client, args, msgs, meta, writer, fh)
        history = msgs + [{"role": "assistant", "content": assistant}]
        await asyncio.sleep(rng.expovariate(1.0 / args.think_time))


async def run_sharegpt(args, client, writer, fh):
    rng = random.Random(args.seed)
    counter = itertools.count()
    tasks = []
    for sid, pairs in load_sharegpt(args, rng):
        tasks.append(asyncio.create_task(
            run_session(args, sid, pairs, client, writer, fh, counter, random.Random(rng.random()))))
        await asyncio.sleep(rng.expovariate(args.rate))  # Poisson session starts
    await asyncio.gather(*tasks)


async def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--model", default="Qwen/Qwen2.5-7B-Instruct")
    ap.add_argument("--workload", choices=["high_reuse", "low_reuse", "sharegpt"], required=True)
    ap.add_argument("--out", required=True, help="CSV file to write")
    ap.add_argument("--rate", type=float, default=1.0,
                    help="requests/s (high/low reuse) or session starts/s (sharegpt)")
    ap.add_argument("--max-tokens", type=int, default=64)
    ap.add_argument("--seed", type=int, default=0)
    # high_reuse / low_reuse
    ap.add_argument("--num-requests", type=int, default=200)
    ap.add_argument("--num-prefixes", type=int, default=8)
    ap.add_argument("--prefix-words", type=int, default=3000, help="~1.3 tokens per word")
    ap.add_argument("--zipf-s", type=float, default=1.1, help="higher = more skewed reuse")
    # sharegpt
    ap.add_argument("--sharegpt-path")
    ap.add_argument("--num-sessions", type=int, default=50)
    ap.add_argument("--min-turns", type=int, default=3)
    ap.add_argument("--max-turns", type=int, default=8)
    ap.add_argument("--max-msg-chars", type=int, default=4000)
    ap.add_argument("--think-time", type=float, default=5.0, help="mean seconds between turns")
    ap.add_argument("--system-prompt", default="You are a helpful assistant.")
    args = ap.parse_args()

    if args.workload == "sharegpt" and not args.sharegpt_path:
        ap.error("--sharegpt-path is required for the sharegpt workload")

    rng = random.Random(args.seed)
    timeout = httpx.Timeout(600.0, connect=10.0)
    with open(args.out, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        async with httpx.AsyncClient(timeout=timeout) as client:
            if args.workload == "high_reuse":
                await run_independent(args, high_reuse_requests(args, rng), client, writer, fh)
            elif args.workload == "low_reuse":
                await run_independent(args, low_reuse_requests(args, rng), client, writer, fh)
            else:
                await run_sharegpt(args, client, writer, fh)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    asyncio.run(main())