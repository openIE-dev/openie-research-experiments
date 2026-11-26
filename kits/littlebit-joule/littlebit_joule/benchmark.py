#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Benchmark runner for Kit 4 (`kits/littlebit-joule/`, Shot on Goal #2):
Sub-Bit SVD + Binary Latent Factors + Walsh-Hadamard Internal Rotation evaluated on
`Joules-per-Correct-Decision` vs. Mandatory Deterministic Null Control.
"""

from __future__ import annotations

import argparse
import ctypes
import platform
import json
import math
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

# Exact sub-bit storage accounting for W in R^(512 x 512) at rank r = 22:
SUBBIT_STORAGE_BITS = (
    (M_OUT * RANK_R)        # U_sign: 512 * 22 = 11,264 bits
    + (RANK_R * D_IN)       # V_sign: 22 * 512 = 11,264 bits
    + (M_OUT * 16)          # row_scale_q12: 512 * 16 = 8,192 bits
    + (D_IN * 16)           # col_pre_scale_q12: 512 * 16 = 8,192 bits
    + D_IN                  # rad_sign_words: 512 bits
    + (RANK_R * 16)         # sigma_q10: 22 * 16 = 352 bits
)  # = 39,776 bits = 4,972 bytes -> 0.1517 bits/weight
SUBBIT_BPW = round(SUBBIT_STORAGE_BITS / TOTAL_WEIGHTS, 4)
SUBBIT_BYTES = SUBBIT_STORAGE_BITS // 8


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
    lib.lb_fwht_i32.argtypes = [ctypes.POINTER(ctypes.c_int32), ctypes.c_int]
    lib.lb_fwht_i32.restype = None
    lib.lb_bipolar_dot_xnor512.argtypes = [ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_uint64)]
    lib.lb_bipolar_dot_xnor512.restype = ctypes.c_int32
    return lib


REGIME_SPECS = [
    {
        "id": 0,
        "key": "deterministic_null_lut",
        "label": "Deterministic Null (4 KiB Compiled Quadrant LUT)",
        "bits_per_weight": None,
        "footprint_bytes": 4096,
        "default_reps": 800,
        "quick_reps": 300,
    },
    {
        "id": 1,
        "key": "dense_int8_baseline",
        "label": "Dense INT8 Baseline (8.00 bpw MatVec + ReLU)",
        "bits_per_weight": 8.0,
        "footprint_bytes": TOTAL_WEIGHTS,
        "default_reps": 80,
        "quick_reps": 30,
    },
    {
        "id": 2,
        "key": "subbit_naive_float_unpack",
        "label": f"Sub-Bit Naive FP32 Unpack ({SUBBIT_BPW} bpw -> Runtime FP32 Decompress)",
        "bits_per_weight": SUBBIT_BPW,
        "footprint_bytes": SUBBIT_BYTES,
        "default_reps": 8,
        "quick_reps": 3,
    },
    {
        "id": 3,
        "key": "littlebit_joule_packed_int",
        "label": f"LittleBit-Joule Packed Int ({SUBBIT_BPW} bpw XNOR+Popcount + Int FWHT)",
        "bits_per_weight": SUBBIT_BPW,
        "footprint_bytes": SUBBIT_BYTES,
        "default_reps": 250,
        "quick_reps": 100,
    },
]


def run_benchmark(quick: bool = False) -> tuple[dict[str, Any], dict[str, Any], str]:
    lib = compile_and_load_library()
    n_dev = 1500
    n_test = 1024 if quick else 1200
    n_trials = 10 if quick else 20

    meter = EnergyMeter()
    idle_pre_w = meter.sample_idle_power_w(0.15) if meter.available else None
    host = sanitized_host_info()

    ctx = lib.lb_init(n_dev, n_test)
    if not ctx:
        raise RuntimeError("Failed to initialize LbContext")

    try:
        raw_k = ctypes.c_double()
        rot_k = ctypes.c_double()
        lib.lb_get_kurtosis(ctx, ctypes.byref(raw_k), ctypes.byref(rot_k))

        per_regime_samples: dict[str, dict[str, Any]] = {}
        for spec in REGIME_SPECS:
            per_regime_samples[spec["key"]] = {
                "ns_per_decision": [],
                "ns_per_correct": [],
                "pkg_uj_per_decision": [],
                "pkg_uj_per_correct": [],
                "core_uj_per_correct": [],
                "fnv_hashes": set(),
                "correct": 0,
            }

        # Warm-up pass across all 4 regimes
        c_tmp = ctypes.c_int()
        ns_tmp = ctypes.c_double()
        for spec in REGIME_SPECS:
            lib.lb_eval_regime(ctx, spec["id"], 1, ctypes.byref(c_tmp), ctypes.byref(ns_tmp))

        # Interleaved trials to eliminate thermal / turbo ordering bias
        for trial in range(n_trials):
            rotated_order = REGIME_SPECS[trial % 4 :] + REGIME_SPECS[: trial % 4]
            for spec in rotated_order:
                reps = spec["quick_reps"] if quick else spec["default_reps"]
                corr_c = ctypes.c_int()
                el_ns = ctypes.c_double()
                s0 = meter.snapshot()
                fnv = lib.lb_eval_regime(ctx, spec["id"], reps, ctypes.byref(corr_c), ctypes.byref(el_ns))
                s1 = meter.snapshot()
                d = meter.diff(s0, s1)

                correct = int(corr_c.value)
                total_decisions = n_test * reps
                total_correct = max(1, correct * reps)

                rec = per_regime_samples[spec["key"]]
                rec["correct"] = correct
                rec["fnv_hashes"].add(f"{fnv:016x}")
                rec["ns_per_decision"].append(float(el_ns.value) / total_decisions)
                rec["ns_per_correct"].append(float(el_ns.value) / total_correct)

                if d["pkg_reported_j"] is not None:
                    pkg_uj = d["pkg_reported_j"] * 1e6
                    rec["pkg_uj_per_decision"].append(pkg_uj / total_decisions)
                    rec["pkg_uj_per_correct"].append(pkg_uj / total_correct)
                if d["core_reported_j"] is not None:
                    core_uj = d["core_reported_j"] * 1e6
                    rec["core_uj_per_correct"].append(core_uj / total_correct)
    finally:
        lib.lb_free(ctx)

    idle_post_w = meter.sample_idle_power_w(0.15) if meter.available else None
    telemetry_meta = meter.metadata()
    if idle_pre_w is not None and idle_post_w is not None:
        mean_idle = 0.5 * (idle_pre_w + idle_post_w)
        telemetry_meta["idle_pkg_w_pre"] = idle_pre_w
        telemetry_meta["idle_pkg_w_post"] = idle_post_w
        telemetry_meta["idle_drift_pct"] = round(100.0 * abs(idle_post_w - idle_pre_w) / max(mean_idle, 1e-6), 2)

    regimes_out: dict[str, Any] = {}
    total_repeatability_checks = 0
    divergent_checks = 0

    for spec in REGIME_SPECS:
        key = spec["key"]
        rec = per_regime_samples[key]
        hashes = sorted(rec["fnv_hashes"])
        total_repeatability_checks += n_trials
        if len(hashes) != 1:
            divergent_checks += len(hashes) - 1

        acc = rec["correct"] / n_test
        regimes_out[key] = {
            "label": spec["label"],
            "bits_per_weight": spec["bits_per_weight"],
            "footprint_bytes": spec["footprint_bytes"],
            "held_out_instances": n_test,
            "correct_decisions": rec["correct"],
            "accuracy": round(acc, 4),
            "prediction_stream_fnv64": hashes[0],
            "deterministic_across_all_trials": len(hashes) == 1,
            "wall_ns_per_decision": iqr_stats(rec["ns_per_decision"], digits=2),
            "wall_ns_per_correct_decision": iqr_stats(rec["ns_per_correct"], digits=2),
            "energy_evidence_class": meter.evidence_class,
            "pkg_reported_uj_per_decision": iqr_stats(rec["pkg_uj_per_decision"], digits=4) if rec["pkg_uj_per_decision"] else None,
            "pkg_reported_uj_per_correct_decision": iqr_stats(rec["pkg_uj_per_correct"], digits=4) if rec["pkg_uj_per_correct"] else None,
            "core_reported_uj_per_correct_decision": iqr_stats(rec["core_uj_per_correct"], digits=4) if rec["core_uj_per_correct"] else None,
        }

    # Same-meter comparative ratios (strictly within `reported_j` when available, and wall-clock separately)
    int8_r = regimes_out["dense_int8_baseline"]
    naive_r = regimes_out["subbit_naive_float_unpack"]
    packed_r = regimes_out["littlebit_joule_packed_int"]
    dnull_r = regimes_out["deterministic_null_lut"]

    wall_packed_vs_int8 = round(
        int8_r["wall_ns_per_correct_decision"]["median"] / packed_r["wall_ns_per_correct_decision"]["median"], 2
    )
    wall_impedance_tax_naive_vs_int8 = round(
        naive_r["wall_ns_per_correct_decision"]["median"] / int8_r["wall_ns_per_correct_decision"]["median"], 2
    )
    wall_packed_vs_naive = round(
        naive_r["wall_ns_per_correct_decision"]["median"] / packed_r["wall_ns_per_correct_decision"]["median"], 2
    )

    energy_ratios: dict[str, Any] = {"evidence_class": meter.evidence_class}
    if meter.available and packed_r["pkg_reported_uj_per_correct_decision"]:
        e_int8 = int8_r["pkg_reported_uj_per_correct_decision"]["median"]
        e_naive = naive_r["pkg_reported_uj_per_correct_decision"]["median"]
        e_pack = packed_r["pkg_reported_uj_per_correct_decision"]["median"]
        e_dnull = dnull_r["pkg_reported_uj_per_correct_decision"]["median"]
        energy_ratios.update(
            {
                "impedance_tax_naive_unpack_over_int8_x": round(e_naive / e_int8, 2) if e_int8 else None,
                "littlebit_packed_improvement_over_int8_x": round(e_int8 / e_pack, 2) if e_pack else None,
                "littlebit_packed_improvement_over_naive_unpack_x": round(e_naive / e_pack, 2) if e_pack else None,
                "deterministic_null_improvement_over_int8_x": round(e_int8 / e_dnull, 2) if e_dnull else None,
            }
        )

    cp95_div = clopper_pearson_upper(divergent_checks, total_repeatability_checks, alpha=0.05, two_sided=False)

    results = {
        "schema": "openie.kit.littlebit_joule.v1",
        "shot_on_goal": "Shot #2: LittleBit-Style Sub-Bit Compression Optimized for Joules-per-Correct-Decision vs. Deterministic Null",
        "provenance_tier": "Signed Provenance · Self-Checked",
        "license": "Apache-2.0",
        "mode": "quick" if quick else "standard",
        "host": host,
        "energy_telemetry": telemetry_meta,
        "geometry_and_compression": {
            "matrix_shape": [M_OUT, D_IN],
            "total_weights": TOTAL_WEIGHTS,
            "latent_binary_rank_r": RANK_R,
            "subbit_total_bits": SUBBIT_STORAGE_BITS,
            "subbit_total_bytes": SUBBIT_BYTES,
            "effective_bits_per_weight": SUBBIT_BPW,
            "compression_ratio_vs_int8_x": round(TOTAL_WEIGHTS / SUBBIT_BYTES, 2),
            "compression_ratio_vs_fp16_x": round((TOTAL_WEIGHTS * 2) / SUBBIT_BYTES, 2),
            "walsh_hadamard_outlier_crest_before": round(float(raw_k.value), 4),
            "walsh_hadamard_outlier_crest_after": round(float(rot_k.value), 4),
        },
        "determinism_gate": {
            "trials_per_regime": n_trials,
            "total_regime_trial_runs": total_repeatability_checks,
            "divergent_runs": divergent_checks,
            "clopper_pearson_95_upper_bound_divergence": round(cp95_div, 6),
        },
        "regimes": regimes_out,
        "comparative_findings": {
            "wall_clock_ratios_per_correct_decision": {
                "decompression_impedance_tax_naive_over_int8_x": wall_impedance_tax_naive_vs_int8,
                "littlebit_packed_speedup_over_int8_x": wall_packed_vs_int8,
                "littlebit_packed_speedup_over_naive_unpack_x": wall_packed_vs_naive,
            },
            "rapl_reported_j_ratios_per_correct_decision": energy_ratios,
        },
    }

    receipt_payload = {
        "held_out_instances": n_test,
        "effective_bits_per_weight": SUBBIT_BPW,
        "energy_evidence_class": meter.evidence_class,
        "prediction_fnv64_by_regime": {k: v["prediction_stream_fnv64"] for k, v in regimes_out.items()},
        "accuracy_by_regime": {k: v["accuracy"] for k, v in regimes_out.items()},
        "pkg_reported_uj_per_correct_median": {
            k: (v["pkg_reported_uj_per_correct_decision"]["median"] if v["pkg_reported_uj_per_correct_decision"] else None)
            for k, v in regimes_out.items()
        },
        "results_blake3": blake3_derive_key_hex(
            "openie.kit.littlebit_joule.results.v1",
            json.dumps(results, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        ),
    }
    receipt = seal_signed_receipt(
        kit_id="kits/littlebit-joule",
        payload=receipt_payload,
        domain_context="openie.kit.littlebit_joule.receipt.v1",
    )
    assert verify_signed_receipt(receipt), "Self-check of Ed25519 + BLAKE3 receipt failed!"

    md = _render_markdown(results, receipt)
    return results, receipt, md


def _render_markdown(res: dict[str, Any], receipt: dict[str, Any]) -> str:
    geo = res["geometry_and_compression"]
    tel = res["energy_telemetry"]
    regs = res["regimes"]
    comp = res["comparative_findings"]
    er = comp["rapl_reported_j_ratios_per_correct_decision"]
    wr = comp["wall_clock_ratios_per_correct_decision"]

    lines = [
        "# Kit 4 (`littlebit-joule`) — Hardware-Metered Results",
        "",
        f"- **Provenance Tier:** `{res['provenance_tier']}` (`Apache-2.0`)",
        f"- **Host CPU & OS:** `{res['host']['cpu_model']}` (`{res['host']['os_kernel']}`, `{res['host']['cc_version']}`)",
        f"- **Energy Evidence Class:** **`{tel['evidence_class']}`** (`measured_j = null`, `est_j` never mixed)",
    ]
    if tel["evidence_class"] == "reported_j":
        lines.append(
            f"- **RAPL Counters:** `{tel['package_counter']}` (`{tel['package_domain']}`) & `{tel['core_counter']}` (`{tel['core_domain']}`), "
            f"idle pre/post `{tel.get('idle_pkg_w_pre')} W` / `{tel.get('idle_pkg_w_post')} W` (`{tel.get('idle_drift_pct')}%` drift)"
        )
    lines.extend(
        [
            f"- **Matrix & Factorization:** `{geo['matrix_shape'][0]}×{geo['matrix_shape'][1]}` (`{geo['total_weights']:,}` weights), rank `r = {geo['latent_binary_rank_r']}`, "
            f"**`{geo['effective_bits_per_weight']} bits/weight`** (`{geo['subbit_total_bytes']:,}` B = **`{geo['compression_ratio_vs_int8_x']}x` smaller than INT8** / `{geo['compression_ratio_vs_fp16_x']}x` smaller than FP16)",
            f"- **Walsh-Hadamard Internal Rotation Effect:** Peak-to-RMS outlier crest reduced from `{geo['walsh_hadamard_outlier_crest_before']}` -> **`{geo['walsh_hadamard_outlier_crest_after']}`** prior to 1-bit latent sign quantization",
            f"- **Determinism:** `{res['determinism_gate']['divergent_runs']} / {res['determinism_gate']['total_regime_trial_runs']}` divergent runs across `{res['determinism_gate']['trials_per_regime']}` interleaved trials (95% Clopper–Pearson upper bound `<= {res['determinism_gate']['clopper_pearson_95_upper_bound_divergence']}`)",
            f"- **Signed Receipt (`BLAKE3` + `Ed25519`):** `{receipt['body_blake3'][:24]}...` (offline signature check: `PASS`)",
            "",
            "## 4-Regime Comparison (`Joules-per-Correct-Decision` vs. `Deterministic Null`)",
            "",
            "| Regime | Bits / Weight | Footprint | Held-Out Accuracy | Wall `ns / correct` (`IQR`) | Package `reported_j` `µJ / correct` (`IQR`) | Core `reported_j` `µJ / correct` |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for k in ("deterministic_null_lut", "dense_int8_baseline", "subbit_naive_float_unpack", "littlebit_joule_packed_int"):
        r = regs[k]
        bpw = f"`{r['bits_per_weight']:.4f}`" if r["bits_per_weight"] is not None else "`n/a (LUT)`"
        w = r["wall_ns_per_correct_decision"]
        p_uj = r["pkg_reported_uj_per_correct_decision"]
        c_uj = r["core_reported_uj_per_correct_decision"]
        p_str = f"**`{p_uj['median']}`** (`{p_uj['p25']}–{p_uj['p75']}`)" if p_uj else "`unmetered`"
        c_str = f"`{c_uj['median']}`" if c_uj else "`unmetered`"
        lines.append(
            f"| `{k}` | {bpw} | `{r['footprint_bytes']:,} B` | **`{100.0 * r['accuracy']:.2f}%`** (`{r['correct_decisions']}/{r['held_out_instances']}`) | "
            f"`{w['median']}` (`{w['p25']}–{w['p75']}`) | {p_str} | {c_str} |"
        )

    lines.extend(
        [
            "",
            "## Key Empirical Findings",
            "",
            f"1. **Decompression Impedance Tax Exposed (`subbit_naive_float_unpack` vs `dense_int8_baseline`):** "
            f"Compressing weights to `{geo['effective_bits_per_weight']} bpw` (`{geo['compression_ratio_vs_int8_x']}x` smaller than INT8) while unpacking to `FP32` at batch-1 decision time costs **`{wr['decompression_impedance_tax_naive_over_int8_x']}x` more wall time** "
            + (
                f"and **`{er['impedance_tax_naive_unpack_over_int8_x']}x` more package `reported_j` per correct decision** than plain INT8."
                if er.get("impedance_tax_naive_unpack_over_int8_x")
                else "per correct decision than plain INT8."
            ),
            f"2. **Packed Integer Execution Resolves the Impedance Tax (`littlebit_joule_packed_int`):** "
            f"Executing the same `{geo['effective_bits_per_weight']} bpw` factors via in-place integer Walsh-Hadamard butterfly + `uint64` `XNOR + popcount` achieves **`{100.0 * regs['littlebit_joule_packed_int']['accuracy']:.2f}%`** accuracy while delivering **`{wr['littlebit_packed_speedup_over_int8_x']}x` lower latency than INT8** (`{wr['littlebit_packed_speedup_over_naive_unpack_x']}x` faster than naive FP32 unpack)"
            + (
                f" and **`{er['littlebit_packed_improvement_over_int8_x']}x` lower package `reported_j` per correct decision than INT8** (`{er['littlebit_packed_improvement_over_naive_unpack_x']}x` lower than naive unpack)."
                if er.get("littlebit_packed_improvement_over_int8_x")
                else "."
            ),
            f"3. **Why the Deterministic Null Control Is Mandatory (`deterministic_null_lut`):** "
            f"A `4 KiB` compiled quadrant table (`0` neural FLOPs) already solves **`{100.0 * regs['deterministic_null_lut']['accuracy']:.2f}%`** of instances"
            + (
                f" at **`{er['deterministic_null_improvement_over_int8_x']}x` lower `reported_j` per correct decision than INT8**—"
                if er.get("deterministic_null_improvement_over_int8_x")
                else "—"
            )
            + f"isolating the exact `{100.0 * (regs['littlebit_joule_packed_int']['accuracy'] - regs['deterministic_null_lut']['accuracy']):.2f}` percentage-point fine-spectral increment paid for by the sub-bit projection.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Run Kit 4 (littlebit-joule) benchmark and seal provenance receipt")
    ap.add_argument("--quick", action="store_true", help="Run reduced trial counts for fast verification")
    ap.add_argument("--out-dir", type=Path, default=KIT_ROOT / "results")
    args = ap.parse_args()

    results, receipt, md = run_benchmark(quick=args.quick)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    res_json = json.dumps(results, indent=2) + "\n"
    rec_json = json.dumps(receipt, indent=2) + "\n"
    assert_sanitized(res_json)
    assert_sanitized(rec_json)
    assert_sanitized(md)

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
