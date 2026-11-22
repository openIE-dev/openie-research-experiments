//! Conformance test suite for `jcp-satb-cad-spine`:
//! 1. Exhaustive SATB-IO (`L0..L4` x `A1..N`) <-> JCP (`JCR-1`) lattice mapping &
//!    monotone no-silent-upgrade meet checks (`280 x 280 = 78,400` pairs).
//! 2. Allow vector + canonical det-CBOR Ed25519 `COSE_Sign1` verification.
//! 3. BudgetExceeded deny vector (`debited_uj == 0`).
//! 4. UntrustedControl (`Trust::Data`) anti-tool-poisoning deny vector.
//! 5. Revoked grant deny vector + `AlreadyResolved` double-settle refusal vector.
//! 6. SATB Falsifier 6 (`> 5.0%` baseline drift drops `satb_derived_marginal_uj`
//!    while keeping `satb_raw_counter_uj` sealed inside signed `JCR-1` bytes).
//! 7. SATB Step 7 (`|sum(phases) - window| <= 1 uJ`) phase-sum conservation check.
//! 8. Multi-stage `openie-cad` (`Material`, `SupplyChain`, `Compute`) `JCR-1`
//!    receipt chain + `efficiency/1` outcome receipt + `jcp_receipt::replay_ledger`
//!    crash-recovery equivalence.
//! 9. `10,000`-wakeup cold-chain trace at `-20 C`, `+4 C`, and `+25 C` proving
//!    deterministic refusal of non-essential radio bursts under `-20 C` sag while
//!    preserving `100%` of safety-critical excursion alerts.

use ed25519_dalek::SigningKey;
use jcp_efficiency::{aggregate, Efficiency};
use jcp_grant::{issue, revoke};
use jcp_runtime::Runtime;
use jcp_schema::{
    Capability, Caveat, ContentId, Coverage, DenyReason, Did, Energy, FrameKind, Grant,
    Provenance, Trust, Verdict,
};
use jcp_satb_cad_spine::{
    run_coldchain_10k_simulation, CadTract, ColdChainCellProfile, CounterMechanism, EvidenceTier,
    JcpLatticeRung, SatbAttribution, SatbBoundary, SatbProvenance, SpineReceiptChain,
    StageAttemptSpec,
};

fn key(seed: u8) -> SigningKey {
    SigningKey::from_bytes(&[seed; 32])
}

