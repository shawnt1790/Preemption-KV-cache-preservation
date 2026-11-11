#!/bin/bash
# Start vLLM with automatic prefix caching and the LMCache connector, in the background.
# Usage: bash serve.sh [lmcache-config.yaml]     (default: lmcache-local.yaml)
# Logs:  ~/logs/vllm.log    Stop: bash stop.sh
set -euo pipefail
cd "$(dirname "$0")"
source "$HOME/kv-env/bin/activate"

MODEL="${MODEL:-Qwen/Qwen2.5-7B-Instruct}"   # matches workload_gen.py's default
PORT="${PORT:-8000}"
export LMCACHE_CONFIG_FILE="$(realpath "${1:-lmcache-local.yaml}")"
# FlashInfer's sampler JIT-compiles CUDA kernels at warmup and needs g++, which the
# image lacks (engine hangs on "cannot execute cc1plus"); use vLLM's PyTorch sampler.
export VLLM_USE_FLASHINFER_SAMPLER=0
# LMCache names chunks with Python's hash(), which is randomized per process. Without a fixed
# seed, a restarted server can't find any KV the old one saved in the remote store.
export PYTHONHASHSEED=0
mkdir -p "$HOME/logs"

# --enable-prefix-caching : vLLM reuses KV blocks in GPU memory across requests with a shared prefix
# --kv-transfer-config    : LMCache connector; kv_both = it both saves KV out and loads it back.
#   Uses the connector class LMCache ships itself: vLLM 0.32's built-in "LMCacheConnectorV1"
#   imports lmcache.integration.vllm.vllm_v1_adapter, which lmcache 0.5.x moved away.
# --max-model-len 16384   : room for the 4-8K-token shared system prompts plus questions
# --gpu-memory-utilization: ~15 GB of weights on the 23 GB L4 leaves ~5 GB for GPU KV cache
nohup vllm serve "$MODEL" \
  --port "$PORT" \
  --enable-prefix-caching \
  --kv-transfer-config '{"kv_connector":"LMCacheConnectorV1Dynamic","kv_connector_module_path":"lmcache.integration.vllm.lmcache_connector_v1","kv_role":"kv_both"}' \
  --max-model-len 16384 \
  --gpu-memory-utilization 0.90 \
  > "$HOME/logs/vllm.log" 2>&1 &
VLLM_PID=$!; echo "vllm pid $VLLM_PID (config: $LMCACHE_CONFIG_FILE)"

# Wait until the server answers; the first start also downloads ~15 GB of weights.
for i in $(seq 1 900); do   # 1 s polls, so callers get t_ready to within 1 s
  if curl -sf "localhost:$PORT/health" >/dev/null; then echo "ready after ~$i s"; exit 0; fi
  if ! kill -0 "$VLLM_PID" 2>/dev/null; then echo "vllm exited; see ~/logs/vllm.log"; tail -20 "$HOME/logs/vllm.log"; exit 1; fi
  sleep 1
done
echo "not ready after 15 min; see ~/logs/vllm.log"; exit 1
