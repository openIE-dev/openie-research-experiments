#!/usr/bin/env python3
"""RCE Track A solver. Runs in the task's work copy (cwd) and walks the gear
stack, cheapest first, until the task's tests pass:

  G0 localize   run the tests, rank functions by the problem text and the
                failing test names.
  G1 patterns   TBar's 15 fix-pattern categories as guarded rewrites on
                the syntax tree (`rce repair candidates`), single site
                then two-site, each checked by the tests.
  G2 local LLM  the local model rewrites one ranked function; the tests
                check it. Last gear. At most RCE_SOLVER_LLM_CALLS calls.

Nothing is applied unless the tests pass. Receipts go to ../gears.json:
gear reached, test runs, LLM calls, the winning edit.
Env: RCE_PROBLEM, RCE_TEST_CMD, RCE_LOCAL_LLM_URL (default 127.0.0.1:8091).
"""
import json, os, re, subprocess, sys, time, urllib.request

PROBLEM = os.environ.get("RCE_PROBLEM", "")
TEST = os.environ["RCE_TEST_CMD"]
URL = os.environ.get("RCE_LOCAL_LLM_URL", "http://127.0.0.1:8091").rstrip("/") + "/v1/chat/completions"
MAX_LLM = int(os.environ.get("RCE_SOLVER_LLM_CALLS", "3"))
MAX_RULES = int(os.environ.get("RCE_SOLVER_RULE_TRIES", "600"))
MAX_PAIRS = int(os.environ.get("RCE_SOLVER_PAIR_TRIES", "150"))
R = {"gear": None, "test_runs": 0, "llm_calls": 0, "rule_tries": 0, "edit": None, "ranked": []}

BUDGET = [600.0]  # per test run, seconds; set from the first run

def run_tests():
    """Tests in their own process group; a hung mutant is killed whole."""
    R["test_runs"] += 1
    t = time.time()
    p = subprocess.Popen(["sh", "-c", TEST], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    try:
        out, _ = p.communicate(timeout=BUDGET[0])
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, 9); p.communicate()
        R["timeouts"] = R.get("timeouts", 0) + 1
        return False, "timeout"
    if R["test_runs"] == 1: BUDGET[0] = max(10.0, 5 * (time.time() - t))
    return p.returncode == 0, out[-3000:]

def sources():
    out = []
    for root, ds, fs in os.walk("."):
        ds[:] = [d for d in ds if d not in ("target", ".git", "__pycache__", "tests")]
        for f in fs:
            if (f.endswith(".rs") or f.endswith(".py")) and not f.startswith("test_"):
                out.append(os.path.join(root, f)[2:])
    return sorted(out)

def functions(path):
    """(name, start, end) spans of top level and impl level functions."""
    text = open(path, encoding="utf-8").read()
    spans = []
    if path.endswith(".rs"):
        for m in re.finditer(r"\bfn\s+(\w+)[^{;]*\{", text):
            if m.group(1).startswith("test") or "#[test]" in text[max(0, m.start() - 80):m.start()]: continue
            i, depth = m.end(), 1
            while i < len(text) and depth:
                depth += {"{": 1, "}": -1}.get(text[i], 0); i += 1
            s = text.rfind("\n", 0, m.start()) + 1
            spans.append((m.group(1), s, i))
    else:
        lines = text.splitlines(True); off = [0]
        for l in lines: off.append(off[-1] + len(l))
        for k, l in enumerate(lines):
            m = re.match(r"(\s*)def\s+(\w+)", l)
            if not m: continue
            ind, j = len(m.group(1)), k + 1
            depth = l.count("(") - l.count(")")
            while depth > 0 and j < len(lines):  # multi-line signature
                depth += lines[j].count("(") - lines[j].count(")"); j += 1
            while j < len(lines) and (not lines[j].strip() or len(lines[j]) - len(lines[j].lstrip()) > ind): j += 1
            spans.append((m.group(2), off[k], off[j]))
    return text, spans

def words(s):
    w = set()
    for t in re.findall(r"[A-Za-z][A-Za-z0-9_]*", s):
        for p in re.split(r"_|(?<=[a-z])(?=[A-Z])", t):
            if len(p) > 2: w.add(p.lower())
    return w

def test_bodies(log):
    """Source of the failing tests: Rust test fns named in the log, or test_task.py."""
    out = []
    if os.path.exists("test_task.py"): out.append(open("test_task.py").read())
    names = {n.split("::")[-1] for n in re.findall(r"([\w:]+) --- FAILED", log)}
    for f in sources():
        if not f.endswith(".rs"): continue
        text, _ = functions(f)
        for n in names:
            for m in re.finditer(r"fn\s+" + re.escape(n) + r"\s*\(", text):
                i = text.find("{", m.end()); depth, j = 1, i + 1
                while j < len(text) and depth:
                    depth += {"{": 1, "}": -1}.get(text[j], 0); j += 1
                out.append(text[m.start():j])
    return "\n".join(out)

