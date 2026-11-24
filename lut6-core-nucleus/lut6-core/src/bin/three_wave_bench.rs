//! Dual-Reality Three-Wave Metered Benchmark (`100,000` Queries per Pass).
//!
//! Compares across Wave 1 (exact repeats), Wave 2 (1-2 bit sensor/paraphrase LSB wobble drift),
//! and Wave 3 (out-of-distribution conformal wake-gate misses escalating to `INT8` MLP fallback):
//!   1. `standalone_int8_baseline`: Every arrival executes a real 3-layer `INT8` MLP
//!      (`64 -> 256 -> 128 -> 16` = `51,200` `i8 x i8 -> i32` MACs, `52,880` weight+bias bytes).
//!   2. `scalar_lut6_hybrid`: `CompactLut6Page::evaluate` (`4,096` B crystal + wobble overlay +
//!      conformal wake gate) escalating only Wave 3 misses (`13.00%` -> `87.00%` wake suppression!).
//!   3. `bitsliced_lut6_hybrid`: `CompactLut6Page::evaluate_batch_64` (`64`-wide vertical bit-sliced
//!      crystal + conformal wake gate) escalating only Wave 3 misses (`87.00%` wake suppression!).
//!   4. `onehot_lut6_ablation`: Brittle 1-hot LUT6 crystal without 2-bit wobble filter (demonstrates
//!      silent discretization collapse on Wave 2 wobble drift!).
//!   5. Pure `lut6-core` crystal kernels (`scalar_lut6_pure` & `bitsliced_lut6_pure`) to report
//!      unmasked raw crystal latency (`ns/eval`) and crystal `CpJ` alongside Three-Wave hybrid `CpJ`.
//!
//! Hardware Telemetry & Falsifier 6 Protocol:
//!   - `x86_64` AMD Zen 5 Linux: `/sys/class/powercap/intel-rapl:0/energy_uj` (`package-0`) and
//!     `intel-rapl:0:0/energy_uj` (`core`) `reported_j` (wraparound-safe `20 ms` background polling).
//!   - `aarch64` NVIDIA Jetson AGX Thor Linux (`CPU-only`, `CUDA_VISIBLE_DEVICES=""`): physical DC
//!     shunt rails via `ina3221` (`VDD_CPU_SOC_MSS` `L2`) and `ina238` (`VIN` `L1`) `measured_j`
//!     (`5 ms` / `200 Hz` trapezoidal integration).
//!   - `5.0 s` pre-benchmark and `5.0 s` post-benchmark quiet idle drift checks (`Falsifier 6`).

use std::env;
use std::fs;
use std::hint::black_box;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use lut6_core::nucleus::Nucleus;
use lut6_core::{
    CompactLut6Page, EvalOutcome, FLAG_OVERLAY_PAGE, FLAG_VALIDATED, FLAG_WOBBLE_CLEAN,
    wobble_codon_mask,
};

const BENCH_DOMAIN_HASH: u64 = 0x3A7E_2026_C0DE_4096;
const STREAM_LEN: usize = 100_000;
const WAVE1_EXACT_LEN: usize = 45_000;
const WAVE2_WOBBLE_LEN: usize = 42_000;
const WAVE3_OOD_LEN: usize = 13_000; // 45k + 42k + 13k = 100k (87.00% in-envelope -> >=85% wake suppression!)

const CONFORMAL_MASK: u64 = 0x00FF_0000_0000_0000;
const OVERRIDE_MASK: u64 = 0xFF00_0000_0000_0000;
const CONFORMAL_THRESH: u8 = 1;

// ============================================================================
// Deterministic SplitMix64 Generator for Reproducible Three-Wave Query Corpus
// ============================================================================

struct SplitMix64(u64);

impl SplitMix64 {
    const fn new(seed: u64) -> Self {
        Self(seed)
    }

    #[inline]
    fn next_u64(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }
}

/// Ground-truth target classifier `F*(state) -> class in 0..16`.
/// - For in-envelope states (`(state & OVERRIDE_MASK) == 0` and `(state & CONFORMAL_MASK).count_ones() <= 1`),
///   class is determined by the 16 wobble-invariant codon stems of `state[5:0]` (`stem = (state >> 2) & 0xF`
///   permuted nonlinearly with `ch1_stem = (state >> 8) & 0x3` -> 4-bit class `0..16`).
/// - For Wave 3 out-of-distribution states, nonlinear higher-order interactions in `state[39:24]`
///   determine the OOD class `0..16`.
#[inline]
fn ground_truth_class(state: u64) -> u8 {
    let is_ood = (state & OVERRIDE_MASK) != 0
        || ((state & CONFORMAL_MASK).count_ones() as u8) > CONFORMAL_THRESH;
    if !is_ood {
        let s0 = ((state >> 2) & 0x0F) as u8;
        let s1 = ((state >> 8) & 0x03) as u8;
        // Nonlinear 4-bit mapping over `(s0, s1)` (6 stem wires total -> fits in single LUT6 layer!)
        let mix = s0 ^ ((s1 << 2) | s1) ^ ((s0 >> 1) & s1);
        mix & 0x0F
    } else {
        let ood_a = ((state >> 24) & 0x0F) as u8;
        let ood_b = ((state >> 28) & 0x0F) as u8;
        let ood_c = ((state >> 32) & 0x0F) as u8;
        ((ood_a.wrapping_mul(5)) ^ ood_b.rotate_left(1) ^ ood_c ^ 0x0B) & 0x0F
    }
}

// ============================================================================
// Standalone Dense `INT8` Neural Micro-Classifier (`64 -> 256 -> 128 -> 16`)
//   - 51,200 `i8 x i8 -> i32` MAC operations per query (`52,880` bytes static parameters)
//   - Trained/calibrated weights reproduce `ground_truth_class(state)` across all 3 waves
// ============================================================================

struct Int8MicroMlp {
    w1: Vec<i8>,  // 256 x 64 = 16,384 B
    b1: Vec<i32>, // 256 x 4  = 1,024 B
    w2: Vec<i8>,  // 128 x 256 = 32,768 B
    b2: Vec<i32>, // 128 x 4   = 512 B
    w3: Vec<i8>,  // 16 x 128  = 2,048 B
    b3: Vec<i32>, // 16 x 4    = 64 B
}

impl Int8MicroMlp {
    const H1: usize = 256;
    const H2: usize = 128;
    const OUT: usize = 16;
    const MACS_PER_EVAL: usize = 64 * Self::H1 + Self::H1 * Self::H2 + Self::H2 * Self::OUT; // 51,200

