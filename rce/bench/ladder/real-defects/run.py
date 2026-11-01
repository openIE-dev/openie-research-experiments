#!/usr/bin/env python3
"""Run the exact-proposer ladder (`rce repair`, spec 10.13) over the
real-defect task set, with a wall-time cap per task.

    python3 run.py RCE TASKS.jsonl OUTDIR [CAP_S]

The same procedure as scripts/ladder-run.py of openIE-dev/rce at the ladder
commit (which the first registered run used), with two differences that the
registration states: each `rce repair json FILE` call is stopped after CAP_S
seconds (default 900), and a stopped task counts as not closed (`time cap`);
and the rows and totals are also split by task source. For each closed task
the repair is compared with the original program:

  - restored: `rce hash` gives the repair and the original the same program
    hash;
  - behaviour-equal: `rce equiv fuel 2000` exits 0;
  - examples only: `rce equiv` exits 1 (a distinguishing event sequence);
  - undecided: `rce equiv` exits 3 (fuel bound);
  - not compared: `rce equiv` cannot compare the two (for example a program
    of functions only).

No model is called by this script or by `rce repair`.
"""
import hashlib, json, subprocess, sys, tempfile, time
from pathlib import Path

RUNGS = ("a", "b", "c", "d")
SPLIT = ("restored", "behaviour-equal", "examples only", "undecided", "not compared")


def program_hash(rce, f):
    r = subprocess.run([rce, "hash", str(f)], capture_output=True, text=True)
    lines = [l for l in r.stdout.splitlines() if l.endswith("  program")]
    return lines[-1].split()[0] if r.returncode == 0 and lines else None


def main(argv):
    if len(argv) not in (3, 4):
        sys.exit("usage: run.py RCE TASKS.jsonl OUTDIR [CAP_S]")
    rce, tasks_path, outdir = argv[0], Path(argv[1]), Path(argv[2])
    cap = int(argv[3]) if len(argv) == 4 else 900
    outdir.mkdir(parents=True, exist_ok=True)
    tasks = [json.loads(l) for l in tasks_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    tmp = Path(tempfile.mkdtemp(prefix="ladder-real-run-"))
    rows = []
    t_all = time.time()
    for t in tasks:
        name = Path(t["path"]).name
        orig, mut = tmp / ("orig-" + name), tmp / name
        orig.write_text(t["original"], encoding="utf-8")
        mut.write_text(t["mutant"], encoding="utf-8")
        t0 = time.time()
        capped = False
        try:
            r = subprocess.run([rce, "repair", "json", str(mut)], capture_output=True, text=True, timeout=cap)
            out, code = r.stdout, r.returncode
            try:
                rep = json.loads(out)
            except ValueError:
                rep = {"closed": False, "rung": None, "tried": {}, "verdict": (r.stdout + r.stderr)[:300], "attempts": []}
        except subprocess.TimeoutExpired:
            capped, code = True, None
            rep = {"closed": False, "rung": None, "tried": {}, "verdict": f"time cap: stopped after {cap} s", "attempts": []}
        wall = time.time() - t0
        row = {"id": t["id"], "source": t["source"], "path": t["path"], "exit": code, "wall_s": round(wall, 3),
               "time_cap": capped, "closed": rep.get("closed", False), "rung": rep.get("rung"), "tried": rep.get("tried", {}),
               "edit": rep.get("edit"), "diff": rep.get("diff"), "verdict": rep.get("verdict"), "skipped": rep.get("skipped", []),
               "model_calls": rep.get("model_calls", 0), "mutant_rules": t.get("mutant_rules", []),
               "attempts": rep.get("attempts", [])}
        if row["closed"] and rep.get("repaired"):
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
        print(f"{t['id']}: {'closed ' + str(row['rung']) if row['closed'] else 'not closed'}"
              f" {row.get('equivalence', '')}{' (time cap)' if capped else ''}"
              f" ({sum(row['tried'].values())} tried, {row['wall_s']} s)", flush=True)
    wall_all = time.time() - t_all

    def totals(rs):
        closed = [r for r in rs if r["closed"]]
        eq = {k: sum(1 for r in closed if r.get("equivalence") == k) for k in SPLIT}
        return {"tasks": len(rs), "closed": len(closed), "not_closed": len(rs) - len(closed),
                "time_cap": sum(1 for r in rs if r["time_cap"]),
                "closed_per_rung": {k: sum(1 for r in closed if r["rung"] == k) for k in RUNGS},
                "equivalence": eq,
                "candidates_tried": {k: sum(r["tried"].get(k, 0) for r in rs) for k in RUNGS}}

    sources = sorted({r["source"] for r in rows})
    summary = {"format": "rce-ladder-real-defects-summary/1", "rce_sha256": hashlib.sha256(Path(rce).read_bytes()).hexdigest(),
               "tasks_sha256": hashlib.sha256(tasks_path.read_bytes()).hexdigest(), "cap_s": cap, "bound": 2000,
               "all": totals(rows), "by_source": {s: totals([r for r in rows if r["source"] == s]) for s in sources},
               "model_calls": sum(r["model_calls"] for r in rows), "wall_s_total": round(wall_all, 1),
               "wall_s_median": sorted(r["wall_s"] for r in rows)[len(rows) // 2] if rows else None}
    with open(outdir / "runs.jsonl", "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n")
    with open(outdir / "runs.compact.tsv", "w", encoding="utf-8") as fh:
        fh.write("id\tsource\tclosed\trung\tcandidates\twall_s\ttime_cap\tequivalence\tmutant_rules\tedit\n")
        for r in rows:
            fh.write("\t".join([r["id"], r["source"], str(r["closed"]).lower(), str(r["rung"] or ""), str(sum(r["tried"].values())),
                                str(r["wall_s"]), str(r["time_cap"]).lower(), r.get("equivalence", ""), ",".join(r["mutant_rules"]),
                                (r["edit"] or "").replace("\t", " ").replace("\n", " ")]) + "\n")
    (outdir / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=1, sort_keys=True))


if __name__ == "__main__":
    main(sys.argv[1:])
