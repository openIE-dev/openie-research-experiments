//! Joules a cache hit did not spend — a counterfactual, kept apart from measurement.
//!
//! # Why this needs a type of its own
//!
//! MCP's 2026-07-28 revision added `CacheableResult` with `ttlMs` and `cacheScope`, so
//! a served result can now declare itself reusable. When it is reused, work that would
//! have run did not, and that is a real and interesting quantity: for a family whose
//! whole doctrine is "inference is the last resort", the cheapest joule is the one never
//! spent.
//!
//! It is also the easiest quantity in the system to lie with, which is why it does not
//! simply become another `Energy`.
//!
//! # Avoided energy is a counterfactual, not a measurement
//!
//! Nothing measures a joule that was not spent. An avoided figure is a claim about what
//! *would* have happened, and the only thing that makes it checkable is a pointer to the
//! execution it is standing in for. So [`AvoidedEnergy`] cannot be constructed without
//! naming the receipt whose measured cost it claims to have avoided. Without that, "this
//! hit saved 10 mJ" is unfalsifiable — and unfalsifiable savings are how an efficiency
//! programme reports progress it never made.
//!
//! # It must never be added to energy spent
//!
//! The sharp hazard. If avoided joules were summed alongside spent joules, or subtracted
//! from them, a system could manufacture arbitrary efficiency — and with enough cache
//! hits, report negative consumption. Physics does not have a negative-joule case; an
//! accounting system that does has a bug that looks like a triumph.
//!
//! So this type deliberately produces no `Energy`, exposes no arithmetic against a spend
//! total, and is named for what it is. A rollup that wants both reports them as **two
//! figures**, never one.
//!
//! # A cache hit is not free
//!
//! Looking up, validating and returning a cached result costs something. Claiming the
//! full prior cost as "avoided" over-claims by exactly that amount, so the net figure
//! subtracts it — and when a lookup costs more than recomputing would have, the saving
//! is reported as negative rather than clamped to zero. A cache that does not pay for
//! itself is a real and worth-knowing outcome, and rounding it up to "no saving" hides
//! the one case an operator most needs to see.

use jcp_schema::ContentId;

/// Errors from constructing an avoided-energy claim.
#[derive(Debug, PartialEq, Eq)]
pub enum AvoidedError {
    /// The basis names no measured cost, so there is nothing to have avoided.
    ZeroBasis,
    /// The basis figure carries no acquisition class, so it is not comparable to
    /// anything — including to the spend it is standing in for.
    NoBasisProvenance,
}

impl core::fmt::Display for AvoidedError {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        match self {
            AvoidedError::ZeroBasis => {
                write!(f, "a basis of 0 uJ avoids nothing; there is no claim to make")
            }
            AvoidedError::NoBasisProvenance => {
                write!(f, "the basis measurement must carry its acquisition class")
            }
        }
    }
}

impl std::error::Error for AvoidedError {}

/// Joules a cache hit did not spend, and the execution that figure stands in for.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AvoidedEnergy {
    /// The receipt whose measured cost this hit claims to have avoided. Required:
    /// it is the only thing that makes the claim checkable, and a verifier can
    /// resolve it and read the figure for itself.
    pub basis_receipt: ContentId,
    /// The measured microjoules recorded in that receipt.
    pub basis_uj: u64,
    /// The acquisition class of **that** measurement — carried because the saving
    /// inherits it. A saving standing in for an `Estimator` figure is an estimated
    /// saving, however precisely it is printed.
    pub basis_provenance: String,
    /// What serving the hit actually cost. A lookup is not free.
    pub hit_cost_uj: u64,
    /// The TTL the cached result was served under, from `CacheableResult.ttlMs`.
    /// Carried so a reader can see the window the reuse was authorised for.
    pub ttl_ms: u64,
}