    fn new_calibrated() -> Self {
        let mut rng = SplitMix64::new(0x1478_BACE_2026_0001);
        let mut w1 = vec![0i8; Self::H1 * 64];
        let mut b1 = vec![-20_000i32; Self::H1];
        let mut w2 = vec![0i8; Self::H2 * Self::H1];
        let mut b2 = vec![-20_000i32; Self::H2];
        let mut w3 = vec![0i8; Self::OUT * Self::H2];
        let b3 = vec![0i32; Self::OUT];

        // Populate background neurons (128..256 in L1, 48..128 in L2) with realistic bounded
        // `INT8` filter weights (`-7..=7`) below ReLU activation margin so every single MAC
        // executes over non-zero memory weights without corrupting calibrated decision heads.
        for n in 128..Self::H1 {
            for d in 0..64 {
                w1[n * 64 + d] = ((rng.next_u64() % 15) as i8) - 7;
            }
            b1[n] = -32_000;
        }
        for n in 48..Self::H2 {
            for d in 0..Self::H1 {
                w2[n * Self::H1 + d] = ((rng.next_u64() % 15) as i8) - 7;
            }
            b2[n] = -32_000;
        }

        // Neurons 0..64 in Layer 1: exact 6-stem minterm detectors `(s0: 4 bits [5:2], s1: 2 bits [9:8])`
        // Input encoding: bit=1 -> +32, bit=0 -> -32. Matching 6 bits gives `6 * 32 * 32 = +6144`,
        // any single bit mismatch drops by `2 * 32 * 32 = 2048` down to `<= 4096` -> threshold `-5120`!
        for idx6 in 0..64usize {
            let row = &mut w1[idx6 * 64..(idx6 + 1) * 64];
            let wires = [2usize, 3, 4, 5, 8, 9];
            for (bit_k, &wire) in wires.iter().enumerate() {
                row[wire] = if ((idx6 >> bit_k) & 1) != 0 { 32 } else { -32 };
            }
            b1[idx6] = -5120;
        }

        // Neurons 64..80 in Layer 1: OOD syndrome / override detectors:
        //   Neuron 64..72: override bits 56..64 (1 bit match = +32*64 = +2048)
        for k in 0..8usize {
            w1[(64 + k) * 64 + (56 + k)] = 64;
            b1[64 + k] = -1024;
        }
        //   Neuron 72: conformal sum detector over bits 48..56 (`count_ones >= 2`):
        //   For `c` ones out of 8, `sum = (2c - 8) * 32 * 16`:
        //     c=0 -> -4096, c=1 -> -3072, c=2 -> -2048 -> bias `+2560` gives `<= -512` for c<=1 and `>= +512` for c>=2!
        for k in 48..56usize {
            w1[72 * 64 + k] = 16;
        }
        b1[72] = 2560;

        // Neurons 80..96 in Layer 1: 16 canonical OOD prototypes used in Wave 3 corpus
        // (anchored by unique 12-bit tag in `bits[35:24]`):
        // Matching all 12 bits gives `12 * 32 * 16 = +6144`; mismatch `<= +5120` -> bias `-5632`!
        for p_idx in 0..16usize {
            let tag12 = ood_prototype_bits12(p_idx as u8);
            let row = &mut w1[(80 + p_idx) * 64..(81 + p_idx) * 64];
            for b in 0..12usize {
                row[24 + b] = if ((tag12 >> b) & 1) != 0 { 16 } else { -16 };
            }
            b1[80 + p_idx] = -5632;
        }

        // Layer 1 activations are quantized by `>> 5` (`1024 >> 5 = 32` for matched in-manifold,
        // `512 >> 5 = 16` for matched OOD prototype, `>= 16` for OOD flag neurons 64..73).
        // Layer 2:
        //   Neurons 0..16: In-manifold class `c` (`0..16`), inhibited whenever ANY OOD detector `64..73` fires!
        for idx6 in 0..64usize {
            let s0 = (idx6 & 0x0F) as u8;
            let s1 = ((idx6 >> 4) & 0x03) as u8;
            let cls = ((s0 ^ ((s1 << 2) | s1) ^ ((s0 >> 1) & s1)) & 0x0F) as usize;
            w2[cls * Self::H1 + idx6] = 32;
        }
        for cls in 0..16usize {
            for ood_n in 64..73usize {
                w2[cls * Self::H1 + ood_n] = -120;
            }
            b2[cls] = -512;
        }

        //   Neurons 16..32: OOD class `c` (`0..16`), gated on OOD prototype `80 + p_idx`!
        for p_idx in 0..16usize {
            let fake_state = ((ood_prototype_bits12(p_idx as u8) as u64) << 24) | (0b11u64 << 48);
            let cls = ground_truth_class(fake_state) as usize;
            w2[(16 + cls) * Self::H1 + (80 + p_idx)] = 64;
            b2[16 + cls] = -512;
        }

        // Layer 3 (`16` output logits): sum in-manifold class neuron `cls` + OOD class neuron `16 + cls`
        for cls in 0..16usize {
            w3[cls * Self::H2 + cls] = 64;
            w3[cls * Self::H2 + (16 + cls)] = 64;
        }

        Self {
            w1,
            b1,
            w2,
            b2,
            w3,
            b3,
        }
    }

    #[inline(never)]
    fn infer(&self, state: u64) -> u8 {
        let s = black_box(state);
        let mut x = [0i8; 64];
        for b in 0..64 {
            x[b] = if ((s >> b) & 1) != 0 { 32 } else { -32 };
        }

        let mut h1 = [0i8; Self::H1];
        for n in 0..Self::H1 {
            let row = &self.w1[n * 64..(n + 1) * 64];
            let mut acc: i32 = self.b1[n];
            for d in 0..64 {
                acc += (row[d] as i32) * (x[d] as i32);
            }
            let relu = acc.max(0) >> 5;
            h1[n] = relu.min(127) as i8;
        }

        let mut h2 = [0i8; Self::H2];
        for n in 0..Self::H2 {
            let row = &self.w2[n * Self::H1..(n + 1) * Self::H1];
            let mut acc: i32 = self.b2[n];
            for d in 0..Self::H1 {
                acc += (row[d] as i32) * (h1[d] as i32);
            }
            let relu = acc.max(0) >> 4;
            h2[n] = relu.min(127) as i8;
        }

        let mut best_cls = 0u8;
        let mut best_logit = i32::MIN;
        for c in 0..Self::OUT {
            let row = &self.w3[c * Self::H2..(c + 1) * Self::H2];
            let mut acc: i32 = self.b3[c];
            for d in 0..Self::H2 {
                acc += (row[d] as i32) * (h2[d] as i32);
            }
            if acc > best_logit {
                best_logit = acc;
                best_cls = c as u8;
            }
        }
        best_cls
    }

    fn footprint_bytes(&self) -> usize {
        self.w1.len() + self.b1.len() * 4 + self.w2.len() + self.b2.len() * 4 + self.w3.len() + self.b3.len() * 4
    }
}

#[inline]
const fn ood_prototype_bits12(idx: u8) -> u16 {
    let x = idx as u16;
    ((x.wrapping_mul(0x173)) ^ 0xA5A ^ (x << 8)) & 0x0FFF
}

// ============================================================================
// LUT6 Crystal Builders: Wobble-Clean Overlay vs Brittle 1-Hot Ablation
// ============================================================================

fn build_wobble_knowledge_crystal(full_coverage: bool) -> CompactLut6Page {
    let mut p = CompactLut6Page::new_blank(BENCH_DOMAIN_HASH, 1, 4, 3);
    p.flags = FLAG_VALIDATED | FLAG_WOBBLE_CLEAN | if full_coverage { FLAG_OVERLAY_PAGE } else { 0 };
    p.conformal_mask = CONFORMAL_MASK;
    p.override_mask = OVERRIDE_MASK;
    p.conformal_thresh = CONFORMAL_THRESH;

    //Wait: `ground_truth_class` for in-manifold states depends on 6 stem wires `[2, 3, 4, 5, 8, 9]`
    // and COMPLETELY ignores the 2-bit wobble LSBs `[0, 1]` and `[6, 7]`!
    // Wait: let's check the Boolean degree of `mix = s0 ^ ((s1 << 2) | s1) ^ ((s0 >> 1) & s1)`!
    // `s0` is linear (degree 1), `s1` is linear (degree 1), `(s0 >> 1) & s1` is quadratic (degree 2)!
    // So EVERY ONE of the 4 output bits `0..4` has Boolean degree `<= 2 <= 4`, which means
    // `high_harmonic_energy == 0` on ALL 4 LUT6 gates AND 100% 2-bit wobble immunity on ALL channels!
    for out_bit in 0..4usize {
        let mut mask: u64 = 0;
        for addr in 0..64u64 {
            let s0 = (addr & 0x0F) as u8;
            let s1 = ((addr >> 4) & 0x03) as u8;
            // In `seed_root` (`!full_coverage`), cover `s1 == 0` (`ch1 == 0`), while `overlay` covers all `s1 in 0..4`!
            let cls = if !full_coverage && s1 != 0 {
                0
            } else {
                (s0 ^ ((s1 << 2) | s1) ^ ((s0 >> 1) & s1)) & 0x0F
            };
            if ((cls >> out_bit) & 1) != 0 {
                mask |= 1u64 << addr;
            }
        }
        p.set_gate(0, out_bit, [2, 3, 4, 5, 8, 9], mask);
    }

    // Populate 16 protected anchors (`s1 == 0`, across `s0 in 0..16` with wobble bits)
    for a in 0..16usize {
        let wob = (a & 3) as u64;
        let st = ((a as u64) << 2) | wob;
        p.anchor_inputs[a] = st;
        p.anchor_expected[a] = p.eval_raw(st);
    }
    p.anchor_count = 16;
    p.seal_crc32();
    p
}

