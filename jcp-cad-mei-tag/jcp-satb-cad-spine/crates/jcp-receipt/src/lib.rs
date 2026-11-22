//! The JCP receipt (SPEC §8).
//!
//! Every decision the runtime makes — **allow and deny alike** — seals as a
//! signed JCR-1 record of who acted, what grant they exercised, the verdict (and
//! reason, if denied), the joules it cost, and the budget left. Unlike an
//! OpenTelemetry span, a receipt is non-repudiable: forging the audit means
//! forging a signature. Receipts seal as the family's shared JCR-1 envelope
//! (canonical det-CBOR + COSE_Sign1/EdDSA), so a JCP receipt verifies with the
//! same tooling as a Sandbox, Map, or proof receipt.

use ed25519_dalek::SigningKey;
use jcp_runtime::Decision;
use jcp_schema::{ContentId, Frame, Grant, Verdict};
use serde_json::{json, Value};

pub mod jcr1;

/// Errors from sealing or verifying a receipt.
#[derive(Debug, thiserror::Error)]
pub enum ReceiptError {
    #[error("envelope payload does not match the decision")]
    PayloadMismatch,
    #[error("unknown receipt profile: {0}")]
    UnknownProfile(String),
    #[error(transparent)]
    Jcr1(#[from] jcr1::Jcr1Error),
}

/// The receipt profile this library **mints**. `jcp/2` adds `payload_hash` to
/// the signed core (SPEC §8), so a receipt binds *what was acted upon*, not only
/// that a decision happened.
pub const PROFILE: &str = "jcp/2";

/// The predecessor profile. Receipts sealed under it are still **verifiable**
/// (see [`verify`]), but are no longer minted.
pub const PROFILE_V1: &str = "jcp/1";

/// The **flow** profile (SPEC §8, §4.10): `jcp/2` plus a `flow` block recording a
/// call's propagated provenance verdict. Minted **only** when a call is tainted;
/// a clean call still seals as [`PROFILE`] (`jcp/2`), byte-for-byte, so nothing
/// on the existing path moves.
pub const PROFILE_FLOW: &str = "jcp/3";

/// What a flow verdict seals: the argument's provenance facts and, if the grant
/// carried one, the digest of the flow ceiling it was tested against. A `None`
/// or bottom `facts` means the call was clean and the receipt stays `jcp/2`.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct FlowSeal {
    pub facts: Option<jcp_schema::FlowFacts>,
    /// The ceiling's content id ([`jcp_schema::FlowCeiling`] digest), if any.
    pub ceiling: Option<jcp_schema::ContentId>,
}

impl FlowSeal {
    /// A clean seal — the call touched no untrusted provenance, so the receipt is
    /// an ordinary `jcp/2`.
    pub fn clean() -> Self {
        FlowSeal { facts: None, ceiling: None }
    }

    /// Is this seal tainted (a non-bottom label)? Decides whether a receipt is
    /// minted as `jcp/3` rather than `jcp/2`.
    fn is_tainted(&self) -> bool {
        self.facts.as_ref().is_some_and(|f| !f.is_bottom())
    }
}


/// Project a decision to the **legacy `jcp/1`** wire — byte-for-byte what this
/// library sealed before `payload_hash` existed. Retained solely so previously
/// sealed receipts keep verifying; never used to mint.
fn to_jcr1_wire_v1(frame: &Frame, grant: &Grant, decision: &Decision, steward: &str) -> Value {
    let mut wire = to_jcr1_wire(frame, grant, decision, steward);
    if let Value::Object(ref mut o) = wire {
        o.insert("jcp_receipt".into(), json!(PROFILE_V1));
        o.remove("payload_hash");
    }
    wire
}

/// Project a decision to JCR-1 wire JSON — the [`PROFILE`] (`jcp/2`) core
/// (SPEC §8). A flat uint/text map; fields that don't apply (a deny reason on an
/// allow) are omitted.
/// The attested environment a decision was recorded in.
///
/// # The hole this closes
///
/// A JCP receipt proves that *this steward decided this, and signed it*. It says
/// nothing about the machine the steward was running on. Sandbox roots a
/// separate chain in hardware — a measured boot, a TEE quote, an append-only
/// audit head — and until now the two chains never referred to each other. Both
/// halves existed and neither named the other, so a compromised harness could
/// emit a perfectly valid, perfectly verifiable chain of decisions.
///
/// This is the reference from the action chain to the attested one.
///
/// # What carrying it does NOT establish
///
/// It is a **pointer, not evidence**. A host that will misreport its decisions
/// can equally write an attestation id it did not earn. The binding becomes
/// worth something only when a verifier resolves that id, checks the
/// attestation verifies under a Supervisor key it trusts, and confirms the
/// attestation actually covers this host and this time window — all of which is
/// `sandbox-attest`'s job, not this crate's. `jcp-receipt` takes no dependency
/// on `sandbox-attest` and performs no resolution.
///
/// So a receipt carrying an environment is not "attested"; it is *claiming an
/// environment a verifier can go and check*. The difference is the whole point,
/// and [`Decision`]-side code must not collapse it.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct EnvironmentBinding {
    /// Content address of the sandbox attestation for the run this host is
    /// inside.
    pub attestation_id: ContentId,
    /// The isolation tier that attestation claims, as its wire tag. Carried so
    /// a reader can see the claim without resolving it — and so a mismatch
    /// against the resolved attestation is detectable.
    pub tier: String,
}

impl EnvironmentBinding {
    /// Name the attestation this host is running under.
    pub fn new(attestation_id: ContentId, tier: impl Into<String>) -> Self {
        EnvironmentBinding { attestation_id, tier: tier.into() }
    }
}

/// The JCR-1 wire for a decision recorded inside an attested environment.
///
/// Identical to [`to_jcr1_wire`] when `environment` is `None`, field for field —
/// so every receipt sealed before this existed, and every published vector,
/// canonicalizes to the same bytes and still verifies.
pub fn to_jcr1_wire_in_environment(
    frame: &Frame,
    grant: &Grant,
    decision: &Decision,
    steward: &str,
    environment: Option<&EnvironmentBinding>,
) -> Value {
    let mut v = to_jcr1_wire(frame, grant, decision, steward);
    if let (Some(env), Some(obj)) = (environment, v.as_object_mut()) {
        obj.insert(
            "environment".into(),
            json!({ "attestation": env.attestation_id.to_hex(), "tier": env.tier }),
        );
    }
    v
}

/// A **relying-party** check: refuse a receipt that does not name the
/// environment it was recorded in.
///
/// Passing does not mean the environment was verified — see
/// [`EnvironmentBinding`]. It means the receipt points at an attestation, which
/// the caller must now resolve. A caller that stops here has learned only that
/// the host was willing to name something.
pub fn environment_of(wire: &Value) -> Option<EnvironmentBinding> {
    let env = wire.get("environment")?;
    let id = env.get("attestation").and_then(Value::as_str)?;
    let tier = env.get("tier").and_then(Value::as_str)?;
    Some(EnvironmentBinding {
        attestation_id: ContentId::from_hex(id).ok()?,
        tier: tier.to_string(),
    })
}

pub fn to_jcr1_wire(frame: &Frame, grant: &Grant, decision: &Decision, steward: &str) -> Value {
    let mut obj = serde_json::Map::new();
    obj.insert("jcp_receipt".into(), json!(PROFILE));
    obj.insert("grant_id".into(), json!(grant.id().to_hex()));
    obj.insert("issuer".into(), json!(grant.issuer.to_did_key()));
    obj.insert("subject".into(), json!(grant.subject.to_did_key()));
    obj.insert("resource".into(), json!(frame.resource.to_hex()));
    obj.insert("action".into(), json!(frame.action));
    // What the decision was ACTUALLY over. Without this a receipt proves a
    // decision happened for an action but not on what payload — a tool-call
    // receipt would not bind its arguments.
    obj.insert("payload_hash".into(), json!(frame.payload_hash.to_hex()));
    obj.insert("frame_kind".into(), json!(frame_kind_tag(frame)));
    obj.insert("trust".into(), json!(trust_tag(frame)));
    obj.insert("verdict".into(), json!(decision.verdict.wire_tag()));
    if let Verdict::Deny(reason) = decision.verdict {
        obj.insert("deny_reason".into(), json!(reason.label()));
    }
    obj.insert("cost_uj".into(), json!(decision.cost.uj()));
    obj.insert("energy_provenance".into(), json!(decision.cost.provenance.jcr1_label()));
    // Coverage rides beside provenance, but only when it is `Partial`: the
    // whole-task case is the default and is omitted, so every receipt sealed
    // before this field existed canonicalizes to the same bytes and still
    // verifies. Without this the distinction would exist in the type and vanish
    // in the artifact, which is the failure the field was added to prevent — a
    // partial reading would reach a verifier looking exactly like a whole one.
    if !decision.cost.coverage.is_whole() {
        obj.insert("energy_coverage".into(), json!(decision.cost.coverage.label()));
    }
    obj.insert("budget_remaining_uj".into(), json!(decision.budget_remaining_uj));
    obj.insert("budget_uj".into(), json!(grant.budget_uj));
    obj.insert("steward".into(), json!(steward));
    if debit_is_stated(decision) {
        obj.insert("debited_uj".into(), json!(decision.debited_uj));
    }
    if decision.debited_minor != 0 {
        obj.insert("debited_minor".into(), json!(decision.debited_minor));
    }
    let mut wire = Value::Object(obj);
    state_tainted(&mut wire, decision);
    wire
}

/// Whether a reader finds that a decision's receipt debited (SPEC §8.1): an
/// allow always, and a denial where it states a debit. Read off the leaf's
/// figure, since only an unchained receipt carries a `flow` block.
fn reads_as_debited(decision: &Decision) -> bool {
    decision.is_allow() || decision.debited_uj != 0
}

/// State what a decision accrued against a tainted sub-budget (SPEC §4.10)
/// wherever its receipt would read otherwise without the member (§8.1): a
/// receipt carrying a `flow` block that debited reads as having accrued its
/// `cost_uj`, which is what a tainted call accrues, and any other receipt as
/// having accrued nothing. So a tainted call sealed with its flow block keeps
/// the bytes it always had. A builder that adds the block calls this again.
fn state_tainted(wire: &mut Value, decision: &Decision) {
    if let Value::Object(o) = wire {
        let read = if o.contains_key("flow") && reads_as_debited(decision) { decision.cost.uj() } else { 0 };
        if decision.tainted_uj == read {
            o.remove("tainted_uj");
        } else {
            o.insert("tainted_uj".into(), json!(decision.tainted_uj));
        }
    }
}

/// Whether `reason` can be sealed from the debit point, after the work ran and
/// its joules were debited (SPEC §4.9, §4.12). Both reasons can also refuse a
/// call before any work, with nothing debited.
fn may_follow_a_debit(reason: &str) -> bool {
    matches!(reason, "caveat-unsatisfied" | "window-exceeded")
}

/// Whether the core must state what a decision debited (SPEC §8.1): wherever
/// the verdict alone would read otherwise, and on every denial that can follow
/// a debit, so the absence of `debited_uj` there can only mean a receipt sealed
/// before the member existed. Every other receipt keeps the bytes it always had.
fn debit_is_stated(decision: &Decision) -> bool {
    match decision.verdict {
        Verdict::Allow => decision.debited_uj != decision.cost.uj(),
        Verdict::Deny(reason) => decision.debited_uj != 0 || may_follow_a_debit(reason.label()),
    }
}

/// The members the `jcp/2` core gained after it was first minted, newest
/// first, a generation per entry (SPEC §8.1).
const LATER_MEMBERS: [&[&str]; 2] =
    [&["debited_minor", "chain_debited_minor", "tainted_uj"], &["debited_uj", "chain_debited_uj"]];

/// Check a verified payload against the core a decision projects to.
///
/// A receipt sealed before a generation of members existed recomputes without
/// it, and without every later one, so it keeps verifying (SPEC §8.1). Such an
/// envelope does not bind what those members state, which is the most it can
/// say; one that carries them must match them.
fn check_core(payload: &[u8], mut wire: Value) -> Result<(), ReceiptError> {
    if payload == jcr1::signed_core_bytes(&wire)? {
        return Ok(());
    }
    for generation in LATER_MEMBERS {
        let mut dropped = false;
        if let Value::Object(ref mut o) = wire {
            for member in generation {
                dropped |= o.remove(*member).is_some();
            }
        }
        if dropped && payload == jcr1::signed_core_bytes(&wire)? {
            return Ok(());
        }
    }
    Err(ReceiptError::PayloadMismatch)
}

/// The `flow` block of a `jcp/3` receipt: the sealed provenance verdict. All
/// text/uint/array (no float/bool/null), so it survives canonical CBOR, and the
/// witness is a **commitment** — the artifact itself is disclosed out of band, not
/// carried here.
fn flow_block(facts: &jcp_schema::FlowFacts, seal: &FlowSeal, decision: &Decision) -> Value {
    use jcp_schema::flow::{Integrity, Origins, Readers};
    let label = &facts.label;
    let integrity = match label.integrity {
        Integrity::Untrusted => "untrusted",
        Integrity::Derived => "derived",
        Integrity::Attested => "attested",
        Integrity::Principal => "principal",
    };
    let origins = match &label.origins {
        Origins::Any => json!("any"),
        Origins::Set(set) => {
            Value::Array(set.iter().map(|o| json!(o.channel.to_hex())).collect())
        }
    };
    let readers = match &label.readers {
        Readers::Public => json!("public"),
        Readers::Only(dids) => {
            Value::Array(dids.iter().map(|d| json!(d.to_did_key())).collect())
        }
    };
    // The flow verdict is about the gate specifically: "above" the ceiling exactly
    // when the decision was denied for flow. A tainted call denied for another
    // reason (or allowed under a permissive ceiling) passed the flow gate: "below".
    let verdict = if decision.verdict == Verdict::Deny(jcp_schema::DenyReason::TaintedFlow) {
        "above"
    } else {
        "below"
    };
    let mut block = serde_json::Map::new();
    block.insert("label".into(), json!(label.digest().map(|c| c.to_hex()).unwrap_or_default()));
    block.insert("integrity".into(), json!(integrity));
    block.insert("origins".into(), origins);
    block.insert("readers".into(), readers);
    block.insert("witness".into(), json!(facts.witness_id.to_hex()));
    if let Some(ceiling) = &seal.ceiling {
        block.insert("ceiling".into(), json!(ceiling.to_hex()));
    }
    block.insert("verdict".into(), json!(verdict));
    // The monitor's own evaluation cost — sealed as its OWN field, never folded
    // into `cost_uj` (the tool's energy), so a call's energy keeps its meaning.
    block.insert("flow_uj".into(), json!(facts.eval_uj));
    block.insert("flow_energy_provenance".into(), json!(facts.eval_prov.jcr1_label()));
    Value::Object(block)
}

