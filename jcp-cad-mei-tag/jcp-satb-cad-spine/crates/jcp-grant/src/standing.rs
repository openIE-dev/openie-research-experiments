//! Standing grants (SPEC §4.6): bounded authority for event-triggered work.
//!
//! Autonomous agents increasingly start work *themselves* — on a webhook, a
//! schedule, a ticket — with no human in the loop at the firing instant. The
//! danger is obvious: a long-lived credential that any trigger can spend is
//! unbounded authority wearing an automation costume. JCP's answer keeps the
//! object-capability discipline: a **standing grant** is an ordinary grant the
//! issuer holds, plus a signed **mint policy** that says how a trigger may
//! turn it into work. Each firing mints a fresh, strictly-weaker child grant —
//! one event, one bounded child — through the same [`attenuate`] path every
//! delegation uses, so each fire is chain-verifiable and leaves a receipt that
//! traces back to the standing grant.
//!
//! The policy bounds three things at once: **which** trigger may fire it (an
//! event-class content id — a webhook for one source cannot spend a grant
//! meant for another), **how much** each firing may spend (`per_fire_budget_uj`,
//! a slice strictly within the parent's budget), and **how often** it may fire
//! (`max_fires`). A [`MintLedger`] carries the running count and cumulative
//! spend so the rate limit and the parent's budget conservation hold across
//! firings without any coordination — the same local-enforcement property as
//! sharded budgets (SPEC §4.5).
//!
//! The ledger is not the record. Each firing is sealed as a receipt stating
//! `minted_uj` (SPEC §8.1), recorded before the child leaves the enforcement
//! point, and a restart rebuilds the ledger from those receipts
//! ([`MintLedger::of_firings`]). A ledger read back from anywhere else is only
//! ever [`restored`](MintLedger::restore) upward: one reading fewer fires looks
//! the same as a standing grant that fired less often.

use ed25519_dalek::{Signature, Signer, SigningKey, Verifier};
use jcp_schema::{canonical_cbor, Capability, ContentId, Did, SignedGrant};
use serde::{Deserialize, Serialize};

use crate::{attenuate, verify, GrantError};

/// The triggering event a firing presents: an event **class** (which source /
/// kind of trigger this is, content-addressed) and the specific payload that
/// fired. The policy binds `class`; `payload_id` ties the minted child to the
/// concrete event for the audit trail.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct TriggerEvent {
    pub class: ContentId,
    pub payload_id: ContentId,
}

/// The signed rule by which a standing grant may be fired (SPEC §4.6).
/// Bound to one grant by id; only that grant's issuer may sign it.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct MintPolicy {
    /// The grant this policy governs.
    pub grant_id: ContentId,
    /// The event class permitted to fire it.
    pub trigger_class: ContentId,
    /// The budget each minted child carries; MUST be ≤ the grant's budget and
    /// is the per-event ceiling.
    pub per_fire_budget_uj: u64,
    /// The maximum number of children this policy may ever mint.
    pub max_fires: u64,
    /// The capability each child receives; MUST be ⊆ the grant's capability.
    pub capability: Capability,
    /// Expiry stamped on each child (`0` = inherit "never", still bounded by
    /// the parent at mint time).
    pub expiry: u64,
    pub nonce: [u8; 16],
}

/// A mint policy plus the issuer's Ed25519 signature over its canonical bytes.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct SignedMintPolicy {
    pub policy: MintPolicy,
    pub signature: Vec<u8>,
}

/// The running state of a standing grant: how many times it has fired and how
/// much its firings minted. Conservation is arithmetic — no consensus needed.
///
/// It is a figure the enforcement point holds, not the record of what
/// happened. The record is the receipt each firing seals (SPEC §4.6, §8.1),
/// and an enforcement point that restarts rebuilds the ledger from its stream
/// with [`of_firings`](Self::of_firings). `default()` is a standing grant that
/// has never fired, and nothing else: a ledger reading fewer fires than
/// happened looks exactly like one that fired less, so a stored copy that is
/// stale, reset or lost would hand firings back. A copy read from storage is
/// therefore applied with [`restore`](Self::restore), which never lowers a
/// figure.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct MintLedger {
    pub fires: u64,
    pub spent_uj: u64,
}

impl MintLedger {
    /// The ledger a record of firings rebuilds: one fire for each, and the
    /// budget each minted, summed. `minted` is each firing's `minted_uj` as
    /// its receipt states it (`jcp_receipt::replay_mints`), for one standing
    /// grant.
    pub fn of_firings(minted: impl IntoIterator<Item = u64>) -> Self {
        minted.into_iter().fold(MintLedger::default(), |l, uj| MintLedger {
            fires: l.fires.saturating_add(1),
            spent_uj: l.spent_uj.saturating_add(uj),
        })
    }

