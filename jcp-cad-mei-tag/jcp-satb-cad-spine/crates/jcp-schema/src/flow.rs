//! The flow lattice (SPEC §4.10) — propagated provenance labels.
//!
//! JCP's [`Trust`](crate::Trust) tag is a one-*bit* boundary marker: a frame is
//! principal `Control` or untrusted `Data`, and a `Data` frame may never exercise
//! a capability. That stops output from being *executed*, but it cannot express
//! "this argument was **derived** from an earlier untrusted read": the bit does
//! not propagate through the values a run computes.
//!
//! This module is the propagated form. A [`Label`] is a point in a lattice with
//! three independent axes:
//!
//! - **integrity** — how believable the value is, a total order from `Untrusted`
//!   up to `Principal`;
//! - **origins** — the set of channels a value's bytes flowed from;
//! - **readers** — who may see it (present and sealed, but *enforcement* is a
//!   later increment — see the crate SPEC; today it only rides along).
//!
//! The one join `⊔` folds a derived value's label from its inputs. The whole
//! point is the ordering `⊑`: a value may exercise a capability only when its
//! label sits at or below the grant's [`FlowCeiling`]. Everything downstream (the
//! runtime gate, the sealed verdict, replay) is built on the algebra proven here,
//! so this module carries the lattice **laws** as tests rather than leaving them
//! implicit.
//!
//! Direction, fixed once: `⊥` (bottom) is the *cleanest* label — `Principal`
//! integrity, no origins, `Public` readers — and `join` moves *up* toward more
//! taint. So `a ⊑ b` reads "a is at least as clean as b", and taint on a derived
//! value never decreases below any of its inputs (the no-laundering law).
//!
//! All collections are `BTree*`, never `Hash*`: a label is content-addressed and
//! sealed into a receipt, so iteration order must be deterministic across runs and
//! platforms.

use std::collections::BTreeSet;

use serde::{Deserialize, Serialize};

use crate::{ContentId, Did, SchemaError, Trust};

/// The integrity axis: how believable a value is. A **total** order — higher is
/// more trusted. In the taint join two labels take the *weaker* (lower) integrity,
/// because a value derived from an untrusted input is no more believable than that
/// input.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum Integrity {
    Untrusted,
    Derived,
    Attested,
    Principal,
}

impl Integrity {
    /// The weaker (less believable) of the two — the taint join on this axis.
    pub fn weaker(self, other: Self) -> Self {
        if self <= other {
            self
        } else {
            other
        }
    }

    /// The stronger (more believable) of the two — the meet, used when attenuating
    /// a ceiling (a child ceiling may only *raise* the integrity it demands).
    pub fn stronger(self, other: Self) -> Self {
        if self >= other {
            self
        } else {
            other
        }
    }
}

/// Where a value's bytes came from: a **content-addressed** channel (the
/// `mcp_resource(server, tool)` id), optionally narrowed to the principal that
/// spoke on it. Content-addressed rather than string-named so an origin cannot be
/// forged by naming, and so a resource-keyed taint floor can be authored against a
/// known channel id at startup.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
pub struct Origin {
    pub channel: ContentId,
    #[serde(skip_serializing_if = "Option::is_none", default)]
    pub principal: Option<Did>,
}

impl Origin {
    pub fn channel(channel: ContentId) -> Self {
        Origin { channel, principal: None }
    }
    pub fn from(channel: ContentId, principal: Did) -> Self {
        Origin { channel, principal: Some(principal) }
    }
}

/// Above this many distinct origins a label saturates to [`Origins::Any`]. A
/// bound is needed so a long-running session's label cannot grow without limit;
/// saturation is *sound* because `Any` is the top of the axis and only ever denies
/// more (a ceiling that excludes some origin also excludes `Any`).
pub const MAX_ORIGINS: usize = 64;

/// The origins axis. `Any` is the top: it stands for "could be from anywhere", a
/// conservative over-approximation a ceiling can never satisfy unless it, too, is
/// `Any`.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case", from = "OriginsWire")]
pub enum Origins {
    Set(BTreeSet<Origin>),
    Any,
}

