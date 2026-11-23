// GE-H8: One-Hour (216,000-Tick at 60 Hz) Deterministic Replay from Input Log D Alone
// Across macOS arm64, Linux x86_64, and Windows 11 x86_64 + 4-Channel Ambient Leak Control.
// Compiled via: rustc --edition 2021 -C opt-level=3 ge_h8_replay.rs -o ge_h8_replay[.exe]

use std::collections::HashMap;
use std::env;
use std::fs;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

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

fn sha256_bytes(bytes: &[u8]) -> [u8; 32] {
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
    let mut out = [0u8; 32];
    for (i, word) in h.iter().enumerate() {
        out[4 * i..4 * i + 4].copy_from_slice(&word.to_be_bytes());
    }
    out
}

fn hex32(b: &[u8; 32]) -> String {
    let mut s = String::with_capacity(64);
    for byte in b {
        use std::fmt::Write as _;
        let _ = write!(&mut s, "{:02x}", byte);
    }
    s
}

const ONE: i64 = 1_i64 << 32;
const TICKS_1H: usize = 216_000;
const CKPT_STRIDE: usize = 100;

#[inline]
fn qmul(a: i64, b: i64) -> i64 {
    (((a as i128) * (b as i128)) >> 32) as i64
}

fn splitmix(seed: u64) -> u64 {
    let mut z = seed.wrapping_add(0x9E3779B97F4A7C15);
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58476D1CE4E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D049BB133111EB);
    z ^ (z >> 31)
}

// Generate deterministic 2-byte-per-tick compact input log D:
// Header: 8-byte magic "RCEDLOG1" + 8-byte seed (LE) + 4-byte session_id (LE) + 4-byte ticks (LE) = 24 bytes
// Body: 216,000 * 2 bytes = 432,000 bytes -> total 432,024 bytes.
fn build_input_log(session_id: u32, seed: u64) -> Vec<u8> {
    let mut buf = Vec::with_capacity(24 + TICKS_1H * 2);
    buf.extend_from_slice(b"RCEDLOG1");
    buf.extend_from_slice(&seed.to_le_bytes());
    buf.extend_from_slice(&session_id.to_le_bytes());
    buf.extend_from_slice(&(TICKS_1H as u32).to_le_bytes());
    let mut s = seed ^ ((session_id as u64) * 0x517CC1B727220A95);
    let mut cur_cmd: u16 = 0;
    for t in 0..TICKS_1H {
        if t % 12 == 0 {
            s = splitmix(s ^ (t as u64));
            let dx = ((s & 3) as u16) % 3;         // 0=-1, 1=0, 2=+1
            let dy = (((s >> 2) & 3) as u16) % 3;  // 0=-1, 1=0, 2=+1
            let act1 = ((s >> 4) & 1) as u16;
            let act2 = if (s >> 5) & 7 == 0 { 1u16 } else { 0u16 };
            let aim = (((s >> 8) & 0x3F) as u16) & 0x3F;
            cur_cmd = dx | (dy << 2) | (act1 << 4) | (act2 << 5) | (aim << 6);
        }
        buf.extend_from_slice(&cur_cmd.to_le_bytes());
    }
    buf
}

fn parse_input_log(raw: &[u8]) -> (u32, u64, Vec<u16>) {
    assert!(&raw[0..8] == b"RCEDLOG1", "invalid log header");
    let seed = u64::from_le_bytes(raw[8..16].try_into().unwrap());
    let sid = u32::from_le_bytes(raw[16..20].try_into().unwrap());
    let n = u32::from_le_bytes(raw[20..24].try_into().unwrap()) as usize;
    assert_eq!(raw.len(), 24 + n * 2);
    let mut cmds = Vec::with_capacity(n);
    for i in 0..n {
        let off = 24 + i * 2;
        cmds.push(u16::from_le_bytes([raw[off], raw[off + 1]]));
    }
    (sid, seed, cmds)
}

