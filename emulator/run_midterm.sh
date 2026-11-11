#!/bin/bash
# All midterm runs (plan: 8 configurations x 2 runs on high-reuse, plus steady-state runs).
# Ordered so the core result lands first if time runs short. The plan's cut order is
# 120 s notice, then second runs, so those come last.
# Usage (on kv-gpu, from the repo root): nohup bash emulator/run_midterm.sh > ~/logs/midterm.log 2>&1 &
# Extra args go to every run, e.g. --rate 4. Finished runs are skipped, so a rerun resumes.
set -uo pipefail
cd "$(dirname "$0")/.."
source "$HOME/kv-env/bin/activate"
E="python emulator/preempt.py"

run() {   # run <run_id> <mode> <args...>; skip runs that already finished
  local id=$1; shift
  if [ -f "results/runs/$id/summary.json" ]; then echo "skip $id"; return; fi
  echo "=== $(date +%H:%M:%S) $id"
  $E "$@" --run-id "$id" "${EXTRA[@]}" || echo "FAILED $id"
}
EXTRA=("$@")

[ -f results/keymap.json ] || $E register "${EXTRA[@]}"

for seed in 1 2; do
  run none-r$seed          run --strategy none --seed $seed
  run write-through-r$seed run --strategy write-through --seed $seed
  for n in 0 30; do
    run reactive$n-r$seed run --strategy reactive --notice-s $n --seed $seed
    run hybrid$n-r$seed   run --strategy hybrid --notice-s $n --seed $seed
  done
  if [ $seed = 1 ]; then
    for s in none write-through hybrid; do run steady-$s-r1 steady --strategy $s --seed 1; done
  fi
  run reactive120-r$seed run --strategy reactive --notice-s 120 --seed $seed
  run hybrid120-r$seed   run --strategy hybrid --notice-s 120 --seed $seed
done
echo "=== $(date +%H:%M:%S) all done"
