# Serving stack troubleshooting

Problems hit while setting up `kv-gpu` (2026-11-09), with how to spot each one and the fix.
Stack: vLLM 0.32.0 + LMCache 0.5.7 + torch 2.13.0, Qwen2.5-7B-Instruct on one L4.

## Normal workflow (on the VM)

```bash
bash ~/infra/setup_store.sh      # on kv-store: install and configure Redis (durable store)
bash ~/infra/setup_gpu.sh        # on kv-gpu: rebuild the pinned env in ~/kv-env (ends with an "OK vllm ..." line)
bash ~/infra/serve.sh            # start vLLM (local CPU tier only); "ready after ~80-130 s"
bash ~/infra/serve.sh lmcache-remote.yaml   # same, plus write-through to Redis on kv-store
python ~/infra/smoke_test.py     # expect: TTFT cold ~2.6 s | warm ~0.2 s
bash ~/infra/stop.sh             # stop vLLM
```

Log: `~/logs/vllm.log`. The real error is usually well above the last traceback, so search it:
`grep -nE "Error|error:|fatal" ~/logs/vllm.log | head`.

## 1. LMCache kernels fail to load (torch version mismatch)

**Symptom:** `import lmcache.cuda_ops` fails with `undefined symbol: c10_cuda_check_implementation`,
or the log has a LMCache WARNING like "compiled extension not found; stays on the torch baseline".
LMCache still runs after that, just slower, so this one is easy to miss.

**Cause:** LMCache wheels are compiled against one torch version. vLLM 0.33 pins torch 2.14,
but lmcache 0.5.7 was built for torch 2.13. An unpinned `pip install vllm lmcache` can also pull
an old lmcache (0.3.7), which is broken the same way.

**Fix:** install only from `requirements-gpu.lock.txt` (`setup_gpu.sh` does this). To upgrade,
change vLLM and LMCache together and re-check `python -c "import torch, lmcache.cuda_ops"`.

## 2. `No module named 'lmcache.integration.vllm.vllm_v1_adapter'`

**Symptom:** the model loads, then the engine dies with this `ModuleNotFoundError`, followed by
`RuntimeError: Engine core initialization failed`.

**Cause:** vLLM's built-in `"kv_connector":"LMCacheConnectorV1"` imports LMCache's old module
path. LMCache 0.5.x moved that code to `lmcache/inprocess/integration/vllm/`.

**Fix:** use the connector class that LMCache ships itself (already in `serve.sh`):

```json
{"kv_connector":"LMCacheConnectorV1Dynamic",
 "kv_connector_module_path":"lmcache.integration.vllm.lmcache_connector_v1",
 "kv_role":"kv_both"}
```

## 3. vLLM hangs at startup: `cannot execute 'cc1plus'`

**Symptom:** `serve.sh` prints "not ready after 15 min". The process is still alive and the GPU
memory is in use, but `/health` never answers. The log has `Ninja build failed` and
`gcc: fatal error: cannot execute 'cc1plus'` from `flashinfer/sampling.py`.

**Cause:** at warmup, FlashInfer's sampler compiles CUDA kernels on the fly, which needs g++.
The Deep Learning VM image has no g++, so the engine waits forever instead of exiting.

**Fix:** `serve.sh` sets `VLLM_USE_FLASHINFER_SAMPLER=0`, which makes vLLM use its PyTorch
sampler. If another FlashInfer kernel ever needs compiling, install a compiler instead
(`sudo apt-get install -y g++`).

## 4. `pkill -f "vllm serve"` over ssh doesn't stop vLLM

**Symptom:** `gcloud compute ssh kv-gpu --command="pkill -f 'vllm serve'; ..."` prints nothing,
and vLLM keeps running.

**Cause:** the remote shell's own command line contains "vllm serve", so `pkill` kills the ssh
shell first.

**Fix:** use `bash ~/infra/stop.sh`, which matches only the Python process.

## 5. Durable store: there is no `lm://` LMCache server in 0.5.x

