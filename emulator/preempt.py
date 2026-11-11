#!/usr/bin/env python3
"""Preemption emulator (Person A). Runs on kv-gpu, next to vLLM and the Redis store.

  register  Map each high-reuse prefix_id to the Redis keys of its KV chunks (run once).
  run       One preemption: workload -> notice -> wait -> kill -> keep what the strategy
            saved -> replacement server -> workload continues.
  steady    No preemption; measures the steady-state cost of a strategy.

Plan shortcuts, which the slides should state:
  * The replacement is a restart of vLLM on the same VM. That frees GPU memory and LMCache's
    CPU tier; weights reload from the local disk.
  * Every `run` writes through to Redis while serving. At the kill, the emulator deletes the
    chunks of every prefix the strategy would not have saved within the notice window, so the
    replacement finds exactly what that strategy preserved.
    none: delete all; write-through: keep all; reactive/hybrid: keep policy.select_prefixes().
  * The steady-state hybrid replicates its hot set as same-sized Redis values every 30 s.
    That reproduces the traffic and storage, but they're not LMCache's own chunks.

Output: results/runs/<run_id>/{requests.csv, events.json, summary.json, *.log}, plus a row
in results/run_log.csv. events.json has the t_notice/t_kill/t_ready that analysis/plots.py reads.
"""
import argparse
import csv
import json
import os
import random
import signal
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import redis

REPO = Path(__file__).resolve().parent.parent
INFRA = REPO / "infra"
RESULTS = REPO / "results"
sys.path.insert(0, str(REPO / "policy"))
sys.path.insert(0, str(REPO / "workload"))
from policy import KV_BYTES_PER_TOKEN, hot_set, hotness_table, rank_prefixes, select_prefixes  # noqa: E402
from workload_gen import filler  # noqa: E402  (same prompt text as the high_reuse workload)

MODEL = "Qwen/Qwen2.5-7B-Instruct"
KV = KV_BYTES_PER_TOKEN[MODEL]
BANDWIDTH_BPS = 7.1e8      # measured Redis write rate, 1 connection (results/README.md)
KEYMAP = RESULTS / "keymap.json"
CONFIG = {"none": "lmcache-local.yaml", "write-through": "lmcache-remote.yaml",
          "hybrid": "lmcache-local.yaml"}   # steady-state configs; every `run` uses remote


def store():
    return redis.Redis(host="kv-store", port=6379)


def sh(script, *args, log=None):
    subprocess.run(["bash", str(INFRA / script), *args], check=True,
                   stdout=log, stderr=subprocess.STDOUT if log else None)


def fresh_server(config, log):
    """Stop vLLM, empty the store, start vLLM with `config`. Returns seconds to ready."""
    sh("stop.sh", log=log)
    store().flushall()
    t = time.time()
    sh("serve.sh", config, log=log)
    return time.time() - t


def start_workload(args, out_csv, log):
    cmd = [sys.executable, str(REPO / "workload" / "workload_gen.py"), "--workload", "high_reuse",
           "--num-prefixes", str(args.num_prefixes), "--prefix-words", str(args.prefix_words),
           "--num-requests", "1000000", "--rate", str(args.rate), "--seed", str(args.seed),
           "--model", MODEL, "--out", str(out_csv)]
    return subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)


def stop_workload(proc):
    proc.send_signal(signal.SIGINT)   # the generator flushes each row, so the CSV stays whole
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()


def read_rows(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q / 100 * len(xs)))] * 1000 if xs else None


def ttft_stats(rows, t0, t1):
    """p50/p99 TTFT (ms) and throughput for ok requests sent in [t0, t1)."""
    ok = [r for r in rows if r["status"] == "ok" and t0 <= float(r["send_wall"]) < t1 and r["ttft_s"]]
    ttft = [float(r["ttft_s"]) for r in ok]
    e2e = [float(r["e2e_s"]) for r in ok]
    span = max(t1 - t0, 1e-9)
    return {"n_ok": len(ok), "ttft_p50_ms": pct(ttft, 50), "ttft_p99_ms": pct(ttft, 99),
            "e2e_p50_ms": pct(e2e, 50), "e2e_p99_ms": pct(e2e, 99),
            "throughput_req_s": len(ok) / span,
            "throughput_tok_s": sum(int(r["output_chunks"] or 0) for r in ok) / span}