impl AvoidedEnergy {
    /// Claim the joules a hit avoided, against the receipt it reused.
    pub fn against(
        basis_receipt: ContentId,
        basis_uj: u64,
        basis_provenance: impl Into<String>,
        hit_cost_uj: u64,
        ttl_ms: u64,
    ) -> Result<Self, AvoidedError> {
        if basis_uj == 0 {
            return Err(AvoidedError::ZeroBasis);
        }
        let basis_provenance = basis_provenance.into();
        if basis_provenance.trim().is_empty() {
            return Err(AvoidedError::NoBasisProvenance);
        }
        Ok(AvoidedEnergy { basis_receipt, basis_uj, basis_provenance, hit_cost_uj, ttl_ms })
    }

    /// The net saving in microjoules: what the prior execution measured, less what
    /// serving the hit cost.
    ///
    /// Signed on purpose. A negative result means the cache cost more than the work
    /// it replaced, which is a real outcome — and clamping it to zero would erase
    /// the single case an operator most needs to act on.
    pub fn net_avoided_uj(&self) -> i128 {
        i128::from(self.basis_uj) - i128::from(self.hit_cost_uj)
    }

    /// Whether the cache actually paid for itself on this hit.
    pub fn paid_for_itself(&self) -> bool {
        self.net_avoided_uj() > 0
    }

    /// The wire form. Deliberately not an `Energy`: this figure must never flow
    /// into a field that means *spent*, and giving it the spend type is how that
    /// happens by accident.
    pub fn to_json(&self) -> String {
        format!(
            "{{\"kind\":\"avoided\",\"basis_receipt\":\"{}\",\"basis_uj\":{},\
             \"basis_provenance\":\"{}\",\"hit_cost_uj\":{},\"net_avoided_uj\":{},\
             \"ttl_ms\":{}}}",
            self.basis_receipt.to_hex(),
            self.basis_uj,
            self.basis_provenance,
            self.hit_cost_uj,
            self.net_avoided_uj(),
            self.ttl_ms
        )
    }
}

/// A period's cache savings, reported **beside** energy spent and never merged into
/// it.
///
/// The two totals answer different questions — "what did this cost" and "what did
/// reuse save" — and only the first is a measurement. Keeping them in one struct with
/// separate accessors is the point: a caller that wants both gets both, and a caller
/// that wants a spend total cannot accidentally receive a netted-off number.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AvoidedSummary {
    /// How many hits were claimed.
    pub hits: u64,
    /// Sum of the basis figures.
    pub basis_uj: u128,
    /// Sum of what serving those hits cost.
    pub hit_cost_uj: u128,
    /// Hits where the cache did not pay for itself.
    pub unprofitable_hits: u64,
}

impl AvoidedSummary {
    /// Fold one claim in.
    pub fn record(&mut self, a: &AvoidedEnergy) {
        self.hits += 1;
        self.basis_uj += u128::from(a.basis_uj);
        self.hit_cost_uj += u128::from(a.hit_cost_uj);
        if !a.paid_for_itself() {
            self.unprofitable_hits += 1;
        }
    }

    /// Net microjoules avoided across the period. Signed, for the same reason as
    /// [`AvoidedEnergy::net_avoided_uj`].
    pub fn net_avoided_uj(&self) -> i128 {
        self.basis_uj as i128 - self.hit_cost_uj as i128
    }

