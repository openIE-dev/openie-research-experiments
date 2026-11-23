#!/usr/bin/env python3
"""
GE-H5: Multi-Actor Q32.32 Spatial-Grid Arena Scaling Benchmark (500 Ticks x 10 Actor Counts x 5 Tiers).

Tiers:
  1. rce_python3    : `rce emit python` (CPython 3)
  2. rce_nodejs_v22 : `rce emit js` (Node.js v22)
  3. form_wasm32_v8 : Form-projected Rust `wasm32-unknown-unknown` (-C opt-level=3) on Node.js V8
  4. form_cpp20_o3  : Form-projected C++20 (`clang++ -std=c++20 -O3`)
  5. form_rust_o3   : Form-projected native Rust (`rustc -C opt-level=3`)

Telemetry:
  Linux SATB L2 `/sys/class/powercap/intel-rapl:0/energy_uj` (package-0) and `intel-rapl:0:0/energy_uj` (core).
  `measured_j = None`, `board_metered = False`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import platform
import shutil
import statistics as st
import struct
import subprocess
import sys
import time

ACTOR_COUNTS = [64, 128, 256, 300, 350, 500, 1000, 2500, 5000, 10000]
TICKS = 500


class RaplReader:
    def __init__(self) -> None:
        self.pkg_p = pathlib.Path("/sys/class/powercap/intel-rapl:0/energy_uj")
        self.pkg_m = pathlib.Path("/sys/class/powercap/intel-rapl:0/max_energy_range_uj")
        self.core_p = pathlib.Path("/sys/class/powercap/intel-rapl:0:0/energy_uj")
        self.core_m = pathlib.Path("/sys/class/powercap/intel-rapl:0:0/max_energy_range_uj")
        self.ok = self.pkg_p.exists() and os.access(self.pkg_p, os.R_OK)
        self.pkg_max = int(self.pkg_m.read_text().strip()) if self.ok and self.pkg_m.exists() else 0
        self.core_ok = self.core_p.exists() and os.access(self.core_p, os.R_OK)
        self.core_max = int(self.core_m.read_text().strip()) if self.core_ok and self.core_m.exists() else 0

    def read(self) -> tuple[int | None, int | None]:
        pkg = int(self.pkg_p.read_text().strip()) if self.ok else None
        core = int(self.core_p.read_text().strip()) if self.core_ok else None
        return pkg, core

    @staticmethod
    def diff(a: int | None, b: int | None, wrap: int) -> int | None:
        if a is None or b is None:
            return None
        if b >= a:
            return b - a
        return (wrap - a) + b if wrap > 0 else 0


PY_DRIVER = r'''#!/usr/bin/env python3
import hashlib, json, struct, sys, time
sys.path.insert(0, sys.argv[1])
import emitted_actor as m

N = int(sys.argv[2])
TICKS = int(sys.argv[3])
ONE = 4294967296
SHIFT64 = 64 * ONE

def splitmix64(x):
    z = (x + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
    return (z ^ (z >> 31)) & 0xFFFFFFFFFFFFFFFF

ef_init = [("x0", ("int", "i64"), None), ("y0", ("int", "i64"), None)]
ef_step = [
    ("cell_pop", ("int", "i64"), None),
    ("near_dx", ("int", "i64"), None),
    ("near_dy", ("int", "i64"), None),
    ("target_dx", ("int", "i64"), None),
    ("target_dy", ("int", "i64"), None),
]

actors = []
for i in range(N):
    h = splitmix64(0x2026112347454835 ^ i)
    x0 = ((h & 0xFFFF) - 32768) * 7669584
    y0 = (((h >> 16) & 0xFFFF) - 32768) * 7669584
    m.fuel_reset()
    s = m.initial_state()
    ev = m.construct("InitActor", ef_init, [("x0", m.lit(x0)), ("y0", m.lit(y0))])
    s, _ = m.delta(s, ev)
    actors.append(s)

sys.stdout.write("READY\n")
sys.stdout.flush()
line = sys.stdin.readline()

tick_ms = []
lit = m.lit
construct = m.construct
delta = m.delta
fuel_reset = m.fuel_reset

for t in range(1, TICKS + 1):
    t0 = time.perf_counter()
    cell_pop = [0] * 256
    cell_ux = [0] * 256
    cell_uy = [0] * 256
    xs = [0] * N
    ys = [0] * N
    uxs = [0] * N
    uys = [0] * N
    cs = [0] * N
    for i in range(N):
        flds = actors[i][0][1]
        xi = flds[0][1].v
        yi = flds[1][1].v
        xs[i] = xi
        ys[i] = yi
        gx = ((xi >> 32) + 64) >> 3
        if gx < 0: gx = 0
        elif gx > 15: gx = 15
        gy = ((yi >> 32) + 64) >> 3
        if gy < 0: gy = 0
        elif gy > 15: gy = 15
        c = (gy << 4) | gx
        cs[i] = c
        ux = (xi + SHIFT64) >> 16
        uy = (yi + SHIFT64) >> 16
        uxs[i] = ux
        uys[i] = uy
        cell_pop[c] += 1
        cell_ux[c] += ux
        cell_uy[c] += uy

    bx = (((t * 3) % 128) - 64) * (ONE >> 1)
    by = (((t * 5) % 128) - 64) * (ONE >> 1)

    for i in range(N):
        c = cs[i]
        cp = cell_pop[c]
        if cp > 1:
            other_ux = (cell_ux[c] - uxs[i]) // (cp - 1)
            other_uy = (cell_uy[c] - uys[i]) // (cp - 1)
            ndx = (other_ux - uxs[i]) << 16
            ndy = (other_uy - uys[i]) << 16
        else:
            ndx = 0
            ndy = 0
        tdx = bx - xs[i]
        tdy = by - ys[i]
        fuel_reset()
        ev = construct("StepActor", ef_step, [
            ("cell_pop", lit(cp)),
            ("near_dx", lit(ndx)),
            ("near_dy", lit(ndy)),
            ("target_dx", lit(tdx)),
            ("target_dy", lit(tdy)),
        ])
        actors[i], _ = delta(actors[i], ev)
    tick_ms.append((time.perf_counter() - t0) * 1000.0)

buf = bytearray()
for i in range(N):
    flds = actors[i][0][1]
    buf += struct.pack("<9q", *(flds[k][1].v for k in range(9)))
sha = hashlib.sha256(buf).hexdigest()
sys.stdout.write("DONE\t" + json.dumps({"sha256": sha, "tick_ms": tick_ms, "loops": 1}) + "\n")
sys.stdout.flush()
'''

JS_DRIVER = r'''import crypto from "node:crypto";
import readline from "node:readline";
import { initialState, delta, construct, fuelReset, Int } from "./emitted_actor.mjs";

const N = parseInt(process.argv[2], 10);
const TICKS = parseInt(process.argv[3], 10);
const ONE = 4294967296n;
const SHIFT64 = 64n * ONE;
const MASK64 = 0xFFFFFFFFFFFFFFFFn;

function splitmix64(x) {
  let z = (x + 0x9E3779B97F4A7C15n) & MASK64;
  z = ((z ^ (z >> 30n)) * 0xBF58476D1CE4E5B9n) & MASK64;
  z = ((z ^ (z >> 27n)) * 0x94D049BB133111EBn) & MASK64;
  return (z ^ (z >> 31n)) & MASK64;
}

const efInit = [["x0", ["int", "i64"], null], ["y0", ["int", "i64"], null]];
const efStep = [
  ["cell_pop", ["int", "i64"], null],
  ["near_dx", ["int", "i64"], null],
  ["near_dy", ["int", "i64"], null],
  ["target_dx", ["int", "i64"], null],
  ["target_dy", ["int", "i64"], null],
];
const lit = (v) => new Int(v, "i64");

const actors = new Array(N);
for (let i = 0; i < N; i++) {
  const h = splitmix64(0x2026112347454835n ^ BigInt(i));
  const x0 = ((h & 0xFFFFn) - 32768n) * 7669584n;
  const y0 = (((h >> 16n) & 0xFFFFn) - 32768n) * 7669584n;
  fuelReset();
  let s = initialState();
  const ev = construct("InitActor", efInit, [["x0", lit(x0)], ["y0", lit(y0)]]);
  [s] = delta(s, ev);
  actors[i] = s;
}

const rl = readline.createInterface({ input: process.stdin, terminal: false });
process.stdout.write("READY\n");
rl.once("line", () => {
  const tickMs = [];
  const xs = new BigInt64Array(N);
  const ys = new BigInt64Array(N);
  const uxs = new BigInt64Array(N);
  const uys = new BigInt64Array(N);
  const cs = new Int32Array(N);
  const cellPop = new Int32Array(256);
  const cellUx = new BigInt64Array(256);
  const cellUy = new BigInt64Array(256);

  for (let t = 1; t <= TICKS; t++) {
    const t0 = performance.now();
    cellPop.fill(0);
    cellUx.fill(0n);
    cellUy.fill(0n);
    for (let i = 0; i < N; i++) {
      const flds = actors[i][0][1];
      const xi = flds[0][1].v;
      const yi = flds[1][1].v;
      xs[i] = xi;
      ys[i] = yi;
      let gx = Number((xi >> 32n) + 64n) >> 3;
      if (gx < 0) gx = 0; else if (gx > 15) gx = 15;
      let gy = Number((yi >> 32n) + 64n) >> 3;
      if (gy < 0) gy = 0; else if (gy > 15) gy = 15;
      const c = (gy << 4) | gx;
      cs[i] = c;
      const ux = (xi + SHIFT64) >> 16n;
      const uy = (yi + SHIFT64) >> 16n;
      uxs[i] = ux;
      uys[i] = uy;
      cellPop[c] += 1;
      cellUx[c] += ux;
      cellUy[c] += uy;
    }
    const bx = BigInt(((t * 3) % 128) - 64) * (ONE >> 1n);
    const by = BigInt(((t * 5) % 128) - 64) * (ONE >> 1n);
    for (let i = 0; i < N; i++) {
      const c = cs[i];
      const cp = BigInt(cellPop[c]);
      let ndx = 0n, ndy = 0n;
      if (cp > 1n) {
        const oux = (cellUx[c] - uxs[i]) / (cp - 1n);
        const ouy = (cellUy[c] - uys[i]) / (cp - 1n);
        ndx = (oux - uxs[i]) << 16n;
        ndy = (ouy - uys[i]) << 16n;
      }
      const tdx = bx - xs[i];
      const tdy = by - ys[i];
      fuelReset();
      const ev = construct("StepActor", efStep, [
        ["cell_pop", lit(cp)],
        ["near_dx", lit(ndx)],
        ["near_dy", lit(ndy)],
        ["target_dx", lit(tdx)],
        ["target_dy", lit(tdy)],
      ]);
      [actors[i]] = delta(actors[i], ev);
    }
    tickMs.push(performance.now() - t0);
  }
  const buf = Buffer.alloc(N * 72);
  let off = 0;
  for (let i = 0; i < N; i++) {
    const flds = actors[i][0][1];
    for (let k = 0; k < 9; k++) {
      buf.writeBigInt64LE(flds[k][1].v, off);
      off += 8;
    }
  }
  const sha = crypto.createHash("sha256").update(buf).digest("hex");
  process.stdout.write("DONE\t" + JSON.stringify({ sha256: sha, tick_ms: tickMs, loops: 1 }) + "\n");
  rl.close();
  process.exit(0);
});
'''

RUST_SRC = r'''// Form-projected native Rust for ge_h5_actor_arena.rce
use std::env;
use std::io::{self, BufRead, Write};
use std::time::Instant;

const ONE: i64 = 4294967296;
const BOUND: i64 = 257698037760;
const CHASE_DIST: i64 = 68719476736;
const AVOID_SPEED: i64 = 67108864;
const CHASE_SPEED: i64 = 100663296;
const PATROL_SPEED: i64 = 50331648;
const DRAG_NUM: i64 = 984;
const DRAG_DEN: i64 = 1024;
const SHIFT64: i64 = 64 * ONE;

#[derive(Clone, Copy)]
struct Actor {
    x: i64,
    y: i64,
    vx: i64,
    vy: i64,
    fsm: i64,
    cooldown: i64,
    pulses: i64,
    energy: i64,
    ticks: i64,
}

#[inline(always)]
fn sign_q(v: i64) -> i64 {
    if v > 0 { 1 } else if v < 0 { -1 } else { 0 }
}

#[inline(always)]
fn step_actor(a: &mut Actor, cp: i64, ndx: i64, ndy: i64, tdx: i64, tdy: i64) {
    a.ticks += 1;
    if a.cooldown > 0 {
        a.cooldown -= 1;
    }
    let manhattan_tgt = tdx.abs() + tdy.abs();
    let mut ax: i64 = 0;
    let mut ay: i64 = 0;

    if cp >= 3 {
        a.fsm = 2;
        ax = -sign_q(ndx) * AVOID_SPEED;
        ay = -sign_q(ndy) * AVOID_SPEED;
        if a.cooldown == 0 && a.energy >= 10 {
            a.cooldown = 12;
            a.pulses += 1;
            a.energy -= 10;
        }
    } else if manhattan_tgt < CHASE_DIST {
        a.fsm = 1;
        ax = sign_q(tdx) * CHASE_SPEED;
        ay = sign_q(tdy) * CHASE_SPEED;
        if manhattan_tgt < (CHASE_DIST / 4) && a.cooldown == 0 && a.energy >= 15 {
            a.cooldown = 16;
            a.pulses += 1;
            a.energy -= 15;
        }
    } else {
        a.fsm = 0;
        let phase = a.ticks % 64;
        if phase < 16 {
            ax = PATROL_SPEED;
        } else if phase < 32 {
            ay = PATROL_SPEED;
        } else if phase < 48 {
            ax = -PATROL_SPEED;
        } else {
            ay = -PATROL_SPEED;
        }
        if a.energy < 1000 {
            a.energy += 1;
        }
    }

    a.vx = ((a.vx + ax) * DRAG_NUM) / DRAG_DEN;
    a.vy = ((a.vy + ay) * DRAG_NUM) / DRAG_DEN;
    let nx = a.x + a.vx;
    let ny = a.y + a.vy;

    if nx > BOUND {
        a.x = (2 * BOUND) - nx;
        a.vx = -a.vx;
    } else if nx < -BOUND {
        a.x = (-2 * BOUND) - nx;
        a.vx = -a.vx;
    } else {
        a.x = nx.clamp(-BOUND, BOUND);
    }

    if ny > BOUND {
        a.y = (2 * BOUND) - ny;
        a.vy = -a.vy;
    } else if ny < -BOUND {
        a.y = (-2 * BOUND) - ny;
        a.vy = -a.vy;
    } else {
        a.y = ny.clamp(-BOUND, BOUND);
    }
}

fn splitmix64(x: u64) -> u64 {
    let mut z = x.wrapping_add(0x9E3779B97F4A7C15);
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58476D1CE4E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D049BB133111EB);
    z ^ (z >> 31)
}

fn init_actors(n: usize) -> Vec<Actor> {
    let mut out = Vec::with_capacity(n);
    for i in 0..n {
        let h = splitmix64(0x2026112347454835 ^ (i as u64));
        let x0 = (((h & 0xFFFF) as i64) - 32768) * 7669584;
        let y0 = ((((h >> 16) & 0xFFFF) as i64) - 32768) * 7669584;
        out.push(Actor {
            x: x0.clamp(-BOUND, BOUND),
            y: y0.clamp(-BOUND, BOUND),
            vx: 33554432,
            vy: 33554432,
            fsm: 0,
            cooldown: 0,
            pulses: 0,
            energy: 1000,
            ticks: 0,
        });
    }
    out
}

fn main() {
    let args: Vec<String> = env::args().collect();
    let n: usize = args[1].parse().unwrap();
    let ticks: usize = args[2].parse().unwrap();
    let loops: usize = args.get(3).and_then(|s| s.parse().ok()).unwrap_or(1);

    let init_state = init_actors(n);
    let mut actors = init_state.clone();
    let mut uxs = vec![0i64; n];
    let mut uys = vec![0i64; n];
    let mut cs = vec![0usize; n];

    let stdout = io::stdout();
    {
        let mut h = stdout.lock();
        writeln!(h, "READY").unwrap();
        h.flush().unwrap();
    }
    let mut line = String::new();
    io::stdin().lock().read_line(&mut line).unwrap();

    let mut tick_ms = Vec::with_capacity(ticks);
    for rep in 0..loops {
        actors.copy_from_slice(&init_state);
        for t in 1..=ticks {
            let t0 = Instant::now();
            let mut cell_pop = [0i64; 256];
            let mut cell_ux = [0i64; 256];
            let mut cell_uy = [0i64; 256];

            for i in 0..n {
                let xi = actors[i].x;
                let yi = actors[i].y;
                let gx = (((xi >> 32) + 64) >> 3).clamp(0, 15) as usize;
                let gy = (((yi >> 32) + 64) >> 3).clamp(0, 15) as usize;
                let c = (gy << 4) | gx;
                cs[i] = c;
                let ux = (xi + SHIFT64) >> 16;
                let uy = (yi + SHIFT64) >> 16;
                uxs[i] = ux;
                uys[i] = uy;
                cell_pop[c] += 1;
                cell_ux[c] += ux;
                cell_uy[c] += uy;
            }
            let bx = ((((t * 3) % 128) as i64) - 64) * (ONE >> 1);
            let by = ((((t * 5) % 128) as i64) - 64) * (ONE >> 1);

            for i in 0..n {
                let c = cs[i];
                let cp = cell_pop[c];
                let (ndx, ndy) = if cp > 1 {
                    let oux = (cell_ux[c] - uxs[i]) / (cp - 1);
                    let ouy = (cell_uy[c] - uys[i]) / (cp - 1);
                    ((oux - uxs[i]) << 16, (ouy - uys[i]) << 16)
                } else {
                    (0, 0)
                };
                let tdx = bx - actors[i].x;
                let tdy = by - actors[i].y;
                step_actor(&mut actors[i], cp, ndx, ndy, tdx, tdy);
            }
            if rep == loops - 1 {
                tick_ms.push(t0.elapsed().as_secs_f64() * 1000.0);
            }
        }
    }

    let mut raw = Vec::with_capacity(n * 72);
    for a in &actors {
        for v in [a.x, a.y, a.vx, a.vy, a.fsm, a.cooldown, a.pulses, a.energy, a.ticks] {
            raw.extend_from_slice(&v.to_le_bytes());
        }
    }
    // Emit hex bytes for Python SHA-256 verification or write raw state file
    let out_path = &args[4];
    std::fs::write(out_path, &raw).unwrap();
    print!("DONE\t{{\"loops\":{},\"tick_ms\":[", loops);
    for (idx, v) in tick_ms.iter().enumerate() {
        if idx > 0 { print!(","); }
        print!("{:.6}", v);
    }
    println!("]}}");
}
'''

CPP_SRC = r'''// Form-projected C++20 (-O3) for ge_h5_actor_arena.rce
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

static constexpr int64_t ONE = 4294967296LL;
static constexpr int64_t BOUND = 257698037760LL;
static constexpr int64_t CHASE_DIST = 68719476736LL;
static constexpr int64_t AVOID_SPEED = 67108864LL;
static constexpr int64_t CHASE_SPEED = 100663296LL;
static constexpr int64_t PATROL_SPEED = 50331648LL;
static constexpr int64_t DRAG_NUM = 984LL;
static constexpr int64_t DRAG_DEN = 1024LL;
static constexpr int64_t SHIFT64 = 64LL * ONE;

struct Actor {
    int64_t x, y, vx, vy, fsm, cooldown, pulses, energy, ticks;
};

static inline int64_t sign_q(int64_t v) {
    return (v > 0) ? 1 : ((v < 0) ? -1 : 0);
}

static inline int64_t abs_q(int64_t v) {
    return (v < 0) ? -v : v;
}

static inline void step_actor(Actor& a, int64_t cp, int64_t ndx, int64_t ndy, int64_t tdx, int64_t tdy) {
    a.ticks += 1;
    if (a.cooldown > 0) a.cooldown -= 1;

    int64_t manhattan_tgt = abs_q(tdx) + abs_q(tdy);
    int64_t ax = 0, ay = 0;

    if (cp >= 3) {
        a.fsm = 2;
        ax = -sign_q(ndx) * AVOID_SPEED;
        ay = -sign_q(ndy) * AVOID_SPEED;
        if (a.cooldown == 0 && a.energy >= 10) {
            a.cooldown = 12;
            a.pulses += 1;
            a.energy -= 10;
        }
    } else if (manhattan_tgt < CHASE_DIST) {
        a.fsm = 1;
        ax = sign_q(tdx) * CHASE_SPEED;
        ay = sign_q(tdy) * CHASE_SPEED;
        if (manhattan_tgt < (CHASE_DIST / 4) && a.cooldown == 0 && a.energy >= 15) {
            a.cooldown = 16;
            a.pulses += 1;
            a.energy -= 15;
        }
    } else {
        a.fsm = 0;
        int64_t phase = a.ticks % 64;
        if (phase < 16) ax = PATROL_SPEED;
        else if (phase < 32) ay = PATROL_SPEED;
        else if (phase < 48) ax = -PATROL_SPEED;
        else ay = -PATROL_SPEED;
        if (a.energy < 1000) a.energy += 1;
    }

    a.vx = ((a.vx + ax) * DRAG_NUM) / DRAG_DEN;
    a.vy = ((a.vy + ay) * DRAG_NUM) / DRAG_DEN;
    int64_t nx = a.x + a.vx;
    int64_t ny = a.y + a.vy;

    if (nx > BOUND) { a.x = (2 * BOUND) - nx; a.vx = -a.vx; }
    else if (nx < -BOUND) { a.x = (-2 * BOUND) - nx; a.vx = -a.vx; }
    else { a.x = std::clamp(nx, -BOUND, BOUND); }

    if (ny > BOUND) { a.y = (2 * BOUND) - ny; a.vy = -a.vy; }
    else if (ny < -BOUND) { a.y = (-2 * BOUND) - ny; a.vy = -a.vy; }
    else { a.y = std::clamp(ny, -BOUND, BOUND); }
}

static uint64_t splitmix64(uint64_t x) {
    uint64_t z = x + 0x9E3779B97F4A7C15ULL;
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}

int main(int argc, char** argv) {
    size_t n = std::stoul(argv[1]);
    size_t ticks = std::stoul(argv[2]);
    size_t loops = (argc > 3) ? std::stoul(argv[3]) : 1;
    std::string out_path = argv[4];

    std::vector<Actor> init_state(n);
    for (size_t i = 0; i < n; ++i) {
        uint64_t h = splitmix64(0x2026112347454835ULL ^ static_cast<uint64_t>(i));
        int64_t x0 = (static_cast<int64_t>(h & 0xFFFFULL) - 32768LL) * 7669584LL;
        int64_t y0 = (static_cast<int64_t>((h >> 16) & 0xFFFFULL) - 32768LL) * 7669584LL;
        init_state[i] = Actor{std::clamp(x0, -BOUND, BOUND), std::clamp(y0, -BOUND, BOUND), 33554432LL, 33554432LL, 0, 0, 0, 1000, 0};
    }
    std::vector<Actor> actors(n);
    std::vector<int64_t> uxs(n), uys(n);
    std::vector<size_t> cs(n);

    std::printf("READY\n");
    std::fflush(stdout);
    std::string line;
    std::getline(std::cin, line);

    std::vector<double> tick_ms;
    tick_ms.reserve(ticks);

    for (size_t rep = 0; rep < loops; ++rep) {
        std::memcpy(actors.data(), init_state.data(), n * sizeof(Actor));
        for (size_t t = 1; t <= ticks; ++t) {
            auto t0 = std::chrono::steady_clock::now();
            int64_t cell_pop[256] = {0};
            int64_t cell_ux[256] = {0};
            int64_t cell_uy[256] = {0};

            for (size_t i = 0; i < n; ++i) {
                int64_t xi = actors[i].x;
                int64_t yi = actors[i].y;
                int64_t gx = std::clamp<int64_t>(((xi >> 32) + int64_t(64)) >> 3, 0, 15);
                int64_t gy = std::clamp<int64_t>(((yi >> 32) + int64_t(64)) >> 3, 0, 15);
                size_t c = (static_cast<size_t>(gy) << 4) | static_cast<size_t>(gx);
                cs[i] = c;
                int64_t ux = (xi + SHIFT64) >> 16;
                int64_t uy = (yi + SHIFT64) >> 16;
                uxs[i] = ux;
                uys[i] = uy;
                cell_pop[c] += 1;
                cell_ux[c] += ux;
                cell_uy[c] += uy;
            }
            int64_t bx = (static_cast<int64_t>((t * 3) % 128) - 64LL) * (ONE >> 1);
            int64_t by = (static_cast<int64_t>((t * 5) % 128) - 64LL) * (ONE >> 1);

            for (size_t i = 0; i < n; ++i) {
                size_t c = cs[i];
                int64_t cp = cell_pop[c];
                int64_t ndx = 0, ndy = 0;
                if (cp > 1) {
                    int64_t oux = (cell_ux[c] - uxs[i]) / (cp - 1);
                    int64_t ouy = (cell_uy[c] - uys[i]) / (cp - 1);
                    ndx = (oux - uxs[i]) << 16;
                    ndy = (ouy - uys[i]) << 16;
                }
                step_actor(actors[i], cp, ndx, ndy, bx - actors[i].x, by - actors[i].y);
            }
            if (rep + 1 == loops) {
                auto t1 = std::chrono::steady_clock::now();
                tick_ms.push_back(std::chrono::duration<double, std::milli>(t1 - t0).count());
            }
        }
    }
    std::ofstream ofs(out_path, std::ios::binary);
    ofs.write(reinterpret_cast<const char*>(actors.data()), static_cast<std::streamsize>(n * sizeof(Actor)));
    ofs.close();

    std::printf("DONE\t{\"loops\":%zu,\"tick_ms\":[", loops);
    for (size_t i = 0; i < tick_ms.size(); ++i) {
        if (i > 0) std::printf(",");
        std::printf("%.6f", tick_ms[i]);
    }
    std::printf("]}\n");
    std::fflush(stdout);
    return 0;
}
'''

WASM_LIB_RS = r'''#![no_std]

#[panic_handler]
fn panic(_info: &core::panic::PanicInfo) -> ! {
    loop {}
}

const ONE: i64 = 4294967296;
const BOUND: i64 = 257698037760;
const CHASE_DIST: i64 = 68719476736;
const AVOID_SPEED: i64 = 67108864;
const CHASE_SPEED: i64 = 100663296;
const PATROL_SPEED: i64 = 50331648;
const DRAG_NUM: i64 = 984;
const DRAG_DEN: i64 = 1024;
const SHIFT64: i64 = 64 * ONE;
const MAX_N: usize = 10000;

#[repr(C)]
#[derive(Clone, Copy)]
pub struct Actor {
    x: i64, y: i64, vx: i64, vy: i64, fsm: i64, cooldown: i64, pulses: i64, energy: i64, ticks: i64,
}

static mut ACTORS: [Actor; MAX_N] = [Actor { x: 0, y: 0, vx: 0, vy: 0, fsm: 0, cooldown: 0, pulses: 0, energy: 0, ticks: 0 }; MAX_N];
static mut UXS: [i64; MAX_N] = [0; MAX_N];
static mut UYS: [i64; MAX_N] = [0; MAX_N];
static mut CS: [usize; MAX_N] = [0; MAX_N];

#[inline(always)]
fn sign_q(v: i64) -> i64 { if v > 0 { 1 } else if v < 0 { -1 } else { 0 } }
#[inline(always)]
fn clamp_q(v: i64, lo: i64, hi: i64) -> i64 { if v < lo { lo } else if v > hi { hi } else { v } }

fn splitmix64(x: u64) -> u64 {
    let mut z = x.wrapping_add(0x9E3779B97F4A7C15);
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58476D1CE4E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D049BB133111EB);
    z ^ (z >> 31)
}

#[no_mangle]
pub extern "C" fn wasm_init(n: usize) {
    unsafe {
        for i in 0..n {
            let h = splitmix64(0x2026112347454835 ^ (i as u64));
            let x0 = (((h & 0xFFFF) as i64) - 32768) * 7669584;
            let y0 = ((((h >> 16) & 0xFFFF) as i64) - 32768) * 7669584;
            ACTORS[i] = Actor {
                x: clamp_q(x0, -BOUND, BOUND),
                y: clamp_q(y0, -BOUND, BOUND),
                vx: 33554432,
                vy: 33554432,
                fsm: 0,
                cooldown: 0,
                pulses: 0,
                energy: 1000,
                ticks: 0,
            };
        }
    }
}

#[no_mangle]
pub extern "C" fn wasm_step(n: usize, t: usize) {
    unsafe {
        let mut cell_pop = [0i64; 256];
        let mut cell_ux = [0i64; 256];
        let mut cell_uy = [0i64; 256];

        for i in 0..n {
            let xi = ACTORS[i].x;
            let yi = ACTORS[i].y;
            let gx = clamp_q(((xi >> 32) + 64) >> 3, 0, 15) as usize;
            let gy = clamp_q(((yi >> 32) + 64) >> 3, 0, 15) as usize;
            let c = (gy << 4) | gx;
            CS[i] = c;
            let ux = (xi + SHIFT64) >> 16;
            let uy = (yi + SHIFT64) >> 16;
            UXS[i] = ux;
            UYS[i] = uy;
            cell_pop[c] += 1;
            cell_ux[c] += ux;
            cell_uy[c] += uy;
        }
        let bx = ((((t * 3) % 128) as i64) - 64) * (ONE >> 1);
        let by = ((((t * 5) % 128) as i64) - 64) * (ONE >> 1);

        for i in 0..n {
            let c = CS[i];
            let cp = cell_pop[c];
            let (ndx, ndy) = if cp > 1 {
                let oux = (cell_ux[c] - UXS[i]) / (cp - 1);
                let ouy = (cell_uy[c] - UYS[i]) / (cp - 1);
                ((oux - UXS[i]) << 16, (ouy - UYS[i]) << 16)
            } else { (0, 0) };
            let a = &mut ACTORS[i];
            let tdx = bx - a.x;
            let tdy = by - a.y;
            a.ticks += 1;
            if a.cooldown > 0 { a.cooldown -= 1; }
            let manhattan_tgt = tdx.abs() + tdy.abs();
            let mut ax: i64 = 0;
            let mut ay: i64 = 0;
            if cp >= 3 {
                a.fsm = 2;
                ax = -sign_q(ndx) * AVOID_SPEED;
                ay = -sign_q(ndy) * AVOID_SPEED;
                if a.cooldown == 0 && a.energy >= 10 {
                    a.cooldown = 12; a.pulses += 1; a.energy -= 10;
                }
            } else if manhattan_tgt < CHASE_DIST {
                a.fsm = 1;
                ax = sign_q(tdx) * CHASE_SPEED;
                ay = sign_q(tdy) * CHASE_SPEED;
                if manhattan_tgt < (CHASE_DIST / 4) && a.cooldown == 0 && a.energy >= 15 {
                    a.cooldown = 16; a.pulses += 1; a.energy -= 15;
                }
            } else {
                a.fsm = 0;
                let phase = a.ticks % 64;
                if phase < 16 { ax = PATROL_SPEED; }
                else if phase < 32 { ay = PATROL_SPEED; }
                else if phase < 48 { ax = -PATROL_SPEED; }
                else { ay = -PATROL_SPEED; }
                if a.energy < 1000 { a.energy += 1; }
            }
            a.vx = ((a.vx + ax) * DRAG_NUM) / DRAG_DEN;
            a.vy = ((a.vy + ay) * DRAG_NUM) / DRAG_DEN;
            let nx = a.x + a.vx;
            let ny = a.y + a.vy;
            if nx > BOUND { a.x = (2 * BOUND) - nx; a.vx = -a.vx; }
            else if nx < -BOUND { a.x = (-2 * BOUND) - nx; a.vx = -a.vx; }
            else { a.x = clamp_q(nx, -BOUND, BOUND); }
            if ny > BOUND { a.y = (2 * BOUND) - ny; a.vy = -a.vy; }
            else if ny < -BOUND { a.y = (-2 * BOUND) - ny; a.vy = -a.vy; }
            else { a.y = clamp_q(ny, -BOUND, BOUND); }
        }
    }
}

#[no_mangle]
pub extern "C" fn wasm_actors_ptr() -> *const Actor {
    core::ptr::addr_of!(ACTORS) as *const Actor
}
'''

WASM_DRIVER_JS = r'''import crypto from "node:crypto";
import fs from "node:fs";
import readline from "node:readline";

const wasmBytes = fs.readFileSync(process.argv[2]);
const N = parseInt(process.argv[3], 10);
const TICKS = parseInt(process.argv[4], 10);
const LOOPS = parseInt(process.argv[5] || "1", 10);

const { instance } = await WebAssembly.instantiate(wasmBytes, {});
const { memory, wasm_init, wasm_step, wasm_actors_ptr } = instance.exports;
wasm_init(N);

const rl = readline.createInterface({ input: process.stdin, terminal: false });
process.stdout.write("READY\n");
rl.once("line", () => {
  const tickMs = [];
  for (let rep = 0; rep < LOOPS; rep++) {
    wasm_init(N);
    for (let t = 1; t <= TICKS; t++) {
      const t0 = performance.now();
      wasm_step(N, t);
      if (rep + 1 === LOOPS) tickMs.push(performance.now() - t0);
    }
  }
  const ptr = wasm_actors_ptr();
  const view = Buffer.from(memory.buffer, ptr, N * 72);
  const sha = crypto.createHash("sha256").update(view).digest("hex");
  process.stdout.write("DONE\t" + JSON.stringify({ sha256: sha, loops: LOOPS, tick_ms: tickMs }) + "\n");
  rl.close();
  process.exit(0);
});
'''


def percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = (len(sorted_vals) - 1) * q
    lo = int(idx)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = idx - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def run_handshaked(cmd: list[str], cwd: pathlib.Path, rapl: RaplReader) -> dict:
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdin and proc.stdout and proc.stderr
    rdy = proc.stdout.readline().strip()
    if rdy != "READY":
        err = proc.stderr.read()
        proc.kill()
        raise RuntimeError(f"Expected READY from {cmd}, got {rdy!r}: {err}")
    pkg0, core0 = rapl.read()
    t0 = time.perf_counter()
    proc.stdin.write("GO\n")
    proc.stdin.flush()
    done = proc.stdout.readline().strip()
    wall_s = time.perf_counter() - t0
    pkg1, core1 = rapl.read()
    proc.wait(timeout=600)
    if not done.startswith("DONE\t"):
        err = proc.stderr.read()
        raise RuntimeError(f"Expected DONE from {cmd}, got {done!r}: {err}")
    payload = json.loads(done.split("\t", 1)[1])
    payload["wall_s"] = wall_s
    payload["pkg_uj"] = rapl.diff(pkg0, pkg1, rapl.pkg_max)
    payload["core_uj"] = rapl.diff(core0, core1, rapl.core_max)
    return payload


def compute_ceiling_20ms(rows: list[dict]) -> dict:
    # Check if p50_ms crosses 20.0 ms within [64 .. 10000]
    for i, r in enumerate(rows):
        if r["p50_ms_per_tick"] >= 20.0:
            if i == 0:
                return {"crossed_within_10k": True, "n_20ms_p50": int(64 * (20.0 / r["p50_ms_per_tick"]))}
            prev = rows[i - 1]
            frac = (20.0 - prev["p50_ms_per_tick"]) / max(1e-9, r["p50_ms_per_tick"] - prev["p50_ms_per_tick"])
            n_est = int(round(prev["N"] + frac * (r["N"] - prev["N"])))
            return {"crossed_within_10k": True, "n_20ms_p50": n_est}
    # Extrapolate from N=10000 per-actor cost (us/actor)
    last = rows[-1]
    us_per_actor = (last["p50_ms_per_tick"] * 1000.0) / last["N"]
    implied = int(round(20000.0 / max(1e-6, us_per_actor)))
    return {
        "crossed_within_10k": False,
        "n_20ms_p50_extrapolated": implied,
        "us_per_actor_at_10k": round(us_per_actor, 4),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--rce", required=True)
    ap.add_argument("--rce-form", required=True)
    ap.add_argument("--node", default="node")
    ap.add_argument("--rustc", default="rustc")
    ap.add_argument("--clangxx", default="clang++")
    ap.add_argument("--counts", default=",".join(str(x) for x in ACTOR_COUNTS))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    work = pathlib.Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    counts = [int(x) for x in args.counts.split(",") if x.strip()]

    # 1. Check & emit Python and JS from real `rce`
    shutil.copy2(args.rce_form, work / "ge_h5_actor_arena.rce")
    subprocess.run([args.rce, "check", str(work / "ge_h5_actor_arena.rce")], check=True)
    subprocess.run([args.rce, "test", str(work / "ge_h5_actor_arena.rce")], check=True)
    (work / "emitted_actor.py").write_text(
        subprocess.check_output([args.rce, "emit", "python", str(work / "ge_h5_actor_arena.rce")], text=True)
    )
    (work / "emitted_actor.mjs").write_text(
        subprocess.check_output([args.rce, "emit", "js", str(work / "ge_h5_actor_arena.rce")], text=True)
    )
    (work / "py_driver.py").write_text(PY_DRIVER)
    (work / "js_driver.mjs").write_text(JS_DRIVER)
    (work / "form_rust.rs").write_text(RUST_SRC)
    (work / "form_cpp.cpp").write_text(CPP_SRC)
    (work / "form_wasm.rs").write_text(WASM_LIB_RS)
    (work / "wasm_driver.mjs").write_text(WASM_DRIVER_JS)

    # 2. Compile Wasm32, C++20 -O3, and Rust -O3
    subprocess.run(
        [args.rustc, "--edition", "2021", "--crate-type=cdylib", "--target", "wasm32-unknown-unknown", "-C", "opt-level=3", str(work / "form_wasm.rs"), "-o", str(work / "form_wasm.wasm")],
        check=True,
    )
    subprocess.run(
        [args.clangxx, "-std=c++20", "-O3", str(work / "form_cpp.cpp"), "-o", str(work / "form_cpp")],
        check=True,
    )
    subprocess.run(
        [args.rustc, "--edition", "2021", "-C", "opt-level=3", str(work / "form_rust.rs"), "-o", str(work / "form_rust")],
        check=True,
    )

    rapl = RaplReader()
    tiers_out = {
        "rce_python3": [],
        "rce_nodejs_v22": [],
        "form_wasm32_v8": [],
        "form_cpp20_o3": [],
        "form_rust_o3": [],
    }
    canonical_hashes: dict[int, str] = {}
    sha_mismatches = 0

    for n in counts:
        # Calibrate loops for fast compiled tiers so RAPL window >= ~250 ms
        fast_loops = max(1, int(round(300000 / max(64, n))))
        wasm_loops = max(1, int(round(120000 / max(64, n))))

        # Tier 5: Native Rust -O3
        raw_rs = work / f"raw_rs_{n}.bin"
        res_rs = run_handshaked([str(work / "form_rust"), str(n), str(TICKS), str(fast_loops), str(raw_rs)], work, rapl)
        sha_rs = hashlib.sha256(raw_rs.read_bytes()).hexdigest()
        raw_rs.unlink(missing_ok=True)
        canonical_hashes[n] = sha_rs

        # Tier 4: C++20 -O3
        raw_cpp = work / f"raw_cpp_{n}.bin"
        res_cpp = run_handshaked([str(work / "form_cpp"), str(n), str(TICKS), str(fast_loops), str(raw_cpp)], work, rapl)
        sha_cpp = hashlib.sha256(raw_cpp.read_bytes()).hexdigest()
        raw_cpp.unlink(missing_ok=True)

        # Tier 3: Rust Wasm32 on Node V8
        res_wasm = run_handshaked([args.node, str(work / "wasm_driver.mjs"), str(work / "form_wasm.wasm"), str(n), str(TICKS), str(wasm_loops)], work, rapl)
        sha_wasm = res_wasm["sha256"]

        # Tier 2: rce emit js on Node v22
        res_js = run_handshaked([args.node, str(work / "js_driver.mjs"), str(n), str(TICKS)], work, rapl)
        sha_js = res_js["sha256"]

        # Tier 1: rce emit python on Python 3
        res_py = run_handshaked([sys.executable, str(work / "py_driver.py"), str(work), str(n), str(TICKS)], work, rapl)
        sha_py = res_py["sha256"]

        for t_id, res, sha in [
            ("rce_python3", res_py, sha_py),
            ("rce_nodejs_v22", res_js, sha_js),
            ("form_wasm32_v8", res_wasm, sha_wasm),
            ("form_cpp20_o3", res_cpp, sha_cpp),
            ("form_rust_o3", res_rs, sha_rs),
        ]:
            if sha != canonical_hashes[n]:
                sha_mismatches += 1
            tms = sorted(res["tick_ms"])
            total_ticks = TICKS * int(res["loops"])
            pkg_mj = (res["pkg_uj"] / 1000.0) / total_ticks if res["pkg_uj"] is not None else None
            core_mj = (res["core_uj"] / 1000.0) / total_ticks if res["core_uj"] is not None else None
            row = {
                "N": n,
                "ticks": TICKS,
                "calibration_loops": int(res["loops"]),
                "p50_ms_per_tick": round(percentile(tms, 0.50), 5),
                "p99_ms_per_tick": round(percentile(tms, 0.99), 5),
                "mean_ms_per_tick": round(st.mean(tms), 5),
                "us_per_actor_p50": round((percentile(tms, 0.50) * 1000.0) / n, 4),
                "rapl_pkg_reported_mj_per_tick": round(pkg_mj, 5) if pkg_mj is not None else None,
                "rapl_core_reported_mj_per_tick": round(core_mj, 5) if core_mj is not None else None,
                "sha256_tick_500": sha,
                "matches_canonical": sha == canonical_hashes[n],
            }
            tiers_out[t_id].append(row)
        print(
            f"[GE-H5] N={n:5d} | py={tiers_out['rce_python3'][-1]['p50_ms_per_tick']:8.3f}ms "
            f"| js={tiers_out['rce_nodejs_v22'][-1]['p50_ms_per_tick']:7.3f}ms "
            f"| wasm={tiers_out['form_wasm32_v8'][-1]['p50_ms_per_tick']:6.4f}ms "
            f"| cpp={tiers_out['form_cpp20_o3'][-1]['p50_ms_per_tick']:6.4f}ms "
            f"| rs={tiers_out['form_rust_o3'][-1]['p50_ms_per_tick']:6.4f}ms "
            f"| sha_ok={sha_mismatches==0}",
            flush=True,
        )

    ceilings = {k: compute_ceiling_20ms(v) for k, v in tiers_out.items()}
    summary = {
        "hypothesis": "GE-H5",
        "host": platform.node(),
        "os": platform.platform(),
        "measured_j": None,
        "board_metered": False,
        "telemetry_channel": "SATB L2 Linux powercap intel-rapl:0 (package-0 and core energy_uj)",
        "ticks_per_N": TICKS,
        "actor_counts": counts,
        "total_cells": len(counts) * 5,
        "cross_tier_sha256_mismatches": sha_mismatches,
        "gamerule_reference_ceiling_actors": 308,
        "ceilings_20ms": ceilings,
        "tiers": tiers_out,
    }
    pathlib.Path(args.out).write_text(json.dumps(summary, indent=2))
    print(f"Wrote {args.out} (mismatches={sha_mismatches})")


if __name__ == "__main__":
    main()
