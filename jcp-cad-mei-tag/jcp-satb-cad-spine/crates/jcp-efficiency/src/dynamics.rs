//! Time-resolved energy, and the honest limit of what a deviation establishes.
//!
//! # Why a total is not enough
//!
//! [`crate::trace`] reconciles an outcome against its activities and names the
//! residual. That is conservation, and it is static: one scalar per outcome.
//! Real compute is not static. The same declared work costs different joules on
//! a throttled part, a contended host, a cold cache, or a frequency-scaled
//! core — and a single total cannot tell any of those apart from each other,
//! let alone from interference.
//!
//! So energy has to be carried as a **series**, each window graded on its own,
//! and compared against a baseline that says where it was measured.
//!
//! # The thing this module refuses to do
//!
//! There is no `Malicious` variant in [`Deviation`], and that is the most
//! important line in this file.
//!
//! Energy does not carry intent. A deviation says the joules did not match the
//! expectation; it cannot say why, and on a stack whose normal behaviour has
//! never been charted it cannot even say the expectation was right. A type with
//! a `Malicious` arm would be used — some caller would map `Unexplained` onto
//! it, a dashboard would colour it red, and a number with no evidential basis
//! would start informing decisions about people. That is the same failure as a
//! prover returning `Proved` because a stand-in said so, moved into security.
//!
//! What this module produces is a **partition**: attributable, explained by a
//! named cause *with evidence*, unexplained, or unresolvable. `Unexplained` is
//! a request for a look, not a verdict. The difference between interference and
//! an uncharted-but-legitimate stack is a question evidence answers, and this
//! makes that question askable instead of pre-answering it wrongly.
//!
//! # Explaining requires evidence, not a label
//!
//! [`OperationalCause`] never explains a deviation on its own. Each cause
//! carries a content-id for the reading that supports it — a thermal sample, a
//! co-tenancy attestation, a cache-state record. A cause asserted without
//! evidence leaves the window `Unexplained`, because otherwise "explained"
//! becomes the laundering channel: anything inconvenient gets labelled
//! `ThermalThrottle` and disappears.
//!
//! # Absence of detection is not absence
//!
//! A window is a sampling interval, and a phenomenon shorter than one window is
//! invisible to it. That case is [`Deviation::Unresolvable`], never
//! `WithinBand`. Reporting "nothing found" at a resolution that could not have
//! found it is the quietest way to be wrong, and the one an auditor is least
//! able to catch.

use serde::{Deserialize, Serialize};

use jcp_schema::{ContentId, Coverage, Provenance};

/// One time-resolved energy sample.
///
/// Provenance and coverage are per-window on purpose. Counters do not have
/// uniform resolution: a host may expose a package counter continuously and an
/// accelerator counter only while a queue is active, so the same trace can be
/// `HwShunt`/`Whole` in one window and `Estimator`/`Partial` in the next. A
/// single grade for the series would be a grade for its best window.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct EnergyWindow {
    /// Monotonic start, nanoseconds.
    pub started_ns: u64,
    /// Window length, nanoseconds. This is the trace's resolution floor.
    pub duration_ns: u64,
    /// Energy attributed to this window.
    pub joules_uj: u64,
    /// How this window's figure was acquired.
    pub provenance: Provenance,
    /// How much of the window's work the figure accounts for.
    pub coverage: Coverage,
    /// The operation this window is declared to cover, when one is named.
    pub declared_work: Option<ContentId>,
}

/// Where a baseline was measured, so a reader can tell whether it applies.
///
/// The same discipline as `mesh-router`'s `Calibration`: an expectation is a
/// fit, and a fit is only a fit somewhere. A baseline taken on different
/// silicon, at a different occupancy, or before a toolchain change is not
/// wrong — it is *inapplicable*, and the two must not be confused, because
/// comparing against an inapplicable baseline manufactures deviations that say
/// nothing about the workload.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Baseline {
    /// The expected energy for one window of this shape, in µJ.
    pub expected_uj: u64,
    /// Half-width of the accepted band, in µJ. Deviation is measured against
    /// the band, not the point: a point expectation would flag every window.
    pub band_uj: u64,
    /// Where the expectation came from — a harness run id, a receipt
    /// content-id, a document. Names the measurement; does not substitute for
    /// it.
    pub source: String,
    /// The window length the baseline was fit at. A baseline fit at a coarser
    /// resolution than the trace cannot speak to the trace's windows.
    pub fit_window_ns: u64,
    /// Whether the operator has declared this baseline applicable to the host
    /// and workload being traced. Defaults to false at construction: an
    /// undeclared baseline is treated as inapplicable, so forgetting
    /// under-claims rather than manufacturing findings.
    pub declared_applicable: bool,
}

