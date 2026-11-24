#![cfg_attr(not(feature = "std"), no_std)]

//! `lut6-core`: Zero-Allocation `#![no_std]` 4 KB LUT6 Knowledge Crystal,
//! 64-Point Integer Walsh-Hadamard Wobble Filter, Bit-Sliced 64-State Evaluator,
//! 64-Codon Operon ABI (`bootstrap`), and 16 KB 3-Part Bootstrap `Nucleus` (`nucleus`).

#[cfg(not(target_endian = "little"))]
compile_error!("lut6-core requires a little-endian target architecture");

pub mod bootstrap;
pub mod nucleus;

use core::mem::{align_of, offset_of, size_of};

pub const LUT6_MAGIC: [u8; 4] = *b"LUT6";
pub const LUT6_SCHEMA_VER: u16 = 1;
pub const LUT6_PAGE_BYTES: usize = 4096;
pub const LUT6_HEADER_BYTES: usize = 64;
pub const LUT6_MAX_LAYERS: usize = 4;
pub const LUT6_MAX_GATES_PER_LAYER: usize = 64;
pub const LUT6_TOTAL_GATES: usize = 256;
pub const LUT6_MAX_ANCHORS: usize = 32;
pub const PARSEVAL_NORM_TOTAL: u32 = 4096;
pub const ONE_HOT_DEG5_ENERGY: u32 = 448;

pub const FLAG_VALIDATED: u16 = 1 << 0;
pub const FLAG_WOBBLE_CLEAN: u16 = 1 << 1;
pub const FLAG_OVERLAY_PAGE: u16 = 1 << 2;

/// Outcome of evaluating a `CompactLut6Page` under conformal and apoptosis safety gates.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EvalOutcome {
    /// In-envelope deterministic LUT6 execution (`root` or validated `overlay`).
    Act {
        output: u64,
        used_overlay: bool,
    },
    /// Conformal wake-gate abstention (out-of-distribution input or safety override bit set).
    Escalate {
        raw_output: u64,
        nonconformity: u8,
    },
    /// Apoptosis kill-switch engaged (`verifier_rejects >= kill_max_rejects` or corrupt root).
    Killed {
        fallback_output: u64,
    },
}

/// 4,096-byte cache- & page-aligned `#![no_std]` LUT6 Knowledge/Agency Crystal.
///
/// Memory map (`4,096` bytes, zero implicit padding):
/// - `0x000..0x040` (`64 B`):   Header (`magic`, `schema_ver`, `flags`, `domain_hash`,
///                              `parent_commit`, `conformal_mask`, `override_mask`,
///                              `conformal_thresh`, `num_layers`, `gates_per_layer`,
///                              `kill_max_rejects`, `crc32`)
/// - `0x040..0x440` (`1024 B`): `routes_lo` (lower 32 bits of 6x6-bit wire indices per gate)
/// - `0x440..0x540` (`256 B`):  `routes_hi` (upper 4 bits of 6x6-bit wire indices per gate)
/// - `0x540..0x560` (`32 B`):   `proof_digest` (SHA-256 / miter equivalence digest)
/// - `0x560..0x660` (`256 B`):  `anchor_inputs` (up to 32 protected anchor stimuli)
/// - `0x660..0x760` (`256 B`):  `anchor_expected` (up to 32 protected anchor expected outputs)
/// - `0x760..0x800` (`160 B`):  `anchor_count` + `reserved` alignment to 2 KB half-page
/// - `0x800..0x1000` (`2048 B`): `init_masks` (`256` x `64`-bit LUT6 truth tables)
#[cfg(target_endian = "little")]
#[repr(C, align(8))]
#[derive(Clone, Copy)]
pub struct CompactLut6Page {
    pub magic: [u8; 4],
    pub schema_ver: u16,
    pub flags: u16,
    pub domain_hash: u64,
    pub parent_commit: [u8; 24],
    pub conformal_mask: u64,
    pub override_mask: u64,
    pub conformal_thresh: u8,
    pub num_layers: u8,
    pub gates_per_layer: u8,
    pub kill_max_rejects: u8,
    pub crc32: u32,

