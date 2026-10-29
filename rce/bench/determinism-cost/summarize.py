#!/usr/bin/env python3
"""Tables of RESULTS.md from results/results.json (bench-determinism.py).

    summarize.py results/results.json > results/tables.md
"""
import json, statistics, sys

d = json.load(open(sys.argv[1]))
P = d["programs"]
cpu = lambda p, k: P[p]["configs"][k]["ns_per_step_cpu"] if k in P[p]["configs"] else None
wall = lambda p, k: P[p]["configs"][k]["ns_per_step_wall"] if k in P[p]["configs"] else None


def f(x, nd=0):
    if x is None:
        return "-"
    if abs(x) >= 100 or nd == 0:
        return f"{x:,.0f}"
    return f"{x:.{nd}f}"


def r(a, b):
    return None if a is None or b is None or b <= 0 else a / b


m = d["machine"]
print(f"Machine: {m['cpu']}, {m['logical_cpus']} logical CPUs, {m['os']}; load average at start {m['loadavg_at_start']}; rce {m['rce_commit']} (tree dirty: {m['rce_tree_dirty']}); {m['rustc']}; {m['steps']} steps per stream, {m['repeats']} repeats, runs of at least {m['min_run_s']} s; seed {m['seed']}.\n")

cols = ["checker_delta", "checker_encode", "checker_chain", "checker_chainfast", "checker_ckpt64", "checker_host", "checker_host1",
        "emit_quiet", "emit_trace_quiet", "emit_plain", "emit_trace", "hand_fma", "hand_nofma", "hand_nofma_log"]
names = ["b delta", "encode", "a chain", "chainfast", "ckpt64", "a host", "host1", "c quiet", "c trace quiet", "c plain", "c trace", "d fma", "d nofma", "d nofma+log"]
print("### CPU ns per step (median of the repeats)\n")
print("| program | class | " + " | ".join(names) + " |")
print("|---|---|" + "---:|" * len(names))
for p, v in P.items():
    print(f"| {p} | {v['class']} | " + " | ".join(f(cpu(p, c), 1) for c in cols) + " |")
print("\n### Wall ns per step (median of the repeats)\n")
print("| program | " + " | ".join(names) + " |")
print("|---|" + "---:|" * len(names))
for p, v in P.items():
    print(f"| {p} | " + " | ".join(f(wall(p, c), 1) for c in cols) + " |")

facs = [
    ("log, checker: a chain / b delta", "checker_chain", "checker_delta"),
    ("log, host: a host / b delta", "checker_host", "checker_delta"),
    ("log, emitted: trace quiet / quiet", "emit_trace_quiet", "emit_quiet"),
    ("log, native: nofma+log / nofma", "hand_nofma_log", "hand_nofma"),
    ("float rule: nofma / fma", "hand_nofma", "hand_fma"),
    ("emitted / hand: quiet / fma", "emit_quiet", "hand_fma"),
    ("emitted+log / hand: trace quiet / fma", "emit_trace_quiet", "hand_fma"),
    ("checker / emitted: b delta / c quiet", "checker_delta", "emit_quiet"),
    ("chainfast / chain (hex from a table)", "checker_chainfast", "checker_chain"),
    ("ckpt64 / chain", "checker_ckpt64", "checker_chain"),
]
print("\n### Ratios (CPU)\n")
print("| program | class | " + " | ".join(n for n, _, _ in facs) + " |")
print("|---|---|" + "---:|" * len(facs))
for p, v in P.items():
    print(f"| {p} | {v['class']} | " + " | ".join(f(r(cpu(p, a), cpu(p, b)), 2) for _, a, b in facs) + " |")

print("\n### Median ratio per class (CPU), classed against the claimed 10x to 100x\n")
klass = lambda x: "-" if x is None else ("below 10x" if x < 10 else ("10x to 100x" if x <= 100 else "above 100x"))
classes = sorted({v["class"] for v in P.values()})
print("| factor | " + " | ".join(classes) + " | all |")
print("|---|" + "---|" * (len(classes) + 1))
for n, a, b in facs[:7]:
    row = []
    for c in classes + ["all"]:
        xs = [r(cpu(p, a), cpu(p, b)) for p, v in P.items() if (c == "all" or v["class"] == c)]
        xs = [x for x in xs if x is not None]
        med = statistics.median(xs) if xs else None
        row.append(f"{f(med, 2)} ({klass(med)}, n={len(xs)})" if xs else "-")
    print(f"| {n} | " + " | ".join(row) + " |")

print("\n### Where the checker's time goes (share of a host, CPU)\n")
print("| program | delta | JSON encoding | SHA-256 + hex | host bookkeeping | dominant |")
print("|---|---:|---:|---:|---:|---|")
for p in P:
    b, e, a, h = (cpu(p, k) for k in ("checker_delta", "checker_encode", "checker_chain", "checker_host"))
    parts = {"delta": b, "JSON encoding": e - b, "SHA-256 + hex": a - e, "host bookkeeping": h - a}
    dom = max(parts, key=parts.get)
    print(f"| {p} | " + " | ".join(f"{100 * x / h:.0f}%" for x in parts.values()) + f" | {dom} |")

print("\n### est_j per million steps (estimate: CPU seconds x 10 W, paper section 6.3; not measured)\n")
print("| program | b delta | a chain | a host | c quiet | c trace quiet | d fma | d nofma+log |")
print("|---|---:|---:|---:|---:|---:|---:|---:|")
for p in P:
    print(f"| {p} | " + " | ".join(f(None if cpu(p, k) is None else cpu(p, k) * 1e-9 * 10 * 1e6, 3) for k in ("checker_delta", "checker_chain", "checker_host", "emit_quiet", "emit_trace_quiet", "hand_fma", "hand_nofma_log")) + " |")

print("\n### Parity\n")
for p, v in P.items():
    bad = [k for k, x in v["parity"].items() if x is False]
    print(f"- {p}: chain head `{v['parity']['chain_head'][:16]}`; " + ("all checks equal" if not bad else f"FAILED: {bad}"))
