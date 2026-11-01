#!/usr/bin/env python3
"""tasks.list.tsv from tasks.jsonl: one row per task, with the hashes that
pin it (the texts themselves are reproduced by tasks.py from git).

    python3 list.py tasks.jsonl > tasks.list.tsv
"""
import json, sys

print("id\tsource\tline\tmutant_rules\toriginal_sha256\tmutant_sha256\tcommit")
for l in open(sys.argv[1], encoding="utf-8"):
    if l.strip():
        t = json.loads(l)
        print("\t".join([t["id"], t["source"], str(t["line"]), ",".join(t["mutant_rules"]), t["original_sha256"],
                         t["mutant_sha256"], t["commit"]]))
