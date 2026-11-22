//! Unified Ed25519 `COSE_Sign1` canonical det-CBOR `JCR-1` receipt chain spine
//! joining `jcp-runtime`, `jcp-receipt`, `jcp-efficiency`, `SATB-IO` falsifiers,
//! and `openie-cad` (`Material`, `SupplyChain`, `Compute`) session stages.

use ed25519_dalek::SigningKey;
use jcp_efficiency::{Efficiency, EfficiencyLog, EfficiencyReceipt};
use jcp_energy::Rapl;
use jcp_receipt::{jcr1, to_jcr1_wire_logged, ReceiptLog};
use jcp_runtime::{Decision, HoldHandle, HoldId, Ledger, Runtime};
use jcp_schema::{
    ContentId, Did, Energy, FlowFacts, Frame, FrameKind, Grant, SignedGrant, Trust,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use crate::falsifiers::{Falsifier6Gate, Step7SumGate};
use crate::lattice::{CadTract, EvidenceTier, SatbProvenance};

/// Errors produced when sealing or replaying a `JCR-1` spine stream.
#[derive(Debug, thiserror::Error)]
pub enum SpineError {
    #[error("canonical det-CBOR encoding error: {0}")]
    CanonicalCbor(String),
    #[error("receipt log verification failed at sequence {0}")]
    BrokenReceiptChain(usize),
    #[error("ReceiptLog::resume rejected chain at {0:?}")]
    ResumeRejected(String),
    #[error("efficiency/1 chain verification failed at sequence {0}")]
    BrokenEfficiencyChain(usize),
    #[error("COSE_Sign1 decode failed: {0}")]
    CoseDecode(String),
}

/// Input specification for one `openie-cad` stage or `SATB-IO` benchmark attempt.
#[derive(Debug, Clone)]
pub struct StageAttemptSpec {
    pub stage: String,
    pub tract: CadTract,
    pub action: String,
    pub resource: ContentId,
    pub payload_bytes: Vec<u8>,
    pub trust: Trust,
    pub frame_kind: FrameKind,
    pub timestamp_s: u64,
    pub window_us: u64,
    pub backend: String,
    pub provenance: SatbProvenance,
    pub measured_uj: Option<u64>,
    pub reported_uj: Option<u64>,
    pub est_uj: Option<u64>,
    pub idle_bracket_uw: Option<(u64, u64)>,
    pub step7_subphases_uj: Option<Vec<u64>>,
}

impl StageAttemptSpec {
    /// Evaluate Falsifier 6 when pre/post idle baselines are provided.
    pub fn evaluate_falsifier6(&self) -> Option<Falsifier6Gate> {
        let raw_uj = self.measured_uj.or(self.reported_uj)?;
        let (pre_uw, post_uw) = self.idle_bracket_uw?;
        Some(Falsifier6Gate::evaluate(
            raw_uj,
            self.window_us,
            pre_uw,
            post_uw,
        ))
    }

    /// Evaluate Step 7 when sequential sub-phase energies are provided.
    pub fn evaluate_step7(&self) -> Option<Step7SumGate> {
        let phases = self.step7_subphases_uj.as_ref()?;
        let window_uj = self
            .measured_uj
            .or(self.reported_uj)
            .or(self.est_uj)
            .unwrap_or(0);
        Some(Step7SumGate::evaluate(phases, window_uj))
    }

    /// Resolve the `jcp_schema::Energy` figure passed into `jcp_runtime::Runtime`.
    /// When `provenance` maps to `NotAvailable`, falls back to zero-cost `Estimator`
    /// for refusal/audit framing while sealing `"satb_evidence_tier": "not_available"`.
    pub fn runtime_energy(&self) -> Energy {
        let primary_uj = self
            .measured_uj
            .or(self.reported_uj)
            .or(self.est_uj)
            .unwrap_or(0);
        self.provenance
            .to_jcp_energy(primary_uj)
            .unwrap_or_else(|| Energy::estimator(0))
    }

    /// Build strictly canonical det-CBOR-compatible (`u64` + `String` only) extension
    /// members to embed inside the signed `JCR-1` payload.
    pub fn signed_extension_members(&self) -> (Vec<(&'static str, Value)>, Option<Falsifier6Gate>, Option<Step7SumGate>) {
        let rung = self.provenance.to_jcp_rung();
        let f6 = self.evaluate_falsifier6();
        let s7 = self.evaluate_step7();
        let mut ext: Vec<(&'static str, Value)> = vec![
            ("cad_stage", json!(self.stage)),
            ("cad_tract", json!(self.tract.as_str())),
            ("cad_window_us", json!(self.window_us)),
            ("satb_boundary", json!(self.provenance.boundary.as_str())),
            (
                "satb_attribution",
                json!(self.provenance.attribution.as_str()),
            ),
            (
                "satb_evidence_tier",
                json!(rung.evidence_tier().as_str()),
            ),
        ];
        if !self.backend.is_empty() {
            ext.push(("cad_backend", json!(self.backend)));
        }
        if let crate::lattice::JcpLatticeRung::HwShunt { vendor_opaque, .. } = rung {
            ext.push(("satb_vendor_opaque", json!(u64::from(vendor_opaque))));
        }
        if let Some(m) = self.measured_uj {
            ext.push(("satb_measured_uj", json!(m)));
        }
        if let Some(r) = self.reported_uj {
            ext.push(("satb_reported_uj", json!(r)));
        }
        if let Some(e) = self.est_uj {
            ext.push(("satb_est_uj", json!(e)));
        }
        if let Some(gate) = f6 {
            ext.push(("satb_raw_counter_uj", json!(gate.raw_counter_uj)));
            ext.push(("satb_drift_bps", json!(gate.drift_bps)));
            ext.push(("satb_falsifier6_pass", json!(u64::from(gate.passed))));
            if let Some(marginal_uj) = gate.derived_marginal_uj {
                ext.push(("satb_derived_marginal_uj", json!(marginal_uj)));
            }
        }
        if let Some(gate) = s7 {
            ext.push(("satb_step7_residual_uj", json!(gate.residual_uj)));
            ext.push(("satb_step7_pass", json!(u64::from(gate.passed))));
        }
        (ext, f6, s7)
    }
}

/// Active two-phase `hold` ticket carrying both runtime `HoldId` and sealed hold receipt `ContentId`.
#[derive(Debug, Clone)]
pub struct HoldTicket {
    pub hold_id: HoldId,
    pub held_uj: u64,
    pub hold_receipt_cid: ContentId,
    pub frame: Frame,
    pub seq: u64,
}

/// Metadata summary of a sealed `JCR-1` stage receipt.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SealedStageReceipt {
    pub seq: u64,
    pub prev_hex: String,
    pub receipt_cid_hex: String,
    pub envelope_cbor_hex: String,
    pub stage: String,
    pub tract: CadTract,
    pub verdict: String,
    pub deny_reason: Option<String>,
    pub debited_uj: u64,
    pub budget_remaining_uj: u64,
    pub evidence_tier: EvidenceTier,
    pub measured_uj: Option<u64>,
    pub reported_uj: Option<u64>,
    pub est_uj: Option<u64>,
    pub falsifier6: Option<Falsifier6Gate>,
    pub step7: Option<Step7SumGate>,
}

/// Summary returned by end-to-end verification and crash-recovery replay of a spine chain.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReplayAuditSummary {
    pub steward: String,
    pub steward_pubkey_hex: String,
    pub verified_jcr1_entries: usize,
    pub head_cid_hex: String,
    pub replayed_total_debited_uj: u64,
    pub unresolved_holds_count: usize,
    pub session_provenance_floor: SatbProvenance,
    pub session_evidence_floor: EvidenceTier,
    pub efficiency_entries: usize,
}