/// Wire form of [`Origins`] — deserialised through [`Origins::normalize`] so an
/// over-large `Set` on the wire becomes `Any`, keeping `⊑` antisymmetric (two
/// distinct encodings of the top would break it).
#[derive(Deserialize)]
#[serde(rename_all = "kebab-case")]
enum OriginsWire {
    Set(BTreeSet<Origin>),
    Any,
}

impl From<OriginsWire> for Origins {
    fn from(wire: OriginsWire) -> Self {
        match wire {
            OriginsWire::Set(set) => Origins::Set(set).normalized(),
            OriginsWire::Any => Origins::Any,
        }
    }
}

impl Origins {
    pub fn none() -> Self {
        Origins::Set(BTreeSet::new())
    }

    pub fn one(origin: Origin) -> Self {
        let mut set = BTreeSet::new();
        set.insert(origin);
        Origins::Set(set)
    }

    pub fn is_empty(&self) -> bool {
        matches!(self, Origins::Set(set) if set.is_empty())
    }

    /// Collapse an over-large set to `Any`. Idempotent; `Any` stays `Any`.
    pub fn normalized(self) -> Self {
        match self {
            Origins::Set(set) if set.len() > MAX_ORIGINS => Origins::Any,
            other => other,
        }
    }

    /// Join — union, saturating to `Any`. The taint direction: a value drawn from
    /// two sources carries both.
    pub fn join(&self, other: &Self) -> Self {
        match (self, other) {
            (Origins::Any, _) | (_, Origins::Any) => Origins::Any,
            (Origins::Set(a), Origins::Set(b)) => {
                Origins::Set(a.union(b).cloned().collect()).normalized()
            }
        }
    }

    /// Meet — intersection; `Any` is the identity (used when attenuating a
    /// ceiling, where `Any` means "no origin restriction").
    pub fn meet(&self, other: &Self) -> Self {
        match (self, other) {
            (Origins::Any, x) | (x, Origins::Any) => x.clone(),
            (Origins::Set(a), Origins::Set(b)) => {
                Origins::Set(a.intersection(b).cloned().collect())
            }
        }
    }

    /// `self ⊑ other`: subset, with everything below `Any`.
    pub fn leq(&self, other: &Self) -> bool {
        match (self, other) {
            (_, Origins::Any) => true,
            (Origins::Any, Origins::Set(_)) => false,
            (Origins::Set(a), Origins::Set(b)) => a.is_subset(b),
        }
    }

    /// Does this label's origin set touch any origin in `mask`? The taint floor's
    /// test: a resource can forbid values that carry a given origin. `Any` touches
    /// every non-empty mask (the conservative reading of "could be from anywhere").
    pub fn intersects(&self, mask: &Self) -> bool {
        match (self, mask) {
            (Origins::Any, m) => !m.is_empty() || matches!(m, Origins::Any),
            (s, Origins::Any) => !s.is_empty() || matches!(s, Origins::Any),
            (Origins::Set(a), Origins::Set(b)) => a.intersection(b).next().is_some(),
        }
    }
}

/// The confidentiality axis: who may see a value. `Public` is the bottom (any
/// reader). Present and sealed so the wire is stable, but audience *enforcement*
/// is a later increment; today it only propagates.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum Readers {
    Public,
    Only(BTreeSet<Did>),
}

impl Readers {
    /// Join — audience *intersection* (a value combining two secrets is readable
    /// only by those cleared for both), so fewer readers is more taint. `Public`
    /// is the identity.
    pub fn join(&self, other: &Self) -> Self {
        match (self, other) {
            (Readers::Public, x) | (x, Readers::Public) => x.clone(),
            (Readers::Only(a), Readers::Only(b)) => {
                Readers::Only(a.intersection(b).copied().collect())
            }
        }
    }

    /// Meet — audience *union*; `Public` absorbs (used to attenuate a ceiling's
    /// reader bound).
    pub fn meet(&self, other: &Self) -> Self {
        match (self, other) {
            (Readers::Public, _) | (_, Readers::Public) => Readers::Public,
            (Readers::Only(a), Readers::Only(b)) => {
                Readers::Only(a.union(b).copied().collect())
            }
        }
    }

    /// `self ⊑ other`: `other`'s audience is a subset of `self`'s (more readable is
    /// cleaner). `Public` is below every `Only`.
    pub fn leq(&self, other: &Self) -> bool {
        match (self, other) {
            (Readers::Public, _) => true,
            (Readers::Only(_), Readers::Public) => false,
            (Readers::Only(a), Readers::Only(b)) => b.is_subset(a),
        }
    }
}

