// Cross-OS Rust native (`x86_64-pc-windows-msvc`, `x86_64`/`aarch64` Linux, `arm64` macOS)
// target for `game-engines` (`GE-H1` Q32.32 & `GE-H2` IEEE-754 f64/f32 + UCRT/libm/glibc trig + FMA).
// Compiled via: rustc --edition 2021 -O sim_rust.rs -o sim_rust[.exe]

use std::env;
use std::io::{self, BufRead, Write};
use std::time::Instant;

const K256: [u32; 64] = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
];

fn sha256_hex(bytes: &[u8]) -> String {
    let mut h: [u32; 8] = [
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
        0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
    ];
    let bit_len = (bytes.len() as u64) * 8;
    let pad_len = (bytes.len() + 9 + 63) & !63;
    let mut msg = vec![0u8; pad_len];
    msg[..bytes.len()].copy_from_slice(bytes);
    msg[bytes.len()] = 0x80;
    msg[pad_len - 8..pad_len].copy_from_slice(&bit_len.to_be_bytes());

    let mut w = [0u32; 64];
    for chunk in msg.chunks_exact(64) {
        for i in 0..16 {
            w[i] = u32::from_be_bytes([chunk[4 * i], chunk[4 * i + 1], chunk[4 * i + 2], chunk[4 * i + 3]]);
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16].wrapping_add(s0).wrapping_add(w[i - 7]).wrapping_add(s1);
        }
        let (mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut hh) =
            (h[0], h[1], h[2], h[3], h[4], h[5], h[6], h[7]);
        for i in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ ((!e) & g);
            let t1 = hh.wrapping_add(s1).wrapping_add(ch).wrapping_add(K256[i]).wrapping_add(w[i]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let t2 = s0.wrapping_add(maj);
            hh = g;
            g = f;
            f = e;
            e = d.wrapping_add(t1);
            d = c;
            c = b;
            b = a;
            a = t1.wrapping_add(t2);
        }
        h[0] = h[0].wrapping_add(a);
        h[1] = h[1].wrapping_add(b);
        h[2] = h[2].wrapping_add(c);
        h[3] = h[3].wrapping_add(d);
        h[4] = h[4].wrapping_add(e);
        h[5] = h[5].wrapping_add(f);
        h[6] = h[6].wrapping_add(g);
        h[7] = h[7].wrapping_add(hh);
    }
    let mut out = String::with_capacity(64);
    for word in h {
        use std::fmt::Write as _;
        let _ = write!(&mut out, "{:08x}", word);
    }
    out
}

const N_BODIES: usize = 16;
const N_PICKUPS: usize = 4;
const ONE: i64 = 1_i64 << 32;
const BOUND: i64 = 62 * ONE;
const MAX_V: i64 = 48 * ONE;
const DT_Q: i64 = 1_i64 << 26;
const DRAG_IDLE: i64 = 4273492459;
const DRAG_DASH: i64 = 4286377361;
const REST_WALL: i64 = 3865470566;
const ONE_PLUS_E: i64 = 7945689498;
const MIN_DIST: i64 = 4 * ONE;
const MIN_DIST_SQ: i128 = (MIN_DIST as i128) * (MIN_DIST as i128);
const PICKUP_DIST: i64 = 5 * ONE;
const PICKUP_DIST_SQ: i128 = (PICKUP_DIST as i128) * (PICKUP_DIST as i128);
const DIAG: i64 = 3037000500;

const DIR_X: [i64; 8] = [ONE, DIAG, 0, -DIAG, -ONE, -DIAG, 0, DIAG];
const DIR_Y: [i64; 8] = [0, DIAG, ONE, DIAG, 0, -DIAG, -ONE, -DIAG];

const INITIAL_SEED: u64 = 2316557121413006641;
const SM_C0: u64 = 11400714819323198485;
const SM_C1: u64 = 13787848793156543929;
const SM_C2: u64 = 10723151780598845931;

#[inline]
fn splitmix64_next(state: u64) -> (u64, u64) {
    let s = state.wrapping_add(SM_C0);
    let mut z = s;
    z = (z ^ (z >> 30)).wrapping_mul(SM_C1);
    z = (z ^ (z >> 27)).wrapping_mul(SM_C2);
    let out = z ^ (z >> 31);
    (s, out)
}

#[inline]
fn qmul(a: i64, b: i64) -> i64 {
    (((a as i128) * (b as i128)) >> 32) as i64
}

#[inline]
fn trunc_div128(num: i128, den: i128) -> i64 {
    let d = den as u128;
    if num >= 0 {
        ((num as u128) / d) as i64
    } else {
        -((((-num) as u128) / d) as i64)
    }
}

#[inline]
fn isqrt_u128(n: u128) -> i64 {
    if n == 0 {
        return 0;
    }
    let mut bits = 0u32;
    let mut tmp = n;
    while tmp > 0 {
        bits += 1;
        tmp >>= 1;
    }
    let mut x = 1_u128 << ((bits + 1) >> 1);
    loop {
        let y = (x + n / x) >> 1;
        if y >= x {
            return x as i64;
        }
        x = y;
    }
}

