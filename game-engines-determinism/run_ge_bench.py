#!/usr/bin/env python3
"""
Reproducible Multi-Target Falsifier Benchmark (`GE-H1` & `GE-H2`) for `game-engines`.

Executes:
  1. `GE-H1`: 16-body 2D deterministic game simulation (`Q32.32` 64-bit integer physics,
     `SplitMix64` input event stream, pickups with deferred structural respawn, cooldown FSM)
     across 5 compilation/runtime targets for `100,000` ticks (`10^5`), verifying SHA-256
     canonical state vector equality every `1,000` ticks and at tick `100,000`, while measuring
     wall-clock ms and macOS kernel `L3` `proc_pid_rusage(child_pid, RUSAGE_INFO_V6).ri_energy_nj`
     (`reported_j`, `measured_j = None`, `board_metered = False`).

  2. `GE-H2`: Floating-point boundary/negative control on the identical 16-body loop (`25,000`
     ticks, hashed every single tick) comparing IEEE-754 `f64` strict (`-ffp-contract=off`)
     against `clang++ -O3 -ffast-math` (FMA contraction & reassociation), `Node.js Math.sin/cos`
     transcendental steering impulses, and `f32` single precision, recording exact first
     divergence ticks (`t_div_ieee_bits`, `t_div_macro_1e3`, `t_div_gameplay`).
"""

from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import hashlib
import json
import platform
import shutil
import statistics as st
import subprocess
import sys
import tempfile
from pathlib import Path

_LIBSYSTEM = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
_RUSAGE_INFO_V6 = 6


def read_pid_l3_rusage(pid: int) -> tuple[int, int]:
    """Returns `(ri_energy_nj, ri_instructions)` for `pid` via rootless `proc_pid_rusage`."""
    buf = (ctypes.c_uint64 * 64)()
    rc = _LIBSYSTEM.proc_pid_rusage(int(pid), _RUSAGE_INFO_V6, ctypes.byref(buf))
    if rc != 0:
        raise RuntimeError(f"proc_pid_rusage failed with rc={rc} for pid={pid}")
    return int(buf[42]), int(buf[31])


def safe_sd(vals: list[float]) -> float:
    return st.stdev(vals) if len(vals) > 1 else 0.0


def run_handshaked_target(cmd: list[str], cwd: Path) -> dict:
    """Runs target with READY/GO/EXIT handshake to isolate L3 `ri_energy_nj` on exact child PID."""
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None

    ready = proc.stdout.readline().strip()
    if ready != "READY":
        err = proc.stderr.read()
        proc.kill()
        raise RuntimeError(f"Target {cmd[0]} failed READY (got {ready!r}): {err}")

    e0_nj, i0 = read_pid_l3_rusage(proc.pid)
    proc.stdin.write("GO\n")
    proc.stdin.flush()

    done_line = proc.stdout.readline().strip()
    e1_nj, i1 = read_pid_l3_rusage(proc.pid)

    proc.stdin.write("EXIT\n")
    proc.stdin.flush()
    proc.wait(timeout=30.0)

    if not done_line.startswith("DONE\t"):
        err = proc.stderr.read()
        raise RuntimeError(f"Target {cmd[0]} failed DONE (got {done_line!r}): {err}")

    payload = json.loads(done_line.split("\t", 1)[1])
    loops = int(payload["loops"])
    de_nj = max(0, e1_nj - e0_nj)
    di = max(0, i1 - i0)
    return {
        "wall_ms_per_100k": float(payload["wall_ms"]),
        "loops": loops,
        "l3_ri_energy_nj_per_100k": de_nj / loops,
        "l3_reported_j_per_100k": (de_nj / loops) / 1e9,
        "l3_instructions_per_100k": di / loops,
        "checkpoints": payload["checkpoints"],
    }


def first_divergence_tick(ref_trace: list[list[str]], cmp_trace: list[list[str]], col: int) -> int | None:
    n = min(len(ref_trace), len(cmp_trace))
    for idx in range(n):
        if ref_trace[idx][col] != cmp_trace[idx][col]:
            return idx + 1  # 1-indexed tick
    return None


def get_tool_version(cmd: list[str]) -> str:
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    first = (res.stdout or res.stderr).strip().splitlines()
    return first[0].strip() if first else "unknown"


