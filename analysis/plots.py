#!/usr/bin/env python3
"""Midterm figures for the spot KV-cache project (Person B).

Three subcommands, one per figure. Each writes a PNG (for slides) and a CSV of the
plotted numbers (for the report / a table view).

1) TTFT over time across a preemption, one line per strategy
   python analysis/plots.py ttft \
       --run "No preservation=results/none.csv,results/none_events.json" \
       --run "Write-through=results/wt.csv,results/wt_events.json" \
       --run "Reactive flush=results/reactive30.csv,results/reactive30_events.json" \
       --run "Hybrid=results/hybrid30.csv,results/hybrid30_events.json" \
       --out figures/ttft_preemption.png

   Each events file is written by Person A's emulator, wall-clock seconds:
       {"t_notice": 1794268000.0, "t_kill": 1794268030.0, "t_ready": 1794268045.0}

2) Share of the hot cache preserved vs. notice length (needs only a log + bandwidth)
   python analysis/plots.py preserved --log results/hr.csv --bandwidth-mbps 200 \
       --hybrid-n 4 8 --model Qwen/Qwen2.5-7B-Instruct --out figures/preserved.png

3) Steady-state overhead (runs with no preemption), one CSV per strategy
   python analysis/plots.py overhead \
       --run "No preservation=results/ss_none.csv" \
       --run "Write-through=results/ss_wt.csv" \
       --run "Hybrid=results/ss_hybrid.csv" \
       --out figures/overhead.png

Requires: pip install matplotlib numpy
"""
import argparse
import csv
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "policy"))
from policy import KV_BYTES_PER_TOKEN, hotness_table, select_prefixes  # noqa: E402

# ---------- style: fixed colour per strategy (never re-assigned by rank) ----------
STRATEGY_COLORS = {
    "No preservation": "#2a78d6",   # slot 1 blue
    "Write-through": "#eb6834",     # slot 2 orange
    "Reactive flush": "#1baf7a",    # slot 3 aqua
    "Hybrid": "#eda100",            # slot 4 yellow
}
EXTRA_COLORS = ["#e87ba4", "#008300"]  # slots 5-6 for any further series
INK, INK_2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK_2, "xtick.color": INK_2, "ytick.color": INK_2,
    "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 11,
    "axes.titlesize": 13, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "legend.frameon": False, "axes.axisbelow": True,
})


