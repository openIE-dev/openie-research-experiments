#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""LLVM MLIR / CIRCT (`hw.module` + `comb` dialect) & IEEE 1364 Verilog Lowering +
`Alive2`-Style Exhaustive `2^N` Translation-Validation Equivalence Checker (`circt/emit_circt_hw.py`).

Lowers a verified 6-input OpenIE Commit-Gate Lookup Table (`N = 6`, `2^6 = 64` minterms,
4 outputs: `commit_allow`, `hazard_trap`, `gate_class_hi`, `gate_class_lo`) AND a composed
10-input (`N = 10`, `2^10 = 1,024` states) 2-stage LUT6 cone into:
  1. Valid LLVM MLIR / CIRCT IR (`hw.module` + `comb.and` / `comb.or` / `comb.xor` / `hw.constant` / `hw.output`),
  2. Synthesizable zero-latch IEEE 1364-2005 Verilog (`module openie_commit_gate_lut6`),
and executes an exhaustive `2^N` `Alive2`-style bit-exactness equivalence proof across:
  `High-Level Spec` == `Parsed CIRCT hw+comb SSA IR` == `Parsed IEEE 1364 Verilog`
  (+ live `iverilog`/`vvp` RTL simulation & `yosys` LUT6 synthesis check when installed!).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

INPUT_NAMES_6 = (
    "spec_ok",         # bit 0: context-isolated relational spec satisfied
    "mutant_killed",   # bit 1: 100% AST mutants killed (not SPEC_VACUOUS_REFUSED)
    "ortho_ok",        # bit 2: energy classes strictly orthogonal (measured_j ⊥ reported_j ⊥ est_j)
    "sig_valid",       # bit 3: RFC 9052 / Ed25519 provenance signature valid
    "epoch_fresh",     # bit 4: capability revocation epoch current
    "fuel_within_cap", # bit 5: Wasm front-door fuel budget unexhausted
)
OUTPUT_NAMES_4 = (
    "commit_allow",    # out 0: 1 iff ALL 6 safety/provenance preconditions hold
    "hazard_trap",     # out 1: 1 iff spec_ok=1 & sig_valid=1 BUT (!mutant_killed or !ortho_ok or !epoch_fresh)
    "gate_class_hi",   # out 2: encoded audit reason bit 1
    "gate_class_lo",   # out 3: odd parity over all 6 inputs (integrity check bit)
)


# ── 1. High-Level Reference Specification (`N = 6` LUT6 & `N = 10` Cone) ─────

def high_level_spec_lut6(vec6: int) -> tuple[int, int, int, int]:
    """Canonical high-level specification of the 6-input OpenIE Hardware Commit Gate."""
    spec_ok = (vec6 >> 0) & 1
    mutant_killed = (vec6 >> 1) & 1
    ortho_ok = (vec6 >> 2) & 1
    sig_valid = (vec6 >> 3) & 1
    epoch_fresh = (vec6 >> 4) & 1
    fuel_ok = (vec6 >> 5) & 1

    commit_allow = spec_ok & mutant_killed & ortho_ok & sig_valid & epoch_fresh & fuel_ok
    # Goodhart / vacuity / orthogonality hazard trap: looks signed & passing, but fails structural barrier!
    hazard_trap = 1 if (spec_ok == 1 and sig_valid == 1 and (mutant_killed == 0 or ortho_ok == 0 or epoch_fresh == 0)) else 0
    # Gate diagnostic class MSB: 1 if security/crypto/epoch fault (`!sig_valid or !epoch_fresh`), else 0
    gate_class_hi = 1 if (sig_valid == 0 or epoch_fresh == 0) else 0
    # 6-input XOR integrity parity bit (classic non-monotone LUT6 benchmark function!)
    gate_class_lo = spec_ok ^ mutant_killed ^ ortho_ok ^ sig_valid ^ epoch_fresh ^ fuel_ok
    return (commit_allow, hazard_trap, gate_class_hi, gate_class_lo)


def build_lut6_init_masks() -> dict[str, int]:
    """Compute exact 64-bit Xilinx/CIRCT `LUT6` `INIT` truth-table masks (`uint64`) for all 4 outputs."""
    masks = {name: 0 for name in OUTPUT_NAMES_4}
    for v in range(64):
        outs = high_level_spec_lut6(v)
        for idx, name in enumerate(OUTPUT_NAMES_4):
            if outs[idx]:
                masks[name] |= 1 << v
    return masks