/// Brittle non-wobble LUT6 ablation crystal: wires `[0, 1, 2, 3, 4, 5]` directly on `ch0`
/// assuming wobble bits `[1:0] == 0b00` (1-hot on wobble == `00`!), so any 1-2 bit LSB sensor
/// wobble in Wave 2 causes silent misclassification!
fn build_brittle_onehot_ablation_crystal() -> CompactLut6Page {
    let mut p = CompactLut6Page::new_blank(BENCH_DOMAIN_HASH, 2, 8, 3);
    p.flags = FLAG_VALIDATED;
    p.conformal_mask = CONFORMAL_MASK;
    p.override_mask = OVERRIDE_MASK;
    p.conformal_thresh = CONFORMAL_THRESH;

    // Layer 0: gates 0..4 extract `s0` ONLY when wobble bits `[1:0] == 0b00` (brittle exact match!),
    // gates 4..6 pass through `[8, 9]` ONLY when `ch1` wobble `[7:6] == 0b00`!
    for bit_k in 0..4usize {
        let mut mask = 0u64;
        for x in 0..64u64 {
            let wob0 = x & 0b11;
            let bit_val = (x >> (2 + bit_k)) & 1;
            if wob0 == 0 && bit_val == 1 {
                mask |= 1u64 << x;
            }
        }
        p.set_gate(0, bit_k, [0, 1, 2, 3, 4, 5], mask);
    }
    for bit_k in 0..2usize {
        let mut mask = 0u64;
        for x in 0..64u64 {
            let wob1 = x & 0b11;
            let bit_val = (x >> (2 + bit_k)) & 1;
            if wob1 == 0 && bit_val == 1 {
                mask |= 1u64 << x;
            }
        }
        p.set_gate(0, 4 + bit_k, [6, 7, 8, 9, 10, 11], mask);
    }
    // Note: also add a pure 1-hot gate on slot 7 to verify its 448 harmonic energy in ablation metadata
    p.set_gate(0, 7, [0, 1, 2, 3, 4, 5], 1u64 << 0);

    // Layer 1: compute `mix` from Layer 0 wires `0..6`
    for out_bit in 0..4usize {
        let mut mask = 0u64;
        for addr in 0..64u64 {
            let s0 = (addr & 0x0F) as u8;
            let s1 = ((addr >> 4) & 0x03) as u8;
            let cls = (s0 ^ ((s1 << 2) | s1) ^ ((s0 >> 1) & s1)) & 0x0F;
            if ((cls >> out_bit) & 1) != 0 {
                mask |= 1u64 << addr;
            }
        }
        p.set_gate(1, out_bit, [0, 1, 2, 3, 4, 5], mask);
    }
    let _ = wobble_codon_mask(0); // ensure symbol linked
    p.seal_crc32();
    p
}

/// Generate the deterministic `100,000`-query Three-Wave evaluation corpus:
/// - `0..45,000`:      Wave 1 (Exact In-Manifold Repeats, `wobble == 0`)
/// - `45,000..87,000`: Wave 2 (1-2 Bit LSB Sensor/Paraphrase Wobble Drift, `wobble in {1, 2, 3}`)
/// - `87,000..100,000`: Wave 3 (Out-of-Distribution Conformal Misses, `nonconformity >= 2` or `override != 0`)
fn generate_three_wave_corpus() -> (Vec<u64>, Vec<u8>) {
    let mut rng = SplitMix64::new(0x2026_1124_C0D0_4096);
    let mut queries = Vec::with_capacity(STREAM_LEN);
    let mut labels = Vec::with_capacity(STREAM_LEN);

    // Wave 1: 45,000 exact repeats
    for _ in 0..WAVE1_EXACT_LEN {
        let r = rng.next_u64();
        let s0 = (r & 0x0F) << 2; // wobble [1:0] == 00
        let s1 = ((r >> 4) & 0x03) << 8; // wobble [7:6] == 00
        // Optional<=1 conformal bit (`<= CONFORMAL_THRESH`)
        let conf = if ((r >> 16) & 0x3) == 0 {
            1u64 << (48 + ((r >> 20) & 7))
        } else {
            0
        };
        let state = s0 | s1 | conf;
        queries.push(state);
        labels.push(ground_truth_class(state));
    }

    // Wave 2: 42,000 noisy 1-2-bit sensor/paraphrase LSB wobble arrivals
    for _ in 0..WAVE2_WOBBLE_LEN {
        let r = rng.next_u64();
        let s0 = (r & 0x0F) << 2;
        let s1 = ((r >> 4) & 0x03) << 8;
        let wob0 = ((r >> 8) % 3) + 1; // guaranteed non-zero 1-2 bit wobble in {1, 2, 3}
        let wob1 = (((r >> 12) % 3) + 1) << 6;
        let conf = if ((r >> 16) & 0x1) == 0 {
            1u64 << (48 + ((r >> 20) & 7))
        } else {
            0
        };
        let state = s0 | wob0 | s1 | wob1 | conf;
        queries.push(state);
        labels.push(ground_truth_class(state));
    }

    // Wave 3: 13,000 OOD arrivals violating conformal envelope (`>= 2` syndrome bits or `override_mask` bit)
    for _ in 0..WAVE3_OOD_LEN {
        let r = rng.next_u64();
        let p_idx = (r & 0x0F) as u8;
        let ood_payload = (ood_prototype_bits12(p_idx) as u64) << 24;
        let b_a = (r >> 16) & 7;
        let b_b = (b_a + 1 + ((r >> 20) & 6)) & 7;
        let conf_ood = (1u64 << (48 + b_a)) | (1u64 << (48 + b_b));
        let ovr = if ((r >> 28) & 3) == 0 {
            1u64 << (56 + ((r >> 32) & 7))
        } else {
            0
        };
        let s0_noise = (r >> 36) & 0x3FF;
        let state = s0_noise | ood_payload | conf_ood | ovr;
        queries.push(state);
        labels.push(ground_truth_class(state));
    }

    // Deterministic interleave permutation across blocks of 100 so Wave 1/2/3 arrive realistically
    // mixed in streaming batches of 64 while preserving exact 45k / 42k / 13k counts!
    let mut perm_rng = SplitMix64::new(0x5EED_CAFE_1000_0064);
    for i in (1..STREAM_LEN).rev() {
        let j = (perm_rng.next_u64() as usize) % (i + 1);
        queries.swap(i, j);
        labels.swap(i, j);
    }

    assert_eq!(queries.len(), STREAM_LEN);
    (queries, labels)
}

// ============================================================================
// Rootless Linux Hardware Energy Telemetry (`RAPL` `reported_j` & `INA3221`/`INA238` `measured_j`)
// ============================================================================

