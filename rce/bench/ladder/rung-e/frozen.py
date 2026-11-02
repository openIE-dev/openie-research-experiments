#!/usr/bin/env python3
"""Rebuild the frozen task set of the second registered ladder run
(real-defects/tasks.jsonl, SHA-256 6ae255a3...af50) from git and its list.

    python3 -I frozen.py RCE_REPO LIST.tsv OUT.jsonl

RCE_REPO is a clone of openIE-dev/rce and LIST.tsv is
real-defects/tasks.list.tsv. No `rce` binary is run: every text comes from
git and every other field from the list.

  history   original = the file at the commit, mutant = the file at its
            parent, subject = the commit subject (as real-defects/tasks.py);
  guard,    original = the file at the base commit; the mutant is the one
  rename    site of real-defects/tasks.py (guard_sites or rename_sites of
            the original) whose text has the listed mutant SHA-256.

Tasks are written in the order of the list, as real-defects/tasks.py wrote
them, with the same fields and encoding. The last line printed is the
SHA-256 of OUT.jsonl; a text whose SHA-256 differs from the list stops the
script.
"""
import hashlib, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "real-defects"))
import tasks as run2  # noqa: E402  (real-defects/tasks.py, unchanged)


def main(argv):
    if len(argv) != 3:
        sys.exit("usage: frozen.py RCE_REPO LIST.tsv OUT.jsonl")
    repo, lst, out = argv[0], Path(argv[1]), Path(argv[2])
    rows = [l.split("\t") for l in lst.read_text(encoding="utf-8").splitlines()[1:] if l.strip()]
    tasks = []
    for tid, source, line, rules, osha, msha, commit in rows:
        path = tid.split("@")[0] if source.startswith("history") else tid.split("#")[0]
        t = {"id": tid, "source": source, "operator": source, "path": path, "commit": commit,
             "mutant_rules": [r for r in rules.split(",") if r], "line": int(line)}
        if source.startswith("history"):
            t["subject"] = run2.git(repo, "log", "-1", "--format=%s", commit).strip()
            t["original"] = run2.git(repo, "show", f"{commit}:{path}")
            t["mutant"] = run2.git(repo, "show", f"{commit}^:{path}")
        else:
            src = run2.git(repo, "show", f"{commit}:{path}")
            sl = run2.spec_lines(src)
            sites = run2.guard_sites(src, sl) if source == "guard" else run2.rename_sites(src, sl)
            lines = src.split("\n")
            found = None
            for i, new in sites:
                m = "\n".join(lines[:i] + [new] + lines[i + 1:])
                if run2.sha(m) == msha:
                    found = m
                    break
            t["original"], t["mutant"] = src, found
        if t["mutant"] is None or run2.sha(t["original"]) != osha or run2.sha(t["mutant"]) != msha:
            sys.exit(f"{tid}: text does not match the list")
        t["original_sha256"], t["mutant_sha256"] = osha, msha
        tasks.append(t)
    with open(out, "w", encoding="utf-8") as fh:
        for t in tasks:
            fh.write(json.dumps(t, sort_keys=True, ensure_ascii=False) + "\n")
    print(f"{len(tasks)} tasks")
    print(hashlib.sha256(out.read_bytes()).hexdigest())


if __name__ == "__main__":
    main(sys.argv[1:])
