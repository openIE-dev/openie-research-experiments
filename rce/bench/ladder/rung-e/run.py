#!/usr/bin/env python3
"""Run the exact-proposer ladder (`rce repair`, spec 10.13, rungs a to e)
over the frozen task set of the second registered run, in one arm.

    python3 -I run.py RCE TASKS.jsonl OUTDIR ARM [CAP_S]

ARM is `plain` or `known`:

  plain   rce repair json FILE
  known   rce repair json known ORIGINAL FILE

FILE holds the task's mutant; in the `known` arm ORIGINAL holds the task's
original text, given as the known-good version. Each `rce repair` call is
stopped after CAP_S seconds (default 900) and then counts as not closed
(time cap), as in the second run's run.py. Before the repair, `rce check`
runs on the original and on the mutant (standalone) and both exit codes are
recorded.

A task is closed when `rce repair` reports `closed` with a rung a to e. A
mutant the checker admits as given (`rung` "none") is not closed and is
counted apart (`admitted as given`). For each closed task the repair is
compared with the original program:

  - restored: `rce hash` gives the repair and the original the same program
    hash;
  - behaviour-equal: `rce equiv fuel 2000` exits 0;
  - examples only: `rce equiv` exits 1 (a distinguishing event sequence);
  - undecided: `rce equiv` exits 3 (fuel bound);
  - not compared: `rce equiv` cannot compare the two.

A rung e closure whose edit begins "the renaming onto" is the renaming read
from `known GOOD` (no search) and is counted as `e-known`; every other rung e
closure is `e-search`. No model is called by this script or by `rce repair`;
`model_calls` is the count `rce repair json` reports per task.
"""
import hashlib, json, subprocess, sys, tempfile, time
from pathlib import Path

RUNGS = ("a", "b", "c", "d", "e")
SPLIT = ("restored", "behaviour-equal", "examples only", "undecided", "not compared")


def program_hash(rce, f):
    r = subprocess.run([rce, "hash", str(f)], capture_output=True, text=True)
    lines = [l for l in r.stdout.splitlines() if l.endswith("  program")]
    return lines[-1].split()[0] if r.returncode == 0 and lines else None


def totals(rs):
    closed = [r for r in rs if r["closed"]]
    eq = {k: sum(1 for r in closed if r.get("equivalence") == k) for k in SPLIT}
    return {"tasks": len(rs), "closed": len(closed), "not_closed": len(rs) - len(closed),
            "admitted_as_given": sum(1 for r in rs if r["rung"] == "none"),
            "time_cap": sum(1 for r in rs if r["time_cap"]),
            "closed_per_rung": {k: sum(1 for r in closed if r["rung"] == k) for k in RUNGS},
            "closed_e_known": sum(1 for r in closed if r["e_known"]),
            "closed_e_search": sum(1 for r in closed if r["rung"] == "e" and not r["e_known"]),
            "equivalence": eq,
            "behaves_the_same": eq["restored"] + eq["behaviour-equal"],
            "candidates_tried": {k: sum(r["tried"].get(k, 0) for r in rs) for k in RUNGS},
            "candidates_tried_total": sum(sum(r["tried"].get(k, 0) for k in RUNGS) for r in rs),
            "model_calls": sum(r["model_calls"] for r in rs),
            "original_admitted": sum(1 for r in rs if r["original_check"] == 0),
            "mutant_requires_change": sum(1 for r in rs if r["mutant_check"] != 0)}


