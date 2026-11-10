#!/bin/bash
# Follow-up runs after run_midterm.sh (waits for it to finish first):
#  1. none and write-through at notice 0 s, so every strategy in the 0 s comparison is killed at the
#     same point in the same request stream. The post-restart transient depends strongly on which
#     requests arrive first, so the kill time matters.
#  2. Diagnostic at 2 req/s (the GPU can recompute faster than requests arrive): does hybrid's
#     kept hot set get fast TTFT when the replacement isn't swamped by recompute?
# Usage (on kv-gpu, from the repo root): setsid nohup bash emulator/run_extra.sh > ~/logs/extra.log 2>&1 < /dev/null &
set -uo pipefail
cd "$(dirname "$0")/.."
source "$HOME/kv-env/bin/activate"
while pgrep -f run_midterm.sh >/dev/null; do sleep 30; done

run() {
  local id=$1; shift
  if [ -f "results/runs/$id/summary.json" ]; then echo "skip $id"; return; fi
  echo "=== $(date +%H:%M:%S) $id"
  python emulator/preempt.py run "$@" --run-id "$id" || echo "FAILED $id"
}
for seed in 1 2; do
  run none0-r$seed          --strategy none          --notice-s 0 --seed $seed --rate 4
  run write-through0-r$seed --strategy write-through --notice-s 0 --seed $seed --rate 4
done
run diag-none0-rate2   --strategy none   --notice-s 0 --seed 1 --rate 2
run diag-hybrid0-rate2 --strategy hybrid --notice-s 0 --seed 1 --rate 2
echo "=== $(date +%H:%M:%S) extra done"