// Session 0: Stealth Mansion (5 coupled actor modules: PlayerStealth, 4 GhostPatrol, 3 GargoyleSpotter, ObserverLOS, ExitTrigger)
struct StealthMansion {
    px: i64,
    py: i64,
    noise: i64,
    crouching: u8,
    gx: [i64; 4],
    gy: [i64; 4],
    gwp: [u8; 4],
    galert: [u16; 4],
    spot_phase: [i64; 3],
    spot_meter: [i64; 3],
    keys_held: u32,
    rooms_cleared: u32,
    resets: u32,
    tick: u64,
}

impl StealthMansion {
    fn new(seed: u64) -> Self {
        let mut gx = [0i64; 4];
        let mut gy = [0i64; 4];
        for i in 0..4 {
            let h = splitmix(seed ^ (i as u64));
            gx[i] = (((h & 0xFF) as i64) - 128) * (ONE / 8);
            gy[i] = ((((h >> 8) & 0xFF) as i64) - 128) * (ONE / 8);
        }
        Self {
            px: -12 * ONE,
            py: -12 * ONE,
            noise: 0,
            crouching: 0,
            gx,
            gy,
            gwp: [0, 1, 2, 3],
            galert: [0; 4],
            spot_phase: [0, 20 * ONE, 40 * ONE],
            spot_meter: [0; 3],
            keys_held: 0,
            rooms_cleared: 0,
            resets: 0,
            tick: 0,
        }
    }

    fn step(&mut self, cmd: u16, leak_mode: u8) {
        self.tick += 1;
        let dx = (cmd & 3) as i64 - 1;
        let dy = ((cmd >> 2) & 3) as i64 - 1;
        let crouch = ((cmd >> 4) & 1) as u8;
        self.crouching = crouch;
        let spd = if crouch == 1 { ONE / 16 } else { ONE / 8 };
        self.px = (self.px + dx * spd).clamp(-20 * ONE, 20 * ONE);
        self.py = (self.py + dy * spd).clamp(-20 * ONE, 20 * ONE);
        if dx != 0 || dy != 0 {
            self.noise = (self.noise + if crouch == 1 { 1 } else { 4 }).min(100);
        } else {
            self.noise = (self.noise - 3).max(0);
        }

        // Ambient leak controls (strictly disabled when leak_mode == 0)
        if leak_mode == 1 {
            let ns = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().subsec_nanos() as i64;
            self.px = self.px.wrapping_add(ns & 0xFF);
        } else if leak_mode == 2 {
            let addr = &cmd as *const u16 as usize as u64;
            let jitter = splitmix(addr ^ self.tick) & 0x7F;
            self.py = self.py.wrapping_add(jitter as i64);
        } else if leak_mode == 3 {
            let mut m: HashMap<u32, i64> = HashMap::new();
            for k in 0..8u32 {
                m.insert(k, (k as i64 + 1) * 13);
            }
            let mut acc = 0i64;
            for (k, v) in &m {
                acc = acc.wrapping_mul(31).wrapping_add(*v ^ (*k as i64));
            }
            self.px = self.px.wrapping_add(acc & 0x3FF);
        } else if leak_mode == 4 {
            let ang = (self.tick as f64) * 0.137 + 0.25;
            let s_bits = (ang.sin().to_bits() & 0xFFFF) as i64;
            self.spot_phase[0] = self.spot_phase[0].wrapping_add(s_bits);
        }

        const WPS: [(i64, i64); 4] = [
            (-14 * ONE, -14 * ONE),
            (14 * ONE, -14 * ONE),
            (14 * ONE, 14 * ONE),
            (-14 * ONE, 14 * ONE),
        ];
        let mut spotted = false;
        for i in 0..4 {
            let (tx, ty) = if self.noise > 50 || self.galert[i] > 0 {
                if self.noise > 50 {
                    self.galert[i] = 45;
                } else {
                    self.galert[i] -= 1;
                }
                (self.px, self.py)
            } else {
                WPS[self.gwp[i] as usize]
            };
            let step_g = ONE / 12;
            if self.gx[i] < tx {
                self.gx[i] = (self.gx[i] + step_g).min(tx);
            } else if self.gx[i] > tx {
                self.gx[i] = (self.gx[i] - step_g).max(tx);
            }
            if self.gy[i] < ty {
                self.gy[i] = (self.gy[i] + step_g).min(ty);
            } else if self.gy[i] > ty {
                self.gy[i] = (self.gy[i] - step_g).max(ty);
            }
            if (self.gx[i] - tx).abs() < ONE / 4 && (self.gy[i] - ty).abs() < ONE / 4 && self.galert[i] == 0 {
                self.gwp[i] = (self.gwp[i] + 1) & 3;
            }
            let ddx = (self.px - self.gx[i]) >> 16;
            let ddy = (self.py - self.gy[i]) >> 16;
            if ddx * ddx + ddy * ddy < (2 * 65536) * (2 * 65536) {
                spotted = true;
            }
        }
        for j in 0..3 {
            self.spot_phase[j] = (self.spot_phase[j] + ONE / 32) % (64 * ONE);
            let sx = (-10 + (j as i64) * 10) * ONE;
            let sy = ((self.spot_phase[j] >> 32) - 32).abs() * (ONE / 2) - 8 * ONE;
            let ddx = (self.px - sx) >> 16;
            let ddy = (self.py - sy) >> 16;
            if ddx * ddx + ddy * ddy < (3 * 65536) * (3 * 65536) && self.crouching == 0 {
                self.spot_meter[j] += 8;
                if self.spot_meter[j] >= 24 {
                    spotted = true;
                }
            } else {
                self.spot_meter[j] = (self.spot_meter[j] - 2).max(0);
            }
        }
        let key_x = (((self.keys_held as i64 * 11) % 25) - 12) * ONE;
        let key_y = (((self.rooms_cleared as i64 * 7 + 5) % 25) - 12) * ONE;
        if (self.px - key_x).abs() < 3 * ONE && (self.py - key_y).abs() < 3 * ONE {
            self.keys_held += 1;
        }
        if spotted {
            self.resets += 1;
            self.px = -12 * ONE;
            self.py = -12 * ONE;
            self.noise = 0;
            self.spot_meter = [0; 3];
        } else if self.keys_held >= 2 && self.px > 10 * ONE && self.py > 10 * ONE {
            self.rooms_cleared += 1;
            self.keys_held = 0;
            self.px = -12 * ONE;
            self.py = -12 * ONE;
        }
    }

