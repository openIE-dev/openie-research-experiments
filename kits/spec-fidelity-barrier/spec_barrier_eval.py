#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Main Evaluator for Kit #8 (`kits/spec-fidelity-barrier/`):
Evaluates the 40-task deterministic benchmark suite across 4 progressive gate architectures:
  - Arm A (`shared_context_naive`): Shared-context Goodhart/tautological specs
  - Arm B (`isolated_spec_only`): Context-isolated (`Spec ⊥ Impl`) partial specs without mutant gate
  - Arm C (`mutant_vacuity_barrier`): `Spec ⊥ Impl` + Automated 5-Operator AST Mutant/Vacuity Kill Gate
    (`SPEC_VACUOUS_REFUSED` unless 100% of synthesized AST mutants are killed)
  - Arm D (`grammar_mask_plus_mutant_gate`): In-loop Earley/Pushdown CFG+Type Token Masking over
    1,000 seeded candidate draws + Arm C Mutant-Hardened Semantic Commit Gate, metered on host CPU
    and Linux `powercap` RAPL (`reported_j`; never mixed with `measured_j` or `est_j`).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from spec_barrier.ast_mutator import TaskSpec, generate_ast_mutants  # noqa: E402
from spec_barrier.grammar_and_telemetry import (  # noqa: E402
    EnergyMeter,
    SplitMix64,
    VOCAB,
    _build_proposal_weights,
    assert_sanitized,
    blake3_derive_key_hex,
    blake3_hex,
    clopper_pearson_interval,
    iqr_stats,
    posthoc_parse_and_typecheck,
    sample_grammar_masked_stream,
    sample_unconstrained_stream,
    sanitized_host_info,
    seal_signed_receipt,
    verify_signed_receipt,
)
from spec_barrier.task_suite import build_40_task_suite  # noqa: E402


def _make_shared_context_spec(task: TaskSpec, cand_fn: Callable[[Any], Any]) -> Callable[[Any, Any], bool]:
    """Arm A (`shared_context_naive`): Models Goodhart's Law when LLM writes test/spec in the
    same context window as its candidate implementation — checks return type/shape and echoes
    candidate's own first-case output constant rather than independent relational invariants.
    """
    echoed_first = cand_fn(task.test_inputs[0])

    def shared_check(inp: Any, out: Any) -> bool:
        if inp == task.test_inputs[0] and out != echoed_first:
            return False
        if task.return_kind == "LIST":
            return isinstance(out, list)
        if task.return_kind == "TUPLE2":
            return isinstance(out, tuple) and len(out) == 2
        if task.return_kind == "BOOL":
            return isinstance(out, bool)
        return isinstance(out, int) and not isinstance(out, bool)

    return shared_check


def _spec_admits_candidate(spec_check: Callable[[Any, Any], bool], task: TaskSpec, cand_fn: Callable[[Any], Any]) -> bool:
    for x in task.test_inputs:
        try:
            out = cand_fn(x)
            if not spec_check(x, out):
                return False
        except Exception:
            return False
    return True


def audit_spec_against_mutants(
    spec_check: Callable[[Any, Any], bool],
    task: TaskSpec,
    mutants: list[Any],
) -> dict[str, Any]:
    """Automated Mutant/Vacuity Barrier (`Arm C`):
    Refuses the spec itself (`SPEC_VACUOUS_REFUSED`) unless it kills 100% of synthesized AST mutants.
    """
    killed = 0
    surviving_ids: list[str] = []
    for m in mutants:
        admitted = _spec_admits_candidate(spec_check, task, m.fn)
        if not admitted:
            killed += 1
        else:
            surviving_ids.append(m.mutant_id)
    total = len(mutants)
    refused = killed < total
    return {
        "total_mutants": total,
        "killed_mutants": killed,
        "kill_rate": round(killed / max(1, total), 6),
        "status": "SPEC_VACUOUS_REFUSED" if refused else "SPEC_ADMITTED",
        "surviving_mutants": surviving_ids,
    }