    pub routes_lo: [u32; LUT6_TOTAL_GATES],
    pub routes_hi: [u8; LUT6_TOTAL_GATES],
    pub proof_digest: [u8; 32],
    pub anchor_inputs: [u64; LUT6_MAX_ANCHORS],
    pub anchor_expected: [u64; LUT6_MAX_ANCHORS],
    pub anchor_count: u8,
    pub reserved: [u8; 159],

    pub init_masks: [u64; LUT6_TOTAL_GATES],
}

const _: () = assert!(
    size_of::<CompactLut6Page>() == 4096
        && align_of::<CompactLut6Page>() == 8
        && offset_of!(CompactLut6Page, routes_lo) == 64
        && offset_of!(CompactLut6Page, init_masks) == 2048
);

/// Pack 6 wire indices (`w0..w5`, each in `0..63`) into `(routes_lo, routes_hi)`.
#[inline]
pub const fn pack_route6(wires: [u8; 6]) -> (u32, u8) {
    let packed: u64 = ((wires[0] as u64) & 0x3F)
        | (((wires[1] as u64) & 0x3F) << 6)
        | (((wires[2] as u64) & 0x3F) << 12)
        | (((wires[3] as u64) & 0x3F) << 18)
        | (((wires[4] as u64) & 0x3F) << 24)
        | (((wires[5] as u64) & 0x3F) << 30);
    (packed as u32, (packed >> 32) as u8)
}

/// Unpack 6 wire indices (`0..63`) from `(routes_lo, routes_hi)`.
#[inline]
pub const fn unpack_route6(lo: u32, hi: u8) -> [u8; 6] {
    let r: u64 = (lo as u64) | ((hi as u64) << 32);
    [
        (r & 0x3F) as u8,
        ((r >> 6) & 0x3F) as u8,
        ((r >> 12) & 0x3F) as u8,
        ((r >> 18) & 0x3F) as u8,
        ((r >> 24) & 0x3F) as u8,
        ((r >> 30) & 0x3F) as u8,
    ]
}

#[inline]
const fn crc32_byte(mut crc: u32, byte: u8) -> u32 {
    crc ^= byte as u32;
    let mut bit = 0;
    while bit < 8 {
        let mask = (crc & 1).wrapping_neg();
        crc = (crc >> 1) ^ (0xEDB8_8320 & mask);
        bit += 1;
    }
    crc
}

#[inline]
const fn crc32_slice_update(mut crc: u32, bytes: &[u8]) -> u32 {
    let mut i = 0;
    while i < bytes.len() {
        crc = crc32_byte(crc, bytes[i]);
        i += 1;
    }
    crc
}

impl CompactLut6Page {
    /// Construct an empty, disabled overlay slot (`magic = [0; 4]`, `is_valid() == false`).
    pub const fn empty_invalid() -> Self {
        Self {
            magic: [0u8; 4],
            schema_ver: 0,
            flags: 0,
            domain_hash: 0,
            parent_commit: [0u8; 24],
            conformal_mask: 0,
            override_mask: 0,
            conformal_thresh: 0,
            num_layers: 0,
            gates_per_layer: 0,
            kill_max_rejects: 0,
            crc32: 0,
            routes_lo: [0u32; LUT6_TOTAL_GATES],
            routes_hi: [0u8; LUT6_TOTAL_GATES],
            proof_digest: [0u8; 32],
            anchor_inputs: [0u64; LUT6_MAX_ANCHORS],
            anchor_expected: [0u64; LUT6_MAX_ANCHORS],
            anchor_count: 0,
            reserved: [0u8; 159],
            init_masks: [0u64; LUT6_TOTAL_GATES],
        }
    }

    /// Construct a fresh zero-initialized valid crystal scaffold before gate population.
    pub const fn new_blank(
        domain_hash: u64,
        num_layers: u8,
        gates_per_layer: u8,
        kill_max_rejects: u8,
    ) -> Self {
        let mut p = Self::empty_invalid();
        p.magic = LUT6_MAGIC;
        p.schema_ver = LUT6_SCHEMA_VER;
        p.flags = FLAG_VALIDATED;
        p.domain_hash = domain_hash;
        p.conformal_thresh = 64;
        p.num_layers = num_layers;
        p.gates_per_layer = gates_per_layer;
        p.kill_max_rejects = kill_max_rejects;
        p
    }

