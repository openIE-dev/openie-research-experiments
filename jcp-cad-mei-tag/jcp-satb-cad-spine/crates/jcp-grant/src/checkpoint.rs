//! Mid-run checkpoints and amendments (SPEC §4.7): steering a long run under
//! separation of duties.
//!
//! A multi-hour agent run is not a black box that returns at the end. At
//! defined boundaries the running agent commits to its state — a
//! **checkpoint** — and a *different* principal may steer it: tighten its
//! budget, drop a capability, or hand it a new instruction set, before it
//! continues. Every step is signed and chained, so the record answers not
//! just "what did the agent do" but "who intervened, when, and how".
//!
//! Two roles, structurally distinct (the separation-of-duties rule the
//! methodology layer requires):
//!
//! - the **author** of a checkpoint is the running agent — the grant's
//!   `subject`. It commits to its own state; it cannot steer itself.
//! - the **amender** is the grant's `issuer` — the steward who delegated the
//!   authority in the first place, and is therefore already a distinct
//!   principal from the agent. Steering is an issuer power, like revocation
//!   (§4.3); an amendment is a *soft revoke* that re-bounds the run instead of
//!   killing it.
//!
//! An amendment may only **tighten**, and the bar is what the grant has *left*
//! at the checkpoint, not what it was issued with. The distinction is the whole
//! point: on a 1 000 µJ grant whose run has already spent 900, an amendment of
//! 1 000 reads as "tightening" against the issued figure while handing the run
//! ten times its remainder. A checkpoint that states its [`Spend`] is therefore
//! measured against [`remaining_uj`]; one that states nothing falls back to the
//! issued budget, which is the older and weaker rule (see
//! [`amendable_ceiling_uj`] for why the fallback is not a refusal). Widening is
//! just issuing a new grant, and is out of scope here.
//!
//! What the spend figure is worth. The checkpoint is authored by the *agent* —
//! the party the remainder constrains — so its declared spend is a claim, not
//! an independent measurement, and the `provenance` grade travels with it so
//! the amender can see which kind of claim it is. Two things make the claim
//! hard to shrink: it is signed, so understating it is attributable, and it is
//! cumulative, so [`checkpoint_follows`] catches a later checkpoint that
//! declares less than an earlier one or drops the field it once carried. What
//! this layer does not do is independently meter the run; a deployment that
//! needs that binds receipts (§5) to the checkpoint instead of trusting the
//! figure.

use ed25519_dalek::{Signature, Signer, SigningKey, Verifier};
use jcp_schema::{canonical_cbor, ContentId, Did, Grant, Provenance, SignedGrant};
use serde::{Deserialize, Serialize};

use crate::{issue, GrantError};

/// A commitment, made by the running agent, to the run's state at a boundary.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Checkpoint {
    /// The grant the run is currently bounded by.
    pub grant_id: ContentId,
    /// The agent making the commitment — MUST be the grant's `subject`.
    pub author: Did,
    /// A content address committing to the run's state at this boundary
    /// (e.g. a sandbox snapshot root, §13 of the Sandbox spec).
    pub state_hash: ContentId,
    /// Monotonic checkpoint index within the run.
    pub seq: u64,
    pub nonce: [u8; 16],
    /// What the run has spent under this grant, as of this boundary.
    ///
    /// `None` is the historical shape and is skipped on the wire, so every
    /// checkpoint written before this field existed keeps its
    /// [`Checkpoint::id`] and the sealed conformance vectors are unchanged.
    /// It is also the *weaker* shape — see [`remaining_uj`].
    ///
    /// `skip_serializing_if` is load-bearing, not tidiness: the JCR-1 signed
    /// core forbids nulls, so without it `Checkpoint::id()` fails outright with
    /// `DisallowedType("null")` on every checkpoint that states no spend.
    /// Omission is the only encoding the canonical form permits.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub spent: Option<Spend>,
}

