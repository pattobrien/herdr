#!/usr/bin/env python3
"""Print a comparison table across benchmark result files."""
import json
import os
import sys

BENCH_DIR = os.path.dirname(os.path.abspath(__file__))
FILES = [
    ("raw", "results-raw.json"),
    ("tmux", "results-tmux.json"),
    ("herdr 0.8.0", "results-herdr.json"),
    ("fork", "results-fork.json"),
]

rows = {}
for label, name in FILES:
    path = os.path.join(BENCH_DIR, name)
    if not os.path.exists(path):
        continue
    data = json.load(open(path))
    entry = {}
    for key in ("typing_idle", "typing_churn", "typing_graphics"):
        r = data.get(key)
        entry[key] = (
            f"{r['p50_ms']}/{r['p95_ms']}ms ({r['echoed']}/{r['sent']})" if r and r["echoed"] else "-"
        )
    for key in ("churn_egress", "graphics_egress"):
        r = data.get(key)
        entry[key] = f"{r['bytes_per_sec']/1e6:.1f}MB/s" if r else "-"
    if "error" in data:
        entry["error"] = data["error"]
    rows[label] = entry

cols = ["typing_idle", "typing_churn", "typing_graphics", "churn_egress", "graphics_egress"]
print(f"{'target':<14}" + "".join(f"{c:<26}" for c in cols))
for label, entry in rows.items():
    print(f"{label:<14}" + "".join(f"{entry.get(c, '-'):<26}" for c in cols))
    if "error" in entry:
        print(f"  ERROR: {entry['error']}")
