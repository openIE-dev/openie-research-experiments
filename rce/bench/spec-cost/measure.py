#!/usr/bin/env python3
"""Specification cost over the RCE corpus (critique 10, RJ-F2 proxies), as registered in PREREG.json.

    python3 measure.py --repo PATH/TO/rce-checkout --rce PATH/TO/rce --out results [--only REL]

Part A: bytes and lines of the intent text, the obligations (example, check and contract lines),
the body, the bare program's nameless Form, and the emitted Python and Rust of the bare program.
Part B: typed mutants of the body only (obligations held fixed), scored against an oracle that
does not use the obligations (random event streams and rce equiv on the bare programs).
"""
import argparse, difflib, itertools, json, math, re, subprocess, sys, tempfile
from pathlib import Path

SEED = 0x5EED_C0DE_0010
OPS = ("rename", "operator", "literal", "guard", "type")
PER_OP, DRAWS, RANDOM_STREAMS, MAX_LEN, POOL_CAP = 10, 40, 64, 6, 64
INT_RANGE = {f"{s}{b}": ((-(1 << (b - 1)), (1 << (b - 1)) - 1) if s == "i" else (0, (1 << b) - 1))
             for s in "iu" for b in (8, 16, 32, 64)}
OBL = re.compile(r"^\s*(example|check)\b")
CONTRACT = re.compile(r"^\s*(requires|ensures|decreases|ghost)\b")
REMOVE_IN_BARE = re.compile(r"^\s*(example|check|requires|ensures)\b")


def classify_lines(src):
    """One label per line: intent, obligation, body, comment, blank."""
    lines = src.split("\n")
    lab = [None] * len(lines)
    i = 0
    while i < len(lines):
        l = lines[i]
        if not l.strip():
            lab[i] = "blank"
        elif l.lstrip().startswith("#"):
            lab[i] = "comment"
        elif re.match(r"^\s*intent\s", l):
            lab[i] = "intent"
            ind = len(l) - len(l.lstrip())
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or len(lines[j]) - len(lines[j].lstrip()) > ind):
                m = lines[j]
                if not m.strip():
                    lab[j] = "blank"
                elif m.lstrip().startswith("#"):
                    lab[j] = "comment"
                elif OBL.match(m):
                    lab[j] = "obligation"
                else:
                    lab[j] = "intent"  # STRING lines of the block
                j += 1
            i = j
            continue
        elif OBL.match(l) or CONTRACT.match(l):
            lab[i] = "obligation"
        else:
            lab[i] = "body"
        i += 1
    return lines, lab


def measure(lines, lab, which, strip_comments):
    sel = [strip_comments(l, "#").strip() for l, k in zip(lines, lab) if k == which]
    sel = [s for s in sel if s]
    return {"lines": len(sel), "bytes": sum(len(s.encode()) for s in sel) + max(0, len(sel) - 1)}


def bare(src, examples_only=False):
    """Remove the intent block, check lines and requires/ensures lines (bare), or only check lines (examples_only)."""
    lines, lab = classify_lines(src)
    out = []
    for l, k in zip(lines, lab):
        if examples_only:
            if re.match(r"^\s*check\b", l):
                continue
        elif k == "intent" or (k == "obligation" and REMOVE_IN_BARE.match(l)):
            continue
        out.append(l)
    return "\n".join(out)


def kind_of(src):
    if re.search(r"^state\s", src, re.M):
        return "machine"
    if re.search(r"^fn main\(", src, re.M):
        return "command"
    return "library"


def split_top(s):
    out, depth, cur, q = [], 0, "", None
    for ch in s:
        if q:
            cur += ch
            if ch == q and not cur.endswith("\\" + q):
                q = None
            continue
        if ch in "\"'":
            q = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
            continue
        cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def example_streams(src):
    out = []
    for l in src.split("\n"):
        m = re.match(r"^\s*example\s+(.*?)\s*->", l)
        if m and m.group(1).strip():
            out.append(split_top(m.group(1)))
    return out