impl Baseline {
    /// A baseline that does not yet claim to apply anywhere.
    pub fn new(expected_uj: u64, band_uj: u64, source: impl Into<String>, fit_window_ns: u64) -> Self {
        Baseline {
            expected_uj,
            band_uj,
            source: source.into(),
            fit_window_ns,
            declared_applicable: false,
        }
    }

    /// Declare this baseline applicable to the host and workload being traced.
    /// An explicit act, because it is the step that turns a number from
    /// somewhere else into a yardstick here.
    pub fn declared_applicable(mut self) -> Self {
        self.declared_applicable = true;
        self
    }
}

/// A named, evidenced reason a window's energy departed from expectation.
///
/// Every variant carries the content-id of a reading that supports it. The
/// evidence is the whole point: without it a cause is a label, and labels
/// explain anything.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum OperationalCause {
    /// The part was thermally limited. Evidence: a thermal sample covering the
    /// window.
    ThermalThrottle { reading: ContentId },
    /// The host was shared with work this trace does not account for.
    /// Evidence: a co-tenancy or utilisation record.
    ContendedHost { reading: ContentId },
    /// First execution: cold caches, JIT or kernel compilation. Evidence: a
    /// record showing this was a first run.
    ColdStart { reading: ContentId },
    /// The core ran at a different operating point than the baseline's.
    /// Evidence: a frequency or power-state sample.
    FrequencyScaled { reading: ContentId },
    /// The meter does not cover part of this window's work, so the figure is
    /// structurally low. Evidence: the coverage record.
    MeterCoverageGap { reading: ContentId },
}

impl OperationalCause {
    /// The reading that supports this cause.
    pub fn evidence(&self) -> ContentId {
        match self {
            OperationalCause::ThermalThrottle { reading }
            | OperationalCause::ContendedHost { reading }
            | OperationalCause::ColdStart { reading }
            | OperationalCause::FrequencyScaled { reading }
            | OperationalCause::MeterCoverageGap { reading } => *reading,
        }
    }

    /// The §-style token for this cause, for a receipt's claim vocabulary.
    pub fn token(&self) -> &'static str {
        match self {
            OperationalCause::ThermalThrottle { .. } => "thermal_throttle",
            OperationalCause::ContendedHost { .. } => "contended_host",
            OperationalCause::ColdStart { .. } => "cold_start",
            OperationalCause::FrequencyScaled { .. } => "frequency_scaled",
            OperationalCause::MeterCoverageGap { .. } => "meter_coverage_gap",
        }
    }
}

/// What one window's energy establishes against its baseline.
///
/// **There is deliberately no `Malicious` variant.** See the module docs: a
/// deviation cannot carry intent, and a type that offered that arm would have it
/// used.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum Deviation {
    /// Inside the baseline's band. Says the window is unremarkable *at this
    /// resolution and against this baseline* — nothing more.
    WithinBand,
    /// Outside the band, and a named cause with evidence accounts for it.
    Explained { cause: OperationalCause, excess_uj: i128 },
    /// Outside the band with no evidenced cause. **This is not a finding of
    /// wrongdoing.** It is the set a human should look at, and on an uncharted
    /// stack it will often be the largest set — which is a statement about the
    /// stack's charting, not about the workload's honesty.
    Unexplained { excess_uj: i128 },
    /// The baseline does not apply here — undeclared, or fit at a resolution
    /// coarser than this window. No comparison is made, because comparing
    /// against an inapplicable baseline manufactures deviations.
    BaselineInapplicable { reason: &'static str },
    /// The window is longer than the phenomenon being asked about, so this
    /// window could not have shown it. Distinct from `WithinBand`: one is
    /// "looked and saw nothing", the other is "could not have seen it".
    Unresolvable { window_ns: u64, asked_ns: u64 },
}

impl EnergyWindow {
    /// Classify this window against a baseline.
    pub fn classify(&self, baseline: &Baseline) -> Deviation {
        if !baseline.declared_applicable {
            return Deviation::BaselineInapplicable {
                reason: "baseline not declared applicable to this host and workload",
            };
        }
        if baseline.fit_window_ns > self.duration_ns {
            return Deviation::BaselineInapplicable {
                reason: "baseline fit at a coarser window than this trace samples",
            };
        }
        let lo = baseline.expected_uj.saturating_sub(baseline.band_uj);
        let hi = baseline.expected_uj.saturating_add(baseline.band_uj);
        if self.joules_uj >= lo && self.joules_uj <= hi {
            return Deviation::WithinBand;
        }
        Deviation::Unexplained {
            excess_uj: i128::from(self.joules_uj) - i128::from(baseline.expected_uj),
        }
    }

