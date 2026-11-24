//! 64-Bit `AgencyStateWord` -> `OperonFrame` Codon & Operon ABI (`SEED_AGENCY`).
//!
//! Encodes the complete endogenous control policy inside a single `const`-constructed
//! 4,096-byte `CompactLut6Page` (`SEED_AGENCY`) with `high_harmonic_energy == 0` across
//! every active gate and full compile-time `rustc` verification across all 9 opcodes and
//! all 2-bit LSB wobble perturbations.

use crate::{
    CompactLut6Page, FLAG_VALIDATED, FLAG_WOBBLE_CLEAN, LUT6_TOTAL_GATES, high_harmonic_energy,
    wobble_codon_mask,
};

pub const AGENCY_DOMAIN_HASH: u64 = 0xA6E4_C700_64C0_D041;

// ============================================================================
// 6-Bit Canonical Operon Codon Opcodes (4-bit stem in [5:2], 2-bit wobble [1:0] = 00)
// ============================================================================

/// Metabolic Homeostasis: halt execution and issue `WFI` zero-clock sleep.
pub const STOP_HALT: u8 = 0x00;

/// Endogenous Splicing: admit and activate a verified `.lut6` overlay crystal.
pub const SPLICE_PAGE: u8 = 0x10;
/// Endogenous State Folding: fold episodic trace summary into next `AgencyStateWord`.
pub const FOLD_STATE: u8 = 0x18;

/// Allosteric Tool Dispatch: deterministic PIO / SPI hardware bus transaction.
pub const BUS_PIO_SPI: u8 = 0x20;
/// Allosteric Tool Dispatch: structured UART / MCP peripheral frame dispatch.
pub const BUS_UART_MCP: u8 = 0x24;
/// Allosteric Tool Dispatch: wake local NPU / `INT8` neural micro-classifier.
pub const WAKE_LOCAL_NPU: u8 = 0x28;
/// Allosteric Tool Dispatch: execute deterministic anchor / invariant verifier check.
pub const VERIFY_CHECK: u8 = 0x2C;

/// Frontier Transcription: escalate out-of-distribution trace to synthesize new `.lut6` page.
pub const TRANSCRIBE_FRONTIER: u8 = 0x30;
/// Apoptosis Safety: emergency rollback of overlay back to immutable `root`.
pub const APOPTOSIS_ROLLBACK: u8 = 0x3C;

// Homeostasis flag bit positions inside `AgencyStateWord` (`[11:6]`)
pub const HOMEO_GOAL_PENDING: u8 = 1 << 0; // wire 6
pub const HOMEO_CONFORMAL_IN_BOUNDS: u8 = 1 << 1; // wire 7
pub const HOMEO_NPU_BUDGET_OK: u8 = 1 << 2; // wire 8
pub const HOMEO_FRONTIER_BUDGET_OK: u8 = 1 << 3; // wire 9
pub const HOMEO_OVERLAY_READY: u8 = 1 << 4; // wire 10
pub const HOMEO_APOPTOSIS_ALARM: u8 = 1 << 5; // wire 11

// Hardware control strobe bit positions inside `OperonFrame` (`[11:6]`)
pub const CTRL_SLEEP_WFI: u8 = 1 << 0; // wire 6
pub const CTRL_BUS_STROBE: u8 = 1 << 1; // wire 7
pub const CTRL_WAKE_NPU: u8 = 1 << 2; // wire 8
pub const CTRL_WAKE_FRONTIER: u8 = 1 << 3; // wire 9
pub const CTRL_SPLICE_ENABLE: u8 = 1 << 4; // wire 10
pub const CTRL_ROLLBACK_TRAP: u8 = 1 << 5; // wire 11

/// 64-bit input stimulus & metabolic state word entering `SEED_AGENCY`.
///
/// Layout:
/// - `[5:0]`:   `stimulus_codon` (bits `[1:0]` = 2-bit sensor/paraphrase wobble; `[5:2]` = stem)
/// - `[11:6]`:  `homeostasis_flags` (`HOMEO_*`)
/// - `[23:12]`: reserved / internal scratch wires (`0` on entry; `SEED_AGENCY` uses `0..24`)
/// - `[27:24]`: `target_slot` (4-bit page/bus peripheral slot `0..15`, passed through)
/// - `[39:28]`: `epoch_tag` (12-bit monotonic epoch tag, passed through)
/// - `[63:40]`: `payload_arg` (24-bit operand / address / digest prefix, passed through)
#[repr(transparent)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct AgencyStateWord(pub u64);