/// Energy spent under a grant up to a checkpoint, with the provenance of the
/// figure.
///
/// Cumulative rather than since-the-previous-checkpoint: one checkpoint then
/// answers "how much is left" on its own, without the verifier having to hold
/// the whole chain and without a missing link silently understating the total.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Spend {
    /// Microjoules spent under this grant so far.
    pub uj: u64,
    /// How the figure was obtained. Carried because a budget decision made on
    /// an `Estimator` figure is a different decision from one made on a
    /// hardware reading, and the amendment it justifies is signed either way.
    pub provenance: Provenance,
}

/// What the grant has left at this checkpoint, when the checkpoint says what
/// it spent.
///
/// `None` when the checkpoint declares no spend. That is not zero — it is
/// *unknown*, and the two must not be confused: treating unknown as zero
/// would let an amendment hand back the whole grant.
pub fn remaining_uj(grant: &Grant, cp: &Checkpoint) -> Option<u64> {
    cp.spent.map(|s| grant.budget_uj.saturating_sub(s.uj))
}

impl Checkpoint {
    pub fn id(&self) -> ContentId {
        ContentId::of(self).expect("checkpoint fields are canonical")
    }
}

/// A checkpoint plus the agent's signature over its canonical bytes.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct SignedCheckpoint {
    pub checkpoint: Checkpoint,
    pub signature: Vec<u8>,
}

/// A steward's signed steering decision applied at a checkpoint.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Amendment {
    /// The checkpoint being steered.
    pub checkpoint_id: ContentId,
    /// The steward — MUST be the grant's `issuer` and MUST differ from the
    /// checkpoint's author (separation of duties).
    pub amender: Did,
    /// The budget the run continues under; MUST be ≤ the checkpoint grant's.
    pub new_budget_uj: u64,
    /// An optional commitment to a revised instruction set handed to the
    /// agent for the next interval.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub instruction_id: Option<ContentId>,
    pub nonce: [u8; 16],
}

impl Amendment {
    pub fn id(&self) -> ContentId {
        ContentId::of(self).expect("amendment fields are canonical")
    }
}

/// An amendment plus the steward's signature over its canonical bytes.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct SignedAmendment {
    pub amendment: Amendment,
    pub signature: Vec<u8>,
}

