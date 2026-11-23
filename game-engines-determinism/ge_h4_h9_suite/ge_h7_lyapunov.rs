// GE-H7: Full ln(Delta / delta_0) Lyapunov Slope Sweep Across 3 Physics-Heavy Templates
// Compiled with: rustc -C opt-level=3 -C llvm-args=-fp-contract=off ge_h7_lyapunov.rs -o ge_h7_lyapunov
// Templates:
//   GE-T1: 16-Body Chaotic Bumper Arena (16 rigid disks + 5 convex Sinai bumpers in [-10, 10]^2)
//   GE-T2: 12-Peg Galton/Pinball Elastic Lattice (4 high-energy pinballs + 12 staggered convex pegs + bottom kicker)
//   GE-T3: 8-Node Coupled Spring-Pendulum Bridge (8 2D mass nodes with nonlinear cubic-stiffening springs + central pylon)

use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Instant;

const DT: f64 = 1.0 / 60.0;
const MAX_TICKS: u32 = 50_000;
const DELTA_MACRO: f64 = 1.0;
const POWERS: [i32; 7] = [-52, -44, -36, -28, -23, -16, -10];
const N_SEEDS: u32 = 40;

struct SplitMix64 {
    s: u64,
}
impl SplitMix64 {
    fn new(seed: u64) -> Self {
        Self { s: seed }
    }
    fn next_u64(&mut self) -> u64 {
        self.s = self.s.wrapping_add(0x9E3779B97F4A7C15);
        let mut z = self.s;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58476D1CE4E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D049BB133111EB);
        z ^ (z >> 31)
    }
    fn next_unit(&mut self) -> f64 {
        ((self.next_u64() >> 11) as f64) * (1.0 / ((1u64 << 53) as f64))
    }
    fn range(&mut self, lo: f64, hi: f64) -> f64 {
        lo + (hi - lo) * self.next_unit()
    }
}

#[derive(Clone)]
struct Arena16 {
    x: [f64; 16],
    y: [f64; 16],
    vx: [f64; 16],
    vy: [f64; 16],
}

impl Arena16 {
    fn init(seed: u32) -> Self {
        let mut rng = SplitMix64::new(0x4745_4837_5431_0000 ^ (seed as u64).wrapping_mul(0x517CC1B727220A95));
        let mut x = [0.0; 16];
        let mut y = [0.0; 16];
        let mut vx = [0.0; 16];
        let mut vy = [0.0; 16];
        // Body 0 placed in [0.20, 0.65] near central bumper (0,0) so |x[0]| < 1.0 (ulp <= 2^-53)
        // up to first convex scattering contact, preventing pre-collision binade rounding coalescence
        x[0] = rng.range(0.20, 0.65);
        y[0] = rng.range(1.85, 2.25);
        vx[0] = rng.range(-1.8, -0.6);
        vy[0] = rng.range(-6.5, -4.8);
        for i in 1..16 {
            let col = (i % 4) as f64 - 1.5;
            let row = (i / 4) as f64 - 1.5;
            x[i] = col * 4.2 + rng.range(-0.4, 0.4);
            y[i] = row * 4.2 + rng.range(-0.4, 0.4);
            vx[i] = rng.range(-6.5, 6.5);
            vy[i] = rng.range(-6.5, 6.5);
        }
        Self { x, y, vx, vy }
    }