    /// Classify, offering a cause. The cause is accepted only because it
    /// carries evidence; `None` leaves the window unexplained rather than
    /// quietly excused.
    pub fn classify_with(
        &self,
        baseline: &Baseline,
        cause: Option<OperationalCause>,
    ) -> Deviation {
        match (self.classify(baseline), cause) {
            (Deviation::Unexplained { excess_uj }, Some(cause)) => {
                Deviation::Explained { cause, excess_uj }
            }
            (other, _) => other,
        }
    }

    /// Whether this window could resolve a phenomenon of `asked_ns`.
    pub fn resolves(&self, asked_ns: u64) -> Deviation {
        if asked_ns < self.duration_ns {
            Deviation::Unresolvable { window_ns: self.duration_ns, asked_ns }
        } else {
            Deviation::WithinBand
        }
    }
}

/// The partition over a window series. Counts, never a score.
///
/// There is no single number here, and that is deliberate. A "risk score" would
/// collapse `unexplained` and `inapplicable` and `unresolvable` into one figure
/// that reads as confidence, when the three mean "look at this", "we have no
/// yardstick", and "we could not have seen it" — which call for completely
/// different responses.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct Partition {
    pub within_band: usize,
    pub explained: usize,
    pub unexplained: usize,
    pub baseline_inapplicable: usize,
    pub unresolvable: usize,
    /// Σ excess over the unexplained windows, signed.
    pub unexplained_excess_uj: i128,
    /// The weakest provenance across every window classified. `None` until a
    /// window has been folded in — an empty partition has no grade to report,
    /// and inventing one would be a claim about nothing.
    pub provenance_floor: Option<Provenance>,
}

impl Partition {
    /// Fold one classified window in.
    pub fn record(&mut self, window: &EnergyWindow, d: &Deviation) {
        match d {
            Deviation::WithinBand => self.within_band += 1,
            Deviation::Explained { .. } => self.explained += 1,
            Deviation::Unexplained { excess_uj } => {
                self.unexplained += 1;
                self.unexplained_excess_uj += *excess_uj;
            }
            Deviation::BaselineInapplicable { .. } => self.baseline_inapplicable += 1,
            Deviation::Unresolvable { .. } => self.unresolvable += 1,
        }
        self.provenance_floor = Some(match self.provenance_floor {
            None => window.provenance,
            Some(have) => weakest(have, window.provenance),
        });
    }

    /// How many windows were actually compared against an applicable baseline.
    ///
    /// The denominator that matters. A partition reporting zero unexplained
    /// windows out of a hundred means nothing if ninety-nine of them had no
    /// applicable baseline — and that is the shape most "nothing anomalous
    /// found" reports take on an uncharted stack.
    pub fn compared(&self) -> usize {
        self.within_band + self.explained + self.unexplained
    }

    /// Whether this partition supports saying anything at all about the series.
    ///
    /// `false` when nothing was compared. A report built on an empty comparison
    /// is not a quiet report, it is a vacuous one.
    pub fn is_substantive(&self) -> bool {
        self.compared() > 0
    }
}

fn weakest(a: Provenance, b: Provenance) -> Provenance {
    fn rank(p: Provenance) -> u8 {
        match p {
            Provenance::HwShunt => 2,
            Provenance::ModelBased => 1,
            Provenance::Estimator => 0,
        }
    }
    if rank(b) < rank(a) { b } else { a }
}

/// A granted energy budget against what the windows actually account for.
///
/// # Why fractions of a percent are detectable here and nowhere else
///
/// Everything in this family carries energy as **integer microjoules**, and the
/// sums are exact. That makes the detection floor a property of arithmetic
/// rather than of statistics: the smallest representable discrepancy is 1 µJ,
/// so against a budget of `N` µJ the floor is `1_000_000 / N` parts per
/// million. On a one-joule budget that is **1 ppm — one ten-thousandth of a
/// percent**. A drift of a fraction of a percent sits three orders of magnitude
/// above the floor, which is why it is not a subtle signal but an obvious one.
///
/// This is the part that does not survive the usual construction. Almost
/// everywhere in computing, an energy figure is *derived from a performance
/// proxy* — utilisation times a thermal design figure, tokens times a
/// coefficient, instructions times picojoules-per-op — and never measured. The
/// model error in such a figure is tens of percent. A fractional-percent drift
/// is then invisible by construction: it is far inside the error bar of the
/// estimator that produced the number, and no amount of resolution recovers it.
/// Deriving energy from performance does not merely lose accuracy; it destroys
/// the ability to notice that the books do not balance.
///
/// So the instrument is conservation, not anomaly detection. A band comparison
/// asks "is this unusual against a model of normal", which an uncharted stack
/// cannot answer. Conservation asks "do these joules fit anywhere", which needs
/// no model of normal — only exact arithmetic and a grant that said how many
/// were allowed. [`Provenance`] remains load-bearing throughout: a budget
/// reconciled against `Estimator` windows is reconciled against a model's
/// opinion, and the floor below is then fiction. The floor is real only to the
/// extent the windows were measured.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Budget {
    /// Microjoules the grant authorised.
    pub granted_uj: u64,
    /// Σ of the windows' energy.
    pub accounted_uj: u128,
    /// The weakest provenance across the windows that produced
    /// [`Self::accounted_uj`]. Carried because the detection floor is only as
    /// real as the measurement under it.
    pub provenance_floor: Option<Provenance>,
}