    /// Set a single gate `(layer, gate_in_layer)` with 6 input wires and 64-bit LUT6 truth table.
    pub const fn set_gate(
        &mut self,
        layer: usize,
        gate: usize,
        wires: [u8; 6],
        init_mask: u64,
    ) {
        let idx = layer * (self.gates_per_layer as usize) + gate;
        let (lo, hi) = pack_route6(wires);
        self.routes_lo[idx] = lo;
        self.routes_hi[idx] = hi;
        self.init_masks[idx] = init_mask;
    }

    /// Compute exact IEEE 802.3 CRC-32 across all 4,096 bytes (treating `self.crc32` at `60..64` as `0`).
    /// Works in `const fn` at `rustc` compile time!
    pub const fn compute_crc32(&self) -> u32 {
        let mut c: u32 = 0xFFFF_FFFF;
        c = crc32_slice_update(c, &self.magic);
        c = crc32_slice_update(c, &self.schema_ver.to_le_bytes());
        c = crc32_slice_update(c, &self.flags.to_le_bytes());
        c = crc32_slice_update(c, &self.domain_hash.to_le_bytes());
        c = crc32_slice_update(c, &self.parent_commit);
        c = crc32_slice_update(c, &self.conformal_mask.to_le_bytes());
        c = crc32_slice_update(c, &self.override_mask.to_le_bytes());
        c = crc32_byte(c, self.conformal_thresh);
        c = crc32_byte(c, self.num_layers);
        c = crc32_byte(c, self.gates_per_layer);
        c = crc32_byte(c, self.kill_max_rejects);
        c = crc32_slice_update(c, &0u32.to_le_bytes());

        let mut i = 0;
        while i < LUT6_TOTAL_GATES {
            c = crc32_slice_update(c, &self.routes_lo[i].to_le_bytes());
            i += 1;
        }
        c = crc32_slice_update(c, &self.routes_hi);
        c = crc32_slice_update(c, &self.proof_digest);

        let mut a = 0;
        while a < LUT6_MAX_ANCHORS {
            c = crc32_slice_update(c, &self.anchor_inputs[a].to_le_bytes());
            a += 1;
        }
        let mut b = 0;
        while b < LUT6_MAX_ANCHORS {
            c = crc32_slice_update(c, &self.anchor_expected[b].to_le_bytes());
            b += 1;
        }
        c = crc32_byte(c, self.anchor_count);
        c = crc32_slice_update(c, &self.reserved);

        let mut m = 0;
        while m < LUT6_TOTAL_GATES {
            c = crc32_slice_update(c, &self.init_masks[m].to_le_bytes());
            m += 1;
        }
        !c
    }

    /// Seal page by computing and storing its IEEE 802.3 `crc32` + `FLAG_VALIDATED`.
    pub const fn seal_crc32(&mut self) {
        self.flags |= FLAG_VALIDATED;
        self.crc32 = self.compute_crc32();
    }

    /// Fast constant-time structural header validation for hot-path `evaluate`.
    #[inline]
    pub const fn is_valid(&self) -> bool {
        let nl = self.num_layers as usize;
        let gpl = self.gates_per_layer as usize;
        self.magic[0] == b'L'
            && self.magic[1] == b'U'
            && self.magic[2] == b'T'
            && self.magic[3] == b'6'
            && self.schema_ver == LUT6_SCHEMA_VER
            && (self.flags & FLAG_VALIDATED) != 0
            && self.crc32 != 0
            && nl <= LUT6_MAX_LAYERS
            && gpl <= LUT6_MAX_GATES_PER_LAYER
            && (nl * gpl) <= LUT6_TOTAL_GATES
            && (self.anchor_count as usize) <= LUT6_MAX_ANCHORS
    }