    /// Restore from another reading of this standing grant's history: the
    /// ledger its receipts rebuild, or a copy read from storage. The higher
    /// count and the higher spend win, so a restore can refuse a firing that
    /// would have been allowed, never allow one that would have been refused.
    pub fn restore(&mut self, other: &MintLedger) {
        self.fires = self.fires.max(other.fires);
        self.spent_uj = self.spent_uj.max(other.spent_uj);
    }
}

/// Sign a mint policy. Only the governed grant's **issuer** may author it; the
/// signing key MUST be the issuer's.
#[allow(clippy::too_many_arguments)]
pub fn issue_policy(
    issuer_sk: &SigningKey,
    grant: &SignedGrant,
    trigger_class: ContentId,
    per_fire_budget_uj: u64,
    max_fires: u64,
    capability: Capability,
    expiry: u64,
    nonce: [u8; 16],
) -> Result<SignedMintPolicy, GrantError> {
    let issuer = Did::from_verifying_key(&issuer_sk.verifying_key());
    if issuer != grant.grant.issuer {
        return Err(GrantError::NotTheIssuer);
    }
    // The policy can never authorize more than the grant: narrow at author time
    // so a firing's only remaining checks are the trigger and the ledger.
    if per_fire_budget_uj > grant.grant.budget_uj {
        return Err(GrantError::Amplifies("per-fire budget exceeds grant"));
    }
    if !capability.is_subset_of(&grant.grant.capability) {
        return Err(GrantError::Amplifies("policy capability exceeds grant"));
    }
    let policy = MintPolicy {
        grant_id: grant.grant.id(),
        trigger_class,
        per_fire_budget_uj,
        max_fires,
        capability,
        expiry,
        nonce,
    };
    let bytes = canonical_cbor(&policy)?;
    let signature = issuer_sk.sign(&bytes).to_bytes().to_vec();
    Ok(SignedMintPolicy { policy, signature })
}

/// Verify a mint policy against the grant it governs: it must name that grant,
/// be signed by the grant's issuer, and not amplify it.
pub fn verify_policy(sp: &SignedMintPolicy, grant: &SignedGrant) -> Result<(), GrantError> {
    if sp.policy.grant_id != grant.grant.id() {
        return Err(GrantError::ChainBroken("policy names a different grant"));
    }
    let vk = grant.grant.issuer.verifying_key()?;
    let bytes = canonical_cbor(&sp.policy)?;
    let sig = Signature::from_slice(&sp.signature).map_err(|e| GrantError::SigShape(e.to_string()))?;
    vk.verify(&bytes, &sig).map_err(|_| GrantError::BadSignature)?;
    if sp.policy.per_fire_budget_uj > grant.grant.budget_uj {
        return Err(GrantError::Amplifies("per-fire budget exceeds grant"));
    }
    if !sp.policy.capability.is_subset_of(&grant.grant.capability) {
        return Err(GrantError::Amplifies("policy capability exceeds grant"));
    }
    Ok(())
}

/// Why a firing was refused.
#[derive(Debug)]
pub enum MintError {
    /// The presented event is not of the class the policy binds.
    WrongTrigger,
    /// `max_fires` already reached.
    RateLimited,
    /// This firing would push cumulative spend past the grant's budget.
    BudgetExhausted,
    /// An underlying grant error (bad signature, not the holder, …).
    Grant(GrantError),
}

impl From<GrantError> for MintError {
    fn from(e: GrantError) -> Self {
        MintError::Grant(e)
    }
}

