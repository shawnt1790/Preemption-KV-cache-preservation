#!/bin/bash
# End-to-end check of the durable store: KV written to Redis on kv-store survives a vLLM
# restart (a stand-in for preemption) and is loaded back instead of recomputed.
#   1. empty Redis, start vLLM with lmcache-remote.yaml, send the long prompt (cold)
#   2. restart vLLM: GPU prefix cache and LMCache's CPU tier are both gone
#   3. send the same prompt: it should hit in Redis ("need to load" > 0) with a low TTFT
# Usage (on kv-gpu): bash warm_restart_test.sh
set -euo pipefail
cd "$(dirname "$0")"
source "$HOME/kv-env/bin/activate"
redis() { python -c "import redis,sys; r=redis.Redis('kv-store'); print(eval(sys.argv[1]))" "$1"; }

bash stop.sh
redis "r.flushall()"
bash serve.sh lmcache-remote.yaml
echo "== before restart"; python smoke_test.py
echo "redis keys: $(redis 'r.dbsize()') | bytes: $(redis "r.info('memory')['used_memory_human']")"

bash stop.sh
bash serve.sh lmcache-remote.yaml
echo "== after restart (cold column = first request on the new server)"; python smoke_test.py
grep -E "LMCache hit tokens" "$HOME/logs/vllm.log" | tail -2 | sed 's/.*Total tokens/Total tokens/'
