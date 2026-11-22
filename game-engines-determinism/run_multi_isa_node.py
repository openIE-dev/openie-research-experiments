#!/usr/bin/env python3
"""
Portable Multi-ISA / Multi-OS Benchmark Runner for `game-engines` (`GE-H1` & `GE-H2`).

Runs on x86_64 Linux, aarch64 Linux, and arm64 macOS without private paths:
  1. Compiles `sim_rust`, `sim_wasm.wasm`, `sim_cpp` (Clang strict, Clang FMA, Clang fast-math,
     and GNU GCC strict where available).
  2. Executes `GE-H1` at `--stride 100` (all 1,000 SHA-256 checkpoints from tick 100 to 100,000)
     and `--stride 1000` (5 timed replicates with OS/RAPL `reported_j` where available;
     `measured_j = None`, `board_metered = False`).
  3. Executes `GE-H2` for 25,000 ticks across strict IEEE-754 `f64` (`-ffp-contract=off`),
     hardware FMA (`-mavx2 -mfma` on x86_64 / `fmadd` on arm64), `-ffast-math`, and
     transcendental `sin/cos` (`f64_trig`), saving compressed per-tick trace files for
     exact cross-ISA / cross-OS divergence comparison.
"""

from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import gzip
import json
import os
import platform
import shutil
import statistics as st
import subprocess
import sys
import tempfile
from pathlib import Path


def safe_sd(vals: list[float]) -> float:
    return st.stdev(vals) if len(vals) > 1 else 0.0


def cmd_first_line(cmd: list[str]) -> str:
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=10)
        lines = (res.stdout or res.stderr).strip().splitlines()
        return lines[0].strip() if lines else "unavailable"
    except Exception:
        return "unavailable"


def detect_cpu_brand() -> str:
    sys_name = platform.system()
    if sys_name == "Darwin":
        return cmd_first_line(["sysctl", "-n", "machdep.cpu.brand_string"])
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.lower().startswith("model name"):
                val = line.split(":", 1)[1].strip()
                if val and val != "-":
                    return val
    except Exception:
        pass
    out = cmd_first_line(["lscpu"])
    return out if out != "unavailable" else platform.processor() or platform.machine()


class RaplReader:
    """Reads Linux powercap RAPL `energy_uj` (SATB L2 socket/core `reported_j`) if readable."""

    def __init__(self) -> None:
        self.pkg_path: Path | None = None
        self.pkg_max: int = 0
        self.core_path: Path | None = None
        self.core_max: int = 0
        if platform.system() != "Linux":
            return
        p0 = Path("/sys/class/powercap/intel-rapl:0/energy_uj")
        p0_max = Path("/sys/class/powercap/intel-rapl:0/max_energy_range_uj")
        if p0.exists() and os.access(p0, os.R_OK):
            self.pkg_path = p0
            try:
                self.pkg_max = int(p0_max.read_text().strip())
            except Exception:
                self.pkg_max = 0
        c0 = Path("/sys/class/powercap/intel-rapl:0:0/energy_uj")
        c0_max = Path("/sys/class/powercap/intel-rapl:0:0/max_energy_range_uj")
        if c0.exists() and os.access(c0, os.R_OK):
            self.core_path = c0
            try:
                self.core_max = int(c0_max.read_text().strip())
            except Exception:
                self.core_max = 0

    @property
    def available(self) -> bool:
        return self.pkg_path is not None

    def read_uj(self) -> tuple[int | None, int | None]:
        pkg = int(self.pkg_path.read_text().strip()) if self.pkg_path else None
        core = int(self.core_path.read_text().strip()) if self.core_path else None
        return pkg, core

    @staticmethod
    def delta_uj(u0: int | None, u1: int | None, max_range: int) -> int | None:
        if u0 is None or u1 is None:
            return None
        if u1 >= u0:
            return u1 - u0
        if max_range > 0:
            return (max_range - u0) + u1
        return 0


class MacRusageReader:
    """Reads macOS per-PID `proc_pid_rusage(RUSAGE_INFO_V6).ri_energy_nj` (SATB L3 `reported_j`)."""

    def __init__(self) -> None:
        self.lib = None
        if platform.system() == "Darwin":
            try:
                self.lib = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
            except Exception:
                self.lib = None

    @property
    def available(self) -> bool:
        return self.lib is not None

    def read_nj(self, pid: int) -> int | None:
        if self.lib is None:
            return None
        buf = (ctypes.c_uint64 * 64)()
        rc = self.lib.proc_pid_rusage(int(pid), 6, ctypes.byref(buf))
        if rc != 0:
            return None
        return int(buf[42])


