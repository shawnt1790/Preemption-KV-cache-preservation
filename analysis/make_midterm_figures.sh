#!/usr/bin/env bash
# Builds the midterm figures from Person A's runs (repeat 1) into figures/.
# Run from the repo root:  bash analysis/make_midterm_figures.sh
set -euo pipefail
R=results/runs
OUT=figures/final

# 1) TTFT across a preemption, 0 s notice (none@0 and write-through@0, so every run is killed at the same point)
python analysis/plots.py ttft \
  --run "No preservation=$R/none0-r1/requests.csv,$R/none0-r1/events.json" \
  --run "Write-through=$R/write-through0-r1/requests.csv,$R/write-through0-r1/events.json" \
  --run "Reactive flush=$R/reactive0-r1/requests.csv,$R/reactive0-r1/events.json" \
  --run "Hybrid=$R/hybrid0-r1/requests.csv,$R/hybrid0-r1/events.json" \
  --xmin -60 --xmax 240 --bin-s 10 --title "TTFT across a preemption, 0 s notice" \
  --out $OUT/ttft_0s.png

# 2) TTFT across a preemption, 30 s notice
python analysis/plots.py ttft \
  --run "No preservation=$R/none-r1/requests.csv,$R/none-r1/events.json" \
  --run "Write-through=$R/write-through-r1/requests.csv,$R/write-through-r1/events.json" \
  --run "Reactive flush=$R/reactive30-r1/requests.csv,$R/reactive30-r1/events.json" \
  --run "Hybrid=$R/hybrid30-r1/requests.csv,$R/hybrid30-r1/events.json" \
  --xmin -60 --xmax 240 --bin-s 10 --title "TTFT across a preemption, 30 s notice" \
  --out $OUT/ttft_30s.png

# 3) Share of the hot cache preserved vs. notice length (measured 0.71 GB/s, hybrid N = 8)
T_NOTICE=$(python -c "import json; print(json.load(open('$R/hybrid0-r1/events.json'))['t_notice'])")
python analysis/plots.py preserved --log $R/hybrid0-r1/requests.csv --t-notice "$T_NOTICE" \
  --bandwidth-mbps 710 --hybrid-n 8 --title "Share of the hot cache preserved vs. notice length" \
  --out $OUT/preserved.png

# 4) Steady-state overhead (same 60 s warm-up + 240 s window as the emulator)
python analysis/plots.py overhead --warmup-s 60 --measure-s 240 \
  --run "No preservation=$R/steady-none-r1/requests.csv" \
  --run "Write-through=$R/steady-write-through-r1/requests.csv" \
  --run "Hybrid=$R/steady-hybrid-r1/requests.csv" \
  --out $OUT/overhead.png