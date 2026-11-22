#!/usr/bin/env python3
"""
Step 2: Real On-Chip `reported_j` (`L3` `proc_pid_rusage` `ri_energy_nj` + `L2` `macmon` `IOReport`)
Receipts for `openIE-dev/rce` and `openIE-dev/rce-vc` on Apple Silicon (Apple M5 Max).

Follows `SATB` v0.4 / RCE D.11 provenance discipline:
  - `L3` (`label = "D"`): `proc_pid_rusage(tracked_pid, RUSAGE_INFO_V6)` (`ri_energy_nj` slot 42,
    `ri_instructions` slot 31, `ri_cycles` slot 32), strictly isolating the SUT process from any
    host CPU co-tenant (`yosys-abc`).
  - `L2` (`label = "A2"`): `macmon pipe -s 0 -i 200` (`IOReport` `chip_power`, `cpu_power`, `gpu_power`),
    with pre/post `2.0s` trimmed baseline windows and Falsifier 6 check (`idle_drift_pct <= 5.0%`).
  - `measured_j`: `None` (`board_metered = False`; no external shunt or wall power meter attached).
"""

import ctypes
import json
import os
import platform
import statistics
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

AUDIT_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = Path(__file__).resolve().parent
RCE_DIR = AUDIT_ROOT / "rce"
RCEVC_DIR = AUDIT_ROOT / "rce-vc"
METER_RCE = RCE_DIR / "spec/checker/target/release/meter-rce"
METER_RCEVC = RCEVC_DIR / "target/release/meter-rcevc"

_LIBSYSTEM = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
_RUSAGE_INFO_V6 = 6


def read_pid_l3_rusage(pid: int) -> tuple[int, int, int]:
    buf = (ctypes.c_uint64 * 64)()
    rc = _LIBSYSTEM.proc_pid_rusage(int(pid), _RUSAGE_INFO_V6, ctypes.byref(buf))
    if rc != 0:
        return 0, 0, 0
    return int(buf[42]), int(buf[31]), int(buf[32])


