//! End-to-End 3-Part Self-Hosting Bootstrap `Nucleus` Ratchet & Apoptosis Demo.
//!
//! Exercises:
//! 1. Booting the `16,384`-byte `CrystalArena16K` (`knowledge_root` + `SEED_AGENCY` + overlays).
//! 2. Wobble-invariant sensory & operon dispatch (`STOP_HALT`, `BUS_PIO_SPI`, `TRANSCRIBE_FRONTIER`).
//! 3. Rejecting an overfit 1-hot memorization patch (`high_harmonic_energy == 448 > 0`).
//! 4. Rejecting a catastrophic-forgetting patch (`AnchorRegression`).
//! 5. Splicing a valid 2-bit wobble-invariant overlay (`SPLICE_PAGE 0x10`, `high_harmonic_energy == 0`).
//! 6. Triggering `APOPTOSIS_ROLLBACK (0x3C)` once `verifier_rejects >= kill_max_rejects`, proving
//!    bit-for-bit preservation of `knowledge_root` and `agency_root`.

use std::mem::size_of;

use lut6_core::bootstrap::{
    APOPTOSIS_ROLLBACK, AgencyStateWord, BUS_PIO_SPI, HOMEO_CONFORMAL_IN_BOUNDS,
    HOMEO_FRONTIER_BUDGET_OK, HOMEO_GOAL_PENDING, HOMEO_NPU_BUDGET_OK, HOMEO_OVERLAY_READY,
    SPLICE_PAGE, STOP_HALT, TRANSCRIBE_FRONTIER,
};
use lut6_core::nucleus::{CrystalArena16K, Nucleus, RefineError};
use lut6_core::{
    CompactLut6Page, EvalOutcome, FLAG_OVERLAY_PAGE, FLAG_VALIDATED, FLAG_WOBBLE_CLEAN,
    ONE_HOT_DEG5_ENERGY, high_harmonic_energy, wobble_codon_mask,
};

const DEMO_DOMAIN_HASH: u64 = 0xD04A_1400_C0DE_0001;

fn build_seed_knowledge() -> CompactLut6Page {
    let mut p = CompactLut6Page::new_blank(DEMO_DOMAIN_HASH, 1, 8, 3);
    p.flags = FLAG_VALIDATED | FLAG_WOBBLE_CLEAN;
    p.conformal_mask = 0x00FF_0000_0000_0000;
    p.override_mask = 0xFF00_0000_0000_0000;
    p.conformal_thresh = 1;
    // Recognize codon family 0x04 (`0x04..=0x07`) on output bit 0 and 0x08 (`0x08..=0x0B`) on bit 1
    p.set_gate(0, 0, [0, 1, 2, 3, 4, 5], wobble_codon_mask(0x04));
    p.set_gate(0, 1, [0, 1, 2, 3, 4, 5], wobble_codon_mask(0x08));

    p.anchor_inputs[0] = 0x04;
    p.anchor_expected[0] = 0b01;
    p.anchor_inputs[1] = 0x07; // +3 LSB wobble variant of 0x04
    p.anchor_expected[1] = 0b01;
    p.anchor_inputs[2] = 0x09; // +1 LSB wobble variant of 0x08
    p.anchor_expected[2] = 0b10;
    p.anchor_count = 3;
    p.seal_crc32();
    p
}