def event_pool(src, corpus, rng, ex_streams):
    pool = []
    for s in ex_streams:
        for e in s:
            if e not in pool:
                pool.append(e)
    ints = set()
    _, occ = corpus.occurrences(src, r"(?<![\w.])\d+(?![\w.])")
    for _, m in occ:
        v = int(m.group(0))
        ints.update({v - 1, v, v + 1})
    strs = sorted({seg for is_s, seg in corpus.segments(src) if is_s and seg.startswith('"')})
    for l in src.split("\n"):
        m = re.match(r"^event\s+(\w+)\s*(?:\((.*)\))?\s*$", l)
        if not m:
            continue
        name, fields = m.group(1), m.group(2)
        if not fields or not fields.strip():
            if name not in pool:
                pool.append(name)
            continue
        vals = []
        for f in split_top(fields):
            if ":" not in f:
                vals = None
                break
            fn, ty = (x.strip() for x in f.split(":", 1))
            if ty in INT_RANGE:
                lo, hi = INT_RANGE[ty]
                vs = sorted({0, 1, lo, hi} | ({-1} if lo < 0 else set()) | {v for v in ints if lo <= v <= hi})
            elif ty == "bool":
                vs = ["true", "false"]
            elif ty == "text":
                vs = ['""'] + strs
            else:
                vals = None
                break
            vals.append([f"{fn}: {v}" for v in vs])
        if vals is None:
            continue
        combos = list(itertools.islice(itertools.product(*vals), 4096))
        pick = combos if len(combos) <= POOL_CAP else [combos[rng.next() % len(combos)] for _ in range(POOL_CAP)]
        for c in pick:
            inst = f"{name}({', '.join(c)})"
            if inst not in pool:
                pool.append(inst)
    return pool


class R:
    def __init__(self, bin_, tmp):
        self.bin, self.tmp, self.n = bin_, Path(tmp), 0

    def write(self, text):
        self.n += 1
        p = self.tmp / f"f{self.n}.rce"
        p.write_text(text, encoding="utf-8")
        return p

    def run(self, *a):
        try:
            r = subprocess.run([self.bin, *map(str, a)], capture_output=True, text=True, timeout=60)
            return r.returncode, r.stdout, r.stderr
        except subprocess.TimeoutExpired:
            return -9, "", "timeout"


def first_code(text):
    m = re.search(r"\bW-[A-Z0-9]+-\d+\b", text)
    return m.group(0) if m else None


def traces(rce, f, streams_file):
    rc, out, _ = rce.run("trace", "--json", f, "--streams", streams_file)
    if rc != 0:
        return None
    try:
        j = json.loads(out)
    except ValueError:
        return None
    res = []
    for t in j["traces"]:
        res.append([json.dumps({k: v for k, v in s.items() if k not in ("hash", "prev_hash", "hashed", "seq")}, sort_keys=True)
                    for s in t["steps"]])
    return res


