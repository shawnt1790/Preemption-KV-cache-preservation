"""Tests for policy.py. Run with:  python test_policy.py   (or: pytest test_policy.py)"""
import csv
import os
import tempfile

from policy import KV_BYTES_PER_TOKEN, rank_prefixes, select_prefixes

GB = 10**9

# ---- select_prefixes: the six cases from the spec ----
RANKED = ["hr-0", "hr-2", "hr-1", "hr-5"]
SIZES = {"hr-0": 2 * GB, "hr-2": 3 * GB, "hr-1": 1 * GB, "hr-5": 2 * GB}
BW = 200 * 10**6  # 200 MB/s

SPEC_CASES = [
    # (name, notice_s, hot_set_n, expected)
    ("reactive 0 s", 0, 0, []),
    ("reactive 32 s (6 GB)", 32, 0, ["hr-0", "hr-2", "hr-1"]),
    ("reactive 22 s, skip-and-continue (4 GB)", 22, 0, ["hr-0", "hr-1"]),
    ("hybrid N=2, 0 s", 0, 2, ["hr-0", "hr-2"]),
    ("hybrid N=2, 12 s (2 GB)", 12, 2, ["hr-0", "hr-2", "hr-1"]),
    ("reactive 122 s (24 GB)", 122, 0, ["hr-0", "hr-2", "hr-1", "hr-5"]),
]


def test_select_spec_cases():
    for name, notice, n, expected in SPEC_CASES:
        got = select_prefixes(RANKED, SIZES, BW, notice, hot_set_n=n)
        assert got == expected, f"{name}: expected {expected}, got {got}"


# ---- rank_prefixes ----
FIELDS = ["req_id", "workload", "prefix_id", "session_id", "turn", "send_wall", "ttft_s",
          "e2e_s", "output_chunks", "prompt_chars", "prompt_tokens", "status"]


def _write_log(rows):
    fd, path = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(fd, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for i, r in enumerate(rows):
            w.writerow({"req_id": i, "workload": "test", "session_id": "", "turn": 0,
                        "ttft_s": "0.1", "e2e_s": "0.2", "output_chunks": 5,
                        "status": "ok", **r})
    return path


def test_rank_prefixes():
    t = 1000.0
    rows = [
        # A: 3 hits x 4000 tokens = 12000
        {"prefix_id": "A", "send_wall": t - 10, "prompt_chars": 16000, "prompt_tokens": 4000},
        {"prefix_id": "A", "send_wall": t - 20, "prompt_chars": 16000, "prompt_tokens": 4000},
        {"prefix_id": "A", "send_wall": t - 30, "prompt_chars": 16000, "prompt_tokens": 4000},
        # B: growing history, largest length counts: 2 hits x 9000 = 18000 -> hottest
        {"prefix_id": "B", "send_wall": t - 40, "prompt_chars": 4000, "prompt_tokens": 1000},
        {"prefix_id": "B", "send_wall": t - 5, "prompt_chars": 36000, "prompt_tokens": 9000},
        # C and D tie at 6000; C is larger, so C ranks first
        {"prefix_id": "C", "send_wall": t - 50, "prompt_chars": 24000, "prompt_tokens": 6000},
        {"prefix_id": "D", "send_wall": t - 60, "prompt_chars": 12000, "prompt_tokens": 3000},
        {"prefix_id": "D", "send_wall": t - 61, "prompt_chars": 12000, "prompt_tokens": 3000},
        # E: no prompt_tokens -> falls back to chars / 4 = 500 tokens
        {"prefix_id": "E", "send_wall": t - 70, "prompt_chars": 2000, "prompt_tokens": ""},
        # excluded: outside the 300 s window, at/after the notice, or failed
        {"prefix_id": "OLD", "send_wall": t - 400, "prompt_chars": 99999, "prompt_tokens": 99999},
        {"prefix_id": "LATE", "send_wall": t, "prompt_chars": 99999, "prompt_tokens": 99999},
        {"prefix_id": "ERR", "send_wall": t - 1, "prompt_chars": 99999, "prompt_tokens": 99999,
         "status": "error:ReadError"},
    ]
    path = _write_log(rows)
    try:
        kv = KV_BYTES_PER_TOKEN["Qwen/Qwen2.5-7B-Instruct"]
        ranked, sizes = rank_prefixes(path, t_notice=t, kv_bytes_per_token=kv)
        assert ranked == ["B", "A", "C", "D", "E"], ranked
        assert sizes["B"] == 9000 * kv
        assert sizes["E"] == 500 * kv
    finally:
        os.remove(path)


def test_kv_bytes():
    assert KV_BYTES_PER_TOKEN["Qwen/Qwen2.5-7B-Instruct"] == 57_344
    assert KV_BYTES_PER_TOKEN["meta-llama/Llama-3.1-8B-Instruct"] == 131_072


if __name__ == "__main__":
    for fn in (test_select_spec_cases, test_rank_prefixes, test_kv_bytes):
        fn()
        print(f"PASS {fn.__name__}")
    print("all tests passed")