/// Fire a standing grant: mint one bounded child for one trigger event.
///
/// The delegator MUST hold the standing grant (be its `subject`). The event
/// MUST be of the policy's class; the ledger MUST have firings remaining and
/// budget headroom. On success the child is a normal attenuated grant (its
/// `parent` is the standing grant's id, so receipts trace via `chain_ids`),
/// and the ledger is advanced. The ledger is advanced **only** on success.
///
/// The enforcement point MUST seal the firing's receipt
/// (`jcp_receipt::ReceiptLog::append_mint`) and record it durably before the
/// child leaves it (SPEC §4.6, §4.11): a firing the record does not hold is
/// handed back by the next restart.
#[allow(clippy::too_many_arguments)]
pub fn mint_on_trigger(
    standing: &SignedGrant,
    policy: &SignedMintPolicy,
    ledger: &mut MintLedger,
    delegator_sk: &SigningKey,
    to_subject: Did,
    event: &TriggerEvent,
    nonce: [u8; 16],
) -> Result<SignedGrant, MintError> {
    verify(standing)?;
    verify_policy(policy, standing)?;
    if event.class != policy.policy.trigger_class {
        return Err(MintError::WrongTrigger);
    }
    if ledger.fires >= policy.policy.max_fires {
        return Err(MintError::RateLimited);
    }
    let next_spend = ledger.spent_uj.saturating_add(policy.policy.per_fire_budget_uj);
    if next_spend > standing.grant.budget_uj {
        return Err(MintError::BudgetExhausted);
    }
    // The mint is an ordinary attenuation — it inherits every narrowing and
    // chain-verification guarantee, including delegation-depth control.
    let child = attenuate(
        standing,
        delegator_sk,
        to_subject,
        policy.policy.capability.clone(),
        policy.policy.per_fire_budget_uj,
        policy.policy.expiry,
        nonce,
    )?;
    ledger.fires += 1;
    ledger.spent_uj = next_spend;
    Ok(child)
}

#[cfg(test)]
mod tests {
    use super::*;
    use jcp_schema::Grant;

    fn did(sk: &SigningKey) -> Did {
        Did::from_verifying_key(&sk.verifying_key())
    }

    fn setup() -> (SigningKey, SignedGrant, SignedMintPolicy) {
        let issuer = SigningKey::from_bytes(&[1u8; 32]);
        let cap = Capability::new(ContentId::of_bytes(b"resource"), ["read", "write"]);
        let grant = Grant {
            issuer: did(&issuer),
            subject: did(&issuer), // issuer holds it and fires it
            capability: cap.clone(),
            budget_uj: 1_000,
            budget_funds: None,
            caveats: Vec::new(),
            expiry: 0,
            parent: None,
            delegate_depth: None,
            nonce: [0u8; 16],
        };
        let sg = crate::issue(&issuer, grant).unwrap();
        let child_cap = Capability::new(ContentId::of_bytes(b"resource"), ["read"]);
        let policy = issue_policy(
            &issuer,
            &sg,
            ContentId::of_bytes(b"webhook:builds"),
            200,
            3,
            child_cap,
            0,
            [9u8; 16],
        )
        .unwrap();
        (issuer, sg, policy)
    }

    fn event(class: &[u8], n: u8) -> TriggerEvent {
        TriggerEvent {
            class: ContentId::of_bytes(class),
            payload_id: ContentId::of_bytes(&[n]),
        }
    }

    #[test]
    fn fires_bounded_children_that_trace_to_the_standing_grant() {
        let (issuer, sg, policy) = setup();
        let mut ledger = MintLedger::default();
        let sub = did(&SigningKey::from_bytes(&[2u8; 32]));
        let child = mint_on_trigger(
            &sg, &policy, &mut ledger, &issuer, sub, &event(b"webhook:builds", 1), [1u8; 16],
        )
        .unwrap();
        assert_eq!(child.grant.parent, Some(sg.grant.id()));
        assert_eq!(child.grant.budget_uj, 200);
        assert_eq!(child.grant.capability.actions, vec!["read"]);
        assert_eq!(ledger.fires, 1);
        assert_eq!(ledger.spent_uj, 200);
        verify(&child).unwrap();
    }

    #[test]
    fn wrong_trigger_is_refused() {
        let (issuer, sg, policy) = setup();
        let mut ledger = MintLedger::default();
        let sub = did(&SigningKey::from_bytes(&[2u8; 32]));
        let r = mint_on_trigger(
            &sg, &policy, &mut ledger, &issuer, sub, &event(b"webhook:OTHER", 1), [1u8; 16],
        );
        assert!(matches!(r.unwrap_err(), MintError::WrongTrigger));
        assert_eq!(ledger.fires, 0, "a refused firing does not advance the ledger");
    }

    #[test]
    fn rate_limit_holds() {
        let (issuer, sg, policy) = setup();
        let mut ledger = MintLedger::default();
        let sub = did(&SigningKey::from_bytes(&[2u8; 32]));
        for n in 0..3 {
            mint_on_trigger(
                &sg, &policy, &mut ledger, &issuer, sub, &event(b"webhook:builds", n),
                [n; 16],
            )
            .unwrap();
        }
        let r = mint_on_trigger(
            &sg, &policy, &mut ledger, &issuer, sub, &event(b"webhook:builds", 9), [9u8; 16],
        );
        assert!(matches!(r.unwrap_err(), MintError::RateLimited));
        assert_eq!(ledger.fires, 3);
    }