fn run_q32_sim(ticks: u32, stride: u32) -> Vec<(u32, String)> {
    let mut rng: u64 = INITIAL_SEED;
    let mut bx = [0i64; N_BODIES];
    let mut by = [0i64; N_BODIES];
    let mut bvx = [0i64; N_BODIES];
    let mut bvy = [0i64; N_BODIES];
    let mut bmass = [0i64; N_BODIES];
    let mut bfsm = [0u8; N_BODIES];
    let mut btimer = [0u16; N_BODIES];
    let mut bscore = [0u32; N_BODIES];

    for i in 0..N_BODIES {
        let gx = (((i as i64 & 3) * 30) - 45) * ONE;
        let gy = ((((i as i64) >> 2) * 30) - 45) * ONE;
        let (r_next1, r1) = splitmix64_next(rng);
        let (r_next2, r2) = splitmix64_next(r_next1);
        rng = r_next2;
        let jx = ((r1 & 0xFFFF_FFFF) as i64) - 2147483648;
        let jy = (((r1 >> 32) & 0xFFFF_FFFF) as i64) - 2147483648;
        bx[i] = gx + jx;
        by[i] = gy + jy;
        bvx[i] = (((r2 & 0xFFFF_FFFF) as i64) - 2147483648) * 24;
        bvy[i] = ((((r2 >> 32) & 0xFFFF_FFFF) as i64) - 2147483648) * 24;
        bmass[i] = (4 + (i as i64 & 3)) << 30;
    }

    let mut px = [0i64; N_PICKUPS];
    let mut py = [0i64; N_PICKUPS];
    let mut pactive = [1u8; N_PICKUPS];
    let mut prespawn = [0u16; N_PICKUPS];
    for p in 0..N_PICKUPS {
        px[p] = if (p & 1) == 0 { -20 * ONE } else { 20 * ONE };
        py[p] = if (p >> 1) == 0 { -20 * ONE } else { 20 * ONE };
    }

    let mut checkpoints = Vec::new();
    let mut buf = [0u8; 732];
    let mut tick: u32 = 0;

    for _ in 0..ticks {
        let (rng2, ev) = splitmix64_next(rng);
        rng = rng2;
        let actor = (ev & 15) as usize;
        let d = ((ev >> 4) & 7) as usize;
        let want_dash = ((ev >> 7) & 3) == 0;
        if want_dash && bfsm[actor] == 0 {
            bfsm[actor] = 1;
            btimer[actor] = 12;
            bvx[actor] += 6 * DIR_X[d];
            bvy[actor] += 6 * DIR_Y[d];
        } else {
            bvx[actor] += 2 * DIR_X[d];
            bvy[actor] += 2 * DIR_Y[d];
        }

        for i in 0..N_BODIES {
            if bfsm[i] == 1 {
                btimer[i] -= 1;
                if btimer[i] == 0 {
                    bfsm[i] = 2;
                    btimer[i] = 40;
                }
            } else if bfsm[i] == 2 {
                btimer[i] -= 1;
                if btimer[i] == 0 {
                    bfsm[i] = 0;
                }
            }
            let drag = if bfsm[i] == 1 { DRAG_DASH } else { DRAG_IDLE };
            let mut vx = qmul(bvx[i], drag).clamp(-MAX_V, MAX_V);
            let mut vy = qmul(bvy[i], drag).clamp(-MAX_V, MAX_V);
            let mut x = bx[i] + qmul(vx, DT_Q);
            let mut y = by[i] + qmul(vy, DT_Q);
            if x > BOUND {
                x = 2 * BOUND - x;
                vx = -qmul(vx, REST_WALL);
            } else if x < -BOUND {
                x = -2 * BOUND - x;
                vx = -qmul(vx, REST_WALL);
            }
            if y > BOUND {
                y = 2 * BOUND - y;
                vy = -qmul(vy, REST_WALL);
            } else if y < -BOUND {
                y = -2 * BOUND - y;
                vy = -qmul(vy, REST_WALL);
            }
            bx[i] = x;
            by[i] = y;
            bvx[i] = vx;
            bvy[i] = vy;
        }

        for i in 0..N_BODIES {
            for j in (i + 1)..N_BODIES {
                let dx = bx[j] - bx[i];
                let dy = by[j] - by[i];
                let dist_sq = (dx as i128) * (dx as i128) + (dy as i128) * (dy as i128);
                if dist_sq > 0 && dist_sq < MIN_DIST_SQ {
                    let dist = isqrt_u128(dist_sq as u128);
                    let nx = trunc_div128((dx as i128) * (ONE as i128), dist as i128);
                    let ny = trunc_div128((dy as i128) * (ONE as i128), dist as i128);
                    let sep = (MIN_DIST - dist) >> 1;
                    let cx = qmul(sep, nx);
                    let cy = qmul(sep, ny);
                    bx[i] -= cx;
                    by[i] -= cy;
                    bx[j] += cx;
                    by[j] += cy;

                    let rvx = bvx[j] - bvx[i];
                    let rvy = bvy[j] - bvy[i];
                    let vn = qmul(rvx, nx) + qmul(rvy, ny);
                    if vn < 0 {
                        let j_base = qmul(-vn, ONE_PLUS_E);
                        let msum = bmass[i] + bmass[j];
                        let dvi = trunc_div128((j_base as i128) * (bmass[j] as i128), msum as i128);
                        let dvj = trunc_div128((j_base as i128) * (bmass[i] as i128), msum as i128);
                        bvx[i] -= qmul(dvi, nx);
                        bvy[i] -= qmul(dvi, ny);
                        bvx[j] += qmul(dvj, nx);
                        bvy[j] += qmul(dvj, ny);
                    }
                }
            }
        }

        let mut deact = [0u8; N_PICKUPS];
        let mut resp = [0u8; N_PICKUPS];
        for p in 0..N_PICKUPS {
            if pactive[p] == 1 {
                for i in 0..N_BODIES {
                    let pdx = bx[i] - px[p];
                    let pdy = by[i] - py[p];
                    if (pdx as i128) * (pdx as i128) + (pdy as i128) * (pdy as i128) <= PICKUP_DIST_SQ {
                        bscore[i] += 1;
                        deact[p] = 1;
                        break;
                    }
                }
            } else {
                prespawn[p] -= 1;
                if prespawn[p] == 0 {
                    resp[p] = 1;
                }
            }
        }
        for p in 0..N_PICKUPS {
            if deact[p] == 1 {
                pactive[p] = 0;
                prespawn[p] = 75;
            }
            if resp[p] == 1 {
                let (rng3, rp) = splitmix64_next(rng);
                rng = rng3;
                px[p] = (((rp & 0xFFFF_FFFF) as i64) - 2147483648) * 80;
                py[p] = ((((rp >> 32) & 0xFFFF_FFFF) as i64) - 2147483648) * 80;
                pactive[p] = 1;
            }
        }

        tick += 1;
        if stride > 0 && (tick % stride == 0 || tick == ticks) {
            buf[0..4].copy_from_slice(&tick.to_le_bytes());
            buf[4..12].copy_from_slice(&rng.to_le_bytes());
            let mut o = 12;
            for i in 0..N_BODIES {
                buf[o..o + 8].copy_from_slice(&bx[i].to_le_bytes()); o += 8;
                buf[o..o + 8].copy_from_slice(&by[i].to_le_bytes()); o += 8;
                buf[o..o + 8].copy_from_slice(&bvx[i].to_le_bytes()); o += 8;
                buf[o..o + 8].copy_from_slice(&bvy[i].to_le_bytes()); o += 8;
                buf[o..o + 4].copy_from_slice(&bscore[i].to_le_bytes()); o += 4;
                buf[o..o + 2].copy_from_slice(&btimer[i].to_le_bytes()); o += 2;
                buf[o] = bfsm[i]; o += 1;
                buf[o] = 0; o += 1;
            }
            for p in 0..N_PICKUPS {
                buf[o..o + 8].copy_from_slice(&px[p].to_le_bytes()); o += 8;
                buf[o..o + 8].copy_from_slice(&py[p].to_le_bytes()); o += 8;
                buf[o..o + 2].copy_from_slice(&prespawn[p].to_le_bytes()); o += 2;
                buf[o] = pactive[p]; o += 1;
                buf[o] = 0; o += 1;
            }
            checkpoints.push((tick, sha256_hex(&buf)));
        }
    }
    checkpoints
}

