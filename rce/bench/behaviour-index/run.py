#!/usr/bin/env python3
"""The behaviour-index measurement (PREREG.json in this directory).

    run.py --rce PATH/TO/rce --rce-root PATH/TO/rce-checkout --corpus DIR --out DIR

DIR (--corpus) is the output of `scripts/corpus.py` of the same rce commit
(forms.jsonl, negatives.jsonl). The script builds the pair populations,
computes the program hash (`rce hash`, last line) and the behaviour
fingerprint (`rce fingerprint`) of every program at each registered depth,
decides every pair with `rce equiv`, and writes results/pairs.jsonl,
results/collisions.jsonl, results/programs.jsonl and results/summary.json.
It is a pure function of the checkout, the corpus and the registered
constants below.
"""
import argparse, hashlib, json, subprocess, sys, time
from pathlib import Path

DEPTHS = [1, 2, 4, 8]
PRIMARY_DEPTH = 8
FUEL = 20000
PAIR_CAP = 200  # equiv calls per fingerprint bucket, first pairs in sorted order
HERE = Path(__file__).resolve().parent


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


class Rce:
    def __init__(self, exe):
        self.exe = exe

    def run(self, *a):
        t0 = time.perf_counter()
        r = subprocess.run([self.exe, *a], capture_output=True, text=True, timeout=600)
        return r, time.perf_counter() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rce", required=True)
    ap.add_argument("--rce-root", required=True)
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    rce = Rce(a.rce)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    work = out / ".work"
    work.mkdir(exist_ok=True)
    commit = subprocess.run(["git", "-C", a.rce_root, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()

    # ---- programs: one file per distinct source text
    progs = {}  # source sha -> {file, origin}

    def add(src, origin):
        h = sha(src)
        if h not in progs:
            f = work / f"{h[:16]}.rce"
            f.write_text(src, encoding="utf-8")
            progs[h] = {"file": str(f), "origins": [origin], "sha": h}
        elif origin not in progs[h]["origins"]:
            progs[h]["origins"].append(origin)
        return h

    forms = [json.loads(l) for l in open(Path(a.corpus) / "forms.jsonl")]
    negs = [json.loads(l) for l in open(Path(a.corpus) / "negatives.jsonl")]
    by_shape = {r["shape_hash"]: r for r in forms}
    pairs = []  # (set, a_sha, b_sha, note)
    for r in forms:
        pa = add(r["source"], "corpus")
        pb = add(r["nameless"], "t7-projection")
        pairs.append(("T7", pa, pb, r["path"]))
    for n in negs:
        if n.get("kind") != "mutant" or n.get("verdict") != "accept":
            continue
        parent = by_shape.get(n["parent_shape_hash"])
        if parent is None:
            continue
        pa = add(parent["source"], "corpus")
        pb = add(n["source"], "mutant:" + n.get("outcome", "?"))
        if pa == pb:
            continue
        s = {"accept_equivalent": "M-eq", "accept_behaviour_change": "M-change", "accept_same_shape": "M-same", "accept_no_examples": "M-noex"}.get(n.get("outcome"), "M-other")
        pairs.append((s, pa, pb, f"{n['path']} {n.get('operator')}"))
    for fa in sorted((HERE / "reshapings").glob("*_a.rce")):
        fb = fa.with_name(fa.name[:-6] + "_b.rce")
        pa = add(fa.read_text(), "reshaping")
        pb = add(fb.read_text(), "reshaping")
        pairs.append(("H", pa, pb, fa.name[:-6]))

    # ---- per program: admitted?, program hash, fingerprint per depth with cost
    for h, p in sorted(progs.items()):
        r, _ = rce.run("check", p["file"])
        p["admitted"] = r.returncode == 0
        r, _ = rce.run("hash", p["file"])
        p["program_hash"] = r.stdout.strip().splitlines()[-1].split()[0] if r.returncode == 0 and r.stdout.strip() else None
        p["fp"] = {}
        for d in DEPTHS:
            r, dt = rce.run("fingerprint", "--json", "--depth", str(d), "--fuel", str(FUEL), p["file"])
            if r.returncode == 0:
                j = json.loads(r.stdout)
                p["fp"][str(d)] = {"hash": j["fingerprint"], "states": j["states"], "alphabet": j["alphabet"], "s": round(dt, 5)}
            else:
                p["fp"][str(d)] = {"hash": None, "why": (r.stdout + r.stderr).strip()[:200], "s": round(dt, 5)}

    equiv_cache = {}

    def equiv(x, y):
        k = tuple(sorted((x, y)))
        if k not in equiv_cache:
            r, dt = rce.run("equiv", "--json", "--fuel", str(FUEL), progs[k[0]]["file"], progs[k[1]]["file"])
            try:
                j = json.loads(r.stdout)
                equiv_cache[k] = {"equivalent": j["equivalent"], "exact": j["exact"], "s": round(dt, 5)}
            except ValueError:
                equiv_cache[k] = {"equivalent": None, "why": (r.stdout + r.stderr).strip()[:200], "s": round(dt, 5)}
        return equiv_cache[k]

    # ---- pairs
    prow = []
    for s, x, y, note in pairs:
        px, py = progs[x], progs[y]
        e = equiv(x, y)
        row = {"set": s, "a": x, "b": y, "note": note, "equiv": e,
               "same_program_hash": px["program_hash"] is not None and px["program_hash"] == py["program_hash"],
               "fp": {}}
        for d in DEPTHS:
            fa, fb = px["fp"][str(d)]["hash"], py["fp"][str(d)]["hash"]
            row["fp"][str(d)] = None if fa is None or fb is None else fa == fb
        prow.append(row)

    # ---- false positives: every bucket of equal fingerprints over all programs
    coll = []
    fp_stats = {}
    for d in DEPTHS:
        buckets = {}
        for h, p in progs.items():
            f = p["fp"][str(d)]["hash"]
            if f is not None:
                buckets.setdefault(f, []).append(h)
        st = {"fingerprinted": sum(len(v) for v in buckets.values()), "buckets": len(buckets), "shared_buckets": 0,
              "pairs_in_buckets": 0, "pairs_checked": 0, "pairs_equivalent": 0, "pairs_different": 0, "pairs_undecided": 0,
              "pairs_different_with_distinct_program_hash": 0, "buckets_capped": 0}
        for f, hs in sorted(buckets.items()):
            if len(hs) < 2:
                continue
            st["shared_buckets"] += 1
            hs = sorted(hs)
            allp = [(hs[i], hs[j]) for i in range(len(hs)) for j in range(i + 1, len(hs))]
            st["pairs_in_buckets"] += len(allp)
            if len(allp) > PAIR_CAP:
                st["buckets_capped"] += 1
            for x, y in allp[:PAIR_CAP]:
                e = equiv(x, y)
                st["pairs_checked"] += 1
                if e["equivalent"] is True:
                    st["pairs_equivalent"] += 1
                elif e["equivalent"] is False:
                    st["pairs_different"] += 1
                    if progs[x]["program_hash"] != progs[y]["program_hash"]:
                        st["pairs_different_with_distinct_program_hash"] += 1
                    coll.append({"depth": d, "fingerprint": f, "a": x, "b": y, "equiv": e,
                                 "a_origins": progs[x]["origins"], "b_origins": progs[y]["origins"]})
                else:
                    st["pairs_undecided"] += 1
        fp_stats[str(d)] = st

    # ---- summary
    def med(xs):
        xs = sorted(xs)
        if not xs:
            return None
        q = lambda f: xs[min(len(xs) - 1, int(round(f * (len(xs) - 1))))]
        return {"n": len(xs), "median": q(0.5), "p95": q(0.95), "max": xs[-1], "min": xs[0]}

    sets = {}
    for s in sorted({r["set"] for r in prow}):
        rs = [r for r in prow if r["set"] == s]
        eq = [r for r in rs if r["equiv"]["equivalent"] is True]
        ne = [r for r in rs if r["equiv"]["equivalent"] is False]
        v = {"pairs": len(rs), "equiv_equivalent": len(eq), "equiv_exact": sum(1 for r in eq if r["equiv"]["exact"]),
             "equiv_different": len(ne), "equiv_undecided": len(rs) - len(eq) - len(ne),
             "equivalent_same_program_hash": sum(1 for r in eq if r["same_program_hash"]),
             "equivalent_distinct_program_hash": sum(1 for r in eq if not r["same_program_hash"]),
             "different_same_program_hash": sum(1 for r in ne if r["same_program_hash"])}
        for d in DEPTHS:
            k = str(d)
            both = [r for r in eq if r["fp"][k] is not None]
            v[f"depth{d}"] = {
                "equivalent_both_fingerprinted": len(both),
                "equivalent_same_fingerprint": sum(1 for r in both if r["fp"][k]),
                "equivalent_distinct_program_hash_same_fingerprint": sum(1 for r in both if r["fp"][k] and not r["same_program_hash"]),
                "equivalent_distinct_program_hash_both_fingerprinted": sum(1 for r in both if not r["same_program_hash"]),
                "different_both_fingerprinted": sum(1 for r in ne if r["fp"][k] is not None),
                "different_same_fingerprint": sum(1 for r in ne if r["fp"][k]),
                "undecided_same_fingerprint": sum(1 for r in rs if r["equiv"]["equivalent"] is None and r["fp"][k]),
            }
        sets[s] = v
    admitted = [p for p in progs.values() if p["admitted"]]
    cover = {str(d): {"fingerprinted": sum(1 for p in progs.values() if p["fp"][str(d)]["hash"]),
                      "not_fingerprinted_reasons": {}} for d in DEPTHS}
    for d in DEPTHS:
        for p in progs.values():
            if p["fp"][str(d)]["hash"] is None:
                w = p["fp"][str(d)]["why"]
                key = "no state region" if "a command" in w else "no explorable event" if "no event" in w else "fuel" if "fuel" in w else w[:80]
                cover[str(d)]["not_fingerprinted_reasons"][key] = cover[str(d)]["not_fingerprinted_reasons"].get(key, 0) + 1
    cost = {str(d): {"seconds": med([p["fp"][str(d)]["s"] for p in progs.values() if p["fp"][str(d)]["hash"]]),
                     "states": med([p["fp"][str(d)]["states"] for p in progs.values() if p["fp"][str(d)]["hash"]])} for d in DEPTHS}
    eq_cost = med([e["s"] for e in equiv_cache.values()])
    summary = {"rce_commit": commit, "depths": DEPTHS, "primary_depth": PRIMARY_DEPTH, "fuel": FUEL, "pair_cap": PAIR_CAP,
               "programs": len(progs), "programs_admitted": len(admitted), "coverage": cover, "sets": sets,
               "false_positives": fp_stats, "cost_fingerprint": cost, "cost_equiv_seconds": eq_cost, "equiv_calls": len(equiv_cache)}
    with open(out / "pairs.jsonl", "w") as fh:
        for r in prow:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    with open(out / "collisions.jsonl", "w") as fh:
        for r in coll:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    with open(out / "programs.jsonl", "w") as fh:
        for h, p in sorted(progs.items()):
            q = dict(p)
            q.pop("file")
            fh.write(json.dumps(q, sort_keys=True) + "\n")
    (out / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
    for f in work.iterdir():
        f.unlink()
    work.rmdir()
    print(json.dumps(summary, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
