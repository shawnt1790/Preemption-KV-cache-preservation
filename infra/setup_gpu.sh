#!/bin/bash
# Rebuild the pinned serving environment on a fresh GPU VM.
# Image: deeplearning-platform-release / common-cu129-ubuntu-2204-nvidia-580 (driver 580, L4)
#
# Pinned stack (see requirements-gpu.lock.txt for every package):
#   vllm 0.32.0 + lmcache 0.5.7 + torch 2.13.0 (cu130), Python 3.12
# Why not vllm 0.33.0: it moved to torch 2.14, but the lmcache 0.5.7 wheel's
# compiled CUDA kernels (lmcache.cuda_ops) are built against torch 2.13 and fail
# to load with an undefined-symbol error. Upgrade both only as a matched pair.
#
# Usage: bash setup_gpu.sh   (run from the directory containing the lock file)
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v uv >/dev/null && [ ! -x "$HOME/.local/bin/uv" ]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"

[ -d "$HOME/kv-env" ] || uv venv --python 3.12 "$HOME/kv-env"
source "$HOME/kv-env/bin/activate"
uv pip sync requirements-gpu.lock.txt

python - <<'EOF'
import torch, lmcache.cuda_ops, vllm, lmcache
from importlib.metadata import version
assert torch.cuda.is_available(), "no GPU visible"
print("OK  vllm", vllm.__version__, "| lmcache", version("lmcache"),
      "| torch", torch.__version__, "|", torch.cuda.get_device_name(0))
EOF