def store_bytes(r, keys=None):
    """Total value bytes in the store (or of `keys`)."""
    keys = list(r.scan_iter(count=1000)) if keys is None else keys
    pipe = r.pipeline()
    for k in keys:
        pipe.strlen(k)
    return sum(pipe.execute()) if keys else 0


def append_run_log(row):
    path = RESULTS / "run_log.csv"
    with open(path, newline="") as fh:
        fields = next(csv.reader(fh))
    with open(path, "a", newline="") as fh:
        csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore").writerow(row)


# ---------------------------------------------------------------- register

def cmd_register(args):
    """Send each prefix once to an empty store and record which keys appear. With
    PYTHONHASHSEED=0 the keys are the same on every server, so this runs once."""
    run_dir = RESULTS / "runs" / "register"
    run_dir.mkdir(parents=True, exist_ok=True)
    with open(run_dir / "emulator.log", "w") as log:
        fresh_server("lmcache-remote.yaml", log)
    r = store()
    keymap, seen = {}, set()
    with httpx.Client(timeout=600) as client:
        for k in range(args.num_prefixes):
            system = f"[shared prefix {k}] {filler(args.prefix_words, random.Random(1000 + k))}"
            client.post("http://localhost:8000/v1/chat/completions", json={
                "model": MODEL, "max_tokens": 1, "temperature": 0,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": "Register this prefix."}]}).raise_for_status()
            # LMCache writes asynchronously: wait until the key count stops changing.
            last, stable = -1, 0
            while stable < 4:
                n = r.dbsize()
                stable = stable + 1 if n == last else 0
                last = n
                time.sleep(0.25)
            keys = {key.decode() for key in r.scan_iter(count=1000)} - seen
            seen |= keys
            keymap[f"hr-{k}"] = sorted(keys)
            print(f"hr-{k}: {len(keys)} keys", flush=True)
    meta = {"num_prefixes": args.num_prefixes, "prefix_words": args.prefix_words,
            "total_bytes": store_bytes(r), "keymap": keymap}
    KEYMAP.write_text(json.dumps(meta, indent=1))
    chunks = sum(len(v) for v in keymap.values()) // 2
    print(f"wrote {KEYMAP}: {chunks} chunks, {meta['total_bytes'] / 1e9:.2f} GB")


def load_keymap(args):
    meta = json.loads(KEYMAP.read_text())
    assert (meta["num_prefixes"], meta["prefix_words"]) == (args.num_prefixes, args.prefix_words), \
        "keymap was built for a different workload; rerun `register`"
    return meta["keymap"]


# ---------------------------------------------------------------- run

def cmd_run(args):
    keymap = load_keymap(args)
    label = args.strategy if args.strategy in ("none", "write-through") else f"{args.strategy}{args.notice_s:g}"
    run_id = args.run_id or f"{label}-r{args.seed}"
    run_dir = RESULTS / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    req_csv, ev = run_dir / "requests.csv", {}
    log = open(run_dir / "emulator.log", "w")
    r = store()

    ev["first_start_s"] = fresh_server("lmcache-remote.yaml", log)
    wl = start_workload(args, req_csv, open(run_dir / "workload.log", "w"))
    ev["t_start"] = time.time()
    time.sleep(args.pre_s)

    # Notice. The policy decides now, from the request log so far.
    ev["t_notice"] = time.time()
    ranked, sizes = rank_prefixes(str(req_csv), ev["t_notice"], KV)
    if args.strategy == "none":
        keep = []
    elif args.strategy == "write-through":
        keep = list(ranked)
    else:
        n = args.hot_set_n if args.strategy == "hybrid" else 0
        keep = select_prefixes(ranked, sizes, BANDWIDTH_BPS, args.notice_s, hot_set_n=n)
    freq = {p: f for p, (f, _, _) in hotness_table(str(req_csv), ev["t_notice"]).items()}
    storage_at_notice = r.info("memory")["used_memory"]
    time.sleep(args.notice_s)  # vLLM keeps serving through the notice window

    # Kill. Process exit frees GPU memory and LMCache's CPU tier.
    ev["t_kill"] = time.time()
    sh("stop.sh", log=log)
    ev["t_killed"] = time.time()
    gpu_mib = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True).stdout.strip()

    # Leave in the store only what this strategy would have saved.
    if args.strategy != "write-through":
        keep_keys = {k.encode() for p in keep for k in keymap.get(p, [])}
        drop = [k for k in r.scan_iter(count=1000) if k not in keep_keys]
        for i in range(0, len(drop), 500):
            r.delete(*drop[i:i + 500])
    bytes_saved = store_bytes(r)

    # Replacement server; the workload keeps sending the whole time.
    ev["t_restart"] = time.time()
    sh("serve.sh", "lmcache-remote.yaml", log=log)
    ev["t_ready"] = time.time()
    time.sleep(args.post_s)
    stop_workload(wl)
    ev["t_end"] = time.time()

    rows = read_rows(req_csv)
    after = [r_ for r_ in rows if r_["status"] == "ok" and float(r_["send_wall"]) >= ev["t_ready"]]
    if after:
        first = min(after, key=lambda r_: float(r_["send_wall"]) + float(r_["e2e_s"]))
        ev["t_first_served"] = float(first["send_wall"]) + float(first["ttft_s"] or first["e2e_s"])
    hot_bytes = sum(sizes.values())
    summary = {
        "run_id": run_id, "strategy": args.strategy, "notice_s": args.notice_s,
        "hot_set_n": args.hot_set_n if args.strategy == "hybrid" else None, "seed": args.seed,
        "rate": args.rate, "num_prefixes": args.num_prefixes, "bandwidth_Bps": BANDWIDTH_BPS,
        "ranked": ranked, "keep": keep,
        "share_preserved_pct": 100 * sum(sizes[p] for p in keep if p in sizes) / hot_bytes if hot_bytes else 0,
        # share of the last 300 s of requests whose prefix survived (closer to the TTFT impact)
        "share_requests_preserved_pct": 100 * sum(freq.get(p, 0) for p in keep) / max(sum(freq.values()), 1),
        "bytes_saved": bytes_saved, "storage_at_notice_bytes": storage_at_notice,
        "gpu_mem_after_kill_mib": gpu_mib,
        "downtime_s": ev["t_ready"] - ev["t_kill"],
        "restart_to_ready_s": ev["t_ready"] - ev["t_restart"],
        "kill_to_first_served_s": ev.get("t_first_served", float("nan")) - ev["t_kill"],
        "before": ttft_stats(rows, ev["t_start"] + args.warmup_s, ev["t_notice"]),
        "after_60s": ttft_stats(rows, ev["t_ready"], ev["t_ready"] + 60),
        "after_all": ttft_stats(rows, ev["t_ready"], ev["t_end"]),
        "errors": sum(1 for r_ in rows if r_["status"] != "ok"),
    }
    (run_dir / "events.json").write_text(json.dumps(ev, indent=1))
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=1))
    append_run_log({
        "run_id": run_id, "date": time.strftime("%Y-%m-%d"), "strategy": args.strategy,
        "workload": f"high-reuse ({args.num_prefixes} prefixes, {args.rate:g} req/s)",
        "notice_s": args.notice_s, "hot_set_n": summary["hot_set_n"] or "", "repeat": args.seed,
        "lmcache_config": "lmcache-remote.yaml + emulated deletes",
        "ttft_p50_ms": round(summary["before"]["ttft_p50_ms"] or 0),
        "ttft_p99_ms": round(summary["before"]["ttft_p99_ms"] or 0),
        "first_ttft_after_restart_ms": round(summary["after_60s"]["ttft_p50_ms"] or 0),
        "throughput_tok_s": round(summary["before"]["throughput_tok_s"]),
        "bytes_saved": bytes_saved, "storage_bytes": storage_at_notice, "status": "ok",
        "notes": f"preserved {summary['share_preserved_pct']:.0f}% of hot-set bytes, "
                 f"{summary['share_requests_preserved_pct']:.0f}% of recent requests; "
                 f"after-restart TTFT p50 is over the first 60 s; downtime {summary['downtime_s']:.0f} s",
    })
    print(json.dumps({k: summary[k] for k in ("run_id", "share_preserved_pct", "downtime_s")}
                     | {"before_p50": summary["before"]["ttft_p50_ms"],
                        "after60_p50": summary["after_60s"]["ttft_p50_ms"]}))