def run_handshaked(cmd: list[str], cwd: Path, rapl: RaplReader, mac_r: MacRusageReader) -> dict:
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = ""
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None
    ready = proc.stdout.readline().strip()
    if ready != "READY":
        err = proc.stderr.read()
        proc.kill()
        raise RuntimeError(f"Target {cmd[0]} failed READY (got {ready!r}): {err}")

    pkg0, core0 = rapl.read_uj()
    mac0 = mac_r.read_nj(proc.pid)

    proc.stdin.write("GO\n")
    proc.stdin.flush()

    done_line = proc.stdout.readline().strip()
    pkg1, core1 = rapl.read_uj()
    mac1 = mac_r.read_nj(proc.pid)

    proc.stdin.write("EXIT\n")
    proc.stdin.flush()
    proc.wait(timeout=120.0)

    if not done_line.startswith("DONE\t"):
        err = proc.stderr.read()
        raise RuntimeError(f"Target {cmd[0]} failed DONE (got {done_line!r}): {err}")

    payload = json.loads(done_line.split("\t", 1)[1])
    loops = int(payload["loops"])
    dpkg_uj = rapl.delta_uj(pkg0, pkg1, rapl.pkg_max)
    dcore_uj = rapl.delta_uj(core0, core1, rapl.core_max)
    dmac_nj = (max(0, mac1 - mac0) if (mac0 is not None and mac1 is not None) else None)

    return {
        "wall_ms_per_100k": float(payload["wall_ms"]),
        "loops": loops,
        "rapl_pkg_j_per_100k": (dpkg_uj / 1e6 / loops) if dpkg_uj is not None else None,
        "rapl_core_j_per_100k": (dcore_uj / 1e6 / loops) if dcore_uj is not None else None,
        "mac_l3_j_per_100k": (dmac_nj / 1e9 / loops) if dmac_nj is not None else None,
        "checkpoints": payload["checkpoints"],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host-id", required=True, help="Canonical host tag, e.g. amd_zen5_x86_64_linux")
    ap.add_argument("--out-dir", required=True, help="Directory for output JSON and compressed traces")
    ap.add_argument("--replicates", type=int, default=5)
    ap.add_argument("--ticks-h1", type=int, default=100000)
    ap.add_argument("--ticks-h2", type=int, default=25000)
    ap.add_argument("--node-bin", default="", help="Optional explicit path to node binary")
    ap.add_argument("--compiled-only", action="store_true", help="Run only Rust + C++20 native targets")
    args = ap.parse_args()

    work_dir = Path(__file__).resolve().parent
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    sys_name = platform.system()
    arch = platform.machine()
    is_mac = sys_name == "Darwin"
    is_x86 = arch in ("x86_64", "AMD64")

    rustc_bin = shutil.which("rustc") or "rustc"
    clangxx_bin = shutil.which("clang++") or "clang++"
    gxx_bin = shutil.which("g++")
    node_bin = args.node_bin or shutil.which("node") or ""
    py_bin = sys.executable

    mingw_bin = shutil.which("x86_64-w64-mingw32-g++")
    wine_bin = shutil.which("wine64") or shutil.which("wine")

    # Verify whether g++ is genuine GNU GCC (on macOS g++ aliases Apple clang++)
    has_gnu_gxx = False
    if gxx_bin and not is_mac:
        gxx_v = cmd_first_line([gxx_bin, "--version"])
        has_gnu_gxx = "clang" not in gxx_v.lower() and "unavailable" not in gxx_v.lower()

    os_desc = (
        f"macOS {cmd_first_line(['sw_vers', '-productVersion'])} ({platform.release()})"
        if is_mac
        else f"Linux {platform.release()}"
    )
    glibc_ver = "Apple libSystem" if is_mac else cmd_first_line(["ldd", "--version"])

    rapl = RaplReader()
    mac_r = MacRusageReader()

    start_utc = dt.datetime.now(dt.timezone.utc).isoformat()
    dl_flags = [] if is_mac else ["-ldl"]
    fma_arch_flags = ["-mavx2", "-mfma"] if is_x86 else []

    with tempfile.TemporaryDirectory(prefix="ge_wave3_build_") as btmp:
        bdir = Path(btmp)
        rust_exe = bdir / "sim_rust"
        wasm_file = bdir / "sim_wasm.wasm"
        clang_strict_exe = bdir / "sim_cpp_clang_strict"
        clang_fma_exe = bdir / "sim_cpp_clang_fma"
        clang_fast_exe = bdir / "sim_cpp_clang_fastmath"
        gcc_strict_exe = bdir / "sim_cpp_gcc_strict"

        print(f"[{args.host_id}] Compiling targets ({arch}, {os_desc})...", flush=True)
        subprocess.run(
            [rustc_bin, "--edition", "2021", "-O", str(work_dir / "sim_rust.rs"), "-o", str(rust_exe)],
            check=True,
        )
        if node_bin and not args.compiled_only:
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
                *dl_flags,
                "-o",
                str(clang_strict_exe),
            ],
            check=True,
        )
        subprocess.run(
            [
                clangxx_bin,
                "-std=c++20",
                "-O3",
                "-ffp-contract=fast",
                "-fno-fast-math",
                *fma_arch_flags,
                str(work_dir / "sim_cpp.cpp"),
                *dl_flags,
                "-o",
                str(clang_fma_exe),
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
                *fma_arch_flags,
                str(work_dir / "sim_cpp.cpp"),
                *dl_flags,
                "-o",
                str(clang_fast_exe),
            ],
            check=True,
        )
        if has_gnu_gxx and gxx_bin:
            subprocess.run(
                [
                    gxx_bin,
                    "-std=c++20",
                    "-O3",
                    "-ffp-contract=off",
                    "-fno-fast-math",
                    str(work_dir / "sim_cpp.cpp"),
                    *dl_flags,
                    "-o",
                    str(gcc_strict_exe),
                ],
                check=True,
            )

        # Build GE-H1 target list
        native_loops = "40" if rapl.available else "20"
        h1_specs: list[tuple[str, str, list[str], list[str]]] = [
            (
                "rust_native",
                f"Rust native ({arch}, rustc -O)",
                [str(rust_exe), "--mode", "q32", "--ticks", str(args.ticks_h1), "--stride", "100", "--loops", "1", "--handshake"],
                [str(rust_exe), "--mode", "q32", "--ticks", str(args.ticks_h1), "--stride", "1000", "--loops", native_loops, "--handshake"],
            ),
            (
                "cpp20_clang_o3",
                f"C++20 native (clang++ -O3 -ffp-contract=off, {arch})",
                [str(clang_strict_exe), "--mode", "q32", "--ticks", str(args.ticks_h1), "--stride", "100", "--loops", "1", "--handshake"],
                [str(clang_strict_exe), "--mode", "q32", "--ticks", str(args.ticks_h1), "--stride", "1000", "--loops", native_loops, "--handshake"],
            ),
        ]
        if has_gnu_gxx:
            h1_specs.append(
                (
                    "cpp20_gcc_o3",
                    f"C++20 native (g++ -O3 -ffp-contract=off, {arch})",
                    [str(gcc_strict_exe), "--mode", "q32", "--ticks", str(args.ticks_h1), "--stride", "100", "--loops", "1", "--handshake"],
                    [str(gcc_strict_exe), "--mode", "q32", "--ticks", str(args.ticks_h1), "--stride", "1000", "--loops", native_loops, "--handshake"],
                )
            )
        if node_bin and not args.compiled_only:
            h1_specs.append(
                (
                    "rust_wasm32_node",
                    "Rust -> WebAssembly (wasm32-unknown-unknown in Node.js)",
                    [node_bin, str(work_dir / "run_wasm.mjs"), "--wasm", str(wasm_file), "--ticks", str(args.ticks_h1), "--stride", "100", "--loops", "1", "--handshake"],
                    [node_bin, str(work_dir / "run_wasm.mjs"), "--wasm", str(wasm_file), "--ticks", str(args.ticks_h1), "--stride", "1000", "--loops", "15", "--handshake"],
                )
            )
            h1_specs.append(
                (
                    "javascript_bigint_node",
                    "JavaScript (Node.js ES2024 BigInt)",
                    [node_bin, str(work_dir / "sim_js.mjs"), "--mode", "q32", "--ticks", str(args.ticks_h1), "--stride", "100", "--loops", "1", "--handshake"],
                    [node_bin, str(work_dir / "sim_js.mjs"), "--mode", "q32", "--ticks", str(args.ticks_h1), "--stride", "1000", "--loops", "2", "--handshake"],
                )
            )
        if not args.compiled_only:
            h1_specs.append(
                (
                    "python3_int",
                    f"Python {platform.python_version()} (CPython int)",
                    [py_bin, str(work_dir / "sim_py.py"), "--mode", "q32", "--ticks", str(args.ticks_h1), "--stride", "100", "--loops", "1", "--handshake"],
                    [py_bin, str(work_dir / "sim_py.py"), "--mode", "q32", "--ticks", str(args.ticks_h1), "--stride", "1000", "--loops", "1", "--handshake"],
                )
            )

        print(f"[{args.host_id}] Running GE-H1 1,000-checkpoint pass (stride=100) across {len(h1_specs)} targets...", flush=True)
        stride100_ckpts: dict[str, dict[str, str]] = {}
        for tid, _desc, cmd100, _cmd1000 in h1_specs:
            r100 = run_handshaked(cmd100, work_dir, rapl, mac_r)
            stride100_ckpts[tid] = r100["checkpoints"]
            print(
                f"  [stride=100] {tid:24s} count={len(r100['checkpoints'])} "
                f"H(100)={r100['checkpoints']['100'][:12]}... H(100k)={r100['checkpoints']['100000'][:12]}...",
                flush=True,
            )

        ref_ck100 = stride100_ckpts["rust_native"]
        assert len(ref_ck100) == 1000, f"Expected 1000 checkpoints, got {len(ref_ck100)}"

        print(f"[{args.host_id}] Running GE-H1 timed/energy replicates ({args.replicates} reps, stride=1000)...", flush=True)
        h1_summaries: list[dict] = []
        for tid, desc, _cmd100, cmd1000 in h1_specs:
            reps = []
            for r_i in range(args.replicates):
                rep = run_handshaked(cmd1000, work_dir, rapl, mac_r)
                reps.append(rep)
            w_vals = [x["wall_ms_per_100k"] for x in reps]
            pkg_vals = [x["rapl_pkg_j_per_100k"] for x in reps if x["rapl_pkg_j_per_100k"] is not None]
            core_vals = [x["rapl_core_j_per_100k"] for x in reps if x["rapl_core_j_per_100k"] is not None]
            mac_vals = [x["mac_l3_j_per_100k"] for x in reps if x["mac_l3_j_per_100k"] is not None]

            mismatches_1000 = sum(1 for k, v in ref_ck100.items() if stride100_ckpts[tid].get(k) != v)
            mismatches_reps = sum(
                1
                for x in reps
                for k, v in x["checkpoints"].items()
                if ref_ck100.get(k) != v
            )
            summary = {
                "host_id": args.host_id,
                "target_id": tid,
                "description": desc,
                "replicates": args.replicates,
                "loops_per_replicate": reps[0]["loops"],
                "wall_ms_per_100k_mean": round(st.mean(w_vals), 4),
                "wall_ms_per_100k_sd": round(safe_sd(w_vals), 4),
                "ns_per_tick_mean": round(st.mean(w_vals) * 1e6 / args.ticks_h1, 2),
                "rapl_pkg_reported_j_per_100k_mean": round(st.mean(pkg_vals), 6) if pkg_vals else None,
                "rapl_pkg_reported_j_per_100k_sd": round(safe_sd(pkg_vals), 6) if pkg_vals else None,
                "rapl_core_reported_j_per_100k_mean": round(st.mean(core_vals), 6) if core_vals else None,
                "rapl_core_reported_j_per_100k_sd": round(safe_sd(core_vals), 6) if core_vals else None,
                "mac_l3_reported_j_per_100k_mean": round(st.mean(mac_vals), 6) if mac_vals else None,
                "mac_l3_reported_j_per_100k_sd": round(safe_sd(mac_vals), 6) if mac_vals else None,
                "measured_j": None,
                "checkpoints_verified_stride100": len(stride100_ckpts[tid]),
                "checkpoint_mismatches_vs_host_rust": mismatches_1000,
                "replicate_checkpoint_mismatches": mismatches_reps,
                "tick_100_sha256": stride100_ckpts[tid]["100"],
                "tick_1000_sha256": stride100_ckpts[tid]["1000"],
                "tick_50000_sha256": stride100_ckpts[tid]["50000"],
                "tick_100000_sha256": stride100_ckpts[tid]["100000"],
            }
            h1_summaries.append(summary)
            e_str = (
                f"RAPL_pkg={summary['rapl_pkg_reported_j_per_100k_mean']:.4f}J"
                if pkg_vals
                else (f"L3={summary['mac_l3_reported_j_per_100k_mean']:.4f}J" if mac_vals else "reported_j=None")
            )
            print(
                f"  [timed] {tid:24s} wall={summary['wall_ms_per_100k_mean']:8.3f}ms  {e_str}  mismatches={mismatches_1000}",
                flush=True,
            )

        # Run GE-H2 25,000-tick float traces
        print(f"[{args.host_id}] Running GE-H2 {args.ticks_h2}-tick float traces...", flush=True)
        t_h2 = str(args.ticks_h2)
        h2_trace_specs: list[tuple[str, list[str]]] = [
            ("cpp_clang_f64_strict", [str(clang_strict_exe), "--mode", "f64_strict", "--ticks", t_h2]),
            ("cpp_clang_f64_trig", [str(clang_strict_exe), "--mode", "f64_trig", "--ticks", t_h2]),
            ("cpp_clang_f64_fma", [str(clang_fma_exe), "--mode", "f64_strict", "--ticks", t_h2]),
            ("cpp_clang_f64_fma_trig", [str(clang_fma_exe), "--mode", "f64_trig", "--ticks", t_h2]),
            ("cpp_clang_f64_fastmath", [str(clang_fast_exe), "--mode", "f64_strict", "--ticks", t_h2]),
            ("cpp_clang_f64_fastmath_trig", [str(clang_fast_exe), "--mode", "f64_trig", "--ticks", t_h2]),
            ("cpp_clang_f32_strict", [str(clang_strict_exe), "--mode", "f32_strict", "--ticks", t_h2]),
            ("rust_f64_strict", [str(rust_exe), "--mode", "f64_strict", "--ticks", t_h2]),
            ("rust_f64_trig", [str(rust_exe), "--mode", "f64_trig", "--ticks", t_h2]),
        ]
        if has_gnu_gxx:
            h2_trace_specs.extend(
                [
                    ("cpp_gcc_f64_strict", [str(gcc_strict_exe), "--mode", "f64_strict", "--ticks", t_h2]),
                    ("cpp_gcc_f64_trig", [str(gcc_strict_exe), "--mode", "f64_trig", "--ticks", t_h2]),
                ]
            )
        if node_bin and not args.compiled_only:
            h2_trace_specs.extend(
                [
                    ("node_v8_f64_strict", [node_bin, str(work_dir / "sim_js.mjs"), "--mode", "f64_strict", "--ticks", t_h2]),
                    ("node_v8_f64_trig", [node_bin, str(work_dir / "sim_js.mjs"), "--mode", "f64_trig", "--ticks", t_h2]),
                ]
            )

        h2_traces_payload: dict[str, list[list[str]]] = {}
        for tr_id, tr_cmd in h2_trace_specs:
            env = os.environ.copy()
            env["CUDA_VISIBLE_DEVICES"] = ""
            raw_out = subprocess.run(tr_cmd, cwd=str(work_dir), capture_output=True, text=True, check=True, env=env).stdout
            tr_data = json.loads(raw_out)["trace"]
            h2_traces_payload[tr_id] = tr_data
            print(f"  [GE-H2] {tr_id:28s} ticks={len(tr_data)} final_ieee={tr_data[-1][0]}", flush=True)

    end_utc = dt.datetime.now(dt.timezone.utc).isoformat()
    traces_gz_path = out_dir / f"h2_traces_{args.host_id}.json.gz"
    with gzip.open(traces_gz_path, "wt", encoding="utf-8") as gz:
        json.dump({"host_id": args.host_id, "ticks": args.ticks_h2, "traces": h2_traces_payload}, gz)

    receipt = {
        "host_id": args.host_id,
        "bench_root": "$BENCH_ROOT",
        "measured_j": None,
        "board_metered": False,
        "energy_telemetry": (
            "SATB L2 powercap RAPL (/sys/class/powercap/intel-rapl:0/energy_uj package-0 & core)"
            if rapl.available
            else (
                "SATB L3 proc_pid_rusage(RUSAGE_INFO_V6).ri_energy_nj"
                if mac_r.available
                else "none (CPU-only timing; GPU lock respected)"
            )
        ),
        "environment": {
            "cpu": detect_cpu_brand(),
            "arch": arch,
            "os": os_desc,
            "libc_libm": glibc_ver,
            "rustc": cmd_first_line([rustc_bin, "--version"]),
            "clangxx": cmd_first_line([clangxx_bin, "--version"]),
            "gxx": cmd_first_line([gxx_bin, "--version"]) if has_gnu_gxx and gxx_bin else None,
            "node": cmd_first_line([node_bin, "--version"]) if node_bin else None,
            "python": f"Python {platform.python_version()}",
            "mingw_gxx_available": bool(mingw_bin),
            "wine64_available": bool(wine_bin),
            "start_utc": start_utc,
            "end_utc": end_utc,
        },
        "ge_h1_targets": h1_summaries,
        "ge_h1_canonical_1000_checkpoints": ref_ck100,
        "ge_h2_trace_keys": list(h2_traces_payload.keys()),
    }
    receipt_path = out_dir / f"host_receipt_{args.host_id}.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"[{args.host_id}] Wrote {receipt_path.name} and {traces_gz_path.name}.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
