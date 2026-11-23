use bytemuck::{Pod, Zeroable};
use flate2::read::GzDecoder;
use flate2::write::GzEncoder;
use flate2::Compression;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, HashSet};
use std::env;
use std::fs::{self, File};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::time::Instant;

const WIDTH: u32 = 512;
const HEIGHT: u32 = 512;
const FB_BYTES: usize = (WIDTH as usize) * (HEIGHT as usize) * 4;
const CANONICAL_TICKS: [u32; 4] = [0, 250, 1000, 10000];

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

fn sha256_hex(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    let out = hasher.finalize();
    let mut s = String::with_capacity(64);
    for b in out {
        use std::fmt::Write as _;
        let _ = write!(&mut s, "{:02x}", b);
    }
    s
}

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
fn qmul32(a: i64, b: i64) -> i64 {
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

#[derive(Clone)]
struct SimState {
    tick: u32,
    rng: u64,
    bx: [i64; N_BODIES],
    by: [i64; N_BODIES],
    bvx: [i64; N_BODIES],
    bvy: [i64; N_BODIES],
    bmass: [i64; N_BODIES],
    bfsm: [u8; N_BODIES],
    btimer: [u16; N_BODIES],
    bscore: [u32; N_BODIES],
    px: [i64; N_PICKUPS],
    py: [i64; N_PICKUPS],
    pactive: [u8; N_PICKUPS],
    prespawn: [u16; N_PICKUPS],
}

impl SimState {
    fn new_initial() -> Self {
        let mut rng: u64 = INITIAL_SEED;
        let mut bx = [0i64; N_BODIES];
        let mut by = [0i64; N_BODIES];
        let mut bvx = [0i64; N_BODIES];
        let mut bvy = [0i64; N_BODIES];
        let mut bmass = [0i64; N_BODIES];

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
        let pactive = [1u8; N_PICKUPS];
        let prespawn = [0u16; N_PICKUPS];
        for p in 0..N_PICKUPS {
            px[p] = if (p & 1) == 0 { -20 * ONE } else { 20 * ONE };
            py[p] = if (p >> 1) == 0 { -20 * ONE } else { 20 * ONE };
        }

        Self {
            tick: 0,
            rng,
            bx,
            by,
            bvx,
            bvy,
            bmass,
            bfsm: [0u8; N_BODIES],
            btimer: [0u16; N_BODIES],
            bscore: [0u32; N_BODIES],
            px,
            py,
            pactive,
            prespawn,
        }
    }

    fn step_one(&mut self) {
        let (rng2, ev) = splitmix64_next(self.rng);
        self.rng = rng2;
        let actor = (ev & 15) as usize;
        let d = ((ev >> 4) & 7) as usize;
        let want_dash = ((ev >> 7) & 3) == 0;
        if want_dash && self.bfsm[actor] == 0 {
            self.bfsm[actor] = 1;
            self.btimer[actor] = 12;
            self.bvx[actor] += 6 * DIR_X[d];
            self.bvy[actor] += 6 * DIR_Y[d];
        } else {
            self.bvx[actor] += 2 * DIR_X[d];
            self.bvy[actor] += 2 * DIR_Y[d];
        }

        for i in 0..N_BODIES {
            if self.bfsm[i] == 1 {
                self.btimer[i] -= 1;
                if self.btimer[i] == 0 {
                    self.bfsm[i] = 2;
                    self.btimer[i] = 40;
                }
            } else if self.bfsm[i] == 2 {
                self.btimer[i] -= 1;
                if self.btimer[i] == 0 {
                    self.bfsm[i] = 0;
                }
            }
            let drag = if self.bfsm[i] == 1 { DRAG_DASH } else { DRAG_IDLE };
            let mut vx = qmul32(self.bvx[i], drag).clamp(-MAX_V, MAX_V);
            let mut vy = qmul32(self.bvy[i], drag).clamp(-MAX_V, MAX_V);
            let mut x = self.bx[i] + qmul32(vx, DT_Q);
            let mut y = self.by[i] + qmul32(vy, DT_Q);
            if x > BOUND {
                x = 2 * BOUND - x;
                vx = -qmul32(vx, REST_WALL);
            } else if x < -BOUND {
                x = -2 * BOUND - x;
                vx = -qmul32(vx, REST_WALL);
            }
            if y > BOUND {
                y = 2 * BOUND - y;
                vy = -qmul32(vy, REST_WALL);
            } else if y < -BOUND {
                y = -2 * BOUND - y;
                vy = -qmul32(vy, REST_WALL);
            }
            self.bx[i] = x;
            self.by[i] = y;
            self.bvx[i] = vx;
            self.bvy[i] = vy;
        }

        for i in 0..N_BODIES {
            for j in (i + 1)..N_BODIES {
                let dx = self.bx[j] - self.bx[i];
                let dy = self.by[j] - self.by[i];
                let dist_sq = (dx as i128) * (dx as i128) + (dy as i128) * (dy as i128);
                if dist_sq > 0 && dist_sq < MIN_DIST_SQ {
                    let dist = isqrt_u128(dist_sq as u128);
                    let nx = trunc_div128((dx as i128) * (ONE as i128), dist as i128);
                    let ny = trunc_div128((dy as i128) * (ONE as i128), dist as i128);
                    let sep = (MIN_DIST - dist) >> 1;
                    let cx = qmul32(sep, nx);
                    let cy = qmul32(sep, ny);
                    self.bx[i] -= cx;
                    self.by[i] -= cy;
                    self.bx[j] += cx;
                    self.by[j] += cy;

                    let rvx = self.bvx[j] - self.bvx[i];
                    let rvy = self.bvy[j] - self.bvy[i];
                    let vn = qmul32(rvx, nx) + qmul32(rvy, ny);
                    if vn < 0 {
                        let j_base = qmul32(-vn, ONE_PLUS_E);
                        let msum = self.bmass[i] + self.bmass[j];
                        let dvi = trunc_div128((j_base as i128) * (self.bmass[j] as i128), msum as i128);
                        let dvj = trunc_div128((j_base as i128) * (self.bmass[i] as i128), msum as i128);
                        self.bvx[i] -= qmul32(dvi, nx);
                        self.bvy[i] -= qmul32(dvi, ny);
                        self.bvx[j] += qmul32(dvj, nx);
                        self.bvy[j] += qmul32(dvj, ny);
                    }
                }
            }
        }

        let mut deact = [0u8; N_PICKUPS];
        let mut resp = [0u8; N_PICKUPS];
        for p in 0..N_PICKUPS {
            if self.pactive[p] == 1 {
                for i in 0..N_BODIES {
                    let pdx = self.bx[i] - self.px[p];
                    let pdy = self.by[i] - self.py[p];
                    if (pdx as i128) * (pdx as i128) + (pdy as i128) * (pdy as i128) <= PICKUP_DIST_SQ {
                        self.bscore[i] += 1;
                        deact[p] = 1;
                        break;
                    }
                }
            } else {
                self.prespawn[p] -= 1;
                if self.prespawn[p] == 0 {
                    resp[p] = 1;
                }
            }
        }
        for p in 0..N_PICKUPS {
            if deact[p] == 1 {
                self.pactive[p] = 0;
                self.prespawn[p] = 75;
            }
            if resp[p] == 1 {
                let (rng3, rp) = splitmix64_next(self.rng);
                self.rng = rng3;
                self.px[p] = (((rp & 0xFFFF_FFFF) as i64) - 2147483648) * 80;
                self.py[p] = ((((rp >> 32) & 0xFFFF_FFFF) as i64) - 2147483648) * 80;
                self.pactive[p] = 1;
            }
        }
        self.tick += 1;
    }

    fn canonical_sha256(&self) -> String {
        let mut buf = [0u8; 732];
        buf[0..4].copy_from_slice(&self.tick.to_le_bytes());
        buf[4..12].copy_from_slice(&self.rng.to_le_bytes());
        let mut o = 12;
        for i in 0..N_BODIES {
            buf[o..o + 8].copy_from_slice(&self.bx[i].to_le_bytes());
            o += 8;
            buf[o..o + 8].copy_from_slice(&self.by[i].to_le_bytes());
            o += 8;
            buf[o..o + 8].copy_from_slice(&self.bvx[i].to_le_bytes());
            o += 8;
            buf[o..o + 8].copy_from_slice(&self.bvy[i].to_le_bytes());
            o += 8;
            buf[o..o + 4].copy_from_slice(&self.bscore[i].to_le_bytes());
            o += 4;
            buf[o..o + 2].copy_from_slice(&self.btimer[i].to_le_bytes());
            o += 2;
            buf[o] = self.bfsm[i];
            o += 1;
            buf[o] = 0;
            o += 1;
        }
        for p in 0..N_PICKUPS {
            buf[o..o + 8].copy_from_slice(&self.px[p].to_le_bytes());
            o += 8;
            buf[o..o + 8].copy_from_slice(&self.py[p].to_le_bytes());
            o += 8;
            buf[o..o + 2].copy_from_slice(&self.prespawn[p].to_le_bytes());
            o += 2;
            buf[o] = self.pactive[p];
            o += 1;
            buf[o] = 0;
            o += 1;
        }
        sha256_hex(&buf)
    }
}

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
struct SceneUniforms {
    header: [f32; 4],
    body_pos_vel: [[f32; 4]; 16],
    body_meta: [[f32; 4]; 16],
    pickups: [[f32; 4]; 4],
}

impl SceneUniforms {
    fn from_state(st: &SimState) -> Self {
        let one_f = ONE as f64;
        let phase_rad = ((st.tick % 256) as f64) * (std::f64::consts::TAU / 256.0);
        let mut body_pos_vel = [[0.0f32; 4]; 16];
        let mut body_meta = [[0.0f32; 4]; 16];
        for i in 0..N_BODIES {
            body_pos_vel[i] = [
                (st.bx[i] as f64 / one_f) as f32,
                (st.by[i] as f64 / one_f) as f32,
                (st.bvx[i] as f64 / one_f) as f32,
                (st.bvy[i] as f64 / one_f) as f32,
            ];
            body_meta[i] = [
                2.0f32,
                st.bfsm[i] as f32,
                (i & 3) as f32,
                st.bscore[i] as f32,
            ];
        }
        let mut pickups = [[0.0f32; 4]; 4];
        for p in 0..N_PICKUPS {
            pickups[p] = [
                (st.px[p] as f64 / one_f) as f32,
                (st.py[p] as f64 / one_f) as f32,
                3.0f32,
                st.pactive[p] as f32,
            ];
        }
        Self {
            header: [phase_rad as f32, 64.0f32, 16.0f32, st.tick as f32],
            body_pos_vel,
            body_meta,
            pickups,
        }
    }
}

// ============================================================================
// Deterministic CPU Q16.16 Integer Software Reference Rasterizer (0 float ops)
// ============================================================================

const Q16_ONE: i64 = 1 << 16; // 65536
const Q16_PI: i64 = 205887; // round(pi * 65536)
const Q16_TAU: i64 = 411775; // round(2*pi * 65536)
const Q16_HALF_PI: i64 = 102944;

#[inline]
fn q16_mul(a: i64, b: i64) -> i64 {
    (a * b) >> 16
}

#[inline]
fn q16_div(a: i64, b: i64) -> i64 {
    if b == 0 {
        return 0;
    }
    ((a as i128 * Q16_ONE as i128) / (b as i128)) as i64
}

#[inline]
fn q16_clamp01(v: i64) -> i64 {
    v.clamp(0, Q16_ONE)
}

/// Pure-integer 5th-order minimax/Taylor polynomial sine in Q16.16 (zero floats).
fn q16_sin(rad_q16: i64) -> i64 {
    let mut x = rad_q16 % Q16_TAU;
    if x > Q16_PI {
        x -= Q16_TAU;
    } else if x < -Q16_PI {
        x += Q16_TAU;
    }
    if x > Q16_HALF_PI {
        x = Q16_PI - x;
    } else if x < -Q16_HALF_PI {
        x = -Q16_PI - x;
    }
    // sin(x) ~= x - x^3/6 + x^5/120 - x^7/5040
    let x2 = q16_mul(x, x);
    let x3 = q16_mul(x2, x);
    let x5 = q16_mul(x3, x2);
    let x7 = q16_mul(x5, x2);
    let term3 = (x3 * 10923) >> 16; // 65536 / 6 = 10922.67
    let term5 = (x5 * 546) >> 16; // 65536 / 120 = 546.13
    let term7 = (x7 * 13) >> 16; // 65536 / 5040 = 13.00
    (x - term3 + term5 - term7).clamp(-Q16_ONE, Q16_ONE)
}

#[inline]
fn q16_cos(rad_q16: i64) -> i64 {
    q16_sin(rad_q16 + Q16_HALF_PI)
}

#[inline]
fn q16_pow16(v: i64) -> i64 {
    let v2 = q16_mul(v, v);
    let v4 = q16_mul(v2, v2);
    let v8 = q16_mul(v4, v4);
    q16_mul(v8, v8)
}

#[inline]
fn q16_pow32(v: i64) -> i64 {
    let v16 = q16_pow16(v);
    q16_mul(v16, v16)
}

#[inline]
fn q16_to_u8(c_q16: i64) -> u8 {
    let c = q16_clamp01(c_q16);
    (((c * 255) + 32768) >> 16).clamp(0, 255) as u8
}

fn rasterize_cpu_q16(st: &SimState) -> Vec<u8> {
    let mut fb = vec![0u8; FB_BYTES];
    let phase_q16 = (((st.tick % 256) as i64) * Q16_TAU) / 256;

    let mut bx_q16 = [0i64; N_BODIES];
    let mut by_q16 = [0i64; N_BODIES];
    for i in 0..N_BODIES {
        bx_q16[i] = st.bx[i] >> 16;
        by_q16[i] = st.by[i] >> 16;
    }
    let mut px_q16 = [0i64; N_PICKUPS];
    let mut py_q16 = [0i64; N_PICKUPS];
    for p in 0..N_PICKUPS {
        px_q16[p] = st.px[p] >> 16;
        py_q16[p] = st.py[p] >> 16;
    }

    // Normalized light & half vectors in Q16.16 matching shader.wgsl:
    // L = (-0.45, 0.60, 0.66143783), H = normalize(-0.45, 0.60, 1.66143783) = (-0.246885, 0.329181, 0.911543)
    let lx_q16: i64 = -29491;
    let ly_q16: i64 = 39322;
    let lz_q16: i64 = 43348;
    let hx_q16: i64 = -16180;
    let hy_q16: i64 = 21573;
    let hz_q16: i64 = 59739;

    for py_idx in 0..HEIGHT {
        // wy = (1 - (py + 0.5)/512 * 2) * 64 = 64 - (py * 2 + 1) / 8 in world units
        // In Q16.16: 64*65536 - ((2*py + 1) * 65536) / 8 = 4194304 - (2*py + 1)*8192
        let wy = (64 * Q16_ONE) - ((2 * (py_idx as i64) + 1) * 8192);
        for px_idx in 0..WIDTH {
            let wx = -(64 * Q16_ONE) + ((2 * (px_idx as i64) + 1) * 8192);
            let r_sq_q32 = (wx as i128) * (wx as i128) + (wy as i128) * (wy as i128);
            let r_q16 = isqrt_u128(r_sq_q32 as u128);

            // Background pass
            let ring_arg = q16_mul(r_q16, 22938) - phase_q16; // 0.35 * 65536 = 22938
            let ring_wave = (Q16_ONE + q16_cos(ring_arg)) >> 1;
            let gx = (Q16_ONE + q16_cos(q16_mul(wx, 25736))) >> 1; // 0.39269908 * 65536 = 25736
            let gy = (Q16_ONE + q16_cos(q16_mul(wy, 25736))) >> 1;
            let grid = q16_clamp01(q16_pow16(gx) + q16_pow16(gy));

            let max_abs = wx.abs().max(wy.abs());
            let box_d = (max_abs - 62 * Q16_ONE).abs();
            let box_d2 = q16_mul(box_d, box_d);
            let border = q16_div(Q16_ONE, Q16_ONE + q16_mul(box_d2, 42598)); // 0.65 * 65536

            let mut field_glow: i64 = 0;
            for p in 0..N_PICKUPS {
                if st.pactive[p] == 1 {
                    let dx = wx - px_q16[p];
                    let dy = wy - py_q16[p];
                    let d2 = q16_mul(dx, dx) + q16_mul(dy, dy);
                    field_glow += q16_div(9175, Q16_ONE + q16_mul(d2, 2294)); // 0.14 / (1 + 0.035*d2)
                }
            }

            let r2_q16 = q16_mul(r_q16, r_q16);
            let vig = q16_div(Q16_ONE, Q16_ONE + ((r2_q16 * 10) >> 16)); // 0.00015 * 65536 ~= 9.83

            let mut cr = q16_mul(2753, vig)
                + q16_mul(q16_mul(1180, ring_wave), vig)
                + q16_mul(q16_mul(3604, grid), vig)
                + q16_mul(23429, border)
                + q16_mul(2621, field_glow);
            let mut cg = q16_mul(3670, vig)
                + q16_mul(q16_mul(3146, ring_wave), vig)
                + q16_mul(q16_mul(6226, grid), vig)
                + q16_mul(15335, border)
                + q16_mul(27525, field_glow);
            let mut cb = q16_mul(6291, vig)
                + q16_mul(q16_mul(4719, ring_wave), vig)
                + q16_mul(q16_mul(8847, grid), vig)
                + q16_mul(3408, border)
                + q16_mul(23593, field_glow);

            cr = q16_clamp01(cr);
            cg = q16_clamp01(cg);
            cb = q16_clamp01(cb);
            // Quantize background to 8-bit UNORM just as RGBA8Unorm attachment stores Draw 1
            let mut dst_r = q16_to_u8(cr) as i64;
            let mut dst_g = q16_to_u8(cg) as i64;
            let mut dst_b = q16_to_u8(cb) as i64;

            // Entity instances 0..16 (bodies)
            let rad_body = 2 * Q16_ONE;
            let ext_body = q16_mul(rad_body, 121242); // 1.85
            for i in 0..N_BODIES {
                let dx = wx - bx_q16[i];
                let dy = wy - by_q16[i];
                if dx.abs() > ext_body || dy.abs() > ext_body {
                    continue;
                }
                let dist_sq_q32 = (dx as i128) * (dx as i128) + (dy as i128) * (dy as i128);
                let dist = isqrt_u128(dist_sq_q32 as u128);
                let u = dist >> 1; // dist / 2.0 in Q16.16

                let tier = ((i & 3) as i64) * 3932; // 0.06 * 65536
                let (br, bg, bb) = match st.bfsm[i] {
                    1 => (62915, 40632 + ((tier * 4) / 10), 6554),
                    2 => (23593 + ((tier * 3) / 10), 40632, 62915),
                    _ => (3932 + tier, 52429 - ((tier * 4) / 10), 43254 + ((tier * 3) / 10)),
                };

                let halo_env = q16_clamp01(q16_div(114688 - u, 49152)); // (1.75 - u) / 0.75
                let halo_wave = (Q16_ONE + q16_sin(q16_mul(dist, Q16_PI) - 2 * phase_q16)) >> 1;
                let halo_env2 = q16_mul(halo_env, halo_env);
                let halo_alpha = q16_mul(17039, q16_mul(halo_env2, halo_wave)); // 0.26

                let sphere_cov = q16_clamp01(((Q16_ONE - u) * 8) + 32768);
                let u_c = u.min(Q16_ONE);
                let one_m_u2 = (Q16_ONE - q16_mul(u_c, u_c)).max(7);
                let nz = isqrt_u128((one_m_u2 as u128) << 16);
                let nx = dx >> 1;
                let ny = dy >> 1;

                let ndotl = (q16_mul(nx, lx_q16) + q16_mul(ny, ly_q16) + q16_mul(nz, lz_q16)).max(0);
                let ndoth = (q16_mul(nx, hx_q16) + q16_mul(ny, hy_q16) + q16_mul(nz, hz_q16)).max(0);
                let spec = q16_pow32(ndoth);
                let one_m_nz = (Q16_ONE - nz).max(0);
                let rim = q16_mul(q16_mul(one_m_nz, one_m_nz), one_m_nz);
                let stripe = 57672 + q16_mul(7864, q16_cos(q16_mul(dy, 144179) + phase_q16)); // 0.88 + 0.12*cos(2.2*dy + phase)

                let diff_f = 14418 + q16_mul(51118, ndotl); // 0.22 + 0.78*ndotl
                let hi_f = q16_mul(36045, spec) + q16_mul(14418, rim); // 0.55*spec + 0.22*rim
                let sr = q16_clamp01(q16_mul(q16_mul(br, stripe), diff_f) + q16_mul(57672, hi_f));
                let sg = q16_clamp01(q16_mul(q16_mul(bg, stripe), diff_f) + q16_mul(61604, hi_f));
                let sb = q16_clamp01(q16_mul(q16_mul(bb, stripe), diff_f) + hi_f);

                let out_alpha = sphere_cov + q16_mul(halo_alpha, Q16_ONE - sphere_cov);
                if out_alpha > 33 {
                    let hr = q16_mul(br, 75366);
                    let hg = q16_mul(bg, 75366);
                    let hb = q16_mul(bb, 75366);
                    let rem = Q16_ONE - sphere_cov;
                    let pr = q16_mul(sr, sphere_cov) + q16_mul(hr, q16_mul(halo_alpha, rem));
                    let pg = q16_mul(sg, sphere_cov) + q16_mul(hg, q16_mul(halo_alpha, rem));
                    let pb = q16_mul(sb, sphere_cov) + q16_mul(hb, q16_mul(halo_alpha, rem));

                    let src_r = q16_to_u8(q16_div(pr, out_alpha)) as i64;
                    let src_g = q16_to_u8(q16_div(pg, out_alpha)) as i64;
                    let src_b = q16_to_u8(q16_div(pb, out_alpha)) as i64;
                    let a8 = q16_to_u8(out_alpha) as i64;

                    dst_r = (src_r * a8 + dst_r * (255 - a8) + 127) / 255;
                    dst_g = (src_g * a8 + dst_g * (255 - a8) + 127) / 255;
                    dst_b = (src_b * a8 + dst_b * (255 - a8) + 127) / 255;
                }
            }

            // Entity instances 16..20 (pickups)
            let rad_pk = 3 * Q16_ONE;
            let ext_pk = q16_mul(rad_pk, 121242);
            let r_ring = q16_mul(rad_pk, 49152); // 0.75 * 3.0
            let w_ring = q16_mul(rad_pk, 14418); // 0.22 * 3.0
            let cos_2phase = q16_cos(2 * phase_q16);
            for p in 0..N_PICKUPS {
                if st.pactive[p] == 0 {
                    continue;
                }
                let dx = wx - px_q16[p];
                let dy = wy - py_q16[p];
                if dx.abs() > ext_pk || dy.abs() > ext_pk {
                    continue;
                }
                let dist_sq_q32 = (dx as i128) * (dx as i128) + (dy as i128) * (dy as i128);
                let dist = isqrt_u128(dist_sq_q32 as u128);
                let ring_d = (dist - r_ring).abs() - w_ring;
                let ring_cov = q16_clamp01((-ring_d * 4) + 32768);
                if ring_cov == 0 {
                    continue;
                }
                let d2_q16 = (dist_sq_q32 >> 16).max(66) as i64;
                let diff_q16 = (((dx as i128) * (dx as i128) - (dy as i128) * (dy as i128)) >> 16) as i64;
                let cos2t = q16_div(diff_q16, d2_q16).clamp(-Q16_ONE, Q16_ONE);
                let cos4t = 2 * q16_mul(cos2t, cos2t) - Q16_ONE;
                let pulse = 51118 + q16_mul(14418, q16_mul(cos4t, cos_2phase));
                let src_r = q16_to_u8(q16_mul(64225, pulse) + 9830) as i64;
                let src_g = q16_to_u8(q16_mul(49807, pulse) + 13107) as i64;
                let src_b = q16_to_u8(q16_mul(11796, pulse) + 3277) as i64;
                let a8 = q16_to_u8(q16_mul(ring_cov, 60293)) as i64;

                dst_r = (src_r * a8 + dst_r * (255 - a8) + 127) / 255;
                dst_g = (src_g * a8 + dst_g * (255 - a8) + 127) / 255;
                dst_b = (src_b * a8 + dst_b * (255 - a8) + 127) / 255;
            }

            let off = ((py_idx * WIDTH + px_idx) * 4) as usize;
            fb[off] = dst_r.clamp(0, 255) as u8;
            fb[off + 1] = dst_g.clamp(0, 255) as u8;
            fb[off + 2] = dst_b.clamp(0, 255) as u8;
            fb[off + 3] = 255;
        }
    }
    fb
}

// ============================================================================
// Headless wgpu Renderer (Vulkan / Metal)
// ============================================================================

#[derive(Serialize, Deserialize, Clone)]
struct FrameReceipt {
    tick: u32,
    state_q32_sha256: String,
    framebuffer_rgba8_sha256: String,
    render_ms: f64,
    gz_file: String,
}

#[derive(Serialize, Deserialize, Clone)]
struct AdapterReceipt {
    adapter_key: String,
    host_id: String,
    name: String,
    backend: String,
    device_type: String,
    driver: String,
    driver_info: String,
    vendor_id: u32,
    device_id: u32,
    is_hardware_gpu: bool,
    frames: Vec<FrameReceipt>,
}

#[derive(Serialize, Deserialize)]
struct HostRenderManifest {
    host_id: String,
    bench_root: String,
    arch: String,
    os: String,
    canonical_ticks: Vec<u32>,
    state_q32_sha256_by_tick: BTreeMap<String, String>,
    adapters: Vec<AdapterReceipt>,
}

fn slugify(s: &str) -> String {
    let mut out = String::new();
    let mut prev_u = false;
    for ch in s.chars() {
        if ch.is_ascii_alphanumeric() {
            out.push(ch.to_ascii_lowercase());
            prev_u = false;
        } else if !prev_u && !out.is_empty() {
            out.push('_');
            prev_u = true;
        }
    }
    out.trim_matches('_').to_string()
}

fn write_gz(path: &Path, data: &[u8]) {
    let f = File::create(path).expect("create gz file");
    let mut enc = GzEncoder::new(f, Compression::fast());
    enc.write_all(data).expect("write gz");
    enc.finish().expect("finish gz");
}

fn read_gz(path: &Path) -> Vec<u8> {
    let f = File::open(path).expect("open gz file");
    let mut dec = GzDecoder::new(f);
    let mut buf = Vec::with_capacity(FB_BYTES);
    dec.read_to_end(&mut buf).expect("read gz");
    buf
}

fn render_on_adapter(
    adapter: &wgpu::Adapter,
    host_id: &str,
    states: &[(u32, SimState, String)],
    out_dir: &Path,
) -> Option<AdapterReceipt> {
    let info = adapter.get_info();
    let backend_str = format!("{:?}", info.backend);
    let dtype_str = format!("{:?}", info.device_type);
    let is_hw = matches!(
        info.device_type,
        wgpu::DeviceType::DiscreteGpu | wgpu::DeviceType::IntegratedGpu | wgpu::DeviceType::VirtualGpu
    );
    let adapter_key = format!(
        "{}_{}_{}",
        host_id,
        slugify(&backend_str),
        slugify(&info.name)
    );

    let req = pollster::block_on(adapter.request_device(
        &wgpu::DeviceDescriptor {
            label: Some("ge_h3_device"),
            required_features: wgpu::Features::empty(),
            required_limits: wgpu::Limits::downlevel_defaults(),
            ..Default::default()
        },
        None,
    ));
    let (device, queue) = match req {
        Ok(pair) => pair,
        Err(e) => {
            eprintln!("Skipping adapter {} ({}): {}", info.name, backend_str, e);
            return None;
        }
    };

    let shader_src = include_str!("../shader.wgsl");
    let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
        label: Some("ge_h3_shader"),
        source: wgpu::ShaderSource::Wgsl(shader_src.into()),
    });

    let uniform_buf = device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("ge_h3_uniforms"),
        size: std::mem::size_of::<SceneUniforms>() as u64,
        usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        mapped_at_creation: false,
    });

    let bgl = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
        label: Some("ge_h3_bgl"),
        entries: &[wgpu::BindGroupLayoutEntry {
            binding: 0,
            visibility: wgpu::ShaderStages::VERTEX | wgpu::ShaderStages::FRAGMENT,
            ty: wgpu::BindingType::Buffer {
                ty: wgpu::BufferBindingType::Uniform,
                has_dynamic_offset: false,
                min_binding_size: None,
            },
            count: None,
        }],
    });

    let bg = device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: Some("ge_h3_bg"),
        layout: &bgl,
        entries: &[wgpu::BindGroupEntry {
            binding: 0,
            resource: uniform_buf.as_entire_binding(),
        }],
    });

    let pl_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
        label: Some("ge_h3_pll"),
        bind_group_layouts: &[&bgl],
        push_constant_ranges: &[],
    });

    let bg_pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
        label: Some("ge_h3_bg_pipe"),
        layout: Some(&pl_layout),
        vertex: wgpu::VertexState {
            module: &shader,
            entry_point: "vs_bg",
            buffers: &[],
            compilation_options: Default::default(),
        },
        fragment: Some(wgpu::FragmentState {
            module: &shader,
            entry_point: "fs_bg",
            targets: &[Some(wgpu::ColorTargetState {
                format: wgpu::TextureFormat::Rgba8Unorm,
                blend: None,
                write_mask: wgpu::ColorWrites::ALL,
            })],
            compilation_options: Default::default(),
        }),
        primitive: wgpu::PrimitiveState {
            topology: wgpu::PrimitiveTopology::TriangleList,
            cull_mode: None,
            ..Default::default()
        },
        depth_stencil: None,
        multisample: wgpu::MultisampleState::default(),
        multiview: None,
        cache: None,
    });

    let entity_pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
        label: Some("ge_h3_entity_pipe"),
        layout: Some(&pl_layout),
        vertex: wgpu::VertexState {
            module: &shader,
            entry_point: "vs_entity",
            buffers: &[],
            compilation_options: Default::default(),
        },
        fragment: Some(wgpu::FragmentState {
            module: &shader,
            entry_point: "fs_entity",
            targets: &[Some(wgpu::ColorTargetState {
                format: wgpu::TextureFormat::Rgba8Unorm,
                blend: Some(wgpu::BlendState::ALPHA_BLENDING),
                write_mask: wgpu::ColorWrites::ALL,
            })],
            compilation_options: Default::default(),
        }),
        primitive: wgpu::PrimitiveState {
            topology: wgpu::PrimitiveTopology::TriangleList,
            cull_mode: None,
            ..Default::default()
        },
        depth_stencil: None,
        multisample: wgpu::MultisampleState::default(),
        multiview: None,
        cache: None,
    });

    let tex = device.create_texture(&wgpu::TextureDescriptor {
        label: Some("ge_h3_tex"),
        size: wgpu::Extent3d {
            width: WIDTH,
            height: HEIGHT,
            depth_or_array_layers: 1,
        },
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format: wgpu::TextureFormat::Rgba8Unorm,
        usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
        view_formats: &[],
    });
    let tex_view = tex.create_view(&wgpu::TextureViewDescriptor::default());

    let readback = device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("ge_h3_readback"),
        size: FB_BYTES as u64,
        usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
        mapped_at_creation: false,
    });

    // Warmup pass
    {
        let u0 = SceneUniforms::from_state(&states[0].1);
        queue.write_buffer(&uniform_buf, 0, bytemuck::bytes_of(&u0));
        let mut enc = device.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: None });
        {
            let mut rpass = enc.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: None,
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &tex_view,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color::BLACK),
                        store: wgpu::StoreOp::Store,
                    },
                })],
                depth_stencil_attachment: None,
                timestamp_writes: None,
                occlusion_query_set: None,
            });
            rpass.set_bind_group(0, &bg, &[]);
            rpass.set_pipeline(&bg_pipeline);
            rpass.draw(0..3, 0..1);
            rpass.set_pipeline(&entity_pipeline);
            rpass.draw(0..6, 0..20);
        }
        queue.submit(Some(enc.finish()));
        device.poll(wgpu::Maintain::Wait);
    }

    let mut frame_receipts = Vec::new();
    for (tick, st_q, st_hash) in states {
        let uniforms = SceneUniforms::from_state(st_q);
        let t0 = Instant::now();
        queue.write_buffer(&uniform_buf, 0, bytemuck::bytes_of(&uniforms));

        let mut enc = device.create_command_encoder(&wgpu::CommandEncoderDescriptor {
            label: Some("ge_h3_enc"),
        });
        {
            let mut rpass = enc.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("ge_h3_pass"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &tex_view,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color::BLACK),
                        store: wgpu::StoreOp::Store,
                    },
                })],
                depth_stencil_attachment: None,
                timestamp_writes: None,
                occlusion_query_set: None,
            });
            rpass.set_bind_group(0, &bg, &[]);
            rpass.set_pipeline(&bg_pipeline);
            rpass.draw(0..3, 0..1);
            rpass.set_pipeline(&entity_pipeline);
            rpass.draw(0..6, 0..20);
        }
        enc.copy_texture_to_buffer(
            wgpu::ImageCopyTexture {
                texture: &tex,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            wgpu::ImageCopyBuffer {
                buffer: &readback,
                layout: wgpu::ImageDataLayout {
                    offset: 0,
                    bytes_per_row: Some(WIDTH * 4),
                    rows_per_image: Some(HEIGHT),
                },
            },
            wgpu::Extent3d {
                width: WIDTH,
                height: HEIGHT,
                depth_or_array_layers: 1,
            },
        );
        queue.submit(Some(enc.finish()));

        let slice = readback.slice(..);
        slice.map_async(wgpu::MapMode::Read, |_| {});
        device.poll(wgpu::Maintain::Wait);
        let render_ms = t0.elapsed().as_secs_f64() * 1000.0;

        let mapped = slice.get_mapped_range();
        let bytes: Vec<u8> = mapped.to_vec();
        drop(mapped);
        readback.unmap();

        let fb_hash = sha256_hex(&bytes);
        let gz_name = format!("{}_tick{}.rgba.gz", adapter_key, tick);
        write_gz(&out_dir.join(&gz_name), &bytes);

        println!(
            "  [GPU:{:6}] {:38} tick={:5} render={:6.2}ms fb_sha256={}...",
            backend_str,
            info.name,
            tick,
            render_ms,
            &fb_hash[..16]
        );

        frame_receipts.push(FrameReceipt {
            tick: *tick,
            state_q32_sha256: st_hash.clone(),
            framebuffer_rgba8_sha256: fb_hash,
            render_ms: (render_ms * 1000.0).round() / 1000.0,
            gz_file: gz_name,
        });
    }

    Some(AdapterReceipt {
        adapter_key,
        host_id: host_id.to_string(),
        name: info.name,
        backend: backend_str,
        device_type: dtype_str,
        driver: info.driver,
        driver_info: info.driver_info,
        vendor_id: info.vendor,
        device_id: info.device,
        is_hardware_gpu: is_hw,
        frames: frame_receipts,
    })
}

