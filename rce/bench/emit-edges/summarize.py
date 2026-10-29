#!/usr/bin/env python3
"""Track T4 (emit-edges): the summary of one run of tests/emit_edges.rs.

Usage: summarize.py RAW_DIR OUT_DIR COMMIT

RAW_DIR is the directory the test wrote under RCE_EMIT_EDGES_OUT. This
script copies the per-example rows, writes one row per target to
targets.jsonl, and writes summary.json: only fields that do not depend on
the run host (the tool versions are in targets.jsonl, not in the summary),
as canonical JSON (sorted keys, two-space indent). It prints the SHA-256 of
summary.json, the summary digest of PREREG.json. Standard library only.
"""
import hashlib
import json
import pathlib
import shutil
import sys

TARGETS = ["rust", "python", "js", "scala", "wasm32-wasip1"]


def main():
    raw, out, commit = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), sys.argv[3]
    out.mkdir(parents=True, exist_ok=True)
    ref = json.loads((raw / "reference.json").read_text())
    for name in ["examples.jsonl", "module.rce"]:
        shutil.copyfile(raw / name, out / name)
    rows, agrees, skipped, absent = [], [], [], []
    for t in TARGETS:
        p = raw / f"target-{t}.json"
        if not p.exists():
            absent.append(t)  # the test ended before it wrote a row: a difference or a failed run
            rows.append({"target": t, "outcome": "no row"})
            continue
        row = json.loads(p.read_text())
        rows.append(row)
        if row["outcome"] == "agrees":
            ok = (
                row["line_for_line"] and row["byte_for_byte"] and row["d_heads"]
                and row["stdout_sha256"] == ref["observation_sha256"]
                and row["heads_sha256"] == ref["heads_sha256"]
            )
            (agrees if ok else absent).append(t)
        else:
            skipped.append(t)
    (out / "targets.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    summary = {
        "track": "T4 emit-edges",
        "run_commit": commit,
        "reference": ref,
        "targets_agreeing": agrees,
        "targets_skipped": skipped,
        "targets_without_agreement": absent,
        "verdict": "every target that ran agrees" if agrees and not absent else "a target differs or did not run",
    }
    text = json.dumps(summary, sort_keys=True, indent=2) + "\n"
    (out / "summary.json").write_text(text)
    digest = hashlib.sha256(text.encode()).hexdigest()
    (out / "summary.json.sha256").write_text(f"{digest}  summary.json\n")
    print(digest)
    return 0 if agrees and not absent else 1


if __name__ == "__main__":
    sys.exit(main())