/// Project a decision to flow-aware wire JSON. When the call is clean this is
/// byte-for-byte [`to_jcr1_wire`] (`jcp/2`); when tainted it is `jcp/3` — the same
/// core plus a `flow` block. The clean case producing identical bytes is what lets
/// a non-flow deployment and a flow deployment share a receipt stream.
pub fn to_jcr1_wire_flow(
    frame: &Frame,
    grant: &Grant,
    decision: &Decision,
    steward: &str,
    seal: &FlowSeal,
) -> Value {
    let mut wire = to_jcr1_wire(frame, grant, decision, steward);
    if seal.is_tainted() {
        if let (Value::Object(ref mut o), Some(facts)) = (&mut wire, &seal.facts) {
            o.insert("jcp_receipt".into(), json!(PROFILE_FLOW));
            o.insert("flow".into(), flow_block(facts, seal, decision));
        }
        state_tainted(&mut wire, decision);
    }
    wire
}

/// Seal a decision with its flow verdict. A clean call yields an ordinary `jcp/2`
/// envelope indistinguishable from [`seal`]; a tainted call yields `jcp/3`.
pub fn seal_flow(
    frame: &Frame,
    grant: &Grant,
    decision: &Decision,
    key: &SigningKey,
    steward: &str,
    seal: &FlowSeal,
) -> Result<Vec<u8>, ReceiptError> {
    let core = jcr1::signed_core_bytes(&to_jcr1_wire_flow(frame, grant, decision, steward, seal))?;
    Ok(jcr1::cose_sign1_envelope(&core, key, steward))
}

/// Verify a flow envelope: like [`verify`], but recomputes the `jcp/3` core from
/// the same `seal`, so a `jcp/3` receipt round-trips. A `jcp/2` envelope (a clean
/// call) verifies here too, since a clean seal recomputes the `jcp/2` core.
pub fn verify_flow(
    frame: &Frame,
    grant: &Grant,
    decision: &Decision,
    seal: &FlowSeal,
    envelope: &[u8],
    steward: &str,
    pubkey: &[u8; 32],
) -> Result<(), ReceiptError> {
    let payload = jcr1::verify_cose_sign1(envelope, steward, pubkey)?;
    let expected = match profile_of(&payload)?.as_str() {
        PROFILE | PROFILE_FLOW => to_jcr1_wire_flow(frame, grant, decision, steward, seal),
        PROFILE_V1 => to_jcr1_wire_v1(frame, grant, decision, steward),
        other => return Err(ReceiptError::UnknownProfile(other.to_string())),
    };
    check_core(&payload, expected)
}

fn frame_kind_tag(f: &Frame) -> &'static str {
    use jcp_schema::FrameKind::*;
    match f.kind {
        ToolCall => "tool-call",
        ToolResult => "tool-result",
        AgentTask => "agent-task",
        AgentReply => "agent-reply",
    }
}

fn trust_tag(f: &Frame) -> &'static str {
    match f.trust {
        jcp_schema::Trust::Control => "control",
        jcp_schema::Trust::Data => "data",
    }
}

/// The canonical signed-core bytes (JCR-1 det-CBOR) for a decision.
pub fn signed_core(
    frame: &Frame,
    grant: &Grant,
    decision: &Decision,
    steward: &str,
) -> Result<Vec<u8>, ReceiptError> {
    Ok(jcr1::signed_core_bytes(&to_jcr1_wire(frame, grant, decision, steward))?)
}

/// Project a CHAINED decision to JCR-1 wire JSON: the leaf grant's fields plus
/// `chain_ids` — every grant id in the delegation chain, root first — so the
/// receipt records every budget the decision debited and replay (§8.1) can
/// re-apply ancestor debits with no external index. Where a capped debit left
/// the links differing, `chain_debited_uj` says what each was debited, and
/// `chain_debited_minor` does for money where a link had no money ceiling.
/// For a one-link chain all three are omitted and the bytes are identical to
/// [`to_jcr1_wire`].
pub fn to_jcr1_wire_chained(
    frame: &Frame,
    chain_ids: &[jcp_schema::ContentId],
    leaf: &Grant,
    decision: &Decision,
    steward: &str,
) -> Value {
    let mut wire = to_jcr1_wire(frame, leaf, decision, steward);
    if chain_ids.len() > 1 {
        if let Value::Object(ref mut obj) = wire {
            obj.insert(
                "chain_ids".into(),
                Value::Array(chain_ids.iter().map(|c| json!(c.to_hex())).collect()),
            );
            if !decision.chain_debited_uj.is_empty() {
                obj.insert("chain_debited_uj".into(), json!(decision.chain_debited_uj));
            }
            if !decision.chain_debited_minor.is_empty() {
                obj.insert("chain_debited_minor".into(), json!(decision.chain_debited_minor));
            }
        }
    }
    wire
}

/// The canonical signed-core bytes for a chained decision.
pub fn signed_core_chained(
    frame: &Frame,
    chain_ids: &[jcp_schema::ContentId],
    leaf: &Grant,
    decision: &Decision,
    steward: &str,
) -> Result<Vec<u8>, ReceiptError> {
    Ok(jcr1::signed_core_bytes(&to_jcr1_wire_chained(frame, chain_ids, leaf, decision, steward))?)
}

/// Seal a chained decision. Identical to [`seal`] for a one-link chain.
pub fn seal_chained(
    frame: &Frame,
    chain_ids: &[jcp_schema::ContentId],
    leaf: &Grant,
    decision: &Decision,
    key: &SigningKey,
    steward: &str,
) -> Result<Vec<u8>, ReceiptError> {
    let core = signed_core_chained(frame, chain_ids, leaf, decision, steward)?;
    Ok(jcr1::cose_sign1_envelope(&core, key, steward))
}

/// Verify a chained receipt against the full chain ids it should record.
pub fn verify_chained(
    frame: &Frame,
    chain_ids: &[jcp_schema::ContentId],
    leaf: &Grant,
    decision: &Decision,
    envelope: &[u8],
    steward: &str,
    pubkey: &[u8; 32],
) -> Result<(), ReceiptError> {
    let payload = jcr1::verify_cose_sign1(envelope, steward, pubkey)?;
    let expected = match profile_of(&payload)?.as_str() {
        PROFILE => to_jcr1_wire_chained(frame, chain_ids, leaf, decision, steward),
        PROFILE_V1 => {
            // The v1 chained projection: the v1 core plus `chain_ids`, exactly
            // as `to_jcr1_wire_chained` layered it before `payload_hash`.
            let mut wire = to_jcr1_wire_v1(frame, leaf, decision, steward);
            if chain_ids.len() > 1 {
                if let Value::Object(ref mut obj) = wire {
                    obj.insert(
                        "chain_ids".into(),
                        Value::Array(chain_ids.iter().map(|c| json!(c.to_hex())).collect()),
                    );
                }
            }
            wire
        }
        other => return Err(ReceiptError::UnknownProfile(other.to_string())),
    };
    check_core(&payload, expected)
}

/// Seal a decision into a JCR-1 COSE_Sign1 envelope. Both allows and denies are
/// sealed — the deny audit is as load-bearing as the allow audit.
pub fn seal(
    frame: &Frame,
    grant: &Grant,
    decision: &Decision,
    key: &SigningKey,
    steward: &str,
) -> Result<Vec<u8>, ReceiptError> {
    let core = signed_core(frame, grant, decision, steward)?;
    Ok(jcr1::cose_sign1_envelope(&core, key, steward))
}

/// The enforcement point doing the sealing: its key, its id, and how current
/// its revocation knowledge is.
///
/// One value rather than three arguments repeated across every seal, because it
/// is one thing — the point — and the members a receipt states about the point
/// are the same on every receipt it seals.
#[derive(Clone, Copy)]
pub struct Sealer<'a> {
    /// The signing key.
    pub key: &'a SigningKey,
    /// The steward id, which becomes the COSE `kid`.
    pub steward: &'a str,
    /// The point's revocation marker (SPEC §4.3), where it has declared one.
    ///
    /// Read it from the enforcement point that decided —
    /// `Runtime::revocation_marker` — rather than inventing one: a marker the
    /// sealer made up says nothing about what the decider knew. `None` is
    /// omitted from the receipt, which keeps "did not say" distinguishable from
    /// "said 0" and leaves the core byte-identical to one sealed by [`seal`].
    pub known_through: Option<u64>,
}

impl<'a> Sealer<'a> {
    /// A point that has not declared a revocation marker.
    pub fn new(key: &'a SigningKey, steward: &'a str) -> Self {
        Sealer { key, steward, known_through: None }
    }

    /// The same point, declaring `marker`.
    pub fn known_through(mut self, marker: Option<u64>) -> Self {
        self.known_through = marker;
        self
    }
}

/// [`seal`], stating what the receipt says about the point that sealed it
/// (SPEC §4.3).
pub fn seal_from_point(
    frame: &Frame,
    grant: &Grant,
    decision: &Decision,
    sealer: &Sealer<'_>,
) -> Result<Vec<u8>, ReceiptError> {
    seal_stating(
        frame,
        grant,
        decision,
        sealer.key,
        sealer.steward,
        &point_members(sealer.known_through),
    )
}

/// The members a receipt states about the point that sealed it.
fn point_members(known_through: Option<u64>) -> Vec<(&'static str, Value)> {
    match known_through {
        Some(m) => vec![("known_through", json!(m))],
        None => Vec::new(),
    }
}

/// Seal a decision as a **hold** (SPEC §8.1) outside a hash-chained log:
/// [`seal`] stating `held_uj`, and `held_minor` where the hold reserved money
/// (§4.8).
///
/// The logged form is [`ReceiptLog::append_hold`]. This one exists because a
/// gateway that seals decisions without a log would otherwise have no way to
/// record a hold at all, and a hold a receipt does not state is a reservation
/// no replay can restore — the enforcement point would come back from a restart
/// with the interrupted charge payable a second time.
pub fn seal_hold(
    frame: &Frame,
    grant: &Grant,
    decision: &Decision,
    sealer: &Sealer<'_>,
    held_uj: u64,
    held_minor: u64,
) -> Result<Vec<u8>, ReceiptError> {
    let mut stated = point_members(sealer.known_through);
    stated.extend(hold_members(decision, held_uj, held_minor));
    seal_stating(frame, grant, decision, sealer.key, sealer.steward, &stated)
}

/// Seal the accounting decision of work a hold let run, naming the hold it
/// settles (SPEC §8.1): [`seal`] stating `settles`. The logged form is
/// [`ReceiptLog::append_settle`].
pub fn seal_settle(
    frame: &Frame,
    grant: &Grant,
    decision: &Decision,
    sealer: &Sealer<'_>,
    hold: jcp_schema::ContentId,
) -> Result<Vec<u8>, ReceiptError> {
    let mut stated = point_members(sealer.known_through);
    stated.extend(settle_members(decision, hold));
    seal_stating(frame, grant, decision, sealer.key, sealer.steward, &stated)
}

/// Seal a partial capture against a hold (SPEC §8.1) outside a log: the
/// unlogged form of [`ReceiptLog::append_capture`].
pub fn seal_capture(
    frame: &Frame,
    grant: &Grant,
    decision: &Decision,
    sealer: &Sealer<'_>,
    hold: jcp_schema::ContentId,
) -> Result<Vec<u8>, ReceiptError> {
    let mut stated = point_members(sealer.known_through);
    stated.push(("captures", json!(hold.to_hex())));
    seal_stating(frame, grant, decision, sealer.key, sealer.steward, &stated)
}

/// Seal the reclaim of a hold's money (SPEC §8.1) outside a log.
pub fn seal_reclaim(
    frame: &Frame,
    grant: &Grant,
    decision: &Decision,
    sealer: &Sealer<'_>,
    hold: jcp_schema::ContentId,
) -> Result<Vec<u8>, ReceiptError> {
    let mut stated = point_members(sealer.known_through);
    stated.push(("reclaims", json!(hold.to_hex())));
    seal_stating(frame, grant, decision, sealer.key, sealer.steward, &stated)
}

/// Seal a capture's reversal (SPEC §8.1) outside a log: money `capture`
/// drew that the rail did not move, returned to its hold. A refusal states no
/// amount.
pub fn seal_reversal(
    frame: &Frame,
    grant: &Grant,
    decision: &Decision,
    sealer: &Sealer<'_>,
    capture: jcp_schema::ContentId,
    amount: u64,
) -> Result<Vec<u8>, ReceiptError> {
    let mut stated = point_members(sealer.known_through);
    stated.push(("reverses", json!(capture.to_hex())));
    if decision.is_allow() {
        stated.push(("reversed_minor", json!(amount)));
    }
    seal_stating(frame, grant, decision, sealer.key, sealer.steward, &stated)
}

/// Seal a refund (SPEC §8.1) outside a log. A refusal states no amount.
pub fn seal_refund(
    frame: &Frame,
    grant: &Grant,
    decision: &Decision,
    sealer: &Sealer<'_>,
    refunded_minor: u64,
) -> Result<Vec<u8>, ReceiptError> {
    let mut stated = point_members(sealer.known_through);
    if decision.is_allow() {
        stated.push(("refunded_minor", json!(refunded_minor)));
    }
    seal_stating(frame, grant, decision, sealer.key, sealer.steward, &stated)
}

fn seal_stating(
    frame: &Frame,
    grant: &Grant,
    decision: &Decision,
    key: &SigningKey,
    steward: &str,
    stated: &[(&str, Value)],
) -> Result<Vec<u8>, ReceiptError> {
    let mut wire = to_jcr1_wire(frame, grant, decision, steward);
    if let Value::Object(ref mut o) = wire {
        for (member, value) in stated {
            o.insert((*member).into(), value.clone());
        }
    }
    let core = jcr1::signed_core_bytes(&wire)?;
    Ok(jcr1::cose_sign1_envelope(&core, key, steward))
}

