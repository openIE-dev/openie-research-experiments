#!/usr/bin/env python3
"""Ladder L1: real single-statement bugs (ManySStuBs4J 2.0 sstubsLarge, TSSB-3M), 0 model calls.
Usage: l1_sstubs.py manysstubs|tssb INPUT OUT.jsonl [--max N] [--jobs J]
Task: the before-side of the fix hunk (developer diff context, about 3 lines each side), the bug line given.
Gate: the patched hunk is token-identical (whitespace ignored) to the after-side of the developer fix.
Only the hunk is visible to RCE here (no full file): the corpus for G0-V is the hunk alone."""
import json, os, re, subprocess, sys, hashlib, random, gzip
from concurrent.futures import ProcessPoolExecutor
RCE = os.environ.get("RCE", "/workspace/rce-work/build3/target/release/rce")
WD = os.environ.get("LADDER_WD", "/tmp/ladder-wd")
VOCAB = int(os.environ.get("L1_VOCAB", "300"))
NORM = lambda b: re.sub(rb"\s+", b"", b)
def sstub_view(before, after, ln):
    """The single statement only: after-side = before-side with the bug line replaced by its fixed line
    (other edits of the same commit hunk are not part of the sstub). Needs equal line counts."""
    b, a = before.split("\n"), after.split("\n")
    if len(b) != len(a) or not (0 < ln <= len(b)): return before, after
    t = list(b); t[ln - 1] = a[ln - 1]; return before, "\n".join(t)
def hunk_at(patch, bugline):
    m = re.search(r"(?m)^@@ -(\d+)", patch); h = hunk(patch)
    if not h or not m: return h
    ln = bugline - int(m.group(1)) + 1
    if not (0 < ln <= len(h[0].split("\n"))): return h
    b, a = sstub_view(h[0], h[1], ln); return b, a, ln
def hunk(patch):
    """before text, after text, 1-based before-line of the first removed line; None unless one hunk."""
    hs = [h for h in re.split(r"(?m)^@@[^\n]*\n", patch)[1:]]
    if len(hs) != 1: return None
    b, a, first = [], [], None
    for l in hs[0].split("\n"):
        if l.startswith("\\"): continue
        if l.startswith("-"): b.append(l[1:]); first = first or len(b)
        elif l.startswith("+"): a.append(l[1:]); first = first or len(b) + 1
        elif l.startswith(" ") or l == "": b.append(l[1:]); a.append(l[1:])
    while b and a and b[-1] == "" and a[-1] == "": b.pop(); a.pop()
    return ("\n".join(b), "\n".join(a), first) if first else None
def run(t):
    tid, before, after, ln, lang, meta = t
    d = os.path.join(WD, f"l1w{os.getpid()}"); os.makedirs(d, exist_ok=True)
    f = os.path.join(d, "Frag." + ("py" if lang == "python" else "java")); open(f, "w").write(before)
    rec = dict(meta, id=tid, rung="L1", lang=lang, llm_calls=0, solved=False, gear=None, rank=None, pattern=None, n_cands=0, cpu_s=0.0, err=False)
    k = 0
    vf = os.path.join(WD, "vocab", hashlib.sha1(meta["project"].encode()).hexdigest()[:12])
    # G0 on the hunk; then G0 on the hunk cut to start at the bug line (leading context that does not parse,
    # e.g. the inside of a string concatenation, can swallow the line)
    bl, al = before.split("\n"), after.split("\n")
    views = [("G0", before, after, ln), ("G0-cut", "\n".join(bl[ln - 1:]), "\n".join(al[ln - 1:]), 1)]
    for gname, bt, at, l in views:
        open(f, "w").write(bt)
        cmd = [RCE, "repair", "g0", f, str(l), "--lang", lang] + (["--vocab", vf] if os.path.exists(vf) else [])
        c0 = os.times(); p = subprocess.run(cmd, capture_output=True, text=True); c1 = os.times()
        rec["cpu_s"] = round(rec["cpu_s"] + (c1.children_user - c0.children_user) + (c1.children_system - c0.children_system), 4)
        try: locs = json.loads(p.stdout or "[]")
        except Exception: locs = []; rec["err"] = True
        mb, target = bt.encode(), NORM(at.encode())
        for loc in locs:
            for c in loc["cands"]:
                k += 1
                if NORM(mb[:c["start"]] + c["text"].encode() + mb[c["end"]:]) == target:
                    rec.update(solved=True, gear=gname, rank=k, pattern=c["pattern"]); break
            if rec["solved"]: break
        if rec["solved"]: break
    rec["n_cands"] = k
    return rec
def tasks_manysstubs(path):
    for x in json.load(open(path)):
        h = hunk_at(x["fixPatch"], x["bugLineNum"])
        if not h: continue
        yield (hashlib.sha1((x["fixCommitSHA1"] + x["bugFilePath"] + str(x["bugLineNum"])).encode()).hexdigest()[:16], h[0], h[1], h[2], "java",
               {"src": "ManySStuBs4J-2.0/sstubsLarge", "project": x["projectName"], "bugType": x["bugType"]})
def tasks_tssb(path):
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rt") as fh:
        for l in fh:
            x = json.loads(l); h = hunk(x.get("diff", ""))
            if not h: continue
            yield (hashlib.sha1((x.get("commit_sha", "") + x.get("file", x.get("file_path", "")) + h[0][:200]).encode()).hexdigest()[:16], h[0], h[1], h[2], "python",
                   {"src": "TSSB-3M-1.0.0/" + os.path.basename(path), "project": x.get("project", ""), "bugType": x.get("sstub_pattern", "")})
def main():
    kind, inp, out = sys.argv[1:4]; a = sys.argv[4:]
    g = lambda k, d: type(d)(a[a.index(k) + 1]) if k in a else d
    mx, jobs, skip = g("--max", 10**9), g("--jobs", os.cpu_count()), g("--skip", 0)
    done = set(json.loads(l)["id"] for l in open(out)) if os.path.exists(out) else set()
    gen = tasks_manysstubs(inp) if kind == "manysstubs" else tasks_tssb(inp)
    ts, seen = [], set()
    for t in gen:
        if t[0] in seen: continue
        seen.add(t[0]); ts.append(t)
    # G0 index: per project, identifiers of the BEFORE side of every hunk (buggy code only, never a fix), by frequency
    import collections
    voc = collections.defaultdict(collections.Counter)
    for t in ts:
        for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", t[1]): voc[t[5]["project"]][w] += 1
    os.makedirs(os.path.join(WD, "vocab"), exist_ok=True)
    KW = set("if else for while return new class public private protected static final void int long boolean true false null this super try catch throw throws def and or not in is None True False import from self".split())
    for pj, c in voc.items():
        open(os.path.join(WD, "vocab", hashlib.sha1(pj.encode()).hexdigest()[:12]), "w").write("\n".join(w for w, _ in c.most_common(VOCAB) if w not in KW))
    ts.sort(key=lambda t: t[0]); random.Random(20261011).shuffle(ts)
    for i, t in enumerate(ts): t[5]["pos"] = i
    ts = [t for t in ts[skip:mx] if t[0] not in done]  # --skip 2000: TEST split only (PREREG splits)
    print(f"todo {len(ts)} done {len(done)}", file=sys.stderr, flush=True)
    with open(out, "a") as fo, ProcessPoolExecutor(jobs) as ex:
        for i, r in enumerate(ex.map(run, ts, chunksize=64)):
            fo.write(json.dumps(r) + "\n")
            if i % 5000 == 0: fo.flush(); print(i, file=sys.stderr, flush=True)
if __name__ == "__main__": main()
