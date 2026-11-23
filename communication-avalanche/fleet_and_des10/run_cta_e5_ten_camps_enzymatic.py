#!/usr/bin/env python3
"""
CTA-E5 Hardware Benchmark Runner: The 10 Siloed AI Paradigm Camps vs.
Immediate Digital Enzymatic Synthesis (`DES-10`).

Executes on BOTH:
  1. `djc-asus-rog` (`13th Gen Intel Core i9-13900H`, Linux `powercap` `RAPL` `reported_j`)
  2. `NVIDIA Jetson AGX Thor` (`aarch64` Tegra Linux, `CUDA_VISIBLE_DEVICES=""` CPU-only,
     physical Texas Instruments `INA3221` `VDD_CPU_SOC_MSS` L2 & `INA238` `VIN` L1 `measured_j`)

Stages:
  - `populate-cache`: Populates deterministic `Claude Sonnet 5.5` response cache across the
    15 calibration probes + 100 test tasks (`C1`, `C9` 3-agent debate, and `DES-10` R5
    escalations) with strict in-memory API key handling and `< $1.90` spend circuit breaker.
  - `run-local-host`: Profiles `cost_lut_10camp.json` on the 15 held-out calibration probes
    (0 overlap with the 100 test tasks), measures the live Inter-Camp Handoff Activation
    Barrier (`Digital Enzyme` binary IR + Rust `BLAKE3+Ed25519` vs. `Camp 9` natural-language
    serialization + live `Claude Sonnet 5.5` re-parse), measures the 25-task (5/regime) live
    end-to-end HTTPS subset for `C1` / `C9` / `DES-10`, and executes the full 100-task x 11-arm
    benchmark (`1,100` episodes) in realistic mixed Zipfian stream order.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import threading
import time
from typing import Any

from cta_e5_camps_impl import (
    ALL_SOLO_CAMPS,
    BilinearEBMScorer,
    CachedSonnetClient,
    DES10CompositeEngine,
    EpisodicDeBruijnStore,
    RustEnzymeDaemon,
    pack_phi_ir,
    parse_llm_prediction,
    run_camp_solo,
)
from cta_e5_corpus import (
    corpus_sha256,
    evaluate_oracle,
    get_calibration_probes,
    get_public_corpus,
)

HERE = Path(__file__).resolve().parent
PREREG_PATH = HERE / "PREREG_cta_e4_e5.json"
RESULTS_DIR = HERE / "results"


# ============================================================================
# 1. Host Hardware Meter (Linux RAPL `reported_j` OR Jetson Thor INA `measured_j`)
# ============================================================================


class LocalHostEnergyMeter:
    """Strict separated hardware reader: either TI INA238/INA3221 shunts OR Linux RAPL."""

    def __init__(self) -> None:
        self.ina238: Path | None = None
        self.ina3221: Path | None = None
        hw = Path("/sys/class/hwmon")
        if hw.exists():
            for d in sorted(hw.iterdir()):
                try:
                    nm = (d / "name").read_text().strip()
                except Exception:
                    nm = ""
                if nm == "ina238" and (d / "power1_input").exists():
                    self.ina238 = d
                elif nm == "ina3221" and (d / "in2_input").exists():
                    self.ina3221 = d

        self.board_metered = self.ina238 is not None and self.ina3221 is not None
        self.rapl_pkg = Path("/sys/class/powercap/intel-rapl:0/energy_uj")
        self.rapl_core = Path("/sys/class/powercap/intel-rapl:0:0/energy_uj")
        self.rapl_psys = Path("/sys/class/powercap/intel-rapl:1/energy_uj")
        max_p = Path("/sys/class/powercap/intel-rapl:0/max_energy_range_uj")
        self.has_rapl = self.rapl_pkg.exists() and os.access(self.rapl_pkg, os.R_OK)
        self.max_uj = int(max_p.read_text().strip()) if max_p.exists() else 262_143_328_850

    @staticmethod
    def _ri(p: Path) -> int:
        try:
            return int(p.read_text().strip())
        except Exception:
            return 0

    def _read_shunt_w(self) -> tuple[float, float, float, float]:
        assert self.ina238 is not None and self.ina3221 is not None
        vin_w = self._ri(self.ina238 / "power1_input") / 1e6
        gpu_w = (self._ri(self.ina3221 / "in1_input") * self._ri(self.ina3221 / "curr1_input")) / 1e6
        cpu_w = (self._ri(self.ina3221 / "in2_input") * self._ri(self.ina3221 / "curr2_input")) / 1e6
        sys_w = (self._ri(self.ina3221 / "in3_input") * self._ri(self.ina3221 / "curr3_input")) / 1e6
        return vin_w, cpu_w, gpu_w, sys_w

    def measure_fn(self, fn: Any, min_duration_s: float = 0.0) -> tuple[Any, dict[str, Any]]:
        """Measures `fn()`, repeating deterministically if `min_duration_s > 0` for shunt/RAPL SNR."""
        stop_ev = threading.Event()
        shunt_trace: list[tuple[float, float, float, float, float]] = []
        t_origin = time.perf_counter()

        def sampler() -> None:
            while not stop_ev.is_set():
                ts = time.perf_counter() - t_origin
                vw, cw, gw, sw = self._read_shunt_w()
                shunt_trace.append((ts, vw, cw, gw, sw))
                time.sleep(0.005)  # 200 Hz physical shunt integration

        thr = threading.Thread(target=sampler, daemon=True) if self.board_metered else None
        if thr is not None:
            thr.start()

        pkg0 = self._ri(self.rapl_pkg) if self.has_rapl else 0
        core0 = self._ri(self.rapl_core) if self.has_rapl else 0
        psys0 = self._ri(self.rapl_psys) if self.has_rapl else 0
        pkg_acc = core_acc = psys_acc = 0

        def sample_rapl_step() -> None:
            nonlocal pkg0, core0, psys0, pkg_acc, core_acc, psys_acc
            if not self.has_rapl:
                return
            p1, c1, s1 = self._ri(self.rapl_pkg), self._ri(self.rapl_core), self._ri(self.rapl_psys)
            pkg_acc += (p1 - pkg0) if p1 >= pkg0 else (self.max_uj - pkg0 + p1)
            core_acc += (c1 - core0) if c1 >= core0 else (self.max_uj - core0 + c1)
            psys_acc += (s1 - psys0) if s1 >= psys0 else (self.max_uj - psys0 + s1)
            pkg0, core0, psys0 = p1, c1, s1

        t0 = time.perf_counter()
        reps = 0
        out = None
        try:
            while True:
                out = fn()
                reps += 1
                sample_rapl_step()
                if (time.perf_counter() - t0) >= min_duration_s:
                    break
        finally:
            wall_s = max(1e-9, time.perf_counter() - t0)
            stop_ev.set()
            if thr is not None:
                thr.join(timeout=0.5)

        per_rep_s = wall_s / reps
        tel: dict[str, Any] = {
            "board_metered": self.board_metered,
            "batch_reps": reps,
            "wall_s": round(per_rep_s, 6),
            "l1_vin_ina238_measured_j": None,
            "l2_vdd_cpu_soc_mss_measured_j": None,
            "l2_vdd_gpu_measured_j": None,
            "pkg_reported_j": None,
            "core_reported_j": None,
            "psys_reported_j": None,
        }
        if self.board_metered and shunt_trace:
            if len(shunt_trace) >= 2:
                ev = ec = eg = 0.0
                for i in range(len(shunt_trace) - 1):
                    dt = max(0.0, shunt_trace[i + 1][0] - shunt_trace[i][0])
                    ev += 0.5 * (shunt_trace[i][1] + shunt_trace[i + 1][1]) * dt
                    ec += 0.5 * (shunt_trace[i][2] + shunt_trace[i + 1][2]) * dt
                    eg += 0.5 * (shunt_trace[i][3] + shunt_trace[i + 1][3]) * dt
                head_dt = max(0.0, shunt_trace[0][0])
                tail_dt = max(0.0, wall_s - shunt_trace[-1][0])
                ev += shunt_trace[0][1] * head_dt + shunt_trace[-1][1] * tail_dt
                ec += shunt_trace[0][2] * head_dt + shunt_trace[-1][2] * tail_dt
                eg += shunt_trace[0][3] * head_dt + shunt_trace[-1][3] * tail_dt
            else:
                ev = shunt_trace[0][1] * wall_s
                ec = shunt_trace[0][2] * wall_s
                eg = shunt_trace[0][3] * wall_s
            tel["l1_vin_ina238_measured_j"] = round(ev / reps, 6)
            tel["l2_vdd_cpu_soc_mss_measured_j"] = round(ec / reps, 6)
            tel["l2_vdd_gpu_measured_j"] = round(eg / reps, 6)
        if self.has_rapl:
            tel["pkg_reported_j"] = round((pkg_acc / 1e6) / reps, 6)
            tel["core_reported_j"] = round((core_acc / 1e6) / reps, 6)
            tel["psys_reported_j"] = round((psys_acc / 1e6) / reps, 6)
        return out, tel

    def measure_idle_5s(self) -> dict[str, Any]:
        _, tel = self.measure_fn(lambda: time.sleep(5.0), min_duration_s=0.0)
        return tel



def build_realistic_stream_100(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Orders the 100 test tasks as a realistic mixed arrival stream: R2/R3/R4/R5 archetypes
    (including R3_01, R3_02, R5_01, R5_02) arrive before the 4 novel alpha-renamed R1_17..20
    recurrences so online downward crystallization (R3-R5 -> C5) is tested directly.
    """
    by_reg = {r: [t for t in tasks if t["regime"] == r] for r in ("R1", "R2", "R3", "R4", "R5")}
    stream: list[dict[str, Any]] = []
    # Wave 1..16: interleave R2, R3, R4, R5, and prior-seed R1_01..16
    for i in range(16):
        stream.append(by_reg["R2"][i])
        stream.append(by_reg["R3"][i])
        stream.append(by_reg["R4"][i])
        stream.append(by_reg["R5"][i])
        stream.append(by_reg["R1"][i])
    # Wave 17..20: remaining R2, R3, R4, R5 followed by crystallized recurrences R1_17..20
    for i in range(16, 20):
        stream.append(by_reg["R2"][i])
        stream.append(by_reg["R3"][i])
        stream.append(by_reg["R4"][i])
        stream.append(by_reg["R5"][i])
        stream.append(by_reg["R1"][i])
    assert len(stream) == 100
    return stream