def main(argv):
    if len(argv) not in (4, 5) or argv[3] not in ("plain", "known"):
        sys.exit("usage: run.py RCE TASKS.jsonl OUTDIR plain|known [CAP_S]")
    rce, tasks_path, outdir, arm = argv[0], Path(argv[1]), Path(argv[2]), argv[3]
    cap = int(argv[4]) if len(argv) == 5 else 900
    outdir.mkdir(parents=True, exist_ok=True)
    tasks = [json.loads(l) for l in tasks_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    tmp = Path(tempfile.mkdtemp(prefix="ladder-run3-"))
    rows = []
    t_all = time.time()
    for t in tasks:
        name = Path(t["path"]).name
        orig, mut = tmp / ("orig-" + name), tmp / name
        orig.write_text(t["original"], encoding="utf-8")
        mut.write_text(t["mutant"], encoding="utf-8")
        oc = subprocess.run([rce, "check", str(orig)], capture_output=True, text=True).returncode
        mc = subprocess.run([rce, "check", str(mut)], capture_output=True, text=True).returncode
        cmd = [rce, "repair", "json"] + (["known", str(orig)] if arm == "known" else []) + [str(mut)]
        t0 = time.time()
        capped = False
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=cap)
            code = r.returncode
            try:
                rep = json.loads(r.stdout)
            except ValueError:
                rep = {"closed": False, "rung": None, "tried": {}, "verdict": (r.stdout + r.stderr)[:300], "attempts": []}
        except subprocess.TimeoutExpired:
            capped, code = True, None
            rep = {"closed": False, "rung": None, "tried": {}, "verdict": f"time cap: stopped after {cap} s", "attempts": []}
        wall = time.time() - t0
        rung = rep.get("rung")
        closed = bool(rep.get("closed", False)) and rung in RUNGS
        edit = rep.get("edit")
        row = {"id": t["id"], "source": t["source"], "path": t["path"], "arm": arm, "exit": code, "wall_s": round(wall, 3),
               "time_cap": capped, "closed": closed, "rung": rung, "tried": rep.get("tried", {}),
               "e_known": closed and rung == "e" and (edit or "").startswith("the renaming onto"),
               "edit": edit, "diff": rep.get("diff"), "verdict": rep.get("verdict"), "skipped": rep.get("skipped", []),
               "model_calls": rep.get("model_calls", 0), "mutant_rules": t.get("mutant_rules", []),
               "original_check": oc, "mutant_check": mc, "attempts": rep.get("attempts", [])}
        if closed and rep.get("repaired"):
            fixed = tmp / ("fixed-" + name)
            fixed.write_text(rep["repaired"], encoding="utf-8")
            ho, hf = program_hash(rce, orig), program_hash(rce, fixed)
            if ho and ho == hf:
                row["equivalence"] = "restored"
            else:
                e = subprocess.run([rce, "equiv", "fuel", "2000", str(orig), str(fixed)], capture_output=True, text=True)
                row["equiv_exit"] = e.returncode
                row["equivalence"] = {0: "behaviour-equal", 1: "examples only", 3: "undecided"}.get(e.returncode, "not compared")
                if row["equivalence"] == "not compared":
                    row["equiv_note"] = (e.stdout + e.stderr).strip()[:200]
            fixed.unlink()
        rows.append(row)
        orig.unlink()
        mut.unlink()
        print(f"{arm} {t['id']}: {'closed ' + str(rung) if closed else 'not closed'}"
              f" {row.get('equivalence', '')}{' (time cap)' if capped else ''}"
              f" ({sum(row['tried'].values())} tried, {row['wall_s']} s, exit {code})", flush=True)
    wall_all = time.time() - t_all
    sources = sorted({r["source"] for r in rows})
    summary = {"format": "rce-ladder-run3-summary/1", "arm": arm, "command": " ".join(["rce", "repair", "json"] + (["known", "ORIGINAL"] if arm == "known" else []) + ["FILE"]),
               "rce_sha256": hashlib.sha256(Path(rce).read_bytes()).hexdigest(),
               "tasks_sha256": hashlib.sha256(tasks_path.read_bytes()).hexdigest(), "cap_s": cap, "bound": 2000,
               "all": totals(rows), "by_source": {s: totals([r for r in rows if r["source"] == s]) for s in sources},
               "exit_codes": {str(k): sum(1 for r in rows if r["exit"] == k) for k in sorted({r["exit"] for r in rows}, key=str)},
               "model_calls": sum(r["model_calls"] for r in rows), "wall_s_total": round(wall_all, 1),
               "wall_s_median": sorted(r["wall_s"] for r in rows)[len(rows) // 2] if rows else None,
               "wall_s_max": max(r["wall_s"] for r in rows) if rows else None}
    with open(outdir / "runs.jsonl", "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n")
    with open(outdir / "runs.compact.tsv", "w", encoding="utf-8") as fh:
        fh.write("id\tsource\tarm\texit\tclosed\trung\te_known\tcandidates\ttried_a\ttried_b\ttried_c\ttried_d\ttried_e\twall_s\ttime_cap\tequivalence\toriginal_check\tmutant_check\tmutant_rules\tedit\n")
        for r in rows:
            fh.write("\t".join([r["id"], r["source"], arm, str(r["exit"]), str(r["closed"]).lower(), str(r["rung"] or ""),
                                str(r["e_known"]).lower(), str(sum(r["tried"].values())), *[str(r["tried"].get(k, 0)) for k in RUNGS], str(r["wall_s"]), str(r["time_cap"]).lower(),
                                r.get("equivalence", ""), str(r["original_check"]), str(r["mutant_check"]), ",".join(r["mutant_rules"]),
                                (r["edit"] or "").replace("\t", " ").replace("\n", " ")[:400]]) + "\n")
    (outdir / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
    print(json.dumps(summary["all"], indent=1, sort_keys=True))


if __name__ == "__main__":
    main(sys.argv[1:])
