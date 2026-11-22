//! Energy traceability across the three levels an AI system is accountable at:
//! **operation**, **activity**, and **outcome**.
//!
//! # The levels, and where the family already measures
//!
//! A deployed system is answerable at three different grains, and they are not
//! interchangeable:
//!
//! - **Operation** — one unit of work. `jcp-receipt`'s JCR-1 work receipt
//!   carries `joules_uj` with a [`Provenance`] grade. This level is measured.
//! - **Activity** — one *authorised* thing done: a grant checked, an
//!   environment attested, work performed, an effect committed, bytes egressed.
//!   `jcp-action-receipt`'s AR-1 binds all five by content-id.
//! - **Outcome** — whether any of it *bought* anything. `efficiency/1` anchors
//!   on `completed` and totals the energy the unit spent.
//!
//! # The two seams this module closes
//!
//! **An outcome's energy was unbound.** [`crate::Efficiency::task`] is a
//! `String`. An outcome could claim any total it liked and nothing tied that
//! figure to the activities that produced it — the one level where a number is
//! most load-bearing was the one level identified by free text. Here an outcome
//! names its activities by [`ContentId`], so a verifier can resolve each one
//! and add the figures up itself.
//!
//! **An activity had no energy of its own.** AR-1 carries exactly one joules
//! figure and it belongs to *binding 3: work*. The cost of the authorisation
//! check, the attestation, the verification, and of pushing bytes off the
//! device is real and was attributed nowhere. `Egress` counts bytes and no
//! joules.
//!
//! So the sum of an outcome's operations is **not** the outcome's energy, and
//! the difference is not noise — it is the cost of being accountable. This
//! module names that difference instead of letting it vanish.
//!
//! # Conservation, with the residual named
//!
//! Reconciliation is exact integer arithmetic in µJ, summed in `u128`:
//!
//! ```text
//! residual_uj = total_uj - Σ activity.joules_uj
//! ```
//!
//! The residual is **signed** and never clamped. Negative means the bound
//! activities claim more energy than the outcome admits — double-counted work,
//! or a wrong binding — and that is a finding, not a rounding error. Clamping
//! it to zero would hide exactly the case an auditor needs.
//!
//! This mirrors `eoc-carbon`'s allocation discipline, where
//! `Σ shares + residual == total` holds exactly and the residual is a named
//! field rather than a silent remainder.
//!
//! # A chain is only as graded as its weakest link
//!
//! The composite [`Provenance`] is the **floor** across the parts, never an
//! average and never the best: one `Estimator` activity makes the whole trace
//! estimated, because the trace cannot be more measured than the thing in it
//! that was not measured. Coverage takes the floor the same way — one `Partial`
//! part makes the composite `Partial`, since the missing share does not become
//! accounted for by sitting next to accounted shares.
//!
//! This is the same rule as `Vmm::attained_tier` returning the floor and
//! `Backing` defaulting to `Unstated`: aggregation must not be a laundering
//! step.

use serde::{Deserialize, Serialize};

use jcp_schema::{ContentId, Coverage, Energy, Provenance};

/// One activity bound into an outcome, as a verifier reads it.
///
/// The fields are copied from the AR-1 receipt named by [`Self::receipt`] so a
/// reconciliation can be checked without resolving every receipt — but
/// [`Self::receipt`] is what makes the claim falsifiable: resolve it and the
/// copied figures must match.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ActivityRef {
    /// The AR-1 action receipt. The binding, and the only thing here that
    /// cannot be fabricated without also fabricating a signed receipt.
    pub receipt: ContentId,
    /// The work's energy, from AR-1 `joules_uj`.
    pub joules_uj: u64,
    /// How that figure was acquired, from AR-1 `energy_provenance`. Carried
    /// verbatim; never upgraded here.
    pub provenance: Provenance,
    /// How much of the activity's work the figure accounts for.
    pub coverage: Coverage,
}

impl ActivityRef {
    /// Bind one activity.
    pub fn new(
        receipt: ContentId,
        joules_uj: u64,
        provenance: Provenance,
        coverage: Coverage,
    ) -> Self {
        ActivityRef { receipt, joules_uj, provenance, coverage }
    }
}