def train_ebm_and_profile_lut(
    meter: LocalHostEnergyMeter,
    llm: CachedSonnetClient,
    host_id: str,
) -> tuple[BilinearEBMScorer, dict[str, Any]]:
    """Calibrates EBM + profiles all 10 camps on the 15 held-out calibration probes (0 test overlap)."""
    cal_probes = get_calibration_probes()
    ebm = BilinearEBMScorer()
    c5_cal = EpisodicDeBruijnStore(seed_prior=True)

    # Contrastive calibration on the 15 held-out probes using C5/C8/C7/C2/C1 positive witnesses
    cal_pairs = []
    for p in cal_probes:
        from cta_e5_camps_impl import _generate_candidate_pool_64

        negs = _generate_candidate_pool_64(p, seed_offset=5)[:8]
        # Obtain positive witness from exact specialist on calibration probe
        for cid in ("C5_Episodic_Case_Store_Solo", "C8_SubSymbolic_LUT_Automaton_Solo", "C7_Causal_Bayesian_DoCalc_Solo", "C2_Symbolic_Constraint_Solo", "C4_MCTS_Rollout_Search_Solo", "C1_Autoregressive_LLM_Solo"):
            ok, pred, _ = run_camp_solo(cid, p, llm, c5_cal, ebm)
            if ok and evaluate_oracle(p["task_id"], pred):
                cal_pairs.append((p["schema_ir"], pred, [n for n in negs if n != pred][:5]))
                break
    ebm.calibrate_contrastive(cal_pairs)

    profiles = []
    for cid in ALL_SOLO_CAMPS:
        is_llm = cid in ("C1_Autoregressive_LLM_Solo", "C9_MultiAgent_NL_Debate_Solo")

        def _run_cal(camp: str = cid) -> tuple[int, int, float]:
            passed = false_c = 0
            usd = 0.0
            for pr in cal_probes:
                ok, pred, meta = run_camp_solo(camp, pr, llm, c5_cal, ebm)
                usd += meta["cost_usd"]
                if ok:
                    if evaluate_oracle(pr["task_id"], pred):
                        passed += 1
                    else:
                        false_c += 1
            return passed, false_c, usd

        (passed, false_c, usd), tel = meter.measure_fn(_run_cal, min_duration_s=0.0 if is_llm else 0.35)
        n_p = len(cal_probes)
        primary_j = (
            tel["l2_vdd_cpu_soc_mss_measured_j"]
            if tel["board_metered"]
            else tel["pkg_reported_j"]
        ) or 0.001
        per_task_mj = (primary_j * 1000.0) / n_p
        # Include cloud cost weight for SSP routing when arm invokes remote frontier LLM
        ssp_uj = int(round(per_task_mj * 1000.0 + (usd / n_p) * 1.5e8))
        profiles.append({
            "camp_id": cid,
            "calibration_probes": n_p,
            "cal_pass_count": passed,
            "cal_false_commits": false_c,
            "cal_mean_latency_ms": round((tel["wall_s"] * 1000.0) / n_p, 4),
            "cal_vdd_cpu_soc_measured_mj_per_probe": (
                round((tel["l2_vdd_cpu_soc_mss_measured_j"] * 1000.0) / n_p, 4)
                if tel["l2_vdd_cpu_soc_mss_measured_j"] is not None
                else None
            ),
            "cal_pkg_reported_mj_per_probe": (
                round((tel["pkg_reported_j"] * 1000.0) / n_p, 4)
                if tel["pkg_reported_j"] is not None
                else None
            ),
            "cal_cloud_usd_per_probe": round(usd / n_p, 6),
            "ssp_cost_weight_uj": max(10, ssp_uj),
        })

    return ebm, {
        "host_id": host_id,
        "board_metered": meter.board_metered,
        "calibration_probes_total": len(cal_probes),
        "zero_test_overlap": True,
        "camp_profiles": profiles,
    }