impl Budget {
    /// Reconcile a window series against a grant.
    pub fn reconcile(granted_uj: u64, windows: &[EnergyWindow]) -> Self {
        let accounted_uj: u128 = windows.iter().map(|w| u128::from(w.joules_uj)).sum();
        let provenance_floor = windows
            .iter()
            .map(|w| w.provenance)
            .reduce(weakest);
        Budget { granted_uj, accounted_uj, provenance_floor }
    }

    /// `accounted - granted`, signed. Positive is overspend; negative is energy
    /// the grant allowed that nothing claimed. Never clamped — both directions
    /// are findings, and the negative one is how unattributed work hides.
    pub fn drift_uj(&self) -> i128 {
        self.accounted_uj as i128 - i128::from(self.granted_uj)
    }

    /// The drift in parts per million of the grant. `None` for a zero grant: a
    /// ratio against nothing is not a figure.
    pub fn drift_ppm(&self) -> Option<i128> {
        if self.granted_uj == 0 {
            return None;
        }
        Some(self.drift_uj() * 1_000_000 / i128::from(self.granted_uj))
    }

    /// The smallest drift this budget can represent, in ppm — one microjoule
    /// expressed against the grant.
    ///
    /// Exact, not estimated. This is the number that says whether a given
    /// tolerance is even askable: a 0.1 % tolerance on a 1 mJ grant is 1 ppm of
    /// nothing useful, while on a 1 J grant it is a thousand times the floor.
    pub fn detectable_floor_ppm(&self) -> Option<u64> {
        if self.granted_uj == 0 {
            return None;
        }
        Some((1_000_000 / self.granted_uj).max(1))
    }

    /// Whether the observed drift is above this budget's representational floor.
    ///
    /// `false` means the books balance to the limit of what integers can say at
    /// this grant size — which is a real and bounded statement, unlike "no
    /// anomaly detected".
    pub fn drift_is_resolvable(&self) -> bool {
        match self.detectable_floor_ppm() {
            None => false,
            Some(floor) => self.drift_ppm().is_some_and(|d| d.unsigned_abs() >= u128::from(floor)),
        }
    }

    /// Whether the floor is a claim about measurement or about a model.
    ///
    /// A budget whose windows are `Estimator` has a floor that is arithmetically
    /// exact and physically meaningless: the estimator's own error dwarfs it.
    /// Reporting a 1 ppm floor over modelled windows would be the most precise
    /// way to mislead available here.
    pub fn floor_is_physical(&self) -> bool {
        matches!(self.provenance_floor, Some(Provenance::HwShunt))
    }
}

/// The physical envelope a part cannot leave, used to **refute** energy claims.
///
/// # Energy cannot be faked; the measurement of it can
///
/// The joules were spent. The heat left the die. That quantity is not
/// negotiable — but the *report* of it is exactly as corruptible as any other
/// report. A counter can be lied about, a figure can be fabricated, and a
/// `HwShunt` grade can be stamped on a number that came from nowhere. A meter
/// reading a frozen register while claiming hardware measurement is not a
/// hypothetical: it is a defect that ships.
///
/// So energy buys no immunity. What it buys is something no synthetic unit has:
/// **an external referent**. A token count, an API-call count, a
/// request-per-second figure can be any number whatsoever — nothing outside the
/// accounting system constrains them, so a fabricated one is indistinguishable
/// from a true one. A joule count is bounded by physics. The part has a power
/// envelope; the window has a duration; the product of the two is a ceiling no
/// honest figure can exceed, and the idle draw is a floor no powered part can
/// fall below while doing work.
///
/// That makes a faked energy figure *falsifiable*, which is a strictly weaker
/// and strictly more honest property than unfakeable.
///
/// # Refutes, never verifies
///
/// [`PhysicalVerdict`] has no `Verified` arm, for the same reason
/// `sandbox-attest`'s locality bound has none: passing a physical check means
/// the figure is *not impossible*, which is not the same as true. A figure
/// inside the envelope may still be fabricated, and the envelope will never
/// say so.
///
/// The bounds are deliberately **permissive** — peak burst rating for the
/// ceiling, not typical; absolute idle for the floor. A refutation from a
/// generous bound is unassailable: nobody can argue the part was merely running
/// hot. The same reason the locality check uses the speed of light in vacuum
/// rather than in fibre.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct PowerEnvelope {
    /// Absolute peak the part can draw, milliwatts. Use the burst rating, not
    /// the sustained or typical figure.
    pub peak_mw: u64,
    /// Floor the part cannot fall below while powered and executing,
    /// milliwatts. Zero disables the floor check for parts with no credible
    /// idle figure — honest, and it gives up the ability to catch a dead
    /// counter.
    pub idle_floor_mw: u64,
    /// Where these bounds come from — a datasheet, a measured sweep, a receipt.
    /// Names the source; does not substitute for it.
    pub source: String,
}