#[inline]
fn canon_f64(v: f64) -> f64 {
    if v == 0.0 { 0.0 } else { v }
}

fn run_f64_trace(ticks: u32, use_trig: bool, use_fma: bool) -> Vec<(String, String, String)> {
    let one_f = ONE as f64;
    let dir_fx: [f64; 8] = DIR_X.map(|v| (v as f64) / one_f);
    let dir_fy: [f64; 8] = DIR_Y.map(|v| (v as f64) / one_f);

    let mut rng: u64 = INITIAL_SEED;
    let mut bx = [0.0f64; N_BODIES];
    let mut by = [0.0f64; N_BODIES];
    let mut bvx = [0.0f64; N_BODIES];
    let mut bvy = [0.0f64; N_BODIES];
    let mut bmass = [0.0f64; N_BODIES];
    let mut bfsm = [0u8; N_BODIES];
    let mut btimer = [0u16; N_BODIES];
    let mut bscore = [0u32; N_BODIES];

    for i in 0..N_BODIES {
        let gx = (((i as i64 & 3) * 30) - 45) * ONE;
        let gy = ((((i as i64) >> 2) * 30) - 45) * ONE;
        let (r_next1, r1) = splitmix64_next(rng);
        let (r_next2, r2) = splitmix64_next(r_next1);
        rng = r_next2;
        let jx = ((r1 & 0xFFFF_FFFF) as i64) - 2147483648;
        let jy = (((r1 >> 32) & 0xFFFF_FFFF) as i64) - 2147483648;
        bx[i] = ((gx + jx) as f64) / one_f;
        by[i] = ((gy + jy) as f64) / one_f;
        bvx[i] = ((((r2 & 0xFFFF_FFFF) as i64) - 2147483648) * 24) as f64 / one_f;
        bvy[i] = (((((r2 >> 32) & 0xFFFF_FFFF) as i64) - 2147483648) * 24) as f64 / one_f;
        bmass[i] = ((4 + (i as i64 & 3)) << 30) as f64 / one_f;
    }

    let mut px = [0.0f64; N_PICKUPS];
    let mut py = [0.0f64; N_PICKUPS];
    let mut pactive = [1u8; N_PICKUPS];
    let mut prespawn = [0u16; N_PICKUPS];
    for p in 0..N_PICKUPS {
        px[p] = if (p & 1) == 0 { -20.0 } else { 20.0 };
        py[p] = if (p >> 1) == 0 { -20.0 } else { 20.0 };
    }

    let dt_f = 1.0 / 64.0;
    let drag_idle_f = (DRAG_IDLE as f64) / one_f;
    let drag_dash_f = (DRAG_DASH as f64) / one_f;
    let rest_wall_f = (REST_WALL as f64) / one_f;
    let one_plus_e_f = (ONE_PLUS_E as f64) / one_f;

    let mut out = Vec::with_capacity(ticks as usize);
    let mut ieee_buf = [0u8; 732];
    let mut mm_buf = [0u8; 4 + N_BODIES * 23];
    let mut gp_buf = [0u8; 4 + N_BODIES * 6 + N_PICKUPS];
    let mut tick: u32 = 0;

    #[inline]
    fn madd(a: f64, b: f64, c: f64, fma: bool) -> f64 {
        if fma { a.mul_add(b, c) } else { c + a * b }
    }

    for _ in 0..ticks {
        let (rng2, ev) = splitmix64_next(rng);
        rng = rng2;
        let actor = (ev & 15) as usize;
        let d = ((ev >> 4) & 7) as usize;
        let want_dash = ((ev >> 7) & 3) == 0;
        let (ux, uy) = if use_trig {
            let theta = madd(0.017453292519943295, (tick + 1) as f64, 0.7853981633974483 * (d as f64), use_fma);
            (theta.cos(), theta.sin())
        } else {
            (dir_fx[d], dir_fy[d])
        };
        if want_dash && bfsm[actor] == 0 {
            bfsm[actor] = 1;
            btimer[actor] = 12;
            bvx[actor] = madd(6.0, ux, bvx[actor], use_fma);
            bvy[actor] = madd(6.0, uy, bvy[actor], use_fma);
        } else {
            bvx[actor] = madd(2.0, ux, bvx[actor], use_fma);
            bvy[actor] = madd(2.0, uy, bvy[actor], use_fma);
        }

        for i in 0..N_BODIES {
            if bfsm[i] == 1 {
                btimer[i] -= 1;
                if btimer[i] == 0 {
                    bfsm[i] = 2;
                    btimer[i] = 40;
                }
            } else if bfsm[i] == 2 {
                btimer[i] -= 1;
                if btimer[i] == 0 {
                    bfsm[i] = 0;
                }
            }
            let drag = if bfsm[i] == 1 { drag_dash_f } else { drag_idle_f };
            let mut vx = (bvx[i] * drag).clamp(-48.0, 48.0);
            let mut vy = (bvy[i] * drag).clamp(-48.0, 48.0);
            let mut x = madd(vx, dt_f, bx[i], use_fma);
            let mut y = madd(vy, dt_f, by[i], use_fma);
            if x > 62.0 {
                x = 124.0 - x;
                vx = -(vx * rest_wall_f);
            } else if x < -62.0 {
                x = -124.0 - x;
                vx = -(vx * rest_wall_f);
            }
            if y > 62.0 {
                y = 124.0 - y;
                vy = -(vy * rest_wall_f);
            } else if y < -62.0 {
                y = -124.0 - y;
                vy = -(vy * rest_wall_f);
            }
            bx[i] = x;
            by[i] = y;
            bvx[i] = vx;
            bvy[i] = vy;
        }

        for i in 0..N_BODIES {
            for j in (i + 1)..N_BODIES {
                let dx = bx[j] - bx[i];
                let dy = by[j] - by[i];
                let dist_sq = madd(dx, dx, dy * dy, use_fma);
                if dist_sq > 0.0 && dist_sq < 16.0 {
                    let dist = dist_sq.sqrt();
                    let nx = dx / dist;
                    let ny = dy / dist;
                    let sep = 0.5 * (4.0 - dist);
                    bx[i] = madd(-sep, nx, bx[i], use_fma);
                    by[i] = madd(-sep, ny, by[i], use_fma);
                    bx[j] = madd(sep, nx, bx[j], use_fma);
                    by[j] = madd(sep, ny, by[j], use_fma);
                    let rvx = bvx[j] - bvx[i];
                    let rvy = bvy[j] - bvy[i];
                    let vn = madd(rvx, nx, rvy * ny, use_fma);
                    if vn < 0.0 {
                        let j_base = (-vn) * one_plus_e_f;
                        let msum = bmass[i] + bmass[j];
                        let dvi = (j_base * bmass[j]) / msum;
                        let dvj = (j_base * bmass[i]) / msum;
                        bvx[i] = madd(-dvi, nx, bvx[i], use_fma);
                        bvy[i] = madd(-dvi, ny, bvy[i], use_fma);
                        bvx[j] = madd(dvj, nx, bvx[j], use_fma);
                        bvy[j] = madd(dvj, ny, bvy[j], use_fma);
                    }
                }
            }
        }

        let mut deact = [0u8; N_PICKUPS];
        let mut resp = [0u8; N_PICKUPS];
        for p in 0..N_PICKUPS {
            if pactive[p] == 1 {
                for i in 0..N_BODIES {
                    let pdx = bx[i] - px[p];
                    let pdy = by[i] - py[p];
                    if madd(pdx, pdx, pdy * pdy, use_fma) <= 25.0 {
                        bscore[i] += 1;
                        deact[p] = 1;
                        break;
                    }
                }
            } else {
                prespawn[p] -= 1;
                if prespawn[p] == 0 {
                    resp[p] = 1;
                }
            }
        }
        for p in 0..N_PICKUPS {
            if deact[p] == 1 {
                pactive[p] = 0;
                prespawn[p] = 75;
            }
            if resp[p] == 1 {
                let (rng3, rp) = splitmix64_next(rng);
                rng = rng3;
                px[p] = ((((rp & 0xFFFF_FFFF) as i64) - 2147483648) * 80) as f64 / one_f;
                py[p] = (((((rp >> 32) & 0xFFFF_FFFF) as i64) - 2147483648) * 80) as f64 / one_f;
                pactive[p] = 1;
            }
        }

        tick += 1;
        ieee_buf[0..4].copy_from_slice(&tick.to_le_bytes());
        ieee_buf[4..12].copy_from_slice(&rng.to_le_bytes());
        mm_buf[0..4].copy_from_slice(&tick.to_le_bytes());
        gp_buf[0..4].copy_from_slice(&tick.to_le_bytes());
        let (mut o1, mut o2, mut o3) = (12usize, 4usize, 4usize);
        for i in 0..N_BODIES {
            ieee_buf[o1..o1 + 8].copy_from_slice(&canon_f64(bx[i]).to_bits().to_le_bytes()); o1 += 8;
            ieee_buf[o1..o1 + 8].copy_from_slice(&canon_f64(by[i]).to_bits().to_le_bytes()); o1 += 8;
            ieee_buf[o1..o1 + 8].copy_from_slice(&canon_f64(bvx[i]).to_bits().to_le_bytes()); o1 += 8;
            ieee_buf[o1..o1 + 8].copy_from_slice(&canon_f64(bvy[i]).to_bits().to_le_bytes()); o1 += 8;
            ieee_buf[o1..o1 + 4].copy_from_slice(&bscore[i].to_le_bytes()); o1 += 4;
            ieee_buf[o1..o1 + 2].copy_from_slice(&btimer[i].to_le_bytes()); o1 += 2;
            ieee_buf[o1] = bfsm[i]; o1 += 1;
            ieee_buf[o1] = 0; o1 += 1;

            let qx = (bx[i] * 1000.0).floor() as i64;
            let qy = (by[i] * 1000.0).floor() as i64;
            mm_buf[o2..o2 + 8].copy_from_slice(&qx.to_le_bytes()); o2 += 8;
            mm_buf[o2..o2 + 8].copy_from_slice(&qy.to_le_bytes()); o2 += 8;
            mm_buf[o2..o2 + 4].copy_from_slice(&bscore[i].to_le_bytes()); o2 += 4;
            mm_buf[o2..o2 + 2].copy_from_slice(&btimer[i].to_le_bytes()); o2 += 2;
            mm_buf[o2] = bfsm[i]; o2 += 1;

            let quad = (if bx[i] >= 0.0 { 1u8 } else { 0u8 }) | (if by[i] >= 0.0 { 2u8 } else { 0u8 });
            gp_buf[o3..o3 + 4].copy_from_slice(&bscore[i].to_le_bytes()); o3 += 4;
            gp_buf[o3] = bfsm[i]; o3 += 1;
            gp_buf[o3] = quad; o3 += 1;
        }
        for p in 0..N_PICKUPS {
            ieee_buf[o1..o1 + 8].copy_from_slice(&canon_f64(px[p]).to_bits().to_le_bytes()); o1 += 8;
            ieee_buf[o1..o1 + 8].copy_from_slice(&canon_f64(py[p]).to_bits().to_le_bytes()); o1 += 8;
            ieee_buf[o1..o1 + 2].copy_from_slice(&prespawn[p].to_le_bytes()); o1 += 2;
            ieee_buf[o1] = pactive[p]; o1 += 1;
            ieee_buf[o1] = 0; o1 += 1;
            gp_buf[o3] = pactive[p]; o3 += 1;
        }
        out.push((
            sha256_hex(&ieee_buf)[..16].to_string(),
            sha256_hex(&mm_buf)[..16].to_string(),
            sha256_hex(&gp_buf)[..16].to_string(),
        ));
    }
    out
}

