#!/usr/bin/env python3
"""Defects4J harness for the G1 pattern engine.

One bug per call: d4j_repair.py PROJECT BUG OUTDIR.

Protocol:
  1. defects4j checkout of the buggy version, then defects4j compile.
  2. Localization is perfect at line level: the buggy-side lines of the
     developer patch (TBar's perfect-localization setting, Section 4).
  3. Candidates come from `rce repair candidates` over those lines.
  4. Each candidate is compiled with javac (the edited file only) and run
     against the triggering tests. Survivors run the relevant test classes.
     Plausible: no failure beyond those the buggy version already had,
     and every trigger passes.
  5. Correct: the patched file equals the developer-fixed file after
     whitespace is removed. This is syntactic identity, a lower bound on
     semantic correctness.
  6. est_j: child CPU seconds (test JVM included) times EST_W_PER_CPU,
     an estimate, not a measurement; the box has no RAPL.
"""
import json, os, re, resource, subprocess, sys, time

EST_W_PER_CPU = 10.0
MAX_CANDS = int(os.environ.get("D4J_MAX_CANDS", "150"))
HERE = os.path.dirname(os.path.abspath(__file__))
RCE = os.environ.get("RCE_BIN", os.path.join(HERE, "../../../../target/release/rce"))
D4J = os.environ.get("D4J_HOME", "/workspace/d4j")
JDK = os.environ.get("D4J_JDK", "/workspace/d4j-tools/jdk-11.0.32.1+1")
ENV = dict(os.environ, PATH=f"{JDK}/bin:{D4J}/framework/bin:" + os.environ["PATH"], JAVA_HOME=JDK)

def log(*a): print(f"[{time.strftime('%H:%M:%S')}]", *a, file=sys.stderr, flush=True)

def sh(cmd, cwd=None, timeout=600):
    log("sh", " ".join(cmd[:3]))
    try:
        p = subprocess.run(cmd, cwd=cwd, env=ENV, capture_output=True, text=True, timeout=timeout, errors="replace")
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"

def export(w, prop):
    return sh(["defects4j", "export", "-p", prop], cwd=w)[1].strip()

def changed_lines(patch):
    """Buggy-side (b side, '+') line numbers per file; insertion points too."""
    out, f, ln = {}, None, 0
    for l in patch.splitlines():
        if l.startswith("+++ "): f = l[6:] if l.startswith("+++ b/") else l[4:]; continue
        if l.startswith("--- "): continue
        m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", l)
        if m: ln = int(m.group(1)); continue
        if f is None: continue
        if l.startswith("+"): out.setdefault(f, set()).add(ln); ln += 1
        elif l.startswith("-"): out.setdefault(f, set()).update({max(1, ln - 1), ln})
        else: ln += 1
    return out

SRV = None

def norm(s): return re.sub(r"\s+", "", s)