impl AgencyStateWord {
    #[inline]
    pub const fn new(
        stimulus_codon: u8,
        homeostasis_flags: u8,
        target_slot: u8,
        epoch_tag: u16,
        payload_arg: u32,
    ) -> Self {
        let w = ((stimulus_codon as u64) & 0x3F)
            | (((homeostasis_flags as u64) & 0x3F) << 6)
            | (((target_slot as u64) & 0x0F) << 24)
            | (((epoch_tag as u64) & 0x0FFF) << 28)
            | (((payload_arg as u64) & 0x00FF_FFFF) << 40);
        Self(w)
    }

    #[inline]
    pub const fn with_wobble(self, wobble_2bit: u8) -> Self {
        Self((self.0 & !0x3u64) | ((wobble_2bit as u64) & 0x3))
    }

    #[inline]
    pub const fn stimulus_codon(self) -> u8 {
        (self.0 & 0x3F) as u8
    }

    #[inline]
    pub const fn homeostasis_flags(self) -> u8 {
        ((self.0 >> 6) & 0x3F) as u8
    }
}

/// 64-bit output action frame emitted by `SEED_AGENCY`.
#[repr(transparent)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct OperonFrame(pub u64);

impl OperonFrame {
    #[inline]
    pub const fn opcode(self) -> u8 {
        (self.0 & 0x3F) as u8
    }

    #[inline]
    pub const fn control_signals(self) -> u8 {
        ((self.0 >> 6) & 0x3F) as u8
    }

    #[inline]
    pub const fn target_slot(self) -> u8 {
        ((self.0 >> 24) & 0x0F) as u8
    }

    #[inline]
    pub const fn epoch_tag(self) -> u16 {
        ((self.0 >> 28) & 0x0FFF) as u16
    }

    #[inline]
    pub const fn payload_arg(self) -> u32 {
        ((self.0 >> 40) & 0x00FF_FFFF) as u32
    }

    #[inline]
    pub const fn is_sleep_wfi(self) -> bool {
        (self.control_signals() & CTRL_SLEEP_WFI) != 0
    }

    #[inline]
    pub const fn is_apoptosis(self) -> bool {
        (self.control_signals() & CTRL_ROLLBACK_TRAP) != 0
    }
}

/// Helper to build a 64-bit LUT6 `init_mask` from a predicate over `(b0..b5)` at compile time.
macro_rules! lut6_mask {
    (|$b0:ident, $b1:ident, $b2:ident, $b3:ident, $b4:ident, $b5:ident| $body:expr) => {{
        let mut mask: u64 = 0;
        let mut x: u32 = 0;
        while x < 64 {
            let $b0: bool = (x & 1) != 0;
            let $b1: bool = ((x >> 1) & 1) != 0;
            let $b2: bool = ((x >> 2) & 1) != 0;
            let $b3: bool = ((x >> 3) & 1) != 0;
            let $b4: bool = ((x >> 4) & 1) != 0;
            let $b5: bool = ((x >> 5) & 1) != 0;
            if $body {
                mask |= 1u64 << x;
            }
            x += 1;
        }
        mask
    }};
}

const MASK_WIRE0: u64 = lut6_mask!(|b0, _b1, _b2, _b3, _b4, _b5| b0);

const fn stem_match_mask(stem_4bit: u8) -> u64 {
    let s0 = (stem_4bit & 1) != 0;
    let s1 = ((stem_4bit >> 1) & 1) != 0;
    let s2 = ((stem_4bit >> 2) & 1) != 0;
    let s3 = ((stem_4bit >> 3) & 1) != 0;
    lut6_mask!(|b0, b1, b2, b3, _b4, _b5| (b0 == s0) && (b1 == s1) && (b2 == s2) && (b3 == s3))
}