    #[test]
    fn cumulative_budget_is_conserved_across_fires() {
        // A policy whose per-fire slice * max_fires would exceed the grant:
        // the budget guard stops it before the rate limit does.
        let issuer = SigningKey::from_bytes(&[1u8; 32]);
        let cap = Capability::new(ContentId::of_bytes(b"r"), ["read"]);
        let grant = Grant {
            issuer: did(&issuer), subject: did(&issuer), capability: cap.clone(),
            budget_uj: 250, expiry: 0, parent: None, delegate_depth: None, nonce: [0u8; 16], budget_funds: None, caveats: Vec::new(),
        };
        let sg = crate::issue(&issuer, grant).unwrap();
        let policy = issue_policy(
            &issuer, &sg, ContentId::of_bytes(b"cron"), 100, 10, cap, 0, [0u8; 16],
        )
        .unwrap();
        let mut ledger = MintLedger::default();
        let sub = did(&issuer);
        mint_on_trigger(&sg, &policy, &mut ledger, &issuer, sub, &event(b"cron", 1), [1u8; 16]).unwrap();
        mint_on_trigger(&sg, &policy, &mut ledger, &issuer, sub, &event(b"cron", 2), [2u8; 16]).unwrap();
        // 200 spent; a third 100 would exceed 250.
        let r = mint_on_trigger(&sg, &policy, &mut ledger, &issuer, sub, &event(b"cron", 3), [3u8; 16]);
        assert!(matches!(r.unwrap_err(), MintError::BudgetExhausted));
        assert_eq!(ledger.spent_uj, 200);
    }

    #[test]
    fn policy_cannot_amplify_the_grant() {
        let issuer = SigningKey::from_bytes(&[1u8; 32]);
        let cap = Capability::new(ContentId::of_bytes(b"r"), ["read"]);
        let grant = Grant {
            issuer: did(&issuer), subject: did(&issuer), capability: cap.clone(),
            budget_uj: 100, expiry: 0, parent: None, delegate_depth: None, nonce: [0u8; 16], budget_funds: None, caveats: Vec::new(),
        };
        let sg = crate::issue(&issuer, grant).unwrap();
        // per-fire budget over the grant's ceiling is refused at author time.
        let r = issue_policy(&issuer, &sg, ContentId::of_bytes(b"x"), 500, 1, cap.clone(), 0, [0u8; 16]);
        assert!(matches!(r, Err(GrantError::Amplifies(_))));
        // capability beyond the grant is refused too.
        let wider = Capability::new(ContentId::of_bytes(b"r"), ["read", "write"]);
        let r2 = issue_policy(&issuer, &sg, ContentId::of_bytes(b"x"), 100, 1, wider, 0, [0u8; 16]);
        assert!(matches!(r2, Err(GrantError::Amplifies(_))));
    }

    /// A restore never lowers a figure: a stale or reset copy read back from
    /// storage leaves a ledger where it was, and the ledger the record
    /// rebuilds raises one that is behind it. Fault P3's restart, from a
    /// ledger persisted after the first fire, is in jcp-receipt's
    /// `tests/replay_debits.rs`, where the firings' receipts are sealed.
    #[test]
    fn a_restore_never_hands_back_a_firing() {
        let (issuer, sg, policy) = setup(); // max_fires 3, 200 µJ a fire
        let sub = did(&SigningKey::from_bytes(&[2u8; 32]));
        let mut ledger = MintLedger::default();
        for n in 1..=3 {
            mint_on_trigger(&sg, &policy, &mut ledger, &issuer, sub, &event(b"webhook:builds", n), [n; 16]).unwrap();
        }
        let live = ledger.clone();
        ledger.restore(&MintLedger::default());
        ledger.restore(&MintLedger { fires: 1, spent_uj: 200 });
        assert_eq!(ledger, live, "a stale copy lowered the ledger");

        let mut behind = MintLedger { fires: 1, spent_uj: 200 };
        behind.restore(&MintLedger::of_firings([200, 200, 200]));
        assert_eq!(behind, live, "the record raises a ledger behind it");
        let r = mint_on_trigger(&sg, &policy, &mut behind, &issuer, sub, &event(b"webhook:builds", 9), [9; 16]);
        assert!(matches!(r, Err(MintError::RateLimited)));
        assert_eq!(MintLedger::of_firings([]), MintLedger::default());
    }
}
