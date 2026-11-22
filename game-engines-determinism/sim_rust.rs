// Rust native (`aarch64-apple-darwin`) target for `game-engines` (`GE-H1` Q32.32 & `GE-H2` f64).
// Compiled via: rustc --edition 2021 -O sim_rust.rs -o sim_rust

use std::env;
use std::io::{self, BufRead, Write};
use std::time::Instant;

extern "C" {
    fn CC_SHA256(data: *const u8, len: u32, md: *mut u8) -> *mut u8;
}

fn sha256_hex(bytes: &[u8]) -> String {
    let mut md = [0u8; 32];
    unsafe {
        CC_SHA256(bytes.as_ptr(), bytes.len() as u32, md.as_mut_ptr());
    }
    let mut s = String::with_capacity(64);
    for b in md {
        use std::fmt::Write as _;
        let _ = write!(&mut s, "{:02x}", b);
    }
    s
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

fn run_f64_trace(ticks: u32, use_trig: bool) -> Vec<(String, String, String)> {
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

    for _ in 0..ticks {
        let (rng2, ev) = splitmix64_next(rng);
        rng = rng2;
        let actor = (ev & 15) as usize;
        let d = ((ev >> 4) & 7) as usize;
        let want_dash = ((ev >> 7) & 3) == 0;
        let (ux, uy) = if use_trig {
            let theta = 0.017453292519943295 * ((tick + 1) as f64) + 0.7853981633974483 * (d as f64);
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
        let tr = run_f64_trace(ticks, mode == "f64_trig");
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
