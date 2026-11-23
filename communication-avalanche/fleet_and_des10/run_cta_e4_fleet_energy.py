#!/usr/bin/env python3
"""
CTA-E4: 5-Host Cross-Silicon & Cross-OS Fleet Energy Audit Runner.

Executes compiled Rust `cta_fleet_rust` (`bench-crypto` 50,000 iterations at 64B / 1KiB /
16KiB / 64KiB + `bench-e4-dag` 16-node zero-clock OS-event threshold vs. 1,000 Hz clocked
polling across 4 counterbalanced 5.0 s interleaved pairs at 1% bursty duty) across 5 hosts:
  1. NVIDIA Jetson AGX Thor (aarch64 Tegra Linux, CPU-only, TI INA238 VIN + INA3221 VDD_CPU_SOC_MSS measured_j)
  2. Intel Core i9-13900H (x86_64 Raptor Lake Linux, powercap intel-rapl package-0 & core reported_j)
  3. AMD Ryzen AI Max+ 395 (x86_64 Zen 5 Strix Halo Linux, intel-rapl package-0 & core + amdgpu PPT reported_j)
  4. Apple M3 Ultra (arm64 Darwin macOS under memguard, proc_pid_rusage RUSAGE_INFO_V6 ri_energy_nj L3 reported_j)
  5. Windows 11 Pro x86-64 + RTX 2060 (Win32 Event vs 1 kHz HighRes Timer, rootless nvml.dll mJ L2 reported_j & L3 cycles)

Strict separation rule: `measured_j` (physical board/rail shunts) and `reported_j` (RAPL /
Darwin CLPC / NVML) are reported in separate columns and NEVER summed across classes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
RUST_SRC_DIR = HERE / "cta_fleet_rust"
PREREG_PATH = HERE / "PREREG_cta_e4_e5.json"
RESULTS_DIR = HERE / "results"


def ssh_run(target: str, remote_cmd: str, timeout: int = 300) -> str:
    cp = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "GSSAPIAuthentication=no",
            "-o",
            "ConnectTimeout=12",
            target,
            remote_cmd,
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return cp.stdout


def scp_to(local_files: list[Path], target: str, remote_dest: str) -> None:
    subprocess.run(
        [
            "scp",
            "-q",
            "-o",
            "BatchMode=yes",
            "-o",
            "GSSAPIAuthentication=no",
            *[str(f) for f in local_files],
            f"{target}:{remote_dest}",
        ],
        check=True,
        timeout=120,
    )


def summarize_host_e4(
    host_id: str,
    label: str,
    arch_os: str,
    primary_rail_kind: str,
    primary_rail_field: str,
    crypto_json: dict[str, Any],
    dag_json: dict[str, Any],
    extra_meta: dict[str, Any],
) -> dict[str, Any]:
    buckets_by_sz = {int(b["payload_bytes"]): b for b in crypto_json["buckets"]}
    b_1k = buckets_by_sz[1024]
    b_16k = buckets_by_sz[16384]

    wins = dag_json["windows"]
    ev_wins = sorted([w for w in wins if w["regime"] == "event_threshold"], key=lambda x: x["pair_idx"])
    pl_wins = sorted([w for w in wins if w["regime"] == "poll_1000hz"], key=lambda x: x["pair_idx"])

    def get_rail(w: dict[str, Any], field: str) -> float | None:
        v = w["telemetry"].get(field)
        return float(v) if v is not None else None

    paired_deltas: list[float] = []
    ev_vals: list[float] = []
    pl_vals: list[float] = []
    for ew, pw in zip(ev_wins, pl_wins):
        ve = get_rail(ew, primary_rail_field)
        vp = get_rail(pw, primary_rail_field)
        if ve is not None and vp is not None:
            ev_vals.append(ve)
            pl_vals.append(vp)
            paired_deltas.append(round(vp - ve, 4))

    # Secondary rail on Thor (INA238 whole-board VIN) or Core RAPL on x86
    sec_field = (
        "l1_vin_ina238_measured_j"
        if host_id == "jetson_agx_thor"
        else ("core_reported_j" if "rapl" in primary_rail_kind else None)
    )
    sec_ev = [get_rail(w, sec_field) for w in ev_wins] if sec_field else []
    sec_pl = [get_rail(w, sec_field) for w in pl_wins] if sec_field else []
    sec_paired = (
        [round(p - e, 4) for e, p in zip(sec_ev, sec_pl) if e is not None and p is not None]
        if sec_field
        else []
    )

    pre_idle = dag_json["pre_idle_5s"]
    post_idle = dag_json["post_idle_5s"]
    pre_v = pre_idle.get(primary_rail_field)
    post_v = post_idle.get(primary_rail_field)
    pre_w = (pre_v / max(1e-6, pre_idle["elapsed_s"])) if pre_v is not None else None
    post_w = (post_v / max(1e-6, post_idle["elapsed_s"])) if post_v is not None else None
    drift_pct = (
        abs(post_w - pre_w) / max(1e-6, pre_w) * 100.0
        if (pre_w is not None and post_w is not None and pre_w > 1e-6)
        else 0.0
    )
    cotenant_active = bool(extra_meta.get("gpu_cotenant_lock_active", False))
    withhold_a2_net = cotenant_active or (drift_pct > 10.0)

    ev_mean_s = statistics.mean(w["window_s"] for w in ev_wins)
    pl_mean_s = statistics.mean(w["window_s"] for w in pl_wins)

    return {
        "host_id": host_id,
        "host_label": label,
        "arch_os": arch_os,
        "board_metered": bool(crypto_json["board_metered"]),
        "os_event_mechanism": dag_json["os_event_mechanism"],
        "telemetry_grammar": primary_rail_kind,
        "primary_rail_field": primary_rail_field,
        "host_metadata": extra_meta,
        "falsifier_6_audit": {
            "pre_idle_5s_mean_w": round(pre_w, 4) if pre_w is not None else None,
            "post_idle_5s_mean_w": round(post_w, 4) if post_w is not None else None,
            "idle_drift_pct": round(drift_pct, 2),
            "gpu_cotenant_lock_active": cotenant_active,
            "withhold_single_window_net_subtraction": withhold_a2_net,
            "disclosure": (
                "Shared-host co-tenant or >10% thermal/idle drift: A2 single-window net idle subtraction withheld; "
                "raw unsubtracted rails and counterbalanced within-pair (poll_1000hz - event_threshold) deltas reported."
                if withhold_a2_net
                else "Dedicated quiet host within <=10% pre/post idle drift."
            ),
        },
        "crypto_attestation_50k": {
            "1KiB": b_1k,
            "16KiB": b_16k,
            "all_buckets": crypto_json["buckets"],
        },
        "dag_16node_5s_x4_pairs_1pct_duty": {
            "event_threshold_mean_primary": round(statistics.mean(ev_vals), 4) if ev_vals else None,
            "poll_1000hz_mean_primary": round(statistics.mean(pl_vals), 4) if pl_vals else None,
            "event_threshold_mean_primary_w": round(statistics.mean(ev_vals) / ev_mean_s, 4) if ev_vals else None,
            "poll_1000hz_mean_primary_w": round(statistics.mean(pl_vals) / pl_mean_s, 4) if pl_vals else None,
            "paired_poll_minus_event_primary_deltas": paired_deltas,
            "paired_poll_minus_event_primary_mean": round(statistics.mean(paired_deltas), 4) if paired_deltas else None,
            "secondary_rail_field": sec_field,
            "event_threshold_mean_secondary": (
                round(statistics.mean([x for x in sec_ev if x is not None]), 4)
                if any(x is not None for x in sec_ev)
                else None
            ),
            "poll_1000hz_mean_secondary": (
                round(statistics.mean([x for x in sec_pl if x is not None]), 4)
                if any(x is not None for x in sec_pl)
                else None
            ),
            "paired_poll_minus_event_secondary_deltas": sec_paired,
            "event_threshold_mean_wakeups": round(statistics.mean(w["node_wakeups"] for w in ev_wins), 1),
            "poll_1000hz_mean_wakeups": round(statistics.mean(w["node_wakeups"] for w in pl_wins), 1),
            "event_threshold_mean_empty_polls": round(statistics.mean(w["empty_polling_wakeups"] for w in ev_wins), 1),
            "poll_1000hz_mean_empty_polls": round(statistics.mean(w["empty_polling_wakeups"] for w in pl_wins), 1),
            "event_threshold_mean_cpu_ms": round(statistics.mean(w["telemetry"]["cpu_time_ms"] for w in ev_wins), 2),
            "poll_1000hz_mean_cpu_ms": round(statistics.mean(w["telemetry"]["cpu_time_ms"] for w in pl_wins), 2),
            "event_threshold_p50_ms": round(statistics.mean(w["latency_p50_ms"] for w in ev_wins), 3),
            "poll_1000hz_p50_ms": round(statistics.mean(w["latency_p50_ms"] for w in pl_wins), 3),
            "raw_pre_idle_5s": pre_idle,
            "raw_post_idle_5s": post_idle,
            "raw_windows": wins,
        },
    }


def run_posix_host(cfg: dict[str, Any]) -> dict[str, Any]:
    hid = cfg["host_id"]
    target = cfg["ssh"]
    wdir = cfg["work_dir"]
    wrap = cfg.get("wrap_prefix", "")
    env_pre = cfg.get("env_prefix", "")
    print(f"[CTA-E4] Starting {hid} ...", file=sys.stderr, flush=True)

    ssh_run(target, f"mkdir -p {wdir}/src {wdir}/tmp")
    try:
        scp_to([RUST_SRC_DIR / "Cargo.toml"], target, f"{wdir}/Cargo.toml")
        scp_to(
            [RUST_SRC_DIR / "src/main.rs", RUST_SRC_DIR / "src/telemetry.rs"],
            target,
            f"{wdir}/src/",
        )
        build_cmd = (
            f"{env_pre} PATH=\"$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH\" "
            f"{wrap} cargo build --release --manifest-path {wdir}/Cargo.toml"
        )
        ssh_run(target, build_cmd, timeout=420)
        bin_p = f"{wdir}/target/release/cta_fleet_rust"
        if cfg.get("cargo_target_dir"):
            bin_p = f"{cfg['cargo_target_dir']}/release/cta_fleet_rust"

        meta_out = ssh_run(
            target,
            f'{env_pre} python3 -c \'import json, os, platform; '
            f'lk = os.path.exists(os.path.expanduser("~/gpu-lock/GPU_ACTIVE")); '
            f'print(json.dumps({{"kernel": platform.release(), "arch": platform.machine(), '
            f'"cpus": os.cpu_count(), "gpu_cotenant_lock_active": lk}}))\'',
        )
        extra_meta = json.loads(meta_out.strip().splitlines()[-1])
        crypto_raw = ssh_run(target, f"{env_pre} {wrap} {bin_p} bench-crypto --iters 50000", timeout=240)
        dag_raw = ssh_run(target, f"{env_pre} {wrap} {bin_p} bench-e4-dag --window-s 5.0 --pairs 4", timeout=300)
        print(f"[CTA-E4] Completed {hid}.", file=sys.stderr, flush=True)
        return summarize_host_e4(
            hid,
            cfg["label"],
            cfg["arch_os"],
            cfg["rail_kind"],
            cfg["primary_field"],
            json.loads(crypto_raw),
            json.loads(dag_raw),
            extra_meta,
        )
    finally:
        if not cfg.get("keep_remote_bin", False):
            ssh_run(target, f"rm -rf {wdir}", timeout=60)


def run_windows_host(cfg: dict[str, Any]) -> dict[str, Any]:
    hid = cfg["host_id"]
    target = cfg["ssh"]
    print(f"[CTA-E4] Starting {hid} (Windows 11) ...", file=sys.stderr, flush=True)
    ssh_run(target, 'powershell -NoProfile -Command "New-Item -ItemType Directory -Force -Path $env:TEMP\\wave5b_cta\\src | Out-Null"')
    win_tmp = ssh_run(target, 'powershell -NoProfile -Command "(Resolve-Path $env:TEMP\\wave5b_cta).Path"').strip().replace("\\", "/")
    try:
        scp_to([RUST_SRC_DIR / "Cargo.toml"], target, f"{win_tmp}/Cargo.toml")
        scp_to([RUST_SRC_DIR / "src/main.rs", RUST_SRC_DIR / "src/telemetry.rs"], target, f"{win_tmp}/src/")
        ssh_run(
            target,
            'powershell -NoProfile -Command "$w = Join-Path $env:TEMP \'wave5b_cta\'; cargo build --release --manifest-path (Join-Path $w \'Cargo.toml\')"',
            timeout=420,
        )
        crypto_raw = ssh_run(
            target,
            'powershell -NoProfile -Command "& (Join-Path $env:TEMP \'wave5b_cta\\target\\release\\cta_fleet_rust.exe\') bench-crypto --iters 50000"',
            timeout=240,
        )
        dag_raw = ssh_run(
            target,
            'powershell -NoProfile -Command "& (Join-Path $env:TEMP \'wave5b_cta\\target\\release\\cta_fleet_rust.exe\') bench-e4-dag --window-s 5.0 --pairs 4"',
            timeout=300,
        )
        extra_meta = {
            "os_build": "Windows 11 Pro x86-64 (NT 10.0.26300)",
            "gpu_device": "NVIDIA GeForce RTX 2060 (rootless nvml.dll cumulative mJ L2)",
            "cpu_rapl_rootless": "not_exposed_rootless_on_win11 (QueryProcessCycleTime L3 + NVML mJ L2 recorded)",
            "gpu_cotenant_lock_active": False,
        }
        print(f"[CTA-E4] Completed {hid}.", file=sys.stderr, flush=True)
        return summarize_host_e4(
            hid,
            cfg["label"],
            cfg["arch_os"],
            cfg["rail_kind"],
            cfg["primary_field"],
            json.loads(crypto_raw),
            json.loads(dag_raw),
            extra_meta,
        )
    finally:
        ssh_run(target, 'powershell -NoProfile -Command "Remove-Item -Recurse -Force $env:TEMP\\wave5b_cta -ErrorAction SilentlyContinue"', timeout=60)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--thor-ssh", default=os.environ.get("CTA_THOR_SSH", ""))
    ap.add_argument("--rog-ssh", default=os.environ.get("CTA_ROG_SSH", ""))
    ap.add_argument("--zen5-ssh", default=os.environ.get("CTA_ZEN5_SSH", ""))
    ap.add_argument("--m3-ssh", default=os.environ.get("CTA_M3_SSH", ""))
    ap.add_argument("--win-ssh", default=os.environ.get("CTA_WIN_SSH", ""))
    ap.add_argument("--keep-e5-bins", action="store_true")
    args = ap.parse_args()

    if not PREREG_PATH.exists():
        raise RuntimeError(f"Pre-registration lock missing: {PREREG_PATH}")
    prereg_sha = hashlib.sha256(PREREG_PATH.read_bytes()).hexdigest()

    m3_wdir = "/Volumes/macos_4TB_external_1/tmp_wave5b_cta"
    posix_hosts = [
        {
            "host_id": "jetson_agx_thor",
            "label": "NVIDIA Jetson AGX Thor (aarch64 Tegra Linux, CPU-Only)",
            "arch_os": "aarch64 Linux 6.8-tegra",
            "ssh": args.thor_ssh,
            "work_dir": "/tmp/wave5b_cta_e4",
            "env_prefix": 'CUDA_VISIBLE_DEVICES=""',
            "rail_kind": "measured_j (TI INA3221 ch2 VDD_CPU_SOC_MSS L2 & INA238 VIN L1 physical shunts)",
            "primary_field": "l2_vdd_cpu_soc_mss_measured_j",
            "keep_remote_bin": args.keep_e5_bins,
        },
        {
            "host_id": "intel_i9_13900h",
            "label": "13th Gen Intel Core i9-13900H (20t Raptor Lake Linux)",
            "arch_os": "x86_64 Linux 7.0",
            "ssh": args.rog_ssh,
            "work_dir": "/var/tmp/wave5b_cta_e4",
            "env_prefix": 'TMPDIR="/var/tmp/wave5b_cta_e4/tmp"',
            "rail_kind": "reported_j (Linux powercap intel-rapl:0 package-0 & intel-rapl:0:0 core)",
            "primary_field": "pkg_reported_j",
            "keep_remote_bin": args.keep_e5_bins,
        },
        {
            "host_id": "amd_ryzen_ai_max_395",
            "label": "AMD Ryzen AI Max+ 395 (32t Zen 5 Strix Halo + Radeon 8060S)",
            "arch_os": "x86_64 Linux 7.0",
            "ssh": args.zen5_ssh,
            "work_dir": "/tmp/wave5b_cta_e4",
            "env_prefix": "",
            "rail_kind": "reported_j (Linux powercap intel-rapl:0 APU package + intel-rapl:0:0 core + amdgpu PPT)",
            "primary_field": "pkg_reported_j",
            "keep_remote_bin": False,
        },
        {
            "host_id": "apple_m3_ultra",
            "label": "Apple M3 Ultra (arm64 macOS Darwin XNU)",
            "arch_os": "arm64 Darwin 27.2.0",
            "ssh": args.m3_ssh,
            "work_dir": m3_wdir,
            "cargo_target_dir": f"{m3_wdir}/target",
            "env_prefix": f'CARGO_TARGET_DIR="{m3_wdir}/target" CARGO_HOME="{m3_wdir}/cargo_home"',
            "wrap_prefix": "/Volumes/macos_4TB_external_1/wai-build/bin/memguard --max-gb 16 --",
            "rail_kind": "reported_j (Darwin proc_pid_rusage RUSAGE_INFO_V6 ri_energy_nj L3 per-process)",
            "primary_field": "darwin_ri_energy_reported_j",
            "keep_remote_bin": False,
        },
    ]
    win_host = {
        "host_id": "win11_rtx2060",
        "label": "Windows 11 Pro x86-64 Bare-Metal + NVIDIA RTX 2060",
        "arch_os": "x86_64 Windows 11 NT 10.0.26300",
        "ssh": args.win_ssh,
        "rail_kind": "reported_j (Rootless nvml.dll RTX 2060 cumulative mJ L2 + QueryProcessCycleTime L3)",
        "primary_field": "win_nvml_gpu_reported_j",
    }

    t0 = time.perf_counter()
    results_by_id: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = {ex.submit(run_posix_host, cfg): cfg["host_id"] for cfg in posix_hosts}
        futs[ex.submit(run_windows_host, win_host)] = win_host["host_id"]
        for fut in as_completed(futs):
            hid = futs[fut]
            results_by_id[hid] = fut.result()

    ordered_ids = [
        "jetson_agx_thor",
        "intel_i9_13900h",
        "amd_ryzen_ai_max_395",
        "apple_m3_ultra",
        "win11_rtx2060",
    ]
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_obj = {
        "experiment": "CTA-E4",
        "title": "5-Host Cross-Silicon & Cross-OS Fleet Energy Audit",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "prereg_sha256": prereg_sha,
        "elapsed_wall_s": round(time.perf_counter() - t0, 2),
        "strict_separation_policy": (
            "measured_j (NVIDIA Jetson AGX Thor TI INA238 VIN L1 & INA3221 VDD_CPU_SOC_MSS L2 physical shunts) "
            "and reported_j (Intel/AMD RAPL, Apple Darwin ri_energy_nj, Windows NVML mJ) are kept strictly "
            "separate and never summed."
        ),
        "hosts": [results_by_id[k] for k in ordered_ids],
    }
    out_path = RESULTS_DIR / "cta_e4_five_host_energy.json"
    out_path.write_text(json.dumps(out_obj, indent=2) + "\n", encoding="utf-8")
    print(f"[CTA-E4] Wrote {out_path} in {out_obj['elapsed_wall_s']} s.", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