/// Stateful enforcement + `JCR-1` receipt chain spine across `openie-cad` and `SATB-IO`.
pub struct SpineReceiptChain {
    steward_sk: SigningKey,
    steward: String,
    pub runtime: Runtime,
    seq: u64,
    head: ContentId,
    entries: Vec<Vec<u8>>,
    records: Vec<SealedStageReceipt>,
    efficiency_log: EfficiencyLog,
    provenance_acc: Option<SatbProvenance>,
}

impl SpineReceiptChain {
    pub fn new(steward_sk: SigningKey, steward: impl Into<String>) -> Self {
        let steward_str = steward.into();
        let eff_sk = SigningKey::from_bytes(&steward_sk.to_bytes());
        Self {
            steward_sk,
            steward: steward_str.clone(),
            runtime: Runtime::new(),
            seq: 0,
            head: ContentId([0u8; 32]),
            entries: Vec::new(),
            records: Vec::new(),
            efficiency_log: EfficiencyLog::new(eff_sk, steward_str),
            provenance_acc: None,
        }
    }

    pub fn steward(&self) -> &str {
        &self.steward
    }

    pub fn steward_pubkey(&self) -> [u8; 32] {
        self.steward_sk.verifying_key().to_bytes()
    }

    pub fn head(&self) -> ContentId {
        self.head
    }