/// What a physical bound establishes about an energy figure.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum PhysicalVerdict {
    /// The figure is inside the envelope. **Not** a finding that it is correct:
    /// a fabricated figure inside the envelope passes this check, and must.
    NotRefuted { headroom_uj: u64 },
    /// The figure exceeds what the part could draw for the window's duration.
    /// Physically impossible, whatever the counter said.
    RefutedAbove { claimed_uj: u64, ceiling_uj: u64 },
    /// The figure is below what a powered, executing part must draw. This is
    /// the shape a dead or frozen counter takes: a busy window reporting
    /// implausibly little.
    RefutedBelow { claimed_uj: u64, floor_uj: u64 },
    /// The window has no duration, so no bound can be computed. Not a pass.
    Unboundable,
}

impl PowerEnvelope {
    /// The most the part could have spent over `duration_ns`, in µJ.
    ///
    /// mW × ns = 1e-3 W × 1e-9 s = 1e-12 J = 1e-6 µJ, so the product divides by
    /// 1e6 to land in microjoules. Computed in `u128` and saturating: a
    /// ceiling that overflowed to a small number would refute honest figures.
    pub fn ceiling_uj(&self, duration_ns: u64) -> u128 {
        u128::from(self.peak_mw).saturating_mul(u128::from(duration_ns)) / 1_000_000
    }

    /// The least a powered, executing part must have spent over `duration_ns`.
    pub fn floor_uj(&self, duration_ns: u64) -> u128 {
        u128::from(self.idle_floor_mw).saturating_mul(u128::from(duration_ns)) / 1_000_000
    }

    /// Try to refute a window's energy figure against physics.
    pub fn check(&self, window: &EnergyWindow) -> PhysicalVerdict {
        if window.duration_ns == 0 {
            return PhysicalVerdict::Unboundable;
        }
        let claimed = u128::from(window.joules_uj);
        let ceiling = self.ceiling_uj(window.duration_ns);
        if claimed > ceiling {
            return PhysicalVerdict::RefutedAbove {
                claimed_uj: window.joules_uj,
                ceiling_uj: ceiling.min(u128::from(u64::MAX)) as u64,
            };
        }
        let floor = self.floor_uj(window.duration_ns);
        if floor > 0 && claimed < floor {
            return PhysicalVerdict::RefutedBelow {
                claimed_uj: window.joules_uj,
                floor_uj: floor.min(u128::from(u64::MAX)) as u64,
            };
        }
        PhysicalVerdict::NotRefuted {
            headroom_uj: (ceiling - claimed).min(u128::from(u64::MAX)) as u64,
        }
    }
}

/// The character of a draw over time — the one thing here that cannot be faked.
///
/// # Why shape, and not the total
///
/// The quantity is physical and the measurement is forgeable, but **how** the
/// energy was consumed is the signature of what the silicon actually did. You
/// can report any number you like; you cannot make a part draw the profile of a
/// sustained matmul while it executes a memory-bound scan. The shape is a
/// property of the computation.
///
/// This closes a hole conservation alone leaves open. A total can be balanced
/// by padding — invent an operation, attribute the surplus joules to it, and the
/// books add up. The profile does not cooperate: a fictional operation
/// contributes no draw, so the observed character stops matching the declared
/// work mix.
///
/// # Why it survives an uncharted stack
///
/// This is the part that answers the hard question. On unfamiliar silicon the
/// *magnitudes* move — a different process node, a different power envelope, a
/// different memory hierarchy all shift the absolute joules, which is exactly
/// why a band baseline fails there. The *character* does not: a compute-bound
/// steady state is flat on any part, a cold start ramps on any part, a
/// queue-driven workload alternates on any part. So a declaration can be
/// refuted by shape on hardware nobody has ever profiled, without any model of
/// what normal looks like on it.
///
/// # Refutes a declaration, not a person
///
/// An inconsistency says the declared work did not produce this draw. It does
/// not say what did, and it never says intent. The declaration has to be made
/// **in advance** — classifying the shape first and then deciding what it must
/// have been is post-hoc pattern matching, which is the anomaly-detection trap
/// this module exists to avoid.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum DrawShape {
    /// Flat within tolerance. Compute-bound steady state.
    Sustained,
    /// Rising then settling. Cold caches, kernel or JIT compilation, page-in.
    Ramping,
    /// Alternating high and low. Queue-driven, memory-bound, or I/O-gated.
    Bursty,
    /// At or near the floor throughout. The part was not doing the declared
    /// work — or the counter is dead, which looks identical from here and is
    /// why [`PowerEnvelope::check`] is the companion test.
    Idle,
}

