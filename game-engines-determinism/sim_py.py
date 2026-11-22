#!/usr/bin/env python3
"""
Python 3.13 target for `game-engines` (`GE-H1` Q32.32 fixed-point & `GE-H2` f64 float control).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import sys
import time

N_BODIES = 16
N_PICKUPS = 4
ONE = 1 << 32
ARENA = 64 * ONE
RADIUS = 2 * ONE
PICKUP_R = 3 * ONE
BOUND = 62 * ONE
MAX_V = 48 * ONE
DT_Q = 1 << 26
DRAG_IDLE = 4273492459
DRAG_DASH = 4286377361
REST_WALL = 3865470566
ONE_PLUS_E = 7945689498
MIN_DIST = 4 * ONE
MIN_DIST_SQ = MIN_DIST * MIN_DIST
PICKUP_DIST = 5 * ONE
PICKUP_DIST_SQ = PICKUP_DIST * PICKUP_DIST
DIAG = 3037000500

DIR_X = (ONE, DIAG, 0, -DIAG, -ONE, -DIAG, 0, DIAG)
DIR_Y = (0, DIAG, ONE, DIAG, 0, -DIAG, -ONE, -DIAG)
DIR_FX = tuple(v / float(ONE) for v in DIR_X)
DIR_FY = tuple(v / float(ONE) for v in DIR_Y)

INITIAL_SEED = 2316557121413006641
MASK64 = (1 << 64) - 1
SM_C0 = 11400714819323198485
SM_C1 = 13787848793156543929
SM_C2 = 10723151780598845931


def splitmix64_next(state: int) -> tuple[int, int]:
    s = (state + SM_C0) & MASK64
    z = s
    z = ((z ^ (z >> 30)) * SM_C1) & MASK64
    z = ((z ^ (z >> 27)) * SM_C2) & MASK64
    out = (z ^ (z >> 31)) & MASK64
    return s, out


def qmul(a: int, b: int) -> int:
    return (a * b) >> 32


def trunc_div128(num: int, den: int) -> int:
    if num >= 0:
        return num // den
    return -((-num) // den)


def init_q32_state():
    rng = INITIAL_SEED
    bx = [0] * N_BODIES
    by = [0] * N_BODIES
    bvx = [0] * N_BODIES
    bvy = [0] * N_BODIES
    bmass = [0] * N_BODIES
    bfsm = [0] * N_BODIES
    btimer = [0] * N_BODIES
    bscore = [0] * N_BODIES

    for i in range(N_BODIES):
        gx = ((i & 3) * 30 - 45) * ONE
        gy = ((i >> 2) * 30 - 45) * ONE
        rng, r1 = splitmix64_next(rng)
        rng, r2 = splitmix64_next(rng)
        jx = (r1 & 0xFFFFFFFF) - 2147483648
        jy = ((r1 >> 32) & 0xFFFFFFFF) - 2147483648
        bx[i] = gx + jx
        by[i] = gy + jy
        bvx[i] = ((r2 & 0xFFFFFFFF) - 2147483648) * 24
        bvy[i] = (((r2 >> 32) & 0xFFFFFFFF) - 2147483648) * 24
        bmass[i] = (4 + (i & 3)) << 30

    px = [(-20 * ONE) if (p & 1) == 0 else (20 * ONE) for p in range(N_PICKUPS)]
    py = [(-20 * ONE) if (p >> 1) == 0 else (20 * ONE) for p in range(N_PICKUPS)]
    pactive = [1] * N_PICKUPS
    prespawn = [0] * N_PICKUPS
    return [0, rng, bx, by, bvx, bvy, bmass, bfsm, btimer, bscore, px, py, pactive, prespawn]


def serialize_q32_state(st_arr) -> bytes:
    tick, rng, bx, by, bvx, bvy, _bmass, bfsm, btimer, bscore, px, py, pactive, prespawn = st_arr
    parts = [struct.pack("<IQ", tick, rng)]
    for i in range(N_BODIES):
        parts.append(
            struct.pack(
                "<qqqqIHBB",
                bx[i],
                by[i],
                bvx[i],
                bvy[i],
                bscore[i],
                btimer[i],
                bfsm[i],
                0,
            )
        )
    for p in range(N_PICKUPS):
        parts.append(struct.pack("<qqHBB", px[p], py[p], prespawn[p], pactive[p], 0))
    return b"".join(parts)


def run_q32_sim(ticks: int, stride: int) -> dict[str, str]:
    st_arr = init_q32_state()
    tick, rng, bx, by, bvx, bvy, bmass, bfsm, btimer, bscore, px, py, pactive, prespawn = st_arr
    isqrt = math.isqrt
    checkpoints: dict[str, str] = {}

    for _ in range(ticks):
        rng, ev = splitmix64_next(rng)
        actor = ev & 15
        d = (ev >> 4) & 7
        want_dash = ((ev >> 7) & 3) == 0
        if want_dash and bfsm[actor] == 0:
            bfsm[actor] = 1
            btimer[actor] = 12
            bvx[actor] += 6 * DIR_X[d]
            bvy[actor] += 6 * DIR_Y[d]
        else:
            bvx[actor] += 2 * DIR_X[d]
            bvy[actor] += 2 * DIR_Y[d]

        for i in range(N_BODIES):
            st_i = bfsm[i]
            if st_i == 1:
                t_rem = btimer[i] - 1
                if t_rem == 0:
                    bfsm[i] = 2
                    btimer[i] = 40
                    st_i = 2
                else:
                    btimer[i] = t_rem
            elif st_i == 2:
                t_rem = btimer[i] - 1
                btimer[i] = t_rem
                if t_rem == 0:
                    bfsm[i] = 0
                    st_i = 0

            drag = DRAG_DASH if st_i == 1 else DRAG_IDLE
            vx = (bvx[i] * drag) >> 32
            vy = (bvy[i] * drag) >> 32
            if vx > MAX_V:
                vx = MAX_V
            elif vx < -MAX_V:
                vx = -MAX_V
            if vy > MAX_V:
                vy = MAX_V
            elif vy < -MAX_V:
                vy = -MAX_V

            x = bx[i] + ((vx * DT_Q) >> 32)
            y = by[i] + ((vy * DT_Q) >> 32)
            if x > BOUND:
                x = 2 * BOUND - x
                vx = -((vx * REST_WALL) >> 32)
            elif x < -BOUND:
                x = -2 * BOUND - x
                vx = -((vx * REST_WALL) >> 32)
            if y > BOUND:
                y = 2 * BOUND - y
                vy = -((vy * REST_WALL) >> 32)
            elif y < -BOUND:
                y = -2 * BOUND - y
                vy = -((vy * REST_WALL) >> 32)

            bx[i] = x
            by[i] = y
            bvx[i] = vx
            bvy[i] = vy

        for i in range(N_BODIES):
            for j in range(i + 1, N_BODIES):
                dx = bx[j] - bx[i]
                dy = by[j] - by[i]
                dist_sq = dx * dx + dy * dy
                if 0 < dist_sq < MIN_DIST_SQ:
                    dist = isqrt(dist_sq)
                    nx = trunc_div128(dx * ONE, dist)
                    ny = trunc_div128(dy * ONE, dist)
                    sep = (MIN_DIST - dist) >> 1
                    cx = (sep * nx) >> 32
                    cy = (sep * ny) >> 32
                    bx[i] -= cx
                    by[i] -= cy
                    bx[j] += cx
                    by[j] += cy

                    rvx = bvx[j] - bvx[i]
                    rvy = bvy[j] - bvy[i]
                    vn = ((rvx * nx) >> 32) + ((rvy * ny) >> 32)
                    if vn < 0:
                        j_base = ((-vn) * ONE_PLUS_E) >> 32
                        msum = bmass[i] + bmass[j]
                        dvi = trunc_div128(j_base * bmass[j], msum)
                        dvj = trunc_div128(j_base * bmass[i], msum)
                        bvx[i] -= (dvi * nx) >> 32
                        bvy[i] -= (dvi * ny) >> 32
                        bvx[j] += (dvj * nx) >> 32
                        bvy[j] += (dvj * ny) >> 32

        deact0 = deact1 = deact2 = deact3 = 0
        resp0 = resp1 = resp2 = resp3 = 0
        deact = [deact0, deact1, deact2, deact3]
        resp = [resp0, resp1, resp2, resp3]
        for p in range(N_PICKUPS):
            if pactive[p] == 1:
                px_p = px[p]
                py_p = py[p]
                for i in range(N_BODIES):
                    pdx = bx[i] - px_p
                    pdy = by[i] - py_p
                    if pdx * pdx + pdy * pdy <= PICKUP_DIST_SQ:
                        bscore[i] += 1
                        deact[p] = 1
                        break
            else:
                rt = prespawn[p] - 1
                prespawn[p] = rt
                if rt == 0:
                    resp[p] = 1

        for p in range(N_PICKUPS):
            if deact[p] == 1:
                pactive[p] = 0
                prespawn[p] = 75
            if resp[p] == 1:
                rng, rp = splitmix64_next(rng)
                px[p] = ((rp & 0xFFFFFFFF) - 2147483648) * 80
                py[p] = (((rp >> 32) & 0xFFFFFFFF) - 2147483648) * 80
                pactive[p] = 1

        tick += 1
        if stride > 0 and (tick % stride == 0 or tick == ticks):
            st_arr[0] = tick
            st_arr[1] = rng
            checkpoints[str(tick)] = hashlib.sha256(serialize_q32_state(st_arr)).hexdigest()

    return checkpoints


def canon_f64(val: float) -> float:
    return 0.0 if val == 0.0 else val


def run_float_trace(ticks: int, use_trig: bool) -> list[tuple[str, str, str]]:
    st_q = init_q32_state()
    rng = st_q[1]
    bx = [v / float(ONE) for v in st_q[2]]
    by = [v / float(ONE) for v in st_q[3]]
    bvx = [v / float(ONE) for v in st_q[4]]
    bvy = [v / float(ONE) for v in st_q[5]]
    bmass = [v / float(ONE) for v in st_q[6]]
    bfsm = list(st_q[7])
    btimer = list(st_q[8])
    bscore = list(st_q[9])
    px = [v / float(ONE) for v in st_q[10]]
    py = [v / float(ONE) for v in st_q[11]]
    pactive = list(st_q[12])
    prespawn = list(st_q[13])

    dt_f = 1.0 / 64.0
    drag_idle_f = DRAG_IDLE / float(ONE)
    drag_dash_f = DRAG_DASH / float(ONE)
    rest_wall_f = REST_WALL / float(ONE)
    one_plus_e_f = ONE_PLUS_E / float(ONE)

    out_hashes: list[tuple[str, str, str]] = []
    tick = 0
    for _ in range(ticks):
        rng, ev = splitmix64_next(rng)
        actor = ev & 15
        d = (ev >> 4) & 7
        want_dash = ((ev >> 7) & 3) == 0
        if use_trig:
            theta = 0.017453292519943295 * float(tick + 1) + 0.7853981633974483 * float(d)
            ux = math.cos(theta)
            uy = math.sin(theta)
        else:
            ux = DIR_FX[d]
            uy = DIR_FY[d]

        if want_dash and bfsm[actor] == 0:
            bfsm[actor] = 1
            btimer[actor] = 12
            bvx[actor] = bvx[actor] + 6.0 * ux
            bvy[actor] = bvy[actor] + 6.0 * uy
        else:
            bvx[actor] = bvx[actor] + 2.0 * ux
            bvy[actor] = bvy[actor] + 2.0 * uy

        for i in range(N_BODIES):
            if bfsm[i] == 1:
                btimer[i] -= 1
                if btimer[i] == 0:
                    bfsm[i] = 2
                    btimer[i] = 40
            elif bfsm[i] == 2:
                btimer[i] -= 1
                if btimer[i] == 0:
                    bfsm[i] = 0

            drag = drag_dash_f if bfsm[i] == 1 else drag_idle_f
            vx = bvx[i] * drag
            vy = bvy[i] * drag
            vx = max(-48.0, min(48.0, vx))
            vy = max(-48.0, min(48.0, vy))
            x = bx[i] + vx * dt_f
            y = by[i] + vy * dt_f
            if x > 62.0:
                x = 124.0 - x
                vx = -(vx * rest_wall_f)
            elif x < -62.0:
                x = -124.0 - x
                vx = -(vx * rest_wall_f)
            if y > 62.0:
                y = 124.0 - y
                vy = -(vy * rest_wall_f)
            elif y < -62.0:
                y = -124.0 - y
                vy = -(vy * rest_wall_f)
            bx[i], by[i], bvx[i], bvy[i] = x, y, vx, vy

        for i in range(N_BODIES):
            for j in range(i + 1, N_BODIES):
                dx = bx[j] - bx[i]
                dy = by[j] - by[i]
                dist_sq = dx * dx + dy * dy
                if 0.0 < dist_sq < 16.0:
                    dist = math.sqrt(dist_sq)
                    nx = dx / dist
                    ny = dy / dist
                    sep = 0.5 * (4.0 - dist)
                    bx[i] = bx[i] - sep * nx
                    by[i] = by[i] - sep * ny
                    bx[j] = bx[j] + sep * nx
                    by[j] = by[j] + sep * ny
                    rvx = bvx[j] - bvx[i]
                    rvy = bvy[j] - bvy[i]
                    vn = rvx * nx + rvy * ny
                    if vn < 0.0:
                        j_base = (-vn) * one_plus_e_f
                        msum = bmass[i] + bmass[j]
                        dvi = (j_base * bmass[j]) / msum
                        dvj = (j_base * bmass[i]) / msum
                        bvx[i] = bvx[i] - dvi * nx
                        bvy[i] = bvy[i] - dvi * ny
                        bvx[j] = bvx[j] + dvj * nx
                        bvy[j] = bvy[j] + dvj * ny

        deact = [0] * N_PICKUPS
        resp = [0] * N_PICKUPS
        for p in range(N_PICKUPS):
            if pactive[p] == 1:
                for i in range(N_BODIES):
                    pdx = bx[i] - px[p]
                    pdy = by[i] - py[p]
                    if pdx * pdx + pdy * pdy <= 25.0:
                        bscore[i] += 1
                        deact[p] = 1
                        break
            else:
                prespawn[p] -= 1
                if prespawn[p] == 0:
                    resp[p] = 1
        for p in range(N_PICKUPS):
            if deact[p] == 1:
                pactive[p] = 0
                prespawn[p] = 75
            if resp[p] == 1:
                rng, rp = splitmix64_next(rng)
                px[p] = (((rp & 0xFFFFFFFF) - 2147483648) * 80) / float(ONE)
                py[p] = ((((rp >> 32) & 0xFFFFFFFF) - 2147483648) * 80) / float(ONE)
                pactive[p] = 1

        tick += 1
        ieee_buf = bytearray(struct.pack("<IQ", tick, rng))
        mm_buf = bytearray(struct.pack("<I", tick))
        gp_buf = bytearray(struct.pack("<I", tick))
        for i in range(N_BODIES):
            ieee_buf += struct.pack(
                "<ddddIHBB",
                canon_f64(bx[i]),
                canon_f64(by[i]),
                canon_f64(bvx[i]),
                canon_f64(bvy[i]),
                bscore[i],
                btimer[i],
                bfsm[i],
                0,
            )
            mm_buf += struct.pack("<qqIHB", int(math.floor(bx[i] * 1000.0)), int(math.floor(by[i] * 1000.0)), bscore[i], btimer[i], bfsm[i])
            quad = (1 if bx[i] >= 0.0 else 0) | (2 if by[i] >= 0.0 else 0)
            gp_buf += struct.pack("<IBB", bscore[i], bfsm[i], quad)
        for p in range(N_PICKUPS):
            ieee_buf += struct.pack("<ddHBB", canon_f64(px[p]), canon_f64(py[p]), prespawn[p], pactive[p], 0)
            gp_buf += struct.pack("<B", pactive[p])

        out_hashes.append(
            (
                hashlib.sha256(ieee_buf).hexdigest()[:16],
                hashlib.sha256(mm_buf).hexdigest()[:16],
                hashlib.sha256(gp_buf).hexdigest()[:16],
            )
        )
    return out_hashes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["q32", "f64_strict", "f64_trig"], default="q32")
    ap.add_argument("--ticks", type=int, default=100000)
    ap.add_argument("--stride", type=int, default=1000)
    ap.add_argument("--loops", type=int, default=1)
    ap.add_argument("--handshake", action="store_true")
    args = ap.parse_args()

    if args.mode == "q32":
        run_q32_sim(100, 100)
        if args.handshake:
            sys.stdout.write("READY\n")
            sys.stdout.flush()
            sys.stdin.readline()
        t0 = time.perf_counter_ns()
        ck = {}
        for _ in range(args.loops):
            ck = run_q32_sim(args.ticks, args.stride)
        t1 = time.perf_counter_ns()
        out = {"wall_ms": (t1 - t0) / 1e6 / args.loops, "loops": args.loops, "checkpoints": ck}
        sys.stdout.write("DONE\t" + json.dumps(out) + "\n")
        sys.stdout.flush()
        if args.handshake:
            sys.stdin.readline()
    else:
        tr = run_float_trace(args.ticks, use_trig=(args.mode == "f64_trig"))
        sys.stdout.write(json.dumps({"trace": tr}) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