def sample_idle_window(window_s: float = 2.0, gpu_ceiling_w: float = 1.5, max_cooldown_s: float = 4.0) -> tuple[float, float]:
    t0 = time.perf_counter()
    settled = False
    vals: list[float] = []
    proc = None
    try:
        proc = subprocess.Popen(
            ["macmon", "pipe", "-s", "0", "-i", "200"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        assert proc.stdout is not None
        t_sample = None
        for line in proc.stdout:
            now = time.perf_counter()
            try:
                d = json.loads(line)
                chip_w = float(d.get("chip_power", d.get("all_power", 0.0)))
                gpu_w = float(d.get("gpu_power", 0.0))
            except Exception:
                continue
            if not settled:
                if gpu_w <= gpu_ceiling_w or (now - t0) >= max_cooldown_s:
                    settled = True
                    t_sample = now
                    vals.append(chip_w)
            else:
                vals.append(chip_w)
                assert t_sample is not None
                if (now - t_sample) >= window_s and len(vals) >= 6:
                    break
    finally:
        if proc is not None:
            proc.kill()
    cool_s = max(0.0, (time.perf_counter() - t0) - window_s)
    if len(vals) >= 6:
        sv = sorted(vals)[1:-1]
        mean_w = sum(sv) / len(sv)
    elif vals:
        mean_w = sum(vals) / len(vals)
    else:
        mean_w = 0.0
    return mean_w, round(cool_s, 3)


def run_synced_metered(cmd: list[str]) -> dict:
    """
    Launches a `--sync` Rust meter binary, waits until warmup/genesis finishes (`READY`),
    samples `idle_pre_w`, attaches `L3` `proc_pid_rusage(child.pid)` + `L2` `macmon` `IOReport`,
    signals `GO\\n`, reads `DONE {...}`, and samples `idle_post_w` + Falsifier 6 drift check.
    """
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdin and proc.stdout
    ready_line = proc.stdout.readline().strip()
    if ready_line != "READY":
        err = proc.stderr.read() if proc.stderr else ""
        proc.kill()
        raise RuntimeError(f"Expected READY, got {ready_line!r}: {err}")

    idle_pre_w, cool_pre_s = sample_idle_window()
    e0_nj, i0, c0 = read_pid_l3_rusage(proc.pid)

    samples: list[tuple[float, float, float, float]] = []
    stop = threading.Event()
    mproc = subprocess.Popen(
        ["macmon", "pipe", "-s", "0", "-i", "200"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )

    def reader():
        assert mproc.stdout is not None
        for ln in mproc.stdout:
            if stop.is_set():
                break
            try:
                d = json.loads(ln)
                t_obj = d.get("temp") or {}
                samples.append(
                    (
                        float(d.get("chip_power", d.get("all_power", 0.0))),
                        float(d.get("cpu_power", 0.0)),
                        float(d.get("gpu_power", 0.0)),
                        float(t_obj.get("gpu_temp_avg", 0.0)),
                    )
                )
            except Exception:
                pass

    thr = threading.Thread(target=reader, daemon=True)
    thr.start()

    t_wall0 = time.perf_counter()
    proc.stdin.write("GO\n")
    proc.stdin.flush()
    done_line = proc.stdout.readline().strip()
    ext_wall_s = time.perf_counter() - t_wall0
    e1_nj, i1, c1 = read_pid_l3_rusage(proc.pid)

    stop.set()
    mproc.kill()
    thr.join(timeout=0.5)
    proc.wait(timeout=5.0)

    idle_post_w, cool_post_s = sample_idle_window()

    if not done_line.startswith("DONE "):
        raise RuntimeError(f"Unexpected output: {done_line!r}")
    inner = json.loads(done_line[5:])

    mean_idle = 0.5 * (idle_pre_w + idle_post_w)
    drift_pct = abs(idle_post_w - idle_pre_w) / max(0.1, mean_idle) * 100.0
    drift_valid = drift_pct <= 5.0
    n_s = len(samples)
    mean_chip = sum(s[0] for s in samples) / n_s if n_s else mean_idle
    mean_cpu = sum(s[1] for s in samples) / n_s if n_s else 0.0
    mean_gpu = sum(s[2] for s in samples) / n_s if n_s else 0.0
    peak_temp = max((s[3] for s in samples), default=0.0)
    wall_s = float(inner["wall_s"])
    gross_j = mean_chip * wall_s
    marginal_j = (mean_chip - mean_idle) * wall_s

    ext_l3_nj = max(0, e1_nj - e0_nj)
    # Prefer in-process `self_l3_ri_energy_nj` read tightly around the inner loop (pre-exit)
    l3_nj = int(inner.get("self_l3_ri_energy_nj", ext_l3_nj))
    l3_j = l3_nj / 1e9

    return {
        "workload": inner,
        "satb_meter": {
            "boundary": "SATB_Dual_L2_SoC_A2_and_L3_PID_D",
            "board_metered": False,
            "measured_j": None,
            "wall_s": round(wall_s, 6),
            "external_sync_wall_s": round(ext_wall_s, 6),
            "l2_soc_a2": {
                "level": "L2_package_soc",
                "attribution_label": "A2",
                "sampler": "macmon pipe -s 0 -i 200 (IOReport)",
                "samples": n_s,
                "cooldown_pre_s": cool_pre_s,
                "cooldown_post_s": cool_post_s,
                "idle_pre_w": round(idle_pre_w, 3),
                "idle_post_w": round(idle_post_w, 3),
                "idle_drift_pct": round(drift_pct, 2),
                "baseline_drift_valid_5pct": drift_valid,
                "mean_chip_w": round(mean_chip, 3),
                "mean_cpu_w": round(mean_cpu, 3),
                "mean_gpu_w": round(mean_gpu, 3),
                "peak_gpu_temp_c": round(peak_temp, 1),
                "reported_gross_j": round(gross_j, 4),
                "reported_derived_marginal_j": round(marginal_j, 4) if drift_valid else "invalidated_by_cotenant_drift_falsifier6",
            },
            "l3_pid_d": {
                "level": "L3_process_cgroup",
                "attribution_label": "D",
                "counter": "proc_pid_rusage(pid, RUSAGE_INFO_V6).ri_energy_nj",
                "reported_j": round(l3_j, 6),
                "reported_nj": l3_nj,
                "external_parent_observed_nj": ext_l3_nj,
                "ri_instructions": int(inner.get("self_l3_instructions", max(0, i1 - i0))),
                "ri_cycles": int(inner.get("self_l3_cycles", max(0, c1 - c0))),
            },
        },
    }


def git_head_info(repo: Path) -> dict:
    short = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "--short=8", "HEAD"], text=True).strip()
    full = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    date = subprocess.check_output(["git", "-C", str(repo), "log", "-1", "--format=%cs", "HEAD"], text=True).strip()
    return {"commit_short": short, "commit_full": full, "commit_date": date}


def detect_cotenant() -> list[str]:
    out = subprocess.check_output(["ps", "-Ao", "pcpu,comm"], text=True, errors="ignore")
    busy = []
    for ln in out.splitlines()[1:]:
        parts = ln.strip().split(None, 1)
        if len(parts) == 2:
            try:
                cpu = float(parts[0])
                name = Path(parts[1]).name
                if cpu >= 25.0 and name not in ("ps", "macmon", "python3", "Python"):
                    busy.append(f"{name} ({cpu:.1f}% CPU)")
            except ValueError:
                pass
    return busy


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    chip_brand = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip()
    ncpu = int(subprocess.check_output(["sysctl", "-n", "hw.ncpu"], text=True).strip())
    cotenants = detect_cotenant()

    print(f"[Step 2] Host: {chip_brand} ({ncpu} logical CPUs) | Co-tenants: {cotenants}")

    # 1. RCE Form check (with W-MUT-1 mutation gate, N = 20 passes = 1,240 Form checks, R = 3 runs)
    rce_check_runs = []
    for r in range(3):
        res = run_synced_metered([str(METER_RCE), str(RCE_DIR / "spec"), "check_mut", "20", "--sync"])
        w = res["workload"]
        l3_j = res["satb_meter"]["l3_pid_d"]["reported_j"]
        uj_per_form = l3_j * 1e6 / w["checks_ok"]
        mj_per_suite = l3_j * 1e3 / w["passes"]
        res["derived_metrics"] = {
            "reported_l3_uj_per_form_check": round(uj_per_form, 2),
            "reported_l3_mj_per_62_form_suite": round(mj_per_suite, 3),
            "wall_ms_per_form_check": round(w["wall_s"] * 1e3 / w["checks_ok"], 4),
            "wall_ms_per_62_form_suite": round(w["wall_s"] * 1e3 / w["passes"], 3),
            "measured_j": None,
        }
        rce_check_runs.append(res)
        print(
            f"  [rce check_mut N=20 run {r+1}/3] wall={w['wall_s']:.3f}s | L3={l3_j:.4f} J "
            f"({uj_per_form:.1f} uJ/Form, {mj_per_suite:.2f} mJ/suite) | "
            f"L2 drift={res['satb_meter']['l2_soc_a2']['idle_drift_pct']}% (valid={res['satb_meter']['l2_soc_a2']['baseline_drift_valid_5pct']})"
        )

    # 2. RCE Full Suite: check (with W-MUT-1) + run/trace examples + emit (form, rust, python, js, scala), N = 20 passes
    print("  [rce full_suite_mut N=20] Running 20 full check+run+emit passes across all 62 spec example Forms...")
    rce_full = run_synced_metered([str(METER_RCE), str(RCE_DIR / "spec"), "full_suite_mut", "20", "--sync"])
    wf = rce_full["workload"]
    l3_full_j = rce_full["satb_meter"]["l3_pid_d"]["reported_j"]
    rce_full["derived_metrics"] = {
        "reported_l3_j_total_20_passes": round(l3_full_j, 4),
        "reported_l3_mj_per_full_suite": round(l3_full_j * 1e3 / wf["passes"], 2),
        "reported_l3_uj_per_form_lifecycle": round(l3_full_j * 1e6 / wf["checks_ok"], 2),
        "wall_s_per_full_suite": round(wf["wall_s"] / wf["passes"], 4),
        "wall_ms_per_form_lifecycle": round(wf["wall_s"] * 1e3 / wf["checks_ok"], 3),
        "measured_j": None,
    }
    print(
        f"  [rce full_suite_mut N=20] wall={wf['wall_s']:.3f}s | L3={l3_full_j:.4f} J "
        f"({rce_full['derived_metrics']['reported_l3_mj_per_full_suite']:.2f} mJ/full suite) | "
        f"L2 drift={rce_full['satb_meter']['l2_soc_a2']['idle_drift_pct']}%"
    )

    # 3. RCE-VC 100,000-unit admission benchmark:
    #    (a) Exact README configuration: 64 writers x 5 rounds = 320 admissions on 100,000 units (R = 5 runs)
    rcevc_320_runs = []
    for r in range(5):
        out = subprocess.check_output([str(METER_RCEVC), "64", "5", "10000"], text=True).strip()
        row = json.loads(out[5:])
        rcevc_320_runs.append(row)
    med_320_us = statistics.median(x["wall_us_per_submission"] for x in rcevc_320_runs)
    med_320_uj = statistics.median(x["self_l3_uj_per_submission"] for x in rcevc_320_runs)
    print(f"  [rce-vc 100k units 64x5=320 admissions, R=5] median wall={med_320_us:.2f} us/adm | median L3={med_320_uj:.2f} uJ/adm")

    #    (b) Sustained >= 1.5s window: 64 writers x 500 rounds = 32,000 admissions on 100,000 units (R = 3 synced runs)
    rcevc_sustained_runs = []
    for r in range(3):
        res = run_synced_metered([str(METER_RCEVC), "64", "500", "10000", "--sync"])
        wv = res["workload"]
        l3_vj = res["satb_meter"]["l3_pid_d"]["reported_j"]
        uj_adm = l3_vj * 1e6 / wv["submissions"]
        res["derived_metrics"] = {
            "reported_l3_uj_per_admission": round(uj_adm, 3),
            "wall_us_per_admission": round(wv["wall_s"] * 1e6 / wv["submissions"], 3),
            "instructions_per_admission": round(wv["self_l3_instructions"] / wv["submissions"], 1),
            "est_uj_per_admission_table": round(wv["est_uj_total"] / wv["submissions"], 1),
            "measured_j": None,
        }
        rcevc_sustained_runs.append(res)
        print(
            f"  [rce-vc 100k units 64x500=32000 admissions run {r+1}/3] wall={wv['wall_s']:.3f}s "
            f"({res['derived_metrics']['wall_us_per_admission']:.2f} us/adm) | "
            f"L3={l3_vj:.4f} J ({uj_adm:.2f} uJ/adm) | "
            f"L2 drift={res['satb_meter']['l2_soc_a2']['idle_drift_pct']}%"
        )

    summary = {
        "schema": "openie-rce-reported-energy-receipt/1",
        "recorded_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "machine": {
            "chip": chip_brand,
            "arch": platform.machine(),
            "os": f"macOS {platform.mac_ver()[0]}",
            "logical_cpus": ncpu,
            "active_cotenants_untouched": cotenants,
        },
        "provenance_labels": {
            "reported_j": "macOS kernel proc_pid_rusage(pid, RUSAGE_INFO_V6).ri_energy_nj (SATB L3 label D, per-PID isolated) + macmon IOReport (SATB L2 label A2, whole-SoC with Falsifier 6 5% idle-drift gate)",
            "measured_j": None,
            "board_metered": False,
        },
        "repos": {
            "rce": git_head_info(RCE_DIR),
            "rce_vc": git_head_info(RCEVC_DIR),
        },
        "rce_spec_examples_check_mut_n20": {
            "passes_per_run": 20,
            "programs_per_pass": 61,
            "files_per_pass": 62,
            "total_form_checks_per_run": 1240,
            "median_reported_l3_uj_per_form_check": round(
                statistics.median(r["derived_metrics"]["reported_l3_uj_per_form_check"] for r in rce_check_runs), 2
            ),
            "median_reported_l3_mj_per_62_form_suite": round(
                statistics.median(r["derived_metrics"]["reported_l3_mj_per_62_form_suite"] for r in rce_check_runs), 3
            ),
            "median_wall_ms_per_form_check": round(
                statistics.median(r["derived_metrics"]["wall_ms_per_form_check"] for r in rce_check_runs), 4
            ),
            "median_wall_s_window": round(statistics.median(r["workload"]["wall_s"] for r in rce_check_runs), 4),
            "measured_j": None,
            "runs": rce_check_runs,
        },
        "rce_spec_examples_full_suite_check_run_emit_n20": {
            "passes": 20,
            "programs_per_pass": 61,
            "files_per_pass": 62,
            "total_form_checks": wf["checks_ok"],
            "total_example_traces_ran": wf["traces_ran"],
            "total_target_emissions": wf["emits_ok"],
            "targets": ["form", "rust", "python", "js", "scala"],
            "reported_l3_j_total_20_passes": rce_full["derived_metrics"]["reported_l3_j_total_20_passes"],
            "reported_l3_mj_per_full_suite": rce_full["derived_metrics"]["reported_l3_mj_per_full_suite"],
            "reported_l3_uj_per_form_lifecycle": rce_full["derived_metrics"]["reported_l3_uj_per_form_lifecycle"],
            "wall_s_total": round(wf["wall_s"], 4),
            "wall_s_per_full_suite": rce_full["derived_metrics"]["wall_s_per_full_suite"],
            "measured_j": None,
            "run": rce_full,
        },
        "rce_vc_100k_units_admission": {
            "units": 100000,
            "modules": 10000,
            "units_per_module": 10,
            "readme_workload_64w_x_5r_320_admissions": {
                "trials": 5,
                "submissions_per_trial": 320,
                "median_wall_us_per_admission": round(med_320_us, 3),
                "median_reported_l3_uj_per_admission": round(med_320_uj, 3),
                "median_genesis_s": round(statistics.median(x["genesis_s"] for x in rcevc_320_runs), 4),
                "measured_j": None,
                "runs": rcevc_320_runs,
            },
            "sustained_window_64w_x_500r_32000_admissions": {
                "trials": 3,
                "submissions_per_trial": 32000,
                "median_wall_s_window": round(statistics.median(r["workload"]["wall_s"] for r in rcevc_sustained_runs), 4),
                "median_wall_us_per_admission": round(
                    statistics.median(r["derived_metrics"]["wall_us_per_admission"] for r in rcevc_sustained_runs), 3
                ),
                "median_reported_l3_uj_per_admission": round(
                    statistics.median(r["derived_metrics"]["reported_l3_uj_per_admission"] for r in rcevc_sustained_runs), 3
                ),
                "median_instructions_per_admission": round(
                    statistics.median(r["derived_metrics"]["instructions_per_admission"] for r in rcevc_sustained_runs), 1
                ),
                "measured_j": None,
                "runs": rcevc_sustained_runs,
            },
        },
    }

    out_json = OUT_DIR / "step2_reported_j_receipts.json"
    out_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[Step 2] Wrote {out_json.name}")


if __name__ == "__main__":
    main()