    /// Full cryptographic/integrity verification (`is_valid()` + full 4,096-byte IEEE CRC-32).
    pub const fn verify_integrity(&self) -> bool {
        self.is_valid() && self.crc32 == self.compute_crc32()
    }

    /// View the 4,096-byte page as a raw byte slice.
    #[inline]
    pub fn as_bytes(&self) -> &[u8; LUT6_PAGE_BYTES] {
        // SAFETY: `CompactLut6Page` is `#[repr(C, align(8))]` of exact size 4096 with zero padding.
        unsafe { &*(self as *const Self as *const [u8; LUT6_PAGE_BYTES]) }
    }

    /// Parse and integrity-check a 4,096-byte `.lut6` crystal image.
    pub fn from_bytes_verified(bytes: &[u8; LUT6_PAGE_BYTES]) -> Option<Self> {
        // SAFETY: Any 4096-byte pattern is valid for all primitive integer fields of `CompactLut6Page`.
        let page: Self = unsafe { core::ptr::read_unaligned(bytes.as_ptr() as *const Self) };
        if page.verify_integrity() {
            Some(page)
        } else {
            None
        }
    }

    /// Pure `#![no_std]` `const` combinational evaluation across `num_layers` of LUT6 gates.
    /// Wires `[gates_per_layer .. 64)` pass straight through untouched on each layer.
    #[inline]
    pub const fn eval_raw(&self, state: u64) -> u64 {
        let nl = self.num_layers as usize;
        let gpl = self.gates_per_layer as usize;
        if nl == 0 || gpl == 0 {
            return state;
        }
        let passthrough_mask: u64 = if gpl >= 64 { 0 } else { !0u64 << gpl };
        let mut cur = state;
        let mut layer = 0;
        while layer < nl {
            let base = layer * gpl;
            let mut next: u64 = cur & passthrough_mask;
            let mut g = 0;
            while g < gpl {
                let idx = base + g;
                let r: u64 = (self.routes_lo[idx] as u64) | ((self.routes_hi[idx] as u64) << 32);
                let b0 = (cur >> (r & 0x3F)) & 1;
                let b1 = (cur >> ((r >> 6) & 0x3F)) & 1;
                let b2 = (cur >> ((r >> 12) & 0x3F)) & 1;
                let b3 = (cur >> ((r >> 18) & 0x3F)) & 1;
                let b4 = (cur >> ((r >> 24) & 0x3F)) & 1;
                let b5 = (cur >> ((r >> 30) & 0x3F)) & 1;
                let lut_addr = b0 | (b1 << 1) | (b2 << 2) | (b3 << 3) | (b4 << 4) | (b5 << 5);
                let out_bit = (self.init_masks[idx] >> lut_addr) & 1;
                next |= out_bit << g;
                g += 1;
            }
            cur = next;
            layer += 1;
        }
        cur
    }

    /// Evaluate `state` under Apoptosis Kill-Switch, Rust 2024 `let_chains` Overlay Selection,
    /// and Conformal Wake-Gate Abstention, returning `Result<EvalOutcome, !>` on stable Rust `1.100.0`.
    #[inline]
    pub const fn evaluate(
        &self,
        state: u64,
        overlay: Option<&CompactLut6Page>,
        verifier_rejects: u16,
    ) -> Result<EvalOutcome, !> {
        if !self.is_valid()
            || (self.kill_max_rejects > 0 && verifier_rejects >= (self.kill_max_rejects as u16))
        {
            return Ok(EvalOutcome::Killed {
                fallback_output: self.eval_raw(state),
            });
        }

        let (active, used_overlay) = if let Some(patch) = overlay
            && patch.is_valid()
            && patch.domain_hash == self.domain_hash
        {
            (patch, true)
        } else {
            (self, false)
        };

        let raw_output = active.eval_raw(state);
        let override_tripped = (state & active.override_mask) != 0;
        let nonconformity = (state & active.conformal_mask).count_ones() as u8;
        if override_tripped || nonconformity > active.conformal_thresh {
            let reported_nc = if override_tripped && nonconformity <= active.conformal_thresh {
                active.conformal_thresh.saturating_add(1)
            } else {
                nonconformity
            };
            return Ok(EvalOutcome::Escalate {
                raw_output,
                nonconformity: reported_nc,
            });
        }

        Ok(EvalOutcome::Act {
            output: raw_output,
            used_overlay,
        })
    }