#[test]
fn vector_01_satb_jcp_lattice_roundtrip_and_exhaustive_no_upgrade_meet() {
    // 1a. Canonical forward & inverse checks across all five required tiers
    let p_shunt_whole = SatbProvenance::rail_shunt(SatbBoundary::L0, SatbAttribution::A1, true);
    let e_whole = p_shunt_whole.to_jcp_energy(250_000).unwrap();
    assert_eq!(e_whole.provenance, Provenance::HwShunt);
    assert_eq!(e_whole.coverage, Coverage::Whole);
    assert_eq!(p_shunt_whole.evidence_tier(), EvidenceTier::MeasuredJ);

    let p_shunt_partial = SatbProvenance::rail_shunt(SatbBoundary::L2, SatbAttribution::B, false);
    let e_part = p_shunt_partial.to_jcp_energy(120_000).unwrap();
    assert_eq!(e_part.provenance, Provenance::HwShunt);
    assert_eq!(e_part.coverage, Coverage::Partial);
    assert_eq!(p_shunt_partial.evidence_tier(), EvidenceTier::MeasuredJ);

    let p_rapl = SatbProvenance::vendor_counter(SatbBoundary::L1, SatbAttribution::A2, false);
    assert_eq!(
        p_rapl.to_jcp_rung(),
        JcpLatticeRung::HwShunt {
            coverage: Coverage::Partial,
            vendor_opaque: true
        }
    );
    assert_eq!(p_rapl.evidence_tier(), EvidenceTier::ReportedJ);

    let p_kepler = SatbProvenance::kepler_cpu_share(SatbBoundary::L3);
    assert_eq!(
        p_kepler.to_jcp_rung(),
        JcpLatticeRung::ModelBased {
            coverage: Coverage::Partial
        }
    );
    assert_eq!(p_kepler.evidence_tier(), EvidenceTier::ReportedJ);

    let p_est = SatbProvenance::estimator(SatbBoundary::L2);
    assert_eq!(
        p_est.to_jcp_rung(),
        JcpLatticeRung::Estimator {
            coverage: Coverage::Whole
        }
    );
    assert_eq!(p_est.evidence_tier(), EvidenceTier::EstJ);

    let p_closed = SatbProvenance::unattested_api();
    assert_eq!(p_closed.to_jcp_rung(), JcpLatticeRung::NotAvailable);
    assert_eq!(p_closed.to_jcp_energy(999), None);
    assert_eq!(p_closed.evidence_tier(), EvidenceTier::NotAvailable);

    // Canonical inverse round-trip on every JcpLatticeRung variant
    for rung in [
        JcpLatticeRung::HwShunt {
            coverage: Coverage::Whole,
            vendor_opaque: false,
        },
        JcpLatticeRung::HwShunt {
            coverage: Coverage::Partial,
            vendor_opaque: false,
        },
        JcpLatticeRung::HwShunt {
            coverage: Coverage::Whole,
            vendor_opaque: true,
        },
        JcpLatticeRung::HwShunt {
            coverage: Coverage::Partial,
            vendor_opaque: true,
        },
        JcpLatticeRung::ModelBased {
            coverage: Coverage::Partial,
        },
        JcpLatticeRung::Estimator {
            coverage: Coverage::Whole,
        },
        JcpLatticeRung::NotAvailable,
    ] {
        let rep = SatbProvenance::from_jcp_rung(rung);
        assert_eq!(rep.to_jcp_rung(), rung, "canonical inverse must round-trip");
    }

    // 1b. Exhaustive 280 x 280 cartesian product monotonicity verification
    let mut universe = Vec::new();
    for b in SatbBoundary::ALL {
        for a in SatbAttribution::ALL {
            for m in CounterMechanism::ALL {
                universe.push(SatbProvenance {
                    boundary: b,
                    attribution: a,
                    mechanism: m,
                });
            }
        }
    }
    assert_eq!(universe.len(), 280);

    for &x in &universe {
        assert_eq!(x.meet(x), x, "idempotence");
        let rx = x.to_jcp_rung();
        for &y in &universe {
            let ry = y.to_jcp_rung();
            let xy = x.meet(y);
            assert_eq!(xy, y.meet(x), "commutativity");
            let rxy = xy.to_jcp_rung();
            assert!(
                rxy.rank() <= rx.rank().min(ry.rank()),
                "provenance rung silently upgraded: {x:?} ({rx:?}) ^ {y:?} ({ry:?}) -> {xy:?} ({rxy:?})"
            );
            assert!(
                rxy.evidence_tier() <= rx.evidence_tier().min(ry.evidence_tier()),
                "evidence tier silently upgraded"
            );
            if rx.coverage() == Some(Coverage::Partial) || ry.coverage() == Some(Coverage::Partial)
            {
                if let Some(cov) = rxy.coverage() {
                    assert_eq!(cov, Coverage::Partial, "coverage silently upgraded to Whole");
                }
            }
        }
    }
}