    fn encode_into(&self, out: &mut Vec<u8>) {
        out.clear();
        out.extend_from_slice(&self.px.to_le_bytes());
        out.extend_from_slice(&self.py.to_le_bytes());
        out.extend_from_slice(&self.noise.to_le_bytes());
        out.push(self.crouching);
        for i in 0..4 {
            out.extend_from_slice(&self.gx[i].to_le_bytes());
            out.extend_from_slice(&self.gy[i].to_le_bytes());
            out.push(self.gwp[i]);
            out.extend_from_slice(&self.galert[i].to_le_bytes());
        }
        for j in 0..3 {
            out.extend_from_slice(&self.spot_phase[j].to_le_bytes());
            out.extend_from_slice(&self.spot_meter[j].to_le_bytes());
        }
        out.extend_from_slice(&self.keys_held.to_le_bytes());
        out.extend_from_slice(&self.rooms_cleared.to_le_bytes());
        out.extend_from_slice(&self.resets.to_le_bytes());
        out.extend_from_slice(&self.tick.to_le_bytes());
    }
}

// Session 1: Wave Arena (7 coupled actor modules: PlayerAvatar, Raycaster, FastChaser, Bruiser, BossFSM, WaveSpawner, ScoreHUD)
struct WaveArena {
    px: i64,
    py: i64,
    hp: i64,
    dash_cd: u16,
    ray_cd: u16,
    clip: u16,
    ax: [i64; 12],
    ay: [i64; 12],
    ahp: [i64; 12],
    akind: [u8; 12],
    boss_phase: u8,
    boss_timer: u16,
    wave: u32,
    rng_s: u64,
    score: u64,
    combo: u32,
    tick: u64,
}