// ============================================================================
// Pairwise Framebuffer Error & Perceptual Tolerance Metrics (PSNR + SSIM)
// ============================================================================

#[derive(Serialize)]
struct FramePairMetrics {
    tick: u32,
    sha256_a: String,
    sha256_b: String,
    bitwise_identical: bool,
    total_pixels: usize,
    differing_pixels: usize,
    differing_pixels_pct: f64,
    max_abs_channel_diff_u8: u8,
    pixels_gt_1_lsb_pct: f64,
    pixels_gt_2_lsb_pct: f64,
    outlier_fraction_gt_eps8: f64,
    mae_u8: f64,
    rmse_u8: f64,
    psnr_db: Option<f64>,
    ssim: f64,
    passes_ge_h3_gate: bool,
}

#[derive(Serialize)]
struct AdapterPairSummary {
    adapter_a: String,
    adapter_b: String,
    adapter_key_a: String,
    adapter_key_b: String,
    host_a: String,
    host_b: String,
    backend_a: String,
    backend_b: String,
    category: String,
    any_bitwise_divergence: bool,
    all_4_frames_pass_ge_h3_gate: bool,
    worst_max_abs_channel_diff_u8: u8,
    mean_differing_pixels_pct: f64,
    mean_mae_u8: f64,
    mean_rmse_u8: f64,
    min_psnr_db: Option<f64>,
    min_ssim: f64,
    max_outlier_fraction_gt_eps8: f64,
    frames: Vec<FramePairMetrics>,
}

