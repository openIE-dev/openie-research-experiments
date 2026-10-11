#!/usr/bin/env python3
"""Defects4J harness for G1-J, the TBar template port (src/repair/tbar.rs).

One bug per call: d4j_tbar.py PROJECT BUG OUTDIR.  No model is called.

Protocol (TBar PerfectFL, Liu et al. ISSTA 2019, with two stated changes):
  1. defects4j checkout + compile of the buggy version.
  2. Localization: TBar's own BugPositions.txt, in file order, each range
     expanded to its lines in order. This is the exact input TBar used.
  3. Candidates: `rce repair tbar FILE LINE --src SRC` per line, in the
     order the port emits them (TBar's template dispatch order). Whole-file
     duplicates are skipped; at most 10000 tried, TBar's own cap, and a
     wall-clock cap of D4J_WALL_S seconds (stated in the report).
  4. A candidate is compiled (javac, edited file only), run on the trigger
     tests, then on the relevant tests. Plausible: every trigger passes and
     no relevant test fails that passed on the buggy version.
  5. Multi-location (change 1): when a candidate makes a strict subset of
     the triggers fail and breaks nothing else, it is KEPT and the search
     moves to the next position on top of it. TBar instead restores the file
     and counts a bug fixed once separate partial patches add up (Math-4);
     we only count a bug when one combined patch passes.
  6. Correct (change 2, replacing whitespace identity): every file of the
     developer patch has the same normal form (rce repair ast-eq: tokens
     of the tree-sitter parse, comments, layout, redundant parentheses and
     one-statement braces dropped) in the patched and developer-fixed
     version. AST-equal patches are correct; every other plausible patch is
     reviewed by hand (REVIEW.md).
"""
import json, os, re, resource, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import d4j_repair as R
from d4j_repair import sh, export, log, Server, patch_for, RCE, D4J

MAX_TRIES = int(os.environ.get("D4J_MAX_TRIES", "10000"))
WALL = float(os.environ.get("D4J_WALL_S", "1800"))
POS = os.environ.get("TBAR_POSITIONS", "/workspace/TBar/BugPositions.txt")

def positions(proj, bug, patch):
    out = []
    for l in open(POS):
        p = l.strip().split("@")
        if len(p) != 3 or p[0] != f"{proj}_{bug}": continue
        ls = []
        for r in p[2].split(","):
            a, _, b = r.partition("-"); ls += list(range(int(a), int(b or a) + 1))
        out.append((p[1], ls))
    if not out:  # fallback: buggy-side lines of the developer patch
        out = [(f, sorted(s)) for f, s in R.changed_lines(patch).items()]
    return out

def ast_eq(a_text, b_text, tmp):
    pa, pb = tmp + ".a.java", tmp + ".b.java"
    open(pa, "w", encoding="utf-8", newline="").write(a_text); open(pb, "w", encoding="utf-8", newline="").write(b_text)
    r = subprocess.run([RCE, "repair", "ast-eq", pa, pb], capture_output=True, text=True)
    return r.returncode == 0