/// Why a checkpoint or amendment was refused.
#[derive(Debug)]
pub enum CheckpointError {
    /// A checkpoint authored by a principal that is not the grant's subject.
    NotTheSubject,
    /// An amendment by a principal that is not the grant's issuer.
    NotTheIssuer,
    /// The amender and the agent are the same principal — an agent may not
    /// steer itself.
    SeparationOfDuties,
    /// An amendment that would widen authority rather than tighten it.
    Amplifies(&'static str),
    /// A signature that did not verify.
    BadSignature,
    /// An object that names the wrong grant or checkpoint.
    ChainBroken(&'static str),
    /// Malformed signature bytes.
    SigShape(String),
    Grant(GrantError),
}

impl From<GrantError> for CheckpointError {
    fn from(e: GrantError) -> Self {
        CheckpointError::Grant(e)
    }
}

/// The most an amendment at this checkpoint may grant.
///
/// The remainder where the checkpoint declares its spend; the whole grant
/// otherwise. The fallback is deliberately the old, weaker rule rather than a
/// refusal: a checkpoint written before `spent` existed is still a valid
/// checkpoint, and rejecting it would break running deployments to fix a hole
/// it cannot express. What it does mean is that the guarantee is only as
/// strong as the checkpoint — which [`remaining_uj`] returning `None` is how a
/// verifier finds out.
fn amendable_ceiling_uj(grant: &Grant, cp: &Checkpoint) -> u64 {
    remaining_uj(grant, cp).unwrap_or(grant.budget_uj)
}

/// Check that `next` is a lawful successor to `prev` within one run.
///
/// Each object on its own is well-formed; this is the relationship between
/// them, and it is where an understated spend becomes visible. A declared
/// spend is cumulative, so across a chain it may only rise, and a checkpoint
/// that once declared a figure may not later go silent — otherwise an agent
/// could check in at 900 µJ spent, then check in again saying nothing, and
/// recover the whole issued budget as its ceiling.
///
/// Callers that keep the chain SHOULD run this before honouring an amendment
/// at `next`. It is deliberately not folded into [`verify_checkpoint`], which
/// is given one checkpoint and cannot see a predecessor it was never handed.
pub fn checkpoint_follows(prev: &Checkpoint, next: &Checkpoint) -> Result<(), CheckpointError> {
    if next.grant_id != prev.grant_id {
        return Err(CheckpointError::ChainBroken("checkpoints name different grants"));
    }
    if next.author != prev.author {
        return Err(CheckpointError::ChainBroken("checkpoints have different authors"));
    }
    if next.seq <= prev.seq {
        return Err(CheckpointError::ChainBroken("checkpoint seq did not advance"));
    }
    match (prev.spent, next.spent) {
        (Some(p), Some(n)) if n.uj < p.uj => Err(CheckpointError::Amplifies(
            "cumulative spend fell between checkpoints",
        )),
        (Some(_), None) => Err(CheckpointError::Amplifies(
            "a checkpoint that declared its spend later declared none",
        )),
        _ => Ok(()),
    }
}

/// Say which ceiling was exceeded, since the two are different claims.
fn amplify_reason(cp: &Checkpoint) -> &'static str {
    if cp.spent.is_some() {
        "amended budget exceeds what the grant has left at this checkpoint"
    } else {
        "amended budget exceeds the grant"
    }
}

/// Emit a checkpoint. The signer MUST be the grant's `subject` — only the
/// running agent commits to its own state.
/// `spent` is `Option` rather than a plain figure because a run that genuinely
/// cannot meter itself must be able to say so, and because the difference
/// matters: `None` means *unknown*, not zero, and an amendment at an
/// unknown-spend checkpoint falls back to the weaker whole-grant ceiling.
/// It is a parameter rather than a second constructor so that every call site
/// decides visibly.
#[allow(clippy::too_many_arguments)]
pub fn checkpoint(
    agent_sk: &SigningKey,
    grant: &SignedGrant,
    state_hash: ContentId,
    seq: u64,
    nonce: [u8; 16],
    spent: Option<Spend>,
) -> Result<SignedCheckpoint, CheckpointError> {
    let author = Did::from_verifying_key(&agent_sk.verifying_key());
    if author != grant.grant.subject {
        return Err(CheckpointError::NotTheSubject);
    }
    let cp = Checkpoint { grant_id: grant.grant.id(), author, state_hash, seq, nonce, spent };
    let bytes = canonical_cbor(&cp).map_err(GrantError::from)?;
    let signature = agent_sk.sign(&bytes).to_bytes().to_vec();
    Ok(SignedCheckpoint { checkpoint: cp, signature })
}

/// Verify a checkpoint against the grant it cites: it must name that grant, be
/// authored by the grant's subject, and carry the subject's signature.
pub fn verify_checkpoint(sc: &SignedCheckpoint, grant: &SignedGrant) -> Result<(), CheckpointError> {
    if sc.checkpoint.grant_id != grant.grant.id() {
        return Err(CheckpointError::ChainBroken("checkpoint names a different grant"));
    }
    if sc.checkpoint.author != grant.grant.subject {
        return Err(CheckpointError::NotTheSubject);
    }
    let vk = sc.checkpoint.author.verifying_key().map_err(GrantError::from)?;
    let bytes = canonical_cbor(&sc.checkpoint).map_err(GrantError::from)?;
    let sig = Signature::from_slice(&sc.signature).map_err(|e| CheckpointError::SigShape(e.to_string()))?;
    vk.verify(&bytes, &sig).map_err(|_| CheckpointError::BadSignature)
}

/// Author an amendment at a checkpoint. The signer MUST be the grant's issuer
/// (steering is an issuer power) and MUST differ from the checkpoint's author
/// (separation of duties); the new budget MUST NOT exceed the grant's.
pub fn amend(
    steward_sk: &SigningKey,
    grant: &SignedGrant,
    cp: &SignedCheckpoint,
    new_budget_uj: u64,
    instruction_id: Option<ContentId>,
    nonce: [u8; 16],
) -> Result<SignedAmendment, CheckpointError> {
    let amender = Did::from_verifying_key(&steward_sk.verifying_key());
    if amender != grant.grant.issuer {
        return Err(CheckpointError::NotTheIssuer);
    }
    if amender == cp.checkpoint.author {
        return Err(CheckpointError::SeparationOfDuties);
    }
    // The ceiling is what the grant has LEFT, not what it was issued with.
    //
    // Comparing against `grant.budget_uj` was the bug: on a 1 000 000 µJ grant
    // whose run had already spent 900 000, an amendment of 1 000 000 passed as
    // "tightening" while handing the run ten times its remainder. An amendment
    // is a soft revoke, and a soft revoke that restores spent budget is an
    // escalation — which is exactly what this module's own documentation says
    // steering can never do.
    if new_budget_uj > amendable_ceiling_uj(&grant.grant, &cp.checkpoint) {
        return Err(CheckpointError::Amplifies(amplify_reason(&cp.checkpoint)));
    }
    let amendment = Amendment {
        checkpoint_id: cp.checkpoint.id(),
        amender,
        new_budget_uj,
        instruction_id,
        nonce,
    };
    let bytes = canonical_cbor(&amendment).map_err(GrantError::from)?;
    let signature = steward_sk.sign(&bytes).to_bytes().to_vec();
    Ok(SignedAmendment { amendment, signature })
}

/// Verify an amendment against the grant and checkpoint it steers: it must
/// name that checkpoint, be authored by the grant's issuer, differ from the
/// agent, not amplify the budget, and carry the issuer's signature.
pub fn verify_amendment(
    sa: &SignedAmendment,
    grant: &SignedGrant,
    cp: &SignedCheckpoint,
) -> Result<(), CheckpointError> {
    if sa.amendment.checkpoint_id != cp.checkpoint.id() {
        return Err(CheckpointError::ChainBroken("amendment names a different checkpoint"));
    }
    if sa.amendment.amender != grant.grant.issuer {
        return Err(CheckpointError::NotTheIssuer);
    }
    if sa.amendment.amender == cp.checkpoint.author {
        return Err(CheckpointError::SeparationOfDuties);
    }
    if sa.amendment.new_budget_uj > amendable_ceiling_uj(&grant.grant, &cp.checkpoint) {
        return Err(CheckpointError::Amplifies(amplify_reason(&cp.checkpoint)));
    }
    let vk = sa.amendment.amender.verifying_key().map_err(GrantError::from)?;
    let bytes = canonical_cbor(&sa.amendment).map_err(GrantError::from)?;
    let sig = Signature::from_slice(&sa.signature).map_err(|e| CheckpointError::SigShape(e.to_string()))?;
    vk.verify(&bytes, &sig).map_err(|_| CheckpointError::BadSignature)
}

/// Mint the **continuation grant** the run resumes under: the steward (issuer)
/// re-binds the same agent to the same capability with the amended budget,
/// linked back to the steered grant. This is an issuer re-issue, not a
/// holder delegation — it is justified by the signed checkpoint+amendment
/// pair, which an auditor verifies alongside it, rather than by the
/// holder-delegation rule of `verify_chain`.
pub fn apply_amendment(
    steward_sk: &SigningKey,
    grant: &SignedGrant,
    cp: &SignedCheckpoint,
    sa: &SignedAmendment,
) -> Result<SignedGrant, CheckpointError> {
    verify_checkpoint(cp, grant)?;
    verify_amendment(sa, grant, cp)?;
    let steward = Did::from_verifying_key(&steward_sk.verifying_key());
    if steward != grant.grant.issuer {
        return Err(CheckpointError::NotTheIssuer);
    }
    let continuation = Grant {
        issuer: steward,
        subject: grant.grant.subject,
        capability: grant.grant.capability.clone(),
        budget_uj: sa.amendment.new_budget_uj,
        budget_funds: None,
        caveats: Vec::new(),
        expiry: grant.grant.expiry,
        parent: Some(grant.grant.id()),
        delegate_depth: grant.grant.delegate_depth,
        nonce: sa.amendment.nonce,
    };
    Ok(issue(steward_sk, continuation)?)
}

#[cfg(test)]
mod tests {
    use super::*;
    use jcp_schema::Capability;

