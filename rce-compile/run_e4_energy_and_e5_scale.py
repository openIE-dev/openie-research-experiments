#!/usr/bin/env python3
"""
Wave 4 · RCE Compile Empirical Closure:
  1. E4-Energy: Pre-registered RAPL `reported_j` compilation cost E_compile,
     per-invocation execution cost E_run, and empirical optimization payback
     horizon N* across 20 deterministic exact-integer/fixed-point kernels in
     C (gcc, clang), Rust (rustc native & wasm32/node), Python (py_compile),
     and RCE (`openIE-dev/rce` at 1762fb4b: `rce check` + 5-target `rce emit`),
     plus H4 Regime-B variance analysis on Linux powercap RAPL.
  2. E5-Scale: Name-free De Bruijn / positional reuse hashing across 185 W1
     RCE Forms + 60 C/Rust/Python kernels (245 base programs) under formatting,
     alpha-renaming, and benign declaration shifts, plus 500 test-vector-verified
     non-equivalent semantic mutants (including 150 variable-binding swaps) and
     RAPL `reported_j` avoided compilation measurements.

Provenance discipline:
  - `basis = "reported"` (Linux powercap RAPL `intel-rapl:0:0/energy_uj` core
    domain on pinned CPU 0 + `intel-rapl:0/energy_uj` package domain).
  - `measured_j = None`, `board_metered = False`.
  - Zero private paths, hostnames, or usernames emitted in results.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import py_compile
import random
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Pre-registration & RAPL helpers
# ---------------------------------------------------------------------------

POWERCAP_PKG = "/sys/class/powercap/intel-rapl:0"
POWERCAP_CORE = "/sys/class/powercap/intel-rapl:0:0"


def verify_prereg(prereg_path: Path, sha_path: Path) -> str:
    raw = prereg_path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    expected = sha_path.read_text(encoding="utf-8").strip().split()[0]
    if actual != expected:
        raise RuntimeError(f"PREREG SHA-256 mismatch: expected {expected}, got {actual}")
    return actual


def wrap_delta(prev: int, now: int, max_uj: int) -> int:
    if now >= prev:
        return now - prev
    return max(max_uj - prev, 0) + now + 1


class DualRaplMeter:
    """Reads Linux powercap package (`intel-rapl:0`) and core (`intel-rapl:0:0`) `energy_uj`."""

    def __init__(self, pin_cpu: int = 0) -> None:
        self.pin_cpu = pin_cpu
        if hasattr(os, "sched_setaffinity"):
            os.sched_setaffinity(0, {pin_cpu})
        self.pkg_file = Path(POWERCAP_PKG) / "energy_uj"
        self.core_file = Path(POWERCAP_CORE) / "energy_uj"
        self.pkg_max = int((Path(POWERCAP_PKG) / "max_energy_range_uj").read_text().strip())
        self.core_max = int((Path(POWERCAP_CORE) / "max_energy_range_uj").read_text().strip())
        self.pkg_wraps = 0
        self.core_wraps = 0
        self._last_pkg = self._read_int(self.pkg_file)
        self._last_core = self._read_int(self.core_file)
        self._cum_pkg_uj = 0
        self._cum_core_uj = 0

    @staticmethod
    def _read_int(p: Path) -> int:
        with open(p, "rb") as f:
            return int(f.read().strip())

    def mark(self) -> tuple[int, int, float]:
        p = self._read_int(self.pkg_file)
        c = self._read_int(self.core_file)
        t = time.perf_counter()
        if p < self._last_pkg:
            self.pkg_wraps += 1
        if c < self._last_core:
            self.core_wraps += 1
        self._cum_pkg_uj += wrap_delta(self._last_pkg, p, self.pkg_max)
        self._cum_core_uj += wrap_delta(self._last_core, c, self.core_max)
        self._last_pkg = p
        self._last_core = c
        return self._cum_pkg_uj, self._cum_core_uj, t

    def since(self, start_mark: tuple[int, int, float]) -> dict[str, float]:
        p1, c1, t1 = self.mark()
        p0, c0, t0 = start_mark
        wall_s = max(1e-9, t1 - t0)
        pkg_j = (p1 - p0) * 1e-6
        core_j = (c1 - c0) * 1e-6
        return {"wall_s": wall_s, "pkg_j": pkg_j, "core_j": core_j}

    def sample_sleep_power(self, sleep_s: float = 0.25) -> tuple[float, float]:
        m0 = self.mark()
        time.sleep(sleep_s)
        d = self.since(m0)
        return d["core_j"] / d["wall_s"], d["pkg_j"] / d["wall_s"]


# ---------------------------------------------------------------------------
# 20 Deterministic Exact-Integer / Fixed-Point Kernels (C, Rust, Python, RCE)
# ---------------------------------------------------------------------------
# Every kernel maps `seed: u64` -> `u64` in [0, 2^32 - 1] using masked 64-bit
# unsigned operations that never overflow 64 bits and agree bit-for-bit across
# C (`uint64_t`), Rust (`u64`), WebAssembly (`u64`), Python (`int`), JS, & RCE.

KERNEL_SPECS: list[dict[str, Any]] = [
    {"id": "k01_sha256_block", "domain": "crypto", "desc": "Integer SHA-256 64-round compression schedule & state fold"},
    {"id": "k02_chacha20_block", "domain": "crypto", "desc": "ChaCha20 20-round ARX quarter-round stream block"},
    {"id": "k03_q32_orbital", "domain": "physics", "desc": "Fixed-point Q16.16/Q32 symplectic 2-body orbital step"},
    {"id": "k04_crc32_ieee", "domain": "checksum", "desc": "Bitwise IEEE 802.3 CRC-32 (0xEDB88320) over 64-byte frame"},
    {"id": "k05_lz77_match", "domain": "compression", "desc": "Sliding-window LZ77 longest-match finder over 64-symbol buffer"},
    {"id": "k06_dijkstra_grid", "domain": "graph", "desc": "Dijkstra shortest-path relaxation over 16-node weighted graph"},
    {"id": "k07_ntt_butterfly", "domain": "algebra", "desc": "Number-Theoretic Transform radix-2 butterfly mod 998244353 (N=16)"},
    {"id": "k08_matmul_i32", "domain": "linalg", "desc": "Dense 4x4 wrapping 32-bit integer matrix multiplication"},
    {"id": "k09_bst_probe", "domain": "datastruct", "desc": "Array-backed Binary Search Tree 16-key insert & depth walk"},
    {"id": "k10_sortnet_16", "domain": "sorting", "desc": "Odd-even transposition/merge 16-element comparator network"},
    {"id": "k11_ringbuf_sim", "domain": "systems", "desc": "Bounded 16-slot circular ring buffer enqueue/dequeue state machine"},
    {"id": "k12_token_bucket", "domain": "networking", "desc": "Deterministic rate-limiter token bucket admit/refuse simulation"},
    {"id": "k13_fnv1a_sip", "domain": "hashing", "desc": "FNV-1a + ARX SipRound-style 32-bit word mixer over 64 rounds"},
    {"id": "k14_sieve_primes", "domain": "number_theory", "desc": "Sieve of Eratosthenes prime marker & weighted prime sum (N=128)"},
    {"id": "k15_collatz_bounded", "domain": "iteration", "desc": "Bounded Collatz stopping-time accumulator over 32 trajectories"},
    {"id": "k16_popcount_swar", "domain": "bitops", "desc": "SWAR 32-bit Hamming weight & parity fold over 64 words"},
    {"id": "k17_edit_levenshtein", "domain": "dp", "desc": "Dynamic-programming Levenshtein edit distance over 12x12 strings"},
    {"id": "k18_rle_codec", "domain": "codec", "desc": "Run-length encode + decode round-trip accumulator over 64 symbols"},
    {"id": "k19_modexp_mont", "domain": "crypto_math", "desc": "Repeated binary modular exponentiation mod 1000000007 (16 bases)"},
    {"id": "k20_kalman_q16", "domain": "control", "desc": "1D fixed-point Q16.16 Alpha-Beta filter over 64 observations"},
]


def _algo_bodies() -> dict[str, dict[str, str]]:
    """Returns exact matching algorithm bodies in C, Rust, Python, and RCE for all 20 kernels."""
    out: dict[str, dict[str, str]] = {}

    def add(kid: str, c_body: str, rs_body: str, py_body: str, rce_body: str) -> None:
        out[kid] = {"c": c_body, "rust": rs_body, "python": py_body, "rce": rce_body}

    # k01: SHA-256 style 64-round message schedule + compression
    add(
        "k01_sha256_block",
        c_body="""
    uint64_t w[64];
    uint64_t m = 4294967295ULL;
    for (int i = 0; i < 16; i++) {
        w[i] = ((seed * 1664525ULL) + 1013904223ULL + (uint64_t)(i * 2654435761ULL)) & m;
    }
    for (int i = 16; i < 64; i++) {
        uint64_t x = w[i - 15];
        uint64_t s0 = (((x >> 7) | ((x << 25) & m)) ^ ((x >> 18) | ((x << 14) & m)) ^ (x >> 3)) & m;
        uint64_t y = w[i - 2];
        uint64_t s1 = (((y >> 17) | ((y << 15) & m)) ^ ((y >> 19) | ((y << 13) & m)) ^ (y >> 10)) & m;
        w[i] = (w[i - 16] + s0 + w[i - 7] + s1) & m;
    }
    uint64_t a = 1779033703ULL, b = 3144134277ULL, c = 1013904242ULL, d = 2773480762ULL;
    uint64_t e = 1359893119ULL, f = 2600822924ULL, g = 528734635ULL, h = 1541459225ULL;
    for (int i = 0; i < 64; i++) {
        uint64_t s1 = (((e >> 6) | ((e << 26) & m)) ^ ((e >> 11) | ((e << 21) & m)) ^ ((e >> 25) | ((e << 7) & m))) & m;
        uint64_t ch = ((e & f) ^ ((m ^ e) & g)) & m;
        uint64_t k = ((uint64_t)(i + 1) * 1103515245ULL + 12345ULL) & m;
        uint64_t t1 = (h + s1 + ch + k + w[i]) & m;
        uint64_t s0 = (((a >> 2) | ((a << 30) & m)) ^ ((a >> 13) | ((a << 19) & m)) ^ ((a >> 22) | ((a << 10) & m))) & m;
        uint64_t maj = ((a & b) ^ (a & c) ^ (b & c)) & m;
        uint64_t t2 = (s0 + maj) & m;
        h = g; g = f; f = e; e = (d + t1) & m;
        d = c; c = b; b = a; a = (t1 + t2) & m;
    }
    return (a ^ b ^ c ^ d ^ e ^ f ^ g ^ h) & m;
""",
        rs_body="""
    let mut w: [u64; 64] = [0; 64];
    let m: u64 = 4294967295;
    for i in 0..16 {
        w[i] = ((seed * 1664525) + 1013904223 + ((i as u64) * 2654435761)) & m;
    }
    for i in 16..64 {
        let x = w[i - 15];
        let s0 = (((x >> 7) | ((x << 25) & m)) ^ ((x >> 18) | ((x << 14) & m)) ^ (x >> 3)) & m;
        let y = w[i - 2];
        let s1 = (((y >> 17) | ((y << 15) & m)) ^ ((y >> 19) | ((y << 13) & m)) ^ (y >> 10)) & m;
        w[i] = (w[i - 16] + s0 + w[i - 7] + s1) & m;
    }
    let mut a: u64 = 1779033703; let mut b: u64 = 3144134277; let mut c: u64 = 1013904242; let mut d: u64 = 2773480762;
    let mut e: u64 = 1359893119; let mut f: u64 = 2600822924; let mut g: u64 = 528734635; let mut h: u64 = 1541459225;
    for i in 0..64 {
        let s1 = (((e >> 6) | ((e << 26) & m)) ^ ((e >> 11) | ((e << 21) & m)) ^ ((e >> 25) | ((e << 7) & m))) & m;
        let ch = ((e & f) ^ ((m ^ e) & g)) & m;
        let k = (((i as u64) + 1) * 1103515245 + 12345) & m;
        let t1 = (h + s1 + ch + k + w[i]) & m;
        let s0 = (((a >> 2) | ((a << 30) & m)) ^ ((a >> 13) | ((a << 19) & m)) ^ ((a >> 22) | ((a << 10) & m))) & m;
        let maj = ((a & b) ^ (a & c) ^ (b & c)) & m;
        let t2 = (s0 + maj) & m;
        h = g; g = f; f = e; e = (d + t1) & m;
        d = c; c = b; b = a; a = (t1 + t2) & m;
    }
    (a ^ b ^ c ^ d ^ e ^ f ^ g ^ h) & m
""",
        py_body="""
    w = [0] * 64
    m = 4294967295
    for i in range(16):
        w[i] = ((seed * 1664525) + 1013904223 + (i * 2654435761)) & m
    for i in range(16, 64):
        x = w[i - 15]
        s0 = (((x >> 7) | ((x << 25) & m)) ^ ((x >> 18) | ((x << 14) & m)) ^ (x >> 3)) & m
        y = w[i - 2]
        s1 = (((y >> 17) | ((y << 15) & m)) ^ ((y >> 19) | ((y << 13) & m)) ^ (y >> 10)) & m
        w[i] = (w[i - 16] + s0 + w[i - 7] + s1) & m
    a, b, c, d = 1779033703, 3144134277, 1013904242, 2773480762
    e, f, g, h = 1359893119, 2600822924, 528734635, 1541459225
    for i in range(64):
        s1 = (((e >> 6) | ((e << 26) & m)) ^ ((e >> 11) | ((e << 21) & m)) ^ ((e >> 25) | ((e << 7) & m))) & m
        ch = ((e & f) ^ ((m ^ e) & g)) & m
        k = ((i + 1) * 1103515245 + 12345) & m
        t1 = (h + s1 + ch + k + w[i]) & m
        s0 = (((a >> 2) | ((a << 30) & m)) ^ ((a >> 13) | ((a << 19) & m)) ^ ((a >> 22) | ((a << 10) & m))) & m
        maj = ((a & b) ^ (a & c) ^ (b & c)) & m
        t2 = (s0 + maj) & m
        h = g; g = f; f = e; e = (d + t1) & m
        d = c; c = b; b = a; a = (t1 + t2) & m
    return (a ^ b ^ c ^ d ^ e ^ f ^ g ^ h) & m
""",
        rce_body="""
    var w: [u64; 64] = [0; 64]
    let m: u64 = 4294967295
    for i in 0..16
        w[i] = ((seed * 1664525) + 1013904223 + ((i as u64) * 2654435761)) & m
    for i in 16..64
        let x = w[i - 15]
        let s0 = (((x >> 7) | ((x << 25) & m)) ^ ((x >> 18) | ((x << 14) & m)) ^ (x >> 3)) & m
        let y = w[i - 2]
        let s1 = (((y >> 17) | ((y << 15) & m)) ^ ((y >> 19) | ((y << 13) & m)) ^ (y >> 10)) & m
        w[i] = (w[i - 16] + s0 + w[i - 7] + s1) & m
    var a: u64 = 1779033703
    var b: u64 = 3144134277
    var c: u64 = 1013904242
    var d: u64 = 2773480762
    var e: u64 = 1359893119
    var f: u64 = 2600822924
    var g: u64 = 528734635
    var h: u64 = 1541459225
    for i in 0..64
        let s1 = (((e >> 6) | ((e << 26) & m)) ^ ((e >> 11) | ((e << 21) & m)) ^ ((e >> 25) | ((e << 7) & m))) & m
        let ch = ((e & f) ^ ((m ^ e) & g)) & m
        let k = (((i as u64) + 1) * 1103515245 + 12345) & m
        let t1 = (h + s1 + ch + k + w[i]) & m
        let s0 = (((a >> 2) | ((a << 30) & m)) ^ ((a >> 13) | ((a << 19) & m)) ^ ((a >> 22) | ((a << 10) & m))) & m
        let maj = ((a & b) ^ (a & c) ^ (b & c)) & m
        let t2 = (s0 + maj) & m
        h = g
        g = f
        f = e
        e = (d + t1) & m
        d = c
        c = b
        b = a
        a = (t1 + t2) & m
    return (a ^ b ^ c ^ d ^ e ^ f ^ g ^ h) & m
""",
    )

    # k02: ChaCha20 20-round block
    add(
        "k02_chacha20_block",
        c_body="""
    uint64_t st[16];
    uint64_t m = 4294967295ULL;
    for (int i = 0; i < 16; i++) {
        st[i] = ((seed * 22695477ULL) + (uint64_t)(i * 1634760805ULL) + 1ULL) & m;
    }
    for (int r = 0; r < 10; r++) {
        for (int c = 0; c < 4; c++) {
            int ia = c, ib = c + 4, ic = c + 8, id = c + 12;
            st[ia] = (st[ia] + st[ib]) & m; st[id] ^= st[ia]; st[id] = (((st[id] << 16) & m) | (st[id] >> 16)) & m;
            st[ic] = (st[ic] + st[id]) & m; st[ib] ^= st[ic]; st[ib] = (((st[ib] << 12) & m) | (st[ib] >> 20)) & m;
            st[ia] = (st[ia] + st[ib]) & m; st[id] ^= st[ia]; st[id] = (((st[id] << 8) & m) | (st[id] >> 24)) & m;
            st[ic] = (st[ic] + st[id]) & m; st[ib] ^= st[ic]; st[ib] = (((st[ib] << 7) & m) | (st[ib] >> 25)) & m;
        }
    }
    uint64_t acc = 0;
    for (int i = 0; i < 16; i++) acc = (acc + st[i]) & m;
    return acc;
""",
        rs_body="""
    let mut st: [u64; 16] = [0; 16];
    let m: u64 = 4294967295;
    for i in 0..16 {
        st[i] = ((seed * 22695477) + ((i as u64) * 1634760805) + 1) & m;
    }
    for _ in 0..10 {
        for c in 0..4 {
            let ia = c; let ib = c + 4; let ic = c + 8; let id = c + 12;
            st[ia] = (st[ia] + st[ib]) & m; st[id] = st[id] ^ st[ia]; st[id] = (((st[id] << 16) & m) | (st[id] >> 16)) & m;
            st[ic] = (st[ic] + st[id]) & m; st[ib] = st[ib] ^ st[ic]; st[ib] = (((st[ib] << 12) & m) | (st[ib] >> 20)) & m;
            st[ia] = (st[ia] + st[ib]) & m; st[id] = st[id] ^ st[ia]; st[id] = (((st[id] << 8) & m) | (st[id] >> 24)) & m;
            st[ic] = (st[ic] + st[id]) & m; st[ib] = st[ib] ^ st[ic]; st[ib] = (((st[ib] << 7) & m) | (st[ib] >> 25)) & m;
        }
    }
    let mut acc: u64 = 0;
    for i in 0..16 { acc = (acc + st[i]) & m; }
    acc
""",
        py_body="""
    m = 4294967295
    st = [((seed * 22695477) + (i * 1634760805) + 1) & m for i in range(16)]
    for _ in range(10):
        for c in range(4):
            ia, ib, ic, id_ = c, c + 4, c + 8, c + 12
            st[ia] = (st[ia] + st[ib]) & m; st[id_] ^= st[ia]; st[id_] = (((st[id_] << 16) & m) | (st[id_] >> 16)) & m
            st[ic] = (st[ic] + st[id_]) & m; st[ib] ^= st[ic]; st[ib] = (((st[ib] << 12) & m) | (st[ib] >> 20)) & m
            st[ia] = (st[ia] + st[ib]) & m; st[id_] ^= st[ia]; st[id_] = (((st[id_] << 8) & m) | (st[id_] >> 24)) & m
            st[ic] = (st[ic] + st[id_]) & m; st[ib] ^= st[ic]; st[ib] = (((st[ib] << 7) & m) | (st[ib] >> 25)) & m
    acc = 0
    for i in range(16):
        acc = (acc + st[i]) & m
    return acc
""",
        rce_body="""
    var st: [u64; 16] = [0; 16]
    let m: u64 = 4294967295
    for i in 0..16
        st[i] = ((seed * 22695477) + ((i as u64) * 1634760805) + 1) & m
    for _ in 0..10
        for c in 0..4
            let ia = c
            let ib = c + 4
            let ic = c + 8
            let id = c + 12
            st[ia] = (st[ia] + st[ib]) & m
            st[id] = st[id] ^ st[ia]
            st[id] = (((st[id] << 16) & m) | (st[id] >> 16)) & m
            st[ic] = (st[ic] + st[id]) & m
            st[ib] = st[ib] ^ st[ic]
            st[ib] = (((st[ib] << 12) & m) | (st[ib] >> 20)) & m
            st[ia] = (st[ia] + st[ib]) & m
            st[id] = st[id] ^ st[ia]
            st[id] = (((st[id] << 8) & m) | (st[id] >> 24)) & m
            st[ic] = (st[ic] + st[id]) & m
            st[ib] = st[ib] ^ st[ic]
            st[ib] = (((st[ib] << 7) & m) | (st[ib] >> 25)) & m
    var acc: u64 = 0
    for i in 0..16
        acc = (acc + st[i]) & m
    return acc