impl WaveArena {
    fn new(seed: u64) -> Self {
        let mut s = Self {
            px: 0,
            py: 0,
            hp: 100,
            dash_cd: 0,
            ray_cd: 0,
            clip: 24,
            ax: [0; 12],
            ay: [0; 12],
            ahp: [0; 12],
            akind: [0; 12],
            boss_phase: 0,
            boss_timer: 0,
            wave: 1,
            rng_s: seed ^ 0xA5A5_5A5A_1234_5678,
            score: 0,
            combo: 1,
            tick: 0,
        };
        s.spawn_wave();
        s
    }

    fn spawn_wave(&mut self) {
        for i in 0..12 {
            self.rng_s = splitmix(self.rng_s);
            let side = (self.rng_s & 3) as i64;
            let offset = (((self.rng_s >> 8) & 0x1F) as i64 - 16) * ONE;
            let (sx, sy) = match side {
                0 => (-24 * ONE, offset),
                1 => (24 * ONE, offset),
                2 => (offset, -24 * ONE),
                _ => (offset, 24 * ONE),
            };
            self.ax[i] = sx;
            self.ay[i] = sy;
            self.akind[i] = if i == 11 { 2 } else if i >= 8 { 1 } else { 0 };
            self.ahp[i] = match self.akind[i] {
                0 => 30,
                1 => 70,
                _ => 180,
            };
        }
    }

    fn step(&mut self, cmd: u16, leak_mode: u8) {
        self.tick += 1;
        let dx = (cmd & 3) as i64 - 1;
        let dy = ((cmd >> 2) & 3) as i64 - 1;
        let pulse = ((cmd >> 4) & 1) == 1;
        let dash = ((cmd >> 5) & 1) == 1;
        let aim_idx = ((cmd >> 6) & 0xF) as usize % 12;

        let spd = if dash && self.dash_cd == 0 {
            self.dash_cd = 30;
            ONE / 3
        } else {
            if self.dash_cd > 0 {
                self.dash_cd -= 1;
            }
            ONE / 8
        };
        self.px = (self.px + dx * spd).clamp(-24 * ONE, 24 * ONE);
        self.py = (self.py + dy * spd).clamp(-24 * ONE, 24 * ONE);

        if leak_mode == 1 {
            let ns = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().subsec_nanos() as i64;
            self.px = self.px.wrapping_add(ns & 0x7F);
        }

        if self.ray_cd > 0 {
            self.ray_cd -= 1;
        }
        if pulse && self.ray_cd == 0 {
            if self.clip == 0 {
                self.clip = 24;
                self.ray_cd = 12;
            } else {
                self.clip -= 1;
                self.ray_cd = 4;
                if self.ahp[aim_idx] > 0 {
                    self.ahp[aim_idx] -= 25;
                    if self.ahp[aim_idx] <= 0 {
                        self.ahp[aim_idx] = 0;
                        self.combo = (self.combo + 1).min(16);
                        let pts = (10u64 + (self.akind[aim_idx] as u64) * 20) * (self.combo as u64);
                        self.score += pts;
                    }
                }
            }
        }

        let mut active = 0usize;
        for i in 0..12 {
            if self.ahp[i] <= 0 {
                continue;
            }
            active += 1;
            let step_a = match self.akind[i] {
                0 => ONE / 10,
                1 => if self.ahp[i] < 30 { ONE / 9 } else { ONE / 14 },
                _ => {
                    self.boss_timer += 1;
                    if self.boss_timer >= 60 {
                        self.boss_timer = 0;
                        self.boss_phase = (self.boss_phase + 1) % 3;
                    }
                    if self.boss_phase == 1 { ONE / 7 } else { ONE / 18 }
                }
            };
            if self.ax[i] < self.px {
                self.ax[i] += step_a;
            } else if self.ax[i] > self.px {
                self.ax[i] -= step_a;
            }
            if self.ay[i] < self.py {
                self.ay[i] += step_a;
            } else if self.ay[i] > self.py {
                self.ay[i] -= step_a;
            }
            if (self.ax[i] - self.px).abs() < ONE && (self.ay[i] - self.py).abs() < ONE {
                self.hp -= 5;
                self.combo = 1;
                if self.hp <= 0 {
                    self.hp = 100;
                    self.px = 0;
                    self.py = 0;
                }
            }
        }
        if active == 0 {
            self.wave += 1;
            self.spawn_wave();
        }
    }

