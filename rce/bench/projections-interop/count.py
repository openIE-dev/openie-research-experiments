#!/usr/bin/env python3
"""M1 and M2: lines of code (PREREG.json, "counting").

A counted line is a line that is not blank and not only a comment (`#` in
Python, `//` in Rust and JS; a Python docstring line counts as a comment
when it lies inside a triple-quoted block that opens a module, class or
function). Usage: count.py RCE_TREE EMITTED_DIR > results/loc.json, where
EMITTED_DIR holds LANG/NAME.EXT as examples/interop/check.py writes them.
"""
import json, os, re, sys

TREE, EMITTED = sys.argv[1], sys.argv[2]
NAMES = ["counter", "bank", "multi_region", "traffic_light", "door", "inventory", "rcedb", "float_keys"]
EXT = {"python": "py", "js": "mjs", "rust": "rs"}
COMMENT = {"python": "#", "js": "//", "rust": "//"}


def counted(lines, lang):
    n, doc = 0, False
    for l in lines:
        s = l.strip()
        if lang == "python" and (s.startswith('"""') or doc):
            q = s.count('"""')
            if doc:
                doc = q % 2 == 0
            else:
                doc = q % 2 == 1
            continue
        if not s or s.startswith(COMMENT[lang]):
            continue
        n += 1
    return n


def file_lines(p):
    return open(p, encoding="utf-8").read().split("\n")


def emitted(lang, name):
    ls = file_lines(os.path.join(EMITTED, lang, f"{name}.{EXT[lang]}"))
    # the runtime ends at the LOOP_LIMIT line (and, for JS, `const KC = {};`), prog.rs
    end = max(i for i, l in enumerate(ls) if l.startswith(("LOOP_LIMIT =", "const LOOP_LIMIT", "const KC = {};")))
    # the driver: from `def observe()` / `function observe()` / `fn main()` to the end
    drv = next(i for i, l in enumerate(ls) if re.match(r"(def observe\(\)|function observe\(\)|fn main\(\))", l))
    return {"total": counted(ls, lang), "runtime": counted(ls[: end + 1], lang),
            "program": counted(ls[end + 1: drv], lang), "driver": counted(ls[drv:], lang)}


def hand_sections(lang):
    p = {"python": "hand/python/programs.py", "js": "hand/js/programs.mjs", "rust": "hand/rust/src/programs.rs"}[lang]
    ls = file_lines(os.path.join(TREE, "examples/interop", p))
    marks = [(i, re.match(r"(?:#|//) ---- (\w+)", l).group(1)) for i, l in enumerate(ls) if re.match(r"(?:#|//) ---- \w+", l)]
    out = {"preamble": counted(ls[: marks[0][0]], lang)}
    for k, (i, n) in enumerate(marks):
        j = marks[k + 1][0] if k + 1 < len(marks) else len(ls)
        if n in NAMES:
            out[n] = counted(ls[i:j], lang)
        else:
            out["tail"] = counted(ls[i:j], lang)
    if "tail" not in out:
        out["tail"] = 0
    return out


def files(lang, paths):
    return {p: counted(file_lines(os.path.join(TREE, "examples/interop", p)), lang) for p in paths}


res = {"emitted": {l: {n: emitted(l, n) for n in NAMES} for l in EXT},
       "hand": {l: hand_sections(l) for l in EXT},
       "glue": {
           "python": files("python", ["python/rce_host.py", "python/service.py", "python/fastapi_app.py", "python/numpy_drive.py"]),
           "js": files("js", ["js/rce_host.mjs", "js/service.mjs", "js/Program.mjs", "js/react_drive.mjs", "js/browser_drive.mjs"]),
           "rust": files("rust", ["rust/src/adapter.rs", "rust/src/main.rs", "rust/src/bench.rs"]),
       },
       "hand_glue": {
           "python": files("python", ["hand/python/drive.py"]),
           "js": files("js", ["hand/js/drive.mjs"]),
           "rust": files("rust", ["hand/rust/src/main.rs"]),
       }}
# per-program glue: counted lines of the glue that name one of the eight programs
per = {}
for lang, fs in res["glue"].items():
    c = 0
    for p in fs:
        for l in file_lines(os.path.join(TREE, "examples/interop", p)):
            s = l.strip()
            if s and not s.startswith(COMMENT[lang]) and any(re.search(r"\b%s\b" % n, s) for n in NAMES):
                c += 1
    per[lang] = c
res["glue_per_program_lines"] = per
json.dump(res, sys.stdout, indent=1, sort_keys=True)
print()