#[test]
fn vector_02_allow_budget_exceeded_untrusted_control_and_revocation() {
    let issuer_sk = key(1);
    let worker_sk = key(2);
    let steward_sk = key(7);

    let issuer_did = Did::from_verifying_key(&issuer_sk.verifying_key());
    let worker_did = Did::from_verifying_key(&worker_sk.verifying_key());
    let res = ContentId::of_bytes(b"cad:session:mei-tag");

    let sg = issue(
        &issuer_sk,
        Grant {
            issuer: issuer_did,
            subject: worker_did,
            capability: Capability::new(res, ["cad.solve"]),
            budget_uj: 500_000,
            budget_funds: None,
            caveats: Vec::new(),
            expiry: 0,
            parent: None,
            delegate_depth: None,
            nonce: [1; 16],
        },
    )
    .unwrap();

    let mut spine = SpineReceiptChain::new(steward_sk, "did:openie:steward:lane4");

    // 1. Allow (`300_000 uJ` RAPL reported_j)
    let allow_spec = StageAttemptSpec {
        stage: "cad.eda.drc".to_string(),
        tract: CadTract::Compute,
        action: "cad.solve".to_string(),
        resource: res,
        payload_bytes: b"board=mei_jcp_tag_v1".to_vec(),
        trust: Trust::Control,
        frame_kind: FrameKind::ToolCall,
        timestamp_s: 100,
        window_us: 1_200_000,
        backend: "linux-rapl".to_string(),
        provenance: SatbProvenance::vendor_counter(SatbBoundary::L1, SatbAttribution::A2, false),
        measured_uj: None,
        reported_uj: Some(300_000),
        est_uj: Some(280_000),
        idle_bracket_uw: Some((4_000_000, 4_120_000)), // 3.0% drift -> pass
        step7_subphases_uj: Some(vec![110_000, 190_000]),
    };
    let (d1, r1) = spine.decide_and_seal(&sg, worker_did, &allow_spec).unwrap();
    assert!(d1.is_allow());
    assert_eq!(d1.debited_uj, 300_000);
    assert_eq!(r1.verdict, "allow");
    assert_eq!(r1.evidence_tier, EvidenceTier::ReportedJ);

    // 2. BudgetExceeded deny (`250_000 uJ` > `200_000 uJ` remaining -> 0 debited)
    let over_spec = StageAttemptSpec {
        reported_uj: Some(250_000),
        stage: "cad.router.overbudget".to_string(),
        ..allow_spec.clone()
    };
    let (d2, r2) = spine.decide_and_seal(&sg, worker_did, &over_spec).unwrap();
    assert_eq!(d2.verdict, Verdict::Deny(DenyReason::BudgetExceeded));
    assert_eq!(d2.debited_uj, 0);
    assert_eq!(r2.deny_reason.as_deref(), Some("budget-exceeded"));

    // 3. UntrustedControl deny (`Trust::Data` tool-poisoning frame -> refused before budget)
    let untrusted_spec = StageAttemptSpec {
        trust: Trust::Data,
        reported_uj: Some(10_000),
        stage: "cad.poisoned.prompt".to_string(),
        ..allow_spec.clone()
    };
    let (d3, r3) = spine
        .decide_and_seal(&sg, worker_did, &untrusted_spec)
        .unwrap();
    assert_eq!(d3.verdict, Verdict::Deny(DenyReason::UntrustedControl));
    assert_eq!(d3.debited_uj, 0);
    assert_eq!(r3.deny_reason.as_deref(), Some("untrusted-control"));

    // 4. Revocation deny (`revoke` signed by issuer -> refused)
    let rev = revoke(&issuer_sk, &sg.grant, [9; 16]).unwrap();
    spine.runtime.apply_revocation(&rev, &sg.grant).unwrap();
    let post_rev_spec = StageAttemptSpec {
        reported_uj: Some(10_000),
        stage: "cad.post_revocation".to_string(),
        ..allow_spec
    };
    let (d4, r4) = spine
        .decide_and_seal(&sg, worker_did, &post_rev_spec)
        .unwrap();
    assert_eq!(d4.verdict, Verdict::Deny(DenyReason::Revoked));
    assert_eq!(d4.debited_uj, 0);
    assert_eq!(r4.deny_reason.as_deref(), Some("revoked"));

    let (ledger, _, summary) = spine.verify_and_replay().unwrap();
    assert_eq!(summary.verified_jcr1_entries, 4);
    assert_eq!(summary.replayed_total_debited_uj, 300_000);
    assert_eq!(ledger.uj, vec![(sg.grant.id(), 300_000)]);
}