    fn did(sk: &SigningKey) -> Did {
        Did::from_verifying_key(&sk.verifying_key())
    }

    /// steward (issuer) delegates to agent (subject) — distinct principals.
    fn setup() -> (SigningKey, SigningKey, SignedGrant) {
        let steward = SigningKey::from_bytes(&[1u8; 32]);
        let agent = SigningKey::from_bytes(&[2u8; 32]);
        let cap = Capability::new(ContentId::of_bytes(b"task"), ["read", "write"]);
        let grant = Grant {
            issuer: did(&steward),
            subject: did(&agent),
            capability: cap,
            budget_uj: 1_000,
            budget_funds: None,
            caveats: Vec::new(),
            expiry: 0,
            parent: None,
            delegate_depth: None,
            nonce: [0u8; 16],
        };
        (steward.clone(), agent.clone(), issue(&steward, grant).unwrap())
    }

    #[test]
    fn checkpoint_round_trips_and_binds_to_subject() {
        let (_steward, agent, g) = setup();
        let cp = checkpoint(&agent, &g, ContentId::of_bytes(b"state-1"), 0, [1u8; 16], None).unwrap();
        verify_checkpoint(&cp, &g).unwrap();
        assert_eq!(cp.checkpoint.author, g.grant.subject);
    }