fn main() {
    let root_k = build_seed_knowledge();
    let root_k_crc = root_k.crc32;
    let mut nucleus = Nucleus::new_bootstrap(root_k);
    let root_a_crc = nucleus.arena.agency_root.crc32;

    assert_eq!(size_of::<CrystalArena16K>(), 16_384);
    assert_eq!(size_of::<CompactLut6Page>(), 4_096);

    // 1. Metabolic Homeostasis when no goal is pending
    let idle_frame = nucleus.step_agency(AgencyStateWord::new(
        BUS_PIO_SPI | 0b10,
        HOMEO_CONFORMAL_IN_BOUNDS,
        0,
        1,
        0,
    ));
    assert_eq!(idle_frame.opcode(), STOP_HALT);
    assert!(idle_frame.is_sleep_wfi());

    // 2. OOD Conformal Escalation (`nonconformity = 3 > 1`)
    let ood_state: u64 = 0x0007_0000_0000_0014;
    let Ok(ood_res) = nucleus.query_knowledge(ood_state);
    assert!(matches!(ood_res, EvalOutcome::Escalate { nonconformity: 3, .. }));

    let frontier_frame = nucleus.step_agency(AgencyStateWord::new(
        BUS_PIO_SPI,
        HOMEO_GOAL_PENDING | HOMEO_FRONTIER_BUDGET_OK,
        1,
        2,
        0x14,
    ));
    assert_eq!(frontier_frame.opcode(), TRANSCRIBE_FRONTIER);

    // 3. Reject Candidate A: 1-hot brittle patch (`high_harmonic_energy == 448`)
    let mut bad_onehot = root_k;
    bad_onehot.flags |= FLAG_OVERLAY_PAGE;
    bad_onehot.set_gate(0, 2, [0, 1, 2, 3, 4, 5], 1u64 << 0x14);
    bad_onehot.seal_crc32();
    assert_eq!(high_harmonic_energy(bad_onehot.init_masks[2]), ONE_HOT_DEG5_ENERGY);

    let err_a = nucleus.refine_knowledge(&bad_onehot, &[]).unwrap_err();
    assert_eq!(
        err_a,
        RefineError::HighHarmonicNoise {
            gate_idx: 2,
            energy: 448,
            max_allowed: 0,
        }
    );
    assert_eq!(nucleus.verifier_rejects, 1);

    // 4. Reject Candidate B: Wobble-clean (`0` harmonic noise), but corrupts protected Anchor #0
    let mut bad_forget = root_k;
    bad_forget.flags |= FLAG_OVERLAY_PAGE;
    bad_forget.set_gate(0, 0, [0, 1, 2, 3, 4, 5], 0); // forgets 0x04!
    bad_forget.set_gate(0, 2, [0, 1, 2, 3, 4, 5], wobble_codon_mask(0x14));
    bad_forget.seal_crc32();

    let err_b = nucleus.refine_knowledge(&bad_forget, &[]).unwrap_err();
    assert!(matches!(err_b, RefineError::AnchorRegression { anchor_idx: 0, .. }));
    assert_eq!(nucleus.verifier_rejects, 2);

    // 5. Admit Candidate C: Wobble-clean + 100% Zero-Regression Anchor Retention!
    let nom = HOMEO_GOAL_PENDING
        | HOMEO_CONFORMAL_IN_BOUNDS
        | HOMEO_NPU_BUDGET_OK
        | HOMEO_FRONTIER_BUDGET_OK
        | HOMEO_OVERLAY_READY;
    let splice_frame = nucleus.step_agency(AgencyStateWord::new(SPLICE_PAGE | 0b11, nom, 0, 3, 0));
    assert_eq!(splice_frame.opcode(), SPLICE_PAGE);

    let mut good_patch = root_k;
    good_patch.flags |= FLAG_OVERLAY_PAGE;
    good_patch.set_gate(0, 2, [0, 1, 2, 3, 4, 5], wobble_codon_mask(0x14));
    good_patch.seal_crc32();

    let receipt = nucleus
        .refine_knowledge(&good_patch, &[(0x0B, 0b10)])
        .expect("wobble-clean retention-preserving crystal must splice");
    assert_eq!(receipt.generation, 1);
    assert_eq!(receipt.max_gate_harmonic_energy, 0);
    assert_eq!(receipt.anchors_verified, 4);

    // Verify all 4 wobble variants (`0x14..=0x17`) now resolve in single-pass `Act` via overlay!
    for w in 0..4u64 {
        let Ok(out) = nucleus.query_knowledge(0x14 | w);
        assert_eq!(
            out,
            EvalOutcome::Act {
                output: 0b100,
                used_overlay: true,
            }
        );
    }

    // 6. Trigger Apoptosis (`verifier_rejects` hits `kill_max_rejects == 3`)
    let _ = nucleus.refine_knowledge(&bad_onehot, &[]);
    assert_eq!(nucleus.verifier_rejects, 3);
    assert!(nucleus.apoptosis_latched);
    assert!(!nucleus.has_knowledge_overlay());

    let Ok(post_kill) = nucleus.query_knowledge(0x04);
    assert_eq!(
        post_kill,
        EvalOutcome::Killed {
            fallback_output: 0b01,
        }
    );

    // Verify explicit `APOPTOSIS_ROLLBACK (0x3C)` codon also latches rollback cleanly
    let apop_frame = nucleus.step_agency(AgencyStateWord::new(APOPTOSIS_ROLLBACK | 0b01, nom, 0, 4, 0));
    assert_eq!(apop_frame.opcode(), APOPTOSIS_ROLLBACK);
    assert!(apop_frame.is_apoptosis());

    // Immutable roots remain 100% untouched
    assert_eq!(nucleus.arena.knowledge_root.crc32, root_k_crc);
    assert_eq!(nucleus.arena.agency_root.crc32, root_a_crc);
    assert!(nucleus.arena.knowledge_root.verify_integrity());
    assert!(nucleus.arena.agency_root.verify_integrity());

    println!(
        "{{\n  \"demo\": \"lut6_3part_bootstrap_nucleus_ratchet\",\n  \
         \"crystal_arena_bytes\": {},\n  \"page_bytes\": {},\n  \
         \"rejected_1hot_harmonic_energy\": {},\n  \"admitted_overlay_harmonic_energy\": {},\n  \
         \"anchors_verified\": {},\n  \"wobble_variants_verified\": 4,\n  \
         \"apoptosis_triggered_at_rejects\": {},\n  \
         \"immutable_roots_intact\": true,\n  \
         \"knowledge_root_crc32\": \"0x{:08x}\",\n  \
         \"agency_root_crc32\": \"0x{:08x}\"\n}}",
        size_of::<CrystalArena16K>(),
        size_of::<CompactLut6Page>(),
        ONE_HOT_DEG5_ENERGY,
        receipt.max_gate_harmonic_energy,
        receipt.anchors_verified,
        nucleus.verifier_rejects,
        root_k_crc,
        root_a_crc
    );
}