/// Verify a JCR-1 envelope against a steward key and confirm its payload is
/// exactly this decision's canonical signed core.
pub fn verify(
    frame: &Frame,
    grant: &Grant,
    decision: &Decision,
    envelope: &[u8],
    steward: &str,
    pubkey: &[u8; 32],
) -> Result<(), ReceiptError> {
    let payload = jcr1::verify_cose_sign1(envelope, steward, pubkey)?;
    // Version dispatch (SPEC §8): recompute the preimage under the profile the
    // envelope itself claims, so a receipt sealed as `jcp/1` — before
    // `payload_hash` existed — still verifies against the same decision.
    let expected = match profile_of(&payload)?.as_str() {
        PROFILE => to_jcr1_wire(frame, grant, decision, steward),
        PROFILE_V1 => to_jcr1_wire_v1(frame, grant, decision, steward),
        other => return Err(ReceiptError::UnknownProfile(other.to_string())),
    };
    check_core(&payload, expected)
}

/// Read the `jcp_receipt` profile tag out of a verified payload. Until now the
/// tag was written but never read; version dispatch is what makes it load-bearing.
fn profile_of(payload: &[u8]) -> Result<String, ReceiptError> {
    let v: Value = jcp_schema::from_canonical_cbor(payload)
        .map_err(|_| ReceiptError::UnknownProfile("<undecodable>".into()))?;
    v.get("jcp_receipt")
        .and_then(Value::as_str)
        .map(str::to_string)
        .ok_or_else(|| ReceiptError::UnknownProfile("<absent>".into()))
}

/// The fields of one verified receipt, extracted from its signed core — what
/// group accounting and state replay consume.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ReceiptCore {
    pub grant_id: jcp_schema::ContentId,
    /// Every grant id the decision debited (root first), when the receipt
    /// records a multi-hop chain; one-link decisions omit it.
    pub chain_ids: Option<Vec<jcp_schema::ContentId>>,
    pub subject: String,
    pub action: String,
    pub verdict: String,
    pub deny_reason: Option<String>,
    /// The content id of the payload the decision was over. `Some` on `jcp/2`;
    /// `None` on a legacy `jcp/1` receipt, which did not bind its payload.
    pub payload_hash: Option<String>,
    pub cost_uj: u64,
    /// What the decision debited, where the core states it (SPEC §8.1). Read
    /// it through [`debits`](Self::debits), which also answers where it does not.
    pub debited_uj: Option<u64>,
    /// What each link of `chain_ids` was debited, where they differ.
    pub chain_debited_uj: Option<Vec<u64>>,
    /// The money the decision debited, where the core states it (SPEC §8.1).
    /// Read it through [`money_debits`](Self::money_debits).
    pub debited_minor: Option<u64>,
    /// What each link of `chain_ids` was debited in money, where they differ.
    pub chain_debited_minor: Option<Vec<u64>>,
    /// What the decision accrued against a tainted sub-budget, where the core
    /// states it. Read it through [`tainted_accruals`](Self::tainted_accruals).
    pub tainted_uj: Option<u64>,
    /// Whether the core carries a `flow` block: a `jcp/3` receipt, whose
    /// call's argument was tainted (SPEC §4.10).
    pub flow: bool,
    /// On a hold, sealed before the work its allow lets run, the most that
    /// work can debit (SPEC §8.1). Read it through [`read_stream`], which
    /// knows whether a later receipt settled the hold.
    pub held_uj: Option<u64>,
    /// The money a hold reserves, where it reserves any (SPEC §4.8, §8.1).
    /// `None` on a hold that reserves no money — a grant with no money ceiling
    /// — which keeps a joules-only hold byte-identical to one sealed before
    /// this field existed.
    pub held_minor: Option<u64>,
    /// How current the sealing point's revocation knowledge was (SPEC §4.3).
    ///
    /// `None` means the point did not say, which an auditor **MUST** read as
    /// *unverifiable* for revocation rather than as compliant: "did not say" is
    /// not "was current". Given a revocation issued at marker `M`, an allow
    /// stating `known_through < M` is explicable as propagation delay, and one
    /// stating `>= M` is not.
    pub known_through: Option<u64>,
    /// The hold this receipt **captures from** without resolving it (SPEC
    /// §8.1): a partial draw, leaving the rest reserved.
    pub captures: Option<jcp_schema::ContentId>,
    /// The hold whose money reservation this receipt **reclaims** after its
    /// capture deadline (SPEC §8.1). The joule reservation stays.
    pub reclaims: Option<jcp_schema::ContentId>,
    /// The capture this receipt reverses: money it drew that never moved
    /// (SPEC §8.1).
    pub reverses: Option<jcp_schema::ContentId>,
    /// What an allowed reversal returned to the hold.
    pub reversed_minor: Option<u64>,
    /// Money this receipt **refunds** to its grant (SPEC §8.1), lowering the
    /// net spend and never the gross debit.
    pub refunded_minor: Option<u64>,
    /// The content id of the hold whose work this receipt's decision
    /// accounts for (SPEC §8.1).
    pub settles: Option<jcp_schema::ContentId>,
    /// On a firing of a standing grant (SPEC §4.6), the budget the child it
    /// minted carries: what the firing adds to the standing grant's mint
    /// ledger beside one fire. Read the stream's firings through
    /// [`replay_mints`].
    pub minted_uj: Option<u64>,
    pub budget_remaining_uj: u64,
    pub steward: String,
}

impl ReceiptCore {
    /// What this decision debited, grant by grant, root first (SPEC §8.1). A
    /// refusal debited nothing and yields nothing. An allow yields every grant
    /// it names even at zero: it was a call, and a replay must know one ran.
    ///
    /// A denial that can follow a debit and states no debit was sealed before
    /// `debited_uj` existed, and cannot show that it debited nothing. It reads
    /// as its `cost_uj`, the most it can have been: an unknown debit is not a
    /// zero one, and a replay must never restore less than was debited.
    ///
    /// A hold debits nothing itself and yields nothing: its work is accounted
    /// for by the receipt that settles it, or, where none does, by its
    /// [`held`](Self::held) figure ([`read_stream`]). A firing debits nothing
    /// and yields nothing either: the work its child does is debited on the
    /// child's own receipts, and what the firing counts is in the standing
    /// grant's mint ledger ([`replay_mints`]).
    pub fn debits(&self) -> Vec<(jcp_schema::ContentId, u64)> {
        if self.is_hold() || self.is_mint() {
            return Vec::new();
        }
        let grants = self.chain_ids.clone().unwrap_or_else(|| vec![self.grant_id]);
        if let Some(per_link) = &self.chain_debited_uj {
            return grants.into_iter().zip(per_link.iter().copied()).collect();
        }
        let allowed = self.verdict == "allow";
        let unstated = allowed || self.deny_reason.as_deref().is_some_and(may_follow_a_debit);
        let uj = self.debited_uj.unwrap_or(if unstated { self.cost_uj } else { 0 });
        if uj == 0 && !allowed {
            return Vec::new();
        }
        grants.into_iter().map(|g| (g, uj)).collect()
    }

    /// What this decision debited in money, grant by grant, root first (SPEC
    /// §8.1), in each grant's money-ceiling minor units. Only a figure the
    /// core states counts, and a grant debited none is left out. A receipt
    /// sealed before `debited_minor` existed states none, so it cannot show a
    /// money debit and yields nothing.
    pub fn money_debits(&self) -> Vec<(jcp_schema::ContentId, u64)> {
        let grants = self.chain_ids.clone().unwrap_or_else(|| vec![self.grant_id]);
        let per_link = match (&self.chain_debited_minor, self.debited_minor) {
            (Some(per_link), _) => per_link.clone(),
            (None, Some(minor)) => vec![minor; grants.len()],
            (None, None) => return Vec::new(),
        };
        grants.into_iter().zip(per_link).filter(|(_, minor)| *minor != 0).collect()
    }

    /// What this decision accrued against the tainted sub-budget of each grant
    /// it names (SPEC §8.1, §4.10). With `tainted_uj`, that figure. Otherwise
    /// a receipt carrying a `flow` block that debited accrued its `cost_uj`,
    /// as a tainted call does, and any other receipt accrued nothing.
    pub fn tainted_accruals(&self) -> Vec<(jcp_schema::ContentId, u64)> {
        let uj = match self.tainted_uj {
            Some(uj) => uj,
            None if self.flow && !self.debits().is_empty() => self.cost_uj,
            None => 0,
        };
        if uj == 0 {
            return Vec::new();
        }
        let grants = self.chain_ids.clone().unwrap_or_else(|| vec![self.grant_id]);
        grants.into_iter().map(|g| (g, uj)).collect()
    }

    /// Whether this receipt is a hold (SPEC §8.1): an allow stating
    /// `held_uj`. A refusal debits nothing (C3), so `held_uj` on one holds
    /// nothing and it reads by the ordinary rules.
    pub fn is_hold(&self) -> bool {
        self.held_uj.is_some() && self.verdict == "allow"
    }

    /// Whether this receipt is a firing of a standing grant (SPEC §4.6,
    /// §8.1): an allow stating `minted_uj`. A refusal mints nothing (C3), so
    /// `minted_uj` on one fires nothing and it reads by the ordinary rules.
    pub fn is_mint(&self) -> bool {
        self.minted_uj.is_some() && self.verdict == "allow"
    }

    /// What a hold no receipt settles debited from every grant it names: its
    /// `held_uj` (SPEC §8.1). Empty for any other receipt. Whether a hold is
    /// settled is a fact about the stream, not the receipt: [`read_stream`]
    /// decides it.
    pub fn held(&self) -> Vec<(jcp_schema::ContentId, u64)> {
        match self.held_uj {
            Some(uj) if self.is_hold() => {
                self.chain_ids.clone().unwrap_or_else(|| vec![self.grant_id]).into_iter().map(|g| (g, uj)).collect()
            }
            _ => Vec::new(),
        }
    }

    /// What a hold no receipt settles reserved in **money** from every grant it
    /// names: its `held_minor` (SPEC §4.8, §8.1). Empty for any other receipt,
    /// and for a hold that reserved none.
    ///
    /// A replay that restored the joules of an unresolved hold but not its
    /// money would rebuild a state in which the interrupted charge can be paid
    /// for a second time.
    /// The hold this receipt **settles**, where it settles one (SPEC §8.1).
    ///
    /// Stating `settles` is not enough. A resolution refused before it took
    /// its hold — `already-resolved`, `currency-mismatch`, `wrong-subject` —
    /// left the hold outstanding whatever its receipt names, so a reader that
    /// took the member at its word would release a reservation whose work is
    /// still running. A conforming writer omits the member on those; this is
    /// the reader's half of the same rule, for a log it did not write. Every
    /// other outcome consumed the hold, a denial that debited among them.
    pub fn settles_its_hold(&self) -> Option<jcp_schema::ContentId> {
        let left_outstanding = self.verdict == "deny"
            && matches!(
                self.deny_reason.as_deref(),
                Some("already-resolved" | "currency-mismatch" | "wrong-subject")
            );
        if left_outstanding { None } else { self.settles }
    }

    pub fn held_money(&self) -> Vec<(jcp_schema::ContentId, u64)> {
        match self.held_minor {
            Some(minor) if self.is_hold() && minor > 0 => {
                self.chain_ids.clone().unwrap_or_else(|| vec![self.grant_id]).into_iter().map(|g| (g, minor)).collect()
            }
            _ => Vec::new(),
        }
    }
}

/// The member a resolution's receipt states: `settles`, naming its hold —
/// **only where the resolution consumed the hold**.
///
/// A resolution refused before it took the hold (`already-resolved`,
/// `currency-mismatch`, `wrong-subject`) leaves the hold outstanding, and a
/// receipt for it that named the hold would tell every reader the reservation
/// was over. A point restarted from such a log came back without the
/// reservation while the work behind it was still running — found by replaying
/// random sequences at every prefix, at 120 µJ released by a settle in the
/// wrong currency.
fn settle_members(decision: &Decision, hold: jcp_schema::ContentId) -> Vec<(&'static str, Value)> {
    if decision.consumed_the_hold() {
        vec![("settles", json!(hold.to_hex()))]
    } else {
        Vec::new()
    }
}

/// The members a hold's receipt states: `held_uj` always, and `held_minor`
/// only where the hold reserved money — so a joules-only hold's core stays
/// byte-identical to one sealed before the money dimension existed. A refusal
/// holds nothing (C3), so it states neither.
fn hold_members(decision: &Decision, held_uj: u64, held_minor: u64) -> Vec<(&'static str, Value)> {
    if !decision.is_allow() {
        return Vec::new();
    }
    let mut out = vec![("held_uj", json!(held_uj))];
    if held_minor > 0 {
        out.push(("held_minor", json!(held_minor)));
    }
    out
}