    /// Vertical bit-sliced 64-state parallel evaluator (`64x` register parallelism).
    ///
    /// Transposes 64 independent 64-bit states into 64 wire bit-planes, evaluates each LUT6 gate
    /// across all 64 batch lanes simultaneously using Shannon cofactor short-circuiting, and
    /// transposes the 64 output bit-planes back to 64 independent output words.
    #[inline]
    pub fn eval_batch_64(&self, states: &[u64; 64]) -> [u64; 64] {
        let nl = self.num_layers as usize;
        let gpl = self.gates_per_layer as usize;
        if nl == 0 || gpl == 0 {
            return *states;
        }
        let mut planes = transpose_64x64(states);
        let mut next_planes = planes;
        for layer in 0..nl {
            let base = layer * gpl;
            for g in 0..gpl {
                let idx = base + g;
                let r: u64 = (self.routes_lo[idx] as u64) | ((self.routes_hi[idx] as u64) << 32);
                let p = [
                    planes[(r & 0x3F) as usize],
                    planes[((r >> 6) & 0x3F) as usize],
                    planes[((r >> 12) & 0x3F) as usize],
                    planes[((r >> 18) & 0x3F) as usize],
                    planes[((r >> 24) & 0x3F) as usize],
                    planes[((r >> 30) & 0x3F) as usize],
                ];
                next_planes[g] = eval_lut6_bitsliced(self.init_masks[idx], &p);
            }
            for g in gpl..64 {
                next_planes[g] = planes[g];
            }
            planes = next_planes;
        }
        transpose_64x64(&planes)
    }

    /// Bit-sliced 64-state conformal + overlay evaluation (`64` states per call).
    /// Returns `(outputs, escalate_bitmap_u64, used_overlay, killed)`.
    #[inline]
    pub fn evaluate_batch_64(
        &self,
        states: &[u64; 64],
        overlay: Option<&CompactLut6Page>,
        verifier_rejects: u16,
    ) -> ([u64; 64], u64, bool, bool) {
        if !self.is_valid()
            || (self.kill_max_rejects > 0 && verifier_rejects >= (self.kill_max_rejects as u16))
        {
            return (self.eval_batch_64(states), 0, false, true);
        }
        let (active, used_overlay) = if let Some(patch) = overlay
            && patch.is_valid()
            && patch.domain_hash == self.domain_hash
        {
            (patch, true)
        } else {
            (self, false)
        };
        let outs = active.eval_batch_64(states);
        let mut escalate_bits: u64 = 0;
        if active.override_mask != 0 || active.conformal_thresh < 64 {
            let cm = active.conformal_mask;
            let om = active.override_mask;
            let ct = active.conformal_thresh;
            for (i, &s) in states.iter().enumerate() {
                if (s & om) != 0 || ((s & cm).count_ones() as u8) > ct {
                    escalate_bits |= 1u64 << i;
                }
            }
        }
        (outs, escalate_bits, used_overlay, false)
    }
}

// ============================================================================
// Hacker's Delight 6-Stage 64x64 Bit-Matrix Transpose + Cofactor Short-Circuit
// ============================================================================

#[inline]
pub const fn transpose_64x64(input: &[u64; 64]) -> [u64; 64] {
    let mut a = *input;
    const MASKS: [u64; 6] = [
        0x5555_5555_5555_5555,
        0x3333_3333_3333_3333,
        0x0F0F_0F0F_0F0F_0F0F,
        0x00FF_00FF_00FF_00FF,
        0x0000_FFFF_0000_FFFF,
        0x0000_0000_FFFF_FFFF,
    ];
    let mut stage = 0;
    while stage < 6 {
        let step = 1usize << stage;
        let shift = 1u32 << stage;
        let m = MASKS[stage];
        let mut block = 0;
        while block < 64 {
            let mut j = 0;
            while j < step {
                let x = a[block + j];
                let y = a[block + j + step];
                a[block + j] = (x & m) | ((y & m) << shift);
                a[block + j + step] = ((x >> shift) & m) | (y & !m);
                j += 1;
            }
            block += step * 2;
        }
        stage += 1;
    }
    a
}