/// Construct the canonical `4,096`-byte `SEED_AGENCY` bootstrap crystal at compile time.
///
/// Every gate across all 4 layers (`4 x 20 = 80` gates) has Boolean degree `<= 4`
/// (`high_harmonic_energy == 0`), proving strict 2-bit wobble immunity and zero parity noise.
pub const fn build_seed_agency() -> CompactLut6Page {
    let mut p = CompactLut6Page::new_blank(AGENCY_DOMAIN_HASH, 4, 20, 3);
    p.flags = FLAG_VALIDATED | FLAG_WOBBLE_CLEAN;
    p.conformal_mask = 0;
    p.override_mask = 0;
    p.conformal_thresh = 64;
    p.proof_digest = *b"SEED_AGENCY_LUT6_CONST_VERIFIED!";

    // ------------------------------------------------------------------------
    // Layer 0 (20 gates): Wobble-invariant stem extraction + homeostasis latch
    //   0..3:  stem bits [0..3] from wires (0,1,2,3,4,5) ignoring wobble (0,1)
    //   4:     is_apop_codon = wobble_codon_mask(APOPTOSIS_ROLLBACK)
    //   5:     is_stop_codon = wobble_codon_mask(STOP_HALT)
    //   6..11: pass-through homeostasis flags (wires 6..11)
    // ------------------------------------------------------------------------
    p.set_gate(
        0,
        0,
        [0, 1, 2, 3, 4, 5],
        lut6_mask!(|_b0, _b1, b2, _b3, _b4, _b5| b2),
    );
    p.set_gate(
        0,
        1,
        [0, 1, 2, 3, 4, 5],
        lut6_mask!(|_b0, _b1, _b2, b3, _b4, _b5| b3),
    );
    p.set_gate(
        0,
        2,
        [0, 1, 2, 3, 4, 5],
        lut6_mask!(|_b0, _b1, _b2, _b3, b4, _b5| b4),
    );
    p.set_gate(
        0,
        3,
        [0, 1, 2, 3, 4, 5],
        lut6_mask!(|_b0, _b1, _b2, _b3, _b4, b5| b5),
    );
    p.set_gate(0, 4, [0, 1, 2, 3, 4, 5], wobble_codon_mask(APOPTOSIS_ROLLBACK));
    p.set_gate(0, 5, [0, 1, 2, 3, 4, 5], wobble_codon_mask(STOP_HALT));
    let mut w = 6usize;
    while w <= 11 {
        p.set_gate(0, w, [w as u8, 0, 0, 0, 0, 0], MASK_WIRE0);
        w += 1;
    }
    // 12: pre-decode `TRANSCRIBE_FRONTIER` 4-bit stem directly from wires [2, 3, 4, 5] (4 inputs, deg 4)
    p.set_gate(
        0,
        12,
        [2, 3, 4, 5, 0, 0],
        stem_match_mask(TRANSCRIBE_FRONTIER >> 2),
    );

    // ------------------------------------------------------------------------
    // Layer 1 (20 gates): Priority envelope + 4-bit stem decoders (all deg <= 4)
    //   0: act_apop    = is_apop_codon (4) || apoptosis_alarm (11)
    //   1: normal_ok   = !is_apop_codon (4) && !apoptosis_alarm (11) && goal_pending (6) && conformal_in_bounds (7)
    //   2: ood_active  = !is_apop_codon (4) && !apoptosis_alarm (11) && goal_pending (6) && !conformal_in_bounds (7)
    //   3: c_splice    = stem == (SPLICE_PAGE >> 2)
    //   4: c_fold      = stem == (FOLD_STATE >> 2)
    //   5: c_pio       = stem == (BUS_PIO_SPI >> 2)
    //   6: c_uart      = stem == (BUS_UART_MCP >> 2)
    //   7: c_npu       = stem == (WAKE_LOCAL_NPU >> 2)
    //   8: c_verify    = stem == (VERIFY_CHECK >> 2)
    //   9: c_fr_gated  = c_frontier_l0 (12) && frontier_budget_ok (9)
    //  10: npu_budget_ok (from L0 wire 8)
    //  11: frontier_budget_ok (from L0 wire 9)
    //  12: overlay_ready (from L0 wire 10)
    //  13: ood_fr_elig = goal_pending (6) && !conformal_in_bounds (7) && !npu_budget_ok (8) && frontier_budget_ok (9)
    // ------------------------------------------------------------------------
    p.set_gate(
        1,
        0,
        [4, 11, 0, 0, 0, 0],
        lut6_mask!(|ap_c, ap_f, _b2, _b3, _b4, _b5| ap_c || ap_f),
    );
    p.set_gate(
        1,
        1,
        [4, 11, 6, 7, 0, 0],
        lut6_mask!(|ap_c, ap_f, goal, conf, _b4, _b5| !ap_c && !ap_f && goal && conf),
    );
    p.set_gate(
        1,
        2,
        [4, 11, 6, 7, 0, 0],
        lut6_mask!(|ap_c, ap_f, goal, conf, _b4, _b5| !ap_c && !ap_f && goal && !conf),
    );
    p.set_gate(1, 3, [0, 1, 2, 3, 0, 0], stem_match_mask(SPLICE_PAGE >> 2));
    p.set_gate(1, 4, [0, 1, 2, 3, 0, 0], stem_match_mask(FOLD_STATE >> 2));
    p.set_gate(1, 5, [0, 1, 2, 3, 0, 0], stem_match_mask(BUS_PIO_SPI >> 2));
    p.set_gate(1, 6, [0, 1, 2, 3, 0, 0], stem_match_mask(BUS_UART_MCP >> 2));
    p.set_gate(1, 7, [0, 1, 2, 3, 0, 0], stem_match_mask(WAKE_LOCAL_NPU >> 2));
    p.set_gate(1, 8, [0, 1, 2, 3, 0, 0], stem_match_mask(VERIFY_CHECK >> 2));
    p.set_gate(
        1,
        9,
        [12, 9, 0, 0, 0, 0],
        lut6_mask!(|c_fr, fr_b, _b2, _b3, _b4, _b5| c_fr && fr_b),
    );
    p.set_gate(1, 10, [8, 0, 0, 0, 0, 0], MASK_WIRE0);
    p.set_gate(1, 11, [9, 0, 0, 0, 0, 0], MASK_WIRE0);
    p.set_gate(1, 12, [10, 0, 0, 0, 0, 0], MASK_WIRE0);
    p.set_gate(
        1,
        13,
        [6, 7, 8, 9, 0, 0],
        lut6_mask!(|goal, conf, npu_b, fr_b, _b4, _b5| goal && !conf && !npu_b && fr_b),
    );
    //  14: c_pio_uart_fold = stem in {FOLD_STATE>>2 (6), BUS_PIO_SPI>>2 (8), BUS_UART_MCP>>2 (9)} (4 inputs -> deg <= 4)
    p.set_gate(
        1,
        14,
        [0, 1, 2, 3, 0, 0],
        stem_match_mask(FOLD_STATE >> 2)
            | stem_match_mask(BUS_PIO_SPI >> 2)
            | stem_match_mask(BUS_UART_MCP >> 2),
    );

    // ------------------------------------------------------------------------
    // Layer 2 (20 gates): Mutually-exclusive gated Operon fire lines (all <= 4 inputs, deg <= 4)
    //   0: fire_apop          = act_apop (0)
    //   1: fire_splice        = normal_ok (1) && c_splice (3) && overlay_ready (12)
    //   2: fire_fold          = normal_ok (1) && c_fold (4)
    //   3: fire_pio           = normal_ok (1) && c_pio (5)
    //   4: fire_uart          = normal_ok (1) && c_uart (6)
    //   5: fire_npu           = (ood_active (2) || (normal_ok (1) && c_npu (7))) && npu_budget (10)
    //   6: fire_verify        = normal_ok (1) && c_verify (8)
    //   7: fire_frontier      = (!act_apop (0) && ood_fr_elig (13)) || (normal_ok (1) && c_fr_gated (9))
    //   8: grp_bus            = normal_ok (1) && (c_pio (5) || c_uart (6))
    //   9: grp_splice_or_fold = normal_ok (1) && ((c_splice (3) && overlay_ready (12)) || c_fold (4))
    //  10: grp_ver_or_apop    = act_apop (0) || (normal_ok (1) && c_verify (8))
    // ------------------------------------------------------------------------
    p.set_gate(2, 0, [0, 0, 0, 0, 0, 0], MASK_WIRE0);
    p.set_gate(
        2,
        1,
        [1, 3, 12, 0, 0, 0],
        lut6_mask!(|ok, sp, rdy, _b3, _b4, _b5| ok && sp && rdy),
    );
    p.set_gate(
        2,
        2,
        [1, 4, 0, 0, 0, 0],
        lut6_mask!(|ok, fld, _b2, _b3, _b4, _b5| ok && fld),
    );
    p.set_gate(
        2,
        3,
        [1, 5, 0, 0, 0, 0],
        lut6_mask!(|ok, pio, _b2, _b3, _b4, _b5| ok && pio),
    );
    p.set_gate(
        2,
        4,
        [1, 6, 0, 0, 0, 0],
        lut6_mask!(|ok, uar, _b2, _b3, _b4, _b5| ok && uar),
    );
    p.set_gate(
        2,
        5,
        [2, 1, 7, 10, 0, 0],
        lut6_mask!(|ood, ok, npu, bud, _b4, _b5| (ood || (ok && npu)) && bud),
    );
    p.set_gate(
        2,
        6,
        [1, 8, 0, 0, 0, 0],
        lut6_mask!(|ok, ver, _b2, _b3, _b4, _b5| ok && ver),
    );
    p.set_gate(
        2,
        7,
        [0, 13, 1, 9, 0, 0],
        lut6_mask!(|ap, ood_fr, ok, c_fr_b, _b4, _b5| (!ap && ood_fr) || (ok && c_fr_b)),
    );
    p.set_gate(
        2,
        8,
        [1, 5, 6, 0, 0, 0],
        lut6_mask!(|ok, pio, uar, _b3, _b4, _b5| ok && (pio || uar)),
    );
    p.set_gate(
        2,
        9,
        [1, 3, 12, 4, 0, 0],
        lut6_mask!(|ok, sp, rdy, fld, _b4, _b5| ok && ((sp && rdy) || fld)),
    );
    p.set_gate(
        2,
        10,
        [0, 1, 8, 0, 0, 0],
        lut6_mask!(|ap, ok, ver, _b3, _b4, _b5| ap || (ok && ver)),
    );
    // Helper 4-input gate from Layer 1 wires `[1, 14, 3, 12]` so Layer 3 `sleep_wfi` takes <= 4 inputs:
    //  11: grp_non_sleep_a = normal_ok (1) && (c_pio_uart_fold (14) || (c_splice (3) && overlay_ready (12)))
    p.set_gate(
        2,
        11,
        [1, 14, 3, 12, 0, 0],
        lut6_mask!(|ok, puf, sp, rdy, _b4, _b5| ok && (puf || (sp && rdy))),
    );

    // ------------------------------------------------------------------------
    // Layer 3 (20 gates): Canonical `OperonFrame[11:0]` synthesis (all deg <= 4)
    //   0: opcode[0] = 0
    //   1: opcode[1] = 0 (2-bit wobble canonicalized to 00)
    //   2: opcode[2] = fire_uart (4) || fire_verify (6) || fire_apop (0)     [0x24, 0x2C, 0x3C]
    //   3: opcode[3] = fire_fold (2) || fire_npu (5) || fire_verify (6) || fire_apop (0) [0x18, 0x28, 0x2C, 0x3C]
    //   4: opcode[4] = fire_splice (1) || fire_fold (2) || fire_frontier (7) || fire_apop (0) [0x10, 0x18, 0x30, 0x3C]
    //   5: opcode[5] = grp_bus (8) || fire_npu (5) || fire_frontier (7) || grp_ver_or_apop (10) [0x20..0x3C]
    //   6: CTRL_SLEEP_WFI     = !(grp_non_sleep_a (11) || fire_npu (5) || fire_frontier (7) || grp_ver_or_apop (10))
    //   7: CTRL_BUS_STROBE    = grp_bus (8)
    //   8: CTRL_WAKE_NPU      = fire_npu (5)
    //   9: CTRL_WAKE_FRONTIER = fire_frontier (7)
    //  10: CTRL_SPLICE_ENABLE = grp_splice_or_fold (9)
    //  11: CTRL_ROLLBACK_TRAP = fire_apop (0)
    // ------------------------------------------------------------------------
    p.set_gate(3, 0, [0, 0, 0, 0, 0, 0], 0);
    p.set_gate(3, 1, [0, 0, 0, 0, 0, 0], 0);
    p.set_gate(
        3,
        2,
        [4, 6, 0, 0, 0, 0],
        lut6_mask!(|uar, ver, ap, _b3, _b4, _b5| uar || ver || ap),
    );
    p.set_gate(
        3,
        3,
        [2, 5, 6, 0, 0, 0],
        lut6_mask!(|fld, npu, ver, ap, _b4, _b5| fld || npu || ver || ap),
    );
    p.set_gate(
        3,
        4,
        [1, 2, 7, 0, 0, 0],
        lut6_mask!(|spl, fld, fr, ap, _b4, _b5| spl || fld || fr || ap),
    );
    p.set_gate(
        3,
        5,
        [8, 5, 7, 10, 0, 0],
        lut6_mask!(|bus, npu, fr, va, _b4, _b5| bus || npu || fr || va),
    );
    p.set_gate(
        3,
        6,
        [11, 5, 7, 10, 0, 0],
        lut6_mask!(|nsa, npu, fr, va, _b4, _b5| !(nsa || npu || fr || va)),
    );
    p.set_gate(3, 7, [8, 0, 0, 0, 0, 0], MASK_WIRE0);
    p.set_gate(3, 8, [5, 0, 0, 0, 0, 0], MASK_WIRE0);
    p.set_gate(3, 9, [7, 0, 0, 0, 0, 0], MASK_WIRE0);
    p.set_gate(3, 10, [9, 0, 0, 0, 0, 0], MASK_WIRE0);
    p.set_gate(3, 11, [0, 0, 0, 0, 0, 0], MASK_WIRE0);

    // Populate embedded self-test anchors right inside `SEED_AGENCY`
    let base_flags = HOMEO_GOAL_PENDING
        | HOMEO_CONFORMAL_IN_BOUNDS
        | HOMEO_NPU_BUDGET_OK
        | HOMEO_FRONTIER_BUDGET_OK
        | HOMEO_OVERLAY_READY;
    let test_codons: [u8; 9] = [
        STOP_HALT,
        SPLICE_PAGE,
        FOLD_STATE,
        BUS_PIO_SPI,
        BUS_UART_MCP,
        WAKE_LOCAL_NPU,
        VERIFY_CHECK,
        TRANSCRIBE_FRONTIER,
        APOPTOSIS_ROLLBACK,
    ];
    let mut k = 0usize;
    while k < 9 {
        let inp = AgencyStateWord::new(test_codons[k], base_flags, k as u8, 7, 0xCAFE_00 + k as u32);
        p.anchor_inputs[k] = inp.0;
        p.anchor_expected[k] = p.eval_raw(inp.0);
        k += 1;
    }
    p.anchor_count = 9;
    p.seal_crc32();
    p
}