/// Verify a receipt's envelope and extract its signed core. Only a receipt
/// whose signature verifies under the expected steward key yields fields — an
/// unverified receipt yields nothing.
pub fn extract(envelope: &[u8], steward: &str, pubkey: &[u8; 32]) -> Result<ReceiptCore, ReceiptError> {
    let payload = jcr1::verify_cose_sign1(envelope, steward, pubkey)?;
    let v: Value = jcp_schema::from_canonical_cbor(&payload)
        .map_err(|e| ReceiptError::Jcr1(jcr1::Jcr1Error::Envelope(format!("core: {e}"))))?;
    let field = |k: &str| v.get(k).and_then(Value::as_str).map(str::to_string);
    let uint = |k: &str| v.get(k).and_then(Value::as_u64);
    let bad = |what: &str| ReceiptError::Jcr1(jcr1::Jcr1Error::Envelope(format!("core missing {what}")));
    let chain_ids = match v.get("chain_ids").and_then(Value::as_array) {
        None => None,
        Some(arr) => Some(
            arr.iter()
                .map(|e| {
                    e.as_str()
                        .ok_or_else(|| bad("chain_ids entry"))
                        .and_then(|h| {
                            jcp_schema::ContentId::from_hex(h)
                                .map_err(|e| ReceiptError::Jcr1(jcr1::Jcr1Error::Envelope(e.to_string())))
                        })
                })
                .collect::<Result<Vec<_>, _>>()?,
        ),
    };
    // A debit member is read strictly: one that does not parse must not read as
    // absent, which means something else.
    let debited_uj = match v.get("debited_uj") {
        None => None,
        Some(n) => Some(n.as_u64().ok_or_else(|| bad("a uint debited_uj"))?),
    };
    let chain_debited_uj = match v.get("chain_debited_uj") {
        None => None,
        Some(a) => {
            let per_link = a
                .as_array()
                .ok_or_else(|| bad("a chain_debited_uj array"))?
                .iter()
                .map(|n| n.as_u64().ok_or_else(|| bad("a uint chain_debited_uj entry")))
                .collect::<Result<Vec<_>, _>>()?;
            if Some(per_link.len()) != chain_ids.as_ref().map(Vec::len) {
                return Err(bad("a chain_debited_uj entry for each of chain_ids"));
            }
            Some(per_link)
        }
    };
    let debited_minor = match v.get("debited_minor") {
        None => None,
        Some(n) => Some(n.as_u64().ok_or_else(|| bad("a uint debited_minor"))?),
    };
    let chain_debited_minor = match v.get("chain_debited_minor") {
        None => None,
        Some(a) => {
            let per_link = a
                .as_array()
                .ok_or_else(|| bad("a chain_debited_minor array"))?
                .iter()
                .map(|n| n.as_u64().ok_or_else(|| bad("a uint chain_debited_minor entry")))
                .collect::<Result<Vec<_>, _>>()?;
            if Some(per_link.len()) != chain_ids.as_ref().map(Vec::len) {
                return Err(bad("a chain_debited_minor entry for each of chain_ids"));
            }
            Some(per_link)
        }
    };
    let tainted_uj = match v.get("tainted_uj") {
        None => None,
        Some(n) => Some(n.as_u64().ok_or_else(|| bad("a uint tainted_uj"))?),
    };
    let hold_ref = |k: &str| -> Result<Option<jcp_schema::ContentId>, ReceiptError> {
        match v.get(k) {
            None => Ok(None),
            Some(h) => {
                let hex = h.as_str().ok_or_else(|| bad("a hex hold reference"))?;
                jcp_schema::ContentId::from_hex(hex).map(Some).map_err(|_| bad("a hex hold reference"))
            }
        }
    };
    let captures = hold_ref("captures")?;
    let reclaims = hold_ref("reclaims")?;
    let reverses = hold_ref("reverses")?;
    let reversed_minor = match v.get("reversed_minor") {
        None => None,
        Some(n) => Some(n.as_u64().ok_or_else(|| bad("a uint reversed_minor"))?),
    };
    let refunded_minor = match v.get("refunded_minor") {
        None => None,
        Some(n) => Some(n.as_u64().ok_or_else(|| bad("a uint refunded_minor"))?),
    };
    let known_through = match v.get("known_through") {
        None => None,
        Some(n) => Some(n.as_u64().ok_or_else(|| bad("a uint known_through"))?),
    };
    let held_minor = match v.get("held_minor") {
        None => None,
        Some(n) => Some(n.as_u64().ok_or_else(|| bad("a uint held_minor"))?),
    };
    let held_uj = match v.get("held_uj") {
        None => None,
        Some(n) => Some(n.as_u64().ok_or_else(|| bad("a uint held_uj"))?),
    };
    let settles = match v.get("settles") {
        None => None,
        Some(h) => Some(
            jcp_schema::ContentId::from_hex(h.as_str().ok_or_else(|| bad("a hex settles"))?)
                .map_err(|_| bad("a hex settles"))?,
        ),
    };
    let minted_uj = match v.get("minted_uj") {
        None => None,
        Some(n) => Some(n.as_u64().ok_or_else(|| bad("a uint minted_uj"))?),
    };
    Ok(ReceiptCore {
        grant_id: jcp_schema::ContentId::from_hex(&field("grant_id").ok_or_else(|| bad("grant_id"))?)
            .map_err(|e| ReceiptError::Jcr1(jcr1::Jcr1Error::Envelope(e.to_string())))?,
        chain_ids,
        subject: field("subject").ok_or_else(|| bad("subject"))?,
        action: field("action").ok_or_else(|| bad("action"))?,
        verdict: field("verdict").ok_or_else(|| bad("verdict"))?,
        deny_reason: field("deny_reason"),
        payload_hash: field("payload_hash"),
        cost_uj: uint("cost_uj").ok_or_else(|| bad("cost_uj"))?,
        debited_uj,
        chain_debited_uj,
        debited_minor,
        chain_debited_minor,
        tainted_uj,
        flow: v.get("flow").is_some(),
        held_uj,
        held_minor,
        known_through,
        captures,
        reclaims,
        reverses,
        reversed_minor,
        refunded_minor,
        settles,
        minted_uj,
        budget_remaining_uj: uint("budget_remaining_uj").ok_or_else(|| bad("budget_remaining_uj"))?,
        steward: field("steward").ok_or_else(|| bad("steward"))?,
    })
}

/// Per-grant, per-subject totals over a verified receipt stream — the group
/// accounting profile (SPEC §8.2). When a team of agents works under sub-grants
/// of one root, this is cost and outcome attribution per worker, computed from
/// evidence rather than self-reporting.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Totals {
    pub allows: u64,
    pub denies: u64,
    pub spent_uj: u64,
}

/// Aggregate a receipt stream into totals keyed by `(grant_id hex, subject)`.
/// Receipts that fail verification are counted, not silently skipped — a
/// ledger that drops entries is not a ledger.
///
/// A hold (SPEC §8.1) is not counted: its work is counted by the receipt that
/// settles it, and a hold no receipt settles is work whose outcome and cost
/// the stream cannot tell (§4.11), which [`unresolved_holds`] names. So on a
/// stream holding such a hold the joules attributed to its grant fall short
/// of what [`replay_spend`] restores by its `held_uj`: a replay restores the
/// most the work can have debited, attribution only what a receipt shows.
/// Nor is a firing of a standing grant (§4.6): the work it lets run is
/// counted on its child's receipts.
pub fn aggregate<'a>(
    receipts: impl IntoIterator<Item = &'a [u8]>,
    steward: &str,
    pubkey: &[u8; 32],
) -> (std::collections::BTreeMap<(String, String), Totals>, u64) {
    let mut out: std::collections::BTreeMap<(String, String), Totals> = Default::default();
    let mut bad = 0u64;
    for env in receipts {
        match extract(env, steward, pubkey) {
            Ok(core) if core.is_hold() || core.is_mint() => {}
            Ok(core) => {
                // The leaf's debit: a denial from the debit point spent joules
                // too, and a worker answers for them.
                let debited = core.debits().last().map_or(0, |(_, uj)| *uj);
                let allowed = core.verdict == "allow";
                let t = out.entry((core.grant_id.to_hex(), core.subject)).or_default();
                if allowed {
                    t.allows += 1;
                } else {
                    t.denies += 1;
                }
                t.spent_uj = t.spent_uj.saturating_add(debited);
            }
            Err(_) => bad += 1,
        }
    }
    (out, bad)
}

/// Replay a receipt stream into the spend ledger a [`jcp_runtime::Runtime`]
/// restores from (SPEC §8.1: **the receipt stream is the write-ahead log** —
/// an enforcement point that crashes rebuilds its budget state from its own
/// sealed output). Each verified receipt contributes what it debited, whatever
/// its verdict ([`ReceiptCore::debits`]): a denial from the debit point still
/// debited the work that ran, and a refusal contributes nothing. A hold no
/// receipt in the stream settles contributes its `held_uj` ([`read_stream`]).
///
/// This is the joules alone. An enforcement point that also enforces a money
/// ceiling (§4.8) or a tainted sub-budget (§4.10) restores from
/// [`replay_ledger`], or a restart hands those back.
pub fn replay_spend<'a>(
    receipts: impl IntoIterator<Item = &'a [u8]>,
    steward: &str,
    pubkey: &[u8; 32],
) -> Vec<(jcp_schema::ContentId, u64)> {
    read_stream(receipts, steward, pubkey).into_iter().flatten().flat_map(|l| l.uj).collect()
}

/// Read a receipt stream receipt by receipt (SPEC §8.1): what each verified
/// receipt restores in joules, money and tainted accrual, `None` for one that
/// does not verify.
///
/// Every receipt reads as [`ReceiptCore::debits`],
/// [`money_debits`](ReceiptCore::money_debits) and
/// [`tainted_accruals`](ReceiptCore::tainted_accruals) say, but a hold is read
/// against the whole stream: one that a verified receipt settles restores
/// nothing, its work being the settling receipt's, and one that none settles
/// was interrupted between its decision and its outcome, so it restores its
/// `held_uj` from every grant it names, and, carrying a `flow` block, as much
/// against each one's tainted sub-budget ([`unresolved_holds`]).
pub fn read_stream<'a>(
    receipts: impl IntoIterator<Item = &'a [u8]>,
    steward: &str,
    pubkey: &[u8; 32],
) -> Vec<Option<jcp_runtime::Ledger>> {
    read_stream_reopening(receipts, steward, pubkey, &std::collections::BTreeSet::new())
}

/// What allowed reversals returned, by the capture each names (SPEC §8.1).
fn reversals<'c>(cores: impl Iterator<Item = &'c ReceiptCore>) -> std::collections::BTreeMap<jcp_schema::ContentId, u64> {
    let mut out = std::collections::BTreeMap::new();
    for c in cores {
        if let (Some(capture), Some(minor), "allow") = (c.reverses, c.reversed_minor, c.verdict.as_str()) {
            *out.entry(capture).or_insert(0u64) += minor;
        }
    }
    out
}

/// A receipt's money debits, less what reversals returned of them: a
/// capture the rail never moved debited nothing.
fn money_net(
    id: &jcp_schema::ContentId,
    core: &ReceiptCore,
    reversed: &std::collections::BTreeMap<jcp_schema::ContentId, u64>,
) -> Vec<(jcp_schema::ContentId, u64)> {
    let back = reversed.get(id).copied().unwrap_or(0);
    core.money_debits().into_iter().map(|(g, m)| (g, m.saturating_sub(back))).filter(|(_, m)| *m > 0).collect()
}

/// A hold no receipt settles, and what it still reserves: its figures less
/// what captures have drawn, and no money once it has been reclaimed.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OpenHold {
    /// The hold's receipt: its envelope's content id.
    pub id: jcp_schema::ContentId,
    /// The grant it is on.
    pub grant_id: jcp_schema::ContentId,
    /// Joules it still reserves.
    pub uj: u64,
    /// Money it still reserves.
    pub minor: u64,
    /// Money captures drew from it that reversals have not returned.
    pub drawn_minor: u64,
    /// The payload its frame committed to.
    pub payload_hash: Option<String>,
    /// Whether its money has been reclaimed.
    pub reclaimed: bool,
}

/// The holds in a stream that could be taken up again after a restart
/// (`Runtime::adopt_hold`): unsettled, on a single grant, and not under a
/// flow ceiling. A chained or flow-tainted hold is not listed, and restores
/// as debited as it always has.
pub fn open_holds<'a>(receipts: impl IntoIterator<Item = &'a [u8]>, steward: &str, pubkey: &[u8; 32]) -> Vec<OpenHold> {
    let cores: Vec<(jcp_schema::ContentId, ReceiptCore)> = receipts
        .into_iter()
        .filter_map(|env| extract(env, steward, pubkey).ok().map(|c| (jcp_schema::ContentId::of_bytes(env), c)))
        .collect();
    let settled: std::collections::BTreeSet<jcp_schema::ContentId> = cores.iter().filter_map(|(_, c)| c.settles_its_hold()).collect();
    let reclaimed: std::collections::BTreeSet<jcp_schema::ContentId> =
        cores.iter().filter(|(_, c)| c.verdict == "allow").filter_map(|(_, c)| c.reclaims).collect();
    let reversed = reversals(cores.iter().map(|(_, c)| c));
    let drawn = |hold: &jcp_schema::ContentId, f: &dyn Fn(&jcp_schema::ContentId, &ReceiptCore) -> u64| -> u64 {
        cores.iter().filter(|(_, c)| c.captures == Some(*hold)).map(|(id, c)| f(id, c)).sum()
    };
    cores
        .iter()
        .filter(|(id, c)| c.is_hold() && !settled.contains(id) && c.chain_ids.is_none() && !c.flow)
        .map(|(id, c)| {
            let gone = reclaimed.contains(id);
            let uj = c.held_uj.unwrap_or(0).saturating_sub(drawn(id, &|_, x| x.debits().iter().map(|(_, n)| n).sum()));
            let drawn_minor: u64 = drawn(id, &|cid, x| money_net(cid, x, &reversed).iter().map(|(_, n)| n).sum());
            let minor = c.held_minor.unwrap_or(0).saturating_sub(drawn_minor);
            OpenHold {
                id: *id,
                grant_id: c.grant_id,
                uj,
                minor: if gone { 0 } else { minor },
                drawn_minor,
                payload_hash: c.payload_hash.clone(),
                reclaimed: gone,
            }
        })
        .collect()
}

/// [`replay_ledger`], leaving out what the holds named in `reopen` still
/// reserve: the ledger to restore a runtime from before taking those holds
/// up again with `Runtime::adopt_hold`. Everything else, their captures
/// included, is restored as always.
pub fn replay_ledger_reopening<'a>(
    receipts: impl IntoIterator<Item = &'a [u8]>,
    steward: &str,
    pubkey: &[u8; 32],
    reopen: &std::collections::BTreeSet<jcp_schema::ContentId>,
) -> jcp_runtime::Ledger {
    let mut ledger = jcp_runtime::Ledger::default();
    for read in read_stream_reopening(receipts, steward, pubkey, reopen).into_iter().flatten() {
        ledger.uj.extend(read.uj);
        ledger.minor.extend(read.minor);
        ledger.tainted_uj.extend(read.tainted_uj);
        ledger.refunded_minor.extend(read.refunded_minor);
    }
    ledger
}