    fn step(&mut self) {
        const R: f64 = 0.65;
        const WALL: f64 = 9.35;
        const BUMPERS: [(f64, f64, f64); 5] = [
            (0.0, 0.0, 1.15),
            (-4.2, -4.2, 1.05),
            (4.2, -4.2, 1.05),
            (-4.2, 4.2, 1.05),
            (4.2, 4.2, 1.05),
        ];
        for i in 0..16 {
            self.x[i] += self.vx[i] * DT;
            self.y[i] += self.vy[i] * DT;
            if self.x[i] > WALL {
                self.x[i] = 2.0 * WALL - self.x[i];
                self.vx[i] = -self.vx[i];
            } else if self.x[i] < -WALL {
                self.x[i] = -2.0 * WALL - self.x[i];
                self.vx[i] = -self.vx[i];
            }
            if self.y[i] > WALL {
                self.y[i] = 2.0 * WALL - self.y[i];
                self.vy[i] = -self.vy[i];
            } else if self.y[i] < -WALL {
                self.y[i] = -2.0 * WALL - self.y[i];
                self.vy[i] = -self.vy[i];
            }
            for &(bx, by, br) in &BUMPERS {
                let dx = self.x[i] - bx;
                let dy = self.y[i] - by;
                let min_d = R + br;
                let d2 = dx * dx + dy * dy;
                if d2 < min_d * min_d && d2 > 1e-30 {
                    let d = d2.sqrt();
                    let nx = dx / d;
                    let ny = dy / d;
                    let overlap = min_d - d;
                    self.x[i] += nx * overlap;
                    self.y[i] += ny * overlap;
                    let vn = self.vx[i] * nx + self.vy[i] * ny;
                    if vn < 0.0 {
                        self.vx[i] -= 2.0 * vn * nx;
                        self.vy[i] -= 2.0 * vn * ny;
                    }
                }
            }
        }
        let min_pair = 2.0 * R;
        let min_pair2 = min_pair * min_pair;
        for i in 0..16 {
            for j in (i + 1)..16 {
                let dx = self.x[j] - self.x[i];
                let dy = self.y[j] - self.y[i];
                let d2 = dx * dx + dy * dy;
                if d2 < min_pair2 && d2 > 1e-30 {
                    let d = d2.sqrt();
                    let nx = dx / d;
                    let ny = dy / d;
                    let half_ov = 0.5 * (min_pair - d);
                    self.x[i] -= nx * half_ov;
                    self.y[i] -= ny * half_ov;
                    self.x[j] += nx * half_ov;
                    self.y[j] += ny * half_ov;
                    let dvx = self.vx[j] - self.vx[i];
                    let dvy = self.vy[j] - self.vy[i];
                    let rel = dvx * nx + dvy * ny;
                    if rel < 0.0 {
                        self.vx[i] += rel * nx;
                        self.vy[i] += rel * ny;
                        self.vx[j] -= rel * nx;
                        self.vy[j] -= rel * ny;
                    }
                }
            }
        }
    }

    fn dist(&self, o: &Self) -> f64 {
        let mut s = 0.0;
        for i in 0..16 {
            let dx = self.x[i] - o.x[i];
            let dy = self.y[i] - o.y[i];
            s += dx * dx + dy * dy;
        }
        s.sqrt()
    }
}

#[derive(Clone)]
struct Galton12 {
    x: [f64; 4],
    y: [f64; 4],
    vx: [f64; 4],
    vy: [f64; 4],
}

impl Galton12 {
    fn init(seed: u32) -> Self {
        let mut rng = SplitMix64::new(0x4745_4837_5432_0000 ^ (seed as u64).wrapping_mul(0x9E3779B97F4A7C15));
        let mut x = [0.0; 4];
        let mut y = [0.0; 4];
        let mut vx = [0.0; 4];
        let mut vy = [0.0; 4];
        // Ball 0 placed in [0.15, 0.55] above peg (0, 4.2) so |x[0]| < 1.0 up to first peg contact
        x[0] = rng.range(0.15, 0.55);
        y[0] = rng.range(5.25, 5.75);
        vx[0] = rng.range(-0.9, -0.2);
        vy[0] = rng.range(-3.5, -1.5);
        for i in 1..4 {
            x[i] = (i as f64 - 2.0) * 2.4 + rng.range(-0.4, 0.4);
            y[i] = 6.5 + rng.range(-1.0, 1.2);
            vx[i] = rng.range(-4.0, 4.0);
            vy[i] = rng.range(-3.0, 2.0);
        }
        Self { x, y, vx, vy }
    }