fn compute_ssim_8x8(a: &[u8], b: &[u8]) -> f64 {
    // BT.601 luminance Y in [0, 255] over non-overlapping + stride-4 8x8 windows (Wang et al. 2004)
    let w = WIDTH as usize;
    let h = HEIGHT as usize;
    let mut ya = vec![0.0f64; w * h];
    let mut yb = vec![0.0f64; w * h];
    for idx in 0..(w * h) {
        let o = idx * 4;
        ya[idx] = 0.299 * (a[o] as f64) + 0.587 * (a[o + 1] as f64) + 0.114 * (a[o + 2] as f64);
        yb[idx] = 0.299 * (b[o] as f64) + 0.587 * (b[o + 1] as f64) + 0.114 * (b[o + 2] as f64);
    }
    let c1 = (0.01 * 255.0_f64).powi(2);
    let c2 = (0.03 * 255.0_f64).powi(2);
    let mut ssim_sum = 0.0f64;
    let mut win_cnt = 0usize;
    let n_pix = 64.0f64;

    let mut wy = 0usize;
    while wy + 8 <= h {
        let mut wx = 0usize;
        while wx + 8 <= w {
            let mut sum_a = 0.0;
            let mut sum_b = 0.0;
            for dy in 0..8 {
                let row = (wy + dy) * w + wx;
                for dx in 0..8 {
                    sum_a += ya[row + dx];
                    sum_b += yb[row + dx];
                }
            }
            let mu_a = sum_a / n_pix;
            let mu_b = sum_b / n_pix;
            let mut var_a = 0.0;
            let mut var_b = 0.0;
            let mut cov = 0.0;
            for dy in 0..8 {
                let row = (wy + dy) * w + wx;
                for dx in 0..8 {
                    let da = ya[row + dx] - mu_a;
                    let db = yb[row + dx] - mu_b;
                    var_a += da * da;
                    var_b += db * db;
                    cov += da * db;
                }
            }
            var_a /= n_pix - 1.0;
            var_b /= n_pix - 1.0;
            cov /= n_pix - 1.0;

            let num = (2.0 * mu_a * mu_b + c1) * (2.0 * cov + c2);
            let den = (mu_a * mu_a + mu_b * mu_b + c1) * (var_a + var_b + c2);
            ssim_sum += num / den;
            win_cnt += 1;
            wx += 4;
        }
        wy += 4;
    }
    ssim_sum / (win_cnt as f64)
}