    fn encode_into(&self, out: &mut Vec<u8>) {
        out.clear();
        out.extend_from_slice(&self.px.to_le_bytes());
        out.extend_from_slice(&self.py.to_le_bytes());
        out.extend_from_slice(&self.hp.to_le_bytes());
        out.extend_from_slice(&self.dash_cd.to_le_bytes());
        out.extend_from_slice(&self.ray_cd.to_le_bytes());
        out.extend_from_slice(&self.clip.to_le_bytes());
        for i in 0..12 {
            out.extend_from_slice(&self.ax[i].to_le_bytes());
            out.extend_from_slice(&self.ay[i].to_le_bytes());
            out.extend_from_slice(&self.ahp[i].to_le_bytes());
            out.push(self.akind[i]);
        }
        out.push(self.boss_phase);
        out.extend_from_slice(&self.boss_timer.to_le_bytes());
        out.extend_from_slice(&self.wave.to_le_bytes());
        out.extend_from_slice(&self.rng_s.to_le_bytes());
        out.extend_from_slice(&self.score.to_le_bytes());
        out.extend_from_slice(&self.combo.to_le_bytes());
        out.extend_from_slice(&self.tick.to_le_bytes());
    }
}

// Session 2: Tanks Q32.32 Arena (5 coupled modules: TankChassis, BallisticsQ32, RadialFalloff, HealthShield, RoundDirector)
struct TanksQ32 {
    tx: [i64; 2],
    ty: [i64; 2],
    tvx: [i64; 2],
    tvy: [i64; 2],
    hull: [i64; 2],
    shield: [i64; 2],
    px: [i64; 2],
    py: [i64; 2],
    pz: [i64; 2],
    pvx: [i64; 2],
    pvy: [i64; 2],
    pvz: [i64; 2],
    pactive: [u8; 2],
    wins: [u32; 2],
    round_no: u32,
    wind_x: i64,
    tick: u64,
}

impl TanksQ32 {
    fn new(seed: u64) -> Self {
        let w = (((splitmix(seed) & 0xFF) as i64) - 128) * (ONE / 256);
        Self {
            tx: [-16 * ONE, 16 * ONE],
            ty: [0, 0],
            tvx: [0, 0],
            tvy: [0, 0],
            hull: [100, 100],
            shield: [50, 50],
            px: [0, 0],
            py: [0, 0],
            pz: [0, 0],
            pvx: [0, 0],
            pvy: [0, 0],
            pvz: [0, 0],
            pactive: [0, 0],
            wins: [0, 0],
            round_no: 1,
            wind_x: w,
            tick: 0,
        }
    }

