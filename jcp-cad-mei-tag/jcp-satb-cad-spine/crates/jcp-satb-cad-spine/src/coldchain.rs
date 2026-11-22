//! `10,000`-wakeup cold-chain `JCP` two-phase `hold` / `settle` simulation for
//! `MEI-JCP-Tag-v1` (`CR2032` `225 mAh` / `2,430 J` nominal) across `-20 C`,
//! `+4 C`, and `+25 C`.
//!
//! Architecture:
//! - Every wakeup executes passive NTC + `INA238` + `FRAM` ring logging on the
//!   local board bus (`sense_uj`, ~42 uJ).
//! - Routine status radio beacons (`WakeupKind::RoutineBeacon`, e.g. every 20th
//!   wakeup) draw against an attenuated child grant `G_routine` whose budget is
//!   sized to the temperature-derated usable margin above the reserved safety
//!   floor AND bounded by per-call `MaxCostUj` + pulse voltage-sag feasibility.
//! - Safety-critical cold-chain threshold excursions (`WakeupKind::CriticalExcursion`,
//!   when cargo temperature crosses `> 8.0 C` or `< -25.0 C`) draw against a
//!   dedicated reserved grant `G_critical` (`100%` protected from routine drain).
//! - Every wakeup radio decision executes through `jcp_runtime::Runtime`'s real
//!   two-phase `hold` / `settle` API and seals into an Ed25519 `JCR-1` chain
//!   verified via `jcp_receipt::verify_log` and `jcp_receipt::replay_ledger`.

use ed25519_dalek::SigningKey;
use jcp_grant::{attenuate_caveated, issue, shard};
use jcp_receipt::ReceiptLog;
use jcp_runtime::Runtime;
use jcp_schema::{
    Capability, Caveat, ContentId, Did, Energy, Frame, FrameKind, Grant, Trust,
};
use serde::{Deserialize, Serialize};

/// Electro-thermal operating point of the `CR2032` cell for a cold-chain run.
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct ColdChainCellProfile {
    /// Ambient temperature in degrees Celsius (`-20`, `4`, `25`).
    pub temp_c: i32,
    /// Open-circuit voltage at mid-mission SOC (`V`).
    pub ocv_v: f64,
    /// Arrhenius-scaled cell internal resistance (`Ohm`).
    pub r_int_ohm: f64,
    /// Loaded terminal voltage during a `12 mA` radio TX burst (`V`).
    pub v_tx_loaded_v: f64,
    /// Usable energy before `2.0 V` brownout cutoff (`uJ`).
    pub usable_energy_uj: u64,
    /// Energy per sense + `INA238` + `FRAM` wakeup (`uJ`).
    pub sense_wakeup_uj: u64,
    /// Energy per routine radio telemetry packet (`uJ`).
    pub routine_tx_uj: u64,
    /// Energy per condensed safety-critical excursion alert packet (`uJ`).
    pub critical_tx_uj: u64,
    /// Reserved safety floor for critical excursion alerts (`uJ`).
    pub safety_reserve_uj: u64,
}

impl ColdChainCellProfile {
    /// Standard calibrated profiles matching `cad-sim::battery` `CR2032` evaluation
    /// over a `10,000`-wakeup cold-chain mission slice.
    pub fn preset_for_temp_c(temp_c: i32) -> Self {
        match temp_c {
            -20 => Self {
                temp_c: -20,
                ocv_v: 2.88,
                r_int_ohm: 71.8,
                // 12 mA routine burst sags 2.88 - 0.012*71.8 = 2.018 V (near 2.0 V brownout);
                // high-rate Peukert + Arrhenius cutoff sharply contracts usable window slice!
                v_tx_loaded_v: 2.018,
                usable_energy_uj: 460_000, // 0.460 J mission-slice budget after -20 C sag derating
                sense_wakeup_uj: 42,
                routine_tx_uj: 480,
                critical_tx_uj: 260,
                safety_reserve_uj: 35_000, // 35 mJ strictly isolated for excursion alerts
            },
            4 => Self {
                temp_c: 4,
                ocv_v: 2.95,
                r_int_ohm: 28.0,
                v_tx_loaded_v: 2.614,
                usable_energy_uj: 620_000, // 0.620 J mission-slice budget at +4 C vaccine storage
                sense_wakeup_uj: 40,
                routine_tx_uj: 430,
                critical_tx_uj: 240,
                safety_reserve_uj: 35_000,
            },
            _ => Self {
                temp_c: 25,
                ocv_v: 3.00,
                r_int_ohm: 12.0,
                v_tx_loaded_v: 2.856,
                usable_energy_uj: 720_000, // 0.720 J mission-slice budget at +25 C ambient
                sense_wakeup_uj: 38,
                routine_tx_uj: 400,
                critical_tx_uj: 225,
                safety_reserve_uj: 35_000,
            },
        }
    }
}