fn read_stream_reopening<'a>(
    receipts: impl IntoIterator<Item = &'a [u8]>,
    steward: &str,
    pubkey: &[u8; 32],
    reopen: &std::collections::BTreeSet<jcp_schema::ContentId>,
) -> Vec<Option<jcp_runtime::Ledger>> {
    let cores: Vec<Option<(jcp_schema::ContentId, ReceiptCore)>> = receipts
        .into_iter()
        .map(|env| extract(env, steward, pubkey).ok().map(|c| (jcp_schema::ContentId::of_bytes(env), c)))
        .collect();
    let settled: std::collections::BTreeSet<jcp_schema::ContentId> =
        cores.iter().flatten().filter_map(|(_, c)| c.settles_its_hold()).collect();
    // What the captures drawing on each hold already debited, per grant. An
    // unsettled hold restores what it still reserves — its figure LESS these —
    // because the captures restore their own debits, and restoring the whole
    // reservation beside them would count the captured part twice.
    type Drawn = std::collections::BTreeMap<(jcp_schema::ContentId, jcp_schema::ContentId), u64>;
    let reversed = reversals(cores.iter().flatten().map(|(_, c)| c));
    let mut captured_uj = Drawn::new();
    let mut captured_minor = Drawn::new();
    for (id, c) in cores.iter().flatten() {
        if let Some(hold) = c.captures {
            for (g, uj) in c.debits() {
                *captured_uj.entry((hold, g)).or_insert(0) += uj;
            }
            for (g, m) in money_net(id, c, &reversed) {
                *captured_minor.entry((hold, g)).or_insert(0) += m;
            }
        }
    }
    // A reclaimed hold reserves no money any more; its joules still count.
    let reclaimed: std::collections::BTreeSet<jcp_schema::ContentId> = cores
        .iter()
        .flatten()
        .filter(|(_, c)| c.verdict == "allow")
        .filter_map(|(_, c)| c.reclaims)
        .collect();
    cores
        .into_iter()
        .map(|read| {
            let (id, core) = read?;
            let mut ledger = jcp_runtime::Ledger {
                uj: core.debits(),
                minor: money_net(&id, &core, &reversed),
                tainted_uj: core.tainted_accruals(),
                refunded_minor: match core.refunded_minor {
                    Some(m) if core.verdict == "allow" && m > 0 => vec![(core.grant_id, m)],
                    _ => Vec::new(),
                },
            };
            if !settled.contains(&id) && !reopen.contains(&id) {
                let less = |v: Vec<(jcp_schema::ContentId, u64)>, drawn: &Drawn| {
                    v.into_iter()
                        .map(|(g, n)| (g, n.saturating_sub(drawn.get(&(id, g)).copied().unwrap_or(0))))
                        .filter(|(_, n)| *n > 0)
                        .collect::<Vec<_>>()
                };
                let held = less(core.held(), &captured_uj);
                if core.flow {
                    ledger.tainted_uj.extend(held.iter().copied());
                }
                ledger.uj.extend(held);
                if !reclaimed.contains(&id) {
                    ledger.minor.extend(less(core.held_money(), &captured_minor));
                }
            }
            Some(ledger)
        })
        .collect()
}

/// The holds in a receipt stream that no verified receipt in it settles, by
/// the content id of each one's envelope (SPEC §8.1, §4.11): decisions whose
/// work was in flight when the enforcement point stopped, whose outcome the
/// stream cannot tell. [`read_stream`] restores each at its `held_uj`.
pub fn unresolved_holds<'a>(
    receipts: impl IntoIterator<Item = &'a [u8]>,
    steward: &str,
    pubkey: &[u8; 32],
) -> Vec<jcp_schema::ContentId> {
    let cores: Vec<(jcp_schema::ContentId, ReceiptCore)> = receipts
        .into_iter()
        .filter_map(|env| extract(env, steward, pubkey).ok().map(|c| (jcp_schema::ContentId::of_bytes(env), c)))
        .collect();
    let settled: std::collections::BTreeSet<jcp_schema::ContentId> = cores.iter().filter_map(|(_, c)| c.settles_its_hold()).collect();
    cores.into_iter().filter(|(id, c)| c.is_hold() && !settled.contains(id)).map(|(id, _)| id).collect()
}

/// Replay a receipt stream into the whole ledger a [`jcp_runtime::Runtime`]
/// restores with [`restore_ledger`](jcp_runtime::Runtime::restore_ledger)
/// (SPEC §8.1): the joules [`replay_spend`] gives, and beside them the money
/// each receipt debited ([`ReceiptCore::money_debits`]) and what it accrued
/// against a tainted sub-budget ([`ReceiptCore::tainted_accruals`]), with
/// each hold read against the stream ([`read_stream`]). Only verified
/// receipts contribute.
pub fn replay_ledger<'a>(
    receipts: impl IntoIterator<Item = &'a [u8]>,
    steward: &str,
    pubkey: &[u8; 32],
) -> jcp_runtime::Ledger {
    let mut ledger = jcp_runtime::Ledger::default();
    for read in read_stream(receipts, steward, pubkey).into_iter().flatten() {
        ledger.uj.extend(read.uj);
        ledger.minor.extend(read.minor);
        ledger.tainted_uj.extend(read.tainted_uj);
        ledger.refunded_minor.extend(read.refunded_minor);
    }
    ledger
}

/// The firings of standing grants in a receipt stream (SPEC §4.6, §8.1), in
/// stream order, each as the standing grant it names and the `minted_uj` its
/// receipt states. Only verified receipts contribute.
///
/// This is what rebuilds a standing grant's mint ledger: one fire for each
/// entry naming it, and the budget each minted, summed
/// (`jcp_grant::standing::MintLedger::of_firings`). A mint ledger the
/// enforcement point stored is applied beside it with `MintLedger::restore`,
/// which keeps the higher figures, so neither a stale copy nor a short stream
/// hands a firing back.
pub fn replay_mints<'a>(
    receipts: impl IntoIterator<Item = &'a [u8]>,
    steward: &str,
    pubkey: &[u8; 32],
) -> Vec<(jcp_schema::ContentId, u64)> {
    receipts
        .into_iter()
        .filter_map(|env| extract(env, steward, pubkey).ok())
        .filter(ReceiptCore::is_mint)
        .filter_map(|core| core.minted_uj.map(|uj| (core.grant_id, uj)))
        .collect()
}

/// A hash-chained, append-only receipt log (SPEC §8.1). Each entry's signed
/// core commits to the **content id of the previous entry's envelope** via a
/// `prev` field (`0…0` for the genesis entry), so the stream is tamper-evident
/// as a *sequence*, not merely a bag of individually-signed records: you cannot
/// excise, reorder, or splice a receipt without breaking the chain at that
/// point. This is the integrity layer OpenTelemetry lacks and the property the
/// EU AI Act's logging obligations (Aug 2026) and the "notarized agents" line
/// of research both reach for — built from the family's own JCR-1 envelope.
/// A record that an earlier entry's content was erased.
///
/// # Why a hash chain needs this shape
///
/// The chain links on envelope bytes: each entry's `prev` is the content id of
/// the one before it. So an entry cannot be edited or removed to satisfy an
/// erasure request — either breaks every link after it, and a chain that no
/// longer verifies is not evidence of anything, including of the erasure.
///
/// Erasure is therefore **forward-only**. The erased envelope stops being
/// retained; its content id does not change, so the links still resolve; and a
/// tombstone is *appended* declaring what happened. What is lost is the ability
/// to read what was done. What survives is that something was done, where in
/// the order, and what it cost.
///
/// # Why the energy stays
///
/// Every energy total, efficiency figure and facility rollup over this log is a
/// sum across its entries. An erasure that dropped the joules would silently
/// shrink all of them, and the shrinkage would be indistinguishable from a
/// genuine efficiency gain — a conservation break arriving through the back
/// door of a privacy feature.
///
/// Joules and an acquisition label are not personal data. The payload hash, the
/// resource, the subject and the action are — and none of them are here.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Tombstone {
    /// Content id of the erased entry. Unchanged by erasure, which is what
    /// keeps the chain intact.
    pub erased: jcp_schema::ContentId,
    /// When the erasure was performed (microseconds since the epoch).
    pub erased_at_us: u64,
    /// The authority the erasure was carried out under — a request reference or
    /// a policy id, never the requesting party's identity. A tombstone that
    /// named the subject would re-introduce the datum the erasure removed.
    pub authority: String,
    /// The erased entry's energy, retained so rollups stay conserved.
    pub cost_uj: u64,
    /// Its acquisition class, retained for the same reason: a figure without
    /// one is not comparable to the others in the same sum.
    pub energy_provenance: String,
}

/// The profile tag a tombstone carries.
pub const TOMBSTONE_PROFILE: &str = "jcp.tombstone/1";

/// The JCR-1 wire for a tombstone: its own profile, so a reader can never
/// mistake it for a decision that happened to have no payload.
pub fn tombstone_wire(
    t: &Tombstone,
    steward: &str,
    seq: u64,
    prev: &jcp_schema::ContentId,
) -> Value {
    json!({
        "jcp_receipt": TOMBSTONE_PROFILE,
        "erased": t.erased.to_hex(),
        "erased_at_us": t.erased_at_us,
        "authority": t.authority,
        "cost_uj": t.cost_uj,
        "energy_provenance": t.energy_provenance,
        "steward": steward,
        "seq": seq,
        "prev": prev.to_hex(),
    })
}

pub struct ReceiptLog {
    steward_sk: SigningKey,
    steward: String,
    head: jcp_schema::ContentId,
    seq: u64,
    entries: Vec<Vec<u8>>,
    /// How current this point's revocation knowledge was (SPEC §4.3), stated
    /// on every receipt it seals while declared. `None` means the point has
    /// not said — which an auditor reads as *unverifiable* for revocation,
    /// never as current.
    known_through: Option<u64>,
}

/// Why a log would not adopt a prior chain ([`ReceiptLog::resume`]).
#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
pub enum ResumeError {
    /// The prior stream stops being a verified chain at this index — the same
    /// index [`verify_log`] reports. Nothing was adopted.
    #[error("prior receipt chain broken at index {0}")]
    BrokenAt(usize),
    /// This log has already sealed entries of its own. Adopting a history now
    /// would renumber them, so the call is refused rather than silently
    /// orphaning the given number of entries.
    #[error("log already holds {0} sealed entries; resume before the first append")]
    NotEmpty(usize),
}

/// The genesis predecessor: an all-zero content id, the "no prior receipt"
/// sentinel the first entry's `prev` links to.
fn genesis_prev() -> jcp_schema::ContentId {
    jcp_schema::ContentId::from_hex(&"0".repeat(64)).expect("64 hex zeros parse")
}

impl ReceiptLog {
    /// Open an empty log under a steward key.
    pub fn new(steward_sk: SigningKey, steward: impl Into<String>) -> Self {
        ReceiptLog {
            steward_sk,
            steward: steward.into(),
            head: genesis_prev(),
            seq: 0,
            entries: Vec::new(),
            known_through: None,
        }
    }

    /// Declare how current this point's revocation knowledge is, as a marker
    /// monotonic in whatever its revocation feed counts (SPEC §4.3).
    ///
    /// Every receipt sealed afterwards states it, which is what separates a
    /// propagation delay from a violation. Without it, an allow by a point that
    /// *had not yet heard* of a revocation is indistinguishable, after the
    /// fact, from an allow by a point that heard and ignored it: the first is
    /// explicable, the second is a breach of this specification, and nothing in
    /// the receipt told them apart. JCP neither defines nor interprets the
    /// marker; it requires only that a larger value mean "has seen at least as
    /// much", so a sequence number, a log index and a timestamp all serve.
    ///
    /// Read it from the enforcement point that decided —
    /// `Runtime::revocation_marker` — rather than inventing one here: a marker
    /// the sealer made up says nothing about what the decider knew.
    pub fn declare_revocation_marker(&mut self, marker: u64) {
        self.known_through = Some(marker);
    }

    /// The marker this log states, where it states one.
    pub fn revocation_marker(&self) -> Option<u64> {
        self.known_through
    }

    /// The members every receipt from this point states: its revocation
    /// marker, where it has declared one.
    fn point_members(&self) -> Vec<(&'static str, Value)> {
        match self.known_through {
            Some(m) => vec![("known_through", json!(m))],
            None => Vec::new(),
        }
    }

    /// Append a tombstone recording that an earlier entry's content was erased.
    ///
    /// This does **not** alter the erased entry: it cannot, because the chain
    /// links on envelope bytes. The caller stops retaining that envelope's body;
    /// this records the fact, forward, as a new link. The chain continues to
    /// verify precisely because nothing behind it moved.
    pub fn erase(&mut self, t: &Tombstone) -> Vec<u8> {
        let wire = tombstone_wire(t, &self.steward, self.seq, &self.head);
        let core = jcr1::signed_core_bytes(&wire).expect("canonical core");
        let env = jcr1::cose_sign1_envelope(&core, &self.steward_sk, &self.steward);
        self.head = jcp_schema::ContentId::of_bytes(&env);
        self.seq += 1;
        self.entries.push(env.clone());
        env
    }

    /// Seal a decision as the next link in the chain, returning the new entry's
    /// envelope bytes. Both allows and denies are chained — excising a deny
    /// breaks the chain exactly as excising an allow would.
    pub fn append(&mut self, frame: &Frame, grant: &Grant, decision: &Decision) -> Vec<u8> {
        // Through the same path as every other entry point, so a member the
        // log states about itself — its revocation marker (§4.3) — is on this
        // receipt too. Building the wire here instead was how the marker came
        // to be stated on holds and settles but not on a plain decision.
        self.append_flow_stating(frame, grant, decision, &FlowSeal::clean(), &[])
    }

    /// Seal a chained decision as the next link: [`append`](Self::append) for a
    /// receipt that names every link it debited (SPEC §8.1). A one-link chain
    /// appends what `append` would.
    pub fn append_chained(
        &mut self,
        frame: &Frame,
        chain_ids: &[jcp_schema::ContentId],
        leaf: &Grant,
        decision: &Decision,
    ) -> Vec<u8> {
        self.append_chained_stating(frame, chain_ids, leaf, decision, &[])
    }