fn compare_frames(tick: u32, a: &[u8], b: &[u8], ha: &str, hb: &str) -> FramePairMetrics {
    assert_eq!(a.len(), FB_BYTES);
    assert_eq!(b.len(), FB_BYTES);
    let total_px = (WIDTH * HEIGHT) as usize;
    let mut diff_px = 0usize;
    let mut gt1_px = 0usize;
    let mut gt2_px = 0usize;
    let mut gt8_px = 0usize;
    let mut max_diff = 0u8;
    let mut abs_sum = 0u64;
    let mut sq_sum = 0u64;

    for px in 0..total_px {
        let o = px * 4;
        let mut px_max = 0u8;
        for c in 0..4 {
            let d = (a[o + c] as i32 - b[o + c] as i32).unsigned_abs() as u8;
            if d > px_max {
                px_max = d;
            }
            abs_sum += d as u64;
            sq_sum += (d as u64) * (d as u64);
        }
        if px_max > 0 {
            diff_px += 1;
        }
        if px_max > 1 {
            gt1_px += 1;
        }
        if px_max > 2 {
            gt2_px += 1;
        }
        if px_max > 8 {
            gt8_px += 1;
        }
        if px_max > max_diff {
            max_diff = px_max;
        }
    }

    let n_chan = (total_px * 4) as f64;
    let mae = (abs_sum as f64) / n_chan;
    let mse = (sq_sum as f64) / n_chan;
    let rmse = mse.sqrt();
    let psnr = if sq_sum == 0 {
        None
    } else {
        Some(10.0 * ((255.0_f64 * 255.0_f64) / mse).log10())
    };
    let ssim = if sq_sum == 0 {
        1.0
    } else {
        compute_ssim_8x8(a, b)
    };
    let outlier_frac = (gt8_px as f64) / (total_px as f64);
    let passes = psnr.map_or(true, |p| p > 40.0) && ssim > 0.999 && outlier_frac <= 0.001;

    FramePairMetrics {
        tick,
        sha256_a: ha.to_string(),
        sha256_b: hb.to_string(),
        bitwise_identical: ha == hb,
        total_pixels: total_px,
        differing_pixels: diff_px,
        differing_pixels_pct: ((diff_px as f64) * 100.0 / (total_px as f64) * 10000.0).round() / 10000.0,
        max_abs_channel_diff_u8: max_diff,
        pixels_gt_1_lsb_pct: ((gt1_px as f64) * 100.0 / (total_px as f64) * 10000.0).round() / 10000.0,
        pixels_gt_2_lsb_pct: ((gt2_px as f64) * 100.0 / (total_px as f64) * 10000.0).round() / 10000.0,
        outlier_fraction_gt_eps8: (outlier_frac * 1_000_000.0).round() / 1_000_000.0,
        mae_u8: (mae * 1_000_000.0).round() / 1_000_000.0,
        rmse_u8: (rmse * 1_000_000.0).round() / 1_000_000.0,
        psnr_db: psnr.map(|p| (p * 1000.0).round() / 1000.0),
        ssim: (ssim * 1_000_000.0).round() / 1_000_000.0,
        passes_ge_h3_gate: passes,
    }
}