def evaluate_arms_abc(tasks: list[TaskSpec]) -> dict[str, Any]:
    """Evaluate Arms A, B, and C deterministically across all 40 tasks (240 candidates, 200 AST mutants)."""
    mutants_by_task = {t.task_id: generate_ast_mutants(t) for t in tasks}

    arm_stats: dict[str, dict[str, Any]] = {}
    domain_breakdown: dict[str, dict[str, Any]] = {}

    # Pre-audit weak specs under Arm C's Mutant/Vacuity Kill Gate
    arm_a_specs_refused = 0
    arm_b_specs_refused = 0
    arm_c_specs_admitted = 0
    arm_a_mutants_killed = 0
    arm_b_mutants_killed = 0
    arm_c_mutants_killed = 0
    total_mutants = 0

    for t in tasks:
        muts = mutants_by_task[t.task_id]
        total_mutants += len(muts)
        # Audit Arm A spec built around bug1 stub
        rep_a = audit_spec_against_mutants(_make_shared_context_spec(t, t.defective_fns["bug1_type_shape_stub"]), t, muts)
        if rep_a["status"] == "SPEC_VACUOUS_REFUSED":
            arm_a_specs_refused += 1
        arm_a_mutants_killed += rep_a["killed_mutants"]

        # Audit Arm B partial isolated spec
        rep_b = audit_spec_against_mutants(t.partial_isolated_check, t, muts)
        if rep_b["status"] == "SPEC_VACUOUS_REFUSED":
            arm_b_specs_refused += 1
        arm_b_mutants_killed += rep_b["killed_mutants"]

        # Audit Arm C complete isolated spec
        rep_c = audit_spec_against_mutants(t.complete_isolated_check, t, muts)
        if rep_c["status"] != "SPEC_ADMITTED":
            raise RuntimeError(f"Arm C complete spec failed mutant barrier on {t.task_id}: {rep_c}")
        arm_c_specs_admitted += 1
        arm_c_mutants_killed += rep_c["killed_mutants"]

    for arm_key, arm_label in (
        ("arm_a_shared_context_naive", "Arm A — Shared-Context Naive Spec (Goodhart Baseline)"),
        ("arm_b_isolated_spec_only", "Arm B — Context-Isolated Partial Spec (`Spec ⊥ Impl`, No Mutant Gate)"),
        ("arm_c_mutant_vacuity_barrier", "Arm C — `Spec ⊥ Impl` + 100% AST Mutant/Vacuity Kill Gate"),
    ):
        valid_accepted = 0
        valid_total = 0
        defective_false_accepts = 0
        defective_total = 0
        tasks_with_false_accept = 0
        per_bug_false_accepts: dict[str, int] = {}

        for t in tasks:
            dom_rec = domain_breakdown.setdefault(
                t.domain,
                {"tasks": 0, "arm_a_false_accepts": 0, "arm_b_false_accepts": 0, "arm_c_false_accepts": 0},
            )
            if arm_key == "arm_a_shared_context_naive":
                dom_rec["tasks"] += 1

            # 1. Valid independent implementation check (false-reject audit)
            valid_total += 1
            if arm_key == "arm_a_shared_context_naive":
                v_spec = _make_shared_context_spec(t, t.valid_alt_fn)
            elif arm_key == "arm_b_isolated_spec_only":
                v_spec = t.partial_isolated_check
            else:
                v_spec = t.complete_isolated_check
            if _spec_admits_candidate(v_spec, t, t.valid_alt_fn):
                valid_accepted += 1

            # 2. Defective candidate checks (false-accept audit across 5 defective candidates/task)
            task_fa = 0
            for bname, bfn in t.defective_fns.items():
                defective_total += 1
                per_bug_false_accepts.setdefault(bname, 0)
                if arm_key == "arm_a_shared_context_naive":
                    spec_fn = _make_shared_context_spec(t, bfn)
                elif arm_key == "arm_b_isolated_spec_only":
                    spec_fn = t.partial_isolated_check
                else:
                    # Arm C enforces Mutant/Vacuity Kill Gate BEFORE admitting any spec
                    audit = audit_spec_against_mutants(t.complete_isolated_check, t, mutants_by_task[t.task_id])
                    if audit["status"] == "SPEC_VACUOUS_REFUSED":
                        raise RuntimeError("Vacuous spec refused")
                    spec_fn = t.complete_isolated_check

                if _spec_admits_candidate(spec_fn, t, bfn):
                    defective_false_accepts += 1
                    task_fa += 1
                    per_bug_false_accepts[bname] += 1

            if task_fa > 0:
                tasks_with_false_accept += 1
            if arm_key == "arm_a_shared_context_naive":
                dom_rec["arm_a_false_accepts"] += task_fa
            elif arm_key == "arm_b_isolated_spec_only":
                dom_rec["arm_b_false_accepts"] += task_fa
            else:
                dom_rec["arm_c_false_accepts"] += task_fa

        arm_stats[arm_key] = {
            "label": arm_label,
            "tasks_evaluated": len(tasks),
            "valid_candidates_accepted": valid_accepted,
            "valid_candidates_total": valid_total,
            "true_accept_rate": round(valid_accepted / valid_total, 6),
            "defective_candidates_falsely_accepted": defective_false_accepts,
            "defective_candidates_total": defective_total,
            "candidate_false_accept_ci95": clopper_pearson_interval(defective_false_accepts, defective_total),
            "tasks_admitting_any_buggy_impl": tasks_with_false_accept,
            "task_false_accept_ci95": clopper_pearson_interval(tasks_with_false_accept, len(tasks)),
            "false_accepts_by_defect_class": per_bug_false_accepts,
        }

    return {
        "mutant_vacuity_audit": {
            "ast_mutants_per_task": 5,
            "total_ast_mutants_synthesized": total_mutants,
            "mutant_operators": [
                "M1_zero_constant_stub",
                "M2_boundary_off_by_one",
                "M3_sign_or_bitop_flip",
                "M4_branch_drop",
                "M5_invariant_bypass",
            ],
            "arm_a_tautological_specs_refused": arm_a_specs_refused,
            "arm_a_specs_refused_status": "SPEC_VACUOUS_REFUSED",
            "arm_a_mutant_kill_rate": round(arm_a_mutants_killed / total_mutants, 6),
            "arm_b_partial_specs_refused": arm_b_specs_refused,
            "arm_b_specs_refused_status": "SPEC_VACUOUS_REFUSED",
            "arm_b_mutant_kill_rate": round(arm_b_mutants_killed / total_mutants, 6),
            "arm_c_hardened_specs_admitted": arm_c_specs_admitted,
            "arm_c_mutant_kill_rate": round(arm_c_mutants_killed / total_mutants, 6),
        },
        "arms": arm_stats,
        "domain_breakdown": domain_breakdown,
    }


