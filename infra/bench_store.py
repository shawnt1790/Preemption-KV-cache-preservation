"""Measure write and read bandwidth from kv-gpu to the Redis store on kv-store, using
values the size of one LMCache chunk (256 tokens x 57,344 B/token for Qwen2.5-7B bf16).
The write number is BANDWIDTH_BPS for select_prefixes (bytes saved = bandwidth x window).
Usage (on kv-gpu): python bench_store.py [--host kv-store] [--total-gb 3]
Uses keys "bench:*" and deletes them afterwards; LMCache's keys are left alone.
"""
import argparse
import os
import time
from concurrent.futures import ThreadPoolExecutor

import redis

CHUNK_BYTES = 256 * 57344  # 14,680,064 = LMCache "full chunk size" in the vLLM log

p = argparse.ArgumentParser()
p.add_argument("--host", default="kv-store")
p.add_argument("--total-gb", type=float, default=3.0)
p.add_argument("--repeats", type=int, default=3)
args = p.parse_args()

n = max(1, int(args.total_gb * 1e9 // CHUNK_BYTES))
payload = os.urandom(CHUNK_BYTES)  # random, so nothing along the way can compress it
pool = redis.ConnectionPool(host=args.host, port=6379, max_connections=32)
r = redis.Redis(connection_pool=pool)


def run(op, threads: int) -> float:
    """Return GB/s for n chunk-sized SETs or GETs spread over `threads` connections."""
    start = time.perf_counter()
    with ThreadPoolExecutor(threads) as ex:
        results = list(ex.map(op, range(n)))
    elapsed = time.perf_counter() - start
    assert all(results), "an operation failed or returned nothing"
    return n * CHUNK_BYTES / elapsed / 1e9


def write(i):
    return r.set(f"bench:{i}", payload)


def read(i):
    return len(r.get(f"bench:{i}")) == CHUNK_BYTES


print(f"{n} chunks x {CHUNK_BYTES / 1e6:.1f} MB = {n * CHUNK_BYTES / 1e9:.2f} GB per pass, "
      f"{args.repeats} passes, best and median")
for threads in (1, 8):
    for name, op in (("write", write), ("read", read)):
        rates = sorted(run(op, threads) for _ in range(args.repeats))
        print(f"{name:5s} threads={threads}: best {rates[-1]:.2f} GB/s, "
              f"median {rates[len(rates) // 2]:.2f} GB/s")
r.delete(*[f"bench:{i}" for i in range(n)])