/// Why a trace cannot be presented as traceable.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum TraceError {
    /// The outcome names no activities. Its energy total is then an assertion
    /// about nothing a verifier can resolve — the free-text case this module
    /// exists to retire.
    Unbound,
    /// The bound activities claim more energy than the outcome admits.
    /// Double-counted work, or an activity bound to the wrong outcome.
    OverAccounted { accounted_uj: u128, total_uj: u64 },
    /// The same activity receipt appears twice. Summing it twice inflates the
    /// accounted figure and shrinks the residual, which flatters the trace in
    /// exactly the direction that matters.
    DuplicateActivity { receipt: ContentId },
}

impl core::fmt::Display for TraceError {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        match self {
            TraceError::Unbound => write!(
                f,
                "outcome names no activities: its energy total is not traceable \
                 to anything a verifier can resolve"
            ),
            TraceError::OverAccounted { accounted_uj, total_uj } => write!(
                f,
                "bound activities account for {accounted_uj} uJ but the outcome \
                 admits only {total_uj} uJ; the work is double-counted or an \
                 activity is bound to the wrong outcome"
            ),
            TraceError::DuplicateActivity { receipt } => write!(
                f,
                "activity {} is bound twice; summing it twice inflates the \
                 accounted figure and shrinks the residual",
                receipt.to_hex()
            ),
        }
    }
}

impl std::error::Error for TraceError {}

/// What reconciling an outcome against its activities establishes.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Reconciliation {
    /// Σ of the bound activities' work energy.
    pub accounted_uj: u128,
    /// `total - accounted`. **Signed and never clamped.** Positive is the cost
    /// of being accountable — authorisation, attestation, verification, egress
    /// — which no operation receipt claims. Zero means the outcome admits
    /// exactly its operations and nothing else, which for a gated, attested,
    /// receipt-emitting system is itself worth a second look.
    pub residual_uj: i128,
    /// The weakest provenance across the outcome and every bound activity.
    pub provenance_floor: Provenance,
    /// `Partial` if the outcome or any activity is partial.
    pub coverage_floor: Coverage,
    /// How many activities were reconciled.
    pub activities: usize,
}

impl Reconciliation {
    /// The share of the outcome's energy that no operation receipt claims, in
    /// parts per million.
    ///
    /// This is the number the three-level question actually turns on: how much
    /// of what an outcome cost is attributable to a measured operation, and how
    /// much is the overhead of accountability itself. `None` when the total is
    /// zero — a ratio against nothing is not a figure.
    pub fn unattributed_ppm(&self, total_uj: u64) -> Option<i128> {
        if total_uj == 0 {
            return None;
        }
        Some(self.residual_uj * 1_000_000 / i128::from(total_uj))
    }
}

/// An outcome, the activities that produced it, and the arithmetic between them.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct OutcomeTrace {
    /// The outcome's own energy figure, as `efficiency/1` records it.
    pub total: Energy,
    /// Whether the outcome was reached. Carried because energy spent on an
    /// outcome that did not complete is a different claim from energy spent on
    /// one that did, and a trace that drops it loses the anchor.
    pub completed: bool,
    /// The activities this outcome is traced to.
    pub activities: Vec<ActivityRef>,
}

impl OutcomeTrace {
    /// Trace an outcome to its activities.
    pub fn new(total: Energy, completed: bool, activities: Vec<ActivityRef>) -> Self {
        OutcomeTrace { total, completed, activities }
    }

    /// The outcome's energy in µJ, preferring the measured figure.
    ///
    /// `measured_uj` when present, `estimated_uj` otherwise — and the choice is
    /// already graded by [`Energy::provenance`], so this does not re-decide it.
    pub fn total_uj(&self) -> u64 {
        self.total.measured_uj.unwrap_or(self.total.estimated_uj)
    }

