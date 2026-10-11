#!/usr/bin/env python3
"""Ladder L1 with full-file context: ManySStuBs4J tasks with the buggy file fetched at the fix's parent commit
(raw.githubusercontent.com/<owner>/<repo>/<parentSHA>/<path>), cached gzip under CACHE.
Usage: l1_fullfile.py fetch LO HI | run OUT.jsonl LO HI [--jobs J]   (LO/HI: shuffle positions, PREREG order)
Validity (rule, before running): the fetched file's bug line must equal the hunk's bug line (whitespace ignored).
Gate: the patched file is token-identical to the file with the bug line replaced by the developer's fixed line."""
import json, os, re, sys, gzip, hashlib, subprocess, urllib.request, random
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import l1_sstubs as L
RCE = os.environ.get("RCE", "/workspace/rce-work/build3/target/release/rce")
CACHE = os.environ.get("L1F_CACHE", "/workspace/ladder-out/l1f-cache")
WD = os.environ.get("LADDER_WD", "/tmp/ladder-wd")
NORM = lambda b: re.sub(rb"\s+", b"", b)
def ordered():
    d = json.load(open(os.environ.get("SSTUBS", "/workspace/ladder-out/sstubsLarge.json")))
    pos = json.load(open("/workspace/ladder-out/manysstubs-pos.json"))
    out = {}
    for x in d:
        i = hashlib.sha1((x["fixCommitSHA1"] + x["bugFilePath"] + str(x["bugLineNum"])).encode()).hexdigest()[:16]
        if i in pos and i not in out: out[i] = (pos[i], x)
    return sorted(out.items(), key=lambda kv: kv[1][0])
def url(x):
    own, _, repo = x["projectName"].partition(".")
    return f"https://raw.githubusercontent.com/{own}/{repo}/{x['fixCommitParentSHA1']}/{x['bugFilePath']}"
def fetch1(item):
    i, (p, x) = item; f = os.path.join(CACHE, i + ".gz")
    if os.path.exists(f): return 1
    try:
        b = urllib.request.urlopen(url(x), timeout=30).read()
        open(f, "wb").write(gzip.compress(b)); return 1
    except Exception: open(f + ".miss", "w").close(); return 0
def run(item):
    i, (p, x) = item
    rec = {"id": i, "pos": p, "rung": "L1", "src": "ManySStuBs4J-2.0+parent-file", "project": x["projectName"], "bugType": x["bugType"],
           "llm_calls": 0, "solved": False, "valid": False, "gear": None, "rank": None, "pattern": None, "n_cands": 0, "cpu_s": 0.0}
    f = os.path.join(CACHE, i + ".gz")
    if not os.path.exists(f): rec["valid"] = None; return rec
    src = gzip.decompress(open(f, "rb").read()).decode("utf-8", "replace")
    h = L.hunk_at(x["fixPatch"], x["bugLineNum"])
    if not h: return rec
    hb, ha = h[0].split("\n"), h[1].split("\n"); k = h[2]; ln = x["bugLineNum"]
    lines = src.split("\n")
    if not (0 < ln <= len(lines)) or len(hb) != len(ha) or NORM(lines[ln - 1].encode()) != NORM(hb[k - 1].encode()): return rec
    rec["valid"] = True
    tgt = list(lines); tgt[ln - 1] = ha[k - 1]
    d = os.path.join(WD, f"l1f{os.getpid()}"); os.makedirs(d, exist_ok=True)
    fn = os.path.join(d, os.path.basename(x["bugFilePath"])); open(fn, "w").write(src)
    c0 = os.times(); pr = subprocess.run([RCE, "repair", "g0", fn, str(ln), "--lang", "java"], capture_output=True, text=True); c1 = os.times()
    rec["cpu_s"] = round((c1.children_user - c0.children_user) + (c1.children_system - c0.children_system), 4)
    mb, ob = src.encode(), "\n".join(tgt).encode(); dl = len(ob) - len(mb)
    ls0 = len("\n".join(lines[:ln - 1]).encode()) + (1 if ln > 1 else 0); le0 = ls0 + len(lines[ln - 1].encode())
    try: locs = json.loads(pr.stdout or "[]")
    except Exception: locs = []
    n = 0
    for loc in locs:
        for c in loc["cands"]:
            n += 1; a, b = min(c["start"], ls0), max(c["end"], le0)
            if NORM(mb[a:c["start"]] + c["text"].encode() + mb[c["end"]:b]) == NORM(ob[a:b + dl]):
                rec.update(solved=True, gear="G0", rank=n, pattern=c["pattern"]); break
        if rec["solved"]: break
    rec["n_cands"] = n
    return rec
if __name__ == "__main__":
    os.makedirs(CACHE, exist_ok=True)
    if sys.argv[1] == "fetch":
        lo, hi = int(sys.argv[2]), int(sys.argv[3]); items = ordered()[lo:hi]
        with ThreadPoolExecutor(16) as ex: got = sum(ex.map(fetch1, items))
        print("fetched", got, "of", len(items))
    else:
        out, lo, hi = sys.argv[2], int(sys.argv[3]), int(sys.argv[4]); a = sys.argv[5:]
        jobs = int(a[a.index("--jobs") + 1]) if "--jobs" in a else 4
        done = set(json.loads(l)["id"] for l in open(out)) if os.path.exists(out) else set()
        items = [it for it in ordered()[lo:hi] if it[0] not in done]
        with open(out, "a") as fo, ProcessPoolExecutor(jobs) as ex:
            for r in ex.map(run, items, chunksize=16): fo.write(json.dumps(r) + "\n")