def stats(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    n = len(xs)
    q = lambda f: xs[min(n - 1, max(0, int(round(f * (n - 1)))))]
    return {"n": n, "median": round(q(0.5), 3), "q1": round(q(0.25), 3), "q3": round(q(0.75), 3), "min": round(xs[0], 3), "max": round(xs[-1], 3)}


def wilson(k, n, z=1.96):
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 3), round(c + h, 3)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--rce", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--only")
    a = ap.parse_args()
    repo = Path(a.repo).resolve()
    sys.path.insert(0, str(repo / "scripts"))
    import corpus  # the population rule, the mutation operators and the Rng of scripts/corpus.py
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.mkdtemp(dir=out)
    rce = R(a.rce, tmp)
    commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short=8", "HEAD"], capture_output=True, text=True).stdout.strip()
    runtimes = {t: (repo / "spec/checker/src/emit" / f).read_text() for t, f in (("python", "rt.py"), ("rust", "rt.rs"))}

    cands = [(p.relative_to(repo).as_posix(), o, p.read_text(encoding="utf-8")) for p, _, o in corpus.population()]
    cands += [(p.relative_to(repo).as_posix(), "conformance-accept", s) for p, s, _ in corpus.conformance(True)]
    if a.only:
        cands = [c for c in cands if c[0] == a.only]
    files, seen, notes = [], set(), {"not_admitted": 0, "no_obligation": 0, "duplicate_shape": 0, "bare_requires_change": []}
    for rel, origin, src in cands:
        f = rce.write(src)
        if rce.run("check", f)[0] != 0:
            notes["not_admitted"] += 1
            continue
        lines, lab = classify_lines(src)
        if "obligation" not in lab and "intent" not in lab:
            notes["no_obligation"] += 1
            continue
        shape = corpus.sha(rce.run("fmt", "--nameless", f)[1])
        if shape in seen:
            notes["duplicate_shape"] += 1
            continue
        seen.add(shape)
        n_ex = sum(1 for l, k in zip(lines, lab) if k == "obligation" and re.match(r"^\s*example\b", l))
        n_chk = sum(1 for l, k in zip(lines, lab) if k == "obligation" and re.match(r"^\s*check\b", l))
        n_con = sum(1 for l, k in zip(lines, lab) if k == "obligation" and CONTRACT.match(l))
        row = {"commit": commit, "path": rel, "origin": origin, "kind": kind_of(src), "shape_hash": shape,
               "has_intent": "intent" in lab, "examples": n_ex, "checks": n_chk, "contract_lines": n_con,
               "subset": "primary" if ("intent" in lab or n_ex) else "checks_or_contracts_only",
               "intent_text": measure(lines, lab, "intent", corpus.strip_comments),
               "obligations": measure(lines, lab, "obligation", corpus.strip_comments),
               "body": measure(lines, lab, "body", corpus.strip_comments)}
        b = bare(src)
        bf = rce.write(b)
        row["bare_admitted"] = rce.run("check", bf)[0] == 0
        if row["bare_admitted"]:
            row["form_nameless_bytes"] = len(rce.run("fmt", "--nameless", bf)[1].encode())
            for t in ("python", "rust"):
                rc, text, _ = rce.run("emit", t, bf)
                if rc == 0:
                    if re.match(r"^(#|//) rce-program ", text):  # the one-line provenance header the emitter writes first
                        text = text.split("\n", 1)[1]
                    prog = text[len(runtimes[t]):] if text.startswith(runtimes[t]) else text
                    row[t] = {"bytes": len(prog.encode()), "lines": prog.count("\n"), "runtime_prefix_verbatim": text.startswith(runtimes[t])}
                    # secondary (not registered): without the DISPLAY_ESCAPE table, a constant line every emitted program carries
                    rest = [l for l in prog.split("\n") if not re.match(r"^(const )?DISPLAY_ESCAPE\b", l)]
                    row[t]["bytes_no_table"] = len("\n".join(rest).encode())
                    row[t]["lines_no_table"] = "\n".join(rest).count("\n")
        else:
            notes["bare_requires_change"].append(rel)
        ob, bo, it = row["obligations"], row["body"], row["intent_text"]
        row["ratio_bytes"] = round(ob["bytes"] / bo["bytes"], 4) if bo["bytes"] else None
        row["ratio_lines"] = round(ob["lines"] / bo["lines"], 4) if bo["lines"] else None
        row["ratio_bytes_with_intent"] = round((ob["bytes"] + it["bytes"]) / bo["bytes"], 4) if bo["bytes"] else None
        row["ratio_lines_with_intent"] = round((ob["lines"] + it["lines"]) / bo["lines"], 4) if bo["lines"] else None
        row["_src"] = src
        files.append(row)

    # Part B
    rng = corpus.Rng(SEED)
    sub = [r for r in files if r["bare_admitted"] and ((r["subset"] == "primary" and r["kind"] == "machine" and r["examples"])
                                                      or (r["kind"] == "command" and r["checks"]))]
    mutants = []
    for r in sub:
        src = r["_src"]
        lines, lab = classify_lines(src)
        pb = rce.write(bare(src))
        arm = "machine" if r["kind"] == "machine" else "command"
        if arm == "machine":
            ex = example_streams(src)
            pool = event_pool(src, corpus, rng, ex)
            streams = [", ".join(s) for s in ex]
            for _ in range(RANDOM_STREAMS):
                n = 1 + rng.next() % MAX_LEN
                streams.append(", ".join(pool[rng.next() % len(pool)] for _ in range(n)))
            sf = Path(tmp) / f"streams-{r['shape_hash'][:12]}.txt"
            sf.write_text("\n".join(streams) + "\n")
            base = traces(rce, pb, sf)
            r["streams"] = {"example": len(ex), "random": RANDOM_STREAMS, "pool": len(pool), "traced": base is not None}
            if base is None:
                r["part_b"] = "base trace failed"
                continue
        else:
            base_run = rce.run("run", pb)
        seen_m = set()
        for op in OPS:
            kept = 0
            for _ in range(DRAWS):
                if kept >= PER_OP:
                    break
                t = corpus.mutate_typed(src, rng, op)
                if t is None or t == src or t in seen_m:
                    continue
                seen_m.add(t)
                mlines = t.split("\n")
                ok = True
                for tag, i1, i2, _, _ in difflib.SequenceMatcher(None, lines, mlines, autojunk=False).get_opcodes():
                    if tag != "equal" and (tag == "insert" or any(lab[i] != "body" for i in range(i1, i2))):
                        ok = False
                        break
                if not ok:
                    continue
                kept += 1
                changed = [l for l in difflib.unified_diff(lines, mlines, lineterm="", n=0) if l[:1] in "+-" and not l.startswith(("+++", "---"))]
                m = {"path": r["path"], "arm": arm, "operator": op, "diff": changed[:4]}
                mb = rce.write(bare(t))
                rc_b, o_b, e_b = rce.run("check", mb)
                if rc_b != 0:
                    m["outcome"] = "not_a_program"
                    m["bare_diagnostic"] = first_code(o_b + e_b)
                    mutants.append(m)
                    continue
                if arm == "machine":
                    tr = traces(rce, mb, sf)
                    k = r["streams"]["example"]
                    diff_streams = [i for i in range(len(base)) if tr is None or i >= len(tr) or tr[i] != base[i]]
                    rc_e, o_e, _ = rce.run("equiv", "--json", pb, mb)
                    try:
                        eq = json.loads(o_e)["equivalent"]
                    except (ValueError, KeyError):
                        eq = None
                    m["differs_streams"] = bool(diff_streams)
                    m["differs_example_streams"] = any(i < k for i in diff_streams)
                    m["equiv"] = eq
                    m["first_distinguishing_stream"] = streams[diff_streams[0]] if diff_streams else None
                    changed_beh = bool(diff_streams) or eq is False
                else:
                    mr = rce.run("run", mb)
                    changed_beh = mr[:2] != base_run[:2]
                    m["differs_example_streams"] = None
                m["outcome"] = "behaviour_changing" if changed_beh else "no_difference_found"
                rc_f, o_f, e_f = rce.run("check", rce.write(t))
                m["caught_obligations"] = rc_f != 0
                m["diagnostic"] = first_code(o_f + e_f) if rc_f else None
                rc_x, o_x, e_x = rce.run("check", rce.write(bare(t, examples_only=True)))
                m["caught_examples_only"] = rc_x != 0
                mutants.append(m)
        mine = [m for m in mutants if m["path"] == r["path"] and m["outcome"] == "behaviour_changing"]
        r["part_b"] = {"behaviour_changing": len(mine), "caught_obligations": sum(m["caught_obligations"] for m in mine),
                       "caught_examples_only": sum(m["caught_examples_only"] for m in mine)}
        for f in Path(tmp).glob("f*.rce"):
            f.unlink()

    for r in files:
        r.pop("_src", None)
    for f in Path(tmp).iterdir():
        f.unlink()
    Path(tmp).rmdir()
    with open(out / "files.jsonl", "w") as fh:
        for r in files:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    with open(out / "mutants.jsonl", "w") as fh:
        for m in mutants:
            fh.write(json.dumps(m, sort_keys=True) + "\n")

    def part_a(rows):
        return {"files": len(rows),
                **{k: stats([r[k] for r in rows]) for k in ("ratio_bytes", "ratio_lines", "ratio_bytes_with_intent", "ratio_lines_with_intent")},
                **{f"{k}_{u}": stats([r[k][u] for r in rows]) for k in ("intent_text", "obligations", "body") for u in ("bytes", "lines")},
                "form_nameless_bytes": stats([r.get("form_nameless_bytes") for r in rows]),
                **{f"{t}_{u}": stats([r.get(t, {}).get(u) for r in rows]) for t in ("python", "rust") for u in ("bytes", "lines", "bytes_no_table", "lines_no_table")},
                "obligation_bytes_over_python_bytes_no_table": stats([r["obligations"]["bytes"] / r["python"]["bytes_no_table"] for r in rows if r.get("python", {}).get("bytes_no_table")]),
                "body_bytes_over_python_bytes_no_table": stats([r["body"]["bytes"] / r["python"]["bytes_no_table"] for r in rows if r.get("python", {}).get("bytes_no_table")]),
                "obligation_bytes_over_python_bytes": stats([r["obligations"]["bytes"] / r["python"]["bytes"] for r in rows if r.get("python", {}).get("bytes")]),
                "files_ratio_bytes_above_1": sum(1 for r in rows if (r["ratio_bytes"] or 0) > 1)}

    prim = [r for r in files if r["subset"] == "primary"]
    summary = {"commit": commit, "seed": hex(SEED), "candidates": len(cands), "files": len(files), "notes": notes,
               "part_a": {"primary": part_a(prim), "checks_or_contracts_only": part_a([r for r in files if r["subset"] != "primary"]),
                          "all": part_a(files),
                          "primary_by_origin": {o: part_a([r for r in prim if r["origin"] == o]) for o in sorted({r["origin"] for r in prim})},
                          "primary_by_kind": {k: part_a([r for r in prim if r["kind"] == k]) for k in sorted({r["kind"] for r in prim})},
                          "all_by_kind": {k: part_a([r for r in files if r["kind"] == k]) for k in sorted({r["kind"] for r in files})}},
               "part_b": {}}
    for arm in ("machine", "command"):
        ms = [m for m in mutants if m["arm"] == arm]
        bc = [m for m in ms if m["outcome"] == "behaviour_changing"]
        rows = [r for r in sub if r["kind"] == arm and isinstance(r.get("part_b"), dict) and r["part_b"]["behaviour_changing"]]
        d = {"files": len([r for r in sub if r["kind"] == arm]), "files_with_behaviour_changing": len(rows), "mutants": len(ms),
             "by_outcome": {o: sum(1 for m in ms if m["outcome"] == o) for o in ("not_a_program", "no_difference_found", "behaviour_changing")},
             "caught_obligations": sum(m["caught_obligations"] for m in bc), "caught_examples_only": sum(m["caught_examples_only"] for m in bc),
             "behaviour_changing": len(bc)}
        d["catch_obligations"] = round(d["caught_obligations"] / len(bc), 3) if bc else None
        d["catch_obligations_wilson95"] = wilson(d["caught_obligations"], len(bc))
        d["catch_examples_only"] = round(d["caught_examples_only"] / len(bc), 3) if bc else None
        d["catch_examples_only_wilson95"] = wilson(d["caught_examples_only"], len(bc))
        d["caught_diagnostics"] = {c: sum(1 for m in bc if m["caught_obligations"] and m["diagnostic"] == c) for c in sorted({m["diagnostic"] for m in bc if m["caught_obligations"]}, key=str)}
        d["caught_no_difference_found"] = sum(1 for m in ms if m["outcome"] == "no_difference_found" and m["caught_obligations"])
        d["per_file_catch_obligations"] = stats([r["part_b"]["caught_obligations"] / r["part_b"]["behaviour_changing"] for r in rows])
        d["pinned_files"] = sum(1 for r in rows if r["part_b"]["caught_obligations"] == r["part_b"]["behaviour_changing"])
        d["by_operator"] = {op: {"behaviour_changing": sum(1 for m in bc if m["operator"] == op),
                                 "caught_obligations": sum(1 for m in bc if m["operator"] == op and m["caught_obligations"])} for op in OPS}
        if arm == "machine":
            cp = [m for m in bc if m["differs_example_streams"]]
            d["corpus_py_definition"] = {"behaviour_changing": len(cp), "caught_obligations": sum(m["caught_obligations"] for m in cp),
                                         "catch": round(sum(m["caught_obligations"] for m in cp) / len(cp), 3) if cp else None,
                                         "wilson95": wilson(sum(m["caught_obligations"] for m in cp), len(cp))}
            d["seen_only_by_random_streams_or_equiv"] = len(bc) - len(cp)
            d["equiv_only"] = sum(1 for m in bc if not m["differs_streams"] and m["equiv"] is False)
        summary["part_b"][arm] = d
    (out / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
    print(json.dumps({"files": len(files), "part_b": {k: {x: v[x] for x in ("files", "mutants", "behaviour_changing", "catch_obligations", "catch_examples_only")} for k, v in summary["part_b"].items()},
                      "primary_ratio_bytes": summary["part_a"]["primary"]["ratio_bytes"]}, indent=1))


if __name__ == "__main__":
    main()