#[test]
fn vector_03_falsifier_6_drift_rejection_and_step_7_conservation_in_signed_cbor() {
    let issuer_sk = key(3);
    let worker_sk = key(4);
    let steward_sk = key(8);

    let issuer_did = Did::from_verifying_key(&issuer_sk.verifying_key());
    let worker_did = Did::from_verifying_key(&worker_sk.verifying_key());
    let res = ContentId::of_bytes(b"satb:harness:attempt");

    let sg = issue(
        &issuer_sk,
        Grant {
            issuer: issuer_did,
            subject: worker_did,
            capability: Capability::new(res, ["satb.measure"]),
            budget_uj: 5_000_000,
            budget_funds: None,
            caveats: Vec::new(),
            expiry: 0,
            parent: None,
            delegate_depth: None,
            nonce: [2; 16],
        },
    )
    .unwrap();

    let mut spine = SpineReceiptChain::new(steward_sk, "did:openie:steward:satb");

    // Attempt A: 6.40% pre/post idle drift (> 5.00% Falsifier 6 limit) + 5 uJ Step 7 residual
    let drifted_spec = StageAttemptSpec {
        stage: "satb.attempt.drifted".to_string(),
        tract: CadTract::Compute,
        action: "satb.measure".to_string(),
        resource: res,
        payload_bytes: b"run=drifted".to_vec(),
        trust: Trust::Control,
        frame_kind: FrameKind::AgentTask,
        timestamp_s: 200,
        window_us: 1_000_000,
        backend: "linux-rapl".to_string(),
        provenance: SatbProvenance::vendor_counter(SatbBoundary::L1, SatbAttribution::A2, false),
        measured_uj: None,
        reported_uj: Some(900_000),
        est_uj: None,
        idle_bracket_uw: Some((5_000_000, 5_320_000)), // 640 bps = 6.40% > 5.00%
        step7_subphases_uj: Some(vec![400_000, 499_995]), // residual = 5 uJ > 1 uJ
    };
    let (_, rec_drift) = spine
        .decide_and_seal(&sg, worker_did, &drifted_spec)
        .unwrap();
    let f6 = rec_drift.falsifier6.unwrap();
    assert!(!f6.passed);
    assert_eq!(f6.drift_bps, 640);
    assert_eq!(f6.raw_counter_uj, 900_000);
    assert_eq!(f6.derived_marginal_uj, None);
    assert!(!rec_drift.step7.unwrap().passed);

    // Inspect the cryptographically verified det-CBOR payload directly!
    let cbor_val = spine.decode_verified_payload(0).unwrap();
    assert_eq!(cbor_val["satb_raw_counter_uj"], 900_000);
    assert_eq!(cbor_val["satb_drift_bps"], 640);
    assert_eq!(cbor_val["satb_falsifier6_pass"], 0);
    assert!(
        cbor_val.get("satb_derived_marginal_uj").is_none(),
        "Falsifier 6 failure MUST omit derived_marginal_uj from signed JCR-1 payload"
    );
    assert_eq!(cbor_val["satb_step7_residual_uj"], 5);
    assert_eq!(cbor_val["satb_step7_pass"], 0);

    // Attempt B: 2.20% drift (<= 5.00%) + 1 uJ Step 7 residual (<= 1 uJ) -> both pass!
    let clean_spec = StageAttemptSpec {
        stage: "satb.attempt.clean".to_string(),
        idle_bracket_uw: Some((5_000_000, 5_110_000)), // 220 bps = 2.20%
        reported_uj: Some(6_200_000),
        step7_subphases_uj: Some(vec![2_100_000, 4_099_999]), // residual = 1 uJ <= 1 uJ
        ..drifted_spec
    };
    spine.runtime = Runtime::new();
    let sg_big = issue(
        &issuer_sk,
        Grant {
            budget_uj: 10_000_000,
            nonce: [3; 16],
            ..sg.grant.clone()
        },
    )
    .unwrap();
    let (_, rec_clean) = spine
        .decide_and_seal(&sg_big, worker_did, &clean_spec)
        .unwrap();
    assert!(rec_clean.falsifier6.unwrap().passed);
    assert!(rec_clean.step7.unwrap().passed);

    let cbor_clean = spine.decode_verified_payload(1).unwrap();
    assert_eq!(cbor_clean["satb_falsifier6_pass"], 1);
    assert_eq!(cbor_clean["satb_derived_marginal_uj"], 1_145_000);
    assert_eq!(cbor_clean["satb_step7_pass"], 1);

    let (_, _, summary) = spine.verify_and_replay().unwrap();
    assert_eq!(summary.verified_jcr1_entries, 2);
}

