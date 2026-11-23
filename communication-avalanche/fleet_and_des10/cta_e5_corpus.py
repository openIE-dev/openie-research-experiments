#!/usr/bin/env python3
"""
CTA-E5 Benchmark Corpus: 100 Test Tasks across 5 Regimes (R1-R5, 20/regime)
plus 15 Held-Out Calibration Probes (CAL_R1-CAL_R5, 3/regime, 0 overlap).

Strict Oracle Isolation (Falsifier 3):
  - `get_public_corpus()` and `get_calibration_probes()` strip all ground-truth answers
    and held-out oracle test vectors before passing tasks to any camp or Digital Enzyme.
  - `evaluate_oracle(task_id, prediction)` is invoked strictly post-commit by the outer
    benchmark scorer.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import random
from typing import Any

# ============================================================================
# 1. Canonical Episode Seed Bank (Prior Solved Archetypes for R1 & C5)
# ============================================================================


def _eval_r1_archetype(arch_id: str, params: list[int]) -> int:
    a, b, c, d = params[0], params[1], params[2], params[3]
    if arch_id == "affine_sat_q1000":
        v = (a * b + c * 1000) // 1000
        return max(-d, min(d, v))
    if arch_id == "quorum_clamp_diff":
        w = 3 * a - 2 * b + c
        return w if abs(w) >= d else 0
    if arch_id == "parity_quad_step":
        q = a * a + b * c
        return (q ^ d) if (q & 1) else (q + d)
    if arch_id == "deadzone_relay":
        err = a - b
        if abs(err) <= c:
            return 0
        return (err - c) * d if err > 0 else (err + c) * d
    if arch_id == "xor_rot16_tag":
        u = ((a & 0xFFFF) * 257 + (b & 0xFFFF)) & 0xFFFF
        rot = ((u << (c % 15 + 1)) | (u >> (16 - (c % 15 + 1)))) & 0xFFFF
        return rot ^ (d & 0xFFFF)
    if arch_id == "interval_quant_mid":
        mid = (a + b) // 2
        step = max(1, c)
        return (mid // step) * step + d
    if arch_id == "mod_affine_congruence":
        m = max(3, d)
        return ((a * b + c) % m + m) % m
    if arch_id == "leaky_dual_accum":
        s1 = max(0, a - c)
        s2 = max(0, b - c)
        return s1 * d + s2
    # Newly crystallizable archetypes (first encountered in R3/R5 during online stream!)
    if arch_id == "cryst_mod_pair_witness":
        m = max(5, d)
        for x in range(1, m):
            if (a * x + b) % m == (c % m):
                return x
        return -1
    if arch_id == "cryst_bounded_triad_sum":
        return max(0, min(d, a + b - c))
    if arch_id == "cryst_rle_chunk_count":
        # Total chunks when run of length `a` is split at max chunk `b` plus run `c` split at `b`
        k = max(1, b)
        return ((a + k - 1) // k) + ((c + k - 1) // k) + (0 * d)
    if arch_id == "cryst_prefix_step_peaks":
        seq = [a, b, c, d, a + c, b + d]
        mx = -10**18
        cnt = 0
        for v in seq:
            if v > mx:
                mx = v
                cnt += 1
        return cnt
    raise ValueError(f"Unknown R1 archetype {arch_id}")


PRIOR_SEED_ARCHETYPES = [
    ("affine_sat_q1000", "clamp((p0 * p1 + p2 * 1000) // 1000, -p3, p3)"),
    ("quorum_clamp_diff", "(3*p0 - 2*p1 + p2) if abs(3*p0 - 2*p1 + p2) >= p3 else 0"),
    ("parity_quad_step", "((p0*p0 + p1*p2) ^ p3) if ((p0*p0 + p1*p2) & 1) else ((p0*p0 + p1*p2) + p3)"),
    ("deadzone_relay", "0 if abs(p0 - p1) <= p2 else ((p0 - p1 - p2)*p3 if p0 > p1 else (p0 - p1 + p2)*p3)"),
    ("xor_rot16_tag", "rotl16(((p0 & 0xffff)*257 + (p1 & 0xffff)) & 0xffff, (p2 % 15) + 1) ^ (p3 & 0xffff)"),
    ("interval_quant_mid", "(((p0 + p1) // 2) // max(1, p2)) * max(1, p2) + p3"),
    ("mod_affine_congruence", "((p0 * p1 + p2) % max(3, p3))"),
    ("leaky_dual_accum", "max(0, p0 - p2) * p3 + max(0, p1 - p2)"),
]

CRYSTALLIZABLE_ARCHETYPES = [
    ("cryst_mod_pair_witness", "smallest x in 1..max(5,p3)-1 with (p0*x + p1) % max(5,p3) == p2 % max(5,p3), else -1"),
    ("cryst_bounded_triad_sum", "max(0, min(p3, p0 + p1 - p2))"),
    ("cryst_rle_chunk_count", "ceil_div(p0, max(1, p1)) + ceil_div(p2, max(1, p1))"),
    ("cryst_prefix_step_peaks", "strict prefix maxima count of [p0, p1, p2, p3, p0+p2, p1+p3]"),
]


def _build_r1_tasks(rng: random.Random, count: int, prefix: str, include_cryst: bool) -> tuple[list[dict], dict[str, Any]]:
    tasks, oracles = [], {}
    alias_sets = [
        ("alpha", "beta", "gamma", "bound"),
        ("sensor_u", "gain_v", "bias_w", "cap_z"),
        ("flux_a", "rate_b", "trim_c", "limit_d"),
        ("xi_0", "xi_1", " eta_2".strip(), "tau_3"),
    ]
    # Zipfian weights over the 8 prior archetypes for the first (count - 4) tasks
    n_prior = (count - 4) if include_cryst else count
    for idx in range(count):
        tid = f"{prefix}_{idx + 1:02d}"
        if include_cryst and idx >= n_prior:
            arch_id, canon_expr = CRYSTALLIZABLE_ARCHETYPES[idx - n_prior]
            requires_online_cryst = True
        else:
            # Zipfian skew: earlier archetypes recur more frequently
            zipf_pool = [0, 0, 0, 1, 1, 1, 2, 2, 3, 3, 4, 5, 6, 7]
            arch_id, canon_expr = PRIOR_SEED_ARCHETYPES[zipf_pool[idx % len(zipf_pool)]]
            requires_online_cryst = False

        names = list(alias_sets[idx % len(alias_sets)])
        perm = [0, 1, 2, 3]
        rng.shuffle(perm)
        raw_vals = [rng.randint(7, 65), rng.randint(5, 48), rng.randint(3, 29), rng.randint(11, 90)]
        ans = _eval_r1_archetype(arch_id, raw_vals)

        # Permuted named bindings presented to solvers (alpha-renamed + argument-permuted!)
        permuted_bindings = {names[perm[k]]: raw_vals[k] for k in range(4)}
        renamed_expr = canon_expr
        for k in range(4):
            renamed_expr = renamed_expr.replace(f"p{k}", f"__{names[perm[k]]}__")
        renamed_expr = renamed_expr.replace("__", "")

        pub_ex_vals = [12, 9, 4, 25]
        pub_ex_ans = _eval_r1_archetype(arch_id, pub_ex_vals)

        tasks.append({
            "task_id": tid,
            "regime": "R1",
            "answer_kind": "int",
            "requires_online_crystallization": requires_online_cryst,
            "prompt_nl": (
                f"Evaluate the alpha-renamed recurrence schema `{renamed_expr}` (using Python integer floor "
                f"division `//` and exact bitwise ops) at bindings {json.dumps(permuted_bindings, sort_keys=True)}. "
                f"Return ONLY JSON `{{\"answer\": <int>}}`."
            ),
            "schema_ir": {
                "kind": "alpha_renamed_recurrence",
                "debruijn_op_skeleton": canon_expr,  # structural normal form after alpha-erasure
                "canonical_ordered_args": raw_vals,
                "permuted_bindings": permuted_bindings,
            },
            "public_examples": [{"canonical_args": pub_ex_vals, "expected": pub_ex_ans}],
        })
        oracles[tid] = {"expected_int": ans, "archetype": arch_id}
    return tasks, oracles


# ============================================================================
# 2. R2: Sub-Microsecond Bitvector / Boolean Gate / Protocol Framing (20 Tasks)
# ============================================================================


def _eval_r2_circuit(spec: dict[str, Any], word: int) -> int:
    nbits = spec["n_bits"]
    b = [(word >> i) & 1 for i in range(nbits)]
    gtype = spec["gate_family"]
    mask_a = spec["mask_a"]
    mask_b = spec["mask_b"]
    thresh = spec["thresh"]

    pop_a = bin(word & mask_a).count("1")
    par_b = bin(word & mask_b).count("1") & 1
    if gtype == "quorum_xor_parity":
        return 1 if ((pop_a >= thresh) ^ bool(par_b)) else 0
    if gtype == "can_stuff_and_guard":
        # Detect 4 consecutive 1s in lower nbits OR parity mismatch on mask_b
        run4 = any(all(((word >> (i + k)) & 1) == 1 for k in range(4)) for i in range(nbits - 3))
        return 1 if (run4 and par_b == 0) or (not run4 and pop_a == thresh) else 0
    if gtype == "fsm_mealy_header_eof":
        # 3-state Mealy automaton scanning bits LSB->MSB: S0(idle)->S1(hdr)->S2(payload)->S0(eof)
        st = 0
        out_acc = 0
        for i, bit in enumerate(b):
            if st == 0:
                st = 1 if bit == 1 else 0
            elif st == 1:
                if bit == par_b:
                    st = 2
                    out_acc ^= 1 << (i % 4)
                else:
                    st = 0
            else:
                if bit == 1 and (i % 2 == (thresh % 2)):
                    st = 0
                    out_acc ^= 1
                else:
                    st = 1
        return out_acc & 1
    # lut6_cascade
    lo6 = word & 0x3F
    hi = (word >> 3) & 0x3F
    lut_tbl = spec["lut6_hex"]
    g0 = (lut_tbl >> lo6) & 1
    g1 = (lut_tbl >> hi) & 1
    return (g0 ^ g1) if par_b else (g0 | g1)


def _build_r2_tasks(rng: random.Random, count: int, prefix: str) -> tuple[list[dict], dict[str, Any]]:
    tasks, oracles = [], {}
    families = ["quorum_xor_parity", "can_stuff_and_guard", "fsm_mealy_header_eof", "lut6_cascade"]
    for idx in range(count):
        tid = f"{prefix}_{idx + 1:02d}"
        nbits = 6 + (idx % 5)  # 6 to 10 bits
        fam = families[idx % len(families)]
        mask_a = rng.randint(7, (1 << nbits) - 1) | 0b101
        mask_b = rng.randint(5, (1 << nbits) - 1) | 0b011
        thresh = 2 + (idx % 3)
        lut6 = rng.getrandbits(64) | 0xA5C3_5A3C_9669_0F0F
        spec = {
            "gate_family": fam,
            "n_bits": nbits,
            "mask_a": mask_a,
            "mask_b": mask_b,
            "thresh": thresh,
            "lut6_hex": lut6,
        }
        eval_inputs = [rng.randint(0, (1 << nbits) - 1) for _ in range(16)]
        packed_16bit = sum((_eval_r2_circuit(spec, w) << i) for i, w in enumerate(eval_inputs))
        pub_inputs = [0, (1 << nbits) - 1, mask_a & ((1 << nbits) - 1)]
        pub_outputs = [_eval_r2_circuit(spec, w) for w in pub_inputs]

        tasks.append({
            "task_id": tid,
            "regime": "R2",
            "answer_kind": "int",
            "prompt_nl": (
                f"Bitvector / FSM classification task (`{fam}`, `{nbits}`-bit words): given circuit spec "
                f"`mask_a={mask_a}`, `mask_b={mask_b}`, `thresh={thresh}`, `lut6_hex={lut6}`, evaluate the "
                f"1-bit output `y_i` for each of the 16 input words `W = {eval_inputs}` (where bit `b` of word `w` "
                f"is `(w >> b) & 1`). Rules: "
                f"`quorum_xor_parity`: `int((popcount(w & mask_a) >= thresh) ^ ((popcount(w & mask_b) & 1) == 1))`; "
                f"`can_stuff_and_guard`: let `run4` = 4 consecutive 1-bits anywhere in bits `0..{nbits-1}` and "
                f"`par_b = popcount(w & mask_b) & 1`; output `1` iff `(run4 and par_b==0) or (not run4 and popcount(w & mask_a)==thresh)`; "
                f"`fsm_mealy_header_eof`: 3-state Mealy scan `st=0, out_acc=0` over `i=0..{nbits-1}`, `bit=(w>>i)&1`: "
                f"if `st==0`: `st = 1 if bit==1 else 0`; elif `st==1`: if `bit==par_b`: `st=2; out_acc ^= 1<<(i%4)` else `st=0`; "
                f"else (`st==2`): if `bit==1 and (i%2)==(thresh%2)`: `st=0; out_acc ^= 1` else `st=1`; output `out_acc & 1`; "
                f"`lut6_cascade`: `g0=(lut6_hex>>(w&63))&1`, `g1=(lut6_hex>>((w>>3)&63))&1`, output `g0^g1` if `par_b==1` else `g0|g1`. "
                f"Pack the 16 outputs into integer `sum(y_i << i for i in range(16))`. Return ONLY JSON `{{\"answer\": <int>}}`."
            ),
            "schema_ir": {"kind": "boolean_lut_fsm", "circuit_spec": spec, "eval_inputs": eval_inputs},
            "public_examples": [{"word": w, "bit_out": y} for w, y in zip(pub_inputs, pub_outputs)],
        })
        oracles[tid] = {"expected_int": packed_16bit}
    return tasks, oracles


# ============================================================================
# 3. R3: Exact Deductive / Arithmetic / SAT-SMT Constraint Satisfaction (20)
# ============================================================================


def _build_r3_tasks(rng: random.Random, count: int, prefix: str) -> tuple[list[dict], dict[str, Any]]:
    tasks, oracles = [], {}
    domain = list(range(1, 9))  # 1..8, 5 distinct variables -> P(8,5) = 6,720 states
    all_perms = list(itertools.permutations(domain, 5))

    idx = 0
    attempt = 0
    while idx < count:
        attempt += 1
        target = all_perms[(idx * 797 + attempt * 131) % len(all_perms)]
        c1_w = [rng.randint(1, 4) for _ in range(5)]
        c1_rhs = sum(w * x for w, x in zip(c1_w, target))
        c2_rhs = target[0] + target[2] - target[4]
        mod_p = [5, 7, 9, 11][idx % 4]
        mod_rem = (2 * target[1] + 3 * target[3] + target[4]) % mod_p
        ord_pair = (0, 3) if target[0] < target[3] else (3, 0)
        xor_rhs = (target[1] ^ target[2]) + target[0]

        # Verify uniqueness across all 8^5 tuples with AllDifferent!
        matches = []
        for cand in all_perms:
            if cand[ord_pair[0]] >= cand[ord_pair[1]]:
                continue
            if cand[0] + cand[2] - cand[4] != c2_rhs:
                continue
            if ((cand[1] ^ cand[2]) + cand[0]) != xor_rhs:
                continue
            if (2 * cand[1] + 3 * cand[3] + cand[4]) % mod_p != mod_rem:
                continue
            if sum(w * x for w, x in zip(c1_w, cand)) != c1_rhs:
                continue
            matches.append(list(cand))
            if len(matches) > 1:
                break

        if len(matches) == 1:
            tid = f"{prefix}_{idx + 1:02d}"
            clauses = {
                "domain_inclusive": [1, 8],
                "n_vars": 5,
                "all_different": True,
                "lt_pair": list(ord_pair),
                "linear_weights": c1_w,
                "linear_rhs": c1_rhs,
                "triad_v0_plus_v2_minus_v4": c2_rhs,
                "mod_p": mod_p,
                "mod_2v1_plus_3v3_plus_v4": mod_rem,
                "xor_v1_v2_plus_v0": xor_rhs,
            }
            tasks.append({
                "task_id": tid,
                "regime": "R3",
                "answer_kind": "int_list",
                "prompt_nl": (
                    f"Find the unique 5-tuple `v = [v0, v1, v2, v3, v4]` of pairwise-distinct integers in `1..8` "
                    f"satisfying ALL 5 constraints: "
                    f"(1) `v[{ord_pair[0]}] < v[{ord_pair[1]}]`; "
                    f"(2) `{c1_w[0]}*v0 + {c1_w[1]}*v1 + {c1_w[2]}*v2 + {c1_w[3]}*v3 + {c1_w[4]}*v4 == {c1_rhs}`; "
                    f"(3) `v0 + v2 - v4 == {c2_rhs}`; "
                    f"(4) `(2*v1 + 3*v3 + v4) % {mod_p} == {mod_rem}`; "
                    f"(5) `(v1 ^ v2) + v0 == {xor_rhs}`. "
                    f"Return ONLY JSON `{{\"answer\": [v0, v1, v2, v3, v4]}}`."
                ),
                "schema_ir": {"kind": "fd_sat_constraints", "clauses": clauses},
                "public_examples": [{"check": "all_different_in_1..8", "expected": True}],
            })
            oracles[tid] = {"expected_list": matches[0], "clauses": clauses}
            idx += 1
    return tasks, oracles


# ============================================================================
# 4. R4: Structural Causal do(X=x) & Non-Myopic 6-Step Horizon Planning (20)
# ============================================================================


def _build_r4_tasks(rng: random.Random, count: int, prefix: str) -> tuple[list[dict], dict[str, Any]]:
    tasks, oracles = [], {}
    n_causal = count // 2
    # Part A: Confounded Simpson's-paradox Structural Causal DAGs (Z1, Z2 -> X, Y; X -> Y)
    for idx in range(n_causal):
        tid = f"{prefix}_{idx + 1:02d}"
        # 4 strata s = 0..3 over confounders (Z1, Z2) with exact integer permille/bp weights summing to 10,000
        w_raw = [1800 + 200 * (idx % 3), 3200 - 100 * (idx % 3), 2900, 0]
        w_raw[3] = 10000 - sum(w_raw[:3])
        # High-severity strata choose X=1 frequently (0.85, 0.80) but have low base survival Y=1;
        # within EVERY stratum X=1 raises P(Y=1) over X=0, yet observational P(Y=1|X=1) < P(Y=1|X=0)!
        px1 = [8500, 7800, 2200, 1400]
        base_y0 = [1200 + 80 * idx, 2100 + 60 * idx, 6800 + 50 * idx, 7900 + 40 * idx]
        lift = 1100 + 70 * (idx % 5)
        py_x0 = [min(9500, v) for v in base_y0]
        py_x1 = [min(9800, v + lift) for v in py_x0]

        # Exact backdoor do-calculus: P(Y=1 | do(X=1)) = sum_z P(Z=z) * P(Y=1 | X=1, Z=z)
        p_do_x1_bp = round(sum(w_raw[s] * py_x1[s] for s in range(4)) / 10000.0)
        p_do_x0_bp = round(sum(w_raw[s] * py_x0[s] for s in range(4)) / 10000.0)
        # Confounded observational P(Y=1 | X=1)
        num_obs1 = sum(w_raw[s] * (px1[s] / 10000.0) * (py_x1[s] / 10000.0) for s in range(4))
        den_obs1 = sum(w_raw[s] * (px1[s] / 10000.0) for s in range(4))
        p_obs_x1_bp = round(10000.0 * num_obs1 / den_obs1)

        scm_spec = {
            "strata_prior_bp": w_raw,
            "p_x1_given_z_bp": px1,
            "p_y1_given_x0_z_bp": py_x0,
            "p_y1_given_x1_z_bp": py_x1,
            "confounded_obs_x1_bp": p_obs_x1_bp,
        }
        tasks.append({
            "task_id": tid,
            "regime": "R4",
            "answer_kind": "int",
            "sub_regime": "causal_do_calculus",
            "prompt_nl": (
                f"Structural Causal DAG `Z -> X`, `Z -> Y`, `X -> Y` with 4 confounder strata `z in 0..3` "
                f"(all probabilities in basis points `bp`, where `10000 bp = 1.0`): "
                f"`P(Z=z) = {w_raw} bp`, `P(X=1|Z=z) = {px1} bp`, "
                f"`P(Y=1|X=0,Z=z) = {py_x0} bp`, `P(Y=1|X=1,Z=z) = {py_x1} bp`. "
                f"Compute the exact interventional probability `round(10000 * P(Y=1 | do(X=1)))` via "
                f"Pearl's backdoor adjustment (do NOT return confounded observational `P(Y=1|X=1)`). "
                f"Return ONLY JSON `{{\"answer\": <int>}}`."
            ),
            "schema_ir": {"kind": "causal_backdoor_do", "scm": scm_spec, "target_do_x": 1},
            "public_examples": [{"query": "do(X=0)_bp", "expected": p_do_x0_bp}],
        })
        oracles[tid] = {"expected_int": p_do_x1_bp, "confounded_trap_bp": p_obs_x1_bp}

    # Part B: 6-Step Deceptive-Valley Horizon Planning MDPs (3^6 = 729 trajectories)
    for j in range(count - n_causal):
        idx = n_causal + j
        tid = f"{prefix}_{idx + 1:02d}"
        # Deterministic 6-step tree with state (step, mode, pos); action a in {0, 1, 2}
        # Action 0 at step 0 enters greedy valley (+14, +14, +14, -65, -65, -40 = -128);
        # Unique optimal sequence pays a -5 toll at step 0 via a_star[0] and hits +92 bonus at step 5!
        a_star = [(j + s * 2 + 1) % 3 for s in range(6)]
        if a_star[0] == 0:
            a_star[0] = 1
        step_bonuses = [rng.randint(9, 17) for _ in range(6)]
        mdp_spec = {
            "horizon": 6,
            "n_actions": 3,
            "greedy_trap_step0_action": 0,
            "greedy_early_reward": 15,
            "greedy_late_penalty": -72,
            "bridge_toll_step0": -5,
            "target_gates": a_star,
            "gate_bonuses": step_bonuses,
            "terminal_summit_bonus": 85 + 3 * j,
        }

        def score_traj(seq: list[int], sp: dict[str, Any] = mdp_spec) -> int:
            if seq[0] == sp["greedy_trap_step0_action"]:
                tot = 0
                for stp, act in enumerate(seq):
                    if stp < 3:
                        tot += sp["greedy_early_reward"] - act * 2
                    else:
                        tot += sp["greedy_late_penalty"] + act
                return tot
            tot = sp["bridge_toll_step0"] if seq[0] == sp["target_gates"][0] else -12
            on_ridge = seq[0] == sp["target_gates"][0]
            for stp in range(1, 6):
                if on_ridge and seq[stp] == sp["target_gates"][stp]:
                    tot += sp["gate_bonuses"][stp]
                else:
                    on_ridge = False
                    tot += 2 - abs(seq[stp] - sp["target_gates"][stp]) * 4
            if on_ridge:
                tot += sp["terminal_summit_bonus"]
            return tot

        best_val = score_traj(a_star)
        # Confirm strict uniqueness over all 3^6 = 729 trajectories
        winners = [
            list(cand)
            for cand in itertools.product((0, 1, 2), repeat=6)
            if score_traj(list(cand)) == best_val
        ]
        assert len(winners) == 1 and winners[0] == a_star

        tasks.append({
            "task_id": tid,
            "regime": "R4",
            "answer_kind": "int_list",
            "sub_regime": "deceptive_horizon_mdp",
            "prompt_nl": (
                f"6-step non-myopic sequential decision MDP (`a_0..a_5` each in `{{0,1,2}}`): "
                f"choosing `a_0 == 0` enters a greedy deceptive valley yielding `+15 - 2*a_t` for `t=0,1,2` "
                f"followed by `-72 + a_t` for `t=3,4,5`. Otherwise at `t=0` reward is `-5` if `a_0 == {a_star[0]}` "
                f"(putting agent `on_ridge=True`) else `-12` (`on_ridge=False`). For `t=1..5`, if `on_ridge` and "
                f"`a_t == G[t]` where `G = {a_star}`, reward is `B[t]` with `B = {step_bonuses}` and `on_ridge` "
                f"stays `True`; else `on_ridge` becomes `False` and step reward is `2 - 4*abs(a_t - G[t])`. "
                f"If `on_ridge` remains `True` after `t=5`, add terminal summit bonus `+{mdp_spec['terminal_summit_bonus']}`. "
                f"Return the unique reward-maximizing 6-action sequence as JSON `{{\"answer\": [a0,a1,a2,a3,a4,a5]}}`."
            ),
            "schema_ir": {"kind": "horizon_mdp_6step", "mdp": mdp_spec},
            "public_examples": [{"greedy_all_zeros_return": score_traj([0, 0, 0, 0, 0, 0])}],
        })
        oracles[tid] = {"expected_list": a_star, "optimal_return": best_val}

    return tasks, oracles


# ============================================================================
# 5. R5: Open-World Spec-to-Program Synthesis & Multi-Constraint Repair (20+3)
# ============================================================================

R5_SPECS: list[dict[str, Any]] = [
    {
        "fn_name": "rle_chunked",
        "sig": "def rle_chunked(xs: list[int], k: int) -> list[tuple[int, int]]:",
        "doc": "Run-length encode `xs` into `(value, run_len)` tuples, splitting any contiguous run longer than `max(1, k)` into chunks of at most `max(1, k)`.",
        "pub": [(([1, 1, 1, 1, 2, 2], 3), [(1, 3), (1, 1), (2, 2)]), (([], 4), [])],
        "hold": [
            (([5, 5, 5, 5, 5], 2), [(5, 2), (5, 2), (5, 1)]),
            (([7, -1, -1, 7], 1), [(7, 1), (-1, 1), (-1, 1), (7, 1)]),
            (([0, 0, 0], 0), [(0, 1), (0, 1), (0, 1)]),
            (([3], 10), [(3, 1)]),
        ],
    },
    {
        "fn_name": "count_strict_prefix_maxima",
        "sig": "def count_strict_prefix_maxima(xs: list[int]) -> int:",
        "doc": "Count indices `i` where `xs[i]` is strictly greater than all `xs[0..i-1]` (`xs[0]` always counts if `xs` is non-empty; return `0` for `[]`).",
        "pub": [(([3, 1, 4, 4, 5],), 3), (([],), 0)],
        "hold": [
            (([-10, -5, -5, -2, -8, 0],), 4),
            (([9, 8, 7, 6],), 1),
            (([0],), 1),
            (([-3, -4, -3],), 1),
        ],
    },
    {
        "fn_name": "merge_closed_intervals",
        "sig": "def merge_closed_intervals(iv: list[tuple[int, int]]) -> list[tuple[int, int]]:",
        "doc": "Sort and merge overlapping or touching closed integer intervals `(l, r)` (`l <= r`), returning disjoint `(l, r)` tuples in ascending order.",
        "pub": [(([(1, 3), (2, 6), (8, 10)],), [(1, 6), (8, 10)]), (([],), [])],
        "hold": [
            (([(5, 7), (1, 2), (2, 5)],), [(1, 7)]),
            (([(-4, -1), (-10, -5), (-5, -4)],), [(-10, -1)]),
            (([(3, 3), (3, 3)],), [(3, 3)]),
            (([(10, 12), (1, 4), (6, 8)],), [(1, 4), (6, 8), (10, 12)]),
        ],
    },
    {
        "fn_name": "valid_brackets_escaped",
        "sig": "def valid_brackets_escaped(s: str) -> bool:",
        "doc": "Return True iff `()`, `[]`, `{}` outside double-quoted strings are balanced and all `\"...\"` strings close properly (`\\` inside `\"...\"` escapes the next char).",
        "pub": [(('a(")[", [1])',), True), (('a("unclosed)',), False)],
        "hold": [
            (('{"k": "v\\"]x"}[()]',), True),
            (('{"k": "v\\\\"}[)',), False),
            (('"trailing\\"',), False),
            (('',), True),
        ],
    },
    {
        "fn_name": "sliding_window_min",
        "sig": "def sliding_window_min(xs: list[int], w: int) -> list[int]:",
        "doc": "Return `[min(xs[i:i+w]) for i in range(len(xs)-w+1)]` in `O(n)` time; if `w <= 0` or `w > len(xs)`, return `[]`.",
        "pub": [(([4, 2, 5, 1, 3], 3), [2, 1, 1]), (([1, 2], 5), [])],
        "hold": [
            (([-1, -5, -2, -8, 4], 2), [-5, -5, -8, -8]),
            (([7, 6, 5, 4], 1), [7, 6, 5, 4]),
            (([1, 2, 3], 0), []),
            (([], 2), []),
        ],
    },
    {
        "fn_name": "lex_toposort",
        "sig": "def lex_toposort(n: int, edges: list[tuple[int, int]]) -> list[int]:",
        "doc": "Return the lexicographically smallest topological ordering of nodes `0..n-1` for directed edges `u -> v`; return `[]` if any cycle (including self-loop) exists.",
        "pub": [((4, [(0, 2), (1, 2), (2, 3)]), [0, 1, 2, 3]), ((2, [(0, 1), (1, 0)]), [])],
        "hold": [
            ((5, [(3, 1), (2, 0)]), [1, 2, 0, 3, 4] if False else [2, 0, 3, 1, 4]),
            ((3, [(1, 1)]), []),
            ((4, [(0, 1), (0, 1), (2, 0)]), [2, 0, 1, 3]),
            ((0, []), []),
        ],
    },
    {
        "fn_name": "lis_strict_len",
        "sig": "def lis_strict_len(xs: list[int]) -> int:",
        "doc": "Return the length of the longest strictly increasing subsequence of `xs` (`0` for `[]`).",
        "pub": [(([10, 9, 2, 5, 3, 7, 101, 18],), 4), (([7, 7, 7],), 1)],
        "hold": [
            (([],), 0),
            (([-5, -2, -2, 0, -1, 3],), 4),
            (([5, 4, 3, 2, 1],), 1),
            (([1, 3, 2, 4, 3, 5],), 4),
        ],
    },
    {
        "fn_name": "exact_fraction_sum",
        "sig": "def exact_fraction_sum(fracs: list[tuple[int, int]]) -> tuple[int, int]:",
        "doc": "Sum rational pairs `(num, den)` (`den != 0`) and return reduced `(p, q)` with `q > 0` and `gcd(|p|, q) == 1` (`(0, 1)` for empty or zero sum).",
        "pub": [(([(1, 6), (1, 3)],), (1, 2)), (([],), (0, 1))],
        "hold": [
            (([(1, -4), (-1, 4)],), (-1, 2)),
            (([(3, 5), (-6, 10)],), (0, 1)),
            (([(7, 12), (5, 18)],), (31, 36)),
            (([(-2, -6)],), (1, 3)),
        ],
    },
    {
        "fn_name": "knapsack_maxval_minwt",
        "sig": "def knapsack_maxval_minwt(cap: int, items: list[tuple[int, int]]) -> tuple[int, int]:",
        "doc": "0/1 knapsack over `(weight, value)` items with capacity `cap`: maximize total value, breaking ties by MINIMUM total weight. Return `(max_val, min_wt)`.",
        "pub": [((10, [(6, 10), (5, 10), (4, 8)]), (18, 9)), ((0, [(1, 5)]), (0, 0))],
        "hold": [
            ((7, [(5, 12), (4, 12), (3, 12)]), (24, 7)),
            ((6, [(6, 15), (2, 8), (3, 7)]), (15, 5)),
            ((5, []), (0, 0)),
            ((4, [(0, 3), (4, 5)]), (8, 4)),
        ],
    },
    {
        "fn_name": "weighted_edit_distance",
        "sig": "def weighted_edit_distance(a: str, b: str, ins_c: int, del_c: int, sub_c: int) -> int:",
        "doc": "Minimum cost to transform string `a` into `b` with insertion cost `ins_c`, deletion cost `del_c`, and mismatch substitution cost `sub_c` (`0` if chars match).",
        "pub": [(("cat", "cut", 2, 2, 3), 3), (("", "ab", 4, 1, 5), 8)],
        "hold": [
            (("abc", "abc", 1, 1, 1), 0),
            (("kitten", "sitting", 1, 1, 10), 5),
            (("ab", "", 3, 5, 2), 10),
            (("x", "y", 2, 2, 7), 4),
        ],
    },
    {
        "fn_name": "balanced_ternary",
        "sig": "def balanced_ternary(n: int) -> str:",
        "doc": "Encode signed integer `n` in canonical balanced ternary using `'+'` (+1), `'0'` (0), `'-'` (-1) with no leading `'0'` except `0 -> '0'`.",
        "pub": [((5,), "+--"), ((0,), "0")],
        "hold": [
            ((-5,), "-++"),
            ((13,), "+++"),
            ((-1,), "-"),
            ((8,), "+0-"),
        ],
    },
    {
        "fn_name": "generalized_crt_pair_list",
        "sig": "def generalized_crt_pair_list(congs: list[tuple[int, int]]) -> tuple[int, int]:",
        "doc": "Solve `x % m_i == r_i % m_i` (`m_i >= 1`) for possibly non-coprime moduli. Return `(x, M)` with `0 <= x < M = lcm(m_i)` (`(0, 1)` for `[]`), or `(-1, -1)` if inconsistent.",
        "pub": [(([(2, 3), (3, 5)],), (8, 15)), (([(1, 4), (3, 6)],), (-1, -1))],
        "hold": [
            (([(3, 6), (7, 10)],), (27, 30)),
            (([],), (0, 1)),
            (([(-1, 5), (4, 10)],), (4, 10)),
            (([(0, 1)],), (0, 1)),
        ],
    },
]


R5_SPECS.extend([
    {
        "fn_name": "max_bounded_submatrix",
        "sig": "def max_bounded_submatrix(grid: list[list[int]], max_h: int, max_w: int) -> int:",
        "doc": "Return the maximum sum over all non-empty rectangular submatrices of `grid` with height `1..max_h` and width `1..max_w`.",
        "pub": [(([[1, -2, 3], [4, 5, -1]], 2, 2), 9), (([[-5, -2]], 1, 2), -2)],
        "hold": [
            (([[3, 3, 3], [3, 3, 3]], 1, 2), 6),
            (([[10, -20, 15], [10, -20, 15]], 2, 1), 30),
            (([[-8, -3], [-4, -9]], 2, 2), -3),
            (([[2, -1, 4]], 1, 3), 5),
        ],
    },
    {
        "fn_name": "lru_trace_sim",
        "sig": "def lru_trace_sim(cap: int, ops: list[tuple[str, int, int]]) -> list[int]:",
        "doc": "Simulate LRU cache of capacity `cap >= 1`: `('PUT', k, v)` inserts/updates `k->v` (marking MRU); `('GET', k, 0)` appends value or `-1` on miss (marking MRU on hit). Return all GET results.",
        "pub": [((2, [("PUT", 1, 10), ("PUT", 2, 20), ("GET", 1, 0), ("PUT", 3, 30), ("GET", 2, 0)]), [10, -1])],
        "hold": [
            ((1, [("PUT", 1, 5), ("PUT", 1, 9), ("GET", 1, 0), ("PUT", 2, 4), ("GET", 1, 0)]), [9, -1]),
            ((2, [("GET", 7, 0), ("PUT", 7, 1), ("PUT", 8, 2), ("PUT", 7, 3), ("PUT", 9, 4), ("GET", 8, 0), ("GET", 7, 0)]), [-1, -1, 3]),
            ((3, []), []),
        ],
    },
    {
        "fn_name": "largest_histogram_rect",
        "sig": "def largest_histogram_rect(hs: list[int]) -> int:",
        "doc": "Return the largest rectangle area in histogram `hs` (`hs[i] >= 0`, `0` for `[]`).",
        "pub": [(([2, 1, 5, 6, 2, 3],), 10), (([],), 0)],
        "hold": [
            (([6, 2, 5, 4, 5, 1, 6],), 12),
            (([4, 4, 4, 4],), 16),
            (([0, 0, 5, 0],), 5),
            (([9],), 9),
        ],
    },
    {
        "fn_name": "decode_nested_brackets",
        "sig": "def decode_nested_brackets(s: str) -> str:",
        "doc": "Expand `k[substr]` nested repeat patterns (e.g. `'3[a2[c]]' -> 'accaccacc'`, multi-digit `k >= 0` allowed).",
        "pub": [(("3[a2[c]]",), "accaccacc"), (("2[ab]z",), "ababz")],
        "hold": [
            (("10[x]",), "xxxxxxxxxx"),
            (("a0[bc]d",), "ad"),
            (("2[a2[b3[c]]]",), "abcccbcccabcccbccc"),
            (("plain",), "plain"),
        ],
    },
    {
        "fn_name": "shortest_grid_wall_break",
        "sig": "def shortest_grid_wall_break(grid: list[list[int]], k: int) -> int:",
        "doc": "Minimum 4-neighbor steps from `(0,0)` to `(R-1,C-1)` in binary `grid` (`0`=free, `1`=wall) eliminating at most `k` walls (`(0,0)` is `0`; return `-1` if unreachable).",
        "pub": [(([[0, 1, 0], [0, 1, 0], [0, 0, 0]], 1), 4), (([[0, 1], [1, 0]], 0), -1)],
        "hold": [
            (([[0]], 0), 0),
            (([[0, 1, 1], [1, 1, 1], [1, 1, 0]], 1), -1),
            (([[0, 1, 1], [1, 1, 1], [1, 1, 0]], 3), 4),
            (([[0, 0, 0], [1, 1, 0], [0, 0, 0], [0, 1, 1], [0, 0, 0]], 1), 6),
        ],
    },
    {
        "fn_name": "poly_eval_and_deriv_mod",
        "sig": "def poly_eval_and_deriv_mod(coeffs: list[int], x: int) -> tuple[int, int]:",
        "doc": "For `P(x) = sum(coeffs[i] * x**i for i in range(len(coeffs)))`, return `(P(x) % MOD, P'(x) % MOD)` where `MOD = 1_000_000_007` (`(0, 0)` for `[]`).",
        "pub": [(([3, 2, 5], 4), (91, 42)), (([], 9), (0, 0))],
        "hold": [
            (([7], 100), (7, 0)),
            (([-1, 0, 1], 3), (8, 6)),
            (([1, 1, 1, 1], 0), (1, 1)),
            (([10**9 + 8, 2], 10**9 + 7), (1, 2)),
        ],
    },
    {
        "fn_name": "max_weighted_intervals",
        "sig": "def max_weighted_intervals(jobs: list[tuple[int, int, int]]) -> int:",
        "doc": "Given `(start, end, weight)` jobs (`start < end`, `weight >= 0`), select non-overlapping jobs (`end_i <= start_j` allowed!) maximizing total weight.",
        "pub": [(([(1, 3, 50), (3, 5, 20), (2, 4, 100)],), 100), (([],), 0)],
        "hold": [
            (([(1, 3, 40), (3, 6, 50), (2, 5, 70)],), 90),
            (([(1, 2, 10), (2, 3, 10), (3, 4, 10), (1, 4, 25)],), 30),
            (([(0, 10, 5), (2, 4, 6), (4, 8, 7)],), 13),
        ],
    },
    {
        "fn_name": "strict_third_majority",
        "sig": "def strict_third_majority(xs: list[int]) -> list[int]:",
        "doc": "Return sorted distinct elements appearing strictly more than `len(xs) // 3` times in `xs`.",
        "pub": [(([3, 2, 3],), [3]), (([1, 2, 3],), [])],
        "hold": [
            (([1, 1, 2, 2, 3],), [1, 2]),
            (([],), []),
            (([-4, -4, -1, -1, -4, -1, 9],), [-4, -1]),
            (([5],), [5]),
        ],
    },
    # 3 Calibration-only R5 probes (CAL_R5_01..03 — zero overlap with test R5_01..20!)
    {
        "fn_name": "zigzag_level_sums",
        "sig": "def zigzag_level_sums(xs: list[int], width: int) -> list[int]:",
        "doc": "Chunk `xs` into rows of `max(1, width)`, reverse odd-indexed rows (`1, 3, ...`), and return `[row[0] for row in rows]`.",
        "pub": [(([1, 2, 3, 4, 5, 6], 3), [1, 6]), (([], 3), [])],
        "hold": [(([10, 20, 30, 40, 50], 2), [10, 40, 50]), (([7], 0), [7])],
    },
    {
        "fn_name": "count_inversions_small",
        "sig": "def count_inversions_small(xs: list[int]) -> int:",
        "doc": "Return the number of pairs `0 <= i < j < len(xs)` with `xs[i] > xs[j]`.",
        "pub": [(([2, 4, 1, 3, 5],), 3), (([],), 0)],
        "hold": [(([5, 4, 3, 2, 1],), 10), (([1, 1, 1],), 0), (([-1, -3, 0],), 1)],
    },
    {
        "fn_name": "next_greater_circular",
        "sig": "def next_greater_circular(xs: list[int]) -> list[int]:",
        "doc": "For each `i`, return the first strictly greater element scanning circularly `(i+1)%n ...`, or `-1` if none exists.",
        "pub": [(([1, 2, 1],), [2, -1, 2]), (([],), [])],
        "hold": [(([5, 4, 3, 2, 1],), [-1, 5, 5, 5, 5]), (([2, 2, 2],), [-1, -1, -1])],
    },
])


def _build_r5_tasks(specs: list[dict[str, Any]], prefix: str) -> tuple[list[dict], dict[str, Any]]:
    tasks, oracles = [], {}
    for idx, sp in enumerate(specs):
        tid = f"{prefix}_{idx + 1:02d}"
        pub_str = "; ".join(f"{sp['fn_name']}{args!r} == {exp!r}" for args, exp in sp["pub"])
        tasks.append({
            "task_id": tid,
            "regime": "R5",
            "answer_kind": "python_fn",
            "fn_name": sp["fn_name"],
            "signature": sp["sig"],
            "prompt_nl": (
                f"Implement complete standalone Python 3 function `{sp['sig']}` (stdlib imports allowed, no markdown prose). "
                f"Specification: {sp['doc']} Public examples: `{pub_str}`. "
                f"Return ONLY a ```python ... ``` code block defining `{sp['fn_name']}`."
            ),
            "schema_ir": {
                "kind": "open_world_py_synthesis",
                "fn_name": sp["fn_name"],
                "signature": sp["sig"],
                "public_io": [{"args": list(a), "expected": e} for a, e in sp["pub"]],
            },
            "public_examples": [{"args": list(a), "expected": e} for a, e in sp["pub"]],
        })
        oracles[tid] = {"fn_name": sp["fn_name"], "vectors": sp["pub"] + sp["hold"]}
    return tasks, oracles


def _assemble_suites() -> tuple[list[dict], dict[str, Any], list[dict], dict[str, Any]]:
    rng_test = random.Random(2026112305)
    t_r1, o_r1 = _build_r1_tasks(rng_test, 20, "R1", include_cryst=True)
    t_r2, o_r2 = _build_r2_tasks(rng_test, 20, "R2")
    t_r3, o_r3 = _build_r3_tasks(rng_test, 20, "R3")
    t_r4, o_r4 = _build_r4_tasks(rng_test, 20, "R4")
    t_r5, o_r5 = _build_r5_tasks(R5_SPECS[:20], "R5")
    test_tasks = t_r1 + t_r2 + t_r3 + t_r4 + t_r5
    test_oracles = {**o_r1, **o_r2, **o_r3, **o_r4, **o_r5}

    rng_cal = random.Random(99002026)
    c_r1, co_r1 = _build_r1_tasks(rng_cal, 3, "CAL_R1", include_cryst=False)
    c_r2, co_r2 = _build_r2_tasks(rng_cal, 3, "CAL_R2")
    c_r3, co_r3 = _build_r3_tasks(rng_cal, 3, "CAL_R3")
    c_r4, co_r4 = _build_r4_tasks(rng_cal, 4, "CAL_R4")
    c_r4 = [c_r4[0], c_r4[1], c_r4[2]]  # 2 causal + 1 horizon MDP = 3 calibration probes
    co_r4 = {t["task_id"]: co_r4[t["task_id"]] for t in c_r4}
    c_r5, co_r5 = _build_r5_tasks(R5_SPECS[20:23], "CAL_R5")
    cal_tasks = c_r1 + c_r2 + c_r3 + c_r4 + c_r5
    cal_oracles = {**co_r1, **co_r2, **co_r3, **co_r4, **co_r5}
    return test_tasks, test_oracles, cal_tasks, cal_oracles


_TEST_TASKS, _TEST_ORACLES, _CAL_TASKS, _CAL_ORACLES = _assemble_suites()
_ALL_ORACLES = {**_TEST_ORACLES, **_CAL_ORACLES}


def get_public_corpus() -> list[dict[str, Any]]:
    return json.loads(json.dumps(_TEST_TASKS))


def get_calibration_probes() -> list[dict[str, Any]]:
    return json.loads(json.dumps(_CAL_TASKS))


def corpus_sha256() -> str:
    raw = json.dumps({"test_100": _TEST_TASKS, "cal_15": _CAL_TASKS}, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def evaluate_oracle(task_id: str, prediction: Any) -> bool:
    orc = _ALL_ORACLES[task_id]
    if "expected_int" in orc:
        return isinstance(prediction, int) and not isinstance(prediction, bool) and prediction == orc["expected_int"]
    if "expected_list" in orc:
        return isinstance(prediction, (list, tuple)) and [int(x) for x in prediction] == orc["expected_list"]
    if "vectors" in orc:
        if not isinstance(prediction, str) or "def " not in prediction:
            return False
        ns: dict[str, Any] = {}
        try:
            exec(compile(prediction, f"<{task_id}>", "exec"), ns, ns)
            fn = ns.get(orc["fn_name"])
            if not callable(fn):
                return False
            # Execute twice on deep-copied inputs to catch mutable-state/cache side-effect bugs
            for args, exp in orc["vectors"]:
                a1 = json.loads(json.dumps(args))
                # Restore tuple inner elements where spec expects tuples
                got1 = fn(*a1)
                a2 = json.loads(json.dumps(args))
                got2 = fn(*a2)
                if got1 != exp and json.loads(json.dumps(got1)) != json.loads(json.dumps(exp)):
                    return False
                if got1 != got2:
                    return False
            return True
        except Exception:
            return False
    return False