# ── 2. Quine-McCluskey Boolean Minimizer (`N <= 8`) for Compact `comb` / RTL ─

def _popcnt(x: int) -> int:
    return x.bit_count()


def quine_mccluskey_sop(n_vars: int, on_minterms: list[int]) -> list[tuple[int, int]]:
    """Deterministic Quine-McCluskey prime-implicant cover returning `(mask, pattern)` cubes
    where cube holds iff `(vec & mask) == pattern`. (`mask` bit=1 means literal is cared).
    """
    if not on_minterms:
        return []
    full_mask = (1 << n_vars) - 1
    # Represent implicant as `(care_mask, value_bits)`
    current = {(full_mask, m) for m in on_minterms}
    primes: set[tuple[int, int]] = set()
    while current:
        nxt: set[tuple[int, int]] = set()
        used: set[tuple[int, int]] = set()
        items = sorted(current)
        for i in range(len(items)):
            m1, v1 = items[i]
            for j in range(i + 1, len(items)):
                m2, v2 = items[j]
                if m1 != m2:
                    continue
                diff = v1 ^ v2
                if _popcnt(diff) == 1:
                    used.add(items[i])
                    used.add(items[j])
                    nxt.add((m1 & ~diff, v1 & ~diff))
        primes |= (current - used)
        current = nxt

    uncovered = set(on_minterms)
    chosen: list[tuple[int, int]] = []
    prime_list = sorted(primes, key=lambda mp: (_popcnt(mp[0]), mp[0], mp[1]))

    # Essential prime implicants first, then greedy largest-coverage tie-broken deterministically
    while uncovered:
        best_cube = max(
            prime_list,
            key=lambda mp: (sum(1 for m in uncovered if (m & mp[0]) == mp[1]), -_popcnt(mp[0]), -mp[0], -mp[1]),
        )
        chosen.append(best_cube)
        uncovered = {m for m in uncovered if (m & best_cube[0]) != best_cube[1]}
    return chosen


# ── 3. Valid LLVM MLIR / CIRCT (`hw.module` + `comb` Dialect) Emitter ────────

def emit_circt_mlir(module_name: str = "openie_commit_gate_lut6") -> str:
    """Emit standards-compliant LLVM CIRCT (`hw` + `comb` dialects) SSA IR."""
    lines: list[str] = [
        "// SPDX-License-Identifier: Apache-2.0",
        "// Generated by OpenIE `kits/standards-bridge/circt/emit_circt_hw.py`",
        "// Dialect: LLVM CIRCT `hw` + `comb` (synthesizable combinational hardware IR)",
        "module {",
        f"  hw.module @{module_name}(",
    ]
    port_lines = [f"    in %{nm} : i1," for nm in INPUT_NAMES_6]
    for idx, onm in enumerate(OUTPUT_NAMES_4):
        comma = "," if idx + 1 < len(OUTPUT_NAMES_4) else ""
        port_lines.append(f"    out {onm} : i1{comma}")
    lines.extend(port_lines)
    lines.append("  ) {")
    lines.append("    %false = hw.constant false")
    lines.append("    %true = hw.constant true")

    # Pre-invert each input once via `comb.xor %in, %true : i1` (canonical CIRCT `comb` inversion!)
    for nm in INPUT_NAMES_6:
        lines.append(f"    %not_{nm} = comb.xor %{nm}, %true : i1")

    ssa_id = 0
    out_ssa: dict[str, str] = {}

    for out_idx, out_name in enumerate(OUTPUT_NAMES_4):
        if out_name == "gate_class_lo":
            # Canonical variadic `comb.xor` for parity bit!
            arg_list = ", ".join(f"%{nm}" for nm in INPUT_NAMES_6)
            ssa_name = f"%parity_{ssa_id}"
            ssa_id += 1
            lines.append(f"    {ssa_name} = comb.xor {arg_list} : i1")
            out_ssa[out_name] = ssa_name
            continue

        minterms = [v for v in range(64) if high_level_spec_lut6(v)[out_idx] == 1]
        cubes = quine_mccluskey_sop(6, minterms)
        if not cubes:
            out_ssa[out_name] = "%false"
            continue

        cube_ssas: list[str] = []
        for care_mask, pat in cubes:
            lits: list[str] = []
            for bit_i, in_nm in enumerate(INPUT_NAMES_6):
                if (care_mask >> bit_i) & 1:
                    lits.append(f"%{in_nm}" if ((pat >> bit_i) & 1) else f"%not_{in_nm}")
            if not lits:
                cube_ssas.append("%true")
            elif len(lits) == 1:
                cube_ssas.append(lits[0])
            else:
                cname = f"%cube_{ssa_id}"
                ssa_id += 1
                lines.append(f"    {cname} = comb.and {', '.join(lits)} : i1")
                cube_ssas.append(cname)

        if len(cube_ssas) == 1:
            out_ssa[out_name] = cube_ssas[0]
        else:
            oname = f"%sop_{ssa_id}"
            ssa_id += 1
            lines.append(f"    {oname} = comb.or {', '.join(cube_ssas)} : i1")
            out_ssa[out_name] = oname

    out_vals = ", ".join(out_ssa[nm] for nm in OUTPUT_NAMES_4)
    out_types = ", ".join("i1" for _ in OUTPUT_NAMES_4)
    lines.append(f"    hw.output {out_vals} : {out_types}")
    lines.append("  }")
    lines.append("}")
    return "\n".join(lines) + "\n"