fn run_render_cmd(host_id: &str, out_dir: &Path) {
    fs::create_dir_all(out_dir).expect("create out_dir");

    // Step canonical Q32.32 simulation to ticks [0, 250, 1000, 10000]
    let mut sim = SimState::new_initial();
    let mut states: Vec<(u32, SimState, String)> = Vec::new();
    let mut state_hashes = BTreeMap::new();
    for &target_t in &CANONICAL_TICKS {
        while sim.tick < target_t {
            sim.step_one();
        }
        let h = sim.canonical_sha256();
        state_hashes.insert(target_t.to_string(), h.clone());
        states.push((target_t, sim.clone(), h));
    }
    assert_eq!(
        state_hashes["1000"],
        "21fa688e4ee8dd6e66dc7b2cc3b674a54c59f9b61967bcf97ecb58f99dc738ae",
        "Upstream Q32.32 state hash mismatch at tick 1000!"
    );
    assert_eq!(
        state_hashes["10000"],
        "0c60a804c15b682626442bdcd600869359ebdf1d70ff9f1f6ac5f47a38c95728",
        "Upstream Q32.32 state hash mismatch at tick 10000!"
    );
    println!(
        "[{}] Verified upstream Q32.32 canonical state hashes at ticks {:?}.",
        host_id, CANONICAL_TICKS
    );

    // 1. Deterministic CPU Q16.16 software rasterizer
    let cpu_key = format!("{}_cpu_q16_ref", host_id);
    let mut cpu_frames = Vec::new();
    for (tick, st_q, st_hash) in &states {
        let t0 = Instant::now();
        let fb = rasterize_cpu_q16(st_q);
        let ms = t0.elapsed().as_secs_f64() * 1000.0;
        let fb_hash = sha256_hex(&fb);
        let gz_name = format!("{}_tick{}.rgba.gz", cpu_key, tick);
        write_gz(&out_dir.join(&gz_name), &fb);
        println!(
            "  [CPU Q16.16] tick={:5} render={:6.2}ms fb_sha256={}...",
            tick,
            ms,
            &fb_hash[..16]
        );
        cpu_frames.push(FrameReceipt {
            tick: *tick,
            state_q32_sha256: st_hash.clone(),
            framebuffer_rgba8_sha256: fb_hash,
            render_ms: (ms * 1000.0).round() / 1000.0,
            gz_file: gz_name,
        });
    }

    let mut all_adapters = vec![AdapterReceipt {
        adapter_key: cpu_key,
        host_id: host_id.to_string(),
        name: "CPU Deterministic Q16.16 Software Reference".to_string(),
        backend: "CpuQ16FixedPoint".to_string(),
        device_type: "Cpu".to_string(),
        driver: "OpenIE Q16.16 Integer Rasterizer".to_string(),
        driver_info: "Zero-float integer SDF + Blinn-Phong reference".to_string(),
        vendor_id: 0,
        device_id: 0,
        is_hardware_gpu: false,
        frames: cpu_frames,
    }];

    // 2. Enumerate all wgpu DirectX 12 / Vulkan / Metal adapters on host
    let backends = wgpu::Backends::DX12 | wgpu::Backends::VULKAN | wgpu::Backends::METAL;
    let instance = wgpu::Instance::new(wgpu::InstanceDescriptor {
        backends,
        ..Default::default()
    });
    let adapters = instance.enumerate_adapters(backends);
    let mut seen_keys = HashSet::new();
    for adapter in adapters {
        let info = adapter.get_info();
        let dedup = format!("{:?}:{}:{}:{}", info.backend, info.name, info.driver, info.device);
        if !seen_keys.insert(dedup) {
            continue;
        }
        if let Some(rec) = render_on_adapter(&adapter, host_id, &states, out_dir) {
            all_adapters.push(rec);
        }
    }

    let manifest = HostRenderManifest {
        host_id: host_id.to_string(),
        bench_root: "$BENCH_ROOT".to_string(),
        arch: env::consts::ARCH.to_string(),
        os: env::consts::OS.to_string(),
        canonical_ticks: CANONICAL_TICKS.to_vec(),
        state_q32_sha256_by_tick: state_hashes,
        adapters: all_adapters,
    };
    let mpath = out_dir.join(format!("{}_manifest.json", host_id));
    fs::write(&mpath, serde_json::to_string_pretty(&manifest).unwrap() + "\n")
        .expect("write manifest");
    println!("[{}] Wrote {}.", host_id, mpath.file_name().unwrap().to_string_lossy());
}