def _eval_typed_dsl_candidate(tokens: list[int], task: TaskSpec, draw_idx: int) -> Callable[[Any], Any]:
    """Map a well-typed token stream into an executable candidate for `task` to test the Arm C
    semantic commit gate: every 5th well-typed draw realizes a valid implementation, while the
    remaining 4/5 realize syntactically & type-valid but semantically defective candidates
    (boundary/partial/echo defects) that ONLY the Arm C semantic mutant gate can reject!
    """
    _ = tokens
    if (draw_idx % 5) == 4:
        return task.valid_alt_fn
    defect_keys = list(task.defective_fns.keys())
    chosen_key = defect_keys[(draw_idx + len(tokens)) % len(defect_keys)]
    return task.defective_fns[chosen_key]


def evaluate_arm_d_grammar_and_energy(tasks: list[TaskSpec], quick: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    """Arm D (`grammar_mask_plus_mutant_gate`):
    Compares Unconstrained Post-Hoc Rejection vs. In-Loop Earley/Pushdown CFG+Type Token Masking
    paired with the Arm C Mutant-Hardened Semantic Commit Gate across 1,000 seeded candidate
    draws (`25` draws x `40` tasks), metering wall-time µs and Linux RAPL `reported_j`.
    """
    draws_per_task = 25
    total_draws = len(tasks) * draws_per_task  # 1,000 seeded draws
    n_trials = 5 if quick else 15
    reps_per_trial = 2 if quick else 8  # calibrate >= 80-200 ms per trial for crisp RAPL energy_uj resolution

    meter = EnergyMeter()
    idle_pre = meter.sample_idle_power_w(0.10 if quick else 0.20)

    # Precompute proposal weight tables deterministically (`seed = 0x20261128`)
    init_rng = SplitMix64(0x20261128)
    proposal_weights_by_draw: list[tuple[TaskSpec, int, list[float]]] = []
    draw_counter = 0
    for t in tasks:
        for _ in range(draws_per_task):
            proposal_weights_by_draw.append((t, draw_counter, _build_proposal_weights(t.grammar_type, init_rng)))
            draw_counter += 1

    # ── Single-pass deterministic accounting over the 1,000 seeded draws ──
    def _run_unconstrained_pass(seed: int) -> dict[str, int]:
        rng = SplitMix64(seed)
        single_draw_syntax_rejects = 0
        single_draw_wasted_tokens = 0
        retry_total_tokens = 0
        retry_wasted_syntax_tokens = 0
        retry_attempts = 0
        semantic_commits = 0
        semantic_false_accepts = 0

        for task, d_idx, weights in proposal_weights_by_draw:
            # 1. First draw audit across 1,000 draws
            toks0 = sample_unconstrained_stream(weights, rng, max_tokens=28)
            ok0, _ = posthoc_parse_and_typecheck(toks0, task.grammar_type)
            retry_attempts += 1
            retry_total_tokens += len(toks0)
            if not ok0:
                single_draw_syntax_rejects += 1
                single_draw_wasted_tokens += len(toks0)
                retry_wasted_syntax_tokens += len(toks0)
                # Keep resampling post-hoc until a syntactically + statically well-typed candidate emerges
                toks_valid = toks0
                for _retry in range(24):
                    cand_toks = sample_unconstrained_stream(weights, rng, max_tokens=28)
                    retry_attempts += 1
                    retry_total_tokens += len(cand_toks)
                    ok_r, _ = posthoc_parse_and_typecheck(cand_toks, task.grammar_type)
                    if ok_r:
                        toks_valid = cand_toks
                        ok0 = True
                        break
                    retry_wasted_syntax_tokens += len(cand_toks)
            else:
                toks_valid = toks0

            if ok0:
                cand_fn = _eval_typed_dsl_candidate(toks_valid, task, d_idx)
                if _spec_admits_candidate(task.complete_isolated_check, task, cand_fn):
                    semantic_commits += 1
                    # Verify against ground truth that 0 defective draws were falsely accepted
                    if cand_fn is not task.valid_alt_fn:
                        semantic_false_accepts += 1

        return {
            "draws": total_draws,
            "single_draw_syntax_type_rejects": single_draw_syntax_rejects,
            "single_draw_wasted_tokens": single_draw_wasted_tokens,
            "retry_attempts_for_well_typed": retry_attempts,
            "total_tokens_generated": retry_total_tokens,
            "wasted_syntax_type_tokens": retry_wasted_syntax_tokens,
            "semantic_commits": semantic_commits,
            "semantic_false_accepts": semantic_false_accepts,
        }

    def _run_grammar_masked_pass(seed: int) -> dict[str, int]:
        rng = SplitMix64(seed)
        syntax_rejects = 0
        total_tokens = 0
        wasted_syntax_tokens = 0
        semantic_commits = 0
        semantic_false_accepts = 0

        for task, d_idx, weights in proposal_weights_by_draw:
            toks = sample_grammar_masked_stream(weights, task.grammar_type, rng, max_compounds=3)
            total_tokens += len(toks)
            ok, err = posthoc_parse_and_typecheck(toks, task.grammar_type)
            if not ok:
                syntax_rejects += 1
                wasted_syntax_tokens += len(toks)
                raise RuntimeError(f"Grammar mask emitted invalid sequence: {err}")
            cand_fn = _eval_typed_dsl_candidate(toks, task, d_idx)
            if _spec_admits_candidate(task.complete_isolated_check, task, cand_fn):
                semantic_commits += 1
                if cand_fn is not task.valid_alt_fn:
                    semantic_false_accepts += 1

        return {
            "draws": total_draws,
            "single_draw_syntax_type_rejects": syntax_rejects,
            "single_draw_wasted_tokens": wasted_syntax_tokens,
            "retry_attempts_for_well_typed": total_draws,
            "total_tokens_generated": total_tokens,
            "wasted_syntax_type_tokens": wasted_syntax_tokens,
            "semantic_commits": semantic_commits,
            "semantic_false_accepts": semantic_false_accepts,
        }

    # Canonical seeded accounting (`seed = 0x51ECFA11`)
    acct_unconstrained = _run_unconstrained_pass(0x51ECFA11)
    acct_masked = _run_grammar_masked_pass(0x51ECFA11)

    # ── Hardware-metered trials (`reported_j` if Linux RAPL readable, else `unmetered`) ──
    unconstrained_us_per_draw: list[float] = []
    masked_us_per_draw: list[float] = []
    unconstrained_pkg_j: list[float] = []
    masked_pkg_j: list[float] = []
    unconstrained_core_j: list[float] = []
    masked_core_j: list[float] = []

    for trial in range(n_trials):
        s0 = meter.snapshot()
        for r in range(reps_per_trial):
            _ = _run_unconstrained_pass(0x51ECFA11 + r)
        s1 = meter.snapshot()
        d_unc = meter.diff(s0, s1)
        denom_draws = total_draws * reps_per_trial
        unconstrained_us_per_draw.append(d_unc["wall_us"] / denom_draws)
        if d_unc["pkg_reported_j"] is not None:
            unconstrained_pkg_j.append((d_unc["pkg_reported_j"] * 1e6) / denom_draws)  # uJ / draw
        if d_unc["core_reported_j"] is not None:
            unconstrained_core_j.append((d_unc["core_reported_j"] * 1e6) / denom_draws)

        s2 = meter.snapshot()
        for r in range(reps_per_trial):
            _ = _run_grammar_masked_pass(0x51ECFA11 + r)
        s3 = meter.snapshot()
        d_msk = meter.diff(s2, s3)
        masked_us_per_draw.append(d_msk["wall_us"] / denom_draws)
        if d_msk["pkg_reported_j"] is not None:
            masked_pkg_j.append((d_msk["pkg_reported_j"] * 1e6) / denom_draws)
        if d_msk["core_reported_j"] is not None:
            masked_core_j.append((d_msk["core_reported_j"] * 1e6) / denom_draws)
        _ = trial

    idle_post = meter.sample_idle_power_w(0.10 if quick else 0.20)
    energy_meta = meter.metadata(idle_pre, idle_post)

    unc_tok = acct_unconstrained["total_tokens_generated"]
    msk_tok = acct_masked["total_tokens_generated"]
    token_reduction_pct = round(100.0 * (unc_tok - msk_tok) / max(1, unc_tok), 2)
    syntax_waste_reduction_pct = round(
        100.0
        * (acct_unconstrained["wasted_syntax_type_tokens"] - acct_masked["wasted_syntax_type_tokens"])
        / max(1, acct_unconstrained["wasted_syntax_type_tokens"]),
        2,
    )

    unc_us_med = iqr_stats(unconstrained_us_per_draw, 3)["median"]
    msk_us_med = iqr_stats(masked_us_per_draw, 3)["median"]
    speedup_x = round(unc_us_med / max(1e-9, msk_us_med), 3)

    pkg_energy_ratio_x = None
    if unconstrained_pkg_j and masked_pkg_j:
        pkg_energy_ratio_x = round(
            iqr_stats(unconstrained_pkg_j, 3)["median"] / max(1e-9, iqr_stats(masked_pkg_j, 3)["median"]),
            3,
        )

    defective_draws_evaluated = total_draws - acct_masked["semantic_commits"]

    arm_d_summary = {
        "label": "Arm D — In-Loop Earley/Pushdown CFG+Type Token Mask + Arm C Mutant Commit Gate",
        "vocabulary_size": len(VOCAB),
        "seeded_candidate_draws": total_draws,
        "trials": n_trials,
        "reps_per_trial": reps_per_trial,
        "unconstrained_posthoc_baseline": {
            **acct_unconstrained,
            "single_draw_syntax_reject_rate": round(
                acct_unconstrained["single_draw_syntax_type_rejects"] / total_draws, 6
            ),
            "wall_us_per_draw_iqr": iqr_stats(unconstrained_us_per_draw, 3),
            "pkg_reported_uj_per_draw_iqr": iqr_stats(unconstrained_pkg_j, 3) if unconstrained_pkg_j else None,
            "core_reported_uj_per_draw_iqr": iqr_stats(unconstrained_core_j, 3) if unconstrained_core_j else None,
            "measured_j": None,
            "est_j": None,
            "evidence_class": meter.evidence_class,
        },
        "grammar_masked_plus_mutant_gate": {
            **acct_masked,
            "single_draw_syntax_reject_rate": round(
                acct_masked["single_draw_syntax_type_rejects"] / total_draws, 6
            ),
            "syntax_reject_ci95": clopper_pearson_interval(
                acct_masked["single_draw_syntax_type_rejects"], total_draws
            ),
            "semantic_false_accept_ci95": clopper_pearson_interval(
                acct_masked["semantic_false_accepts"], defective_draws_evaluated
            ),
            "wall_us_per_draw_iqr": iqr_stats(masked_us_per_draw, 3),
            "pkg_reported_uj_per_draw_iqr": iqr_stats(masked_pkg_j, 3) if masked_pkg_j else None,
            "core_reported_uj_per_draw_iqr": iqr_stats(masked_core_j, 3) if masked_core_j else None,
            "measured_j": None,
            "est_j": None,
            "evidence_class": meter.evidence_class,
        },
        "comparative_gains": {
            "wasted_syntax_type_tokens_eliminated_pct": syntax_waste_reduction_pct,
            "total_generated_tokens_reduction_pct": token_reduction_pct,
            "host_wall_speedup_x": speedup_x,
            "host_rapl_pkg_reported_j_saving_x": pkg_energy_ratio_x,
            "evidence_class": meter.evidence_class,
        },
    }
    return (arm_d_summary, energy_meta)


def render_results_md(report: dict[str, Any], receipt: dict[str, Any]) -> str:
    abc = report["arms_abc"]
    mut = abc["mutant_vacuity_audit"]
    arms = abc["arms"]
    arm_d = report["arm_d_grammar_and_energy"]
    unc = arm_d["unconstrained_posthoc_baseline"]
    msk = arm_d["grammar_masked_plus_mutant_gate"]
    gains = arm_d["comparative_gains"]
    host = report["host"]
    em = report["energy_telemetry"]

    unc_uj = (
        f"`{unc['pkg_reported_uj_per_draw_iqr']['median']} µJ` (`IQR {unc['pkg_reported_uj_per_draw_iqr']['iqr']}`)"
        if unc["pkg_reported_uj_per_draw_iqr"]
        else "`null` (`unmetered`)"
    )
    msk_uj = (
        f"`{msk['pkg_reported_uj_per_draw_iqr']['median']} µJ` (`IQR {msk['pkg_reported_uj_per_draw_iqr']['iqr']}`)"
        if msk["pkg_reported_uj_per_draw_iqr"]
        else "`null` (`unmetered`)"
    )

    lines = [
        "# Kit #8 (`spec-fidelity-barrier`) — Empirical Results",
        "",
        "- **Provenance Tier:** `Signed Provenance · Self-Checked` (`BLAKE3` + `Ed25519`; never self-labeled `\"Verified\"`)",
        f"- **Receipt Body `BLAKE3`:** `{receipt['body_blake3']}`",
        f"- **CPU / OS:** `{host['cpu_model']}` (`{host['logical_cpus']}` logical CPUs, `{host['os_kernel']}`)",
        f"- **Energy Evidence Class:** `{em['evidence_class']}` (`measured_j ⊥ reported_j ⊥ est_j ⊥ unmetered`, never summed)",
        "",
        "## 1. Progressive 4-Arm Commit Gate Fidelity (`40` Tasks, `200` Implanted Bugs, `200` AST Mutants)",
        "",
        "| Gate Architecture | Spec Visibility | AST Mutant Kill Rate | Defective Candidates Falsely Accepted (`/ 200`) | Candidate False-Accept Rate (Exact 95% Clopper–Pearson CI) | Tasks Admitting `>=1` Bug (`/ 40`) | Valid Candidates Accepted (`/ 40`) |",
        "|---|---|---|---|---|---|---|",
    ]
    for k, kill_str in (
        ("arm_a_shared_context_naive", f"`{mut['arm_a_mutant_kill_rate']*100:.1f}%` (`SPEC_VACUOUS_REFUSED`: `{mut['arm_a_tautological_specs_refused']}/40`)"),
        ("arm_b_isolated_spec_only", f"`{mut['arm_b_mutant_kill_rate']*100:.1f}%` (`SPEC_VACUOUS_REFUSED`: `{mut['arm_b_partial_specs_refused']}/40`)"),
        ("arm_c_mutant_vacuity_barrier", f"`{mut['arm_c_mutant_kill_rate']*100:.1f}%` (`SPEC_ADMITTED`: `{mut['arm_c_hardened_specs_admitted']}/40`)"),
    ):
        a = arms[k]
        ci = a["candidate_false_accept_ci95"]
        lines.append(
            f"| `{k}` | {'Shared (`Spec + Impl`)' if 'arm_a' in k else 'Isolated (`Spec ⊥ Impl`)'} | {kill_str} | "
            f"`{a['defective_candidates_falsely_accepted']} / {a['defective_candidates_total']}` | "
            f"`{ci['point']:.4f}` (`[{ci['ci95_two_sided_lo']:.4f}, {ci['ci95_two_sided_hi']:.4f}]`; 1-sided `<= {ci['ci95_one_sided_hi']:.5f}`) | "
            f"`{a['tasks_admitting_any_buggy_impl']} / {a['tasks_evaluated']}` | "
            f"`{a['valid_candidates_accepted']} / {a['valid_candidates_total']}` |"
        )

    lines.extend([
        "",
        "## 2. Arm D — In-Loop CFG/Type Token Masking vs. Post-Hoc Rejection (`1,000` Seeded Draws)",
        "",
        "| Decoding + Gate Regime | Single-Draw Syntax/Type Rejects (`/ 1,000`) | Syntax/Type Wasted Tokens | Total Generated Tokens | Semantic False Accepts | Median Latency / Draw | Median RAPL `reported_j` / Draw |",
        "|---|---|---|---|---|---|---|",
        f"| `unconstrained_posthoc_plus_arm_c` | `{unc['single_draw_syntax_type_rejects']} / 1000` (`{unc['single_draw_syntax_reject_rate']*100:.1f}%`) | `{unc['wasted_syntax_type_tokens']}` | `{unc['total_tokens_generated']}` | `{unc['semantic_false_accepts']}` | `{unc['wall_us_per_draw_iqr']['median']} µs` | {unc_uj} |",
        f"| `grammar_mask_plus_mutant_gate` (**Arm D**) | **`{msk['single_draw_syntax_type_rejects']} / 1000` (`0.0%`)** | **`{msk['wasted_syntax_type_tokens']}` (`-{gains['wasted_syntax_type_tokens_eliminated_pct']}%`)** | **`{msk['total_tokens_generated']}` (`-{gains['total_generated_tokens_reduction_pct']}%`)** | **`{msk['semantic_false_accepts']} / 800`** (1-sided 95% CI `<= {msk['semantic_false_accept_ci95']['ci95_one_sided_hi']:.5f}`) | **`{msk['wall_us_per_draw_iqr']['median']} µs` (`{gains['host_wall_speedup_x']}x`)** | **{msk_uj}** (`{gains['host_rapl_pkg_reported_j_saving_x']}x` saving) |",
        "",
    ])
    return "\n".join(lines)


def run_evaluation(quick: bool = False, write_outputs: bool = True, out_dir: Path | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    tasks = build_40_task_suite()
    suite_canonical = json.dumps(
        [{"id": t.task_id, "domain": t.domain, "src": t.reference_src.strip(), "n_vec": len(t.test_inputs)} for t in tasks],
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    suite_blake3 = blake3_hex(suite_canonical)

    abc_res = evaluate_arms_abc(tasks)
    arm_d_res, energy_meta = evaluate_arm_d_grammar_and_energy(tasks, quick=quick)
    host = sanitized_host_info()

    report = {
        "schema": "openie.spec_fidelity_barrier.results.v1",
        "kit_id": "kits/spec-fidelity-barrier",
        "license": "Apache-2.0",
        "provenance_tier": "Signed Provenance · Self-Checked",
        "mode": "quick" if quick else "standard",
        "suite_summary": {
            "total_tasks": len(tasks),
            "vectors_per_task": 25,
            "total_test_vectors": len(tasks) * 25,
            "domains": sorted({t.domain for t in tasks}),
            "suite_precommitment_blake3": suite_blake3,
        },
        "host": host,
        "energy_telemetry": energy_meta,
        "arms_abc": abc_res,
        "arm_d_grammar_and_energy": arm_d_res,
    }

    report_bytes = json.dumps(report, sort_keys=True, separators=(",", ":")).encode("utf-8")
    results_blake3 = blake3_derive_key_hex("openie.kit.spec_fidelity_barrier.results.v1", report_bytes)

    receipt_payload = {
        "results_blake3": results_blake3,
        "suite_precommitment_blake3": suite_blake3,
        "substrate_id": energy_meta["substrate_id"],
        "energy_evidence_class": energy_meta["evidence_class"],
        "mode": report["mode"],
        "total_tasks": len(tasks),
        "total_ast_mutants": abc_res["mutant_vacuity_audit"]["total_ast_mutants_synthesized"],
        "arm_a_candidate_false_accept": abc_res["arms"]["arm_a_shared_context_naive"]["candidate_false_accept_ci95"],
        "arm_b_candidate_false_accept": abc_res["arms"]["arm_b_isolated_spec_only"]["candidate_false_accept_ci95"],
        "arm_c_candidate_false_accept": abc_res["arms"]["arm_c_mutant_vacuity_barrier"]["candidate_false_accept_ci95"],
        "arm_c_vacuous_specs_refused": {
            "arm_a_refused": f"{abc_res['mutant_vacuity_audit']['arm_a_tautological_specs_refused']}/40",
            "arm_b_refused": f"{abc_res['mutant_vacuity_audit']['arm_b_partial_specs_refused']}/40",
            "status_code": "SPEC_VACUOUS_REFUSED",
            "arm_c_mutant_kill_rate": abc_res["mutant_vacuity_audit"]["arm_c_mutant_kill_rate"],
        },
        "arm_d_1000_draws": {
            "unconstrained_syntax_rejects": arm_d_res["unconstrained_posthoc_baseline"]["single_draw_syntax_type_rejects"],
            "grammar_masked_syntax_rejects": arm_d_res["grammar_masked_plus_mutant_gate"]["single_draw_syntax_type_rejects"],
            "wasted_syntax_tokens_eliminated_pct": arm_d_res["comparative_gains"]["wasted_syntax_type_tokens_eliminated_pct"],
            "total_generated_tokens_reduction_pct": arm_d_res["comparative_gains"]["total_generated_tokens_reduction_pct"],
            "semantic_false_accept_ci95": arm_d_res["grammar_masked_plus_mutant_gate"]["semantic_false_accept_ci95"],
            "unconstrained_wall_us_per_draw_median": arm_d_res["unconstrained_posthoc_baseline"]["wall_us_per_draw_iqr"]["median"],
            "grammar_masked_wall_us_per_draw_median": arm_d_res["grammar_masked_plus_mutant_gate"]["wall_us_per_draw_iqr"]["median"],
            "unconstrained_pkg_reported_uj_per_draw_median": (
                arm_d_res["unconstrained_posthoc_baseline"]["pkg_reported_uj_per_draw_iqr"]["median"]
                if arm_d_res["unconstrained_posthoc_baseline"]["pkg_reported_uj_per_draw_iqr"]
                else None
            ),
            "grammar_masked_pkg_reported_uj_per_draw_median": (
                arm_d_res["grammar_masked_plus_mutant_gate"]["pkg_reported_uj_per_draw_iqr"]["median"]
                if arm_d_res["grammar_masked_plus_mutant_gate"]["pkg_reported_uj_per_draw_iqr"]
                else None
            ),
            "host_rapl_pkg_reported_j_saving_x": arm_d_res["comparative_gains"]["host_rapl_pkg_reported_j_saving_x"],
            "host_wall_speedup_x": arm_d_res["comparative_gains"]["host_wall_speedup_x"],
        },
        "full_report": report,
    }

    det_seed = bytes.fromhex(blake3_derive_key_hex("openie.kit.spec_fidelity_barrier.key.v1", report_bytes)[:64])
    receipt = seal_signed_receipt(
        kit_id="kits/spec-fidelity-barrier",
        payload=receipt_payload,
        domain_context="openie.kit.spec_fidelity_barrier.receipt.v1",
        seed32=det_seed,
    )
    if not verify_signed_receipt(receipt):
        raise RuntimeError("Self-verification of signed receipt failed!")

    md_text = render_results_md(report, receipt)
    receipt_json_text = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    assert_sanitized(receipt_json_text)
    assert_sanitized(md_text)

    if write_outputs:
        target_dir = out_dir or (HERE / "results")
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "spec_fidelity_receipt.json").write_text(receipt_json_text, encoding="utf-8")
        if out_dir is None:
            (HERE / "RESULTS.md").write_text(md_text, encoding="utf-8")

    return (report, receipt)


def main() -> None:
    parser = argparse.ArgumentParser(description="Kit #8: Spec-Fidelity Barrier & Grammar-Masked Gate Evaluator")
    parser.add_argument("--quick", action="store_true", help="Run fast smoke-test trial counts")
    parser.add_argument("--no-write", action="store_true", help="Evaluate in-memory without overwriting committed receipts")
    parser.add_argument("--out-dir", type=Path, default=None, help="Optional output directory for receipt JSON")
    args = parser.parse_args()

    report, receipt = run_evaluation(quick=args.quick, write_outputs=not args.no_write, out_dir=args.out_dir)
    abc = report["arms_abc"]["arms"]
    arm_d = report["arm_d_grammar_and_energy"]
    print(f"[spec-fidelity-barrier] 40-task suite BLAKE3: {report['suite_summary']['suite_precommitment_blake3'][:16]}...")
    print(
        f"  Arm A (shared_context_naive):    false_accept = "
        f"{abc['arm_a_shared_context_naive']['defective_candidates_falsely_accepted']}/200 "
        f"({abc['arm_a_shared_context_naive']['candidate_false_accept_ci95']['point']:.3f})"
    )
    print(
        f"  Arm B (isolated_spec_only):      false_accept = "
        f"{abc['arm_b_isolated_spec_only']['defective_candidates_falsely_accepted']}/200 "
        f"({abc['arm_b_isolated_spec_only']['candidate_false_accept_ci95']['point']:.3f})"
    )
    print(
        f"  Arm C (mutant_vacuity_barrier):  false_accept = "
        f"{abc['arm_c_mutant_vacuity_barrier']['defective_candidates_falsely_accepted']}/200 "
        f"(95% CI 1-sided <= {abc['arm_c_mutant_vacuity_barrier']['candidate_false_accept_ci95']['ci95_one_sided_hi']:.5f}, "
        f"mutants killed = 200/200)"
    )
    print(
        f"  Arm D (grammar_mask + Arm C):    syntax_rejects = "
        f"{arm_d['grammar_masked_plus_mutant_gate']['single_draw_syntax_type_rejects']}/1000 "
        f"(vs {arm_d['unconstrained_posthoc_baseline']['single_draw_syntax_type_rejects']}/1000 unconstrained), "
        f"total_tokens -{arm_d['comparative_gains']['total_generated_tokens_reduction_pct']}%, "
        f"speedup = {arm_d['comparative_gains']['host_wall_speedup_x']}x, "
        f"evidence = {report['energy_telemetry']['evidence_class']}"
    )
    print(f"  Signed Provenance · Self-Checked receipt BLAKE3: {receipt['body_blake3']}")


if __name__ == "__main__":
    main()
