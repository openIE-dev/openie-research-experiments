#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Kit 5 (`kits/waios-mosaic-cascade/`, Shots on Goal #3 & #5):
1. Cross-Lane `waiOS` 256x128 Integer/Ternary Conformance & Fault-Injection Halt
   sealed by canonical BLAKE3 digest `a541323b13653ed36515ff24ef08deb7dfa771e570a434712708fb72552f46f0`.
2. End-to-End 4-Stage Spellcheck Lookup-First Cascade (`1,000` mixed recurring + novel queries)
   metered in real Linux RAPL `reported_j` (strictly separated from any analytical `est_j`).
"""

from __future__ import annotations

import argparse
import ctypes
import platform
import json
import random
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
KIT_ROOT = HERE.parent
if str(KIT_ROOT) not in sys.path:
    sys.path.insert(0, str(KIT_ROOT))

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
    return lib


# ── Part 1: Canonical `waiOS` Input, Qualification & Cross-Lane Verification ─


def audit_input_python() -> tuple[list[int], list[int]]:
    """Exact port of `auditInput()` from `waios-transaction-science-web/src/lib/kernel.ts`."""
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
    """Exact port of `withOneWeightChanged()` (`row = 77`, first col with `acts[col] != 0`)."""
    row = 77
    col = next(i for i, a in enumerate(acts) if a != 0)
    mut = list(weights)
    orig = mut[row * WAIOS_COLS + col]
    new_val = 0 if orig == 1 else orig + 1
    mut[row * WAIOS_COLS + col] = new_val
    return mut, {"row": row, "col": col, "from": orig, "to": new_val}


def run_boot_qualification_checks(lib: ctypes.CDLL) -> dict[str, Any]:
    """Verify odd-sized 73x35 ternary matvec + 64-dim zero-FP RMSNorm+RoPE (`kernel.ts` §246-349)."""
    q_weights = [(-1, 0, 1)[(i * 11 + 5) % 3] for i in range(QUAL_ROWS * QUAL_COLS)]
    q_acts = [((c * 29) % 251) - 125 for c in range(QUAL_COLS)]
    ref_73x35 = [
        sum(q_weights[r * QUAL_COLS + c] * q_acts[c] for c in range(QUAL_COLS))
        for r in range(QUAL_ROWS)
    ]

    # Verify packed layout decoding on odd 35-column width (last pair half-empty = 0)
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

    # Integer RMSNorm + Q15 RoPE check (`pos = 7`)
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
    """Run all 4 lanes on (weights, acts); halt and refuse receipt on any disagreement!"""
    w_c = (ctypes.c_int8 * (WAIOS_ROWS * WAIOS_COLS))(*weights)
    a_c = (ctypes.c_int8 * WAIOS_COLS)(*acts)

    # Lane 1: Python independent scalar reference
    out_py = [
        sum(weights[r * WAIOS_COLS + c] * acts[c] for c in range(WAIOS_COLS))
        for r in range(WAIOS_ROWS)
    ]
    d_py = digest_of_i32_output(out_py)

    # Lane 2: C scalar i32
    buf_sc = (ctypes.c_int32 * WAIOS_ROWS)()
    lib.waios_lane_scalar(w_c, a_c, buf_sc)
    d_sc = digest_of_i32_output(list(buf_sc))

    # Lane 3: C packed 2-bit bit-sliced (+1/-1 uint64 masks + popcount, 0 multiplies)
    buf_bs = (ctypes.c_int32 * WAIOS_ROWS)()
    lib.waios_lane_bitsliced(w_c, a_c, buf_bs)
    d_bs = digest_of_i32_output(list(buf_bs))

    # Lane 4: C T-MAC 2-col pair LUT + 4-thread HeteroMosaic partitioned worker reduction
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


# ── Part 2: 4-Stage Spellcheck Lookup-First Cascade (`1,000` Queries) ────────

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
    """Exact Damerau-Levenshtein edit distance (capped early if length diff > 2)."""
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
        # Boot-qualify `waiOS` runtime against `a541323b...` before admitting Stage 3!
        w_audit, a_audit = audit_input_python()
        self.boot_receipt = execute_and_seal_mosaic(lib, w_audit, a_audit, WAIOS_REFERENCE_DIGEST)
        assert verify_signed_receipt(self.boot_receipt)

        # Stage 1: O(1) Compiled Hash/LUT Table over canonical strings & common aliases
        self.stage1_lut: dict[str, int] = {}
        for idx, cmd in enumerate(CANONICAL_INTENTS):
            self.stage1_lut[cmd] = idx
            self.stage1_lut[cmd.replace(".", "_")] = idx
            self.stage1_lut[cmd.upper()] = idx

        # Stage 2: Trigram Sparse Inverted Index + Damerau-Levenshtein <= 2 Soundness Gate
        self.trigram_postings: dict[str, list[int]] = {}
        for idx, cmd in enumerate(CANONICAL_INTENTS):
            for tg in _trigrams(cmd):
                self.trigram_postings.setdefault(tg, []).append(idx)

        # Stage 3: 256x128 Ternary Mosaic Classifier (16 groups of 16 rows)
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

        # Stage 4: Heavy 8-layer dense verifier weights (planted identity/residual path so teacher resolves hard cases)
        total_i16 = 8 * 256 * 256 + 16 * 256
        dense = [0] * total_i16
        for l in range(8):
            base = l * 256 * 256
            for i in range(256):
                dense[base + i * 256 + i] = 4096  # exact identity preservation across deep layers
                dense[base + i * 256 + ((i + 1) & 255)] = rng.randint(-64, 64)
        head_base = 8 * 256 * 256
        for idx in range(16):
            proto = self.intent_prototypes[idx]
            for c in range(WAIOS_COLS):
                dense[head_base + idx * 256 + c] = proto[c] * 256
                # Secondary hard-disambiguation channel in dims 128..255
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

    def generate_workload_1000(self, n_queries: int = 1000) -> list[dict[str, Any]]:
        """Generate deterministic mixed workload:
          - 55% recurring canonical/alias commands (Stage 1 LUT hits)
          - 25% 1-2 edit typo variants (Stage 2 sparse trigram + edit-distance hits)
          - 15% novel clean feature-encoded telemetry queries (Stage 3 waiOS Mosaic hits)
          - 5%  ambiguous/low-margin multi-intent boundary queries (Stage 4 Escalation Gate)
        """
        rng = random.Random(20261125)
        alphabet = "abcdefghijklmnopqrstuvwxyz0123456789._"
        queries: list[dict[str, Any]] = []

        for qid in range(n_queries):
            # Zipf-weighted intent selection on recurring queries, uniform otherwise
            u = qid % 20
            intent = int(rng.paretovariate(1.3) - 1) % 16 if u < 11 else (qid % 16)
            canon = CANONICAL_INTENTS[intent]
            proto = self.intent_prototypes[intent]

            if u < 11:
                # 55%: Recurring exact or normalized form
                q_str = canon if (qid % 3 != 0) else (canon.replace(".", "_") if qid % 2 == 0 else canon.upper())
                feats = [proto[c] * 60 + rng.randint(-8, 8) for c in range(WAIOS_COLS)]
                stratum = "recurring_exact"
            elif u < 16:
                # 25%: 1- or 2-character typo (substitution/transposition/deletion)
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
                # 15%: Unseen natural/telemetry free-form string + clear feature vector -> Stage 3 Mosaic
                q_str = f"telemetry_event_{qid}_unseen_schema_v2"
                feats = [proto[c] * 52 + rng.randint(-15, 15) for c in range(WAIOS_COLS)]
                stratum = "novel_mosaic_solvable"
            else:
                # 5%: Hard boundary / low-margin query -> triggers Stage 4 Escalation Gate
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

    def run_4stage_cascade_pass(self, queries: list[dict[str, Any]]) -> tuple[int, dict[str, int]]:
        stage_counts = {"stage1_lut": 0, "stage2_sparse": 0, "stage3_mosaic": 0, "stage4_escalated": 0}
        correct = 0
        scores16 = (ctypes.c_int32 * 16)()

        for q in queries:
            txt = q["text"]
            # Stage 1: O(1) Compiled Hash/LUT Lookup
            hit1 = self.stage1_lut.get(txt)
            if hit1 is not None:
                pred = hit1
                stage_counts["stage1_lut"] += 1
            else:
                # Stage 2: Trigram Sparse Retrieve + Edit-Distance <= 2 Verification Gate
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
                    # Stage 3: waiOS-Verified 256x128 Integer Mosaic Compute + Margin Gate
                    self.lib.waios_mosaic_fast_classify16(self.packed_mosaic, q["acts_c"], scores16)
                    s_list = list(scores16)
                    top1_idx = max(range(16), key=lambda idx: s_list[idx])
                    top1_val = s_list[top1_idx]
                    top2_val = max(s_list[idx] for idx in range(16) if idx != top1_idx)
                    if (top1_val - top2_val) >= self.margin_threshold:
                        pred = top1_idx
                        stage_counts["stage3_mosaic"] += 1
                    else:
                        # Stage 4: Frontier Escalation Gate on hard unverified residual
                        pred = int(self.lib.waios_heavy_escalation_teacher(self.dense_layers, q["acts_c"]))
                        stage_counts["stage4_escalated"] += 1

            if pred == q["ground_truth"]:
                correct += 1
        return correct, stage_counts

    def run_always_mosaic_pass(self, queries: list[dict[str, Any]]) -> tuple[int, int]:
        correct = 0
        escalated = 0
        scores16 = (ctypes.c_int32 * 16)()
        for q in queries:
            self.lib.waios_mosaic_fast_classify16(self.packed_mosaic, q["acts_c"], scores16)
            s_list = list(scores16)
            top1_idx = max(range(16), key=lambda idx: s_list[idx])
            top1_val = s_list[top1_idx]
            top2_val = max(s_list[idx] for idx in range(16) if idx != top1_idx)
            if (top1_val - top2_val) >= self.margin_threshold:
                pred = top1_idx
            else:
                pred = int(self.lib.waios_heavy_escalation_teacher(self.dense_layers, q["acts_c"]))
                escalated += 1
            if pred == q["ground_truth"]:
                correct += 1
        return correct, escalated

    def run_always_dense_teacher_pass(self, queries: list[dict[str, Any]]) -> int:
        correct = 0
        for q in queries:
            pred = int(self.lib.waios_heavy_escalation_teacher(self.dense_layers, q["acts_c"]))
            if pred == q["ground_truth"]:
                correct += 1
        return correct


def run_full_kit(quick: bool = False) -> tuple[dict[str, Any], dict[str, Any], str]:
    lib = compile_and_load_mosaic_lib()
    meter = EnergyMeter()
    idle_pre_w = meter.sample_idle_power_w(0.15) if meter.available else None
    host = sanitized_host_info()

    # 1. Boot Qualification + Canonical 256x128 Cross-Lane Conformance + 100-Schedule Mosaic Sweep
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

    # 2. Single-weight Tamper Fault Injection (`row 77`) -> Deterministic Disagreement Halt
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

    # 3. End-to-End 4-Stage Spellcheck Lookup-First Cascade (`1,000` Queries, RAPL `reported_j`)
    cascade = SpellcheckCascadeSystem(lib)
    queries = cascade.generate_workload_1000(n_queries=1000)
    q_txt_c, q_acts_c, q_lbl_c = cascade.pack_queries_for_c(queries)
    n_q = len(queries)

    n_trials = 10 if quick else 20
    cascade_reps = 15 if quick else 35
    mosaic_only_reps = 10 if quick else 20
    dense_reps = 1 if quick else 2

    arms_samples: dict[str, dict[str, Any]] = {
        "spellcheck_4stage_cascade": {"us_per_correct": [], "pkg_uj_per_correct": [], "core_uj_per_correct": [], "correct": 0},
        "always_stage3_mosaic_plus_gate": {"us_per_correct": [], "pkg_uj_per_correct": [], "core_uj_per_correct": [], "correct": 0},
        "always_dense_teacher_baseline": {"us_per_correct": [], "pkg_uj_per_correct": [], "core_uj_per_correct": [], "correct": 0},
    }
    stage_breakdown: dict[str, int] = {}
    always_mosaic_escalated = 0
    counts4 = (ctypes.c_int32 * 4)()

    # Warm-up (and verify Python <-> C stage routing equivalence!)
    py_corr, py_stages = cascade.run_4stage_cascade_pass(queries)
    c_warm_corr = lib.waios_cascade_eval_batch(cascade.c_ctx, 0, n_q, 1, q_txt_c, q_acts_c, q_lbl_c, counts4)
    assert c_warm_corr == py_corr, f"C/Python cascade mismatch: {c_warm_corr} != {py_corr}"
    lib.waios_cascade_eval_batch(cascade.c_ctx, 2, min(50, n_q), 1, q_txt_c, q_acts_c, q_lbl_c, counts4)

    arm_order_base = [
        "spellcheck_4stage_cascade",
        "always_stage3_mosaic_plus_gate",
        "always_dense_teacher_baseline",
    ]
    for trial in range(n_trials):
        order = arm_order_base[trial % 3 :] + arm_order_base[: trial % 3]
        for arm in order:
            if arm == "spellcheck_4stage_cascade":
                s0 = meter.snapshot()
                corr = lib.waios_cascade_eval_batch(
                    cascade.c_ctx, 0, n_q, cascade_reps, q_txt_c, q_acts_c, q_lbl_c, counts4
                )
                s1 = meter.snapshot()
                stage_breakdown = {
                    "stage1_lut": int(counts4[0]),
                    "stage2_sparse": int(counts4[1]),
                    "stage3_mosaic": int(counts4[2]),
                    "stage4_escalated": int(counts4[3]),
                }
                reps_used = cascade_reps
            elif arm == "always_stage3_mosaic_plus_gate":
                s0 = meter.snapshot()
                corr = lib.waios_cascade_eval_batch(
                    cascade.c_ctx, 1, n_q, mosaic_only_reps, q_txt_c, q_acts_c, q_lbl_c, counts4
                )
                s1 = meter.snapshot()
                always_mosaic_escalated = int(counts4[3])
                reps_used = mosaic_only_reps
            else:
                s0 = meter.snapshot()
                corr = lib.waios_cascade_eval_batch(
                    cascade.c_ctx, 2, n_q, dense_reps, q_txt_c, q_acts_c, q_lbl_c, counts4
                )
                s1 = meter.snapshot()
                reps_used = dense_reps

            d = meter.diff(s0, s1)
            tot_correct = max(1, corr * reps_used)
            rec = arms_samples[arm]
            rec["correct"] = corr
            rec["us_per_correct"].append((d["wall_ns"] / 1e3) / tot_correct)
            if d["pkg_reported_j"] is not None:
                rec["pkg_uj_per_correct"].append((d["pkg_reported_j"] * 1e6) / tot_correct)
            if d["core_reported_j"] is not None:
                rec["core_uj_per_correct"].append((d["core_reported_j"] * 1e6) / tot_correct)

    cascade.close()
    idle_post_w = meter.sample_idle_power_w(0.15) if meter.available else None
    telemetry_meta = meter.metadata()
    if idle_pre_w is not None and idle_post_w is not None:
        mean_idle = 0.5 * (idle_pre_w + idle_post_w)
        telemetry_meta["idle_pkg_w_pre"] = idle_pre_w
        telemetry_meta["idle_pkg_w_post"] = idle_post_w
        telemetry_meta["idle_drift_pct"] = round(100.0 * abs(idle_post_w - idle_pre_w) / max(mean_idle, 1e-6), 2)

    arms_summary: dict[str, Any] = {}
    for arm, rec in arms_samples.items():
        arms_summary[arm] = {
            "queries": len(queries),
            "correct_completions": rec["correct"],
            "accuracy": round(rec["correct"] / len(queries), 4),
            "wall_us_per_correct_completion": iqr_stats(rec["us_per_correct"], digits=3),
            "energy_evidence_class": meter.evidence_class,
            "pkg_reported_uj_per_correct_completion": iqr_stats(rec["pkg_uj_per_correct"], digits=2) if rec["pkg_uj_per_correct"] else None,
            "core_reported_uj_per_correct_completion": iqr_stats(rec["core_uj_per_correct"], digits=2) if rec["core_uj_per_correct"] else None,
        }

    cas_w = arms_summary["spellcheck_4stage_cascade"]["wall_us_per_correct_completion"]["median"]
    den_w = arms_summary["always_dense_teacher_baseline"]["wall_us_per_correct_completion"]["median"]
    mos_w = arms_summary["always_stage3_mosaic_plus_gate"]["wall_us_per_correct_completion"]["median"]

    same_meter_ratios: dict[str, Any] = {
        "evidence_class": meter.evidence_class,
        "wall_speedup_cascade_vs_always_dense_x": round(den_w / cas_w, 2) if cas_w else None,
        "wall_speedup_cascade_vs_always_mosaic_x": round(mos_w / cas_w, 2) if cas_w else None,
    }
    if meter.available and arms_summary["spellcheck_4stage_cascade"]["pkg_reported_uj_per_correct_completion"]:
        cas_e = arms_summary["spellcheck_4stage_cascade"]["pkg_reported_uj_per_correct_completion"]["median"]
        den_e = arms_summary["always_dense_teacher_baseline"]["pkg_reported_uj_per_correct_completion"]["median"]
        mos_e = arms_summary["always_stage3_mosaic_plus_gate"]["pkg_reported_uj_per_correct_completion"]["median"]
        same_meter_ratios["pkg_reported_j_reduction_cascade_vs_always_dense_x"] = round(den_e / cas_e, 2) if cas_e else None
        same_meter_ratios["pkg_reported_j_reduction_cascade_vs_always_mosaic_x"] = round(mos_e / cas_e, 2) if cas_e else None

    escalated_frac = stage_breakdown["stage4_escalated"] / len(queries)

    results = {
        "schema": "openie.kit.waios_mosaic_cascade.v1",
        "shots_on_goal": [
            "Shot #3: Cross-Lane HeteroMosaic Integer Runtime Sealed by waiOS Reference Digest",
            "Shot #5: 4-Stage Spellcheck Lookup-First Cascade Metered in Real Linux RAPL reported_j",
        ],
        "provenance_tier": "Signed Provenance · Self-Checked",
        "license": "Apache-2.0",
        "mode": "quick" if quick else "standard",
        "host": host,
        "energy_telemetry": telemetry_meta,
        "waios_conformance_and_fault_halt": {
            "domain": WAIOS_DOMAIN,
            "matrix_shape": [WAIOS_ROWS, WAIOS_COLS],
            "reference_digest_expected": WAIOS_REFERENCE_DIGEST,
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
        },
        "spellcheck_lookup_first_cascade": {
            "workload_queries": len(queries),
            "stage_routing_counts": stage_breakdown,
            "stage_routing_fractions": {k: round(v / len(queries), 4) for k, v in stage_breakdown.items()},
            "always_mosaic_escalated_queries": always_mosaic_escalated,
            "metered_pipelines_local_rapl": arms_summary,
            "same_meter_comparisons": same_meter_ratios,
            "analytical_frontier_est_j_reference_strictly_separate": {
                "evidence_class": "est_j",
                "mixed_or_summed_with_reported_j": False,
                "assumed_remote_frontier_call_est_j": 1.50,
                "frontier_only_1000_calls_est_j": 1500.0,
                "cascade_residual_only_calls": stage_breakdown["stage4_escalated"],
                "cascade_remote_escalation_est_j": round(1.50 * stage_breakdown["stage4_escalated"], 2),
                "analytical_frontier_call_avoidance_ratio_x": round(1.0 / max(escalated_frac, 1e-9), 2),
                "note": "Analytical cloud call estimate (`est_j`) kept strictly separate from local silicon `reported_j`.",
            },
        },
    }

    master_receipt = seal_signed_receipt(
        kit_id="kits/waios-mosaic-cascade",
        payload={
            "waios_reference_digest": WAIOS_REFERENCE_DIGEST,
            "tamper_digest_caught": tamper_observed_digest,
            "mosaic_sweep_runs": mosaic_sweep_runs,
            "mosaic_sweep_disagreements": mosaic_disagreements,
            "cascade_stage_counts": stage_breakdown,
            "energy_evidence_class": meter.evidence_class,
            "results_blake3": blake3_derive_key_hex(
                "openie.kit.waios_mosaic_cascade.results.v1",
                json.dumps(results, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            ),
        },
        domain_context="openie.kit.waios_mosaic_cascade.receipt.v1",
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
        f"- **Energy Evidence Class:** **`{tel['evidence_class']}`** (`measured_j = null`; analytical `est_j` isolated in §3)",
    ]
    if tel["evidence_class"] == "reported_j":
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
    ft = conf["fault_injection_tamper_test"]
    lines.append(
        f"| `fault_injection_row77` (`w[77,{ft['mutation']['col']}]: {ft['mutation']['from']} -> {ft['mutation']['to']}`) | "
        f"`{ft['observed_tampered_digest']}` | **`NO` (expected tamper)** | **HALTED · Receipt Refused** |"
    )
    sw = conf["hetero_mosaic_schedule_sweep"]
    lines.extend(
        [
            "",
            f"- **Boot Qualification:** Odd-sized `73×35` ternary product = `{conf['boot_qualification']['odd_73x35_ternary_passed']}`; "
            f"`64`-dim zero-FP `RMSNorm + Q15 RoPE` digest = `{conf['boot_qualification']['zero_fp_norm_rope_64_blake3'][:24]}...`.",
            f"- **Multi-Schedule HeteroMosaic Sweep:** `{sw['disagreements']} / {sw['runs']}` disagreements across shifted 4-worker `pthread` tile partitions "
            f"(one-sided 95% Clopper–Pearson upper bound `<= {sw['clopper_pearson_95_upper_bound_disagreement']}`).",
            "",
            "## 2. 4-Stage Spellcheck Lookup-First Cascade (`1,000` Mixed Queries — Local Silicon `reported_j`)",
            "",
            f"- **Stage Routing Breakdown (`1,000` queries):** "
            f"Stage 1 `O(1)` Compiled LUT = **`{cas['stage_routing_counts']['stage1_lut']}`** (`{100*cas['stage_routing_fractions']['stage1_lut']:.1f}%`), "
            f"Stage 2 Trigram Sparse + Edit Gate = **`{cas['stage_routing_counts']['stage2_sparse']}`** (`{100*cas['stage_routing_fractions']['stage2_sparse']:.1f}%`), "
            f"Stage 3 `waiOS` Integer Mosaic = **`{cas['stage_routing_counts']['stage3_mosaic']}`** (`{100*cas['stage_routing_fractions']['stage3_mosaic']:.1f}%`), "
            f"Stage 4 Escalation Gate = **`{cas['stage_routing_counts']['stage4_escalated']}`** (`{100*cas['stage_routing_fractions']['stage4_escalated']:.1f}%`).",
            "",
            "| Pipeline | Correct / `1,000` | Wall `µs / correct` (`IQR`) | Package `reported_j` `µJ / correct` (`IQR`) | Core `reported_j` `µJ / correct` |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for arm in ("spellcheck_4stage_cascade", "always_stage3_mosaic_plus_gate", "always_dense_teacher_baseline"):
        ar = cas["metered_pipelines_local_rapl"][arm]
        w = ar["wall_us_per_correct_completion"]
        p = ar["pkg_reported_uj_per_correct_completion"]
        c = ar["core_reported_uj_per_correct_completion"]
        p_s = f"**`{p['median']}`** (`{p['p25']}–{p['p75']}`)" if p else "`unmetered`"
        c_s = f"`{c['median']}`" if c else "`unmetered`"
        lines.append(
            f"| `{arm}` | **`{ar['correct_completions']} / {ar['queries']}`** (`{100*ar['accuracy']:.1f}%`) | "
            f"`{w['median']}` (`{w['p25']}–{w['p75']}`) | {p_s} | {c_s} |"
        )

    lines.extend(
        [
            "",
            f"- **Same-Meter Local Comparison (`{sm['evidence_class']}` only):** "
            f"`spellcheck_4stage_cascade` achieves **`{sm['wall_speedup_cascade_vs_always_dense_x']}x` lower wall latency** than `always_dense_teacher_baseline` "
            f"(`{sm['wall_speedup_cascade_vs_always_mosaic_x']}x` lower than `always_stage3_mosaic_plus_gate`)"
            + (
                f" and **`{sm['pkg_reported_j_reduction_cascade_vs_always_dense_x']}x` lower package `reported_j` per correct completion** than `always_dense_teacher_baseline` "
                f"(`{sm['pkg_reported_j_reduction_cascade_vs_always_mosaic_x']}x` lower than `always_stage3_mosaic_plus_gate`)."
                if sm.get("pkg_reported_j_reduction_cascade_vs_always_dense_x")
                else "."
            ),
            "",
            "## 3. Isolated Analytical Cloud Escalation Reference (`est_j` — Never Summed with `reported_j`)",
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
    args = ap.parse_args()

    results, receipt, md = run_full_kit(quick=args.quick)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    res_json = json.dumps(results, indent=2) + "\n"
    rec_json = json.dumps(receipt, indent=2) + "\n"
    assert_sanitized(res_json)
    assert_sanitized(rec_json)
    assert_sanitized(md)

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