    /// Seal an allowed chained authorisation as a **hold** naming every link,
    /// before the work it lets run (SPEC §8.1): [`append_hold`](Self::append_hold)
    /// for a call through a delegation chain, stating `held_uj`
    /// ([`jcp_runtime::Runtime::hold_chained`]) beside `chain_ids`. Until a
    /// receipt settles it, a replay reads every link as debited `held_uj`. A
    /// refusal holds nothing and is sealed as
    /// [`append_chained`](Self::append_chained) seals it.
    pub fn append_hold_chained(
        &mut self,
        frame: &Frame,
        chain_ids: &[jcp_schema::ContentId],
        leaf: &Grant,
        decision: &Decision,
        held_uj: u64,
        held_minor: u64,
    ) -> Vec<u8> {
        let stated = hold_members(decision, held_uj, held_minor);
        self.append_chained_stating(frame, chain_ids, leaf, decision, &stated)
    }

    /// Seal the accounting decision of work a chained hold let run, naming
    /// the hold it settles (SPEC §8.1): [`append_settle`](Self::append_settle)
    /// for a call through a delegation chain. A replay then restores what
    /// this receipt debited from each link, and nothing for the hold.
    pub fn append_settle_chained(
        &mut self,
        frame: &Frame,
        chain_ids: &[jcp_schema::ContentId],
        leaf: &Grant,
        decision: &Decision,
        hold: jcp_schema::ContentId,
    ) -> Vec<u8> {
        self.append_chained_stating(frame, chain_ids, leaf, decision, &settle_members(decision, hold))
    }

    /// [`append_capture`](Self::append_capture) for a draw through a
    /// delegation chain: the receipt names every link it debited and the hold
    /// it draws on, so a replay has each link's hold restore that much less.
    pub fn append_capture_chained(
        &mut self,
        frame: &Frame,
        chain_ids: &[jcp_schema::ContentId],
        leaf: &Grant,
        decision: &Decision,
        hold: jcp_schema::ContentId,
    ) -> Vec<u8> {
        self.append_chained_stating(frame, chain_ids, leaf, decision, &[("captures", json!(hold.to_hex()))])
    }

    /// [`append_reversal`](Self::append_reversal) for a chained hold: the
    /// money returns to every funded link.
    pub fn append_reversal_chained(
        &mut self,
        frame: &Frame,
        chain_ids: &[jcp_schema::ContentId],
        leaf: &Grant,
        decision: &Decision,
        capture: jcp_schema::ContentId,
        amount: u64,
    ) -> Vec<u8> {
        let mut stated: Vec<(&str, Value)> = vec![("reverses", json!(capture.to_hex()))];
        if decision.is_allow() {
            stated.push(("reversed_minor", json!(amount)));
        }
        self.append_chained_stating(frame, chain_ids, leaf, decision, &stated)
    }

    /// [`append_reclaim`](Self::append_reclaim) for a chained hold: no link
    /// restores its money afterwards, and every link still restores its joules.
    pub fn append_reclaim_chained(
        &mut self,
        frame: &Frame,
        chain_ids: &[jcp_schema::ContentId],
        leaf: &Grant,
        decision: &Decision,
        hold: jcp_schema::ContentId,
    ) -> Vec<u8> {
        self.append_chained_stating(frame, chain_ids, leaf, decision, &[("reclaims", json!(hold.to_hex()))])
    }

    fn append_chained_stating(
        &mut self,
        frame: &Frame,
        chain_ids: &[jcp_schema::ContentId],
        leaf: &Grant,
        decision: &Decision,
        stated: &[(&str, Value)],
    ) -> Vec<u8> {
        let mut wire = to_jcr1_wire_chained(frame, chain_ids, leaf, decision, &self.steward);
        if let Value::Object(ref mut o) = wire {
            o.insert("seq".into(), json!(self.seq));
            o.insert("prev".into(), json!(self.head.to_hex()));
            for (member, value) in self.point_members().iter().chain(stated) {
                o.insert((*member).into(), value.clone());
            }
        }
        let core = jcr1::signed_core_bytes(&wire).expect("canonical core");
        let env = jcr1::cose_sign1_envelope(&core, &self.steward_sk, &self.steward);
        self.head = jcp_schema::ContentId::of_bytes(&env);
        self.seq += 1;
        self.entries.push(env.clone());
        env
    }

    /// Seal a decision as the next link, carrying its flow verdict. A clean call
    /// appends a `jcp/2` entry byte-identical to [`append`](Self::append); a
    /// tainted call appends a `jcp/3` entry. Either way the chaining (`seq`/`prev`)
    /// is identical, so a mixed stream verifies end to end via [`verify_log`].
    pub fn append_flow(
        &mut self,
        frame: &Frame,
        grant: &Grant,
        decision: &Decision,
        seal: &FlowSeal,
    ) -> Vec<u8> {
        self.append_flow_stating(frame, grant, decision, seal, &[])
    }

    /// Seal an allowed authorisation as a **hold**, before the work it lets
    /// run (SPEC §8.1, §4.11): [`append_flow`](Self::append_flow) of the
    /// authorisation, stating `held_uj`, at least what the work can debit
    /// (the figure [`jcp_runtime::Runtime::hold`] returns, having placed the
    /// hold it counts live). Its id ([`head`](Self::head)
    /// once it is appended) is what the receipt sealed after the work
    /// [`settles`](Self::append_settle). Until a receipt settles it, a replay
    /// restores `held_uj` from the grant, so an enforcement point that records
    /// the hold durably before the work starts cannot lose the work's debit to a
    /// crash, whenever the crash comes.
    ///
    /// A refusal debits nothing (C3) and lets nothing run, so it holds nothing:
    /// it is sealed as [`append_flow`](Self::append_flow) seals it.
    pub fn append_hold(
        &mut self,
        frame: &Frame,
        grant: &Grant,
        decision: &Decision,
        seal: &FlowSeal,
        held_uj: u64,
        held_minor: u64,
    ) -> Vec<u8> {
        let stated = hold_members(decision, held_uj, held_minor);
        self.append_flow_stating(frame, grant, decision, seal, &stated)
    }

    /// Seal the accounting decision of work a hold let run, naming the hold
    /// it settles by its id (SPEC §8.1): [`append_flow`](Self::append_flow)
    /// stating `settles`. A replay then restores what this receipt debited,
    /// and nothing for the hold.
    pub fn append_settle(
        &mut self,
        frame: &Frame,
        grant: &Grant,
        decision: &Decision,
        seal: &FlowSeal,
        hold: jcp_schema::ContentId,
    ) -> Vec<u8> {
        self.append_flow_stating(frame, grant, decision, seal, &settle_members(decision, hold))
    }

    /// Seal a **partial capture** against a hold (SPEC §8.1), naming the hold
    /// it draws on without resolving it. A replay restores this receipt's own
    /// debits and has the hold restore that much less.
    pub fn append_capture(
        &mut self,
        frame: &Frame,
        grant: &Grant,
        decision: &Decision,
        seal: &FlowSeal,
        hold: jcp_schema::ContentId,
    ) -> Vec<u8> {
        self.append_flow_stating(frame, grant, decision, seal, &[("captures", json!(hold.to_hex()))])
    }

    /// Seal the **reclaim** of a hold's money after its capture deadline (SPEC
    /// §8.1). A replay then restores no money for the hold, and still its
    /// joules.
    pub fn append_reclaim(
        &mut self,
        frame: &Frame,
        grant: &Grant,
        decision: &Decision,
        hold: jcp_schema::ContentId,
    ) -> Vec<u8> {
        let stated = [("reclaims", json!(hold.to_hex()))];
        self.append_flow_stating(frame, grant, decision, &FlowSeal::clean(), &stated)
    }

    /// Seal a capture's **reversal** (SPEC §8.1): money `capture` drew that the
    /// rail did not move, returned to its hold. A refusal states no amount.
    pub fn append_reversal(
        &mut self,
        frame: &Frame,
        grant: &Grant,
        decision: &Decision,
        capture: jcp_schema::ContentId,
        amount: u64,
    ) -> Vec<u8> {
        let mut stated: Vec<(&str, Value)> = vec![("reverses", json!(capture.to_hex()))];
        if decision.is_allow() {
            stated.push(("reversed_minor", json!(amount)));
        }
        self.append_flow_stating(frame, grant, decision, &FlowSeal::clean(), &stated)
    }

    /// Seal a **refund** to a grant (SPEC §8.1), stating the amount. A refusal
    /// refunds nothing and states nothing.
    pub fn append_refund(
        &mut self,
        frame: &Frame,
        grant: &Grant,
        decision: &Decision,
        refunded_minor: u64,
    ) -> Vec<u8> {
        let stated: Vec<(&str, Value)> = if decision.is_allow() {
            vec![("refunded_minor", json!(refunded_minor))]
        } else {
            Vec::new()
        };
        self.append_flow_stating(frame, grant, decision, &FlowSeal::clean(), &stated)
    }

    /// Seal a firing of a standing grant (SPEC §4.6, §8.1) as the next link:
    /// an allow on the standing grant, action `mint`, whose `resource` is the
    /// mint policy's content id and whose `payload_hash` is the trigger
    /// event's payload id, stating `minted_uj`, the budget of the child the
    /// firing minted. `remaining_uj` is what the mint ledger leaves of the
    /// standing grant's budget after the firing. A firing runs no work, so it
    /// costs nothing and debits nothing: the child's own receipts debit what
    /// its work spends.
    ///
    /// The enforcement point records the envelope durably before the child
    /// leaves it. A replay then counts the firing ([`replay_mints`]) whenever
    /// the enforcement point stops, so a restart cannot fire the standing
    /// grant past its policy.
    pub fn append_mint(
        &mut self,
        standing: &Grant,
        policy_id: jcp_schema::ContentId,
        payload_id: jcp_schema::ContentId,
        minted_uj: u64,
        remaining_uj: u64,
    ) -> Vec<u8> {
        let frame = Frame {
            kind: jcp_schema::FrameKind::AgentTask,
            trust: jcp_schema::Trust::Control,
            grant_id: standing.id(),
            action: "mint".into(),
            resource: policy_id,
            payload_hash: payload_id,
            model: None,
        };
        let decision = Decision {
            verdict: Verdict::Allow,
            cost: jcp_schema::Energy::estimator(0),
            budget_remaining_uj: remaining_uj,
            debited_uj: 0,
            chain_debited_uj: Vec::new(),
            debited_minor: 0,
            chain_debited_minor: Vec::new(),
            tainted_uj: 0,
        };
        self.append_flow_stating(&frame, standing, &decision, &FlowSeal::clean(), &[("minted_uj", json!(minted_uj))])
    }

    fn append_flow_stating(
        &mut self,
        frame: &Frame,
        grant: &Grant,
        decision: &Decision,
        seal: &FlowSeal,
        stated: &[(&str, Value)],
    ) -> Vec<u8> {
        let mut wire = to_jcr1_wire_logged(frame, grant, decision, &self.steward, self.seq, &self.head);
        if seal.is_tainted() {
            if let (Value::Object(ref mut o), Some(facts)) = (&mut wire, &seal.facts) {
                o.insert("jcp_receipt".into(), json!(PROFILE_FLOW));
                o.insert("flow".into(), flow_block(facts, seal, decision));
            }
            state_tainted(&mut wire, decision);
        }
        if let Value::Object(ref mut o) = wire {
            for (member, value) in self.point_members().iter().chain(stated) {
                o.insert((*member).into(), value.clone());
            }
        }
        let core = jcr1::signed_core_bytes(&wire).expect("canonical core");
        let env = jcr1::cose_sign1_envelope(&core, &self.steward_sk, &self.steward);
        self.head = jcp_schema::ContentId::of_bytes(&env);
        self.seq += 1;
        self.entries.push(env.clone());
        env
    }

    /// Seal every later receipt under another key. The chain continues: the
    /// next receipt still commits to the one before it, whichever key signed
    /// that.
    ///
    /// A log whose key changes no longer verifies under one key
    /// ([`verify_log`]). What tells a reader where the change is, and that
    /// the steward made it, is a log seal that committed to the new key
    /// beforehand (`jcp-logseal`).
    pub fn rekey(&mut self, steward_sk: SigningKey) {
        self.steward_sk = steward_sk;
    }

    /// Adopt this steward's own prior receipt stream as the log's history, so
    /// the next [`append`](Self::append) links onto the real predecessor
    /// instead of restarting at genesis.
    ///
    /// This is the durability half of SPEC §8.1 — "an enforcement point that
    /// crashes MUST be able to rebuild its budget state by replaying its own
    /// verified receipt stream ... durability and audit are the same artifact".
    /// Without it a restarted enforcement point appends `seq = 0, prev = 0…0`
    /// onto a file that already holds a chain, and [`verify_log`] over the
    /// accumulated stream fails at the first post-restart entry: the one
    /// artifact that records the spend is also the one that will not verify.
    ///
    /// The stream is verified end to end *before* anything is adopted, so a
    /// broken history cannot become this log's history. Pair it with
    /// [`replay_ledger`] to rebuild the budget side.
    ///
    /// # Errors
    /// [`ResumeError::BrokenAt`] if the prior chain does not verify under this
    /// log's steward key; [`ResumeError::NotEmpty`] if this log has already
    /// appended.
    pub fn resume(&mut self, prior: Vec<Vec<u8>>) -> Result<usize, ResumeError> {
        if !self.entries.is_empty() {
            return Err(ResumeError::NotEmpty(self.entries.len()));
        }
        let pubkey = self.steward_sk.verifying_key().to_bytes();
        verify_log(&prior, &self.steward, &pubkey).map_err(ResumeError::BrokenAt)?;
        self.head = prior
            .last()
            .map_or_else(genesis_prev, |e| jcp_schema::ContentId::of_bytes(e));
        self.seq = prior.len() as u64;
        self.entries = prior;
        Ok(self.entries.len())
    }

    /// The steward id these entries are sealed under.
    pub fn steward(&self) -> &str {
        &self.steward
    }

    /// The steward's public key — what [`verify_log`] and [`replay_spend`]
    /// check the stream against.
    pub fn steward_pubkey(&self) -> [u8; 32] {
        self.steward_sk.verifying_key().to_bytes()
    }

    /// The sealed entries, in order.
    pub fn entries(&self) -> &[Vec<u8>] {
        &self.entries
    }