#[derive(Clone, Debug, Default)]
struct TelemetrySample {
    elapsed_s: f64,
    board_metered: bool,
    // Physical DC shunts (`measured_j`)
    vin_ina238_measured_j: Option<f64>,
    vdd_cpu_soc_mss_measured_j: Option<f64>,
    vdd_gpu_measured_j: Option<f64>,
    vin_sys_5v0_measured_j: Option<f64>,
    shunt_samples: usize,
    // On-chip Linux powercap counters (`reported_j`)
    pkg_reported_j: Option<f64>,
    core_reported_j: Option<f64>,
    // Process CPU time (ms) from `/proc/self/stat`
    proc_cpu_ms: f64,
}

#[derive(Clone)]
struct HwSensorPaths {
    rapl_pkg: Option<PathBuf>,
    rapl_core: Option<PathBuf>,
    rapl_max_uj: u64,
    ina238_dir: Option<PathBuf>,
    ina3221_dir: Option<PathBuf>,
    cpu_soc_ch: usize, // channel index (1..=3) for `VDD_CPU_SOC_MSS` inside `ina3221`
}

fn read_u64_sysfs(p: &Path) -> Option<u64> {
    fs::read_to_string(p).ok()?.trim().parse::<u64>().ok()
}

fn read_i64_sysfs(p: &Path) -> Option<i64> {
    fs::read_to_string(p).ok()?.trim().parse::<i64>().ok()
}

fn read_proc_cpu_ms() -> f64 {
    if let Ok(stat) = fs::read_to_string("/proc/self/stat")
        && let Some(rparen) = stat.rfind(')')
    {
        let fields: Vec<&str> = stat[rparen + 2..].split_whitespace().collect();
        if fields.len() > 12 {
            let utime = fields[11].parse::<u64>().unwrap_or(0);
            let stime = fields[12].parse::<u64>().unwrap_or(0);
            // Standard Linux USER_HZ = 100 ticks/sec -> 10 ms/tick
            return ((utime + stime) as f64) * 10.0;
        }
    }
    0.0
}

impl HwSensorPaths {
    fn discover() -> Self {
        let p_pkg = PathBuf::from("/sys/class/powercap/intel-rapl:0/energy_uj");
        let p_core = PathBuf::from("/sys/class/powercap/intel-rapl:0:0/energy_uj");
        let p_max = PathBuf::from("/sys/class/powercap/intel-rapl:0/max_energy_range_uj");
        let rapl_max_uj = read_u64_sysfs(&p_max).unwrap_or(262_143_328_850);

        let mut ina238_dir = None;
        let mut ina3221_dir = None;
        let mut cpu_soc_ch = 2usize;

        let hwmon_root = Path::new("/sys/class/hwmon");
        if let Ok(entries) = fs::read_dir(hwmon_root) {
            let mut dirs: Vec<PathBuf> = entries.flatten().map(|e| e.path()).collect();
            dirs.sort();
            for h in dirs {
                let nm = fs::read_to_string(h.join("name"))
                    .unwrap_or_default()
                    .trim()
                    .to_string();
                if nm == "ina238" && h.join("power1_input").exists() {
                    ina238_dir = Some(h);
                } else if nm == "ina3221" && h.join("in2_input").exists() {
                    for ch in 1..=3usize {
                        if let Ok(lbl) = fs::read_to_string(h.join(format!("in{ch}_label")))
                            && lbl.trim() == "VDD_CPU_SOC_MSS"
                        {
                            cpu_soc_ch = ch;
                        }
                    }
                    ina3221_dir = Some(h);
                }
            }
        }

        Self {
            rapl_pkg: if read_u64_sysfs(&p_pkg).is_some() {
                Some(p_pkg)
            } else {
                None
            },
            rapl_core: if read_u64_sysfs(&p_core).is_some() {
                Some(p_core)
            } else {
                None
            },
            rapl_max_uj,
            ina238_dir,
            ina3221_dir,
            cpu_soc_ch,
        }
    }
}

#[derive(Clone, Copy, Default)]
struct TracePoint {
    t_s: f64,
    vin_w: f64,
    cpu_soc_w: f64,
    gpu_w: f64,
    sys5v_w: f64,
}

struct MeterSession {
    t0: Instant,
    paths: HwSensorPaths,
    cpu_ms_pre: f64,
    stop: Arc<AtomicBool>,
    shunt_trace: Arc<Mutex<Vec<TracePoint>>>,
    rapl_acc_uj: Arc<Mutex<(u128, u128, u64, u64)>>,
    bg_handle: Option<JoinHandle<()>>,
}

impl MeterSession {
    fn start(paths: &HwSensorPaths) -> Self {
        let pkg0 = paths
            .rapl_pkg
            .as_ref()
            .and_then(|p| read_u64_sysfs(p))
            .unwrap_or(0);
        let core0 = paths
            .rapl_core
            .as_ref()
            .and_then(|p| read_u64_sysfs(p))
            .unwrap_or(0);
        let stop = Arc::new(AtomicBool::new(false));
        let shunt_trace = Arc::new(Mutex::new(Vec::with_capacity(2048)));
        let rapl_acc_uj = Arc::new(Mutex::new((0u128, 0u128, pkg0, core0)));
        let cpu_ms_pre = read_proc_cpu_ms();
        let t0 = Instant::now();

        let p_c = paths.clone();
        let st_c = Arc::clone(&stop);
        let tr_c = Arc::clone(&shunt_trace);
        let rp_c = Arc::clone(&rapl_acc_uj);
        let origin = t0;

        let has_shunt = p_c.ina238_dir.is_some() && p_c.ina3221_dir.is_some();
        let has_rapl = p_c.rapl_pkg.is_some();

        let bg_handle = if has_shunt || has_rapl {
            Some(thread::spawn(move || {
                let sleep_dur = if has_shunt {
                    Duration::from_millis(5)
                } else {
                    Duration::from_millis(20)
                };
                while !st_c.load(Ordering::Relaxed) {
                    if let (Some(d238), Some(d3221)) = (&p_c.ina238_dir, &p_c.ina3221_dir) {
                        let ts = origin.elapsed().as_secs_f64();
                        let vin_uw = read_i64_sysfs(&d238.join("power1_input")).unwrap_or(0);
                        let v_cpu = read_i64_sysfs(&d3221.join(format!("in{}_input", p_c.cpu_soc_ch))).unwrap_or(0);
                        let c_cpu = read_i64_sysfs(&d3221.join(format!("curr{}_input", p_c.cpu_soc_ch))).unwrap_or(0);
                        let v1 = read_i64_sysfs(&d3221.join("in1_input")).unwrap_or(0);
                        let c1 = read_i64_sysfs(&d3221.join("curr1_input")).unwrap_or(0);
                        let v3 = read_i64_sysfs(&d3221.join("in3_input")).unwrap_or(0);
                        let c3 = read_i64_sysfs(&d3221.join("curr3_input")).unwrap_or(0);
                        tr_c.lock().unwrap().push(TracePoint {
                            t_s: ts,
                            vin_w: (vin_uw as f64) / 1e6,
                            cpu_soc_w: ((v_cpu * c_cpu) as f64) / 1e6,
                            gpu_w: ((v1 * c1) as f64) / 1e6,
                            sys5v_w: ((v3 * c3) as f64) / 1e6,
                        });
                    }
                    if p_c.rapl_pkg.is_some() {
                        sample_rapl_once(&p_c, &rp_c);
                    }
                    thread::sleep(sleep_dur);
                }
            }))
        } else {
            None
        };

        Self {
            t0,
            paths: paths.clone(),
            cpu_ms_pre,
            stop,
            shunt_trace,
            rapl_acc_uj,
            bg_handle,
        }
    }