fn run_f32_trace(ticks: u32, use_trig: bool) -> Vec<(String, String, String)> {
    let one_f = ONE as f64;
    let dir_fx: [f32; 8] = DIR_X.map(|v| ((v as f64) / one_f) as f32);
    let dir_fy: [f32; 8] = DIR_Y.map(|v| ((v as f64) / one_f) as f32);

    let mut rng: u64 = INITIAL_SEED;
    let mut bx = [0.0f32; N_BODIES];
    let mut by = [0.0f32; N_BODIES];
    let mut bvx = [0.0f32; N_BODIES];
    let mut bvy = [0.0f32; N_BODIES];
    let mut bmass = [0.0f32; N_BODIES];
    let mut bfsm = [0u8; N_BODIES];
    let mut btimer = [0u16; N_BODIES];
    let mut bscore = [0u32; N_BODIES];

    for i in 0..N_BODIES {
        let gx = (((i as i64 & 3) * 30) - 45) * ONE;
        let gy = ((((i as i64) >> 2) * 30) - 45) * ONE;
        let (r_next1, r1) = splitmix64_next(rng);
        let (r_next2, r2) = splitmix64_next(r_next1);
        rng = r_next2;
        let jx = ((r1 & 0xFFFF_FFFF) as i64) - 2147483648;
        let jy = (((r1 >> 32) & 0xFFFF_FFFF) as i64) - 2147483648;
        bx[i] = (((gx + jx) as f64) / one_f) as f32;
        by[i] = (((gy + jy) as f64) / one_f) as f32;
        bvx[i] = (((((r2 & 0xFFFF_FFFF) as i64) - 2147483648) * 24) as f64 / one_f) as f32;
        bvy[i] = ((((((r2 >> 32) & 0xFFFF_FFFF) as i64) - 2147483648) * 24) as f64 / one_f) as f32;
        bmass[i] = ((((4 + (i as i64 & 3)) << 30) as f64) / one_f) as f32;
    }

    let mut px = [0.0f32; N_PICKUPS];
    let mut py = [0.0f32; N_PICKUPS];
    let mut pactive = [1u8; N_PICKUPS];
    let mut prespawn = [0u16; N_PICKUPS];
    for p in 0..N_PICKUPS {
        px[p] = if (p & 1) == 0 { -20.0 } else { 20.0 };
        py[p] = if (p >> 1) == 0 { -20.0 } else { 20.0 };
    }

    let dt_f = 1.0f32 / 64.0f32;
    let drag_idle_f = ((DRAG_IDLE as f64) / one_f) as f32;
    let drag_dash_f = ((DRAG_DASH as f64) / one_f) as f32;
    let rest_wall_f = ((REST_WALL as f64) / one_f) as f32;
    let one_plus_e_f = ((ONE_PLUS_E as f64) / one_f) as f32;

    let mut out = Vec::with_capacity(ticks as usize);
    let mut ieee_buf = [0u8; 732];
    let mut mm_buf = [0u8; 4 + N_BODIES * 23];
    let mut gp_buf = [0u8; 4 + N_BODIES * 6 + N_PICKUPS];
    let mut tick: u32 = 0;

    for _ in 0..ticks {
        let (rng2, ev) = splitmix64_next(rng);
        rng = rng2;
        let actor = (ev & 15) as usize;
        let d = ((ev >> 4) & 7) as usize;
        let want_dash = ((ev >> 7) & 3) == 0;
        let (ux, uy) = if use_trig {
            let theta = 0.017453292519943295f32 * ((tick + 1) as f32) + 0.7853981633974483f32 * (d as f32);
            (theta.cos(), theta.sin())
        } else {
            (dir_fx[d], dir_fy[d])
        };
        if want_dash && bfsm[actor] == 0 {
            bfsm[actor] = 1;
            btimer[actor] = 12;
            bvx[actor] = bvx[actor] + 6.0 * ux;
            bvy[actor] = bvy[actor] + 6.0 * uy;
        } else {
            bvx[actor] = bvx[actor] + 2.0 * ux;
            bvy[actor] = bvy[actor] + 2.0 * uy;
        }

        for i in 0..N_BODIES {
            if bfsm[i] == 1 {
                btimer[i] -= 1;
                if btimer[i] == 0 {
                    bfsm[i] = 2;
                    btimer[i] = 40;
                }
            } else if bfsm[i] == 2 {
                btimer[i] -= 1;
                if btimer[i] == 0 {
                    bfsm[i] = 0;
                }
            }
            let drag = if bfsm[i] == 1 { drag_dash_f } else { drag_idle_f };
            let mut vx = (bvx[i] * drag).clamp(-48.0, 48.0);
            let mut vy = (bvy[i] * drag).clamp(-48.0, 48.0);
            let mut x = bx[i] + vx * dt_f;
            let mut y = by[i] + vy * dt_f;
            if x > 62.0 {
                x = 124.0 - x;
                vx = -(vx * rest_wall_f);
            } else if x < -62.0 {
                x = -124.0 - x;
                vx = -(vx * rest_wall_f);
            }
            if y > 62.0 {
                y = 124.0 - y;
                vy = -(vy * rest_wall_f);
            } else if y < -62.0 {
                y = -124.0 - y;
                vy = -(vy * rest_wall_f);
            }
            bx[i] = x;
            by[i] = y;
            bvx[i] = vx;
            bvy[i] = vy;
        }

        for i in 0..N_BODIES {
            for j in (i + 1)..N_BODIES {
                let dx = bx[j] - bx[i];
                let dy = by[j] - by[i];
                let dist_sq = dx * dx + dy * dy;
                if dist_sq > 0.0 && dist_sq < 16.0 {
                    let dist = dist_sq.sqrt();
                    let nx = dx / dist;
                    let ny = dy / dist;
                    let sep = 0.5 * (4.0 - dist);
                    bx[i] = bx[i] - sep * nx;
                    by[i] = by[i] - sep * ny;
                    bx[j] = bx[j] + sep * nx;
                    by[j] = by[j] + sep * ny;
                    let rvx = bvx[j] - bvx[i];
                    let rvy = bvy[j] - bvy[i];
                    let vn = rvx * nx + rvy * ny;
                    if vn < 0.0 {
                        let j_base = (-vn) * one_plus_e_f;
                        let msum = bmass[i] + bmass[j];
                        let dvi = (j_base * bmass[j]) / msum;
                        let dvj = (j_base * bmass[i]) / msum;
                        bvx[i] = bvx[i] - dvi * nx;
                        bvy[i] = bvy[i] - dvi * ny;
                        bvx[j] = bvx[j] + dvj * nx;
                        bvy[j] = bvy[j] + dvj * ny;
                    }
                }
            }
        }

        let mut deact = [0u8; N_PICKUPS];
        let mut resp = [0u8; N_PICKUPS];
        for p in 0..N_PICKUPS {
            if pactive[p] == 1 {
                for i in 0..N_BODIES {
                    let pdx = bx[i] - px[p];
                    let pdy = by[i] - py[p];
                    if pdx * pdx + pdy * pdy <= 25.0 {
                        bscore[i] += 1;
                        deact[p] = 1;
                        break;
                    }
                }
            } else {
                prespawn[p] -= 1;
                if prespawn[p] == 0 {
                    resp[p] = 1;
                }
            }
        }
        for p in 0..N_PICKUPS {
            if deact[p] == 1 {
                pactive[p] = 0;
                prespawn[p] = 75;
            }
            if resp[p] == 1 {
                let (rng3, rp) = splitmix64_next(rng);
                rng = rng3;
                px[p] = (((((rp & 0xFFFF_FFFF) as i64) - 2147483648) * 80) as f64 / one_f) as f32;
                py[p] = ((((((rp >> 32) & 0xFFFF_FFFF) as i64) - 2147483648) * 80) as f64 / one_f) as f32;
                pactive[p] = 1;
            }
        }

        tick += 1;
        ieee_buf[0..4].copy_from_slice(&tick.to_le_bytes());
        ieee_buf[4..12].copy_from_slice(&rng.to_le_bytes());
        mm_buf[0..4].copy_from_slice(&tick.to_le_bytes());
        gp_buf[0..4].copy_from_slice(&tick.to_le_bytes());
        let (mut o1, mut o2, mut o3) = (12usize, 4usize, 4usize);
        for i in 0..N_BODIES {
            ieee_buf[o1..o1 + 8].copy_from_slice(&canon_f64(bx[i] as f64).to_bits().to_le_bytes()); o1 += 8;
            ieee_buf[o1..o1 + 8].copy_from_slice(&canon_f64(by[i] as f64).to_bits().to_le_bytes()); o1 += 8;
            ieee_buf[o1..o1 + 8].copy_from_slice(&canon_f64(bvx[i] as f64).to_bits().to_le_bytes()); o1 += 8;
            ieee_buf[o1..o1 + 8].copy_from_slice(&canon_f64(bvy[i] as f64).to_bits().to_le_bytes()); o1 += 8;
            ieee_buf[o1..o1 + 4].copy_from_slice(&bscore[i].to_le_bytes()); o1 += 4;
            ieee_buf[o1..o1 + 2].copy_from_slice(&btimer[i].to_le_bytes()); o1 += 2;
            ieee_buf[o1] = bfsm[i]; o1 += 1;
            ieee_buf[o1] = 0; o1 += 1;

            let qx = ((bx[i] as f64) * 1000.0).floor() as i64;
            let qy = ((by[i] as f64) * 1000.0).floor() as i64;
            mm_buf[o2..o2 + 8].copy_from_slice(&qx.to_le_bytes()); o2 += 8;
            mm_buf[o2..o2 + 8].copy_from_slice(&qy.to_le_bytes()); o2 += 8;
            mm_buf[o2..o2 + 4].copy_from_slice(&bscore[i].to_le_bytes()); o2 += 4;
            mm_buf[o2..o2 + 2].copy_from_slice(&btimer[i].to_le_bytes()); o2 += 2;
            mm_buf[o2] = bfsm[i]; o2 += 1;

            let quad = (if bx[i] >= 0.0 { 1u8 } else { 0u8 }) | (if by[i] >= 0.0 { 2u8 } else { 0u8 });
            gp_buf[o3..o3 + 4].copy_from_slice(&bscore[i].to_le_bytes()); o3 += 4;
            gp_buf[o3] = bfsm[i]; o3 += 1;
            gp_buf[o3] = quad; o3 += 1;
        }
        for p in 0..N_PICKUPS {
            ieee_buf[o1..o1 + 8].copy_from_slice(&canon_f64(px[p] as f64).to_bits().to_le_bytes()); o1 += 8;
            ieee_buf[o1..o1 + 8].copy_from_slice(&canon_f64(py[p] as f64).to_bits().to_le_bytes()); o1 += 8;
            ieee_buf[o1..o1 + 2].copy_from_slice(&prespawn[p].to_le_bytes()); o1 += 2;
            ieee_buf[o1] = pactive[p]; o1 += 1;
            ieee_buf[o1] = 0; o1 += 1;
            gp_buf[o3] = pactive[p]; o3 += 1;
        }
        out.push((
            sha256_hex(&ieee_buf)[..16].to_string(),
            sha256_hex(&mm_buf)[..16].to_string(),
            sha256_hex(&gp_buf)[..16].to_string(),
        ));
    }
    out
}