#[test]
fn vector_04_openie_cad_three_tract_chain_hold_settle_and_efficiency_replay() {
    let issuer_sk = key(5);
    let cad_sk = key(6);
    let steward_sk = key(9);

    let issuer_did = Did::from_verifying_key(&issuer_sk.verifying_key());
    let cad_did = Did::from_verifying_key(&cad_sk.verifying_key());
    let res = ContentId::of_bytes(b"openie-cad:project:mei-jcp-tag-v1");

    let sg = issue(
        &issuer_sk,
        Grant {
            issuer: issuer_did,
            subject: cad_did,
            capability: Capability::new(
                res,
                ["tract.material", "tract.supply_chain", "tract.compute"],
            ),
            budget_uj: 50_000_000,
            budget_funds: None,
            caveats: vec![Caveat::MaxCostUj(20_000_000)],
            expiry: 0,
            parent: None,
            delegate_depth: None,
            nonce: [4; 16],
        },
    )
    .unwrap();

    let mut spine = SpineReceiptChain::new(steward_sk, "did:openie:steward:cad-session");

    // Stage 1: Material tract (FR-4 + ABS embodied analytical estimate -> est_j)
    let s_mat = StageAttemptSpec {
        stage: "cad.material.embodied".to_string(),
        tract: CadTract::Material,
        action: "tract.material".to_string(),
        resource: res,
        payload_bytes: b"fr4+abs-enclosure".to_vec(),
        trust: Trust::Control,
        frame_kind: FrameKind::ToolCall,
        timestamp_s: 10,
        window_us: 250,
        backend: "analytical-estimator".to_string(),
        provenance: SatbProvenance::estimator(SatbBoundary::L2),
        measured_uj: None,
        reported_uj: None,
        est_uj: Some(5_000_000),
        idle_bracket_uw: None,
        step7_subphases_uj: None,
    };
    spine.decide_and_seal(&sg, cad_did, &s_mat).unwrap();

    // Stage 2: SupplyChain tract (pick-and-place + stencil analytical estimate -> est_j)
    let s_sc = StageAttemptSpec {
        stage: "cad.supply_chain.jlcpcb_smt".to_string(),
        tract: CadTract::SupplyChain,
        action: "tract.supply_chain".to_string(),
        est_uj: Some(3_500_000),
        ..s_mat.clone()
    };
    spine.decide_and_seal(&sg, cad_did, &s_sc).unwrap();

    // Stage 3: Compute tract via two-phase hold -> autoroute+DRC -> settle (RAPL reported_j)
    let (hold_dec, ticket_opt) = spine
        .place_hold_and_seal(
            &sg,
            cad_did,
            "cad.compute.autoroute_drc",
            CadTract::Compute,
            "tract.compute",
            res,
            b"grid=0.25mm;layers=2",
            Trust::Control,
            20,
        )
        .unwrap();
    assert!(hold_dec.is_allow());
    let ticket = ticket_opt.unwrap();
    assert_eq!(ticket.held_uj, 20_000_000);

    let s_comp = StageAttemptSpec {
        stage: "cad.compute.autoroute_drc".to_string(),
        tract: CadTract::Compute,
        action: "tract.compute".to_string(),
        resource: res,
        payload_bytes: b"grid=0.25mm;layers=2".to_vec(),
        trust: Trust::Control,
        frame_kind: FrameKind::ToolCall,
        timestamp_s: 22,
        window_us: 1_100_000,
        backend: "linux-rapl".to_string(),
        provenance: SatbProvenance::vendor_counter(SatbBoundary::L1, SatbAttribution::A2, false),
        measured_uj: None,
        reported_uj: Some(12_400_000),
        est_uj: Some(11_000_000),
        idle_bracket_uw: Some((6_000_000, 6_150_000)),
        step7_subphases_uj: Some(vec![8_400_000, 4_000_000]),
    };
    let (settle_dec, _) = spine
        .settle_hold_and_seal(&sg.grant, &ticket, &s_comp)
        .unwrap();
    assert!(settle_dec.is_allow());
    assert_eq!(settle_dec.debited_uj, 12_400_000);

    // Double-settle on the same hold MUST be refused `already-resolved` and leave hold settled!
    let (dup_dec, dup_rec) = spine
        .settle_hold_and_seal(&sg.grant, &ticket, &s_comp)
        .unwrap();
    assert_eq!(dup_dec.verdict, Verdict::Deny(DenyReason::AlreadyResolved));
    assert_eq!(dup_dec.debited_uj, 0);
    assert_eq!(dup_rec.deny_reason.as_deref(), Some("already-resolved"));

    // Seal outcome-anchored `efficiency/1` receipt over the session's lattice meet floor (`EstJ` / `Partial`)
    let session_total_uj = 5_000_000 + 3_500_000 + 12_400_000;
    let mut partial_est = Energy::estimator(session_total_uj);
    partial_est.coverage = Coverage::Partial;
    let eff = Efficiency {
        task: "mei-jcp-tag-v1:cad-build".to_string(),
        completed: true,
        verdict: "drc-0-errors-step-stl-verified".to_string(),
        tokens_in: 1_200,
        tokens_out: 400,
        energy: partial_est,
        wall_ns: 1_350_000_000,
        value_uusd: None,
        energy_attestation: None,
    };
    spine.append_efficiency(&eff);

    let (ledger, eff_receipts, summary) = spine.verify_and_replay().unwrap();
    assert_eq!(summary.verified_jcr1_entries, 5);
    assert_eq!(summary.unresolved_holds_count, 0);
    assert_eq!(summary.replayed_total_debited_uj, session_total_uj);
    // Session combined `Estimator (Whole)` ^ `VendorOpaque RAPL (Partial)` -> floor is `EstJ` + `Partial`!
    assert_eq!(summary.session_evidence_floor, EvidenceTier::EstJ);
    assert_eq!(
        summary.session_provenance_floor.to_jcp_rung(),
        JcpLatticeRung::Estimator {
            coverage: Coverage::Partial
        }
    );

    let mut crashed_and_restored = Runtime::new();
    crashed_and_restored.restore_ledger(ledger);
    assert_eq!(
        crashed_and_restored.spent(&sg.grant.id()),
        spine.runtime.spent(&sg.grant.id())
    );

    let totals = aggregate(&eff_receipts);
    assert_eq!(totals.completed_units, 1);
    assert_eq!(totals.wasted_units, 0);
    assert_eq!(totals.completed_uj, session_total_uj);
    assert_eq!(totals.coverage, Coverage::Partial);
}

