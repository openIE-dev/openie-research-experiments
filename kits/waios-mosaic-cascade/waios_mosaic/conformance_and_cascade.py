#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Kit 5 (`kits/waios-mosaic-cascade/`, Shots on Goal #3, #5 & #6):
1. Cross-Lane `waiOS` 256x128 Integer/Ternary Conformance & Fault-Injection Halt
   sealed by canonical BLAKE3 digest `a541323b13653ed36515ff24ef08deb7dfa771e570a434712708fb72552f46f0`
   across x86_64, ARMv9 (Jetson AGX Thor), and ARM Cortex-A53 (AMD Kria KV260).
2. End-to-End 4-Stage Spellcheck Lookup-First Cascade (`1,000` mixed recurring + novel queries)
   plus 75-cell `(Zipf s, d_max, margin tau)` cascade grid sweep metered on Physical DC Shunt
   Board Rails (`measured_j`) and Linux RAPL (`reported_j`), strictly separated from analytical `est_j`.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import platform
import random
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
KIT_ROOT = HERE.parent
if str(KIT_ROOT) not in sys.path:
    sys.path.insert(0, str(KIT_ROOT))

from waios_mosaic.cross_fabric import run_cross_fabric_conformance  # noqa: E402
from waios_mosaic.crypto_receipt import (  # noqa: E402
    EnergyMeter,
    assert_sanitized,
    blake3_derive_key_hex,
    clopper_pearson_upper,
    iqr_stats,
    sanitized_host_info,
    seal_signed_receipt,
    verify_signed_receipt,
)

WAIOS_ROWS = 256
WAIOS_COLS = 128
WAIOS_DOMAIN = "waios.tmac.v1"
WAIOS_REFERENCE_DIGEST = "a541323b13653ed36515ff24ef08deb7dfa771e570a434712708fb72552f46f0"
WAIOS_CHANGED_DIGEST = "4ac7c4fbc2f2a031ac4f3c0e485867fb689d24d4872bdb1b0a6bc80cf88b69dc"

QUAL_ROWS = 73
QUAL_COLS = 35
NORM_ROPE_DIM = 64

_MASK64 = (1 << 64) - 1
_LCG_MUL = 6364136223846793005
_LCG_ADD = 1442695040888963407
_SEED = 0xDEADBEEFCAFEBABE

SWEEP_ZIPF_SKEWS = [0.0, 0.50, 0.85, 1.15, 1.40]
SWEEP_D_MAX = [0, 1, 2]
SWEEP_TAU = [1500, 3000, 4500, 6500, 9000]


class WaiosDisagreementHaltError(RuntimeError):
    """Raised when any execution lane or reference check disagrees; refuses to seal a receipt."""

    def __init__(self, message: str, observed_digest: str, expected_digest: str):
        super().__init__(message)
        self.observed_digest = observed_digest
        self.expected_digest = expected_digest


def compile_and_load_mosaic_lib(build_dir: Path | None = None) -> ctypes.CDLL:
    cc_bin = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if not cc_bin:
        raise RuntimeError("C compiler (`cc`/`gcc`/`clang`) required to build native Mosaic kernels.")
    bdir = build_dir or (KIT_ROOT / ".build")
    bdir.mkdir(parents=True, exist_ok=True)
    so_path = bdir / "libwaios_mosaic.so"
    c_src = HERE / "mosaic_kernels.c"
    if not so_path.exists() or c_src.stat().st_mtime > so_path.stat().st_mtime:
        arch_flags = ["-O2", "-mpopcnt"] if platform.machine().lower() in ("x86_64", "amd64") else ["-O2"]
        subprocess.run(
            [cc_bin, *arch_flags, "-shared", "-fPIC", "-pthread", str(c_src), "-o", str(so_path)],
            check=True,
            timeout=120,
        )
    lib = ctypes.CDLL(str(so_path))
    i8_p = ctypes.POINTER(ctypes.c_int8)
    u8_p = ctypes.POINTER(ctypes.c_uint8)
    i16_p = ctypes.POINTER(ctypes.c_int16)
    i32_p = ctypes.POINTER(ctypes.c_int32)

    lib.waios_audit_input.argtypes = [i8_p, i8_p]
    lib.waios_audit_input.restype = None
    lib.waios_lane_scalar.argtypes = [i8_p, i8_p, i32_p]
    lib.waios_lane_scalar.restype = None
    lib.waios_lane_bitsliced.argtypes = [i8_p, i8_p, i32_p]
    lib.waios_lane_bitsliced.restype = None
    lib.waios_lane_tmac_lut.argtypes = [i8_p, i8_p, i32_p]
    lib.waios_lane_tmac_lut.restype = None
    lib.waios_lane_hetero_mosaic.argtypes = [i8_p, i8_p, ctypes.c_int, i32_p]
    lib.waios_lane_hetero_mosaic.restype = None
    lib.waios_pack_ternary.argtypes = [i8_p, ctypes.c_int, ctypes.c_int, u8_p]
    lib.waios_pack_ternary.restype = None
    lib.waios_mosaic_fast_classify16.argtypes = [u8_p, i8_p, i32_p]
    lib.waios_mosaic_fast_classify16.restype = None
    lib.waios_heavy_escalation_teacher.argtypes = [i16_p, i8_p]
    lib.waios_heavy_escalation_teacher.restype = ctypes.c_int
    lib.waios_cascade_init.argtypes = [ctypes.c_char_p, u8_p, i16_p, ctypes.c_int]
    lib.waios_cascade_init.restype = ctypes.c_void_p
    lib.waios_cascade_free.argtypes = [ctypes.c_void_p]
    lib.waios_cascade_free.restype = None
    lib.waios_cascade_eval_batch.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_char_p,
        i8_p,
        i32_p,
        i32_p,
    ]
    lib.waios_cascade_eval_batch.restype = ctypes.c_int
    lib.waios_cascade_eval_grid.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_char_p,
        i8_p,
        i32_p,
        i32_p,
    ]
    lib.waios_cascade_eval_grid.restype = ctypes.c_int
    return lib


# ── Part 1: Canonical `waiOS` Input, Qualification & Cross-Lane Verification ─

def audit_input_python() -> tuple[list[int], list[int]]:
    s = _SEED
    weights: list[int] = []
    for _ in range(WAIOS_ROWS * WAIOS_COLS):
        s = (s * _LCG_MUL + _LCG_ADD) & _MASK64
        m = (s >> 32) % 3
        weights.append(-1 if m == 0 else (0 if m == 1 else 1))
    acts: list[int] = []
    for _ in range(WAIOS_COLS):
        s = (s * _LCG_MUL + _LCG_ADD) & _MASK64
        acts.append(int((s >> 40) % 251) - 125)
    return weights, acts


def digest_of_i32_output(out_vals: list[int]) -> str:
    payload = struct.pack(f"<{len(out_vals)}i", *out_vals)
    return blake3_derive_key_hex(WAIOS_DOMAIN, payload)


def with_one_weight_changed(weights: list[int], acts: list[int]) -> tuple[list[int], dict[str, int]]:
    mut = list(weights)
    row = 77
    col = next((c for c in range(WAIOS_COLS) if acts[c] != 0), 0)
    idx = row * WAIOS_COLS + col
    before = mut[idx]
    after = 0 if before == 1 else (before + 1)
    mut[idx] = after
    return mut, {"row": row, "col": col, "from": before, "to": after}


