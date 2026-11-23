#!/usr/bin/env python3
"""
Wave 5 · RCE Compile E4-Prelude: Pre-Compiled `librce_rt.rlib` Shared Runtime Crate
vs. Monolithic Embedded Prelude (`openIE-dev/rce` at commit `1762fb4bb65a`).

Pre-registration: `PREREG_rce_compile_wave5_rlib.json`
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
import re
import shutil
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

POWERCAP_PKG = "/sys/class/powercap/intel-rapl:0"
POWERCAP_CORE = "/sys/class/powercap/intel-rapl:0:0"


def verify_prereg(prereg_path: Path, sha_path: Path) -> str:
    actual = hashlib.sha256(prereg_path.read_bytes()).hexdigest()
    expected = sha_path.read_text(encoding="utf-8").strip().split()[0]
    if actual != expected:
        raise RuntimeError(f"PREREG SHA-256 mismatch: expected {expected}, got {actual}")
    return actual


def wrap_delta(prev: int, now: int, max_uj: int) -> int:
    return (now - prev) if now >= prev else (max(max_uj - prev, 0) + now + 1)


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
        self._last_pkg = int(self.pkg_file.read_bytes().strip())
        self._last_core = int(self.core_file.read_bytes().strip())
        self._cum_pkg_uj = 0
        self._cum_core_uj = 0

    def mark(self) -> tuple[int, int, float]:
        p = int(self.pkg_file.read_bytes().strip())
        c = int(self.core_file.read_bytes().strip())
        t = time.perf_counter()
        if p < self._last_pkg:
            self.pkg_wraps += 1
        if c < self._last_core:
            self.core_wraps += 1
        self._cum_pkg_uj += wrap_delta(self._last_pkg, p, self.pkg_max)
        self._cum_core_uj += wrap_delta(self._last_core, c, self.core_max)
        self._last_pkg, self._last_core = p, c
        return self._cum_pkg_uj, self._cum_core_uj, t

    def since(self, start_mark: tuple[int, int, float]) -> dict[str, float]:
        p1, c1, t1 = self.mark()
        p0, c0, t0 = start_mark
        return {
            "wall_s": max(1e-9, t1 - t0),
            "pkg_j": (p1 - p0) * 1e-6,
            "core_j": (c1 - c0) * 1e-6,
        }

    def sample_sleep_power(self, sleep_s: float = 0.25) -> tuple[float, float]:
        m0 = self.mark()
        time.sleep(sleep_s)
        d = self.since(m0)
        return d["core_j"] / d["wall_s"], d["pkg_j"] / d["wall_s"]


RCE_BODIES: dict[str, str] = {
    "k01_sha256_block": """    var w: [u64; 64] = [0; 64]
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
    return (a ^ b ^ c ^ d ^ e ^ f ^ g ^ h) & m""",
    "k02_chacha20_block": """    var st: [u64; 16] = [0; 16]
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
    return acc""",
    "k03_q32_orbital": """    let m: u64 = 4294967295
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
    return (px ^ (py << 8) ^ vx ^ vy) & m""",
    "k04_crc32_ieee": """    let m: u64 = 4294967295
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
    return (crc ^ m) & m""",
    "k05_lz77_match": """    var buf: [u64; 64] = [0; 64]
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
    return score""",
    "k06_dijkstra_grid": """    var dist: [u64; 16] = [1000000; 16]
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
    return acc""",
    "k07_ntt_butterfly": """    let modp: u64 = 998244353
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
    return acc""",
    "k08_matmul_i32": """    let m: u64 = 4294967295
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
    return acc""",
    "k09_bst_probe": """    var keys: [u64; 16] = [0; 16]
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
    return ((depth_sum << 16) ^ keys[15] ^ left[0] ^ right[0]) & 4294967295""",
    "k10_sortnet_16": """    var a: [u64; 16] = [0; 16]
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
    return acc""",
    "k11_ringbuf_sim": """    var rb: [u64; 16] = [0; 16]
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
    return (((sum << 4) & 4294967295) ^ count ^ (head as u64) ^ (tail as u64)) & 4294967295""",
    "k12_token_bucket": """    var tokens: u64 = 50
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
    return ((admitted << 12) ^ (refused << 4) ^ tokens) & 4294967295""",
    "k13_fnv1a_sip": """    let m: u64 = 4294967295
    var h: u64 = 2166136261
    var v0: u64 = (seed ^ 19349663) & m
    var v1: u64 = ((seed * 1664525) ^ 83492791) & m
    for i in 0..64
        let b = (v0 + (i as u64) * 73) & 255
        h = ((h ^ b) * 16777619) & m
        v0 = (v0 + v1) & m
        v1 = (((v1 << 13) & m) | (v1 >> 19)) ^ v0
        v0 = ((v0 << 16) & m) | (v0 >> 16)
    return (h ^ v0 ^ v1) & m""",
    "k14_sieve_primes": """    var comp: [u64; 128] = [0; 128]
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
    return acc""",
    "k15_collatz_bounded": """    var total: u64 = 0
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
    return total""",
    "k16_popcount_swar": """    var s: u64 = (seed * 2654435761 + 1) & 4294967295
    var acc: u64 = 0
    for _ in 0..64
        s = (s * 1664525 + 1013904223) & 4294967295
        var x: u64 = s
        x = x - ((x >> 1) & 1431655765)
        x = (x & 858993459) + ((x >> 2) & 858993459)
        let pc = ((((x + (x >> 4)) & 252645135) * 16843009) >> 24) & 63
        acc = (acc * 37 + pc) & 4294967295
    return acc""",
    "k17_edit_levenshtein": """    var sa: [u64; 12] = [0; 12]
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
    return acc""",
    "k18_rle_codec": """    var src: [u64; 64] = [0; 64]
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
    return (((decoded_sum << 8) & 4294967295) ^ ((n_runs + 1) as u64)) & 4294967295""",
    "k19_modexp_mont": """    let modm: u64 = 1000000007
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
    return acc""",
    "k20_kalman_q16": """    var x_est: u64 = 655360
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
    return (x_est ^ (v_est << 8)) & 4294967295""",
}


HOOKS_PRELUDE = """
pub type StepFn = fn(&Vec<(&'static str, V)>, &V) -> R<Option<Vec<(&'static str, V)>>>;

pub struct RceProgramHooks {
    pub loop_limit: i128,
    pub initial_state: fn() -> R<State>,
    pub decl_fields: fn(&str) -> Option<&'static [&'static str]>,
    pub variant_index: fn(&str) -> Option<(i128, &'static [&'static str])>,
    pub event_index: fn(&str) -> Option<usize>,
    pub is_variant: fn(&str) -> bool,
    pub sup_tree: fn() -> Vec<&'static str>,
    pub event_fields: fn(&str) -> Option<Vec<(&'static str, &'static str)>>,
    pub actor_events: fn(&str) -> Vec<&'static str>,
    pub actor_handlers: fn(&str) -> Vec<StepFn>,
    pub actor_init: fn(&str) -> Vec<(&'static str, V)>,
    pub node_names: fn() -> Vec<&'static str>,
    pub node_of: fn(&str) -> usize,
    pub supervisor_of: fn(&str) -> Option<(&'static str, &'static str, Vec<&'static str>, &'static str, u32)>,
    pub restart_window: fn() -> u64,
    pub user_fn: fn(&str, Option<V>, Vec<V>) -> R<Call>,
    pub has_user_fn: fn(&str) -> bool,
    pub raw_fn: fn(&str, Vec<V>) -> R<V>,
    pub user_method: fn(&str, &str) -> Option<fn(Option<V>, Vec<V>) -> R<Call>>,
    pub kind_of: fn(&str) -> &str,
    pub steps_of: fn(&str) -> Vec<StepFn>,
}

