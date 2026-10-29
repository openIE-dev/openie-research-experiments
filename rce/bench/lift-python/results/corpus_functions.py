#!/usr/bin/env python3
"""Function-level coverage over every program of lang/python3.13/corpus
(descriptive, not a registered metric). Run from lang/python3.13/corpus of
openIE-dev/rce at the commit of rce-commit.txt:

    python3 corpus_functions.py RCE > corpus-functions.txt
"""
import os
import subprocess
import sys
import tempfile
import tomllib

sys.path.insert(0, "../../../spec/lift/python")
import lift_py  # noqa: E402

B = sys.argv[1]
m = tomllib.load(open("manifest.toml", "rb"))
tot = lif = intl = 0
by, only = {}, {}
with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as d:
    for c in m["case"]:
        it = c["provenance"]["item"]
        for fn, text, diags in lift_py.lift_functions(it + ".py", open(c["file"], "rb").read()):
            tot += 1
            if diags:
                rules = sorted({x[1] for x in diags})
                for r in rules:
                    by[r] = by.get(r, 0) + 1
                own = [r for r in rules if r != "L-PY-CALLEE"]
                if len(own) == 1:
                    only[own[0]] = only.get(own[0], 0) + 1
                print(f"requires change {it}:{fn}: {', '.join(rules)}")
            else:
                p = os.path.join(d, "f.rce")
                open(p, "w").write(text)
                if subprocess.run([B, "check", p], capture_output=True).returncode == 0:
                    lif += 1
                    print(f"lifted {it}:{fn}")
                else:
                    intl += 1
                    print(f"internal {it}:{fn}")
print()
print("functions", tot)
print("lifted", lif)
print("internal", intl)
print(f"coverage {100 * lif / tot:.1f}%")
print("requires change, functions naming each rule:")
for k in sorted(by):
    print(" ", k, by[k])
print("requires change, functions whose only rule (L-PY-CALLEE aside) is:")
for k in sorted(only):
    print(" ", k, only[k])