/// A point in the flow lattice: the propagated provenance of a value. `⊥` (see
/// [`Label::bottom`]) is the cleanest; [`Label::join`] moves toward more taint.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Label {
    pub integrity: Integrity,
    pub origins: Origins,
    pub readers: Readers,
}

impl Label {
    /// `⊥` — a principal-authored value from no channel, readable by all. The label
    /// of every value in a run that has touched no untrusted source, so a clean run
    /// is byte-identical to the pre-lattice world.
    pub fn bottom() -> Self {
        Label { integrity: Integrity::Principal, origins: Origins::none(), readers: Readers::Public }
    }

    /// `⊤` — maximally tainted: untrusted, from anywhere, readable by nobody. The
    /// saturation point; rarely constructed directly but the identity for meet.
    pub fn top() -> Self {
        Label { integrity: Integrity::Untrusted, origins: Origins::Any, readers: Readers::Only(BTreeSet::new()) }
    }

    pub fn is_bottom(&self) -> bool {
        *self == Label::bottom()
    }

    /// Fold two labels — the taint join, component-wise. This is the operation
    /// that propagates provenance from a value's inputs onto the value.
    pub fn join(&self, other: &Self) -> Self {
        Label {
            integrity: self.integrity.weaker(other.integrity),
            origins: self.origins.join(&other.origins),
            readers: self.readers.join(&other.readers),
        }
    }

    /// The meet — greatest lower bound. Used to attenuate a ceiling so a child can
    /// only make it stricter.
    pub fn meet(&self, other: &Self) -> Self {
        Label {
            integrity: self.integrity.stronger(other.integrity),
            origins: self.origins.meet(&other.origins),
            readers: self.readers.meet(&other.readers),
        }
    }

    /// `self ⊑ other` — is this label at least as clean as `other`? A value may
    /// exercise a capability exactly when its label `⊑` the ceiling.
    pub fn leq(&self, other: &Self) -> bool {
        self.integrity >= other.integrity
            && self.origins.leq(&other.origins)
            && self.readers.leq(&other.readers)
    }

    /// The content address of this label — its identity in a witness and the value
    /// sealed into a receipt. Pure and order-free because every field is `BTree`,
    /// so the same label digests identically on any platform (the determinism law).
    pub fn digest(&self) -> Result<ContentId, SchemaError> {
        ContentId::of(self)
    }

    /// Retract the propagated label to the one-bit [`Trust`] tag: a value is
    /// `Data` exactly when its integrity is `Untrusted`, else `Control`. This is
    /// the coarsening the pre-lattice world sees, and it is monotone — refining a
    /// label never contradicts the bit.
    pub fn trust(&self) -> Trust {
        match self.integrity {
            Integrity::Untrusted => Trust::Data,
            _ => Trust::Control,
        }
    }
}

impl From<Trust> for Label {
    /// Embed the one-bit tag as a label: `Control` is a principal-clean value,
    /// `Data` an untrusted one — both from no specific channel. The inverse of
    /// [`Label::trust`] on this range, so `Label::from(t).trust() == t`.
    fn from(trust: Trust) -> Self {
        match trust {
            Trust::Control => Label::bottom(),
            Trust::Data => Label {
                integrity: Integrity::Untrusted,
                origins: Origins::none(),
                readers: Readers::Public,
            },
        }
    }
}

/// A grant's flow ceiling: the greatest (most tainted) label whose values may
/// still exercise the capability, plus an optional smaller joule budget that
/// applies once a call is tainted at all.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct FlowCeiling {
    pub ceiling: Label,
    #[serde(skip_serializing_if = "Option::is_none", default)]
    pub tainted_budget_uj: Option<u64>,
}

impl FlowCeiling {
    pub fn new(ceiling: Label) -> Self {
        FlowCeiling { ceiling, tainted_budget_uj: None }
    }

