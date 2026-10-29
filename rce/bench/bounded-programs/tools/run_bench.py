"""The registered run of rce/bench/bounded-programs (see ../PREREG.json).

usage: run_bench.py RCE_BIN RCE_PROGRAMS_DIR OUT_DIR WORK_DIR [m1 m2 m3 m4]

RCE_PROGRAMS_DIR is programs/ of openIE-dev/rce at the registered commit.
Every measurement is a wall-clock time of one process (time.perf_counter),
with its peak resident set size; timings are the median of REPS runs.
"""
import json, os, re, resource, statistics, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
rce, progs, out, work = [os.path.abspath(a) for a in sys.argv[1:5]]
which = sys.argv[5:] or ["m1", "m2", "m3", "m4"]
os.makedirs(out, exist_ok=True); os.makedirs(work, exist_ok=True)
MEM = 4 * 1024 ** 3
REPS = 3


def run(cmd, timeout=300, cwd=None):
    """One process: wall seconds, peak RSS in KiB, exit status, output."""
    def lim():
        resource.setrlimit(resource.RLIMIT_AS, (MEM, MEM))
    t = time.perf_counter()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, preexec_fn=lim, cwd=cwd)
        rc, o = p.returncode, p.stdout + p.stderr
    except subprocess.TimeoutExpired:
        rc, o = "timeout", ""
    dt = time.perf_counter() - t
    # ru_maxrss of children is a maximum over all children so far, so a peak
    # is measured by peak_rss in a fresh wrapper process instead.
    return {"wall_s": round(dt, 4), "rc": rc, "out": o[-600:]}


def timed(cmd, reps=REPS, timeout=300, cwd=None):
    rs = [run(cmd, timeout, cwd) for _ in range(reps)]
    return {"wall_s_median": round(statistics.median(r["wall_s"] for r in rs), 4),
            "wall_s_all": [r["wall_s"] for r in rs], "rc": rs[0]["rc"], "out": rs[0]["out"]}


def peak_rss(cmd, timeout=300):
    """Peak RSS (KiB) of one run, read from the child's rusage alone."""
    code = ("import resource,subprocess,sys,json;"
            "resource.setrlimit(resource.RLIMIT_AS,(%d,%d));" % (MEM, MEM) +
            "p=subprocess.run(sys.argv[1:],capture_output=True);"
            "print(json.dumps({'rc':p.returncode,'maxrss_kb':resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss}))")
    try:
        p = subprocess.run([sys.executable, "-c", code] + cmd, capture_output=True, text=True, timeout=timeout)
        return json.loads(p.stdout.strip().splitlines()[-1])
    except Exception as e:  # timeout or no output
        return {"rc": "timeout" if isinstance(e, subprocess.TimeoutExpired) else str(e), "maxrss_kb": None}


def dump(name, obj):
    with open(os.path.join(out, name), "w") as f:
        json.dump(obj, f, indent=1, sort_keys=True)
        f.write("\n")


def without_checks(src):
    return "\n".join(l for l in src.splitlines() if not l.startswith("check ")) + "\n"