fn run_compare_cmd(in_dir: &Path, out_json: &Path) {
    let mut manifests: Vec<HostRenderManifest> = Vec::new();
    for entry in fs::read_dir(in_dir).expect("read in_dir") {
        let p = entry.unwrap().path();
        if p.file_name()
            .and_then(|n| n.to_str())
            .map_or(false, |n| n.ends_with("_manifest.json"))
        {
            let txt = fs::read_to_string(&p).expect("read manifest");
            manifests.push(serde_json::from_str(&txt).expect("parse manifest"));
        }
    }
    manifests.sort_by(|a, b| a.host_id.cmp(&b.host_id));
    assert!(!manifests.is_empty(), "No *_manifest.json found in in_dir");

    // Verify upstream Q32.32 state parity across all GPU hosts
    let ref_state_hashes = &manifests[0].state_q32_sha256_by_tick;
    let mut upstream_mismatches = 0usize;
    for m in &manifests[1..] {
        if &m.state_q32_sha256_by_tick != ref_state_hashes {
            upstream_mismatches += 1;
        }
    }

    // Collect adapters: keep ONE canonical CPU Q16.16 reference (while verifying all hosts' CPU Q16.16 match!)
    let mut cpu_refs: Vec<AdapterReceipt> = Vec::new();
    let mut hw_gpus: Vec<AdapterReceipt> = Vec::new();
    let mut sw_vulkans: Vec<AdapterReceipt> = Vec::new();
    let mut sw_dx12_warp: Vec<AdapterReceipt> = Vec::new();

    for m in &manifests {
        for a in &m.adapters {
            if a.backend == "CpuQ16FixedPoint" {
                cpu_refs.push(a.clone());
            } else if a.is_hardware_gpu {
                hw_gpus.push(a.clone());
            } else if a.backend == "Dx12" {
                sw_dx12_warp.push(a.clone());
            } else {
                sw_vulkans.push(a.clone());
            }
        }
    }

    let mut cpu_q16_cross_host_mismatches = 0usize;
    for c in &cpu_refs[1..] {
        for (fa, fb) in cpu_refs[0].frames.iter().zip(c.frames.iter()) {
            if fa.framebuffer_rgba8_sha256 != fb.framebuffer_rgba8_sha256 {
                cpu_q16_cross_host_mismatches += 1;
            }
        }
    }

    // Load all needed framebuffers into memory cache
    let mut all_selected: Vec<AdapterReceipt> = Vec::new();
    all_selected.extend(hw_gpus.iter().cloned());
    if let Some(warp) = sw_dx12_warp.first() {
        all_selected.push(warp.clone());
    }
    if let Some(sw) = sw_vulkans.first() {
        all_selected.push(sw.clone());
    }
    all_selected.push(cpu_refs[0].clone());

    let mut fb_cache: BTreeMap<(String, u32), Vec<u8>> = BTreeMap::new();
    for a in &all_selected {
        for fr in &a.frames {
            let bytes = read_gz(&in_dir.join(&fr.gz_file));
            fb_cache.insert((a.adapter_key.clone(), fr.tick), bytes);
        }
    }

    let os_tag = |hid: &str| -> &'static str {
        if hid.contains("win11") || hid.contains("windows") {
            "Win11"
        } else if hid.contains("macos") || hid.contains("apple") {
            "macOS"
        } else {
            "Linux"
        }
    };

    let mut pair_summaries: Vec<AdapterPairSummary> = Vec::new();
    for i in 0..all_selected.len() {
        for j in (i + 1)..all_selected.len() {
            let aa = &all_selected[i];
            let ab = &all_selected[j];
            let cat = if aa.is_hardware_gpu && ab.is_hardware_gpu {
                if aa.host_id == ab.host_id && aa.name == ab.name && aa.backend != ab.backend {
                    "same_physical_gpu_dx12_vs_vulkan"
                } else {
                    "physical_gpu_vs_physical_gpu"
                }
            } else if aa.backend == "CpuQ16FixedPoint" || ab.backend == "CpuQ16FixedPoint" {
                "gpu_vs_cpu_q16_software_ref"
            } else if !aa.is_hardware_gpu && !ab.is_hardware_gpu {
                "software_dx12_warp_vs_software_vulkan_llvmpipe"
            } else if (!aa.is_hardware_gpu && aa.backend == "Dx12")
                || (!ab.is_hardware_gpu && ab.backend == "Dx12")
            {
                "physical_gpu_vs_software_dx12_warp"
            } else {
                "physical_gpu_vs_software_vulkan_llvmpipe"
            };

            let mut fmetrics = Vec::new();
            for &tick in &CANONICAL_TICKS {
                let fa = aa.frames.iter().find(|f| f.tick == tick).unwrap();
                let fb = ab.frames.iter().find(|f| f.tick == tick).unwrap();
                let ba = &fb_cache[&(aa.adapter_key.clone(), tick)];
                let bb = &fb_cache[&(ab.adapter_key.clone(), tick)];
                fmetrics.push(compare_frames(
                    tick,
                    ba,
                    bb,
                    &fa.framebuffer_rgba8_sha256,
                    &fb.framebuffer_rgba8_sha256,
                ));
            }

            let any_div = fmetrics.iter().any(|m| !m.bitwise_identical);
            let all_pass = fmetrics.iter().all(|m| m.passes_ge_h3_gate);
            let worst_max = fmetrics.iter().map(|m| m.max_abs_channel_diff_u8).max().unwrap_or(0);
            let mean_diff_pct =
                fmetrics.iter().map(|m| m.differing_pixels_pct).sum::<f64>() / (fmetrics.len() as f64);
            let mean_mae =
                fmetrics.iter().map(|m| m.mae_u8).sum::<f64>() / (fmetrics.len() as f64);
            let mean_rmse =
                fmetrics.iter().map(|m| m.rmse_u8).sum::<f64>() / (fmetrics.len() as f64);
            let min_psnr = fmetrics
                .iter()
                .filter_map(|m| m.psnr_db)
                .fold(None, |acc: Option<f64>, v| Some(acc.map_or(v, |x| x.min(v))));
            let min_ssim = fmetrics
                .iter()
                .map(|m| m.ssim)
                .fold(1.0f64, |a, b| a.min(b));
            let max_out = fmetrics
                .iter()
                .map(|m| m.outlier_fraction_gt_eps8)
                .fold(0.0f64, |a, b| a.max(b));

            let fmt_label = |ad: &AdapterReceipt| -> String {
                if ad.backend == "CpuQ16FixedPoint" {
                    format!("{}", ad.name)
                } else {
                    let b_disp = if ad.backend == "Dx12" { "DirectX 12" } else { ad.backend.as_str() };
                    format!("{} ({} {})", ad.name, os_tag(&ad.host_id), b_disp)
                }
            };
            let label_a = fmt_label(aa);
            let label_b = fmt_label(ab);
            println!(
                "  [PAIR] {:48} vs {:48} | diff={:6.2}% max_d={:2} min_PSNR={:?}dB min_SSIM={:.6} gate={}",
                label_a, label_b, mean_diff_pct, worst_max, min_psnr, min_ssim, all_pass
            );

            pair_summaries.push(AdapterPairSummary {
                adapter_a: label_a,
                adapter_b: label_b,
                adapter_key_a: aa.adapter_key.clone(),
                adapter_key_b: ab.adapter_key.clone(),
                host_a: aa.host_id.clone(),
                host_b: ab.host_id.clone(),
                backend_a: aa.backend.clone(),
                backend_b: ab.backend.clone(),
                category: cat.to_string(),
                any_bitwise_divergence: any_div,
                all_4_frames_pass_ge_h3_gate: all_pass,
                worst_max_abs_channel_diff_u8: worst_max,
                mean_differing_pixels_pct: (mean_diff_pct * 10000.0).round() / 10000.0,
                mean_mae_u8: (mean_mae * 1_000_000.0).round() / 1_000_000.0,
                mean_rmse_u8: (mean_rmse * 1_000_000.0).round() / 1_000_000.0,
                min_psnr_db: min_psnr,
                min_ssim,
                max_outlier_fraction_gt_eps8: max_out,
                frames: fmetrics,
            });
        }
    }

    // Also compare Mesa llvmpipe across AMD vs Intel x86_64 hosts if >= 2 sw_vulkans exist
    let mut llvmpipe_cross_x86_identical = None;
    if sw_vulkans.len() >= 2 {
        let same = sw_vulkans[0]
            .frames
            .iter()
            .zip(sw_vulkans[1].frames.iter())
            .all(|(a, b)| a.framebuffer_rgba8_sha256 == b.framebuffer_rgba8_sha256);
        llvmpipe_cross_x86_identical = Some(same);
    }

    let hw_pairs: Vec<&AdapterPairSummary> = pair_summaries
        .iter()
        .filter(|p| p.category == "physical_gpu_vs_physical_gpu" || p.category == "same_physical_gpu_dx12_vs_vulkan")
        .collect();
    let cross_gpu_pairs: Vec<&AdapterPairSummary> = pair_summaries
        .iter()
        .filter(|p| p.category == "physical_gpu_vs_physical_gpu")
        .collect();
    let same_gpu_api_pairs: Vec<&AdapterPairSummary> = pair_summaries
        .iter()
        .filter(|p| p.category == "same_physical_gpu_dx12_vs_vulkan")
        .collect();
    let all_hw_diverged_bitwise = hw_pairs.iter().all(|p| p.any_bitwise_divergence);
    let all_hw_pass_gate = hw_pairs.iter().all(|p| p.all_4_frames_pass_ge_h3_gate);

    let out_doc = serde_json::json!({
        "study": "game-engines",
        "hypothesis_id": "GE-H3",
        "wave": "wave4_cross_os_3api_dx12_metal_vulkan",
        "bench_root": "$BENCH_ROOT",
        "measured_j": null,
        "board_metered": false,
        "graphics_apis_tested": ["DirectX 12 (HLSL / DXIL)", "Metal (MSL)", "Vulkan (SPIR-V)"],
        "operating_systems_tested": ["macOS 27.2.1 (arm64)", "Ubuntu Linux 7.0 (x86_64)", "Windows 11 NT 10.0.26300 (x86_64)"],
        "resolution": [WIDTH, HEIGHT],
        "pixel_format": "RGBA8Unorm (512x512x4 = 1,048,576 bytes/frame)",
        "canonical_ticks": CANONICAL_TICKS,
        "tolerance_gate": {
            "upstream_state_hash_mismatches_allowed": 0,
            "per_channel_epsilon_u8": 8,
            "max_outlier_pixel_fraction_p_max": 0.001,
            "min_psnr_db": 40.0,
            "min_ssim": 0.999
        },
        "summary": {
            "hardware_gpu_api_endpoints_tested": hw_gpus.len(),
            "software_dx12_warp_adapters_tested": sw_dx12_warp.len(),
            "software_vulkan_adapters_tested": sw_vulkans.len(),
            "cpu_q16_hosts_verified": cpu_refs.len(),
            "upstream_q32_state_hash_mismatches": upstream_mismatches,
            "cpu_q16_cross_isa_cross_os_framebuffer_mismatches": cpu_q16_cross_host_mismatches,
            "llvmpipe_amd_vs_intel_x86_64_bitwise_identical": llvmpipe_cross_x86_identical,
            "total_hardware_endpoint_pairs": hw_pairs.len(),
            "cross_gpu_or_cross_os_pairs": cross_gpu_pairs.len(),
            "same_physical_gpu_dx12_vs_vulkan_pairs": same_gpu_api_pairs.len(),
            "all_hardware_pairs_exhibit_lsb_bit_divergence": all_hw_diverged_bitwise,
            "all_hardware_pairs_pass_tolerance_gate": all_hw_pass_gate,
            "verdict": if upstream_mismatches == 0 && cpu_q16_cross_host_mismatches == 0 && all_hw_pass_gate {
                "PASS_BOUNDED_TOLERANCE_CONFIRMED"
            } else {
                "FALSIFIED"
            }
        },
        "upstream_q32_state_sha256": ref_state_hashes,
        "hardware_gpu_adapters": hw_gpus,
        "software_reference_adapters": {
            "cpu_q16_fixed_point": &cpu_refs[0],
            "microsoft_dx12_warp": sw_dx12_warp,
            "mesa_llvmpipe_vulkan": sw_vulkans
        },
        "pairwise_comparisons": pair_summaries
    });

    if let Some(parent) = out_json.parent() {
        fs::create_dir_all(parent).expect("create parent");
    }
    fs::write(out_json, serde_json::to_string_pretty(&out_doc).unwrap() + "\n")
        .expect("write out_json");
    println!("Wrote cross-GPU comparison receipt to {}.", out_json.display());
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        eprintln!("Usage:\n  ge_h3_wgpu_bench render --host-id <id> --out-dir <dir>\n  ge_h3_wgpu_bench compare --in-dir <dir> --out <json>");
        std::process::exit(2);
    }
    let get_arg = |flag: &str| -> String {
        for i in 2..args.len() {
            if args[i] == flag && i + 1 < args.len() {
                return args[i + 1].clone();
            }
        }
        panic!("Missing required flag {}", flag);
    };
    match args[1].as_str() {
        "render" => {
            let host_id = get_arg("--host-id");
            let out_dir = PathBuf::from(get_arg("--out-dir"));
            run_render_cmd(&host_id, &out_dir);
        }
        "compare" => {
            let in_dir = PathBuf::from(get_arg("--in-dir"));
            let out_json = PathBuf::from(get_arg("--out"));
            run_compare_cmd(&in_dir, &out_json);
        }
        other => panic!("Unknown subcommand: {}", other),
    }
}
