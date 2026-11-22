// Rust -> WebAssembly (`wasm32-unknown-unknown`) target for `game-engines` (`GE-H1` Q32.32).
// Compiled via: rustc --edition 2021 --target wasm32-unknown-unknown -O --crate-type cdylib sim_wasm.rs -o sim_wasm.wasm

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

static mut OUT_BUF: [u8; 732 * 256] = [0u8; 732 * 256];

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

#[no_mangle]
pub extern "C" fn get_out_ptr() -> *const u8 {
    core::ptr::addr_of!(OUT_BUF) as *const u8
}

#[no_mangle]
pub extern "C" fn run_q32_checkpoints(ticks: u32, stride: u32) -> u32 {
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

    let mut snap_idx: usize = 0;
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
        if stride > 0 && (tick % stride == 0 || tick == ticks) && snap_idx < 256 {
            let base = snap_idx * 732;
            unsafe {
                let dst = &mut OUT_BUF[base..base + 732];
                dst[0..4].copy_from_slice(&tick.to_le_bytes());
                dst[4..12].copy_from_slice(&rng.to_le_bytes());
                let mut o = 12;
                for i in 0..N_BODIES {
                    dst[o..o + 8].copy_from_slice(&bx[i].to_le_bytes()); o += 8;
                    dst[o..o + 8].copy_from_slice(&by[i].to_le_bytes()); o += 8;
                    dst[o..o + 8].copy_from_slice(&bvx[i].to_le_bytes()); o += 8;
                    dst[o..o + 8].copy_from_slice(&bvy[i].to_le_bytes()); o += 8;
                    dst[o..o + 4].copy_from_slice(&bscore[i].to_le_bytes()); o += 4;
                    dst[o..o + 2].copy_from_slice(&btimer[i].to_le_bytes()); o += 2;
                    dst[o] = bfsm[i]; o += 1;
                    dst[o] = 0; o += 1;
                }
                for p in 0..N_PICKUPS {
                    dst[o..o + 8].copy_from_slice(&px[p].to_le_bytes()); o += 8;
                    dst[o..o + 8].copy_from_slice(&py[p].to_le_bytes()); o += 8;
                    dst[o..o + 2].copy_from_slice(&prespawn[p].to_le_bytes()); o += 2;
                    dst[o] = pactive[p]; o += 1;
                    dst[o] = 0; o += 1;
                }
            }
            snap_idx += 1;
        }
    }
    snap_idx as u32
}