# ---------------------------------------------------------------- M1
def m1():
    src = open(os.path.join(progs, "text/json_nest.rce")).read()
    base = without_checks(src) + '\nfn wide(w: usize) -> text = "[" + ",".join(["7" for _i in 0..w]) + "]"\n'
    res = {"program": "programs/text/json_nest.rce"}
    res["check"] = timed([rce, "check", os.path.join(progs, "text/json_nest.rce")])
    res["test"] = timed([rce, "test", os.path.join(progs, "text/json_nest.rce")])
    res["descent_verdict"] = run([rce, "check", os.path.join(progs, "text/change/json_descent.rce")])
    rows = []

    def drive(kind, expr, expect, param):
        f = os.path.join(work, "m1_%s_%d.rce" % (kind, param))
        open(f, "w").write(base + "\nfn main()\n    emit (%s).tostr()\n" % expr)
        t = timed([rce, "run", f], reps=REPS if param <= 2000 else 1, timeout=900)
        got = re.findall(r'emit "(-?\d+)"', t["out"])
        row = {"kind": kind, "param": param, "expect": expect, "got": got[0] if got else None,
               "wall_s_median": t["wall_s_median"], "wall_s_all": t["wall_s_all"], "rc": t["rc"],
               "tail": t["out"][-200:], "peak": peak_rss([rce, "run", f], timeout=900)}
        rows.append(row)
        print(json.dumps({k: row[k] for k in ("kind", "param", "got", "wall_s_median", "rc")}), flush=True)

    for d in [1, 10, 100, 1000, 2000, 4000]:
        drive("loop", "loop_depth(nest(%d))" % d, str(d), d)
        drive("malformed", "loop_depth(unclosed(%d))" % d, str(-(2 * d + 1)), d)
    for d in [1, 10, 100, 1000, 2000]:
        drive("recursion", "depth_of(nest(%d))" % d, str(d), d)
    for w in [1000, 4000, 16000]:
        drive("wide", "loop_depth(wide(%d))" % w, "1", w)
    res["runs"] = rows

    # the smallest depth at which `rce test` of `check depth_of(nest(d)) == d`
    # ends in a native abort rather than a verdict (bisection on 100..4000)
    def aborts(d):
        f = os.path.join(work, "m1_stack_%d.rce" % d)
        open(f, "w").write(without_checks(src) + "\ncheck depth_of(nest(%d)) == %d\n" % (d, d))
        r = run([rce, "test", f], timeout=600)
        return r["rc"] not in (0, 1), r
    lo, hi, probes = 100, 4000, []
    a, r = aborts(hi); probes.append((hi, r["rc"]))
    if a:
        while hi - lo > 10:
            mid = (lo + hi) // 2
            a, r = aborts(mid); probes.append((mid, r["rc"]))
            if a: hi = mid
            else: lo = mid
    res["test_stack_abort"] = {"last_pass": lo, "first_abort": hi, "probes": probes}

    # the capped alternative: recursive descent with `bound 2000`
    bd = os.path.join(HERE, "json_descent_bound.rce")
    bsrc = without_checks(open(bd).read())
    for d in [1000, 1999, 2000]:
        f = os.path.join(work, "m1_bound_%d.rce" % d)
        open(f, "w").write(bsrc + "\nfn main()\n    emit run(%d).tostr()\n" % d)
        r = run([rce, "run", f], timeout=600)
        res.setdefault("bounded_descent", []).append({"depth": d, "rc": r["rc"], "wall_s": r["wall_s"], "tail": r["out"][-120:]})
    dump("m1_json.json", res)