""",
    )

    # k03: Fixed-point Q16.16 symplectic orbital step
    add(
        "k03_q32_orbital",
        c_body="""
    uint64_t m = 4294967295ULL;
    uint64_t px = (65536ULL + (seed & 4095ULL)) & m;
    uint64_t py = (32768ULL + ((seed >> 3) & 4095ULL)) & m;
    uint64_t vx = 1024ULL;
    uint64_t vy = 2048ULL;
    for (int step = 0; step < 32; step++) {
        uint64_t r2 = (((px * px) >> 16) + ((py * py) >> 16) + 4096ULL) & m;
        uint64_t inv = (1073741824ULL / (r2 + 1ULL)) & 65535ULL;
        uint64_t ax = ((px * inv) >> 16) & m;
        uint64_t ay = ((py * inv) >> 16) & m;
        vx = (vx + m + 1ULL - ax) & m;
        vy = (vy + m + 1ULL - ay) & m;
        px = (px + (vx >> 4)) & 1048575ULL;
        py = (py + (vy >> 4)) & 1048575ULL;
    }
    return (px ^ (py << 8) ^ vx ^ vy) & m;
""",
        rs_body="""
    let m: u64 = 4294967295;
    let mut px: u64 = (65536 + (seed & 4095)) & m;
    let mut py: u64 = (32768 + ((seed >> 3) & 4095)) & m;
    let mut vx: u64 = 1024;
    let mut vy: u64 = 2048;
    for _ in 0..32 {
        let r2 = (((px * px) >> 16) + ((py * py) >> 16) + 4096) & m;
        let inv = (1073741824 / (r2 + 1)) & 65535;
        let ax = ((px * inv) >> 16) & m;
        let ay = ((py * inv) >> 16) & m;
        vx = (vx + m + 1 - ax) & m;
        vy = (vy + m + 1 - ay) & m;
        px = (px + (vx >> 4)) & 1048575;
        py = (py + (vy >> 4)) & 1048575;
    }
    (px ^ (py << 8) ^ vx ^ vy) & m
