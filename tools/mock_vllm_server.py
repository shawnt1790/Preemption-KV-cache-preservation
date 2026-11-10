"""Fake vLLM server for testing workload_gen.py without a GPU.

Speaks the same streaming /v1/chat/completions format as vLLM, including the
usage chunk with prompt_tokens. "Prefill" time grows with prompt length, and a
prompt seen before responds faster, so TTFT behaves roughly like a prefix cache.

    python mock_vllm_server.py            # listens on http://localhost:8000
    python mock_vllm_server.py --port 8001
Stop it with Ctrl+C. Restarting it clears the "cache", like a preemption.
"""
import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SEEN = set()
LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        msgs = body.get("messages", [])
        prompt_chars = sum(len(m["content"]) for m in msgs)
        prefix = msgs[0]["content"] if msgs else ""
        with LOCK:
            hit = prefix in SEEN
            SEEN.add(prefix)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()

        def send(obj):
            self.wfile.write(b"data: " + json.dumps(obj).encode() + b"\n\n")
            self.wfile.flush()

        send({"choices": [{"delta": {"role": "assistant"}}]})
        prefill = prompt_chars / 200_000          # ~0.1 s per 20K chars when cold
        time.sleep(prefill * (0.1 if hit else 1.0))  # cache hit: 10x faster
        n_out = min(body.get("max_tokens", 16), 16)
        for _ in range(n_out):
            send({"choices": [{"delta": {"content": "x "}}]})
            time.sleep(0.01)
        if body.get("stream_options", {}).get("include_usage"):
            send({"choices": [], "usage": {"prompt_tokens": prompt_chars // 4,
                                           "completion_tokens": n_out}})
        self.wfile.write(b"data: [DONE]\n\n")

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    print(f"mock vLLM server on http://localhost:{args.port} (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()