#!/usr/bin/env python3
"""100-bug Defects4J run: all active Lang bugs, all Chart bugs, then the first
Math bugs up to 100, in bug-id order. G1 only, no model. Each bug's checkout is
deleted when it finishes; result.json and plausible.patch are kept.
usage: run_batch.py OUTDIR [JOBS]"""
import csv, json, os, shutil, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
D4J = os.environ.get("D4J_HOME", "/workspace/d4j")
out, jobs = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 3
bugs = []
for proj in ("Lang", "Chart", "Math"):
    for r in csv.DictReader(open(f"{D4J}/framework/projects/{proj}/active-bugs.csv")):
        bugs.append((proj, int(r["bug.id"])))
bugs = bugs[:100]
def one(pb):
    proj, b = pb; d = os.path.join(out, f"{proj}-{b}")
    if os.path.exists(os.path.join(d, "result.json")): return
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "log.txt"), "w") as lg:
        subprocess.run([sys.executable, os.path.join(HERE, os.environ.get("D4J_HARNESS", "d4j_repair.py")), proj, str(b), d], stdout=lg, stderr=lg, timeout=3600)
    shutil.rmtree(os.path.join(d, "work"), ignore_errors=True); shutil.rmtree(os.path.join(d, "runner"), ignore_errors=True)
    print(proj, b, open(os.path.join(d, "result.json")).read().replace("\n", "")[:200] if os.path.exists(os.path.join(d, "result.json")) else "no result", flush=True)
with ThreadPoolExecutor(jobs) as ex: list(ex.map(lambda pb: (lambda: one(pb))() if True else None, bugs))
rs = [json.load(open(os.path.join(out, f"{p}-{b}", "result.json"))) for p, b in bugs if os.path.exists(os.path.join(out, f"{p}-{b}", "result.json"))]
s = {"bugs": len(bugs), "results": len(rs), "errors": sum(1 for r in rs if r.get("error")),
     "plausible": sum(r["plausible"] for r in rs), "correct": sum(r["correct"] for r in rs),
     "llm_calls": 0, "est_j_total": round(sum(r.get("est_j", 0) for r in rs), 1),
     "est_j_note": "estimate: child CPU seconds x 10 W per CPU, not measured",
     "fixed": [r["bug"] + (" correct" if r["correct"] else " plausible") for r in rs if r["plausible"]]}
json.dump(s, open(os.path.join(out, "summary.json"), "w"), indent=1); print(json.dumps(s, indent=1))