    /// Reconcile the outcome against its activities, or refuse to.
    ///
    /// Refuses an unbound outcome, a duplicated activity, and an over-accounted
    /// total. Everything else reconciles, including a large positive residual —
    /// that is a legitimate and interesting result, not an error.
    pub fn reconcile(&self) -> Result<Reconciliation, TraceError> {
        if self.activities.is_empty() {
            return Err(TraceError::Unbound);
        }

        // Duplicate detection before summing: the whole point of the residual
        // is that it is exact, and a double-counted activity corrupts it
        // silently in the flattering direction.
        for (i, a) in self.activities.iter().enumerate() {
            if self.activities[..i].iter().any(|b| b.receipt == a.receipt) {
                return Err(TraceError::DuplicateActivity { receipt: a.receipt });
            }
        }

        // u128 so a long trace cannot overflow into a small number — a wrapped
        // sum would under-account and inflate the residual.
        let accounted_uj: u128 =
            self.activities.iter().map(|a| u128::from(a.joules_uj)).sum();
        let total_uj = self.total_uj();
        if accounted_uj > u128::from(total_uj) {
            return Err(TraceError::OverAccounted { accounted_uj, total_uj });
        }

        let residual_uj = i128::from(total_uj) - accounted_uj as i128;

        let provenance_floor = self
            .activities
            .iter()
            .map(|a| a.provenance)
            .fold(self.total.provenance, weakest_provenance);
        let coverage_floor = self
            .activities
            .iter()
            .map(|a| a.coverage)
            .fold(self.total.coverage, weakest_coverage);

        Ok(Reconciliation {
            accounted_uj,
            residual_uj,
            provenance_floor,
            coverage_floor,
            activities: self.activities.len(),
        })
    }
}

/// The weaker of two acquisition classes: `HwShunt` > `ModelBased` > `Estimator`.
///
/// A composite is never more measured than its least-measured part. Averaging
/// would let one hardware reading launder a pile of estimates.
pub(crate) fn weakest_provenance(a: Provenance, b: Provenance) -> Provenance {
    fn rank(p: Provenance) -> u8 {
        match p {
            Provenance::HwShunt => 2,
            Provenance::ModelBased => 1,
            Provenance::Estimator => 0,
        }
    }
    if rank(b) < rank(a) {
        b
    } else {
        a
    }
}

/// `Partial` if either is partial. An unaccounted share does not become
/// accounted for by being summed with accounted ones.
pub(crate) fn weakest_coverage(a: Coverage, b: Coverage) -> Coverage {
    match (a, b) {
        (Coverage::Whole, Coverage::Whole) => Coverage::Whole,
        _ => Coverage::Partial,
    }
}


#[cfg(test)]
mod seal_gate_tests {
    use super::*;
    use crate::dynamics::{EnergyWindow, PowerEnvelope};

    fn energy(uj: u64, p: Provenance, c: Coverage) -> Energy {
        Energy { measured_uj: Some(uj), estimated_uj: uj, provenance: p, coverage: c }
    }
    fn act(tag: &[u8], uj: u64, p: Provenance, c: Coverage) -> ActivityRef {
        ActivityRef::new(ContentId::of_bytes(tag), uj, p, c)
    }
    fn win(uj: u64, dur_ns: u64) -> EnergyWindow {
        EnergyWindow {
            started_ns: 0,
            duration_ns: dur_ns,
            joules_uj: uj,
            provenance: Provenance::HwShunt,
            coverage: Coverage::Whole,
            declared_work: None,
        }
    }
    fn env() -> PowerEnvelope {
        PowerEnvelope { peak_mw: 60_000, idle_floor_mw: 1_000, source: "burst".into() }
    }
    fn sound() -> OutcomeTrace {
        OutcomeTrace::new(
            energy(1_000_000, Provenance::HwShunt, Coverage::Whole),
            true,
            vec![act(b"a1", 400_000, Provenance::HwShunt, Coverage::Whole),
                 act(b"a2", 350_000, Provenance::HwShunt, Coverage::Whole)],
        )
    }

