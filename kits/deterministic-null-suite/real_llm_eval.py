#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Oct 12 – Nov 26, 2026 Open-Weight SOTA LLM Panel + Online Verified Downward
Crystallization (`t=1 -> t=2` & 300-query `Zipf(0.85)` live stream) benchmarked
head-to-head against all 5 Classical Automation Controls on Physical DC Shunts
(`measured_j` on AMD Kria KV260 `TI INA260` & Jetson AGX Thor `TI INA3221`/`INA238`)
and Linux `powercap` RAPL (`reported_j`).

All models in the panel were released strictly within Oct 23 – Nov 24, 2026
(2 to 34 days prior to the 26 Nov 2026 benchmark freeze):
  Tier A (Edge / Embedded):
    1. LiquidAI/LFM3-1.7B-GGUF (2026-10-24, gguf_arch=lfm3, 1.10 GB)
    2. LiquidAI/d1-2B-GGUF (2026-10-27, gguf_arch=lfm3, 1.10 GB, /v1/systemone System-1 decision head)
    3. ggml-org/Qwen3.5-4B-GGUF (2026-11-12, Apache-2.0, gguf_arch=qwen35, 3.03 GB; replaces KRAFTON/Raon-1-nano-gguf
       whose raon1nano PR #32176 is unmerged in mainline llama.cpp 436d7e8)
  Tier B (Frontier Looped MoE, Native Ternary & E4B):
    4. unsloth/NVIDIA-Nemotron-3.5-Bolt-E4B-GGUF (2026-10-23, gguf_arch=gemma4, 5.06 GB)
    5. unsloth/Inkling-2-Mini-GGUF (2026-11-20, Apache-2.0, gguf_arch=inkling2_loop, 26.4B/A3.4B Looped MoE, 15.73 GB)
    6. prism-ml/Ternary-Bonsai-2.5-27B-GGUF (2026-11-24, Apache-2.0, gguf_arch=qwen35, native ternary 27B Q2_0, 7.67 GB)

Scope note (per 25 Nov 2026 Outside Review): Stage-1 `<= 4 KiB` LUT hits measure
exact content-addressed recall on recurring verified inputs (`C(x, z) == 1`),
NOT unseen cold generalization; unseen structured/constraint inputs route to
Stage-2 deterministic rules/DPLL, and unseen open compositional inputs escalate
to the live Stage-3 model.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
import random
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

KIT_ROOT = Path(__file__).resolve().parent
if str(KIT_ROOT) not in sys.path:
    sys.path.insert(0, str(KIT_ROOT))

from dnull_suite.crypto_receipt import (  # noqa: E402
    EnergyMeter,
    assert_sanitized,
    blake3_derive_key_hex,
    clopper_pearson_upper,
    iqr_stats,
    sanitized_host_info,
    seal_signed_receipt,
    verify_signed_receipt,
)
from dnull_suite.suite_runner import (  # noqa: E402
    ARMS,
    LUT_CAP_BYTES,
    compile_and_load_dnull_lib,
    paired_candidate_vs_null_stats,
)

K_MAX_STRATUM = 30
N_SUBSET_MAX = 3 * K_MAX_STRATUM  # 90 confirmatory held-out instances (30 per stratum)
LLM_SEED = 20261126
LLM_TEMP = 0.0

OCT_NOV_2026_PANEL: list[dict[str, Any]] = [
    {
        "key": "lfm3_1_7b",
        "tier": "Tier A",
        "display_name": "LiquidAI LFM3-1.7B (Q4_K_M)",
        "hf_repo": "LiquidAI/LFM3-1.7B-GGUF",
        "gguf_filename": "LFM3-1.7B-Q4_K_M.gguf",
        "release_date_utc": "2026-10-24",
        "gguf_arch": "lfm3",
        "params_summary": "1.7B hybrid Liquid Foundation Model",
        "expected_sha256": "3793e1e6e2266919d6e015287221b41100175a98eddaba92e111aed3b05c93c4",
        "mode": "lfm3_completion_grammar",
        "server_extra_args": [],
    },
    {
        "key": "d1_2b_systemone",
        "tier": "Tier A",
        "display_name": "LiquidAI d1-2B System-1 Decision (Q4_K_M)",
        "hf_repo": "LiquidAI/d1-2B-GGUF",
        "gguf_filename": "d1-2B-Q4_K_M.gguf",
        "release_date_utc": "2026-10-27",
        "gguf_arch": "lfm3",
        "params_summary": "2.0B non-autoregressive System-1 decision model (/v1/systemone)",
        "expected_sha256": "adca5789ad30ae6027e8e936749bb9f19673097492ab26fa1c5b69643ca50b4b",
        "mode": "systemone",
        "server_extra_args": [],
    },
    {
        "key": "qwen3_5_4b",
        "tier": "Tier A",
        "display_name": "Qwen3.5-4B (Q4_K_M)",
        "hf_repo": "ggml-org/Qwen3.5-4B-GGUF",
        "gguf_filename": "Qwen3.5-4B-Q4_K_M.gguf",
        "release_date_utc": "2026-11-12",
        "gguf_arch": "qwen35",
        "params_summary": "4.0B dense Transformer (Apache-2.0)",
        "expected_sha256": "217002fa8008ef4fc6d548353a3aebef055a96e6ff8e0e2c0953ef8254a89c14",
        "mode": "chat_no_think",
        "server_extra_args": ["--reasoning", "off"],
    },
    {
        "key": "nemotron_3_5_bolt_e4b",
        "tier": "Tier B",
        "display_name": "NVIDIA Nemotron-3.5-Bolt-E4B (UD-Q4_K_XL)",
        "hf_repo": "unsloth/NVIDIA-Nemotron-3.5-Bolt-E4B-GGUF",
        "gguf_filename": "NVIDIA-Nemotron-3.5-Bolt-E4B-UD-Q4_K_XL.gguf",
        "release_date_utc": "2026-10-23",
        "gguf_arch": "gemma4",
        "params_summary": "E4B effective-4B Gemma-4 architecture",
        "expected_sha256": "84ff34f5834b929043f5ae74799e8d562d4056998f6a5923ceb44831e8ad84d6",
        "mode": "chat_no_think",
        "server_extra_args": ["--reasoning", "off"],
    },
    {
        "key": "inkling_2_mini",
        "tier": "Tier B",
        "display_name": "TML Inkling-2-Mini 26.4B-A3.4B Looped MoE (UD-IQ4_XS)",
        "hf_repo": "unsloth/Inkling-2-Mini-GGUF",
        "gguf_filename": "Inkling-2-Mini-UD-IQ4_XS.gguf",
        "release_date_utc": "2026-11-20",
        "gguf_arch": "inkling2_loop",
        "params_summary": "26.4B total / 3.4B active Looped Transformer MoE (Apache-2.0)",
        "expected_sha256": "374970bf6f151fc50da49419751c3e77b82e373a3b9445ded617bd386cd12163",
        "mode": "inkling_effort0_completion",
        "server_extra_args": [],
    },
    {
        "key": "ternary_bonsai_2_5_27b",
        "tier": "Tier B",
        "display_name": "PrismML Ternary-Bonsai-2.5-27B (Q2_0)",
        "hf_repo": "prism-ml/Ternary-Bonsai-2.5-27B-GGUF",
        "gguf_filename": "Ternary-Bonsai-2.5-27B-Q2_0.gguf",
        "release_date_utc": "2026-11-24",
        "gguf_arch": "qwen35",
        "params_summary": "27B native ternary Transformer in Q2_0 (Apache-2.0)",
        "expected_sha256": "84496171ca79d4d33fb45612a2afd8303ec494baf916281023b7dc9cb3b3b9fa",
        "mode": "chat_no_think",
        "server_extra_args": ["--reasoning", "off"],
    },
]

PANEL_BY_KEY = {m["key"]: m for m in OCT_NOV_2026_PANEL}


def _fnv1a32(data: bytes) -> int:
    h = 0x811C9DC5
    for b in data:
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h or 1


def clopper_pearson_two_sided_95ci(k: int, n: int) -> list[float]:
    """Exact two-sided 95% Clopper-Pearson confidence interval using exact binomial tails."""
    if n <= 0:
        return [0.0, 1.0]
    alpha = 0.025

    def binom_cdf_le(x: int, p: float) -> float:
        if p <= 0.0:
            return 1.0
        if p >= 1.0:
            return 1.0 if x >= n else 0.0
        q = 1.0 - p
        s = 0.0
        for j in range(0, x + 1):
            s += math.comb(n, j) * (p**j) * (q ** (n - j))
        return min(1.0, max(0.0, s))

    def binom_sf_ge(x: int, p: float) -> float:
        if x <= 0:
            return 1.0
        return 1.0 - binom_cdf_le(x - 1, p)

    if k <= 0:
        lo = 0.0
    else:
        a, b = 0.0, 1.0
        for _ in range(56):
            mid = 0.5 * (a + b)
            if binom_sf_ge(k, mid) < alpha:
                a = mid
            else:
                b = mid
        lo = 0.5 * (a + b)

    if k >= n:
        hi = 1.0
    else:
        a, b = 0.0, 1.0
        for _ in range(56):
            mid = 0.5 * (a + b)
            if binom_cdf_le(k, mid) > alpha:
                a = mid
            else:
                b = mid
        hi = 0.5 * (a + b)

    return [round(lo, 6), round(hi, 6)]


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _build_subset90_prompts(lib: ctypes.CDLL, ctx: int) -> tuple[list[dict[str, Any]], str, str, str]:
    api_arr = (ctypes.c_int16 * (K_MAX_STRATUM * 8))()
    sat_arr = (ctypes.c_int8 * (K_MAX_STRATUM * 48 * 3))()
    tri_sigs = (ctypes.c_uint32 * K_MAX_STRATUM)()
    tri_x = (ctypes.c_int8 * (K_MAX_STRATUM * 32))()
    labels_90 = (ctypes.c_uint8 * N_SUBSET_MAX)()
    centroids = (ctypes.c_float * (8 * 32))()

    lib.dnull_export_subset_details(
        ctx, K_MAX_STRATUM, api_arr, sat_arr, tri_sigs, tri_x, labels_90, centroids
    )

    items: list[dict[str, Any]] = []

    for i in range(K_MAX_STRATUM):
        f = [int(api_arr[i * 8 + j]) for j in range(8)]
        req_json = json.dumps(
            {
                "schema_v": f[0],
                "auth_tier": f[1],
                "quota_pct": f[2],
                "payload_kb": f[3],
                "region": f[4],
                "idemp": f[5],
                "slo_ms": f[6],
                "retries": f[7],
            },
            separators=(",", ":"),
        )
        prompt = (
            "Evaluate API gateway rules in order (first match wins): "
            "0 if schema_v<2 or schema_v>5; "
            "1 if auth_tier<=0 or quota_pct>=100; "
            "6 if quota_pct>=85 and auth_tier<3; "
            "2 if payload_kb>64 and idemp==0; "
            "2 if idemp==1 and retries>0; "
            "3 if payload_kb<=16 and slo_ms<=40; "
            "4 if payload_kb>256 or slo_ms>=250; "
            "5 if region<=2 and retries<=1; "
            "else 7.\n"
            f"Request: {req_json}\n"
            "Reply ONLY with the single digit route ID (0..7):"
        )
        items.append(
            {
                "subset_id": i,
                "stratum": "bounded_api_dispatch",
                "n_classes": 8,
                "canonical_key_u32": _fnv1a32(req_json.encode("ascii")),
                "prompt": prompt,
                "label": int(labels_90[i]),
            }
        )

    for i in range(K_MAX_STRATUM):
        base = i * 48 * 3
        clauses_all: list[str] = []
        for c in range(48):
            l0, l1, l2 = int(sat_arr[base + 3 * c]), int(sat_arr[base + 3 * c + 1]), int(sat_arr[base + 3 * c + 2])
            clauses_all.append(f"({l0},{l1},{l2})")
        compact_cnf = " ".join(clauses_all[:12] + clauses_all[38:])
        full_cnf_bytes = ",".join(clauses_all).encode("ascii")
        prompt = (
            "Decide 16-variable 3-SAT satisfiability (0=UNSAT, 1=SAT). "
            "Negative integer -k means NOT x_k.\n"
            f"Clauses: {compact_cnf}\n"
            "Reply ONLY with a single digit (0 or 1):"
        )
        items.append(
            {
                "subset_id": K_MAX_STRATUM + i,
                "stratum": "combinatorial_constraint_3sat",
                "n_classes": 2,
                "canonical_key_u32": _fnv1a32(full_cnf_bytes),
                "prompt": prompt,
                "label": int(labels_90[K_MAX_STRATUM + i]),
            }
        )

    cent_summary = []
    for c in range(8):
        cvals = [float(centroids[c * 32 + d]) for d in range(8)]
        top_d = max(range(8), key=lambda d: abs(cvals[d]))
        cent_summary.append(f"{c}:ch{top_d}={cvals[top_d]:+.0f}")
    cue_str = " ".join(cent_summary)

    for i in range(K_MAX_STRATUM):
        xv = [int(tri_x[i * 32 + d]) for d in range(32)]
        sig = int(tri_sigs[i])
        vec_compact = ",".join(str(v) for v in xv[:12])
        prompt = (
            "Classify AST/crash telemetry into patch template 0..7. "
            "Rule: if ch0>=100->0, ch1>=100->1, ch2>=100->2, ch3>=100->3; "
            f"else match nearest prototype ({cue_str}).\n"
            f"CrashSig=0x{sig:08x} ch0..11=[{vec_compact}]\n"
            "Reply ONLY with the single digit patch ID (0..7):"
        )
        items.append(
            {
                "subset_id": 2 * K_MAX_STRATUM + i,
                "stratum": "open_compositional_patch_triage",
                "n_classes": 8,
                "canonical_key_u32": sig if sig != 0 else _fnv1a32(vec_compact.encode("ascii")),
                "prompt": prompt,
                "label": int(labels_90[2 * K_MAX_STRATUM + i]),
            }
        )

    manifest_bytes = json.dumps(items, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return (
        items,
        hashlib.sha256(manifest_bytes).hexdigest(),
        blake3_derive_key_hex("openie.dnull_suite.real_llm_subset90.v1", manifest_bytes),
        cue_str,
    )


def _select_stratified_prefix(items90: list[dict[str, Any]], k_per_stratum: int) -> list[dict[str, Any]]:
    assert 1 <= k_per_stratum <= K_MAX_STRATUM
    return (
        items90[0:k_per_stratum]
        + items90[K_MAX_STRATUM : K_MAX_STRATUM + k_per_stratum]
        + items90[2 * K_MAX_STRATUM : 2 * K_MAX_STRATUM + k_per_stratum]
    )


def _parse_int_choice(raw_text: str, n_classes: int) -> int:
    cleaned = raw_text.strip()
    m = re.search(r"\b([0-7])\b", cleaned)
    if m:
        v = int(m.group(1))
        if 0 <= v < n_classes:
            return v
    for ch in cleaned:
        if ch.isdigit():
            v = int(ch)
            if 0 <= v < n_classes:
                return v
    return 0


def _query_model_server(base_url: str, mode: str, prompt: str, n_classes: int) -> tuple[int, str, int, int]:
    if mode == "systemone":
        opts = {str(k): f"Class {k}" for k in range(n_classes)}
        payload = {
            "state": prompt,
            "questions": {
                "q0": {
                    "type": "choice",
                    "instructions": f"Select the correct integer ID from 0 to {n_classes - 1}.",
                    "criteria": opts,
                }
            },
        }
        req = urllib.request.Request(
            f"{base_url}/v1/systemone",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=240) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        choice_str = str(data["answers"]["q0"]["choice"])
        usage = data.get("usage", {})
        return (
            _parse_int_choice(choice_str, n_classes),
            choice_str,
            int(usage.get("input_tokens", 0)),
            int(usage.get("output_tokens", 0)),
        )

    if mode == "lfm3_completion_grammar":
        payload = {
            "prompt": (
                "<|im_start|>system\nOutput ONLY a single integer digit.<|im_end|>\n"
                f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n<think></think>"
            ),
            "grammar": f"root ::= [0-{n_classes - 1}]",
            "temperature": LLM_TEMP,
            "top_k": 1,
            "seed": LLM_SEED,
            "max_tokens": 2,
            "cache_prompt": False,
        }
        req = urllib.request.Request(
            f"{base_url}/v1/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=240) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        txt = str(data["choices"][0]["text"])
        usage = data.get("usage", {})
        return (
            _parse_int_choice(txt, n_classes),
            txt,
            int(usage.get("prompt_tokens", 0)),
            int(usage.get("completion_tokens", 0)),
        )

    if mode == "inkling_effort0_completion":
        payload = {
            "prompt": (
                "<|message_system|><|content_text|>Thinking effort level: 0<|end_message|>"
                "<|message_system|><|content_text|>Output ONLY a single integer digit.<|end_message|>"
                f"<|message_user|><|content_text|>{prompt}<|end_message|>"
                "<|message_model|><|content_text|>"
            ),
            "temperature": LLM_TEMP,
            "top_k": 1,
            "seed": LLM_SEED,
            "max_tokens": 4,
            "cache_prompt": False,
        }
        req = urllib.request.Request(
            f"{base_url}/v1/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=240) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        txt = str(data["choices"][0]["text"])
        usage = data.get("usage", {})
        return (
            _parse_int_choice(txt, n_classes),
            txt,
            int(usage.get("prompt_tokens", 0)),
            int(usage.get("completion_tokens", 0)),
        )

    payload = {
        "model": "sota-panel",
        "messages": [
            {"role": "system", "content": "Output ONLY a single integer digit with no explanation."},
            {"role": "user", "content": prompt},
        ],
        "reasoning_effort": "none",
        "chat_template_kwargs": {"enable_thinking": False, "reasoning_effort": "none"},
        "temperature": LLM_TEMP,
        "top_k": 1,
        "seed": LLM_SEED,
        "max_tokens": 8,
        "cache_prompt": False,
    }
    req = urllib.request.Request(
        f"{base_url}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=240) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    txt = str(data["choices"][0]["message"].get("content") or "")
    usage = data.get("usage", {})
    return (
        _parse_int_choice(txt, n_classes),
        txt,
        int(usage.get("prompt_tokens", 0)),
        int(usage.get("completion_tokens", 0)),
    )


class _MockPanelHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/health"):
            body = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        ln = int(self.headers.get("Content-Length", "0"))
        raw = json.loads(self.rfile.read(ln).decode("utf-8"))
        if self.path.startswith("/v1/systemone"):
            st = str(raw.get("state", ""))
            h = str(sum(ord(c) for c in st) % 2)
            reply = json.dumps(
                {
                    "answers": {"q0": {"type": "choice", "choice": h}},
                    "usage": {"input_tokens": 64, "output_tokens": 0},
                }
            ).encode("utf-8")
        elif self.path.startswith("/v1/completions"):
            pr = str(raw.get("prompt", ""))
            h = str(sum(ord(c) for c in pr) % 2)
            reply = json.dumps(
                {
                    "choices": [{"text": h}],
                    "usage": {"prompt_tokens": 64, "completion_tokens": 2},
                }
            ).encode("utf-8")
        else:
            user_msg = raw["messages"][-1]["content"]
            h = str(sum(ord(c) for c in user_msg) % 2)
            reply = json.dumps(
                {
                    "choices": [{"message": {"content": h}}],
                    "usage": {"prompt_tokens": 64, "completion_tokens": 2},
                }
            ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)


def _eval_classical_arms_for_k(
    lib: ctypes.CDLL,
    ctx: int,
    meter: EnergyMeter,
    k_per_stratum: int,
    mock_dry_run: bool,
) -> tuple[dict[str, Any], dict[str, list[int]]]:
    n_sub = 3 * k_per_stratum
    is_shunt = meter.board_metered
    c3_tmp = (ctypes.c_int * 3)()
    preds_c = (ctypes.c_uint8 * n_sub)()
    el_ns = ctypes.c_double()
    classical_res: dict[str, Any] = {}
    arm_preds: dict[str, list[int]] = {}
    n_arm_trials = 2 if mock_dry_run else (6 if is_shunt else 10)

    for sp in ARMS:
        def _probe_sub(aid: int = sp["id"]) -> None:
            lib.dnull_eval_arm_subset(ctx, aid, k_per_stratum, 1, c3_tmp, preds_c, ctypes.byref(el_ns))

        reps = meter.calibrate_reps(
            _probe_sub,
            default_reps=sp["default_reps"] * 8,
            quick_reps=sp["quick_reps"] * 4,
            quick=mock_dry_run,
            target_shunt_s=0.68,
        )
        lib.dnull_eval_arm_subset(ctx, sp["id"], k_per_stratum, 1, c3_tmp, preds_c, ctypes.byref(el_ns))
        arm_preds[sp["key"]] = [int(preds_c[i]) for i in range(n_sub)]

        ns_vals: list[float] = []
        gross_uj_vals: list[float] = []
        sec_uj_vals: list[float] = []
        pkg_uj_vals: list[float] = []
        win_s_vals: list[float] = []
        shunt_cnts: list[int] = []
        c_tot = 0

        for _ in range(n_arm_trials):
            s0 = meter.snapshot()
            lib.dnull_eval_arm_subset(ctx, sp["id"], k_per_stratum, reps, c3_tmp, None, ctypes.byref(el_ns))
            s1 = meter.snapshot() if not is_shunt else None
            d = meter.diff(s0, s1)
            c_list = [int(c3_tmp[0]), int(c3_tmp[1]), int(c3_tmp[2])]
            c_tot = sum(c_list)
            tot_corr = max(1, c_tot * reps)
            ns_vals.append(float(el_ns.value) / tot_corr)
            if d["primary_measured_j"] is not None:
                gross_uj_vals.append((float(d["primary_measured_j"]) * 1e6) / tot_corr)
                win_s_vals.append(float(d["wall_s"]))
                shunt_cnts.append(int(d["shunt_samples"]))
                if d["secondary_measured_j"] is not None:
                    sec_uj_vals.append((float(d["secondary_measured_j"]) * 1e6) / tot_corr)
            if d["pkg_reported_j"] is not None:
                pkg_uj_vals.append((float(d["pkg_reported_j"]) * 1e6) / tot_corr)

        classical_res[sp["key"]] = {
            "category": sp["category"],
            "reps_per_trial": reps,
            "n_instances": n_sub,
            "k_per_stratum": k_per_stratum,
            "correct": c_tot,
            "overall_accuracy": round(c_tot / n_sub, 4),
            "overall_accuracy_clopper_pearson_95ci": clopper_pearson_two_sided_95ci(c_tot, n_sub),
            "stratum_accuracy": {
                "bounded_api_dispatch": round(int(c3_tmp[0]) / k_per_stratum, 4),
                "combinatorial_constraint_3sat": round(int(c3_tmp[1]) / k_per_stratum, 4),
                "open_compositional_patch_triage": round(int(c3_tmp[2]) / k_per_stratum, 4),
            },
            "wall_ns_per_correct": iqr_stats(ns_vals, 2),
            "gross_rail_measured_uj_per_correct": iqr_stats(gross_uj_vals, 4) if gross_uj_vals else None,
            "secondary_carrier_measured_uj_per_correct": iqr_stats(sec_uj_vals, 4) if sec_uj_vals else None,
            "pkg_reported_uj_per_correct": iqr_stats(pkg_uj_vals, 4) if pkg_uj_vals else None,
            "_win_s_vals": win_s_vals,
            "_gross_uj_vals": gross_uj_vals,
            "shunt_samples_median": int(iqr_stats([float(c) for c in shunt_cnts], 0)["median"]) if shunt_cnts else 0,
        }
    return classical_res, arm_preds


def run_real_llm_crystallization_eval(
    llama_server_bin: Path | None = None,
    models_dir: Path | None = None,
    model_keys: list[str] | None = None,
    k_per_stratum_default: int = 30,
    k_overrides: dict[str, int] | None = None,
    stream_teacher_key: str | None = None,
    threads: int | None = None,
    ctx_size: int = 1024,
    delete_gguf_after_eval: bool = False,
    mock_dry_run: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    lib = compile_and_load_dnull_lib()
    meter = EnergyMeter()
    is_shunt = meter.board_metered
    host = sanitized_host_info()
    n_threads = threads or min(16, max(2, os.cpu_count() or 4))
    k_overrides = k_overrides or {}

    if mock_dry_run:
        selected_keys = model_keys or ["lfm3_1_7b", "d1_2b_systemone"]
    else:
        selected_keys = model_keys or [m["key"] for m in OCT_NOV_2026_PANEL]
    for mk in selected_keys:
        if mk not in PANEL_BY_KEY:
            raise ValueError(f"Unknown panel model key: {mk}")
        assert PANEL_BY_KEY[mk]["release_date_utc"] >= "2026-10-12", f"Model older than 45-day window: {mk}"

    idle_pre = meter.sample_idle_baseline(0.15 if mock_dry_run else (1.0 if is_shunt else 0.25)) if meter.available else None

    ctx = lib.dnull_init()
    if not ctx:
        meter.close()
        raise RuntimeError("dnull_init failed")

    mock_httpd: HTTPServer | None = None
    try:
        items90, subset90_sha256, subset90_blake3, cue_str = _build_subset90_prompts(lib, ctx)

        distinct_ks = sorted({k_per_stratum_default} | {k_overrides.get(mk, k_per_stratum_default) for mk in selected_keys})
        classical_by_k: dict[int, dict[str, Any]] = {}
        arm_preds_by_k: dict[int, dict[str, list[int]]] = {}
        for kv in distinct_ks:
            cl_r, ap_r = _eval_classical_arms_for_k(lib, ctx, meter, kv, mock_dry_run)
            classical_by_k[kv] = cl_r
            arm_preds_by_k[kv] = ap_r

        if mock_dry_run:
            m_port = _free_local_port()
            mock_httpd = HTTPServer(("127.0.0.1", m_port), _MockPanelHandler)
            threading.Thread(target=mock_httpd.serve_forever, daemon=True).start()
            mock_base_url = f"http://127.0.0.1:{m_port}"
        else:
            mock_base_url = ""
            assert llama_server_bin is not None and llama_server_bin.is_file(), f"Missing llama-server: {llama_server_bin}"
            assert models_dir is not None and models_dir.is_dir(), f"Missing models_dir: {models_dir}"

        chosen_teacher = stream_teacher_key or selected_keys[-1]
        if chosen_teacher not in selected_keys:
            chosen_teacher = selected_keys[0]

        panel_results: dict[str, Any] = {}
        raw_t1_preds_by_model: dict[str, tuple[int, list[int], list[dict[str, Any]]]] = {}
        pooled_spot_runs = 0
        pooled_spot_divergences = 0

        k_stream = k_overrides.get(chosen_teacher, k_per_stratum_default)
        items_stream_base = _select_stratified_prefix(items90, k_stream)
        n_stream_base = len(items_stream_base)

        api_all = (ctypes.c_int16 * (50 * 8))()
        sat_all = (ctypes.c_int8 * (50 * 48 * 3))()
        tri_sigs_all = (ctypes.c_uint32 * 50)()
        tri_x_all = (ctypes.c_int8 * (50 * 32))()
        labels_150 = (ctypes.c_uint8 * 150)()
        centroids_150 = (ctypes.c_float * (8 * 32))()
        lib.dnull_export_subset_details(ctx, 50, api_all, sat_all, tri_sigs_all, tri_x_all, labels_150, centroids_150)

        c3_150 = (ctypes.c_int * 3)()
        shd_preds_150 = (ctypes.c_uint8 * 150)()
        el_ns_tmp = ctypes.c_double()
        lib.dnull_eval_arm_subset(ctx, 5, 50, 1, c3_150, shd_preds_150, ctypes.byref(el_ns_tmp))

        rng = random.Random(LLM_SEED)
        z_weights = [1.0 / ((r + 1) ** 0.85) for r in range(n_stream_base)]
        z_tot = sum(z_weights)
        z_cdf: list[float] = []
        acc_z = 0.0
        for w in z_weights:
            acc_z += w / z_tot
            z_cdf.append(acc_z)

        stream_n = 40 if mock_dry_run else 300
        stream_events: list[dict[str, Any]] = []
        for step in range(stream_n):
            if (step % 100) < 85:
                u = rng.random()
                pick = next((idx for idx, cut in enumerate(z_cdf) if u <= cut), n_stream_base - 1)
                it = items_stream_base[pick]
                s_idx = pick // k_stream
                local_i = pick % k_stream
                shd_p = int(shd_preds_150[s_idx * 50 + local_i])
                stream_events.append(
                    {
                        "key": int(it["canonical_key_u32"]),
                        "stratum": it["stratum"],
                        "n_classes": it["n_classes"],
                        "prompt": it["prompt"],
                        "shd_pred": shd_p,
                        "label": it["label"],
                        "was_in_t1": True,
                    }
                )
            else:
                s_idx = step % 3
                local_i = 30 + ((step // 3) % 20)
                lbl = int(labels_150[s_idx * 50 + local_i])
                shd_p = int(shd_preds_150[s_idx * 50 + local_i])
                if s_idx == 0:
                    f = [int(api_all[local_i * 8 + j]) for j in range(8)]
                    kh = _fnv1a32(str(f).encode("ascii"))
                    pr = f"Gateway request {f}. Reply ONLY with digit 0..7:"
                    nc, st_name = 8, "bounded_api_dispatch"
                elif s_idx == 1:
                    kh = 0xD0000000 + local_i
                    pr = "Decide 3-SAT (0 or 1). Reply ONLY with digit 0 or 1:"
                    nc, st_name = 2, "combinatorial_constraint_3sat"
                else:
                    xv = [int(tri_x_all[local_i * 32 + d]) for d in range(12)]
                    sig = int(tri_sigs_all[local_i])
                    kh = sig if sig != 0 else (0xE0000000 + local_i)
                    pr = (
                        "Classify AST/crash telemetry into patch template 0..7. "
                        f"Rule: if ch0>=100->0, ch1>=100->1, ch2>=100->2, ch3>=100->3; else match nearest prototype ({cue_str}).\n"
                        f"CrashSig=0x{sig:08x} ch0..11={xv}\n"
                        "Reply ONLY with the single digit patch ID (0..7):"
                    )
                    nc, st_name = 8, "open_compositional_patch_triage"
                stream_events.append(
                    {
                        "key": kh,
                        "stratum": st_name,
                        "n_classes": nc,
                        "prompt": pr,
                        "shd_pred": shd_p,
                        "label": lbl,
                        "was_in_t1": False,
                    }
                )

        d_stream: dict[str, Any] | None = None
        stream_correct = 0
        stream_stage_counts = {"stage1_crystallized_lut": 0, "stage2_classical_solver": 0, "stage3_live_llm_escalated": 0}

        ordered_keys = [mk for mk in selected_keys if mk != chosen_teacher] + [chosen_teacher]

        for mk in ordered_keys:
            spec = PANEL_BY_KEY[mk]
            k_m = k_overrides.get(mk, k_per_stratum_default)
            items_m = _select_stratified_prefix(items90, k_m)
            n_m = len(items_m)
            labels_m = [it["label"] for it in items_m]
            sub_m_sha256 = hashlib.sha256(
                json.dumps(items_m, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()

            srv_proc: subprocess.Popen[str] | None = None
            gguf_file: Path | None = None
            try:
                if mock_dry_run:
                    base_url = mock_base_url
                    gguf_sha = "mock_dry_run_no_weights"
                    gguf_bytes = 0
                else:
                    assert models_dir is not None and llama_server_bin is not None
                    gguf_file = models_dir / spec["gguf_filename"]
                    assert gguf_file.is_file(), f"Missing GGUF file: {gguf_file}"
                    h_obj = hashlib.sha256()
                    with gguf_file.open("rb") as fh:
                        while chunk := fh.read(8 * 1024 * 1024):
                            h_obj.update(chunk)
                    gguf_sha = h_obj.hexdigest()
                    assert gguf_sha == spec["expected_sha256"], f"SHA-256 mismatch for {mk}: {gguf_sha}"
                    gguf_bytes = gguf_file.stat().st_size

                    port = _free_local_port()
                    base_url = f"http://127.0.0.1:{port}"
                    srv_proc = subprocess.Popen(
                        [
                            str(llama_server_bin),
                            "-m",
                            str(gguf_file),
                            "--host",
                            "127.0.0.1",
                            "--port",
                            str(port),
                            "-ngl",
                            "0",
                            "-t",
                            str(n_threads),
                            "-c",
                            str(ctx_size),
                            *spec["server_extra_args"],
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        text=True,
                    )
                    ready = False
                    for _ in range(300):
                        if srv_proc.poll() is not None:
                            raise RuntimeError(f"llama-server exited early ({srv_proc.returncode}) for {mk}")
                        try:
                            with urllib.request.urlopen(f"{base_url}/health", timeout=1) as hr:
                                if hr.status == 200:
                                    ready = True
                                    break
                        except Exception:
                            time.sleep(0.3)
                    if not ready:
                        raise RuntimeError(f"llama-server failed healthcheck for {mk}")

                    _query_model_server(base_url, spec["mode"], items_m[0]["prompt"], items_m[0]["n_classes"])

                preds_m: list[int] = []
                p_tok_tot = 0
                c_tok_tot = 0
                s0_m = meter.snapshot()
                for it in items_m:
                    pred, _, pt, ct = _query_model_server(base_url, spec["mode"], it["prompt"], it["n_classes"])
                    preds_m.append(pred)
                    p_tok_tot += pt
                    c_tok_tot += ct
                s1_m = meter.snapshot() if not is_shunt else None
                d_m = meter.diff(s0_m, s1_m)

                spot_k = 2 if mock_dry_run else min(3, n_m)
                spot_div = 0
                spot_indices = [0, k_m, 2 * k_m][:spot_k]
                for s_i in spot_indices:
                    it_s = items_m[s_i]
                    p2, _, _, _ = _query_model_server(base_url, spec["mode"], it_s["prompt"], it_s["n_classes"])
                    if p2 != preds_m[s_i]:
                        spot_div += 1
                pooled_spot_runs += len(spot_indices)
                pooled_spot_divergences += spot_div

                raw_t1_preds_by_model[mk] = (k_m, preds_m, items_m)

                c_api = sum(1 for a, b in zip(preds_m[0:k_m], labels_m[0:k_m]) if a == b)
                c_sat = sum(1 for a, b in zip(preds_m[k_m : 2 * k_m], labels_m[k_m : 2 * k_m]) if a == b)
                c_tri = sum(1 for a, b in zip(preds_m[2 * k_m : 3 * k_m], labels_m[2 * k_m : 3 * k_m]) if a == b)
                c_tot_m = c_api + c_sat + c_tri

                shd_preds_m = arm_preds_by_k[k_m]["shape_d_classical_best"]
                paired_overall = paired_candidate_vs_null_stats(preds_m, shd_preds_m, labels_m)
                paired_strata = {
                    "bounded_api_dispatch": paired_candidate_vs_null_stats(
                        preds_m[0:k_m], shd_preds_m[0:k_m], labels_m[0:k_m]
                    ),
                    "combinatorial_constraint_3sat": paired_candidate_vs_null_stats(
                        preds_m[k_m : 2 * k_m], shd_preds_m[k_m : 2 * k_m], labels_m[k_m : 2 * k_m]
                    ),
                    "open_compositional_patch_triage": paired_candidate_vs_null_stats(
                        preds_m[2 * k_m : 3 * k_m], shd_preds_m[2 * k_m : 3 * k_m], labels_m[2 * k_m : 3 * k_m]
                    ),
                }

                panel_results[mk] = {
                    "tier": spec["tier"],
                    "display_name": spec["display_name"],
                    "hf_repo_and_file": f"{spec['hf_repo']}/{spec['gguf_filename']}",
                    "release_date_utc": spec["release_date_utc"],
                    "gguf_arch": spec["gguf_arch"],
                    "params_summary": spec["params_summary"],
                    "inference_mode": spec["mode"],
                    "gguf_sha256": gguf_sha,
                    "gguf_size_bytes": gguf_bytes,
                    "n_instances": n_m,
                    "k_per_stratum": k_m,
                    "evaluated_subset_sha256": sub_m_sha256,
                    "correct": c_tot_m,
                    "overall_accuracy": round(c_tot_m / n_m, 4),
                    "overall_accuracy_clopper_pearson_95ci": clopper_pearson_two_sided_95ci(c_tot_m, n_m),
                    "stratum_correct": {
                        "bounded_api_dispatch": c_api,
                        "combinatorial_constraint_3sat": c_sat,
                        "open_compositional_patch_triage": c_tri,
                    },
                    "stratum_accuracy": {
                        "bounded_api_dispatch": round(c_api / k_m, 4),
                        "combinatorial_constraint_3sat": round(c_sat / k_m, 4),
                        "open_compositional_patch_triage": round(c_tri / k_m, 4),
                    },
                    "stratum_clopper_pearson_95ci": {
                        "bounded_api_dispatch": clopper_pearson_two_sided_95ci(c_api, k_m),
                        "combinatorial_constraint_3sat": clopper_pearson_two_sided_95ci(c_sat, k_m),
                        "open_compositional_patch_triage": clopper_pearson_two_sided_95ci(c_tri, k_m),
                    },
                    "prompt_tokens_total": p_tok_tot,
                    "completion_tokens_total": c_tok_tot,
                    "spot_check_runs": len(spot_indices),
                    "spot_check_divergences": spot_div,
                    "paired_vs_shape_d_on_identical_subset": {
                        "overall": paired_overall,
                        "by_stratum": paired_strata,
                    },
                    "_raw_diff": d_m,
                }

                if mk == chosen_teacher:
                    online_lut: dict[int, int] = {}
                    for prev_mk, (prev_k, prev_preds, prev_items) in raw_t1_preds_by_model.items():
                        for it_p, pr_p in zip(prev_items, prev_preds):
                            if pr_p == it_p["label"] and len(online_lut) < 512:
                                online_lut[int(it_p["canonical_key_u32"])] = int(pr_p)
                    for idx_b, it_b in enumerate(items_stream_base):
                        if it_b["stratum"] in ("bounded_api_dispatch", "combinatorial_constraint_3sat"):
                            s_idx = idx_b // k_stream
                            loc = idx_b % k_stream
                            sp_v = int(shd_preds_150[s_idx * 50 + loc])
                            if sp_v == it_b["label"] and len(online_lut) < 512:
                                online_lut[int(it_b["canonical_key_u32"])] = sp_v

                    s0_stream = meter.snapshot()
                    for ev in stream_events:
                        kh = ev["key"]
                        if kh in online_lut:
                            pred_s = online_lut[kh]
                            stream_stage_counts["stage1_crystallized_lut"] += 1
                        elif ev["stratum"] in ("bounded_api_dispatch", "combinatorial_constraint_3sat"):
                            pred_s = ev["shd_pred"]
                            stream_stage_counts["stage2_classical_solver"] += 1
                            if pred_s == ev["label"] and len(online_lut) < 512:
                                online_lut[kh] = pred_s
                        else:
                            pred_s, _, _, _ = _query_model_server(base_url, spec["mode"], ev["prompt"], ev["n_classes"])
                            stream_stage_counts["stage3_live_llm_escalated"] += 1
                            if pred_s == ev["label"] and len(online_lut) < 512:
                                online_lut[kh] = pred_s
                        if pred_s == ev["label"]:
                            stream_correct += 1
                    s1_stream = meter.snapshot() if not is_shunt else None
                    d_stream = meter.diff(s0_stream, s1_stream)

            finally:
                if srv_proc is not None:
                    srv_proc.terminate()
                    try:
                        srv_proc.wait(timeout=5)
                    except Exception:
                        srv_proc.kill()
                if delete_gguf_after_eval and gguf_file is not None and gguf_file.exists():
                    gguf_file.unlink()

        teacher_k, teacher_preds, teacher_items = raw_t1_preds_by_model[chosen_teacher]
        single_keys: list[int] = []
        single_vals: list[int] = []
        for it_t, pr_t in zip(teacher_items, teacher_preds):
            if pr_t == it_t["label"]:
                single_keys.append(int(it_t["canonical_key_u32"]))
                single_vals.append(int(pr_t))

        union_map: dict[int, int] = {}
        for _, (_, m_preds, m_items) in raw_t1_preds_by_model.items():
            for it_m, pr_m in zip(m_items, m_preds):
                if pr_m == it_m["label"]:
                    union_map[int(it_m["canonical_key_u32"])] = int(pr_m)
        teacher_key_set = {int(it["canonical_key_u32"]) for it in teacher_items}
        union_keys = [k for k in union_map if k in teacher_key_set]
        union_vals = [union_map[k] for k in union_keys]

        qh_c = (ctypes.c_uint32 * n_stream_base)(*(int(it["canonical_key_u32"]) for it in teacher_items))
        fb_c = (ctypes.c_uint8 * n_stream_base)(*arm_preds_by_k[teacher_k]["shape_d_classical_best"])
        lb_c = (ctypes.c_uint8 * n_stream_base)(*(int(it["label"]) for it in teacher_items))

        ck_single = (ctypes.c_uint32 * max(1, len(single_keys)))(*(single_keys or [1]))
        cv_single = (ctypes.c_uint8 * max(1, len(single_vals)))(*(single_vals or [0]))
        hits_single = ctypes.c_int()
        lut_ns_single = ctypes.c_double()
        single_t2_corr = lib.dnull_eval_crystallized_lut_batch(
            ck_single, cv_single, len(single_keys), qh_c, fb_c, lb_c, n_stream_base, 1, ctypes.byref(hits_single), ctypes.byref(lut_ns_single)
        )

        ck_union = (ctypes.c_uint32 * max(1, len(union_keys)))(*(union_keys or [1]))
        cv_union = (ctypes.c_uint8 * max(1, len(union_vals)))(*(union_vals or [0]))
        hits_union = ctypes.c_int()
        lut_ns_union = ctypes.c_double()

        def _probe_union_lut() -> None:
            lib.dnull_eval_crystallized_lut_batch(
                ck_union, cv_union, len(union_keys), qh_c, fb_c, lb_c, n_stream_base, 100, ctypes.byref(hits_union), ctypes.byref(lut_ns_union)
            )

        cryst_chunks = meter.calibrate_reps(_probe_union_lut, default_reps=2500, quick_reps=20, quick=mock_dry_run, target_shunt_s=0.68)
        cryst_reps = cryst_chunks * 100
        s0_lut = meter.snapshot()
        union_t2_corr = lib.dnull_eval_crystallized_lut_batch(
            ck_union, cv_union, len(union_keys), qh_c, fb_c, lb_c, n_stream_base, cryst_reps, ctypes.byref(hits_union), ctypes.byref(lut_ns_union)
        )
        s1_lut = meter.snapshot() if not is_shunt else None
        d_lut = meter.diff(s0_lut, s1_lut)

    finally:
        if mock_httpd is not None:
            mock_httpd.shutdown()
            mock_httpd.server_close()
        lib.dnull_free(ctx)

    idle_post = meter.sample_idle_baseline(0.15 if mock_dry_run else (1.0 if is_shunt else 0.25)) if meter.available else None
    telemetry_meta = meter.metadata(idle_pre, idle_post)
    meter.close()

    f6_flag = bool(telemetry_meta.get("falsifier_6_idle_drift_flag", False))
    mean_idle_w = telemetry_meta.get("idle_trimmed_mean_w")

    for kv, cl_dict in classical_by_k.items():
        for _, rec in cl_dict.items():
            ws_list = rec.pop("_win_s_vals")
            gj_list = rec.pop("_gross_uj_vals")
            if is_shunt and (not f6_flag) and mean_idle_w is not None and gj_list:
                net_list = []
                tot_c = max(1, rec["correct"] * rec["reps_per_trial"])
                for gj_uj, ws in zip(gj_list, ws_list):
                    gross_j = (gj_uj * tot_c) * 1e-6
                    net_list.append((max(0.0, gross_j - float(mean_idle_w) * ws) * 1e6) / tot_c)
                rec["net_above_idle_a1_a2_measured_uj_per_correct"] = iqr_stats(net_list, 4)
            else:
                rec["net_above_idle_a1_a2_measured_uj_per_correct"] = None
            rec["net_above_idle_a1_a2_withheld_per_falsifier_6"] = bool(is_shunt and f6_flag)

    def _energy_summary(d: dict[str, Any], tot_corr: int) -> dict[str, Any]:
        tc = max(1, tot_corr)
        gross_uj = round((float(d["primary_measured_j"]) * 1e6) / tc, 4) if d["primary_measured_j"] is not None else None
        net_a12_uj = None
        if is_shunt and (not f6_flag) and mean_idle_w is not None and d["primary_measured_j"] is not None:
            net_j = max(0.0, float(d["primary_measured_j"]) - float(mean_idle_w) * float(d["wall_s"]))
            net_a12_uj = round((net_j * 1e6) / tc, 4)
        sec_uj = round((float(d["secondary_measured_j"]) * 1e6) / tc, 4) if d["secondary_measured_j"] is not None else None
        pkg_uj = round((float(d["pkg_reported_j"]) * 1e6) / tc, 4) if d["pkg_reported_j"] is not None else None
        core_uj = round((float(d["core_reported_j"]) * 1e6) / tc, 4) if d["core_reported_j"] is not None else None
        return {
            "evidence_class": meter.evidence_class,
            "wall_ms_total": d["wall_ms"],
            "wall_us_per_correct": round((d["wall_ns"] / 1e3) / tc, 3),
            "gross_rail_measured_uj_per_correct": gross_uj,
            "net_above_idle_a1_a2_measured_uj_per_correct": net_a12_uj,
            "net_above_idle_a1_a2_withheld_per_falsifier_6": bool(is_shunt and f6_flag),
            "secondary_carrier_measured_uj_per_correct": sec_uj,
            "shunt_samples": int(d["shunt_samples"]),
            "pkg_reported_uj_per_correct": pkg_uj,
            "core_reported_uj_per_correct": core_uj,
        }

    ordered_panel_out: dict[str, Any] = {}
    for mk in selected_keys:
        mrec = panel_results[mk]
        d_m = mrec.pop("_raw_diff")
        e_m = _energy_summary(d_m, mrec["correct"])
        mrec["energy_and_latency"] = e_m

        k_m = mrec["k_per_stratum"]
        shd_rec = classical_by_k[k_m]["shape_d_classical_best"]
        lut_rec = classical_by_k[k_m]["arm1_lookup_table"]
        same_meter: dict[str, Any] = {"evidence_class": meter.evidence_class}
        if meter.evidence_class == "measured_j":
            llm_e = float(e_m["gross_rail_measured_uj_per_correct"])
            shd_e = float(shd_rec["gross_rail_measured_uj_per_correct"]["median"])
            lut_e = float(lut_rec["gross_rail_measured_uj_per_correct"]["median"])
            same_meter["cold_llm_over_shape_d_classical_x"] = round(llm_e / shd_e, 2) if shd_e > 0 else None
            same_meter["cold_llm_over_stage1_lut_x"] = round(llm_e / lut_e, 2) if lut_e > 0 else None
        elif meter.evidence_class == "reported_j":
            llm_e = float(e_m["pkg_reported_uj_per_correct"])
            shd_e = float(shd_rec["pkg_reported_uj_per_correct"]["median"])
            lut_e = float(lut_rec["pkg_reported_uj_per_correct"]["median"])
            same_meter["cold_llm_over_shape_d_classical_x"] = round(llm_e / shd_e, 2) if shd_e > 0 else None
            same_meter["cold_llm_over_stage1_lut_x"] = round(llm_e / lut_e, 2) if lut_e > 0 else None
        mrec["same_meter_energy_ratios"] = same_meter
        ordered_panel_out[mk] = mrec

    assert d_stream is not None
    lut_t2_energy = _energy_summary(d_lut, max(1, union_t2_corr * cryst_reps))
    stream_energy = _energy_summary(d_stream, stream_correct)

    teacher_e_rec = ordered_panel_out[chosen_teacher]["energy_and_latency"]
    stream_ratios: dict[str, Any] = {"evidence_class": meter.evidence_class, "stage3_live_teacher": chosen_teacher}
    if meter.evidence_class == "measured_j":
        te_uj = float(teacher_e_rec["gross_rail_measured_uj_per_correct"])
        st_uj = float(stream_energy["gross_rail_measured_uj_per_correct"])
        t2_uj = float(lut_t2_energy["gross_rail_measured_uj_per_correct"])
        stream_ratios["cold_teacher_over_zipf085_stream_gross_x"] = round(te_uj / st_uj, 2) if st_uj > 0 else None
        stream_ratios["cold_teacher_over_crystallized_t2_replay_gross_x"] = round(te_uj / t2_uj, 2) if t2_uj > 0 else None
        if teacher_e_rec["net_above_idle_a1_a2_measured_uj_per_correct"] and stream_energy["net_above_idle_a1_a2_measured_uj_per_correct"]:
            tn_uj = float(teacher_e_rec["net_above_idle_a1_a2_measured_uj_per_correct"])
            sn_uj = float(stream_energy["net_above_idle_a1_a2_measured_uj_per_correct"])
            stream_ratios["cold_teacher_over_zipf085_stream_net_a1_a2_x"] = round(tn_uj / sn_uj, 2) if sn_uj > 0 else None
    elif meter.evidence_class == "reported_j":
        te_uj = float(teacher_e_rec["pkg_reported_uj_per_correct"])
        st_uj = float(stream_energy["pkg_reported_uj_per_correct"])
        t2_uj = float(lut_t2_energy["pkg_reported_uj_per_correct"])
        stream_ratios["cold_teacher_over_zipf085_stream_pkg_x"] = round(te_uj / st_uj, 2) if st_uj > 0 else None
        stream_ratios["cold_teacher_over_crystallized_t2_replay_pkg_x"] = round(te_uj / t2_uj, 2) if t2_uj > 0 else None

    results: dict[str, Any] = {
        "schema": "openie.deterministic_null_sota_panel_crystallization.v2",
        "kit_id": "kits/deterministic-null-suite/oct-nov-2026-sota-llm-crystallization",
        "provenance_tier": "Signed Provenance · Self-Checked",
        "license": "Apache-2.0",
        "panel_recency_window": {
            "window_start_utc": "2026-10-12",
            "window_end_utc": "2026-11-26",
            "max_age_days": 45,
            "llama_cpp_commit": "436d7e8 (2026-11-26 mainline HEAD, CPU-only -ngl 0)",
            "cpu_threads": n_threads,
            "temperature": LLM_TEMP,
            "seed": LLM_SEED,
            "pooled_spot_check_runs": pooled_spot_runs,
            "pooled_spot_check_divergences": pooled_spot_divergences,
            "clopper_pearson_95_upper_bound_divergence": round(
                clopper_pearson_upper(pooled_spot_divergences, pooled_spot_runs), 6
            ),
        },
        "host": host,
        "energy_telemetry": telemetry_meta,
        "confirmatory_subset_precommitment": {
            "subset90_n_instances_total": N_SUBSET_MAX,
            "subset90_instances_per_stratum": K_MAX_STRATUM,
            "subset90_prompts_and_labels_sha256": subset90_sha256,
            "subset90_prompts_and_labels_blake3": subset90_blake3,
            "lut_cap_bytes": LUT_CAP_BYTES,
        },
        "classical_arms_by_k_per_stratum": {f"k_{kv}_n_{3 * kv}": classical_by_k[kv] for kv in distinct_ks},
        "oct_nov_2026_sota_panel_cold_t1": ordered_panel_out,
        "verified_downward_crystallization_t2": {
            "scope_note": (
                "Stage-1 <= 4 KiB LUT hits measure exact content-addressed recall on recurring verified inputs "
                "(C(x, z) == 1), NOT unseen cold generalization; unseen structured/constraint arrivals route to "
                "Stage-2 classical rules/DPLL and unseen open triage arrivals escalate to the live Stage-3 teacher."
            ),
            "stage3_teacher_key": chosen_teacher,
            "n_base_instances": n_stream_base,
            "single_teacher_t2_replay_with_shape_d_fallback": {
                "verified_admissions_t1": len(single_keys),
                "lut_hits": int(hits_single.value),
                "correct": int(single_t2_corr),
                "accuracy": round(int(single_t2_corr) / n_stream_base, 4),
                "clopper_pearson_95ci": clopper_pearson_two_sided_95ci(int(single_t2_corr), n_stream_base),
            },
            "multi_teacher_union_t2_replay_with_shape_d_fallback": {
                "teachers_unioned": list(selected_keys),
                "verified_admissions_union": len(union_keys),
                "lut_hits": int(hits_union.value),
                "correct": int(union_t2_corr),
                "accuracy": round(int(union_t2_corr) / n_stream_base, 4),
                "clopper_pearson_95ci": clopper_pearson_two_sided_95ci(int(union_t2_corr), n_stream_base),
                "reps_measured": cryst_reps,
                "energy_and_latency": lut_t2_energy,
            },
            "compiled_agency_zipf085_live_stream": {
                "stream_queries": stream_n,
                "zipf_skew_s": 0.85,
                "recurring_fraction": 0.85,
                "unseen_cold_arrival_fraction": 0.15,
                "stage_routing_counts": stream_stage_counts,
                "stage_routing_fractions": {k: round(v / stream_n, 4) for k, v in stream_stage_counts.items()},
                "correct": stream_correct,
                "accuracy": round(stream_correct / stream_n, 4),
                "clopper_pearson_95ci": clopper_pearson_two_sided_95ci(stream_correct, stream_n),
                "energy_and_latency": stream_energy,
                "same_meter_energy_ratios_vs_cold_teacher": stream_ratios,
            },
        },
    }

    receipt = seal_signed_receipt(
        kit_id="kits/deterministic-null-suite/oct-nov-2026-sota-llm-crystallization",
        payload={
            "substrate_id": telemetry_meta.get("substrate_id"),
            "models_evaluated": list(selected_keys),
            "stage3_teacher_key": chosen_teacher,
            "subset90_sha256": subset90_sha256,
            "energy_evidence_class": meter.evidence_class,
            "pooled_spot_check_runs": pooled_spot_runs,
            "pooled_spot_check_divergences": pooled_spot_divergences,
            "results_blake3": blake3_derive_key_hex(
                "openie.kit.dnull_sota_panel.results.v2",
                json.dumps(results, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            ),
        },
        domain_context="openie.kit.dnull_sota_panel.receipt.v2",
    )
    assert verify_signed_receipt(receipt)
    md = _render_md_single(results, receipt)
    return results, receipt, md


def _render_md_single(res: dict[str, Any], receipt: dict[str, Any]) -> str:
    tel = res["energy_telemetry"]
    e_key = "gross_rail_measured_uj_per_correct" if tel["evidence_class"] == "measured_j" else "pkg_reported_uj_per_correct"
    lines = [
        "# Oct–Nov 2026 Open-Weight SOTA Panel + Verified Crystallization Receipt",
        "",
        f"- **Host:** `{res['host']['cpu_model']}` (`{tel['evidence_class']}`, `board_metered={tel.get('board_metered')}`)",
        "",
        "| Model (`Oct–Nov 2026`) | Release | `N` | API | 3-SAT | Triage | Overall Acc (`95% CI`) | Energy `µJ/correct` (`x Shape D`) |",
        "|---|---|---:|---:|---:|---:|---|---:|",
    ]
    for mk, m in res["oct_nov_2026_sota_panel_cold_t1"].items():
        sa = m["stratum_accuracy"]
        ci = m["overall_accuracy_clopper_pearson_95ci"]
        e_val = m["energy_and_latency"][e_key]
        rx = m["same_meter_energy_ratios"].get("cold_llm_over_shape_d_classical_x")
        lines.append(
            f"| `{m['display_name']}` | `{m['release_date_utc']}` | `{m['n_instances']}` | "
            f"`{100*sa['bounded_api_dispatch']:.1f}%` | `{100*sa['combinatorial_constraint_3sat']:.1f}%` | `{100*sa['open_compositional_patch_triage']:.1f}%` | "
            f"**`{100*m['overall_accuracy']:.2f}%`** (`[{100*ci[0]:.1f}%, {100*ci[1]:.1f}%]`) | **`{e_val}`** (`{rx}x`) |"
        )
    cryst = res["verified_downward_crystallization_t2"]
    st = cryst["compiled_agency_zipf085_live_stream"]
    lines.extend(
        [
            "",
            f"- **Multi-Teacher Union `t=2` Replay:** Acc = **`{100*cryst['multi_teacher_union_t2_replay_with_shape_d_fallback']['accuracy']:.2f}%`** (`{cryst['multi_teacher_union_t2_replay_with_shape_d_fallback']['verified_admissions_union']}` verified admissions)",
            f"- **Compiled Agency `Zipf(0.85)` Live Stream (`{st['stream_queries']}` queries, Stage-3 `{cryst['stage3_teacher_key']}`):** Acc = **`{100*st['accuracy']:.2f}%`**, Energy = **`{st['energy_and_latency'][e_key]} µJ/correct`**, Ratios = `{st['same_meter_energy_ratios_vs_cold_teacher']}`, Stages = `{st['stage_routing_counts']}`",
            f"- **Signed Receipt:** `{receipt['body_blake3'][:24]}...` (`PASS`)",
            "",
        ]
    )
    return "\n".join(lines)


def _parse_k_overrides(spec_str: str) -> dict[str, int]:
    out: dict[str, int] = {}
    if not spec_str.strip():
        return out
    for part in spec_str.split(","):
        k, v = part.strip().split("=")
        out[k.strip()] = int(v.strip())
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Benchmark Oct-Nov 2026 Open-Weight SOTA Panel + Verified Crystallization")
    ap.add_argument("--llama-server-bin", type=Path, default=None)
    ap.add_argument("--models-dir", type=Path, default=None)
    ap.add_argument("--models", type=str, default="", help="Comma-separated model keys (default: all 6)")
    ap.add_argument("--k-per-stratum", type=int, default=30, help="Default instances per stratum (30 -> N=90, 15 -> N=45)")
    ap.add_argument("--k-overrides", type=str, default="", help="Per-model k overrides e.g. ternary_bonsai_2_5_27b=15")
    ap.add_argument("--stream-teacher", type=str, default="", help="Model key for Stage-3 live Zipf(0.85) escalation")
    ap.add_argument("--threads", type=int, default=None)
    ap.add_argument("--ctx-size", type=int, default=1024)
    ap.add_argument("--delete-gguf-after-eval", action="store_true")
    ap.add_argument("--mock-dry-run", action="store_true")
    ap.add_argument("--out-dir", type=Path, default=KIT_ROOT / "results")
    ap.add_argument("--tag", type=str, default="real_llm")
    args = ap.parse_args()

    srv_bin = args.llama_server_bin
    if not args.mock_dry_run and srv_bin is None:
        found = os.environ.get("LLAMA_SERVER_BIN") or shutil.which("llama-server")
        if found:
            srv_bin = Path(found)

    mkeys = [x.strip() for x in args.models.split(",") if x.strip()] or None
    kov = _parse_k_overrides(args.k_overrides)

    res, rec, md = run_real_llm_crystallization_eval(
        llama_server_bin=srv_bin,
        models_dir=args.models_dir,
        model_keys=mkeys,
        k_per_stratum_default=args.k_per_stratum,
        k_overrides=kov,
        stream_teacher_key=args.stream_teacher or None,
        threads=args.threads,
        ctx_size=args.ctx_size,
        delete_gguf_after_eval=args.delete_gguf_after_eval,
        mock_dry_run=args.mock_dry_run,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    res_json = json.dumps(res, indent=2) + "\n"
    rec_json = json.dumps(rec, indent=2) + "\n"
    assert_sanitized(res_json)
    assert_sanitized(rec_json)
    assert_sanitized(md)

    (args.out_dir / f"results_{args.tag}.json").write_text(res_json, encoding="utf-8")
    (args.out_dir / f"receipt_{args.tag}.json").write_text(rec_json, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
