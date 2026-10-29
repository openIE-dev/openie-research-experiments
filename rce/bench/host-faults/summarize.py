#!/usr/bin/env python3
"""Summarise runs.jsonl (one line per run of tests/host_faults.rs) into summary.json and tables."""
import collections, json, sys
src = sys.argv[1] if len(sys.argv) > 1 else "results/runs.jsonl"
rows = [json.loads(l) for l in open(src)]
by = collections.defaultdict(list)
for r in rows:
    by[(r["program"], r["mix"])].append(r)
out = {}
for (p, m), rs in sorted(by.items()):
    s = {"runs": len(rs), "not_live": sum(not r["live"] for r in rs),
         "a": sum(bool(r["a"]) or r["rerun_same_d"] is False for r in rs),
         "b": sum(bool(r["b"]) for r in rs), "c": sum(bool(r["c"]) for r in rs),
         "reruns": sum(r["rerun_same_d"] is not None for r in rs),
         "entries": sum(r["entries"] for r in rs),
         "ids": sum(r.get("ids", 0) for r in rs), "ids_after_restart": sum(r.get("ids_after_restart", 0) for r in rs),
         "host_dups_removed": sum(r["host_dups_removed"] for r in rs),
         "faults": collections.Counter(), "kept": collections.Counter(),
         "d_runs": collections.Counter(), "d_events": collections.Counter(), "d_min_seed": {},
         "d_example": {}, "gap_runs": collections.Counter()}
    for r in sorted(rs, key=lambda r: r["seed"]):
        s["faults"].update(r["faults"]); s["kept"].update(r["kept"])
        for k, n in r["d"].items():
            s["d_runs"][k] += 1; s["d_events"][k] += n
            if k not in s["d_min_seed"]:
                s["d_min_seed"][k] = r["seed"]
                s["d_example"][k] = r["d_note"][:2]
        for k in r.get("gap", {}):
            s["gap_runs"][k] += 1
    out[f"{p} {m}"] = s
json.dump(out, open("results/summary.json", "w"), indent=1, sort_keys=True, default=dict)
print("| program | mix | runs | (a) | (b) | (c) | not live | entries | net ids (after a restart) | kept | (d) runs per kind (lowest seed) |")
print("|---|---|---|---|---|---|---|---|---|---|---|")
for k, s in out.items():
    p, m = k.split(" ")
    d = "; ".join(f"{x} {n} (seed {s['d_min_seed'][x]})" for x, n in sorted(s["d_runs"].items())) or "0"
    if s["gap_runs"]:
        d += "; gap: " + "; ".join(f"{x} {n}" for x, n in s["gap_runs"].items())
    kept = ", ".join(f"{c} {n}" for c, n in sorted(s["kept"].items())) or "0"
    ids = f"{s['ids']} ({s['ids_after_restart']})" if s["ids"] else "-"
    print(f"| {p} | {m} | {s['runs']} | {s['a']} | {s['b']} | {s['c']} | {s['not_live']} | {s['entries']} | {ids} | {kept} | {d} |")
