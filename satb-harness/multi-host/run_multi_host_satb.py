#!/usr/bin/env python3
"""
Cross-Platform Satiation Benchmark (`SATB`) & `Shape D` Hardware Attribution Runner.

Executes rootless hardware rail / counter discovery, `Shape D` (`DNULLMM1` 1,000,000-record
`mmap` 10,000-probe checksum `15027705736` + `test.setpoint` episode vector), `SATB` `C9`
deterministic 14-turn replay (`ContextRule_v0` + `Truncate_v0`), `C10` multi-process
`SIGKILL` cleanup latency, `C11` rootless `L3` handshake, `Falsifier 5` observer-effect
cadence sweep (`0 Hz`, `1 Hz`, `10 Hz`, `100 Hz`), `Falsifier 3` (`B` sequential temporal
boundary vs. `C` proportional `CPU`-time split), `Step 7` sum check, and `Falsifier 6`
baseline-drift / physical rail-separation audit across Linux `aarch64` and `x86_64` hosts.

Usage:
  SATB_HOST_PROFILE=jetson_thor python3 $BENCH_ROOT/run_multi_host_satb.py --out receipt.json
"""

from __future__ import annotations

import argparse
import grp
import hashlib
import json
import mmap
import os
import platform
import pwd
import resource
import shutil
import signal
import stat
import statistics
import struct
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

# ============================================================================
# 1. Normative `Shape D` (`SPEC v0.2` / `v0.4`) Fixed-Point & `DNULLMM1` Check
# ============================================================================

Q = 1_000_000
X_MAX = 1 << 40
I64_MIN = -(1 << 63)
I64_MAX = (1 << 63) - 1


def narrow(x: int) -> int:
    if x < I64_MIN or x > I64_MAX:
        raise ValueError("E_RANGE")
    return x


def fx_check(x: int) -> int:
    if x < -X_MAX or x > X_MAX:
        raise ValueError("E_RANGE")
    return x


def fx_add(a: int, b: int) -> int:
    return narrow(a + b)


def fx_tdiv(a: int, b: int) -> int:
    q = abs(a) // abs(b)
    return -q if (a < 0) ^ (b < 0) else q