    /// The doctrine, as a test: traceability is a precondition. An untraceable
    /// outcome cannot be admitted for sealing at all — a signature over an
    /// unchecked claim is the most durable way to publish it.
    #[test]
    fn an_untraceable_outcome_cannot_be_sealed() {
        let t = OutcomeTrace::new(
            energy(1_000, Provenance::HwShunt, Coverage::Whole), true, vec![],
        );
        assert_eq!(
            t.admit(&[], None),
            Err(SealRefusal::NotTraceable(TraceError::Unbound))
        );
    }

    /// A frozen counter cannot be sealed as anything. This is the live defect
    /// shape: a busy window reporting nothing while the meter claims hardware.
    #[test]
    fn a_frozen_counter_cannot_be_sealed() {
        let t = sound();
        let dead = win(0, 400_000_000); // 400 ms claiming zero
        match t.admit(&[dead], Some(&env())) {
            Err(SealRefusal::PhysicallyRefuted { window_index, detail }) => {
                assert_eq!(window_index, 0);
                assert!(detail.contains("frozen counter"), "{detail}");
            }
            other => panic!("a dead counter must not seal: {other:?}"),
        }
    }

    /// Nor can a figure no part could have drawn.
    #[test]
    fn a_physically_impossible_figure_cannot_be_sealed() {
        let t = sound();
        let absurd = win(10_000_000, 1_000_000);
        assert!(matches!(
            t.admit(&[absurd], Some(&env())),
            Err(SealRefusal::PhysicallyRefuted { .. })
        ));
    }

    /// The grade is derived, never supplied. Claiming hardware over modelled
    /// evidence is refused rather than quietly downgraded: the caller has a
    /// bug, and writing the weaker grade silently would hide it.
    #[test]
    fn a_grade_the_evidence_does_not_support_is_refused() {
        let t = OutcomeTrace::new(
            energy(1_000, Provenance::HwShunt, Coverage::Whole),
            true,
            vec![act(b"a1", 300, Provenance::Estimator, Coverage::Whole)],
        );
        assert_eq!(
            t.admit(&[], None),
            Err(SealRefusal::GradeNotEarned {
                claimed: Provenance::HwShunt,
                floor: Provenance::Estimator
            })
        );
    }

    /// A sound trace is admitted, and what comes back carries the grade the
    /// evidence earned — so the sealer writes that instead of the claim.
    #[test]
    fn an_admitted_trace_carries_the_earned_grade_not_the_claimed_one() {
        let t = OutcomeTrace::new(
            energy(1_000, Provenance::ModelBased, Coverage::Whole),
            true,
            vec![act(b"a1", 300, Provenance::ModelBased, Coverage::Partial)],
        );
        let a = t.admit(&[], None).expect("admits");
        assert_eq!(a.earned_provenance(), Provenance::ModelBased);
        assert_eq!(
            a.earned_coverage(), Coverage::Partial,
            "one partial part makes the receipt partial"
        );
        assert_eq!(a.reconciliation().residual_uj, 700);
    }

    /// Claiming LESS than the evidence supports is allowed — under-claiming is
    /// always permitted, and the receipt still records the floor.
    #[test]
    fn under_claiming_is_permitted() {
        let t = OutcomeTrace::new(
            energy(1_000, Provenance::Estimator, Coverage::Whole),
            true,
            vec![act(b"a1", 300, Provenance::HwShunt, Coverage::Whole)],
        );
        let a = t.admit(&[], None).expect("under-claiming admits");
        assert_eq!(a.earned_provenance(), Provenance::Estimator, "the floor is the claim");
    }