def main() -> int:
    ap = argparse.ArgumentParser(description="Execute GE-H1 and GE-H2 multi-target falsifier suite")
    ap.add_argument("--replicates", type=int, default=5, help="Replicates per GE-H1 target (default: 5)")
    ap.add_argument("--ticks-h1", type=int, default=100000, help="Ticks for GE-H1 (default: 100000)")
    ap.add_argument("--stride-h1", type=int, default=1000, help="Checkpoint stride for GE-H1 (default: 1000)")
    ap.add_argument("--ticks-h2", type=int, default=25000, help="Ticks for GE-H2 float trace (default: 25000)")
    args = ap.parse_args()

    work_dir = Path(__file__).resolve().parent
    start_utc = dt.datetime.now(dt.timezone.utc).isoformat()

    rustc_bin = shutil.which("rustc") or "rustc"
    clangxx_bin = shutil.which("clang++") or "clang++"
    node_bin = shutil.which("node") or "node"
    py_bin = sys.executable

    cpu_brand = get_tool_version(["sysctl", "-n", "machdep.cpu.brand_string"])
    sw_ver = get_tool_version(["sw_vers", "-productVersion"])
    rustc_ver = get_tool_version([rustc_bin, "--version"])
    clang_ver = get_tool_version([clangxx_bin, "--version"])
    node_ver = get_tool_version([node_bin, "--version"])
    py_ver = f"Python {platform.python_version()}"

    with tempfile.TemporaryDirectory(prefix="ge_bench_build_") as build_tmp:
        bdir = Path(build_tmp)
        rust_native_exe = bdir / "sim_rust"
        wasm_file = bdir / "sim_wasm.wasm"
        cpp_strict_exe = bdir / "sim_cpp_strict"
        cpp_fastmath_exe = bdir / "sim_cpp_fastmath"

        print("[1/4] Compiling Rust native, Rust Wasm32, C++20 strict, and C++20 -ffast-math targets...", flush=True)
        subprocess.run(
            [rustc_bin, "--edition", "2021", "-O", str(work_dir / "sim_rust.rs"), "-o", str(rust_native_exe)],
            check=True,
        )
        subprocess.run(
            [
                rustc_bin,
                "--edition",
                "2021",
                "--target",
                "wasm32-unknown-unknown",
                "-O",
                "--crate-type",
                "cdylib",
                str(work_dir / "sim_wasm.rs"),
                "-o",
                str(wasm_file),
            ],
            check=True,
        )
        subprocess.run(
            [
                clangxx_bin,
                "-std=c++20",
                "-O3",
                "-ffp-contract=off",
                "-fno-fast-math",
                str(work_dir / "sim_cpp.cpp"),
                "-o",
                str(cpp_strict_exe),
            ],
            check=True,
        )
        subprocess.run(
            [
                clangxx_bin,
                "-std=c++20",
                "-O3",
                "-ffast-math",
                "-ffp-contract=fast",
                str(work_dir / "sim_cpp.cpp"),
                "-o",
                str(cpp_fastmath_exe),
            ],
            check=True,
        )
        wasm_size_bytes = wasm_file.stat().st_size

        h1_targets = [
            (
                "rust_native_aarch64",
                "Rust native (aarch64-apple-darwin, rustc -O)",
                [
                    str(rust_native_exe),
                    "--mode",
                    "q32",
                    "--ticks",
                    str(args.ticks_h1),
                    "--stride",
                    str(args.stride_h1),
                    "--loops",
                    "25",
                    "--handshake",
                ],
            ),
            (
                "rust_wasm32_node",
                "Rust -> WebAssembly (wasm32-unknown-unknown in Node.js WebAssembly)",
                [
                    node_bin,
                    str(work_dir / "run_wasm.mjs"),
                    "--wasm",
                    str(wasm_file),
                    "--ticks",
                    str(args.ticks_h1),
                    "--stride",
                    str(args.stride_h1),
                    "--loops",
                    "15",
                    "--handshake",
                ],
            ),
            (
                "cpp20_clang_o3",
                "C++20 native (clang++ -std=c++20 -O3)",
                [
                    str(cpp_strict_exe),
                    "--mode",
                    "q32",
                    "--ticks",
                    str(args.ticks_h1),
                    "--stride",
                    str(args.stride_h1),
                    "--loops",
                    "25",
                    "--handshake",
                ],
            ),
            (
                "javascript_bigint_node",
                "JavaScript (Node.js ES2024 BigInt)",
                [
                    node_bin,
                    str(work_dir / "sim_js.mjs"),
                    "--mode",
                    "q32",
                    "--ticks",
                    str(args.ticks_h1),
                    "--stride",
                    str(args.stride_h1),
                    "--loops",
                    "2",
                    "--handshake",
                ],
            ),
            (
                "python_3_13",
                "Python 3.13 (CPython int)",
                [
                    py_bin,
                    str(work_dir / "sim_py.py"),
                    "--mode",
                    "q32",
                    "--ticks",
                    str(args.ticks_h1),
                    "--stride",
                    str(args.stride_h1),
                    "--loops",
                    "1",
                    "--handshake",
                ],
            ),
        ]

        print(
            f"[2/4] Running GE-H1 ({args.ticks_h1} ticks, {args.replicates} replicates x 5 targets)...",
            flush=True,
        )
        h1_raw: dict[str, list[dict]] = {tid: [] for tid, _, _ in h1_targets}
        for r_idx in range(args.replicates):
            for tid, label, cmd in h1_targets:
                rep = run_handshaked_target(cmd, work_dir)
                h1_raw[tid].append(rep)
                print(
                    f"  [Rep {r_idx + 1}/{args.replicates}] {tid:24s} "
                    f"wall={rep['wall_ms_per_100k']:8.2f} ms  "
                    f"L3={rep['l3_reported_j_per_100k']*1000:8.3f} mJ  "
                    f"H(100k)={rep['checkpoints'][str(args.ticks_h1)][:16]}...",
                    flush=True,
                )

        # Verify GE-H1 bitwise checkpoint identity across all 5 targets & all replicates
        ref_tid = h1_targets[0][0]
        canonical_checkpoints: dict[str, str] = h1_raw[ref_tid][0]["checkpoints"]
        checkpoint_keys = sorted(canonical_checkpoints.keys(), key=lambda k: int(k))

        total_pairwise_checks = 0
        mismatches: list[dict] = []
        tids = [t[0] for t in h1_targets]
        for i in range(len(tids)):
            for j in range(i + 1, len(tids)):
                ck_a = h1_raw[tids[i]][0]["checkpoints"]
                ck_b = h1_raw[tids[j]][0]["checkpoints"]
                for k in checkpoint_keys:
                    total_pairwise_checks += 1
                    if ck_a.get(k) != ck_b.get(k):
                        mismatches.append(
                            {"pair": f"{tids[i]} vs {tids[j]}", "tick": int(k), "a": ck_a.get(k), "b": ck_b.get(k)}
                        )
        # Also verify intra-target determinism across all replicates
        intra_rep_mismatches = 0
        for tid in tids:
            for rep in h1_raw[tid][1:]:
                if rep["checkpoints"] != canonical_checkpoints:
                    intra_rep_mismatches += 1

        ref_e_nj = st.mean(r["l3_ri_energy_nj_per_100k"] for r in h1_raw["rust_native_aarch64"])
        ref_w_ms = st.mean(r["wall_ms_per_100k"] for r in h1_raw["rust_native_aarch64"])

        h1_target_summaries: list[dict] = []
        for tid, label, _cmd in h1_targets:
            rows = h1_raw[tid]
            w_vals = [r["wall_ms_per_100k"] for r in rows]
            e_nj_vals = [r["l3_ri_energy_nj_per_100k"] for r in rows]
            e_j_vals = [r["l3_reported_j_per_100k"] for r in rows]
            inst_vals = [r["l3_instructions_per_100k"] for r in rows]
            w_mean = st.mean(w_vals)
            e_nj_mean = st.mean(e_nj_vals)
            h1_target_summaries.append(
                {
                    "target_id": tid,
                    "description": label,
                    "replicates": len(rows),
                    "calibration_loops_per_replicate": rows[0]["loops"],
                    "wall_ms_per_100k_mean": round(w_mean, 4),
                    "wall_ms_per_100k_sd": round(safe_sd(w_vals), 4),
                    "ns_per_tick_mean": round(w_mean * 1e6 / args.ticks_h1, 2),
                    "l3_ri_energy_nj_per_100k_mean": round(e_nj_mean, 1),
                    "l3_ri_energy_nj_per_100k_sd": round(safe_sd(e_nj_vals), 1),
                    "l3_reported_j_per_100k_mean": round(st.mean(e_j_vals), 6),
                    "l3_reported_j_per_100k_sd": round(safe_sd(e_j_vals), 6),
                    "l3_nj_per_tick_mean": round(e_nj_mean / args.ticks_h1, 2),
                    "l3_instructions_per_100k_mean": round(st.mean(inst_vals), 1),
                    "wall_ratio_vs_rust_native": round(w_mean / ref_w_ms, 2),
                    "l3_energy_ratio_vs_rust_native": round(e_nj_mean / ref_e_nj, 2),
                    "tick_1000_sha256": rows[0]["checkpoints"]["1000"],
                    "tick_50000_sha256": rows[0]["checkpoints"]["50000"],
                    "tick_100000_sha256": rows[0]["checkpoints"][str(args.ticks_h1)],
                    "all_100_checkpoints_match_canonical": rows[0]["checkpoints"] == canonical_checkpoints,
                }
            )

        print(f"[3/4] Running GE-H2 floating-point drift controls ({args.ticks_h2} ticks)...", flush=True)

        def fetch_trace(cmd: list[str]) -> list[list[str]]:
            out = subprocess.run(cmd, cwd=str(work_dir), capture_output=True, text=True, check=True).stdout
            return json.loads(out)["trace"]

        t_str = str(args.ticks_h2)
        traces = {
            "cpp_f64_strict": fetch_trace([str(cpp_strict_exe), "--mode", "f64_strict", "--ticks", t_str]),
            "rust_f64_strict": fetch_trace([str(rust_native_exe), "--mode", "f64_strict", "--ticks", t_str]),
            "js_f64_strict": fetch_trace([node_bin, str(work_dir / "sim_js.mjs"), "--mode", "f64_strict", "--ticks", t_str]),
            "py_f64_strict": fetch_trace([py_bin, str(work_dir / "sim_py.py"), "--mode", "f64_strict", "--ticks", t_str]),
            "cpp_f64_fastmath_fma": fetch_trace([str(cpp_fastmath_exe), "--mode", "f64_strict", "--ticks", t_str]),
            "cpp_f32_strict": fetch_trace([str(cpp_strict_exe), "--mode", "f32_strict", "--ticks", t_str]),
            "cpp_f64_strict_trig": fetch_trace([str(cpp_strict_exe), "--mode", "f64_trig", "--ticks", t_str]),
            "rust_f64_strict_trig": fetch_trace([str(rust_native_exe), "--mode", "f64_trig", "--ticks", t_str]),
            "py_f64_strict_trig": fetch_trace([py_bin, str(work_dir / "sim_py.py"), "--mode", "f64_trig", "--ticks", t_str]),
            "js_f64_math_sin_trig": fetch_trace([node_bin, str(work_dir / "sim_js.mjs"), "--mode", "f64_trig", "--ticks", t_str]),
            "cpp_f64_fastmath_trig": fetch_trace([str(cpp_fastmath_exe), "--mode", "f64_trig", "--ticks", t_str]),
            "cpp_f32_strict_trig": fetch_trace([str(cpp_strict_exe), "--mode", "f32_trig", "--ticks", t_str]),
        }

        h2_pairs = [
            # Pure IEEE-754 algebraic (+, -, *, /, sqrt) comparisons vs cpp_f64_strict
            ("cpp_f64_strict", "rust_f64_strict", "Same-ISA IEEE-754 f64 algebraic+sqrt (FMA off): Clang vs Rustc"),
            ("cpp_f64_strict", "js_f64_strict", "Same-ISA IEEE-754 f64 algebraic+sqrt (FMA off): Clang vs V8 Number"),
            ("cpp_f64_strict", "py_f64_strict", "Same-ISA IEEE-754 f64 algebraic+sqrt (FMA off): Clang vs CPython float"),
            (
                "cpp_f64_strict",
                "cpp_f64_fastmath_fma",
                "Compiler FMA contraction & reassociation: -ffp-contract=off vs -O3 -ffast-math",
            ),
            ("cpp_f64_strict", "cpp_f32_strict", "Precision step-down: IEEE-754 binary64 (f64) vs binary32 (f32)"),
            # Transcendental steering impulse (cos/sin) comparisons vs cpp_f64_strict_trig
            ("cpp_f64_strict_trig", "rust_f64_strict_trig", "Same-OS libm sin/cos (f64 strict): Clang vs Rustc"),
            ("cpp_f64_strict_trig", "py_f64_strict_trig", "Same-OS libm sin/cos (f64 strict): Clang vs CPython math.sin"),
            (
                "cpp_f64_strict_trig",
                "js_f64_math_sin_trig",
                "Cross-runtime transcendental drift (f64 strict, no fast-math): system libm vs Node.js V8 Math.sin/cos",
            ),
            (
                "cpp_f64_strict_trig",
                "cpp_f64_fastmath_trig",
                "Transcendental + FMA contraction: f64 strict vs -O3 -ffast-math",
            ),
            (
                "cpp_f64_strict_trig",
                "cpp_f32_strict_trig",
                "Transcendental + binary32 precision: f64 strict vs f32 strict",
            ),
        ]

        h2_results: list[dict] = []
        for ref_name, cmp_name, desc in h2_pairs:
            t_ieee = first_divergence_tick(traces[ref_name], traces[cmp_name], 0)
            t_mm = first_divergence_tick(traces[ref_name], traces[cmp_name], 1)
            t_gp = first_divergence_tick(traces[ref_name], traces[cmp_name], 2)
            row = {
                "reference": ref_name,
                "candidate": cmp_name,
                "mechanism": desc,
                "ticks_tested": args.ticks_h2,
                "diverged": t_ieee is not None,
                "t_div_ieee_bits": t_ieee,
                "t_div_macro_1e3": t_mm,
                "t_div_gameplay": t_gp,
            }
            h2_results.append(row)
            print(
                f"  {ref_name:20s} vs {cmp_name:22s} -> "
                f"t_div_bits={str(t_ieee):>6s}  t_div_1e3={str(t_mm):>6s}  t_div_gameplay={str(t_gp):>6s}",
                flush=True,
            )

    end_utc = dt.datetime.now(dt.timezone.utc).isoformat()
    print("[4/4] Writing results.json, RESULTS.md, and SHA256SUMS...", flush=True)

    ge_h1_passed = (len(mismatches) == 0) and (intra_rep_mismatches == 0)
    results_doc = {
        "study": "game-engines",
        "measured_j": None,
        "board_metered": False,
        "energy_reporting_level": "reported_j",
        "telemetry_channel": "L3 proc_pid_rusage(child_pid, RUSAGE_INFO_V6).ri_energy_nj (SATB label D)",
        "environment": {
            "cpu": cpu_brand,
            "os": f"macOS {sw_ver}",
            "arch": platform.machine(),
            "rustc": rustc_ver,
            "clangxx": clang_ver,
            "node": node_ver,
            "python": py_ver,
            "wasm_module_bytes": wasm_size_bytes,
            "start_utc": start_utc,
            "end_utc": end_utc,
        },
        "GE_H1": {
            "hypothesis": "16-body 2D Form simulation projections under Q32.32 64-bit integer physics are bitwise identical across all 5 targets for 100,000 ticks.",
            "ticks": args.ticks_h1,
            "checkpoint_stride": args.stride_h1,
            "checkpoints_per_target": len(checkpoint_keys),
            "target_pairs": 10,
            "total_pairwise_hash_comparisons": total_pairwise_checks,
            "pairwise_hash_mismatches": len(mismatches),
            "intra_target_replicate_mismatches": intra_rep_mismatches,
            "falsified": not ge_h1_passed,
            "verdict": "PASS_ZERO_MISMATCHES" if ge_h1_passed else "FALSIFIED",
            "canonical_tick_1000_sha256": canonical_checkpoints["1000"],
            "canonical_tick_50000_sha256": canonical_checkpoints["50000"],
            "canonical_tick_100000_sha256": canonical_checkpoints[str(args.ticks_h1)],
            "targets": h1_target_summaries,
            "canonical_checkpoints_all_100": canonical_checkpoints,
        },
        "GE_H2": {
            "hypothesis": "Floating-point negative/boundary control: compiler FMA contraction (-ffast-math), cross-runtime sin/cos transcendentals (libm vs V8 Math.sin), and binary32 precision diverge at exact measurable ticks and cascade via chaotic 16-body collisions into macroscopic gameplay desynchronization.",
            "ticks_tested": args.ticks_h2,
            "comparisons": h2_results,
        },
    }

    results_json_path = work_dir / "results.json"
    results_json_path.write_text(json.dumps(results_doc, indent=2) + "\n", encoding="utf-8")

    # Build RESULTS.md
    md_lines = [
        "# `game-engines` Empirical Falsifier Suite (`GE-H1` & `GE-H2`)",
        "",
        f"- **Host**: `{cpu_brand}`, `macOS {sw_ver}` (`{platform.machine()}`)",
        f"- **Toolchains**: `{rustc_ver}` | `{clang_ver}` | `Node.js {node_ver}` | `{py_ver}`",
        "- **Energy Discipline**: `measured_j = None`, `board_metered = false`, strictly `reported_j` via macOS kernel per-PID `proc_pid_rusage(child_pid, RUSAGE_INFO_V6).ri_energy_nj` (`SATB` level `L3`, label `D`).",
        "",
        "## 1. `GE-H1`: Cross-Target 100,000-Tick Determinism (`Q32.32` Integer Physics)",
        "",
        f"- **Verdict**: **`{results_doc['GE_H1']['verdict']}`** (`{len(mismatches)}` mismatches across `{total_pairwise_checks}` pairwise SHA-256 checkpoint comparisons; `10` target pairs x `100` checkpoints from tick `1,000` to `100,000`).",
        f"- **Canonical SHA-256 at tick `1,000`**: `{canonical_checkpoints['1000']}`",
        f"- **Canonical SHA-256 at tick `50,000`**: `{canonical_checkpoints['50000']}`",
        f"- **Canonical SHA-256 at tick `100,000`**: `{canonical_checkpoints[str(args.ticks_h1)]}`",
        "",
        "| Target | Wall ms / 100k (mean ± SD) | ns / tick | `L3` `reported_j` / 100k (J) | `L3` nJ / tick | Energy ratio vs Rust | 100/100 SHA-256 match |",
        "|---|---:|---:|---:|---:|---:|:---:|",
    ]
    for t in h1_target_summaries:
        md_lines.append(
            f"| `{t['target_id']}` | `{t['wall_ms_per_100k_mean']:.3f} ± {t['wall_ms_per_100k_sd']:.3f}` | "
            f"`{t['ns_per_tick_mean']:.1f}` | `{t['l3_reported_j_per_100k_mean']:.6f} ± {t['l3_reported_j_per_100k_sd']:.6f}` | "
            f"`{t['l3_nj_per_tick_mean']:.2f}` | `{t['l3_energy_ratio_vs_rust_native']:.2f}x` | "
            f"`{'YES' if t['all_100_checkpoints_match_canonical'] else 'NO'}` |"
        )

    md_lines.extend(
        [
            "",
            "## 2. `GE-H2`: Floating-Point Drift & Chaotic Cascade Boundary Control (`25,000` Ticks)",
            "",
            "Each tick records three SHA-256 observables over the 16-body arena:",
            "1. `t_div_ieee_bits`: first tick where canonical IEEE-754 state bits diverge;",
            "2. `t_div_macro_1e3`: first tick where quantized `10^-3` arena-unit positions diverge;",
            "3. `t_div_gameplay`: first tick where discrete gameplay state (`score`, `cooldown FSM`, `active pickups`, `arena quadrant`) diverges.",
            "",
            "| Reference | Candidate | Mechanism | `t_div_ieee_bits` | `t_div_macro_1e3` | `t_div_gameplay` |",
            "|---|---|---|---:|---:|---:|",
        ]
    )
    for r in h2_results:
        b_s = f"`{r['t_div_ieee_bits']}`" if r["t_div_ieee_bits"] is not None else "`None (>25,000)`"
        m_s = f"`{r['t_div_macro_1e3']}`" if r["t_div_macro_1e3"] is not None else "`None (>25,000)`"
        g_s = f"`{r['t_div_gameplay']}`" if r["t_div_gameplay"] is not None else "`None (>25,000)`"
        md_lines.append(f"| `{r['reference']}` | `{r['candidate']}` | {r['mechanism']} | {b_s} | {m_s} | {g_s} |")

    results_md_path = work_dir / "RESULTS.md"
    results_md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    # Write SHA256SUMS over all files in work_dir except SHA256SUMS itself
    tracked_files = sorted(
        p for p in work_dir.iterdir() if p.is_file() and p.name != "SHA256SUMS" and not p.name.startswith(".")
    )
    sha_lines = []
    for p in tracked_files:
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        sha_lines.append(f"{h}  {p.name}")
    (work_dir / "SHA256SUMS").write_text("\n".join(sha_lines) + "\n", encoding="utf-8")
    print("Completed GE-H1 and GE-H2 suite successfully.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
