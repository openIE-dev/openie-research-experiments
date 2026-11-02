#!/usr/bin/env python3
"""The report of the third registered ladder run, from its raw results.

    python3 -I report.py RESULTS RUN2_RESULTS

RESULTS holds plain/ and known/ (each runs.compact.tsv and summary.json, and
rerun-killed/ when the registration's one rerun was made); RUN2_RESULTS is
real-defects/results (runs.compact.tsv and rerun-killed/runs.compact.tsv).
A row of rerun-killed/ replaces the row of the same task. Writes
RESULTS/REPORT.md and RESULTS/report.json; every number in them is computed
here from those files, and each prediction and falsifier of PREREG.json is
evaluated by the rule written next to it below.
"""
import json, sys
from pathlib import Path

RUNGS = ("a", "b", "c", "d", "e")
SPLIT = ("restored", "behaviour-equal", "examples only", "undecided", "not compared")
SOURCES = ("history-admit", "history-fix", "guard", "rename")
NESTED = "spec/examples/29_nested_kind.rce@013e21ed"


def tsv(p):
    lines = Path(p).read_text(encoding="utf-8").splitlines()
    head = lines[0].split("\t")
    return [dict(zip(head, l.split("\t"))) for l in lines[1:] if l.strip()]


def merged(d):
    rows = tsv(d / "runs.compact.tsv")
    rr = d / "rerun-killed" / "runs.compact.tsv"
    rerun = {r["id"]: r for r in tsv(rr)} if rr.exists() else {}
    return [rerun.get(r["id"], r) for r in rows], sorted(rerun)


def stats(rs):
    closed = [r for r in rs if r["closed"] == "true"]
    eq = {k: sum(1 for r in closed if r["equivalence"] == k) for k in SPLIT}
    out = {"tasks": len(rs), "closed": len(closed), "not_closed": len(rs) - len(closed),
           "closed_per_rung": {k: sum(1 for r in closed if r["rung"] == k) for k in RUNGS},
           "equivalence": eq, "behaves_the_same": eq["restored"] + eq["behaviour-equal"]}
    if rs and "tried_a" in rs[0]:
        out.update({"admitted_as_given": sum(1 for r in rs if r["rung"] == "none"),
                    "time_cap": sum(1 for r in rs if r["time_cap"] == "true"),
                    "closed_e_known": sum(1 for r in closed if r["e_known"] == "true"),
                    "closed_e_search": sum(1 for r in closed if r["rung"] == "e" and r["e_known"] != "true"),
                    "candidates_tried": {k: sum(int(r["tried_" + k]) for r in rs) for k in RUNGS},
                    "candidates_tried_total": sum(int(r["candidates"]) for r in rs),
                    "original_admitted": sum(1 for r in rs if r["original_check"] == "0"),
                    "mutant_requires_change": sum(1 for r in rs if r["mutant_check"] != "0"),
                    "killed": sum(1 for r in rs if r["exit"] not in ("None", "") and int(r["exit"]) < 0)})
    return out


def by_source(rs):
    d = {s: stats([r for r in rs if r["source"] == s]) for s in SOURCES}
    d["history"] = stats([r for r in rs if r["source"].startswith("history")])
    d["guard+rename"] = stats([r for r in rs if r["source"] in ("guard", "rename")])
    d["all"] = stats(rs)
    return d


def outcome(r):
    return (r["closed"], r["rung"] if r["closed"] == "true" else "", r["equivalence"] if r["closed"] == "true" else "")