    /// With no envelope supplied no physical check runs, and that is not a
    /// pass — the trace is admitted on its arithmetic alone, which is exactly
    /// what the absence of an envelope means.
    #[test]
    fn no_envelope_means_no_physical_claim_was_made() {
        let t = sound();
        let implausible = win(0, 400_000_000);
        assert!(t.admit(&[implausible], None).is_ok(), "arithmetic closes; physics unchecked");
        assert!(t.admit(&[win(0, 400_000_000)], Some(&env())).is_err(), "with an envelope it does not");
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn energy(uj: u64, p: Provenance, c: Coverage) -> Energy {
        Energy { measured_uj: Some(uj), estimated_uj: uj, provenance: p, coverage: c }
    }

    fn act(tag: &[u8], uj: u64, p: Provenance, c: Coverage) -> ActivityRef {
        ActivityRef::new(ContentId::of_bytes(tag), uj, p, c)
    }

    /// The seam this module closes: an outcome whose energy is traceable to
    /// nothing is refused, rather than published as a number.
    #[test]
    fn an_unbound_outcome_is_refused() {
        let t = OutcomeTrace::new(
            energy(1_000_000, Provenance::HwShunt, Coverage::Whole),
            true,
            vec![],
        );
        assert_eq!(t.reconcile(), Err(TraceError::Unbound));
    }

    /// The residual is the cost of being accountable — authorisation,
    /// attestation, verification, egress — which no operation receipt claims.
    /// It is named, not absorbed.
    #[test]
    fn the_residual_names_what_no_operation_claims() {
        let t = OutcomeTrace::new(
            energy(1_000_000, Provenance::HwShunt, Coverage::Whole),
            true,
            vec![
                act(b"a1", 400_000, Provenance::HwShunt, Coverage::Whole),
                act(b"a2", 350_000, Provenance::HwShunt, Coverage::Whole),
            ],
        );
        let r = t.reconcile().expect("reconciles");
        assert_eq!(r.accounted_uj, 750_000);
        assert_eq!(r.residual_uj, 250_000, "a quarter of the outcome is overhead");
        assert_eq!(r.activities, 2);
        // A quarter of a joule unattributed, expressed against the whole.
        assert_eq!(r.unattributed_ppm(t.total_uj()), Some(250_000));
    }

    /// Over-accounting is a finding, not a rounding error: the work is
    /// double-counted or an activity is bound to the wrong outcome.
    #[test]
    fn activities_claiming_more_than_the_outcome_are_refused() {
        let t = OutcomeTrace::new(
            energy(100, Provenance::HwShunt, Coverage::Whole),
            true,
            vec![act(b"a1", 90, Provenance::HwShunt, Coverage::Whole),
                 act(b"a2", 50, Provenance::HwShunt, Coverage::Whole)],
        );
        assert_eq!(
            t.reconcile(),
            Err(TraceError::OverAccounted { accounted_uj: 140, total_uj: 100 })
        );
    }

    /// A duplicated activity inflates the accounted figure and shrinks the
    /// residual — flattering in exactly the direction that matters, so it is
    /// caught before the sum.
    #[test]
    fn a_duplicated_activity_is_refused_before_it_can_flatter() {
        let dup = act(b"same", 100, Provenance::HwShunt, Coverage::Whole);
        let t = OutcomeTrace::new(
            energy(1_000, Provenance::HwShunt, Coverage::Whole),
            true,
            vec![dup.clone(), dup.clone()],
        );
        match t.reconcile() {
            Err(TraceError::DuplicateActivity { receipt }) => {
                assert_eq!(receipt, ContentId::of_bytes(b"same"));
            }
            other => panic!("a double-bound activity must be refused: {other:?}"),
        }
    }

    /// A chain is only as graded as its weakest link. One estimate makes the
    /// whole trace estimated — averaging would let a hardware reading launder
    /// a pile of models.
    #[test]
    fn provenance_takes_the_floor_never_the_average() {
        let t = OutcomeTrace::new(
            energy(1_000, Provenance::HwShunt, Coverage::Whole),
            true,
            vec![
                act(b"a1", 300, Provenance::HwShunt, Coverage::Whole),
                act(b"a2", 300, Provenance::Estimator, Coverage::Whole),
            ],
        );
        let r = t.reconcile().unwrap();
        assert_eq!(r.provenance_floor, Provenance::Estimator);
    }

    /// An unaccounted share does not become accounted for by sitting next to
    /// accounted ones.
    #[test]
    fn coverage_takes_the_floor_too() {
        let t = OutcomeTrace::new(
            energy(1_000, Provenance::HwShunt, Coverage::Whole),
            true,
            vec![
                act(b"a1", 300, Provenance::HwShunt, Coverage::Whole),
                act(b"a2", 300, Provenance::HwShunt, Coverage::Partial),
            ],
        );
        assert_eq!(t.reconcile().unwrap().coverage_floor, Coverage::Partial);
    }

    /// A trace whose operations exactly equal its outcome admits no overhead at
    /// all — for a gated, attested, receipt-emitting system that is itself
    /// worth a second look, so the residual reports zero rather than hiding it.
    #[test]
    fn a_zero_residual_is_reported_not_hidden() {
        let t = OutcomeTrace::new(
            energy(500, Provenance::HwShunt, Coverage::Whole),
            true,
            vec![act(b"a1", 500, Provenance::HwShunt, Coverage::Whole)],
        );
        let r = t.reconcile().unwrap();
        assert_eq!(r.residual_uj, 0);
        assert_eq!(r.unattributed_ppm(500), Some(0));
    }

    /// Energy spent on an outcome that did not complete is a different claim
    /// from energy spent on one that did; the anchor is carried, not dropped.
    #[test]
    fn the_outcome_anchor_survives_into_the_trace() {
        let t = OutcomeTrace::new(
            energy(900, Provenance::HwShunt, Coverage::Whole),
            false,
            vec![act(b"a1", 900, Provenance::HwShunt, Coverage::Whole)],
        );
        assert!(!t.completed, "the joules bought nothing, and the trace says so");
        assert!(t.reconcile().is_ok());
    }

    /// A ratio against nothing is not a figure.
    #[test]
    fn no_ratio_against_a_zero_total() {
        let t = OutcomeTrace::new(
            energy(0, Provenance::Estimator, Coverage::Whole),
            true,
            vec![act(b"a1", 0, Provenance::Estimator, Coverage::Whole)],
        );
        assert_eq!(t.reconcile().unwrap().unattributed_ppm(0), None);
    }
}

// ---------------------------------------------------------------------------
// Enforcement: a precondition, not a report
// ---------------------------------------------------------------------------

/// Why an outcome receipt must not be sealed.
///
/// §5 of the spec says JCP "makes it a precondition, not a report". Until this
/// existed, traceability was a report: [`crate::Efficiency::seal`] serialises
/// and signs whatever it is handed, so an untraceable outcome, a
/// double-counted activity or a physically impossible figure could all be
/// sealed, signed, and indistinguishable afterwards from a sound one. A
/// signature over an unchecked claim is the most durable way to publish it.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SealRefusal {
    /// The trace does not reconcile. Carries the reason.
    NotTraceable(TraceError),
    /// A window's figure is impossible for the part and duration — above the
    /// envelope, or below the floor a powered executing part must draw. The
    /// second is the shape a frozen counter takes, and §5's liveness rule
    /// exists because of it.
    PhysicallyRefuted { window_index: usize, detail: String },
    /// The receipt claims a hardware grade the evidence under it does not
    /// support. Refused rather than silently downgraded **in this direction**,
    /// because a caller asking to seal `HwShunt` over modelled windows has a
    /// bug, not a preference.
    GradeNotEarned { claimed: Provenance, floor: Provenance },
}