    fn step(&mut self, cmd: u16, leak_mode: u8) {
        self.tick += 1;
        let dx0 = (cmd & 3) as i64 - 1;
        let dy0 = ((cmd >> 2) & 3) as i64 - 1;
        let launch0 = ((cmd >> 4) & 1) == 1;
        let dx1 = (((cmd >> 6) & 3) as i64) - 1;
        let dy1 = (((cmd >> 8) & 3) as i64) - 1;
        let launch1 = ((cmd >> 5) & 1) == 1;

        let dxs = [dx0, dx1];
        let dys = [dy0, dy1];
        let launches = [launch0, launch1];
        const DRAG: i64 = (ONE * 95) / 100;

        for i in 0..2 {
            self.tvx[i] = qmul(self.tvx[i] + dxs[i] * (ONE / 32), DRAG);
            self.tvy[i] = qmul(self.tvy[i] + dys[i] * (ONE / 32), DRAG);
            self.tx[i] = (self.tx[i] + self.tvx[i]).clamp(-28 * ONE, 28 * ONE);
            self.ty[i] = (self.ty[i] + self.tvy[i]).clamp(-28 * ONE, 28 * ONE);
            if self.shield[i] < 50 && (self.tick % 30 == 0) {
                self.shield[i] += 1;
            }
            if launches[i] && self.pactive[i] == 0 {
                let opp = 1 - i;
                self.pactive[i] = 1;
                self.px[i] = self.tx[i];
                self.py[i] = self.ty[i];
                self.pz[i] = ONE;
                self.pvx[i] = (self.tx[opp] - self.tx[i]) / 24;
                self.pvy[i] = (self.ty[opp] - self.ty[i]) / 24;
                self.pvz[i] = ONE / 2;
            }
        }

        if leak_mode == 1 {
            let ns = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().subsec_nanos() as i64;
            self.tx[0] = self.tx[0].wrapping_add(ns & 0x7F);
        }

        for i in 0..2 {
            if self.pactive[i] == 1 {
                self.pvx[i] += self.wind_x / 64;
                self.pvz[i] -= ONE / 24; // Q32.32 gravity
                self.px[i] += self.pvx[i];
                self.py[i] += self.pvy[i];
                self.pz[i] += self.pvz[i];
                if self.pz[i] <= 0 {
                    self.pactive[i] = 0;
                    // Quadratic integer radial falloff inside radius R = 6 * ONE
                    for tgt in 0..2 {
                        let rx = (self.px[i] - self.tx[tgt]) >> 16;
                        let ry = (self.py[i] - self.ty[tgt]) >> 16;
                        let r2 = rx * rx + ry * ry;
                        let max_r = 6i64 * 65536;
                        let max_r2 = max_r * max_r;
                        if r2 < max_r2 {
                            let rem = max_r2 - r2;
                            let impact = ((40i128 * (rem as i128)) / (max_r2 as i128)) as i64;
                            if self.shield[tgt] >= impact {
                                self.shield[tgt] -= impact;
                            } else {
                                let rem_imp = impact - self.shield[tgt];
                                self.shield[tgt] = 0;
                                self.hull[tgt] -= rem_imp;
                            }
                        }
                    }
                }
            }
        }

        if self.hull[0] <= 0 || self.hull[1] <= 0 {
            if self.hull[0] > self.hull[1] {
                self.wins[0] += 1;
            } else if self.hull[1] > self.hull[0] {
                self.wins[1] += 1;
            }
            self.round_no += 1;
            self.tx = [-16 * ONE, 16 * ONE];
            self.ty = [0, 0];
            self.tvx = [0, 0];
            self.tvy = [0, 0];
            self.hull = [100, 100];
            self.shield = [50, 50];
            self.pactive = [0, 0];
            self.wind_x = -self.wind_x;
        }
    }

    fn encode_into(&self, out: &mut Vec<u8>) {
        out.clear();
        for i in 0..2 {
            out.extend_from_slice(&self.tx[i].to_le_bytes());
            out.extend_from_slice(&self.ty[i].to_le_bytes());
            out.extend_from_slice(&self.tvx[i].to_le_bytes());
            out.extend_from_slice(&self.tvy[i].to_le_bytes());
            out.extend_from_slice(&self.hull[i].to_le_bytes());
            out.extend_from_slice(&self.shield[i].to_le_bytes());
            out.extend_from_slice(&self.px[i].to_le_bytes());
            out.extend_from_slice(&self.py[i].to_le_bytes());
            out.extend_from_slice(&self.pz[i].to_le_bytes());
            out.extend_from_slice(&self.pvx[i].to_le_bytes());
            out.extend_from_slice(&self.pvy[i].to_le_bytes());
            out.extend_from_slice(&self.pvz[i].to_le_bytes());
            out.push(self.pactive[i]);
            out.extend_from_slice(&self.wins[i].to_le_bytes());
        }
        out.extend_from_slice(&self.round_no.to_le_bytes());
        out.extend_from_slice(&self.wind_x.to_le_bytes());
        out.extend_from_slice(&self.tick.to_le_bytes());
    }
}

