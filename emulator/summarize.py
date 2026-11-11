#!/usr/bin/env python3
"""Collect results/runs/*/summary.json into one table per experiment type, averaging repeats.

  python emulator/summarize.py      -> results/midterm_preemption.csv, results/midterm_steady.csv,
                                       and both tables as markdown on stdout
"""
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path

RESULTS = Path(__file__).resolve().parent.parent / "results"
ORDER = ["none", "write-through", "reactive", "hybrid"]


def mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.mean(xs) if xs else None


def fmt(x, nd=0):
    return "" if x is None else f"{x:.{nd}f}"


def split_after(run_dir, s, window_s=60):
    """Median TTFT (ms) in the first `window_s` after ready, for requests whose prefix the
    strategy kept vs. didn't. Shows whether kept prefixes are fast even when the queue isn't."""
    ev = json.loads((run_dir / "events.json").read_text())
    keep = set(s["keep"])
    kept, lost = [], []
    with open(run_dir / "requests.csv", newline="") as fh:
        for r in csv.DictReader(fh):
            t = float(r["send_wall"])
            if r["status"] == "ok" and r["ttft_s"] and ev["t_ready"] <= t < ev["t_ready"] + window_s:
                (kept if r["prefix_id"] in keep else lost).append(float(r["ttft_s"]) * 1000)
    med = lambda xs: statistics.median(xs) if xs else None  # noqa: E731
    return med(kept), med(lost)


def table(rows, cols):
    out = ["| " + " | ".join(c for c, _ in cols) + " |", "|" + "---|" * len(cols)]
    out += ["| " + " | ".join(str(r[k]) for _, k in cols) + " |" for r in rows]
    return "\n".join(out)


def main():
    pre, steady = defaultdict(list), defaultdict(list)
    for f in sorted(RESULTS.glob("runs/*/summary.json")):
        s = json.loads(f.read_text())
        if s["run_id"].startswith(("pilot", "diag-")):
            continue
        if s["run_id"].startswith("steady-"):
            steady[s["strategy"]].append(s)
        else:
            # Grouped by notice for every strategy: none/write-through save the same at any notice,
            # but the notice sets when in the request stream the kill happens, which matters.
            notice = s["notice_s"]
            s["kept_p50"], s["lost_p50"] = split_after(f.parent, s)
            pre[(s["strategy"], notice)].append(s)

    rows = []
    for (strategy, notice), runs in sorted(pre.items(), key=lambda kv: (ORDER.index(kv[0][0]), kv[0][1] or 0)):
        rows.append({
            "strategy": strategy, "notice_s": fmt(notice), "runs": len(runs),
            "share_bytes_pct": fmt(mean([r["share_preserved_pct"] for r in runs])),
            "share_requests_pct": fmt(mean([r["share_requests_preserved_pct"] for r in runs])),
            "gb_saved": fmt(mean([r["bytes_saved"] / 1e9 for r in runs]), 2),
            "ttft_before_p50_ms": fmt(mean([r["before"]["ttft_p50_ms"] for r in runs])),
            "ttft_after60_p50_ms": fmt(mean([r["after_60s"]["ttft_p50_ms"] for r in runs])),
            "ttft_after60_p99_ms": fmt(mean([r["after_60s"]["ttft_p99_ms"] for r in runs])),
            "after60_kept_p50_ms": fmt(mean([r["kept_p50"] for r in runs])),
            "after60_lost_p50_ms": fmt(mean([r["lost_p50"] for r in runs])),
            "downtime_s": fmt(mean([r["downtime_s"] for r in runs])),
            "kill_to_first_served_s": fmt(mean([r["kill_to_first_served_s"] for r in runs])),
            "run_ids": " ".join(r["run_id"] for r in runs),
        })
    srows = []
    for strategy, runs in sorted(steady.items(), key=lambda kv: ORDER.index(kv[0])):
        srows.append({
            "strategy": strategy, "runs": len(runs),
            "ttft_p50_ms": fmt(mean([r["ttft_p50_ms"] for r in runs])),
            "ttft_p99_ms": fmt(mean([r["ttft_p99_ms"] for r in runs])),
            "e2e_p50_ms": fmt(mean([r["e2e_p50_ms"] for r in runs])),
            "e2e_p99_ms": fmt(mean([r["e2e_p99_ms"] for r in runs])),
            "throughput_req_s": fmt(mean([r["throughput_req_s"] for r in runs]), 2),
            "throughput_tok_s": fmt(mean([r["throughput_tok_s"] for r in runs])),
            "storage_gb": fmt(mean([r["storage_bytes"] / 1e9 for r in runs]), 2),
            "replicated_gb": fmt(mean([r.get("bytes_replicated", 0) / 1e9 for r in runs]), 2),
        })
    for name, data in (("midterm_preemption.csv", rows), ("midterm_steady.csv", srows)):
        if data:
            with open(RESULTS / name, "w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(data[0]))
                w.writeheader()
                w.writerows(data)

    print("### Preemption runs (mean over repeats)\n")
    print(table(rows, [("Strategy", "strategy"), ("Notice (s)", "notice_s"), ("Runs", "runs"),
                       ("Hot-set bytes kept %", "share_bytes_pct"), ("Recent requests covered %", "share_requests_pct"),
                       ("GB kept", "gb_saved"), ("TTFT p50 before (ms)", "ttft_before_p50_ms"),
                       ("TTFT p50 first 60 s after (ms)", "ttft_after60_p50_ms"),
                       ("TTFT p99 first 60 s after (ms)", "ttft_after60_p99_ms"),
                       ("...kept prefixes p50", "after60_kept_p50_ms"), ("...lost prefixes p50", "after60_lost_p50_ms"),
                       ("Kill → first served (s)", "kill_to_first_served_s")]))
    print("\n### Steady state, no preemption (mean over repeats)\n")
    print(table(srows, [("Strategy", "strategy"), ("Runs", "runs"), ("TTFT p50 (ms)", "ttft_p50_ms"),
                        ("TTFT p99 (ms)", "ttft_p99_ms"), ("E2E p50 (ms)", "e2e_p50_ms"),
                        ("E2E p99 (ms)", "e2e_p99_ms"), ("Throughput (req/s)", "throughput_req_s"),
                        ("Output tok/s", "throughput_tok_s"), ("Store used (GB)", "storage_gb"),
                        ("Replicated (GB)", "replicated_gb")]))


if __name__ == "__main__":
    main()