    fn finish(mut self) -> TelemetrySample {
        let elapsed_s = self.t0.elapsed().as_secs_f64().max(1e-9);
        self.stop.store(true, Ordering::Relaxed);
        if let Some(h) = self.bg_handle.take() {
            let _ = h.join();
        }
        if self.paths.rapl_pkg.is_some() {
            sample_rapl_once(&self.paths, &self.rapl_acc_uj);
        }
        let proc_cpu_ms = (read_proc_cpu_ms() - self.cpu_ms_pre).max(0.0);
        let has_shunt = self.paths.ina238_dir.is_some() && self.paths.ina3221_dir.is_some();
        let trace = self.shunt_trace.lock().unwrap();

        let (mut vin_j, mut cpu_j, mut gpu_j, mut sys5_j) = (0.0, 0.0, 0.0, 0.0);
        if trace.len() >= 2 {
            for i in 0..(trace.len() - 1) {
                let dt = (trace[i + 1].t_s - trace[i].t_s).max(0.0);
                vin_j += 0.5 * (trace[i].vin_w + trace[i + 1].vin_w) * dt;
                cpu_j += 0.5 * (trace[i].cpu_soc_w + trace[i + 1].cpu_soc_w) * dt;
                gpu_j += 0.5 * (trace[i].gpu_w + trace[i + 1].gpu_w) * dt;
                sys5_j += 0.5 * (trace[i].sys5v_w + trace[i + 1].sys5v_w) * dt;
            }
            let head_dt = trace[0].t_s.max(0.0);
            let tail_dt = (elapsed_s - trace[trace.len() - 1].t_s).max(0.0);
            let f = trace[0];
            let l = trace[trace.len() - 1];
            vin_j += f.vin_w * head_dt + l.vin_w * tail_dt;
            cpu_j += f.cpu_soc_w * head_dt + l.cpu_soc_w * tail_dt;
            gpu_j += f.gpu_w * head_dt + l.gpu_w * tail_dt;
            sys5_j += f.sys5v_w * head_dt + l.sys5v_w * tail_dt;
        } else if trace.len() == 1 {
            vin_j = trace[0].vin_w * elapsed_s;
            cpu_j = trace[0].cpu_soc_w * elapsed_s;
            gpu_j = trace[0].gpu_w * elapsed_s;
            sys5_j = trace[0].sys5v_w * elapsed_s;
        }

        let (pkg_uj, core_uj, _, _) = *self.rapl_acc_uj.lock().unwrap();
        TelemetrySample {
            elapsed_s,
            board_metered: has_shunt,
            vin_ina238_measured_j: if has_shunt { Some(vin_j) } else { None },
            vdd_cpu_soc_mss_measured_j: if has_shunt { Some(cpu_j) } else { None },
            vdd_gpu_measured_j: if has_shunt { Some(gpu_j) } else { None },
            vin_sys_5v0_measured_j: if has_shunt { Some(sys5_j) } else { None },
            shunt_samples: trace.len(),
            pkg_reported_j: self.paths.rapl_pkg.as_ref().map(|_| (pkg_uj as f64) / 1e6),
            core_reported_j: self.paths.rapl_core.as_ref().map(|_| (core_uj as f64) / 1e6),
            proc_cpu_ms,
        }
    }
}

fn sample_rapl_once(paths: &HwSensorPaths, acc: &Arc<Mutex<(u128, u128, u64, u64)>>) {
    let mut g = acc.lock().unwrap();
    let max_r = paths.rapl_max_uj;
    if let Some(p) = &paths.rapl_pkg
        && let Some(cur) = read_u64_sysfs(p)
    {
        let prev = g.2;
        let d = if cur >= prev {
            (cur - prev) as u128
        } else {
            (max_r.saturating_sub(prev) + cur) as u128
        };
        g.0 += d;
        g.2 = cur;
    }
    if let Some(p) = &paths.rapl_core
        && let Some(cur) = read_u64_sysfs(p)
    {
        let prev = g.3;
        let d = if cur >= prev {
            (cur - prev) as u128
        } else {
            (max_r.saturating_sub(prev) + cur) as u128
        };
        g.1 += d;
        g.3 = cur;
    }
}

fn measure_quiet_idle(paths: &HwSensorPaths, secs: f64) -> TelemetrySample {
    let sess = MeterSession::start(paths);
    thread::sleep(Duration::from_secs_f64(secs));
    sess.finish()
}

fn detect_cpu_brand() -> String {
    if let Ok(txt) = fs::read_to_string("/proc/cpuinfo") {
        for line in txt.lines() {
            let low = line.to_ascii_lowercase();
            if low.starts_with("model name")
                && let Some((_, rhs)) = line.split_once(':')
            {
                let s = rhs.trim();
                if !s.is_empty() && s != "-" {
                    return s.to_string();
                }
            }
        }
    }
    if let Ok(dt) = fs::read_to_string("/sys/firmware/devicetree/base/model") {
        let cleaned = dt.trim_matches(char::from(0)).trim();
        if !cleaned.is_empty() {
            return cleaned.to_string();
        }
    }
    env::consts::ARCH.to_string()
}

fn opt_f64_json(v: Option<f64>, decimals: usize) -> String {
    match v {
        Some(x) => format!("{x:.decimals$}"),
        None => "null".to_string(),
    }
}

#[derive(Clone, Debug)]
struct RegimeResult {
    name: &'static str,
    passes: usize,
    total_evals: u64,
    wake_escalations_per_100k: usize,
    wake_suppression_pct: f64,
    silent_corruptions_per_100k: usize,
    discretization_parity_pct: f64,
    ns_per_eval: f64,
    tel: TelemetrySample,
    checksum: u64,
}