/// What comparing a declared shape against an observed one establishes.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum ShapeVerdict {
    /// Observed character matches what was declared. Not a finding of honesty:
    /// a different workload of the same character also matches.
    Consistent { shape: DrawShape },
    /// The declared work did not produce this draw. A refutation of the
    /// declaration — not an attribution of cause, and never of intent.
    Inconsistent { declared: DrawShape, observed: DrawShape },
    /// Too few windows to speak to character. Three is the minimum at which
    /// flat, rising and alternating are distinguishable at all; fewer is
    /// `Unresolvable`, never `Consistent`.
    Unresolvable { windows: usize },
}

/// Classify the character of a window series.
///
/// Integer arithmetic throughout, in µJ. `idle_floor_uj` is the per-window
/// floor from the [`PowerEnvelope`]; a series at or under it is `Idle`
/// regardless of its variation.
pub fn observe_shape(windows: &[EnergyWindow], idle_floor_uj: u64) -> Option<DrawShape> {
    if windows.len() < 3 {
        return None;
    }
    let v: Vec<u64> = windows.iter().map(|w| w.joules_uj).collect();
    let n = v.len() as u128;
    let sum: u128 = v.iter().map(|&x| u128::from(x)).sum();
    let mean = sum / n;

    if mean <= u128::from(idle_floor_uj) {
        return Some(DrawShape::Idle);
    }

    // Mean absolute deviation as a permille of the mean — integer, no floats,
    // so the classification is reproducible rather than platform-dependent.
    let mad: u128 = v
        .iter()
        .map(|&x| u128::from(x).abs_diff(mean))
        .sum::<u128>()
        / n;
    let spread_permille = mad.checked_mul(1000).and_then(|m| m.checked_div(mean)).unwrap_or(0);

    // Flat enough to be one steady state.
    if spread_permille <= 100 {
        return Some(DrawShape::Sustained);
    }

    // Rising: the second half's mean clearly exceeds the first half's, and the
    // series does not swing back and forth.
    let half = v.len() / 2;
    let first: u128 = v[..half].iter().map(|&x| u128::from(x)).sum::<u128>() / half as u128;
    let last: u128 =
        v[v.len() - half..].iter().map(|&x| u128::from(x)).sum::<u128>() / half as u128;
    let direction_changes = v
        .windows(3)
        .filter(|w| (w[1] > w[0]) != (w[2] > w[1]))
        .count();
    if last > first + first / 4 && direction_changes * 4 < v.len() {
        return Some(DrawShape::Ramping);
    }

    Some(DrawShape::Bursty)
}

