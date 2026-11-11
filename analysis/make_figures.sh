#!/bin/bash
# Every midterm figure, from the emulator runs in results/runs/ (both repeats pooled).
# Usage, from the repo root: bash analysis/make_figures.sh
# Needs: pip install matplotlib numpy
set -euo pipefail
cd "$(dirname "$0")/.."
P="python analysis/plots.py"
R=results/runs

runs=()
pair() {   # pair <label> <run_id_prefix>: adds one --run per repeat to $runs
  for r in 1 2; do runs+=(--run "$1=$R/$2-r$r/requests.csv,$R/$2-r$r/events.json"); done
}

# 1) TTFT across a preemption. Each figure compares strategies killed at the same point in the
#    same request stream: none and write-through ran at both 0 s and 30 s for this reason.
runs=(); pair "No preservation" none; pair "Write-through" write-through
pair "Reactive flush" reactive30; pair "Hybrid (N=8)" hybrid30
$P ttft "${runs[@]}" --title "TTFT across a preemption, 30 s notice" --out figures/ttft_30s.png

runs=(); pair "No preservation" none0; pair "Write-through" write-through0
pair "Reactive flush" reactive0; pair "Hybrid (N=8)" hybrid0
$P ttft "${runs[@]}" --title "TTFT across a preemption, 0 s notice" --out figures/ttft_0s.png

runs=(); pair "Reactive flush" reactive120; pair "Hybrid (N=8)" hybrid120
$P ttft "${runs[@]}" --title "TTFT across a preemption, 120 s notice" --out figures/ttft_120s.png

# 2) Share preserved vs. notice, from the request log at a real notice (hybrid30-r1), at the
#    measured 0.71 GB/s. N = 4 / 8 / 16 is the hot-set-size sweep; the runs used N = 8.
#    The axis stops at 40 s because everything is kept from ~18 s on; the CSV still has 120 s.
T_NOTICE=$(python -c "import json; print(json.load(open('$R/hybrid30-r1/events.json'))['t_notice'])")
$P preserved --log $R/hybrid30-r1/requests.csv --t-notice "$T_NOTICE" --bandwidth-mbps 710 \
  --hybrid-n 4 8 16 --main-n 8 --max-notice 40 --mark 0 10 20 30 120 --out figures/preserved.png

# 3) Steady state: same 60 s warmup + 240 s window as emulator/preempt.py steady.
$P overhead --warmup-s 60 --measure-s 240 --out figures/overhead.png \
  --run "No preservation=$R/steady-none-r1/requests.csv,$R/steady-none-r1/summary.json" \
  --run "Write-through=$R/steady-write-through-r1/requests.csv,$R/steady-write-through-r1/summary.json" \
  --run "Hybrid (N=8)=$R/steady-hybrid-r1/requests.csv,$R/steady-hybrid-r1/summary.json"
