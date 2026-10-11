#!/usr/bin/env python3
"""Ladder L0: single-token operator mutants over real Java sources, solved by G1-J (rce repair tbar).
Usage: l0_mutants.py SRC_ROOT OUT.jsonl [--max N] [--jobs J] [--seed S]
One task = one PIT-style operator mutation on one line of a real file, location given (perfect FL).
Correctness gate: some candidate, applied, restores the original file token for token
(all whitespace removed before comparison; G1-J prints operators without spaces).
No model is called. Resumable: task ids already in OUT are skipped. cpu_s recorded; joules are
estimated from cpu_s elsewhere (labeled), RAPL on jetson-hub for a subsample."""
import json, os, random, re, subprocess, sys, time, hashlib
from concurrent.futures import ProcessPoolExecutor
RCE = os.environ.get("RCE", "/workspace/rce-work/build3/target/release/rce")  # runs pin a copy: RCE=/workspace/ladder-out/rce-<commit>
WD = os.environ.get("LADDER_WD", "/tmp/ladder-wd")
OPS = [
 ("relational", r"(?<![<>=!&|\-])(<=|>=|==|!=|<|>)(?![<>=])", ["<", "<=", ">", ">=", "==", "!="]),
 ("logical", r"(&&|\|\|)", ["&&", "||"]),
 ("pylogical", r"(?<=\s)(and|or)(?=\s)", ["and", "or"]),
 ("pybool", r"\b(True|False)\b", ["True", "False"]),
 ("arith", r"(?<=[\w\)\]]) ([+\-*/]) (?=[\w\(])", ["+", "-", "*", "/"]),
 ("bool", r"\b(true|false)\b", ["true", "false"]),
 ("intlit", r"(?<![\w.])([0-9])(?![\w.])", None),
]
ROOT = None
PY = False
NORM = lambda b: re.sub(rb"\s+", b"", b)  # gate: token-identical to the original, layout ignored
def mask(line):
    s = re.sub(r'"(\\.|[^"\\])*"', lambda m: "\0" * len(m.group()), line)
    s = re.sub(r"'(\\.|[^'\\])*'", lambda m: "\0" * len(m.group()), s)
    i = s.find("//") if not PY else s.find("#"); return s if i < 0 else s[:i] + "\0" * (len(s) - i)
def code_mask(text, py):
    """Per line, the set of columns that are code (not string, comment or docstring).
    Generator validity rule (preregistered): a mutant must change a code token."""
    lines = text.split("\n"); bad = [set() for _ in lines]
    if py:
        import io, tokenize
        try:
            for tk in tokenize.generate_tokens(io.StringIO(text).readline):
                if tk.type in (tokenize.STRING, tokenize.COMMENT) or tk.type == getattr(tokenize, "FSTRING_MIDDLE", -1):
                    (r0, c0), (r1, c1) = tk.start, tk.end
                    for r in range(r0, r1 + 1):
                        a = c0 if r == r0 else 0; b = c1 if r == r1 else len(lines[r - 1])
                        bad[r - 1].update(range(a, b))
        except Exception: return None
    else:
        inb = False
        for i, l in enumerate(lines):
            j = 0
            while j < len(l):
                if inb:
                    k = l.find("*/", j); e = len(l) if k < 0 else k + 2; bad[i].update(range(j, e)); j = e; inb = k < 0
                else:
                    k = l.find("/*", j)
                    if k < 0: break
                    if l.find("//", j) != -1 and l.find("//", j) < k: break
                    j = k; inb = True
    return bad
def mutants(path):
    global PY; PY = path.endswith(".py")
    text = open(path, encoding="utf-8", errors="replace").read()
    lines = text.split("\n"); bad = code_mask(text, PY)
    if bad is None: return
    for ln, line in enumerate(lines, 1):
        t = line.strip()
        if not t or t.startswith(("*", "/*", "//", "import", "package", "@")): continue
        m = mask(line)
        for cls, rx, reps in OPS:
            for mt in re.finditer(rx, m):
                a, b = mt.span(1); orig = line[a:b]
                if a in bad[ln - 1]: continue
                if cls == "relational" and orig in "<>" and re.search(r"\w<\w|\w>\s*\w|<[A-Z?]", line): continue  # generics
                rs = reps if reps else [str(int(orig) + 1)] + ([str(int(orig) - 1)] if orig != "0" else [])
                for r in rs:
                    if r != orig: yield ln, cls, a, b, orig, r