    /// Attenuate for a delegation hop: the child ceiling is the **meet** of the two
    /// (so it can only get stricter) and the tainted budget the **min**. Because
    /// both moves are monotone-down, a child can never widen what a parent allowed
    /// — capability amplification is unrepresentable, not merely rejected.
    pub fn attenuate(&self, child: &FlowCeiling) -> FlowCeiling {
        let tainted_budget_uj = match (self.tainted_budget_uj, child.tainted_budget_uj) {
            (Some(a), Some(b)) => Some(a.min(b)),
            (Some(a), None) => Some(a),
            (None, b) => b,
        };
        FlowCeiling { ceiling: self.ceiling.meet(&child.ceiling), tainted_budget_uj }
    }

    /// Does a value with label `l` pass this ceiling?
    pub fn admits(&self, l: &Label) -> bool {
        l.leq(&self.ceiling)
    }
}

/// Fold a slice of labels — the join over all of them, starting from `⊥`. The
/// label of a value derived from many inputs. Order-free (join is commutative and
/// associative), which is what lets replay re-fold a witness in any order.
pub fn fold(labels: &[Label]) -> Label {
    labels.iter().fold(Label::bottom(), |acc, l| acc.join(l))
}

/// What the runtime consumes at gate time: a value's folded [`Label`], a
/// commitment to the [witness](../../jcp_flow) that justifies it, and the monitor's
/// own metered cost of computing it (reported separately, never folded into the
/// call's energy).
///
/// A `bottom` facts value means "provenance computed, and clean" — distinct from
/// *no* facts (`None` at the gate), which fails closed against a ceiling. This is
/// deliberately not a wire type: it travels in-process from the gateway to the
/// runtime, and what gets sealed is the label and `witness_id`, via the receipt.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FlowFacts {
    pub label: Label,
    pub witness_id: ContentId,
    /// The monitor's own energy for computing the label (microjoules).
    pub eval_uj: u64,
    pub eval_prov: crate::Provenance,
}

impl FlowFacts {
    /// Clean facts — a value with no untrusted provenance and no monitor cost.
    pub fn bottom() -> Self {
        FlowFacts {
            label: Label::bottom(),
            witness_id: ContentId([0u8; 32]),
            eval_uj: 0,
            eval_prov: crate::Provenance::Estimator,
        }
    }