fn main() {
    let args: Vec<String> = env::args().collect();
    let get_arg = |flag: &str, def: &str| -> String {
        for i in 1..args.len() {
            if args[i] == flag && i + 1 < args.len() {
                return args[i + 1].clone();
            }
        }
        def.to_string()
    };
    let mode = get_arg("--mode", "q32");
    let ticks: u32 = get_arg("--ticks", "100000").parse().unwrap();
    let stride: u32 = get_arg("--stride", "1000").parse().unwrap();
    let loops: u32 = get_arg("--loops", "1").parse().unwrap();
    let handshake = args.iter().any(|a| a == "--handshake");

    if mode == "q32" {
        let _ = run_q32_sim(500, 500);
        let stdin = io::stdin();
        let mut stdout = io::stdout();
        let mut line = String::new();
        if handshake {
            let _ = writeln!(stdout, "READY");
            let _ = stdout.flush();
            let _ = stdin.lock().read_line(&mut line);
        }
        let t0 = Instant::now();
        let mut ck = Vec::new();
        for _ in 0..loops {
            ck = run_q32_sim(ticks, stride);
        }
        let wall_ms = (t0.elapsed().as_secs_f64() * 1000.0) / (loops as f64);
        let mut json = format!("{{\"wall_ms\":{:.6},\"loops\":{},\"checkpoints\":{{", wall_ms, loops);
        for (idx, (t, h)) in ck.iter().enumerate() {
            if idx > 0 {
                json.push(',');
            }
            json.push_str(&format!("\"{}\":\"{}\"", t, h));
        }
        json.push_str("}}");
        let _ = writeln!(stdout, "DONE\t{}", json);
        let _ = stdout.flush();
        if handshake {
            line.clear();
            let _ = stdin.lock().read_line(&mut line);
        }
    } else {
        let tr = match mode.as_str() {
            "f64_strict" => run_f64_trace(ticks, false, false),
            "f64_trig" => run_f64_trace(ticks, true, false),
            "f64_fma" => run_f64_trace(ticks, false, true),
            "f64_fma_trig" => run_f64_trace(ticks, true, true),
            "f32_strict" => run_f32_trace(ticks, false),
            "f32_trig" => run_f32_trace(ticks, true),
            other => panic!("Unknown mode: {}", other),
        };
        let mut json = String::from("{\"trace\":[");
        for (idx, (h1, h2, h3)) in tr.iter().enumerate() {
            if idx > 0 {
                json.push(',');
            }
            json.push_str(&format!("[\"{}\",\"{}\",\"{}\"]", h1, h2, h3));
        }
        json.push_str("]}");
        println!("{}", json);
    }
}
