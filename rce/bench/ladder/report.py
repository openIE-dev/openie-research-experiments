#!/usr/bin/env python3
"""Per-rung table from result jsonl files: TEST split only (PREREG splits), Wilson 95% CI,
model calls, search bits (log2 rank of the solving candidate), est_j = cpu_s x 10 W (an estimate)."""
import json, math, sys, collections
L0_DEV = ("commons-lang/", "requests/", "flask/")
def wilson(k, n, z=1.96):
    if n == 0: return (0, 0)
    p = k / n; d = 1 + z * z / n; c = p + z * z / (2 * n); h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)
POS = {}
def rows(path, rung):
    if "manysstubs" in path and not POS:
        try: POS.update(json.load(open("/workspace/ladder-out/manysstubs-pos.json")))
        except Exception: pass
    for l in open(path):
        r = json.loads(l)
        if "pos" not in r and r["id"] in POS: r["pos"] = POS[r["id"]]
        if rung == "L0" and r["file"].startswith(L0_DEV): continue
        if rung == "L1" and r.get("pos", 10**9) < 2000: continue
        yield r
def table(groups):
    out = ["| stratum | N | solved | rate | Wilson 95% CI | model calls | median search bits | est_j per solved (cpu_s x 10 W, estimate) |", "|---|---|---|---|---|---|---|---|"]
    for name, R in groups:
        n = len(R); k = sum(r["solved"] for r in R); lo, hi = wilson(k, n)
        bits = sorted(math.log2(r["rank"]) for r in R if r["solved"] and r["rank"])
        mb = bits[len(bits) // 2] if bits else float("nan"); j = sum(r["cpu_s"] for r in R) * 10 / max(k, 1)
        out.append(f"| {name} | {n} | {k} | {k/max(n,1):.4f} | [{lo:.4f}, {hi:.4f}] | {sum(r['llm_calls'] for r in R)} | {mb:.1f} | {j:.3f} |")
    return "\n".join(out)
if __name__ == "__main__":
    spec = [a.split("=") for a in sys.argv[1:]]  # RUNG=path[:posfile]
    for rung, path in spec:
        R = list(rows(path, rung.split("-")[0]))
        key = "op" if rung.startswith("L0") else "bugType"
        by = collections.defaultdict(list)
        for r in R: by[r.get(key) or "?"].append(r)
        print(f"\n### {rung} ({path})\n"); print(table([("all", R)] + sorted(by.items(), key=lambda x: -len(x[1]))))