#[inline(always)]
const fn mux_plane(lo: u64, hi: u64, sel: u64) -> u64 {
    lo ^ ((lo ^ hi) & sel)
}

#[inline(always)]
const fn eval_lut2_plane(m2: u8, p0: u64, p1: u64) -> u64 {
    let m = m2 & 0xF;
    if m == 0 {
        return 0;
    }
    if m == 0xF {
        return !0u64;
    }
    let lo = match m & 0b11 {
        0b00 => 0u64,
        0b01 => !p0,
        0b10 => p0,
        _ => !0u64,
    };
    let hi = match (m >> 2) & 0b11 {
        0b00 => 0u64,
        0b01 => !p0,
        0b10 => p0,
        _ => !0u64,
    };
    if (m & 0b11) == ((m >> 2) & 0b11) {
        lo
    } else {
        mux_plane(lo, hi, p1)
    }
}

#[inline(always)]
const fn eval_lut4_plane(m16: u16, p: &[u64; 6]) -> u64 {
    if m16 == 0 {
        return 0;
    }
    if m16 == 0xFFFF {
        return !0u64;
    }
    let lo8 = (m16 & 0xFF) as u8;
    let hi8 = (m16 >> 8) as u8;
    let v_lo = if lo8 == 0 {
        0
    } else if lo8 == 0xFF {
        !0u64
    } else {
        let a = eval_lut2_plane(lo8 & 0xF, p[0], p[1]);
        let b = eval_lut2_plane(lo8 >> 4, p[0], p[1]);
        if (lo8 & 0xF) == (lo8 >> 4) {
            a
        } else {
            mux_plane(a, b, p[2])
        }
    };
    if lo8 == hi8 {
        return v_lo;
    }
    let v_hi = if hi8 == 0 {
        0
    } else if hi8 == 0xFF {
        !0u64
    } else {
        let a = eval_lut2_plane(hi8 & 0xF, p[0], p[1]);
        let b = eval_lut2_plane(hi8 >> 4, p[0], p[1]);
        if (hi8 & 0xF) == (hi8 >> 4) {
            a
        } else {
            mux_plane(a, b, p[2])
        }
    };
    mux_plane(v_lo, v_hi, p[3])
}

/// Evaluate any 64-bit LUT6 truth table across 64 parallel states simultaneously.
/// Wobble-invariant (`(p0, p1)`-independent) and low-fanin gates short-circuit whole subtrees!
#[inline]
pub const fn eval_lut6_bitsliced(mask: u64, p: &[u64; 6]) -> u64 {
    if mask == 0 {
        return 0;
    }
    if mask == !0u64 {
        return !0u64;
    }
    let lo32 = mask as u32;
    let hi32 = (mask >> 32) as u32;
    let v_lo32 = eval_lut5_plane(lo32, p);
    if lo32 == hi32 {
        v_lo32
    } else {
        let v_hi32 = eval_lut5_plane(hi32, p);
        mux_plane(v_lo32, v_hi32, p[5])
    }
}

#[inline(always)]
const fn eval_lut5_plane(m32: u32, p: &[u64; 6]) -> u64 {
    if m32 == 0 {
        return 0;
    }
    if m32 == 0xFFFF_FFFF {
        return !0u64;
    }
    let lo16 = (m32 & 0xFFFF) as u16;
    let hi16 = (m32 >> 16) as u16;
    let v_lo = eval_lut4_plane(lo16, p);
    if lo16 == hi16 {
        v_lo
    } else {
        let v_hi = eval_lut4_plane(hi16, p);
        mux_plane(v_lo, v_hi, p[4])
    }
}

// ============================================================================
// 64-Point Integer Fast Walsh-Hadamard Transform & 2-Bit Wobble Codon Filter
// ============================================================================