    fn step(&mut self) {
        const R: f64 = 0.45;
        const GRAV: f64 = -9.81;
        const PEGS: [(f64, f64, f64); 12] = [
            (-3.6, 4.2, 0.80), (0.0, 4.2, 0.80), (3.6, 4.2, 0.80),
            (-5.4, 1.4, 0.80), (-1.8, 1.4, 0.80), (1.8, 1.4, 0.80),
            (-3.6, -1.4, 0.80), (0.0, -1.4, 0.80), (3.6, -1.4, 0.80),
            (5.4, 1.4, 0.80), (-1.8, -4.2, 0.80), (1.8, -4.2, 0.80),
        ];
        const WALL_X: f64 = 7.2;
        const TOP_Y: f64 = 8.6;
        const BOT_Y: f64 = -7.6;

        for i in 0..4 {
            // Symplectic Euler / Verlet kick-drift with elastic kicker floor
            self.vy[i] += GRAV * DT;
            self.x[i] += self.vx[i] * DT;
            self.y[i] += self.vy[i] * DT;

            if self.x[i] > WALL_X {
                self.x[i] = 2.0 * WALL_X - self.x[i];
                self.vx[i] = -self.vx[i];
            } else if self.x[i] < -WALL_X {
                self.x[i] = -2.0 * WALL_X - self.x[i];
                self.vx[i] = -self.vx[i];
            }
            if self.y[i] > TOP_Y {
                self.y[i] = 2.0 * TOP_Y - self.y[i];
                self.vy[i] = -self.vy[i].abs();
            } else if self.y[i] < BOT_Y {
                self.y[i] = 2.0 * BOT_Y - self.y[i];
                self.vy[i] = self.vy[i].abs();
                if self.vy[i] < 14.5 {
                    self.vy[i] = 15.2;
                }
            }

            for &(px, py, pr) in &PEGS {
                let dx = self.x[i] - px;
                let dy = self.y[i] - py;
                let md = R + pr;
                let d2 = dx * dx + dy * dy;
                if d2 < md * md && d2 > 1e-30 {
                    let d = d2.sqrt();
                    let nx = dx / d;
                    let ny = dy / d;
                    let ov = md - d;
                    self.x[i] += nx * ov;
                    self.y[i] += ny * ov;
                    let vn = self.vx[i] * nx + self.vy[i] * ny;
                    if vn < 0.0 {
                        self.vx[i] -= 2.0 * vn * nx;
                        self.vy[i] -= 2.0 * vn * ny;
                    }
                }
            }
        }
        let mp = 2.0 * R;
        let mp2 = mp * mp;
        for i in 0..4 {
            for j in (i + 1)..4 {
                let dx = self.x[j] - self.x[i];
                let dy = self.y[j] - self.y[i];
                let d2 = dx * dx + dy * dy;
                if d2 < mp2 && d2 > 1e-30 {
                    let d = d2.sqrt();
                    let nx = dx / d;
                    let ny = dy / d;
                    let hov = 0.5 * (mp - d);
                    self.x[i] -= nx * hov;
                    self.y[i] -= ny * hov;
                    self.x[j] += nx * hov;
                    self.y[j] += ny * hov;
                    let dvx = self.vx[j] - self.vx[i];
                    let dvy = self.vy[j] - self.vy[i];
                    let rel = dvx * nx + dvy * ny;
                    if rel < 0.0 {
                        self.vx[i] += rel * nx;
                        self.vy[i] += rel * ny;
                        self.vx[j] -= rel * nx;
                        self.vy[j] -= rel * ny;
                    }
                }
            }
        }
    }

    fn dist(&self, o: &Self) -> f64 {
        let mut s = 0.0;
        for i in 0..4 {
            let dx = self.x[i] - o.x[i];
            let dy = self.y[i] - o.y[i];
            s += dx * dx + dy * dy;
        }
        s.sqrt()
    }
}

#[derive(Clone)]
struct Bridge8 {
    x: [f64; 8],
    y: [f64; 8],
    vx: [f64; 8],
    vy: [f64; 8],
}