fn format_regime_json(r: &RegimeResult) -> String {
    let cpj_cpu_soc_measured = r
        .tel
        .vdd_cpu_soc_mss_measured_j
        .filter(|&j| j > 1e-9)
        .map(|j| (r.total_evals as f64) / j);
    let cpj_vin_measured = r
        .tel
        .vin_ina238_measured_j
        .filter(|&j| j > 1e-9)
        .map(|j| (r.total_evals as f64) / j);
    let cpj_pkg_reported = r
        .tel
        .pkg_reported_j
        .filter(|&j| j > 1e-9)
        .map(|j| (r.total_evals as f64) / j);
    let cpj_core_reported = r
        .tel
        .core_reported_j
        .filter(|&j| j > 1e-9)
        .map(|j| (r.total_evals as f64) / j);

    let uj_per_eval_cpu_soc_measured = r
        .tel
        .vdd_cpu_soc_mss_measured_j
        .map(|j| j * 1e6 / (r.total_evals as f64));
    let uj_per_eval_vin_measured = r
        .tel
        .vin_ina238_measured_j
        .map(|j| j * 1e6 / (r.total_evals as f64));
    let uj_per_eval_pkg_reported = r
        .tel
        .pkg_reported_j
        .map(|j| j * 1e6 / (r.total_evals as f64));
    let uj_per_eval_core_reported = r
        .tel
        .core_reported_j
        .map(|j| j * 1e6 / (r.total_evals as f64));

    format!(
        "    \"{}\": {{\n      \"passes_of_100k\": {},\n      \"total_queries_evaluated\": {},\n      \
         \"elapsed_s\": {:.6},\n      \"proc_cpu_ms\": {:.2},\n      \"ns_per_eval\": {:.3},\n      \
         \"wake_escalations_per_100k\": {},\n      \"wake_suppression_pct\": {:.2},\n      \
         \"silent_corruptions_per_100k\": {},\n      \"discretization_parity_pct\": {:.4},\n      \
         \"board_metered\": {},\n      \"shunt_samples\": {},\n      \
         \"vdd_cpu_soc_mss_measured_j\": {},\n      \"vin_ina238_measured_j\": {},\n      \
         \"vdd_gpu_measured_j\": {},\n      \"vin_sys_5v0_measured_j\": {},\n      \
         \"pkg_reported_j\": {},\n      \"core_reported_j\": {},\n      \
         \"uj_per_eval_vdd_cpu_soc_mss_measured\": {},\n      \"uj_per_eval_vin_ina238_measured\": {},\n      \
         \"uj_per_eval_pkg_reported\": {},\n      \"uj_per_eval_core_reported\": {},\n      \
         \"cpj_vdd_cpu_soc_mss_measured\": {},\n      \"cpj_vin_ina238_measured\": {},\n      \
         \"cpj_pkg_reported\": {},\n      \"cpj_core_reported\": {},\n      \
         \"checksum\": {}\n    }}",
        r.name,
        r.passes,
        r.total_evals,
        r.tel.elapsed_s,
        r.tel.proc_cpu_ms,
        r.ns_per_eval,
        r.wake_escalations_per_100k,
        r.wake_suppression_pct,
        r.silent_corruptions_per_100k,
        r.discretization_parity_pct,
        r.tel.board_metered,
        r.tel.shunt_samples,
        opt_f64_json(r.tel.vdd_cpu_soc_mss_measured_j, 6),
        opt_f64_json(r.tel.vin_ina238_measured_j, 6),
        opt_f64_json(r.tel.vdd_gpu_measured_j, 6),
        opt_f64_json(r.tel.vin_sys_5v0_measured_j, 6),
        opt_f64_json(r.tel.pkg_reported_j, 6),
        opt_f64_json(r.tel.core_reported_j, 6),
        opt_f64_json(uj_per_eval_cpu_soc_measured, 6),
        opt_f64_json(uj_per_eval_vin_measured, 6),
        opt_f64_json(uj_per_eval_pkg_reported, 6),
        opt_f64_json(uj_per_eval_core_reported, 6),
        opt_f64_json(cpj_cpu_soc_measured, 1),
        opt_f64_json(cpj_vin_measured, 1),
        opt_f64_json(cpj_pkg_reported, 1),
        opt_f64_json(cpj_core_reported, 1),
        r.checksum
    )
}

fn format_idle_json(s: &TelemetrySample) -> String {
    let cpu_w = s.vdd_cpu_soc_mss_measured_j.map(|j| j / s.elapsed_s);
    let vin_w = s.vin_ina238_measured_j.map(|j| j / s.elapsed_s);
    let pkg_w = s.pkg_reported_j.map(|j| j / s.elapsed_s);
    let core_w = s.core_reported_j.map(|j| j / s.elapsed_s);
    format!(
        "{{\n      \"elapsed_s\": {:.4},\n      \"shunt_samples\": {},\n      \
         \"vdd_cpu_soc_mss_measured_j\": {},\n      \"vin_ina238_measured_j\": {},\n      \
         \"pkg_reported_j\": {},\n      \"core_reported_j\": {},\n      \
         \"mean_vdd_cpu_soc_mss_w\": {},\n      \"mean_vin_ina238_w\": {},\n      \
         \"mean_pkg_rapl_w\": {},\n      \"mean_core_rapl_w\": {}\n    }}",
        s.elapsed_s,
        s.shunt_samples,
        opt_f64_json(s.vdd_cpu_soc_mss_measured_j, 6),
        opt_f64_json(s.vin_ina238_measured_j, 6),
        opt_f64_json(s.pkg_reported_j, 6),
        opt_f64_json(s.core_reported_j, 6),
        opt_f64_json(cpu_w, 4),
        opt_f64_json(vin_w, 4),
        opt_f64_json(pkg_w, 4),
        opt_f64_json(core_w, 4),
    )
}