# ── 4. Synthesizable IEEE 1364-2005 Verilog Emitter ──────────────────────────

def emit_ieee1364_verilog(module_name: str = "openie_commit_gate_lut6") -> str:
    """Emit zero-latch synthesizable IEEE 1364-2005 Verilog for ASIC/FPGA toolchains."""
    masks = build_lut6_init_masks()
    lines: list[str] = [
        "// SPDX-License-Identifier: Apache-2.0",
        "// Generated by OpenIE `kits/standards-bridge/circt/emit_circt_hw.py`",
        "// Standard: Synthesizable IEEE 1364-2005 Verilog (zero latches, pure combinational LUT6)",
        "`timescale 1ns / 1ps",
        "",
        f"module {module_name} (",
    ]
    for nm in INPUT_NAMES_6:
        lines.append(f"    input  wire {nm},")
    for idx, onm in enumerate(OUTPUT_NAMES_4):
        comma = "," if idx + 1 < len(OUTPUT_NAMES_4) else ""
        lines.append(f"    output wire {onm}{comma}")
    lines.append(");")
    for onm, init64 in masks.items():
        lines.append(f"    // LUT6 INIT mask for `{onm}`: 64'h{init64:016x}")

    lines.append("")
    for out_idx, out_name in enumerate(OUTPUT_NAMES_4):
        if out_name == "gate_class_lo":
            xor_expr = " ^ ".join(INPUT_NAMES_6)
            lines.append(f"    assign {out_name} = {xor_expr};")
            continue
        minterms = [v for v in range(64) if high_level_spec_lut6(v)[out_idx] == 1]
        cubes = quine_mccluskey_sop(6, minterms)
        if not cubes:
            lines.append(f"    assign {out_name} = 1'b0;")
            continue
        terms: list[str] = []
        for care_mask, pat in cubes:
            lits = [
                (INPUT_NAMES_6[b] if ((pat >> b) & 1) else f"~{INPUT_NAMES_6[b]}")
                for b in range(6)
                if (care_mask >> b) & 1
            ]
            terms.append("1'b1" if not lits else ("(" + " & ".join(lits) + ")"))
        lines.append(f"    assign {out_name} = {' | '.join(terms)};")

    lines.append("endmodule")
    return "\n".join(lines) + "\n"


# ── 5. Independent CIRCT `hw+comb` SSA Parser & Evaluator (`Alive2`-style) ───