def run_boot_qualification_checks(lib: ctypes.CDLL) -> dict[str, Any]:
    s = _SEED ^ 0xA5A5A5A5A5A5A5A5
    q_weights: list[int] = []
    for _ in range(QUAL_ROWS * QUAL_COLS):
        s = (s * _LCG_MUL + _LCG_ADD) & _MASK64
        m = (s >> 32) % 3
        q_weights.append(-1 if m == 0 else (0 if m == 1 else 1))
    q_acts: list[int] = []
    for _ in range(QUAL_COLS):
        s = (s * _LCG_MUL + _LCG_ADD) & _MASK64
        q_acts.append(int((s >> 40) % 251) - 125)

    ref_73x35 = [
        sum(q_weights[r * QUAL_COLS + c] * q_acts[c] for c in range(QUAL_COLS))
        for r in range(QUAL_ROWS)
    ]
    w_arr = (ctypes.c_int8 * len(q_weights))(*q_weights)
    pairs = (QUAL_COLS + 1) // 2
    packed = (ctypes.c_uint8 * (pairs * QUAL_ROWS))()
    lib.waios_pack_ternary(w_arr, QUAL_ROWS, QUAL_COLS, packed)
    unpacked_out = [0] * QUAL_ROWS
    for g in range(pairs):
        a0 = q_acts[2 * g]
        a1 = q_acts[2 * g + 1] if (2 * g + 1 < QUAL_COLS) else 0
        for r in range(QUAL_ROWS):
            code = int(packed[g * QUAL_ROWS + r])
            c0, c1 = code & 3, (code >> 2) & 3
            s0 = a0 if c0 == 1 else (-a0 if c0 == 2 else 0)
            s1 = a1 if c1 == 1 else (-a1 if c1 == 2 else 0)
            unpacked_out[r] += s0 + s1
    odd_73x35_ok = unpacked_out == ref_73x35

    rope_strides = [17, 13, 11, 9, 7, 5, 4, 3, 2, 2, 1, 1, 1, 1, 1, 1]
    cos_q15 = [
        32767, 32609, 32137, 31356, 30273, 28898, 27245, 25329,
        23170, 20787, 18204, 15446, 12539, 9512, 6393, 3212,
        0, -3212, -6393, -9512, -12539, -15446, -18204, -20787,
        -23170, -25329, -27245, -28898, -30273, -31356, -32137, -32609,
        -32767, -32609, -32137, -31356, -30273, -28898, -27245, -25329,
        -23170, -20787, -18204, -15446, -12539, -9512, -6393, -3212,
        0, 3212, 6393, 9512, 12539, 15446, 18204, 20787,
        23170, 25329, 27245, 28898, 30273, 31356, 32137, 32609,
    ]
    sin_q15 = [
        0, 3212, 6393, 9512, 12539, 15446, 18204, 20787,
        23170, 25329, 27245, 28898, 30273, 31356, 32137, 32609,
        32767, 32609, 32137, 31356, 30273, 28898, 27245, 25329,
        23170, 20787, 18204, 15446, 12539, 9512, 6393, 3212,
        0, -3212, -6393, -9512, -12539, -15446, -18204, -20787,
        -23170, -25329, -27245, -28898, -30273, -31356, -32137, -32609,
        -32767, -32609, -32137, -31356, -30273, -28898, -27245, -25329,
        -23170, -20787, -18204, -15446, -12539, -9512, -6393, -3212,
    ]

    def isqrt_u32(n: int) -> int:
        x = n & 0xFFFFFFFF
        if x == 0:
            return 0
        res = 0
        bit = 1 << 30
        while bit > x:
            bit >>= 2
        while bit != 0:
            if x >= res + bit:
                x -= res + bit
                res = (res >> 1) + bit
            else:
                res >>= 1
            bit >>= 2
        return res

    def clamp_i32(v: int, lo: int, hi: int) -> int:
        return lo if v < lo else (hi if v > hi else v)

    def sdiv_trunc(num: int, den: int) -> int:
        mag = abs(num) // max(den, 1)
        return -mag if num < 0 else mag

    def sdiv_pow2_trunc(val: int, shift: int) -> int:
        mag = abs(val) >> shift
        return -mag if val < 0 else mag

    x_in = [((i * 274 + 29) % 2401) - 1200 for i in range(NORM_ROPE_DIM)]
    gamma_q8 = [210 + ((i * 38) % 90) for i in range(NORM_ROPE_DIM)]
    sum_sq = sum(clamp_i32(v, -1000, 1000) ** 2 for v in x_in)
    mean_sq_q8 = ((sum_sq // NORM_ROPE_DIM) << 8) + 16
    rms_q4 = max(isqrt_u32(mean_sq_q8), 1)
    nr_out = [0] * NORM_ROPE_DIM
    for p in range(NORM_ROPE_DIM // 2):
        i0, i1 = 2 * p, 2 * p + 1
        y0 = clamp_i32(sdiv_trunc(clamp_i32(x_in[i0], -1000, 1000) * gamma_q8[i0] * 4, rms_q4), -127, 127)
        y1 = clamp_i32(sdiv_trunc(clamp_i32(x_in[i1], -1000, 1000) * gamma_q8[i1] * 4, rms_q4), -127, 127)
        phase = (7 * rope_strides[p & 15] + (p >> 4)) & 63
        c_v, s_v = cos_q15[phase], sin_q15[phase]
        nr_out[i0] = clamp_i32(sdiv_pow2_trunc(y0 * c_v - y1 * s_v, 15), -127, 127)
        nr_out[i1] = clamp_i32(sdiv_pow2_trunc(y0 * s_v + y1 * c_v, 15), -127, 127)

    nr_digest = blake3_derive_key_hex("waios.norm_rope.v1", struct.pack("<64i", *nr_out))
    return {
        "odd_73x35_ternary_passed": odd_73x35_ok,
        "zero_fp_norm_rope_64_blake3": nr_digest,
        "all_passed": odd_73x35_ok and all(-127 <= v <= 127 for v in nr_out),
    }


def execute_and_seal_mosaic(
    lib: ctypes.CDLL,
    weights: list[int],
    acts: list[int],
    expected_digest: str = WAIOS_REFERENCE_DIGEST,
    split_shift: int = 0,
) -> dict[str, Any]:
    w_c = (ctypes.c_int8 * (WAIOS_ROWS * WAIOS_COLS))(*weights)
    a_c = (ctypes.c_int8 * WAIOS_COLS)(*acts)

    out_py = [
        sum(weights[r * WAIOS_COLS + c] * acts[c] for c in range(WAIOS_COLS))
        for r in range(WAIOS_ROWS)
    ]
    d_py = digest_of_i32_output(out_py)

    buf_sc = (ctypes.c_int32 * WAIOS_ROWS)()
    lib.waios_lane_scalar(w_c, a_c, buf_sc)
    d_sc = digest_of_i32_output(list(buf_sc))

    buf_bs = (ctypes.c_int32 * WAIOS_ROWS)()
    lib.waios_lane_bitsliced(w_c, a_c, buf_bs)
    d_bs = digest_of_i32_output(list(buf_bs))

    buf_lut = (ctypes.c_int32 * WAIOS_ROWS)()
    lib.waios_lane_tmac_lut(w_c, a_c, buf_lut)
    d_lut = digest_of_i32_output(list(buf_lut))

    buf_mos = (ctypes.c_int32 * WAIOS_ROWS)()
    lib.waios_lane_hetero_mosaic(w_c, a_c, split_shift, buf_mos)
    d_mos = digest_of_i32_output(list(buf_mos))

    lane_digests = {
        "python_scalar_i32": d_py,
        "c_scalar_i32": d_sc,
        "c_packed_2bit_bitsliced": d_bs,
        "c_tmac_pair_lut": d_lut,
        "c_hetero_mosaic_4worker_pthreads": d_mos,
    }

    for lane_name, d_val in lane_digests.items():
        if d_val != expected_digest:
            raise WaiosDisagreementHaltError(
                f"Disagreement halt on lane {lane_name}: {d_val} != {expected_digest}; receipt refused.",
                observed_digest=d_val,
                expected_digest=expected_digest,
            )

    return seal_signed_receipt(
        kit_id="kits/waios-mosaic-cascade/conformance",
        payload={
            "waios_domain": WAIOS_DOMAIN,
            "reference_digest": expected_digest,
            "lane_digests": lane_digests,
            "all_lanes_equal": True,
        },
        domain_context="openie.kit.waios_conformance.receipt.v1",
    )


# ── Part 2: 4-Stage Spellcheck Lookup-First Cascade (`1,000` Queries + Grid) ─

CANONICAL_INTENTS = [
    "compile.lut6.page",
    "verify.blake3.receipt",
    "route.mosaic.tile",
    "query.dnull.table",
    "pack.ternary.matrix",
    "check.debruijn.form",
    "meter.rapl.package",
    "seal.ed25519.digest",
    "gate.confidence.margin",
    "prune.zonemap.granule",
    "fork.cow.snapshot",
    "sync.hlc.timestamp",
    "encode.hdc.hypervec",
    "parse.binary.frame",
    "audit.sha256.manifest",
    "halt.fault.mismatch",
]


def _damerau_levenshtein_le2(a: str, b: str) -> int:
    if abs(len(a) - len(b)) > 3:
        return 99
    la, lb = len(a), len(b)
    d = [[0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la + 1):
        d[i][0] = i
    for j in range(lb + 1):
        d[0][j] = j
    for i in range(1, la + 1):
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[la][lb]


def _trigrams(s: str) -> set[str]:
    padded = f"^{s}$"
    return {padded[i : i + 3] for i in range(len(padded) - 2)}


class SpellcheckCascadeSystem:
    """4-Stage Lookup-First Cascade backed by boot-qualified `waiOS` Mosaic + Escalation Gate."""

    def __init__(self, lib: ctypes.CDLL) -> None:
        self.lib = lib
        w_audit, a_audit = audit_input_python()
        self.boot_receipt = execute_and_seal_mosaic(lib, w_audit, a_audit, WAIOS_REFERENCE_DIGEST)
        assert verify_signed_receipt(self.boot_receipt)

        self.stage1_lut: dict[str, int] = {}
        for idx, cmd in enumerate(CANONICAL_INTENTS):
            self.stage1_lut[cmd] = idx
            self.stage1_lut[cmd.replace(".", "_")] = idx
            self.stage1_lut[cmd.upper()] = idx

        self.trigram_postings: dict[str, list[int]] = {}
        for idx, cmd in enumerate(CANONICAL_INTENTS):
            for tg in _trigrams(cmd):
                self.trigram_postings.setdefault(tg, []).append(idx)

        rng = random.Random(20261126)
        self.intent_prototypes = [
            [rng.choice((-1, 1)) if (c % 8 == idx % 8 or rng.random() < 0.35) else 0 for c in range(WAIOS_COLS)]
            for idx in range(16)
        ]
        mosaic_w: list[int] = []
        for idx in range(16):
            proto = self.intent_prototypes[idx]
            for g in range(16):
                row_w = []
                for c in range(WAIOS_COLS):
                    if (c + g) % 11 == 0:
                        row_w.append(0)
                    else:
                        row_w.append(proto[c])
                mosaic_w.extend(row_w)
        w_arr = (ctypes.c_int8 * (WAIOS_ROWS * WAIOS_COLS))(*mosaic_w)
        self.packed_mosaic = (ctypes.c_uint8 * ((WAIOS_COLS // 2) * WAIOS_ROWS))()
        self.lib.waios_pack_ternary(w_arr, WAIOS_ROWS, WAIOS_COLS, self.packed_mosaic)

        total_i16 = 8 * 256 * 256 + 16 * 256
        dense = [0] * total_i16
        for l in range(8):
            base = l * 256 * 256
            for i in range(256):
                dense[base + i * 256 + i] = 4096
                dense[base + i * 256 + ((i + 1) & 255)] = rng.randint(-64, 64)
        head_base = 8 * 256 * 256
        for idx in range(16):
            proto = self.intent_prototypes[idx]
            for c in range(WAIOS_COLS):
                dense[head_base + idx * 256 + c] = proto[c] * 256
                dense[head_base + idx * 256 + 128 + c] = (-proto[c]) * 128
        self.dense_layers = (ctypes.c_int16 * total_i16)(*dense)
        self.margin_threshold = 4500

        canon_buf = bytearray(16 * 64)
        for idx, cmd in enumerate(CANONICAL_INTENTS):
            b = cmd.encode("ascii")[:63]
            canon_buf[idx * 64 : idx * 64 + len(b)] = b
        self._canon_c = ctypes.create_string_buffer(bytes(canon_buf), 16 * 64)
        self.c_ctx = self.lib.waios_cascade_init(
            self._canon_c, self.packed_mosaic, self.dense_layers, self.margin_threshold
        )
        assert self.c_ctx, "waios_cascade_init failed"

    def close(self) -> None:
        if getattr(self, "c_ctx", None):
            self.lib.waios_cascade_free(self.c_ctx)
            self.c_ctx = None

    def generate_workload_1000(self, n_queries: int = 1000) -> list[dict[str, Any]]:
        rng = random.Random(20261125)
        alphabet = "abcdefghijklmnopqrstuvwxyz0123456789._"
        queries: list[dict[str, Any]] = []

        for qid in range(n_queries):
            u = qid % 20
            intent = int(rng.paretovariate(1.3) - 1) % 16 if u < 11 else (qid % 16)
            canon = CANONICAL_INTENTS[intent]
            proto = self.intent_prototypes[intent]

            if u < 11:
                q_str = canon if (qid % 3 != 0) else (canon.replace(".", "_") if qid % 2 == 0 else canon.upper())
                feats = [proto[c] * 60 + rng.randint(-8, 8) for c in range(WAIOS_COLS)]
                stratum = "recurring_exact"
            elif u < 16:
                chars = list(canon)
                pos = rng.randrange(1, len(chars) - 1)
                if qid % 3 == 0:
                    chars[pos], chars[pos + 1] = chars[pos + 1], chars[pos]
                elif qid % 3 == 1:
                    chars[pos] = alphabet[(alphabet.index(chars[pos]) + 5) % len(alphabet)]
                else:
                    del chars[pos]
                q_str = "".join(chars)
                feats = [proto[c] * 55 + rng.randint(-12, 12) for c in range(WAIOS_COLS)]
                stratum = "near_miss_typo"
            elif u < 19:
                q_str = f"telemetry_event_{qid}_unseen_schema_v2"
                feats = [proto[c] * 52 + rng.randint(-15, 15) for c in range(WAIOS_COLS)]
                stratum = "novel_mosaic_solvable"
            else:
                rival = (intent + 1) % 16
                rival_proto = self.intent_prototypes[rival]
                q_str = f"ambiguous_boundary_trace_{qid}"
                feats = [
                    int(0.54 * proto[c] * 40 + 0.46 * rival_proto[c] * 40)
                    for c in range(WAIOS_COLS)
                ]
                stratum = "hard_residual_escalated"

            feats_clamped = [max(-125, min(125, int(v))) for v in feats]
            queries.append(
                {
                    "qid": qid,
                    "text": q_str,
                    "acts_c": (ctypes.c_int8 * WAIOS_COLS)(*feats_clamped),
                    "ground_truth": intent,
                    "stratum": stratum,
                }
            )
        rng.shuffle(queries)
        return queries

    def generate_workload_for_zipf_skew(self, zipf_s: float, n_queries: int = 1000) -> list[dict[str, Any]]:
        """Deterministic 1,000-query workload parameterized by recurrence skew s in {0.0, 0.50, 0.85, 1.15, 1.40}."""
        rng = random.Random(20261125 + int(round(zipf_s * 1000)))
        alphabet = "abcdefghijklmnopqrstuvwxyz0123456789._"

        # Recurrence mix scales monotonically with Zipf skew s
        p_exact = min(0.76, 0.10 + 0.44 * (zipf_s / 1.40) + 0.18 * ((zipf_s / 1.40) ** 2))
        p_typo = 0.15 + 0.08 * (1.0 - abs(zipf_s - 0.85) / 1.40)
        p_hard = max(0.02, 0.14 - 0.085 * (zipf_s / 1.40))
        # Remaining fraction goes to novel Mosaic-solvable telemetry

        weights_16 = [1.0 / ((k + 1) ** max(0.0, zipf_s)) for k in range(16)]
        tot_w = sum(weights_16)
        cdf_16: list[float] = []
        acc_w = 0.0
        for w in weights_16:
            acc_w += w / tot_w
            cdf_16.append(acc_w)

        def _draw_zipf() -> int:
            r = rng.random()
            for idx, cut in enumerate(cdf_16):
                if r <= cut:
                    return idx
            return 15

        queries: list[dict[str, Any]] = []
        for qid in range(n_queries):
            intent = _draw_zipf()
            canon = CANONICAL_INTENTS[intent]
            proto = self.intent_prototypes[intent]
            u = (qid + 0.5) / n_queries

            if u < p_exact:
                q_str = canon if (qid % 3 != 0) else (canon.replace(".", "_") if qid % 2 == 0 else canon.upper())
                feats = [proto[c] * 60 + rng.randint(-8, 8) for c in range(WAIOS_COLS)]
                stratum = "recurring_exact"
            elif u < p_exact + p_typo:
                chars = list(canon)
                pos = rng.randrange(1, len(chars) - 2)
                if qid % 2 == 0:
                    # Distance-1 substitution
                    chars[pos] = alphabet[(alphabet.index(chars[pos]) + 5) % len(alphabet)]
                else:
                    # Distance-2 two substitutions so d_max=1 vs d_max=2 splits cleanly!
                    chars[pos] = alphabet[(alphabet.index(chars[pos]) + 5) % len(alphabet)]
                    p2 = len(chars) - 2
                    chars[p2] = alphabet[(alphabet.index(chars[p2]) + 7) % len(alphabet)]
                q_str = "".join(chars)
                feats = [proto[c] * 48 + rng.randint(-14, 14) for c in range(WAIOS_COLS)]
                stratum = "near_miss_typo"
            elif u < 1.0 - p_hard:
                q_str = f"telemetry_event_{qid}_skew_{int(zipf_s*100)}"
                # Spread feature amplitude across [28..62] so tau in {1500..9000} sweeps margin acceptance smoothly
                amp = 28 + (qid % 35)
                feats = [proto[c] * amp + rng.randint(-15, 15) for c in range(WAIOS_COLS)]
                stratum = "novel_mosaic_solvable"
            else:
                rival = (intent + 1) % 16
                rival_proto = self.intent_prototypes[rival]
                q_str = f"ambiguous_boundary_trace_{qid}"
                feats = [
                    int(0.53 * proto[c] * 38 + 0.47 * rival_proto[c] * 38)
                    for c in range(WAIOS_COLS)
                ]
                stratum = "hard_residual_escalated"

            feats_clamped = [max(-125, min(125, int(v))) for v in feats]
            queries.append(
                {
                    "qid": qid,
                    "text": q_str,
                    "acts_c": (ctypes.c_int8 * WAIOS_COLS)(*feats_clamped),
                    "ground_truth": intent,
                    "stratum": stratum,
                }
            )
        rng.shuffle(queries)
        return queries

    def pack_queries_for_c(self, queries: list[dict[str, Any]]) -> tuple[Any, Any, Any]:
        n = len(queries)
        txt_buf = bytearray(n * 64)
        acts_flat: list[int] = []
        labels_flat: list[int] = []
        for i, q in enumerate(queries):
            b = q["text"].encode("ascii")[:63]
            txt_buf[i * 64 : i * 64 + len(b)] = b
            acts_flat.extend(int(v) for v in q["acts_c"])
            labels_flat.append(int(q["ground_truth"]))
        return (
            ctypes.create_string_buffer(bytes(txt_buf), n * 64),
            (ctypes.c_int8 * (n * WAIOS_COLS))(*acts_flat),
            (ctypes.c_int32 * n)(*labels_flat),
        )

    def run_4stage_cascade_pass(self, queries: list[dict[str, Any]]) -> tuple[int, dict[str, int]]:
        stage_counts = {"stage1_lut": 0, "stage2_sparse": 0, "stage3_mosaic": 0, "stage4_escalated": 0}
        correct = 0
        scores16 = (ctypes.c_int32 * 16)()

        for q in queries:
            txt = q["text"]
            hit1 = self.stage1_lut.get(txt)
            if hit1 is not None:
                pred = hit1
                stage_counts["stage1_lut"] += 1
            else:
                low = txt.lower()
                cand_votes: dict[int, int] = {}
                for tg in _trigrams(low):
                    for cid in self.trigram_postings.get(tg, ()):
                        cand_votes[cid] = cand_votes.get(cid, 0) + 1
                pred = -1
                if cand_votes:
                    top_cands = sorted(cand_votes.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
                    best_d = 99
                    best_cid = -1
                    for cid, _ in top_cands:
                        d = _damerau_levenshtein_le2(low, CANONICAL_INTENTS[cid])
                        if d < best_d:
                            best_d = d
                            best_cid = cid
                    if best_d <= 2:
                        pred = best_cid
                        stage_counts["stage2_sparse"] += 1

                if pred < 0:
                    self.lib.waios_mosaic_fast_classify16(self.packed_mosaic, q["acts_c"], scores16)
                    s_list = list(scores16)
                    top1_idx = max(range(16), key=lambda idx: s_list[idx])
                    top1_val = s_list[top1_idx]
                    top2_val = max(s_list[idx] for idx in range(16) if idx != top1_idx)
                    if (top1_val - top2_val) >= self.margin_threshold:
                        pred = top1_idx
                        stage_counts["stage3_mosaic"] += 1
                    else:
                        pred = int(self.lib.waios_heavy_escalation_teacher(self.dense_layers, q["acts_c"]))
                        stage_counts["stage4_escalated"] += 1

            if pred == q["ground_truth"]:
                correct += 1
        return correct, stage_counts


def run_full_kit(quick: bool = False) -> tuple[dict[str, Any], dict[str, Any], str]:
    lib = compile_and_load_mosaic_lib()
    meter = EnergyMeter()
    is_shunt = meter.board_metered
    idle_pre = meter.sample_idle_baseline(0.20 if quick else (1.0 if is_shunt else 0.20)) if meter.available else None
    host = sanitized_host_info()

    qual = run_boot_qualification_checks(lib)
    assert qual["all_passed"], "Boot qualification failed!"

    w_base, a_base = audit_input_python()
    conformance_receipt = execute_and_seal_mosaic(lib, w_base, a_base, WAIOS_REFERENCE_DIGEST, split_shift=0)
    assert verify_signed_receipt(conformance_receipt)

    mosaic_sweep_runs = 40 if quick else 100
    mosaic_disagreements = 0
    w_c = (ctypes.c_int8 * (WAIOS_ROWS * WAIOS_COLS))(*w_base)
    a_c = (ctypes.c_int8 * WAIOS_COLS)(*a_base)
    out_buf = (ctypes.c_int32 * WAIOS_ROWS)()
    for shift in range(mosaic_sweep_runs):
        lib.waios_lane_hetero_mosaic(w_c, a_c, shift, out_buf)
        if digest_of_i32_output(list(out_buf)) != WAIOS_REFERENCE_DIGEST:
            mosaic_disagreements += 1
    cp95_mosaic = clopper_pearson_upper(mosaic_disagreements, mosaic_sweep_runs, alpha=0.05, two_sided=False)

    w_tamper, tamper_meta = with_one_weight_changed(w_base, a_base)
    tamper_caught = False
    tamper_observed_digest = ""
    tamper_receipt_emitted = True
    try:
        _ = execute_and_seal_mosaic(lib, w_tamper, a_base, WAIOS_REFERENCE_DIGEST, split_shift=0)
    except WaiosDisagreementHaltError as exc:
        tamper_caught = True
        tamper_observed_digest = exc.observed_digest
        tamper_receipt_emitted = False
    assert tamper_caught and tamper_observed_digest == WAIOS_CHANGED_DIGEST and not tamper_receipt_emitted

    cross_fabric = run_cross_fabric_conformance(
        weights=w_base,
        acts=a_base,
        tampered_weights=w_tamper,
        digest_fn=digest_of_i32_output,
        expected_digest=WAIOS_REFERENCE_DIGEST,
        expected_tamper_digest=WAIOS_CHANGED_DIGEST,
        quick=quick,
    )
    if cross_fabric["disagreed_fabrics"]:
        raise WaiosDisagreementHaltError(
            f"Cross-fabric disagreement on {cross_fabric['disagreed_fabrics']}",
            observed_digest="cross_fabric_mismatch",
            expected_digest=WAIOS_REFERENCE_DIGEST,
        )

    cascade = SpellcheckCascadeSystem(lib)
    try:
        queries = cascade.generate_workload_1000(n_queries=1000)
        q_txt_c, q_acts_c, q_lbl_c = cascade.pack_queries_for_c(queries)
        n_q = len(queries)
        counts4 = (ctypes.c_int32 * 4)()

        py_corr, _ = cascade.run_4stage_cascade_pass(queries)
        c_warm_corr = lib.waios_cascade_eval_batch(cascade.c_ctx, 0, n_q, 1, q_txt_c, q_acts_c, q_lbl_c, counts4)
        assert c_warm_corr == py_corr, f"C/Python cascade mismatch: {c_warm_corr} != {py_corr}"

        n_trials = (4 if quick else 8) if is_shunt else (10 if quick else 20)
        arm_modes = {
            "spellcheck_4stage_cascade": (0, 35, 15),
            "always_stage3_mosaic_plus_gate": (1, 20, 10),
            "always_dense_teacher_baseline": (2, 2, 1),
        }
        arm_reps: dict[str, int] = {}
        for arm_name, (mode_id, def_r, qk_r) in arm_modes.items():
            def _probe_arm(mid: int = mode_id) -> None:
                lib.waios_cascade_eval_batch(cascade.c_ctx, mid, n_q, 1, q_txt_c, q_acts_c, q_lbl_c, counts4)
            arm_reps[arm_name] = meter.calibrate_reps(
                _probe_arm, def_r, qk_r, quick=quick, target_shunt_s=0.78
            )

        arms_samples: dict[str, dict[str, Any]] = {
            arm: {
                "us_per_correct": [],
                "gross_measured_uj_per_correct": [],
                "paired_net_measured_uj_per_correct": [],
                "secondary_measured_uj_per_correct": [],
                "window_s_samples": [],
                "shunt_samples": [],
                "pkg_uj_per_correct": [],
                "core_uj_per_correct": [],
                "correct": 0,
                "reps_per_trial": arm_reps[arm],
            }
            for arm in arm_modes
        }
        stage_breakdown: dict[str, int] = {}
        always_mosaic_escalated = 0

        arm_order_base = list(arm_modes.keys())
        for trial in range(n_trials):
            round_idle_w = meter.sample_idle_power_w(0.08 if quick else 0.22) if is_shunt else None
            order = arm_order_base[trial % 3 :] + arm_order_base[: trial % 3]
            for arm in order:
                mode_id = arm_modes[arm][0]
                reps_used = arm_reps[arm]
                s0 = meter.snapshot()
                corr = lib.waios_cascade_eval_batch(
                    cascade.c_ctx, mode_id, n_q, reps_used, q_txt_c, q_acts_c, q_lbl_c, counts4
                )
                s1 = meter.snapshot() if not is_shunt else None
                d = meter.diff(s0, s1)

                if mode_id == 0:
                    stage_breakdown = {
                        "stage1_lut": int(counts4[0]),
                        "stage2_sparse": int(counts4[1]),
                        "stage3_mosaic": int(counts4[2]),
                        "stage4_escalated": int(counts4[3]),
                    }
                elif mode_id == 1:
                    always_mosaic_escalated = int(counts4[3])

                tot_correct = max(1, corr * reps_used)
                rec = arms_samples[arm]
                rec["correct"] = corr
                rec["us_per_correct"].append((d["wall_ns"] / 1e3) / tot_correct)
                if d["primary_measured_j"] is not None:
                    gj = float(d["primary_measured_j"])
                    ws = float(d["wall_s"])
                    rec["gross_measured_uj_per_correct"].append((gj * 1e6) / tot_correct)
                    rec["window_s_samples"].append(ws)
                    rec["shunt_samples"].append(int(d["shunt_samples"]))
                    if round_idle_w is not None:
                        rec["paired_net_measured_uj_per_correct"].append(
                            (max(0.0, gj - round_idle_w * ws) * 1e6) / tot_correct
                        )
                    if d["secondary_measured_j"] is not None:
                        rec["secondary_measured_uj_per_correct"].append(
                            (float(d["secondary_measured_j"]) * 1e6) / tot_correct
                        )
                if d["pkg_reported_j"] is not None:
                    rec["pkg_uj_per_correct"].append((d["pkg_reported_j"] * 1e6) / tot_correct)
                if d["core_reported_j"] is not None:
                    rec["core_uj_per_correct"].append((d["core_reported_j"] * 1e6) / tot_correct)

        # 75-cell Cascade Parameter Grid Sweep: (Zipf s x d_max x margin tau)
        skews = [0.0, 1.15, 1.40] if quick else SWEEP_ZIPF_SKEWS
        dmax_list = [0, 2] if quick else SWEEP_D_MAX
        tau_list = [1500, 4500, 9000] if quick else SWEEP_TAU

        cascade_grid_sweep: list[dict[str, Any]] = []
        for s_val in skews:
            sq = cascade.generate_workload_for_zipf_skew(s_val, n_queries=1000)
            sq_txt, sq_acts, sq_lbl = cascade.pack_queries_for_c(sq)
            skew_idle_w = meter.sample_idle_power_w(0.06 if quick else 0.16) if is_shunt else None

            for dm in dmax_list:
                for tau in tau_list:
                    def _probe_cell(dm_v: int = dm, tau_v: int = tau) -> None:
                        lib.waios_cascade_eval_grid(
                            cascade.c_ctx, dm_v, tau_v, 1000, 1, sq_txt, sq_acts, sq_lbl, counts4
                        )
                    cell_reps = meter.calibrate_reps(
                        _probe_cell, default_reps=12, quick_reps=3, quick=quick, target_shunt_s=0.66
                    )
                    s0 = meter.snapshot()
                    c_corr = lib.waios_cascade_eval_grid(
                        cascade.c_ctx, dm, tau, 1000, cell_reps, sq_txt, sq_acts, sq_lbl, counts4
                    )
                    s1 = meter.snapshot() if not is_shunt else None
                    d = meter.diff(s0, s1)
                    tot_c = max(1, c_corr * cell_reps)

                    s1_n, s2_n, s3_n, s4_n = (int(counts4[0]), int(counts4[1]), int(counts4[2]), int(counts4[3]))
                    gross_uj = (
                        round((float(d["primary_measured_j"]) * 1e6) / tot_c, 3)
                        if d["primary_measured_j"] is not None
                        else None
                    )
                    net_uj = (
                        round((max(0.0, float(d["primary_measured_j"]) - skew_idle_w * float(d["wall_s"])) * 1e6) / tot_c, 3)
                        if (d["primary_measured_j"] is not None and skew_idle_w is not None)
                        else None
                    )
                    sec_uj = (
                        round((float(d["secondary_measured_j"]) * 1e6) / tot_c, 3)
                        if d["secondary_measured_j"] is not None
                        else None
                    )
                    pkg_uj = (
                        round((float(d["pkg_reported_j"]) * 1e6) / tot_c, 3)
                        if d["pkg_reported_j"] is not None
                        else None
                    )

                    cascade_grid_sweep.append(
                        {
                            "zipf_skew_s": s_val,
                            "stage2_edit_distance_d_max": dm,
                            "stage3_margin_tau": tau,
                            "queries": 1000,
                            "correct": int(c_corr),
                            "accuracy": round(c_corr / 1000.0, 4),
                            "stage_fractions": {
                                "stage1_lut": round(s1_n / 1000.0, 4),
                                "stage2_sparse": round(s2_n / 1000.0, 4),
                                "stage3_mosaic": round(s3_n / 1000.0, 4),
                                "stage4_escalated": round(s4_n / 1000.0, 4),
                            },
                            "local_wall_us_per_correct": round((d["wall_ns"] / 1e3) / tot_c, 3),
                            "evidence_class": meter.evidence_class,
                            "gross_rail_measured_uj_per_correct": gross_uj,
                            "paired_net_above_idle_measured_uj_per_correct": net_uj,
                            "secondary_carrier_measured_uj_per_correct": sec_uj,
                            "shunt_samples": int(d["shunt_samples"]),
                            "pkg_reported_uj_per_correct": pkg_uj,
                            "isolated_analytical_cloud_est_j": {
                                "evidence_class": "est_j",
                                "mixed_or_summed": False,
                                "stage4_calls": s4_n,
                                "remote_est_j_at_1p5j_per_call": round(1.50 * s4_n, 2),
                            },
                        }
                    )
    finally:
        cascade.close()

    idle_post = meter.sample_idle_baseline(0.20 if quick else (1.0 if is_shunt else 0.20)) if meter.available else None
    telemetry_meta = meter.metadata(idle_pre, idle_post)
    meter.close()

    f6_flag = bool(telemetry_meta.get("falsifier_6_idle_drift_flag", False))
    mean_idle_w = telemetry_meta.get("idle_trimmed_mean_w")

    arms_summary: dict[str, Any] = {}
    for arm, rec in arms_samples.items():
        a1_a2_net: list[float] = []
        if is_shunt and (not f6_flag) and mean_idle_w is not None:
            for gj_uj, ws in zip(rec["gross_measured_uj_per_correct"], rec["window_s_samples"]):
                tot_c = max(1, rec["correct"] * rec["reps_per_trial"])
                gross_j = (gj_uj * tot_c) * 1e-6
                a1_a2_net.append((max(0.0, gross_j - float(mean_idle_w) * ws) * 1e6) / tot_c)

        arms_summary[arm] = {
            "queries_per_pass": n_q,
            "correct_completions": rec["correct"],
            "accuracy": round(rec["correct"] / n_q, 6),
            "reps_per_trial": rec["reps_per_trial"],
            "wall_us_per_correct_completion": iqr_stats(rec["us_per_correct"], 3),
            "evidence_class": meter.evidence_class,
            "gross_rail_measured_uj_per_correct_completion": (
                iqr_stats(rec["gross_measured_uj_per_correct"], 2)
                if rec["gross_measured_uj_per_correct"]
                else None
            ),
            "net_above_idle_a1_a2_measured_uj_per_correct_completion": (
                iqr_stats(a1_a2_net, 2) if a1_a2_net else None
            ),
            "net_above_idle_a1_a2_withheld_per_falsifier_6": bool(is_shunt and f6_flag),
            "paired_round_net_above_idle_measured_uj_per_correct_completion": (
                iqr_stats(rec["paired_net_measured_uj_per_correct"], 2)
                if rec["paired_net_measured_uj_per_correct"]
                else None
            ),
            "secondary_carrier_measured_uj_per_correct_completion": (
                iqr_stats(rec["secondary_measured_uj_per_correct"], 2)
                if rec["secondary_measured_uj_per_correct"]
                else None
            ),
            "shunt_samples_per_trial": (
                iqr_stats([float(c) for c in rec["shunt_samples"]], 1) if rec["shunt_samples"] else None
            ),
            "pkg_reported_uj_per_correct_completion": (
                iqr_stats(rec["pkg_uj_per_correct"], 2) if rec["pkg_uj_per_correct"] else None
            ),
            "core_reported_uj_per_correct_completion": (
                iqr_stats(rec["core_uj_per_correct"], 2) if rec["core_uj_per_correct"] else None
            ),
        }

    cas_us = arms_summary["spellcheck_4stage_cascade"]["wall_us_per_correct_completion"]["median"]
    mos_us = arms_summary["always_stage3_mosaic_plus_gate"]["wall_us_per_correct_completion"]["median"]
    den_us = arms_summary["always_dense_teacher_baseline"]["wall_us_per_correct_completion"]["median"]

    same_meter_ratios: dict[str, Any] = {
        "evidence_class": meter.evidence_class,
        "wall_speedup_cascade_over_always_dense_x": round(den_us / max(cas_us, 1e-9), 2),
        "wall_speedup_cascade_over_always_mosaic_x": round(mos_us / max(cas_us, 1e-9), 2),
    }
    if meter.evidence_class == "measured_j":
        c_e = arms_summary["spellcheck_4stage_cascade"]["gross_rail_measured_uj_per_correct_completion"]["median"]
        m_e = arms_summary["always_stage3_mosaic_plus_gate"]["gross_rail_measured_uj_per_correct_completion"]["median"]
        d_e = arms_summary["always_dense_teacher_baseline"]["gross_rail_measured_uj_per_correct_completion"]["median"]
        same_meter_ratios["measured_j_improvement_cascade_over_always_dense_x"] = round(d_e / max(c_e, 1e-9), 2)
        same_meter_ratios["measured_j_improvement_cascade_over_always_mosaic_x"] = round(m_e / max(c_e, 1e-9), 2)
    elif meter.evidence_class == "reported_j":
        c_e = arms_summary["spellcheck_4stage_cascade"]["pkg_reported_uj_per_correct_completion"]["median"]
        m_e = arms_summary["always_stage3_mosaic_plus_gate"]["pkg_reported_uj_per_correct_completion"]["median"]
        d_e = arms_summary["always_dense_teacher_baseline"]["pkg_reported_uj_per_correct_completion"]["median"]
        same_meter_ratios["reported_j_improvement_cascade_over_always_dense_x"] = round(d_e / max(c_e, 1e-9), 2)
        same_meter_ratios["reported_j_improvement_cascade_over_always_mosaic_x"] = round(m_e / max(c_e, 1e-9), 2)

    escalated_frac = stage_breakdown["stage4_escalated"] / n_q
    results: dict[str, Any] = {
        "schema": "openie.waios_mosaic_cascade.v2",
        "kit_id": "kits/waios-mosaic-cascade",
        "shots_on_goal": [
            "Shot #3 — Cross-Lane HeteroMosaic Integer Runtime Sealed by waiOS Reference Digest a541323b...",
            "Shot #5 — 4-Stage Spellcheck Lookup-First Cascade",
            "Shot #6 — Physical DC Shunt Rail Metering (measured_j) & 75-Cell Cascade Sweep",
        ],
        "provenance_tier": "Signed Provenance · Self-Checked",
        "license": "Apache-2.0",
        "mode": "quick" if quick else "standard",
        "host": host,
        "energy_telemetry": telemetry_meta,
        "waios_conformance_and_fault_halt": {
            "canonical_shape": [WAIOS_ROWS, WAIOS_COLS],
            "blake3_domain": WAIOS_DOMAIN,
            "reference_digest": WAIOS_REFERENCE_DIGEST,
            "lane_digests": conformance_receipt["body"]["payload"]["lane_digests"],
            "boot_qualification": qual,
            "hetero_mosaic_schedule_sweep": {
                "runs": mosaic_sweep_runs,
                "disagreements": mosaic_disagreements,
                "clopper_pearson_95_upper_bound_disagreement": round(cp95_mosaic, 6),
            },
            "fault_injection_tamper_test": {
                "mutation": tamper_meta,
                "expected_tampered_digest": WAIOS_CHANGED_DIGEST,
                "observed_tampered_digest": tamper_observed_digest,
                "disagreement_halt_triggered": tamper_caught,
                "receipt_sealed": tamper_receipt_emitted,
            },
            "cross_fabric_lanes": cross_fabric,
        },
        "spellcheck_lookup_first_cascade": {
            "workload_queries": n_q,
            "stage_routing_counts": stage_breakdown,
            "stage_routing_fractions": {k: round(v / n_q, 4) for k, v in stage_breakdown.items()},
            "always_mosaic_escalated_queries": always_mosaic_escalated,
            "metered_pipelines_local_rapl": arms_summary,
            "metered_pipelines_local_silicon": arms_summary,
            "same_meter_comparisons": same_meter_ratios,
            "analytical_frontier_est_j_reference_strictly_separate": {
                "evidence_class": "est_j",
                "mixed_or_summed_with_reported_j": False,
                "mixed_or_summed_with_measured_j": False,
                "assumed_remote_frontier_call_est_j": 1.50,
                "frontier_only_1000_calls_est_j": 1500.0,
                "cascade_residual_only_calls": stage_breakdown["stage4_escalated"],
                "cascade_remote_escalation_est_j": round(1.50 * stage_breakdown["stage4_escalated"], 2),
                "analytical_frontier_call_avoidance_ratio_x": round(1.0 / max(escalated_frac, 1e-9), 2),
                "note": "Analytical cloud call estimate (`est_j`) kept strictly separate from local `measured_j` and `reported_j`.",
            },
            "cascade_grid_sweep": cascade_grid_sweep,
        },
    }

    master_receipt = seal_signed_receipt(
        kit_id="kits/waios-mosaic-cascade",
        payload={
            "substrate_id": telemetry_meta.get("substrate_id"),
            "waios_reference_digest": WAIOS_REFERENCE_DIGEST,
            "tamper_digest_caught": tamper_observed_digest,
            "mosaic_sweep_runs": mosaic_sweep_runs,
            "mosaic_sweep_disagreements": mosaic_disagreements,
            "cascade_stage_counts": stage_breakdown,
            "grid_cells_evaluated": len(cascade_grid_sweep),
            "energy_evidence_class": meter.evidence_class,
            "results_blake3": blake3_derive_key_hex(
                "openie.kit.waios_mosaic_cascade.results.v2",
                json.dumps(results, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            ),
        },
        domain_context="openie.kit.waios_mosaic_cascade.receipt.v2",
    )
    assert verify_signed_receipt(master_receipt)
    md = _render_markdown(results, master_receipt)
    return results, master_receipt, md


def _render_markdown(res: dict[str, Any], receipt: dict[str, Any]) -> str:
    conf = res["waios_conformance_and_fault_halt"]
    cas = res["spellcheck_lookup_first_cascade"]
    tel = res["energy_telemetry"]
    sm = cas["same_meter_comparisons"]
    est = cas["analytical_frontier_est_j_reference_strictly_separate"]

    lines = [
        "# Kit 5 (`waios-mosaic-cascade`) — Cross-Lane Conformance & 4-Stage Cascade Results",
        "",
        f"- **Provenance Tier:** `{res['provenance_tier']}` (`Apache-2.0`)",
        f"- **Host CPU & OS:** `{res['host']['cpu_model']}` (`{res['host']['os_kernel']}`, `{res['host']['cc_version']}`)",
        f"- **Energy Evidence Class:** **`{tel['evidence_class']}`** (`board_metered = {tel.get('board_metered', False)}`; analytical `est_j` isolated in §3)",
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
            f"- **Signed Receipt (`BLAKE3` + `Ed25519`):** `{receipt['body_blake3'][:24]}...` (offline signature check: `PASS`)",
            "",
            "## 1. Canonical `waiOS` `256×128` Cross-Lane Invariance & Fault-Injection Halt",
            "",
            "| Execution Lane / Test | Observed `BLAKE3` (`waios.tmac.v1`) | Matches `a541323b...46f0` | Receipt Action |",
            "|---|---|---|---|",
        ]
    )
    for lname, ldig in conf["lane_digests"].items():
        lines.append(f"| `{lname}` | `{ldig}` | **`YES`** | Sealed |")
    cf_fabrics = conf.get("cross_fabric_lanes", {}).get("fabrics", {})
    for fname, fmeta in cf_fabrics.items():
        if fmeta.get("matches_reference"):
            lines.append(f"| `{fname}` | `{fmeta['observed_digest']}` | **`YES`** | Sealed |")
    ft = conf["fault_injection_tamper_test"]
    lines.append(
        f"| `fault_injection_row77` (`w[77,{ft['mutation']['col']}]: {ft['mutation']['from']} -> {ft['mutation']['to']}`) | "
        f"`{ft['observed_tampered_digest']}` | **`NO` (expected tamper)** | **HALTED · Receipt Refused** |"
    )
    sw = conf["hetero_mosaic_schedule_sweep"]
    sc = cas["stage_routing_counts"]
    lines.extend(
        [
            "",
            f"- **Multi-Schedule HeteroMosaic Sweep:** `{sw['disagreements']} / {sw['runs']}` disagreements (95% Clopper–Pearson upper bound `<= {sw['clopper_pearson_95_upper_bound_disagreement']}`).",
            "",
            f"## 2. 4-Stage Spellcheck Lookup-First Cascade (`1,000` Queries — Local Silicon `{tel['evidence_class']}`)",
            "",
            f"- **Stage Routing (`1,000` queries):** Stage 1 LUT = **`{sc['stage1_lut']}`**, Stage 2 Sparse = **`{sc['stage2_sparse']}`**, Stage 3 Mosaic = **`{sc['stage3_mosaic']}`**, Stage 4 Escalated = **`{sc['stage4_escalated']}`**.",
            "",
        ]
    )

    if tel["evidence_class"] == "measured_j":
        lines.append("| Pipeline | Correct / `1,000` | Wall `µs / correct` (`IQR`) | Gross Rail `measured_j` `µJ / correct` | Net-Above-Idle `measured_j` `µJ / correct` |")
        lines.append("|---|---:|---:|---:|---:|")
        for arm in ("spellcheck_4stage_cascade", "always_stage3_mosaic_plus_gate", "always_dense_teacher_baseline"):
            a = cas["metered_pipelines_local_silicon"][arm]
            w = a["wall_us_per_correct_completion"]
            g = a["gross_rail_measured_uj_per_correct_completion"]
            n_a12 = a["net_above_idle_a1_a2_measured_uj_per_correct_completion"]
            n_adj = a["paired_round_net_above_idle_measured_uj_per_correct_completion"]
            n_str = f"`{n_a12['median']}` (A1/A2)" if n_a12 else (f"`{n_adj['median']}` (paired; F6 gated)" if n_adj else "`n/a`")
            lines.append(
                f"| `{arm}` | **`{a['correct_completions']} / {a['queries_per_pass']}`** | `{w['median']}` (`{w['p25']}–{w['p75']}`) | **`{g['median']}`** (`{g['p25']}–{g['p75']}`) | {n_str} |"
            )
    else:
        lines.append("| Pipeline | Correct / `1,000` | Wall `µs / correct` (`IQR`) | Package `reported_j` `µJ / correct` (`IQR`) | Core `reported_j` `µJ / correct` |")
        lines.append("|---|---:|---:|---:|---:|")
        for arm in ("spellcheck_4stage_cascade", "always_stage3_mosaic_plus_gate", "always_dense_teacher_baseline"):
            a = cas["metered_pipelines_local_silicon"][arm]
            w = a["wall_us_per_correct_completion"]
            p = a["pkg_reported_uj_per_correct_completion"]
            c = a["core_reported_uj_per_correct_completion"]
            p_str = f"**`{p['median']}`** (`{p['p25']}–{p['p75']}`)" if p else "`unmetered`"
            c_str = f"`{c['median']}`" if c else "`unmetered`"
            lines.append(
                f"| `{arm}` | **`{a['correct_completions']} / {a['queries_per_pass']}`** | `{w['median']}` (`{w['p25']}–{w['p75']}`) | {p_str} | {c_str} |"
            )

    lines.extend(
        [
            "",
            f"- **Parameter Grid Sweep Evaluated:** `{len(cas['cascade_grid_sweep'])}` `(Zipf s, d_max, margin tau)` configurations.",
            "",
            "## 3. Isolated Analytical Cloud Escalation Reference (`est_j` — Never Summed with `measured_j` or `reported_j`)",
            "",
            "| Analytical Scenario (`evidence_class = est_j`) | Remote Frontier Calls | Analytical `est_j` (`@ 1.50 J/call`) | Call Avoidance |",
            "|---|---:|---:|---:|",
            f"| Frontier-Only Pipeline (`100%` remote calls) | `1,000` | `{est['frontier_only_1000_calls_est_j']:.2f} est_j` | `1.00x` |",
            f"| 4-Stage Cascade (`Stage 4` residual only) | `{est['cascade_residual_only_calls']}` | `{est['cascade_remote_escalation_est_j']:.2f} est_j` | **`{est['analytical_frontier_call_avoidance_ratio_x']}x`** |",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Run Kit 5 (waios-mosaic-cascade) conformance & cascade benchmark")
    ap.add_argument("--quick", action="store_true", help="Run reduced trial counts for fast verification")
    ap.add_argument("--out-dir", type=Path, default=KIT_ROOT / "results")
    ap.add_argument("--tag", type=str, default="", help="Optional substrate tag suffix for output files")
    args = ap.parse_args()

    results, receipt, md = run_full_kit(quick=args.quick)
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
        (args.out_dir / "waios_mosaic_cascade_results.json").write_text(res_json, encoding="utf-8")
        (args.out_dir / "waios_mosaic_receipt.json").write_text(rec_json, encoding="utf-8")
        if not args.quick:
            (KIT_ROOT / "RESULTS.md").write_text(md, encoding="utf-8")
        else:
            (args.out_dir / "RESULTS_quick.md").write_text(md, encoding="utf-8")

    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