    pub fn entries(&self) -> &[Vec<u8>] {
        &self.entries
    }

    pub fn records(&self) -> &[SealedStageReceipt] {
        &self.records
    }

    pub fn efficiency_receipts(&self) -> &[Vec<u8>] {
        self.efficiency_log.receipts()
    }

    /// Probe whether `jcp_energy::Rapl` is readable on the current host.
    pub fn host_rapl_available() -> bool {
        Rapl::open().is_some()
    }

    fn fold_provenance(&mut self, prov: SatbProvenance) {
        self.provenance_acc = Some(match self.provenance_acc {
            Some(cur) => cur.meet(prov),
            None => prov,
        });
    }

    fn seal_wire_object(&mut self, wire: &Value) -> Result<(ContentId, String, Vec<u8>), SpineError> {
        let prev_hex = self.head.to_hex();
        let core_bytes =
            jcr1::signed_core_bytes(wire).map_err(|e| SpineError::CanonicalCbor(e.to_string()))?;
        let env = jcr1::cose_sign1_envelope(&core_bytes, &self.steward_sk, &self.steward);
        let cid = ContentId::of_bytes(&env);
        self.head = cid;
        self.seq += 1;
        self.entries.push(env.clone());
        Ok((cid, prev_hex, env))
    }

    /// Execute a single-phase `Runtime::decide` + SATB falsifier evaluation and seal
    /// the resulting canonical det-CBOR `JCR-1` (`COSE_Sign1` / Ed25519) receipt.
    pub fn decide_and_seal(
        &mut self,
        sg: &SignedGrant,
        caller: Did,
        spec: &StageAttemptSpec,
    ) -> Result<(Decision, SealedStageReceipt), SpineError> {
        let frame = Frame {
            kind: spec.frame_kind,
            trust: spec.trust,
            grant_id: sg.grant.id(),
            action: spec.action.clone(),
            resource: spec.resource,
            payload_hash: ContentId::of_bytes(&spec.payload_bytes),
            model: None,
        };
        let cost = spec.runtime_energy();
        let decision = self
            .runtime
            .decide(&frame, sg, caller, cost, spec.timestamp_s);

        let seq = self.seq;
        let mut wire = to_jcr1_wire_logged(&frame, &sg.grant, &decision, &self.steward, seq, &self.head);
        let (ext, f6, s7) = spec.signed_extension_members();
        if let Value::Object(ref mut map) = wire {
            for (k, v) in ext {
                map.insert(k.to_string(), v);
            }
        }
        let (cid, prev_hex, env) = self.seal_wire_object(&wire)?;
        if decision.is_allow() {
            self.fold_provenance(spec.provenance);
        }

        let (verdict_str, deny_reason) = match decision.verdict {
            jcp_schema::Verdict::Allow => ("allow".to_string(), None),
            jcp_schema::Verdict::Deny(r) => ("deny".to_string(), Some(r.label().to_string())),
        };
        let rec = SealedStageReceipt {
            seq,
            prev_hex,
            receipt_cid_hex: cid.to_hex(),
            envelope_cbor_hex: hex::encode(&env),
            stage: spec.stage.clone(),
            tract: spec.tract,
            verdict: verdict_str,
            deny_reason,
            debited_uj: decision.debited_uj,
            budget_remaining_uj: decision.budget_remaining_uj,
            evidence_tier: spec.provenance.evidence_tier(),
            measured_uj: spec.measured_uj,
            reported_uj: spec.reported_uj,
            est_uj: spec.est_uj,
            falsifier6: f6,
            step7: s7,
        };
        self.records.push(rec.clone());
        Ok((decision, rec))
    }