def main(proj, bug, outdir):
    t0 = time.time(); outdir = os.path.abspath(outdir); os.makedirs(outdir, exist_ok=True)
    w = os.path.join(outdir, "work")
    rec = {"bug": f"{proj}-{bug}", "engine": "G1-J (TBar port)", "llm_calls": 0, "plausible": False, "correct": False,
           "partial": False, "tries": 0, "compiled": 0, "patterns": {}, "kept": []}
    def done(**kw):
        rec.update(kw)
        if R.SRV and R.SRV.p is not None: R.SRV.p.stdin.close(); R.SRV.p.wait()
        ru = resource.getrusage(resource.RUSAGE_CHILDREN)
        rec["cpu_s"] = round(ru.ru_utime + ru.ru_stime, 2); rec["est_j"] = round(rec["cpu_s"] * R.EST_W_PER_CPU, 1)
        rec["wall_s"] = round(time.time() - t0, 1)
        json.dump(rec, open(os.path.join(outdir, "result.json"), "w"), indent=1); print(json.dumps(rec)); sys.exit(0)
    if sh(["defects4j", "checkout", "-p", proj, "-v", f"{bug}b", "-w", w])[0] != 0: done(error="checkout")
    if sh(["defects4j", "compile"], cwd=w, timeout=900)[0] != 0: done(error="compile")
    rec["setup_s"] = round(time.time() - t0, 1)
    src_dir, bin_dir = export(w, "dir.src.classes"), export(w, "dir.bin.classes")
    cp = export(w, "cp.test")
    trig = [t for t in export(w, "tests.trigger").split("\n") if t]
    rel = [t for t in export(w, "tests.relevant").split("\n") if t]
    patch = open(f"{D4J}/framework/projects/{proj}/patches/{bug}.src.patch", "rb").read().decode("latin-1")
    pos = positions(proj, bug, patch); rec["positions"] = [[f, ls] for f, ls in pos]
    rdir = os.path.join(outdir, "runner"); os.makedirs(rdir, exist_ok=True)
    sh(["javac", "-nowarn", "-cp", cp, "-d", rdir, os.path.join(R.HERE, "RceRunner.java")])
    srv = R.SRV = Server(rdir, w)
    cpa = ":".join(e if os.path.isabs(e) else os.path.join(w, e) for e in cp.split(":"))
    def run(tests, timeout=300):
        t = time.time(); r = srv.test(cpa, tests, timeout)
        rec["test_s"] = round(rec.get("test_s", 0) + time.time() - t, 1); return r
    base_rel = run(rel, 900)
    if base_rel is None: done(error="baseline tests")
    tt = time.time(); base_trig = run(trig)
    trig_to = max(15.0, 10 * (time.time() - tt)); rec["trigger_timeout_s"] = round(trig_to, 1)
    cur_fail = set(base_trig or trig); rec["baseline_trigger_failures"] = len(cur_fail)
    # Developer-fixed text of every file the patch touches.
    pfiles = sorted(set(re.findall(r"^\+\+\+ b/(\S+)", patch, re.M)))
    fixed = {}
    for f in pfiles:
        p = os.path.join(w, f)
        if not os.path.exists(p): continue
        r = subprocess.run(["patch", "-R", "-s", "-r", "-", "-o", "-", p], input=patch_for(patch, f).encode("latin-1"), capture_output=True)
        if r.returncode == 0: fixed[f] = r.stdout.decode("latin-1")
        else: log("fixed version of", f, "not derived:", r.stderr[:200])
    orig = {f: open(os.path.join(w, f), "rb").read() for f in set(pfiles) | {f for f, _ in pos} if os.path.exists(os.path.join(w, f))}
    seen = set(); tmp = os.path.join(outdir, "cand")
    def finish(plausible, last=None):
        diff = ""
        for f, raw in orig.items():
            now = open(os.path.join(w, f), "rb").read()
            if now != raw:
                diff += subprocess.run(["diff", "-u", "--label", "a/" + f, "--label", "b/" + f, "-", os.path.join(w, f)], input=raw.decode("latin-1"), capture_output=True, text=True, errors="replace").stdout
        if diff: open(os.path.join(outdir, "plausible.patch" if plausible else "partial.patch"), "w").write(diff)
        correct = False
        if plausible and fixed:
            correct = all(ast_eq(open(os.path.join(w, f), "rb").read().decode("latin-1"), fixed[f], tmp) for f in fixed)
        for f, raw in orig.items(): open(os.path.join(w, f), "wb").write(raw)
        done(plausible=plausible, correct=correct, ast_equal=correct, partial=bool(rec["kept"]) and not plausible, fixed_derived=sorted(fixed), patch_files=pfiles,
             pattern=last and last["pattern"])
    stop = False
    for f, lines in pos:
        p = os.path.join(w, f)
        if not f.endswith(".java") or not os.path.exists(p): continue
        shift = []  # (line, delta) of kept edits in this file
        for ln0 in lines:
            if stop: break
            ln = ln0 + sum(d for l, d in shift if l < ln0)
            raw = open(p, "rb").read(); text = raw.decode("latin-1"); u8 = text.encode("utf-8")
            open(tmp + ".java", "wb").write(u8)
            r = subprocess.run([RCE, "repair", "tbar", tmp + ".java", str(ln), "--src", os.path.join(w, src_dir)], capture_output=True, text=True)
            try: sites = json.loads(r.stdout or "[]")
            except ValueError: sites = []
            rec["candidates"] = rec.get("candidates", 0) + sum(len(s["cands"]) for s in sites)
            moved = False
            for s in sites:
                if moved or stop: break
                for c in s["cands"]:
                    if rec["tries"] >= MAX_TRIES or time.time() - t0 > WALL: stop = True; rec["capped"] = "tries" if rec["tries"] >= MAX_TRIES else "wall"; break
                    try: new = (u8[:c["start"]] + c["text"].encode("utf-8") + u8[c["end"]:]).decode("utf-8").encode("latin-1")
                    except (UnicodeError, ValueError): continue
                    if new == raw or new in seen: continue
                    seen.add(new); rec["tries"] += 1
                    rec["patterns"][c["pattern"]] = rec["patterns"].get(c["pattern"], 0) + 1
                    open(p, "wb").write(new)
                    if srv.compile(os.path.join(w, bin_dir), cpa, p):
                        rec["compiled"] += 1
                        ft = run(trig, trig_to)
                        if ft is not None and ft < cur_fail:
                            fr = run(rel, 900)
                            if fr is not None and (fr - set(trig)) <= base_rel:
                                edit = {"file": f, "line": ln0, "pattern": c["pattern"], "from": u8[c["start"]:c["end"]].decode("utf-8", "replace"), "to": c["text"]}
                                rec["kept"].append(edit)
                                if not ft: finish(True, edit)
                                # Partial fix: keep it, move to the next position.
                                cur_fail = ft; moved = True
                                shift.append((ln0, new.count(b"\n") - raw.count(b"\n")))
                                break
                    open(p, "wb").write(raw)
            if not moved: srv.compile(os.path.join(w, bin_dir), cpa, p)
        if stop: break
    finish(False)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