    /// Is this a clean (`⊥`) label? The gate treats bottom facts as "no ceiling
    /// concern"; it is *not* the same as facts being absent.
    pub fn is_bottom(&self) -> bool {
        self.label.is_bottom()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cid(byte: u8) -> ContentId {
        ContentId([byte; 32])
    }
    fn did(byte: u8) -> Did {
        Did([byte; 32])
    }

    /// A representative spread of labels covering every axis extreme, so the
    /// exhaustive law checks below actually exercise the corners (Any, empty
    /// origins, Public, restricted readers, every integrity rank).
    fn sample_labels() -> Vec<Label> {
        let integrities =
            [Integrity::Untrusted, Integrity::Derived, Integrity::Attested, Integrity::Principal];
        let origins = [
            Origins::none(),
            Origins::one(Origin::channel(cid(1))),
            Origins::one(Origin::from(cid(1), did(9))),
            {
                let mut s = BTreeSet::new();
                s.insert(Origin::channel(cid(1)));
                s.insert(Origin::channel(cid(2)));
                Origins::Set(s)
            },
            Origins::Any,
        ];
        let readers = [
            Readers::Public,
            Readers::Only(BTreeSet::new()),
            Readers::Only([did(5)].into_iter().collect()),
            Readers::Only([did(5), did(6)].into_iter().collect()),
        ];
        let mut out = Vec::new();
        for i in &integrities {
            for o in &origins {
                for r in &readers {
                    out.push(Label { integrity: *i, origins: o.clone(), readers: r.clone() });
                }
            }
        }
        out
    }

    #[test]
    fn l1_l2_l4_join_is_idempotent_commutative_with_identity() {
        let bottom = Label::bottom();
        for a in sample_labels() {
            assert_eq!(a.join(&a), a, "L1 idempotent: {a:?}");
            assert_eq!(a.join(&bottom), a, "L4 identity: {a:?}");
            for b in sample_labels() {
                assert_eq!(a.join(&b), b.join(&a), "L2 commutative: {a:?} {b:?}");
            }
        }
    }

    #[test]
    fn l3_join_is_associative() {
        let labels = sample_labels();
        // A representative triple sweep (full cube is ~10^5, this samples every
        // third to stay fast while still crossing axis extremes).
        for (index, a) in labels.iter().enumerate() {
            for b in labels.iter().step_by(3) {
                for c in labels.iter().skip(index % 3).step_by(5) {
                    assert_eq!(
                        a.join(b).join(c),
                        a.join(&b.join(c)),
                        "L3 associative: {a:?} {b:?} {c:?}"
                    );
                }
            }
        }
    }

    #[test]
    fn l5_top_absorbs() {
        let top = Label::top();
        for a in sample_labels() {
            assert_eq!(a.join(&top), top, "L5 absorbing top: {a:?}");
        }
    }

    #[test]
    fn l6_order_agrees_with_join() {
        // a ⊑ b ⟺ a ⊔ b = b — the defining bridge between the order and the join.
        for a in sample_labels() {
            for b in sample_labels() {
                assert_eq!(a.leq(&b), a.join(&b) == b, "L6: {a:?} ⊑ {b:?}");
            }
        }
    }

    #[test]
    fn l7_order_is_a_partial_order() {
        let labels = sample_labels();
        for a in &labels {
            assert!(a.leq(a), "reflexive: {a:?}");
        }
        for a in &labels {
            for b in &labels {
                // antisymmetry
                if a.leq(b) && b.leq(a) {
                    assert_eq!(a, b, "antisymmetric: {a:?} {b:?}");
                }
                if a.leq(b) {
                    for c in labels.iter().step_by(2) {
                        if b.leq(c) {
                            assert!(a.leq(c), "transitive: {a:?} ⊑ {b:?} ⊑ {c:?}");
                        }
                    }
                }
            }
        }
    }

    #[test]
    fn l8_join_is_monotone() {
        // a⊑a' ∧ b⊑b' ⇒ a⊔b ⊑ a'⊔b'
        let labels = sample_labels();
        for a in labels.iter().step_by(2) {
            for a2 in labels.iter().step_by(3) {
                if !a.leq(a2) {
                    continue;
                }
                for b in labels.iter().step_by(5) {
                    for b2 in labels.iter().step_by(7) {
                        if b.leq(b2) {
                            assert!(
                                a.join(b).leq(&a2.join(b2)),
                                "L8 monotone: {a:?}⊑{a2:?}, {b:?}⊑{b2:?}"
                            );
                        }
                    }
                }
            }
        }
    }

    #[test]
    fn l9_join_never_launders() {
        // Each input is ⊑ the fold of the inputs: taint never decreases.
        let labels = sample_labels();
        for a in labels.iter().step_by(2) {
            for b in labels.iter().step_by(3) {
                let derived = a.join(b);
                assert!(a.leq(&derived), "L9: input {a:?} ⊑ derived {derived:?}");
                assert!(b.leq(&derived), "L9: input {b:?} ⊑ derived {derived:?}");
            }
        }
    }

    #[test]
    fn l11_allow_is_downward_closed() {
        // If a ceiling admits l, it admits everything cleaner than l.
        let ceilings = sample_labels();
        let values = sample_labels();
        for ceiling in ceilings.iter().step_by(3) {
            for l in values.iter().step_by(2) {
                if l.leq(ceiling) {
                    for cleaner in values.iter().step_by(5) {
                        if cleaner.leq(l) {
                            assert!(cleaner.leq(ceiling), "L11: {cleaner:?} ⊑ {l:?} ⊑ {ceiling:?}");
                        }
                    }
                }
            }
        }
    }

    #[test]
    fn l12_attenuation_only_narrows() {
        // A child ceiling is never wider than its parent: everything the attenuated
        // ceiling admits, the parent admits too. Amplification is unrepresentable.
        let labels = sample_labels();
        for parent in labels.iter().step_by(2) {
            let parent_c = FlowCeiling::new(parent.clone());
            for child in labels.iter().step_by(3) {
                let attenuated = parent_c.attenuate(&FlowCeiling::new(child.clone()));
                for value in labels.iter().step_by(5) {
                    if attenuated.admits(value) {
                        assert!(
                            parent_c.admits(value),
                            "L12: parent {parent:?} must admit what child-attenuated {:?} admits ({value:?})",
                            attenuated.ceiling
                        );
                    }
                }
            }
        }
        // And the tainted budget only shrinks.
        let a = FlowCeiling { ceiling: Label::bottom(), tainted_budget_uj: Some(500) };
        let b = FlowCeiling { ceiling: Label::bottom(), tainted_budget_uj: Some(200) };
        assert_eq!(a.attenuate(&b).tainted_budget_uj, Some(200));
        assert_eq!(b.attenuate(&a).tainted_budget_uj, Some(200));
    }

    #[test]
    fn l13_saturation_is_sound() {
        // A saturated origin set is above the set it came from: it only denies more.
        let mut set = BTreeSet::new();
        for byte in 0..=(MAX_ORIGINS as u16) {
            set.insert(Origin::channel(cid(byte as u8)));
        }
        let saturated = Origins::Set(set).normalized();
        assert_eq!(saturated, Origins::Any, "over-large set saturates");
        assert!(Origins::one(Origin::channel(cid(1))).leq(&Origins::Any), "L13: Set ⊑ Any");
    }

    #[test]
    fn l14_digest_is_deterministic_and_order_free() {
        // The same label, built two ways with reader/origin insertion in different
        // orders, digests identically.
        let a = Label {
            integrity: Integrity::Derived,
            origins: {
                let mut s = BTreeSet::new();
                s.insert(Origin::channel(cid(2)));
                s.insert(Origin::channel(cid(1)));
                Origins::Set(s)
            },
            readers: Readers::Only([did(6), did(5)].into_iter().collect()),
        };
        let b = Label {
            integrity: Integrity::Derived,
            origins: {
                let mut s = BTreeSet::new();
                s.insert(Origin::channel(cid(1)));
                s.insert(Origin::channel(cid(2)));
                Origins::Set(s)
            },
            readers: Readers::Only([did(5), did(6)].into_iter().collect()),
        };
        assert_eq!(a.digest().unwrap(), b.digest().unwrap(), "L14 determinism");
        // Distinct labels digest distinctly.
        assert_ne!(a.digest().unwrap(), Label::bottom().digest().unwrap());
    }

    #[test]
    fn l16_trust_retraction_round_trips_and_is_monotone() {
        // The one-bit tag embeds and retracts exactly.
        assert_eq!(Label::from(Trust::Control).trust(), Trust::Control);
        assert_eq!(Label::from(Trust::Data).trust(), Trust::Data);

        // Monotone: a cleaner label never retracts to a *less* trusted bit. With
        // Control the trusted tag, l ⊑ m (l cleaner) ⇒ trust(l) is at least as
        // trusted as trust(m). Encode "at least as trusted" as Control > Data.
        fn rank(t: Trust) -> u8 {
            match t {
                Trust::Data => 0,
                Trust::Control => 1,
            }
        }
        for l in sample_labels() {
            for m in sample_labels() {
                if l.leq(&m) {
                    assert!(
                        rank(l.trust()) >= rank(m.trust()),
                        "L16 monotone: cleaner {l:?} must not be less trusted than {m:?}"
                    );
                }
            }
        }
    }

    #[test]
    fn l15_refinement_bottom_is_the_clean_world() {
        // A bottom label passes any ceiling — a clean run is never newly denied.
        for ceiling in sample_labels() {
            assert!(
                FlowCeiling::new(ceiling.clone()).admits(&Label::bottom()),
                "L15: ⊥ admitted by every ceiling {ceiling:?}"
            );
        }
    }

    #[test]
    fn fold_is_the_join_over_inputs() {
        let a = Label { integrity: Integrity::Attested, ..Label::bottom() };
        let b = Label {
            integrity: Integrity::Untrusted,
            origins: Origins::one(Origin::channel(cid(3))),
            readers: Readers::Public,
        };
        assert_eq!(fold(&[a.clone(), b.clone()]), a.join(&b));
        assert_eq!(fold(&[]), Label::bottom());
    }

    #[test]
    fn origins_wire_normalizes_on_deserialize() {
        // An over-large Set arriving on the wire must come back as Any, or two
        // encodings of the top would exist and break antisymmetry (L7).
        let mut set = BTreeSet::new();
        for byte in 0..=(MAX_ORIGINS as u16) {
            set.insert(Origin::channel(cid(byte as u8)));
        }
        let wire = crate::cbor::canonical_cbor(&Origins::Set(set)).unwrap();
        let back: Origins = crate::cbor::from_canonical_cbor(&wire).unwrap();
        assert_eq!(back, Origins::Any);
    }
}