impl core::fmt::Display for SealRefusal {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        match self {
            SealRefusal::NotTraceable(e) => write!(f, "not traceable: {e}"),
            SealRefusal::PhysicallyRefuted { window_index, detail } => {
                write!(f, "window {window_index} is physically refuted: {detail}")
            }
            SealRefusal::GradeNotEarned { claimed, floor } => write!(
                f,
                "receipt claims {claimed:?} but the evidence under it supports only \
                 {floor:?}; a signature would make the stronger claim permanent"
            ),
        }
    }
}

impl std::error::Error for SealRefusal {}

/// What a trace establishes once every precondition has held.
///
/// Construction is the proof: there is no way to build one except through
/// [`OutcomeTrace::admit`], so a function taking an `AdmittedTrace` knows the
/// checks ran rather than hoping the caller remembered. The same reason
/// `sandbox-attest` hands back a sealed run rather than a boolean.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AdmittedTrace {
    reconciliation: Reconciliation,
    /// The grade the evidence actually supports — **derived**, never the one
    /// the caller supplied. Written into the receipt in place of the claim, so
    /// aggregation cannot be the step at which a grade improves.
    earned_provenance: Provenance,
    earned_coverage: Coverage,
}

impl AdmittedTrace {
    pub fn reconciliation(&self) -> &Reconciliation {
        &self.reconciliation
    }
    /// The provenance the receipt is entitled to carry.
    pub fn earned_provenance(&self) -> Provenance {
        self.earned_provenance
    }
    /// The coverage the receipt is entitled to carry.
    pub fn earned_coverage(&self) -> Coverage {
        self.earned_coverage
    }
}