    #[test]
    fn agent_may_not_checkpoint_a_grant_it_does_not_hold() {
        let (steward, _agent, g) = setup();
        // The steward is not the subject — its checkpoint is refused.
        let r = checkpoint(&steward, &g, ContentId::of_bytes(b"s"), 0, [1u8; 16], None);
        assert!(matches!(r, Err(CheckpointError::NotTheSubject)));
    }

    #[test]
    fn issuer_amends_and_run_continues_under_tighter_budget() {
        let (steward, agent, g) = setup();
        let cp = checkpoint(&agent, &g, ContentId::of_bytes(b"state-1"), 0, [1u8; 16], None).unwrap();
        let am = amend(&steward, &g, &cp, 400, Some(ContentId::of_bytes(b"new-instructions")), [2u8; 16]).unwrap();
        verify_amendment(&am, &g, &cp).unwrap();
        let cont = apply_amendment(&steward, &g, &cp, &am).unwrap();
        crate::verify(&cont).unwrap();
        assert_eq!(cont.grant.subject, g.grant.subject, "the same agent continues");
        assert_eq!(cont.grant.budget_uj, 400, "under the tightened budget");
        assert_eq!(cont.grant.parent, Some(g.grant.id()), "linked to the steered grant");
    }

    #[test]
    fn an_agent_cannot_steer_itself() {
        // A grant whose issuer == subject (self-issued): an amendment must
        // still be refused, because amender would equal the checkpoint author.
        let agent = SigningKey::from_bytes(&[2u8; 32]);
        let cap = Capability::new(ContentId::of_bytes(b"t"), ["read"]);
        let self_grant = Grant {
            issuer: did(&agent), subject: did(&agent), capability: cap,
            budget_uj: 1_000, expiry: 0, parent: None, delegate_depth: None, nonce: [0u8; 16], budget_funds: None, caveats: Vec::new(),
        };
        let g = issue(&agent, self_grant).unwrap();
        let cp = checkpoint(&agent, &g, ContentId::of_bytes(b"s"), 0, [1u8; 16], None).unwrap();
        let r = amend(&agent, &g, &cp, 100, None, [2u8; 16]);
        assert!(matches!(r, Err(CheckpointError::SeparationOfDuties)));
    }

    #[test]
    fn a_non_issuer_cannot_amend() {
        let (_steward, agent, g) = setup();
        let stranger = SigningKey::from_bytes(&[9u8; 32]);
        let cp = checkpoint(&agent, &g, ContentId::of_bytes(b"s"), 0, [1u8; 16], None).unwrap();
        let r = amend(&stranger, &g, &cp, 100, None, [2u8; 16]);
        assert!(matches!(r, Err(CheckpointError::NotTheIssuer)));
    }

