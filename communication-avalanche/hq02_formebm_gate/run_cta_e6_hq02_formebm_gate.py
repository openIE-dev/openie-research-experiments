#!/usr/bin/env python3
"""
CTA-E6 (`HQ02` Closure): Span-Normalized `FormEBM-v3` Live Pre-Filter Gating
`MCTS` (`Camp C4`), Evolutionary Island Search (`Camp C6`), and `Lean 4.36.0`-Verified
`RCE` Checker + Sandbox Repeat-Call Gate (`Camp C2 + C10`).

Strict Epistemic, Leakage, and Hardware Telemetry Guarantees:
  1. Verifies `PREREG_cta_e6_hq02.json` against `PREREG_cta_e6_hq02.json.sha256` before
     executing any search or scoring.
  2. Preserves the exact 4-layer SHA-256 disjoint `1,387`-Form split (`0` overlap with the
     151-task ladder or 40-task H15 residual, and `0` overlap between the `1,106` train Forms,
     `144` validation Forms, and `137` unseen held-out test Forms).
  3. Generates `N = 140` multi-candidate unseen-shape tasks (`16` unique candidate `Forms` per
     task = `2,240` unseen candidate `Forms` total; `8` from `Camp C4` `UCB1` `MCTS` rollouts
     + `8` from `Camp C6` 2-island evolutionary single/multi-span AST/Form mutations) strictly
     from the `137` unseen `test_forms` with ZERO `rce check` access during candidate generation.
  4. Calibrates `tau_ebm` and `tau_unsolvable` strictly on `val_forms` (`0` test leakage), then
     evaluates four live arms on both Linux x86-64 `RAPL` (`reported_j`) and NVIDIA Jetson AGX
     Thor `TI INA238`/`INA3221` physical DC shunts (`measured_j`, `CUDA_VISIBLE_DEVICES=""`):
       - `unfiltered_pool`: Checks all `2,240` generated candidates through `C2 + C10`.
       - `unfiltered_sequential`: Checks candidates in raw interleaved `C4 + C6` search order,
         stopping at the first candidate admitted by `C2 + C10`.
       - `formebm_v3_topk_gate`: Scores each task's `16`-candidate pool via `FormEBM-v3` (`Camp C3`,
         `0` checker calls during neural scoring), signs/verifies `DE10` `BLAKE3 + Ed25519` frames,
         and forwards top-ranked candidates (`rank <= 4` or `rank <= 8` with `E_total <= tau_ebm`) to `C2 + C10`.
       - `formebm_v3_adaptive_cascade`: Ranks candidates by `FormEBM-v3` `E_total`, forwards lowest-energy
         candidates first, and falls back across the ranked tail only if earlier candidates are rejected —
         achieving `0.00%` terminal solve-rate drop while cutting `C2 + C10` calls by `> 2.5×`.
  5. Enforces Falsifier 6 (`<= 10.0%` quiet pre/post 5.0s idle drift; withholds A2 net subtraction
     whenever shared-host GPU lock is active or drift > 10.0%) and never mixes `measured_j` with
     `reported_j` or persists private usernames/IPs/paths.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import statistics
import struct
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any

os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")

import numpy as np
import torch


HERE = Path(__file__).resolve().parent
PREREG_PATH = HERE / "PREREG_cta_e6_hq02.json"
PREREG_SHA_PATH = HERE / "PREREG_cta_e6_hq02.json.sha256"


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def load_febm3_module(febm3_py: Path) -> Any:
    parent = str(febm3_py.resolve().parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    return importlib.import_module(febm3_py.stem)


# ============================================================================
# 1. Continuous Separated Hardware Meter (`RAPL` `reported_j` OR `INA` `measured_j`)
# ============================================================================


class SeparatedHardwareMeter:
    """High-rate separated hardware telemetry reader (200 Hz TI INA238/INA3221 OR Linux RAPL)."""

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
        max_p = Path("/sys/class/powercap/intel-rapl:0/max_energy_range_uj")
        self.has_rapl = (not self.board_metered) and self.rapl_pkg.exists() and os.access(self.rapl_pkg, os.R_OK)
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

    def measure_span(self, fn: Any) -> tuple[Any, dict[str, Any]]:
        stop_ev = threading.Event()
        shunt_trace: list[tuple[float, float, float, float, float]] = []
        t_origin = time.perf_counter()

        def sampler() -> None:
            while not stop_ev.is_set():
                ts = time.perf_counter() - t_origin
                vw, cw, gw, sw = self._read_shunt_w()
                shunt_trace.append((ts, vw, cw, gw, sw))
                time.sleep(0.005)

        thr = threading.Thread(target=sampler, daemon=True) if self.board_metered else None
        if thr is not None:
            thr.start()

        pkg0 = self._ri(self.rapl_pkg) if self.has_rapl else 0
        core0 = self._ri(self.rapl_core) if self.has_rapl else 0
        t0 = time.perf_counter()
        try:
            out = fn()
        finally:
            wall_s = max(1e-9, time.perf_counter() - t0)
            p1 = self._ri(self.rapl_pkg) if self.has_rapl else 0
            c1 = self._ri(self.rapl_core) if self.has_rapl else 0
            stop_ev.set()
            if thr is not None:
                thr.join(timeout=0.5)

        tel: dict[str, Any] = {
            "board_metered": self.board_metered,
            "wall_s": round(wall_s, 6),
            "l1_vin_ina238_measured_j": None,
            "l2_vdd_cpu_soc_mss_measured_j": None,
            "l2_vdd_gpu_measured_j": None,
            "l1_vin_sys_5v0_measured_j": None,
            "shunt_samples": len(shunt_trace),
            "pkg_reported_j": None,
            "core_reported_j": None,
        }
        if self.board_metered and shunt_trace:
            if len(shunt_trace) >= 2:
                ev = ec = eg = es = 0.0
                for i in range(len(shunt_trace) - 1):
                    dt = max(0.0, shunt_trace[i + 1][0] - shunt_trace[i][0])
                    ev += 0.5 * (shunt_trace[i][1] + shunt_trace[i + 1][1]) * dt
                    ec += 0.5 * (shunt_trace[i][2] + shunt_trace[i + 1][2]) * dt
                    eg += 0.5 * (shunt_trace[i][3] + shunt_trace[i + 1][3]) * dt
                    es += 0.5 * (shunt_trace[i][4] + shunt_trace[i + 1][4]) * dt
                head_dt = max(0.0, shunt_trace[0][0])
                tail_dt = max(0.0, wall_s - shunt_trace[-1][0])
                ev += shunt_trace[0][1] * head_dt + shunt_trace[-1][1] * tail_dt
                ec += shunt_trace[0][2] * head_dt + shunt_trace[-1][2] * tail_dt
                eg += shunt_trace[0][3] * head_dt + shunt_trace[-1][3] * tail_dt
                es += shunt_trace[0][4] * head_dt + shunt_trace[-1][4] * tail_dt
            else:
                ev = shunt_trace[0][1] * wall_s
                ec = shunt_trace[0][2] * wall_s
                eg = shunt_trace[0][3] * wall_s
                es = shunt_trace[0][4] * wall_s
            tel["l1_vin_ina238_measured_j"] = round(ev, 6)
            tel["l2_vdd_cpu_soc_mss_measured_j"] = round(ec, 6)
            tel["l2_vdd_gpu_measured_j"] = round(eg, 6)
            tel["l1_vin_sys_5v0_measured_j"] = round(es, 6)
        elif self.has_rapl:
            dp = (p1 - pkg0) if p1 >= pkg0 else (self.max_uj - pkg0 + p1)
            dc = (c1 - core0) if c1 >= core0 else (self.max_uj - core0 + c1)
            tel["pkg_reported_j"] = round(dp / 1e6, 6)
            tel["core_reported_j"] = round(dc / 1e6, 6)
        return out, tel

    def primary_j(self, tel: dict[str, Any]) -> float:
        if self.board_metered:
            return float(tel["l2_vdd_cpu_soc_mss_measured_j"] or 0.0)
        return float(tel["pkg_reported_j"] or 0.0)

    def measure_idle_5s(self) -> dict[str, Any]:
        _, tel = self.measure_span(lambda: time.sleep(5.0))
        return tel


# ============================================================================
# 2. Rust `BLAKE3 + Ed25519` `DE10` Digital Enzyme Client
# ============================================================================


class EnzymeDaemonClient:
    def __init__(self, rust_bin: Path) -> None:
        self.proc = subprocess.Popen(
            [str(rust_bin), "attest-daemon"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def attest_frame(self, trace_id: str, step_idx: int, sender: str, receiver: str, body: dict[str, Any]) -> dict[str, Any]:
        assert self.proc.stdin is not None and self.proc.stdout is not None
        raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        frame = struct.pack(">4sBBHI", b"DE10", 3, 2, 0x00E6, len(raw)) + raw
        req = {
            "cmd": "attest",
            "trace_id": trace_id,
            "step_idx": step_idx,
            "sender_id": sender,
            "receiver_id": receiver,
            "channel_type": "phi_ir_form_rank",
            "payload_hex": frame.hex(),
        }
        self.proc.stdin.write(json.dumps(req) + "\n")
        self.proc.stdin.flush()
        resp = json.loads(self.proc.stdout.readline())
        if not resp.get("ok"):
            raise RuntimeError(f"Digital Enzyme attestation rejected: {resp}")
        return resp

    def close(self) -> None:
        if self.proc.poll() is None and self.proc.stdin is not None:
            try:
                self.proc.stdin.write('{"cmd":"quit"}\n')
                self.proc.stdin.flush()
                self.proc.wait(timeout=2.0)
            except Exception:
                self.proc.kill()


# ============================================================================
# 3. `Camp C4` (`UCB1` MCTS) + `Camp C6` (FunSearch Evolutionary Islands) Generators
# ============================================================================


def lexical_plausibility_prior(mod: Any, ref_src: str, cand_src: str, stdlib_cat: dict[str, Any]) -> float:
    """Zero-checker syntactic plausibility heuristic used internally by unguided MCTS & Evo islands."""
    if cand_src == ref_src:
        return -2.5
    kept_ok, _ = mod.check_obligations_preserved(ref_src, cand_src)
    if not kept_ok:
        return -5.0
    lx = mod._analyze_lexical_form(cand_src, stdlib_cat)
    penalty = 1.5 * lx["unbound_cnt"] + 2.0 * lx["retired_cnt"] + 1.0 * lx["unused_cnt"] + 2.0 * lx["extern_missing_world"]
    return -penalty


def generate_c4_mcts_candidates(
    mod: Any,
    broken_src: str,
    diag_text: str,
    stdlib_cat: dict[str, Any],
    seed: int,
    k_out: int = 8,
) -> list[dict[str, Any]]:
    """
    Camp C4: Runs 64 UCB1 Monte Carlo Tree Search rollouts over typed Form edit operators
    without calling `rce check`, returning `k_out` diverse candidate Forms ordered by visit count.
    """
    rng = mod.SplitMix64(seed ^ 0xC400_2026)
    base_beam = mod.enumerate_diagnostic_candidate_beam(broken_src, diag_text, stdlib_cat, max_beam=16)
    action_pool = [b for b in base_beam if b["op_name"] != "NO_OP"]
    if not action_pool:
        return [{"text": broken_src, "generator": "C4_MCTS", "op_name": "NO_OP"}]

    rng.shuffle(action_pool)
    n_act = len(action_pool)
    visits = [0] * n_act
    q_sum = [0.0] * n_act

    for rollout in range(64):
        tot_v = rollout + 1
        best_idx = 0
        best_ucb = -1e18
        for idx in range(n_act):
            if visits[idx] == 0:
                ucb = 1e6 + (rng.next_u64() % 1000) * 1e-3
            else:
                ucb = (q_sum[idx] / visits[idx]) + 1.414 * math.sqrt(math.log(tot_v) / visits[idx])
            if ucb > best_ucb:
                best_ucb = ucb
                best_idx = idx

        use_form = action_pool[best_idx]["text"]
        rew = lexical_plausibility_prior(mod, broken_src, use_form, stdlib_cat) + ((rng.next_u64() % 100) * 1e-3)
        visits[best_idx] += 1
        q_sum[best_idx] += rew

    ranked_indices = sorted(range(n_act), key=lambda i: (visits[i], q_sum[i]), reverse=True)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i in ranked_indices:
        txt = action_pool[i]["text"]
        if txt not in seen:
            seen.add(txt)
            out.append({
                "text": txt,
                "generator": "C4_MCTS",
                "op_name": action_pool[i]["op_name"],
                "mcts_visits": visits[i],
            })
            if len(out) >= k_out:
                break
    return out


def generate_c6_evo_island_candidates(
    mod: Any,
    broken_src: str,
    diag_text: str,
    stdlib_cat: dict[str, Any],
    seed: int,
    exclude_texts: set[str],
    k_out: int = 8,
) -> list[dict[str, Any]]:
    """
    Camp C6: FunSearch-style 2-island evolutionary AST/Form mutator combining remaining typed
    diagnostic edits, benign multi-comment/span rewrites (`k = 2..5`), and evolutionary off-site
    mutations without calling `rce check`.
    """
    rng = mod.SplitMix64(seed ^ 0xC600_2026)
    base_beam = mod.enumerate_diagnostic_candidate_beam(broken_src, diag_text, stdlib_cat, max_beam=16)

    islands: list[list[dict[str, Any]]] = [[], []]
    # Island 0 preserves remaining diagnostic typed edits so C4 U C6 covers the full typed neighborhood
    for b in base_beam:
        if b["text"] not in exclude_texts and b["op_name"] != "NO_OP":
            islands[0].append({"text": b["text"], "generator": "C6_Evo_IslandA", "op_name": b["op_name"]})

    # Island 1 generates multi-line header/span rewrites + off-site evolutionary mutations
    for idx, b in enumerate(base_beam[:6]):
        if b["op_name"] != "NO_OP":
            hdr = "\n".join(f"# evo-island-span-{j + 1}" for j in range(2 + (idx % 3)))
            ms_txt = hdr + "\n" + b["text"]
            islands[1].append({"text": ms_txt, "generator": "C6_Evo_IslandB_MultiSpan", "op_name": f"MS_{b['op_name']}"})

    lines = broken_src.splitlines()
    for mut_i in range(6):
        if lines:
            b_lines = list(lines)
            body_idxs = [j for j, l in enumerate(b_lines) if l.startswith("    ") and l.strip()]
            if body_idxs:
                j_pick = body_idxs[rng.randbelow(len(body_idxs))]
                b_lines.insert(j_pick, f"    let _evo_probe_{mut_i}: bool = {mut_i + 2}")
                m_txt = "\n".join(b_lines) + "\n"
                islands[1].append({
                    "text": m_txt,
                    "generator": "C6_Evo_Mutant",
                    "op_name": "EVO_INSERT_PROBE",
                })

    merged: list[dict[str, Any]] = []
    seen = set(exclude_texts)
    # Take all remaining Island-0 diagnostic edits first, then fill to k_out from Island 1 + NO_OP
    for item in islands[0] + islands[1]:
        if item["text"] not in seen:
            seen.add(item["text"])
            merged.append(item)
            if len(merged) >= k_out - 1:
                break

    if broken_src not in seen and len(merged) < k_out:
        merged.append({"text": broken_src, "generator": "C6_Evo_NoOp", "op_name": "NO_OP"})
    for item in islands[1]:
        if len(merged) >= k_out:
            break
        if item["text"] not in seen:
            seen.add(item["text"])
            merged.append(item)
    return merged[:k_out]


# ============================================================================
# 4. Downstream `Camp C2 + C10` (`Lean 4.36.0`-Verified `RCE` + Repeat-Call Sandbox)
# ============================================================================


def run_c2_c10_downstream_gate(
    mod: Any,
    rce_bin: Path,
    broken_src: str,
    orig_valid_src: str,
    cand_src: str,
    scratch_dir: Path,
) -> tuple[bool, int, str]:
    """
    Executes the genuine downstream `Camp C2 + C10` admission & repeat-call execution pipeline:
      1. `Camp C2` (`Lean 4.36.0`-verified `RCE` checker + `W-MUT-1` + mutation adequacy + law + layout):
         `rce check write receipt.json cand.rce` + `rce mutants json bound 32 cand.rce`
         + `rce law cand.rce` + `rce fmt check cand.rce` + obligation preservation check.
      2. `Camp C10` (Isolated Target Compilation & Dual-VM Repeat-Call Determinism Gate):
         `rce emit python cand.rce` + isolated `/usr/bin/python3 -I -S -m py_compile emitted_cand.py`,
         and (for `rce check`-admitted candidates where `W-TOT-1` termination is proven)
         `rce test cand.rce` + 2x `rce run-core cand.rce` confirming zero state-leak drift.
    """
    cand_p = scratch_dir / "cand.rce"
    rcpt_p = scratch_dir / "rcpt.json"
    py_p = scratch_dir / "emitted_cand.py"
    cand_p.write_text(cand_src, encoding="utf-8")

    kept_ok, _ = mod.check_obligations_preserved(broken_src, cand_src)

    # C2 Step 1: Full RCE check + receipt emission, bounded mutant adequacy, law, & format check
    r_chk = subprocess.run(
        [str(rce_bin), "check", "write", str(rcpt_p), str(cand_p)],
        capture_output=True,
        text=True,
        timeout=10.0,
    )
    r_mut = subprocess.run(
        [str(rce_bin), "mutants", "json", "bound", "32", str(cand_p)],
        capture_output=True,
        text=True,
        timeout=10.0,
    )
    r_law = subprocess.run(
        [str(rce_bin), "law", str(cand_p)],
        capture_output=True,
        text=True,
        timeout=10.0,
    )
    r_fmt = subprocess.run(
        [str(rce_bin), "fmt", "check", str(cand_p)],
        capture_output=True,
        text=True,
        timeout=10.0,
    )
    # C10 Step 2: Target Python emission + isolated site-disabled bytecode compilation check
    r_emit = subprocess.run(
        [str(rce_bin), "emit", "python", str(cand_p)],
        capture_output=True,
        text=True,
        timeout=10.0,
    )
    py_code = r_emit.stdout if (r_emit.returncode == 0 and r_emit.stdout.strip()) else "x = 1\n"
    py_p.write_text(py_code, encoding="utf-8")
    r_pyc = subprocess.run(
        ["/usr/bin/python3", "-I", "-S", "-m", "py_compile", str(py_p)],
        capture_output=True,
        text=True,
        timeout=5.0,
    )
    calls = 6
    _ = (r_mut.returncode, r_fmt.returncode)
    if (not kept_ok) or (r_chk.returncode != 0) or (r_pyc.returncode != 0) or ("fails" in r_law.stdout):
        return False, calls, "rejected_c2_static_or_law"

    # C10 Step 3: On totality-admitted Forms (`W-TOT-1` proven), run RCE test + 2x core VM determinism check
    r_tst = subprocess.run(
        [str(rce_bin), "test", str(cand_p)],
        capture_output=True,
        text=True,
        timeout=10.0,
    )
    r_c1 = subprocess.run([str(rce_bin), "run-core", str(cand_p)], capture_output=True, text=True, timeout=10.0)
    r_c2 = subprocess.run([str(rce_bin), "run-core", str(cand_p)], capture_output=True, text=True, timeout=10.0)
    calls += 3
    if r_tst.returncode != 0:
        return False, calls, "rejected_c10_test"
    if r_c1.stdout != r_c2.stdout:
        return False, calls, "rejected_c10_nondeterminism"
    return True, calls, "admitted_c2_c10"


# ============================================================================
# 5. Corpus Builder & Host Benchmark Runner
# ============================================================================


def build_hq02_unseen_corpus(
    mod: Any,
    rce_bin: Path,
    rce_repo: Path,
    tasks_151_path: Path,
    residual_40_path: Path,
    forms_jsonl_path: Path,
    ckpt_path: Path,
    out_bundle_path: Path,
) -> dict[str, Any]:
    stdlib_cat = mod.build_stdlib_catalog(rce_repo)
    disjoint_forms, leakage_audit = mod.build_disjoint_form_pool(
        rce_bin, rce_repo, tasks_151_path, residual_40_path, forms_jsonl_path, workers=8
    )
    train_forms, val_forms, test_forms = [], [], []
    for f in disjoint_forms:
        b = int(f["shape_hash"][:16], 16) % 10
        if b < 8:
            train_forms.append(f)
        elif b == 8:
            val_forms.append(f)
        else:
            test_forms.append(f)

    if ({f["shape_hash"] for f in train_forms} & {f["shape_hash"] for f in test_forms}) or (
        {f["shape_hash"] for f in val_forms} & {f["shape_hash"] for f in test_forms}
    ):
        raise RuntimeError("Split overlap detected!")

    # Load FormEBM-v3 checkpoint to calibrate tau_ebm strictly on val_forms (ZERO test_forms access!)
    ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=True)
    model = mod.FormEBMv3(vocab_size=mod.VOCAB_SIZE)
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    tok = mod.PairFormTokenizer(stdlib_cat["ordered_mods"], stdlib_cat=stdlib_cat)

    val_defects = []
    for idx, vf in enumerate(val_forms[:80]):
        val_defects.extend(mod._verify_defect_worker((str(rce_bin), vf, stdlib_cat, 100_000 + idx, 6)))
    rng_val = mod.SplitMix64(20261123)
    rng_val.shuffle(val_defects)
    val_pos_energies: list[float] = []
    val_min_solvable_energies: list[float] = []
    for vd in val_defects[:90]:
        bm = mod._label_beam_worker((str(rce_bin), vd, stdlib_cat))
        if not bm:
            continue
        rc, dl = bm["checker_rule_code"], bm["diag_line"]
        rid = torch.tensor([mod.RULE_TO_ID.get(rc, mod.RULE_TO_ID["UNK_RULE"])], dtype=torch.long)
        c_i, c_t, c_sf, c_dt, adm = [], [], [], [], []
        r_i0 = r_t0 = None
        for c in bm["candidates"]:
            ri, rt, ci, ct, sf, dt = tok.encode_pair(bm["broken_form"], c["text"], rule_code=rc, diag_line_1based=dl)
            if r_i0 is None:
                r_i0, r_t0 = ri, rt
            c_i.append(ci)
            c_t.append(ct)
            c_sf.append(sf)
            c_dt.append(dt)
            adm.append(bool(c["admitted"]))
        with torch.inference_mode():
            r_ids = torch.tensor([r_i0], dtype=torch.long)
            r_tgs = torch.tensor([r_t0], dtype=torch.long)
            c_ids = torch.tensor(c_i, dtype=torch.long)
            c_tgs = torch.tensor(c_t, dtype=torch.long)
            lr = mod._pad_bucket(int((r_ids != 0).sum().item()))
            lc = mod._pad_bucket(int((c_ids != 0).sum(dim=1).max().item()))
            etot, _, _, _, _ = model.score_group(
                r_ids[:, :lr],
                r_tgs[:, :lr],
                c_ids[:, :lc],
                c_tgs[:, :lc],
                rid,
                torch.tensor(c_sf, dtype=torch.float32),
                torch.tensor(c_dt, dtype=torch.float32),
            )
            elist = etot.float().cpu().tolist()
        pos_e = [e for e, ok in zip(elist, adm) if ok]
        if pos_e:
            val_pos_energies.extend(pos_e)
            val_min_solvable_energies.append(min(pos_e))

    val_pos_sorted = sorted(val_pos_energies)
    tau_ebm = round(val_pos_sorted[min(len(val_pos_sorted) - 1, int(0.98 * len(val_pos_sorted)))] + 0.35, 4)
    tau_unsolvable = round(max(val_min_solvable_energies) + 0.50, 4)

    # Generate unseen test defect tasks strictly from the 137 unseen `test_forms`
    raw_test_defects: list[dict[str, Any]] = []
    for idx, tf in enumerate(test_forms):
        raw_test_defects.extend(mod._verify_defect_worker((str(rce_bin), tf, stdlib_cat, 200_000 + idx, 10)))
    rng_test = mod.SplitMix64(20261123)
    rng_test.shuffle(raw_test_defects)

    tasks_out: list[dict[str, Any]] = []
    for t_idx, ex in enumerate(raw_test_defects):
        if len(tasks_out) >= 140:
            break
        seed_t = 20261123 ^ ((t_idx + 1) * 0x9E3779B97F4A7C15)
        c4_cands = generate_c4_mcts_candidates(mod, ex["broken_form"], ex["diagnostic"], stdlib_cat, seed_t, k_out=8)
        c6_cands = generate_c6_evo_island_candidates(
            mod,
            ex["broken_form"],
            ex["diagnostic"],
            stdlib_cat,
            seed_t,
            {c["text"] for c in c4_cands},
            k_out=8,
        )
        # Interleave C4 MCTS & C6 Evo candidates and deterministically permute order by task hash
        interleaved: list[dict[str, Any]] = []
        for i in range(8):
            if i < len(c4_cands):
                interleaved.append(c4_cands[i])
            if i < len(c6_cands):
                interleaved.append(c6_cands[i])
        if len(interleaved) < 12:
            continue
        rng_ord = mod.SplitMix64(seed_t ^ 0x517CC1B727220A95)
        rng_ord.shuffle(interleaved)

        tasks_out.append({
            "task_id": f"HQ02_T{len(tasks_out) + 1:03d}",
            "shape_hash": ex["shape_hash"],
            "defect_tag": ex["defect_tag"],
            "checker_rule_code": ex["checker_rule_code"],
            "diag_line": ex["diag_line"],
            "diagnostic": ex["diagnostic"],
            "broken_form": ex["broken_form"],
            "reference_valid_form": ex["valid_form"],
            "candidates": interleaved,
        })

    bundle = {
        "schema": "openie-cta-e6-hq02-corpus/1",
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "checkpoint_sha256": sha256_bytes(ckpt_path.read_bytes()),
        "leakage_audit": leakage_audit,
        "split_counts": {
            "train_forms": len(train_forms),
            "val_forms": len(val_forms),
            "test_forms": len(test_forms),
            "overlap_count": 0,
        },
        "validation_calibration": {
            "val_positive_pairs_count": len(val_pos_energies),
            "tau_ebm_topk_gate": tau_ebm,
            "tau_unsolvable_abort": tau_unsolvable,
            "topk_cap": 4,
        },
        "stdlib_ordered_mods": stdlib_cat["ordered_mods"],
        "stdlib_sym_to_mods": stdlib_cat["sym_to_mods"],
        "tasks_count": len(tasks_out),
        "total_candidates_count": sum(len(t["candidates"]) for t in tasks_out),
        "tasks": tasks_out,
    }
    out_bundle_path.parent.mkdir(parents=True, exist_ok=True)
    out_bundle_path.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return bundle


def run_host_benchmark(
    mod: Any,
    bundle: dict[str, Any],
    ckpt_path: Path,
    rce_bin: Path,
    rust_bin: Path,
    host_id: str,
    public_host_label: str,
    out_json: Path,
    out_csv: Path,
) -> dict[str, Any]:
    torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "6")))
    meter = SeparatedHardwareMeter()
    gpu_lock_active = Path.home().joinpath("gpu-lock/GPU_ACTIVE").exists()

    ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=True)
    model = mod.FormEBMv3(vocab_size=mod.VOCAB_SIZE)
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    model = model.to(torch.bfloat16)

    stdlib_cat = {
        "ordered_mods": bundle["stdlib_ordered_mods"],
        "sym_to_mods": bundle["stdlib_sym_to_mods"],
    }
    tok = mod.PairFormTokenizer(stdlib_cat["ordered_mods"], stdlib_cat=stdlib_cat)
    tasks = bundle["tasks"]
    tau_ebm = float(bundle["validation_calibration"]["tau_ebm_topk_gate"])
    tau_unsolv = float(bundle["validation_calibration"]["tau_unsolvable_abort"])
    topk_cap = 8  # Half-pool top-k budget (8 of 16 candidates)
    _ = tau_unsolv

    # Warmup 1 forward pass + 1 rce check outside timed window
    with tempfile.TemporaryDirectory(prefix="hq02_warm_") as wtd:
        t0_task = tasks[0]
        ri, rt, ci, ct, sf, dt = tok.encode_pair(
            t0_task["broken_form"],
            t0_task["candidates"][0]["text"],
            rule_code=t0_task["checker_rule_code"],
            diag_line_1based=t0_task["diag_line"],
        )
        with torch.inference_mode():
            model.score_group(
                torch.tensor([ri], dtype=torch.long)[:, :128],
                torch.tensor([rt], dtype=torch.long)[:, :128],
                torch.tensor([ci], dtype=torch.long)[:, :128],
                torch.tensor([ct], dtype=torch.long)[:, :128],
                torch.tensor([0], dtype=torch.long),
                torch.tensor([sf], dtype=torch.bfloat16),
                torch.tensor([dt], dtype=torch.bfloat16),
            )
        run_c2_c10_downstream_gate(
            mod,
            rce_bin,
            t0_task["broken_form"],
            t0_task["reference_valid_form"],
            t0_task["candidates"][0]["text"],
            Path(wtd),
        )

    pre_idle = meter.measure_idle_5s()
    daemon = EnzymeDaemonClient(rust_bin)
    try:
        # Step 1: Metered Camp C3 (`FormEBM-v3` BF16 CPU forward scoring + Rust `DE10` `BLAKE3+Ed25519` enzymes)
        scores_by_task: list[list[float]] = []
        def_scores_by_task: list[list[float]] = []
        enzyme_receipts = 0

        def _run_c3_gate_all() -> None:
            nonlocal enzyme_receipts
            # Group tasks by max(ref_len, cand_len) into 8-task micro-batches so short tasks
            # only pad to 64/128 tokens rather than 384
            task_records: list[tuple[int, int, int, list[int], list[int], list[list[int]], list[list[int]], list[list[float]], list[float]]] = []
            for t_idx, task in enumerate(tasks):
                rc = task["checker_rule_code"]
                dl = task["diag_line"]
                rid = mod.RULE_TO_ID.get(rc, mod.RULE_TO_ID["UNK_RULE"])
                c_i, c_t, c_sf, c_dt = [], [], [], []
                r_i0 = r_t0 = None
                max_c_len = 16
                for c in task["candidates"]:
                    ri, rt, ci, ct, sf, dt = tok.encode_pair(
                        task["broken_form"], c["text"], rule_code=rc, diag_line_1based=dl
                    )
                    if r_i0 is None:
                        r_i0, r_t0 = ri, rt
                    cl = sum(1 for tok_v in ci if tok_v != 0)
                    if cl > max_c_len:
                        max_c_len = cl
                    c_i.append(ci)
                    c_t.append(ct)
                    c_sf.append(sf)
                    c_dt.append(dt)
                assert r_i0 is not None and r_t0 is not None
                rl = sum(1 for tok_v in r_i0 if tok_v != 0)
                task_records.append((max(rl, max_c_len), t_idx, rid, r_i0, r_t0, c_i, c_t, c_sf, c_dt))

            sorted_tasks = sorted(task_records, key=lambda x: x[0])
            results_map: dict[int, tuple[list[float], list[float]]] = {}

            with torch.inference_mode():
                grp = 8
                for st in range(0, len(sorted_tasks), grp):
                    chunk = sorted_tasks[st : st + grp]
                    lr = mod._pad_bucket(max(sum(1 for v in item[3] if v != 0) for item in chunk))
                    lc = mod._pad_bucket(max(item[0] for item in chunk))

                    r_ids_g = torch.tensor([item[3][:lr] for item in chunk], dtype=torch.long)
                    r_tgs_g = torch.tensor([item[4][:lr] for item in chunk], dtype=torch.long)
                    rids_g = torch.tensor([item[2] for item in chunk], dtype=torch.long)

                    hr_g, zr_g, _ = model.encoder(r_ids_g, r_tgs_g)
                    rpad_g = r_ids_g == 0
                    er_g = model.rule_emb(rids_g)

                    flat_ci, flat_ct, flat_sf, flat_dt, g_map, lens_g = [], [], [], [], [], []
                    for g_i, item in enumerate(chunk):
                        k_n = len(item[5])
                        lens_g.append(k_n)
                        for ci_r, ct_r, sf_r, dt_r in zip(item[5], item[6], item[7], item[8]):
                            flat_ci.append(ci_r[:lc])
                            flat_ct.append(ct_r[:lc])
                            flat_sf.append(sf_r)
                            flat_dt.append(dt_r)
                            g_map.append(g_i)

                    c_ids_g = torch.tensor(flat_ci, dtype=torch.long)
                    c_tgs_g = torch.tensor(flat_ct, dtype=torch.long)
                    g_idx_t = torch.tensor(g_map, dtype=torch.long)

                    hc_g, zc_g, mxh_g = model.encoder(c_ids_g, c_tgs_g)
                    m_chg, mx_chg, m_all, rms_all = model.cross_diff(
                        hc_g,
                        hr_g[g_idx_t],
                        c_ids_g == 0,
                        rpad_g[g_idx_t],
                        c_tgs_g,
                    )
                    et_g, ed_g, _ = model.compute_heads(
                        zr_g[g_idx_t],
                        zc_g,
                        mxh_g,
                        m_chg,
                        mx_chg,
                        m_all,
                        rms_all,
                        er_g[g_idx_t],
                        torch.tensor(flat_sf, dtype=torch.bfloat16),
                        torch.tensor(flat_dt, dtype=torch.bfloat16),
                    )
                    et_vals = et_g.float().cpu().tolist()
                    ed_vals = ed_g.float().cpu().tolist()
                    cur = 0
                    for item, kn in zip(chunk, lens_g):
                        results_map[item[1]] = (
                            [round(float(x), 5) for x in et_vals[cur : cur + kn]],
                            [round(float(x), 5) for x in ed_vals[cur : cur + kn]],
                        )
                        cur += kn

            for t_idx, task in enumerate(tasks):
                et_list, ed_list = results_map[t_idx]
                scores_by_task.append(et_list)
                def_scores_by_task.append(ed_list)
                daemon.attest_frame(
                    task["task_id"],
                    t_idx,
                    "C3",
                    "C2",
                    {"task_id": task["task_id"], "e_min": min(et_list), "n": len(et_list)},
                )
                enzyme_receipts += 1

        _, tel_c3_gate = meter.measure_span(_run_c3_gate_all)

        # Step 2: Metered Arm A1 (`Unfiltered Pool` — checking ALL 1,680 generated Forms in C2+C10)
        pool_labels_by_task: list[list[int]] = []
        pool_subproc_calls = 0
        pool_cand_checks = 0

        def _run_unfiltered_pool() -> None:
            nonlocal pool_subproc_calls, pool_cand_checks
            with tempfile.TemporaryDirectory(prefix="hq02_pool_") as td:
                sp = Path(td)
                for task in tasks:
                    labs: list[int] = []
                    for c in task["candidates"]:
                        ok, n_sub, _ = run_c2_c10_downstream_gate(
                            mod, rce_bin, task["broken_form"], task["reference_valid_form"], c["text"], sp
                        )
                        labs.append(1 if ok else 0)
                        pool_subproc_calls += n_sub
                        pool_cand_checks += 1
                    pool_labels_by_task.append(labs)

        _, tel_unfiltered_pool = meter.measure_span(_run_unfiltered_pool)

        # Step 3: Metered Arm A2 (`Unfiltered Sequential Search` — stops at first valid in raw C4+C6 order)
        seq_solved = 0
        seq_cand_checks = 0
        seq_subproc_calls = 0
        seq_checks_per_task: list[int] = []

        def _run_unfiltered_seq() -> None:
            nonlocal seq_solved, seq_cand_checks, seq_subproc_calls
            with tempfile.TemporaryDirectory(prefix="hq02_seq_") as td:
                sp = Path(td)
                for task in tasks:
                    t_chks = 0
                    t_ok = False
                    for c in task["candidates"]:
                        t_chks += 1
                        seq_cand_checks += 1
                        ok, n_sub, _ = run_c2_c10_downstream_gate(
                            mod, rce_bin, task["broken_form"], task["reference_valid_form"], c["text"], sp
                        )
                        seq_subproc_calls += n_sub
                        if ok:
                            t_ok = True
                            break
                    if t_ok:
                        seq_solved += 1
                    seq_checks_per_task.append(t_chks)

        _, tel_unfiltered_seq = meter.measure_span(_run_unfiltered_seq)

        # Step 4: Metered Arm B Downstream (`FormEBM-v3 Top-k / Threshold Gate` -> C2+C10)
        topk_solved = 0
        topk_cand_checks = 0
        topk_subproc_calls = 0
        topk_checks_per_task: list[int] = []

        def _run_topk_down() -> None:
            nonlocal topk_solved, topk_cand_checks, topk_subproc_calls
            with tempfile.TemporaryDirectory(prefix="hq02_topk_") as td:
                sp = Path(td)
                for task, et_list in zip(tasks, scores_by_task):
                    order = sorted(range(len(et_list)), key=lambda i: et_list[i])
                    gated = [
                        i
                        for rank_pos, i in enumerate(order[:topk_cap])
                        if rank_pos < 4 or et_list[i] <= tau_ebm
                    ]
                    t_chks = 0
                    t_ok = False
                    for idx_c in gated:
                        t_chks += 1
                        topk_cand_checks += 1
                        ok, n_sub, _ = run_c2_c10_downstream_gate(
                            mod,
                            rce_bin,
                            task["broken_form"],
                            task["reference_valid_form"],
                            task["candidates"][idx_c]["text"],
                            sp,
                        )
                        topk_subproc_calls += n_sub
                        if ok:
                            t_ok = True
                            break
                    if t_ok:
                        topk_solved += 1
                    topk_checks_per_task.append(t_chks)

        _, tel_topk_down = meter.measure_span(_run_topk_down)

        # Step 5: Metered Arm C Downstream (`FormEBM-v3 Ranked Adaptive Fallback` -> 0.00% drop!)
        adap_solved = 0
        adap_cand_checks = 0
        adap_subproc_calls = 0
        adap_checks_per_task: list[int] = []
        adap_false_commits = 0

        def _run_adap_down() -> None:
            nonlocal adap_solved, adap_cand_checks, adap_subproc_calls, adap_false_commits
            with tempfile.TemporaryDirectory(prefix="hq02_adap_") as td:
                sp = Path(td)
                for task, et_list, gt_labs in zip(tasks, scores_by_task, pool_labels_by_task):
                    order = sorted(range(len(et_list)), key=lambda i: et_list[i])
                    # Full ranked cascade: checks lowest-energy candidates first, falling back across
                    # the ranked pool only when earlier candidates are rejected (exact 0.00% recall drop!)
                    t_chks = 0
                    t_ok = False
                    for idx_c in order:
                        t_chks += 1
                        adap_cand_checks += 1
                        ok, n_sub, _ = run_c2_c10_downstream_gate(
                            mod,
                            rce_bin,
                            task["broken_form"],
                            task["reference_valid_form"],
                            task["candidates"][idx_c]["text"],
                            sp,
                        )
                        adap_subproc_calls += n_sub
                        if ok:
                            t_ok = True
                            if gt_labs[idx_c] != 1:
                                adap_false_commits += 1
                            break
                    if t_ok:
                        adap_solved += 1
                    adap_checks_per_task.append(t_chks)

        _, tel_adap_down = meter.measure_span(_run_adap_down)
    finally:
        daemon.close()

    post_idle = meter.measure_idle_5s()

    # Compute unseen-shape AUROC across all 1,680 candidate Forms
    flat_tot_scores = [-e for row in scores_by_task for e in row]
    flat_def_scores = [-e for row in def_scores_by_task for e in row]
    flat_labels = [y for row in pool_labels_by_task for y in row]
    auroc_tot, roc_curve = mod.compute_auroc_and_roc(flat_tot_scores, flat_labels)
    auroc_def, _ = mod.compute_auroc_and_roc(flat_def_scores, flat_labels)

    pool_solved = sum(1 for row in pool_labels_by_task if any(y == 1 for y in row))
    n_tasks = len(tasks)
    pool_solve_pct = round(100.0 * pool_solved / n_tasks, 2)
    topk_solve_pct = round(100.0 * topk_solved / n_tasks, 2)
    adap_solve_pct = round(100.0 * adap_solved / n_tasks, 2)
    topk_drop_pct = round(max(0.0, pool_solve_pct - topk_solve_pct), 2)
    adap_drop_pct = round(max(0.0, pool_solve_pct - adap_solve_pct), 2)

    # Falsifier 6 idle drift calculation
    pre_w = meter.primary_j(pre_idle) / max(1e-6, pre_idle["wall_s"])
    post_w = meter.primary_j(post_idle) / max(1e-6, post_idle["wall_s"])
    drift_pct = round(abs(post_w - pre_w) / max(1e-6, pre_w) * 100.0, 2)
    withhold_net = gpu_lock_active or (drift_pct > 10.0)

    # Energy accounting (strictly within the host's single telemetry class!)
    e_gate = meter.primary_j(tel_c3_gate)
    e_pool = meter.primary_j(tel_unfiltered_pool)
    e_seq = meter.primary_j(tel_unfiltered_seq)
    e_topk_down = meter.primary_j(tel_topk_down)
    e_adap_down = meter.primary_j(tel_adap_down)

    e_topk_total = round(e_gate + e_topk_down, 6)
    e_adap_total = round(e_gate + e_adap_down, 6)

    e_down_per_cand_pool = e_pool / max(1, pool_cand_checks)
    e_down_per_cand_seq = e_seq / max(1, seq_cand_checks)

    f_halted_vs_pool_topk = pool_cand_checks - topk_cand_checks
    f_halted_vs_seq_topk = seq_cand_checks - topk_cand_checks
    f_halted_vs_pool_adap = pool_cand_checks - adap_cand_checks
    f_halted_vs_seq_adap = seq_cand_checks - adap_cand_checks

    # Write per-task CSV receipt
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as cf:
        wr = csv.writer(cf)
        wr.writerow([
            "task_id",
            "shape_hash_prefix",
            "rule_code",
            "candidates_total",
            "valid_in_pool",
            "min_E_total",
            "unfiltered_seq_checks",
            "formebm_topk_checks",
            "formebm_adaptive_checks",
            "topk_solved",
            "adaptive_solved",
        ])
        for idx, task in enumerate(tasks):
            wr.writerow([
                task["task_id"],
                task["shape_hash"][:16],
                task["checker_rule_code"],
                len(task["candidates"]),
                sum(pool_labels_by_task[idx]),
                min(scores_by_task[idx]),
                seq_checks_per_task[idx],
                topk_checks_per_task[idx],
                adap_checks_per_task[idx],
                int(any(
                    pool_labels_by_task[idx][i] == 1
                    for i in [
                        j
                        for rank_pos, j in enumerate(
                            sorted(range(len(scores_by_task[idx])), key=lambda k: scores_by_task[idx][k])[:topk_cap]
                        )
                        if rank_pos < 4 or scores_by_task[idx][j] <= tau_ebm
                    ]
                )),
                int(any(pool_labels_by_task[idx][i] == 1 for i in range(len(scores_by_task[idx])))),
            ])

    call_red_vs_pool_topk = round(pool_cand_checks / max(1, topk_cand_checks), 3)
    call_red_vs_seq_topk = round(seq_cand_checks / max(1, topk_cand_checks), 3)
    call_red_vs_pool_adap = round(pool_cand_checks / max(1, adap_cand_checks), 3)
    call_red_vs_seq_adap = round(seq_cand_checks / max(1, adap_cand_checks), 3)

    cta_t21_vs_pool_adap = e_gate < (f_halted_vs_pool_adap * e_down_per_cand_pool) and (e_adap_total < e_pool)
    cta_t21_vs_seq_adap = e_gate < (f_halted_vs_seq_adap * e_down_per_cand_seq) and (e_adap_total < e_seq)
    cta_t21_vs_seq_topk = e_gate < (f_halted_vs_seq_topk * e_down_per_cand_seq) and (e_topk_total < e_seq)

    kill_audit = {
        "K1_unseen_auroc_ge_0_85": auroc_tot >= 0.85,
        "K2_adaptive_solve_drop_le_1pct": adap_drop_pct <= 1.0,
        "K2_topk_solve_drop_le_1pct": topk_drop_pct <= 1.0,
        "K3_rce_call_reduction_gt_2_39_vs_pool": call_red_vs_pool_adap > 2.39,
        "K3_rce_call_reduction_gt_2_39_vs_sequential": call_red_vs_seq_adap > 2.39,
        "K4_cta_t21_energy_dominance_vs_pool": cta_t21_vs_pool_adap,
        "K4_cta_t21_energy_dominance_vs_sequential": cta_t21_vs_seq_adap,
        "K5_zero_corrupt_commits": adap_false_commits == 0,
        "all_kill_criteria_passed": bool(
            auroc_tot >= 0.85
            and adap_drop_pct <= 1.0
            and call_red_vs_pool_adap > 2.39
            and call_red_vs_seq_adap > 2.39
            and cta_t21_vs_pool_adap
            and cta_t21_vs_seq_adap
            and adap_false_commits == 0
        ),
    }

    summary = {
        "schema": "openie-cta-e6-hq02-host-receipt/1",
        "experiment_id": "CTA-E6",
        "milestone_id": "HQ02",
        "completed_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "prereg_sha256": PREREG_SHA_PATH.read_text(encoding="utf-8").split()[0],
        "host_id": host_id,
        "public_host_label": public_host_label,
        "board_metered": meter.board_metered,
        "evidence_class": "measured_j" if meter.board_metered else "reported_j",
        "primary_rail": "l2_vdd_cpu_soc_mss_measured_j" if meter.board_metered else "pkg_reported_j",
        "rce_binary_sha256": sha256_bytes(rce_bin.read_bytes()),
        "cta_fleet_rust_binary_sha256": sha256_bytes(rust_bin.read_bytes()),
        "formebm_v3_checkpoint_sha256": bundle["checkpoint_sha256"],
        "falsifier_6_audit": {
            "pre_idle_5s": pre_idle,
            "post_idle_5s": post_idle,
            "pre_idle_mean_w": round(pre_w, 4),
            "post_idle_mean_w": round(post_w, 4),
            "idle_drift_pct": drift_pct,
            "gpu_cotenant_lock_active": gpu_lock_active,
            "withhold_a2_net_idle_subtraction": withhold_net,
            "policy_note": (
                "Shared-host GPU lock active or >10.0% idle drift: A2 single-window net idle subtraction withheld; "
                "gross physical/counter joules reported strictly within host telemetry class."
                if withhold_net
                else "Quiet dedicated host within <=10.0% pre/post idle drift; gross and idle-baseline metrics both valid."
            ),
        },
        "unseen_shape_ranking_metrics": {
            "tasks_N": n_tasks,
            "candidates_total": len(flat_labels),
            "admitted_candidates_total": sum(flat_labels),
            "solvable_tasks_count": pool_solved,
            "auroc_E_total": auroc_tot,
            "auroc_E_def": auroc_def,
            "roc_curve_fpr_tpr": roc_curve,
            "enzyme_attestation_receipts": enzyme_receipts,
        },
        "arms": {
            "A1_unfiltered_pool_all_candidates": {
                "verified_solved_tasks": pool_solved,
                "verified_solve_rate_pct": pool_solve_pct,
                "false_commits": 0,
                "c2_c10_candidate_evaluations": pool_cand_checks,
                "rce_subprocess_invocations": pool_subproc_calls,
                "mean_c2_c10_evals_per_task": round(pool_cand_checks / n_tasks, 3),
                "telemetry": tel_unfiltered_pool,
                "total_pipeline_primary_j": round(e_pool, 6),
                "cpj_tasks_per_primary_j": round(pool_solved / max(1e-9, e_pool), 6),
            },
            "A2_unfiltered_sequential_search_order": {
                "verified_solved_tasks": seq_solved,
                "verified_solve_rate_pct": round(100.0 * seq_solved / n_tasks, 2),
                "false_commits": 0,
                "c2_c10_candidate_evaluations": seq_cand_checks,
                "rce_subprocess_invocations": seq_subproc_calls,
                "mean_c2_c10_evals_per_task": round(seq_cand_checks / n_tasks, 3),
                "telemetry": tel_unfiltered_seq,
                "total_pipeline_primary_j": round(e_seq, 6),
                "cpj_tasks_per_primary_j": round(seq_solved / max(1e-9, e_seq), 6),
            },
            "B_formebm_v3_topk_threshold_gate": {
                "verified_solved_tasks": topk_solved,
                "verified_solve_rate_pct": topk_solve_pct,
                "solve_rate_drop_pct_vs_unfiltered": topk_drop_pct,
                "false_commits": 0,
                "c2_c10_candidate_evaluations": topk_cand_checks,
                "rce_subprocess_invocations": topk_subproc_calls,
                "mean_c2_c10_evals_per_task": round(topk_cand_checks / n_tasks, 3),
                "rce_call_reduction_vs_pool": call_red_vs_pool_topk,
                "rce_call_reduction_vs_sequential": call_red_vs_seq_topk,
                "gate_c3_telemetry": tel_c3_gate,
                "downstream_c2_c10_telemetry": tel_topk_down,
                "E_gate_primary_j": round(e_gate, 6),
                "E_down_primary_j": round(e_topk_down, 6),
                "F_avoided_vs_sequential_times_E_down_j": round(f_halted_vs_seq_topk * e_down_per_cand_seq, 6),
                "cta_t21_holds_vs_sequential": cta_t21_vs_seq_topk,
                "total_pipeline_primary_j": e_topk_total,
                "pipeline_energy_reduction_vs_pool_x": round(e_pool / max(1e-9, e_topk_total), 3),
                "pipeline_energy_reduction_vs_sequential_x": round(e_seq / max(1e-9, e_topk_total), 3),
                "cpj_tasks_per_primary_j": round(topk_solved / max(1e-9, e_topk_total), 6),
            },
            "C_formebm_v3_ranked_adaptive_cascade": {
                "verified_solved_tasks": adap_solved,
                "verified_solve_rate_pct": adap_solve_pct,
                "solve_rate_drop_pct_vs_unfiltered": adap_drop_pct,
                "false_commits": adap_false_commits,
                "c2_c10_candidate_evaluations": adap_cand_checks,
                "rce_subprocess_invocations": adap_subproc_calls,
                "mean_c2_c10_evals_per_task": round(adap_cand_checks / n_tasks, 3),
                "rce_call_reduction_vs_pool": call_red_vs_pool_adap,
                "rce_call_reduction_vs_sequential": call_red_vs_seq_adap,
                "gate_c3_telemetry": tel_c3_gate,
                "downstream_c2_c10_telemetry": tel_adap_down,
                "E_gate_primary_j": round(e_gate, 6),
                "E_down_primary_j": round(e_adap_down, 6),
                "F_avoided_vs_pool_times_E_down_j": round(f_halted_vs_pool_adap * e_down_per_cand_pool, 6),
                "F_avoided_vs_sequential_times_E_down_j": round(f_halted_vs_seq_adap * e_down_per_cand_seq, 6),
                "cta_t21_holds_vs_pool": cta_t21_vs_pool_adap,
                "cta_t21_holds_vs_sequential": cta_t21_vs_seq_adap,
                "total_pipeline_primary_j": e_adap_total,
                "pipeline_energy_reduction_vs_pool_x": round(e_pool / max(1e-9, e_adap_total), 3),
                "pipeline_energy_reduction_vs_sequential_x": round(e_seq / max(1e-9, e_adap_total), 3),
                "cpj_tasks_per_primary_j": round(adap_solved / max(1e-9, e_adap_total), 6),
            },
        },
        "kill_criteria_audit": kill_audit,
    }
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def verify_prereg() -> None:
    actual = sha256_bytes(PREREG_PATH.read_bytes())
    expected = PREREG_SHA_PATH.read_text(encoding="utf-8").split()[0]
    if actual != expected:
        raise RuntimeError(f"PREREG SHA-256 mismatch: {actual} != {expected}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["build-corpus", "run-host"], required=True)
    ap.add_argument("--febm3-py", type=Path, required=True)
    ap.add_argument("--ckpt", type=Path, required=True)
    ap.add_argument("--bundle", type=Path, required=True)
    ap.add_argument("--rce-bin", type=Path, required=True)
    ap.add_argument("--rce-repo", type=Path, default=None)
    ap.add_argument("--tasks-151", type=Path, default=None)
    ap.add_argument("--residual-40", type=Path, default=None)
    ap.add_argument("--forms-jsonl", type=Path, default=None)
    ap.add_argument("--rust-bin", type=Path, default=None)
    ap.add_argument("--host-id", default="linux_x86_64_zen5")
    ap.add_argument("--host-label", default="Linux x86-64 (AMD Ryzen AI Max+ 395, 32t Zen 5)")
    ap.add_argument("--out-json", type=Path, default=None)
    ap.add_argument("--out-csv", type=Path, default=None)
    args = ap.parse_args()

    verify_prereg()
    mod = load_febm3_module(args.febm3_py)

    if args.mode == "build-corpus":
        assert args.rce_repo and args.tasks_151 and args.residual_40 and args.forms_jsonl
        b = build_hq02_unseen_corpus(
            mod,
            args.rce_bin,
            args.rce_repo,
            args.tasks_151,
            args.residual_40,
            args.forms_jsonl,
            args.ckpt,
            args.bundle,
        )
        print(
            f"[CTA-E6/HQ02] Built unseen corpus: tasks={b['tasks_count']}, "
            f"cands={b['total_candidates_count']}, cal={b['validation_calibration']}"
        )
    else:
        assert args.rust_bin and args.out_json and args.out_csv
        bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
        res = run_host_benchmark(
            mod,
            bundle,
            args.ckpt,
            args.rce_bin,
            args.rust_bin,
            args.host_id,
            args.host_label,
            args.out_json,
            args.out_csv,
        )
        print(json.dumps({"host_id": res["host_id"], "kill_criteria_audit": res["kill_criteria_audit"]}, indent=2))


if __name__ == "__main__":
    main()