/// Compare a shape declared in advance against the series actually observed.
pub fn check_shape(
    declared: DrawShape,
    windows: &[EnergyWindow],
    idle_floor_uj: u64,
) -> ShapeVerdict {
    match observe_shape(windows, idle_floor_uj) {
        None => ShapeVerdict::Unresolvable { windows: windows.len() },
        Some(observed) if observed == declared => ShapeVerdict::Consistent { shape: observed },
        Some(observed) => ShapeVerdict::Inconsistent { declared, observed },
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn win(started_ns: u64, joules_uj: u64) -> EnergyWindow {
        EnergyWindow {
            started_ns,
            duration_ns: 1_000_000, // 1 ms
            joules_uj,
            provenance: Provenance::HwShunt,
            coverage: Coverage::Whole,
            declared_work: None,
        }
    }

    fn series(vals: &[u64]) -> Vec<EnergyWindow> {
        vals.iter().enumerate().map(|(i, &v)| win(i as u64 * 1_000_000, v)).collect()
    }

    /// The claim this whole module rests on, stated as a test: fractions of a
    /// percent are detectable because the arithmetic is exact integers.
    #[test]
    fn a_fractional_percent_drift_is_three_orders_above_the_floor() {
        // A 1 J grant, overspent by 0.5 % — 5 mJ.
        let granted = 1_000_000u64; // 1 J in µJ
        let b = Budget {
            granted_uj: granted,
            accounted_uj: u128::from(granted) + 5_000,
            provenance_floor: Some(Provenance::HwShunt),
        };
        assert_eq!(b.drift_ppm(), Some(5_000), "0.5 % is 5000 ppm");
        assert_eq!(b.detectable_floor_ppm(), Some(1), "1 µJ of 1 J is 1 ppm");
        assert!(b.drift_is_resolvable());
        assert!(b.floor_is_physical(), "and the floor means something: measured windows");
    }

    /// The floor is arithmetic, not physics, when the windows are modelled.
    /// Reporting 1 ppm over an estimator's output would be the most precise way
    /// to mislead available here.
    #[test]
    fn a_modelled_budget_has_an_exact_but_meaningless_floor() {
        let b = Budget {
            granted_uj: 1_000_000,
            accounted_uj: 1_000_005,
            provenance_floor: Some(Provenance::Estimator),
        };
        assert_eq!(b.detectable_floor_ppm(), Some(1), "arithmetically exact");
        assert!(!b.floor_is_physical(), "and physically meaningless — say so");
    }

    /// Underspend is a finding too: energy the grant allowed that nothing
    /// claimed is how unattributed work hides.
    #[test]
    fn drift_is_signed_in_both_directions() {
        let under = Budget::reconcile(1_000_000, &series(&[100_000, 100_000, 100_000]));
        assert!(under.drift_uj() < 0, "300 mJ claimed against a 1 J grant");
        assert_eq!(under.drift_ppm(), Some(-700_000));
        assert_eq!(Budget::reconcile(0, &series(&[1, 2, 3])).drift_ppm(), None);
    }

    /// The physical floor refutes a dead counter. This is not hypothetical —
    /// it is the shape of a real defect: a busy window whose counter is frozen
    /// reports implausibly little while the meter still claims hardware.
    #[test]
    fn the_physical_floor_refutes_a_frozen_counter() {
        let env = PowerEnvelope {
            peak_mw: 60_000,     // 60 W burst — deliberately generous
            idle_floor_mw: 1_000, // 1 W floor while executing
            source: "datasheet burst rating".into(),
        };
        // A 400 ms busy window reporting zero.
        let dead = EnergyWindow { duration_ns: 400_000_000, joules_uj: 0, ..win(0, 0) };
        match env.check(&dead) {
            PhysicalVerdict::RefutedBelow { claimed_uj, floor_uj } => {
                assert_eq!(claimed_uj, 0);
                assert_eq!(floor_uj, 400_000, "1 W for 400 ms is 400 mJ");
            }
            other => panic!("a frozen counter must be refutable: {other:?}"),
        }
    }

    /// And the ceiling refutes a fabricated figure no part could have drawn.
    #[test]
    fn the_ceiling_refutes_a_physically_impossible_figure() {
        let env = PowerEnvelope {
            peak_mw: 60_000,
            idle_floor_mw: 0,
            source: "burst rating".into(),
        };
        let absurd = EnergyWindow { duration_ns: 1_000_000, joules_uj: 10_000_000, ..win(0, 0) };
        assert!(matches!(env.check(&absurd), PhysicalVerdict::RefutedAbove { .. }));

        // A plausible figure is NOT refuted — and that is not a finding of
        // correctness. There is no `Verified` arm, deliberately.
        let ok = EnergyWindow { duration_ns: 1_000_000, joules_uj: 30_000, ..win(0, 0) };
        assert!(matches!(env.check(&ok), PhysicalVerdict::NotRefuted { .. }));
    }

    /// A zero-duration window yields no bound. Not a pass.
    #[test]
    fn an_instant_window_is_unboundable_not_clean() {
        let env = PowerEnvelope { peak_mw: 1, idle_floor_mw: 1, source: "x".into() };
        let instant = EnergyWindow { duration_ns: 0, joules_uj: 999, ..win(0, 0) };
        assert_eq!(env.check(&instant), PhysicalVerdict::Unboundable);
    }

    /// The hole conservation leaves open: a total balanced by padding. The
    /// shape does not cooperate — a fictional operation contributes no draw, so
    /// the declared character stops matching.
    #[test]
    fn shape_catches_a_total_balanced_by_padding() {
        // Declared: a sustained compute-bound run.
        // Observed: a short burst and then nothing, padded to the same total.
        let padded = series(&[300_000, 10, 10, 10, 10, 10]);
        match check_shape(DrawShape::Sustained, &padded, 100) {
            ShapeVerdict::Inconsistent { declared, observed } => {
                assert_eq!(declared, DrawShape::Sustained);
                assert_ne!(observed, DrawShape::Sustained);
            }
            other => panic!("padding must not read as sustained: {other:?}"),
        }
    }

    /// Character survives a change of scale, which is why this works on silicon
    /// nobody has profiled: the magnitudes move, the shape does not.
    #[test]
    fn character_is_scale_invariant() {
        let small = series(&[1_000, 1_020, 980, 1_010, 990, 1_000]);
        let large: Vec<u64> = [1_000u64, 1_020, 980, 1_010, 990, 1_000]
            .iter()
            .map(|v| v * 37)
            .collect();
        assert_eq!(observe_shape(&small, 10), Some(DrawShape::Sustained));
        assert_eq!(observe_shape(&series(&large), 10), Some(DrawShape::Sustained));
    }

    /// Ramping is distinguishable from alternating, and both from flat.
    #[test]
    fn the_three_characters_are_distinguishable() {
        assert_eq!(
            observe_shape(&series(&[100, 400, 700, 1_000, 1_100, 1_120]), 10),
            Some(DrawShape::Ramping)
        );
        assert_eq!(
            observe_shape(&series(&[100, 2_000, 100, 2_000, 100, 2_000]), 10),
            Some(DrawShape::Bursty)
        );
        assert_eq!(
            observe_shape(&series(&[1_000, 1_000, 1_000, 1_000]), 10),
            Some(DrawShape::Sustained)
        );
    }

    /// Below three windows, character is unresolvable — never "consistent".
    /// Reporting agreement at a resolution that could not disagree is the
    /// quietest way to be wrong.
    #[test]
    fn two_windows_cannot_speak_to_character() {
        assert_eq!(
            check_shape(DrawShape::Sustained, &series(&[1_000, 1_000]), 10),
            ShapeVerdict::Unresolvable { windows: 2 }
        );
        assert_eq!(observe_shape(&series(&[1, 2]), 0), None);
    }

    /// An undeclared baseline makes no comparison. Forgetting to declare must
    /// not manufacture findings.
    #[test]
    fn an_undeclared_baseline_refuses_to_compare() {
        let w = win(0, 5_000);
        let b = Baseline::new(1_000, 100, "harness:run-1", 1_000_000);
        assert!(matches!(w.classify(&b), Deviation::BaselineInapplicable { .. }));
        // Declared, and now the window is outside the band.
        let b = b.declared_applicable();
        assert!(matches!(w.classify(&b), Deviation::Unexplained { .. }));
    }

    /// A baseline fit at a coarser window than the trace samples cannot speak
    /// to the trace's windows.
    #[test]
    fn a_coarser_baseline_does_not_apply_to_finer_windows() {
        let w = win(0, 5_000); // 1 ms window
        let b = Baseline::new(1_000, 100, "harness", 10_000_000).declared_applicable();
        assert!(matches!(w.classify(&b), Deviation::BaselineInapplicable { .. }));
    }

    /// A cause explains a deviation only because it carries evidence. Without
    /// one the window stays unexplained rather than quietly excused.
    #[test]
    fn a_cause_without_evidence_does_not_explain() {
        let w = win(0, 5_000);
        let b = Baseline::new(1_000, 100, "harness", 1_000).declared_applicable();
        assert!(matches!(w.classify_with(&b, None), Deviation::Unexplained { .. }));

        let cause = OperationalCause::ThermalThrottle { reading: ContentId::of_bytes(b"thermal") };
        match w.classify_with(&b, Some(cause.clone())) {
            Deviation::Explained { cause: got, .. } => {
                assert_eq!(got.token(), "thermal_throttle");
                assert_eq!(got.evidence(), ContentId::of_bytes(b"thermal"));
            }
            other => panic!("an evidenced cause explains: {other:?}"),
        }
    }

    /// The denominator that matters: zero unexplained windows means nothing if
    /// nothing was compared.
    #[test]
    fn a_partition_that_compared_nothing_is_vacuous_not_clean() {
        let mut p = Partition::default();
        let w = win(0, 5_000);
        let undeclared = Baseline::new(1_000, 100, "harness", 1_000);
        for _ in 0..99 {
            p.record(&w, &w.classify(&undeclared));
        }
        assert_eq!(p.unexplained, 0, "nothing was flagged");
        assert_eq!(p.compared(), 0, "because nothing was compared");
        assert!(!p.is_substantive(), "so the partition supports no claim");
        assert_eq!(p.baseline_inapplicable, 99);
        assert_eq!(p.provenance_floor, Some(Provenance::HwShunt));
    }

    /// There is no `Malicious` verdict, and that is the load-bearing absence.
    /// Unexplained is a request for a look.
    #[test]
    fn unexplained_is_not_a_verdict_about_intent() {
        let w = win(0, 50_000);
        let b = Baseline::new(1_000, 100, "harness", 1_000).declared_applicable();
        let d = w.classify(&b);
        match d {
            Deviation::Unexplained { excess_uj } => assert_eq!(excess_uj, 49_000),
            other => panic!("expected unexplained: {other:?}"),
        }
        // The partition counts it; it produces no score, and there is no arm
        // anywhere in this module that names intent.
        let mut p = Partition::default();
        p.record(&w, &d);
        assert_eq!(p.unexplained, 1);
        assert_eq!(p.unexplained_excess_uj, 49_000);
    }
}
