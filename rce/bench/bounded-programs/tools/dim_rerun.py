"""Deviation fix for M3: run_bench.py kept only the last 600 characters of
rce dim's output, which cut the one-line JSON when it lists skipped events;
this reruns rce dim --json on the same generated files and keeps all of it."""
import json, subprocess, sys, time
rce, work, out = sys.argv[1:4]
rows = []
for n in [20, 40]:
    f = "%s/checkout%d.rce" % (work, n)
    t = time.perf_counter()
    p = subprocess.run([rce, "dim", "--json", f], capture_output=True, text=True, timeout=1800)
    dt = time.perf_counter() - t
    d = json.loads(p.stdout.strip().splitlines()[-1])
    rows.append({"options": n, "wall_s": round(dt, 2), "rc": p.returncode, "states": d["states"], "behaviours": d["behaviours"],
                 "bound_reached": d["bound_reached"], "skipped": len(d.get("skipped", []))})
    print(json.dumps(rows[-1]), flush=True)
json.dump(rows, open(out, "w"), indent=1); open(out, "a").write("\n")