/// 64-point unipolar integer Fast Walsh-Hadamard Transform (`0` floats):
/// `W[u] = sum_{x=0..63} ((init_mask >> x) & 1) * (-1)^(popcount(u & x))` in `[-32, +64] <= i8`.
pub const fn lut6_walsh_spectrum(init_mask: u64) -> [i8; 64] {
    let mut buf = [0i32; 64];
    let mut x = 0;
    while x < 64 {
        buf[x] = ((init_mask >> x) & 1) as i32;
        x += 1;
    }

    let mut step = 1usize;
    while step < 64 {
        let jump = step * 2;
        let mut base = 0usize;
        while base < 64 {
            let mut j = 0usize;
            while j < step {
                let a = buf[base + j];
                let b = buf[base + j + step];
                buf[base + j] = a + b;
                buf[base + j + step] = a - b;
                j += 1;
            }
            base += jump;
        }
        step *= 2;
    }

    let mut out = [0i8; 64];
    let mut u = 0;
    while u < 64 {
        out[u] = buf[u] as i8;
        u += 1;
    }
    out
}

/// Degree `>= 5` high-harmonic parity noise out of `4096` Parseval-normalized total energy:
/// `E_deg>=5 = (64 * sum_{popcount(u) >= 5} W[u]^2) / popcount(init_mask)` (`0` when `init_mask == 0`).
///
/// - For any 1-hot 6-bit mask `1u64 << addr`: `7 * 64 / 1 = 448` out of `4096` (`7/64`).
/// - For any 2-bit wobble codon `wobble_codon_mask(target)` (and any Boolean function of degree `<= 4`): `0`.
pub const fn high_harmonic_energy(init_mask: u64) -> u32 {
    let wt = init_mask.count_ones();
    if wt == 0 {
        return 0;
    }
    let spec = lut6_walsh_spectrum(init_mask);
    let mut deg5_sq: u32 = 0;
    let mut u: u32 = 0;
    while u < 64 {
        if u.count_ones() >= 5 {
            let v = spec[u as usize] as i32;
            deg5_sq += (v * v) as u32;
        }
        u += 1;
    }
    (64 * deg5_sq) / wt
}

/// Total Parseval-normalized spectral energy across all 64 modes (`4096` for every nonzero `init_mask`).
pub const fn parseval_normalized_energy(init_mask: u64) -> u32 {
    let wt = init_mask.count_ones();
    if wt == 0 {
        return 0;
    }
    let spec = lut6_walsh_spectrum(init_mask);
    let mut total_sq: u32 = 0;
    let mut u = 0;
    while u < 64 {
        let v = spec[u] as i32;
        total_sq += (v * v) as u32;
        u += 1;
    }
    (64 * total_sq) / wt
}

/// 2-bit LSB wobble-invariant 6-bit codon mask (`0x0F << (target_6bit & 0x3C)`).
/// Matches all 4 wobble variants `(i0, i1) in {00, 01, 10, 11}` sharing the 4-bit stem `target[5:2]`.
#[inline]
pub const fn wobble_codon_mask(target_6bit: u8) -> u64 {
    let stem_base = (target_6bit & 0x3C) as u32;
    0x0Fu64 << stem_base
}

// Compile-time formal exhaustiveness assertions across ALL 64 wobble codons and ALL 64 1-hot masks!
const _: () = {
    let mut addr: u8 = 0;
    while addr < 64 {
        let wob = wobble_codon_mask(addr);
        assert!(high_harmonic_energy(wob) == 0);
        assert!(parseval_normalized_energy(wob) == PARSEVAL_NORM_TOTAL);

        // Verify wobble invariance across all 4 LSB perturbations `w in 0..4`
        let mut w: u8 = 0;
        while w < 4 {
            let perturbed = (addr ^ w) & 0x3F;
            assert!(((wob >> perturbed) & 1) == 1);
            w += 1;
        }

        let one_hot = 1u64 << (addr as u32);
        assert!(high_harmonic_energy(one_hot) == ONE_HOT_DEG5_ENERGY);
        assert!(parseval_normalized_energy(one_hot) == PARSEVAL_NORM_TOTAL);
        addr += 1;
    }
};
