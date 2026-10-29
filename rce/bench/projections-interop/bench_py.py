#!/usr/bin/env python3
"""M3 for Python: per-call cost at the boundary (PREREG.json, "boundary_cost").
Usage: bench_py.py RCE_TREE EMITTED_DIR STREAMS_DIR PASSES REPS > results/bench-python.json"""
import dataclasses, enum, json, os, statistics, sys, time

TREE, EMITTED, STREAMS, PASSES, REPS = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
sys.path.insert(0, os.path.join(TREE, "examples/interop/python"))
sys.path.insert(0, os.path.join(TREE, "examples/interop/hand/python"))
import rce_host, programs  # noqa: E402

NAMES = ["counter", "bank", "multi_region", "traffic_light", "door", "inventory", "rcedb", "float_keys"]
ns = time.perf_counter_ns


def emitted(name, texts):
    mod = rce_host.load(os.path.join(EMITTED, "python", name + ".py"), "m_" + name)
    d = s = e = c = 0
    for _ in range(PASSES):
        p = rce_host.Program(mod)
        for t in texts:
            t0 = ns(); ev = p.event(rce_host.decode(t)); t1 = ns(); p.step(ev); t2 = ns(); p.state_json(); t3 = ns()
            d += t1 - t0; s += t2 - t1; e += t3 - t2; c += 1
    return d / c, s / c, e / c


def plain(v):
    """The hand state as JSON-ready values: maps as [key, value] pairs."""
    if dataclasses.is_dataclass(v):
        return {f.name: plain(getattr(v, f.name)) for f in dataclasses.fields(v)}
    if isinstance(v, dict):
        return [[plain(k), plain(x)] for k, x in v.items()]
    if isinstance(v, (list, tuple)):
        return [plain(x) for x in v]
    if isinstance(v, enum.Enum):
        return v.name
    return v


def hand(name, texts):
    init, step = programs.PROGRAMS[name]
    d = s = e = c = 0
    for _ in range(PASSES):
        st = init()
        for t in texts:
            t0 = ns(); ev = json.loads(t); t1 = ns()
            try:
                st2, _ = step(st, ev)
                st = list(st2) if isinstance(st2, tuple) else [st2]
            except programs.Kept:
                pass
            t2 = ns(); json.dumps([plain(r) for r in st]); t3 = ns()
            d += t1 - t0; s += t2 - t1; e += t3 - t2; c += 1
    return d / c, s / c, e / c


out = {}
for n in NAMES:
    texts = [json.dumps(ev) for ev in json.load(open(os.path.join(STREAMS, n + ".0.json")))]
    for kind, f in (("emitted", emitted), ("hand", hand)):
        runs = [f(n, texts) for _ in range(REPS)]
        out.setdefault(kind, {})[n] = {k: round(statistics.median(r[i] for r in runs)) for i, k in enumerate(("decode_ns", "step_ns", "encode_ns"))}
json.dump({"lang": "python", "version": sys.version.split()[0], "passes": PASSES, "reps": REPS, "results": out}, sys.stdout, indent=1, sort_keys=True)
print()
