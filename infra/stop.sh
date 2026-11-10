#!/bin/bash
# Stop vLLM. Matches the python process only, so it is safe to run via
# `gcloud compute ssh --command` (a plain `pkill -f "vllm serve"` kills that ssh shell too).
pids=$(pgrep -f '^[^ ]*python[^ ]* [^ ]*vllm serve') || { echo "vllm not running"; exit 0; }
kill $pids
for i in $(seq 1 30); do pgrep -f '^[^ ]*python[^ ]* [^ ]*vllm serve' >/dev/null || { echo "stopped"; exit 0; }; sleep 1; done
kill -9 $pids; echo "killed"