# ---------------------------------------------------------------- steady

def replicate_hot_set(req_csv, n, stop, stats):
    """Hybrid's background path: every 30 s, copy hot prefixes that aren't in the store yet."""
    r, done = store(), set()
    while not stop.wait(30):
        ranked, sizes = rank_prefixes(str(req_csv), time.time(), KV)
        for p in hot_set(ranked, n):
            if p not in done:
                r.set(f"hybrid:{p}", os.urandom(sizes[p]))
                done.add(p)
                stats["bytes_replicated"] += sizes[p]
                stats["prefixes"] = sorted(done)


def cmd_steady(args):
    run_id = args.run_id or f"steady-{args.strategy}-r{args.seed}"
    run_dir = RESULTS / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    req_csv, log = run_dir / "requests.csv", open(run_dir / "emulator.log", "w")
    fresh_server(CONFIG[args.strategy], log)
    wl = start_workload(args, req_csv, open(run_dir / "workload.log", "w"))
    t_start, stop, stats = time.time(), threading.Event(), {"bytes_replicated": 0, "prefixes": []}
    if args.strategy == "hybrid":
        threading.Thread(target=replicate_hot_set, args=(req_csv, args.hot_set_n, stop, stats),
                         daemon=True).start()
    time.sleep(args.warmup_s + args.measure_s)
    stop.set()
    stop_workload(wl)
    t_measure = t_start + args.warmup_s
    s = ttft_stats(read_rows(req_csv), t_measure, t_measure + args.measure_s)
    storage = store().info("memory")["used_memory"]
    summary = {"run_id": run_id, "strategy": args.strategy, "rate": args.rate, "seed": args.seed,
               "storage_bytes": storage, **stats, **s}
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=1))
    append_run_log({
        "run_id": run_id, "date": time.strftime("%Y-%m-%d"), "strategy": args.strategy,
        "workload": f"high-reuse ({args.num_prefixes} prefixes, {args.rate:g} req/s), steady state",
        "hot_set_n": args.hot_set_n if args.strategy == "hybrid" else "", "repeat": args.seed,
        "lmcache_config": CONFIG[args.strategy] + (" + replicator" if args.strategy == "hybrid" else ""),
        "ttft_p50_ms": round(s["ttft_p50_ms"] or 0), "ttft_p99_ms": round(s["ttft_p99_ms"] or 0),
        "throughput_tok_s": round(s["throughput_tok_s"]), "storage_bytes": storage, "status": "ok",
        "notes": f"e2e p50/p99 {s['e2e_p50_ms'] or 0:.0f}/{s['e2e_p99_ms'] or 0:.0f} ms, "
                 f"{s['throughput_req_s']:.2f} req/s over {args.measure_s:g} s",
    })
    print(json.dumps(summary))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["register", "run", "steady"])
    ap.add_argument("--strategy", choices=["none", "write-through", "reactive", "hybrid"])
    ap.add_argument("--notice-s", type=float, default=30)
    ap.add_argument("--hot-set-n", type=int, default=8)          # Person B's midterm setting
    ap.add_argument("--num-prefixes", type=int, default=64)       # Person B's midterm setting
    ap.add_argument("--prefix-words", type=int, default=3000)
    ap.add_argument("--rate", type=float, default=10)
    ap.add_argument("--seed", type=int, default=1, help="workload seed; also the repeat number")
    ap.add_argument("--pre-s", type=float, default=180, help="workload time before the notice")
    ap.add_argument("--post-s", type=float, default=180, help="workload time after the replacement is ready")
    ap.add_argument("--warmup-s", type=float, default=60, help="excluded from before/steady stats")
    ap.add_argument("--measure-s", type=float, default=240, help="steady: measured window")
    ap.add_argument("--run-id")
    args = ap.parse_args()
    if args.mode != "register" and not args.strategy:
        ap.error("--strategy is required")
    if args.mode == "steady" and args.strategy == "reactive":
        ap.error("reactive has no steady-state cost (it only writes on notice)")
    {"register": cmd_register, "run": cmd_run, "steady": cmd_steady}[args.mode](args)


if __name__ == "__main__":
    main()