    #[test]
    fn an_amendment_may_only_tighten() {
        let (steward, agent, g) = setup();
        let cp = checkpoint(&agent, &g, ContentId::of_bytes(b"s"), 0, [1u8; 16], None).unwrap();
        let r = amend(&steward, &g, &cp, 5_000, None, [2u8; 16]);
        assert!(matches!(r, Err(CheckpointError::Amplifies(_))));
    }

    #[test]
    fn a_forged_amendment_for_another_checkpoint_is_refused() {
        let (steward, agent, g) = setup();
        let cp1 = checkpoint(&agent, &g, ContentId::of_bytes(b"s1"), 0, [1u8; 16], None).unwrap();
        let cp2 = checkpoint(&agent, &g, ContentId::of_bytes(b"s2"), 1, [2u8; 16], None).unwrap();
        let am = amend(&steward, &g, &cp1, 400, None, [3u8; 16]).unwrap();
        // The amendment was authored for cp1; presented against cp2 it fails.
        assert!(matches!(verify_amendment(&am, &g, &cp2), Err(CheckpointError::ChainBroken(_))));
    }
    // ---- the remainder rule -------------------------------------------------

    #[test]
    fn an_amendment_may_not_restore_spent_budget() {
        // The hole this field exists to close. Before `spent`, both `amend` and
        // `verify_amendment` compared against `grant.budget_uj` — the budget as
        // ISSUED — so this amendment was accepted as a tightening while handing
        // the run ten times what it had left.
        let (steward, agent, g) = setup();
        let cp = checkpoint(
            &agent, &g, ContentId::of_bytes(b"s"), 0, [1u8; 16],
            Some(Spend { uj: 900, provenance: Provenance::HwShunt }),
        )
        .unwrap();
        assert_eq!(remaining_uj(&g.grant, &cp.checkpoint), Some(100));
        assert!(matches!(
            amend(&steward, &g, &cp, 1_000, None, [2u8; 16]),
            Err(CheckpointError::Amplifies(_))
        ));
        // One microjoule over the remainder is still over it.
        assert!(matches!(
            amend(&steward, &g, &cp, 101, None, [2u8; 16]),
            Err(CheckpointError::Amplifies(_))
        ));
        // At the remainder exactly, it is allowed.
        let am = amend(&steward, &g, &cp, 100, None, [3u8; 16]).unwrap();
        verify_amendment(&am, &g, &cp).unwrap();
        let cont = apply_amendment(&steward, &g, &cp, &am).unwrap();
        assert_eq!(cont.grant.budget_uj, 100);
    }

    #[test]
    fn verify_amendment_enforces_the_remainder_too() {
        // `amend` refusing is not enough: a steward could sign an over-budget
        // amendment with its own key and hand it straight to an enforcement
        // point, which never calls `amend`. The check has to live on the
        // verifying side as well.
        let (steward, agent, g) = setup();
        let cp = checkpoint(
            &agent, &g, ContentId::of_bytes(b"s"), 0, [1u8; 16],
            Some(Spend { uj: 900, provenance: Provenance::Estimator }),
        )
        .unwrap();
        let forged = Amendment {
            checkpoint_id: cp.checkpoint.id(),
            amender: did(&steward),
            new_budget_uj: 1_000,
            instruction_id: None,
            nonce: [7u8; 16],
        };
        let sig = steward.sign(&canonical_cbor(&forged).unwrap()).to_bytes().to_vec();
        let signed = SignedAmendment { amendment: forged, signature: sig };
        assert!(matches!(
            verify_amendment(&signed, &g, &cp),
            Err(CheckpointError::Amplifies(_))
        ));
        // And the continuation cannot be minted from it either.
        assert!(matches!(
            apply_amendment(&steward, &g, &cp, &signed),
            Err(CheckpointError::Amplifies(_))
        ));
    }