    /// Phase 1 of JCP two-phase metered enforcement (`SPEC §8.1`): place a budget
    /// hold before physical execution and seal the `held_uj` commitment in `JCR-1`.
    pub fn place_hold_and_seal(
        &mut self,
        sg: &SignedGrant,
        caller: Did,
        stage: &str,
        tract: CadTract,
        action: &str,
        resource: ContentId,
        payload_bytes: &[u8],
        trust: Trust,
        now_s: u64,
    ) -> Result<(Decision, Option<HoldTicket>), SpineError> {
        let frame = Frame {
            kind: FrameKind::ToolCall,
            trust,
            grant_id: sg.grant.id(),
            action: action.to_string(),
            resource,
            payload_hash: ContentId::of_bytes(payload_bytes),
            model: None,
        };
        let (decision, handle): (Decision, Option<HoldHandle>) =
            self.runtime
                .hold(&frame, sg, caller, now_s, &FlowFacts::bottom());
        let seq = self.seq;
        let mut wire =
            to_jcr1_wire_logged(&frame, &sg.grant, &decision, &self.steward, seq, &self.head);
        if let Value::Object(ref mut map) = wire {
            map.insert("cad_stage".to_string(), json!(stage));
            map.insert("cad_tract".to_string(), json!(tract.as_str()));
            if let Some(ref h) = handle {
                if decision.is_allow() {
                    map.insert("held_uj".to_string(), json!(h.uj));
                }
            }
        }
        let (cid, prev_hex, env) = self.seal_wire_object(&wire)?;
        let (verdict_str, deny_reason) = match decision.verdict {
            jcp_schema::Verdict::Allow => ("allow".to_string(), None),
            jcp_schema::Verdict::Deny(r) => ("deny".to_string(), Some(r.label().to_string())),
        };
        self.records.push(SealedStageReceipt {
            seq,
            prev_hex,
            receipt_cid_hex: cid.to_hex(),
            envelope_cbor_hex: hex::encode(&env),
            stage: format!("{stage}.hold"),
            tract,
            verdict: verdict_str,
            deny_reason,
            debited_uj: decision.debited_uj,
            budget_remaining_uj: decision.budget_remaining_uj,
            evidence_tier: EvidenceTier::EstJ,
            measured_uj: None,
            reported_uj: None,
            est_uj: handle.as_ref().map(|h| h.uj),
            falsifier6: None,
            step7: None,
        });
        let ticket = handle.map(|h| HoldTicket {
            hold_id: h.id,
            held_uj: h.uj,
            hold_receipt_cid: cid,
            frame,
            seq,
        });
        Ok((decision, ticket))
    }

    /// Phase 2 of JCP two-phase metered enforcement (`SPEC §8.1`): settle a prior
    /// `HoldTicket` with post-execution energy and seal `"settles"` in `JCR-1`.
    pub fn settle_hold_and_seal(
        &mut self,
        grant: &Grant,
        ticket: &HoldTicket,
        spec: &StageAttemptSpec,
    ) -> Result<(Decision, SealedStageReceipt), SpineError> {
        let energy = spec.runtime_energy();
        let decision =
            self.runtime
                .settle(grant, ticket.hold_id, energy, &FlowFacts::bottom());
        let seq = self.seq;
        let mut wire = to_jcr1_wire_logged(
            &ticket.frame,
            grant,
            &decision,
            &self.steward,
            seq,
            &self.head,
        );
        let (ext, f6, s7) = spec.signed_extension_members();
        if let Value::Object(ref mut map) = wire {
            if decision.consumed_the_hold() {
                map.insert(
                    "settles".to_string(),
                    json!(ticket.hold_receipt_cid.to_hex()),
                );
            }
            for (k, v) in ext {
                map.insert(k.to_string(), v);
            }
        }
        let (cid, prev_hex, env) = self.seal_wire_object(&wire)?;
        if decision.is_allow() {
            self.fold_provenance(spec.provenance);
        }
        let (verdict_str, deny_reason) = match decision.verdict {
            jcp_schema::Verdict::Allow => ("allow".to_string(), None),
            jcp_schema::Verdict::Deny(r) => ("deny".to_string(), Some(r.label().to_string())),
        };
        let rec = SealedStageReceipt {
            seq,
            prev_hex,
            receipt_cid_hex: cid.to_hex(),
            envelope_cbor_hex: hex::encode(&env),
            stage: format!("{}.settle", spec.stage),
            tract: spec.tract,
            verdict: verdict_str,
            deny_reason,
            debited_uj: decision.debited_uj,
            budget_remaining_uj: decision.budget_remaining_uj,
            evidence_tier: spec.provenance.evidence_tier(),
            measured_uj: spec.measured_uj,
            reported_uj: spec.reported_uj,
            est_uj: spec.est_uj,
            falsifier6: f6,
            step7: s7,
        };
        self.records.push(rec.clone());
        Ok((decision, rec))
    }