#[test]
fn vector_05_coldchain_10k_wakeups_preserves_100pct_critical_alerts_under_minus_20c_sag() {
    let minus20 = run_coldchain_10k_simulation(ColdChainCellProfile::preset_for_temp_c(-20), false);
    let plus4 = run_coldchain_10k_simulation(ColdChainCellProfile::preset_for_temp_c(4), false);
    let plus25 = run_coldchain_10k_simulation(ColdChainCellProfile::preset_for_temp_c(25), false);

    for s in [&minus20, &plus4, &plus25] {
        assert_eq!(s.total_wakeups, 10_000);
        assert!(s.verify_log_ok, "JCR-1 chain must verify at {} C", s.temp_c);
        assert!(
            s.replay_matches_runtime,
            "replay_ledger must match runtime spend at {} C",
            s.temp_c
        );
        assert_eq!(s.critical_alert_attempts, 40);
        assert_eq!(
            s.critical_alert_allowed, 40,
            "100% of critical alerts must survive at {} C",
            s.temp_c
        );
        assert_eq!(s.critical_alert_refused, 0);
        assert!(s.total_debited_uj <= s.usable_energy_uj);
    }

    // At -20 C, severe Arrhenius R_int sag shrinks the routine grant budget to 5,000 uJ
    // (~10 routine beacons allowed, ~490 deterministically refused), whereas +25 C admits
    // vastly more routine beacons — while BOTH preserve 40/40 (100%) critical excursion alerts!
    assert!(
        minus20.routine_beacon_refused > 450,
        "expected deterministic refusal of non-essential beacons at -20 C, got {}",
        minus20.routine_beacon_refused
    );
    assert!(plus4.routine_beacon_allowed > minus20.routine_beacon_allowed);
    assert!(plus25.routine_beacon_allowed > plus4.routine_beacon_allowed);
}
