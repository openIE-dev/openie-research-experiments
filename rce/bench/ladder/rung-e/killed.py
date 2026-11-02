#!/usr/bin/env python3
"""The tasks of an arm that ended by a signal (exit below 0, not the
runner's time cap), for the one rerun the registration allows.

    python3 -I killed.py RUNS.compact.tsv TASKS.jsonl OUT.jsonl

Prints the number of tasks written.
"""
import json, sys
from pathlib import Path

rows = [l.split("\t") for l in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()[1:] if l.strip()]
ids = {r[0] for r in rows if r[3] not in ("None", "") and int(r[3]) < 0}
n = 0
with open(sys.argv[3], "w", encoding="utf-8") as fh:
    for l in Path(sys.argv[2]).read_text(encoding="utf-8").splitlines():
        if l.strip() and json.loads(l)["id"] in ids:
            fh.write(l + "\n")
            n += 1
print(n)