impl Bridge8 {
    fn init(seed: u32) -> Self {
        let mut rng = SplitMix64::new(0x4745_4837_5433_0000 ^ (seed as u64).wrapping_mul(0x94D049BB133111EB));
        let mut x = [0.0; 8];
        let mut y = [0.0; 8];
        let mut vx = [0.0; 8];
        let mut vy = [0.0; 8];
        // Node 0 placed in [0.30, 0.85] so +2^-52 is always exact >= 2 ULP
        x[0] = rng.range(0.30, 0.85);
        y[0] = rng.range(-0.6, 0.6);
        vx[0] = rng.range(-6.0, 6.0);
        vy[0] = rng.range(-7.5, 7.5);
        for i in 1..8 {
            x[i] = -7.0 + (i as f64) * 2.0 + rng.range(-0.35, 0.35);
            y[i] = rng.range(-1.2, 1.2);
            vx[i] = rng.range(-6.5, 6.5);
            vy[i] = rng.range(-7.5, 7.5);
        }
        Self { x, y, vx, vy }
    }

    fn accel(x: &[f64; 8], y: &[f64; 8]) -> ([f64; 8], [f64; 8]) {
        const K1: f64 = 28.0;
        const K3: f64 = 14.0;
        const L0: f64 = 1.85;
        const GRAV: f64 = -4.5;
        let mut ax = [0.0; 8];
        let mut ay = [GRAV; 8];

        let spring_pair = |x1: f64, y1: f64, x2: f64, y2: f64| -> (f64, f64) {
            let dx = x2 - x1;
            let dy = y2 - y1;
            let d = (dx * dx + dy * dy + 1e-12).sqrt();
            let s = d - L0;
            let f = K1 * s + K3 * s * s * s;
            (f * dx / d, f * dy / d)
        };

        // Left anchor (-8.5, 0) to node 1, chain 1..7, node 0 coupled as central suspended pendulum load to nodes 3 & 4!
        let (fx_l, fy_l) = spring_pair(-8.5, 0.0, x[1], y[1]);
        ax[1] -= fx_l;
        ay[1] -= fy_l;

        for i in 1..7 {
            let (fx, fy) = spring_pair(x[i], y[i], x[i + 1], y[i + 1]);
            ax[i] += fx;
            ay[i] += fy;
            ax[i + 1] -= fx;
            ay[i + 1] -= fy;
        }

        let (fx_r, fy_r) = spring_pair(x[7], y[7], 8.5, 0.0);
        ax[7] += fx_r;
        ay[7] += fy_r;

        // Node 0 is the heavy suspended pendulum bob coupled to deck nodes 3, 4, and 5
        for &k in &[3usize, 4usize, 5usize] {
            let (fx, fy) = spring_pair(x[0], y[0], x[k], y[k]);
            ax[0] += fx;
            ay[0] += fy;
            ax[k] -= fx;
            ay[k] -= fy;
        }
        (ax, ay)
    }

    fn step(&mut self) {
        // Velocity Verlet + convex central bridge piers at (-2.0, -2.2), (2.0, -2.2), (0.0, 1.8)
        let (ax0, ay0) = Self::accel(&self.x, &self.y);
        for i in 0..8 {
            self.x[i] += self.vx[i] * DT + 0.5 * ax0[i] * DT * DT;
            self.y[i] += self.vy[i] * DT + 0.5 * ay0[i] * DT * DT;
        }
        let (ax1, ay1) = Self::accel(&self.x, &self.y);
        for i in 0..8 {
            self.vx[i] += 0.5 * (ax0[i] + ax1[i]) * DT;
            self.vy[i] += 0.5 * (ay0[i] + ay1[i]) * DT;
        }
        const PIERS: [(f64, f64, f64); 3] = [
            (-1.8, -1.9, 0.95),
            (1.8, -1.9, 0.95),
            (0.0, 1.6, 0.85),
        ];
        for i in 0..8 {
            for &(px, py, pr) in &PIERS {
                let dx = self.x[i] - px;
                let dy = self.y[i] - py;
                let d2 = dx * dx + dy * dy;
                if d2 < pr * pr && d2 > 1e-30 {
                    let d = d2.sqrt();
                    let nx = dx / d;
                    let ny = dy / d;
                    let ov = pr - d;
                    self.x[i] += nx * ov;
                    self.y[i] += ny * ov;
                    let vn = self.vx[i] * nx + self.vy[i] * ny;
                    if vn < 0.0 {
                        self.vx[i] -= 2.0 * vn * nx;
                        self.vy[i] -= 2.0 * vn * ny;
                    }
                }
            }
        }
    }