# ---------------------------------------------------------------- M2
def m2():
    prog = os.path.join(progs, "systems/accounts.rce")
    sys.path.insert(0, HERE)
    import gen_events
    ev = gen_events.events(100000)
    evf = os.path.join(work, "events100k.txt")
    open(evf, "w").write("\n".join(ev) + "\n")
    logd = os.path.join(work, "D_accounts")
    if os.path.exists(logd):
        os.remove(logd)
    lat_json = os.path.join(work, "lat100k.json")
    t = time.perf_counter()
    subprocess.run([sys.executable, os.path.join(HERE, "drive.py"), rce, prog, logd, evf, lat_json], check=True)
    total = time.perf_counter() - t
    d = json.load(open(lat_json))
    lat = d["latency_ns"]
    blocks = []
    for b in range(10):
        xs = sorted(lat[b * 10000:(b + 1) * 10000])
        q = lambda p: xs[min(len(xs) - 1, int(p * len(xs)))] / 1000.0
        blocks.append({"block": b, "events": [b * 10000, (b + 1) * 10000], "median_us": q(0.5), "p90_us": q(0.9),
                       "p99_us": q(0.99), "max_us": xs[-1] / 1000.0, "mean_us": sum(xs) / len(xs) / 1000.0})
    # T8 on the log: each kept input's state_hash equals the entry before it
    entries = [json.loads(l) for l in open(logd)]
    by_seq = {e["seq"]: e for e in entries}
    kept_inputs, t8_ok, t8_bad = 0, 0, []
    for e in entries:
        if e["event"]["type"] == "host.StepKept":
            q = e["event"]["payload"]["seq"]
            kept_inputs += 1
            if by_seq[q]["state_hash"] == by_seq[q - 1]["state_hash"]:
                t8_ok += 1
            else:
                t8_bad.append(q)
    types = {}
    for e in entries:
        types[e["event"]["type"]] = types.get(e["event"]["type"], 0) + 1
    res = {"program": "programs/systems/accounts.rce", "events": len(ev), "driver_wall_s": round(total, 2),
           "kept_replies": d["kept"], "rc": d["rc"], "host_tail": d["tail"][-400:], "host_stderr_tail": d["stderr"][-300:],
           "log_entries": len(entries), "log_bytes": os.path.getsize(logd), "entry_types": types,
           "kept_entries": kept_inputs, "t8_state_unchanged": t8_ok, "t8_violations": t8_bad[:20],
           "blocks": blocks}
    # the pure step: rce trace over the same events in one run (no host, no
    # durable append), at three prefix lengths
    tr = []
    for n in [25000, 50000, 100000]:
        sf = os.path.join(work, "stream_%d.txt" % n)
        open(sf, "w").write(", ".join(ev[:n]) + "\n")
        of = os.path.join(work, "trace_%d.json" % n)
        t = time.perf_counter()
        with open(of, "w") as fo:
            p = subprocess.run([rce, "trace", "--json", prog, "--streams", sf], stdout=fo, stderr=subprocess.PIPE, text=True)
        dt = time.perf_counter() - t
        tr.append({"events": n, "wall_s": round(dt, 3), "rc": p.returncode, "us_per_event": round(dt / n * 1e6, 2),
                   "bytes": os.path.getsize(of), "stderr": p.stderr[-200:]})
        os.remove(of)
        print(json.dumps(tr[-1]), flush=True)
    res["trace"] = tr
    dump("m2_service.json", res)
    with open(os.path.join(out, "m2_latency_us.txt"), "w") as f:
        f.write("\n".join("%.1f" % (x / 1000.0) for x in lat) + "\n")
    os.remove(logd)


# ---------------------------------------------------------------- M3
def m3():
    sys.path.insert(0, HERE)
    import gen_checkout
    rows = []
    for n in [5, 10, 20, 40, 80]:
        f = os.path.join(work, "checkout%d.rce" % n)
        s = gen_checkout.gen(n)
        open(f, "w").write(s)
        test = run([rce, "test", f])
        chk = timed([rce, "check", f], reps=5)
        form = run([rce, "emit", "form", f])
        fb = len(subprocess.run([rce, "emit", "form", f], capture_output=True).stdout)
        dim = run([rce, "dim", "--json", f], timeout=900)
        try:
            dj = json.loads(dim["out"].strip().splitlines()[-1]) if dim["rc"] == 0 else {}
        except Exception:
            dj = {}
        row = {"options": n, "source_lines": s.count("\n"), "source_bytes": len(s.encode()),
               "test_rc": test["rc"], "test_out": test["out"][-120:], "check_wall_s_median": chk["wall_s_median"],
               "check_wall_s_all": chk["wall_s_all"], "form_bytes": fb, "form_rc": form["rc"],
               "dim_wall_s": dim["wall_s"], "dim_rc": dim["rc"],
               "dim_states": dj.get("states"), "dim_behaviours": dj.get("behaviours"),
               "dim_bound_reached": dj.get("bound_reached"), "dim_tail": dim["out"][-200:] if not dj else ""}
        rows.append(row)
        print(json.dumps({k: row[k] for k in ("options", "form_bytes", "check_wall_s_median", "dim_states", "dim_bound_reached", "dim_wall_s")}), flush=True)
    # least squares of form bytes and check time on options
    def fit(ys):
        xs = [r["options"] for r in rows]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        sxx = sum((x - mx) ** 2 for x in xs); sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        b = sxy / sxx; a = my - b * mx
        ss = sum((y - a - b * x) ** 2 for x, y in zip(xs, ys)); st = sum((y - my) ** 2 for y in ys)
        return {"intercept": round(a, 4), "slope_per_option": round(b, 6), "r2": round(1 - ss / st, 5)}
    res = {"rows": rows, "fit_form_bytes": fit([r["form_bytes"] for r in rows]),
           "fit_source_bytes": fit([r["source_bytes"] for r in rows]),
           "fit_check_s": fit([r["check_wall_s_median"] for r in rows])}
    # the 40-option program in the repository is the generator's output
    repo40 = open(os.path.join(progs, "money/checkout.rce")).read()
    res["repo_checkout_is_generated_40"] = repo40 == gen_checkout.gen(40)
    dump("m3_checkout.json", res)