def main(argv):
    res, run2 = Path(argv[0]), Path(argv[1])
    plain, plain_rerun = merged(res / "plain")
    known, known_rerun = merged(res / "known")
    r2, r2_rerun = merged(run2)
    sp, sk, s2 = by_source(plain), by_source(known), by_source(r2)
    summ = {a: json.loads((res / a / "summary.json").read_text()) for a in ("plain", "known")}
    P = {r["id"]: r for r in plain}
    K = {r["id"]: r for r in known}
    R2 = {r["id"]: r for r in r2}
    model_calls = {a: summ[a]["model_calls"] for a in summ}

    # ---- per-task changes
    vs2 = [(i, outcome(R2[i]), outcome(P[i])) for i in P if outcome(P[i]) != outcome(R2[i])]
    kvp = [(i, outcome(P[i]), outcome(K[i])) for i in P if outcome(P[i]) != outcome(K[i])]
    gh = [i for i in P if not P[i]["source"] == "rename"]
    ren = [i for i in P if P[i]["source"] == "rename"]
    ren_ok = [i for i in ren if K[i]["original_check"] == "0"]

    # ---- predictions (rule next to each)
    g, rn, hi, al = sp["guard"], sp["rename"], sp["history"], sp["all"]
    gr_cand = sp["guard+rename"]["candidates_tried_total"]
    preds = {
        # P1: plain rename: closed >= 75 and restored >= 70
        "P1": rn["closed"] >= 75 and rn["equivalence"]["restored"] >= 70,
        # P2: plain guard: 27 closed, all at d, 25 restored, each task's outcome as in run 2
        "P2": g["closed"] == 27 and g["closed_per_rung"]["d"] == 27 and g["equivalence"]["restored"] == 25
        and all(outcome(P[i]) == outcome(R2[i]) for i in P if P[i]["source"] == "guard"),
        # P3: plain history: at most 4 of 41 closed, and NESTED closed at c, restored
        "P3": hi["closed"] <= 4 and outcome(P[NESTED]) == ("true", "c", "restored"),
        # P4: plain all: 105 <= closed <= 115 and behaves the same >= 85% of closed
        "P4": 105 <= al["closed"] <= 115 and al["behaves_the_same"] >= 0.85 * al["closed"],
        # P5: plain guard+rename candidates judged in [5900, 7200]
        "P5": 5900 <= gr_cand <= 7200,
        # P6: known: every rename task whose original the checker admits closes by the renaming onto GOOD
        #     and is restored; every guard and history task has the plain arm's outcome
        "P6": all(K[i]["closed"] == "true" and K[i]["e_known"] == "true" and K[i]["equivalence"] == "restored" for i in ren_ok)
        and all(outcome(K[i]) == outcome(P[i]) for i in gh),
        # P7: model calls 0 in both arms
        "P7": model_calls["plain"] == 0 and model_calls["known"] == 0,
    }
    run2_closed_gh = [i for i in gh if R2[i]["closed"] == "true"]
    fals = {
        # F1: met when plain closes fewer than 42 of 83 rename tasks
        "F1": rn["closed"] < 42,
        # F2: met when plain rename behaves the same is below 80% of plain rename closed
        "F2": rn["closed"] > 0 and rn["behaves_the_same"] < 0.8 * rn["closed"],
        # F3: met when a guard or history task closed in run 2 is not closed in plain, or its equivalence differs
        "F3": any(P[i]["closed"] != "true" or P[i]["equivalence"] != R2[i]["equivalence"] for i in run2_closed_gh),
        # F4: met when plain rename closed != 83, rename restored != 77, or guard+rename restored != 102
        "F4": rn["closed"] != 83 or rn["equivalence"]["restored"] != 77 or sp["guard+rename"]["equivalence"]["restored"] != 102,
        # F5: met when a rename task whose original the checker admits is not restored in known
        "F5": any(K[i]["equivalence"] != "restored" for i in ren_ok),
        # F6: met when any task reports a model call
        "F6": model_calls["plain"] != 0 or model_calls["known"] != 0,
    }

    out = {"format": "rce-ladder-run3-report/1", "rce_sha256": summ["plain"]["rce_sha256"],
           "tasks_sha256": summ["plain"]["tasks_sha256"], "plain": sp, "known": sk, "run2": s2,
           "rerun_killed": {"plain": plain_rerun, "known": known_rerun},
           "candidates_guard_rename_plain": gr_cand, "model_calls": model_calls,
           "wall_s": {a: {"total": summ[a]["wall_s_total"], "median": summ[a]["wall_s_median"], "max": summ[a]["wall_s_max"]} for a in summ},
           "predictions_hold": preds, "falsifiers_met": fals,
           "changed_vs_run2_plain": [{"id": i, "run2": a, "run3": b} for i, a, b in vs2],
           "known_differs_from_plain": [{"id": i, "plain": a, "known": b} for i, a, b in kvp],
           "rename_original_admitted": len(ren_ok)}
    (res / "report.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")

    # ---- REPORT.md
    L = []
    w = L.append
    w("# Ladder run 3: rungs a to e on the frozen tasks of run 2")
    w("")
    w(f"`rce` SHA-256 `{out['rce_sha256']}`; task set SHA-256 `{out['tasks_sha256']}` ({al['tasks']} tasks); "
      f"bound 2000; cap {summ['plain']['cap_s']} s per `rce repair` call.")
    w("")
    w(f"- plain arm: `{summ['plain']['command']}`")
    w(f"- known arm: `{summ['known']['command']}` (ORIGINAL is the task's original text)")
    w("")
    if plain_rerun or known_rerun:
        w(f"Rows from the one rerun of tasks ended by a signal: plain {len(plain_rerun)}, known {len(known_rerun)}.")
        w("")
    w("## Closed per rung")
    w("")
    cols = ["history-admit", "history-fix", "guard", "rename", "all"]
    for arm, s in (("plain", sp), ("known", sk)):
        w(f"### {arm} arm")
        w("")
        w("| Rung | " + " | ".join(f"{c} ({s[c]['tasks']})" for c in cols) + " |")
        w("|---|" + "---:|" * len(cols))
        for k in RUNGS:
            w(f"| {k} | " + " | ".join(str(s[c]["closed_per_rung"][k]) for c in cols) + " |")
        w("| e by the renaming onto GOOD | " + " | ".join(str(s[c]["closed_e_known"]) for c in cols) + " |")
        w("| e by search | " + " | ".join(str(s[c]["closed_e_search"]) for c in cols) + " |")
        w("| closed | " + " | ".join(str(s[c]["closed"]) for c in cols) + " |")
        w("| not closed | " + " | ".join(str(s[c]["not_closed"]) for c in cols) + " |")
        w("| of which admitted as given | " + " | ".join(str(s[c]["admitted_as_given"]) for c in cols) + " |")
        w("| of which time cap | " + " | ".join(str(s[c]["time_cap"]) for c in cols) + " |")
        w("")
        w("| Closed repair compared with the original | " + " | ".join(cols) + " |")
        w("|---|" + "---:|" * len(cols))
        for k in SPLIT:
            w(f"| {k} | " + " | ".join(str(s[c]["equivalence"][k]) for c in cols) + " |")
        w("| behaves the same (restored + behaviour-equal) | " + " | ".join(str(s[c]["behaves_the_same"]) for c in cols) + " |")
        w("")
        w("| Candidates judged | " + " | ".join(cols) + " |")
        w("|---|" + "---:|" * len(cols))
        for k in RUNGS:
            w(f"| {k} | " + " | ".join(str(s[c]["candidates_tried"][k]) for c in cols) + " |")
        w("| total | " + " | ".join(str(s[c]["candidates_tried_total"]) for c in cols) + " |")
        w("")
        w(f"Model calls reported: {model_calls[arm]}. Originals the pinned checker admits: {s['all']['original_admitted']} of {al['tasks']}; "
          f"mutants it reports as requiring change: {s['all']['mutant_requires_change']} of {al['tasks']}. Tasks ended by a signal: {s['all']['killed']}. "
          f"Wall time {out['wall_s'][arm]['total']} s, median {out['wall_s'][arm]['median']} s per task, longest {out['wall_s'][arm]['max']} s.")
        w("")
    w("## Against run 2 (registered, rungs a to d)")
    w("")
    w("| Source | Run 2 closed | Run 3 plain closed | Run 3 known closed | Run 2 restored | Run 3 plain restored | Run 3 known restored | Run 2 behaves the same | Run 3 plain behaves the same | Run 3 known behaves the same |")
    w("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for c in ("history", "guard", "rename", "guard+rename", "all"):
        w(f"| {c} ({s2[c]['tasks']}) | {s2[c]['closed']} | {sp[c]['closed']} | {sk[c]['closed']} | "
          f"{s2[c]['equivalence']['restored']} | {sp[c]['equivalence']['restored']} | {sk[c]['equivalence']['restored']} | "
          f"{s2[c]['behaves_the_same']} | {sp[c]['behaves_the_same']} | {sk[c]['behaves_the_same']} |")
    w("")
    w(f"Tasks whose outcome (closed, rung, equivalence) differs between run 2 and the run 3 plain arm: {len(vs2)} "
      f"(history {sum(1 for i, _, _ in vs2 if P[i]['source'].startswith('history'))}, guard {sum(1 for i, _, _ in vs2 if P[i]['source'] == 'guard')}, "
      f"rename {sum(1 for i, _, _ in vs2 if P[i]['source'] == 'rename')}).")
    w("")
    for i, a, b in vs2:
        if not P[i]["source"] == "rename":
            w(f"- `{i}`: run 2 {a}, run 3 plain {b}")
    w("")
    w("Rename tasks closed in the plain arm and not restored:")
    w("")
    for i in ren:
        if P[i]["closed"] == "true" and P[i]["equivalence"] != "restored":
            w(f"- `{i}` ({P[i]['equivalence']}, rung {P[i]['rung']}): {P[i]['edit'][:200]}")
    w("")
    w("Rename tasks not closed in the plain arm:")
    w("")
    for i in ren:
        if P[i]["closed"] != "true":
            w(f"- `{i}` (exit {P[i]['exit']}, rung {P[i]['rung'] or '-'}, {P[i]['candidates']} candidates)")
    w("")
    w(f"## Known arm against plain arm")
    w("")
    w(f"Tasks whose outcome differs: {len(kvp)} (rename {sum(1 for i, _, _ in kvp if P[i]['source'] == 'rename')}, "
      f"other {sum(1 for i, _, _ in kvp if P[i]['source'] != 'rename')}). Rename tasks whose original the pinned checker admits: {len(ren_ok)} of {len(ren)}.")
    w("")
    for i, a, b in kvp:
        if P[i]["source"] != "rename":
            w(f"- `{i}`: plain {a}, known {b}")
    w("")
    w("## Predictions and falsifiers (rules in PREREG.json, evaluated by report.py)")
    w("")
    w("| Prediction | Holds |")
    w("|---|---|")
    for k, v in preds.items():
        w(f"| {k} | {'yes' if v else 'no'} |")
    w("")
    w(f"P5 input: candidates judged on guard and rename tasks, plain arm: {gr_cand}.")
    w("")
    w("| Falsifier | Met (claim false on this set) |")
    w("|---|---|")
    for k, v in fals.items():
        w(f"| {k} | {'yes' if v else 'no'} |")
    w("")
    (res / "REPORT.md").write_text("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    main(sys.argv[1:])
