#!/usr/bin/env python3
"""Ladder L5, function synthesis from spec. 0-model arm: G5-E (synth.py) on the task's examples; optional
index arm: programs already accepted (e.g. from the local-model arm) looked up by task spec, 0 calls.
Usage: l5_run.py mbpp|humaneval DATA OUT.jsonl [--ids LO-HI] [--index INDEX.jsonl] [--jobs J]
MBPP split (Austin et al. 2021): 11-510 test, 511-600 validation, 601-974 train. DEV = validation+train.
Gate: MBPP test_list asserts; HumanEval the hidden check(), run in a separate python -I process, 10 s, 1 GB."""
import ast, json, os, re, sys, subprocess, tempfile, gzip, time, hashlib, resource
from concurrent.futures import ProcessPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
def lit(s):
    try: return True, ast.literal_eval(s)
    except Exception: return False, None
def mbpp_spec(t):
    ex, name = [], None
    for a in t["test_list"]:
        m = re.match(r"\s*assert\s+(.*)$", a.strip())
        if not m: continue
        try: node = ast.parse(m.group(1), mode="eval").body
        except Exception: continue
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq) and isinstance(node.left, ast.Call):
            call, exp = node.left, node.comparators[0]
            name = getattr(call.func, "id", name)
            args = [lit(ast.unparse(x)) for x in call.args]; e = lit(ast.unparse(exp))
            if all(a[0] for a in args) and e[0]: ex.append(([a[1] for a in args], e[1]))
    return name, ex
def he_spec(t):
    p = t["prompt"]; name = t["entry_point"]
    sig = re.search(rf"def {name}\((.*?)\)\s*(->.*?)?:", p, re.S)
    params = [x.split(":")[0].split("=")[0].strip() for x in sig.group(1).split(",") if x.strip()] if sig else []
    ex = []
    for m in re.finditer(rf">>>\s*{name}\((.*)\)\s*\n\s*(.+)", p):
        a, o = lit("(" + m.group(1) + ",)"), lit(m.group(2).strip())
        if a[0] and o[0]: ex.append((list(a[1]), o[1]))
    for m in re.finditer(rf"{name}\((.*?)\)\s*(?:==|➞|=>|->|should return|returns?)\s*(.+)", p):
        a, o = lit("(" + m.group(1) + ",)"), lit(m.group(2).strip().rstrip("."))
        if a[0] and o[0] and (list(a[1]), o[1]) not in ex: ex.append((list(a[1]), o[1]))
    return name, params, ex
def gate(code, tests, timeout=10):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f: f.write(code + "\n" + tests + "\n"); fn = f.name
    def lim(): resource.setrlimit(resource.RLIMIT_AS, (1 << 30, 1 << 30))
    try: r = subprocess.run([sys.executable, "-I", fn], capture_output=True, timeout=timeout, preexec_fn=lim); return r.returncode == 0
    except subprocess.TimeoutExpired: return False
    finally: os.unlink(fn)
def spec_hash(kind, t): return hashlib.sha1((kind + str(t.get("task_id"))).encode()).hexdigest()[:16]
INDEX = {}
def solve(arg):
    kind, t = arg; t0 = time.time(); c0 = os.times()
    rec = {"id": f"{kind}/{t['task_id']}", "rung": "L5", "src": kind, "llm_calls": 0, "solved": False, "gear": None, "n_examples": 0, "program": None}
    if kind == "mbpp":
        name, ex = mbpp_spec(t); params = [f"a{i}" for i in range(len(ex[0][0]))] if ex else []
        head = (t.get("test_setup_code") or "") + "\nimport math\n"; tests = "\n".join(t["test_list"])
        mk = lambda e: f"{head}\ndef {name}({', '.join(params)}):\n    return {e}\n"
    else:
        name, params, ex = he_spec(t); tests = t["test"] + f"\ncheck({name})\n"
        mk = lambda e: "import math\n" + t["prompt"] + f"    return {e}\n"
    rec["n_examples"] = len(ex)
    h = spec_hash(kind, t)
    if h in INDEX:  # compiled-out handler from an earlier supplier, 0 calls
        prog = INDEX[h]
        if gate(prog, tests): rec.update(solved=True, gear="G0-index", program=prog)
    if not rec["solved"] and ex and name:
        try:
            r = subprocess.run([sys.executable, os.path.join(HERE, "synth.py")], input=json.dumps({"params": params, "examples": ex, "timeout": 40}), capture_output=True, text=True, timeout=50)
            e = json.loads(r.stdout or "{}").get("expr")
        except Exception: e = None
        if e:
            prog = mk(e); rec["program"] = prog
            if gate(prog, tests): rec.update(solved=True, gear="G5-E")
    c1 = os.times(); rec["cpu_s"] = round(c1.children_user - c0.children_user + c1.children_system - c0.children_system, 3); rec["wall_s"] = round(time.time() - t0, 2)
    return rec
def _init(ix):
    INDEX.update(ix)
if __name__ == "__main__":
    kind, data, out = sys.argv[1:4]; a = sys.argv[4:]
    g = lambda k, d: a[a.index(k) + 1] if k in a else d
    ts = [json.loads(l) for l in (gzip.open(data, "rt") if data.endswith(".gz") else open(data))]
    if kind == "mbpp" and "--ids" in a:
        lo, hi = map(int, g("--ids", "").split("-")); ts = [t for t in ts if lo <= t["task_id"] <= hi]
    ix = {}
    if "--index" in a:
        for l in open(g("--index", "")): r = json.loads(l); ix[r["spec"]] = r["program"]
    done = set(json.loads(l)["id"] for l in open(out)) if os.path.exists(out) else set()
    ts = [t for t in ts if f"{kind}/{t['task_id']}" not in done]
    with open(out, "a") as fo, ProcessPoolExecutor(int(g("--jobs", "4")), initializer=_init, initargs=(ix,)) as ex:
        for r in ex.map(solve, [(kind, t) for t in ts]): fo.write(json.dumps(r) + "\n"); fo.flush()
