"""Drive `rce host serve FILE --log D` one stdin line per event, in lockstep:
write one event, wait for the host's line for it. Records per-event latency."""
import subprocess, sys, time, json
rce, prog, logd, evfile, outjson = sys.argv[1:6]
errf = open(outjson + ".stderr", "w")
evs = [l.rstrip("\n") for l in open(evfile)]
p = subprocess.Popen([rce, "host", "serve", prog, "--log", logd], stdin=subprocess.PIPE,
                     stdout=subprocess.PIPE, stderr=errf, text=True, bufsize=1)
lat = []; kept = 0; lines = []
for e in evs:
    t = time.perf_counter_ns()
    p.stdin.write(e + "\n"); p.stdin.flush()
    while True:
        line = p.stdout.readline()
        if line == "" or line.startswith("ok") or line.startswith("kept "):
            break
    lat.append(time.perf_counter_ns() - t)
    if line.startswith("kept "): kept += 1
    lines.append(line.rstrip("\n"))
p.stdin.close()
tail = p.stdout.read(); rc = p.wait(); errf.close(); err = open(outjson + ".stderr").read()[-2000:]
json.dump({"n": len(evs), "kept": kept, "latency_ns": lat, "rc": rc, "tail": tail, "stderr": err,
           "first_lines": lines[:5], "last_lines": lines[-5:]}, open(outjson, "w"))
print(json.dumps({"n": len(evs), "kept": kept, "rc": rc, "tail": tail[-400:], "stderr": err[-300:]}))