    /// The content id of the most recent entry (genesis sentinel if empty) —
    /// the commitment a downstream log or independent anchor would countersign.
    pub fn head(&self) -> jcp_schema::ContentId {
        self.head
    }
}

/// Project a decision to logged JCR-1 wire JSON: [`to_jcr1_wire`] plus `seq`
/// and `prev` (the previous entry's envelope content id).
pub fn to_jcr1_wire_logged(
    frame: &Frame,
    grant: &Grant,
    decision: &Decision,
    steward: &str,
    seq: u64,
    prev: &jcp_schema::ContentId,
) -> Value {
    let mut wire = to_jcr1_wire(frame, grant, decision, steward);
    if let Value::Object(ref mut o) = wire {
        o.insert("seq".into(), json!(seq));
        o.insert("prev".into(), json!(prev.to_hex()));
    }
    wire
}

/// Verify a hash-chained receipt stream end to end: every envelope's signature
/// verifies under `pubkey`, `seq` increments from zero, and each entry's `prev`
/// equals the content id of the entry before it (genesis links to the all-zero
/// sentinel). Returns the verified count, or `Err(i)` at the first broken link.
pub fn verify_log(entries: &[Vec<u8>], steward: &str, pubkey: &[u8; 32]) -> Result<usize, usize> {
    follow_chain(entries, |env| jcr1::verify_cose_sign1(env, steward, pubkey).ok())
}

/// Follow a receipt stream's hash chain **without verifying any signature**:
/// every envelope is well-formed and names `steward`, `seq` increments from
/// zero, and each entry's `prev` is the content id of the entry before it.
/// Returns the count, or `Err(i)` at the first broken link.
///
/// On its own this proves nothing about who wrote the stream — anyone can
/// build a chain. It is the half of the check that does not depend on the
/// receipts' signature algorithm: a stream that follows, and whose last
/// content id is one a seal commits to (`jcp-logseal`), is byte for byte the
/// stream that was sealed.
pub fn verify_chain(entries: &[Vec<u8>], steward: &str) -> Result<usize, usize> {
    follow_chain(entries, |env| jcr1::open_unverified(env, steward).ok())
}

/// The chain rule, over whichever way of opening an envelope the caller holds
/// it to.
fn follow_chain(entries: &[Vec<u8>], open: impl Fn(&[u8]) -> Option<Vec<u8>>) -> Result<usize, usize> {
    let mut expected_prev = genesis_prev();
    for (i, env) in entries.iter().enumerate() {
        let Some(payload) = open(env) else {
            return Err(i);
        };
        let Ok(v) = jcp_schema::from_canonical_cbor::<Value>(&payload) else {
            return Err(i);
        };
        let seq = v.get("seq").and_then(Value::as_u64);
        let prev = v.get("prev").and_then(Value::as_str);
        if seq != Some(i as u64) || prev != Some(expected_prev.to_hex().as_str()) {
            return Err(i);
        }
        expected_prev = jcp_schema::ContentId::of_bytes(env);
    }
    Ok(entries.len())
}

#[cfg(test)]
mod tests {
    use super::*;
    use ed25519_dalek::SigningKey;
    use jcp_grant::issue;
    use jcp_runtime::Runtime;
    use jcp_schema::{Capability, ContentId, Did, FrameKind, Trust};

    fn sk(s: u8) -> SigningKey {
        SigningKey::from_bytes(&[s; 32])
    }

    fn scenario() -> (Frame, Grant, Decision) {
        let issuer = sk(1);
        let holder = sk(2);
        let resource = ContentId::of_bytes(b"db");
        let grant = Grant {
            issuer: Did::from_verifying_key(&issuer.verifying_key()),
            subject: Did::from_verifying_key(&holder.verifying_key()),
            capability: Capability::new(resource, ["read"]),
            budget_uj: 100,
            budget_funds: None,
            caveats: Vec::new(),
            expiry: 0,
            parent: None,
            delegate_depth: None,
            nonce: [0; 16],
        };
        let sg = issue(&issuer, grant.clone()).unwrap();
        let frame = Frame {
            kind: FrameKind::ToolCall,
            trust: Trust::Control,
            grant_id: grant.id(),
            action: "read".into(),
            resource,
            payload_hash: ContentId::of_bytes(b"q"),
            model: None,
        };
        let mut rt = Runtime::new();
        let d = rt.decide(&frame, &sg, grant.subject, jcp_schema::Energy::measured(30), 10);
        (frame, grant, d)
    }

    /// The exact scenario `gen-vectors` sealed for the PUBLISHED v1 vectors
    /// (nonce `[9;16]`, cost 30 µJ, `now = 10`) — needed to re-verify the real
    /// legacy bytes below.
    fn published_v1_scenario() -> (Frame, Grant, Decision, Decision) {
        let issuer = sk(1);
        let holder = sk(2);
        let resource = ContentId::of_bytes(b"db");
        let grant = Grant {
            issuer: Did::from_verifying_key(&issuer.verifying_key()),
            subject: Did::from_verifying_key(&holder.verifying_key()),
            capability: Capability::new(resource, ["read"]),
            budget_uj: 100,
            budget_funds: None,
            caveats: Vec::new(),
            expiry: 0,
            parent: None,
            delegate_depth: None,
            nonce: [9; 16],
        };
        let sg = issue(&issuer, grant.clone()).unwrap();
        let mk = |trust: Trust| Frame {
            kind: FrameKind::ToolCall,
            trust,
            grant_id: grant.id(),
            action: "read".into(),
            resource,
            payload_hash: ContentId::of_bytes(b"q"),
            model: None,
        };
        let mut rt = Runtime::new();
        let allow_f = mk(Trust::Control);
        let allow_d = rt.decide(&allow_f, &sg, grant.subject, jcp_schema::Energy::measured(30), 10);
        let deny_f = mk(Trust::Data);
        let deny_d = rt.decide(&deny_f, &sg, grant.subject, jcp_schema::Energy::measured(1), 10);
        (allow_f, grant, allow_d, deny_d)
    }

    /// Absent, the field changes nothing: the same bytes, so every receipt
    /// sealed before this existed and every published vector still verifies.
    #[test]
    fn an_absent_environment_leaves_the_bytes_untouched() {
        let (frame, grant, d) = scenario();
        let steward = "did:example:steward";
        let plain = to_jcr1_wire(&frame, &grant, &d, steward);
        let none = to_jcr1_wire_in_environment(&frame, &grant, &d, steward, None);
        assert_eq!(plain, none, "None must be byte-for-byte the historical wire");
        assert!(environment_of(&plain).is_none());
    }

    /// Present, it names the attested run — and the claimed tier rides along so
    /// a mismatch against the resolved attestation is detectable without
    /// resolving it first.
    #[test]
    fn a_named_environment_reaches_the_wire_and_reads_back() {
        let (frame, grant, d) = scenario();
        let att = ContentId::of_bytes(b"attestation");
        let env = EnvironmentBinding::new(att, "S5");
        let wire = to_jcr1_wire_in_environment(&frame, &grant, &d, "did:example:steward", Some(&env));

        assert_ne!(
            wire,
            to_jcr1_wire(&frame, &grant, &d, "did:example:steward"),
            "the binding must be inside the signed bytes, not beside them"
        );
        let read = environment_of(&wire).expect("round-trips");
        assert_eq!(read, env);
        assert_eq!(read.tier, "S5");
    }

    /// The distinction the type exists to preserve: carrying an attestation id
    /// is a POINTER, not evidence. Nothing here resolves or appraises it, and a
    /// host that will misreport a decision can equally name an attestation it
    /// did not earn — so `environment_of` returning `Some` must never be read
    /// as "attested".
    #[test]
    fn a_pointer_is_not_evidence() {
        let (frame, grant, d) = scenario();
        // An id that resolves to nothing at all is still structurally valid.
        let bogus = EnvironmentBinding::new(ContentId::of_bytes(b"never-existed"), "S7");
        let wire =
            to_jcr1_wire_in_environment(&frame, &grant, &d, "did:example:steward", Some(&bogus));
        assert!(
            environment_of(&wire).is_some(),
            "the crate accepts the claim; it is the verifier's job to resolve it"
        );
        // And the crate takes no dependency that could resolve it — the check
        // that matters lives in sandbox-attest, deliberately not here.
        assert_eq!(environment_of(&wire).unwrap().tier, "S7");
    }

    /// A malformed binding reads as absent rather than as a partial claim.
    #[test]
    fn a_malformed_environment_is_not_half_believed() {
        let (frame, grant, d) = scenario();
        let base = to_jcr1_wire(&frame, &grant, &d, "s");

        // Missing the attestation id entirely.
        let mut wire = base.clone();
        wire.as_object_mut().unwrap().insert("environment".into(), json!({ "tier": "S5" }));
        assert!(environment_of(&wire).is_none(), "a tier alone names nothing");

        // Present but unparseable as a content id.
        let mut wire = base;
        wire.as_object_mut()
            .unwrap()
            .insert("environment".into(), json!({ "attestation": "zz", "tier": "S5" }));
        assert!(environment_of(&wire).is_none(), "an unparseable id is not a claim");
    }

    /// **The migration guarantee.** These are the REAL bytes published in
    /// `conformance/v1/legacy_jcp1.json`, sealed under `jcp/1` before
    /// `payload_hash` existed. They MUST still verify — version dispatch
    /// recomputes the legacy preimage — or the bump silently invalidated every
    /// receipt already in the wild.
    ///
    /// The constant below is a copy of that file's **allow** envelope, kept so this
    /// crate's own suite can stand alone. The published file carries an allow *and*
    /// a deny, and both are verified against the file itself by
    /// `jcp-conformance`'s `tests/pack.rs` — which is what a third party actually
    /// downloads, and what should be believed if the two ever disagree.
    #[test]
    fn published_v1_receipts_still_verify() {
        const V1_ALLOW: &str = "d284581fa201270458196469643a6578616d706c653a6a63702d7265666572656e6365a05901d2ae65747275737467636f6e74726f6c66616374696f6e64726561646669737375657278386469643a6b65793a7a364d6b6f6e334e656364364e6b6b79666f476f48786964327a6e476335394c55334b376d756261526346624c664c5867636f73745f756a181e677374657761726478196469643a6578616d706c653a6a63702d7265666572656e6365677375626a65637478386469643a6b65793a7a364d6b6f39685467674d776a535445614a615055664536747163793278765536426e4e713365336f38715642697948677665726469637465616c6c6f77686772616e745f6964784033623161356139636262373831353134636637353162613030376530373765383038333937376234663037623130346433366565393034643932383939386334687265736f75726365784030663766623535636565393361623937373738323936303865383531666133316536386531326462396466633061383032366164323938333134636633663932696275646765745f756a18646a6672616d655f6b696e6469746f6f6c2d63616c6c6b6a63705f72656365697074656a63702f3171656e657267795f70726f76656e616e63656748775368756e74736275646765745f72656d61696e696e675f756a184658405a7be56b33956c069d4e23127baa7b090e5028b9704dff6ca5ac46da546534e667151f80d7d7a605bcc31ea2bb33ec971e3e8b8794f7248a18b34c33bc438509";
        let (allow_f, grant, allow_d, _) = published_v1_scenario();
        let pubkey = sk(7).verifying_key().to_bytes();
        let env = hex::decode(V1_ALLOW).expect("legacy hex");
        verify(&allow_f, &grant, &allow_d, &env, "did:example:jcp-reference", &pubkey)
            .expect("a published jcp/1 receipt MUST still verify after the jcp/2 bump");

        // And it is recognisably legacy: no payload binding on a v1 receipt.
        let core = extract(&env, "did:example:jcp-reference", &pubkey).unwrap();
        assert_eq!(core.verdict, "allow");
        assert_eq!(core.payload_hash, None, "v1 receipts did not bind their payload");
    }

    /// A freshly minted receipt is `jcp/2` and DOES bind its payload.
    #[test]
    fn new_receipts_bind_the_payload() {
        let (f, g, d) = scenario();
        let key = sk(7);
        let env = seal(&f, &g, &d, &key, "did:example:steward").unwrap();
        let core = extract(&env, "did:example:steward", &key.verifying_key().to_bytes()).unwrap();
        assert_eq!(
            core.payload_hash.as_deref(),
            Some(f.payload_hash.to_hex().as_str()),
            "a jcp/2 receipt must commit the payload it decided over"
        );
    }

    /// Changing only the PAYLOAD must break verification — the property the
    /// whole bump exists to provide. Under `jcp/1` this forgery went undetected.
    #[test]
    fn a_swapped_payload_no_longer_verifies() {
        let (f, g, d) = scenario();
        let key = sk(7);
        let env = seal(&f, &g, &d, &key, "did:example:steward").unwrap();
        // Same grant, same action, same cost — different arguments.
        let tampered = Frame { payload_hash: ContentId::of_bytes(b"different-args"), ..f.clone() };
        let r = verify(&tampered, &g, &d, &env, "did:example:steward", &key.verifying_key().to_bytes());
        assert!(matches!(r, Err(ReceiptError::PayloadMismatch)), "payload swap must be caught");
    }

    #[test]
    fn allow_receipt_seals_and_verifies() {
        let (f, g, d) = scenario();
        assert!(d.is_allow());
        let key = sk(7);
        let steward = "did:example:jcp-runtime";
        let env = seal(&f, &g, &d, &key, steward).unwrap();
        assert!(verify(&f, &g, &d, &env, steward, &key.verifying_key().to_bytes()).is_ok());
        assert!(verify(&f, &g, &d, &env, "did:example:wrong", &key.verifying_key().to_bytes()).is_err());
    }