**Symptom:** older docs say to run an LMCache server and set `remote_url: "lm://host:port"`.
LMCache 0.5.7 has no such server or adapter. (`lmcache server` exists, but it's a different,
same-machine "multiprocess" mode.)

**Fix:** remote storage goes through adapters for external stores
(`lmcache/inprocess/v1/storage_backend/connector/`: redis, valkey, s3, fs, ...). We run Redis
on kv-store (`setup_store.sh`) and use `lmcache-remote.yaml` (`remote_url: "redis://kv-store:6379"`).
Check it with `bash warm_restart_test.sh`.
The "remote_url is deprecated, use remote_storage_plugins" warning is harmless for now.

## 6. KV is in Redis, but a restarted server never finds it

**Symptom:** after a restart the log shows `LMCache hit tokens: 0` for a prompt that was
already stored. `redis-cli dbsize` grows on every restart, as the same chunks get saved
under new names.

**Cause:** LMCache names chunks with Python's `hash()` (`pre_caching_hash_algorithm: builtin`),
which is randomized in every new process.

**Fix:** `serve.sh` sets `PYTHONHASHSEED=0`. Every process that reads or writes the store,
including any replacement server, must use the same value.
After the fix: `LMCache hit tokens: 8448, need to load: 8448`, and TTFT 2.6 s cold vs 1.5 s
loaded from Redis.

## 7. Long jobs die when the ssh session drops; 10 req/s overloads the L4

- `gcloud compute ssh` sessions drop now and then ("Software caused connection abort"), and that
  kills anything attached to them. Start long jobs fully detached:
  `setsid nohup bash emulator/run_midterm.sh --rate 4 > ~/logs/midterm.log 2>&1 < /dev/null &`
  (plink may still sit open afterwards; the job keeps running, so check it from a new ssh).
- At 10 req/s (64 prefixes × ~3,140 tokens, 64 output tokens), median TTFT is about 29 s:
  requests just queue. Rate probe on a warm server: 2 → 193 ms, 4 → 261 ms, 6 → 395 ms median TTFT.
  The midterm runs use **4 req/s**.

## 8. Running commands from Windows / PowerShell

- Quote arguments that contain commas: `"--accelerator=type=nvidia-l4,count=1"`.
- Nested quotes inside `gcloud compute ssh --command="..."` get mangled. Write a script,
  `gcloud compute scp` it to the VM, then run it with `bash`.
- `gcloud compute scp` (pscp) does not expand `~`. Use `kv-gpu:infra/`, not `kv-gpu:~/infra/`.
- External IPs are ephemeral and change on every VM start, and PuTTY caches host keys by IP.
  So the key prompt returns after each restart. Check the fingerprint matches the one from
  before, then accept it as below.
- The first ssh to a new VM asks to cache its host key, which hangs a non-interactive run.
  Connect once with `gcloud compute ssh VM --strict-host-key-checking=no --command="echo ok"`.
- Files copied from Windows have CRLF line endings, so run `sed -i 's/\r$//' file` before `bash file`.
- Long installs and downloads take longer than an interactive session; run them in the
  background or under `nohup`.

## 9. Creating the GPU VM

- `GPUS_ALL_REGIONS` quota starts at 0 and has to be raised to 1 through a quota request.
- Restarting a stopped kv-gpu can fail with `ZONE_RESOURCE_POOL_EXHAUSTED` (L4 stockout). A stopped VM
  can only start in its own zone, so retry `gcloud compute instances start` every minute. Moving zones
  means snapshotting the disk and recreating both VMs.
- L4 capacity often runs out in a zone. Retry across zones (US and Europe, g2-standard-8, then
  g2-standard-4). `kv-store` must be in the same zone as `kv-gpu`.
- Use STANDARD (on-demand) VMs, not spot. The emulator fakes preemptions; a real one would ruin a run.
- Stop both VMs after every session:
  `gcloud compute instances stop kv-gpu kv-store --zone=us-central1-a`