def parse_and_eval_circt_mlir(mlir_text: str, inputs: dict[str, int]) -> tuple[int, ...]:
    """Parse CIRCT `hw.module` + `comb.*` SSA text from scratch, enforce SSA single-assignment
    and dominance, and evaluate outputs on `inputs`.
    """
    env: dict[str, int] = {}
    in_ports: list[str] = []
    for m_in in re.finditer(r"^\s*in\s+%([A-Za-z0-9_]+)\s*:\s*i1\s*,?\s*$", mlir_text, flags=re.MULTILINE):
        pname = m_in.group(1)
        in_ports.append(pname)
        if pname not in inputs:
            raise ValueError(f"Missing input `{pname}` for CIRCT evaluation")
        env[f"%{pname}"] = inputs[pname] & 1

    if tuple(in_ports) != INPUT_NAMES_6:
        raise ValueError(f"Unexpected CIRCT input port signature: {in_ports}")

    for raw_line in mlir_text.splitlines():
        line = raw_line.split("//", 1)[0].strip()
        if not line:
            continue
        m_const = re.match(r"^(%[A-Za-z0-9_]+)\s*=\s*hw\.constant\s+(true|false|\d+)\s*(?::\s*i1)?$", line)
        if m_const:
            lhs, lit = m_const.group(1), m_const.group(2)
            if lhs in env:
                raise ValueError(f"SSA violation: duplicate definition of {lhs}")
            env[lhs] = 1 if lit in ("true", "1") else 0
            continue

        m_comb = re.match(r"^(%[A-Za-z0-9_]+)\s*=\s*comb\.(and|or|xor)\s+(.+?)\s*:\s*i1$", line)
        if m_comb:
            lhs, op, rhs_list = m_comb.group(1), m_comb.group(2), m_comb.group(3)
            if lhs in env:
                raise ValueError(f"SSA violation: duplicate definition of {lhs}")
            vals: list[int] = []
            for tok in [t.strip() for t in rhs_list.split(",")]:
                if tok not in env:
                    raise ValueError(f"SSA dominance violation: `{tok}` used before definition in `{line}`")
                vals.append(env[tok])
            if op == "and":
                res = 1
                for v in vals:
                    res &= v
            elif op == "or":
                res = 0
                for v in vals:
                    res |= v
            else:
                res = 0
                for v in vals:
                    res ^= v
            env[lhs] = res & 1
            continue

        m_out = re.match(r"^hw\.output\s+(.+?)\s*:\s*(.+)$", line)
        if m_out:
            out_toks = [t.strip() for t in m_out.group(1).split(",")]
            return tuple(env[t] for t in out_toks)

    raise ValueError("CIRCT `hw.module` missing `hw.output` terminator")


def parse_and_eval_verilog(verilog_text: str, inputs: dict[str, int]) -> tuple[int, ...]:
    """Independent combinational IEEE 1364 Verilog continuous-`assign` evaluator."""
    assigns: dict[str, str] = {}
    for m in re.finditer(r"^\s*assign\s+([A-Za-z0-9_]+)\s*=\s*(.+?)\s*;\s*$", verilog_text, flags=re.MULTILINE):
        assigns[m.group(1)] = m.group(2)

    def _eval_expr(expr: str) -> int:
        # Replace `1'b0` / `1'b1`, `~ident`, and identifiers safely
        s = expr.replace("1'b0", "0").replace("1'b1", "1")
        for nm in sorted(INPUT_NAMES_6, key=len, reverse=True):
            s = re.sub(rf"\b{re.escape(nm)}\b", str(inputs[nm] & 1), s)
        # In 1-bit Boolean logic, `~0` is `1` and `~1` is `0` (`(1 ^ x)`)
        s = re.sub(r"~\s*([01])", lambda m_not: "0" if m_not.group(1) == "1" else "1", s)
        if not re.match(r"^[\s01()&|^]+$", s):
            raise ValueError(f"Disallowed token in Verilog assign expression: {expr!r} -> {s!r}")
        return int(eval(s, {"__builtins__": {}}, {})) & 1  # noqa: S307

    return tuple(_eval_expr(assigns[nm]) for nm in OUTPUT_NAMES_4)