fn replay_session(raw_log: &[u8], leak_mode: u8, dump_snap_path: Option<&str>) -> (String, String, usize, f64, Vec<[u8; 32]>) {
    let (sid, seed, cmds) = parse_input_log(raw_log);
    let t0 = Instant::now();
    let mut state_buf = Vec::with_capacity(512);
    let mut ckpt_chain = Vec::with_capacity(2160 * 32);
    let mut ckpt_list = Vec::with_capacity(2160);
    let mut snap_stream = if dump_snap_path.is_some() {
        Vec::with_capacity(cmds.len() * 256)
    } else {
        Vec::new()
    };

    match sid {
        0 => {
            let mut sim = StealthMansion::new(seed);
            for (idx, &c) in cmds.iter().enumerate() {
                sim.step(c, leak_mode);
                if dump_snap_path.is_some() || (idx + 1) % CKPT_STRIDE == 0 || idx + 1 == cmds.len() {
                    sim.encode_into(&mut state_buf);
                    if dump_snap_path.is_some() {
                        snap_stream.extend_from_slice(&state_buf);
                    }
                    if (idx + 1) % CKPT_STRIDE == 0 {
                        let h = sha256_bytes(&state_buf);
                        ckpt_chain.extend_from_slice(&h);
                        ckpt_list.push(h);
                    }
                }
            }
            sim.encode_into(&mut state_buf);
        }
        1 => {
            let mut sim = WaveArena::new(seed);
            for (idx, &c) in cmds.iter().enumerate() {
                sim.step(c, leak_mode);
                if dump_snap_path.is_some() || (idx + 1) % CKPT_STRIDE == 0 || idx + 1 == cmds.len() {
                    sim.encode_into(&mut state_buf);
                    if dump_snap_path.is_some() {
                        snap_stream.extend_from_slice(&state_buf);
                    }
                    if (idx + 1) % CKPT_STRIDE == 0 {
                        let h = sha256_bytes(&state_buf);
                        ckpt_chain.extend_from_slice(&h);
                        ckpt_list.push(h);
                    }
                }
            }
            sim.encode_into(&mut state_buf);
        }
        _ => {
            let mut sim = TanksQ32::new(seed);
            for (idx, &c) in cmds.iter().enumerate() {
                sim.step(c, leak_mode);
                if dump_snap_path.is_some() || (idx + 1) % CKPT_STRIDE == 0 || idx + 1 == cmds.len() {
                    sim.encode_into(&mut state_buf);
                    if dump_snap_path.is_some() {
                        snap_stream.extend_from_slice(&state_buf);
                    }
                    if (idx + 1) % CKPT_STRIDE == 0 {
                        let h = sha256_bytes(&state_buf);
                        ckpt_chain.extend_from_slice(&h);
                        ckpt_list.push(h);
                    }
                }
            }
            sim.encode_into(&mut state_buf);
        }
    }
    let wall_ms = t0.elapsed().as_secs_f64() * 1000.0;
    let final_sha = hex32(&sha256_bytes(&state_buf));
    let all_2160_sha = hex32(&sha256_bytes(&ckpt_chain));
    if let Some(p) = dump_snap_path {
        fs::write(p, &snap_stream).expect("write snapshot stream");
    }
    (final_sha, all_2160_sha, state_buf.len(), wall_ms, ckpt_list)
}

fn first_div_tick_leak(raw_log: &[u8], leak_mode: u8) -> usize {
    let (_sid, seed, cmds) = parse_input_log(raw_log);
    let mut a = StealthMansion::new(seed);
    let mut b = StealthMansion::new(seed);
    let mut ba = Vec::with_capacity(256);
    let mut bb = Vec::with_capacity(256);
    // Run two independent replays (with different HashMap random states / clock / stack address / float)
    for (idx, &c) in cmds.iter().take(1000).enumerate() {
        a.step(c, 0);
        b.step(c, leak_mode);
        a.encode_into(&mut ba);
        b.encode_into(&mut bb);
        if ba != bb {
            return idx + 1;
        }
    }
    0
}