def run(task):
    tid, rel, ln, cls, a, b, orig, rep = task
    path = os.path.join(ROOT, rel)
    src = open(path, encoding="utf-8", errors="replace").read()
    lines = src.split("\n"); L = lines[ln - 1]; lines[ln - 1] = L[:a] + rep + L[b:]
    mut = "\n".join(lines); d = os.path.join(WD, f"w{os.getpid()}"); f = os.path.join(d, os.path.basename(path))
    os.makedirs(d, exist_ok=True); open(f, "w", encoding="utf-8").write(mut)
    lang = "python" if path.endswith(".py") else "java"
    rec = {"id": tid, "rung": "L0", "lang": lang, "op": cls, "file": rel, "line": ln, "orig": orig, "mut": rep, "llm_calls": 0,
           "solved": False, "gear": None, "rank": None, "pattern": None, "n_cands": 0, "cpu_s": 0.0, "err": False}
    mb = mut.encode(); ob = src.encode(); k = 0; dl = len(ob) - len(mb)
    ls0 = len("\n".join(lines[:ln - 1]).encode()) + (1 if ln > 1 else 0); le0 = ls0 + len(lines[ln - 1].encode())
    def restores(c):  # compare only the edited window; outside it mutant and original are identical
        a, b = min(c["start"], ls0), max(c["end"], le0)
        return NORM(mb[a:c["start"]] + c["text"].encode() + mb[c["end"]:b]) == NORM(ob[a:b + dl])
    gears = [("G0-T", [RCE, "repair", "g0", f, str(ln), "--lang", lang])]
    if lang == "java": gears.append(("G1-J", [RCE, "repair", "tbar", f, str(ln), "--src", d]))
    for gname, cmd in gears:  # Mixture of Limits: the cheapest gear first, escalate only when its gate fails
        c0 = os.times(); p = subprocess.run(cmd, capture_output=True, text=True); c1 = os.times()
        rec["cpu_s"] = round(rec["cpu_s"] + (c1.children_user - c0.children_user) + (c1.children_system - c0.children_system), 4)
        try: locs = json.loads(p.stdout or "[]")
        except Exception: locs = []; rec["err"] = True
        for loc in locs:
            for c in loc["cands"]:
                k += 1
                if restores(c):
                    rec.update(solved=True, gear=gname, rank=k, pattern=c["pattern"]); break
            if rec["solved"]: break
        if rec["solved"]: break
    rec["n_cands"] = k
    return rec
def _init(r):
    global ROOT; ROOT = r
def main():
    global ROOT
    ROOT, out = os.path.abspath(sys.argv[1]), sys.argv[2]; a = sys.argv[3:]
    g = lambda k, d: type(d)(a[a.index(k) + 1]) if k in a else d
    mx, jobs, seed = g("--max", 10**9), g("--jobs", os.cpu_count()), g("--seed", 20261011)
    done = set()
    if os.path.exists(out): done = {json.loads(l)["id"] for l in open(out) if l.strip()}
    tasks = []
    for d, _, fs in os.walk(ROOT):
        for fn in sorted(fs):
            if fn.endswith((".java", ".py")) and "/test" not in d and not fn.startswith("test"):
                rel = os.path.relpath(os.path.join(d, fn), ROOT)
                for ln, cls, x, y, o, r in mutants(os.path.join(d, fn)):
                    tasks.append((hashlib.sha1(f"{rel}:{ln}:{x}:{r}".encode()).hexdigest()[:16], rel, ln, cls, x, y, o, r))
    tasks.sort(); random.Random(seed).shuffle(tasks)
    print(f"population {len(tasks)}", file=sys.stderr)
    tasks = [t for t in tasks[:mx] if t[0] not in done]
    print(f"todo {len(tasks)} done {len(done)}", file=sys.stderr)
    with open(out, "a") as fo, ProcessPoolExecutor(jobs, initializer=_init, initargs=(ROOT,)) as ex:
        for i, r in enumerate(ex.map(run, tasks, chunksize=32)):
            fo.write(json.dumps(r) + "\n")
            if i % 1000 == 0: fo.flush(); print(i, file=sys.stderr, flush=True)
if __name__ == "__main__": main()
