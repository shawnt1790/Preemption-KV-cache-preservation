"""Hotness ranking and preservation policies (Person B).

Implements the "Spec: hotness score and policy interface" from the plan doc.

    ranked, sizes = rank_prefixes("results/hr.csv", t_notice, KV_BYTES_PER_TOKEN["Qwen/Qwen2.5-7B-Instruct"])
    keep = select_prefixes(ranked, sizes, bandwidth_Bps=200e6, notice_s=30)               # reactive flush
    keep = select_prefixes(ranked, sizes, bandwidth_Bps=200e6, notice_s=30, hot_set_n=2)  # hybrid

No-preservation (keep nothing) and write-through (keep everything) need no policy.
"""
import csv
import math


def kv_bytes_per_token(num_layers, num_kv_heads, head_dim, dtype_bytes=2):
    """KV cache bytes per token: layers x KV heads x head dim x 2 (K and V) x bytes per value.
    Read the first three from the model's config.json
    (num_hidden_layers, num_key_value_heads, hidden_size / num_attention_heads)."""
    return num_layers * num_kv_heads * head_dim * 2 * dtype_bytes


KV_BYTES_PER_TOKEN = {
    "Qwen/Qwen2.5-7B-Instruct": kv_bytes_per_token(28, 4, 128),           # 57,344
    "meta-llama/Llama-3.1-8B-Instruct": kv_bytes_per_token(32, 8, 128),   # 131,072
}

CHARS_PER_TOKEN_FALLBACK = 4  # used only if a log row has no prompt_tokens


def _row_tokens(row):
    n = row.get("prompt_tokens")
    if n not in (None, ""):
        return int(n)
    return math.ceil(int(row["prompt_chars"]) / CHARS_PER_TOKEN_FALLBACK)


def hotness_table(log_csv, t_notice, window_s=300):
    """Per-prefix stats in the window [t_notice - window_s, t_notice).
    Returns {prefix_id: (frequency, tokens, hotness)}."""
    freq, tokens = {}, {}
    with open(log_csv, newline="") as f:
        for row in csv.DictReader(f):
            if row.get("status") != "ok":
                continue
            try:
                t = float(row["send_wall"])
            except (KeyError, ValueError):
                continue
            if not (t_notice - window_s <= t < t_notice):
                continue
            pid = row["prefix_id"]
            freq[pid] = freq.get(pid, 0) + 1
            # largest length in the window = the latest history (what gets reused next)
            tokens[pid] = max(tokens.get(pid, 0), _row_tokens(row))
    return {p: (freq[p], tokens[p], freq[p] * tokens[p]) for p in freq}


def rank_prefixes(log_csv, t_notice, kv_bytes_per_token, window_s=300):
    """Returns (ranked, sizes_bytes):
       ranked       prefix_ids, hottest first (ties: larger prefix, then prefix_id)
       sizes_bytes  {prefix_id: estimated KV size in bytes}"""
    table = hotness_table(log_csv, t_notice, window_s)
    ranked = sorted(table, key=lambda p: (-table[p][2], -table[p][1], p))
    sizes = {p: table[p][1] * kv_bytes_per_token for p in ranked}
    return ranked, sizes


def select_prefixes(ranked, sizes_bytes, bandwidth_Bps, notice_s, hot_set_n=0, safety_s=2.0):
    """Returns the prefix_ids that survive the preemption, in rank order.

    hot_set_n = 0  -> reactive flush
    hot_set_n = N  -> hybrid: the top N already live in the remote store, so they
                      survive regardless of notice; the budget covers the rest.
    budget = bandwidth_Bps * max(notice_s - safety_s, 0)
    A prefix that doesn't fit is skipped; smaller ones further down may still fit."""
    hot = list(ranked[:hot_set_n])
    budget = bandwidth_Bps * max(notice_s - safety_s, 0)
    keep = list(hot)
    for pid in ranked[hot_set_n:]:
        size = sizes_bytes[pid]
        if size <= budget:
            keep.append(pid)
            budget -= size
    order = {p: i for i, p in enumerate(ranked)}
    return sorted(keep, key=order.__getitem__)


def hot_set(ranked, hot_set_n):
    """Prefixes the hybrid policy replicates in the background (call every ~30 s)."""
    return list(ranked[:hot_set_n])