static RCE_HOOKS_CELL: std::sync::OnceLock<&'static RceProgramHooks> = std::sync::OnceLock::new();
pub fn register_program_hooks(h: &'static RceProgramHooks) { let _ = RCE_HOOKS_CELL.set(h); }
#[inline]
fn rce_hooks() -> &'static RceProgramHooks { RCE_HOOKS_CELL.get().expect("RceProgramHooks not registered") }
#[inline] fn loop_limit_val() -> i128 { rce_hooks().loop_limit }
fn initial_state() -> R<State> { (rce_hooks().initial_state)() }
fn decl_fields(n: &str) -> Option<&'static [&'static str]> { (rce_hooks().decl_fields)(n) }
fn variant_index(n: &str) -> Option<(i128, &'static [&'static str])> { (rce_hooks().variant_index)(n) }
fn event_index(n: &str) -> Option<usize> { (rce_hooks().event_index)(n) }
fn is_variant(n: &str) -> bool { (rce_hooks().is_variant)(n) }
fn sup_tree() -> Vec<&'static str> { (rce_hooks().sup_tree)() }
fn event_fields(n: &str) -> Option<Vec<(&'static str, &'static str)>> { (rce_hooks().event_fields)(n) }
fn actor_events(t: &str) -> Vec<&'static str> { (rce_hooks().actor_events)(t) }
fn actor_handlers(t: &str) -> Vec<StepFn> { (rce_hooks().actor_handlers)(t) }
fn actor_init(t: &str) -> Vec<(&'static str, V)> { (rce_hooks().actor_init)(t) }
fn node_names() -> Vec<&'static str> { (rce_hooks().node_names)() }
fn node_of(t: &str) -> usize { (rce_hooks().node_of)(t) }
fn supervisor_of(t: &str) -> Option<(&'static str, &'static str, Vec<&'static str>, &'static str, u32)> { (rce_hooks().supervisor_of)(t) }
fn restart_window() -> u64 { (rce_hooks().restart_window)() }
#[inline] fn user_fn(n: &str, slf: Option<V>, a: Vec<V>) -> R<Call> { (rce_hooks().user_fn)(n, slf, a) }
fn has_user_fn(n: &str) -> bool { (rce_hooks().has_user_fn)(n) }
#[inline] fn raw_fn(n: &str, a: Vec<V>) -> R<V> { (rce_hooks().raw_fn)(n, a) }
fn user_method(h: &str, m: &str) -> Option<fn(Option<V>, Vec<V>) -> R<Call>> { (rce_hooks().user_method)(h, m) }
fn kind_of(n: &str) -> &str { (rce_hooks().kind_of)(n) }
fn steps_of(r: &str) -> Vec<StepFn> { (rce_hooks().steps_of)(r) }
"""

HOOKS_REGISTRATION = """
static PROGRAM_HOOKS: RceProgramHooks = RceProgramHooks {
    loop_limit: LOOP_LIMIT,
    initial_state, decl_fields, variant_index, event_index, is_variant,
    sup_tree, event_fields, actor_events, actor_handlers, actor_init,
    node_names, node_of, supervisor_of, restart_window, user_fn,
    has_user_fn, raw_fn, user_method, kind_of, steps_of,
};
"""

THIN_HEADER = (
    "#![allow(dead_code, unused_mut, unused_variables, unused_parens, unreachable_code, "
    "unused_assignments, non_snake_case, unused_imports, clippy::all)]\n"
    "extern crate rce_rt;\nuse rce_rt::*;\n"
    "use std::sync::Arc as Rc;\nuse std::cell::RefCell;\nuse std::collections::HashMap;\n"
)


def render_rce_source(kid: str, body: str, batch_iters: int = 2000) -> str:
    indented = "\n".join(line for line in body.strip("\n").splitlines())
    return (
        f'intent "deterministic exact integer kernel {kid}"\n\n'
        f"fn kernel(seed: u64) -> u64\n{indented}\n\n"
        f"fn main()\n    var csum: u64 = 0\n    for s in 0..{batch_iters}\n"
        f"        csum = (csum + kernel(s as u64)) & 4294967295\n    emit csum\n"
    )


def split_emitted_rust(emitted_rs: str) -> tuple[str, str]:
    marker = "const LOOP_LIMIT:"
    pre, post = emitted_rs.split(marker, 1)
    # Strip the per-program sha256 comment line 1 so rce_rt.rs is program-independent
    pre_lines = pre.splitlines()
    if pre_lines and pre_lines[0].startswith("// rce-program "):
        pre_lines = pre_lines[1:]
    rt_src = "\n".join(pre_lines).replace("LOOP_LIMIT", "loop_limit_val()") + "\n" + HOOKS_PRELUDE
    step_fn_line = "type StepFn = fn(&Vec<(&'static str, V)>, &V) -> R<Option<Vec<(&'static str, V)>>>;\n"
    kern_body = (marker + post).replace(step_fn_line, "")
    thin_src = THIN_HEADER + kern_body.replace(
        "fn main() {\n", HOOKS_REGISTRATION + "fn main() {\n  register_program_hooks(&PROGRAM_HOOKS);\n"
    )
    return rt_src, thin_src


def compute_payback(ec_low: float, er_low: float, ec_high: float, er_high: float, low_lbl: str, high_lbl: str) -> dict[str, Any]:
    d_comp = ec_high - ec_low
    d_run = er_low - er_high
    if d_run <= 0:
        n_star: int | str = "never"
        status = "never_pays_back"
    elif d_comp <= 0:
        n_star = 0
        status = "dominates_immediately"
    else:
        n_star = int(math.ceil(d_comp / d_run))
        status = "finite_payback"
    return {
        "low_tier": low_lbl,
        "high_tier": high_lbl,
        "delta_compile_core_j": round(d_comp, 6),
        "delta_run_core_j": round(d_run, 9),
        "n_star_invocations": n_star,
        "status": status,
    }


def summarize_paybacks(items: list[dict[str, Any]]) -> dict[str, Any]:
    finite = [x["n_star_invocations"] for x in items if isinstance(x["n_star_invocations"], int) and x["n_star_invocations"] > 0]
    imm = sum(1 for x in items if x["n_star_invocations"] == 0)
    never = sum(1 for x in items if x["n_star_invocations"] == "never")
    # Effective median across all non-infinite kernels (including N*=0 immediate dominance!)
    all_paying = [x["n_star_invocations"] for x in items if isinstance(x["n_star_invocations"], int)]
    return {
        "finite_count": len(finite),
        "immediate_dominance_count": imm,
        "never_pays_back_count": never,
        "median_finite_n_star": int(statistics.median(finite)) if finite else (0 if imm > 0 else None),
        "median_paying_n_star_incl_zero": int(statistics.median(all_paying)) if all_paying else None,
        "min_paying_n_star": min(all_paying) if all_paying else None,
        "max_paying_n_star": max(all_paying) if all_paying else None,
    }


def detect_cpu_model() -> str:
    try:
        for ln in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if ln.lower().startswith("model name"):
                return ln.split(":", 1)[1].strip()
    except Exception:
        pass
    return platform.processor() or "x86_64"


def run_suite(args: argparse.Namespace) -> dict[str, Any]:
    prereg_sha = verify_prereg(args.prereg, args.prereg_sha256)
    w4 = json.loads(args.wave4_e4_json.read_text(encoding="utf-8"))
    w4_by_kid = {k["kernel_id"]: k for k in w4["kernels"]}

    work = args.work_dir
    work.mkdir(parents=True, exist_ok=True)
    meter = DualRaplMeter(pin_cpu=args.pin_cpu)

    env = os.environ.copy()
    env.update({"LC_ALL": "C", "TZ": "UTC", "SOURCE_DATE_EPOCH": "1735689600", "CARGO_BUILD_JOBS": "1", "RAYON_NUM_THREADS": "1"})
    rustc_bin = args.rustc_bin or shutil.which("rustc") or "rustc"
    node_bin = shutil.which("node")

    idle_core_pre_w, idle_pkg_pre_w = meter.sample_sleep_power(2.0)
    load_pre = os.getloadavg()

    # 1. Generate all 20 .rce sources and extract canonical rce_rt.rs from k01
    rce_files: dict[str, Path] = {}
    for kid, body in RCE_BODIES.items():
        p = work / f"{kid}.rce"
        p.write_text(render_rce_source(kid, body, batch_iters=2000), encoding="utf-8")
        rce_files[kid] = p

    k01_emitted = subprocess.check_output([str(args.rce_bin), "emit", "rust", str(rce_files["k01_sha256_block"])], env=env, text=True)
    rt_src, _ = split_emitted_rust(k01_emitted)
    rt_path = work / "rce_rt.rs"
    rt_path.write_text(rt_src, encoding="utf-8")
    rlib_path = work / "librce_rt.rlib"

    # 2. Measure one-time librce_rt.rlib crate compilation (trials = 5)
    rlib_cjs, rlib_pjs, rlib_cnets, rlib_walls, rlib_digests = [], [], [], [], []
    for tr in range(args.rlib_trials):
        tr_dir = work / f"rlib_tr_{tr}"
        tr_dir.mkdir(parents=True, exist_ok=True)
        out_rlib = tr_dir / "librce_rt.rlib"
        ic_w, _ = meter.sample_sleep_power(0.08)
        m0 = meter.mark()
        subprocess.run(
            [rustc_bin, "--edition", "2024", "--crate-name", "rce_rt", "--crate-type=rlib", "-C", "opt-level=3", f"--remap-path-prefix={work}=/src", f"--remap-path-prefix={tr_dir}=/out", str(rt_path), "-o", str(out_rlib)],
            env=env, check=True, capture_output=True,
        )
        d = meter.since(m0)
        rlib_cjs.append(d["core_j"])
        rlib_pjs.append(d["pkg_j"])
        rlib_cnets.append(d["core_j"] - ic_w * d["wall_s"])
        rlib_walls.append(d["wall_s"])
        rlib_digests.append(hashlib.sha256(out_rlib.read_bytes()).hexdigest())
        if tr == 0:
            shutil.copy2(out_rlib, rlib_path)
        shutil.rmtree(tr_dir, ignore_errors=True)

    rlib_bytes = rlib_path.stat().st_size
    one_time_rlib = {
        "rce_rt_lines": len(rt_src.splitlines()),
        "rce_rt_bytes": len(rt_src.encode("utf-8")),
        "rce_rt_sha256": hashlib.sha256(rt_src.encode("utf-8")).hexdigest(),
        "rlib_bytes": rlib_bytes,
        "rlib_sha256": rlib_digests[0],
        "rlib_reproducible_across_trials": len(set(rlib_digests)) == 1,
        "trials": args.rlib_trials,
        "core_reported_j": round(statistics.median(rlib_cjs), 6),
        "core_iqr_j": [round(min(rlib_cjs), 6), round(max(rlib_cjs), 6)],
        "pkg_reported_j": round(statistics.median(rlib_pjs), 6),
        "core_net_reported_j": round(statistics.median(rlib_cnets), 6),
        "wall_s": round(statistics.median(rlib_walls), 6),
        "wall_ms": round(statistics.median(rlib_walls) * 1000.0, 3),
    }
    print(f"[One-Time Prelude] librce_rt.rlib: {rlib_bytes:,} B | {one_time_rlib['wall_ms']:.1f} ms | core={one_time_rlib['core_reported_j']:.4f} J | pkg={one_time_rlib['pkg_reported_j']:.3f} J", flush=True)

    # 3. Measure all 20 kernels with shared librce_rt.rlib (+ optional same-session monolithic & node js)
    TIER_RLIB = "rce check + emit rust -> rustc -O3 (shared .rlib)"
    TIER_MONO = "rce check + emit rust -> rustc -O3"
    TIER_JS = "rce check + 5-target emit (node js)"
    BATCH_ITERS = 2000

    kernel_rows: list[dict[str, Any]] = []
    mismatches = 0

    for idx, (kid, rce_file) in enumerate(rce_files.items(), 1):
        w4_k = w4_by_kid[kid]
        ref_csum = int(w4_k["verified_checksum_2000"])
        kdir = work / kid
        kdir.mkdir(parents=True, exist_ok=True)
        thin_bin = kdir / f"{kid}_rlib_bin"
        thin_meta = {"lines": 0, "bytes": 0, "artifact_bytes": 0, "stripped_bytes": 0}

        # 3a. Compile via shared librce_rt.rlib
        c_js, p_js, c_nets, walls = [], [], [], []
        for tr in range(args.compile_trials):
            ic_w, _ = meter.sample_sleep_power(0.06)
            m0 = meter.mark()
            subprocess.run([str(args.rce_bin), "check", str(rce_file)], env=env, check=True, capture_output=True)
            cp_em = subprocess.run([str(args.rce_bin), "emit", "rust", str(rce_file)], env=env, check=True, capture_output=True, text=True)
            _, thin_src = split_emitted_rust(cp_em.stdout)
            tmp_rs = kdir / f"tmp_thin_{tr}.rs"
            tmp_bin = kdir / f"tmp_thin_bin_{tr}"
            tmp_rs.write_text(thin_src, encoding="utf-8")
            subprocess.run(
                [rustc_bin, "--edition", "2024", "-C", "opt-level=3", f"--remap-path-prefix={kdir}=/src", "--extern", f"rce_rt={rlib_path}", str(tmp_rs), "-o", str(tmp_bin)],
                env=env, check=True, capture_output=True,
            )
            d = meter.since(m0)
            c_js.append(d["core_j"])
            p_js.append(d["pkg_j"])
            c_nets.append(d["core_j"] - ic_w * d["wall_s"])
            walls.append(d["wall_s"])
            if tr == 0:
                thin_meta["lines"] = len(thin_src.splitlines())
                thin_meta["bytes"] = len(thin_src.encode("utf-8"))
                thin_meta["artifact_bytes"] = tmp_bin.stat().st_size
                shutil.copy2(tmp_bin, thin_bin)
                st_bin = kdir / "tmp_strip"
                shutil.copy2(tmp_bin, st_bin)
                subprocess.run(["strip", str(st_bin)], env=env, capture_output=True)
                thin_meta["stripped_bytes"] = st_bin.stat().st_size if st_bin.exists() else thin_meta["artifact_bytes"]
                st_bin.unlink(missing_ok=True)
            tmp_rs.unlink(missing_ok=True)
            tmp_bin.unlink(missing_ok=True)

        # Execute thin_bin (2,000 seeds) and verify bit-exact checksum
        r_walls, r_cjs, r_pjs = [], [], []
        got_csum = -1
        for _ in range(args.run_trials):
            m0 = meter.mark()
            cp_run = subprocess.run([str(thin_bin), "run", "fuel", "500000000"], env=env, check=True, capture_output=True, text=True)
            d = meter.since(m0)
            m_em = re.search(r"emit\s+(\d+)", cp_run.stdout)
            assert m_em is not None, f"Missing emit in {kid}: {cp_run.stdout}"
            got_csum = int(m_em.group(1))
            if got_csum != ref_csum:
                mismatches += 1
                raise RuntimeError(f"F1 Checksum mismatch on {kid}: got {got_csum}, expected {ref_csum}")
            r_walls.append(d["wall_s"] / BATCH_ITERS)
            r_cjs.append(d["core_j"] / BATCH_ITERS)
            r_pjs.append(d["pkg_j"] / BATCH_ITERS)
        thin_bin.unlink(missing_ok=True)

        rlib_tier = {
            "compile_wall_s": round(statistics.median(walls), 6),
            "compile_wall_ms": round(statistics.median(walls) * 1000.0, 3),
            "compile_core_reported_j": round(statistics.median(c_js), 6),
            "compile_core_iqr_j": [round(min(c_js), 6), round(max(c_js), 6)],
            "compile_pkg_reported_j": round(statistics.median(p_js), 6),
            "compile_core_net_reported_j": round(statistics.median(c_nets), 6),
            "thin_rs_lines": thin_meta["lines"],
            "thin_rs_bytes": thin_meta["bytes"],
            "artifact_bytes": thin_meta["artifact_bytes"],
            "artifact_stripped_bytes": thin_meta["stripped_bytes"],
            "run_wall_s": statistics.median(r_walls),
            "run_core_reported_j": statistics.median(r_cjs),
            "run_core_iqr_j": [min(r_cjs), max(r_cjs)],
            "run_pkg_reported_j": statistics.median(r_pjs),
            "batch_iters": BATCH_ITERS,
            "verify_checksum_2000": got_csum,
        }

        # Optional same-session monolithic build check
        mono_same = None
        if args.measure_monolithic:
            mc_js, mp_js, m_walls = [], [], []
            for tr in range(args.mono_trials):
                m0 = meter.mark()
                subprocess.run([str(args.rce_bin), "check", str(rce_file)], env=env, check=True, capture_output=True)
                cp_m = subprocess.run([str(args.rce_bin), "emit", "rust", str(rce_file)], env=env, check=True, capture_output=True)
                mrs = kdir / f"mono_{tr}.rs"
                mbin = kdir / f"mono_bin_{tr}"
                mrs.write_bytes(cp_m.stdout)
                subprocess.run([rustc_bin, "--edition", "2024", "-C", "opt-level=3", str(mrs), "-o", str(mbin)], env=env, check=True, capture_output=True)
                d = meter.since(m0)
                mc_js.append(d["core_j"])
                mp_js.append(d["pkg_j"])
                m_walls.append(d["wall_s"])
                mrs.unlink(missing_ok=True)
                mbin.unlink(missing_ok=True)
            mono_same = {
                "compile_wall_s": round(statistics.median(m_walls), 6),
                "compile_core_reported_j": round(statistics.median(mc_js), 6),
                "compile_pkg_reported_j": round(statistics.median(mp_js), 6),
            }

        # Optional same-session node js check
        js_same = None
        if args.measure_node_js and node_bin:
            jc_js, jp_js, j_walls = [], [], []
            js_path = kdir / f"{kid}.js"
            for tr in range(3):
                m0 = meter.mark()
                for _ in range(3):
                    subprocess.run([str(args.rce_bin), "check", str(rce_file)], env=env, check=True, capture_output=True)
                    for tgt in ("core", "rust", "python", "js", "scala"):
                        cp_t = subprocess.run([str(args.rce_bin), "emit", tgt, str(rce_file)], env=env, check=True, capture_output=True)
                        if tr == 0 and tgt == "js":
                            js_path.write_bytes(cp_t.stdout)
                d = meter.since(m0)
                jc_js.append(d["core_j"] / 3.0)
                jp_js.append(d["pkg_j"] / 3.0)
                j_walls.append(d["wall_s"] / 3.0)
            jr_cjs, jr_pjs, jr_walls = [], [], []
            for _ in range(3):
                m0 = meter.mark()
                cp_j = subprocess.run([node_bin, str(js_path), "run", "fuel", "500000000"], env=env, check=True, capture_output=True, text=True)
                d = meter.since(m0)
                assert int(re.search(r"emit\s+(\d+)", cp_j.stdout).group(1)) == ref_csum
                jr_cjs.append(d["core_j"] / BATCH_ITERS)
                jr_pjs.append(d["pkg_j"] / BATCH_ITERS)
                jr_walls.append(d["wall_s"] / BATCH_ITERS)
            js_path.unlink(missing_ok=True)
            js_same = {
                "compile_wall_s": round(statistics.median(j_walls), 6),
                "compile_core_reported_j": round(statistics.median(jc_js), 6),
                "compile_pkg_reported_j": round(statistics.median(jp_js), 6),
                "run_wall_s": statistics.median(jr_walls),
                "run_core_reported_j": statistics.median(jr_cjs),
                "run_pkg_reported_j": statistics.median(jr_pjs),
            }

        w4_js = w4_k["tiers"][TIER_JS]
        w4_mono = w4_k["tiers"][TIER_MONO]
        rlib_cc = rlib_tier["compile_core_reported_j"]
        rlib_rc = rlib_tier["run_core_reported_j"]
        rt_one = one_time_rlib["core_reported_j"]

        pbs = {
            "marginal_vs_wave4_js": compute_payback(w4_js["compile_core_reported_j"], w4_js["run_core_reported_j"], rlib_cc, rlib_rc, TIER_JS, TIER_RLIB),
            "amortized20_vs_wave4_js": compute_payback(w4_js["compile_core_reported_j"], w4_js["run_core_reported_j"], rlib_cc + rt_one / 20.0, rlib_rc, TIER_JS, f"{TIER_RLIB} [+1/20 .rlib]"),
            "cold1kernel_vs_wave4_js": compute_payback(w4_js["compile_core_reported_j"], w4_js["run_core_reported_j"], rlib_cc + rt_one, rlib_rc, TIER_JS, f"{TIER_RLIB} [+full .rlib]"),
        }
        if js_same is not None:
            pbs["marginal_vs_samesession_js"] = compute_payback(js_same["compile_core_reported_j"], js_same["run_core_reported_j"], rlib_cc, rlib_rc, f"{TIER_JS} (same-session)", TIER_RLIB)
            pbs["amortized20_vs_samesession_js"] = compute_payback(js_same["compile_core_reported_j"], js_same["run_core_reported_j"], rlib_cc + rt_one / 20.0, rlib_rc, f"{TIER_JS} (same-session)", f"{TIER_RLIB} [+1/20 .rlib]")

        red_w4 = round(w4_mono["compile_core_reported_j"] / max(1e-9, rlib_cc), 2)
        red_same = round(mono_same["compile_core_reported_j"] / max(1e-9, rlib_cc), 2) if mono_same else None

        kernel_rows.append({
            "kernel_id": kid,
            "domain": w4_k["domain"],
            "description": w4_k["description"],
            "verified_checksum_2000": got_csum,
            "checksum_matches_wave4": True,
            "wave4_monolithic_compile_core_j": w4_mono["compile_core_reported_j"],
            "wave4_monolithic_compile_wall_s": w4_mono["compile_wall_s"],
            "wave4_monolithic_run_core_j": w4_mono["run_core_reported_j"],
            "wave4_js_compile_core_j": w4_js["compile_core_reported_j"],
            "wave4_js_run_core_j": w4_js["run_core_reported_j"],
            "shared_rlib_tier": rlib_tier,
            "samesession_monolithic": mono_same,
            "samesession_node_js": js_same,
            "compile_core_energy_reduction_vs_wave4_x": red_w4,
            "compile_core_energy_reduction_vs_samesession_x": red_same,
            "payback_horizons": pbs,
        })
        print(
            f"  [{idx:02d}/20] {kid}: csum={got_csum} | rlib_build={rlib_tier['compile_wall_ms']:.1f}ms ({rlib_cc:.3f}J core, {red_w4:.1f}x vs W4"
            + (f", {red_same:.1f}x same-sess" if red_same else "")
            + f") | N*_marg={pbs['marginal_vs_wave4_js']['n_star_invocations']}",
            flush=True,
        )

    idle_core_post_w, idle_pkg_post_w = meter.sample_sleep_power(2.0)
    load_post = os.getloadavg()

    med_cc = round(statistics.median(k["shared_rlib_tier"]["compile_core_reported_j"] for k in kernel_rows), 6)
    med_cp = round(statistics.median(k["shared_rlib_tier"]["compile_pkg_reported_j"] for k in kernel_rows), 6)
    med_cw = round(statistics.median(k["shared_rlib_tier"]["compile_wall_s"] for k in kernel_rows), 6)
    med_sz = int(statistics.median(k["shared_rlib_tier"]["artifact_bytes"] for k in kernel_rows))
    med_st_sz = int(statistics.median(k["shared_rlib_tier"]["artifact_stripped_bytes"] for k in kernel_rows))
    med_rc_uj = round(statistics.median(k["shared_rlib_tier"]["run_core_reported_j"] for k in kernel_rows) * 1e6, 4)
    med_rp_uj = round(statistics.median(k["shared_rlib_tier"]["run_pkg_reported_j"] for k in kernel_rows) * 1e6, 4)
    med_rw_ns = round(statistics.median(k["shared_rlib_tier"]["run_wall_s"] for k in kernel_rows) * 1e9, 2)

    w4_med_cc = w4["summary_by_tier"][TIER_MONO]["median_compile_core_j"]
    w4_med_cw = w4["summary_by_tier"][TIER_MONO]["median_compile_wall_s"]
    same_mono_med_cc = round(statistics.median(k["samesession_monolithic"]["compile_core_reported_j"] for k in kernel_rows), 6) if args.measure_monolithic else None
    same_mono_med_cw = round(statistics.median(k["samesession_monolithic"]["compile_wall_s"] for k in kernel_rows), 6) if args.measure_monolithic else None

    core_drift_pct = round(abs(idle_core_post_w - idle_core_pre_w) / max(1e-6, idle_core_pre_w) * 100.0, 2)
    pkg_drift_pct = round(abs(idle_pkg_post_w - idle_pkg_pre_w) / max(1e-6, idle_pkg_pre_w) * 100.0, 2)

    pb_keys = list(kernel_rows[0]["payback_horizons"].keys())
    pb_summary = {pk: summarize_paybacks([k["payback_horizons"][pk] for k in kernel_rows]) for pk in pb_keys}

    eff_reduction_x = round((same_mono_med_cc if same_mono_med_cc is not None else w4_med_cc) / max(1e-9, med_cc), 2)
    w4_reduction_x = round(w4_med_cc / max(1e-9, med_cc), 2)

    payload: dict[str, Any] = {
        "schema": "openie.rce_compile.e4_rlib_prelude.v1",
        "prereg_id": "rce-compile-wave5-e4-prelude-rlib-2026-11-23",
        "prereg_sha256": prereg_sha,
        "wave4_prereg_sha256": w4["prereg_sha256"],
        "recorded_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bench_root": "$BENCH_ROOT",
        "machine": {
            "os": f"{platform.system()} {platform.release()} {platform.machine()}",
            "cpu_model": detect_cpu_model(),
            "logical_cpus": os.cpu_count(),
            "pinned_cpu": meter.pin_cpu,
            "loadavg_pre": [round(x, 2) for x in load_pre],
            "loadavg_post": [round(x, 2) for x in load_post],
        },
        "provenance": {
            "basis": "reported",
            "regime": "B",
            "board_metered": False,
            "measured_j": None,
            "core_counter": f"{POWERCAP_CORE}/energy_uj",
            "package_counter": f"{POWERCAP_PKG}/energy_uj",
            "idle_core_pre_w": round(idle_core_pre_w, 3),
            "idle_core_post_w": round(idle_core_post_w, 3),
            "idle_core_drift_pct": core_drift_pct,
            "idle_pkg_pre_w": round(idle_pkg_pre_w, 3),
            "idle_pkg_post_w": round(idle_pkg_post_w, 3),
            "idle_pkg_drift_pct": pkg_drift_pct,
            "pkg_wraps": meter.pkg_wraps,
            "core_wraps": meter.core_wraps,
        },
        "toolchains": {
            "rustc": subprocess.check_output([rustc_bin, "--version"], text=True).splitlines()[0].strip(),
            "rce": subprocess.check_output([str(args.rce_bin), "version"], text=True).splitlines()[0].strip(),
            "node": subprocess.check_output([node_bin, "--version"], text=True).splitlines()[0].strip() if node_bin else "not_installed_on_crosscheck_host",
        },
        "one_time_rlib_build": one_time_rlib,
        "summary_15th_tier": {
            "tier_name": TIER_RLIB,
            "kernels_count": len(kernel_rows),
            "checksum_mismatches": mismatches,
            "median_compile_core_j": med_cc,
            "median_compile_pkg_j": med_cp,
            "median_compile_wall_s": med_cw,
            "median_compile_wall_ms": round(med_cw * 1000.0, 3),
            "median_artifact_bytes": med_sz,
            "median_artifact_stripped_bytes": med_st_sz,
            "median_run_core_uj": med_rc_uj,
            "median_run_pkg_uj": med_rp_uj,
            "median_run_ns": med_rw_ns,
            "wave4_monolithic_median_compile_core_j": w4_med_cc,
            "wave4_monolithic_median_compile_wall_s": w4_med_cw,
            "samesession_monolithic_median_compile_core_j": same_mono_med_cc,
            "samesession_monolithic_median_compile_wall_s": same_mono_med_cw,
            "compile_core_reduction_vs_wave4_x": w4_reduction_x,
            "compile_wall_speedup_vs_wave4_x": round(w4_med_cw / max(1e-9, med_cw), 2),
            "compile_core_reduction_vs_samesession_x": eff_reduction_x if same_mono_med_cc is not None else None,
            "compile_wall_speedup_vs_samesession_x": round(same_mono_med_cw / max(1e-9, med_cw), 2) if same_mono_med_cw is not None else None,
            "total_20kernel_suite_monolithic_wave4_core_j": round(sum(k["wave4_monolithic_compile_core_j"] for k in kernel_rows), 4),
            "total_20kernel_suite_rlib_incl_onetime_core_j": round(one_time_rlib["core_reported_j"] + sum(k["shared_rlib_tier"]["compile_core_reported_j"] for k in kernel_rows), 4),
        },
        "payback_horizon_summary": pb_summary,
        "falsifiers_check": {
            "F1_checksum_mismatch_triggered": mismatches > 0,
            "F2_less_than_10x_compile_reduction_triggered": not (w4_reduction_x >= 10.0 and eff_reduction_x >= 10.0),
            "F6_idle_pkg_drift_gt_10pct_flag": pkg_drift_pct > 10.0,
            "F6_idle_core_drift_gt_10pct_flag": core_drift_pct > 10.0,
        },
        "kernels": kernel_rows,
    }
    if args.crosscheck_json and args.crosscheck_json.exists():
        cc_data = json.loads(args.crosscheck_json.read_text(encoding="utf-8"))
        payload["quiet_host_crosscheck"] = {
            "machine": cc_data["machine"],
            "provenance": cc_data["provenance"],
            "one_time_rlib_build": cc_data["one_time_rlib_build"],
            "summary_15th_tier": cc_data["summary_15th_tier"],
            "falsifiers_check": cc_data["falsifiers_check"],
        }
    return payload


def main() -> None:
    ap = argparse.ArgumentParser(description="Wave 5 E4-Prelude librce_rt.rlib benchmark runner")
    ap.add_argument("--prereg", required=True, type=Path)
    ap.add_argument("--prereg-sha256", required=True, type=Path)
    ap.add_argument("--wave4-e4-json", required=True, type=Path)
    ap.add_argument("--rce-bin", required=True, type=Path)
    ap.add_argument("--rustc-bin", default="", type=str)
    ap.add_argument("--work-dir", required=True, type=Path)
    ap.add_argument("--out-json", required=True, type=Path)
    ap.add_argument("--crosscheck-json", default=None, type=Path)
    ap.add_argument("--pin-cpu", default=0, type=int)
    ap.add_argument("--rlib-trials", default=5, type=int)
    ap.add_argument("--compile-trials", default=5, type=int)
    ap.add_argument("--run-trials", default=5, type=int)
    ap.add_argument("--mono-trials", default=2, type=int)
    ap.add_argument("--measure-monolithic", action="store_true")
    ap.add_argument("--measure-node-js", action="store_true")
    args = ap.parse_args()

    res = run_suite(args)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
    print(f"[DONE] Wrote {args.out_json}", flush=True)


if __name__ == "__main__":
    main()
