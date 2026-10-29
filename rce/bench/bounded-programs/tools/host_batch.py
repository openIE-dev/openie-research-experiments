"""Deviation for M2 (added after the registered run): rce trace stops at the
first kept step, so the registered 'pure step' row measured 257 steps.
This measures the host without the lockstep round trip instead: rce host run
with the first n events on stdin, one per line, timed as one process."""
import json, os, subprocess, sys, time
rce, prog, work, out = sys.argv[1:5]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen_events
ev = gen_events.events(100000)
rows = []
for n in [25000, 50000, 100000]:
    logd = os.path.join(work, "D_batch_%d" % n)
    if os.path.exists(logd):
        os.remove(logd)
    data = "\n".join(ev[:n]) + "\n"
    t = time.perf_counter()
    p = subprocess.run([rce, "host", "run", prog, "--log", logd], input=data, capture_output=True, text=True)
    dt = time.perf_counter() - t
    tail = [l for l in p.stdout.splitlines() if l.startswith("durable")]
    rows.append({"events": n, "wall_s": round(dt, 2), "us_per_event": round(dt / n * 1e6, 1), "rc": p.returncode,
                 "durable": tail[-1] if tail else "", "stderr_tail": p.stderr[-160:]})
    print(json.dumps(rows[-1]), flush=True)
    os.remove(logd)
json.dump(rows, open(out, "w"), indent=1); open(out, "a").write("\n")
