#!/usr/bin/env python3
"""H7 on the fuzzed arm: every checker-accepted mutant of the Form corpus is
checked against the invariants of PREREG.json (chain, atomicity,
determinism, the gate, fuel). usage: run.py RCE NEGATIVES.jsonl OUT_DIR"""
import hashlib, json, subprocess, sys, tempfile, time
from pathlib import Path

GENESIS = "0" * 64


import importlib.util, struct
_spec = importlib.util.spec_from_file_location("cjv", "/home/user/rce/scripts/canonical-json-vectors.py")
_cjv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cjv)


def canon(v):
    """The canonical JSON of 6.1 for the values of a trace: sorted keys, no
    spaces, text escaped as the canonical writer does, floats in the shortest
    round-trip text of N3 (the writer of scripts/canonical-json-vectors.py in
    openIE-dev/rce, the project's own reference for the format)."""
    if v is None:
        return "null"
    if v is True or v is False:
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return _cjv.float_text(struct.unpack(">Q", struct.pack(">d", v))[0])
    if isinstance(v, str):
        return _cjv.text(v)
    if isinstance(v, list):
        return "[" + ",".join(canon(x) for x in v) + "]"
    return "{" + ",".join(_cjv.text(k) + ":" + canon(v[k]) for k in sorted(v, key=lambda k: [ord(c) for c in k])) + "}"


def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def main():
    rce, negs, out = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(l) for l in open(negs) if l.strip()]
    acc = [r for r in rows if r.get("kind") == "mutant" and r.get("verdict") == "accept"]
    commit = subprocess.run(["git", "-C", "/home/user/rce", "rev-parse", "--short=8", "HEAD"], capture_output=True, text=True).stdout.strip()
    viol, per_inv, per_op, untraced = [], {k: 0 for k in ("I1", "I2", "I3", "I4", "I5")}, {}, 0
    t0 = time.time()
    with tempfile.TemporaryDirectory() as d:
        for i, r in enumerate(acc):
            f = Path(d) / f"m{i}.rce"
            f.write_text(r["source"], encoding="utf-8")
            per_op.setdefault(r.get("operator"), 0)
            per_op[r["operator"]] += 1

            def bad(inv, why):
                viol.append({"index": i, "parent": r["path"], "operator": r.get("operator"), "mutation": r.get("mutation"), "invariant": inv, "why": why[:300]})
                per_inv[inv] += 1

            c1 = subprocess.run([rce, "check", str(f)], capture_output=True, text=True)
            c2 = subprocess.run([rce, "check", str(f)], capture_output=True, text=True)
            if c1.returncode != 0:
                bad("I4", "rce check refuses the row the corpus recorded as accepted: " + (c1.stdout + c1.stderr).strip())
                continue
            if (c1.stdout, c1.returncode) != (c2.stdout, c2.returncode):
                bad("I3", "rce check differs between two runs")
            t1 = subprocess.run([rce, "trace", "--json", str(f)], capture_output=True, text=True)
            t2 = subprocess.run([rce, "trace", "--json", str(f)], capture_output=True, text=True)
            if t1.stdout != t2.stdout or t1.returncode != t2.returncode:
                bad("I3", "rce trace differs between two runs")
            if t1.returncode != 0:
                untraced += 1
                continue
            j = json.loads(t1.stdout)
            if not j["traces"]:
                untraced += 1
                continue
            for tr in j["traces"]:
                prev = GENESIS
                prev_state = None
                steps = tr["steps"]
                for k, s in enumerate(steps):
                    if s["seq"] != k or s["prev_hash"] != prev:
                        bad("I1", f"{tr['source']} seq {k}: seq or prev_hash")
                    if s["state_hash"] != sha(canon(s["hashed"]["state"])):
                        bad("I1", f"{tr['source']} seq {k}: state_hash")
                    body = {"event": s["hashed"]["event"], "prev_hash": s["prev_hash"], "seq": s["seq"], "state_hash": s["state_hash"]}
                    if s["hash"] != sha(canon(body)):
                        bad("I1", f"{tr['source']} seq {k}: hash")
                    if s["outcome"] != "applied":
                        if prev_state is not None and s["state_hash"] != prev_state:
                            bad("I2", f"{tr['source']} seq {k}: refused step changed the state")
                        if k != len(steps) - 1:
                            bad("I2", f"{tr['source']} seq {k}: refused step is not the last")
                        if isinstance(s["outcome"], dict) and "fuel" in canon(s["outcome"]).lower():
                            bad("I5", f"{tr['source']} seq {k}: fuel trap {canon(s['outcome'])}")
                    prev = s["hash"]
                    prev_state = s["state_hash"]
    summary = {"commit": commit, "accepted_mutants": len(acc), "violations": len(viol), "per_invariant": per_inv, "per_operator": per_op,
               "untraced_no_examples": untraced, "cpu_s": round(time.time() - t0, 1)}
    with open(out / "violations.jsonl", "w") as fh:
        for v in viol:
            fh.write(json.dumps(v, sort_keys=True) + "\n")
    (out / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