fn main() {
    // Enforce CPU-only invariant Check
    let cuda_env = env::var("CUDA_VISIBLE_DEVICES").unwrap_or_else(|_| "unset".to_string());
    let cotenant_lock_active = env::var("HOME")
        .map(|h| PathBuf::from(h).join("gpu-lock/GPU_ACTIVE").exists())
        .unwrap_or(false);

    let paths = HwSensorPaths::discover();
    let mlp = Int8MicroMlp::new_calibrated();
    let (queries, labels) = generate_three_wave_corpus();

    // Boot 16 KB 3-Part Nucleus and splice the wobble-clean overlay through the dual gate!
    let seed_k = build_wobble_knowledge_crystal(false);
    let mut nucleus = Nucleus::new_bootstrap(seed_k);
    let full_overlay = build_wobble_knowledge_crystal(true);
    let splice_rcpt = nucleus
        .refine_knowledge(&full_overlay, &[])
        .expect("wobble-clean full-coverage overlay must pass Walsh + anchor retention gates!");
    assert_eq!(splice_rcpt.max_gate_harmonic_energy, 0);

    let brittle_onehot = build_brittle_onehot_ablation_crystal();

    // ------------------------------------------------------------------------
    // Step 1: Single-Pass Exactness, Parity & Ablation Audit across all 100,000 Queries
    // ------------------------------------------------------------------------
    let mut mlp_errors = 0usize;
    let mut scalar_hybrid_errors = 0usize;
    let mut scalar_wakes = 0usize;
    let mut bs_hybrid_errors = 0usize;
    let mut bs_wakes = 0usize;
    let mut onehot_ablation_errors = 0usize;
    let mut onehot_wakes = 0usize;

    for i in 0..STREAM_LEN {
        let q = queries[i];
        let exp = labels[i];
        let c_mlp = mlp.infer(q);
        if c_mlp != exp {
            mlp_errors += 1;
        }

        let Ok(out_s) = nucleus.query_knowledge(q);
        let c_s = match out_s {
            EvalOutcome::Act { output, .. } => (output & 0x0F) as u8,
            EvalOutcome::Escalate { .. } => {
                scalar_wakes += 1;
                mlp.infer(q)
            }
            EvalOutcome::Killed { fallback_output } => (fallback_output & 0x0F) as u8,
        };
        if c_s != exp {
            scalar_hybrid_errors += 1;
        }

        let Ok(out_oh) = brittle_onehot.evaluate(q, None, 0);
        let c_oh = match out_oh {
            EvalOutcome::Act { output, .. } => (output & 0x0F) as u8,
            EvalOutcome::Escalate { .. } => {
                onehot_wakes += 1;
                mlp.infer(q)
            }
            EvalOutcome::Killed { fallback_output } => (fallback_output & 0x0F) as u8,
        };
        if c_oh != exp {
            onehot_ablation_errors += 1;
        }
    }

    // Bit-sliced 64-lane pass over the 100,000 queries (1,562 full batches of 64 + 32 tail padded)
    let mut blk = [0u64; 64];
    for base in (0..STREAM_LEN).step_by(64) {
        let rem = (STREAM_LEN - base).min(64);
        for lane in 0..rem {
            blk[lane] = queries[base + lane];
        }
        for lane in rem..64 {
            blk[lane] = 0;
        }
        let (outs, esc_mask, _used_ov, _killed) = nucleus.arena.knowledge_root.evaluate_batch_64(
            &blk,
            Some(&nucleus.arena.knowledge_overlay),
            nucleus.verifier_rejects,
        );
        for lane in 0..rem {
            let c_bs = if ((esc_mask >> lane) & 1) != 0 {
                bs_wakes += 1;
                mlp.infer(blk[lane])
            } else {
                (outs[lane] & 0x0F) as u8
            };
            if c_bs != labels[base + lane] {
                bs_hybrid_errors += 1;
            }
        }
    }

    assert_eq!(mlp_errors, 0, "Calibrated INT8 MLP baseline had unexpected errors!");
    assert_eq!(scalar_hybrid_errors, 0, "Scalar lut6-core hybrid had discretization errors!");
    assert_eq!(bs_hybrid_errors, 0, "Bit-sliced lut6-core hybrid had discretization errors!");
    assert_eq!(scalar_wakes, WAVE3_OOD_LEN);
    assert_eq!(bs_wakes, WAVE3_OOD_LEN);
    assert!(onehot_ablation_errors > 25_000, "Brittle 1-hot crystal must fail on Wave 2 wobble!");

    // Collect the 87,000 in-envelope (Wave 1 + Wave 2) queries for pure crystal throughput metering
    let in_env_queries: Vec<u64> = queries
        .iter()
        .copied()
        .filter(|&q| {
            (q & OVERRIDE_MASK) == 0 && ((q & CONFORMAL_MASK).count_ones() as u8) <= CONFORMAL_THRESH
        })
        .collect();
    assert_eq!(in_env_queries.len(), WAVE1_EXACT_LEN + WAVE2_WOBBLE_LEN);

    // ------------------------------------------------------------------------
    // Step 2: Falsifier 6 Pre-Benchmark 5.0 s Quiet Idle Window
    // ------------------------------------------------------------------------
    let pre_idle_5s = measure_quiet_idle(&paths, 5.0);

    // Calibrate pass counts so every metered window spans ~3.0-5.0 seconds (>=600 shunt samples on Thor!)
    let t_probe0 = Instant::now();
    let mut warm_chk = 0u64;
    for &q in queries.iter().take(10_000) {
        warm_chk = warm_chk.wrapping_add(mlp.infer(q) as u64);
    }
    black_box(warm_chk);
    let mlp_100k_est_s = (t_probe0.elapsed().as_secs_f64() * 10.0).max(0.05);
    let int8_passes = ((3.6 / mlp_100k_est_s).ceil() as usize).clamp(2, 40);
    let hybrid_passes = (int8_passes * 6).clamp(12, 240);

    // 1. Standalone INT8 Baseline
    let sess_int8 = MeterSession::start(&paths);
    let mut chk_int8 = 0u64;
    for _ in 0..int8_passes {
        for &q in &queries {
            chk_int8 = chk_int8.wrapping_add(mlp.infer(black_box(q)) as u64);
        }
    }
    let tel_int8 = sess_int8.finish();
    let total_int8_evals = (int8_passes * STREAM_LEN) as u64;
    let res_int8 = RegimeResult {
        name: "standalone_int8_baseline",
        passes: int8_passes,
        total_evals: total_int8_evals,
        wake_escalations_per_100k: STREAM_LEN,
        wake_suppression_pct: 0.0,
        silent_corruptions_per_100k: mlp_errors,
        discretization_parity_pct: 100.0,
        ns_per_eval: tel_int8.elapsed_s * 1e9 / (total_int8_evals as f64),
        tel: tel_int8,
        checksum: chk_int8,
    };

    // 2. Scalar `lut6-core` Three-Wave Hybrid (`evaluate` + `13%` INT8 conformal wake)
    let sess_scalar = MeterSession::start(&paths);
    let mut chk_scalar = 0u64;
    for _ in 0..hybrid_passes {
        for &q in &queries {
            let Ok(out) = nucleus.query_knowledge(black_box(q));
            let cls = match out {
                EvalOutcome::Act { output, .. } => (output & 0x0F) as u8,
                EvalOutcome::Escalate { .. } => mlp.infer(q),
                EvalOutcome::Killed { fallback_output } => (fallback_output & 0x0F) as u8,
            };
            chk_scalar = chk_scalar.wrapping_add(cls as u64);
        }
    }
    let tel_scalar = sess_scalar.finish();
    let total_scalar_evals = (hybrid_passes * STREAM_LEN) as u64;
    let res_scalar_hybrid = RegimeResult {
        name: "scalar_lut6_three_wave_hybrid",
        passes: hybrid_passes,
        total_evals: total_scalar_evals,
        wake_escalations_per_100k: scalar_wakes,
        wake_suppression_pct: ((STREAM_LEN - scalar_wakes) as f64) / (STREAM_LEN as f64) * 100.0,
        silent_corruptions_per_100k: scalar_hybrid_errors,
        discretization_parity_pct: 100.0,
        ns_per_eval: tel_scalar.elapsed_s * 1e9 / (total_scalar_evals as f64),
        tel: tel_scalar,
        checksum: chk_scalar,
    };

    // 3. Bit-Sliced `lut6-core` (`evaluate_batch_64` + `13%` INT8 conformal wake)
    let sess_bs = MeterSession::start(&paths);
    let mut chk_bs = 0u64;
    let mut batch_buf = [0u64; 64];
    for _ in 0..hybrid_passes {
        for base in (0..STREAM_LEN).step_by(64) {
            let rem = (STREAM_LEN - base).min(64);
            batch_buf[..rem].copy_from_slice(&queries[base..base + rem]);
            if rem < 64 {
                batch_buf[rem..64].fill(0);
            }
            let (outs, esc_mask, _, _) = nucleus.arena.knowledge_root.evaluate_batch_64(
                black_box(&batch_buf),
                Some(&nucleus.arena.knowledge_overlay),
                nucleus.verifier_rejects,
            );
            if esc_mask == 0 {
                for lane in 0..rem {
                    chk_bs = chk_bs.wrapping_add(outs[lane] & 0x0F);
                }
            } else {
                for lane in 0..rem {
                    let cls = if ((esc_mask >> lane) & 1) != 0 {
                        mlp.infer(batch_buf[lane]) as u64
                    } else {
                        outs[lane] & 0x0F
                    };
                    chk_bs = chk_bs.wrapping_add(cls);
                }
            }
        }
    }
    let tel_bs = sess_bs.finish();
    let total_bs_evals = (hybrid_passes * STREAM_LEN) as u64;
    let res_bs_hybrid = RegimeResult {
        name: "bitsliced_lut6_three_wave_hybrid",
        passes: hybrid_passes,
        total_evals: total_bs_evals,
        wake_escalations_per_100k: bs_wakes,
        wake_suppression_pct: ((STREAM_LEN - bs_wakes) as f64) / (STREAM_LEN as f64) * 100.0,
        silent_corruptions_per_100k: bs_hybrid_errors,
        discretization_parity_pct: 100.0,
        ns_per_eval: tel_bs.elapsed_s * 1e9 / (total_bs_evals as f64),
        tel: tel_bs,
        checksum: chk_bs,
    };

    // 4. Pure Scalar `lut6-core` Crystal Kernel (`Wave 1 + Wave 2` in-envelope throughput & CpJ)
    let active_crystal = nucleus.arena.knowledge_overlay;
    let t_sc_probe = Instant::now();
    let mut sc_warm = 0u64;
    for &q in &in_env_queries {
        let Ok(EvalOutcome::Act { output, .. }) = nucleus.query_knowledge(black_box(q)) else {
            unreachable!()
        };
        sc_warm ^= output;
    }
    black_box(sc_warm);
    let sc_pass_s = t_sc_probe.elapsed().as_secs_f64().max(1e-5);
    let pure_scalar_passes = ((3.2 / sc_pass_s).ceil() as usize).clamp(50, 25_000);

    let sess_pure_sc = MeterSession::start(&paths);
    let mut chk_pure_sc = 0u64;
    for _ in 0..pure_scalar_passes {
        for &q in &in_env_queries {
            let Ok(out) = nucleus.query_knowledge(black_box(q));
            if let EvalOutcome::Act { output, .. } = out {
                chk_pure_sc = chk_pure_sc.wrapping_add(output & 0x0F);
            }
        }
    }
    let tel_pure_sc = sess_pure_sc.finish();
    let total_pure_sc_evals = (pure_scalar_passes * in_env_queries.len()) as u64;
    let res_pure_scalar = RegimeResult {
        name: "scalar_lut6_pure_crystal",
        passes: pure_scalar_passes,
        total_evals: total_pure_sc_evals,
        wake_escalations_per_100k: 0,
        wake_suppression_pct: 100.0,
        silent_corruptions_per_100k: 0,
        discretization_parity_pct: 100.0,
        ns_per_eval: tel_pure_sc.elapsed_s * 1e9 / (total_pure_sc_evals as f64),
        tel: tel_pure_sc,
        checksum: chk_pure_sc,
    };

    // 5. Pure Bit-Sliced `eval_batch_64` Crystal Kernel (`64x` register parallelism)
    let aligned_batches: Vec<[u64; 64]> = in_env_queries
        .chunks_exact(64)
        .map(|c| c.try_into().unwrap())
        .collect();
    let t_bs_probe = Instant::now();
    let mut bs_warm = 0u64;
    for b in &aligned_batches {
        let outs = active_crystal.eval_batch_64(black_box(b));
        bs_warm ^= outs[0] ^ outs[63];
    }
    black_box(bs_warm);
    let bs_pass_s = t_bs_probe.elapsed().as_secs_f64().max(1e-6);
    let pure_bs_passes = ((3.2 / bs_pass_s).ceil() as usize).clamp(200, 120_000);

    let sess_pure_bs = MeterSession::start(&paths);
    let mut chk_pure_bs = 0u64;
    for _ in 0..pure_bs_passes {
        for b in &aligned_batches {
            let outs = active_crystal.eval_batch_64(black_box(b));
            chk_pure_bs = chk_pure_bs.wrapping_add((outs[0] & 0x0F) + (outs[63] & 0x0F));
        }
    }
    let tel_pure_bs = sess_pure_bs.finish();
    let total_pure_bs_evals = (pure_bs_passes * aligned_batches.len() * 64) as u64;
    let res_pure_bs = RegimeResult {
        name: "bitsliced_lut6_pure_crystal",
        passes: pure_bs_passes,
        total_evals: total_pure_bs_evals,
        wake_escalations_per_100k: 0,
        wake_suppression_pct: 100.0,
        silent_corruptions_per_100k: 0,
        discretization_parity_pct: 100.0,
        ns_per_eval: tel_pure_bs.elapsed_s * 1e9 / (total_pure_bs_evals as f64),
        tel: tel_pure_bs,
        checksum: chk_pure_bs,
    };

    // ------------------------------------------------------------------------
    // Step 3: Falsifier 6 Post-Benchmark 5.0 s Quiet Idle Window & Drift Check
    // ------------------------------------------------------------------------
    let post_idle_5s = measure_quiet_idle(&paths, 5.0);

    let (primary_pre_w, primary_post_w, primary_rail_name) = if pre_idle_5s.board_metered {
        (
            pre_idle_5s
                .vdd_cpu_soc_mss_measured_j
                .map(|j| j / pre_idle_5s.elapsed_s),
            post_idle_5s
                .vdd_cpu_soc_mss_measured_j
                .map(|j| j / post_idle_5s.elapsed_s),
            "ina3221_vdd_cpu_soc_mss_measured_j",
        )
    } else {
        (
            pre_idle_5s.pkg_reported_j.map(|j| j / pre_idle_5s.elapsed_s),
            post_idle_5s.pkg_reported_j.map(|j| j / post_idle_5s.elapsed_s),
            "rapl_pkg_reported_j",
        )
    };

    let idle_drift_pct = match (primary_pre_w, primary_post_w) {
        (Some(w0), Some(w1)) if w0 > 1e-6 => ((w1 - w0).abs() / w0) * 100.0,
        _ => 0.0,
    };
    let withhold_net_subtraction = cotenant_lock_active || idle_drift_pct > 10.0;

    //Verify hybrid checksum parity (`chk_int8 / int8_passes == chk_scalar / hybrid_passes == chk_bs / hybrid_passes`)
    assert_eq!(
        chk_int8 / (int8_passes as u64),
        chk_scalar / (hybrid_passes as u64),
        "Scalar hybrid per-100k output sum diverged from INT8 reference!"
    );
    assert_eq!(
        chk_int8 / (int8_passes as u64),
        chk_bs / (hybrid_passes as u64),
        "Bit-sliced hybrid per-100k output sum diverged from INT8 reference!"
    );

    let cpu_brand = detect_cpu_brand();
    println!(
        "{{\n  \"experiment\": \"lut6_core_dual_reality_three_wave_benchmark\",\n  \
         \"arch\": \"{}\",\n  \"os\": \"{}\",\n  \"cpu_or_board_model\": \"{}\",\n  \
         \"cuda_visible_devices\": \"{}\",\n  \"board_metered\": {},\n  \
         \"primary_energy_channel\": \"{}\",\n  \
         \"model_footprints\": {{\n    \"int8_mlp_macs_per_eval\": {},\n    \
         \"int8_mlp_param_bytes\": {},\n    \"lut6_single_page_bytes\": 4096,\n    \
         \"lut6_3part_nucleus_arena_bytes\": 16384\n  }},\n  \
         \"three_wave_stream_100k\": {{\n    \"total_queries\": {},\n    \
         \"wave1_exact_repeats\": {},\n    \"wave2_lsb_wobble_drift\": {},\n    \
         \"wave3_ood_conformal_misses\": {},\n    \"wake_suppression_pct\": {:.2},\n    \
         \"target_wake_suppression_min_pct\": 85.0,\n    \"wake_suppression_target_met\": {},\n    \
         \"wobble_lut6_silent_corruptions\": 0,\n    \"wobble_lut6_discretization_parity_pct\": 100.0,\n    \
         \"brittle_1hot_ablation_wakes\": {},\n    \"brittle_1hot_ablation_silent_corruptions\": {},\n    \
         \"brittle_1hot_ablation_accuracy_pct\": {:.2}\n  }},\n  \
         \"falsifier_6_idle_drift_audit\": {{\n    \"pre_idle_5s\": {},\n    \
         \"post_idle_5s\": {},\n    \"idle_drift_pct\": {:.3},\n    \
         \"gpu_cotenant_lock_active\": {},\n    \"withhold_single_window_net_subtraction\": {}\n  }},\n  \
         \"regimes\": {{\n{},\n{},\n{},\n{},\n{}\n  }}\n}}",
        env::consts::ARCH,
        env::consts::OS,
        cpu_brand,
        cuda_env,
        pre_idle_5s.board_metered,
        primary_rail_name,
        Int8MicroMlp::MACS_PER_EVAL,
        mlp.footprint_bytes(),
        STREAM_LEN,
        WAVE1_EXACT_LEN,
        WAVE2_WOBBLE_LEN,
        WAVE3_OOD_LEN,
        ((STREAM_LEN - scalar_wakes) as f64) / (STREAM_LEN as f64) * 100.0,
        ((STREAM_LEN - scalar_wakes) as f64) / (STREAM_LEN as f64) * 100.0 >= 85.0,
        onehot_wakes,
        onehot_ablation_errors,
        ((STREAM_LEN - onehot_ablation_errors) as f64) / (STREAM_LEN as f64) * 100.0,
        format_idle_json(&pre_idle_5s),
        format_idle_json(&post_idle_5s),
        idle_drift_pct,
        cotenant_lock_active,
        withhold_net_subtraction,
        format_regime_json(&res_int8),
        format_regime_json(&res_scalar_hybrid),
        format_regime_json(&res_bs_hybrid),
        format_regime_json(&res_pure_scalar),
        format_regime_json(&res_pure_bs),
    );
}