    #[test]
    fn a_silent_checkpoint_keeps_the_older_weaker_ceiling() {
        // Unknown is not zero, but it is also not a refusal: a checkpoint from
        // before the field existed is still valid, and says so by having no
        // remainder to report.
        let (steward, agent, g) = setup();
        let cp = checkpoint(&agent, &g, ContentId::of_bytes(b"s"), 0, [1u8; 16], None).unwrap();
        assert_eq!(remaining_uj(&g.grant, &cp.checkpoint), None);
        amend(&steward, &g, &cp, 1_000, None, [2u8; 16]).unwrap();
        assert!(matches!(
            amend(&steward, &g, &cp, 1_001, None, [3u8; 16]),
            Err(CheckpointError::Amplifies(_))
        ));
    }

    #[test]
    fn a_spend_beyond_the_budget_leaves_nothing_rather_than_wrapping() {
        // An overspend is a real state — enforcement is per-debit and a final
        // debit can land over the line. The remainder saturates at zero; it
        // must not underflow into a vast ceiling.
        let (steward, agent, g) = setup();
        let cp = checkpoint(
            &agent, &g, ContentId::of_bytes(b"s"), 0, [1u8; 16],
            Some(Spend { uj: 4_000, provenance: Provenance::HwShunt }),
        )
        .unwrap();
        assert_eq!(remaining_uj(&g.grant, &cp.checkpoint), Some(0));
        assert!(matches!(
            amend(&steward, &g, &cp, 1, None, [2u8; 16]),
            Err(CheckpointError::Amplifies(_))
        ));
        // Zero is the only lawful continuation: the run may be wound down
        // under a grant that can no longer buy anything, which is different
        // from killing it outright (§4.3).
        amend(&steward, &g, &cp, 0, None, [3u8; 16]).unwrap();
    }

    #[test]
    fn the_spend_field_does_not_change_an_existing_checkpoint() {
        // The wire extension is additive: `spent: None` is skipped, so the
        // signed core is byte-identical to the shape that predates the field
        // and every sealed vector still verifies.
        let (_steward, agent, g) = setup();
        let cp = checkpoint(&agent, &g, ContentId::of_bytes(b"state-1"), 0, [1u8; 16], None).unwrap();
        let bytes = canonical_cbor(&cp.checkpoint).unwrap();
        assert!(
            !bytes.windows(5).any(|w| w == b"spent"),
            "an absent spend must not appear in the signed bytes"
        );
        // And a stated spend does change the id — it is signed, not advisory.
        let with = checkpoint(
            &agent, &g, ContentId::of_bytes(b"state-1"), 0, [1u8; 16],
            Some(Spend { uj: 0, provenance: Provenance::Estimator }),
        )
        .unwrap();
        assert_ne!(
            with.checkpoint.id(), cp.checkpoint.id(),
            "a declared spend of zero is a claim, and differs from no claim"
        );
    }

    #[test]
    fn cumulative_spend_may_not_fall_or_go_silent_across_a_run() {
        let (_steward, agent, g) = setup();
        let mk = |seq: u64, n: u8, spend: Option<Spend>| {
            checkpoint(&agent, &g, ContentId::of_bytes(b"s"), seq, [n; 16], spend)
                .unwrap()
                .checkpoint
        };
        let first = mk(0, 1, Some(Spend { uj: 900, provenance: Provenance::HwShunt }));
        let rose = mk(1, 2, Some(Spend { uj: 950, provenance: Provenance::HwShunt }));
        checkpoint_follows(&first, &rose).unwrap();
        let fell = mk(1, 3, Some(Spend { uj: 100, provenance: Provenance::HwShunt }));
        assert!(matches!(
            checkpoint_follows(&first, &fell),
            Err(CheckpointError::Amplifies(_))
        ));
        let silent = mk(1, 4, None);
        assert!(matches!(
            checkpoint_follows(&first, &silent),
            Err(CheckpointError::Amplifies(_))
        ));
        // Going from silent to stated is fine — that is a deployment turning
        // metering on mid-run, not an agent walking a figure back.
        checkpoint_follows(&mk(0, 5, None), &rose).unwrap();
        // And the chain checks are still chain checks.
        assert!(matches!(
            checkpoint_follows(&rose, &first),
            Err(CheckpointError::ChainBroken(_))
        ));
    }
}
