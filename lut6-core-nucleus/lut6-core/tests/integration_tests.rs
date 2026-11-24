use lut6_core::bootstrap::{
    APOPTOSIS_ROLLBACK, AgencyStateWord, BUS_PIO_SPI, BUS_UART_MCP, FOLD_STATE,
    HOMEO_CONFORMAL_IN_BOUNDS, HOMEO_FRONTIER_BUDGET_OK, HOMEO_GOAL_PENDING, HOMEO_NPU_BUDGET_OK,
    HOMEO_OVERLAY_READY, SEED_AGENCY, SPLICE_PAGE, STOP_HALT, TRANSCRIBE_FRONTIER, VERIFY_CHECK,
    WAKE_LOCAL_NPU, dispatch_seed_agency,
};
use lut6_core::nucleus::{CrystalArena16K, Nucleus, RefineError};
use lut6_core::{
    CompactLut6Page, EvalOutcome, ONE_HOT_DEG5_ENERGY, PARSEVAL_NORM_TOTAL, high_harmonic_energy,
    lut6_walsh_spectrum, parseval_normalized_energy, transpose_64x64, wobble_codon_mask,
};

#[test]
fn page_layout_and_crc32_roundtrip() {
    assert_eq!(core::mem::size_of::<CompactLut6Page>(), 4096);
    assert_eq!(core::mem::align_of::<CompactLut6Page>(), 8);
    assert_eq!(core::mem::size_of::<CrystalArena16K>(), 16_384);
    assert!(SEED_AGENCY.verify_integrity());

    let bytes = SEED_AGENCY.as_bytes();
    let parsed = CompactLut6Page::from_bytes_verified(bytes).expect("CRC32 verified parse");
    assert_eq!(parsed.crc32, SEED_AGENCY.crc32);

    // Flipping any single bit must fail `from_bytes_verified`
    let mut corrupted = *bytes;
    corrupted[2050] ^= 0x01;
    assert!(CompactLut6Page::from_bytes_verified(&corrupted).is_none());
}

#[test]
fn walsh_hadamard_wobble_vs_onehot_exhaustive() {
    for addr in 0..64u8 {
        let wob = wobble_codon_mask(addr);
        assert_eq!(high_harmonic_energy(wob), 0);
        assert_eq!(parseval_normalized_energy(wob), PARSEVAL_NORM_TOTAL);

        let one_hot = 1u64 << (addr as u32);
        assert_eq!(high_harmonic_energy(one_hot), ONE_HOT_DEG5_ENERGY);
        assert_eq!(parseval_normalized_energy(one_hot), PARSEVAL_NORM_TOTAL);

        let spec = lut6_walsh_spectrum(one_hot);
        for &c in &spec {
            assert!(c == 1 || c == -1);
        }
    }
}

#[test]
fn bitsliced_eval_batch_64_matches_scalar_eval_raw() {
    let mut states = [0u64; 64];
    let mut s = 0x1234_5678_9ABC_DEF0u64;
    for slot in &mut states {
        s = s.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
        *slot = s;
    }

    // Check 64x64 bit transpose involution
    assert_eq!(transpose_64x64(&transpose_64x64(&states)), states);

    // Check exact lane-by-lane parity on 4-layer `SEED_AGENCY`
    let batch_out = SEED_AGENCY.eval_batch_64(&states);
    for i in 0..64 {
        assert_eq!(batch_out[i], SEED_AGENCY.eval_raw(states[i]), "lane {i} mismatch");
    }

    // Also test random arbitrary full-degree-6 `init_mask` values across 3 layers
    let mut rand_page = CompactLut6Page::new_blank(0x77, 3, 64, 2);
    for l in 0..3 {
        for g in 0..64 {
            s = s.wrapping_mul(6364136223846793005).wrapping_add(1);
            let wires = [
                (s & 63) as u8,
                ((s >> 6) & 63) as u8,
                ((s >> 12) & 63) as u8,
                ((s >> 18) & 63) as u8,
                ((s >> 24) & 63) as u8,
                ((s >> 30) & 63) as u8,
            ];
            s = s.wrapping_mul(6364136223846793005).wrapping_add(1);
            rand_page.set_gate(l, g, wires, s);
        }
    }
    rand_page.seal_crc32();
    let rand_batch = rand_page.eval_batch_64(&states);
    for i in 0..64 {
        assert_eq!(rand_batch[i], rand_page.eval_raw(states[i]), "arbitrary LUT6 lane {i}");
    }
}

#[test]
fn operon_codons_and_nucleus_apoptosis() {
    let nom = HOMEO_GOAL_PENDING
        | HOMEO_CONFORMAL_IN_BOUNDS
        | HOMEO_NPU_BUDGET_OK
        | HOMEO_FRONTIER_BUDGET_OK
        | HOMEO_OVERLAY_READY;
    for op in [
        STOP_HALT,
        SPLICE_PAGE,
        FOLD_STATE,
        BUS_PIO_SPI,
        BUS_UART_MCP,
        WAKE_LOCAL_NPU,
        VERIFY_CHECK,
        TRANSCRIBE_FRONTIER,
        APOPTOSIS_ROLLBACK,
    ] {
        for wob in 0..4u8 {
            let f = dispatch_seed_agency(AgencyStateWord::new(op | wob, nom, 5, 42, 0xABCD));
            assert_eq!(f.opcode(), op);
            assert_eq!(f.target_slot(), 5);
            assert_eq!(f.epoch_tag(), 42);
            assert_eq!(f.payload_arg(), 0xABCD);
        }
    }

    let mut root = CompactLut6Page::new_blank(0xABCD_EF01, 1, 4, 2);
    root.set_gate(0, 0, [0, 1, 2, 3, 4, 5], wobble_codon_mask(0x08));
    root.anchor_inputs[0] = 0x08;
    root.anchor_expected[0] = 1;
    root.anchor_count = 1;
    root.seal_crc32();

    let mut nuc = Nucleus::new_bootstrap(root);
    let mut bad = root;
    bad.set_gate(0, 1, [0, 1, 2, 3, 4, 5], 1u64 << 19);
    bad.seal_crc32();

    assert!(matches!(
        nuc.refine_knowledge(&bad, &[]),
        Err(RefineError::HighHarmonicNoise { energy: 448, .. })
    ));
    assert!(matches!(
        nuc.refine_knowledge(&bad, &[]),
        Err(RefineError::HighHarmonicNoise { energy: 448, .. })
    ));
    assert!(nuc.apoptosis_latched);
    assert_eq!(
        nuc.query_knowledge(0x08),
        Ok(EvalOutcome::Killed { fallback_output: 1 })
    );
}
