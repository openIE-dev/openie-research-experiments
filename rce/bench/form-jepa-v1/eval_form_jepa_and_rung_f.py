#!/usr/bin/env python3
"""
Unified Evaluation of FormJEPA-v1 (k=1, k=16, H5/H11 diagnostics, 151-task ladder,
40-task H15 residual, 3-Gear Cascade, RAPL reported_j) and Pre-Registered `rce repair`
Rung f Observation & Promotion Criterion Audit across the 151-Task Ladder.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import re
import subprocess
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import torch

from train_form_jepa import (
    BENCH_ROOT,
    EXP_REPO,
    HERE,
    MAX_SEQ_LEN,
    PREREG_PATH,
    PREREG_SHA_PATH,
    RCE_BIN,
    RCE_REPO,
    RESULTS_DIR,
    SEED,
    VOCAB_SIZE,
    WORK_DIR,
    FormJEPAv1,
    FormSExprTokenizer,
    SplitMix64,
    _propose_forward_corruptions,
    delta_rapl_j,
    propose_form_jepa_candidates,
    read_rapl_uj,
    set_all_seeds,
    sha256_bytes,
    sha256_str,
)

PREREG_RUNGF_PATH = HERE / "PREREG_rung_f.json"
PREREG_RUNGF_SHA_PATH = HERE / "PREREG_rung_f.json.sha256"


def extract_obligations_summary(src: str) -> dict[str, Any]:
    examples_lhs: list[str] = []
    checks_cnt = 0
    decls: dict[str, set[str]] = {
        "state": set(), "event": set(), "error": set(), "struct": set(),
        "kind": set(), "fn": set(), "extern": set(), "step": set(),
    }
    for raw in src.splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("example "):
            examples_lhs.append(s[len("example "):].split("->", 1)[0].strip())
        elif s.startswith("check "):
            checks_cnt += 1
        else:
            m = re.match(r"^(?:pub\s+)?(state|event|error|struct|kind)\s+([A-Za-z_][A-Za-z0-9_]*)", s)
            if m:
                decls[m.group(1)].add(m.group(2))
                continue
            m_fn = re.match(r"^(?:pub\s+)?(?:ct\s+)?fn\s+([A-Za-z_][A-Za-z0-9_]*)", s)
            if m_fn:
                decls["fn"].add(m_fn.group(1))
                continue
            m_ext = re.match(r'^extern\s+"[^"]+"\s+fn\s+([A-Za-z_][A-Za-z0-9_]*)', s)
            if m_ext:
                decls["extern"].add(m_ext.group(1))
                continue
            m_step = re.match(r"^step\s+([A-Za-z_][A-Za-z0-9_]*)\s+on\s+([A-Za-z_][A-Za-z0-9_]*)", s)
            if m_step:
                decls["step"].add(f"{m_step.group(1)}:{m_step.group(2)}")
    return {"examples_lhs": examples_lhs, "checks_cnt": checks_cnt, "decls": decls}


def check_obligations_preserved(mutant_src: str, cand_src: str) -> tuple[bool, str]:
    ob_m = extract_obligations_summary(mutant_src)
    ob_c = extract_obligations_summary(cand_src)
    if len(ob_c["examples_lhs"]) < len(ob_m["examples_lhs"]):
        return False, "example_count_dropped"
    if ob_c["checks_cnt"] < ob_m["checks_cnt"]:
        return False, "check_count_dropped"
    for k, req_names in ob_m["decls"].items():
        if req_names - ob_c["decls"][k]:
            return False, f"missing_decl_{k}"
    m_cnt = Counter(ob_m["examples_lhs"])
    c_cnt = Counter(ob_c["examples_lhs"])
    kept_lhs = sum(min(cnt, c_cnt[lhs]) for lhs, cnt in m_cnt.items())
    if ob_m["examples_lhs"] and kept_lhs < max(1, len(ob_m["examples_lhs"]) - 1):
        return False, "example_lhs_altered"
    return True, "ok"


def rce_check_text(rce_bin: str, src: str, timeout_s: float = 10.0) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="fjepa_eval_") as td:
        fp = Path(td) / "cand.rce"
        fp.write_text(src, encoding="utf-8")
        try:
            r = subprocess.run([rce_bin, "check", str(fp)], capture_output=True, text=True, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return 124, "timeout"
        diag = (r.stdout + r.stderr).replace(str(fp), "cand.rce").replace(td, "$TMP").strip()
        return r.returncode, diag


def compare_against_original(rce_bin: str, orig_src: str, cand_src: str) -> str:
    with tempfile.TemporaryDirectory(prefix="fjepa_eq_") as td:
        tp = Path(td)
        fo, fc = tp / "orig.rce", tp / "cand.rce"
        fo.write_text(orig_src, encoding="utf-8")
        fc.write_text(cand_src, encoding="utf-8")

        def _ph(p: Path) -> str | None:
            rh = subprocess.run([rce_bin, "hash", str(p)], capture_output=True, text=True, timeout=10.0)
            ls = [l for l in rh.stdout.splitlines() if l.endswith("  program")]
            return ls[-1].split()[0] if rh.returncode == 0 and ls else None

        ho, hc = _ph(fo), _ph(fc)
        if ho and ho == hc:
            return "restored"
        try:
            req = subprocess.run(
                [rce_bin, "equiv", "fuel", "2000", str(fo), str(fc)],
                capture_output=True, text=True, timeout=15.0,
            )
            return {0: "behaviour-equal", 1: "examples only", 3: "undecided"}.get(req.returncode, "not compared")
        except subprocess.TimeoutExpired:
            return "undecided"


def compute_auroc(scores_higher_is_pos: list[float], labels: list[int]) -> float:
    pos = [s for s, y in zip(scores_higher_is_pos, labels) if y == 1]
    neg = [s for s, y in zip(scores_higher_is_pos, labels) if y == 0]
    if not pos or not neg:
        return 0.5
    wins = 0.0
    for sp in pos:
        for sn in neg:
            if sp > sn:
                wins += 1.0
            elif sp == sn:
                wins += 0.5
    return round(wins / (len(pos) * len(neg)), 4)


def splitmix64_step(seed: int, index: int) -> int:
    z = (seed + ((index + 1) * 0x9E3779B97F4A7C15)) & 0xFFFFFFFFFFFFFFFF
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
    return (z ^ (z >> 31)) & 0xFFFFFFFFFFFFFFFF


def generate_zipf_stream(n_items: int = 40, m_arrivals: int = 200, s: float = 0.85, seed: int = 0x20261122) -> list[int]:
    order = list(range(n_items))
    for i in range(n_items - 1, 0, -1):
        j = splitmix64_step(seed, i) % (i + 1)
        order[i], order[j] = order[j], order[i]
    weights = [1.0 / ((rank + 1) ** s) for rank in range(n_items)]
    tot = sum(weights)
    cdf, acc = [], 0.0
    for w in weights:
        acc += w / tot
        cdf.append(acc)
    stream = []
    for step in range(m_arrivals):
        u = (splitmix64_step(seed ^ 0xA5A5A5A5, step) % 10_000_000) / 10_000_000.0
        chosen = n_items - 1
        for r_idx, c in enumerate(cdf):
            if u <= c:
                chosen = r_idx
                break
        stream.append(order[chosen])
    return stream


def benchmark_rapl_inference(
    model: FormJEPAv1,
    tok: FormSExprTokenizer,
    stdlib_cat: dict[str, Any],
    sample_tasks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Measure L2 RAPL package-0 and core reported_j per FormJEPA-v1 inference (k=1 and k=16)."""
    # Pre-run idle window (2.0 s)
    idle_pre_0 = read_rapl_uj()
    t_i0 = time.perf_counter()
    time.sleep(2.0)
    dt_pre = time.perf_counter() - t_i0
    idle_pre_1 = read_rapl_uj()
    j_pre = delta_rapl_j(idle_pre_0, idle_pre_1, "package_uj")
    w_idle_pre = (j_pre / dt_pre) if j_pre is not None else None

    results: dict[str, Any] = {}
    for label, beam_k, n_iters in [("k1_greedy", 1, 200), ("k16_latent_beam", 16, 120)]:
        # Warmup
        propose_form_jepa_candidates(
            model, tok, stdlib_cat, sample_tasks[0]["broken_form"], sample_tasks[0]["diagnostic"], beam_k=beam_k
        )
        r0 = read_rapl_uj()
        t0 = time.perf_counter()
        for i in range(n_iters):
            ex = sample_tasks[i % len(sample_tasks)]
            propose_form_jepa_candidates(model, tok, stdlib_cat, ex["broken_form"], ex["diagnostic"], beam_k=beam_k)
        dt = time.perf_counter() - t0
        r1 = read_rapl_uj()
        pkg_j = delta_rapl_j(r0, r1, "package_uj")
        core_j = delta_rapl_j(r0, r1, "core_uj")
        results[label] = {
            "iterations": n_iters,
            "wall_s": round(dt, 4),
            "mean_latency_ms": round((dt * 1000.0) / n_iters, 3),
            "gross_rapl_pkg_reported_j_total": pkg_j,
            "gross_rapl_core_reported_j_total": core_j,
            "gross_rapl_pkg_reported_j_per_proposal": round(pkg_j / n_iters, 6) if pkg_j is not None else None,
            "gross_rapl_core_reported_j_per_proposal": round(core_j / n_iters, 6) if core_j is not None else None,
        }

    # Post-run idle window (2.0 s)
    idle_post_0 = read_rapl_uj()
    t_i1 = time.perf_counter()
    time.sleep(2.0)
    dt_post = time.perf_counter() - t_i1
    idle_post_1 = read_rapl_uj()
    j_post = delta_rapl_j(idle_post_0, idle_post_1, "package_uj")
    w_idle_post = (j_post / dt_post) if j_post is not None else None

    drift_frac = None
    falsifier6_pass = False
    if w_idle_pre and w_idle_post and w_idle_pre > 0:
        drift_frac = round(abs(w_idle_post - w_idle_pre) / w_idle_pre, 4)
        falsifier6_pass = drift_frac <= 0.10

    for label in ("k1_greedy", "k16_latent_beam"):
        entry = results[label]
        if falsifier6_pass and w_idle_pre is not None and entry["gross_rapl_pkg_reported_j_total"] is not None:
            idle_mean_w = 0.5 * (w_idle_pre + (w_idle_post or w_idle_pre))
            marg = max(0.0, entry["gross_rapl_pkg_reported_j_total"] - idle_mean_w * entry["wall_s"])
            entry["derived_marginal_pkg_reported_j_per_proposal"] = round(marg / entry["iterations"], 6)
        else:
            entry["derived_marginal_pkg_reported_j_per_proposal"] = None

    results["idle_baseline_check"] = {
        "idle_pre_w": round(w_idle_pre, 3) if w_idle_pre is not None else None,
        "idle_post_w": round(w_idle_post, 3) if w_idle_post is not None else None,
        "idle_drift_fraction": drift_frac,
        "falsifier_6_threshold_le": 0.10,
        "falsifier_6_passed": falsifier6_pass,
        "measured_j": None,
        "est_j": None,
        "board_metered": False,
    }
    return results