def rank(log):
    tb = test_bodies(log)
    failing = " ".join(re.findall(r"([\w:]+) --- FAILED", log))
    want = words(PROBLEM) | words(failing)
    calls = set(re.findall(r"\b([A-Za-z_]\w*)\s*\(", tb)) | set(re.findall(r"\.([A-Za-z_]\w*)\b", tb)) | set(re.findall(r"import ([\w, ]+)", tb)[0].replace(" ", "").split(",") if "import" in tb else [])
    frames = set(re.findall(r'File "(?!.*test_task)[^"]*", line \d+, in (\w+)', log))
    allf, byname = [], {}
    for f in sources():
        text, spans = functions(f)
        for (n, s, e) in spans:
            allf.append((f, n, s, e, text[s:e])); byname.setdefault(n, []).append(len(allf) - 1)
    score = {}
    for k, (f, n, s, e, body) in enumerate(allf):
        nw = words(n)
        sc = 3 * len(nw & want) + sum(1 for x in nw for y in want if x != y and (x.startswith(y) or y.startswith(x))) + 0.1 * len(words(body) & want)
        if n in calls: sc += 4
        if n in frames: sc += 6
        # Writers of a field the failing tests read (`sh.line_no`) are on the path.
        if any(re.search(r"\bself\." + re.escape(c) + r"\s*[-+*]?=(?!=)", body) for c in calls if not c.startswith("assert")): sc += 4
        if sc > 0: score[k] = sc
    # One level of callees inherits most of its caller's score.
    for k, sc in sorted(score.items(), key=lambda x: -x[1])[:6]:
        for c in set(re.findall(r"\b([A-Za-z_]\w*)\b", allf[k][4][len(allf[k][1]) + 4:])):
            for j in byname.get(c, []):
                if j != k: score[j] = max(score.get(j, 0), sc - 0.5)
    ks = sorted(score, key=lambda k: (-score[k], allf[k][0], allf[k][2]))
    top = ks[:6]
    # Then every other function in the files of the top three, in file order.
    files = [allf[k][0] for k in top[:3]]
    rest = [k for k in range(len(allf)) if allf[k][0] in files and k not in top]
    # Then every remaining function of the crate, by score, so nothing is out of reach.
    rest2 = sorted((k for k in range(len(allf)) if k not in top and k not in rest), key=lambda k: (-score.get(k, 0), allf[k][0], allf[k][2]))
    return [(score.get(k, 0), allf[k][0], allf[k][1], allf[k][2], allf[k][3]) for k in top + rest + rest2]

# G1 candidates come from the pattern engine (`rce repair candidates`):
# TBar's 15 fix-pattern categories as guarded rewrites on the tree-sitter
# syntax tree. The tests decide which candidate stays.
def rce_bin():
    for c in (os.environ.get("RCE_BIN"), os.path.join(os.environ.get("RCE_ROOT", ""), "rce"),
              os.path.join(os.environ.get("RCE_ROOT", ""), "../../target/release/rce")):
        if c and os.path.isfile(c) and os.access(c, os.X_OK): return c
    return "rce"

def ctx_literals():
    t = open("test_task.py").read() if os.path.exists("test_task.py") else ""
    return sorted(set(re.findall(r"\b\d+\b", t)), key=int)

CACHE = {}
def engine(f, s, e):
    """Candidates for str span [s, e) of f, as (tier, byte start, byte end, bytes, pattern)."""
    key = (f, s, e)
    if key in CACHE: return CACHE[key]
    text = open(f, encoding="utf-8").read()
    lo, hi = len(text[:s].encode()), len(text[:e].encode())
    cmd = [rce_bin(), "repair", "candidates", f, str(lo), str(hi)]
    for l in ctx_literals(): cmd += ["--lit", l]
    p = subprocess.run(cmd, capture_output=True, text=True)
    out = [(c["tier"], c["start"], c["end"], c["text"].encode(), c["pattern"]) for c in json.loads(p.stdout or "[]")] if p.returncode == 0 else []
    CACHE[key] = out
    return out

def write(f, text): open(f, "w", encoding="utf-8").write(text)

def signature(log):
    if "could not compile" in log or "SyntaxError" in log or "IndentationError" in log: return None
    fails = sorted(set(re.findall(r"([\w:]+) --- FAILED", log)))
    if fails: return " ".join(fails)
    errs = [l for l in log.splitlines() if re.match(r"\w*(Error|Exception)\b", l)]
    return errs[-1] if errs else log[-200:]

SENSITIVE = []

def try_text(f, text, new, base_sig, fn):
    write(f, new)
    ok, log = run_tests()
    if not ok:
        if signature(log) not in (None, base_sig) and fn[:3] not in [(x[1], x[2], x[3]) for x in SENSITIVE]:
            SENSITIVE.append((0,) + fn)
        write(f, text)
    return ok