def tint(hex_color, amount):
    """Blend a colour toward the surface (amount 0 = unchanged, 1 = surface)."""
    a = [int(hex_color[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(SURFACE[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * amount):02x}" for x, y in zip(a, b))


def color_for(label, i):
    for key, c in STRATEGY_COLORS.items():
        if label.lower().startswith(key.lower()):
            return c
    return EXTRA_COLORS[i % len(EXTRA_COLORS)]


def read_log(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def parse_run(spec, need_events):
    if "=" not in spec:
        sys.exit(f'--run must look like "Label=log.csv{",events.json" if need_events else ""}": {spec}')
    label, paths = spec.split("=", 1)
    parts = [p.strip() for p in paths.split(",")]
    if need_events and len(parts) != 2:
        sys.exit(f'--run needs a log and an events file: "Label=log.csv,events.json" ({spec})')
    return label.strip(), parts


def save(fig, out, rows, header):
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    fig.savefig(out, dpi=200, bbox_inches="tight")
    table = os.path.splitext(out)[0] + ".csv"
    with open(table, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"wrote {out} and {table}")


def label_line_end(ax, x, y, text, color):
    ax.annotate(text, (x, y), xytext=(6, 0), textcoords="offset points",
                va="center", fontsize=10, color=INK)
    ax.plot([x], [y], marker="o", ms=5, color=color, mec=SURFACE, mew=2, zorder=5)


# ---------- figure 1: TTFT over time across a preemption ----------

def cmd_ttft(args):
    fig, ax = plt.subplots(figsize=(9, 4.8))
    rows, notice_offsets, ready_offsets = [], [], []
    for i, spec in enumerate(args.run):
        label, (log_path, ev_path) = parse_run(spec, need_events=True)
        ev = json.load(open(ev_path))
        t_kill = ev["t_kill"]
        if "t_notice" in ev:
            notice_offsets.append(ev["t_notice"] - t_kill)
        if "t_ready" in ev:
            ready_offsets.append(ev["t_ready"] - t_kill)
        pts = [(float(r["send_wall"]) - t_kill, float(r["ttft_s"]))
               for r in read_log(log_path) if r["status"] == "ok" and r["ttft_s"]]
        pts = [p for p in pts if args.xmin <= p[0] <= args.xmax]
        if not pts:
            print(f"warning: no requests in the plotted window for {label}")
            continue
        t = np.array([p[0] for p in pts])
        y = np.array([p[1] for p in pts]) * 1000  # ms
        edges = np.arange(args.xmin, args.xmax + args.bin_s, args.bin_s)
        centers, med = [], []
        for lo, hi in zip(edges[:-1], edges[1:]):
            m = (t >= lo) & (t < hi)
            if m.any():
                centers.append((lo + hi) / 2)
                med.append(float(np.median(y[m])))
                rows.append([label, round((lo + hi) / 2, 1), round(med[-1], 1), int(m.sum())])
        c = color_for(label, i)
        ax.plot(centers, med, color=c, lw=2, label=label, solid_capstyle="round")

    xt = ax.get_xaxis_transform()
    if ready_offsets:
        r = float(np.median(ready_offsets))
        ax.axvspan(0, r, color=GRID, alpha=0.7, lw=0, zorder=0)
        ax.text(r, 0.99, " restarting until here", transform=xt, va="top", fontsize=9, color=INK_2)
    ax.axvline(0, color=INK_2, lw=1)
    ax.text(0, 0.92, "kill ", transform=xt, va="top", ha="right", fontsize=9, color=INK_2)
    if notice_offsets:
        n = float(np.median(notice_offsets))
        ax.axvline(n, color=INK_2, lw=1, ls="--")
        ax.text(n, 0.99, "notice ", transform=xt, va="top", ha="right", fontsize=9, color=INK_2)
    ax.set_xlabel("Seconds since the server was killed")
    ax.set_ylabel(f"Median TTFT (ms, {args.bin_s:g} s bins)")
    ax.set_title(args.title)
    ax.set_ylim(bottom=0)
    ax.set_xlim(args.xmin, args.xmax)
    ax.legend(loc="upper left", bbox_to_anchor=(0, -0.15), ncol=4)
    save(fig, args.out, rows, ["strategy", "seconds_since_kill", "median_ttft_ms", "requests"])


# ---------- figure 2: share of the hot cache preserved vs. notice length ----------

def preserved_share(table, keep):
    """Share of recent prefill work that survives: sum of hotness kept / total hotness."""
    total = sum(v[2] for v in table.values())
    return 100.0 * sum(table[p][2] for p in keep) / total if total else 0.0


def cmd_preserved(args):
    rows = read_log(args.log)
    walls = [float(r["send_wall"]) for r in rows if r["send_wall"]]
    t_notice = args.t_notice if args.t_notice else max(walls) + 1
    kv = KV_BYTES_PER_TOKEN.get(args.model) if args.kv_bytes is None else args.kv_bytes
    if kv is None:
        sys.exit(f"unknown model {args.model}; pass --kv-bytes")
    table = hotness_table(args.log, t_notice, args.window_s)
    if not table:
        sys.exit("no requests in the hotness window; check --t-notice / --window-s")
    ranked = sorted(table, key=lambda p: (-table[p][2], -table[p][1], p))
    sizes = {p: table[p][1] * kv for p in ranked}
    total_gb = sum(sizes.values()) / 1e9
    bw = args.bandwidth_mbps * 1e6

    notices = np.arange(0, args.max_notice + 0.5, 0.5)
    series = [("Reactive flush", 0)] + [(f"Hybrid (N={n})", n) for n in args.hybrid_n]
    fig, ax = plt.subplots(figsize=(8, 4.6))
    out_rows = []
    for i, (label, n) in enumerate(series):
        ys = [preserved_share(table, select_prefixes(ranked, sizes, bw, s, hot_set_n=n))
              for s in notices]
        c = color_for(label, i) if n == 0 else (STRATEGY_COLORS["Hybrid"] if i == 1 else EXTRA_COLORS[(i - 2) % 2])
        ax.plot(notices, ys, color=c, lw=2, label=label, drawstyle="steps-post")
        for s in args.mark:
            y = ys[int(s / 0.5)] if s <= args.max_notice else None
            if y is not None:
                ax.plot([s], [y], marker="o", ms=7, color=c, mec=SURFACE, mew=2, zorder=5)
                out_rows.append([label, s, round(y, 1)])
    for s in args.mark:
        ax.axvline(s, color=GRID, lw=1, zorder=0)
    ax.set_xlabel("Preemption notice (s)")
    ax.set_ylabel("Share of recent prefill work preserved (%)")
    ax.set_ylim(0, 105)
    ax.set_xlim(0, args.max_notice * 1.03)
    ax.set_xticks(args.mark)
    ax.set_title(args.title)
    ax.text(0, -0.2, f"{len(ranked)} prefixes, {total_gb:.1f} GB of KV cache, "
            f"{args.bandwidth_mbps:g} MB/s to the remote store, 2 s kill margin",
            transform=ax.transAxes, fontsize=9, color=INK_2)
    ax.legend(loc="upper left", bbox_to_anchor=(0, -0.25), ncol=3)
    save(fig, args.out, out_rows, ["strategy", "notice_s", "share_preserved_pct"])


# ---------- figure 3: steady-state overhead ----------

def cmd_overhead(args):
    stats = []
    for spec in args.run:
        label, (log_path,) = parse_run(spec, need_events=False)
        rows = read_log(log_path)
        ok = [r for r in rows if r["status"] == "ok" and r["ttft_s"]]
        if not ok:
            print(f"warning: no successful requests in {log_path}")
            continue
        ttft = np.array([float(r["ttft_s"]) for r in ok]) * 1000
        e2e = np.array([float(r["e2e_s"]) for r in ok]) * 1000
        sends = sorted(float(r["send_wall"]) for r in ok)
        finish = max(float(r["send_wall"]) + float(r["e2e_s"]) for r in ok)
        dur = max(finish - sends[0], 1e-9)
        stats.append([label, len(ok), round(len(ok) / dur, 3),
                      round(np.percentile(ttft, 50), 1), round(np.percentile(ttft, 99), 1),
                      round(np.percentile(e2e, 50), 1), round(np.percentile(e2e, 99), 1)])

    labels = [s[0] for s in stats]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 4.4), gridspec_kw={"width_ratios": [1.6, 1]})
    x = np.arange(len(stats))
    w = 0.36
    for j, (col, name, amount) in enumerate([(3, "p50", 0.0), (4, "p99", 0.5)]):
        vals = [s[col] for s in stats]
        bars = a1.bar(x + (j - 0.5) * (w + 0.02), vals, width=w,
                      color=[tint(color_for(l, i), amount) for i, l in enumerate(labels)],
                      edgecolor=SURFACE, linewidth=2)
        for b, v in zip(bars, vals):
            a1.annotate(f"{v:.0f}", (b.get_x() + b.get_width() / 2, v), xytext=(0, 3),
                        textcoords="offset points", ha="center", fontsize=9, color=INK)
    a1.set_xticks(x, labels)
    a1.set_ylabel("TTFT (ms)")
    a1.set_title("TTFT, steady state (solid p50, light p99)")
    a1.grid(axis="x", visible=False)

    thr = [s[2] for s in stats]
    bars = a2.bar(x, thr, width=0.6, color=[color_for(l, i) for i, l in enumerate(labels)],
                  edgecolor=SURFACE, linewidth=2)
    for b, v in zip(bars, thr):
        a2.annotate(f"{v:.2f}", (b.get_x() + b.get_width() / 2, v), xytext=(0, 3),
                    textcoords="offset points", ha="center", fontsize=9, color=INK)
    a2.set_xticks(x, labels)
    a2.set_ylabel("Completed requests per second")
    a2.set_title("Throughput")
    a2.grid(axis="x", visible=False)
    for a in (a1, a2):
        plt.setp(a.get_xticklabels(), rotation=15, ha="right")
    fig.tight_layout()
    save(fig, args.out, stats,
         ["strategy", "requests", "req_per_s", "ttft_p50_ms", "ttft_p99_ms", "e2e_p50_ms", "e2e_p99_ms"])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ttft", help="TTFT over time across a preemption")
    p.add_argument("--run", action="append", required=True, help='"Label=log.csv,events.json"')
    p.add_argument("--out", default="figures/ttft_preemption.png")
    p.add_argument("--bin-s", type=float, default=5.0)
    p.add_argument("--xmin", type=float, default=-60.0)
    p.add_argument("--xmax", type=float, default=180.0)
    p.add_argument("--title", default="TTFT across a preemption")
    p.set_defaults(func=cmd_ttft)

    p = sub.add_parser("preserved", help="share of hot cache preserved vs. notice length")
    p.add_argument("--log", required=True, help="workload CSV from before the preemption")
    p.add_argument("--bandwidth-mbps", type=float, required=True, help="measured store write bandwidth, MB/s")
    p.add_argument("--model", default="Qwen/Qwen2.5-7B-Instruct")
    p.add_argument("--kv-bytes", type=int, help="override KV bytes per token")
    p.add_argument("--hybrid-n", type=int, nargs="*", default=[4])
    p.add_argument("--t-notice", type=float, help="wall time of the notice (default: end of log)")
    p.add_argument("--window-s", type=float, default=300)
    p.add_argument("--max-notice", type=float, default=120)
    p.add_argument("--mark", type=float, nargs="*", default=[0, 30, 120])
    p.add_argument("--out", default="figures/preserved_vs_notice.png")
    p.add_argument("--title", default="How much of the hot cache survives a preemption")
    p.set_defaults(func=cmd_preserved)

    p = sub.add_parser("overhead", help="steady-state TTFT and throughput per strategy")
    p.add_argument("--run", action="append", required=True, help='"Label=log.csv"')
    p.add_argument("--out", default="figures/steady_state_overhead.png")
    p.set_defaults(func=cmd_overhead)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()