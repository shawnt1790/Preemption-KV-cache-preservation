"""Stand-in for Person B's policy.py, so the emulator can be built before it lands.
Same signatures as the spec ("Policy interface" in docs/Work Split and Plan ...md).
The emulator imports `policy` and falls back to this file; swapping in the real policy
needs no emulator change.

Not a real policy: rank_prefixes skips the hotness score, and select_prefixes ignores
the budget and keeps everything (it behaves like write-through).
"""
import csv


def rank_prefixes(log_csv, t_notice, kv_bytes_per_token, window_s=300):
    """Returns (ranked, sizes_bytes) for prefixes with an ok request in the window,
    in first-seen order. Size = max prompt_chars / 4 tokens, as in the spec."""
    tokens = {}
    with open(log_csv, newline="") as fh:
        for row in csv.DictReader(fh):
            if row["status"] != "ok" or not (t_notice - window_s <= float(row["send_wall"]) < t_notice):
                continue
            pid = row["prefix_id"]
            tokens[pid] = max(tokens.get(pid, 0), int(row["prompt_chars"]) // 4)
    return list(tokens), {pid: n * kv_bytes_per_token for pid, n in tokens.items()}


def select_prefixes(ranked, sizes_bytes, bandwidth_Bps, notice_s,
                    hot_set_n=0, safety_s=2.0):
    """Stub: keeps every ranked prefix, ignoring the budget."""
    return list(ranked)