def translation_validate_exhaustive_lut6(mlir_text: str, verilog_text: str) -> dict[str, Any]:
    """`Alive2`-style exhaustive `2^6 = 64`-state bit-exact equivalence proof between:
      1. High-level Python reference spec
      2. CIRCT `hw.module` + `comb` SSA IR
      3. Synthesizable IEEE 1364 Verilog
    Returns counterexample witness immediately if any bit diverges.
    """
    mismatches: list[dict[str, Any]] = []
    for vec in range(64):
        inp_map = {nm: (vec >> idx) & 1 for idx, nm in enumerate(INPUT_NAMES_6)}
        ref_out = high_level_spec_lut6(vec)
        circt_out = parse_and_eval_circt_mlir(mlir_text, inp_map)
        vlog_out = parse_and_eval_verilog(verilog_text, inp_map)
        if circt_out != ref_out or vlog_out != ref_out:
            mismatches.append(
                {
                    "input_vec": vec,
                    "inputs": inp_map,
                    "spec": ref_out,
                    "circt_comb": circt_out,
                    "verilog": vlog_out,
                }
            )

    # Also verify 2-stage composed 10-input (`2^10 = 1,024` states) dual-gate cascade!
    cascade_10_mismatches = 0
    for vec10 in range(1024):
        v_stage1 = vec10 & 0x3F
        extra4 = (vec10 >> 6) & 0x0F
        s1_ref = high_level_spec_lut6(v_stage1)
        s1_circt = parse_and_eval_circt_mlir(mlir_text, {nm: (v_stage1 >> i) & 1 for i, nm in enumerate(INPUT_NAMES_6)})
        v_stage2_ref = (s1_ref[0] | ((extra4 & 1) << 1) | (((extra4 >> 1) & 1) << 2) | (((extra4 >> 2) & 1) << 3) | (((extra4 >> 3) & 1) << 4) | ((1 ^ s1_ref[1]) << 5))
        v_stage2_circt = (s1_circt[0] | ((extra4 & 1) << 1) | (((extra4 >> 1) & 1) << 2) | (((extra4 >> 2) & 1) << 3) | (((extra4 >> 3) & 1) << 4) | ((1 ^ s1_circt[1]) << 5))
        s2_ref = high_level_spec_lut6(v_stage2_ref)
        s2_circt = parse_and_eval_circt_mlir(mlir_text, {nm: (v_stage2_circt >> i) & 1 for i, nm in enumerate(INPUT_NAMES_6)})
        s2_vlog = parse_and_eval_verilog(verilog_text, {nm: (v_stage2_circt >> i) & 1 for i, nm in enumerate(INPUT_NAMES_6)})
        if s2_ref != s2_circt or s2_ref != s2_vlog:
            cascade_10_mismatches += 1

    return {
        "lut6_exhaustive_vectors": 64,
        "lut6_mismatches": len(mismatches),
        "composed_10input_cone_vectors": 1024,
        "composed_10input_mismatches": cascade_10_mismatches,
        "bit_exact_proven": len(mismatches) == 0 and cascade_10_mismatches == 0,
        "first_counterexample": mismatches[0] if mismatches else None,
    }


def _run_optional_eda_tools(verilog_text: str) -> dict[str, Any]:
    """When `iverilog`+`vvp` and/or `yosys` are installed (e.g. on Linux build host), run live
    IEEE 1364 RTL simulation across all 64 vectors and Xilinx UltraScale+ LUT6 synthesis!
    """
    path_env = os.environ.copy()
    path_env["PATH"] = f"{Path.home() / '.local' / 'bin'}:{path_env.get('PATH', '')}"
    iverilog_bin = shutil.which("iverilog", path=path_env["PATH"])
    vvp_bin = shutil.which("vvp", path=path_env["PATH"])
    yosys_bin = shutil.which("yosys", path=path_env["PATH"])

    eda_out: dict[str, Any] = {
        "iverilog_rtl_sim_64vec_passed": None,
        "yosys_lut6_synth_passed": None,
        "yosys_lut_cell_count": None,
    }

    with tempfile.TemporaryDirectory(prefix="openie-circt-eda-") as tmpd:
        tdir = Path(tmpd)
        dut_v = tdir / "openie_commit_gate_lut6.v"
        dut_v.write_text(verilog_text, encoding="utf-8")

        if iverilog_bin and vvp_bin:
            # Generate self-checking exhaustive 64-vector IEEE 1364 testbench
            masks = build_lut6_init_masks()
            tb_lines = [
                "`timescale 1ns / 1ps",
                "module tb;",
                "  reg [5:0] v;",
                "  wire commit_allow, hazard_trap, gate_class_hi, gate_class_lo;",
                "  integer errs, k;",
                f"  reg [63:0] exp0 = 64'h{masks['commit_allow']:016x};",
                f"  reg [63:0] exp1 = 64'h{masks['hazard_trap']:016x};",
                f"  reg [63:0] exp2 = 64'h{masks['gate_class_hi']:016x};",
                f"  reg [63:0] exp3 = 64'h{masks['gate_class_lo']:016x};",
                "  openie_commit_gate_lut6 dut (",
                "    .spec_ok(v[0]), .mutant_killed(v[1]), .ortho_ok(v[2]),",
                "    .sig_valid(v[3]), .epoch_fresh(v[4]), .fuel_within_cap(v[5]),",
                "    .commit_allow(commit_allow), .hazard_trap(hazard_trap),",
                "    .gate_class_hi(gate_class_hi), .gate_class_lo(gate_class_lo)",
                "  );",
                "  initial begin",
                "    errs = 0;",
                "    for (k = 0; k < 64; k = k + 1) begin",
                "      v = k[5:0]; #1;",
                "      if (commit_allow !== exp0[k] || hazard_trap !== exp1[k] || gate_class_hi !== exp2[k] || gate_class_lo !== exp3[k])",
                "        errs = errs + 1;",
                "    end",
                '    $display("IVERILOG_ERRS=%0d", errs);',
                "    $finish;",
                "  end",
                "endmodule",
            ]
            tb_v = tdir / "tb.v"
            tb_v.write_text("\n".join(tb_lines) + "\n", encoding="utf-8")
            sim_out = tdir / "sim.vvp"
            try:
                subprocess.run([iverilog_bin, "-o", str(sim_out), str(dut_v), str(tb_v)], check=True, timeout=15, env=path_env)
                sim_txt = subprocess.check_output([vvp_bin, str(sim_out)], text=True, timeout=15, env=path_env)
                eda_out["iverilog_rtl_sim_64vec_passed"] = ("IVERILOG_ERRS=0" in sim_txt)
            except Exception:
                eda_out["iverilog_rtl_sim_64vec_passed"] = False

        if yosys_bin:
            try:
                ys_script = f"read_verilog {dut_v}; synth_xilinx -family xcup -top openie_commit_gate_lut6; stat -json"
                ys_txt = subprocess.check_output([yosys_bin, "-q", "-p", ys_script], text=True, timeout=30, env=path_env)
                j_start = ys_txt.find("{")
                if j_start >= 0:
                    ys_json = json.loads(ys_txt[j_start:])
                    cells = ys_json.get("design", {}).get("num_cells_by_type", {})
                    lut_cells = sum(cnt for k, cnt in cells.items() if "LUT" in k)
                    eda_out["yosys_lut6_synth_passed"] = True
                    eda_out["yosys_lut_cell_count"] = lut_cells
            except Exception:
                eda_out["yosys_lut6_synth_passed"] = False

    return eda_out


