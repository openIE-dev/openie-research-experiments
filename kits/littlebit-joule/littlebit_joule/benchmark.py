#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Benchmark runner for Kit 4 (`kits/littlebit-joule/`, Shots on Goal #2 & #6):
Sub-Bit SVD + Binary Latent Factors + Walsh-Hadamard Internal Rotation evaluated on
`Joules-per-Correct-Decision` vs. Mandatory Deterministic Null Control across:
  - Physical DC Shunt Board Rails (`measured_j` on TI INA3221/INA238 & TI INA260)
  - Linux Powercap RAPL (`reported_j`)
  - 14-point `bitwidth_curve` sweep (`r in {8, 14, 22, 32, 48}`, ternary 2-bpw, INT4, INT8, LUT)
"""

from __future__ import annotations

import argparse
import ctypes
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
KIT_ROOT = HERE.parent
if str(KIT_ROOT) not in sys.path:
    sys.path.insert(0, str(KIT_ROOT))

from littlebit_joule.crypto_receipt import (  # noqa: E402
    EnergyMeter,
    assert_sanitized,
    blake3_derive_key_hex,
    clopper_pearson_upper,
    iqr_stats,
    sanitized_host_info,
    seal_signed_receipt,
    verify_signed_receipt,
)

D_IN = 512
M_OUT = 512
RANK_R = 22
TOTAL_WEIGHTS = M_OUT * D_IN  # 262,144


def subbit_storage_bits_for_rank(r: int) -> int:
    return (M_OUT * r) + (r * D_IN) + (M_OUT * 16) + (D_IN * 16) + D_IN + (r * 16)


SUBBIT_STORAGE_BITS = subbit_storage_bits_for_rank(RANK_R)  # 39,776 bits
SUBBIT_BPW = round(SUBBIT_STORAGE_BITS / TOTAL_WEIGHTS, 4)  # 0.1517 bpw
SUBBIT_BYTES = SUBBIT_STORAGE_BITS // 8  # 4,972 bytes

SWEEP_RANKS = [8, 14, 22, 32, 48]


def compile_and_load_library(build_dir: Path | None = None) -> ctypes.CDLL:
    cc_bin = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if not cc_bin:
        raise RuntimeError("C compiler (`cc`/`gcc`/`clang`) required to build native LittleBit micro-kernels.")
    bdir = build_dir or (KIT_ROOT / ".build")
    bdir.mkdir(parents=True, exist_ok=True)
    so_path = bdir / "liblittlebit_kernels.so"
    c_src = HERE / "kernels.c"
    if not so_path.exists() or c_src.stat().st_mtime > so_path.stat().st_mtime:
        arch_flags = ["-O2", "-mpopcnt"] if platform.machine().lower() in ("x86_64", "amd64") else ["-O2"]
        subprocess.run(
            [cc_bin, *arch_flags, "-shared", "-fPIC", str(c_src), "-lm", "-o", str(so_path)],
            check=True,
            timeout=120,
        )
    lib = ctypes.CDLL(str(so_path))
    lib.lb_init.argtypes = [ctypes.c_int, ctypes.c_int]
    lib.lb_init.restype = ctypes.c_void_p
    lib.lb_free.argtypes = [ctypes.c_void_p]
    lib.lb_free.restype = None
    lib.lb_get_kurtosis.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double),
    ]
    lib.lb_get_kurtosis.restype = None
    lib.lb_eval_regime.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_double),
    ]
    lib.lb_eval_regime.restype = ctypes.c_uint64
    lib.lb_eval_regime_rank.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_double),
    ]
    lib.lb_eval_regime_rank.restype = ctypes.c_uint64
    lib.lb_fwht_i32.argtypes = [ctypes.POINTER(ctypes.c_int32), ctypes.c_int]
    lib.lb_fwht_i32.restype = None
    lib.lb_bipolar_dot_xnor512.argtypes = [ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_uint64)]
    lib.lb_bipolar_dot_xnor512.restype = ctypes.c_int32
    return lib


REGIME_SPECS = [
    {
        "id": 0,
        "rank_r": 0,
        "key": "deterministic_null_lut",
        "label": "Deterministic Null (4 KiB Compiled Quadrant LUT)",
        "bits_per_weight": None,
        "footprint_bytes": 4096,
        "default_reps": 800,
        "quick_reps": 300,
    },
    {
        "id": 1,
        "rank_r": 0,
        "key": "dense_int8_baseline",
        "label": "Dense INT8 Baseline (8.00 bpw MatVec + ReLU)",
        "bits_per_weight": 8.0,
        "footprint_bytes": TOTAL_WEIGHTS,
        "default_reps": 80,
        "quick_reps": 30,
    },
    {
        "id": 2,
        "rank_r": RANK_R,
        "key": "subbit_naive_float_unpack",
        "label": f"Sub-Bit Naive FP32 Unpack ({SUBBIT_BPW} bpw -> Runtime FP32 Decompress)",
        "bits_per_weight": SUBBIT_BPW,
        "footprint_bytes": SUBBIT_BYTES,
        "default_reps": 8,
        "quick_reps": 2,
    },
    {
        "id": 3,
        "rank_r": RANK_R,
        "key": "littlebit_joule_packed_int",
        "label": f"LittleBit-Joule Packed Int ({SUBBIT_BPW} bpw XNOR+Popcount + Int FWHT)",
        "bits_per_weight": SUBBIT_BPW,
        "footprint_bytes": SUBBIT_BYTES,
        "default_reps": 250,
        "quick_reps": 80,
    },
]


def _build_sweep_specs() -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = [
        {
            "key": "deterministic_null_lut",
            "family": "deterministic_null",
            "regime_id": 0,
            "rank_r": 0,
            "bits_per_weight": 0.0,
            "footprint_bytes": 4096,
            "default_reps": 500,
            "quick_reps": 100,
        }
    ]
    for r in SWEEP_RANKS:
        bits = subbit_storage_bits_for_rank(r)
        bpw = round(bits / TOTAL_WEIGHTS, 4)
        fbytes = bits // 8
        specs.append(
            {
                "key": f"littlebit_packed_int_r{r}",
                "family": "littlebit_packed_int",
                "regime_id": 3,
                "rank_r": r,
                "bits_per_weight": bpw,
                "footprint_bytes": fbytes,
                "default_reps": max(60, 260 - 3 * r),
                "quick_reps": 30,
            }
        )
        specs.append(
            {
                "key": f"subbit_naive_fp32_unpack_r{r}",
                "family": "subbit_naive_fp32_unpack",
                "regime_id": 2,
                "rank_r": r,
                "bits_per_weight": bpw,
                "footprint_bytes": fbytes,
                "default_reps": max(2, 10 - r // 6),
                "quick_reps": 1,
            }
        )
    specs.extend(
        [
            {
                "key": "ternary_2bpw",
                "family": "quantized_baseline",
                "regime_id": 4,
                "rank_r": 0,
                "bits_per_weight": 2.0,
                "footprint_bytes": (TOTAL_WEIGHTS // 4) + 4,
                "default_reps": 120,
                "quick_reps": 40,
            },
            {
                "key": "int4_4bpw",
                "family": "quantized_baseline",
                "regime_id": 5,
                "rank_r": 0,
                "bits_per_weight": 4.0,
                "footprint_bytes": (TOTAL_WEIGHTS // 2) + 4,
                "default_reps": 80,
                "quick_reps": 30,
            },
            {
                "key": "dense_int8_8bpw",
                "family": "quantized_baseline",
                "regime_id": 1,
                "rank_r": 0,
                "bits_per_weight": 8.0,
                "footprint_bytes": TOTAL_WEIGHTS,
                "default_reps": 60,
                "quick_reps": 25,
            },
        ]
    )
    return specs


def run_benchmark(quick: bool = False) -> tuple[dict[str, Any], dict[str, Any], str]:
    lib = compile_and_load_library()
    n_dev = 1500
    n_test = 1024 if quick else 1200

    meter = EnergyMeter()
    is_shunt = meter.board_metered
    n_trials = (4 if quick else 8) if is_shunt else (10 if quick else 20)
    sweep_trials = 1 if quick else (2 if is_shunt else 5)

    idle_pre = meter.sample_idle_baseline(0.20 if quick else (1.0 if is_shunt else 0.20)) if meter.available else None
    host = sanitized_host_info()

    ctx = lib.lb_init(n_dev, n_test)
    if not ctx:
        meter.close()
        raise RuntimeError("Failed to initialize LbContext")

    try:
        raw_k = ctypes.c_double()
        rot_k = ctypes.c_double()
        lib.lb_get_kurtosis(ctx, ctypes.byref(raw_k), ctypes.byref(rot_k))

        c_tmp = ctypes.c_int()
        ns_tmp = ctypes.c_double()

        # Calibrate burst reps so every physical shunt trial spans >= 0.70 s (~130-190 I2C samples)
        calibrated_reps: dict[str, int] = {}
        for spec in REGIME_SPECS:
            def _probe(s: dict[str, Any] = spec) -> None:
                lib.lb_eval_regime_rank(
                    ctx, s["id"], max(1, s["rank_r"]), 1, ctypes.byref(c_tmp), ctypes.byref(ns_tmp)
                )
            calibrated_reps[spec["key"]] = meter.calibrate_reps(
                _probe, spec["default_reps"], spec["quick_reps"], quick=quick, target_shunt_s=0.78
            )

        per_regime_samples: dict[str, dict[str, Any]] = {}
        for spec in REGIME_SPECS:
            per_regime_samples[spec["key"]] = {
                "ns_per_decision": [],
                "ns_per_correct": [],
                "gross_measured_uj_per_correct": [],
                "paired_net_measured_uj_per_correct": [],
                "secondary_measured_uj_per_correct": [],
                "window_s_samples": [],
                "shunt_samples_per_trial": [],
                "pkg_uj_per_decision": [],
                "pkg_uj_per_correct": [],
                "core_uj_per_correct": [],
                "fnv_hashes": set(),
                "correct": 0,
                "reps_per_trial": calibrated_reps[spec["key"]],
            }

        for trial in range(n_trials):
            round_idle_w = (
                meter.sample_idle_power_w(0.08 if quick else 0.22) if is_shunt else None
            )
            rotated_order = REGIME_SPECS[trial % 4 :] + REGIME_SPECS[: trial % 4]
            for spec in rotated_order:
                reps = calibrated_reps[spec["key"]]
                corr_c = ctypes.c_int()
                el_ns = ctypes.c_double()
                s0 = meter.snapshot()
                fnv = lib.lb_eval_regime_rank(
                    ctx, spec["id"], max(1, spec["rank_r"]), reps, ctypes.byref(corr_c), ctypes.byref(el_ns)
                )
                s1 = meter.snapshot() if not is_shunt else None
                d = meter.diff(s0, s1)

                correct = int(corr_c.value)
                total_decisions = n_test * reps
                total_correct = max(1, correct * reps)

                rec = per_regime_samples[spec["key"]]
                rec["correct"] = correct
                rec["fnv_hashes"].add(f"{fnv:016x}")
                rec["ns_per_decision"].append(float(el_ns.value) / total_decisions)
                rec["ns_per_correct"].append(float(el_ns.value) / total_correct)

                if d["primary_measured_j"] is not None:
                    gross_j = float(d["primary_measured_j"])
                    win_s = float(d["wall_s"])
                    rec["gross_measured_uj_per_correct"].append((gross_j * 1e6) / total_correct)
                    rec["window_s_samples"].append(win_s)
                    rec["shunt_samples_per_trial"].append(int(d["shunt_samples"]))
                    if round_idle_w is not None:
                        net_j = max(0.0, gross_j - round_idle_w * win_s)
                        rec["paired_net_measured_uj_per_correct"].append((net_j * 1e6) / total_correct)
                    if d["secondary_measured_j"] is not None:
                        rec["secondary_measured_uj_per_correct"].append(
                            (float(d["secondary_measured_j"]) * 1e6) / total_correct
                        )

                if d["pkg_reported_j"] is not None:
                    pkg_uj = d["pkg_reported_j"] * 1e6
                    rec["pkg_uj_per_decision"].append(pkg_uj / total_decisions)
                    rec["pkg_uj_per_correct"].append(pkg_uj / total_correct)
                if d["core_reported_j"] is not None:
                    core_uj = d["core_reported_j"] * 1e6
                    rec["core_uj_per_correct"].append(core_uj / total_correct)

        # Multi-point bit-width curve sweep (`r in {8, 14, 22, 32, 48}` + ternary + INT4 + INT8 + LUT)
        sweep_specs = _build_sweep_specs()
        if quick:
            sweep_specs = [
                sp for sp in sweep_specs if sp["rank_r"] in (0, 8, 22, 48)
            ]
        bitwidth_curve: list[dict[str, Any]] = []
        for sp in sweep_specs:
            def _probe_sp(item: dict[str, Any] = sp) -> None:
                lib.lb_eval_regime_rank(
                    ctx, item["regime_id"], max(1, item["rank_r"]), 1, ctypes.byref(c_tmp), ctypes.byref(ns_tmp)
                )
            if is_shunt and sp["regime_id"] == 2:
                sp_reps = 1
                eff_sweep_trials = 1
            else:
                sp_reps = meter.calibrate_reps(
                    _probe_sp, sp["default_reps"], sp["quick_reps"], quick=quick, target_shunt_s=0.68
                )
                eff_sweep_trials = sweep_trials
            ns_vals: list[float] = []
            gross_uj_vals: list[float] = []
            net_uj_vals: list[float] = []
            sec_uj_vals: list[float] = []
            pkg_uj_vals: list[float] = []
            shunt_cnts: list[int] = []
            sp_correct = 0
            adj_idle_w = meter.sample_idle_power_w(0.06 if quick else 0.16) if is_shunt else None

            for _ in range(eff_sweep_trials):
                corr_c = ctypes.c_int()
                el_ns = ctypes.c_double()
                s0 = meter.snapshot()
                lib.lb_eval_regime_rank(
                    ctx, sp["regime_id"], max(1, sp["rank_r"]), sp_reps, ctypes.byref(corr_c), ctypes.byref(el_ns)
                )
                s1 = meter.snapshot() if not is_shunt else None
                d = meter.diff(s0, s1)
                sp_correct = int(corr_c.value)
                tot_corr = max(1, sp_correct * sp_reps)
                ns_vals.append(float(el_ns.value) / tot_corr)
                if d["primary_measured_j"] is not None:
                    gj = float(d["primary_measured_j"])
                    gross_uj_vals.append((gj * 1e6) / tot_corr)
                    shunt_cnts.append(int(d["shunt_samples"]))
                    if adj_idle_w is not None:
                        net_uj_vals.append((max(0.0, gj - adj_idle_w * float(d["wall_s"])) * 1e6) / tot_corr)
                    if d["secondary_measured_j"] is not None:
                        sec_uj_vals.append((float(d["secondary_measured_j"]) * 1e6) / tot_corr)
                if d["pkg_reported_j"] is not None:
                    pkg_uj_vals.append((float(d["pkg_reported_j"]) * 1e6) / tot_corr)

            pt: dict[str, Any] = {
                "key": sp["key"],
                "family": sp["family"],
                "rank_r": sp["rank_r"] if sp["rank_r"] > 0 else None,
                "bits_per_weight": sp["bits_per_weight"],
                "footprint_bytes": sp["footprint_bytes"],
                "held_out_instances": n_test,
                "correct_decisions": sp_correct,
                "accuracy": round(sp_correct / n_test, 6),
                "wall_ns_per_correct_median": iqr_stats(ns_vals, 2)["median"],
                "evidence_class": meter.evidence_class,
                "gross_rail_measured_uj_per_correct": iqr_stats(gross_uj_vals, 4)["median"] if gross_uj_vals else None,
                "paired_net_above_idle_measured_uj_per_correct": iqr_stats(net_uj_vals, 4)["median"] if net_uj_vals else None,
                "secondary_carrier_measured_uj_per_correct": iqr_stats(sec_uj_vals, 4)["median"] if sec_uj_vals else None,
                "shunt_samples_median": int(iqr_stats([float(c) for c in shunt_cnts], 0)["median"]) if shunt_cnts else 0,
                "pkg_reported_uj_per_correct": iqr_stats(pkg_uj_vals, 4)["median"] if pkg_uj_vals else None,
            }
            bitwidth_curve.append(pt)
    finally:
        lib.lb_free(ctx)

    idle_post = meter.sample_idle_baseline(0.20 if quick else (1.0 if is_shunt else 0.20)) if meter.available else None
    telemetry_meta = meter.metadata(idle_pre, idle_post)
    meter.close()

    f6_flag = bool(telemetry_meta.get("falsifier_6_idle_drift_flag", False))
    mean_idle_w = telemetry_meta.get("idle_trimmed_mean_w")

    regimes_out: dict[str, Any] = {}
    total_determinism_checks = n_trials * len(REGIME_SPECS)
    divergences = 0

    for spec in REGIME_SPECS:
        k = spec["key"]
        rec = per_regime_samples[k]
        if len(rec["fnv_hashes"]) != 1:
            divergences += len(rec["fnv_hashes"]) - 1
        acc = rec["correct"] / n_test

        # A1/A2 net-above-idle only when Falsifier-6 drift <= 5.0%
        a1_a2_net_vals: list[float] = []
        if is_shunt and (not f6_flag) and mean_idle_w is not None:
            for gj_uj, ws in zip(rec["gross_measured_uj_per_correct"], rec["window_s_samples"]):
                tot_corr = max(1, rec["correct"] * rec["reps_per_trial"])
                gross_j = (gj_uj * tot_corr) * 1e-6
                net_j = max(0.0, gross_j - float(mean_idle_w) * ws)
                a1_a2_net_vals.append((net_j * 1e6) / tot_corr)

        regimes_out[k] = {
            "label": spec["label"],
            "bits_per_weight": spec["bits_per_weight"],
            "footprint_bytes": spec["footprint_bytes"],
            "held_out_instances": n_test,
            "correct_decisions": rec["correct"],
            "accuracy": round(acc, 6),
            "prediction_fnv1a64": sorted(rec["fnv_hashes"])[0],
            "deterministic_across_all_trials": len(rec["fnv_hashes"]) == 1,
            "reps_per_trial": rec["reps_per_trial"],
            "wall_ns_per_decision": iqr_stats(rec["ns_per_decision"], 2),
            "wall_ns_per_correct_decision": iqr_stats(rec["ns_per_correct"], 2),
            "evidence_class": meter.evidence_class,
            "gross_rail_measured_uj_per_correct_decision": (
                iqr_stats(rec["gross_measured_uj_per_correct"], 4) if rec["gross_measured_uj_per_correct"] else None
            ),
            "net_above_idle_a1_a2_measured_uj_per_correct_decision": (
                iqr_stats(a1_a2_net_vals, 4) if a1_a2_net_vals else None
            ),
            "net_above_idle_a1_a2_withheld_per_falsifier_6": bool(is_shunt and f6_flag),
            "paired_round_net_above_idle_measured_uj_per_correct_decision": (
                iqr_stats(rec["paired_net_measured_uj_per_correct"], 4)
                if rec["paired_net_measured_uj_per_correct"]
                else None
            ),
            "secondary_carrier_measured_uj_per_correct_decision": (
                iqr_stats(rec["secondary_measured_uj_per_correct"], 4)
                if rec["secondary_measured_uj_per_correct"]
                else None
            ),
            "shunt_samples_per_trial": (
                iqr_stats([float(c) for c in rec["shunt_samples_per_trial"]], 1)
                if rec["shunt_samples_per_trial"]
                else None
            ),
            "pkg_reported_uj_per_decision": (
                iqr_stats(rec["pkg_uj_per_decision"], 4) if rec["pkg_uj_per_decision"] else None
            ),
            "pkg_reported_uj_per_correct_decision": (
                iqr_stats(rec["pkg_uj_per_correct"], 4) if rec["pkg_uj_per_correct"] else None
            ),
            "core_reported_uj_per_correct_decision": (
                iqr_stats(rec["core_uj_per_correct"], 4) if rec["core_uj_per_correct"] else None
            ),
        }

    int8_ns = regimes_out["dense_int8_baseline"]["wall_ns_per_correct_decision"]["median"]
    naive_ns = regimes_out["subbit_naive_float_unpack"]["wall_ns_per_correct_decision"]["median"]
    lb_ns = regimes_out["littlebit_joule_packed_int"]["wall_ns_per_correct_decision"]["median"]
    dnull_ns = regimes_out["deterministic_null_lut"]["wall_ns_per_correct_decision"]["median"]

    wall_ratios = {
        "decompression_impedance_tax_naive_over_int8_x": round(naive_ns / max(int8_ns, 1e-9), 2),
        "littlebit_packed_speedup_over_int8_x": round(int8_ns / max(lb_ns, 1e-9), 2),
        "littlebit_packed_speedup_over_naive_unpack_x": round(naive_ns / max(lb_ns, 1e-9), 2),
        "deterministic_null_speedup_over_int8_x": round(int8_ns / max(dnull_ns, 1e-9), 2),
    }

    energy_ratios: dict[str, Any] = {"evidence_class": meter.evidence_class}
    if meter.evidence_class == "measured_j":
        i8_e = regimes_out["dense_int8_baseline"]["gross_rail_measured_uj_per_correct_decision"]["median"]
        nv_e = regimes_out["subbit_naive_float_unpack"]["gross_rail_measured_uj_per_correct_decision"]["median"]
        lb_e = regimes_out["littlebit_joule_packed_int"]["gross_rail_measured_uj_per_correct_decision"]["median"]
        dn_e = regimes_out["deterministic_null_lut"]["gross_rail_measured_uj_per_correct_decision"]["median"]
        energy_ratios.update(
            {
                "impedance_tax_naive_unpack_over_int8_x": round(nv_e / max(i8_e, 1e-9), 2),
                "littlebit_packed_improvement_over_int8_x": round(i8_e / max(lb_e, 1e-9), 2),
                "littlebit_packed_improvement_over_naive_unpack_x": round(nv_e / max(lb_e, 1e-9), 2),
                "deterministic_null_improvement_over_int8_x": round(i8_e / max(dn_e, 1e-9), 2),
            }
        )
    elif meter.evidence_class == "reported_j":
        i8_e = regimes_out["dense_int8_baseline"]["pkg_reported_uj_per_correct_decision"]["median"]
        nv_e = regimes_out["subbit_naive_float_unpack"]["pkg_reported_uj_per_correct_decision"]["median"]
        lb_e = regimes_out["littlebit_joule_packed_int"]["pkg_reported_uj_per_correct_decision"]["median"]
        dn_e = regimes_out["deterministic_null_lut"]["pkg_reported_uj_per_correct_decision"]["median"]
        energy_ratios.update(
            {
                "impedance_tax_naive_unpack_over_int8_x": round(nv_e / max(i8_e, 1e-9), 2),
                "littlebit_packed_improvement_over_int8_x": round(i8_e / max(lb_e, 1e-9), 2),
                "littlebit_packed_improvement_over_naive_unpack_x": round(nv_e / max(lb_e, 1e-9), 2),
                "deterministic_null_improvement_over_int8_x": round(i8_e / max(dn_e, 1e-9), 2),
            }
        )

    cp95 = clopper_pearson_upper(divergences, total_determinism_checks, alpha=0.05, two_sided=False)
    results: dict[str, Any] = {
        "schema": "openie.littlebit_joule_benchmark.v2",
        "kit_id": "kits/littlebit-joule",
        "shot_on_goal": "Shot #2 & Shot #6 — Sub-Bit SVD + Binary Latent Factors + Walsh-Hadamard Internal Rotation on Physical Board Rails (measured_j) & RAPL (reported_j)",
        "provenance_tier": "Signed Provenance · Self-Checked",
        "license": "Apache-2.0",
        "mode": "quick" if quick else "standard",
        "trials_per_regime": n_trials,
        "host": host,
        "energy_telemetry": telemetry_meta,
        "matrix_and_factorization": {
            "d_in": D_IN,
            "m_out": M_OUT,
            "total_weights": TOTAL_WEIGHTS,
            "svd_rank_r": RANK_R,
            "subbit_storage_bits": SUBBIT_STORAGE_BITS,
            "subbit_storage_bytes": SUBBIT_BYTES,
            "effective_bits_per_weight": SUBBIT_BPW,
            "compression_ratio_vs_int8_x": round((TOTAL_WEIGHTS * 8) / SUBBIT_STORAGE_BITS, 2),
            "compression_ratio_vs_fp16_x": round((TOTAL_WEIGHTS * 16) / SUBBIT_STORAGE_BITS, 2),
            "walsh_hadamard_outlier_crest_max_over_rms_before": round(float(raw_k.value), 4),
            "walsh_hadamard_outlier_crest_max_over_rms_after": round(float(rot_k.value), 4),
        },
        "determinism_gate": {
            "total_regime_runs": total_determinism_checks,
            "divergent_runs": divergences,
            "clopper_pearson_95_upper_bound_divergence": round(cp95, 6),
        },
        "regimes": regimes_out,
        "same_meter_comparisons": {
            "wall_clock_ratios": wall_ratios,
            "energy_per_correct_decision_ratios": energy_ratios,
            "note": "Ratios computed strictly within the same meter & rail class; measured_j, reported_j, est_j, and unmetered are never mixed.",
        },
        "bitwidth_curve": bitwidth_curve,
    }

    receipt = seal_signed_receipt(
        kit_id="kits/littlebit-joule",
        payload={
            "results_blake3": blake3_derive_key_hex(
                "openie.kit.littlebit_joule.results.v2",
                json.dumps(results, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            ),
            "substrate_id": telemetry_meta.get("substrate_id"),
            "effective_bits_per_weight": SUBBIT_BPW,
            "held_out_instances": n_test,
            "trials_per_regime": n_trials,
            "divergent_runs": divergences,
            "energy_evidence_class": meter.evidence_class,
        },
        domain_context="openie.kit.littlebit_joule.receipt.v2",
    )
    assert verify_signed_receipt(receipt), "Self-check failed on generated Ed25519 receipt!"

    md = _render_markdown(results, receipt)
    return results, receipt, md


def _render_markdown(res: dict[str, Any], receipt: dict[str, Any]) -> str:
    geo = res["matrix_and_factorization"]
    det = res["determinism_gate"]
    tel = res["energy_telemetry"]
    regs = res["regimes"]
    wr = res["same_meter_comparisons"]["wall_clock_ratios"]
    er = res["same_meter_comparisons"]["energy_per_correct_decision_ratios"]

    lines = [
        "# Kit 4 (`littlebit-joule`) — Hardware-Metered Results",
        "",
        f"- **Provenance Tier:** `{res['provenance_tier']}` (`Apache-2.0`)",
        f"- **Host CPU & OS:** `{res['host']['cpu_model']}` (`{res['host']['os_kernel']}`, `{res['host']['cc_version']}`)",
        f"- **Energy Evidence Class:** **`{tel['evidence_class']}`** (`board_metered = {tel.get('board_metered', False)}`, `est_j` never mixed)",
    ]
    if tel["evidence_class"] == "measured_j":
        lines.append(
            f"- **Physical DC Shunt Rail:** `{tel['primary_sensor']}` (`{tel['primary_rail']}`)"
            + (f" + `{tel['secondary_sensor']}` (`{tel['secondary_rail']}`)" if tel.get("secondary_sensor") else "")
            + f", idle A1/A2 trimmed `{tel.get('idle_trimmed_mean_w')} W` (`{tel.get('idle_drift_pct')}%` drift, "
            f"`Falsifier 6 flag = {tel.get('falsifier_6_idle_drift_flag')}`)"
        )
    elif tel["evidence_class"] == "reported_j":
        lines.append(
            f"- **RAPL Counters:** `{tel['package_counter']}` (`{tel['package_domain']}`) & `{tel['core_counter']}` (`{tel['core_domain']}`), "
            f"idle pre/post `{tel.get('idle_pkg_w_pre')} W` / `{tel.get('idle_pkg_w_post')} W` (`{tel.get('idle_drift_pct')}%` drift)"
        )
    lines.extend(
        [
            f"- **Matrix & Factorization:** `{geo['m_out']}×{geo['d_in']}` (`{geo['total_weights']:,}` weights), rank `r = {geo['svd_rank_r']}`, "
            f"**`{geo['effective_bits_per_weight']} bits/weight`** (`{geo['subbit_storage_bytes']:,}` B = **`{geo['compression_ratio_vs_int8_x']}x` smaller than INT8**)",
            f"- **Determinism:** `{det['divergent_runs']} / {det['total_regime_runs']}` divergent runs (95% Clopper–Pearson upper bound `<= {det['clopper_pearson_95_upper_bound_divergence']}`)",
            f"- **Signed Receipt (`BLAKE3` + `Ed25519`):** `{receipt['body_blake3'][:24]}...` (offline signature check: `PASS`)",
            "",
            "## 4-Regime Comparison (`Joules-per-Correct-Decision` vs. `Deterministic Null`)",
            "",
        ]
    )
    if tel["evidence_class"] == "measured_j":
        lines.append("| Regime | Bits / Weight | Footprint | Held-Out Accuracy | Wall `ns / correct` (`IQR`) | Gross Rail `measured_j` `µJ / correct` | Net-Above-Idle `measured_j` `µJ / correct` |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|")
        for k in ("deterministic_null_lut", "dense_int8_baseline", "subbit_naive_float_unpack", "littlebit_joule_packed_int"):
            r = regs[k]
            bpw = f"`{r['bits_per_weight']:.4f}`" if r["bits_per_weight"] is not None else "`n/a (LUT)`"
            w = r["wall_ns_per_correct_decision"]
            g = r["gross_rail_measured_uj_per_correct_decision"]
            n_a12 = r["net_above_idle_a1_a2_measured_uj_per_correct_decision"]
            n_adj = r["paired_round_net_above_idle_measured_uj_per_correct_decision"]
            n_str = f"`{n_a12['median']}` (A1/A2)" if n_a12 else (f"`{n_adj['median']}` (paired; F6 gated)" if n_adj else "`n/a`")
            lines.append(
                f"| `{k}` | {bpw} | `{r['footprint_bytes']:,} B` | **`{100.0 * r['accuracy']:.2f}%`** | "
                f"`{w['median']}` (`{w['p25']}–{w['p75']}`) | **`{g['median']}`** (`{g['p25']}–{g['p75']}`) | {n_str} |"
            )
    else:
        lines.append("| Regime | Bits / Weight | Footprint | Held-Out Accuracy | Wall `ns / correct` (`IQR`) | Package `reported_j` `µJ / correct` (`IQR`) | Core `reported_j` `µJ / correct` |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|")
        for k in ("deterministic_null_lut", "dense_int8_baseline", "subbit_naive_float_unpack", "littlebit_joule_packed_int"):
            r = regs[k]
            bpw = f"`{r['bits_per_weight']:.4f}`" if r["bits_per_weight"] is not None else "`n/a (LUT)`"
            w = r["wall_ns_per_correct_decision"]
            p_uj = r["pkg_reported_uj_per_correct_decision"]
            c_uj = r["core_reported_uj_per_correct_decision"]
            p_str = f"**`{p_uj['median']}`** (`{p_uj['p25']}–{p_uj['p75']}`)" if p_uj else "`unmetered`"
            c_str = f"`{c_uj['median']}`" if c_uj else "`unmetered`"
            lines.append(
                f"| `{k}` | {bpw} | `{r['footprint_bytes']:,} B` | **`{100.0 * r['accuracy']:.2f}%`** | "
                f"`{w['median']}` (`{w['p25']}–{w['p75']}`) | {p_str} | {c_str} |"
            )

    lines.extend(
        [
            "",
            "## Key Empirical Findings",
            "",
            f"1. **Decompression Impedance Tax:** Naive `FP32` runtime unpacking at `{geo['effective_bits_per_weight']} bpw` costs **`{wr['decompression_impedance_tax_naive_over_int8_x']}x` more wall time** "
            + (f"and **`{er['impedance_tax_naive_unpack_over_int8_x']}x` more `{tel['evidence_class']}` energy** than INT8." if er.get("impedance_tax_naive_unpack_over_int8_x") else "than INT8."),
            f"2. **Packed Integer Execution:** `littlebit_joule_packed_int` achieves **`{100.0 * regs['littlebit_joule_packed_int']['accuracy']:.2f}%`** accuracy at **`{wr['littlebit_packed_speedup_over_int8_x']}x` lower latency than INT8** "
            + (f"and **`{er['littlebit_packed_improvement_over_int8_x']}x` lower `{tel['evidence_class']}` energy than INT8** (`{er['littlebit_packed_improvement_over_naive_unpack_x']}x` lower than naive unpack)." if er.get("littlebit_packed_improvement_over_int8_x") else "."),
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Run Kit 4 (littlebit-joule) benchmark and seal provenance receipt")
    ap.add_argument("--quick", action="store_true", help="Run reduced trial counts for fast verification")
    ap.add_argument("--out-dir", type=Path, default=KIT_ROOT / "results")
    ap.add_argument("--tag", type=str, default="", help="Optional substrate tag suffix for output files")
    args = ap.parse_args()

    results, receipt, md = run_benchmark(quick=args.quick)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    res_json = json.dumps(results, indent=2) + "\n"
    rec_json = json.dumps(receipt, indent=2) + "\n"
    assert_sanitized(res_json)
    assert_sanitized(rec_json)
    assert_sanitized(md)

    if args.tag:
        (args.out_dir / f"results_{args.tag}.json").write_text(res_json, encoding="utf-8")
        (args.out_dir / f"receipt_{args.tag}.json").write_text(rec_json, encoding="utf-8")
    else:
        (args.out_dir / "littlebit_joule_results.json").write_text(res_json, encoding="utf-8")
        (args.out_dir / "littlebit_joule_receipt.json").write_text(rec_json, encoding="utf-8")
        if not args.quick:
            (KIT_ROOT / "RESULTS.md").write_text(md, encoding="utf-8")
        else:
            (args.out_dir / "RESULTS_quick.md").write_text(md, encoding="utf-8")

    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