def measure_handoff_barrier(
    meter: LocalHostEnergyMeter,
    rust_bin: Path,
    daemon: RustEnzymeDaemon,
    llm: CachedSonnetClient,
    sample_tasks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Measures Digital Enzyme binary IR + BLAKE3+Ed25519 handoff vs Camp 9 Live NL LLM handoff."""
    # 1. Native Rust in-process BLAKE3+Ed25519 1KiB verify (50,000 ops)
    import subprocess as sp

    crypto_raw = json.loads(sp.check_output([str(rust_bin), "bench-crypto", "--iters", "50000"], text=True))
    b1k = next(b for b in crypto_raw["buckets"] if b["payload_bytes"] == 1024)

    # 2. Cross-process Python->Rust Digital Enzyme binary IR pack + BLAKE3+Ed25519 sign+verify (4,000 ops)
    n_enz = 4000

    def _run_enz_pipe() -> None:
        for i in range(n_enz):
            ir_b = pack_phi_ir(1, 2, 10, {"step": i, "vec": [1, 4, 7, 2, 8], "gate": True})
            daemon.attest_ir("hb_bench", i, "C2", "verifier_gate", "enzyme_ir", ir_b)

    _, tel_enz = meter.measure_fn(_run_enz_pipe, min_duration_s=0.0)

    # 3. Live Camp 9 Natural-Language Serialization + 3-Hop LLM Debate Re-Parse Handoff (5 live chains)
    n_nl = 5
    nl_tokens = 0
    nl_usd = 0.0

    def _run_live_nl() -> None:
        nonlocal nl_tokens, nl_usd
        c5_dummy = EpisodicDeBruijnStore(seed_prior=True)
        ebm_dummy = BilinearEBMScorer()
        for i in range(n_nl):
            t = dict(sample_tasks[i % len(sample_tasks)])
            # Append live nonce so each trial performs genuine live HTTPS serialization + 3-hop NL re-parse
            t["prompt_nl"] = f"[Live Handoff Trial {i}] " + t["prompt_nl"]
            _, _, m9 = run_camp_solo("C9_MultiAgent_NL_Debate_Solo", t, llm, c5_dummy, ebm_dummy)
            nl_tokens += m9["input_tokens"] + m9["output_tokens"]
            nl_usd += m9["cost_usd"]

    _, tel_nl = meter.measure_fn(_run_live_nl, min_duration_s=0.0)

    enz_native_us = b1k["verify_p50_us"]
    enz_pipe_us = (tel_enz["wall_s"] * 1e6) / n_enz
    nl_hop_ms = (tel_nl["wall_s"] * 1000.0) / n_nl

    if meter.board_metered:
        enz_native_mj = (b1k["verify_vdd_cpu_soc_mss_measured_uj_per_edge"] or 0.0) / 1000.0
        enz_pipe_mj = (tel_enz["l2_vdd_cpu_soc_mss_measured_j"] * 1000.0) / n_enz
        nl_hop_j = tel_nl["l2_vdd_cpu_soc_mss_measured_j"] / n_nl
        nl_vin_j = tel_nl["l1_vin_ina238_measured_j"] / n_nl
    else:
        enz_native_mj = (b1k["verify_pkg_reported_uj_per_edge"] or 0.0) / 1000.0
        enz_pipe_mj = (tel_enz["pkg_reported_j"] * 1000.0) / n_enz
        nl_hop_j = tel_nl["pkg_reported_j"] / n_nl
        nl_vin_j = None

    return {
        "board_metered": meter.board_metered,
        "digital_enzyme_inproc_rust_1kib": {
            "verify_p50_us": round(enz_native_us, 3),
            "energy_mj_per_handoff": round(enz_native_mj, 5),
            "vin_measured_mj_per_handoff": (
                round((b1k["verify_vin_ina238_measured_uj_per_edge"] or 0.0) / 1000.0, 5)
                if meter.board_metered
                else None
            ),
        },
        "digital_enzyme_stdio_pipe_sign_and_verify": {
            "trials": n_enz,
            "mean_us_per_handoff": round(enz_pipe_us, 3),
            "energy_mj_per_handoff": round(enz_pipe_mj, 5),
        },
        "camp9_natural_language_live_llm_handoff": {
            "live_trials": n_nl,
            "mean_ms_per_handoff": round(nl_hop_ms, 2),
            "local_energy_j_per_handoff": round(nl_hop_j, 4),
            "vin_measured_j_per_handoff": round(nl_vin_j, 4) if nl_vin_j is not None else None,
            "mean_tokens_per_handoff": round(nl_tokens / n_nl, 1),
            "mean_usd_per_handoff": round(nl_usd / n_nl, 6),
        },
        "activation_barrier_reduction_ratios": {
            "latency_speedup_inproc_vs_nl": round((nl_hop_ms * 1000.0) / max(1e-6, enz_native_us), 1),
            "latency_speedup_pipe_vs_nl": round((nl_hop_ms * 1000.0) / max(1e-6, enz_pipe_us), 1),
            "local_energy_ratio_inproc_vs_nl": round((nl_hop_j * 1000.0) / max(1e-6, enz_native_mj), 1),
            "local_energy_ratio_pipe_vs_nl": round((nl_hop_j * 1000.0) / max(1e-6, enz_pipe_mj), 1),
        },
    }



def populate_all_llm_caches(llm: CachedSonnetClient, rust_bin: Path) -> dict[str, Any]:
    """Populates exact Claude Sonnet 5.5 responses for 15 cal probes + 100 test tasks (C1, C9, DES-10)."""
    cal_probes = get_calibration_probes()
    test_tasks = build_realistic_stream_100(get_public_corpus())
    c5_tmp = EpisodicDeBruijnStore(seed_prior=True)
    ebm_tmp = BilinearEBMScorer()

    def _pop_one(t: dict[str, Any]) -> None:
        run_camp_solo("C1_Autoregressive_LLM_Solo", t, llm, c5_tmp, ebm_tmp)
        run_camp_solo("C9_MultiAgent_NL_Debate_Solo", t, llm, c5_tmp, ebm_tmp)

    all_items = cal_probes + test_tasks
    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(_pop_one, all_items))
    llm.save_cache()

    # Run DES-10 once to ensure any 1st/2nd-turn R5 repair prompts are also cached
    dummy_lut = {"camp_profiles": [{"camp_id": c, "ssp_cost_weight_uj": 100} for c in ALL_SOLO_CAMPS]}
    daemon = RustEnzymeDaemon(rust_bin)
    try:
        des = DES10CompositeEngine(daemon, llm, ebm_tmp, dummy_lut)
        for t in test_tasks:
            des.solve_task(t)
    finally:
        daemon.close()
    llm.save_cache()
    return {"cached_entries": len(llm.cache), "live_spend_usd": round(llm.live_spend_usd, 4)}


def run_local_host_e5(
    host_id: str,
    rust_bin: Path,
    llm: CachedSonnetClient,
) -> tuple[dict[str, Any], dict[str, Any]]:
    meter = LocalHostEnergyMeter()
    pre_idle = meter.measure_idle_5s()
    ebm, cost_lut = train_ebm_and_profile_lut(meter, llm, host_id)

    stream_100 = build_realistic_stream_100(get_public_corpus())
    daemon = RustEnzymeDaemon(rust_bin)
    try:
        barrier = measure_handoff_barrier(meter, rust_bin, daemon, llm, stream_100[:8])
        per_live_call_j = barrier["camp9_natural_language_live_llm_handoff"]["local_energy_j_per_handoff"]
        per_live_call_vin_j = barrier["camp9_natural_language_live_llm_handoff"]["vin_measured_j_per_handoff"]

        arms_out: dict[str, Any] = {}
        all_arms = ALL_SOLO_CAMPS + ["DES10_Digital_Enzymatic_Composite"]

        for arm_id in all_arms:
            print(f"[CTA-E5 {host_id}] Running {arm_id} across 100 tasks...", file=sys.stderr, flush=True)

            def _exec_100(aid: str = arm_id) -> dict[str, Any]:
                c5_solo = EpisodicDeBruijnStore(seed_prior=True)
                des_eng = DES10CompositeEngine(daemon, llm, ebm, cost_lut) if aid.startswith("DES10") else None
                per_reg = {r: {"pass": 0, "false_commit": 0, "refused": 0, "llm_calls": 0} for r in ("R1", "R2", "R3", "R4", "R5")}
                tot_calls = tot_in = tot_out = 0
                tot_usd = 0.0
                hop_sums = [0, 0, 0]
                hop_cnt = 0
                for t in stream_100:
                    if des_eng is not None:
                        ok, pred, meta = des_eng.solve_task(t)
                    else:
                        ok, pred, meta = run_camp_solo(aid, t, llm, c5_solo, ebm)
                    rg = t["regime"]
                    tot_calls += meta["llm_calls"]
                    tot_in += meta["input_tokens"]
                    tot_out += meta["output_tokens"]
                    tot_usd += meta["cost_usd"]
                    per_reg[rg]["llm_calls"] += meta["llm_calls"]
                    if "hop_input_tokens" in meta:
                        for h_i in range(3):
                            hop_sums[h_i] += meta["hop_input_tokens"][h_i]
                        hop_cnt += 1
                    if ok:
                        if evaluate_oracle(t["task_id"], pred):
                            per_reg[rg]["pass"] += 1
                        else:
                            per_reg[rg]["false_commit"] += 1
                    else:
                        per_reg[rg]["refused"] += 1
                return {
                    "per_regime": per_reg,
                    "llm_calls": tot_calls,
                    "input_tokens": tot_in,
                    "output_tokens": tot_out,
                    "total_tokens": tot_in + tot_out,
                    "cloud_cost_usd": round(tot_usd, 4),
                    "c9_mean_hop_input_tokens": [round(s / hop_cnt, 1) for s in hop_sums] if hop_cnt else None,
                    "des10_crystallized_schemas": des_eng.crystallized_count if des_eng else 0,
                    "des10_enzyme_receipts": len(des_eng.enzyme_receipts) if des_eng else 0,
                    "des10_ssp_epoch0_ns": des_eng.ssp_epoch0["solve_ns"] if des_eng else None,
                }

            res_data, tel = meter.measure_fn(_exec_100, min_duration_s=0.80)
            tot_pass = sum(v["pass"] for v in res_data["per_regime"].values())
            tot_fc = sum(v["false_commit"] for v in res_data["per_regime"].values())
            tot_ref = sum(v["refused"] for v in res_data["per_regime"].values())

            if meter.board_metered:
                loc_j = tel["l2_vdd_cpu_soc_mss_measured_j"]
                loc_vin_j = tel["l1_vin_ina238_measured_j"]
                e2e_j = loc_j + res_data["llm_calls"] * per_live_call_j
                e2e_vin_j = loc_vin_j + res_data["llm_calls"] * (per_live_call_vin_j or 0.0)
                energy_block = {
                    "board_metered": True,
                    "local_compute_vdd_cpu_soc_measured_j": round(loc_j, 5),
                    "local_compute_vin_ina238_measured_j": round(loc_vin_j, 5),
                    "end_to_end_vdd_cpu_soc_measured_j": round(e2e_j, 4),
                    "end_to_end_vin_ina238_measured_j": round(e2e_vin_j, 4),
                    "pkg_reported_j": None,
                    "core_reported_j": None,
                    "cpj_local_compute_tasks_per_j": round(tot_pass / max(1e-6, loc_j), 4),
                    "cpj_end_to_end_tasks_per_j": round(tot_pass / max(1e-6, e2e_j), 4),
                }
            else:
                loc_j = tel["pkg_reported_j"]
                loc_core_j = tel["core_reported_j"]
                e2e_j = loc_j + res_data["llm_calls"] * per_live_call_j
                energy_block = {
                    "board_metered": False,
                    "local_compute_vdd_cpu_soc_measured_j": None,
                    "local_compute_vin_ina238_measured_j": None,
                    "pkg_reported_j": round(loc_j, 5),
                    "core_reported_j": round(loc_core_j, 5),
                    "psys_reported_j": round(tel["psys_reported_j"], 5),
                    "end_to_end_pkg_reported_j": round(e2e_j, 4),
                    "cpj_local_compute_tasks_per_j": round(tot_pass / max(1e-6, loc_j), 4),
                    "cpj_end_to_end_tasks_per_j": round(tot_pass / max(1e-6, e2e_j), 4),
                }

            arms_out[arm_id] = {
                "verified_pass_count": tot_pass,
                "verified_pass_pct": round(tot_pass, 2),
                "false_commit_count": tot_fc,
                "false_commit_pct": round(tot_fc, 2),
                "refused_count": tot_ref,
                "local_wall_s": round(tel["wall_s"], 5),
                **res_data,
                "hardware_energy": energy_block,
            }
    finally:
        daemon.close()

    post_idle = meter.measure_idle_5s()
    gpu_lock = Path.home().joinpath("gpu-lock/GPU_ACTIVE").exists()
    p_field = "l2_vdd_cpu_soc_mss_measured_j" if meter.board_metered else "pkg_reported_j"
    w_pre = (pre_idle[p_field] or 0.0) / max(1e-6, pre_idle["wall_s"])
    w_post = (post_idle[p_field] or 0.0) / max(1e-6, post_idle["wall_s"])
    drift = abs(w_post - w_pre) / max(1e-6, w_pre) * 100.0

    host_matrix = {
        "host_id": host_id,
        "board_metered": meter.board_metered,
        "gpu_cotenant_lock_active": gpu_lock,
        "falsifier_6_audit": {
            "pre_idle_5s_w": round(w_pre, 4),
            "post_idle_5s_w": round(w_post, 4),
            "idle_drift_pct": round(drift, 2),
            "withhold_net_idle_subtraction": gpu_lock or (drift > 10.0),
        },
        "handoff_activation_barrier": barrier,
        "arms": arms_out,
    }
    return cost_lut, host_matrix


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["populate-cache", "run-local-host", "merge-hosts"], required=True)
    ap.add_argument("--host-id", default="linux_host")
    ap.add_argument("--rust-bin", type=Path, default=Path("cta_fleet_rust"))
    ap.add_argument("--cache-path", type=Path, default=RESULTS_DIR / "llm_cache_sonnet55.json")
    ap.add_argument("--out-lut", type=Path, default=RESULTS_DIR / "cost_lut_10camp.json")
    ap.add_argument("--out-matrix", type=Path, default=RESULTS_DIR / "cta_e5_ten_camps_matrix.json")
    ap.add_argument("--rog-json", type=Path)
    ap.add_argument("--thor-json", type=Path)
    ap.add_argument("--stdin-keys", action="store_true")
    args = ap.parse_args()

    keys: dict[str, str] = {}
    if args.stdin_keys:
        raw = sys.stdin.read().strip()
        if raw:
            keys.update(json.loads(raw))
    for k in ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "CEREBRAS_API_KEY"):
        if os.environ.get(k):
            keys.setdefault(k, os.environ[k])

    if args.mode == "populate-cache":
        llm = CachedSonnetClient(keys, args.cache_path)
        info = populate_all_llm_caches(llm, args.rust_bin)
        print(json.dumps(info))
        return

    if args.mode == "run-local-host":
        llm = CachedSonnetClient(keys, args.cache_path)
        lut, mat = run_local_host_e5(args.host_id, args.rust_bin, llm)
        llm.save_cache()
        args.out_lut.parent.mkdir(parents=True, exist_ok=True)
        args.out_lut.write_text(json.dumps(lut, indent=2) + "\n", encoding="utf-8")
        args.out_matrix.write_text(json.dumps(mat, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"host_id": args.host_id, "live_spend_usd": round(llm.live_spend_usd, 4)}))
        return

    if args.mode == "merge-hosts":
        prereg_sha = hashlib.sha256(PREREG_PATH.read_bytes()).hexdigest()
        rog = json.loads(args.rog_json.read_text(encoding="utf-8"))
        thor = json.loads(args.thor_json.read_text(encoding="utf-8"))
        merged = {
            "experiment": "CTA-E5",
            "title": "The 10 Siloed AI Paradigm Camps vs. Immediate Digital Enzymatic Synthesis (DES-10)",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "prereg_sha256": prereg_sha,
            "corpus_100_test_15_cal_sha256": corpus_sha256(),
            "strict_separation_policy": (
                "Intel i9-13900H RAPL reported_j, NVIDIA Jetson AGX Thor TI INA3221/INA238 physical shunt "
                "measured_j (CPU-only, GPU_ACTIVE respected), and remote Claude Sonnet 5.5 tokens/USD are "
                "reported in strictly separate columns and never summed."
            ),
            "hosts": {
                "intel_i9_13900h_rapl_reported_j": rog,
                "jetson_agx_thor_ina_shunt_measured_j": thor,
            },
        }
        args.out_matrix.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