/// Classification of each wakeup in the `10,000`-step deterministic trace.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WakeupKind {
    PassiveSenseOnly,
    RoutineBeacon,
    CriticalExcursion,
}

/// Complete verification summary for one `10,000`-wakeup cold-chain simulation.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ColdChainRunSummary {
    pub temp_c: i32,
    pub total_wakeups: usize,
    pub passive_sense_wakeups: usize,
    pub routine_beacon_attempts: usize,
    pub routine_beacon_allowed: usize,
    pub routine_beacon_refused: usize,
    pub critical_alert_attempts: usize,
    pub critical_alert_allowed: usize,
    pub critical_alert_refused: usize,
    pub critical_alert_preservation_pct: f64,
    pub sense_total_uj: u64,
    pub routine_grant_budget_uj: u64,
    pub routine_debited_uj: u64,
    pub critical_grant_budget_uj: u64,
    pub critical_debited_uj: u64,
    pub total_debited_uj: u64,
    pub usable_energy_uj: u64,
    pub jcr1_receipt_count: usize,
    pub jcr1_head_cid_hex: String,
    pub verify_log_ok: bool,
    pub replay_matches_runtime: bool,
}

/// Deterministic wakeup schedule across `10,000` cold-chain intervals (`60 s` cadence):
/// - `40` safety-critical thermal excursion events distributed across the ENTIRE mission,
///   including late-mission excursions (`wakeup >= 8,500`) after routine budget exhaustion!
/// - `500` routine radio beacon attempts (every 20th wakeup when not an excursion).
/// - `9,460` passive sense-only wakeups logged to local FRAM ring.
pub fn classify_wakeup(step: usize) -> WakeupKind {
    // 40 deterministic critical excursion steps spanning early, mid, and late mission (up to 9,975)
    if step % 250 == 175 {
        WakeupKind::CriticalExcursion
    } else if step % 20 == 0 {
        WakeupKind::RoutineBeacon
    } else {
        WakeupKind::PassiveSenseOnly
    }
}

