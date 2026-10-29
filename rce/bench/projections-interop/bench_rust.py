#!/usr/bin/env python3
"""M3 for Rust: run the bench mode of the emitted-code service and of the
hand-written crate REPS times per program and take the median per phase.
Usage: bench_rust.py EMITTED_EXE HAND_EXE STREAMS_DIR PASSES REPS > results/bench-rust.json"""
import json, os, statistics, subprocess, sys

EXE, HAND, STREAMS, PASSES, REPS = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5])
NAMES = ["counter", "bank", "multi_region", "traffic_light", "door", "inventory", "rcedb", "float_keys"]
out = {}
for n in NAMES:
    sp = os.path.join(STREAMS, n + ".0.json")
    for kind, exe in (("emitted", EXE), ("hand", HAND)):
        runs = [json.loads(subprocess.run([exe, "bench", n, sp, PASSES], capture_output=True, text=True, check=True).stdout) for _ in range(REPS)]
        out.setdefault(kind, {})[n] = {k: round(statistics.median(r[k] for r in runs)) for k in ("decode_ns", "step_ns", "encode_ns")}
rv = subprocess.run(["rustc", "--version"], capture_output=True, text=True).stdout.strip()
json.dump({"lang": "rust", "version": rv, "passes": int(PASSES), "reps": REPS, "results": out}, sys.stdout, indent=1, sort_keys=True)
print()