def main(proj, bug, outdir):
    t0 = time.time()
    os.makedirs(outdir, exist_ok=True)
    w = os.path.join(outdir, "work")
    rec = {"bug": f"{proj}-{bug}", "plausible": False, "correct": False, "tries": 0, "compiled": 0, "patterns": {}}
    def done(**kw):
        rec.update(kw)
        # Reap the test JVM first so its CPU time lands in RUSAGE_CHILDREN.
        if SRV and SRV.p is not None: SRV.p.stdin.close(); SRV.p.wait()
        ru = resource.getrusage(resource.RUSAGE_CHILDREN)
        rec["cpu_s"] = round(ru.ru_utime + ru.ru_stime, 2)
        rec["est_j"] = round(rec["cpu_s"] * EST_W_PER_CPU, 1)
        rec["wall_s"] = round(time.time() - t0, 1)
        json.dump(rec, open(os.path.join(outdir, "result.json"), "w"), indent=1)
        print(json.dumps(rec)); sys.exit(0)
    if sh(["defects4j", "checkout", "-p", proj, "-v", f"{bug}b", "-w", w])[0] != 0: done(error="checkout")
    if sh(["defects4j", "compile"], cwd=w, timeout=900)[0] != 0: done(error="compile")
    rec["setup_s"] = round(time.time() - t0, 1)
    src_dir, bin_dir = export(w, "dir.src.classes"), export(w, "dir.bin.classes")
    cp = export(w, "cp.test")
    trig = [t for t in export(w, "tests.trigger").split("\n") if t]
    rel = [t for t in export(w, "tests.relevant").split("\n") if t]
    patch = open(f"{D4J}/framework/projects/{proj}/patches/{bug}.src.patch", errors="replace").read()
    lines = changed_lines(patch)
    rdir = os.path.join(outdir, "runner"); os.makedirs(rdir, exist_ok=True)
    sh(["javac", "-nowarn", "-cp", cp, "-d", rdir, os.path.join(HERE, "RceRunner.java")])
    global SRV
    srv = SRV = Server(rdir, w)
    cpa = ":".join(e if os.path.isabs(e) else os.path.join(w, e) for e in cp.split(":"))
    def run(tests, timeout=300):
        t = time.time(); log("test", len(tests)); r = srv.test(cpa, tests, timeout)
        rec["test_s"] = round(rec.get("test_s", 0) + time.time() - t, 1); return r
    base_rel = run(rel, 900)
    if base_rel is None: done(error="baseline tests")
    tt = time.time(); base_trig = run(trig)
    # A mutant that loops forever is cut off at 10x the buggy run (min 15 s).
    trig_to = max(15.0, 10 * (time.time() - tt)); rec["trigger_timeout_s"] = round(trig_to, 1)
    rec["baseline_trigger_failures"] = len(base_trig or [])
    # Developer-fixed text, by reverse-applying the patch to a copy.
    fixed = {}
    for f in lines:
        p = os.path.join(w, f)
        if not os.path.exists(p): continue
        r = subprocess.run(["patch", "-R", "-s", "-o", "-", p], input=patch_for(patch, f), capture_output=True, text=True, errors="replace")
        if r.returncode == 0: fixed[f] = r.stdout
    jv = {"Chart": "1.8", "Closure": "1.8", "Lang": "1.8", "Math": "1.8", "Mockito": "1.8", "Time": "1.8"}.get(proj, "1.8")
    seen = set()
    for f, ls in lines.items():
        p = os.path.join(w, f)
        if not f.endswith(".java") or not os.path.exists(p): continue
        raw = open(p, "rb").read()
        starts = [0] + [i + 1 for i, b in enumerate(raw) if b == 10]
        lo = starts[min(ls) - 1] if min(ls) - 1 < len(starts) else len(raw)
        hi = starts[max(ls)] if max(ls) < len(starts) else len(raw)
        enc = "ISO-8859-1"
        r = subprocess.run([RCE, "repair", "candidates", p, str(lo), str(hi)], capture_output=True, text=True)
        cands = json.loads(r.stdout or "[]")
        rec.setdefault("candidates", 0); rec["candidates"] += len(cands)
        for c in cands:
            if rec["tries"] >= MAX_CANDS: break
            new = raw[:c["start"]] + c["text"].encode("latin-1", "replace") + raw[c["end"]:]
            if new in seen: continue
            seen.add(new); rec["tries"] += 1
            rec["patterns"][c["pattern"]] = rec["patterns"].get(c["pattern"], 0) + 1
            open(p, "wb").write(new)
            ok = srv.compile(os.path.join(w, bin_dir), cpa, p)
            if ok:
                rec["compiled"] += 1
                ft = run(trig, trig_to)
                if ft is not None and not ft:
                    fr = run(rel, 900)
                    if fr is not None and fr <= (base_rel - set(trig)):
                        text = new.decode("latin-1")
                        correct = f in fixed and norm(text) == norm(fixed[f])
                        diff = subprocess.run(["diff", "-u", "-", p], input=raw.decode("latin-1"), capture_output=True, text=True).stdout
                        open(os.path.join(outdir, "plausible.patch"), "w").write(diff)
                        open(p, "wb").write(raw)
                        done(plausible=True, correct=correct, pattern=c["pattern"], tier=c["tier"], edit={"file": f, "from": raw[c["start"]:c["end"]].decode("latin-1"), "to": c["text"]})
            open(p, "wb").write(raw)
        srv.compile(os.path.join(w, bin_dir), cpa, p)
    done()

class Server:
    """One JVM per bug (RceRunner): in-process javac and JUnit in a fresh
    class loader per run. A hung test kills the JVM; the next call restarts it."""
    def __init__(self, rdir, cwd): self.rdir, self.cwd, self.p = rdir, cwd, None
    def start(self):
        self.p = subprocess.Popen(["java", "-Xmx2g", "-cp", self.rdir, "RceRunner"], cwd=self.cwd, env=ENV, stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)
        self.buf = b""
    def ask(self, line, timeout, until):
        # Raw fd reads with our own buffer: select() cannot see lines already
        # sitting in a Python file buffer, which hung the earlier version.
        import select
        if self.p is None or self.p.poll() is not None: self.start()
        self.p.stdin.write((line + "\n").encode("utf-8", "replace")); self.p.stdin.flush()
        out, end, fd = [], time.time() + timeout, self.p.stdout.fileno()
        while True:
            while b"\n" in self.buf:
                l, self.buf = self.buf.split(b"\n", 1)
                l = l.decode("utf-8", "replace"); out.append(l)
                if until(l): return out
            r, _, _ = select.select([fd], [], [], max(0, end - time.time()))
            if not r: self.p.kill(); self.p.wait(); self.p = None; return None
            chunk = os.read(fd, 65536)
            if not chunk: self.p.wait(); self.p = None; return None
            self.buf += chunk
    def compile(self, bindir, cp, f):
        o = self.ask(f"COMPILE {bindir} {bindir}:{cp} {f}", 300, lambda l: l.strip() in ("OK", "ERR"))
        return o is not None and o[-1] == "OK"
    def test(self, cp, tests, timeout):
        o = self.ask("TEST " + cp + " " + " ".join(tests), timeout, lambda l: l.startswith("DONE"))
        if o is None or o[-1] == "DONE -1": return None
        return set(l[5:] for l in o if l.startswith("FAIL "))

def patch_for(patch, f):
    """The part of a multi-file patch that touches f."""
    out, keep = [], False
    for l in patch.splitlines(keepends=True):
        if l.startswith("diff --git"): keep = f in l
        if keep: out.append(l)
    return "".join(out) or patch

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