    /// A saving expressed against a spend total, in parts per million of that spend.
    ///
    /// Takes the spend as an argument rather than holding it, so the two totals stay
    /// structurally separate and this is the only place they meet. `None` when spend
    /// is zero: a ratio against nothing is not a figure, and reporting one would let
    /// a system with no measured spend claim an unbounded saving rate.
    pub fn saving_ppm_of(&self, spent_uj: u128) -> Option<i128> {
        if spent_uj == 0 {
            return None;
        }
        Some(self.net_avoided_uj() * 1_000_000 / spent_uj as i128)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn basis() -> ContentId {
        ContentId::of_bytes(b"prior-receipt")
    }

    /// The claim is only checkable because it names the execution it stands in for.
    #[test]
    fn an_avoided_claim_must_cite_the_receipt_it_reused() {
        let a = AvoidedEnergy::against(basis(), 10_565, "HwShunt", 120, 60_000).unwrap();
        assert_eq!(a.basis_receipt, basis());
        assert_eq!(a.net_avoided_uj(), 10_565 - 120);
        assert!(
            a.to_json().contains(&basis().to_hex()),
            "the basis receipt id must reach the wire so a verifier can resolve it"
        );

        // A basis of zero avoids nothing, so there is no claim to make.
        assert_eq!(
            AvoidedEnergy::against(basis(), 0, "HwShunt", 10, 1),
            Err(AvoidedError::ZeroBasis)
        );
    }

    /// The saving inherits the basis measurement's acquisition class: standing in
    /// for an estimate yields an estimated saving, however precisely it prints.
    #[test]
    fn the_saving_inherits_the_basis_provenance() {
        let a = AvoidedEnergy::against(basis(), 1_000, "Estimator", 10, 1).unwrap();
        assert_eq!(a.basis_provenance, "Estimator");
        assert!(a.to_json().contains("\"basis_provenance\":\"Estimator\""));

        assert_eq!(
            AvoidedEnergy::against(basis(), 1_000, "  ", 10, 1),
            Err(AvoidedError::NoBasisProvenance)
        );
    }

    /// A cache that costs more than the work it replaces is a real outcome, and the
    /// figure says so rather than clamping to "no saving".
    #[test]
    fn a_cache_that_does_not_pay_reports_a_negative_saving() {
        let bad = AvoidedEnergy::against(basis(), 100, "HwShunt", 450, 1).unwrap();
        assert_eq!(bad.net_avoided_uj(), -350);
        assert!(!bad.paid_for_itself());
        assert!(bad.to_json().contains("\"net_avoided_uj\":-350"));

        let good = AvoidedEnergy::against(basis(), 10_000, "HwShunt", 50, 1).unwrap();
        assert!(good.paid_for_itself());
    }

    /// The hazard this module exists to prevent: avoided joules are reported beside
    /// spend, never merged into it. A period of pure cache hits cannot produce a
    /// negative spend total, because the two never meet in one number.
    #[test]
    fn avoided_energy_never_becomes_spend() {
        let mut sum = AvoidedSummary::default();
        for _ in 0..5 {
            sum.record(&AvoidedEnergy::against(basis(), 1_000_000, "HwShunt", 100, 1).unwrap());
        }
        assert_eq!(sum.hits, 5);
        assert_eq!(sum.net_avoided_uj(), 5 * (1_000_000 - 100));

        // The saving is huge relative to a small measured spend — and it is still
        // expressed as a ratio TO that spend, not as a deduction FROM it.
        let spent_uj = 200_u128;
        let ppm = sum.saving_ppm_of(spent_uj).unwrap();
        assert!(ppm > 0);
        // Nothing here yields a spend figure at all, let alone a negative one.
        // `AvoidedSummary` has no `energy()` and produces no `Energy`.

        // A ratio against nothing is not a figure.
        assert_eq!(sum.saving_ppm_of(0), None);
    }

    /// Unprofitable hits are counted, so a cache that is net-positive overall while
    /// losing on most requests is visible rather than averaged away.
    #[test]
    fn unprofitable_hits_are_counted_separately_from_the_net() {
        let mut sum = AvoidedSummary::default();
        // One large win, three small losses.
        sum.record(&AvoidedEnergy::against(basis(), 100_000, "HwShunt", 10, 1).unwrap());
        for _ in 0..3 {
            sum.record(&AvoidedEnergy::against(basis(), 10, "HwShunt", 90, 1).unwrap());
        }
        assert!(sum.net_avoided_uj() > 0, "net positive overall");
        assert_eq!(sum.unprofitable_hits, 3, "and losing on most hits, visibly");
        assert_eq!(sum.hits, 4);
    }
}