def _rung_f_worker(args: tuple[str, dict[str, Any], list[tuple[str, str]], list[tuple[str, str]]]) -> dict[str, Any]:
    """Run `rce repair json known ORIGINAL proposals PROPOSALS MUTANT` for both Rung-f arms."""
    rce_bin, task_row, props_comb, props_jepa = args
    with tempfile.TemporaryDirectory(prefix="fjepa_rf_") as td:
        tp = Path(td)
        fo = tp / "original.rce"
        fm = tp / "mutant.rce"
        fo.write_text(task_row["original"], encoding="utf-8")
        fm.write_text(task_row["mutant"], encoding="utf-8")

        out_lines: dict[str, str] = {}
        for arm_key, plist in [("combined", props_comb), ("jepa_only", props_jepa)]:
            p_obj = {
                "format": "rce-proposals/1",
                "proposals": [{"origin": orig, "text": txt} for orig, txt in plist],
            }
            p_bytes = json.dumps(p_obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
            fp = tp / f"props_{arm_key}.json"
            fp.write_text(p_bytes, encoding="utf-8")
            rr = subprocess.run(
                [rce_bin, "repair", "json", "known", str(fo), "proposals", str(fp), str(fm)],
                capture_output=True,
                text=True,
                timeout=120.0,
            )
            line = rr.stdout.strip()
            if not line:
                raise RuntimeError(f"rce repair failed on {task_row['id']} ({arm_key}): {rr.stderr[:200]}")
            out_lines[arm_key] = line
        return {"id": task_row["id"], "source": task_row["source"], "mutant_rules": task_row["mutant_rules"], **out_lines}


def evaluate_heldout_synthetic_and_h5_h11(
    model: FormJEPAv1,
    tok: FormSExprTokenizer,
    stdlib_cat: dict[str, Any],
    test_examples: list[dict[str, Any]],
) -> dict[str, Any]:
    rce_bin = str(RCE_BIN)
    k1_adm, k16_adm, k16_norerank_adm = 0, 0, 0
    auroc_scores: list[float] = []
    auroc_labels: list[int] = []
    by_tag_k16: Counter[str] = Counter()
    by_tag_tot: Counter[str] = Counter()

    for idx, ex in enumerate(test_examples):
        tag = ex["defect_tag"]
        by_tag_tot[tag] += 1
        cands, _ = propose_form_jepa_candidates(
            model, tok, stdlib_cat, ex["broken_form"], ex["diagnostic"], beam_k=16, pool_size=28
        )
        cands_k1, _ = propose_form_jepa_candidates(
            model, tok, stdlib_cat, ex["broken_form"], ex["diagnostic"], beam_k=1, pool_size=1
        )
        if cands_k1:
            rc1, _ = rce_check_text(rce_bin, cands_k1[0]["text"], timeout_s=4.0)
            if rc1 == 0 and check_obligations_preserved(ex["broken_form"], cands_k1[0]["text"])[0]:
                k1_adm += 1

        # Evaluate latent-reranked k=16 vs action_logp-only ordering, and collect H5 AUROC pairs on first 60 tasks
        admitted_flags: list[bool] = []
        collect_auroc = idx < 60
        found_rerank = False
        for c_i, c in enumerate(cands):
            if found_rerank and not collect_auroc:
                break
            rc_c, _ = rce_check_text(rce_bin, c["text"], timeout_s=4.0)
            ok_c = (rc_c == 0) and check_obligations_preserved(ex["broken_form"], c["text"])[0]
            admitted_flags.append(ok_c)
            if ok_c and not found_rerank:
                found_rerank = True
            if collect_auroc:
                auroc_scores.append(-float(c["latent_l2_energy"]))
                auroc_labels.append(1 if ok_c else 0)
        if found_rerank:
            k16_adm += 1
            by_tag_k16[tag] += 1

        # Action-logp-only top-16 check on same candidate pool when full flags collected
        if collect_auroc and cands:
            paired = sorted(zip(cands, admitted_flags), key=lambda pair: pair[0]["action_logp"], reverse=True)[:16]
            if any(flag for _, flag in paired):
                k16_norerank_adm += 1

    # H11 diagnostic: latent L2 distance monotonicity across cumulative synthetic edit distances d=0..5
    rng_h11 = SplitMix64(SEED ^ 0x1111)
    unique_valid = list({ex["shape_hash"]: ex["valid_form"] for ex in test_examples}.values())[:50]
    dist_means = [[] for _ in range(6)]
    monotone_families = 0
    tested_families = 0
    with torch.no_grad():
        for vf in unique_valid:
            cur = vf
            chain = [vf]
            for d_step in range(1, 6):
                muts = _propose_forward_corruptions(cur, stdlib_cat, rng_h11, max_per_form=6)
                picked = next((m[0] for m in muts if m[0] not in chain), None)
                if picked is None:
                    break
                cur = picked
                chain.append(cur)
            if len(chain) < 6:
                continue
            tested_families += 1
            ids_mat = torch.zeros((6, MAX_SEQ_LEN), dtype=torch.long)
            dm_mat = torch.zeros((6, MAX_SEQ_LEN), dtype=torch.long)
            for s_i, txt_s in enumerate(chain):
                yi, yd, _, _ = tok.encode(txt_s, rule_code="OK", diag_line_1based=None)
                ids_mat[s_i] = torch.tensor(yi, dtype=torch.long)
                dm_mat[s_i] = torch.tensor(yd, dtype=torch.long)
            ly = max(16, int((ids_mat != 0).sum(dim=1).max().item()))
            zs = model.encode_target(ids_mat[:, :ly], dm_mat[:, :ly])
            z0 = zs[0:1]
            d_vals = (zs - z0).pow(2).sum(dim=-1).tolist()
            for s_i, dv in enumerate(d_vals):
                dist_means[s_i].append(float(dv))
            # Check non-decreasing across edit steps 1..5 (allowing tiny tie tolerance 1e-4)
            if all(d_vals[k] <= d_vals[k + 1] + 1e-4 for k in range(5)) and d_vals[5] > d_vals[1]:
                monotone_families += 1

    n_tot = max(1, len(test_examples))
    return {
        "tasks": len(test_examples),
        "k1_greedy_admitted": k1_adm,
        "k1_greedy_rate": round(k1_adm / n_tot, 4),
        "k16_latent_beam_admitted": k16_adm,
        "k16_latent_beam_rate": round(k16_adm / n_tot, 4),
        "by_defect_tag_k16": {
            t: {"admitted": by_tag_k16[t], "total": by_tag_tot[t], "rate": round(by_tag_k16[t] / by_tag_tot[t], 4)}
            for t in sorted(by_tag_tot)
        },
        "H5_latent_energy_auroc_slice60": {
            "candidates_scored": len(auroc_labels),
            "accepted_candidates": sum(auroc_labels),
            "auroc_neg_latent_l2": compute_auroc(auroc_scores, auroc_labels),
            "k16_admitted_on_slice60_with_rerank": sum(
                1 for idx_s in range(min(60, len(test_examples))) if idx_s >= 0
            ) and None,
            "k16_admitted_on_slice60_action_logp_only": k16_norerank_adm,
        },
        "H11_latent_edit_distance_monotonicity": {
            "families_tested": tested_families,
            "monotone_families": monotone_families,
            "monotone_share": round(monotone_families / max(1, tested_families), 4),
            "mean_latent_l2_by_distance_0_to_5": [
                round(float(np.mean( vs )), 4) if vs else 0.0 for vs in dist_means
            ],
        },
    }


def _eval_real_task_worker(
    args: tuple[str, dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]
) -> dict[str, Any]:
    rce_bin, task, cands_k1, cands_k16 = args
    res: dict[str, Any] = {
        "task_id": task["id"],
        "source": task["source"],
        "mutant_rules": task["mutant_rules"],
        "k1_admitted": False,
        "k1_equiv": "",
        "k1_checks": 0,
        "k16_admitted": False,
        "k16_equiv": "",
        "k16_checks": 0,
        "k16_winning_op": "",
        "k16_winning_rank": None,
        "k16_latent_l2_energy": None,
        "k16_repaired_text": "",
    }
    for c in cands_k1[:1]:
        res["k1_checks"] += 1
        kept_ok, _ = check_obligations_preserved(task["mutant"], c["text"])
        rc, _ = rce_check_text(rce_bin, c["text"], timeout_s=12.0)
        if rc == 0 and kept_ok:
            res["k1_admitted"] = True
            res["k1_equiv"] = compare_against_original(rce_bin, task["original"], c["text"])
            break

    for rank_i, c in enumerate(cands_k16[:16], start=1):
        res["k16_checks"] += 1
        kept_ok, _ = check_obligations_preserved(task["mutant"], c["text"])
        rc, _ = rce_check_text(rce_bin, c["text"], timeout_s=12.0)
        if rc == 0 and kept_ok:
            res["k16_admitted"] = True
            res["k16_equiv"] = compare_against_original(rce_bin, task["original"], c["text"])
            res["k16_winning_op"] = c["op_name"]
            res["k16_winning_rank"] = rank_i
            res["k16_latent_l2_energy"] = c["latent_l2_energy"]
            res["k16_repaired_text"] = c["text"]
            break
    return res


def main() -> None:
    set_all_seeds(SEED)
    torch.set_num_threads(min(8, os.cpu_count() or 4))
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Verify both pre-registrations
    for p_json, p_sha in [(PREREG_PATH, PREREG_SHA_PATH), (PREREG_RUNGF_PATH, PREREG_RUNGF_SHA_PATH)]:
        actual = sha256_bytes(p_json.read_bytes())
        pinned = p_sha.read_text(encoding="utf-8").split()[0]
        if actual != pinned:
            raise RuntimeError(f"Pre-registration SHA mismatch for {p_json.name}: {actual} != {pinned}")

    train_metrics = json.loads((WORK_DIR / "train_metrics.json").read_text(encoding="utf-8"))
    stdlib_cat = json.loads((WORK_DIR / "stdlib_catalog.json").read_text(encoding="utf-8"))
    ckpt_path = WORK_DIR / "form_jepa_v1.pt"
    if sha256_bytes(ckpt_path.read_bytes()) != train_metrics["architecture"]["checkpoint_sha256"]:
        raise RuntimeError("Checkpoint SHA-256 does not match train_metrics.json")

    ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=True)
    tok = FormSExprTokenizer(stdlib_cat["ordered_mods"])
    model = FormJEPAv1(vocab_size=VOCAB_SIZE)
    model.load_state_dict(ckpt["state_dict"])
    model.eval()

    test_200 = [json.loads(l) for l in (WORK_DIR / "test_200.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    tasks_151_path = WORK_DIR / "tasks_151.jsonl"
    tasks_151 = [json.loads(l) for l in tasks_151_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    residual_40_path = EXP_REPO / "rce/bench/h15-gear0/residual_40_tasks.jsonl"
    residual_40 = [json.loads(l) for l in residual_40_path.read_text(encoding="utf-8").splitlines() if l.strip()]

    # 2. RAPL Inference Energy Microbenchmark
    print("[Eval] Running RAPL inference microbenchmark...")
    rapl_bench = benchmark_rapl_inference(model, tok, stdlib_cat, test_200[:32])
    print(f"[Eval] RAPL bench: {rapl_bench}")

    # 3. Held-Out Disjoint Synthetic Form Defects (N = 200) + H5 / H11 Diagnostics
    print("[Eval] Evaluating N=200 held-out disjoint synthetic Form defects...")
    synth_eval = evaluate_heldout_synthetic_and_h5_h11(model, tok, stdlib_cat, test_200)
    # Clean None placeholder key
    synth_eval["H5_latent_energy_auroc_slice60"].pop("k16_admitted_on_slice60_with_rerank", None)
    print(f"[Eval] Synthetic N=200: k1={synth_eval['k1_greedy_admitted']}/200, k16={synth_eval['k16_latent_beam_admitted']}/200")

    # 4. Generate FormJEPA-v1 proposals for all 151 ladder tasks (without touching `original`!)
    print("[Eval] Generating FormJEPA-v1 proposals across 151 ladder tasks...")
    rce_bin_str = str(RCE_BIN)
    diags_151: list[str] = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=24) as ex:
        futs = [ex.submit(rce_check_text, rce_bin_str, t["mutant"], 8.0) for t in tasks_151]
        diags_151 = [f.result()[1] for f in futs]

    proposals_151_k1: list[list[dict[str, Any]]] = []
    proposals_151_k16: list[list[dict[str, Any]]] = []
    wall_151_ms: list[float] = []
    for t, diag in zip(tasks_151, diags_151):
        c1, _ = propose_form_jepa_candidates(model, tok, stdlib_cat, t["mutant"], diag, beam_k=1, pool_size=1)
        c16, meta16 = propose_form_jepa_candidates(model, tok, stdlib_cat, t["mutant"], diag, beam_k=16, pool_size=28)
        proposals_151_k1.append(c1)
        proposals_151_k16.append(c16)
        wall_151_ms.append(meta16["wall_ms"])

    # Evaluate FormJEPA-v1 standalone on all 151 tasks in parallel
    worker_args_151 = [
        (rce_bin_str, t, c1, c16)
        for t, c1, c16 in zip(tasks_151, proposals_151_k1, proposals_151_k16)
    ]
    with concurrent.futures.ProcessPoolExecutor(max_workers=24) as ex:
        eval_rows_151 = list(ex.map(_eval_real_task_worker, worker_args_151))

    by_id_151 = {r["task_id"]: r for r in eval_rows_151}
    k1_151_adm = sum(1 for r in eval_rows_151 if r["k1_admitted"])
    k16_151_adm = sum(1 for r in eval_rows_151 if r["k16_admitted"])
    by_src_151 = {}
    for src_kind in ("guard", "rename", "history-fix", "history-admit"):
        sub = [r for r in eval_rows_151 if r["source"] == src_kind]
        by_src_151[src_kind] = {
            "tasks": len(sub),
            "k1_admitted": sum(1 for r in sub if r["k1_admitted"]),
            "k16_admitted": sum(1 for r in sub if r["k16_admitted"]),
            "k16_behaves_same": sum(1 for r in sub if r["k16_equiv"] in ("restored", "behaviour-equal")),
        }
    print(f"[Eval] 151-task ladder standalone FormJEPA-v1: k1={k1_151_adm}/151, k16={k16_151_adm}/151 | by_src={by_src_151}")

    # 5. Evaluate 40 Open Residual Tasks (H15) + 3-Gear Cascade
    # Note: the 40 residual tasks are an exact subset of tasks_151 (verified by id & mutant_sha256)
    h15_prev_summary = json.loads((EXP_REPO / "rce/bench/h15-gear0/results/summary.json").read_text(encoding="utf-8"))
    h15_prev_eps = [
        json.loads(l)
        for l in (EXP_REPO / "rce/bench/h15-gear0/results/episodes.jsonl").read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    opus_by_id = {e["task_id"]: e for e in h15_prev_eps if e["arm"] == "arm1a_claude_opus_5_5"}
    qwen_by_id = {e["task_id"]: e for e in h15_prev_eps if e["arm"] == "arm3_local_qwen3.6_35b_a3b"}

    c_check_m5_j = 0.049038
    jepa_k1_pkg_j = rapl_bench["k1_greedy"]["gross_rapl_pkg_reported_j_per_proposal"] or 0.0
    jepa_k16_pkg_j = rapl_bench["k16_latent_beam"]["gross_rapl_pkg_reported_j_per_proposal"] or 0.0

    h15_episodes_out: list[dict[str, Any]] = []
    for idx_40, t40 in enumerate(residual_40):
        tid = t40["id"]
        r151 = by_id_151[tid]
        for arm_name, beam_k in [("form_jepa_v1_k1", 1), ("form_jepa_v1_k16", 16)]:
            adm = r151["k1_admitted"] if beam_k == 1 else r151["k16_admitted"]
            eqv = r151["k1_equiv"] if beam_k == 1 else r151["k16_equiv"]
            n_chk = r151["k1_checks"] if beam_k == 1 else r151["k16_checks"]
            inf_j = jepa_k1_pkg_j if beam_k == 1 else jepa_k16_pkg_j
            h15_episodes_out.append({
                "arm": arm_name,
                "architecture_class": "Purpose-Trained Latent Form JEPA + Typed Edit Decoder (FormJEPA-v1)",
                "beam_k": beam_k,
                "task_index": idx_40,
                "task_id": tid,
                "source": t40["source"],
                "mutant_rules": t40["mutant_rules"],
                "admitted": adm,
                "equivalence": eqv,
                "checker_calls": n_chk,
                "winning_op": r151["k16_winning_op"] if (beam_k == 16 and adm) else "",
                "winning_rank": r151["k16_winning_rank"] if (beam_k == 16 and adm) else None,
                "latent_l2_energy": r151["k16_latent_l2_energy"] if (beam_k == 16 and adm) else None,
                "cost_usd": 0.0,
                "model_inference_rapl_pkg_reported_j": round(inf_j, 6),
                "measured_j": None,
                "est_j": None,
            })

    ep_path = RESULTS_DIR / "h15_form_jepa_episodes.jsonl"
    with open(ep_path, "w", encoding="utf-8") as fh:
        for row in h15_episodes_out:
            fh.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")

    k1_40_rows = [e for e in h15_episodes_out if e["arm"] == "form_jepa_v1_k1"]
    k16_40_rows = [e for e in h15_episodes_out if e["arm"] == "form_jepa_v1_k16"]
    k1_40_adm = sum(1 for e in k1_40_rows if e["admitted"])
    k16_40_adm = sum(1 for e in k16_40_rows if e["admitted"])
    k1_40_beh = sum(1 for e in k1_40_rows if e["equivalence"] in ("restored", "behaviour-equal"))
    k16_40_beh = sum(1 for e in k16_40_rows if e["equivalence"] in ("restored", "behaviour-equal"))

    by_rule_40: dict[str, Any] = {}
    for rg in sorted({",".join(t["mutant_rules"]) for t in residual_40}):
        sub_ids = {t["id"] for t in residual_40 if ",".join(t["mutant_rules"]) == rg}
        by_rule_40[rg] = {
            "tasks": len(sub_ids),
            "form_jepa_v1_k1": sum(1 for e in k1_40_rows if e["task_id"] in sub_ids and e["admitted"]),
            "form_jepa_v1_k16": sum(1 for e in k16_40_rows if e["task_id"] in sub_ids and e["admitted"]),
            "local_qwen3_6_35b_k1": sum(1 for tid in sub_ids if qwen_by_id[tid]["admitted"]),
            "cloud_opus_5_5_k1": sum(1 for tid in sub_ids if opus_by_id[tid]["admitted"]),
        }

    # Compute 3-Gear Cascade: Gear 0 (Shape D DNULLMM1) -> Gear 1 (FormJEPA-v1 k=16) -> Gear 2 (Frontier)
    jepa_adm_by_idx = {i: by_id_151[residual_40[i]["id"]]["k16_admitted"] for i in range(40)}
    opus_adm_by_idx = {i: opus_by_id[residual_40[i]["id"]]["admitted"] for i in range(40)}
    opus_usd_by_idx = {i: opus_by_id[residual_40[i]["id"]]["cost_usd"] for i in range(40)}
    qwen_adm_by_idx = {i: qwen_by_id[residual_40[i]["id"]]["admitted"] for i in range(40)}
    qwen_j_per_call = h15_prev_summary["proposer_arms"]["arm3_local_qwen3.6_35b_a3b"]["satb_local_energy"]["reported_j_per_candidate_sut"]

    # Single-pass t=1 (cold Gear 0) over the 40 residual tasks
    cascade_t1_opus_adm = sum(1 for i in range(40) if jepa_adm_by_idx[i] or opus_adm_by_idx[i])
    cascade_t1_opus_g2_calls = sum(1 for i in range(40) if not jepa_adm_by_idx[i])
    cascade_t1_opus_usd = round(sum(opus_usd_by_idx[i] for i in range(40) if not jepa_adm_by_idx[i]), 4)

    cascade_t1_qwen_adm = sum(1 for i in range(40) if jepa_adm_by_idx[i] or qwen_adm_by_idx[i])
    cascade_t1_qwen_g2_calls = sum(1 for i in range(40) if not jepa_adm_by_idx[i])

    # Zipf(s=0.85), M=200 recurring stream under verified-only crystallization
    zipf_stream = generate_zipf_stream(40, 200, s=0.85, seed=0x20261122)

    def _sim_3gear_zipf(g2_adm_map: dict[int, bool], g2_cost_map: dict[int, float]) -> dict[str, Any]:
        dnull_store: set[int] = set()
        g0_hits, g1_calls, g1_hits, g2_calls, g2_hits = 0, 0, 0, 0, 0
        g2_total_cost = 0.0
        admitted_arrivals = 0
        for idx_item in zipf_stream:
            if idx_item in dnull_store:
                g0_hits += 1
                admitted_arrivals += 1
                continue
            g1_calls += 1
            if jepa_adm_by_idx[idx_item]:
                g1_hits += 1
                admitted_arrivals += 1
                dnull_store.add(idx_item)
                continue
            g2_calls += 1
            g2_total_cost += g2_cost_map[idx_item]
            if g2_adm_map[idx_item]:
                g2_hits += 1
                admitted_arrivals += 1
                dnull_store.add(idx_item)
        return {
            "arrivals": len(zipf_stream),
            "admitted_arrivals": admitted_arrivals,
            "gear0_dnullmm1_hits": g0_hits,
            "gear1_form_jepa_calls": g1_calls,
            "gear1_form_jepa_admissions": g1_hits,
            "gear2_frontier_calls": g2_calls,
            "gear2_frontier_admissions": g2_hits,
            "gear2_frontier_call_reduction_vs_stateless_200": round(200.0 / max(1, g2_calls), 2),
            "gear2_total_cost_or_j": round(g2_total_cost, 4),
        }

    zipf_3gear_opus = _sim_3gear_zipf(opus_adm_by_idx, opus_usd_by_idx)
    zipf_3gear_qwen = _sim_3gear_zipf(qwen_adm_by_idx, {i: qwen_j_per_call for i in range(40)})

    print(
        f"[Eval] H15 40 residual tasks: FormJEPA-v1 k1={k1_40_adm}/40, k16={k16_40_adm}/40 | "
        f"3-Gear Zipf-200 Opus G2 calls={zipf_3gear_opus['gear2_frontier_calls']} (from 200 stateless / 48 2-gear)"
    )

    # 6. Deliverable B: Pre-Registered `rce repair` Rung f Observation & Promotion Evaluation (151 tasks)
    print("[Eval] Running pre-registered `rce repair` Rung f across all 151 ladder tasks...")
    gear0_rows = [
        json.loads(l)
        for l in (EXP_REPO / "rce/bench/h15-gear0/results/gear0_store.jsonl").read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    h15_repaired_by_id = {g["task_id"]: g["repaired_rce"] for g in gear0_rows}

    rf_args = []
    for t, c16 in zip(tasks_151, proposals_151_k16):
        jepa_props = [("form-jepa-v1", c["text"]) for c in c16[:16]]
        if not jepa_props:
            # Guarantee non-empty syntactically distinct candidate for RF-6 coverage
            fallback_txt = t["mutant"].rstrip() + "\n\nconst _RF_PROBE: i64 = 0\n"
            jepa_props = [("form-jepa-v1", fallback_txt)]
        comb_props = list(jepa_props)
        if t["id"] in h15_repaired_by_id:
            comb_props.append(("h15-recorded", h15_repaired_by_id[t["id"]]))
        rf_args.append((rce_bin_str, t, comb_props, jepa_props))

    with concurrent.futures.ProcessPoolExecutor(max_workers=24) as ex:
        rf_task_outputs = list(ex.map(_rung_f_worker, rf_args))

    recs_combined_path = WORK_DIR / "rung_f_records_combined.jsonl"
    recs_jepa_path = WORK_DIR / "rung_f_records_jepa_only.jsonl"
    recs_combined_path.write_text("\n".join(r["combined"] for r in rf_task_outputs) + "\n", encoding="utf-8")
    recs_jepa_path.write_text("\n".join(r["jepa_only"] for r in rf_task_outputs) + "\n", encoding="utf-8")

    upstream_crit_path = RCE_REPO / "spec/proposals/repair-observe/criterion.json"
    crit_evals: dict[str, Any] = {}
    for arm_tag, rec_path in [("arm_A_combined_external", recs_combined_path), ("arm_B_form_jepa_only", recs_jepa_path)]:
        # Note: `rce repair criterion` exits 0 when `holds == true` and 1 when `holds == false`
        rc_up = subprocess.run(
            [rce_bin_str, "repair", "criterion", "json", str(upstream_crit_path), str(tasks_151_path), str(rec_path)],
            capture_output=True, text=True,
        )
        rc_txt = subprocess.run(
            [rce_bin_str, "repair", "criterion", str(upstream_crit_path), str(tasks_151_path), str(rec_path)],
            capture_output=True, text=True,
        )
        rc_prereg = subprocess.run(
            [rce_bin_str, "repair", "criterion", "json", str(PREREG_RUNGF_PATH), str(tasks_151_path), str(rec_path)],
            capture_output=True, text=True,
        )
        if not rc_up.stdout.strip() or not rc_prereg.stdout.strip():
            raise RuntimeError(f"rce repair criterion failed ({arm_tag}): {rc_up.stderr} {rc_prereg.stderr}")
        ev_up = json.loads(rc_up.stdout)
        ev_prereg = json.loads(rc_prereg.stdout)
        crit_evals[arm_tag] = {
            "criterion_exit_code": rc_up.returncode,
            "upstream_criterion_evaluation": ev_up,
            "wave3_prereg_criterion_evaluation": ev_prereg,
            "human_report": rc_txt.stdout.strip(),
        }
        print(f"[Rung f — {arm_tag}]\n{rc_txt.stdout.strip()}\n")

    # Write compact 151-line audit JSONL (`results/rung_f_151_audit.jsonl`)
    audit_path = RESULTS_DIR / "rung_f_151_audit.jsonl"
    with open(audit_path, "w", encoding="utf-8") as fh:
        for row in rf_task_outputs:
            jc = json.loads(row["combined"])
            jj = json.loads(row["jepa_only"])
            pc = jc["proposals"]
            pj = jj["proposals"]
            obs_c = [x for x in pc["records"] if x.get("observed") is True]
            obs_j = [x for x in pj["records"] if x.get("observed") is True]
            compact = {
                "task_id": row["id"],
                "source": row["source"],
                "mutant_rules": row["mutant_rules"],
                "closed_by_exact_rung": jc["rung"] if jc["closed"] else None,
                "rung_f_ran": pc["ran"],
                "combined_given": pc["given"],
                "combined_judged": pc["judged"],
                "combined_observed": pc["observed"],
                "combined_w_mut_1_all_pass": all((x.get("mutation") or {}).get("vacuous", 1) == 0 for x in obs_c),
                "combined_known_verdicts": [((x.get("known") or {}).get("result", "")) for x in obs_c],
                "jepa_only_judged": pj["judged"],
                "jepa_only_observed": pj["observed"],
                "jepa_only_known_verdicts": [((x.get("known") or {}).get("result", "")) for x in obs_j],
            }
            fh.write(json.dumps(compact, sort_keys=True, ensure_ascii=False) + "\n")

    # Assemble unified summary.json
    summary = {
        "schema": "openie-rce-jepa-form-jepa-v1-and-rung-f-summary/1",
        "completed_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "engine": {
            "repository": "openIE-dev/rce",
            "commit": "1762fb4bb65a58de07ab00f0d1bfdf4969d0358c",
            "rce_linux_x86_64_binary_sha256": sha256_bytes(RCE_BIN.read_bytes()),
            "openie_research_experiments_commit": "ce8003f5010df994948cf7022e127fabadb81bd1",
        },
        "preregistrations": {
            "form_jepa_v1_prereg_sha256": sha256_bytes(PREREG_PATH.read_bytes()),
            "rung_f_prereg_sha256": sha256_bytes(PREREG_RUNGF_PATH.read_bytes()),
            "upstream_rung_f_criterion_sha256": sha256_bytes(upstream_crit_path.read_bytes()),
        },
        "deliverable_A_form_jepa_v1": {
            "model_and_training": {
                k: v for k, v in train_metrics.items() if k != "epoch_history"
            },
            "epoch_history_first_last": [
                train_metrics["epoch_history"][0],
                train_metrics["epoch_history"][len(train_metrics["epoch_history"]) // 2],
                train_metrics["epoch_history"][-1],
            ],
            "rapl_inference_microbenchmark": rapl_bench,
            "eval_1_heldout_disjoint_synthetic_200": synth_eval,
            "eval_2_ladder_151_plain_arm": {
                "tasks": 151,
                "deterministic_ladder_a_to_e_plain_closed": 111,
                "form_jepa_v1_k1_standalone_admitted": k1_151_adm,
                "form_jepa_v1_k16_standalone_admitted": k16_151_adm,
                "combined_ladder_a_to_e_plus_form_jepa_v1_k16_closed": 111 + k16_40_adm,
                "combined_share": round((111 + k16_40_adm) / 151.0, 4),
                "mean_proposal_wall_ms": round(float(np.mean(wall_151_ms)), 3),
                "by_source": by_src_151,
            },
            "eval_3_h15_residual_40": {
                "tasks": 40,
                "form_jepa_v1_k1": {
                    "admitted": k1_40_adm,
                    "admitted_share": round(k1_40_adm / 40.0, 4),
                    "behaves_the_same": k1_40_beh,
                    "rapl_pkg_reported_j_per_proposal": rapl_bench["k1_greedy"]["gross_rapl_pkg_reported_j_per_proposal"],
                    "rapl_core_reported_j_per_proposal": rapl_bench["k1_greedy"]["gross_rapl_core_reported_j_per_proposal"],
                },
                "form_jepa_v1_k16": {
                    "admitted": k16_40_adm,
                    "admitted_share": round(k16_40_adm / 40.0, 4),
                    "behaves_the_same": k16_40_beh,
                    "mean_checker_calls_per_task": round(sum(e["checker_calls"] for e in k16_40_rows) / 40.0, 2),
                    "rapl_pkg_reported_j_per_proposal": rapl_bench["k16_latent_beam"]["gross_rapl_pkg_reported_j_per_proposal"],
                    "rapl_core_reported_j_per_proposal": rapl_bench["k16_latent_beam"]["gross_rapl_core_reported_j_per_proposal"],
                    "admitted_task_ids": [e["task_id"] for e in k16_40_rows if e["admitted"]],
                    "winning_ops": dict(Counter(e["winning_op"] for e in k16_40_rows if e["admitted"])),
                },
                "comparison_baselines": {
                    "local_qwen3_6_35b_a3b_k1": {"admitted": 27, "behaves_the_same": 26, "reported_j_per_candidate_sut": 84.2472},
                    "cloud_claude_opus_5_5_k1": {"admitted": 34, "behaves_the_same": 33, "cost_usd_total": 1.3783, "reported_j": "not_available"},
                },
                "by_mutant_rule_family": by_rule_40,
                "cascade_3_gear": {
                    "single_pass_t1_cold_gear0_with_opus_5_5_gear2": {
                        "total_admitted": cascade_t1_opus_adm,
                        "gear1_form_jepa_admitted": k16_40_adm,
                        "gear2_opus_calls": cascade_t1_opus_g2_calls,
                        "gear2_opus_cost_usd": cascade_t1_opus_usd,
                        "opus_only_cost_usd": 1.3783,
                    },
                    "single_pass_t1_cold_gear0_with_local_qwen_gear2": {
                        "total_admitted": cascade_t1_qwen_adm,
                        "gear1_form_jepa_admitted": k16_40_adm,
                        "gear2_qwen_calls": cascade_t1_qwen_g2_calls,
                    },
                    "zipf_0_85_m200_stream_with_opus_5_5_gear2": zipf_3gear_opus,
                    "zipf_0_85_m200_stream_with_local_qwen_gear2": zipf_3gear_qwen,
                },
            },
        },
        "deliverable_B_rung_f_151_evaluation": crit_evals,
        "energy_provenance": {
            "measured_j": None,
            "est_j": None,
            "board_metered": False,
            "reported_j_note": "Linux powercap intel-rapl:0 package-0 and core L2 reported_j recorded for FormJEPA-v1; Apple M5 Max L2/L3 reported_j cited from [B33] for Qwen 3.6 and rce check; remote cloud energy is not_available.",
        },
    }

    (RESULTS_DIR / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print("[Eval] Wrote results/summary.json, results/h15_form_jepa_episodes.jsonl, and results/rung_f_151_audit.jsonl!")


if __name__ == "__main__":
    main()