/// Immutable 4,096-byte Bootstrap Operon Crystal (`SEED_AGENCY`), compiled & verified at `rustc` compile time.
pub static SEED_AGENCY: CompactLut6Page = build_seed_agency();

/// Evaluate `SEED_AGENCY` on an `AgencyStateWord` in `const` or runtime context.
#[inline]
pub const fn dispatch_seed_agency(word: AgencyStateWord) -> OperonFrame {
    OperonFrame(SEED_AGENCY.eval_raw(word.0))
}

// ============================================================================
// Compile-Time Proof of `SEED_AGENCY` Completeness, Wobble Immunity & Zero Noise
// ============================================================================
const _: () = {
    let agency = build_seed_agency();
    assert!(agency.verify_integrity());

    // 1. Every single LUT6 mask in `SEED_AGENCY` (all 256 slots) has ZERO high-harmonic noise!
    let mut g = 0;
    while g < LUT6_TOTAL_GATES {
        assert!(high_harmonic_energy(agency.init_masks[g]) == 0);
        g += 1;
    }

    // 2. Verify all 9 canonical opcodes across ALL 4 LSB wobble variants (`00, 01, 10, 11`),
    //    including control strobes and lossless pass-through of `target_slot`, `epoch_tag`, `payload_arg`!
    let nom = HOMEO_GOAL_PENDING
        | HOMEO_CONFORMAL_IN_BOUNDS
        | HOMEO_NPU_BUDGET_OK
        | HOMEO_FRONTIER_BUDGET_OK
        | HOMEO_OVERLAY_READY;

    let table: [(u8, u8); 9] = [
        (STOP_HALT, CTRL_SLEEP_WFI),
        (SPLICE_PAGE, CTRL_SPLICE_ENABLE),
        (FOLD_STATE, CTRL_SPLICE_ENABLE),
        (BUS_PIO_SPI, CTRL_BUS_STROBE),
        (BUS_UART_MCP, CTRL_BUS_STROBE),
        (WAKE_LOCAL_NPU, CTRL_WAKE_NPU),
        (VERIFY_CHECK, 0),
        (TRANSCRIBE_FRONTIER, CTRL_WAKE_FRONTIER),
        (APOPTOSIS_ROLLBACK, CTRL_ROLLBACK_TRAP),
    ];

    let mut idx = 0;
    while idx < 9 {
        let (expected_op, expected_ctrl) = table[idx];
        let mut wob: u8 = 0;
        while wob < 4 {
            let stim = AgencyStateWord::new(expected_op | wob, nom, 0xB, 0x3A5, 0x5A_BEEF);
            let out = OperonFrame(agency.eval_raw(stim.0));
            assert!(out.opcode() == expected_op);
            assert!(out.control_signals() == expected_ctrl);
            assert!(out.target_slot() == 0xB);
            assert!(out.epoch_tag() == 0x3A5);
            assert!(out.payload_arg() == 0x5A_BEEF);
            wob += 1;
        }
        idx += 1;
    }

    // 3. Metabolic Homeostasis: when `HOMEO_GOAL_PENDING == 0`, even active tool codons halt & sleep!
    let quiet = AgencyStateWord::new(BUS_PIO_SPI | 0b11, HOMEO_CONFORMAL_IN_BOUNDS, 2, 1, 99);
    let quiet_out = OperonFrame(agency.eval_raw(quiet.0));
    assert!(quiet_out.opcode() == STOP_HALT && quiet_out.is_sleep_wfi());

    // 4. Conformal OOD Escalation: `!HOMEO_CONFORMAL_IN_BOUNDS` escalates to NPU first, then Frontier!
    let ood_npu = AgencyStateWord::new(
        BUS_PIO_SPI,
        HOMEO_GOAL_PENDING | HOMEO_NPU_BUDGET_OK | HOMEO_FRONTIER_BUDGET_OK,
        1,
        1,
        0,
    );
    assert!(OperonFrame(agency.eval_raw(ood_npu.0)).opcode() == WAKE_LOCAL_NPU);

    let ood_frontier = AgencyStateWord::new(
        BUS_PIO_SPI,
        HOMEO_GOAL_PENDING | HOMEO_FRONTIER_BUDGET_OK,
        1,
        1,
        0,
    );
    assert!(OperonFrame(agency.eval_raw(ood_frontier.0)).opcode() == TRANSCRIBE_FRONTIER);

    // 5. Apoptosis Override: `HOMEO_APOPTOSIS_ALARM` preempts every other flag & codon!
    let apop = AgencyStateWord::new(SPLICE_PAGE | 0b10, nom | HOMEO_APOPTOSIS_ALARM, 4, 9, 77);
    let apop_out = OperonFrame(agency.eval_raw(apop.0));
    assert!(apop_out.opcode() == APOPTOSIS_ROLLBACK && apop_out.is_apoptosis());
};
