#!/usr/bin/env python3
"""Diagnostic (not a held-out result): rerun one engine on the tasks an earlier frozen L0 run left unsolved.
These failures were seen before the gear was written, so the outcome is dev-contaminated and is reported as such."""
import json, sys, os, hashlib
import l0_mutants as M
prev, root, out = sys.argv[1:4]
fail = {}
for l in open(prev):
    r = json.loads(l)
    if not r["solved"] and not r["file"].startswith(("commons-lang/", "requests/", "flask/")): fail[r["id"]] = r["file"]
M.ROOT = os.path.abspath(root); tasks = []
for rel in sorted(set(fail.values())):
    for ln, cls, x, y, o, rp in M.mutants(os.path.join(M.ROOT, rel)):
        tid = hashlib.sha1(f"{rel}:{ln}:{x}:{rp}".encode()).hexdigest()[:16]
        if tid in fail: tasks.append((tid, rel, ln, cls, x, y, o, rp))
print("tasks", len(tasks), "of", len(fail), file=sys.stderr)
with open(out, "w") as fo:
    for t in tasks: fo.write(json.dumps(M.run(t)) + "\n")