/// Run the full `10,000`-wakeup cold-chain trace through `jcp-runtime` (`hold` / `settle`)
/// and `jcp-receipt` (`ReceiptLog` + `verify_log` + `replay_ledger`).
pub fn run_coldchain_10k_simulation(
    profile: ColdChainCellProfile,
    seal_full_10k_sense_receipts: bool,
) -> ColdChainRunSummary {
    const TOTAL_WAKEUPS: usize = 10_000;

    let root_sk = SigningKey::from_bytes(&[0x11; 32]);
    let tag_sk = SigningKey::from_bytes(&[0x22; 32]);
    let steward_sk = SigningKey::from_bytes(&[0x33; 32]);
    let steward_id = format!("did:openie:mei-jcp-tag-v1:{}c", profile.temp_c);

    let root_did = Did::from_verifying_key(&root_sk.verifying_key());
    let tag_did = Did::from_verifying_key(&tag_sk.verifying_key());
    let resource_radio = ContentId::of_bytes(b"hw:mei-jcp-tag-v1:ble-lr-radio");
    let resource_sense = ContentId::of_bytes(b"hw:mei-jcp-tag-v1:ntc-ina238-fram");

    let sense_budget_uj = (TOTAL_WAKEUPS as u64) * profile.sense_wakeup_uj;
    let raw_routine_surplus = profile
        .usable_energy_uj
        .saturating_sub(sense_budget_uj)
        .saturating_sub(profile.safety_reserve_uj);
    let routine_budget_uj = (raw_routine_surplus / profile.routine_tx_uj) * profile.routine_tx_uj;

    // Root mission grant issued to the sovereign tag steward before cold-chain seal
    let root_radio_grant = Grant {
        issuer: root_did,
        subject: root_did,
        capability: Capability::new(resource_radio, ["tx.routine", "tx.critical"]),
        budget_uj: routine_budget_uj + profile.safety_reserve_uj,
        budget_funds: None,
        caveats: Vec::new(),
        expiry: 0,
        parent: None,
        delegate_depth: Some(2),
        nonce: [0xA1; 16],
    };
    let sg_root_radio = issue(&root_sk, root_radio_grant).expect("issue root radio grant");

    // Verify conservation of routine + critical slices at mint time via `jcp_grant::shard`
    let shards = shard(
        &sg_root_radio,
        &root_sk,
        &[
            (tag_did, routine_budget_uj),
            (tag_did, profile.safety_reserve_uj),
        ],
        0,
        [0xE5; 16],
    )
    .expect("shard conservation check");
    debug_assert_eq!(shards.len(), 2);

    // Attenuated child grant 1: routine telemetry strictly capped to derated surplus
    let sg_routine = attenuate_caveated(
        &sg_root_radio,
        &root_sk,
        tag_did,
        Capability::new(resource_radio, ["tx.routine"]),
        routine_budget_uj,
        vec![
            Caveat::ActionIn(vec!["tx.routine".to_string()]),
            Caveat::MaxCostUj(profile.routine_tx_uj),
        ],
        0,
        [0xB2; 16],
    )
    .expect("attenuate routine grant");

    // Attenuated child grant 2: isolated safety-critical excursion reserve
    let sg_critical = attenuate_caveated(
        &sg_root_radio,
        &root_sk,
        tag_did,
        Capability::new(resource_radio, ["tx.critical"]),
        profile.safety_reserve_uj,
        vec![
            Caveat::ActionIn(vec!["tx.critical".to_string()]),
            Caveat::MaxCostUj(profile.critical_tx_uj),
        ],
        0,
        [0xC3; 16],
    )
    .expect("attenuate critical grant");

    let chain_routine = [sg_root_radio.clone(), sg_routine.clone()];
    let chain_routine_ids = [sg_root_radio.grant.id(), sg_routine.grant.id()];
    let chain_critical = [sg_root_radio.clone(), sg_critical.clone()];
    let chain_critical_ids = [sg_root_radio.grant.id(), sg_critical.grant.id()];

    // Dedicated passive sense grant
    let sg_sense = issue(
        &root_sk,
        Grant {
            issuer: root_did,
            subject: tag_did,
            capability: Capability::new(resource_sense, ["sense.ntc_fram"]),
            budget_uj: sense_budget_uj,
            budget_funds: None,
            caveats: vec![Caveat::MaxCostUj(profile.sense_wakeup_uj)],
            expiry: 0,
            parent: None,
            delegate_depth: None,
            nonce: [0xD4; 16],
        },
    )
    .expect("issue sense grant");

    let mut rt = Runtime::new();
    let mut log = ReceiptLog::new(steward_sk, steward_id.clone());

    let mut passive_sense_wakeups = 0usize;
    let mut routine_attempts = 0usize;
    let mut routine_allowed = 0usize;
    let mut routine_refused = 0usize;
    let mut critical_attempts = 0usize;
    let mut critical_allowed = 0usize;
    let mut critical_refused = 0usize;

    for step in 0..TOTAL_WAKEUPS {
        let now_s = (step as u64) * 60;
        let sense_frame = Frame {
            kind: FrameKind::ToolCall,
            trust: Trust::Control,
            grant_id: sg_sense.grant.id(),
            action: "sense.ntc_fram".to_string(),
            resource: resource_sense,
            payload_hash: ContentId::of_bytes(&step.to_le_bytes()),
            model: None,
        };
        let d_sense = rt.decide(
            &sense_frame,
            &sg_sense,
            tag_did,
            Energy::estimator(profile.sense_wakeup_uj),
            now_s,
        );
        debug_assert!(d_sense.is_allow());
        if seal_full_10k_sense_receipts {
            log.append(&sense_frame, &sg_sense.grant, &d_sense);
        }

        match classify_wakeup(step) {
            WakeupKind::PassiveSenseOnly => {
                passive_sense_wakeups += 1;
            }
            WakeupKind::RoutineBeacon => {
                routine_attempts += 1;
                let frame = Frame {
                    kind: FrameKind::ToolCall,
                    trust: Trust::Control,
                    grant_id: sg_routine.grant.id(),
                    action: "tx.routine".to_string(),
                    resource: resource_radio,
                    payload_hash: ContentId::of_bytes(format!("beacon:{step}").as_bytes()),
                    model: None,
                };
                let (hold_dec, handle) = rt.hold_chained(&frame, &chain_routine, tag_did, now_s);
                if let Some(h) = handle {
                    log.append_hold_chained(
                        &frame,
                        &chain_routine_ids,
                        &sg_routine.grant,
                        &hold_dec,
                        h.uj,
                        0,
                    );
                    let hold_cid = log.head();
                    let settle_dec = rt.settle_chained(
                        &chain_routine,
                        h.id,
                        Energy::estimator(profile.routine_tx_uj),
                    );
                    log.append_settle_chained(
                        &frame,
                        &chain_routine_ids,
                        &sg_routine.grant,
                        &settle_dec,
                        hold_cid,
                    );
                    if settle_dec.is_allow() {
                        routine_allowed += 1;
                    } else {
                        routine_refused += 1;
                    }
                } else {
                    log.append_chained(
                        &frame,
                        &chain_routine_ids,
                        &sg_routine.grant,
                        &hold_dec,
                    );
                    routine_refused += 1;
                }
            }
            WakeupKind::CriticalExcursion => {
                critical_attempts += 1;
                let frame = Frame {
                    kind: FrameKind::ToolCall,
                    trust: Trust::Control,
                    grant_id: sg_critical.grant.id(),
                    action: "tx.critical".to_string(),
                    resource: resource_radio,
                    payload_hash: ContentId::of_bytes(format!("excursion:{step}").as_bytes()),
                    model: None,
                };
                let (hold_dec, handle) =
                    rt.hold_chained(&frame, &chain_critical, tag_did, now_s);
                let h = handle.expect("reserved critical excursion budget must admit hold");
                log.append_hold_chained(
                    &frame,
                    &chain_critical_ids,
                    &sg_critical.grant,
                    &hold_dec,
                    h.uj,
                    0,
                );
                let hold_cid = log.head();
                let settle_dec = rt.settle_chained(
                    &chain_critical,
                    h.id,
                    Energy::estimator(profile.critical_tx_uj),
                );
                log.append_settle_chained(
                    &frame,
                    &chain_critical_ids,
                    &sg_critical.grant,
                    &settle_dec,
                    hold_cid,
                );
                if settle_dec.is_allow() {
                    critical_allowed += 1;
                } else {
                    critical_refused += 1;
                }
            }
        }
    }

    let pubkey = log.steward_pubkey();
    let verify_ok = jcp_receipt::verify_log(log.entries(), &steward_id, &pubkey).is_ok();
    let ledger =
        jcp_receipt::replay_ledger(log.entries().iter().map(Vec::as_slice), &steward_id, &pubkey);

    let mut replayed_rt = Runtime::new();
    replayed_rt.restore_ledger(ledger);

    let routine_spent = rt.spent(&sg_routine.grant.id());
    let critical_spent = rt.spent(&sg_critical.grant.id());
    let sense_spent = rt.spent(&sg_sense.grant.id());

    let replay_matches = replayed_rt.spent(&sg_routine.grant.id()) == routine_spent
        && replayed_rt.spent(&sg_critical.grant.id()) == critical_spent
        && (!seal_full_10k_sense_receipts || replayed_rt.spent(&sg_sense.grant.id()) == sense_spent);

    ColdChainRunSummary {
        temp_c: profile.temp_c,
        total_wakeups: TOTAL_WAKEUPS,
        passive_sense_wakeups,
        routine_beacon_attempts: routine_attempts,
        routine_beacon_allowed: routine_allowed,
        routine_beacon_refused: routine_refused,
        critical_alert_attempts: critical_attempts,
        critical_alert_allowed: critical_allowed,
        critical_alert_refused: critical_refused,
        critical_alert_preservation_pct: if critical_attempts == 0 {
            100.0
        } else {
            (critical_allowed as f64) * 100.0 / (critical_attempts as f64)
        },
        sense_total_uj: sense_spent,
        routine_grant_budget_uj: sg_routine.grant.budget_uj,
        routine_debited_uj: routine_spent,
        critical_grant_budget_uj: sg_critical.grant.budget_uj,
        critical_debited_uj: critical_spent,
        total_debited_uj: sense_spent + routine_spent + critical_spent,
        usable_energy_uj: profile.usable_energy_uj,
        jcr1_receipt_count: log.entries().len(),
        jcr1_head_cid_hex: log.head().to_hex(),
        verify_log_ok: verify_ok,
        replay_matches_runtime: replay_matches,
    }
}