    #[test]
    fn hash_chained_log_is_tamper_evident() {
        let issuer = sk(1);
        let holder = sk(2);
        let resource = ContentId::of_bytes(b"db");
        let grant = Grant {
            issuer: Did::from_verifying_key(&issuer.verifying_key()),
            subject: Did::from_verifying_key(&holder.verifying_key()),
            capability: Capability::new(resource, ["read"]),
            budget_uj: 1000,
            budget_funds: None,
            caveats: Vec::new(),
            expiry: 0,
            parent: None,
            delegate_depth: None,
            nonce: [0; 16],
        };
        let sg = issue(&issuer, grant.clone()).unwrap();
        let frame = Frame {
            kind: FrameKind::ToolCall,
            trust: Trust::Control,
            grant_id: grant.id(),
            action: "read".into(),
            resource,
            payload_hash: ContentId::of_bytes(b"q"),
            model: None,
        };
        let steward_sk = sk(7);
        let pubkey = steward_sk.verifying_key().to_bytes();
        let steward = "did:example:gw";
        let mut rt = Runtime::new();
        let mut log = ReceiptLog::new(steward_sk, steward);

        // Three sealed decisions: allow, allow, then a deny (data frame).
        for _ in 0..2 {
            let d = rt.decide(&frame, &sg, grant.subject, jcp_schema::Energy::measured(10), 0);
            log.append(&frame, &grant, &d);
        }
        let mut poison = frame.clone();
        poison.trust = Trust::Data;
        let d = rt.decide(&poison, &sg, grant.subject, jcp_schema::Energy::measured(1), 0);
        log.append(&poison, &grant, &d);

        assert_eq!(verify_log(log.entries(), steward, &pubkey), Ok(3));

        // Excise the middle receipt: the chain breaks at the splice point.
        let mut tampered = log.entries().to_vec();
        tampered.remove(1);
        assert_eq!(verify_log(&tampered, steward, &pubkey), Err(1));

        // Reorder: same break.
        let mut swapped = log.entries().to_vec();
        swapped.swap(0, 1);
        assert!(verify_log(&swapped, steward, &pubkey).is_err());
    }

    #[test]
    fn deny_receipt_records_the_reason() {
        let (mut f, g, _) = scenario();
        f.trust = Trust::Data; // a poisoned frame
        let mut rt = Runtime::new();
        let sg = issue(&sk(1), g.clone()).unwrap();
        let d = rt.decide(&f, &sg, g.subject, jcp_schema::Energy::measured(1), 10);
        let wire = to_jcr1_wire(&f, &g, &d, "did:example:r");
        let o = wire.as_object().unwrap();
        assert_eq!(o["verdict"], json!("deny"));
        assert_eq!(o["deny_reason"], json!("untrusted-control"));
        // and it still seals as a non-repudiable record
        let key = sk(7);
        let env = seal(&f, &g, &d, &key, "s").unwrap();
        assert!(verify(&f, &g, &d, &env, "s", &key.verifying_key().to_bytes()).is_ok());
    }

    // ── jcp/3 flow seal (SPEC §8, §4.10) ─────────────────────────────────────

    use jcp_schema::flow::{Integrity, Label, Origin, Origins, Readers};
    use jcp_schema::{FlowFacts, Provenance};

    fn tainted_facts() -> FlowFacts {
        FlowFacts {
            label: Label {
                integrity: Integrity::Untrusted,
                origins: Origins::one(Origin::channel(ContentId::of_bytes(b"mail:read"))),
                readers: Readers::Public,
            },
            witness_id: ContentId::of_bytes(b"a witness"),
            eval_uj: 42,
            eval_prov: Provenance::ModelBased,
        }
    }

    #[test]
    fn a_clean_call_is_byte_identical_to_jcp2() {
        // The load-bearing compatibility property: a clean flow seal produces the
        // exact bytes of the plain path, so a flow deployment and a non-flow one
        // share a stream and every existing receipt is unmoved.
        let (f, g, d) = scenario();
        let key = sk(7);
        let plain = seal(&f, &g, &d, &key, "s").unwrap();
        let clean = seal_flow(&f, &g, &d, &key, "s", &FlowSeal::clean()).unwrap();
        assert_eq!(plain, clean, "a clean flow seal == the plain jcp/2 seal");
        // Even facts that were computed but are bottom stay jcp/2.
        let bottom = FlowSeal { facts: Some(FlowFacts::bottom()), ceiling: None };
        assert_eq!(plain, seal_flow(&f, &g, &d, &key, "s", &bottom).unwrap());
    }

    #[test]
    fn a_tainted_call_seals_jcp3_with_a_flow_block() {
        let (f, g, d) = scenario();
        let key = sk(7);
        let seal_data = FlowSeal {
            facts: Some(tainted_facts()),
            ceiling: Some(ContentId::of_bytes(b"the ceiling")),
        };
        let env = seal_flow(&f, &g, &d, &key, "s", &seal_data).unwrap();

        // It verifies against the same seal, and NOT as a plain jcp/2 (the flow
        // block is part of the signed core).
        let pk = key.verifying_key().to_bytes();
        assert!(verify_flow(&f, &g, &d, &seal_data, &env, "s", &pk).is_ok());
        assert!(verify(&f, &g, &d, &env, "s", &pk).is_err(), "jcp/3 needs the seal to verify");

        // The profile and flow block are present and correct.
        let payload = jcr1::verify_cose_sign1(&env, "s", &pk).unwrap();
        let v: Value = jcp_schema::from_canonical_cbor(&payload).unwrap();
        assert_eq!(v.get("jcp_receipt").and_then(Value::as_str), Some("jcp/3"));
        let flow = v.get("flow").expect("flow block");
        assert_eq!(flow.get("integrity").and_then(Value::as_str), Some("untrusted"));
        assert_eq!(flow.get("verdict").and_then(Value::as_str), Some("below")); // the scenario allowed
        assert_eq!(flow.get("flow_uj").and_then(Value::as_u64), Some(42));
        assert_eq!(flow.get("flow_energy_provenance").and_then(Value::as_str), Some("ModelBased"));
        assert!(flow.get("witness").and_then(Value::as_str).is_some());
        assert!(flow.get("ceiling").and_then(Value::as_str).is_some());
    }

    #[test]
    fn a_flow_denied_call_seals_verdict_above() {
        // A tainted call denied for flow records "above" the ceiling.
        let (f, g, _d) = scenario();
        let denied = Decision::refused(jcp_schema::DenyReason::TaintedFlow, jcp_schema::Energy::measured(0), 100);
        let key = sk(7);
        let seal_data = FlowSeal { facts: Some(tainted_facts()), ceiling: None };
        let env = seal_flow(&f, &g, &denied, &key, "s", &seal_data).unwrap();
        let payload = jcr1::verify_cose_sign1(&env, "s", &key.verifying_key().to_bytes()).unwrap();
        let v: Value = jcp_schema::from_canonical_cbor(&payload).unwrap();
        assert_eq!(v["flow"].get("verdict").and_then(Value::as_str), Some("above"));
        assert_eq!(v.get("deny_reason").and_then(Value::as_str), Some("tainted-flow"));
    }

    #[test]
    fn a_mixed_jcp2_and_jcp3_log_verifies_end_to_end() {
        let (f, g, d) = scenario();
        let key = sk(7);
        let mut log = ReceiptLog::new(key.clone(), "s");
        log.append_flow(&f, &g, &d, &FlowSeal::clean()); // jcp/2
        log.append_flow(&f, &g, &d, &FlowSeal { facts: Some(tainted_facts()), ceiling: None }); // jcp/3
        log.append(&f, &g, &d); // jcp/2 plain
        let pk = key.verifying_key().to_bytes();
        assert_eq!(verify_log(log.entries(), "s", &pk), Ok(3), "the chain is intact across profiles");

        // extract reads a jcp/3 entry's core generically (it is jcp/2 + a block).
        let core = extract(&log.entries()[1], "s", &pk).unwrap();
        assert_eq!(core.verdict, "allow");
        assert_eq!(core.cost_uj, 30, "cost_uj is the tool energy, untouched by flow_uj");
    }
    fn tomb(erased: jcp_schema::ContentId, uj: u64) -> Tombstone {
        Tombstone {
            erased,
            erased_at_us: 1_700_000_000_000_000,
            authority: "dsr-2026-0042".into(),
            cost_uj: uj,
            energy_provenance: "HwShunt".into(),
        }
    }

    // ---- SPEC §8.1: the stream is the write-ahead log ----------------

    /// A restarted enforcement point adopts its own stream, so the chain
    /// continues instead of restarting on top of itself.
    #[test]
    fn a_resumed_log_continues_the_chain() {
        let (frame, grant, d) = scenario();
        let steward = "did:example:steward";

        let mut first_run = ReceiptLog::new(sk(3), steward);
        first_run.append(&frame, &grant, &d);
        first_run.append(&frame, &grant, &d);
        let stream: Vec<Vec<u8>> = first_run.entries().to_vec();
        let head = first_run.head();
        drop(first_run);

        let mut second_run = ReceiptLog::new(sk(3), steward);
        assert_eq!(second_run.resume(stream), Ok(2), "our own chain verifies");
        assert_eq!(second_run.head(), head, "it continues from the real head");
        second_run.append(&frame, &grant, &d);

        assert_eq!(
            verify_log(second_run.entries(), steward, &sk(3).verifying_key().to_bytes()),
            Ok(3),
            "the accumulated stream verifies end to end across the restart"
        );
    }

    /// What happened without the resume, and why it matters: the second run
    /// appends `seq = 0, prev = 0…0` on top of a chain that already has two
    /// links, so the accumulated file — the only record of the spend — stops
    /// verifying at exactly that entry.
    #[test]
    fn a_log_that_does_not_resume_breaks_the_accumulated_stream() {
        let (frame, grant, d) = scenario();
        let steward = "did:example:steward";

        let mut first_run = ReceiptLog::new(sk(3), steward);
        first_run.append(&frame, &grant, &d);
        first_run.append(&frame, &grant, &d);
        let mut accumulated: Vec<Vec<u8>> = first_run.entries().to_vec();

        let mut second_run = ReceiptLog::new(sk(3), steward);
        accumulated.push(second_run.append(&frame, &grant, &d));

        assert_eq!(
            verify_log(&accumulated, steward, &sk(3).verifying_key().to_bytes()),
            Err(2),
            "the first post-restart entry breaks the chain"
        );
    }

    /// A history that does not verify cannot become this log's history.
    #[test]
    fn resume_refuses_a_broken_chain() {
        let (frame, grant, d) = scenario();
        let steward = "did:example:steward";
        let mut first = ReceiptLog::new(sk(3), steward);
        first.append(&frame, &grant, &d);
        first.append(&frame, &grant, &d);
        let mut stream: Vec<Vec<u8>> = first.entries().to_vec();
        *stream[1].last_mut().expect("envelope bytes") ^= 1;

        let mut second = ReceiptLog::new(sk(3), steward);
        assert_eq!(second.resume(stream), Err(ResumeError::BrokenAt(1)));
        assert!(second.entries().is_empty(), "nothing was adopted");
        assert_eq!(second.head(), genesis_prev(), "and the head did not move");
    }

    /// Adopting a history after appending would renumber what this log already
    /// sealed, so it is refused.
    #[test]
    fn resume_refuses_a_log_that_already_appended() {
        let (frame, grant, d) = scenario();
        let steward = "did:example:steward";
        let mut a = ReceiptLog::new(sk(3), steward);
        let stream = vec![a.append(&frame, &grant, &d)];

        let mut b = ReceiptLog::new(sk(3), steward);
        b.append(&frame, &grant, &d);
        assert_eq!(b.resume(stream), Err(ResumeError::NotEmpty(1)));
    }

    /// The invariant a hash chain makes non-negotiable: erasure must not break
    /// the links. Nothing behind the tombstone is touched, so every prior
    /// entry's bytes — and therefore every `prev` — are exactly as they were.
    #[test]
    fn erasure_appends_and_the_chain_survives_it() {
        let (frame, grant, d) = scenario();
        let mut log = ReceiptLog::new(sk(3), "did:example:steward");
        let first = log.append(&frame, &grant, &d);
        let before = jcp_schema::ContentId::of_bytes(&first);
        let n_before = log.entries().len();

        let t = log.erase(&tomb(before, d.cost.uj()));

        assert_eq!(log.entries().len(), n_before + 1, "erasure APPENDS, never removes");
        assert_eq!(log.entries()[0], first, "the erased entry's bytes are untouched");

        // The sealed payload is exactly the chained wire — compared byte-for-byte
        // rather than re-parsed, pinning the content as well as the signature.
        let payload =
            jcr1::verify_cose_sign1(&t, "did:example:steward", &sk(3).verifying_key().to_bytes())
                .expect("tombstone verifies under the steward key");
        let expected = jcr1::signed_core_bytes(&tombstone_wire(
            &tomb(before, d.cost.uj()),
            "did:example:steward",
            1,
            &before,
        ))
        .expect("canonical core");
        assert_eq!(payload, expected);
    }

    /// An erased record still counts toward energy totals. Dropping the joules
    /// would silently shrink every rollup, indistinguishably from an efficiency
    /// gain — a conservation break arriving through a privacy feature.
    #[test]
    fn erasure_conserves_the_energy_total() {
        let (frame, grant, d) = scenario();
        let cost = d.cost.uj();
        let mut log = ReceiptLog::new(sk(3), "did:example:steward");
        let first = log.append(&frame, &grant, &d);
        let t = tomb(jcp_schema::ContentId::of_bytes(&first), cost);
        log.erase(&t);
        assert_eq!(t.cost_uj, cost, "the joules survive the erasure");
        assert_eq!(t.energy_provenance, "HwShunt");
    }

    /// A tombstone must not re-introduce what the erasure removed.
    #[test]
    fn a_tombstone_carries_nothing_personal() {
        let id = jcp_schema::ContentId::of_bytes(b"entry");
        let wire = tombstone_wire(&tomb(id, 42), "s", 1, &id);
        for forbidden in ["payload_hash", "resource", "subject", "action", "issuer"] {
            assert!(
                wire.get(forbidden).is_none(),
                "a tombstone must not carry `{forbidden}` — that is the datum erasure removed"
            );
        }
        assert_eq!(wire["authority"].as_str(), Some("dsr-2026-0042"));
    }

    /// A tombstone declares its own profile, so no reader mistakes it for a
    /// decision that happened to carry no payload.
    #[test]
    fn a_tombstone_is_not_a_decision() {
        let id = jcp_schema::ContentId::of_bytes(b"x");
        let wire = tombstone_wire(&tomb(id, 1), "s", 0, &id);
        assert_eq!(wire["jcp_receipt"].as_str(), Some(TOMBSTONE_PROFILE));
        assert_ne!(wire["jcp_receipt"].as_str(), Some(PROFILE));
        assert!(wire.get("verdict").is_none(), "a tombstone has no verdict");
    }

}