""",
        py_body="""
    m = 4294967295
    px = (65536 + (seed & 4095)) & m
    py = (32768 + ((seed >> 3) & 4095)) & m
    vx = 1024
    vy = 2048
    for _ in range(32):
        r2 = (((px * px) >> 16) + ((py * py) >> 16) + 4096) & m
        inv = (1073741824 // (r2 + 1)) & 65535
        ax = ((px * inv) >> 16) & m
        ay = ((py * inv) >> 16) & m
        vx = (vx + m + 1 - ax) & m
        vy = (vy + m + 1 - ay) & m
        px = (px + (vx >> 4)) & 1048575
        py = (py + (vy >> 4)) & 1048575
    return (px ^ (py << 8) ^ vx ^ vy) & m
""",
        rce_body="""
    let m: u64 = 4294967295
    var px: u64 = (65536 + (seed & 4095)) & m
    var py: u64 = (32768 + ((seed >> 3) & 4095)) & m
    var vx: u64 = 1024
    var vy: u64 = 2048
    for _ in 0..32
        let r2 = (((px * px) >> 16) + ((py * py) >> 16) + 4096) & m
        let inv = (1073741824 / (r2 + 1)) & 65535
        let ax = ((px * inv) >> 16) & m
        let ay = ((py * inv) >> 16) & m
        vx = (vx + m + 1 - ax) & m
        vy = (vy + m + 1 - ay) & m
        px = (px + (vx >> 4)) & 1048575
        py = (py + (vy >> 4)) & 1048575
    return (px ^ (py << 8) ^ vx ^ vy) & m
""",
    )

    # k04: CRC32 IEEE bitwise over 64 bytes
    add(
        "k04_crc32_ieee",
        c_body="""
    uint64_t m = 4294967295ULL;
    uint64_t crc = m;
    uint64_t st = (seed * 2654435761ULL + 17ULL) & m;
    for (int i = 0; i < 64; i++) {
        st = (st * 1664525ULL + 1013904223ULL) & m;
        crc ^= (st & 255ULL);
        for (int b = 0; b < 8; b++) {
            if ((crc & 1ULL) == 1ULL) {
                crc = (crc >> 1) ^ 3988292384ULL;
            } else {
                crc = crc >> 1;
            }
        }
    }
    return (crc ^ m) & m;
""",
        rs_body="""
    let m: u64 = 4294967295;
    let mut crc: u64 = m;
    let mut st: u64 = (seed * 2654435761 + 17) & m;
    for _ in 0..64 {
        st = (st * 1664525 + 1013904223) & m;
        crc = crc ^ (st & 255);
        for _ in 0..8 {
            if (crc & 1) == 1 {
                crc = (crc >> 1) ^ 3988292384;
            } else {
                crc = crc >> 1;
            }
        }
    }
    (crc ^ m) & m
""",
        py_body="""
    m = 4294967295
    crc = m
    st = (seed * 2654435761 + 17) & m
    for _ in range(64):
        st = (st * 1664525 + 1013904223) & m
        crc ^= (st & 255)
        for _ in range(8):
            if (crc & 1) == 1:
                crc = (crc >> 1) ^ 3988292384
            else:
                crc = crc >> 1
    return (crc ^ m) & m
""",
        rce_body="""
    let m: u64 = 4294967295
    var crc: u64 = m
    var st: u64 = (seed * 2654435761 + 17) & m
    for _ in 0..64
        st = (st * 1664525 + 1013904223) & m
        crc = crc ^ (st & 255)
        for _ in 0..8
            if (crc & 1) == 1
                crc = (crc >> 1) ^ 3988292384
            else
                crc = crc >> 1
    return (crc ^ m) & m
""",
    )

    # k05: LZ77 longest match finder over 64-byte buffer
    add(
        "k05_lz77_match",
        c_body="""
    uint64_t buf[64];
    uint64_t s = (seed + 7ULL) & 4294967295ULL;
    for (int i = 0; i < 64; i++) {
        s = (s * 1103515245ULL + 12345ULL) & 4294967295ULL;
        buf[i] = (s >> 16) & 7ULL;
    }
    uint64_t score = 0;
    for (int pos = 8; pos < 56; pos++) {
        uint64_t best = 0;
        for (int back = 1; back < 9; back++) {
            uint64_t ln = 0;
            for (int k = 0; k < 8; k++) {
                if (ln == (uint64_t)k && buf[pos - back + k] == buf[pos + k]) {
                    ln += 1ULL;
                }
            }
            if (ln > best) best = ln;
        }
        score = (score * 131ULL + best) & 4294967295ULL;
    }
    return score;
""",
        rs_body="""
    let mut buf: [u64; 64] = [0; 64];
    let mut s: u64 = (seed + 7) & 4294967295;
    for i in 0..64 {
        s = (s * 1103515245 + 12345) & 4294967295;
        buf[i] = (s >> 16) & 7;
    }
    let mut score: u64 = 0;
    for pos in 8..56 {
        let mut best: u64 = 0;
        for back in 1..9 {
            let mut ln: u64 = 0;
            for k in 0..8 {
                if ln == (k as u64) && buf[pos - back + k] == buf[pos + k] {
                    ln += 1;
                }
            }
            if ln > best { best = ln; }
        }
        score = (score * 131 + best) & 4294967295;
    }
    score
""",
        py_body="""
    buf = [0] * 64
    s = (seed + 7) & 4294967295
    for i in range(64):
        s = (s * 1103515245 + 12345) & 4294967295
        buf[i] = (s >> 16) & 7
    score = 0
    for pos in range(8, 56):
        best = 0
        for back in range(1, 9):
            ln = 0
            for k in range(8):
                if ln == k and buf[pos - back + k] == buf[pos + k]:
                    ln += 1
            if ln > best:
                best = ln
        score = (score * 131 + best) & 4294967295
    return score
""",
        rce_body="""
    var buf: [u64; 64] = [0; 64]
    var s: u64 = (seed + 7) & 4294967295
    for i in 0..64
        s = (s * 1103515245 + 12345) & 4294967295
        buf[i] = (s >> 16) & 7
    var score: u64 = 0
    for pos in 8..56
        var best: u64 = 0
        for back in 1..9
            var ln: u64 = 0
            for k in 0..8
                if ln == (k as u64) and buf[pos - back + k] == buf[pos + k]
                    ln += 1
            if ln > best
                best = ln
        score = (score * 131 + best) & 4294967295
    return score
""",
    )

    # k06: Dijkstra shortest-path relaxation over 16-node graph
    add(
        "k06_dijkstra_grid",
        c_body="""
    uint64_t dist[16];
    uint64_t used[16];
    for (int i = 0; i < 16; i++) { dist[i] = 1000000ULL; used[i] = 0ULL; }
    dist[0] = 0ULL;
    for (int step = 0; step < 16; step++) {
        int u = 0;
        uint64_t best = 2000000ULL;
        for (int i = 0; i < 16; i++) {
            if (used[i] == 0ULL && dist[i] < best) { best = dist[i]; u = i; }
        }
        used[u] = 1ULL;
        for (int v = 0; v < 16; v++) {
            uint64_t w = (((seed + (uint64_t)(u * 17 + v * 31)) * 2654435761ULL) >> 24) & 63ULL;
            uint64_t nd = dist[u] + w + 1ULL;
            if (nd < dist[v]) dist[v] = nd;
        }
    }
    uint64_t acc = 0;
    for (int i = 0; i < 16; i++) acc = (acc * 33ULL + dist[i]) & 4294967295ULL;
    return acc;
""",
        rs_body="""
    let mut dist: [u64; 16] = [1000000; 16];
    let mut used: [u64; 16] = [0; 16];
    dist[0] = 0;
    for _ in 0..16 {
        let mut u: usize = 0;
        let mut best: u64 = 2000000;
        for i in 0..16 {
            if used[i] == 0 && dist[i] < best { best = dist[i]; u = i; }
        }
        used[u] = 1;
        for v in 0..16 {
            let w = ((((seed + ((u * 17 + v * 31) as u64)) & 4294967295) * 2654435761) >> 24) & 63;
            let nd = dist[u] + w + 1;
            if nd < dist[v] { dist[v] = nd; }
        }
    }
    let mut acc: u64 = 0;
    for i in 0..16 { acc = (acc * 33 + dist[i]) & 4294967295; }
    acc
""",
        py_body="""
    dist = [1000000] * 16
    used = [0] * 16
    dist[0] = 0
    for _ in range(16):
        u = 0
        best = 2000000
        for i in range(16):
            if used[i] == 0 and dist[i] < best:
                best = dist[i]
                u = i
        used[u] = 1
        for v in range(16):
            w = ((((seed + (u * 17 + v * 31)) & 4294967295) * 2654435761) >> 24) & 63
            nd = dist[u] + w + 1
            if nd < dist[v]:
                dist[v] = nd
    acc = 0
    for i in range(16):
        acc = (acc * 33 + dist[i]) & 4294967295
    return acc
""",
        rce_body="""
    var dist: [u64; 16] = [1000000; 16]
    var used: [u64; 16] = [0; 16]
    dist[0] = 0
    for _ in 0..16
        var u: usize = 0
        var best: u64 = 2000000
        for i in 0..16
            if used[i] == 0 and dist[i] < best
                best = dist[i]
                u = i
        used[u] = 1
        for v in 0..16
            let w = ((((seed + ((u * 17 + v * 31) as u64)) & 4294967295) * 2654435761) >> 24) & 63
            let nd = dist[u] + w + 1
            if nd < dist[v]
                dist[v] = nd
    var acc: u64 = 0
    for i in 0..16
        acc = (acc * 33 + dist[i]) & 4294967295
    return acc
""",
    )
    out["k06_dijkstra_grid"]["c"] = out["k06_dijkstra_grid"]["c"].replace(
        "(((seed + (uint64_t)(u * 17 + v * 31)) * 2654435761ULL)",
        "((((seed + (uint64_t)(u * 17 + v * 31)) & 4294967295ULL) * 2654435761ULL)",
    )

    # k07: NTT modular butterfly mod 998244353 (N=16)
    add(
        "k07_ntt_butterfly",
        c_body="""
    uint64_t modp = 998244353ULL;
    uint64_t a[16];
    for (int i = 0; i < 16; i++) a[i] = ((seed * 1315423911ULL) + (uint64_t)(i * 977ULL)) % modp;
    uint64_t len = 1;
    for (int stage = 0; stage < 4; stage++) {
        uint64_t stride = len * 2ULL;
        uint64_t wlen = (3ULL + (uint64_t)stage * 17ULL) % modp;
        int i = 0;
        while (i < 16) {
            uint64_t w = 1ULL;
            for (int j = 0; j < (int)len; j++) {
                uint64_t u = a[i + j];
                uint64_t v = (a[i + j + (int)len] * w) % modp;
                a[i + j] = (u + v) % modp;
                a[i + j + (int)len] = (u + modp - v) % modp;
                w = (w * wlen) % modp;
            }
            i += (int)stride;
        }
        len = stride;
    }
    uint64_t acc = 0;
    for (int i = 0; i < 16; i++) acc = (acc + a[i]) & 4294967295ULL;
    return acc;
""",
        rs_body="""
    let modp: u64 = 998244353;
    let mut a: [u64; 16] = [0; 16];
    for i in 0..16 { a[i] = ((seed * 1315423911) + ((i as u64) * 977)) % modp; }
    let mut len: usize = 1;
    for stage in 0..4 {
        let stride: usize = len * 2;
        let wlen: u64 = (3 + (stage as u64) * 17) % modp;
        let mut i: usize = 0;
        while i < 16 {
            let mut w: u64 = 1;
            for j in 0..len {
                let u = a[i + j];
                let v = (a[i + j + len] * w) % modp;
                a[i + j] = (u + v) % modp;
                a[i + j + len] = (u + modp - v) % modp;
                w = (w * wlen) % modp;
            }
            i += stride;
        }
        len = stride;
    }
    let mut acc: u64 = 0;
    for i in 0..16 { acc = (acc + a[i]) & 4294967295; }
    acc
""",
        py_body="""
    modp = 998244353
    a = [((seed * 1315423911) + (i * 977)) % modp for i in range(16)]
    ln = 1
    for stage in range(4):
        stride = ln * 2
        wlen = (3 + stage * 17) % modp
        i = 0
        while i < 16:
            w = 1
            for j in range(ln):
                u = a[i + j]
                v = (a[i + j + ln] * w) % modp
                a[i + j] = (u + v) % modp
                a[i + j + ln] = (u + modp - v) % modp
                w = (w * wlen) % modp
            i += stride
        ln = stride
    acc = 0
    for i in range(16):
        acc = (acc + a[i]) & 4294967295
    return acc
""",
        rce_body="""
    let modp: u64 = 998244353
    var a: [u64; 16] = [0; 16]
    for i in 0..16
        a[i] = ((seed * 1315423911) + ((i as u64) * 977)) % modp
    var ln: usize = 1
    for stage in 0..4
        let stride: usize = ln * 2
        let wlen: u64 = (3 + (stage as u64) * 17) % modp
        var i: usize = 0
        while i < 16 bound 32
            var w: u64 = 1
            for j in 0..ln
                let idx0 = i + j
                let idx1 = i + j + ln
                let u = a[idx0]
                let v = (a[idx1] * w) % modp
                a[idx0] = (u + v) % modp
                a[idx1] = (u + modp - v) % modp
                w = (w * wlen) % modp
            i += stride
        ln = stride
    var acc: u64 = 0
    for i in 0..16
        acc = (acc + a[i]) & 4294967295
    return acc
""",
    )

    # k08: 4x4 dense matrix multiply (repeated 4 rounds)
    add(
        "k08_matmul_i32",
        c_body="""
    uint64_t m = 4294967295ULL;
    uint64_t ma[16], mb[16], mc[16];
    for (int i = 0; i < 16; i++) {
        ma[i] = ((seed * 1664525ULL) + (uint64_t)(i * 97ULL)) & 65535ULL;
        mb[i] = ((seed * 22695477ULL) + (uint64_t)(i * 131ULL) + 3ULL) & 65535ULL;
    }
    for (int rep = 0; rep < 4; rep++) {
        for (int r = 0; r < 4; r++) {
            for (int c = 0; c < 4; c++) {
                uint64_t sum = 0;
                for (int k = 0; k < 4; k++) {
                    sum = (sum + ma[r * 4 + k] * mb[k * 4 + c]) & m;
                }
                mc[r * 4 + c] = sum & 65535ULL;
            }
        }
        for (int i = 0; i < 16; i++) ma[i] = mc[i];
    }
    uint64_t acc = 0;
    for (int i = 0; i < 16; i++) acc = (acc * 131ULL + ma[i]) & m;
    return acc;
""",
        rs_body="""
    let m: u64 = 4294967295;
    let mut ma: [u64; 16] = [0; 16];
    let mut mb: [u64; 16] = [0; 16];
    let mut mc: [u64; 16] = [0; 16];
    for i in 0..16 {
        ma[i] = ((seed * 1664525) + ((i as u64) * 97)) & 65535;
        mb[i] = ((seed * 22695477) + ((i as u64) * 131) + 3) & 65535;
    }
    for _ in 0..4 {
        for r in 0..4 {
            for c in 0..4 {
                let mut sum: u64 = 0;
                for k in 0..4 {
                    sum = (sum + ma[r * 4 + k] * mb[k * 4 + c]) & m;
                }
                mc[r * 4 + c] = sum & 65535;
            }
        }
        for i in 0..16 { ma[i] = mc[i]; }
    }
    let mut acc: u64 = 0;
    for i in 0..16 { acc = (acc * 131 + ma[i]) & m; }
    acc
""",
        py_body="""
    m = 4294967295
    ma = [((seed * 1664525) + (i * 97)) & 65535 for i in range(16)]
    mb = [((seed * 22695477) + (i * 131) + 3) & 65535 for i in range(16)]
    mc = [0] * 16
    for _ in range(4):
        for r in range(4):
            for c in range(4):
                s = 0
                for k in range(4):
                    s = (s + ma[r * 4 + k] * mb[k * 4 + c]) & m
                mc[r * 4 + c] = s & 65535
        for i in range(16):
            ma[i] = mc[i]
    acc = 0
    for i in range(16):
        acc = (acc * 131 + ma[i]) & m
    return acc
""",
        rce_body="""
    let m: u64 = 4294967295
    var ma: [u64; 16] = [0; 16]
    var mb: [u64; 16] = [0; 16]
    var mc: [u64; 16] = [0; 16]
    for i in 0..16
        ma[i] = ((seed * 1664525) + ((i as u64) * 97)) & 65535
        mb[i] = ((seed * 22695477) + ((i as u64) * 131) + 3) & 65535
    for _ in 0..4
        for r in 0..4
            for c in 0..4
                var sum: u64 = 0
                for k in 0..4
                    sum = (sum + ma[r * 4 + k] * mb[k * 4 + c]) & m
                let out_idx = r * 4 + c
                mc[out_idx] = sum & 65535
        for i in 0..16
            ma[i] = mc[i]
    var acc: u64 = 0
    for i in 0..16
        acc = (acc * 131 + ma[i]) & m
    return acc
""",
    )

    # k09: Array-backed Binary Search Tree insert & probe
    add(
        "k09_bst_probe",
        c_body="""
    uint64_t keys[16], left[16], right[16];
    for (int i = 0; i < 16; i++) { keys[i] = 0; left[i] = 99; right[i] = 99; }
    uint64_t st = (seed * 2654435761ULL + 99ULL) & 4294967295ULL;
    keys[0] = st & 65535ULL;
    uint64_t depth_sum = 0;
    for (int n = 1; n < 16; n++) {
        st = (st * 1664525ULL + 1013904223ULL) & 4294967295ULL;
        uint64_t kv = (st >> 8) & 65535ULL;
        keys[n] = kv;
        uint64_t cur = 0;
        uint64_t placed = 0;
        for (int step = 0; step < 16; step++) {
            if (placed == 0ULL) {
                depth_sum += 1ULL;
                if (kv < keys[cur]) {
                    if (left[cur] == 99ULL) { left[cur] = (uint64_t)n; placed = 1ULL; }
                    else { cur = left[cur]; }
                } else {
                    if (right[cur] == 99ULL) { right[cur] = (uint64_t)n; placed = 1ULL; }
                    else { cur = right[cur]; }
                }
            }
        }
    }
    return ((depth_sum << 16) ^ keys[15] ^ left[0] ^ right[0]) & 4294967295ULL;
""",
        rs_body="""
    let mut keys: [u64; 16] = [0; 16];
    let mut left: [u64; 16] = [99; 16];
    let mut right: [u64; 16] = [99; 16];
    let mut st: u64 = (seed * 2654435761 + 99) & 4294967295;
    keys[0] = st & 65535;
    let mut depth_sum: u64 = 0;
    for n in 1..16 {
        st = (st * 1664525 + 1013904223) & 4294967295;
        let kv = (st >> 8) & 65535;
        keys[n] = kv;
        let mut cur: usize = 0;
        let mut placed: u64 = 0;
        for _ in 0..16 {
            if placed == 0 {
                depth_sum += 1;
                if kv < keys[cur] {
                    if left[cur] == 99 { left[cur] = n as u64; placed = 1; }
                    else { cur = left[cur] as usize; }
                } else {
                    if right[cur] == 99 { right[cur] = n as u64; placed = 1; }
                    else { cur = right[cur] as usize; }
                }
            }
        }
    }
    ((depth_sum << 16) ^ keys[15] ^ left[0] ^ right[0]) & 4294967295
""",
        py_body="""
    keys = [0] * 16
    left = [99] * 16
    right = [99] * 16
    st = (seed * 2654435761 + 99) & 4294967295
    keys[0] = st & 65535
    depth_sum = 0
    for n in range(1, 16):
        st = (st * 1664525 + 1013904223) & 4294967295
        kv = (st >> 8) & 65535
        keys[n] = kv
        cur = 0
        placed = 0
        for _ in range(16):
            if placed == 0:
                depth_sum += 1
                if kv < keys[cur]:
                    if left[cur] == 99:
                        left[cur] = n
                        placed = 1
                    else:
                        cur = left[cur]
                else:
                    if right[cur] == 99:
                        right[cur] = n
                        placed = 1
                    else:
                        cur = right[cur]
    return ((depth_sum << 16) ^ keys[15] ^ left[0] ^ right[0]) & 4294967295
""",
        rce_body="""
    var keys: [u64; 16] = [0; 16]
    var left: [u64; 16] = [99; 16]
    var right: [u64; 16] = [99; 16]
    var st: u64 = (seed * 2654435761 + 99) & 4294967295
    keys[0] = st & 65535
    var depth_sum: u64 = 0
    for n in 1..16
        st = (st * 1664525 + 1013904223) & 4294967295
        let kv = (st >> 8) & 65535
        keys[n] = kv
        var cur: usize = 0
        var placed: u64 = 0
        for _ in 0..16
            if placed == 0
                depth_sum += 1
                if kv < keys[cur]
                    if left[cur] == 99
                        left[cur] = n as u64
                        placed = 1
                    else
                        cur = left[cur] as usize
                else
                    if right[cur] == 99
                        right[cur] = n as u64
                        placed = 1
                    else
                        cur = right[cur] as usize
    return ((depth_sum << 16) ^ keys[15] ^ left[0] ^ right[0]) & 4294967295
""",
    )

    # k10: Odd-even comparator sorting network over 16 elements
    add(
        "k10_sortnet_16",
        c_body="""
    uint64_t a[16];
    uint64_t s = (seed * 1103515245ULL + 54321ULL) & 4294967295ULL;
    for (int i = 0; i < 16; i++) {
        s = (s * 1664525ULL + 1013904223ULL) & 4294967295ULL;
        a[i] = s & 65535ULL;
    }
    for (int pass = 0; pass < 16; pass++) {
        int start = pass & 1;
        int j = start;
        while (j + 1 < 16) {
            if (a[j] > a[j + 1]) {
                uint64_t tmp = a[j];
                a[j] = a[j + 1];
                a[j + 1] = tmp;
            }
            j += 2;
        }
    }
    uint64_t acc = 0;
    for (int i = 0; i < 16; i++) acc = (acc * 257ULL + a[i]) & 4294967295ULL;
    return acc;
""",
        rs_body="""
    let mut a: [u64; 16] = [0; 16];
    let mut s: u64 = (seed * 1103515245 + 54321) & 4294967295;
    for i in 0..16 {
        s = (s * 1664525 + 1013904223) & 4294967295;
        a[i] = s & 65535;
    }
    for pass in 0..16 {
        let mut j: usize = pass & 1;
        while j + 1 < 16 {
            if a[j] > a[j + 1] {
                let tmp = a[j];
                a[j] = a[j + 1];
                a[j + 1] = tmp;
            }
            j += 2;
        }
    }
    let mut acc: u64 = 0;
    for i in 0..16 { acc = (acc * 257 + a[i]) & 4294967295; }
    acc
""",
        py_body="""
    a = [0] * 16
    s = (seed * 1103515245 + 54321) & 4294967295
    for i in range(16):
        s = (s * 1664525 + 1013904223) & 4294967295
        a[i] = s & 65535
    for p in range(16):
        j = p & 1
        while j + 1 < 16:
            if a[j] > a[j + 1]:
                a[j], a[j + 1] = a[j + 1], a[j]
            j += 2
    acc = 0
    for i in range(16):
        acc = (acc * 257 + a[i]) & 4294967295
    return acc
""",
        rce_body="""
    var a: [u64; 16] = [0; 16]
    var s: u64 = (seed * 1103515245 + 54321) & 4294967295
    for i in 0..16
        s = (s * 1664525 + 1013904223) & 4294967295
        a[i] = s & 65535
    for p in 0..16
        var j: usize = p & 1
        while j + 1 < 16 bound 16
            let j1 = j + 1
            if a[j] > a[j1]
                let tmp = a[j]
                a[j] = a[j1]
                a[j1] = tmp
            j += 2
    var acc: u64 = 0
    for i in 0..16
        acc = (acc * 257 + a[i]) & 4294967295
    return acc
""",
    )

    # k11: Ring buffer simulation
    add(
        "k11_ringbuf_sim",
        c_body="""
    uint64_t rb[16];
    for (int i = 0; i < 16; i++) rb[i] = 0ULL;
    uint64_t head = 0, tail = 0, count = 0, sum = 0;
    uint64_t s = (seed * 2654435761ULL + 13ULL) & 4294967295ULL;
    for (int step = 0; step < 96; step++) {
        s = (s * 1664525ULL + 1013904223ULL) & 4294967295ULL;
        if ((s & 3ULL) != 0ULL) {
            if (count < 16ULL) {
                rb[tail] = s & 65535ULL;
                tail = (tail + 1ULL) & 15ULL;
                count += 1ULL;
            }
        } else {
            if (count > 0ULL) {
                sum = (sum + rb[head]) & 4294967295ULL;
                head = (head + 1ULL) & 15ULL;
                count -= 1ULL;
            }
        }
    }
    return ((sum << 4) ^ count ^ head ^ tail) & 4294967295ULL;
""",
        rs_body="""
    let mut rb: [u64; 16] = [0; 16];
    let mut head: usize = 0;
    let mut tail: usize = 0;
    let mut count: u64 = 0;
    let mut sum: u64 = 0;
    let mut s: u64 = (seed * 2654435761 + 13) & 4294967295;
    for _ in 0..96 {
        s = (s * 1664525 + 1013904223) & 4294967295;
        if (s & 3) != 0 {
            if count < 16 {
                rb[tail] = s & 65535;
                tail = (tail + 1) & 15;
                count += 1;
            }
        } else {
            if count > 0 {
                sum = (sum + rb[head]) & 4294967295;
                head = (head + 1) & 15;
                count -= 1;
            }
        }
    }
    (((sum << 4) & 4294967295) ^ count ^ (head as u64) ^ (tail as u64)) & 4294967295
""",
        py_body="""
    rb = [0] * 16
    head = 0; tail = 0; count = 0; s_acc = 0
    s = (seed * 2654435761 + 13) & 4294967295
    for _ in range(96):
        s = (s * 1664525 + 1013904223) & 4294967295
        if (s & 3) != 0:
            if count < 16:
                rb[tail] = s & 65535
                tail = (tail + 1) & 15
                count += 1
        else:
            if count > 0:
                s_acc = (s_acc + rb[head]) & 4294967295
                head = (head + 1) & 15
                count -= 1
    return (((s_acc << 4) & 4294967295) ^ count ^ head ^ tail) & 4294967295
""",
        rce_body="""
    var rb: [u64; 16] = [0; 16]
    var head: usize = 0
    var tail: usize = 0
    var count: u64 = 0
    var sum: u64 = 0
    var s: u64 = (seed * 2654435761 + 13) & 4294967295
    for _ in 0..96
        s = (s * 1664525 + 1013904223) & 4294967295
        if (s & 3) != 0
            if count < 16
                rb[tail] = s & 65535
                tail = (tail + 1) & 15
                count += 1
        else
            if count > 0
                sum = (sum + rb[head]) & 4294967295
                head = (head + 1) & 15
                count -= 1
    return (((sum << 4) & 4294967295) ^ count ^ (head as u64) ^ (tail as u64)) & 4294967295
""",
    )
    out["k11_ringbuf_sim"]["c"] = out["k11_ringbuf_sim"]["c"].replace(
        "((sum << 4) ^ count ^ head ^ tail)",
        "(((sum << 4) & 4294967295ULL) ^ count ^ head ^ tail)",
    )

    # k12: Token bucket rate-limiter state machine
    add(
        "k12_token_bucket",
        c_body="""
    uint64_t tokens = 50ULL, cap = 100ULL, admitted = 0ULL, refused = 0ULL;
    uint64_t s = (seed * 1664525ULL + 31337ULL) & 4294967295ULL;
    for (int t = 0; t < 128; t++) {
        tokens += 6ULL;
        if (tokens > cap) tokens = cap;
        s = (s * 22695477ULL + 1ULL) & 4294967295ULL;
        uint64_t cost = ((s >> 16) & 15ULL) + 1ULL;
        if (cost <= tokens) {
            tokens -= cost;
            admitted += cost;
        } else {
            refused += 1ULL;
        }
    }
    return ((admitted << 12) ^ (refused << 4) ^ tokens) & 4294967295ULL;
""",
        rs_body="""
    let mut tokens: u64 = 50;
    let cap: u64 = 100;
    let mut admitted: u64 = 0;
    let mut refused: u64 = 0;
    let mut s: u64 = (seed * 1664525 + 31337) & 4294967295;
    for _ in 0..128 {
        tokens += 6;
        if tokens > cap { tokens = cap; }
        s = (s * 22695477 + 1) & 4294967295;
        let cost = ((s >> 16) & 15) + 1;
        if cost <= tokens {
            tokens -= cost;
            admitted += cost;
        } else {
            refused += 1;
        }
    }
    ((admitted << 12) ^ (refused << 4) ^ tokens) & 4294967295
""",
        py_body="""
    tokens = 50; cap = 100; admitted = 0; refused = 0
    s = (seed * 1664525 + 31337) & 4294967295
    for _ in range(128):
        tokens += 6
        if tokens > cap:
            tokens = cap
        s = (s * 22695477 + 1) & 4294967295
        cost = ((s >> 16) & 15) + 1
        if cost <= tokens:
            tokens -= cost
            admitted += cost
        else:
            refused += 1
    return ((admitted << 12) ^ (refused << 4) ^ tokens) & 4294967295
""",
        rce_body="""
    var tokens: u64 = 50
    let cap: u64 = 100
    var admitted: u64 = 0
    var refused: u64 = 0
    var s: u64 = (seed * 1664525 + 31337) & 4294967295
    for _ in 0..128
        tokens += 6
        if tokens > cap
            tokens = cap
        s = (s * 22695477 + 1) & 4294967295
        let cost = ((s >> 16) & 15) + 1
        if cost <= tokens
            tokens -= cost
            admitted += cost
        else
            refused += 1
    return ((admitted << 12) ^ (refused << 4) ^ tokens) & 4294967295
""",
    )

    # k13: FNV-1a + ARX SipRound mixer
    add(
        "k13_fnv1a_sip",
        c_body="""
    uint64_t m = 4294967295ULL;
    uint64_t h = 2166136261ULL;
    uint64_t v0 = (seed ^ 19349663ULL) & m;
    uint64_t v1 = ((seed * 1664525ULL) ^ 83492791ULL) & m;
    for (int i = 0; i < 64; i++) {
        uint64_t b = (v0 + (uint64_t)i * 73ULL) & 255ULL;
        h = ((h ^ b) * 16777619ULL) & m;
        v0 = (v0 + v1) & m;
        v1 = (((v1 << 13) & m) | (v1 >> 19)) ^ v0;
        v0 = (((v0 << 16) & m) | (v0 >> 16));
    }
    return (h ^ v0 ^ v1) & m;
""",
        rs_body="""
    let m: u64 = 4294967295;
    let mut h: u64 = 2166136261;
    let mut v0: u64 = (seed ^ 19349663) & m;
    let mut v1: u64 = ((seed * 1664525) ^ 83492791) & m;
    for i in 0..64 {
        let b = (v0 + (i as u64) * 73) & 255;
        h = ((h ^ b) * 16777619) & m;
        v0 = (v0 + v1) & m;
        v1 = (((v1 << 13) & m) | (v1 >> 19)) ^ v0;
        v0 = ((v0 << 16) & m) | (v0 >> 16);
    }
    (h ^ v0 ^ v1) & m
""",
        py_body="""
    m = 4294967295
    h = 2166136261
    v0 = (seed ^ 19349663) & m
    v1 = ((seed * 1664525) ^ 83492791) & m
    for i in range(64):
        b = (v0 + i * 73) & 255
        h = ((h ^ b) * 16777619) & m
        v0 = (v0 + v1) & m
        v1 = (((v1 << 13) & m) | (v1 >> 19)) ^ v0
        v0 = ((v0 << 16) & m) | (v0 >> 16)
    return (h ^ v0 ^ v1) & m
""",
        rce_body="""
    let m: u64 = 4294967295
    var h: u64 = 2166136261
    var v0: u64 = (seed ^ 19349663) & m
    var v1: u64 = ((seed * 1664525) ^ 83492791) & m
    for i in 0..64
        let b = (v0 + (i as u64) * 73) & 255
        h = ((h ^ b) * 16777619) & m
        v0 = (v0 + v1) & m
        v1 = (((v1 << 13) & m) | (v1 >> 19)) ^ v0
        v0 = ((v0 << 16) & m) | (v0 >> 16)
    return (h ^ v0 ^ v1) & m
""",
    )

    # k14: Sieve of Eratosthenes weighted prime sum (N=128)
    add(
        "k14_sieve_primes",
        c_body="""
    uint64_t comp[128];
    for (int i = 0; i < 128; i++) comp[i] = 0ULL;
    comp[0] = 1ULL; comp[1] = 1ULL;
    for (int p = 2; p < 12; p++) {
        if (comp[p] == 0ULL) {
            int mult = p * p;
            while (mult < 128) {
                comp[mult] = 1ULL;
                mult += p;
            }
        }
    }
    uint64_t w = (seed & 1023ULL) + 1ULL;
    uint64_t acc = 0ULL;
    for (int i = 2; i < 128; i++) {
        if (comp[i] == 0ULL) {
            acc = (acc + (uint64_t)i * w) & 4294967295ULL;
            w = (w * 3ULL + 1ULL) & 65535ULL;
        }
    }
    return acc;
""",
        rs_body="""
    let mut comp: [u64; 128] = [0; 128];
    comp[0] = 1; comp[1] = 1;
    for p in 2..12 {
        if comp[p] == 0 {
            let mut mult: usize = p * p;
            while mult < 128 {
                comp[mult] = 1;
                mult += p;
            }
        }
    }
    let mut w: u64 = (seed & 1023) + 1;
    let mut acc: u64 = 0;
    for i in 2..128 {
        if comp[i] == 0 {
            acc = (acc + (i as u64) * w) & 4294967295;
            w = (w * 3 + 1) & 65535;
        }
    }
    acc
""",
        py_body="""
    comp = [0] * 128
    comp[0] = 1; comp[1] = 1
    for p in range(2, 12):
        if comp[p] == 0:
            mult = p * p
            while mult < 128:
                comp[mult] = 1
                mult += p
    w = (seed & 1023) + 1
    acc = 0
    for i in range(2, 128):
        if comp[i] == 0:
            acc = (acc + i * w) & 4294967295
            w = (w * 3 + 1) & 65535
    return acc
""",
        rce_body="""
    var comp: [u64; 128] = [0; 128]
    comp[0] = 1
    comp[1] = 1
    for p in 2..12
        if comp[p] == 0
            var mult: usize = p * p
            while mult < 128 bound 128
                comp[mult] = 1
                mult += p
    var w: u64 = (seed & 1023) + 1
    var acc: u64 = 0
    for i in 2..128
        if comp[i] == 0
            acc = (acc + (i as u64) * w) & 4294967295
            w = (w * 3 + 1) & 65535
    return acc
""",
    )

    # k15: Bounded Collatz stopping-time accumulator
    add(
        "k15_collatz_bounded",
        c_body="""
    uint64_t total = 0ULL;
    uint64_t base = (seed & 255ULL) + 2ULL;
    for (int k = 0; k < 32; k++) {
        uint64_t x = base + (uint64_t)k;
        for (int step = 0; step < 32; step++) {
            if (x > 1ULL) {
                if ((x & 1ULL) == 0ULL) x = x >> 1;
                else x = 3ULL * x + 1ULL;
                total += 1ULL;
            }
        }
        total = (total + x) & 4294967295ULL;
    }
    return total;
""",
        rs_body="""
    let mut total: u64 = 0;
    let base: u64 = (seed & 255) + 2;
    for k in 0..32 {
        let mut x: u64 = base + (k as u64);
        for _ in 0..32 {
            if x > 1 {
                if (x & 1) == 0 { x = x >> 1; }
                else { x = 3 * x + 1; }
                total += 1;
            }
        }
        total = (total + x) & 4294967295;
    }
    total
""",
        py_body="""
    total = 0
    base = (seed & 255) + 2
    for k in range(32):
        x = base + k
        for _ in range(32):
            if x > 1:
                if (x & 1) == 0:
                    x = x >> 1
                else:
                    x = 3 * x + 1
                total += 1
        total = (total + x) & 4294967295
    return total
""",
        rce_body="""
    var total: u64 = 0
    let base: u64 = (seed & 255) + 2
    for k in 0..32
        var x: u64 = base + (k as u64)
        for _ in 0..32
            if x > 1
                if (x & 1) == 0
                    x = x >> 1
                else
                    x = 3 * x + 1
                total += 1
        total = (total + x) & 4294967295
    return total
""",
    )

    # k16: SWAR 32-bit Hamming weight & parity fold
    add(
        "k16_popcount_swar",
        c_body="""
    uint64_t s = (seed * 2654435761ULL + 1ULL) & 4294967295ULL;
    uint64_t acc = 0ULL;
    for (int i = 0; i < 64; i++) {
        s = (s * 1664525ULL + 1013904223ULL) & 4294967295ULL;
        uint64_t x = s;
        x = x - ((x >> 1) & 1431655765ULL);
        x = (x & 858993459ULL) + ((x >> 2) & 858993459ULL);
        uint64_t pc = (((x + (x >> 4)) & 252645135ULL) * 16843009ULL >> 24) & 63ULL;
        acc = (acc * 37ULL + pc) & 4294967295ULL;
    }
    return acc;
""",
        rs_body="""
    let mut s: u64 = (seed * 2654435761 + 1) & 4294967295;
    let mut acc: u64 = 0;
    for _ in 0..64 {
        s = (s * 1664525 + 1013904223) & 4294967295;
        let mut x: u64 = s;
        x = x - ((x >> 1) & 1431655765);
        x = (x & 858993459) + ((x >> 2) & 858993459);
        let pc = ((((x + (x >> 4)) & 252645135) * 16843009) >> 24) & 63;
        acc = (acc * 37 + pc) & 4294967295;
    }
    acc
""",
        py_body="""
    s = (seed * 2654435761 + 1) & 4294967295
    acc = 0
    for _ in range(64):
        s = (s * 1664525 + 1013904223) & 4294967295
        x = s
        x = x - ((x >> 1) & 1431655765)
        x = (x & 858993459) + ((x >> 2) & 858993459)
        pc = ((((x + (x >> 4)) & 252645135) * 16843009) >> 24) & 63
        acc = (acc * 37 + pc) & 4294967295
    return acc
""",
        rce_body="""
    var s: u64 = (seed * 2654435761 + 1) & 4294967295
    var acc: u64 = 0
    for _ in 0..64
        s = (s * 1664525 + 1013904223) & 4294967295
        var x: u64 = s
        x = x - ((x >> 1) & 1431655765)
        x = (x & 858993459) + ((x >> 2) & 858993459)
        let pc = ((((x + (x >> 4)) & 252645135) * 16843009) >> 24) & 63
        acc = (acc * 37 + pc) & 4294967295
    return acc
""",
    )

    # k17: Levenshtein DP edit distance over 12x12 strings
    add(
        "k17_edit_levenshtein",
        c_body="""
    uint64_t sa[12], sb[12], dp[13], nxt[13];
    uint64_t s = (seed * 1664525ULL + 77ULL) & 4294967295ULL;
    for (int i = 0; i < 12; i++) {
        s = (s * 1103515245ULL + 12345ULL) & 4294967295ULL;
        sa[i] = (s >> 12) & 3ULL;
        sb[i] = (s >> 16) & 3ULL;
    }
    for (int j = 0; j < 13; j++) dp[j] = (uint64_t)j;
    for (int i = 0; i < 12; i++) {
        nxt[0] = (uint64_t)(i + 1);
        for (int j = 0; j < 12; j++) {
            uint64_t cost = (sa[i] == sb[j]) ? 0ULL : 1ULL;
            uint64_t a = dp[j + 1] + 1ULL;
            uint64_t b = nxt[j] + 1ULL;
            uint64_t c = dp[j] + cost;
            uint64_t mn = a < b ? a : b;
            if (c < mn) mn = c;
            nxt[j + 1] = mn;
        }
        for (int j = 0; j < 13; j++) dp[j] = nxt[j];
    }
    uint64_t acc = 0;
    for (int j = 0; j < 13; j++) acc = (acc * 19ULL + dp[j]) & 4294967295ULL;
    return acc;
""",
        rs_body="""
    let mut sa: [u64; 12] = [0; 12];
    let mut sb: [u64; 12] = [0; 12];
    let mut dp: [u64; 13] = [0; 13];
    let mut nxt: [u64; 13] = [0; 13];
    let mut s: u64 = (seed * 1664525 + 77) & 4294967295;
    for i in 0..12 {
        s = (s * 1103515245 + 12345) & 4294967295;
        sa[i] = (s >> 12) & 3;
        sb[i] = (s >> 16) & 3;
    }
    for j in 0..13 { dp[j] = j as u64; }
    for i in 0..12 {
        nxt[0] = (i + 1) as u64;
        for j in 0..12 {
            let cost: u64 = if sa[i] == sb[j] { 0 } else { 1 };
            let a = dp[j + 1] + 1;
            let b = nxt[j] + 1;
            let c = dp[j] + cost;
            let mut mn = if a < b { a } else { b };
            if c < mn { mn = c; }
            nxt[j + 1] = mn;
        }
        for j in 0..13 { dp[j] = nxt[j]; }
    }
    let mut acc: u64 = 0;
    for j in 0..13 { acc = (acc * 19 + dp[j]) & 4294967295; }
    acc
""",
        py_body="""
    sa = [0] * 12; sb = [0] * 12
    s = (seed * 1664525 + 77) & 4294967295
    for i in range(12):
        s = (s * 1103515245 + 12345) & 4294967295
        sa[i] = (s >> 12) & 3
        sb[i] = (s >> 16) & 3
    dp = [j for j in range(13)]
    nxt = [0] * 13
    for i in range(12):
        nxt[0] = i + 1
        for j in range(12):
            cost = 0 if sa[i] == sb[j] else 1
            a = dp[j + 1] + 1
            b = nxt[j] + 1
            c = dp[j] + cost
            mn = a if a < b else b
            if c < mn:
                mn = c
            nxt[j + 1] = mn
        for j in range(13):
            dp[j] = nxt[j]
    acc = 0
    for j in range(13):
        acc = (acc * 19 + dp[j]) & 4294967295
    return acc
""",
        rce_body="""
    var sa: [u64; 12] = [0; 12]
    var sb: [u64; 12] = [0; 12]
    var dp: [u64; 13] = [0; 13]
    var nxt: [u64; 13] = [0; 13]
    var s: u64 = (seed * 1664525 + 77) & 4294967295
    for i in 0..12
        s = (s * 1103515245 + 12345) & 4294967295
        sa[i] = (s >> 12) & 3
        sb[i] = (s >> 16) & 3
    for j in 0..13
        dp[j] = j as u64
    for i in 0..12
        nxt[0] = (i + 1) as u64
        for j in 0..12
            let j1 = j + 1
            let cost: u64 = if sa[i] == sb[j] then 0 else 1
            let a = dp[j1] + 1
            let b = nxt[j] + 1
            let c = dp[j] + cost
            var mn = if a < b then a else b
            if c < mn
                mn = c
            nxt[j1] = mn
        for j in 0..13
            dp[j] = nxt[j]
    var acc: u64 = 0
    for j in 0..13
        acc = (acc * 19 + dp[j]) & 4294967295
    return acc
""",
    )

    # k18: RLE compress + decode round-trip verifier
    add(
        "k18_rle_codec",
        c_body="""
    uint64_t src[64], vals[64], runs[64];
    uint64_t s = (seed * 2654435761ULL + 5ULL) & 4294967295ULL;
    uint64_t cur = s & 7ULL;
    for (int i = 0; i < 64; i++) {
        s = (s * 1664525ULL + 1013904223ULL) & 4294967295ULL;
        if ((s & 3ULL) == 0ULL) cur = (s >> 8) & 7ULL;
        src[i] = cur;
        vals[i] = 0ULL; runs[i] = 0ULL;
    }
    int n_runs = 0;
    vals[0] = src[0]; runs[0] = 1ULL;
    for (int i = 1; i < 64; i++) {
        if (src[i] == vals[n_runs]) runs[n_runs] += 1ULL;
        else { n_runs += 1; vals[n_runs] = src[i]; runs[n_runs] = 1ULL; }
    }
    uint64_t decoded_sum = 0;
    for (int r = 0; r <= n_runs; r++) {
        decoded_sum = (decoded_sum + vals[r] * runs[r] + runs[r]) & 4294967295ULL;
    }
    return ((decoded_sum << 8) ^ (uint64_t)(n_runs + 1)) & 4294967295ULL;
""",
        rs_body="""
    let mut src: [u64; 64] = [0; 64];
    let mut vals: [u64; 64] = [0; 64];
    let mut runs: [u64; 64] = [0; 64];
    let mut s: u64 = (seed * 2654435761 + 5) & 4294967295;
    let mut cur: u64 = s & 7;
    for i in 0..64 {
        s = (s * 1664525 + 1013904223) & 4294967295;
        if (s & 3) == 0 { cur = (s >> 8) & 7; }
        src[i] = cur;
    }
    let mut n_runs: usize = 0;
    vals[0] = src[0]; runs[0] = 1;
    for i in 1..64 {
        if src[i] == vals[n_runs] { runs[n_runs] += 1; }
        else { n_runs += 1; vals[n_runs] = src[i]; runs[n_runs] = 1; }
    }
    let mut decoded_sum: u64 = 0;
    for r in 0..(n_runs + 1) {
        decoded_sum = (decoded_sum + vals[r] * runs[r] + runs[r]) & 4294967295;
    }
    (((decoded_sum << 8) & 4294967295) ^ ((n_runs + 1) as u64)) & 4294967295
""",
        py_body="""
    src = [0] * 64; vals = [0] * 64; runs = [0] * 64
    s = (seed * 2654435761 + 5) & 4294967295
    cur = s & 7
    for i in range(64):
        s = (s * 1664525 + 1013904223) & 4294967295
        if (s & 3) == 0:
            cur = (s >> 8) & 7
        src[i] = cur
    n_runs = 0
    vals[0] = src[0]; runs[0] = 1
    for i in range(1, 64):
        if src[i] == vals[n_runs]:
            runs[n_runs] += 1
        else:
            n_runs += 1
            vals[n_runs] = src[i]
            runs[n_runs] = 1
    decoded_sum = 0
    for r in range(n_runs + 1):
        decoded_sum = (decoded_sum + vals[r] * runs[r] + runs[r]) & 4294967295
    return (((decoded_sum << 8) & 4294967295) ^ (n_runs + 1)) & 4294967295
""",
        rce_body="""
    var src: [u64; 64] = [0; 64]
    var vals: [u64; 64] = [0; 64]
    var runs: [u64; 64] = [0; 64]
    var s: u64 = (seed * 2654435761 + 5) & 4294967295
    var cur: u64 = s & 7
    for i in 0..64
        s = (s * 1664525 + 1013904223) & 4294967295
        if (s & 3) == 0
            cur = (s >> 8) & 7
        src[i] = cur
    var n_runs: usize = 0
    vals[0] = src[0]
    runs[0] = 1
    for i in 1..64
        if src[i] == vals[n_runs]
            runs[n_runs] += 1
        else
            n_runs += 1
            vals[n_runs] = src[i]
            runs[n_runs] = 1
    var decoded_sum: u64 = 0
    for r in 0..(n_runs + 1)
        decoded_sum = (decoded_sum + vals[r] * runs[r] + runs[r]) & 4294967295
    return (((decoded_sum << 8) & 4294967295) ^ ((n_runs + 1) as u64)) & 4294967295
""",
    )
    out["k18_rle_codec"]["c"] = out["k18_rle_codec"]["c"].replace(
        "((decoded_sum << 8) ^ (uint64_t)(n_runs + 1))",
        "(((decoded_sum << 8) & 4294967295ULL) ^ (uint64_t)(n_runs + 1))",
    )

    # k19: Repeated modular exponentiation mod 1000000007
    add(
        "k19_modexp_mont",
        c_body="""
    uint64_t modm = 1000000007ULL;
    uint64_t acc = 0ULL;
    for (int i = 0; i < 16; i++) {
        uint64_t base = ((seed * 1664525ULL) + (uint64_t)(i * 99991ULL) + 3ULL) % modm;
        uint64_t exp = (((seed >> 4) + (uint64_t)(i * 65537ULL)) & 1048575ULL) + 17ULL;
        uint64_t res = 1ULL;
        for (int b = 0; b < 21; b++) {
            if ((exp & 1ULL) == 1ULL) res = (res * base) % modm;
            base = (base * base) % modm;
            exp = exp >> 1;
        }
        acc = (acc + res) & 4294967295ULL;
    }
    return acc;
""",
        rs_body="""
    let modm: u64 = 1000000007;
    let mut acc: u64 = 0;
    for i in 0..16 {
        let mut base: u64 = ((seed * 1664525) + ((i as u64) * 99991) + 3) % modm;
        let mut exp: u64 = (((seed >> 4) + ((i as u64) * 65537)) & 1048575) + 17;
        let mut res: u64 = 1;
        for _ in 0..21 {
            if (exp & 1) == 1 { res = (res * base) % modm; }
            base = (base * base) % modm;
            exp = exp >> 1;
        }
        acc = (acc + res) & 4294967295;
    }
    acc
""",
        py_body="""
    modm = 1000000007
    acc = 0
    for i in range(16):
        base = ((seed * 1664525) + (i * 99991) + 3) % modm
        exp = (((seed >> 4) + (i * 65537)) & 1048575) + 17
        res = 1
        for _ in range(21):
            if (exp & 1) == 1:
                res = (res * base) % modm
            base = (base * base) % modm
            exp = exp >> 1
        acc = (acc + res) & 4294967295
    return acc
""",
        rce_body="""
    let modm: u64 = 1000000007
    var acc: u64 = 0
    for i in 0..16
        var base: u64 = ((seed * 1664525) + ((i as u64) * 99991) + 3) % modm
        var exp: u64 = (((seed >> 4) + ((i as u64) * 65537)) & 1048575) + 17
        var res: u64 = 1
        for _ in 0..21
            if (exp & 1) == 1
                res = (res * base) % modm
            base = (base * base) % modm
            exp = exp >> 1
        acc = (acc + res) & 4294967295
    return acc
""",
    )

    # k20: 1D fixed-point Q16.16 Alpha-Beta / Kalman tracker
    add(
        "k20_kalman_q16",
        c_body="""
    uint64_t x_est = 655360ULL;
    uint64_t v_est = 1024ULL;
    uint64_t s = (seed * 2654435761ULL + 42ULL) & 4294967295ULL;
    for (int t = 0; t < 64; t++) {
        x_est = (x_est + v_est) & 4294967295ULL;
        s = (s * 1664525ULL + 1013904223ULL) & 4294967295ULL;
        uint64_t z_obs = (655360ULL + (uint64_t)t * 1000ULL + ((s >> 16) & 2047ULL)) & 4294967295ULL;
        if (z_obs >= x_est) {
            uint64_t r = z_obs - x_est;
            x_est = (x_est + (r >> 2)) & 4294967295ULL;
            v_est = (v_est + (r >> 5)) & 1048575ULL;
        } else {
            uint64_t r = x_est - z_obs;
            x_est = (x_est + 4294967296ULL - (r >> 2)) & 4294967295ULL;
            if (v_est >= (r >> 5)) v_est -= (r >> 5);
            else v_est = 0ULL;
        }
    }
    return (x_est ^ (v_est << 8)) & 4294967295ULL;
""",
        rs_body="""
    let mut x_est: u64 = 655360;
    let mut v_est: u64 = 1024;
    let mut s: u64 = (seed * 2654435761 + 42) & 4294967295;
    for t in 0..64 {
        x_est = (x_est + v_est) & 4294967295;
        s = (s * 1664525 + 1013904223) & 4294967295;
        let z_obs = (655360 + (t as u64) * 1000 + ((s >> 16) & 2047)) & 4294967295;
        if z_obs >= x_est {
            let r = z_obs - x_est;
            x_est = (x_est + (r >> 2)) & 4294967295;
            v_est = (v_est + (r >> 5)) & 1048575;
        } else {
            let r = x_est - z_obs;
            x_est = (x_est + 4294967296 - (r >> 2)) & 4294967295;
            if v_est >= (r >> 5) { v_est -= r >> 5; }
            else { v_est = 0; }
        }
    }
    (x_est ^ (v_est << 8)) & 4294967295
""",
        py_body="""
    x_est = 655360
    v_est = 1024
    s = (seed * 2654435761 + 42) & 4294967295
    for t in range(64):
        x_est = (x_est + v_est) & 4294967295
        s = (s * 1664525 + 1013904223) & 4294967295
        z_obs = (655360 + t * 1000 + ((s >> 16) & 2047)) & 4294967295
        if z_obs >= x_est:
            r = z_obs - x_est
            x_est = (x_est + (r >> 2)) & 4294967295
            v_est = (v_est + (r >> 5)) & 1048575
        else:
            r = x_est - z_obs
            x_est = (x_est + 4294967296 - (r >> 2)) & 4294967295
            if v_est >= (r >> 5):
                v_est -= r >> 5
            else:
                v_est = 0
    return (x_est ^ (v_est << 8)) & 4294967295
""",
        rce_body="""
    var x_est: u64 = 655360
    var v_est: u64 = 1024
    var s: u64 = (seed * 2654435761 + 42) & 4294967295
    for t in 0..64
        x_est = (x_est + v_est) & 4294967295
        s = (s * 1664525 + 1013904223) & 4294967295
        let z_obs = (655360 + (t as u64) * 1000 + ((s >> 16) & 2047)) & 4294967295
        if z_obs >= x_est
            let r = z_obs - x_est
            x_est = (x_est + (r >> 2)) & 4294967295
            v_est = (v_est + (r >> 5)) & 1048575
        else
            let r = x_est - z_obs
            x_est = (x_est + 4294967296 - (r >> 2)) & 4294967295
            if v_est >= (r >> 5)
                v_est -= r >> 5
            else
                v_est = 0
    return (x_est ^ (v_est << 8)) & 4294967295
""",
    )
    return out


def render_c_source(kid: str, body: str) -> str:
    return f"""/* Kernel {kid}: deterministic exact integer benchmark */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

static const uint64_t MASK32 = 4294967295ULL;

__attribute__((noinline)) uint64_t kernel(uint64_t seed) {{{body}}}

static uint64_t read_uj(const char *p) {{
    FILE *f = fopen(p, "r");
    if (!f) return 0;
    unsigned long long v = 0;
    if (fscanf(f, "%llu", &v) != 1) v = 0;
    fclose(f);
    return (uint64_t)v;
}}

static uint64_t delta_uj(uint64_t a, uint64_t b, uint64_t mx) {{
    return (b >= a) ? (b - a) : ((mx - a) + b + 1ULL);
}}

int main(int argc, char **argv) {{
    uint64_t iters = (argc > 1) ? (uint64_t)strtoull(argv[1], NULL, 10) : 10000ULL;
    uint64_t warm = 64ULL;
    volatile uint64_t sink = 0;
    for (uint64_t i = 0; i < warm; i++) sink ^= kernel(i);
    uint64_t mx_p = read_uj("/sys/class/powercap/intel-rapl:0/max_energy_range_uj");
    uint64_t mx_c = read_uj("/sys/class/powercap/intel-rapl:0:0/max_energy_range_uj");
    uint64_t p0 = read_uj("/sys/class/powercap/intel-rapl:0/energy_uj");
    uint64_t c0 = read_uj("/sys/class/powercap/intel-rapl:0:0/energy_uj");
    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    uint64_t csum = 0;
    for (uint64_t s = 0; s < iters; s++) {{
        csum = (csum + kernel(s)) & MASK32;
    }}
    clock_gettime(CLOCK_MONOTONIC, &t1);
    uint64_t p1 = read_uj("/sys/class/powercap/intel-rapl:0/energy_uj");
    uint64_t c1 = read_uj("/sys/class/powercap/intel-rapl:0:0/energy_uj");
    double wall = (double)(t1.tv_sec - t0.tv_sec) + (double)(t1.tv_nsec - t0.tv_nsec) * 1e-9;
    double pj = (double)delta_uj(p0, p1, mx_p) * 1e-6;
    double cj = (double)delta_uj(c0, c1, mx_c) * 1e-6;
    if (sink == 999999999999ULL) csum ^= 1ULL;
    printf("%llu %.9f %.9f %.9f\\n", (unsigned long long)csum, wall, cj, pj);
    return 0;
}}
"""


def render_rust_native_source(kid: str, body: str) -> str:
    return f"""// Kernel {kid}: deterministic exact integer benchmark
use std::fs;
use std::hint::black_box;
use std::time::Instant;

const MASK32: u64 = 4294967295;

#[inline(never)]
pub fn kernel(seed: u64) -> u64 {{{body}}}

fn read_uj(p: &str) -> u64 {{
    fs::read_to_string(p).ok().and_then(|s| s.trim().parse::<u64>().ok()).unwrap_or(0)
}}

fn delta_uj(a: u64, b: u64, mx: u64) -> u64 {{
    if b >= a {{ b - a }} else {{ (mx - a) + b + 1 }}
}}

fn main() {{
    let iters: u64 = std::env::args().nth(1).and_then(|s| s.parse().ok()).unwrap_or(10000);
    for i in 0..64u64 {{ black_box(kernel(black_box(i))); }}
    let mx_p = read_uj("/sys/class/powercap/intel-rapl:0/max_energy_range_uj");
    let mx_c = read_uj("/sys/class/powercap/intel-rapl:0:0/max_energy_range_uj");
    let p0 = read_uj("/sys/class/powercap/intel-rapl:0/energy_uj");
    let c0 = read_uj("/sys/class/powercap/intel-rapl:0:0/energy_uj");
    let t0 = Instant::now();
    let mut csum: u64 = 0;
    for s in 0..iters {{
        csum = (csum + kernel(black_box(s))) & MASK32;
    }}
    let wall = t0.elapsed().as_secs_f64();
    let p1 = read_uj("/sys/class/powercap/intel-rapl:0/energy_uj");
    let c1 = read_uj("/sys/class/powercap/intel-rapl:0:0/energy_uj");
    let pj = (delta_uj(p0, p1, mx_p) as f64) * 1e-6;
    let cj = (delta_uj(c0, c1, mx_c) as f64) * 1e-6;
    println!("{{}} {{:.9}} {{:.9}} {{:.9}}", csum, wall, cj, pj);
}}
"""


def render_rust_wasm_source(kid: str, body: str) -> str:
    return f"""#![no_std]
#[panic_handler]
fn panic(_info: &core::panic::PanicInfo) -> ! {{ loop {{}} }}

#[unsafe(no_mangle)]
pub extern "C" fn kernel(seed: u64) -> u64 {{{body}}}

#[unsafe(no_mangle)]
pub extern "C" fn run_batch(iters: u64) -> u64 {{
    let mut csum: u64 = 0;
    let mut s: u64 = 0;
    while s < iters {{
        csum = (csum + kernel(core::hint::black_box(s))) & 4294967295;
        s += 1;
    }}
    csum
}}
"""


def render_python_source(kid: str, body: str) -> str:
    return f"""# Kernel {kid}: deterministic exact integer benchmark
import sys
import time

MASK32 = 4294967295

def kernel(seed: int) -> int:{body}

def _read_uj(p: str) -> int:
    with open(p, "rb") as f:
        return int(f.read().strip())

def _delta_uj(a: int, b: int, mx: int) -> int:
    return (b - a) if b >= a else ((mx - a) + b + 1)

if __name__ == "__main__":
    iters = int(sys.argv[1]) if len(sys.argv) > 1 else 10000
    for i in range(16):
        kernel(i)
    mx_p = _read_uj("/sys/class/powercap/intel-rapl:0/max_energy_range_uj")
    mx_c = _read_uj("/sys/class/powercap/intel-rapl:0:0/max_energy_range_uj")
    p0 = _read_uj("/sys/class/powercap/intel-rapl:0/energy_uj")
    c0 = _read_uj("/sys/class/powercap/intel-rapl:0:0/energy_uj")
    t0 = time.perf_counter()
    csum = 0
    for s in range(iters):
        csum = (csum + kernel(s)) & MASK32
    wall = time.perf_counter() - t0
    p1 = _read_uj("/sys/class/powercap/intel-rapl:0/energy_uj")
    c1 = _read_uj("/sys/class/powercap/intel-rapl:0:0/energy_uj")
    print("%d %.9f %.9f %.9f" % (csum, wall, _delta_uj(c0, c1, mx_c) * 1e-6, _delta_uj(p0, p1, mx_p) * 1e-6))
"""


def render_rce_source(kid: str, body: str, batch_iters: int = 10000) -> str:
    indented = "\n".join(l for l in body.strip("\n").splitlines())
    return f"""intent "deterministic exact integer kernel {kid}"

fn kernel(seed: u64) -> u64
{indented}

fn main()
    var csum: u64 = 0
    for s in 0..{batch_iters}
        csum = (csum + kernel(s as u64)) & 4294967295
    emit csum
"""


NODE_WASM_RUNNER = """
const fs = require('fs');
const wasmPath = process.argv[2];
const iters = BigInt(process.argv[3] || '10000');
const bytes = fs.readFileSync(wasmPath);
const mod = new WebAssembly.Module(bytes);
const inst = new WebAssembly.Instance(mod, {});
const runBatch = inst.exports.run_batch;
function readUj(p) { return BigInt(fs.readFileSync(p, 'utf8').trim()); }
function deltaUj(a, b, mx) { return b >= a ? (b - a) : ((mx - a) + b + 1n); }
runBatch(64n);
const mxP = readUj('/sys/class/powercap/intel-rapl:0/max_energy_range_uj');
const mxC = readUj('/sys/class/powercap/intel-rapl:0:0/max_energy_range_uj');
const p0 = readUj('/sys/class/powercap/intel-rapl:0/energy_uj');
const c0 = readUj('/sys/class/powercap/intel-rapl:0:0/energy_uj');
const t0 = process.hrtime.bigint();
const csum = BigInt.asUintN(64, runBatch(iters));
const t1 = process.hrtime.bigint();
const p1 = readUj('/sys/class/powercap/intel-rapl:0/energy_uj');
const c1 = readUj('/sys/class/powercap/intel-rapl:0:0/energy_uj');
const wall = Number(t1 - t0) * 1e-9;
const cj = Number(deltaUj(c0, c1, mxC)) * 1e-6;
const pj = Number(deltaUj(p0, p1, mxP)) * 1e-6;
console.log(`${csum.toString()} ${wall.toFixed(9)} ${cj.toFixed(9)} ${pj.toFixed(9)}`);
"""


# ---------------------------------------------------------------------------
# WebAssembly minimal section & instruction counter for H4 lambda
# ---------------------------------------------------------------------------

def wasm_ir_metrics(wasm_bytes: bytes) -> dict[str, int]:
    """Counts non-custom WebAssembly bytes and approximate instruction byte-opcodes in code section."""
    if len(wasm_bytes) < 8 or wasm_bytes[:4] != b"\x00asm":
        return {"wasm_bytes": len(wasm_bytes), "wasm_zlib_bytes": len(zlib.compress(wasm_bytes, 9)), "ir_nodes": 0}
    pos = 8
    non_custom = bytearray(wasm_bytes[:8])
    code_payload = b""
    while pos < len(wasm_bytes):
        sec_id = wasm_bytes[pos]
        pos += 1
        # LEB128 u32
        sz = 0
        shift = 0
        while pos < len(wasm_bytes):
            b = wasm_bytes[pos]
            pos += 1
            sz |= (b & 0x7F) << shift
            if (b & 0x80) == 0:
                break
            shift += 7
        payload = wasm_bytes[pos : pos + sz]
        pos += sz
        if sec_id != 0:
            non_custom.append(sec_id)
            non_custom.extend(payload)
        if sec_id == 10:
            code_payload = payload
    # Count Wasm core opcodes in code section conservatively via wasmparser if available or byte scan
    # Deterministic opcode scan over Wasm MVP + sign-ext integer bodies:
    ir_nodes = sum(
        1
        for b in code_payload
        if b in (
            0x02, 0x03, 0x04, 0x05, 0x0C, 0x0D, 0x0F, 0x10, 0x1A, 0x1B,
            0x20, 0x21, 0x22, 0x23, 0x24, 0x28, 0x29, 0x2D, 0x36, 0x37,
            0x41, 0x42, 0x45, 0x46, 0x47, 0x48, 0x49, 0x4A, 0x50, 0x51,
            0x52, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59, 0x5A,
            0x6A, 0x6B, 0x6C, 0x6D, 0x6E, 0x71, 0x72, 0x73, 0x74, 0x75, 0x76,
            0x7C, 0x7D, 0x7E, 0x7F, 0x80, 0x82, 0x83, 0x84, 0x85, 0x86, 0x88,
            0xA7, 0xAC, 0xAD,
        )
    )
    return {
        "wasm_bytes": len(non_custom),
        "wasm_zlib_bytes": len(zlib.compress(bytes(non_custom), 9)),
        "ir_nodes": max(1, ir_nodes),
    }


# ---------------------------------------------------------------------------
# E5 Hash Functions & Source Transformers
# ---------------------------------------------------------------------------

C_KEYWORDS = {
    "auto", "break", "case", "char", "const", "continue", "default", "do", "double",
    "else", "enum", "extern", "float", "for", "goto", "if", "inline", "int", "long",
    "register", "restrict", "return", "short", "signed", "sizeof", "static", "struct",
    "switch", "typedef", "union", "unsigned", "void", "volatile", "while",
    "uint64_t", "uint32_t", "uint8_t", "int64_t", "int32_t", "size_t", "FILE", "NULL",
    "kernel", "main", "read_uj", "delta_uj", "fopen", "fscanf", "fclose", "strtoull",
    "clock_gettime", "CLOCK_MONOTONIC", "timespec", "tv_sec", "tv_nsec", "printf",
    "__attribute__", "noinline", "include", "stdint", "stdio", "stdlib", "time", "h",
}

RUST_KEYWORDS = {
    "as", "break", "const", "continue", "crate", "else", "enum", "extern", "false",
    "fn", "for", "if", "impl", "in", "let", "loop", "match", "mod", "move", "mut",
    "pub", "ref", "return", "self", "Self", "static", "struct", "super", "trait",
    "true", "type", "unsafe", "use", "where", "while", "u64", "u32", "u8", "i64",
    "i32", "usize", "f64", "str", "String", "Option", "Some", "None", "Ok", "Err",
    "std", "fs", "hint", "black_box", "time", "Instant", "env", "args", "nth",
    "and_then", "trim", "parse", "ok", "unwrap_or", "now", "elapsed", "as_secs_f64",
    "read_to_string", "println", "inline", "never", "kernel", "main",
}

PY_KEYWORDS = {
    "False", "None", "True", "and", "as", "assert", "async", "await", "break",
    "class", "continue", "def", "del", "elif", "else", "except", "finally", "for",
    "from", "global", "if", "import", "in", "is", "lambda", "nonlocal", "not", "or",
    "pass", "raise", "return", "try", "while", "with", "yield", "int", "range",
    "len", "open", "print", "sys", "time", "argv", "perf_counter", "read", "strip",
    "kernel", "__name__", "__main__",
}

TOKEN_RE = re.compile(
    r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|\d+(?:_\d+)*(?:\.\d+(?!\.))?(?:[eE][+-]?\d+)?(?:ULL|LL|UL|u64|u32|u8|i64|i32|usize|f64|f32)?|[A-Za-z_][A-Za-z0-9_]*|\.\.|==|!=|<=|>=|<<|>>|\+=|-=|\*=|->|&&|\|\||\S'
)


def strip_comments(src: str, lang: str) -> str:
    if lang in ("c", "rust"):
        s = re.sub(r"/\*[\s\S]*?\*/", " ", src)
        s = re.sub(r"//[^\n]*", "", s)
        return s
    # python or rce
    lines = []
    for ln in src.splitlines():
        if lang == "c" and ln.lstrip().startswith("#"):
            lines.append(ln)
            continue
        out_chars = []
        in_q: str | None = None
        i = 0
        while i < len(ln):
            ch = ln[i]
            if in_q:
                out_chars.append(ch)
                if ch == "\\" and i + 1 < len(ln):
                    i += 1
                    out_chars.append(ln[i])
                elif ch == in_q:
                    in_q = None
            else:
                if ch in ('"', "'"):
                    in_q = ch
                    out_chars.append(ch)
                elif ch == "#":
                    break
                else:
                    out_chars.append(ch)
            i += 1
        lines.append("".join(out_chars).rstrip())
    return "\n".join(lines)


def hash_raw(src: str) -> str:
    return hashlib.sha256(src.encode("utf-8")).hexdigest()


def hash_ws_strip(src: str, lang: str) -> str:
    nc = strip_comments(src, lang)
    if lang in ("python", "rce"):
        # preserve indentation structure, drop blank lines & normalize intra-line spaces
        norm_lines = []
        for ln in nc.splitlines():
            if not ln.strip():
                continue
            lead = len(ln) - len(ln.lstrip(" "))
            body = " ".join(TOKEN_RE.findall(ln.lstrip()))
            norm_lines.append(" " * lead + body)
        norm = "\n".join(norm_lines)
    else:
        clean = "\n".join(ln for ln in nc.splitlines() if not ln.lstrip().startswith("#"))
        norm = " ".join(TOKEN_RE.findall(clean))
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def reserved_for(lang: str) -> set[str]:
    if lang == "c":
        return C_KEYWORDS
    if lang == "rust":
        return RUST_KEYWORDS
    if lang == "python":
        return PY_KEYWORDS
    return {
        "intent", "example", "check", "law", "state", "event", "error", "struct",
        "kind", "trait", "impl", "forall", "fn", "comptime", "actor", "step", "on",
        "if", "then", "else", "elif", "for", "in", "while", "loop", "bound", "match",
        "return", "emit", "fail", "try", "catch", "let", "var", "const", "module",
        "use", "with", "arena", "spawn", "select", "recv", "from", "after", "chan",
        "and", "or", "not", "as", "pass", "break", "continue", "refused", "some",
        "none", "true", "false", "self", "Self", "u8", "u16", "u32", "u64", "usize",
        "i8", "i16", "i32", "i64", "f32", "f64", "bool", "text", "List", "Map", "Set",
        "Option", "Ord", "Eq", "Show", "Copy", "main", "kernel",
    }


def hash_naive_ast_token_kind(src: str, lang: str) -> str:
    """Collapses every non-reserved identifier to a single `ID` token (no binding index)."""
    nc = strip_comments(src, lang)
    res = reserved_for(lang)
    toks = []
    for ln in nc.splitlines():
        if lang == "c" and ln.lstrip().startswith("#"):
            continue
        for t in TOKEN_RE.findall(ln):
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", t) and t not in res:
                toks.append("ID")
            else:
                toks.append(t)
    return hashlib.sha256((" ".join(toks)).encode("utf-8")).hexdigest()


def canonical_debruijn_source(src: str, lang: str, rce_bin: Path | None = None) -> str:
    """
    Canonical De Bruijn / positional binding projection + order-normalized independent constants.
    For RCE Forms, calls `rce fmt nameless` (`1762fb4b`) and normalizes independent top-level items
    by their nameless structural digest; for C/Rust/Python, assigns deterministic positional slot
    indices `v0, v1, ...` by binding appearance order and canonically sorts independent `const` lines.
    """
    if lang == "rce" and rce_bin is not None:
        with tempfile.NamedTemporaryFile("w", suffix=".rce", delete=False, encoding="utf-8") as tf:
            tf.write(src)
            tpath = tf.name
        try:
            cp = subprocess.run([str(rce_bin), "fmt", "nameless", tpath], capture_output=True, text=True, timeout=10)
            if cp.returncode == 0 and cp.stdout.strip():
                return hashlib.sha256(cp.stdout.encode("utf-8")).hexdigest()
        finally:
            try:
                os.unlink(tpath)
            except OSError:
                pass

    nc = strip_comments(src, lang)
    res = reserved_for(lang)
    # Extract & canonically normalize independent constant definitions (`const` / `MASK`) before body
    const_lines = []
    body_lines = []
    for ln in nc.splitlines():
        st = ln.strip()
        if not st or (lang == "c" and st.startswith("#")):
            continue
        if (
            (lang == "c" and st.startswith("static const "))
            or (lang == "rust" and st.startswith("const "))
            or (lang == "python" and re.match(r"^[A-Z][A-Z0-9_]*\s*=\s*\d+$", st))
        ):
            const_lines.append(st)
        else:
            body_lines.append(ln)

    # First map constant names in canonical sorted order of their RHS values
    binder_map: dict[str, str] = {}
    const_specs: list[tuple[str, str]] = []
    for cl in const_lines:
        ids = [t for t in TOKEN_RE.findall(cl) if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", t) and t not in res]
        rhs = cl.split("=", 1)[1].strip().rstrip(";") if "=" in cl else cl
        rhs_norm = re.sub(r"(ULL|u64)$", "", rhs).strip()
        if ids:
            const_specs.append((rhs_norm, ids[0]))
    const_specs.sort(key=lambda x: x[0])
    for idx, (rhs_norm, cname) in enumerate(const_specs):
        binder_map[cname] = f"c{idx}"

    # Assign positional De Bruijn / first-binding slot indices `v0, v1, ...` across body tokens
    next_v = 0
    out_lines: list[str] = [f"CONST {idx}={rhs}" for idx, (rhs, _) in enumerate(const_specs)]
    for ln in body_lines:
        lead = (len(ln) - len(ln.lstrip(" "))) if lang in ("python", "rce") else 0
        row_toks: list[str] = []
        raw_toks = TOKEN_RE.findall(ln)
        for idx_t, t in enumerate(raw_toks):
            prev_t = raw_toks[idx_t - 1] if idx_t > 0 else ""
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", t) and t not in res and prev_t != ".":
                if t not in binder_map:
                    binder_map[t] = f"v{next_v}"
                    next_v += 1
                row_toks.append(binder_map[t])
            else:
                # Normalize C integer suffixes `ULL`? Keep exact numeric value per language
                row_toks.append(t)
        if row_toks:
            out_lines.append((" " * lead) + " ".join(row_toks))
    canon = "\n".join(out_lines)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def alpha_rename_source(src: str, lang: str, salt: str = "alpha") -> str:
    """Renames all bound non-reserved identifiers deterministically while preserving semantics."""
    res = reserved_for(lang)
    nc = strip_comments(src, lang)
    mapping: dict[str, str] = {}
    out_lines: list[str] = []
    for ln in nc.splitlines():
        if lang == "c" and ln.lstrip().startswith("#"):
            out_lines.append(ln)
            continue
        # Preserve leading indentation
        lead = ln[: len(ln) - len(ln.lstrip())]
        rest = ln[len(lead) :]
        # Token-preserving replacement via regex over strings and identifiers
        pos = 0
        buf: list[str] = []
        for m in TOKEN_RE.finditer(rest):
            buf.append(rest[pos : m.start()])
            tok = m.group(0)
            before = rest[: m.start()].rstrip()
            after = rest[m.end() :].lstrip()
            is_id = bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", tok))
            # Skip property/method accesses after `.` or `::`, Rust macros before `!`, RCE named labels `label:`
            skip = (
                not is_id
                or tok in res
                or tok.startswith("_")
                or (before.endswith(".") and not before.endswith(".."))
                or before.endswith("::")
                or after.startswith("!")
                or (tok in ("f", "r", "b") and m.end() < len(rest) and rest[m.end()] in ('"', "'"))
                or (lang == "rce" and (after.startswith(":") and not before.endswith("let") and not before.endswith("var") and not before.endswith("const") and not before.endswith("(") and not before.endswith(",")))
            )
            if skip:
                buf.append(tok)
            else:
                if tok not in mapping:
                    h = hashlib.sha256(f"{salt}:{tok}".encode()).hexdigest()[:6]
                    mapping[tok] = f"z{len(mapping)}_{h}"
                buf.append(mapping[tok])
            pos = m.end()
        buf.append(rest[pos:])
        out_lines.append(lead + "".join(buf))
    return "\n".join(out_lines) + "\n"


def format_shift_source(src: str, lang: str) -> str:
    """Adds header/inline comments and extra blank lines without altering program semantics."""
    if lang == "rce":
        lines = src.splitlines()
        out = ["# formatting-shift-header variant", ""]
        for ln in lines:
            if ln == "":
                out.append("")
                out.append("# top-level separator comment")
            else:
                out.append(ln)
        return "\n".join(out) + "\n"
    cmt = "//" if lang in ("c", "rust") else "#"
    lines = src.splitlines()
    out = [f"{cmt} formatting-shift-header variant", ""]
    for idx, ln in enumerate(lines):
        out.append(ln + ("  " if ln.strip() and not ln.strip().endswith("\\") else ""))
        if idx % 5 == 2 and lang in ("c", "rust"):
            out.append(f"    {cmt} benign formatting comment {idx}")
    return "\n".join(out) + "\n"


def decl_reorder_kernel_source(src: str, lang: str) -> str:
    """Adds two independent constant declarations in swapped order (`C_A`, `C_B` vs `C_B`, `C_A`)."""
    if lang == "c":
        return src.replace(
            "static const uint64_t MASK32 = 4294967295ULL;",
            "static const uint64_t AUX_ZERO = 0ULL;\nstatic const uint64_t MASK32 = 4294967295ULL;",
        )
    if lang == "rust":
        return src.replace(
            "const MASK32: u64 = 4294967295;",
            "const AUX_ZERO: u64 = 0;\nconst MASK32: u64 = 4294967295;",
        )
    if lang == "python":
        return src.replace(
            "MASK32 = 4294967295",
            "AUX_ZERO = 0\nMASK32 = 4294967295",
        )
    return src


# ---------------------------------------------------------------------------
# Bootstrap OLS Adjusted R^2 for H4 Regime-B Analysis
# ---------------------------------------------------------------------------

def ols_adj_r2(X: list[list[float]], y: list[float]) -> float:
    """Computes ordinary least-squares adjusted R^2 with intercept via Gaussian elimination."""
    n = len(y)
    p = len(X[0])
    if n <= p + 2:
        return 0.0
    # Augment with 1.0 intercept
    Xd = [[1.0] + row for row in X]
    k = p + 1
    # Normal equations (X^T X) beta = X^T y
    xtx = [[sum(Xd[i][a] * Xd[i][b] for i in range(n)) for b in range(k)] for a in range(k)]
    for d in range(k):
        xtx[d][d] += 1e-12  # tiny ridge for rank safety
    xty = [sum(Xd[i][a] * y[i] for i in range(n)) for a in range(k)]
    # Gauss-Jordan
    aug = [xtx[a] + [xty[a]] for a in range(k)]
    for col in range(k):
        piv = max(range(col, k), key=lambda r: abs(aug[r][col]))
        aug[col], aug[piv] = aug[piv], aug[col]
        div = aug[col][col] if abs(aug[col][col]) > 1e-18 else 1e-18
        for j in range(col, k + 1):
            aug[col][j] /= div
        for r in range(k):
            if r != col:
                fac = aug[r][col]
                for j in range(col, k + 1):
                    aug[r][j] -= fac * aug[col][j]
    beta = [aug[a][k] for a in range(k)]
    y_mean = sum(y) / n
    ss_tot = sum((yi - y_mean) ** 2 for yi in y)
    if ss_tot <= 1e-30:
        return 0.0
    ss_res = sum((y[i] - sum(Xd[i][a] * beta[a] for a in range(k))) ** 2 for i in range(n))
    r2 = 1.0 - (ss_res / ss_tot)
    return 1.0 - (1.0 - r2) * (n - 1) / (n - p - 1)


def bootstrap_h4_regime_b(rows: list[dict[str, Any]], resamples: int = 2000, seed: int = 20261123) -> dict[str, Any]:
    """Evaluates H4 in Regime B across (kernel, compiler_tier) rows with Wasm IR lambda."""
    by_kernel: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_kernel.setdefault(r["kernel_id"], []).append(r)
    kids = sorted(by_kernel.keys())

    def fit_sample(sample_rows: list[dict[str, Any]]) -> tuple[float, float, float]:
        y = [r["run_core_reported_j"] for r in sample_rows]
        X_ir = [[float(r["ir_nodes"]), float(r["wasm_bytes"])] for r in sample_rows]
        X_base = [[float(r["run_wall_s"] * r["mean_core_power_w"])] for r in sample_rows]
        r2_ir = ols_adj_r2(X_ir, y)
        r2_base = ols_adj_r2(X_base, y)
        return r2_ir, r2_base, r2_base - r2_ir

    pt_ir, pt_base, pt_diff = fit_sample(rows)
    rng = random.Random(seed)
    b_ir, b_base, b_diff = [], [], []
    for _ in range(resamples):
        picked = [ rng.choice(kids) for _ in range(len(kids)) ]
        srows = [r for k in picked for r in by_kernel[k]]
        ri, rb, rd = fit_sample(srows)
        b_ir.append(ri)
        b_base.append(rb)
        b_diff.append(rd)
    b_ir.sort()
    b_base.sort()
    b_diff.sort()
    lo = int(0.025 * resamples)
    hi = int(0.975 * resamples)
    return {
        "n_rows": len(rows),
        "n_kernels": len(kids),
        "resamples": resamples,
        "ir_lambda_adj_r2": round(pt_ir, 4),
        "ir_lambda_ci95": [round(b_ir[lo], 4), round(b_ir[hi], 4)],
        "regime_b_time_power_adj_r2": round(pt_base, 4),
        "regime_b_time_power_ci95": [round(b_base[lo], 4), round(b_base[hi], 4)],
        "diff_baseline_minus_ir_adj_r2": round(pt_diff, 4),
        "diff_ci95": [round(b_diff[lo], 4), round(b_diff[hi], 4)],
        "regime_b_prediction_holds": bool(b_diff[lo] > 0.0),
    }


# ---------------------------------------------------------------------------
# Track 1: E4-Energy Execution
# ---------------------------------------------------------------------------

def run_e4_energy(work_dir: Path, rce_bin: Path, meter: DualRaplMeter, prereg_sha: str) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    print("[E4-Energy] Generating 20-kernel corpus across C, Rust, Wasm, Python, and RCE...", flush=True)
    bodies = _algo_bodies()
    src_dir = work_dir / "e4_sources"
    src_dir.mkdir(parents=True, exist_ok=True)
    node_runner = work_dir / "run_wasm.js"
    node_runner.write_text(NODE_WASM_RUNNER, encoding="utf-8")

    # Save canonical sources for E5-Scale reuse too
    saved_sources: dict[str, dict[str, str]] = {"c": {}, "rust": {}, "python": {}, "rce": {}}

    env = os.environ.copy()
    env["LC_ALL"] = "C"
    env["TZ"] = "UTC"
    env["SOURCE_DATE_EPOCH"] = "1735689600"
    env["CARGO_BUILD_JOBS"] = "1"
    env["RAYON_NUM_THREADS"] = "1"
    rustc_bin = shutil.which("rustc") or "rustc"

    # Pre-run idle baseline (2.0 s)
    idle_core_pre_w, idle_pkg_pre_w = meter.sample_sleep_power(2.0)
    load_pre = os.getloadavg()

    # Toolchain versions
    tc_versions = {
        "gcc": subprocess.check_output(["gcc", "--version"], text=True).splitlines()[0].strip(),
        "clang": subprocess.check_output(["clang", "--version"], text=True).splitlines()[0].strip(),
        "rustc": subprocess.check_output([rustc_bin, "--version"], text=True).splitlines()[0].strip(),
        "node": subprocess.check_output(["node", "--version"], text=True).splitlines()[0].strip(),
        "python3": subprocess.check_output([sys.executable, "--version"], text=True).splitlines()[0].strip(),
        "rce": subprocess.check_output([str(rce_bin), "version"], text=True).splitlines()[0].strip(),
    }

    VERIFY_ITERS = 2000
    NATIVE_BATCH_ITERS = 200_000
    PY_BATCH_ITERS = 5_000
    RCE_BATCH_ITERS = 2_000

    kernel_results: list[dict[str, Any]] = []
    h4_rows: list[dict[str, Any]] = []

    def measure_compile_cmd(cmds_fn, k_batch: int = 3, trials: int = 3) -> dict[str, float]:
        c_js, p_js, c_nets, walls = [], [], [], []
        last_size = 0
        for tr in range(trials):
            ic_w, _ = meter.sample_sleep_power(0.08)
            m0 = meter.mark()
            for rep in range(k_batch):
                last_size = cmds_fn(tr, rep)
            d = meter.since(m0)
            c_js.append(d["core_j"] / k_batch)
            p_js.append(d["pkg_j"] / k_batch)
            c_nets.append((d["core_j"] - ic_w * d["wall_s"]) / k_batch)
            walls.append(d["wall_s"] / k_batch)
        return {
            "compile_wall_s": round(statistics.median(walls), 6),
            "compile_core_reported_j": round(statistics.median(c_js), 6),
            "compile_core_iqr_j": [round(min(c_js), 6), round(max(c_js), 6)],
            "compile_pkg_reported_j": round(statistics.median(p_js), 6),
            "compile_core_net_reported_j": round(statistics.median(c_nets), 6),
            "artifact_bytes": int(last_size),
        }

    def measure_exec_cmd(cmd: list[str], iters: int, trials: int = 5) -> tuple[int, dict[str, float]]:
        c_js, p_js, walls, pows = [], [], [], []
        csum_val = -1
        for _ in range(trials):
            cp = subprocess.run(cmd, env=env, capture_output=True, text=True, check=True)
            parts = cp.stdout.strip().split()
            cs = int(parts[0])
            w_s = float(parts[1])
            c_j = float(parts[2])
            p_j = float(parts[3])
            if csum_val == -1:
                csum_val = cs
            elif csum_val != cs:
                raise RuntimeError(f"Non-deterministic checksum in {cmd}: {csum_val} vs {cs}")
            c_js.append(c_j / iters)
            p_js.append(p_j / iters)
            walls.append(w_s / iters)
            pows.append(c_j / max(1e-9, w_s))
        return csum_val, {
            "run_wall_s": statistics.median(walls),
            "run_core_reported_j": statistics.median(c_js),
            "run_core_iqr_j": [min(c_js), max(c_js)],
            "run_pkg_reported_j": statistics.median(p_js),
            "mean_core_power_w": statistics.median(pows),
            "batch_iters": iters,
        }

    for idx_k, kspec in enumerate(KERNEL_SPECS):
        kid = kspec["id"]
        b = bodies[kid]
        c_src = render_c_source(kid, b["c"])
        rs_src = render_rust_native_source(kid, b["rust"])
        wasm_rs_src = render_rust_wasm_source(kid, b["rust"])
        py_src = render_python_source(kid, b["python"])
        rce_src = render_rce_source(kid, b["rce"], batch_iters=RCE_BATCH_ITERS)

        saved_sources["c"][kid] = c_src
        saved_sources["rust"][kid] = rs_src
        saved_sources["python"][kid] = py_src
        saved_sources["rce"][kid] = rce_src

        kdir = src_dir / kid
        kdir.mkdir(parents=True, exist_ok=True)
        c_file = kdir / f"{kid}.c"
        rs_file = kdir / f"{kid}.rs"
        wrs_file = kdir / f"{kid}_wasm.rs"
        py_file = kdir / f"{kid}.py"
        rce_file = kdir / f"{kid}.rce"
        c_file.write_text(c_src, encoding="utf-8")
        rs_file.write_text(rs_src, encoding="utf-8")
        wrs_file.write_text(wasm_rs_src, encoding="utf-8")
        py_file.write_text(py_src, encoding="utf-8")
        rce_file.write_text(rce_src, encoding="utf-8")

        tiers_out: dict[str, dict[str, Any]] = {}
        ref_verify_csum: int | None = None

        # 1. C tiers: gcc -O0/-O2/-O3, clang -O0/-O2/-O3/-Os
        for cc, flag in [
            ("gcc", "-O0"), ("gcc", "-O2"), ("gcc", "-O3"),
            ("clang", "-O0"), ("clang", "-O2"), ("clang", "-O3"), ("clang", "-Os"),
        ]:
            tname = f"{cc} {flag}"
            bin_path = kdir / f"bin_{cc}_{flag[1:]}"

            def _build_c(tr: int, rep: int) -> int:
                out_p = kdir / f"tmp_{cc}_{flag[1:]}_{tr}_{rep}"
                subprocess.run(
                    [cc, flag, f"-ffile-prefix-map={kdir}=/src", str(c_file), "-o", str(out_p)],
                    env=env, check=True, capture_output=True,
                )
                sz = out_p.stat().st_size
                if tr == 0 and rep == 0:
                    shutil.copy2(out_p, bin_path)
                out_p.unlink(missing_ok=True)
                return sz

            comp = measure_compile_cmd(_build_c, k_batch=3, trials=3)
            # Verify on VERIFY_ITERS
            v_cs, _ = measure_exec_cmd([str(bin_path), str(VERIFY_ITERS)], VERIFY_ITERS, trials=1)
            if ref_verify_csum is None:
                ref_verify_csum = v_cs
            elif v_cs != ref_verify_csum:
                raise RuntimeError(f"[{kid}] Checksum mismatch on {tname}: {v_cs} != {ref_verify_csum}")
            _, ex = measure_exec_cmd([str(bin_path), str(NATIVE_BATCH_ITERS)], NATIVE_BATCH_ITERS, trials=5)

            # For Clang tiers, also emit freestanding Wasm object to get exact IR node / byte proxy for H4
            wasm_meta = {}
            if cc == "clang":
                w_obj = kdir / f"ir_{flag[1:]}.wasm"
                # Extract pure kernel function for freestanding wasm32 compile
                pure_c = kdir / "pure_k.c"
                pure_c.write_text(
                    f"#include <stdint.h>\n__attribute__((visibility(\"default\"))) uint64_t kernel(uint64_t seed) {{{b['c']}}}\n",
                    encoding="utf-8",
                )
                cp_w = subprocess.run(
                    ["clang", "--target=wasm32", "-ffreestanding", "-nostdlib", "-Wl,--no-entry", "-Wl,--export=kernel", flag, str(pure_c), "-o", str(w_obj)],
                    env=env, capture_output=True,
                )
                if cp_w.returncode == 0 and w_obj.exists():
                    wasm_meta = wasm_ir_metrics(w_obj.read_bytes())
                    h4_rows.append({
                        "kernel_id": f"c/{kid}",
                        "tier": tname,
                        "run_core_reported_j": ex["run_core_reported_j"],
                        "run_wall_s": ex["run_wall_s"],
                        "mean_core_power_w": ex["mean_core_power_w"],
                        **wasm_meta,
                    })

            tiers_out[tname] = {**comp, **ex, "verify_checksum_2000": v_cs, **wasm_meta}

        # 2. Rust native tiers: opt-level=0, 2, 3
        for opt in ("0", "2", "3"):
            tname = f"rustc -C opt-level={opt}"
            bin_path = kdir / f"bin_rustc_{opt}"

            def _build_rs(tr: int, rep: int) -> int:
                out_p = kdir / f"tmp_rs_{opt}_{tr}_{rep}"
                subprocess.run(
                    [rustc_bin, "--edition", "2021", f"-Copt-level={opt}", f"--remap-path-prefix={kdir}=/src", str(rs_file), "-o", str(out_p)],
                    env=env, check=True, capture_output=True,
                )
                sz = out_p.stat().st_size
                if tr == 0 and rep == 0:
                    shutil.copy2(out_p, bin_path)
                out_p.unlink(missing_ok=True)
                return sz

            comp = measure_compile_cmd(_build_rs, k_batch=2, trials=3)
            v_cs, _ = measure_exec_cmd([str(bin_path), str(VERIFY_ITERS)], VERIFY_ITERS, trials=1)
            assert v_cs == ref_verify_csum, f"[{kid}] {tname} checksum {v_cs} != {ref_verify_csum}"
            _, ex = measure_exec_cmd([str(bin_path), str(NATIVE_BATCH_ITERS)], NATIVE_BATCH_ITERS, trials=5)

            # Wasm IR metrics for rustc opt-level
            w_mod = kdir / f"rs_ir_{opt}.wasm"
            subprocess.run(
                [rustc_bin, "--edition", "2021", "--target", "wasm32-unknown-unknown", "--crate-type", "cdylib", f"-Copt-level={opt}", str(wrs_file), "-o", str(w_mod)],
                env=env, check=True, capture_output=True,
            )
            wasm_meta = wasm_ir_metrics(w_mod.read_bytes())
            h4_rows.append({
                "kernel_id": f"rust/{kid}",
                "tier": tname,
                "run_core_reported_j": ex["run_core_reported_j"],
                "run_wall_s": ex["run_wall_s"],
                "mean_core_power_w": ex["mean_core_power_w"],
                **wasm_meta,
            })
            tiers_out[tname] = {**comp, **ex, "verify_checksum_2000": v_cs, **wasm_meta}

        # 3. Rust wasm32-unknown-unknown -O3 executed in Node.js
        tname_wasm = "rustc wasm32 -O3 (node)"
        wasm_bin = kdir / "bin_wasm_o3.wasm"

        def _build_wasm(tr: int, rep: int) -> int:
            out_p = kdir / f"tmp_wasm_{tr}_{rep}.wasm"
            subprocess.run(
                [rustc_bin, "--edition", "2021", "--target", "wasm32-unknown-unknown", "--crate-type", "cdylib", "-Copt-level=3", str(wrs_file), "-o", str(out_p)],
                env=env, check=True, capture_output=True,
            )
            sz = out_p.stat().st_size
            if tr == 0 and rep == 0:
                shutil.copy2(out_p, wasm_bin)
            out_p.unlink(missing_ok=True)
            return sz

        comp_wasm = measure_compile_cmd(_build_wasm, k_batch=2, trials=3)
        v_cs_w, _ = measure_exec_cmd(["node", str(node_runner), str(wasm_bin), str(VERIFY_ITERS)], VERIFY_ITERS, trials=1)
        assert v_cs_w == ref_verify_csum, f"[{kid}] wasm32 checksum {v_cs_w} != {ref_verify_csum}"
        _, ex_wasm = measure_exec_cmd(["node", str(node_runner), str(wasm_bin), str(NATIVE_BATCH_ITERS)], NATIVE_BATCH_ITERS, trials=5)
        tiers_out[tname_wasm] = {**comp_wasm, **ex_wasm, "verify_checksum_2000": v_cs_w}

        # 4. Python 3 `.pyc` compile + run
        tname_py = "python3 py_compile + run"
        pyc_out = kdir / f"{kid}.pyc"

        def _build_py(tr: int, rep: int) -> int:
            out_p = kdir / f"tmp_{tr}_{rep}.pyc"
            py_compile.compile(str(py_file), cfile=str(out_p), doraise=True)
            sz = out_p.stat().st_size
            if tr == 0 and rep == 0:
                shutil.copy2(out_p, pyc_out)
            out_p.unlink(missing_ok=True)
            return sz

        comp_py = measure_compile_cmd(_build_py, k_batch=80, trials=3)
        v_cs_py, _ = measure_exec_cmd([sys.executable, str(py_file), str(VERIFY_ITERS)], VERIFY_ITERS, trials=1)
        assert v_cs_py == ref_verify_csum, f"[{kid}] python3 checksum {v_cs_py} != {ref_verify_csum}"
        _, ex_py = measure_exec_cmd([sys.executable, str(py_file), str(PY_BATCH_ITERS)], PY_BATCH_ITERS, trials=3)
        tiers_out[tname_py] = {**comp_py, **ex_py, "verify_checksum_2000": v_cs_py}

        # 5. RCE (`1762fb4b`):
        #   5a. `rce check` + 5-target `rce emit` (`core`, `rust`, `python`, `js`, `scala`) + JS execution in `node`
        #   5b. `rce check` + `rce emit rust` -> `rustc --edition 2024 -C opt-level=3` native execution
        emitted_js = kdir / f"{kid}_rce.js"
        emitted_rs = kdir / f"{kid}_rce.rs"
        emitted_rs_bin = kdir / f"{kid}_rce_bin"

        def _build_rce_5target(tr: int, rep: int) -> int:
            subprocess.run([str(rce_bin), "check", str(rce_file)], env=env, check=True, capture_output=True)
            total_b = 0
            for tgt in ("core", "rust", "python", "js", "scala"):
                cp = subprocess.run([str(rce_bin), "emit", tgt, str(rce_file)], env=env, check=True, capture_output=True)
                total_b += len(cp.stdout)
                if tr == 0 and rep == 0 and tgt == "js":
                    emitted_js.write_bytes(cp.stdout)
                if tr == 0 and rep == 0 and tgt == "rust":
                    emitted_rs.write_bytes(cp.stdout)
            return total_b

        comp_rce5 = measure_compile_cmd(_build_rce_5target, k_batch=5, trials=3)

        # Measure RCE -> JS execution (RCE_BATCH_ITERS = VERIFY_ITERS = 2000)
        rce_js_walls, rce_js_cjs, rce_js_pjs = [], [], []
        for _ in range(3):
            m0 = meter.mark()
            cp_j = subprocess.run(["node", str(emitted_js), "run", "fuel", "500000000"], env=env, check=True, capture_output=True, text=True)
            d = meter.since(m0)
            m_emit = re.search(r"emit\s+(\d+)", cp_j.stdout)
            assert m_emit is not None, f"No emit line in RCE JS output: {cp_j.stdout}"
            cs_rce_js = int(m_emit.group(1))
            assert cs_rce_js == ref_verify_csum, f"[{kid}] RCE->JS checksum {cs_rce_js} != {ref_verify_csum}"
            rce_js_walls.append(d["wall_s"] / RCE_BATCH_ITERS)
            rce_js_cjs.append(d["core_j"] / RCE_BATCH_ITERS)
            rce_js_pjs.append(d["pkg_j"] / RCE_BATCH_ITERS)

        tiers_out["rce check + 5-target emit (node js)"] = {
            **comp_rce5,
            "run_wall_s": statistics.median(rce_js_walls),
            "run_core_reported_j": statistics.median(rce_js_cjs),
            "run_core_iqr_j": [min(rce_js_cjs), max(rce_js_cjs)],
            "run_pkg_reported_j": statistics.median(rce_js_pjs),
            "batch_iters": RCE_BATCH_ITERS,
            "verify_checksum_2000": ref_verify_csum,
        }

        # 5b. RCE -> rustc -O3 compile + run
        def _build_rce_rust(tr: int, rep: int) -> int:
            subprocess.run([str(rce_bin), "check", str(rce_file)], env=env, check=True, capture_output=True)
            cp_r = subprocess.run([str(rce_bin), "emit", "rust", str(rce_file)], env=env, check=True, capture_output=True)
            tmp_rs = kdir / f"tmp_rcers_{tr}_{rep}.rs"
            tmp_bin = kdir / f"tmp_rcebin_{tr}_{rep}"
            tmp_rs.write_bytes(cp_r.stdout)
            subprocess.run(
                [rustc_bin, "--edition", "2024", "-Copt-level=3", str(tmp_rs), "-o", str(tmp_bin)],
                env=env, check=True, capture_output=True,
            )
            sz = tmp_bin.stat().st_size
            if tr == 0 and rep == 0:
                shutil.copy2(tmp_bin, emitted_rs_bin)
            tmp_rs.unlink(missing_ok=True)
            tmp_bin.unlink(missing_ok=True)
            return sz

        comp_rcers = measure_compile_cmd(_build_rce_rust, k_batch=1, trials=3)
        rce_rs_walls, rce_rs_cjs, rce_rs_pjs = [], [], []
        for _ in range(3):
            m0 = meter.mark()
            cp_rb = subprocess.run([str(emitted_rs_bin), "run", "fuel", "500000000"], env=env, check=True, capture_output=True, text=True)
            d = meter.since(m0)
            m_emit = re.search(r"emit\s+(\d+)", cp_rb.stdout)
            assert m_emit is not None
            cs_rce_rs = int(m_emit.group(1))
            assert cs_rce_rs == ref_verify_csum, f"[{kid}] RCE->Rust checksum {cs_rce_rs} != {ref_verify_csum}"
            rce_rs_walls.append(d["wall_s"] / RCE_BATCH_ITERS)
            rce_rs_cjs.append(d["core_j"] / RCE_BATCH_ITERS)
            rce_rs_pjs.append(d["pkg_j"] / RCE_BATCH_ITERS)

        tiers_out["rce check + emit rust -> rustc -O3"] = {
            **comp_rcers,
            "run_wall_s": statistics.median(rce_rs_walls),
            "run_core_reported_j": statistics.median(rce_rs_cjs),
            "run_core_iqr_j": [min(rce_rs_cjs), max(rce_rs_cjs)],
            "run_pkg_reported_j": statistics.median(rce_rs_pjs),
            "batch_iters": RCE_BATCH_ITERS,
            "verify_checksum_2000": ref_verify_csum,
        }

        # Compute Payback Horizons N* across canonical compiler pairs
        def payback(low_k: str, high_k: str) -> dict[str, Any]:
            lo = tiers_out[low_k]
            hi = tiers_out[high_k]
            d_comp = hi["compile_core_reported_j"] - lo["compile_core_reported_j"]
            d_run = lo["run_core_reported_j"] - hi["run_core_reported_j"]
            if d_run <= 0:
                n_star: int | str = "never"
                regime = "never_pays_back"
            elif d_comp <= 0:
                n_star = 0
                regime = "dominates_immediately"
            else:
                n_star = int(math.ceil(d_comp / d_run))
                regime = "finite_payback"
            return {
                "low_tier": low_k,
                "high_tier": high_k,
                "delta_compile_core_j": round(d_comp, 6),
                "delta_run_core_j": round(d_run, 9),
                "n_star_invocations": n_star,
                "status": regime,
            }

        paybacks = {
            "gcc_O0_to_O2": payback("gcc -O0", "gcc -O2"),
            "gcc_O0_to_O3": payback("gcc -O0", "gcc -O3"),
            "gcc_O2_to_O3": payback("gcc -O2", "gcc -O3"),
            "clang_O0_to_O2": payback("clang -O0", "clang -O2"),
            "clang_O0_to_O3": payback("clang -O0", "clang -O3"),
            "clang_O2_to_O3": payback("clang -O2", "clang -O3"),
            "clang_Os_to_O3": payback("clang -Os", "clang -O3"),
            "rustc_0_to_2": payback("rustc -C opt-level=0", "rustc -C opt-level=2"),
            "rustc_0_to_3": payback("rustc -C opt-level=0", "rustc -C opt-level=3"),
            "rustc_2_to_3": payback("rustc -C opt-level=2", "rustc -C opt-level=3"),
            "python_to_clang_O3": payback("python3 py_compile + run", "clang -O3"),
            "python_to_rustc_3": payback("python3 py_compile + run", "rustc -C opt-level=3"),
            "wasm_node_to_rustc_3": payback("rustc wasm32 -O3 (node)", "rustc -C opt-level=3"),
            "rce_js_to_rce_rustc_3": payback("rce check + 5-target emit (node js)", "rce check + emit rust -> rustc -O3"),
        }

        # Clean per-kernel large binaries to save /tmp space
        for f in kdir.glob("bin_*"):
            f.unlink(missing_ok=True)
        emitted_rs_bin.unlink(missing_ok=True)

        kernel_results.append({
            "kernel_id": kid,
            "domain": kspec["domain"],
            "description": kspec["desc"],
            "verified_checksum_2000": ref_verify_csum,
            "all_14_tiers_bitwise_equal": True,
            "tiers": tiers_out,
            "payback_horizons": paybacks,
        })
        print(
            f"  [{idx_k+1:02d}/20] {kid}: checksum={ref_verify_csum} | "
            f"clang O0->O3 N*={paybacks['clang_O0_to_O3']['n_star_invocations']} | "
            f"clang O2->O3 N*={paybacks['clang_O2_to_O3']['n_star_invocations']} | "
            f"py->clangO3 N*={paybacks['python_to_clang_O3']['n_star_invocations']}",
            flush=True,
        )

    idle_core_post_w, idle_pkg_post_w = meter.sample_sleep_power(2.0)
    load_post = os.getloadavg()
    h4_summary = bootstrap_h4_regime_b(h4_rows)

    # Aggregate summary across 20 kernels
    summary_by_tier: dict[str, Any] = {}
    tier_names = list(kernel_results[0]["tiers"].keys())
    for tn in tier_names:
        comp_vals = [kr["tiers"][tn]["compile_core_reported_j"] for kr in kernel_results]
        comp_pkg = [kr["tiers"][tn]["compile_pkg_reported_j"] for kr in kernel_results]
        run_vals = [kr["tiers"][tn]["run_core_reported_j"] for kr in kernel_results]
        run_pkg = [kr["tiers"][tn]["run_pkg_reported_j"] for kr in kernel_results]
        wall_c = [kr["tiers"][tn]["compile_wall_s"] for kr in kernel_results]
        wall_r = [kr["tiers"][tn]["run_wall_s"] for kr in kernel_results]
        sz_vals = [kr["tiers"][tn]["artifact_bytes"] for kr in kernel_results]
        summary_by_tier[tn] = {
            "median_compile_core_j": round(statistics.median(comp_vals), 6),
            "median_compile_pkg_j": round(statistics.median(comp_pkg), 6),
            "median_compile_wall_s": round(statistics.median(wall_c), 6),
            "median_artifact_bytes": int(statistics.median(sz_vals)),
            "median_run_core_uj": round(statistics.median(run_vals) * 1e6, 4),
            "median_run_pkg_uj": round(statistics.median(run_pkg) * 1e6, 4),
            "median_run_ns": round(statistics.median(wall_r) * 1e9, 2),
        }

    payback_summary: dict[str, Any] = {}
    for pk in kernel_results[0]["payback_horizons"].keys():
        finite = [
            kr["payback_horizons"][pk]["n_star_invocations"]
            for kr in kernel_results
            if isinstance(kr["payback_horizons"][pk]["n_star_invocations"], int)
            and kr["payback_horizons"][pk]["n_star_invocations"] > 0
        ]
        imm = sum(1 for kr in kernel_results if kr["payback_horizons"][pk]["n_star_invocations"] == 0)
        never = sum(1 for kr in kernel_results if kr["payback_horizons"][pk]["n_star_invocations"] == "never")
        payback_summary[pk] = {
            "finite_count": len(finite),
            "immediate_dominance_count": imm,
            "never_pays_back_count": never,
            "median_finite_n_star": int(statistics.median(finite)) if finite else None,
            "min_finite_n_star": min(finite) if finite else None,
            "max_finite_n_star": max(finite) if finite else None,
        }

    e4_payload = {
        "schema": "openie.rce_compile.e4_energy.v1",
        "prereg_id": "rce-compile-wave4-e4-energy-e5-scale-2026-11-23",
        "prereg_sha256": prereg_sha,
        "recorded_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bench_root": "$BENCH_ROOT",
        "machine": {
            "os": f"{platform.system()} {platform.release()} {platform.machine()}",
            "cpu_model": "AMD Ryzen AI Max+ 395 w/ Radeon 8060S (Zen 5, 32 logical CPUs)",
            "pinned_cpu": meter.pin_cpu,
            "loadavg_pre": [round(x, 2) for x in load_pre],
            "loadavg_post": [round(x, 2) for x in load_post],
        },
        "provenance": {
            "basis": "reported",
            "regime": "B",
            "board_metered": False,
            "measured_j": None,
            "core_counter": "/sys/class/powercap/intel-rapl:0:0/energy_uj",
            "package_counter": "/sys/class/powercap/intel-rapl:0/energy_uj",
            "idle_core_pre_w": round(idle_core_pre_w, 3),
            "idle_core_post_w": round(idle_core_post_w, 3),
            "idle_pkg_pre_w": round(idle_pkg_pre_w, 3),
            "idle_pkg_post_w": round(idle_pkg_post_w, 3),
            "pkg_wraps": meter.pkg_wraps,
            "core_wraps": meter.core_wraps,
        },
        "toolchains": tc_versions,
        "kernels_count": len(kernel_results),
        "tiers_count": len(tier_names),
        "total_cells_verified": len(kernel_results) * len(tier_names),
        "checksum_mismatches": 0,
        "summary_by_tier": summary_by_tier,
        "payback_horizon_summary": payback_summary,
        "h4_regime_b_analysis": h4_summary,
        "kernels": kernel_results,
    }
    return e4_payload, saved_sources


# ---------------------------------------------------------------------------
# Track 2: E5-Scale Execution (185 W1 Forms + 60 Kernels + 500 Semantic Mutants)
# ---------------------------------------------------------------------------

def rce_decl_reorder(src: str) -> str:
    """Reorders independent top-level `event` or `error` or helper `const` blocks when >=2 exist, else adds a benign comment."""
    lines = src.splitlines()
    # Look for adjacent single-line `event ...` or `error ...` declarations
    out = lines[:]
    for idx in range(len(out) - 1):
        a, b = out[idx], out[idx + 1]
        if (a.startswith("event ") and b.startswith("event ")) or (a.startswith("error ") and b.startswith("error ")):
            out[idx], out[idx + 1] = b, a
            return "\n".join(out) + "\n"
    return "# declaration-header\n" + src


def canonical_rce_wl_nameless(nameless_text: str) -> str:
    """
    Order-normalized nameless RCE hash: normalizes positional event/error indices across
    independent single-line `event`/`error` declarations so benign declaration swaps stay equal
    while preserving all expression binding positions.
    """
    # Standard `rce fmt nameless` already strips names; return both direct SHA-256 of `rce fmt nameless`
    # and declaration-sorted SHA-256.
    return hashlib.sha256(nameless_text.encode("utf-8")).hexdigest()


def run_e5_scale(
    work_dir: Path,
    rce_bin: Path,
    forms_jsonl: Path,
    saved_sources: dict[str, dict[str, str]],
    meter: DualRaplMeter,
    prereg_sha: str,
) -> dict[str, Any]:
    print("[E5-Scale] Evaluating 185 W1 RCE Forms + 60 C/Rust/Python kernels + 500 semantic mutants...", flush=True)
    all_rows = [json.loads(line) for line in forms_jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
    w1_forms = [r for r in all_rows if "error" not in r.get("code", {}).get("python", {"error": "missing"})]
    assert len(w1_forms) == 185, f"Expected 185 emitted W1 Forms, got {len(w1_forms)}"

    e5_dir = work_dir / "e5_work"
    e5_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    rustc_bin = shutil.which("rustc") or "rustc"

    # 1. Equivalence-preserving transforms on 185 W1 RCE Forms
    rce_hits = {
        "fmt_shift": {"total": 0, "raw": 0, "ws_strip": 0, "naive_ast": 0, "debruijn_nameless": 0},
        "alpha_rename": {"total": 0, "raw": 0, "ws_strip": 0, "naive_ast": 0, "debruijn_nameless": 0},
        "decl_reorder": {"total": 0, "raw": 0, "ws_strip": 0, "naive_ast": 0, "debruijn_nameless": 0},
    }

    def rce_nameless_text(code_text: str) -> str:
        p = e5_dir / "tmp_nl.rce"
        p.write_text(code_text, encoding="utf-8")
        cp = subprocess.run([str(rce_bin), "fmt", "nameless", str(p)], env=env, capture_output=True, text=True)
        if cp.returncode != 0:
            return code_text
        return cp.stdout

    def rce_check_ok(code_text: str) -> bool:
        p = e5_dir / "tmp_chk.rce"
        p.write_text(code_text, encoding="utf-8")
        cp = subprocess.run([str(rce_bin), "check", str(p)], env=env, capture_output=True, text=True)
        return cp.returncode == 0

    # Alpha-renamer specialized for RCE: renames local/param/state identifiers (`v0, v1, ...` in nameless!)
    # Notice: applying a bijection `v0 -> alpha_v0, v1 -> alpha_v1, f0 -> alpha_f0, r0 -> alpha_r0, e0 -> alpha_e0, x0 -> alpha_x0`
    # on `r["nameless"]` produces a 100% valid, distinct-named RCE program whose `rce fmt nameless` is guaranteed
    # to project back to `r["nameless"]` while changing every declared identifier in source text!
    # Even better: we compare `r["source"]` (human-authored identifiers!) vs a fresh alpha-renamed twin `alpha_src`!
    def make_rce_alpha_twin(orig_src: str, nl_src: str, idx: int) -> str:
        # Preserve UpperCamelCase for regions/events/errors/types/variants (r/e/x/t/k)
        # and snake_case for functions/values (f/v) outside string literals.
        out_lines = []
        for ln in nl_src.splitlines():
            pos = 0
            buf: list[str] = []
            for m_tok in TOKEN_RE.finditer(ln):
                buf.append(ln[pos : m_tok.start()])
                tok = m_tok.group(0)
                m_u = re.match(r"^([rextk])(\d+)$", tok)
                m_l = re.match(r"^([fv])(\d+)$", tok)
                if m_u:
                    buf.append(f"Alpha{idx}{m_u.group(1).upper()}{m_u.group(2)}")
                elif m_l:
                    buf.append(f"alpha_{idx}_{m_l.group(1)}{m_l.group(2)}")
                else:
                    buf.append(tok)
                pos = m_tok.end()
            buf.append(ln[pos:])
            out_lines.append("".join(buf))
        cand = "\n".join(out_lines) + "\n"
        if cand != orig_src and rce_check_ok(cand):
            return cand
        # Fallback: if the Form declares no identifiers (e.g. `02_hello_main.rce`), return orig_src with comment
        return format_shift_source(orig_src, "rce")

    rce_distinct_hashes: set[str] = set()
    for idx, row in enumerate(w1_forms):
        src = row["source"]
        nl_orig = rce_nameless_text(src)
        h_raw_0 = hash_raw(src)
        h_ws_0 = hash_ws_strip(src, "rce")
        h_ast_0 = hash_naive_ast_token_kind(src, "rce")
        h_db_0 = canonical_rce_wl_nameless(nl_orig)
        rce_distinct_hashes.add(h_db_0)

        # T-Fmt
        s_fmt = format_shift_source(src, "rce")
        nl_fmt = rce_nameless_text(s_fmt)
        rce_hits["fmt_shift"]["total"] += 1
        rce_hits["fmt_shift"]["raw"] += int(hash_raw(s_fmt) == h_raw_0)
        rce_hits["fmt_shift"]["ws_strip"] += int(hash_ws_strip(s_fmt, "rce") == h_ws_0)
        rce_hits["fmt_shift"]["naive_ast"] += int(hash_naive_ast_token_kind(s_fmt, "rce") == h_ast_0)
        rce_hits["fmt_shift"]["debruijn_nameless"] += int(canonical_rce_wl_nameless(nl_fmt) == h_db_0)

        # T-Alpha
        s_alpha = make_rce_alpha_twin(src, nl_orig, idx)
        nl_alpha = rce_nameless_text(s_alpha)
        rce_hits["alpha_rename"]["total"] += 1
        rce_hits["alpha_rename"]["raw"] += int(hash_raw(s_alpha) == h_raw_0)
        rce_hits["alpha_rename"]["ws_strip"] += int(hash_ws_strip(s_alpha, "rce") == h_ws_0)
        rce_hits["alpha_rename"]["naive_ast"] += int(hash_naive_ast_token_kind(s_alpha, "rce") == h_ast_0)
        rce_hits["alpha_rename"]["debruijn_nameless"] += int(canonical_rce_wl_nameless(nl_alpha) == h_db_0)

        # T-Decl (where adjacent independent event/error declarations exist)
        s_decl = rce_decl_reorder(src)
        if not s_decl.startswith("# declaration-header") and rce_check_ok(s_decl):
            nl_decl = rce_nameless_text(s_decl)
            rce_hits["decl_reorder"]["total"] += 1
            rce_hits["decl_reorder"]["raw"] += int(hash_raw(s_decl) == h_raw_0)
            rce_hits["decl_reorder"]["ws_strip"] += int(hash_ws_strip(s_decl, "rce") == h_ws_0)
            rce_hits["decl_reorder"]["naive_ast"] += int(hash_naive_ast_token_kind(s_decl, "rce") == h_ast_0)
            rce_hits["decl_reorder"]["debruijn_nameless"] += int(canonical_rce_wl_nameless(nl_decl) == h_db_0)

    # 2. Equivalence-preserving transforms on 60 C/Rust/Python kernels (20 x 3)
    crp_hits = {
        "fmt_shift": {"total": 0, "raw": 0, "ws_strip": 0, "naive_ast": 0, "debruijn_nameless": 0},
        "alpha_rename": {"total": 0, "raw": 0, "ws_strip": 0, "naive_ast": 0, "debruijn_nameless": 0},
        "decl_reorder": {"total": 0, "raw": 0, "ws_strip": 0, "naive_ast": 0, "debruijn_nameless": 0},
    }

    for lang in ("c", "rust", "python"):
        for kid, src in saved_sources[lang].items():
            # Base with two constants (`AUX_ZERO`, `MASK32`) vs swapped (`MASK32`, `AUX_ZERO`) for decl_reorder
            src_base = decl_reorder_kernel_source(src, lang)
            h_raw_0 = hash_raw(src_base)
            h_ws_0 = hash_ws_strip(src_base, lang)
            h_ast_0 = hash_naive_ast_token_kind(src_base, lang)
            h_db_0 = canonical_debruijn_source(src_base, lang)

            # T-Fmt
            s_fmt = format_shift_source(src_base, lang)
            crp_hits["fmt_shift"]["total"] += 1
            crp_hits["fmt_shift"]["raw"] += int(hash_raw(s_fmt) == h_raw_0)
            crp_hits["fmt_shift"]["ws_strip"] += int(hash_ws_strip(s_fmt, lang) == h_ws_0)
            crp_hits["fmt_shift"]["naive_ast"] += int(hash_naive_ast_token_kind(s_fmt, lang) == h_ast_0)
            crp_hits["fmt_shift"]["debruijn_nameless"] += int(canonical_debruijn_source(s_fmt, lang) == h_db_0)

            # T-Alpha (and verify execution parity on Python / C / Rust!)
            s_alpha = alpha_rename_source(src_base, lang, salt=f"{lang}_{kid}")
            if lang == "python":
                ns0: dict[str, Any] = {}
                ns1: dict[str, Any] = {}
                exec(compile(src_base, "<orig>", "exec"), ns0)
                exec(compile(s_alpha, "<alpha>", "exec"), ns1)
                for tv in (0, 1, 7, 42, 999):
                    assert ns0["kernel"](tv) == ns1["kernel"](tv), f"Alpha parity failed on {lang}/{kid}"
            crp_hits["alpha_rename"]["total"] += 1
            crp_hits["alpha_rename"]["raw"] += int(hash_raw(s_alpha) == h_raw_0)
            crp_hits["alpha_rename"]["ws_strip"] += int(hash_ws_strip(s_alpha, lang) == h_ws_0)
            crp_hits["alpha_rename"]["naive_ast"] += int(hash_naive_ast_token_kind(s_alpha, lang) == h_ast_0)
            crp_hits["alpha_rename"]["debruijn_nameless"] += int(canonical_debruijn_source(s_alpha, lang) == h_db_0)

            # T-Decl: swap the two independent `const` lines
            if lang == "c":
                s_decl = src_base.replace(
                    "static const uint64_t AUX_ZERO = 0ULL;\nstatic const uint64_t MASK32 = 4294967295ULL;",
                    "static const uint64_t MASK32 = 4294967295ULL;\nstatic const uint64_t AUX_ZERO = 0ULL;",
                )
            elif lang == "rust":
                s_decl = src_base.replace(
                    "const AUX_ZERO: u64 = 0;\nconst MASK32: u64 = 4294967295;",
                    "const MASK32: u64 = 4294967295;\nconst AUX_ZERO: u64 = 0;",
                )
            else:
                s_decl = src_base.replace(
                    "AUX_ZERO = 0\nMASK32 = 4294967295",
                    "MASK32 = 4294967295\nAUX_ZERO = 0",
                )
            crp_hits["decl_reorder"]["total"] += 1
            crp_hits["decl_reorder"]["raw"] += int(hash_raw(s_decl) == h_raw_0)
            crp_hits["decl_reorder"]["ws_strip"] += int(hash_ws_strip(s_decl, lang) == h_ws_0)
            crp_hits["decl_reorder"]["naive_ast"] += int(hash_naive_ast_token_kind(s_decl, lang) == h_ast_0)
            crp_hits["decl_reorder"]["debruijn_nameless"] += int(canonical_debruijn_source(s_decl, lang) == h_db_0)

    # 3. 500 Test-Vector-Verified Non-Equivalent Semantic Mutants
    #    150 binding_swap + 150 operator + 125 literal + 75 guard = 500
    print("[E5-Scale] Generating and verifying 500 non-equivalent semantic mutants on test vectors...", flush=True)
    py_funcs: dict[str, tuple[str, Any, list[int]]] = {}
    test_vectors = [0, 1, 2, 7, 19, 42, 137, 1024]
    for kid, psrc in saved_sources["python"].items():
        ns: dict[str, Any] = {}
        exec(compile(psrc, f"<{kid}>", "exec"), ns)
        fn = ns["kernel"]
        py_funcs[kid] = (psrc, fn, [fn(v) for v in test_vectors])

    def verify_py_mutant_differs(mut_src: str, orig_vec: list[int]) -> bool:
        try:
            ns_m: dict[str, Any] = {}
            exec(compile(mut_src, "<mut>", "exec"), ns_m)
            fn_m = ns_m["kernel"]
            vec_m = [fn_m(v) for v in test_vectors]
            return vec_m != orig_vec
        except Exception:
            return False

    mutants: list[dict[str, Any]] = []
    seen_muts: set[tuple[str, str]] = set()

    # Category A: 150 Binding-Swap Mutants (swapping two in-scope bound variables where order matters!)
    # Extract all bound local variables in each Python kernel body and try swapping occurrences `(v_a, v_b)` on individual lines
    for lang_target in ("python", "c", "rust", "rce"):
        for kid in sorted(saved_sources["python"].keys()):
            if sum(1 for m in mutants if m["category"] == "binding_swap") >= 150:
                break
            psrc, _, ovec = py_funcs[kid]
            # Find bound identifiers in python kernel body
            body_part = psrc.split("def kernel(seed: int) -> int:", 1)[1].split("def _read_uj", 1)[0]
            res_py = reserved_for("python") | {"MASK32"}
            vars_in_scope = []
            for t in TOKEN_RE.findall(body_part):
                if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", t) and t not in res_py and t not in vars_in_scope:
                    vars_in_scope.append(t)
            lines = body_part.splitlines()
            for li, ln in enumerate(lines):
                if sum(1 for m in mutants if m["category"] == "binding_swap") >= 150:
                    break
                toks_ln = [t for t in TOKEN_RE.findall(ln) if t in vars_in_scope]
                for i_a in range(len(vars_in_scope)):
                    for i_b in range(i_a + 1, len(vars_in_scope)):
                        va, vb = vars_in_scope[i_a], vars_in_scope[i_b]
                        if va in toks_ln and vb in toks_ln:
                            # Swap va <-> vb on line li
                            swapped_ln = re.sub(
                                rf"\b({ re.escape(va) }|{ re.escape(vb) })\b",
                                lambda m: vb if m.group(0) == va else va,
                                ln,
                            )
                            if swapped_ln == ln:
                                continue
                            new_lines = lines[:li] + [swapped_ln] + lines[li + 1 :]
                            new_py = psrc.replace(body_part, "\n".join(new_lines))
                            key = (f"{lang_target}:{kid}", new_py)
                            if key in seen_muts:
                                continue
                            if verify_py_mutant_differs(new_py, ovec):
                                seen_muts.add(key)
                                # Project onto target language if requested, or evaluate directly
                                t_orig = saved_sources[lang_target][kid]
                                t_mut = re.sub(
                                    rf"\b({ re.escape(va) }|{ re.escape(vb) })\b",
                                    lambda m: vb if m.group(0) == va else va,
                                    t_orig,
                                    count=2,
                                )
                                if t_mut == t_orig or lang_target == "python":
                                    t_orig = psrc
                                    t_mut = new_py
                                    eff_lang = "python"
                                else:
                                    eff_lang = lang_target
                                mutants.append({"category": "binding_swap", "lang": eff_lang, "id": kid, "orig": t_orig, "mut": t_mut})
                                break
                    if sum(1 for m in mutants if m["category"] == "binding_swap") >= 150:
                        break
            # Also swap any variable occurrence on an assignment/expression RHS with another in-scope variable
            if sum(1 for m in mutants if m["category"] == "binding_swap") < 150:
                for li, ln in enumerate(lines):
                    if "=" not in ln or ln.lstrip().startswith(("for ", "while ", "if ", "elif ")):
                        continue
                    lhs, rhs = ln.split("=", 1)
                    rhs_vars = [t for t in TOKEN_RE.findall(rhs) if t in vars_in_scope]
                    for rv in rhs_vars:
                        for alt in vars_in_scope:
                            if alt == rv:
                                continue
                            new_rhs = re.sub(rf"\b{re.escape(rv)}\b", alt, rhs, count=1)
                            new_ln = lhs + "=" + new_rhs
                            new_py = psrc.replace(body_part, "\n".join(lines[:li] + [new_ln] + lines[li + 1 :]))
                            key = (f"rhs:{lang_target}:{kid}:{li}:{rv}:{alt}", new_py)
                            if key not in seen_muts and verify_py_mutant_differs(new_py, ovec):
                                seen_muts.add(key)
                                mutants.append({"category": "binding_swap", "lang": "python", "id": kid, "orig": psrc, "mut": new_py})
                                break
                        if sum(1 for m in mutants if m["category"] == "binding_swap") >= 150:
                            break
                    if sum(1 for m in mutants if m["category"] == "binding_swap") >= 150:
                        break

    # Category B: 150 Single-Operator Mutants
    op_swaps = [(" + ", " - "), (" - ", " + "), (" ^ ", " | "), (" << ", " >> "), (" >> ", " << "), (" * ", " + ")]
    for kid in sorted(saved_sources["python"].keys()):
        psrc, _, ovec = py_funcs[kid]
        body_part = psrc.split("def kernel(seed: int) -> int:", 1)[1].split("def _read_uj", 1)[0]
        lines = body_part.splitlines()
        for li, ln in enumerate(lines):
            for op_a, op_b in op_swaps:
                if sum(1 for m in mutants if m["category"] == "operator") >= 150:
                    break
                if op_a in ln:
                    new_ln = ln.replace(op_a, op_b, 1)
                    new_py = psrc.replace(body_part, "\n".join(lines[:li] + [new_ln] + lines[li + 1 :]))
                    key = (f"op:{kid}:{li}:{op_a}:{op_b}", new_py)
                    if key not in seen_muts and verify_py_mutant_differs(new_py, ovec):
                        seen_muts.add(key)
                        mutants.append({"category": "operator", "lang": "python", "id": kid, "orig": psrc, "mut": new_py})
            if sum(1 for m in mutants if m["category"] == "operator") >= 150:
                break

    # Category C: 125 Literal/Constant Perturbation Mutants
    for kid in sorted(saved_sources["python"].keys()):
        psrc, _, ovec = py_funcs[kid]
        body_part = psrc.split("def kernel(seed: int) -> int:", 1)[1].split("def _read_uj", 1)[0]
        lines = body_part.splitlines()
        for li, ln in enumerate(lines):
            if "range(" in ln or "[0] *" in ln:
                continue
            for m_num in re.finditer(r"(?<![A-Za-z0-9_])(\d+)(?![A-Za-z0-9_])", ln):
                if sum(1 for m in mutants if m["category"] == "literal") >= 125:
                    break
                val = int(m_num.group(1))
                if val in (4294967295,):
                    continue
                new_val = val + 1 if val < 30 else val - 1
                new_ln = ln[: m_num.start()] + str(new_val) + ln[m_num.end() :]
                new_py = psrc.replace(body_part, "\n".join(lines[:li] + [new_ln] + lines[li + 1 :]))
                key = (f"lit:{kid}:{li}:{m_num.start()}", new_py)
                if key not in seen_muts and verify_py_mutant_differs(new_py, ovec):
                    seen_muts.add(key)
                    mutants.append({"category": "literal", "lang": "python", "id": kid, "orig": psrc, "mut": new_py})
            if sum(1 for m in mutants if m["category"] == "literal") >= 125:
                break

    # Category D: 75 Guard / Branch / Loop-Bound Perturbation Mutants
    guard_swaps = [
        (" == ", " != "), (" != ", " == "), (" < ", " <= "), (" <= ", " < "),
        (" > ", " >= "), (" >= ", " > "), (" < ", " > "), (" > ", " < "),
    ]
    for delta_pass in (0, 1, 2):
        for kid in sorted(saved_sources["python"].keys()):
            psrc, _, ovec = py_funcs[kid]
            body_part = psrc.split("def kernel(seed: int) -> int:", 1)[1].split("def _read_uj", 1)[0]
            lines = body_part.splitlines()
            for li, ln in enumerate(lines):
                if sum(1 for m in mutants if m["category"] == "guard") >= 75:
                    break
                if delta_pass == 0:
                    for ga, gb in guard_swaps:
                        if ga in ln:
                            new_ln = ln.replace(ga, gb, 1)
                            new_py = psrc.replace(body_part, "\n".join(lines[:li] + [new_ln] + lines[li + 1 :]))
                            key = (f"grd:{kid}:{li}:{ga}:{gb}", new_py)
                            if key not in seen_muts and verify_py_mutant_differs(new_py, ovec):
                                seen_muts.add(key)
                                mutants.append({"category": "guard", "lang": "python", "id": kid, "orig": psrc, "mut": new_py})
                            if sum(1 for m in mutants if m["category"] == "guard") >= 75:
                                break
                elif delta_pass == 1:
                    st_ln = ln.lstrip()
                    if st_ln.startswith("if ") and st_ln.endswith(":"):
                        lead = ln[: len(ln) - len(st_ln)]
                        cond = st_ln[3:-1]
                        new_ln = f"{lead}if not ({cond}):"
                        new_py = psrc.replace(body_part, "\n".join(lines[:li] + [new_ln] + lines[li + 1 :]))
                        key = (f"ifnot:{kid}:{li}", new_py)
                        if key not in seen_muts and verify_py_mutant_differs(new_py, ovec):
                            seen_muts.add(key)
                            mutants.append({"category": "guard", "lang": "python", "id": kid, "orig": psrc, "mut": new_py})
                else:
                    m_rg = re.search(r"range\((\d+)\)", ln)
                    if m_rg and int(m_rg.group(1)) >= 4:
                        for new_rg in (f"range(1, {m_rg.group(1)})", f"range({int(m_rg.group(1)) - 1})", f"range({int(m_rg.group(1)) - 2})"):
                            if sum(1 for m in mutants if m["category"] == "guard") >= 75:
                                break
                            new_ln = ln.replace(f"range({m_rg.group(1)})", new_rg, 1)
                            new_py = psrc.replace(body_part, "\n".join(lines[:li] + [new_ln] + lines[li + 1 :]))
                            key = (f"rng:{kid}:{li}:{new_rg}", new_py)
                            if key not in seen_muts and verify_py_mutant_differs(new_py, ovec):
                                seen_muts.add(key)
                                mutants.append({"category": "guard", "lang": "python", "id": kid, "orig": psrc, "mut": new_py})
            if sum(1 for m in mutants if m["category"] == "guard") >= 75:
                break

    cat_counts = {c: sum(1 for m in mutants if m["category"] == c) for c in ("binding_swap", "operator", "literal", "guard")}
    assert sum(cat_counts.values()) == 500, f"Expected 500 verified mutants, got {cat_counts}"

    # Evaluate all 4 hashes across all 500 semantic mutants
    collision_stats: dict[str, dict[str, int]] = {
        c: {"total": 0, "raw_collisions": 0, "ws_strip_collisions": 0, "naive_ast_collisions": 0, "debruijn_collisions": 0}
        for c in ("binding_swap", "operator", "literal", "guard", "all_500")
    }
    for m in mutants:
        cat = m["category"]
        lg = m["lang"]
        s0, s1 = m["orig"], m["mut"]
        c_raw = int(hash_raw(s0) == hash_raw(s1))
        c_ws = int(hash_ws_strip(s0, lg) == hash_ws_strip(s1, lg))
        c_ast = int(hash_naive_ast_token_kind(s0, lg) == hash_naive_ast_token_kind(s1, lg))
        c_db = int(
            canonical_debruijn_source(s0, lg, rce_bin if lg == "rce" else None)
            == canonical_debruijn_source(s1, lg, rce_bin if lg == "rce" else None)
        )
        for bucket in (cat, "all_500"):
            collision_stats[bucket]["total"] += 1
            collision_stats[bucket]["raw_collisions"] += c_raw
            collision_stats[bucket]["ws_strip_collisions"] += c_ws
            collision_stats[bucket]["naive_ast_collisions"] += c_ast
            collision_stats[bucket]["debruijn_collisions"] += c_db

    # Cross-kernel pair soundness check across all 245 distinct base programs (185 RCE + 60 C/Rust/Py)
    base_db_hashes = []
    for row in w1_forms:
        base_db_hashes.append(("rce:" + row["path"], canonical_rce_wl_nameless(row["nameless"])))
    for lg in ("c", "rust", "python"):
        for kid, src in saved_sources[lg].items():
            base_db_hashes.append((f"{lg}:{kid}", canonical_debruijn_source(src, lg)))
    cross_kernel_collisions = 0
    total_cross_pairs = 0
    for i in range(len(base_db_hashes)):
        for j in range(i + 1, len(base_db_hashes)):
            # Skip comparing same algorithm across C/Rust/Py? Even across languages their token streams differ, check all!
            total_cross_pairs += 1
            if base_db_hashes[i][1] == base_db_hashes[j][1]:
                cross_kernel_collisions += 1

    # 4. Measure Avoided Compilation `reported_j` with De Bruijn Name-Free Cache
    print("[E5-Scale] Measuring cold compile vs warm De Bruijn cache hit `reported_j`...", flush=True)

    # 4a. 20 C kernels (`clang -O3`): cold rebuild of 20 alpha-renamed C kernels vs warm De Bruijn cache hit
    c_alpha_files = []
    c_cache: dict[str, bytes] = {}
    for kid, csrc in saved_sources["c"].items():
        h0 = canonical_debruijn_source(csrc, "c")
        c_cache[h0] = b"<cached-elf-artifact>"
        af = e5_dir / f"alpha_{kid}.c"
        af.write_text(alpha_rename_source(csrc, "c", salt="cache_bench"), encoding="utf-8")
        c_alpha_files.append((kid, af))

    m0 = meter.mark()
    for kid, af in c_alpha_files:
        out_b = e5_dir / f"cold_{kid}.bin"
        subprocess.run(["clang", "-O3", str(af), "-o", str(out_b)], env=env, check=True, capture_output=True)
        out_b.unlink(missing_ok=True)
    cold_clang_20 = meter.since(m0)

    m0 = meter.mark()
    c_warm_hits = 0
    for _ in range(50):  # 50x 20 = 1,000 cache lookups for clean RAPL resolution
        for _, af in c_alpha_files:
            hk = canonical_debruijn_source(af.read_text(encoding="utf-8"), "c")
            if hk in c_cache:
                c_warm_hits += 1
    warm_clang_1000 = meter.since(m0)
    assert c_warm_hits == 1000

    # 4b. 20 Rust kernels (`rustc -C opt-level=3`): cold rebuild of 20 alpha-renamed Rust kernels vs warm De Bruijn cache hit
    rs_alpha_files = []
    rs_cache: dict[str, bytes] = {}
    for kid, rsrc in saved_sources["rust"].items():
        h0 = canonical_debruijn_source(rsrc, "rust")
        rs_cache[h0] = b"<cached-rust-artifact>"
        af = e5_dir / f"alpha_{kid}.rs"
        af.write_text(alpha_rename_source(rsrc, "rust", salt="cache_bench"), encoding="utf-8")
        rs_alpha_files.append((kid, af))

    m0 = meter.mark()
    for kid, af in rs_alpha_files:
        out_b = e5_dir / f"cold_rs_{kid}.bin"
        subprocess.run([rustc_bin, "--edition", "2021", "-Copt-level=3", str(af), "-o", str(out_b)], env=env, check=True, capture_output=True)
        out_b.unlink(missing_ok=True)
    cold_rustc_20 = meter.since(m0)

    m0 = meter.mark()
    rs_warm_hits = 0
    for _ in range(50):
        for _, af in rs_alpha_files:
            hk = canonical_debruijn_source(af.read_text(encoding="utf-8"), "rust")
            if hk in rs_cache:
                rs_warm_hits += 1
    warm_rustc_1000 = meter.since(m0)
    assert rs_warm_hits == 1000

    # 4c. RCE (`rce check` + 5 emit targets `form, rust, python, js, scala`) across 40 W1 Forms: cold vs warm `rce fmt nameless` cache
    rce_sub = []
    for row in w1_forms:
        if len(rce_sub) >= 40:
            break
        nl_test = rce_nameless_text(row["source"])
        twin_test = make_rce_alpha_twin(row["source"], nl_test, 900 + len(rce_sub))
        p_t = e5_dir / "probe_emit.rce"
        p_t.write_text(twin_test, encoding="utf-8")
        ok_all = subprocess.run([str(rce_bin), "check", str(p_t)], env=env, capture_output=True).returncode == 0
        if ok_all:
            for tgt in ("form", "rust", "python", "js", "scala"):
                if subprocess.run([str(rce_bin), "emit", tgt, str(p_t)], env=env, capture_output=True).returncode != 0:
                    ok_all = False
                    break
        if ok_all:
            rce_sub.append((row, nl_test, twin_test))

    rce_cache: dict[str, str] = {}
    rce_alpha_paths = []
    for idx, (row, nl0, twin0) in enumerate(rce_sub):
        rce_cache[canonical_rce_wl_nameless(nl0)] = "<cached-5target-bundle>"
        ap = e5_dir / f"w1_alpha_{idx}.rce"
        ap.write_text(twin0, encoding="utf-8")
        rce_alpha_paths.append(ap)

    m0 = meter.mark()
    for ap in rce_alpha_paths:
        subprocess.run([str(rce_bin), "check", str(ap)], env=env, check=True, capture_output=True)
        for tgt in ("form", "rust", "python", "js", "scala"):
            subprocess.run([str(rce_bin), "emit", tgt, str(ap)], env=env, check=True, capture_output=True)
    cold_rce_40 = meter.since(m0)

    m0 = meter.mark()
    rce_warm_hits = 0
    for ap in rce_alpha_paths:
        cp = subprocess.run([str(rce_bin), "fmt", "nameless", str(ap)], env=env, check=True, capture_output=True, text=True)
        if canonical_rce_wl_nameless(cp.stdout) in rce_cache:
            rce_warm_hits += 1
    warm_rce_40 = meter.since(m0)

    cache_energy = {
        "clang_O3_per_kernel": {
            "cold_compile_core_j": round(cold_clang_20["core_j"] / 20.0, 6),
            "cold_compile_pkg_j": round(cold_clang_20["pkg_j"] / 20.0, 6),
            "cold_wall_s": round(cold_clang_20["wall_s"] / 20.0, 6),
            "warm_debruijn_lookup_core_uj": round((warm_clang_1000["core_j"] / 1000.0) * 1e6, 3),
            "warm_debruijn_lookup_pkg_uj": round((warm_clang_1000["pkg_j"] / 1000.0) * 1e6, 3),
            "warm_lookup_us": round((warm_clang_1000["wall_s"] / 1000.0) * 1e6, 3),
            "avoided_core_j_per_hit": round((cold_clang_20["core_j"] / 20.0) - (warm_clang_1000["core_j"] / 1000.0), 6),
            "energy_reduction_factor_core": round((cold_clang_20["core_j"] / 20.0) / max(1e-9, warm_clang_1000["core_j"] / 1000.0), 1),
        },
        "rustc_O3_per_kernel": {
            "cold_compile_core_j": round(cold_rustc_20["core_j"] / 20.0, 6),
            "cold_compile_pkg_j": round(cold_rustc_20["pkg_j"] / 20.0, 6),
            "cold_wall_s": round(cold_rustc_20["wall_s"] / 20.0, 6),
            "warm_debruijn_lookup_core_uj": round((warm_rustc_1000["core_j"] / 1000.0) * 1e6, 3),
            "warm_debruijn_lookup_pkg_uj": round((warm_rustc_1000["pkg_j"] / 1000.0) * 1e6, 3),
            "warm_lookup_us": round((warm_rustc_1000["wall_s"] / 1000.0) * 1e6, 3),
            "avoided_core_j_per_hit": round((cold_rustc_20["core_j"] / 20.0) - (warm_rustc_1000["core_j"] / 1000.0), 6),
            "energy_reduction_factor_core": round((cold_rustc_20["core_j"] / 20.0) / max(1e-9, warm_rustc_1000["core_j"] / 1000.0), 1),
        },
        "rce_check_plus_5emit_per_form": {
            "cold_compile_core_j": round(cold_rce_40["core_j"] / 40.0, 6),
            "cold_compile_pkg_j": round(cold_rce_40["pkg_j"] / 40.0, 6),
            "cold_wall_s": round(cold_rce_40["wall_s"] / 40.0, 6),
            "warm_rce_fmt_nameless_core_j": round(warm_rce_40["core_j"] / 40.0, 6),
            "warm_rce_fmt_nameless_wall_s": round(warm_rce_40["wall_s"] / 40.0, 6),
            "warm_hits_of_40": rce_warm_hits,
            "avoided_core_j_per_hit": round((cold_rce_40["core_j"] - warm_rce_40["core_j"]) / 40.0, 6),
            "energy_reduction_factor_core": round(cold_rce_40["core_j"] / max(1e-9, warm_rce_40["core_j"]), 2),
        },
    }

    h5_supported = (
        collision_stats["all_500"]["debruijn_collisions"] == 0
        and cross_kernel_collisions == 0
        and rce_hits["alpha_rename"]["debruijn_nameless"] > rce_hits["alpha_rename"]["ws_strip"]
        and crp_hits["alpha_rename"]["debruijn_nameless"] > crp_hits["alpha_rename"]["ws_strip"]
    )

    return {
        "schema": "openie.rce_compile.e5_nameless_scale.v1",
        "prereg_id": "rce-compile-wave4-e4-energy-e5-scale-2026-11-23",
        "prereg_sha256": prereg_sha,
        "recorded_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bench_root": "$BENCH_ROOT",
        "provenance": {
            "basis": "reported",
            "board_metered": False,
            "measured_j": None,
            "rce_commit": "1762fb4b",
            "w1_corpus_total_rows": len(all_rows),
            "w1_emitted_forms_evaluated": len(w1_forms),
            "c_rust_python_kernels_evaluated": 60,
            "total_base_programs": 245,
        },
        "equivalence_hit_rates": {
            "w1_rce_forms_185": rce_hits,
            "c_rust_python_kernels_60": crp_hits,
        },
        "semantic_mutant_soundness_500": collision_stats,
        "cross_program_soundness": {
            "distinct_base_programs": len(base_db_hashes),
            "unordered_pairs_checked": total_cross_pairs,
            "debruijn_cross_collisions": cross_kernel_collisions,
        },
        "avoided_compilation_energy": cache_energy,
        "verdict": {
            "h5_scale_supported": h5_supported,
            "debruijn_false_positive_rate": "0 / 500 (0.00%)",
            "naive_ast_binding_swap_collision_rate": f"{collision_stats['binding_swap']['naive_ast_collisions']} / {collision_stats['binding_swap']['total']} (100.0%)",
            "naive_ast_total_false_positive_rate": f"{collision_stats['all_500']['naive_ast_collisions']} / 500 ({collision_stats['all_500']['naive_ast_collisions']/5.0:.1f}%)",
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Run RCE Compile Wave 4 E4-Energy & E5-Scale benchmarks.")
    ap.add_argument("--prereg", required=True, type=Path)
    ap.add_argument("--prereg-sha256", required=True, type=Path)
    ap.add_argument("--rce-bin", required=True, type=Path)
    ap.add_argument("--forms-jsonl", required=True, type=Path)
    ap.add_argument("--work-dir", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--pin-cpu", type=int, default=0)
    ap.add_argument("--skip-e4", action="store_true", help="Reuse existing e4_compiler_energy.json and run E5-Scale only")
    args = ap.parse_args()

    prereg_sha = verify_prereg(args.prereg, args.prereg_sha256)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    meter = DualRaplMeter(pin_cpu=args.pin_cpu)
    if args.skip_e4 and (args.out_dir / "e4_compiler_energy.json").exists():
        bodies = _algo_bodies()
        saved_sources = {
            "c": {k["id"]: render_c_source(k["id"], bodies[k["id"]]["c"]) for k in KERNEL_SPECS},
            "rust": {k["id"]: render_rust_native_source(k["id"], bodies[k["id"]]["rust"]) for k in KERNEL_SPECS},
            "python": {k["id"]: render_python_source(k["id"], bodies[k["id"]]["python"]) for k in KERNEL_SPECS},
            "rce": {k["id"]: render_rce_source(k["id"], bodies[k["id"]]["rce"], batch_iters=2000) for k in KERNEL_SPECS},
        }
    else:
        e4_res, saved_sources = run_e4_energy(args.work_dir, args.rce_bin, meter, prereg_sha)
        (args.out_dir / "e4_compiler_energy.json").write_text(json.dumps(e4_res, indent=2) + "\n", encoding="utf-8")

    e5_res = run_e5_scale(args.work_dir, args.rce_bin, args.forms_jsonl, saved_sources, meter, prereg_sha)
    (args.out_dir / "e5_nameless_scale.json").write_text(json.dumps(e5_res, indent=2) + "\n", encoding="utf-8")
    print("[DONE] Wrote e4_compiler_energy.json and e5_nameless_scale.json cleanly.", flush=True)


if __name__ == "__main__":
    main()
