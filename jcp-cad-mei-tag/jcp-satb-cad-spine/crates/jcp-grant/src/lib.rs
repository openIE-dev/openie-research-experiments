//! Grant issuance, verification, and attenuation (SPEC §4–§5).
//!
//! A [`Grant`] is signed by its issuer over its canonical bytes. **Attenuation**
//! is the object-capability delegation rule: the holder of a grant may mint a
//! child, but the child can only be *weaker* — capability ⊆ parent, budget ≤
//! parent, expiry no later than parent. Amplification is rejected, so a
//! delegation chain can never grant more than its root. This is how JCP solves
//! "delegated authority" structurally instead of by policy.

pub mod checkpoint;
pub mod standing;

use std::collections::HashSet;

use ed25519_dalek::{Signature, Signer, SigningKey, Verifier};
use jcp_schema::{
    canonical_cbor, Capability, Caveat, ContentId, Did, Funds, Grant, KeyEvent, Revocation, SchemaError,
    SignedGrant, SignedKeyEvent, SignedRevocation,
};

/// Errors from issuing, verifying, attenuating, revoking, or chain-verifying a
/// grant.
#[derive(Debug, thiserror::Error)]
pub enum GrantError {
    #[error("signature did not verify")]
    BadSignature,
    #[error("the grant's issuer does not match the signing key")]
    IssuerMismatch,
    #[error("only the parent grant's subject may delegate it")]
    NotTheHolder,
    #[error("attenuation would amplify the parent: {0}")]
    Amplifies(&'static str),
    #[error("malformed signature bytes: {0}")]
    SigShape(String),
    #[error("only the grant's issuer may revoke it")]
    NotTheIssuer,
    #[error("delegation chain is broken: {0}")]
    ChainBroken(&'static str),
    #[error("the grant forbids further delegation")]
    DelegationForbidden,
    #[error("shard budgets sum past the parent: {0} > {1}")]
    ShardOverflow(u64, u64),
    #[error("key-rotation event invalid: {0}")]
    BadRotation(&'static str),
    #[error(transparent)]
    Schema(#[from] SchemaError),
}

/// Issue a signed grant. The grant's `issuer` MUST be the signing key's DID.
pub fn issue(issuer_sk: &SigningKey, grant: Grant) -> Result<SignedGrant, GrantError> {
    if grant.issuer != Did::from_verifying_key(&issuer_sk.verifying_key()) {
        return Err(GrantError::IssuerMismatch);
    }
    let bytes = canonical_cbor(&grant)?;
    let signature = issuer_sk.sign(&bytes).to_bytes().to_vec();
    Ok(SignedGrant { grant, signature })
}

/// Verify that the issuer DID's key signed the grant's canonical bytes.
pub fn verify(sg: &SignedGrant) -> Result<(), GrantError> {
    let vk = sg.grant.issuer.verifying_key()?;
    let bytes = canonical_cbor(&sg.grant)?;
    let sig = Signature::from_slice(&sg.signature).map_err(|e| GrantError::SigShape(e.to_string()))?;
    vk.verify(&bytes, &sig).map_err(|_| GrantError::BadSignature)
}

/// Mint a strictly-weaker child grant from a parent the delegator holds.
///
/// The delegator MUST be the parent's `subject`. The child MUST narrow:
/// `capability ⊆ parent.capability`, `budget_uj ≤ parent.budget_uj`, and the
/// child's expiry MUST NOT outlive the parent's (`0` = never expires). The
/// child's `parent` field is set to the parent's id, forming the chain.
#[allow(clippy::too_many_arguments)]
pub fn attenuate(
    parent: &SignedGrant,
    delegator_sk: &SigningKey,
    to_subject: Did,
    capability: Capability,
    budget_uj: u64,
    expiry: u64,
    nonce: [u8; 16],
) -> Result<SignedGrant, GrantError> {
    let p = &parent.grant;
    let delegator = Did::from_verifying_key(&delegator_sk.verifying_key());
    if delegator != p.subject {
        return Err(GrantError::NotTheHolder);
    }
    // Delegation control (SPEC §4.4): a leaf-only grant cannot be delegated.
    if !jcp_schema::depth_allows_delegation(p.delegate_depth) {
        return Err(GrantError::DelegationForbidden);
    }
    if !capability.is_subset_of(&p.capability) {
        return Err(GrantError::Amplifies("capability exceeds parent"));
    }
    if budget_uj > p.budget_uj {
        return Err(GrantError::Amplifies("budget exceeds parent"));
    }
    // Child must not outlive parent. 0 = no expiry.
    let outlives = match (p.expiry, expiry) {
        (0, _) => false,     // parent never expires → any child expiry is fine
        (_, 0) => true,      // child never expires but parent does → amplifies
        (pe, ce) => ce > pe, // child outlasts parent → amplifies
    };
    if outlives {
        return Err(GrantError::Amplifies("expiry outlives parent"));
    }
    let child = Grant {
        issuer: delegator,
        subject: to_subject,
        capability,
        budget_uj,
        // Caveats are INHERITED wholesale (§4.9). A child carries every one of
        // its parent's; `attenuate_caveated` is the path that adds more. Losing
        // one here would silently widen a delegate's authority.
        caveats: p.caveats.clone(),
        // The money ceiling is INHERITED, never dropped. Defaulting this to
        // `None` would silently hand a child unbounded spending authority where
        // its parent was bounded — an amplification, and precisely the bug a
        // second budget dimension invites. To narrow it, use
        // [`attenuate_priced`].
        budget_funds: p.budget_funds.clone(),
        expiry,
        parent: Some(p.id()),
        // The child's allowance is the parent's minus one — depth only narrows.
        delegate_depth: jcp_schema::child_depth_bound(p.delegate_depth),
        nonce,
    };
    issue(delegator_sk, child)
}

/// Whether a child's money ceiling is no broader than its parent's.
///
/// The no-exchange-rate rule reaches attenuation too: a child ceiling in a
/// *different* currency cannot be shown to narrow the parent's without a rate,
/// so it is refused rather than converted.
pub fn funds_narrows(parent: &Option<Funds>, child: &Option<Funds>) -> bool {
    match (parent, child) {
        // Parent unbounded in money → any child ceiling only adds a constraint.
        (None, _) => true,
        // Parent bounded, child unbounded → amplification.
        (Some(_), None) => false,
        (Some(p), Some(c)) => p.same_currency(&c.currency) && c.minor <= p.minor,
    }
}

/// Attenuate with an explicit **money** ceiling as well as a joule ceiling —
/// the dual-ceiling delegation path (SPEC §4.8).
///
/// Both dimensions must narrow independently. No rate is ever invented: a child
/// ceiling denominated in a different currency than the parent's is refused.
#[allow(clippy::too_many_arguments)]
pub fn attenuate_priced(
    parent: &SignedGrant,
    delegator_sk: &SigningKey,
    to_subject: Did,
    capability: Capability,
    budget_uj: u64,
    budget_funds: Option<Funds>,
    expiry: u64,
    nonce: [u8; 16],
) -> Result<SignedGrant, GrantError> {
    if !funds_narrows(&parent.grant.budget_funds, &budget_funds) {
        return Err(GrantError::Amplifies("money ceiling exceeds parent"));
    }
    let mut sg = attenuate(parent, delegator_sk, to_subject, capability, budget_uj, expiry, nonce)?;
    // `attenuate` inherited the parent's ceiling; replace it with the narrowed
    // one and re-sign, so the signature covers the ceiling actually granted.
    sg.grant.budget_funds = budget_funds;
    issue(delegator_sk, sg.grant)
}

/// Whether a child's caveat set is no weaker than its parent's — it must retain
/// every parent caveat. Adding more only narrows (SPEC §4.9).
pub fn caveats_narrow(parent: &[Caveat], child: &[Caveat]) -> bool {
    parent.iter().all(|c| child.contains(c))
}

/// Attenuate while **adding** caveats — the open attenuation axis (SPEC §4.9).
///
/// The child keeps every caveat of its parent and gains `add`, so authority
/// narrows monotonically: a delegate can constrain further but never relax what
/// it was handed. Unlike the fixed axes, the added condition is arbitrary and
/// travels *inside* the signed grant, so any verifier checks it offline.
#[allow(clippy::too_many_arguments)]
pub fn attenuate_caveated(
    parent: &SignedGrant,
    delegator_sk: &SigningKey,
    to_subject: Did,
    capability: Capability,
    budget_uj: u64,
    add: Vec<Caveat>,
    expiry: u64,
    nonce: [u8; 16],
) -> Result<SignedGrant, GrantError> {
    let mut sg = attenuate(parent, delegator_sk, to_subject, capability, budget_uj, expiry, nonce)?;
    // `attenuate` already inherited the parent's caveats; append the new ones,
    // skipping duplicates so the set stays canonical.
    for c in add {
        if !sg.grant.caveats.contains(&c) {
            sg.grant.caveats.push(c);
        }
    }
    // Belt and braces: the result must still be no weaker than the parent.
    if !caveats_narrow(&parent.grant.caveats, &sg.grant.caveats) {
        return Err(GrantError::Amplifies("caveats weaker than parent"));
    }
    issue(delegator_sk, sg.grant)
}

/// Split a grant into sibling shards for **distributed enforcement points**
/// (SPEC §4.5). Each shard is an ordinary attenuated child; the helper's value
/// is the conservation check at mint time: **the shard budgets must sum to no
/// more than the parent's budget**, so each enforcement point can enforce its
/// own shard locally — no coordination, no consensus — and the root is still
/// conserved by arithmetic.
pub fn shard(
    parent: &SignedGrant,
    delegator_sk: &SigningKey,
    slices: &[(Did, u64)],
    expiry: u64,
    nonce_seed: [u8; 16],
) -> Result<Vec<SignedGrant>, GrantError> {
    let total: u64 = slices.iter().map(|(_, b)| *b).fold(0, u64::saturating_add);
    if total > parent.grant.budget_uj {
        return Err(GrantError::ShardOverflow(total, parent.grant.budget_uj));
    }
    slices
        .iter()
        .enumerate()
        .map(|(i, (subject, budget))| {
            let mut nonce = nonce_seed;
            nonce[..8].iter_mut().zip((i as u64).to_be_bytes()).for_each(|(n, b)| *n ^= b);
            attenuate(parent, delegator_sk, *subject, parent.grant.capability.clone(), *budget, expiry, nonce)
        })
        .collect()
}

/// Revoke a grant. Only its **issuer** may revoke it; the signing key MUST be
/// the issuer's. Revocation is transitive — enforcement treats every grant
/// attenuated from a revoked one as revoked too.
pub fn revoke(issuer_sk: &SigningKey, grant: &Grant, nonce: [u8; 16]) -> Result<SignedRevocation, GrantError> {
    let revoker = Did::from_verifying_key(&issuer_sk.verifying_key());
    if revoker != grant.issuer {
        return Err(GrantError::NotTheIssuer);
    }
    let revocation = Revocation { grant_id: grant.id(), revoked_by: revoker, nonce };
    let bytes = canonical_cbor(&revocation)?;
    let signature = issuer_sk.sign(&bytes).to_bytes().to_vec();
    Ok(SignedRevocation { revocation, signature })
}

/// Verify a revocation against the grant it claims to revoke: the ids must
/// match, the revoker must be the grant's issuer, and the signature must verify
/// over the revocation's canonical bytes.
pub fn verify_revocation(sr: &SignedRevocation, grant: &Grant) -> Result<(), GrantError> {
    if sr.revocation.grant_id != grant.id() {
        return Err(GrantError::ChainBroken("revocation names a different grant"));
    }
    if sr.revocation.revoked_by != grant.issuer {
        return Err(GrantError::NotTheIssuer);
    }
    let vk = sr.revocation.revoked_by.verifying_key()?;
    let bytes = canonical_cbor(&sr.revocation)?;
    let sig = Signature::from_slice(&sr.signature).map_err(|e| GrantError::SigShape(e.to_string()))?;
    vk.verify(&bytes, &sig).map_err(|_| GrantError::BadSignature)
}

/// The set of revoked grant ids an enforcement point honors. Entries are added
/// only through [`RevocationSet::apply`], which verifies authority — an
/// unauthorized or unsigned revocation never enters the set.
#[derive(Default, Debug, Clone)]
pub struct RevocationSet {
    revoked: HashSet<ContentId>,
}

impl RevocationSet {
    pub fn new() -> Self {
        Self::default()
    }

    /// Verify and admit a revocation for `grant`.
    pub fn apply(&mut self, sr: &SignedRevocation, grant: &Grant) -> Result<(), GrantError> {
        verify_revocation(sr, grant)?;
        self.revoked.insert(sr.revocation.grant_id);
        Ok(())
    }

    pub fn contains(&self, grant_id: &ContentId) -> bool {
        self.revoked.contains(grant_id)
    }

    /// Whether any link of a delegation chain (root first, leaf last) is
    /// revoked. A revoked ancestor kills the whole subtree.
    pub fn hits_chain(&self, chain: &[SignedGrant]) -> bool {
        chain.iter().any(|sg| self.revoked.contains(&sg.grant.id()))
    }
}

/// Verify a full delegation chain, **root first, leaf last**.
///
/// Checks, per hop: the root has no parent; every later grant's `parent` is the
/// id of the grant before it; each child is issued by the previous grant's
/// subject (the holder delegated it); each child narrows its parent (capability
/// ⊆, budget ≤, expiry no later, every parent caveat carried, money ceiling no
/// wider); and every signature in the chain verifies.
/// A chain that passes conveys exactly what its leaf says and never more than
/// its root.
pub fn verify_chain(chain: &[SignedGrant]) -> Result<(), GrantError> {
    let root = chain.first().ok_or(GrantError::ChainBroken("empty chain"))?;
    if root.grant.parent.is_some() {
        return Err(GrantError::ChainBroken("root grant has a parent"));
    }
    for sg in chain {
        verify(sg)?;
    }
    for pair in chain.windows(2) {
        let (parent, child) = (&pair[0].grant, &pair[1].grant);
        if child.parent != Some(parent.id()) {
            return Err(GrantError::ChainBroken("parent link mismatch"));
        }
        if child.issuer != parent.subject {
            return Err(GrantError::ChainBroken("hop not issued by the previous holder"));
        }
        // Delegation control: a leaf-only parent has no children, and a child's
        // own allowance must fit under the parent's bound (unlimited under a
        // bounded parent is an amplification).
        if !jcp_schema::depth_allows_delegation(parent.delegate_depth) {
            return Err(GrantError::DelegationForbidden);
        }
        match (jcp_schema::child_depth_bound(parent.delegate_depth), child.delegate_depth) {
            (Some(_), None) => return Err(GrantError::Amplifies("delegation depth exceeds parent")),
            (Some(bound), Some(c)) if c > bound => {
                return Err(GrantError::Amplifies("delegation depth exceeds parent"))
            }
            _ => {}
        }
        if !child.capability.is_subset_of(&parent.capability) {
            return Err(GrantError::Amplifies("capability exceeds parent"));
        }
        if child.budget_uj > parent.budget_uj {
            return Err(GrantError::Amplifies("budget exceeds parent"));
        }
        let outlives = match (parent.expiry, child.expiry) {
            (0, _) => false,
            (_, 0) => true,
            (pe, ce) => ce > pe,
        };
        if outlives {
            return Err(GrantError::Amplifies("expiry outlives parent"));
        }
        // Caveats only accumulate (§4.9) and a money ceiling only narrows
        // (§4.8). `attenuate` holds both when it mints, but a chain arrives
        // minted by whoever signed it, so the verifier holds them too: a child
        // that dropped a parent's caveat would otherwise verify and convey the
        // authority the caveat withheld.
        if !caveats_narrow(&parent.caveats, &child.caveats) {
            return Err(GrantError::Amplifies("caveats weaker than parent"));
        }
        if !funds_narrows(&parent.budget_funds, &child.budget_funds) {
            return Err(GrantError::Amplifies("money ceiling exceeds parent"));
        }
    }
    Ok(())
}

// ── Identity continuity: pre-committed key rotation (SPEC §2.1) ─────────────

/// The blake3 pre-commitment for a key: the hash of its 32 public bytes.
pub fn key_commitment(key: &Did) -> ContentId {
    ContentId::of_bytes(&key.0)
}

/// Incept an identity: seq 0, current = the identity key itself, pre-committing
/// to the hash of the *next* key. Signed by the identity key.
pub fn incept(
    identity_sk: &SigningKey,
    next_hash: ContentId,
    nonce: [u8; 16],
) -> Result<SignedKeyEvent, GrantError> {
    let identity = Did::from_verifying_key(&identity_sk.verifying_key());
    let event = KeyEvent { identity, seq: 0, current: identity, next_hash, parent: None, nonce };
    let bytes = canonical_cbor(&event)?;
    let signature = identity_sk.sign(&bytes).to_bytes().to_vec();
    Ok(SignedKeyEvent { event, signature })
}

/// Build rotation event N: the new current key — which MUST be the one whose
/// hash event N−1 pre-committed to — signs the event itself. Possession of the
/// pre-committed key is the proof of control: a thief holding only the *old*
/// key cannot rotate (they don't have the next key), and an owner who *lost*
/// the old key still can (they do).
pub fn rotate_key(
    new_current_sk: &SigningKey,
    log: &KeyLog,
    next_hash: ContentId,
    nonce: [u8; 16],
) -> Result<SignedKeyEvent, GrantError> {
    let new_current = Did::from_verifying_key(&new_current_sk.verifying_key());
    let event = KeyEvent {
        identity: log.identity(),
        seq: log.seq() + 1,
        current: new_current,
        next_hash,
        parent: Some(log.head()),
        nonce,
    };
    let bytes = canonical_cbor(&event)?;
    let signature = new_current_sk.sign(&bytes).to_bytes().to_vec();
    Ok(SignedKeyEvent { event, signature })
}

/// A verified key-rotation log for one identity. Events are admitted only
/// through [`KeyLog::open`] / [`KeyLog::rotate`], which enforce the chain:
/// sequence, parent link, the pre-commitment hash match, and the signature of
/// the key the event declares current.
#[derive(Debug, Clone)]
pub struct KeyLog {
    identity: Did,
    seq: u64,
    current: Did,
    next_hash: ContentId,
    head: ContentId,
}

impl KeyLog {
    /// Open a log from its inception event.
    pub fn open(inception: &SignedKeyEvent) -> Result<Self, GrantError> {
        let e = &inception.event;
        if e.seq != 0 || e.parent.is_some() {
            return Err(GrantError::BadRotation("inception must be seq 0 with no parent"));
        }
        if e.current != e.identity {
            return Err(GrantError::BadRotation("inception current must equal identity"));
        }
        verify_event_sig(inception, &e.identity)?;
        Ok(KeyLog { identity: e.identity, seq: 0, current: e.current, next_hash: e.next_hash, head: e.id() })
    }

    /// Admit rotation event N. The event's `current` key must hash to the
    /// pre-commitment of event N−1 and must have signed the event.
    pub fn rotate(&mut self, ev: &SignedKeyEvent) -> Result<(), GrantError> {
        let e = &ev.event;
        if e.identity != self.identity {
            return Err(GrantError::BadRotation("event names a different identity"));
        }
        if e.seq != self.seq + 1 {
            return Err(GrantError::BadRotation("sequence gap"));
        }
        if e.parent != Some(self.head) {
            return Err(GrantError::BadRotation("parent link mismatch"));
        }
        if key_commitment(&e.current) != self.next_hash {
            return Err(GrantError::BadRotation("current key does not match the pre-commitment"));
        }
        verify_event_sig(ev, &e.current)?;
        self.seq = e.seq;
        self.current = e.current;
        self.next_hash = e.next_hash;
        self.head = e.id();
        Ok(())
    }

    /// The identity (the inception DID — stable across every rotation).
    pub fn identity(&self) -> Did {
        self.identity
    }
    /// The key that currently controls the identity.
    pub fn current(&self) -> Did {
        self.current
    }
    pub fn seq(&self) -> u64 {
        self.seq
    }
    pub fn head(&self) -> ContentId {
        self.head
    }
    /// Whether `key` once controlled this identity but no longer does. An
    /// enforcement point honoring the log SHOULD treat grants issued to or by a
    /// superseded key as candidates for re-issuance.
    pub fn is_current(&self, key: &Did) -> bool {
        *key == self.current
    }
}

fn verify_event_sig(ev: &SignedKeyEvent, signer: &Did) -> Result<(), GrantError> {
    let vk = signer.verifying_key()?;
    let bytes = canonical_cbor(&ev.event)?;
    let sig = Signature::from_slice(&ev.signature).map_err(|e| GrantError::SigShape(e.to_string()))?;
    vk.verify(&bytes, &sig).map_err(|_| GrantError::BadSignature)
}

#[cfg(test)]
mod tests {
    use super::*;
    use jcp_schema::ContentId;

    fn sk(seed: u8) -> SigningKey {
        SigningKey::from_bytes(&[seed; 32])
    }
    fn did(k: &SigningKey) -> Did {
        Did::from_verifying_key(&k.verifying_key())
    }

    /// A child minted by hand, outside `attenuate`, with the parent link set.
    fn hand_minted_child(parent: &SignedGrant, delegator: &SigningKey, caveats: Vec<Caveat>, budget_funds: Option<Funds>) -> SignedGrant {
        let p = &parent.grant;
        issue(
            delegator,
            Grant {
                issuer: did(delegator),
                subject: did(&sk(9)),
                capability: p.capability.clone(),
                budget_uj: p.budget_uj,
                budget_funds,
                caveats,
                expiry: p.expiry,
                parent: Some(p.id()),
                delegate_depth: None,
                nonce: [7; 16],
            },
        )
        .unwrap()
    }

    /// `attenuate` refuses to drop a caveat or widen a money ceiling, but a
    /// chain can be signed by anything; `verify_chain` must refuse both too.
    #[test]
    fn a_chain_cannot_drop_a_caveat_or_widen_a_money_ceiling() {
        let (root_sk, holder) = (sk(1), sk(2));
        let usd = |minor| Some(Funds { currency: "USD".into(), minor });
        let root = issue(
            &root_sk,
            Grant {
                issuer: did(&root_sk),
                subject: did(&holder),
                capability: Capability::new(ContentId::of_bytes(b"db"), ["read"]),
                budget_uj: 1_000,
                budget_funds: usd(500),
                caveats: vec![Caveat::NotAfter(900)],
                expiry: 0,
                parent: None,
                delegate_depth: None,
                nonce: [1; 16],
            },
        )
        .unwrap();

        let faithful = hand_minted_child(&root, &holder, vec![Caveat::NotAfter(900), Caveat::MaxCostUj(10)], usd(400));
        assert!(verify_chain(&[root.clone(), faithful]).is_ok());

        let dropped = hand_minted_child(&root, &holder, vec![], usd(400));
        assert!(matches!(verify_chain(&[root.clone(), dropped]), Err(GrantError::Amplifies(_))));
        let widened = hand_minted_child(&root, &holder, vec![Caveat::NotAfter(900)], usd(600));
        assert!(matches!(verify_chain(&[root.clone(), widened]), Err(GrantError::Amplifies(_))));
        let unbounded = hand_minted_child(&root, &holder, vec![Caveat::NotAfter(900)], None);
        assert!(matches!(verify_chain(&[root, unbounded]), Err(GrantError::Amplifies(_))));
    }

    fn root(issuer: &SigningKey, subject: Did) -> SignedGrant {
        let g = Grant {
            issuer: did(issuer),
            subject,
            capability: Capability::new(ContentId::of_bytes(b"db"), ["read", "write"]),
            budget_uj: 10_000,
            budget_funds: None,
            caveats: Vec::new(),
            expiry: 1000,
            parent: None,
            delegate_depth: None,
            nonce: [1; 16],
        };
        issue(issuer, g).unwrap()
    }

    fn priced_root(issuer: &SigningKey, subject: Did, minor: u64) -> SignedGrant {
        let mut g = root(issuer, subject).grant;
        g.budget_funds = Some(Funds::new("USD", minor));
        issue(issuer, g).unwrap()
    }

    /// A money ceiling MUST be inherited by a plain `attenuate`, never silently
    /// dropped — dropping it would hand the child unbounded spend where the
    /// parent was bounded (an amplification).
    #[test]
    fn attenuate_inherits_the_money_ceiling() {
        let issuer = sk(1);
        let holder = sk(2);
        let parent = priced_root(&issuer, did(&holder), 500);
        let child = attenuate(
            &parent,
            &holder,
            did(&sk(3)),
            Capability::new(ContentId::of_bytes(b"db"), ["read"]),
            5_000,
            500,
            [2; 16],
        )
        .unwrap();
        assert_eq!(child.grant.budget_funds, Some(Funds::new("USD", 500)));
    }

    #[test]
    fn attenuate_priced_narrows_and_refuses_amplification() {
        let issuer = sk(1);
        let holder = sk(2);
        let r = ContentId::of_bytes(b"db");
        let parent = priced_root(&issuer, did(&holder), 500);

        // Narrowing the money ceiling ($5.00 → $2.00) is fine.
        let child = attenuate_priced(
            &parent, &holder, did(&sk(3)), Capability::new(r, ["read"]),
            5_000, Some(Funds::new("USD", 200)), 500, [2; 16],
        )
        .unwrap();
        assert_eq!(child.grant.budget_funds, Some(Funds::new("USD", 200)));
        assert!(verify(&child).is_ok());

        // A larger money ceiling amplifies.
        assert!(matches!(
            attenuate_priced(&parent, &holder, did(&sk(3)), Capability::new(r, ["read"]),
                5_000, Some(Funds::new("USD", 900)), 500, [2; 16]),
            Err(GrantError::Amplifies(_))
        ));
        // Dropping the ceiling (→ unbounded money) amplifies.
        assert!(matches!(
            attenuate_priced(&parent, &holder, did(&sk(3)), Capability::new(r, ["read"]),
                5_000, None, 500, [2; 16]),
            Err(GrantError::Amplifies(_))
        ));
        // A different currency cannot be shown to narrow without a rate → refused.
        assert!(matches!(
            attenuate_priced(&parent, &holder, did(&sk(3)), Capability::new(r, ["read"]),
                5_000, Some(Funds::new("EUR", 100)), 500, [2; 16]),
            Err(GrantError::Amplifies(_))
        ));
    }

    #[test]
    fn issue_then_verify() {
        let issuer = sk(1);
        let g = root(&issuer, did(&sk(2)));
        assert!(verify(&g).is_ok());
    }

    #[test]
    fn issuer_must_match_key() {
        let g = Grant {
            issuer: did(&sk(9)), // not the signer
            subject: did(&sk(2)),
            capability: Capability::new(ContentId::of_bytes(b"db"), ["read"]),
            budget_uj: 1,
            budget_funds: None,
            caveats: Vec::new(),
            expiry: 0,
            parent: None,
            delegate_depth: None,
            nonce: [0; 16],
        };
        assert!(matches!(issue(&sk(1), g), Err(GrantError::IssuerMismatch)));
    }

    #[test]
    fn tampered_grant_fails_verification() {
        let issuer = sk(1);
        let mut g = root(&issuer, did(&sk(2)));
        g.grant.budget_uj = 1_000_000; // forge a bigger budget
        assert!(matches!(verify(&g), Err(GrantError::BadSignature)));
    }

    #[test]
    fn attenuation_narrows_ok() {
        let issuer = sk(1);
        let holder = sk(2);
        let parent = root(&issuer, did(&holder));
        // holder delegates read-only, smaller budget, sooner expiry, to a sub-agent
        let child = attenuate(
            &parent,
            &holder,
            did(&sk(3)),
            Capability::new(ContentId::of_bytes(b"db"), ["read"]),
            5_000,
            500,
            [2; 16],
        )
        .unwrap();
        assert!(verify(&child).is_ok());
        assert_eq!(child.grant.parent, Some(parent.grant.id()));
    }

    /// Caveats are inherited by a plain attenuation — never silently dropped,
    /// which would widen the delegate's authority.
    #[test]
    fn attenuate_inherits_caveats() {
        let issuer = sk(1);
        let holder = sk(2);
        let mut g = root(&issuer, did(&holder)).grant;
        g.caveats = vec![Caveat::MaxCostUj(500)];
        let parent = issue(&issuer, g).unwrap();
        let child = attenuate(
            &parent, &holder, did(&sk(3)),
            Capability::new(ContentId::of_bytes(b"db"), ["read"]), 5_000, 500, [2; 16],
        )
        .unwrap();
        assert_eq!(child.grant.caveats, vec![Caveat::MaxCostUj(500)]);
    }

    /// The open axis: a delegator ADDS an arbitrary condition the delegate
    /// cannot remove, and the result still carries the parent's.
    #[test]
    fn attenuate_caveated_only_narrows() {
        let issuer = sk(1);
        let holder = sk(2);
        let r = ContentId::of_bytes(b"db");
        let mut g = root(&issuer, did(&holder)).grant;
        g.caveats = vec![Caveat::MaxCostUj(500)];
        let parent = issue(&issuer, g).unwrap();

        let child = attenuate_caveated(
            &parent, &holder, did(&sk(3)), Capability::new(r, ["read"]),
            5_000, vec![Caveat::PayloadIs(ContentId::of_bytes(b"one-shot"))], 500, [2; 16],
        )
        .unwrap();
        assert!(verify(&child).is_ok());
        // Keeps the parent's AND gains the new one.
        assert!(child.grant.caveats.contains(&Caveat::MaxCostUj(500)));
        assert!(child.grant.caveats.contains(&Caveat::PayloadIs(ContentId::of_bytes(b"one-shot"))));
        assert!(caveats_narrow(&parent.grant.caveats, &child.grant.caveats));

        // Adding a duplicate does not grow the set.
        let twice = attenuate_caveated(
            &parent, &holder, did(&sk(3)), Capability::new(r, ["read"]),
            5_000, vec![Caveat::MaxCostUj(500)], 500, [3; 16],
        )
        .unwrap();
        assert_eq!(twice.grant.caveats.len(), 1);
    }

    #[test]
    fn caveats_narrow_rejects_a_dropped_condition() {
        let parent = vec![Caveat::MaxCostUj(500), Caveat::NotAfter(900)];
        assert!(caveats_narrow(&parent, &[Caveat::MaxCostUj(500), Caveat::NotAfter(900), Caveat::CallerIs(did(&sk(4)))]));
        assert!(!caveats_narrow(&parent, &[Caveat::MaxCostUj(500)]), "dropping a parent caveat must not count as narrowing");
        assert!(!caveats_narrow(&parent, &[]), "clearing caveats must not count as narrowing");
    }

    #[test]
    fn attenuation_cannot_amplify() {
        let issuer = sk(1);
        let holder = sk(2);
        let parent = root(&issuer, did(&holder));
        let r = ContentId::of_bytes(b"db");
        // bigger budget
        assert!(matches!(
            attenuate(&parent, &holder, did(&sk(3)), Capability::new(r, ["read"]), 20_000, 500, [0; 16]),
            Err(GrantError::Amplifies(_))
        ));
        // broader capability (a new action)
        assert!(matches!(
            attenuate(&parent, &holder, did(&sk(3)), Capability::new(r, ["read", "delete"]), 1, 500, [0; 16]),
            Err(GrantError::Amplifies(_))
        ));
        // longer expiry
        assert!(matches!(
            attenuate(&parent, &holder, did(&sk(3)), Capability::new(r, ["read"]), 1, 2000, [0; 16]),
            Err(GrantError::Amplifies(_))
        ));
        // a non-holder cannot delegate
        assert!(matches!(
            attenuate(&parent, &sk(8), did(&sk(3)), Capability::new(r, ["read"]), 1, 500, [0; 16]),
            Err(GrantError::NotTheHolder)
        ));
    }

    /// root(issuer→holder) → mid(holder→sub) → leaf(sub→leafholder)
    fn three_hop() -> (Vec<SignedGrant>, SigningKey, SigningKey) {
        let issuer = sk(1);
        let holder = sk(2);
        let sub = sk(3);
        let parent = root(&issuer, did(&holder));
        let r = ContentId::of_bytes(b"db");
        let mid = attenuate(&parent, &holder, did(&sub), Capability::new(r, ["read"]), 5_000, 500, [2; 16]).unwrap();
        let leaf = attenuate(&mid, &sub, did(&sk(4)), Capability::new(r, ["read"]), 2_000, 400, [3; 16]).unwrap();
        (vec![parent, mid, leaf], issuer, holder)
    }

    #[test]
    fn chain_verifies_root_to_leaf() {
        let (chain, _, _) = three_hop();
        assert!(verify_chain(&chain).is_ok());
        // each prefix is also a valid chain
        assert!(verify_chain(&chain[..2]).is_ok());
        assert!(verify_chain(&chain[..1]).is_ok());
    }

    #[test]
    fn broken_chains_are_rejected() {
        let (chain, _, _) = three_hop();
        // out of order — the leaf's parent link doesn't match
        let reordered = vec![chain[0].clone(), chain[2].clone(), chain[1].clone()];
        assert!(matches!(verify_chain(&reordered), Err(GrantError::ChainBroken(_))));
        // a chain that starts mid-way has a parented root
        assert!(matches!(verify_chain(&chain[1..]), Err(GrantError::ChainBroken(_))));
        // a forged hop: bump the mid grant's budget after signing
        let mut forged = chain.clone();
        forged[1].grant.budget_uj = 9_999;
        assert!(matches!(verify_chain(&forged), Err(GrantError::BadSignature)));
        assert!(matches!(verify_chain(&[]), Err(GrantError::ChainBroken(_))));
    }

    #[test]
    fn revocation_requires_the_issuer() {
        let (chain, issuer, holder) = three_hop();
        let root_grant = &chain[0].grant;
        // the holder cannot revoke what the issuer granted
        assert!(matches!(revoke(&holder, root_grant, [9; 16]), Err(GrantError::NotTheIssuer)));
        // the issuer can
        let sr = revoke(&issuer, root_grant, [9; 16]).unwrap();
        assert!(verify_revocation(&sr, root_grant).is_ok());
        // and the revocation doesn't transfer to a different grant
        assert!(verify_revocation(&sr, &chain[1].grant).is_err());
    }

    #[test]
    fn revoked_ancestor_kills_the_subtree() {
        let (chain, issuer, _) = three_hop();
        let mut set = RevocationSet::new();
        // an unauthorized revocation never enters the set
        let forged = SignedRevocation {
            revocation: Revocation { grant_id: chain[0].grant.id(), revoked_by: did(&sk(8)), nonce: [0; 16] },
            signature: vec![0; 64],
        };
        assert!(set.apply(&forged, &chain[0].grant).is_err());
        assert!(!set.hits_chain(&chain));
        // the issuer revokes the ROOT — the whole chain dies
        let sr = revoke(&issuer, &chain[0].grant, [9; 16]).unwrap();
        set.apply(&sr, &chain[0].grant).unwrap();
        assert!(set.hits_chain(&chain));
        assert!(set.contains(&chain[0].grant.id()));
        assert!(!set.contains(&chain[2].grant.id())); // leaf id itself not listed — ancestry kills it
    }

    #[test]
    fn delegation_depth_narrows_and_bottoms_out() {
        let issuer = sk(1);
        let holder = sk(2);
        let sub = sk(3);
        let r = ContentId::of_bytes(b"db");
        // depth 1: the holder may delegate once; the grandchild is forbidden
        let root = issue(
            &issuer,
            Grant {
                issuer: did(&issuer),
                subject: did(&holder),
                capability: Capability::new(r, ["read"]),
                budget_uj: 1000,
                budget_funds: None,
                caveats: Vec::new(),
                expiry: 0,
                parent: None,
                delegate_depth: Some(1),
                nonce: [0; 16],
            },
        )
        .unwrap();
        let child = attenuate(&root, &holder, did(&sub), Capability::new(r, ["read"]), 500, 0, [1; 16]).unwrap();
        assert_eq!(child.grant.delegate_depth, Some(0)); // narrowed automatically
        assert!(matches!(
            attenuate(&child, &sub, did(&sk(4)), Capability::new(r, ["read"]), 100, 0, [2; 16]),
            Err(GrantError::DelegationForbidden)
        ));
        assert!(verify_chain(&[root.clone(), child.clone()]).is_ok());
        // a forged grandchild under a depth-0 grant fails chain verification
        let forged_kid = issue(
            &sub,
            Grant {
                issuer: did(&sub),
                subject: did(&sk(4)),
                capability: Capability::new(r, ["read"]),
                budget_uj: 100,
                budget_funds: None,
                caveats: Vec::new(),
                expiry: 0,
                parent: Some(child.grant.id()),
                delegate_depth: None,
                nonce: [3; 16],
            },
        )
        .unwrap();
        assert!(matches!(
            verify_chain(&[root, child, forged_kid]),
            Err(GrantError::DelegationForbidden)
        ));
    }

    #[test]
    fn shard_conserves_the_parent_budget_at_mint() {
        let issuer = sk(1);
        let holder = sk(2);
        let parent = root(&issuer, did(&holder)); // budget 10_000
        let eps = [(did(&sk(3)), 4_000), (did(&sk(4)), 4_000), (did(&sk(5)), 2_000)];
        let shards = shard(&parent, &holder, &eps, 500, [7; 16]).unwrap();
        assert_eq!(shards.len(), 3);
        let total: u64 = shards.iter().map(|s| s.grant.budget_uj).sum();
        assert_eq!(total, 10_000);
        for s in &shards {
            assert!(verify_chain(&[parent.clone(), s.clone()]).is_ok());
        }
        // nonces differ, so sibling ids differ
        assert_ne!(shards[0].grant.id(), shards[1].grant.id());
        // one joule past the parent is refused at mint time
        let over = [(did(&sk(3)), 4_000), (did(&sk(4)), 4_000), (did(&sk(5)), 2_001)];
        assert!(matches!(shard(&parent, &holder, &over, 500, [7; 16]), Err(GrantError::ShardOverflow(10_001, 10_000))));
    }

    #[test]
    fn rotation_follows_the_precommitment() {
        let k0 = sk(10);
        let k1 = sk(11);
        let k2 = sk(12);
        let inception = incept(&k0, key_commitment(&did(&k1)), [0; 16]).unwrap();
        let mut log = KeyLog::open(&inception).unwrap();
        assert_eq!(log.identity(), did(&k0));
        assert!(log.is_current(&did(&k0)));
        // rotate to k1 (pre-committed) — signed by k1, so a LOST k0 is recoverable
        let ev1 = rotate_key(&k1, &log, key_commitment(&did(&k2)), [1; 16]).unwrap();
        log.rotate(&ev1).unwrap();
        assert_eq!(log.current(), did(&k1));
        assert!(!log.is_current(&did(&k0)));
        assert_eq!(log.identity(), did(&k0)); // identity is stable
        // rotate again to k2
        let ev2 = rotate_key(&k2, &log, key_commitment(&did(&sk(13))), [2; 16]).unwrap();
        log.rotate(&ev2).unwrap();
        assert_eq!(log.current(), did(&k2));
        assert_eq!(log.seq(), 2);
    }

    #[test]
    fn a_thief_with_the_current_key_cannot_rotate() {
        let k0 = sk(10);
        let k1 = sk(11);
        let thief = sk(66);
        let inception = incept(&k0, key_commitment(&did(&k1)), [0; 16]).unwrap();
        let mut log = KeyLog::open(&inception).unwrap();
        // the thief holds k0 (current!) but not k1 — their chosen new key
        // fails the pre-commitment hash, however they sign it
        let bad = rotate_key(&thief, &log, key_commitment(&did(&sk(67))), [1; 16]).unwrap();
        assert!(matches!(log.rotate(&bad), Err(GrantError::BadRotation(_))));
        // and they can't forge a k1 event without k1's key
        let mut forged = rotate_key(&thief, &log, key_commitment(&did(&sk(67))), [1; 16]).unwrap();
        forged.event.current = did(&k1); // claim the right key…
        assert!(log.rotate(&forged).is_err()); // …but the signature is the thief's
        // the legitimate holder of k1 still rotates fine
        let good = rotate_key(&k1, &log, key_commitment(&did(&sk(12))), [1; 16]).unwrap();
        assert!(log.rotate(&good).is_ok());
    }

    #[test]
    fn rotation_rejects_gaps_and_replays() {
        let k0 = sk(10);
        let k1 = sk(11);
        let k2 = sk(12);
        let inception = incept(&k0, key_commitment(&did(&k1)), [0; 16]).unwrap();
        let mut log = KeyLog::open(&inception).unwrap();
        let ev1 = rotate_key(&k1, &log, key_commitment(&did(&k2)), [1; 16]).unwrap();
        log.rotate(&ev1).unwrap();
        // replaying the same event is a sequence error
        assert!(matches!(log.rotate(&ev1), Err(GrantError::BadRotation(_))));
        // an inception that lies about seq/current is refused
        let bad_incept = SignedKeyEvent {
            event: KeyEvent {
                identity: did(&k0),
                seq: 1,
                current: did(&k0),
                next_hash: key_commitment(&did(&k1)),
                parent: None,
                nonce: [0; 16],
            },
            signature: inception.signature.clone(),
        };
        assert!(KeyLog::open(&bad_incept).is_err());
    }
}