    /// Append an outcome-anchored `efficiency/1` receipt to the companion efficiency log.
    pub fn append_efficiency(&mut self, eff: &Efficiency) -> Vec<u8> {
        self.efficiency_log.append(eff)
    }

    /// Decode and verify the signed CBOR payload of receipt `seq` under the steward key.
    pub fn decode_verified_payload(&self, seq: usize) -> Result<Value, SpineError> {
        let env = self
            .entries
            .get(seq)
            .ok_or(SpineError::BrokenReceiptChain(seq))?;
        let payload = jcr1::verify_cose_sign1(env, &self.steward, &self.steward_pubkey())
            .map_err(|e| SpineError::CoseDecode(e.to_string()))?;
        jcp_schema::from_canonical_cbor(&payload)
            .map_err(|e| SpineError::CanonicalCbor(e.to_string()))
    }

    /// Verify the entire `JCR-1` stream with `jcp_receipt::verify_log`, confirm
    /// `ReceiptLog::resume` compatibility, replay into `jcp_runtime::Ledger` via
    /// `jcp_receipt::replay_ledger`, and verify any `efficiency/1` receipts.
    pub fn verify_and_replay(&self) -> Result<(Ledger, Vec<EfficiencyReceipt>, ReplayAuditSummary), SpineError> {
        let pk = self.steward_pubkey();
        let verified_count = jcp_receipt::verify_log(&self.entries, &self.steward, &pk)
            .map_err(SpineError::BrokenReceiptChain)?;

        let mut resumed = ReceiptLog::new(
            SigningKey::from_bytes(&self.steward_sk.to_bytes()),
            self.steward.clone(),
        );
        resumed
            .resume(self.entries.clone())
            .map_err(|e| SpineError::ResumeRejected(format!("{e:?}")))?;

        let ledger = jcp_receipt::replay_ledger(
            self.entries.iter().map(Vec::as_slice),
            &self.steward,
            &pk,
        );
        let unresolved = jcp_receipt::unresolved_holds(
            self.entries.iter().map(Vec::as_slice),
            &self.steward,
            &pk,
        );
        let eff_verified =
            jcp_efficiency::verify_chain(self.efficiency_log.receipts(), &self.steward, &pk)
                .map_err(SpineError::BrokenEfficiencyChain)?;

        let total_debited_uj = ledger
            .uj
            .iter()
            .fold(0u64, |acc, (_, v)| acc.saturating_add(*v));
        let floor_prov = self
            .provenance_acc
            .unwrap_or_else(SatbProvenance::unattested_api);

        let summary = ReplayAuditSummary {
            steward: self.steward.clone(),
            steward_pubkey_hex: hex::encode(pk),
            verified_jcr1_entries: verified_count,
            head_cid_hex: self.head.to_hex(),
            replayed_total_debited_uj: total_debited_uj,
            unresolved_holds_count: unresolved.len(),
            session_provenance_floor: floor_prov,
            session_evidence_floor: floor_prov.evidence_tier(),
            efficiency_entries: eff_verified.len(),
        };
        Ok((ledger, eff_verified, summary))
    }
}
