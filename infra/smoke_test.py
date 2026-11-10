"""Smoke test: send the same long prompt twice; the second TTFT should be much lower
because its prefix KV is reused (GPU prefix cache, or LMCache's CPU tier).
Usage: python smoke_test.py [--base-url http://localhost:8000] [--model Qwen/Qwen2.5-7B-Instruct]
"""
import argparse
import json
import time
import urllib.request

p = argparse.ArgumentParser()
p.add_argument("--base-url", default="http://localhost:8000")
p.add_argument("--model", default="Qwen/Qwen2.5-7B-Instruct")
args = p.parse_args()

# ~8.4K tokens of distinct, non-repeating text (repeated text could compress oddly in tokenization)
context = " ".join(f"Record {i}: sensor {i % 97} read {i * 37 % 1000} units at hour {i % 24}." for i in range(400))
prompt = f"{context}\n\nQuestion: which sensor id appears in record 123? Answer briefly."


def ttft() -> float:
    body = json.dumps({"model": args.model, "prompt": prompt, "max_tokens": 8,
                       "temperature": 0, "stream": True}).encode()
    req = urllib.request.Request(f"{args.base_url}/v1/completions", body,
                                 {"Content-Type": "application/json"})
    start = time.perf_counter()
    with urllib.request.urlopen(req) as resp:
        for line in resp:
            if line.startswith(b"data: ") and b'"text"' in line:
                return time.perf_counter() - start
    raise RuntimeError("no tokens streamed")


first, second = ttft(), ttft()
print(f"TTFT cold {first * 1000:.0f} ms | warm {second * 1000:.0f} ms | speedup {first / second:.1f}x")