impl OutcomeTrace {
    /// Admit this trace for sealing, or refuse it.
    ///
    /// Three gates, in the order a verifier would apply them:
    ///
    /// 1. **It reconciles.** An unbound, duplicated or over-accounted trace is
    ///    refused — the arithmetic has to close before anything else matters.
    /// 2. **No window is physically impossible.** Checked against the part's
    ///    envelope when one is supplied. A figure above the burst ceiling or
    ///    below the idle floor is refused regardless of what the counter said,
    ///    because the counter is the thing in question.
    /// 3. **The grade is earned, not asserted.** The receipt may carry no
    ///    stronger provenance than the floor across its parts. A caller asking
    ///    for more is refused rather than quietly downgraded: asking to seal
    ///    `HwShunt` over `Estimator` evidence is a bug in the caller, and
    ///    silently writing the weaker grade would hide it.
    ///
    /// The returned [`AdmittedTrace`] carries the *derived* grade, so the
    /// sealer writes what the evidence supports instead of what it was handed.
    pub fn admit(
        &self,
        windows: &[crate::dynamics::EnergyWindow],
        envelope: Option<&crate::dynamics::PowerEnvelope>,
    ) -> Result<AdmittedTrace, SealRefusal> {
        use crate::dynamics::PhysicalVerdict;

        let reconciliation = self.reconcile().map_err(SealRefusal::NotTraceable)?;

        if let Some(env) = envelope {
            for (i, w) in windows.iter().enumerate() {
                match env.check(w) {
                    PhysicalVerdict::RefutedAbove { claimed_uj, ceiling_uj } => {
                        return Err(SealRefusal::PhysicallyRefuted {
                            window_index: i,
                            detail: format!(
                                "{claimed_uj} uJ exceeds the {ceiling_uj} uJ the part \
                                 could draw in {} ns",
                                w.duration_ns
                            ),
                        })
                    }
                    PhysicalVerdict::RefutedBelow { claimed_uj, floor_uj } => {
                        return Err(SealRefusal::PhysicallyRefuted {
                            window_index: i,
                            detail: format!(
                                "{claimed_uj} uJ is below the {floor_uj} uJ a powered, \
                                 executing part must draw in {} ns — the shape a frozen \
                                 counter takes",
                                w.duration_ns
                            ),
                        })
                    }
                    // Inside the envelope, or unboundable. Neither is a
                    // verification; both are permitted to seal, because the
                    // envelope only ever refutes.
                    _ => {}
                }
            }
        }

        if self.total.provenance != reconciliation.provenance_floor
            && stronger(self.total.provenance, reconciliation.provenance_floor)
        {
            return Err(SealRefusal::GradeNotEarned {
                claimed: self.total.provenance,
                floor: reconciliation.provenance_floor,
            });
        }

        Ok(AdmittedTrace {
            earned_provenance: reconciliation.provenance_floor,
            earned_coverage: reconciliation.coverage_floor,
            reconciliation,
        })
    }
}

/// Whether `a` claims a stronger acquisition class than `b`.
fn stronger(a: Provenance, b: Provenance) -> bool {
    fn rank(p: Provenance) -> u8 {
        match p {
            Provenance::HwShunt => 2,
            Provenance::ModelBased => 1,
            Provenance::Estimator => 0,
        }
    }
    rank(a) > rank(b)
}