def run_circt_lowering_and_proof(out_dir: Path | None = None) -> dict[str, Any]:
    mlir_text = emit_circt_mlir()
    verilog_text = emit_ieee1364_verilog()
    tv_proof = translation_validate_exhaustive_lut6(mlir_text, verilog_text)
    if not tv_proof["bit_exact_proven"]:
        raise RuntimeError(f"Translation validation failed: {tv_proof}")

    # Negative fault-injection test (`Alive2` counterexample soundness check):
    # Flipping a single `comb.and` to `comb.or` in CIRCT IR MUST be caught with `lut6_mismatches > 0`!
    mutated_mlir = mlir_text.replace("comb.and", "comb.or", 1)
    neg_check = translation_validate_exhaustive_lut6(mutated_mlir, verilog_text)
    if neg_check["bit_exact_proven"] or neg_check["first_counterexample"] is None:
        raise RuntimeError("Translation validator failed to detect injected CIRCT `comb` mutation!")

    eda_res = _run_optional_eda_tools(verilog_text)
    masks = build_lut6_init_masks()

    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "openie_commit_gate_lut6.circt.mlir").write_text(mlir_text, encoding="utf-8")
        (out_dir / "openie_commit_gate_lut6.v").write_text(verilog_text, encoding="utf-8")

    return {
        "module": "circt/emit_circt_hw.py",
        "circt_dialects": ["hw", "comb"],
        "verilog_standard": "IEEE 1364-2005",
        "lut_inputs_n": 6,
        "lut_outputs_m": 4,
        "lut6_init_hex_masks": {k: f"0x{v:016x}" for k, v in masks.items()},
        "circt_mlir_sha256": hashlib.sha256(mlir_text.encode("utf-8")).hexdigest(),
        "verilog_sha256": hashlib.sha256(verilog_text.encode("utf-8")).hexdigest(),
        "translation_validation": tv_proof,
        "mutation_soundness_counterexample_caught": True,
        "sample_counterexample_input_vec": neg_check["first_counterexample"]["input_vec"],
        "hardware_eda_verification": eda_res,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="CIRCT hw+comb & IEEE 1364 Verilog Emitter + 2^N Equivalence Prover")
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()
    print(json.dumps(run_circt_lowering_and_proof(out_dir=args.out_dir), indent=2))


if __name__ == "__main__":
    main()