def g1(cands, base_sig):
    tried, singles = set(), []
    R["patterns"] = {}
    for group, tier in [(g, t) for g in (cands[:8], cands[8:]) for t in (1, 2, 3)]:
        for (_, f, n, s, e) in group:
            raw = open(f, "rb").read()
            text = raw.decode("utf-8")
            for (t, a, b, rep, pat) in engine(f, s, e):
                if t != tier: continue
                new = raw[:a] + rep + raw[b:]
                if new in tried: continue
                tried.add(new)
                if R["rule_tries"] >= MAX_RULES: return False
                R["rule_tries"] += 1
                R["patterns"][pat] = R["patterns"].get(pat, 0) + 1
                if tier == 1 and len(singles) < 40: singles.append((f, n, s, e, a, b, rep, pat))
                if try_text(f, text, new.decode("utf-8", "replace"), base_sig, (f, n, s, e)):
                    R["edit"] = {"file": f, "function": n, "tier": tier, "pattern": pat, "from": raw[a:b].decode(), "to": rep.decode()}; return True
    # Two-site: pairs of tier-1 edits in the same function.
    for i in range(len(singles)):
        for j in range(i + 1, len(singles)):
            (f, n, s, e, a1, b1, r1, p1), (f2, _, s2, _, a2, b2, r2, p2) = singles[i], singles[j]
            if (f, s) != (f2, s2) or b1 > a2: continue
            if R["rule_tries"] >= MAX_RULES + MAX_PAIRS: return False
            raw = open(f, "rb").read()
            new = raw[:a1] + r1 + raw[b1:a2] + r2 + raw[b2:]
            R["rule_tries"] += 1; R["pair_tries"] = R.get("pair_tries", 0) + 1
            if try_text(f, raw.decode(), new.decode("utf-8", "replace"), base_sig, (f, n, s, e)):
                R["edit"] = {"file": f, "function": n, "tier": "two-site", "pattern": f"{p1}+{p2}", "edits": [[raw[a1:b1].decode(), r1.decode()], [raw[a2:b2].decode(), r2.decode()]]}; return True
    return False

def g2(cands, log):
    for (_, f, n, s, e) in cands:
        if R["llm_calls"] >= MAX_LLM: return False
        text = open(f, encoding="utf-8").read(); body = text[s:e]
        lang = "rust" if f.endswith(".rs") else "python"
        prompt = (f"Fix the bug. Problem: {PROBLEM}\n\nFailing test output (tail):\n{log[-1200:]}\n\n"
                  f"The function `{n}` in {f} may hold the bug:\n```{lang}\n{body}```\n"
                  f"Reply with the complete corrected function in one ```{lang} block. Change as little as possible.")
        req = {"messages": [{"role": "user", "content": prompt}], "temperature": 0, "seed": 0, "max_tokens": 1500, "cache_prompt": False, "id_slot": 0}
        R["llm_calls"] += 1
        try:
            r = urllib.request.urlopen(urllib.request.Request(URL, json.dumps(req).encode(), {"Content-Type": "application/json"}), timeout=900)
            reply = json.load(r)["choices"][0]["message"]["content"]
        except Exception as ex:
            R.setdefault("llm_errors", []).append(str(ex)); continue
        m = re.search(r"```[a-z]*\n(.*?)```", reply, re.S)
        if not m: continue
        code = m.group(1)
        if not code.endswith("\n"): code += "\n"
        ind = len(body) - len(body.lstrip(" "))
        if ind and not code.startswith(" "): code = "".join(" " * ind + l if l.strip() else l for l in code.splitlines(True))
        if body.endswith("\n\n") and not code.endswith("\n\n"): code += "\n"
        write(f, text[:s] + code + text[e:])
        ok, _ = run_tests()
        if ok:
            R["edit"] = {"file": f, "function": n, "llm": True}; return True
        write(f, text)
    return False

def main():
    t0 = time.time()
    ok, log = run_tests()
    if ok: R["gear"] = "already-passing"
    else:
        cands = rank(log); R["ranked"] = [f"{c[1]}::{c[2]}" for c in cands]
        R["ranked"] = R["ranked"][:6]
        if g1(cands, signature(log)): R["gear"] = "G1-rules"
        else:
            # Mutation sensitivity: functions whose mutants changed the
            # failure are on the failing path; the model sees them first.
            R["sensitive"] = [f"{c[1]}::{c[2]}" for c in SENSITIVE]
            seen = {(c[1], c[3]) for c in SENSITIVE}
            order = SENSITIVE + [c for c in cands if (c[1], c[3]) not in seen]
            R["gear"] = "G2-local-llm" if g2(order, log) else "unresolved"
    R["seconds"] = round(time.time() - t0, 2)
    json.dump(R, open("../gears.json", "w"), indent=1)
    sys.exit(0 if R["gear"] != "unresolved" else 1)

main()