    fn dist(&self, o: &Self) -> f64 {
        let mut s = 0.0;
        for i in 0..8 {
            let dx = self.x[i] - o.x[i];
            let dy = self.y[i] - o.y[i];
            s += dx * dx + dy * dy;
        }
        s.sqrt()
    }
}

fn run_one(tmpl: usize, pow2: i32, seed: u32) -> (u32, f64, f64) {
    let delta0 = 2.0_f64.powi(pow2);
    match tmpl {
        0 => {
            let mut a = Arena16::init(seed);
            let mut b = a.clone();
            b.x[0] += delta0;
            let actual_d0 = (b.x[0] - a.x[0]).abs();
            for tick in 1..=MAX_TICKS {
                a.step();
                b.step();
                let d = a.dist(&b);
                if d >= DELTA_MACRO {
                    return (tick, (tick as f64) * DT, actual_d0);
                }
            }
            (MAX_TICKS, (MAX_TICKS as f64) * DT, actual_d0)
        }
        1 => {
            let mut a = Galton12::init(seed);
            let mut b = a.clone();
            b.x[0] += delta0;
            let actual_d0 = (b.x[0] - a.x[0]).abs();
            for tick in 1..=MAX_TICKS {
                a.step();
                b.step();
                let d = a.dist(&b);
                if d >= DELTA_MACRO {
                    return (tick, (tick as f64) * DT, actual_d0);
                }
            }
            (MAX_TICKS, (MAX_TICKS as f64) * DT, actual_d0)
        }
        _ => {
            let mut a = Bridge8::init(seed);
            let mut b = a.clone();
            b.x[0] += delta0;
            let actual_d0 = (b.x[0] - a.x[0]).abs();
            for tick in 1..=MAX_TICKS {
                a.step();
                b.step();
                let d = a.dist(&b);
                if d >= DELTA_MACRO {
                    return (tick, (tick as f64) * DT, actual_d0);
                }
            }
            (MAX_TICKS, (MAX_TICKS as f64) * DT, actual_d0)
        }
    }
}

fn main() {
    let t0 = Instant::now();
    let mut jobs = Vec::with_capacity(3 * POWERS.len() * (N_SEEDS as usize));
    for tmpl in 0..3 {
        for &p in &POWERS {
            for seed in 0..N_SEEDS {
                jobs.push((tmpl, p, seed));
            }
        }
    }
    let next_idx = Arc::new(Mutex::new(0usize));
    let out = Arc::new(Mutex::new(vec![(0usize, 0i32, 0u32, 0u32, 0.0f64, 0.0f64); jobs.len()]));
    let jobs_arc = Arc::new(jobs);

    let n_workers = thread::available_parallelism().map(|n| n.get()).unwrap_or(8).min(20);
    let mut handles = Vec::new();
    for _ in 0..n_workers {
        let idx_c = Arc::clone(&next_idx);
        let out_c = Arc::clone(&out);
        let jobs_c = Arc::clone(&jobs_arc);
        handles.push(thread::spawn(move || {
            loop {
                let my_i = {
                    let mut g = idx_c.lock().unwrap();
                    if *g >= jobs_c.len() {
                        break;
                    }
                    let v = *g;
                    *g += 1;
                    v
                };
                let (tmpl, p, seed) = jobs_c[my_i];
                let (tick, sec, actual_d0) = run_one(tmpl, p, seed);
                out_c.lock().unwrap()[my_i] = (tmpl, p, seed, tick, sec, actual_d0);
            }
        }));
    }
    for h in handles {
        h.join().unwrap();
    }
    let elapsed_ms = t0.elapsed().as_secs_f64() * 1000.0;
    let res = out.lock().unwrap();
    println!("{{\"elapsed_ms\":{:.3},\"total_trajectories\":{},\"rows\":[", elapsed_ms, res.len());
    for (i, &(tmpl, p, seed, tick, sec, actual_d0)) in res.iter().enumerate() {
        let comma = if i + 1 < res.len() { "," } else { "" };
        println!(
            "  [{},{},{},{},{:.6},{:.6e}]{}",
            tmpl, p, seed, tick, sec, actual_d0, comma
        );
    }
    println!("]}}");
}