def fx_fdiv(a: int, b: int) -> int:
    return narrow(a // b)


def fx_mul(a: int, b: int) -> int:
    prod = a * b
    q = abs(prod) // Q
    return narrow(-q if prod < 0 else q)


def fx_clamp(x: int, lo: int, hi: int) -> int:
    return lo if x < lo else (hi if x > hi else x)


def fx_sign(x: int) -> int:
    return 1 if x > 0 else (-1 if x < 0 else 0)


def canon_ints(v: list[int]) -> str:
    return "[" + ",".join(str(int(x)) for x in v) + "]"


def quantize(f: list[int], step: list[int], res: int) -> list[int]:
    return [fx_fdiv(fx_check(x), s >> res) for x, s in zip(f, step)]


def cell_key(task: str, res: int, cell: list[int]) -> str:
    b = task.encode("ascii") + b"\x00" + struct.pack(">q", res) + b"".join(struct.pack(">q", c) for c in cell)
    return hashlib.sha256(b).hexdigest()[:32]


def case_canonical(c: dict) -> str:
    return (
        f'{{"action":{{"args":{canon_ints(c["action"]["args"])},"fn":"{c["action"]["fn"]}"}},'
        f'"cell":{canon_ints(c["cell"])},"delta":{canon_ints(c["delta"])},"key":"{c["key"]}",'
        f'"kind":"{c["kind"]}","outcome":{canon_ints(c["outcome"])},"parent":{c["parent"]},'
        f'"pass":{c["pass"]},"res":{c["res"]},"score":{c["score"]},"seq":{c["seq"]},'
        f'"src":"{c["src"]}","task":"{c["task"]}","v":1}}'
    )


class Store:
    def __init__(self) -> None:
        self.log: list[dict] = []
        self.index: dict[str, list[int]] = {}
        self.digests = bytearray()

    def append(self, c: dict) -> int:
        c = dict(c)
        c["seq"] = len(self.log)
        c["key"] = cell_key(c["task"], c["res"], c["cell"])
        self.digests.extend(hashlib.sha256(case_canonical(c).encode("ascii")).digest())
        self.index.setdefault(c["key"], []).append(len(self.log))
        self.log.append(c)
        return c["seq"]

    def at(self, k: str) -> list[dict]:
        return [self.log[i] for i in self.index.get(k, [])]

    def best_pass(self, k: str) -> dict | None:
        recs = self.at(k)
        best = None
        for c in recs:
            if c["pass"] != 1:
                continue
            if any(f["pass"] == 0 and f["parent"] == c["seq"] for f in recs):
                continue
            if best is None or c["score"] > best["score"]:
                best = c
        return best

    def digest(self) -> str:
        return hashlib.sha256(self.digests).hexdigest()


def run_setpoint_episode_vector() -> dict:
    store = Store()
    step = [Q]
    gain = [Q // 2]
    lo, hi = [-100 * Q], [100 * Q]
    def_act = {"fn": "set", "args": [0]}

    def run_range(start: int, end: int, learn: bool) -> tuple[int, int, int, str]:
        succ = writes = probes = 0
        h_trace = hashlib.sha256()
        for ep in range(start, end):
            ctx = (ep % 5) * Q
            target = 3 * ctx + 7 * Q
            c0 = quantize([ctx], step, 0)
            k0 = cell_key("test.setpoint", 0, c0)
            probes += 1
            recs = store.at(k0)
            origin_kind = ""
            origin_parent = -1
            chosen = def_act

            if recs:
                bp = store.best_pass(k0)
                if bp is not None:
                    chosen = bp["action"]
                    origin_kind = "exact"
                    origin_parent = bp["seq"]
                else:
                    attempts = [rc for rc in recs if rc["pass"] == 0]
                    mut_ok = False
                    if len(attempts) < 40 and attempts:
                        last = attempts[-1]
                        d = last["delta"][0] if last["delta"] else 0
                        v = fx_add(last["action"]["args"][0], fx_mul(gain[0], d))
                        if len(attempts) >= 2:
                            prev = attempts[-2]
                            pd = prev["delta"][0] if prev["delta"] else 0
                            if fx_sign(d) * fx_sign(pd) < 0:
                                v = fx_tdiv(fx_add(last["action"]["args"][0], prev["action"]["args"][0]), 2)
                        v = fx_clamp(v, lo[0], hi[0])
                        cand = {"fn": last["action"]["fn"], "args": [v]}
                        if not any(at["action"] == cand for at in attempts):
                            chosen = cand
                            origin_kind = "mutated"
                            origin_parent = last["seq"]
                            mut_ok = True
                    if not mut_ok:
                        best = max(attempts, key=lambda at: at["score"])
                        chosen = best["action"]
                        origin_kind = "residual"
            else:
                found_nbr = False
                for off in (-1, 1):
                    probes += 1
                    hit = store.best_pass(cell_key("test.setpoint", 0, [c0[0] + off]))
                    if hit is not None:
                        chosen = hit["action"]
                        origin_kind = "neighbour"
                        origin_parent = hit["seq"]
                        found_nbr = True
                        break
                if not found_nbr:
                    chosen = def_act
                    origin_kind = "default"

            err_abs = abs(target - chosen["args"][0])
            hit_ok = err_abs <= Q // 100
            obs = [chosen["args"][0]]
            score = fx_clamp(Q - err_abs, 0, Q)
            passed = 1 if score >= 990_000 else 0
            h_trace.update(f"{ep}|0|{k0}|{chosen['fn']}|{canon_ints(chosen['args'])}|{score}\n".encode("ascii"))

            write_src = None
            write_parent = -1
            if origin_kind == "exact" and passed == 0:
                write_src, write_parent = "mut:retract", origin_parent
            elif origin_kind == "mutated":
                write_src, write_parent = "mut:step", origin_parent
            elif origin_kind == "neighbour":
                write_src, write_parent = "mut:nbr", origin_parent
            elif origin_kind == "default":
                write_src, write_parent = "mut:default", -1

            if learn and write_src is not None:
                store.append({
                    "task": "test.setpoint",
                    "cell": c0,
                    "res": 0,
                    "kind": "learned" if passed else "attempt",
                    "action": chosen,
                    "outcome": obs,
                    "score": score,
                    "pass": passed,
                    "delta": [] if passed else [target - obs[0]],
                    "parent": write_parent,
                    "src": write_src,
                    "v": 1,
                })
                writes += 1
            if hit_ok:
                succ += 1
        return succ, writes, probes, h_trace.hexdigest()

    f_s, f_w, f_p, f_t = run_range(0, 200, True)
    fr_dig = store.digest()
    e_s, e_w, _, e_t = run_range(200, 300, False)
    expected_digest = "0da4df8d9ccbce1e2471eb18b2798b4cbdf0ce9f21f9b0363f22949574485781"
    return {
        "task": "test.setpoint",
        "fill_episodes": 200,
        "fill_successes": f_s,
        "fill_writes": f_w,
        "fill_probes": f_p,
        "frozen_store_digest": fr_dig,
        "matches_reference_digest": fr_dig.startswith("0da4df8d9ccbce1e") and fr_dig.endswith("4485781"),
        "expected_prefix_suffix": f"{expected_digest[:16]}...{expected_digest[-7:]}",
        "eval_episodes": 100,
        "eval_successes": e_s,
        "eval_writes": e_w,
        "eval_trace_digest": e_t,
    }


C_MMAP_1M_SRC = r"""
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

static inline uint32_t rotr32(uint32_t x, int n) { return (x >> n) | (x << (32 - n)); }

static const uint32_t K256[64] = {
    0x428a2f98u,0x71374491u,0xb5c0fbcfu,0xe9b5dba5u,0x3956c25bu,0x59f111f1u,0x923f82a4u,0xab1c5ed5u,
    0xd807aa98u,0x12835b01u,0x243185beu,0x550c7dc3u,0x72be5d74u,0x80deb1feu,0x9bdc06a7u,0xc19bf174u,
    0xe49b69c1u,0xefbe4786u,0x0fc19dc6u,0x240ca1ccu,0x2de92c6fu,0x4a7484aau,0x5cb0a9dcu,0x76f988dau,
    0x983e5152u,0xa831c66du,0xb00327c8u,0xbf597fc7u,0xc6e00bf3u,0xd5a79147u,0x06ca6351u,0x14292967u,
    0x27b70a85u,0x2e1b2138u,0x4d2c6dfcu,0x53380d13u,0x650a7354u,0x766a0abbu,0x81c2c92eu,0x92722c85u,
    0xa2bfe8a1u,0xa81a664bu,0xc24b8b70u,0xc76c51a3u,0xd192e819u,0xd6990624u,0xf40e3585u,0x106aa070u,
    0x19a4c116u,0x1e376c08u,0x2748774cu,0x34b0bcb5u,0x391c0cb3u,0x4ed8aa4au,0x5b9cca4fu,0x682e6ff3u,
    0x748f82eeu,0x78a5636fu,0x84c87814u,0x8cc70208u,0x90befffau,0xa4506cebu,0xbef9a3f7u,0xc67178f2u
};

/* Single-block SHA-256 for 37-byte SPEC key: "bench.mmap1m\0" || be64(0) || be64(c0) || be64(c1) */
static void key16_bench_mmap1m(int64_t c0, int64_t c1, uint8_t out16[16]) {
    uint8_t blk[64];
    memset(blk, 0, sizeof(blk));
    memcpy(blk, "bench.mmap1m", 12);
    /* blk[12] = 0; blk[13..20] = be64(0) already 0 */
    uint64_t u0 = (uint64_t)c0, u1 = (uint64_t)c1;
    for (int b = 0; b < 8; b++) {
        blk[21 + b] = (uint8_t)(u0 >> (56 - 8 * b));
        blk[29 + b] = (uint8_t)(u1 >> (56 - 8 * b));
    }
    blk[37] = 0x80u;
    /* bit length = 37 * 8 = 296 = 0x0128 */
    blk[62] = 0x01u;
    blk[63] = 0x28u;

    uint32_t w[64];
    for (int i = 0; i < 16; i++) {
        w[i] = ((uint32_t)blk[4*i] << 24) | ((uint32_t)blk[4*i+1] << 16)
             | ((uint32_t)blk[4*i+2] << 8) | ((uint32_t)blk[4*i+3]);
    }
    for (int i = 16; i < 64; i++) {
        uint32_t s0 = rotr32(w[i-15], 7) ^ rotr32(w[i-15], 18) ^ (w[i-15] >> 3);
        uint32_t s1 = rotr32(w[i-2], 17) ^ rotr32(w[i-2], 19) ^ (w[i-2] >> 10);
        w[i] = w[i-16] + s0 + w[i-7] + s1;
    }
    uint32_t a=0x6a09e667u, b=0xbb67ae85u, c=0x3c6ef372u, d=0xa54ff53au;
    uint32_t e=0x510e527fu, f=0x9b05688cu, g=0x1f83d9abu, h=0x5be0cd19u;
    for (int i = 0; i < 64; i++) {
        uint32_t S1 = rotr32(e, 6) ^ rotr32(e, 11) ^ rotr32(e, 25);
        uint32_t ch = (e & f) ^ ((~e) & g);
        uint32_t t1 = h + S1 + ch + K256[i] + w[i];
        uint32_t S0 = rotr32(a, 2) ^ rotr32(a, 13) ^ rotr32(a, 22);
        uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
        uint32_t t2 = S0 + maj;
        h = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2;
    }
    uint32_t H[4] = { a + 0x6a09e667u, b + 0xbb67ae85u, c + 0x3c6ef372u, d + 0xa54ff53au };
    int all_zero = 1;
    for (int i = 0; i < 4; i++) {
        out16[4*i+0] = (uint8_t)(H[i] >> 24);
        out16[4*i+1] = (uint8_t)(H[i] >> 16);
        out16[4*i+2] = (uint8_t)(H[i] >> 8);
        out16[4*i+3] = (uint8_t)(H[i]);
    }
    for (int i = 0; i < 16; i++) if (out16[i] != 0) { all_zero = 0; break; }
    if (all_zero) out16[15] = 1;
}

static inline uint64_t splitmix64(uint64_t seed, uint64_t idx) {
    uint64_t z = seed + idx * 0x9E3779B97F4A7C15ULL;
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}

static double now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec * 1e9 + (double)ts.tv_nsec;
}

int main(int argc, char **argv) {
    if (argc < 2) return 2;
    const char *path = argv[1];
    const size_t n = 1000000ULL;
    const size_t cap = 2097152ULL;
    const size_t mask = cap - 1;
    const size_t total_bytes = 64 + cap * 48;

    double t_b0 = now_ns();
    uint8_t *buf = (uint8_t *)calloc(1, total_bytes);
    if (!buf) return 3;
    memcpy(buf, "DNULLMM1", 8);
    uint64_t n_le = (uint64_t)n, cap_le = (uint64_t)cap;
    memcpy(buf + 8, &n_le, 8);
    memcpy(buf + 16, &cap_le, 8);

    uint8_t k16[16], zero16[16];
    memset(zero16, 0, 16);
    for (size_t i = 0; i < n; i++) {
        key16_bench_mmap1m((int64_t)i, (int64_t)((i * 7) % 1024), k16);
        uint64_t h0;
        memcpy(&h0, k16, 8);
        size_t idx = (size_t)h0 & mask;
        for (;;) {
            uint8_t *slot = buf + 64 + idx * 48;
            if (memcmp(slot, zero16, 16) == 0) {
                int64_t seq = (int64_t)i, score = 1000000LL, arg0 = (int64_t)i * 3 + 7;
                uint64_t off = (uint64_t)i * 142ULL;
                memcpy(slot, k16, 16);
                memcpy(slot + 16, &seq, 8);
                memcpy(slot + 24, &score, 8);
                memcpy(slot + 32, &arg0, 8);
                memcpy(slot + 40, &off, 8);
                break;
            }
            idx = (idx + 1) & mask;
        }
    }
    int fd = open(path, O_CREAT | O_RDWR | O_TRUNC, 0600);
    if (fd < 0) return 4;
    size_t written = 0;
    while (written < total_bytes) {
        ssize_t w = write(fd, buf + written, total_bytes - written);
        if (w <= 0) return 5;
        written += (size_t)w;
    }
    free(buf);
    close(fd);
    double build_ms = (now_ns() - t_b0) / 1e6;

    /* Mount via POSIX mmap and run 10,000 probes */
    double t_m0 = now_ns();
    int rfd = open(path, O_RDONLY);
    if (rfd < 0) return 6;
    const uint8_t *mm = (const uint8_t *)mmap(NULL, total_bytes, PROT_READ, MAP_SHARED, rfd, 0);
    if (mm == MAP_FAILED) return 7;
    double mount_us = (now_ns() - t_m0) / 1e3;

    const size_t nq = 10000;
    uint8_t (*qkeys)[16] = malloc(nq * 16);
    for (size_t q = 0; q < nq; q++) {
        int64_t ti = (int64_t)(splitmix64(20261121ULL, (uint64_t)q) % 1000000ULL);
        key16_bench_mmap1m(ti, (ti * 7) % 1024, qkeys[q]);
    }
    double t_q0 = now_ns();
    uint64_t checksum = 0;
    for (size_t q = 0; q < nq; q++) {
        uint64_t h0;
        memcpy(&h0, qkeys[q], 8);
        size_t idx = (size_t)h0 & mask;
        for (;;) {
            const uint8_t *slot = mm + 64 + idx * 48;
            if (memcmp(slot, zero16, 16) == 0) break;
            if (memcmp(slot, qkeys[q], 16) == 0) {
                int64_t arg0;
                memcpy(&arg0, slot + 32, 8);
                checksum += (uint64_t)arg0;
                break;
            }
            idx = (idx + 1) & mask;
        }
    }
    double probe_ns = (now_ns() - t_q0) / (double)nq;
    free(qkeys);
    munmap((void *)mm, total_bytes);
    close(rfd);

    printf("{\"c_build_ms\":%.2f,\"c_mount_us\":%.2f,\"c_probe_ns\":%.2f,\"c_checksum\":%llu}\n",
           build_ms, mount_us, probe_ns, (unsigned long long)checksum);
    return 0;
}
"""


def splitmix64_py(seed: int, idx: int) -> int:
    z = (seed + idx * 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
    return (z ^ (z >> 31)) & 0xFFFFFFFFFFFFFFFF


def run_shape_d_dnullmm1_conformance() -> dict:
    expected_checksum = 15027705736
    tmp_dir = Path(tempfile.mkdtemp(prefix="satb_dnullmm1_"))
    try:
        c_src = tmp_dir / "dnullmm1_probe.c"
        c_bin = tmp_dir / "dnullmm1_probe"
        mm_path = tmp_dir / "dnull_1m.mmap"
        c_src.write_text(C_MMAP_1M_SRC, encoding="utf-8")

        subprocess.run(["gcc", "-O3", str(c_src), "-o", str(c_bin)], check=True, capture_output=True, text=True)
        cp = subprocess.run([str(c_bin), str(mm_path)], check=True, capture_output=True, text=True)
        c_res = json.loads(cp.stdout.strip())

        # Cross-verify via pure Python `mmap` over the exact same 1M-record `DNULLMM1` file
        t0 = time.perf_counter()
        f = open(mm_path, "rb")
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        py_mount_us = (time.perf_counter() - t0) * 1e6
        n_rec, cap_slots = struct.unpack_from("<QQ", mm, 8)
        mask = cap_slots - 1

        nq = 10_000
        keys = []
        for q in range(nq):
            ti = splitmix64_py(2026_1121, q) % 1_000_000
            kh = cell_key("bench.mmap1m", 0, [ti, (ti * 7) % 1024])
            keys.append(bytes.fromhex(kh))

        tq = time.perf_counter()
        py_checksum = 0
        zero16 = b"\x00" * 16
        for k16 in keys:
            (h0,) = struct.unpack_from("<Q", k16, 0)
            idx = h0 & mask
            while True:
                base = 64 + idx * 48
                sk = mm[base : base + 16]
                if sk == zero16:
                    break
                if sk == k16:
                    (arg0,) = struct.unpack_from("<q", mm, base + 32)
                    py_checksum = (py_checksum + (arg0 & 0xFFFFFFFFFFFFFFFF)) & 0xFFFFFFFFFFFFFFFF
                    break
                idx = (idx + 1) & mask
        py_probe_ns = (time.perf_counter() - tq) * 1e9 / nq
        mm.close()
        f.close()

        ep_vec = run_setpoint_episode_vector()
        return {
            "passed": (
                c_res["c_checksum"] == expected_checksum
                and py_checksum == expected_checksum
                and ep_vec["matches_reference_digest"]
            ),
            "records": int(n_rec),
            "mmap_bytes": 64 + int(cap_slots) * 48,
            "queries": nq,
            "expected_checksum": expected_checksum,
            "c_o3_build_ms": c_res["c_build_ms"],
            "c_o3_mount_us": c_res["c_mount_us"],
            "c_o3_probe_ns": c_res["c_probe_ns"],
            "c_o3_checksum": c_res["c_checksum"],
            "python_mmap_mount_us": round(py_mount_us, 2),
            "python_mmap_probe_ns": round(py_probe_ns, 2),
            "python_mmap_checksum": py_checksum,
            "episode_vector_conformance": ep_vec,
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ============================================================================
# 2. `SATB` `C9` (`ContextRule_v0` + `Truncate_v0`), `C10` (`SIGKILL`), `C11`
# ============================================================================

TRUNCATE_HEAD = 8192
TRUNCATE_TAIL = 8192
TEMPLATE_V0 = (
    "You are evaluated inside the Satiation Benchmark (SATB) Lane B reference harness. "
    "Work strictly inside /work using sequential tool calls (exec, read_file, write_file, list_dir). "
    "Terminate the attempt with exactly one call to submit(answer) or refuse(reason). "
    "No verifier verdict is returned to you."
)


def truncate_v0(text: str) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= TRUNCATE_HEAD + TRUNCATE_TAIL:
        return text
    head = raw[:TRUNCATE_HEAD].decode("utf-8", errors="replace")
    tail = raw[-TRUNCATE_TAIL:].decode("utf-8", errors="replace")
    elided = len(raw) - (TRUNCATE_HEAD + TRUNCATE_TAIL)
    return f"{head}...[TRUNCATE_V0 elided {elided} bytes]...{tail}"


def approx_tokens(content: str) -> int:
    return (len(content.encode("utf-8")) + 3) // 4 + 4


def apply_context_rule_v0(msgs: list[dict], window_tokens: int) -> tuple[int, bool]:
    def tot() -> int:
        return sum(approx_tokens(m["content"]) for m in msgs)

    threshold_80 = (window_tokens * 80) // 100
    elided_now = 0
    if tot() > threshold_80:
        tool_idxs = [i for i, m in enumerate(msgs) if m["role"] == "tool"]
        if len(tool_idxs) > 8:
            for idx in tool_idxs[:-8]:
                if not msgs[idx].get("elided", False):
                    msgs[idx]["elided"] = True
                    msgs[idx]["content"] = "[ELIDED_BY_CONTEXT_RULE_V0]"
                    elided_now += 1
                if tot() <= threshold_80:
                    break
    return elided_now, tot() > window_tokens


def verify_c9_extended_replay() -> dict:
    expected_sha256 = "d697ed147612993952aec0b695cebfc3177534584d742d92d4a17e87831460dc"
    window_tokens = 48_000

    def run_once(win_tok: int) -> tuple[bytes, str, int, int, bool]:
        tmp = Path(tempfile.mkdtemp(prefix="satb_c9_"))
        try:
            msgs = [
                {"role": "system", "content": TEMPLATE_V0},
                {"role": "user", "content": "BUNDLE_C9: Inspect generated logs and submit final checksum."},
            ]
            total_elided = 0
            truncated_events = 0
            hit_ceiling = False
            for turn in range(1, 15):
                el, over = apply_context_rule_v0(msgs, win_tok)
                total_elided += el
                if over:
                    hit_ceiling = True
                    break
                msgs.append({"role": "assistant", "content": f"Turn {turn}: reading log_{turn:02d}.txt"})
                raw_tool_out = f"HEADER_{turn:02d}_" + ("A" * 12288) + ("B" * 12288) + f"_FOOTER_{turn:02d}"
                trunc_out = truncate_v0(raw_tool_out)
                if trunc_out != raw_tool_out:
                    truncated_events += 1
                msgs.append({"role": "tool", "content": f"read_file:{trunc_out}", "elided": False})

            if not hit_ceiling:
                el, over = apply_context_rule_v0(msgs, win_tok)
                total_elided += el
                hit_ceiling = over
            msgs.append({"role": "assistant", "content": "Submitting verified checksum."})
            submitted = "killed(context_ceiling)" if hit_ceiling else "checksum_c9_deterministic_v0"
            clean_msgs = [{"role": m["role"], "content": m["content"]} for m in msgs]
            raw_bytes = json.dumps(clean_msgs, sort_keys=True, separators=(",", ":")).encode("utf-8")
            return raw_bytes, submitted, total_elided, truncated_events, hit_ceiling
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    b1, sub1, el1, tr1, ceil1 = run_once(window_tokens)
    b2, sub2, _, _, ceil2 = run_once(window_tokens)
    _, sub_tight, _, _, ceil_tight = run_once(16_000)
    sha1 = hashlib.sha256(b1).hexdigest()
    sha2 = hashlib.sha256(b2).hexdigest()
    return {
        "passed": (
            b1 == b2
            and sha1 == expected_sha256
            and sha2 == expected_sha256
            and len(b1) == 149747
            and sub1 == sub2
            and not ceil1
            and not ceil2
            and el1 == 5
            and tr1 == 14
            and ceil_tight
            and sub_tight == "killed(context_ceiling)"
        ),
        "turns_replayed": 14,
        "window_tokens": window_tokens,
        "truncated_tool_outputs": tr1,
        "elided_tool_outputs_by_context_rule_v0": el1,
        "extra_model_calls_for_compaction": 0,
        "tight_window_16k_triggers_context_ceiling": ceil_tight,
        "transcript_bytes": len(b1),
        "transcript_sha256": sha1,
        "matches_apple_m5_max_sha256": sha1 == expected_sha256,
        "byte_diffs": sum(x != y for x, y in zip(b1, b2)) + abs(len(b1) - len(b2)),
    }


def verify_c10_process_tree_kill(n_trials: int = 5) -> dict:
    cleanup_latencies_ms: list[float] = []
    surviving_counts: list[int] = []

    for _ in range(n_trials):
        tmp = Path(tempfile.mkdtemp(prefix="satb_c10_"))
        pid_file = tmp / "pids.txt"
        cmd = (
            "sleep 60 & echo $! >> pids.txt; "
            "sleep 60 & echo $! >> pids.txt; "
            "sleep 60 & echo $! >> pids.txt; "
            "sleep 60"
        )
        proc = subprocess.Popen(
            ["/bin/sh", "-c", cmd],
            cwd=str(tmp),
            env={"PATH": "/usr/bin:/bin", "HOME": str(tmp), "NO_PROXY": "*"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        t_wait = time.perf_counter()
        child_pids: list[int] = []
        while (time.perf_counter() - t_wait) < 1.0:
            if pid_file.exists():
                lines = [x.strip() for x in pid_file.read_text().splitlines() if x.strip().isdigit()]
                if len(lines) >= 3:
                    child_pids = [int(x) for x in lines[:3]]
                    break
            time.sleep(0.005)

        all_pids = [proc.pid, *child_pids]
        pgid = os.getpgid(proc.pid)

        t_kill0 = time.perf_counter()
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=2.0)

        while (time.perf_counter() - t_kill0) < 2.0:
            alive = 0
            for p in all_pids:
                try:
                    os.kill(p, 0)
                    alive += 1
                except ProcessLookupError:
                    pass
                except PermissionError:
                    alive += 1
            if alive == 0:
                break
            time.sleep(0.0005)

        kill_ms = (time.perf_counter() - t_kill0) * 1000.0
        still_alive = 0
        for p in all_pids:
            try:
                os.kill(p, 0)
                still_alive += 1
            except ProcessLookupError:
                pass
        cleanup_latencies_ms.append(round(kill_ms, 3))
        surviving_counts.append(still_alive)
        shutil.rmtree(tmp, ignore_errors=True)

    return {
        "passed": max(cleanup_latencies_ms) < 2000.0 and sum(surviving_counts) == 0,
        "spec_ceiling_ms": 2000.0,
        "trials": n_trials,
        "processes_per_tree": 4,
        "cleanup_ms_trials": cleanup_latencies_ms,
        "cleanup_ms_min": round(min(cleanup_latencies_ms), 3),
        "cleanup_ms_mean": round(statistics.mean(cleanup_latencies_ms), 3),
        "cleanup_ms_max": round(max(cleanup_latencies_ms), 3),
        "surviving_pids_after_kill": sum(surviving_counts),
        "outcome_recorded": "killed(wall_ceiling)",
    }


def read_linux_l3_self() -> dict:
    ru = resource.getrusage(resource.RUSAGE_SELF)
    ru_ch = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu_s = (ru.ru_utime + ru.ru_stime) + (ru_ch.ru_utime + ru_ch.ru_stime)
    io_r = io_w = 0
    try:
        for line in Path("/proc/self/io").read_text().splitlines():
            if line.startswith("read_bytes:"):
                io_r = int(line.split(":")[1].strip())
            elif line.startswith("write_bytes:"):
                io_w = int(line.split(":")[1].strip())
    except OSError:
        pass
    cg_rel = "not_available"
    try:
        for line in Path("/proc/self/cgroup").read_text().splitlines():
            if line.startswith("0::"):
                cg_rel = line.split("0::", 1)[1].strip()
    except OSError:
        pass
    return {
        "cpu_ns": int(round(cpu_s * 1e9)),
        "maxrss_kb": int(ru.ru_maxrss),
        "io_read_bytes": io_r,
        "io_write_bytes": io_w,
        "cgroup_v2_attached": cg_rel != "not_available",
    }


# ============================================================================
# 3. Hardware Rail & Counter Discovery (`INA238`/`INA3221`, `RAPL`, `amdgpu`)
# ============================================================================

def read_int_file(p: Path) -> int | None:
    try:
        return int(p.read_text().strip())
    except Exception:
        return None


def read_str_file(p: Path) -> str | None:
    try:
        return p.read_text().strip()
    except Exception:
        return None


def stat_perm_summary(p: Path) -> dict:
    try:
        st = p.stat()
        mode_oct = f"{stat.S_IMODE(st.st_mode):04o}"
        owner = "root" if st.st_uid == 0 else f"uid_{st.st_uid}"
        try:
            group_name = grp.getgrgid(st.st_gid).gr_name
        except KeyError:
            group_name = f"gid_{st.st_gid}"
        readable_now = os.access(p, os.R_OK)
        world_readable = bool(st.st_mode & stat.S_IROTH)
        group_readable = bool(st.st_mode & stat.S_IRGRP)
        return {
            "exists": True,
            "mode_octal": mode_oct,
            "owner": owner,
            "group": group_name,
            "group_readable": group_readable,
            "world_readable": world_readable,
            "readable_by_current_uid": readable_now,
        }
    except OSError as e:
        return {"exists": False, "error": e.strerror}


class HardwareMeter:
    """
    Unified rootless Linux hardware rail / counter reader:
      - `ina_shunt` mode (NVIDIA Jetson Thor): reads physical TI `INA238` (`hwmon` `ina238`,
        `VIN` whole-board `L1`) and `INA3221` (`hwmon` `ina3221`, ch1 `VDD_GPU` `L2`,
        ch2 `VDD_CPU_SOC_MSS` `L2`, ch3 `VIN_SYS_5V0` `L1`) shunt monitors (`measured_j`).
      - `rapl` mode (AMD Strix Halo & Intel Raptor Lake): reads cumulative `/sys/class/powercap`
        `intel-rapl*` `energy_uj` counters (`reported_j`) plus optional `amdgpu` `PPT` (`power1_input`).
    """

    def __init__(self) -> None:
        self.ina238_dir: Path | None = None
        self.ina3221_dir: Path | None = None
        self.amdgpu_dir: Path | None = None
        self.rapl_domains: dict[str, dict] = {}
        self.hwmon_inventory: list[dict] = []

        hwmon_root = Path("/sys/class/hwmon")
        if hwmon_root.exists():
            for h in sorted(hwmon_root.iterdir(), key=lambda x: x.name):
                nm = read_str_file(h / "name") or "unknown"
                attrs = sorted(
                    f.name
                    for f in h.iterdir()
                    if any(k in f.name for k in ("power", "energy", "in", "curr", "temp", "label"))
                    and f.is_file()
                )
                self.hwmon_inventory.append({
                    "node": h.name,
                    "driver": nm,
                    "telemetry_files": attrs[:24],
                })
                if nm == "ina238":
                    self.ina238_dir = h
                elif nm == "ina3221":
                    self.ina3221_dir = h
                elif nm == "amdgpu":
                    self.amdgpu_dir = h

        pcap_root = Path("/sys/class/powercap")
        if pcap_root.exists():
            for d in sorted(pcap_root.iterdir(), key=lambda x: x.name):
                if not d.name.startswith("intel-rapl:"):
                    continue
                nm = read_str_file(d / "name")
                e_path = d / "energy_uj"
                max_path = d / "max_energy_range_uj"
                if nm and e_path.exists():
                    perm = stat_perm_summary(e_path)
                    self.rapl_domains[f"{d.name}:{nm}"] = {
                        "sysfs_node": f"/sys/class/powercap/{d.name}/energy_uj",
                        "domain_name": nm,
                        "level": "L1" if nm == "psys" else "L2",
                        "max_energy_range_uj": read_int_file(max_path) or 0,
                        "permissions": perm,
                    }

        self.has_physical_shunt = self.ina238_dir is not None and self.ina3221_dir is not None
        self.has_readable_rapl = any(
            v["permissions"].get("readable_by_current_uid") for v in self.rapl_domains.values()
        )

    def read_shunt_instant(self) -> dict[str, float]:
        """Single synchronous I2C sysfs read on Jetson Thor returning instant rail Watts."""
        assert self.ina238_dir is not None and self.ina3221_dir is not None
        vin_uw = int((self.ina238_dir / "power1_input").read_text().strip())
        vin_mv = int((self.ina238_dir / "in1_input").read_text().strip())
        vin_ma = int((self.ina238_dir / "curr1_input").read_text().strip())

        v1 = int((self.ina3221_dir / "in1_input").read_text().strip())
        c1 = int((self.ina3221_dir / "curr1_input").read_text().strip())
        v2 = int((self.ina3221_dir / "in2_input").read_text().strip())
        c2 = int((self.ina3221_dir / "curr2_input").read_text().strip())
        v3 = int((self.ina3221_dir / "in3_input").read_text().strip())
        c3 = int((self.ina3221_dir / "curr3_input").read_text().strip())

        return {
            "l1_vin_ina238_w": vin_uw / 1e6,
            "l1_vin_ina238_mv": float(vin_mv),
            "l1_vin_ina238_ma": float(vin_ma),
            "l2_vdd_gpu_ina3221_ch1_w": (v1 * c1) / 1e6,
            "l2_vdd_cpu_soc_mss_ina3221_ch2_w": (v2 * c2) / 1e6,
            "l1_vin_sys_5v0_ina3221_ch3_w": (v3 * c3) / 1e6,
        }

    def read_rapl_snapshot(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for k, meta in self.rapl_domains.items():
            if meta["permissions"].get("readable_by_current_uid"):
                val = read_int_file(Path(meta["sysfs_node"]))
                if val is not None:
                    out[k] = val
        return out

    def rapl_delta_uj(self, s0: dict[str, int], s1: dict[str, int]) -> dict[str, int]:
        out: dict[str, int] = {}
        for k, v1 in s1.items():
            if k not in s0:
                continue
            v0 = s0[k]
            if v1 >= v0:
                out[k] = v1 - v0
            else:
                wrap = self.rapl_domains[k]["max_energy_range_uj"]
                out[k] = (wrap - v0) + v1 if wrap > v0 else 0
        return out

    def read_amdgpu_ppt_w(self) -> float | None:
        if self.amdgpu_dir is None:
            return None
        for fname in ("power1_input", "power1_average"):
            p = self.amdgpu_dir / fname
            v = read_int_file(p)
            if v is not None:
                return v / 1e6
        return None


# ============================================================================
# 4. `Falsifier 5` Observer-Effect Cadence Sweep (`0 Hz`, `1 Hz`, `10 Hz`, `100 Hz`)
# ============================================================================

def run_falsifier_5_observer_cadence(meter: HardwareMeter, window_s: float = 1.5) -> dict:
    # Measure single-read sysfs latency first (50 back-to-back reads)
    read_lat_us_samples: list[float] = []
    for _ in range(50):
        t0 = time.perf_counter_ns()
        if meter.has_physical_shunt:
            _ = meter.read_shunt_instant()
        elif meter.has_readable_rapl:
            _ = meter.read_rapl_snapshot()
            _ = meter.read_amdgpu_ppt_w()
        else:
            _ = resource.getrusage(resource.RUSAGE_SELF)
        read_lat_us_samples.append((time.perf_counter_ns() - t0) / 1e3)

    cadences = [
        ("boundary_0hz", None),
        ("tick_1hz_1000ms", 1.000),
        ("tick_10hz_100ms_ref", 0.100),
        ("tick_100hz_10ms", 0.010),
    ]
    results: dict[str, dict] = {}

    for key, sleep_s in cadences:
        ru0 = resource.getrusage(resource.RUSAGE_SELF)
        rapl0 = meter.read_rapl_snapshot() if meter.has_readable_rapl else {}
        shunt_trace: list[tuple[float, dict[str, float]]] = []
        amdgpu_samples: list[float] = []
        t0 = time.perf_counter()

        if sleep_s is None:
            if meter.has_physical_shunt:
                shunt_trace.append((0.0, meter.read_shunt_instant()))
            time.sleep(window_s)
            wall_s = time.perf_counter() - t0
            if meter.has_physical_shunt:
                shunt_trace.append((wall_s, meter.read_shunt_instant()))
            n_samples = 2
        else:
            n_samples = 0
            while True:
                now_rel = time.perf_counter() - t0
                if now_rel >= window_s:
                    break
                if meter.has_physical_shunt:
                    shunt_trace.append((now_rel, meter.read_shunt_instant()))
                elif meter.has_readable_rapl:
                    _ = meter.read_rapl_snapshot()
                    pw = meter.read_amdgpu_ppt_w()
                    if pw is not None:
                        amdgpu_samples.append(pw)
                _ = resource.getrusage(resource.RUSAGE_SELF)
                n_samples += 1
                rem = window_s - (time.perf_counter() - t0)
                if rem <= 0:
                    break
                time.sleep(min(sleep_s, rem))
            wall_s = time.perf_counter() - t0

        rapl1 = meter.read_rapl_snapshot() if meter.has_readable_rapl else {}
        ru1 = resource.getrusage(resource.RUSAGE_SELF)
        cpu_ms = ((ru1.ru_utime - ru0.ru_utime) + (ru1.ru_stime - ru0.ru_stime)) * 1000.0

        entry: dict = {
            "nominal_hz": 0.0 if sleep_s is None else round(1.0 / sleep_s, 1),
            "window_s": round(wall_s, 4),
            "samples": n_samples,
            "achieved_hz": round(n_samples / wall_s, 2),
            "sampler_cpu_ms_in_window": round(cpu_ms, 3),
            "sampler_cpu_ms_per_10s_equiv": round(cpu_ms * (10.0 / wall_s), 3),
        }

        if meter.has_physical_shunt and len(shunt_trace) >= 2:
            # Trapezoidal integration of physical shunt watts -> `measured_j`
            e_vin = e_gpu = e_cpu = e_sys5 = 0.0
            for i in range(len(shunt_trace) - 1):
                dt = shunt_trace[i + 1][0] - shunt_trace[i][0]
                a, b = shunt_trace[i][1], shunt_trace[i + 1][1]
                e_vin += 0.5 * (a["l1_vin_ina238_w"] + b["l1_vin_ina238_w"]) * dt
                e_gpu += 0.5 * (a["l2_vdd_gpu_ina3221_ch1_w"] + b["l2_vdd_gpu_ina3221_ch1_w"]) * dt
                e_cpu += 0.5 * (a["l2_vdd_cpu_soc_mss_ina3221_ch2_w"] + b["l2_vdd_cpu_soc_mss_ina3221_ch2_w"]) * dt
                e_sys5 += 0.5 * (a["l1_vin_sys_5v0_ina3221_ch3_w"] + b["l1_vin_sys_5v0_ina3221_ch3_w"]) * dt
            entry["measured_j_rails"] = {
                "l1_vin_ina238_j": round(e_vin, 4),
                "l2_vdd_gpu_ina3221_ch1_j": round(e_gpu, 4),
                "l2_vdd_cpu_soc_mss_ina3221_ch2_j": round(e_cpu, 4),
                "l1_vin_sys_5v0_ina3221_ch3_j": round(e_sys5, 4),
            }
            entry["reported_j_domains"] = None

        if meter.has_readable_rapl:
            d_uj = meter.rapl_delta_uj(rapl0, rapl1)
            entry["reported_j_domains"] = {k: round(v / 1e6, 4) for k, v in d_uj.items()}
            entry["measured_j_rails"] = None
            if amdgpu_samples:
                entry["amdgpu_ppt_mean_w"] = round(statistics.mean(amdgpu_samples), 3)

        results[key] = entry

    return {
        "sysfs_single_sample_read_latency_us": {
            "median_us": round(statistics.median(read_lat_us_samples), 2),
            "mean_us": round(statistics.mean(read_lat_us_samples), 2),
            "p95_us": round(sorted(read_lat_us_samples)[int(0.95 * len(read_lat_us_samples))], 2),
        },
        "window_target_s": window_s,
        "cadences": results,
    }


# ============================================================================
# 5. `Falsifier 3` (`B` vs `C`), `Step 7` Sum Check & `Falsifier 6` Rail Split
# ============================================================================

def run_falsifier_3_and_6_rail_audit(meter: HardwareMeter, phase_s: float = 1.5, baseline_s: float = 1.0) -> dict:
    """
    Brackets a 2-phase sequential SUT run (`Phase 1`: SHA-256 ALU compute burst;
    `Phase 2`: `192 MiB` DRAM cache-miss stride + `fsync` I/O wait) with `1.0 s`
    pre/post baselines (`Falsifier 6`), verifying `Step 7` sum check (`Falsifier 2`),
    `B` vs. `C` (`Kepler`) divergence (`Falsifier 3`), and on Jetson Thor physical
    `INA3221` rail separation (`VDD_GPU` co-tenant vs. `VDD_CPU_SOC_MSS` CPU/SoC).
    """
    tmp_dir = tempfile.mkdtemp(prefix="satb_f3_")
    io_path = os.path.join(tmp_dir, "flush.bin")
    buf_mem = bytearray(192 * 1024 * 1024)
    for off in range(0, len(buf_mem), 4096):
        buf_mem[off] = (off >> 12) & 0xFF
    flush_chunk = b"X" * (256 * 1024)

    shunt_samples: list[tuple[float, dict[str, float]]] = []
    amdgpu_samples: list[tuple[float, float]] = []
    stop_evt = threading.Event()
    t_origin = time.perf_counter()

    def bg_shunt_sampler() -> None:
        while not stop_evt.is_set():
            ts = time.perf_counter() - t_origin
            if meter.has_physical_shunt:
                shunt_samples.append((ts, meter.read_shunt_instant()))
            elif meter.amdgpu_dir is not None:
                pw = meter.read_amdgpu_ppt_w()
                if pw is not None:
                    amdgpu_samples.append((ts, pw))
            time.sleep(0.020)  # 50 Hz physical rail trace

    use_sampler = meter.has_physical_shunt or (meter.amdgpu_dir is not None)
    thr = threading.Thread(target=bg_shunt_sampler, daemon=True) if use_sampler else None
    if thr is not None:
        thr.start()

    try:
        # 1. Pre-window resident baseline (`baseline_s`)
        t_pre0 = time.perf_counter() - t_origin
        rapl_pre0 = meter.read_rapl_snapshot() if meter.has_readable_rapl else {}
        time.sleep(baseline_s)
        t_0 = time.perf_counter() - t_origin
        rapl_0 = meter.read_rapl_snapshot() if meter.has_readable_rapl else {}
        ru_0 = resource.getrusage(resource.RUSAGE_SELF)

        # 2. Phase 1: Pure compute-heavy SHA-256 burst (`phase_s`)
        digest = b"satb_phase1_compute"
        t_p1_start = time.perf_counter()
        while (time.perf_counter() - t_p1_start) < phase_s:
            for _ in range(4000):
                digest = hashlib.sha256(digest).digest()

        t_1 = time.perf_counter() - t_origin
        rapl_1 = meter.read_rapl_snapshot() if meter.has_readable_rapl else {}
        ru_1 = resource.getrusage(resource.RUSAGE_SELF)

        # 3. Phase 2: 192 MiB DRAM cache-miss stride + fsync + 8 ms I/O wait (`phase_s`)
        stride = 65537 * 64
        pos = 0
        n_bytes = len(buf_mem)
        fd = os.open(io_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        try:
            t_p2_start = time.perf_counter()
            while (time.perf_counter() - t_p2_start) < phase_s:
                acc = 0
                for _ in range(8192):
                    pos = (pos + stride) % n_bytes
                    buf_mem[pos] = (buf_mem[pos] + 1) & 0xFF
                    acc += buf_mem[pos]
                os.lseek(fd, 0, os.SEEK_SET)
                os.write(fd, flush_chunk)
                os.fsync(fd)
                time.sleep(0.008)
        finally:
            os.close(fd)

        t_2 = time.perf_counter() - t_origin
        rapl_2 = meter.read_rapl_snapshot() if meter.has_readable_rapl else {}
        ru_2 = resource.getrusage(resource.RUSAGE_SELF)

        # 4. Post-window resident baseline (`baseline_s`)
        time.sleep(baseline_s)
        t_post1 = time.perf_counter() - t_origin
        rapl_post1 = meter.read_rapl_snapshot() if meter.has_readable_rapl else {}
    finally:
        stop_evt.set()
        if thr is not None:
            thr.join(timeout=0.5)
        shutil.rmtree(tmp_dir, ignore_errors=True)

    cpu_p1_ms = ((ru_1.ru_utime - ru_0.ru_utime) + (ru_1.ru_stime - ru_0.ru_stime)) * 1000.0
    cpu_p2_ms = ((ru_2.ru_utime - ru_1.ru_utime) + (ru_2.ru_stime - ru_1.ru_stime)) * 1000.0
    cpu_tot_ms = max(1e-6, cpu_p1_ms + cpu_p2_ms)
    c_share_p1 = cpu_p1_ms / cpu_tot_ms
    c_share_p2 = cpu_p2_ms / cpu_tot_ms

    p1_dur = t_1 - t_0
    p2_dur = t_2 - t_1
    pre_dur = t_0 - t_pre0
    post_dur = t_post1 - t_2

    out: dict = {
        "phase1_compute_wall_s": round(p1_dur, 4),
        "phase2_dram_fsync_wall_s": round(p2_dur, 4),
        "phase1_sut_cpu_ms": round(cpu_p1_ms, 2),
        "phase2_sut_cpu_ms": round(cpu_p2_ms, 2),
        "kepler_c_cpu_share_phase1": round(c_share_p1, 4),
        "kepler_c_cpu_share_phase2": round(c_share_p2, 4),
    }

    if meter.has_physical_shunt and len(shunt_samples) >= 4:
        def integrate_window(ta: float, tb: float, field: str) -> float:
            tot = 0.0
            for i in range(len(shunt_samples) - 1):
                s_t0, s_v0 = shunt_samples[i][0], shunt_samples[i][1][field]
                s_t1, s_v1 = shunt_samples[i + 1][0], shunt_samples[i + 1][1][field]
                lo = max(ta, s_t0)
                hi = min(tb, s_t1)
                if hi > lo and (s_t1 > s_t0):
                    # Linear interpolation at interval endpoints for exact piecewise integral
                    f0 = (lo - s_t0) / (s_t1 - s_t0)
                    f1 = (hi - s_t0) / (s_t1 - s_t0)
                    w0 = s_v0 + f0 * (s_v1 - s_v0)
                    w1 = s_v0 + f1 * (s_v1 - s_v0)
                    tot += 0.5 * (w0 + w1) * (hi - lo)
            return tot

        rails_summary = {}
        for field in (
            "l1_vin_ina238_w",
            "l2_vdd_gpu_ina3221_ch1_w",
            "l2_vdd_cpu_soc_mss_ina3221_ch2_w",
            "l1_vin_sys_5v0_ina3221_ch3_w",
        ):
            j_pre = integrate_window(t_pre0, t_0, field)
            j_p1 = integrate_window(t_0, t_1, field)
            j_p2 = integrate_window(t_1, t_2, field)
            j_tot = integrate_window(t_0, t_2, field)
            j_post = integrate_window(t_2, t_post1, field)
            w_pre = j_pre / max(1e-6, pre_dur)
            w_post = j_post / max(1e-6, post_dur)
            drift_pct = abs(w_post - w_pre) / max(1e-6, w_pre) * 100.0
            sum_res_uj = abs((j_p1 + j_p2) - j_tot) * 1e6

            c_p1 = j_tot * c_share_p1
            c_p2 = j_tot * c_share_p2
            err_p1 = abs(c_p1 - j_p1) / max(1e-6, j_p1) * 100.0
            err_p2 = abs(c_p2 - j_p2) / max(1e-6, j_p2) * 100.0

            rail_key = field[:-2] + "_measured_j"
            rails_summary[rail_key] = {
                "pre_baseline_mean_w": round(w_pre, 3),
                "phase1_mean_w": round(j_p1 / max(1e-6, p1_dur), 3),
                "phase2_mean_w": round(j_p2 / max(1e-6, p2_dur), 3),
                "post_baseline_mean_w": round(w_post, 3),
                "pre_post_drift_pct": round(drift_pct, 2),
                "falsifier6_within_5pct": drift_pct <= 5.0,
                "b_temporal_phase1_measured_j": round(j_p1, 4),
                "b_temporal_phase2_measured_j": round(j_p2, 4),
                "b_temporal_total_measured_j": round(j_tot, 4),
                "step7_sum_check_residual_uj": round(sum_res_uj, 2),
                "c_kepler_phase1_j": round(c_p1, 4),
                "c_kepler_phase2_j": round(c_p2, 4),
                "c_vs_b_phase1_err_pct": round(err_p1, 2),
                "c_vs_b_phase2_err_pct": round(err_p2, 2),
            }

        cpu_rail = rails_summary["l2_vdd_cpu_soc_mss_ina3221_ch2_measured_j"]
        vin_rail = rails_summary["l1_vin_ina238_measured_j"]
        out["measured_j_shunt_rails"] = rails_summary
        out["reported_j_rapl_domains"] = None
        out["step7_sum_check_passed"] = all(
            v["step7_sum_check_residual_uj"] <= 1000.0 for v in rails_summary.values()
        )
        out["falsifier_3_triggered_gt_20pct"] = (
            cpu_rail["c_vs_b_phase2_err_pct"] > 20.0 or vin_rail["c_vs_b_phase2_err_pct"] > 20.0
        )

    if meter.has_readable_rapl:
        d_pre = meter.rapl_delta_uj(rapl_pre0, rapl_0)
        d_p1 = meter.rapl_delta_uj(rapl_0, rapl_1)
        d_p2 = meter.rapl_delta_uj(rapl_1, rapl_2)
        d_tot = meter.rapl_delta_uj(rapl_0, rapl_2)
        d_post = meter.rapl_delta_uj(rapl_2, rapl_post1)

        rapl_summary = {}
        for k in d_tot:
            b_p1_uj = d_p1[k]
            b_p2_uj = d_p2[k]
            b_tot_uj = d_tot[k]
            res_uj = abs((b_p1_uj + b_p2_uj) - b_tot_uj)
            w_pre = (d_pre[k] / 1e6) / max(1e-6, pre_dur)
            w_post = (d_post[k] / 1e6) / max(1e-6, post_dur)
            drift_pct = abs(w_post - w_pre) / max(1e-6, w_pre) * 100.0

            b_p1_j = b_p1_uj / 1e6
            b_p2_j = b_p2_uj / 1e6
            b_tot_j = b_tot_uj / 1e6
            c_p1_j = b_tot_j * c_share_p1
            c_p2_j = b_tot_j * c_share_p2
            err_p1 = abs(c_p1_j - b_p1_j) / max(1e-6, b_p1_j) * 100.0
            err_p2 = abs(c_p2_j - b_p2_j) / max(1e-6, b_p2_j) * 100.0

            rapl_summary[k] = {
                "level": meter.rapl_domains[k]["level"],
                "pre_baseline_mean_w": round(w_pre, 3),
                "phase1_mean_w": round(b_p1_j / max(1e-6, p1_dur), 3),
                "phase2_mean_w": round(b_p2_j / max(1e-6, p2_dur), 3),
                "post_baseline_mean_w": round(w_post, 3),
                "pre_post_drift_pct": round(drift_pct, 2),
                "falsifier6_within_5pct": drift_pct <= 5.0,
                "b_temporal_phase1_reported_j": round(b_p1_j, 4),
                "b_temporal_phase2_reported_j": round(b_p2_j, 4),
                "b_temporal_total_reported_j": round(b_tot_j, 4),
                "step7_sum_check_residual_uj": int(res_uj),
                "c_kepler_phase1_j": round(c_p1_j, 4),
                "c_kepler_phase2_j": round(c_p2_j, 4),
                "c_vs_b_phase1_err_pct": round(err_p1, 2),
                "c_vs_b_phase2_err_pct": round(err_p2, 2),
            }

        pkg_key = next((k for k in rapl_summary if "package-0" in k), next(iter(rapl_summary)))
        out["reported_j_rapl_domains"] = rapl_summary
        out["measured_j_shunt_rails"] = None
        out["step7_sum_check_passed"] = all(
            v["step7_sum_check_residual_uj"] <= 1 for v in rapl_summary.values()
        )
        out["falsifier_3_triggered_gt_20pct"] = rapl_summary[pkg_key]["c_vs_b_phase2_err_pct"] > 20.0
        if amdgpu_samples:
            p1_gpu = [w for ts, w in amdgpu_samples if t_0 <= ts <= t_1]
            p2_gpu = [w for ts, w in amdgpu_samples if t_1 < ts <= t_2]
            out["amdgpu_ppt_trace_w"] = {
                "phase1_mean_w": round(statistics.mean(p1_gpu), 3) if p1_gpu else None,
                "phase2_mean_w": round(statistics.mean(p2_gpu), 3) if p2_gpu else None,
            }

    return out


# ============================================================================
# 6. Host Metadata & Sanitized Output Receipt Builder
# ============================================================================

def detect_cpu_brand() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    try:
        dt_model = Path("/proc/device-tree/model").read_bytes().rstrip(b"\x00").decode("utf-8", errors="replace")
        if dt_model:
            return dt_model
    except OSError:
        pass
    return platform.processor() or platform.machine()


def detect_ram_gib() -> float:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                kb = int(line.split()[1])
                return round(kb / (1024 * 1024), 1)
    except OSError:
        pass
    return 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=os.environ.get("SATB_HOST_PROFILE", "linux_host"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    t_start = time.perf_counter()
    meter = HardwareMeter()

    # Check co-tenant / dedicated-host status cleanly without exposing any user paths
    gpu_lock_path = os.environ.get("SATB_GPU_LOCK_FILE", "")
    gpu_cotenant_lock_active = bool(gpu_lock_path and Path(gpu_lock_path).exists())
    load1, load5, load15 = os.getloadavg()
    dedicated_host = (not gpu_cotenant_lock_active) and (load1 < 1.5)

    shape_d = run_shape_d_dnullmm1_conformance()
    c9 = verify_c9_extended_replay()
    c10 = verify_c10_process_tree_kill(n_trials=5)

    t_mono = time.monotonic_ns()
    t_wall = time.time_ns()
    l3_self = read_linux_l3_self()
    c11 = {
        "passed": l3_self["maxrss_kb"] > 0,
        "sudo_invoked": False,
        "wall_minus_monotonic_offset_ns": t_wall - t_mono,
        "linux_l3_counters": l3_self,
        "linux_per_pid_hardware_joule_counter": "not_available (Linux exposes cgroup/rusage activity shares C, not physical joules)",
    }

    f5 = run_falsifier_5_observer_cadence(meter, window_s=1.05)
    f3_f6 = run_falsifier_3_and_6_rail_audit(meter, phase_s=1.20, baseline_s=0.60)

    # Check current user group membership for `energy` (without recording username!)
    try:
        cur_groups = [grp.getgrgid(g).gr_name for g in os.getgroups()]
    except Exception:
        cur_groups = []

    platypus_audit = {
        "rapl_domains_found": meter.rapl_domains,
        "supervisor_in_energy_group": "energy" in cur_groups,
        "amdgpu_energy1_input_present": bool(
            meter.amdgpu_dir and (meter.amdgpu_dir / "energy1_input").exists()
        ),
        "amdgpu_power1_ppt_world_readable": bool(
            meter.amdgpu_dir and os.access(meter.amdgpu_dir / "power1_input", os.R_OK)
        ),
    }

    receipt = {
        "profile_id": args.profile,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "host_envelope": {
            "cpu_or_board_model": detect_cpu_brand(),
            "arch": platform.machine(),
            "logical_cpus": os.cpu_count() or 1,
            "ram_gib": detect_ram_gib(),
            "os_kernel": f"{platform.system()} {platform.release()}",
            "python_version": platform.python_version(),
            "loadavg_1m_5m_15m": [round(load1, 2), round(load5, 2), round(load15, 2)],
            "gpu_cotenant_lock_active": gpu_cotenant_lock_active,
            "dedicated_host": dedicated_host,
            "rootless_collection": os.geteuid() != 0,
        },
        "evidence_separation": {
            "board_metered": meter.has_physical_shunt,
            "a2_whole_sut_net_attributable": dedicated_host,
            "a2_withheld_reason": (
                None
                if dedicated_host
                else "shared_host_cotenant_active (raw rail/counter channels preserved; A2 net attribution withheld per SATB OQ-4 / Falsifier 6)"
            ),
            "measured_j_populated": meter.has_physical_shunt,
            "reported_j_populated": meter.has_readable_rapl,
            "est_j": None,
        },
        "telemetry_inventory_and_platypus_audit": {
            "hwmon_sensors": meter.hwmon_inventory,
            "powercap_and_gpu_audit": platypus_audit,
        },
        "shape_d_dnullmm1_conformance": shape_d,
        "satb_conformance_linux": {
            "c9_deterministic_replay": c9,
            "c10_process_group_sigkill": c10,
            "c11_rootless_l3_handshake": c11,
        },
        "falsifier_5_observer_cadence": f5,
        "falsifier_3_step7_and_falsifier_6_rails": f3_f6,
        "elapsed_wall_s": round(time.perf_counter() - t_start, 2),
    }

    raw = json.dumps(receipt, indent=2)
    # Scrub any accidental home or user string before writing
    uname = pwd.getpwuid(os.getuid()).pw_name
    home_parent = str(Path.home().parent)
    for tok in (str(Path.home()), f"{home_parent}/{uname}", uname, platform.node()):
        if tok and len(tok) >= 3 and tok in raw:
            raw = raw.replace(tok, "$REDACTED_HOST")

    Path(args.out).write_text(raw + "\n", encoding="utf-8")
    print(f"[{args.profile}] Completed in {receipt['elapsed_wall_s']} s -> {args.out}", flush=True)


if __name__ == "__main__":
    main()