fn main() {
    let args: Vec<String> = env::args().collect();
    let mode = args.get(1).map(|s| s.as_str()).unwrap_or("help");
    let dir = args.get(2).map(|s| s.as_str()).unwrap_or(".");
    let seeds: [u64; 3] = [0x2026_1123_4838_0001, 0x2026_1123_4838_0002, 0x2026_1123_4838_0003];
    let names = ["HauntedJaunt_1h", "SurvivalShooter_1h", "TanksQ32_1h"];

    if mode == "gen" {
        for sid in 0..3u32 {
            let log = build_input_log(sid, seeds[sid as usize]);
            let p = format!("{}/D_session_{}.bin", dir, sid);
            fs::write(&p, &log).expect("write D log");
        }
        println!("GENERATED 3 logs in {}", dir);
    } else if mode == "verify" {
        let with_snaps = args.get(3).map(|s| s == "--dump-snaps").unwrap_or(false);
        println!("{{");
        println!("  \"os\": \"{}\",", env::consts::OS);
        println!("  \"arch\": \"{}\",", env::consts::ARCH);
        println!("  \"sessions\": [");
        for sid in 0..3usize {
            let p = format!("{}/D_session_{}.bin", dir, sid);
            let raw = fs::read(&p).expect("read D log");
            let log_sha = hex32(&sha256_bytes(&raw));
            let snap_p = if with_snaps {
                Some(format!("{}/S_snap_{}.bin", dir, sid))
            } else {
                None
            };
            let (final_sha, chain_sha, state_bytes, wall_ms, ckpts) =
                replay_session(&raw, 0, snap_p.as_deref());
            let c1 = hex32(&ckpts[0]);       // tick 100
            let c1080 = hex32(&ckpts[1079]); // tick 108,000 (30 min)
            let c2160 = hex32(&ckpts[2159]); // tick 216,000 (60 min)
            let comma = if sid < 2 { "," } else { "" };
            println!(
                "    {{\"session_id\":{},\"name\":\"{}\",\"ticks\":{},\"checkpoints\":{},\"log_D_bytes\":{},\"log_D_sha256\":\"{}\",\"state_bytes\":{},\"wall_ms\":{:.3},\"ckpt_tick_100_sha256\":\"{}\",\"ckpt_tick_108000_sha256\":\"{}\",\"ckpt_tick_216000_sha256\":\"{}\",\"final_sha256\":\"{}\",\"all_2160_checkpoints_chain_sha256\":\"{}\"}}{}",
                sid, names[sid], TICKS_1H, ckpts.len(), raw.len(), log_sha, state_bytes, wall_ms, c1, c1080, c2160, final_sha, chain_sha, comma
            );
        }
        println!("  ],");
        // Positive falsifier controls on Session 0 D log
        let p0 = format!("{}/D_session_0.bin", dir);
        let raw0 = fs::read(&p0).expect("read D_session_0");
        let leak_names = [
            (1u8, "L1_wall_clock_ns"),
            (2u8, "L2_stack_addr_rng"),
            (3u8, "L3_hash_seed_order"),
            (4u8, "L4_host_libm_sin_f64"),
        ];
        println!("  \"ambient_leak_controls\": [");
        for (idx, &(lm, lname)) in leak_names.iter().enumerate() {
            let t_div = first_div_tick_leak(&raw0, lm);
            let (leak_final, _, _, _, _) = replay_session(&raw0, lm, None);
            let comma = if idx + 1 < leak_names.len() { "," } else { "" };
            println!(
                "    {{\"leak_id\":\"{}\",\"t_div_vs_pure\":{},\"leaked_final_sha256\":\"{}\"}}{}",
                lname, t_div, leak_final, comma
            );
        }
        println!("  ]");
        println!("}}");
    } else {
        eprintln!("Usage: ge_h8_replay [gen|verify] <dir> [--dump-snaps]");
    }
}