# ---------------------------------------------------------------- M4
def m4():
    res = {}
    for name in ["science/graph.rce", "science/dpll.rce"]:
        p = os.path.join(progs, name)
        s = open(p).read()
        code = [l for l in s.splitlines() if not l.lstrip().startswith("#")]
        res[name] = {"lines": len(s.splitlines()), "code_lines": len([l for l in code if l.strip()]),
                     "bound_clauses": sum(len(re.findall(r"\bbound\b", l)) for l in code),
                     "decreases_lines": sum(1 for l in code if l.strip().startswith("decreases")),
                     "test": timed([rce, "test", p])}
    g = without_checks(open(os.path.join(progs, "science/graph.rce")).read())
    rows = []
    for n in [100, 200, 400, 800]:
        for fn in ["far", "far_hops"]:
            f = os.path.join(work, "m4_%s_%d.rce" % (fn, n))
            open(f, "w").write(g + "\nfn main()\n    emit %s(%d).tostr()\n" % (fn, n))
            t = timed([rce, "run", f], timeout=600)
            rows.append({"fn": fn, "n": n, "expect": str(n - 1), "out": t["out"][-60:], "wall_s_median": t["wall_s_median"], "rc": t["rc"]})
            print(json.dumps(rows[-1]), flush=True)
    res["graph_runs"] = rows
    dp = without_checks(open(os.path.join(progs, "science/dpll.rce")).read())
    dp += ("\nfn taut(n: usize) -> bool\n    let cs: List[List[i64]] = [[i as i64, 0 - (i as i64)] for i in 1..=n]\n"
           "    return satisfiable(n, &cs)\n")
    drows = []
    for label, expr in [("php2", "php_sat(2)"), ("php3", "php_sat(3)"), ("php4", "php_sat(4)"), ("php5", "php_sat(5)"),
                        ("taut63", "taut(63)"), ("taut64", "taut(64)")]:
        f = os.path.join(work, "m4_%s.rce" % label)
        open(f, "w").write(dp + "\nfn main()\n    emit %s.tostr()\n" % expr)
        r = run([rce, "run", f], timeout=900)
        drows.append({"case": label, "rc": r["rc"], "wall_s": r["wall_s"], "out": r["out"][-80:]})
        print(json.dumps(drows[-1]), flush=True)
    res["dpll_runs"] = drows
    dump("m4_search.json", res)


env = {"rce": rce, "rce_version": subprocess.run([rce, "v09-status"], capture_output=True, text=True).stdout[:200],
       "uname": " ".join(os.uname()), "cpus": os.cpu_count(), "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
dump("env_%s.json" % "_".join(which), env)
for m in which:
    globals()[m]()
