//! The energy-efficiency spec for agentic work, surfaced as a sealed receipt.
//!
//! The dark-factory race (autonomous agents planning, writing, testing, shipping)
//! is hitting an economics wall: agentic coding burns ~1000× the tokens of a chat,
//! bills explode, and a large share of agentic projects get cancelled for
//! cost/unclear-value. The metrics the field reaches for — cost per token, joules
//! per token — are **rates**, and a rate can't tell you whether the spend bought a
//! *result*. That's the gap this closes.
//!
//! An [`Efficiency`] measurement carries the four figures that matter, sealed
//! against an **outcome anchor** (`completed` + a verdict). The anchor is not
//! this crate's invention — goal-denominated energy accounting is a live line of
//! work (see `MAPPING.md` §0) — but a signed, provenance-graded receipt carrying
//! one is what `efficiency/1` is:
//!
//! 1. **joules per accepted token** — measured µJ at [honest provenance], not a
//!    vendor estimate.
//! 2. **tokens per second** — real throughput ([`Efficiency::tokens_per_sec`]).
//! 3. **value per token** — value delivered ÷ tokens, in micro-USD (optional; a
//!    value figure is never invented).
//! 4. **tokens / joules / dollars per COMPLETED, VERIFIED unit** — the whole spend
//!    to reach a done, tested result. A measurement with `completed = false` is
//!    spend that bought *nothing*; the receipt makes that waste explicit rather
//!    than letting a low "cost per token" hide it.
//!
//! Each measurement seals as an **`efficiency/1`** JCR-1 receipt (COSE_Sign1 /
//! Ed25519), hash-chained, reusing the family envelope — no new crypto. Only
//! integers and strings are sealed (JCR-1 forbids bools and floats): `completed` is
//! `0`/`1`, energy is integer microjoules, and the rate figures are recomputed from
//! the sealed inputs on read. [`aggregate`] then splits value-delivered from total
//! spend across a chain of receipts — the honest efficiency ledger a "cost per
//! token" number can't produce.
//!
//! [honest provenance]: jcp_schema::Provenance

use ed25519_dalek::SigningKey;
use jcp_receipt::jcr1;
use jcp_schema::{ContentId, Coverage, Energy, Provenance};

pub mod avoided;
/// Energy traceability across operation, activity and outcome.
pub mod trace;
/// Time-resolved energy and the limits of what a deviation establishes.
pub mod dynamics;
pub mod training;
use serde_json::{json, Value};

/// One efficiency measurement over a unit of agentic work.
#[derive(Clone, Debug)]
pub struct Efficiency {
    /// The unit of work this measures (a task / project id).
    pub task: String,
    /// Whether the unit reached a **verified, done** result — the outcome anchor.
    /// `false` means the tokens/joules below bought nothing.
    pub completed: bool,
    /// A short verdict label for the outcome (e.g. `tests-pass`, `gate-failed`).
    pub verdict: String,
    /// Input (prompt / context) tokens.
    pub tokens_in: u64,
    /// Accepted output tokens.
    pub tokens_out: u64,
    /// Total energy over the whole unit (every tier), at honest provenance.
    pub energy: Energy,
    /// Wall-clock nanoseconds for the unit — the denominator for tokens/second.
    pub wall_ns: u64,
    /// Value delivered, micro-USD. `None` leaves value/token unstated — a value
    /// figure is never invented.
    pub value_uusd: Option<u64>,
    /// A hex content-id commitment to an external **energy attestation** — the raw
    /// attestation-report bytes produced by the attestation layer
    /// (`sandbox-tee::energy`), which binds this energy figure to a TEE report.
    /// `None` = the figure is signed but its counter is unattested (today's
    /// default). Sealing the commitment binds the receipt to the attestation: swap
    /// the attestation and the id no longer matches. The **trust level**
    /// (integrity-attested vs physically-rooted) is deliberately *not* stored here —
    /// it is derived by verifying the referenced attestation, never asserted in the
    /// receipt. See [`Efficiency::with_energy_attestation`].
    pub energy_attestation: Option<String>,
}

impl Efficiency {
    /// Total tokens the unit consumed (in + out) — the "tokens per project" figure
    /// when `completed`, or the tokens *wasted* when not.
    pub fn tokens_total(&self) -> u64 {
        self.tokens_in.saturating_add(self.tokens_out)
    }

    /// Microjoules per accepted output token — the headline energy figure, matching
    /// the family's `uj_per_accepted_token` convention: `None` when no tokens were
    /// accepted, because the division is undefined then.
    ///
    /// It is not `0`. This is a cost-per-result figure, so `0` is its *optimum* —
    /// returning it for an uncomputable ratio reported the worst outcome (spend
    /// that bought nothing, `completed: false`) as the best one, and the figure is
    /// sealed and read straight back out rather than recomputed. `mesh/SPEC.md`
    /// §6 states the family convention this matches: "omitted when no tokens were
    /// accepted".
    ///
    /// Also `None` for a `Partial` figure. The headline is the unit's energy
    /// per token, a ratio of a task total, and a `Partial` figure MUST NOT be
    /// presented as one (jcp SPEC §5.2). A GPU-only reading divided by the
    /// tokens is not what the unit cost per token, and not a bound on it
    /// either: a partial figure can be short of the work or over it. The
    /// receipt seals `energy_uj` with `energy_coverage` instead, so a reader
    /// still sees what was measured and how much of the work it covers.
    pub fn uj_per_accepted_token(&self) -> Option<u64> {
        if !self.energy.is_whole() {
            return None;
        }
        self.energy.uj().checked_div(self.tokens_out)
    }

    /// Accepted tokens per second — real decode throughput. `0.0` if no time
    /// elapsed. (Derived from the sealed integers; never sealed as a float.)
    pub fn tokens_per_sec(&self) -> f64 {
        if self.wall_ns == 0 {
            0.0
        } else {
            self.tokens_out as f64 / (self.wall_ns as f64 / 1e9)
        }
    }

    /// Micro-USD of value per accepted token — economic efficiency — when a value
    /// figure is given. `None` otherwise (never invented).
    pub fn uusd_per_accepted_token(&self) -> Option<u64> {
        // `and_then`, not `map(... .unwrap_or(0))`: with no accepted tokens the
        // ratio is undefined, and this function's contract is that a value figure
        // is never invented.
        self.value_uusd.and_then(|v| v.checked_div(self.tokens_out))
    }

    /// Commit this measurement to an external energy attestation — the raw report
    /// bytes from the attestation layer (`sandbox-tee::energy`). The receipt seals
    /// the attestation's content id, binding this energy figure to it.
    ///
    /// The composed verification a relying party runs: (1) [`verify`] this receipt;
    /// (2) resolve the attestation and check its content id equals this commitment;
    /// (3) verify the attestation via the attestation layer to derive the honest
    /// trust level (`IntegrityAttested` / `PhysicallyRooted`); (4) confirm the
    /// attested energy equals `energy_uj`. The receipt commits; the attestation
    /// layer adjudicates trust — the receipt never asserts a level it cannot prove.
    pub fn with_energy_attestation(mut self, attestation_report: &[u8]) -> Self {
        self.energy_attestation = Some(ContentId::of_bytes(attestation_report).to_hex());
        self
    }

    /// Seal this measurement as an `efficiency/1` receipt chained after `prev`
    /// (`ContentId([0;32])` for the genesis). Returns the sealed envelope; its
    /// content id is the next entry's `prev`.
    pub fn seal(&self, seq: u64, prev: &ContentId, steward_sk: &SigningKey, steward: &str) -> Vec<u8> {
        let wire = self.wire(seq, prev, steward);
        let core = jcr1::signed_core_bytes(&wire).expect("efficiency wire is a JCR-1 object");
        jcr1::cose_sign1_envelope(&core, steward_sk, steward)
    }

    /// The payload [`Self::seal`] signs, as JSON: what a verifier reads back
    /// with [`read_payload`] once the signature holds. Published conformance
    /// vectors are built from it.
    pub fn payload(&self, seq: u64, prev: &ContentId, steward: &str) -> Value {
        self.wire(seq, prev, steward)
    }

    fn wire(&self, seq: u64, prev: &ContentId, steward: &str) -> Value {
        // JCR-1: integers + strings only. `completed` is 0/1, energy is integer µJ,
        // and the rate figures (tokens/sec, joules-in-J) are recomputed on read.
        let mut o = json!({
            "efficiency_receipt": "efficiency/1",
            "task": self.task,
            "completed": u64::from(self.completed),
            "verdict": self.verdict,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "energy_uj": self.energy.uj(),
            "provenance": self.energy.provenance.jcr1_label(),
            "wall_ns": self.wall_ns,
            "seq": seq,
            "prev": prev.to_hex(),
            "steward": steward,
        });
        // Omitted when undefined, never sealed as 0 — the same shape
        // `mesh-receipt` seals its wedge metric with, and what `mesh/SPEC.md` §6
        // specifies. Canonical CBOR sorts keys, so insertion order here never
        // reaches the wire.
        if let Some(uj) = self.uj_per_accepted_token() {
            o["uj_per_accepted_token"] = json!(uj);
        }
        // Carried only when `Partial` (jcp SPEC §5.2), so a receipt sealed
        // before the field existed, and every whole one, keeps its bytes. It
        // dropped out of the receipt entirely: a GPU-only figure sealed as
        // `HwShunt` reached a verifier as a whole-task total.
        if !self.energy.is_whole() {
            o["energy_coverage"] = json!(self.energy.coverage.label());
        }
        if let Some(v) = self.value_uusd {
            o["value_uusd"] = json!(v);
            if let Some(per) = self.uusd_per_accepted_token() {
                o["uusd_per_accepted_token"] = json!(per);
            }
        }
        if let Some(a) = &self.energy_attestation {
            o["energy_attestation"] = json!(a);
        }
        o
    }
}

/// A steward-signed, hash-chained ledger of `efficiency/1` receipts — the surfaced
/// efficiency record for a fleet / project / period.
pub struct EfficiencyLog {
    steward_sk: SigningKey,
    steward: String,
    steward_pk: [u8; 32],
    seq: u64,
    prev: ContentId,
    receipts: Vec<Vec<u8>>,
}

impl EfficiencyLog {
    /// A new log sealing under `steward_sk` / `steward`.
    pub fn new(steward_sk: SigningKey, steward: impl Into<String>) -> Self {
        let steward_pk = steward_sk.verifying_key().to_bytes();
        EfficiencyLog {
            steward_sk,
            steward: steward.into(),
            steward_pk,
            seq: 0,
            prev: ContentId([0u8; 32]),
            receipts: Vec::new(),
        }
    }

    /// Seal one measurement, append it to the chain, and return the envelope.
    pub fn append(&mut self, eff: &Efficiency) -> Vec<u8> {
        let envelope = eff.seal(self.seq, &self.prev, &self.steward_sk, &self.steward);
        self.prev = ContentId::of_bytes(&envelope);
        self.seq += 1;
        self.receipts.push(envelope.clone());
        envelope
    }

    /// The sealed receipts, in order.
    pub fn receipts(&self) -> &[Vec<u8>] {
        &self.receipts
    }

    /// The sealing steward id.
    pub fn steward(&self) -> &str {
        &self.steward
    }

    /// The steward public key — a third party verifies the chain with this.
    pub fn steward_pubkey(&self) -> [u8; 32] {
        self.steward_pk
    }
}

// ───────────────────────────── verification ─────────────────────────────

/// Errors verifying an `efficiency/1` receipt.
#[derive(Debug, thiserror::Error)]
pub enum EfficiencyError {
    /// A JCR-1 envelope / signature error.
    #[error("jcr1: {0}")]
    Jcr1(#[from] jcr1::Jcr1Error),
    /// A decode error reading the verified payload.
    #[error("schema: {0}")]
    Schema(String),
    /// The verified payload is not a well-formed `efficiency/1` receipt.
    #[error("malformed efficiency receipt: {0}")]
    Malformed(String),
}

/// The fields recovered from a verified `efficiency/1` receipt.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct EfficiencyReceipt {
    /// The unit of work.
    pub task: String,
    /// Whether it reached a verified, done result (the outcome anchor).
    pub completed: bool,
    /// The outcome verdict label.
    pub verdict: String,
    /// Input tokens.
    pub tokens_in: u64,
    /// Accepted output tokens.
    pub tokens_out: u64,
    /// Total energy, microjoules.
    pub energy_uj: u64,
    /// Energy provenance label: `HwShunt`, `ModelBased` or `Estimator`.
    pub provenance: String,
    /// How much of the unit the energy figure covers. `Partial` when the
    /// receipt carries `energy_coverage`; such a receipt seals no
    /// `uj_per_accepted_token`, and is not a task total.
    pub energy_coverage: Coverage,
    /// Wall-clock nanoseconds.
    pub wall_ns: u64,
    /// Microjoules per accepted token (headline). `None` when the receipt sealed
    /// no figure because no tokens were accepted — an undefined ratio, not zero
    /// cost per token.
    pub uj_per_accepted_token: Option<u64>,
    /// Value delivered, micro-USD (when stated).
    pub value_uusd: Option<u64>,
    /// Hex content-id commitment to an external energy attestation (when present) —
    /// resolve + verify it via the attestation layer to derive the honest trust
    /// level. `None` = the counter is unattested.
    pub energy_attestation: Option<String>,
    /// Chain sequence number.
    pub seq: u64,
    /// Previous entry's content id (hex).
    pub prev: String,
    /// Sealing steward.
    pub steward: String,
}

impl EfficiencyReceipt {
    /// Accepted tokens per second, recomputed from the sealed inputs.
    pub fn tokens_per_sec(&self) -> f64 {
        if self.wall_ns == 0 {
            0.0
        } else {
            self.tokens_out as f64 / (self.wall_ns as f64 / 1e9)
        }
    }
}

/// Verify a sealed `efficiency/1` receipt against the steward key and recover its
/// fields ([`read_payload`]). A flipped byte anywhere fails the signature.
pub fn verify(envelope: &[u8], steward: &str, pubkey: &[u8; 32]) -> Result<EfficiencyReceipt, EfficiencyError> {
    let payload = jcr1::verify_cose_sign1(envelope, steward, pubkey)?;
    let v: Value =
        jcp_schema::from_canonical_cbor(&payload).map_err(|e| EfficiencyError::Schema(e.to_string()))?;
    read_payload(&v)
}

/// The provenance a sealed label names, and `None` for a label that is not one.
fn provenance_of(label: &str) -> Option<Provenance> {
    [Provenance::HwShunt, Provenance::ModelBased, Provenance::Estimator]
        .into_iter()
        .find(|p| p.jcr1_label() == label)
}

/// Read an `efficiency/1` payload, the signed core [`verify`] recovers once the
/// signature holds, and refuse one that is not a well-formed receipt. It is
/// apart from [`verify`] so that the payload's rules can be replayed from
/// published vectors with no signature in them
/// (`jcp/conformance/v1/efficiency.json`). Beyond the required fields:
///
/// - `provenance` MUST be one of the three labels;
/// - `energy_coverage`, when present, MUST be `"Partial"`. An absent field is
///   `Whole`, so `"Whole"` and every other value are refused rather than read
///   either way;
/// - a `Partial` receipt MUST NOT carry `uj_per_accepted_token`, since that
///   would present a partial figure as a task total (jcp SPEC §5.2).
pub fn read_payload(v: &Value) -> Result<EfficiencyReceipt, EfficiencyError> {
    if v.get("efficiency_receipt").and_then(Value::as_str) != Some("efficiency/1") {
        return Err(EfficiencyError::Malformed("not an efficiency/1 receipt".into()));
    }
    let s = |k: &str| {
        v.get(k)
            .and_then(Value::as_str)
            .map(str::to_string)
            .ok_or_else(|| EfficiencyError::Malformed(format!("missing string '{k}'")))
    };
    let u = |k: &str| {
        v.get(k)
            .and_then(Value::as_u64)
            .ok_or_else(|| EfficiencyError::Malformed(format!("missing uint '{k}'")))
    };
    let provenance = s("provenance")?;
    if provenance_of(&provenance).is_none() {
        return Err(EfficiencyError::Malformed(format!("'{provenance}' is not a provenance label")));
    }
    let energy_coverage = match v.get("energy_coverage") {
        None => Coverage::Whole,
        Some(c) if c.as_str() == Some(Coverage::Partial.label()) => Coverage::Partial,
        Some(c) => {
            return Err(EfficiencyError::Malformed(format!(
                "energy_coverage {c} is not \"Partial\", the one value it carries; an absent field is Whole"
            )))
        }
    };
    let uj_per_accepted_token = v.get("uj_per_accepted_token").and_then(Value::as_u64);
    if energy_coverage == Coverage::Partial && uj_per_accepted_token.is_some() {
        return Err(EfficiencyError::Malformed(
            "a Partial figure presented as a task total: it carries uj_per_accepted_token".into(),
        ));
    }
    Ok(EfficiencyReceipt {
        task: s("task")?,
        completed: u("completed")? != 0,
        verdict: s("verdict")?,
        tokens_in: u("tokens_in")?,
        tokens_out: u("tokens_out")?,
        energy_uj: u("energy_uj")?,
        provenance,
        energy_coverage,
        wall_ns: u("wall_ns")?,
        uj_per_accepted_token,
        value_uusd: v.get("value_uusd").and_then(Value::as_u64),
        energy_attestation: v.get("energy_attestation").and_then(Value::as_str).map(str::to_string),
        seq: u("seq")?,
        prev: s("prev")?,
        steward: s("steward")?,
    })
}

/// Verify a whole chain of `efficiency/1` receipts: each seal valid under the
/// steward key, and each `prev` linking to the prior envelope's content id. Returns
/// the verified receipts, or the index of the first break.
pub fn verify_chain(
    receipts: &[Vec<u8>],
    steward: &str,
    pubkey: &[u8; 32],
) -> Result<Vec<EfficiencyReceipt>, usize> {
    let mut prev = ContentId([0u8; 32]).to_hex();
    let mut out = Vec::with_capacity(receipts.len());
    for (i, env) in receipts.iter().enumerate() {
        let Ok(r) = verify(env, steward, pubkey) else {
            return Err(i);
        };
        if r.prev != prev {
            return Err(i);
        }
        prev = ContentId::of_bytes(env).to_hex();
        out.push(r);
    }
    Ok(out)
}

// ───────────────────────────── aggregation (the surface) ─────────────────────────────

/// The honest efficiency ledger over a set of measurements: value delivered split
/// from total spend, with waste (spend on units that never completed) made
/// explicit. This is the figure a "cost per token" number cannot produce.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Totals {
    /// Units that reached a verified, done result.
    pub completed_units: u64,
    /// Units that consumed spend but did not complete.
    pub wasted_units: u64,
    /// Tokens (in + out) spent on completed units.
    pub completed_tokens: u64,
    /// Tokens spent on units that never completed — pure waste.
    pub wasted_tokens: u64,
    /// Joules (µJ) spent on completed units.
    pub completed_uj: u64,
    /// Joules (µJ) spent on units that never completed.
    pub wasted_uj: u64,
    /// Value delivered by completed units, micro-USD.
    pub value_uusd: u64,
    /// The weakest provenance among the receipts summed, `None` for none: a
    /// total is never more measured than its least measured part (jcp SPEC
    /// §5.3).
    pub provenance_floor: Option<Provenance>,
    /// `Partial` if any receipt summed was. The energy totals then do not
    /// cover the work, and no per-unit energy figure is given.
    pub coverage: Coverage,
}

impl Totals {
    /// Total tokens per completed unit — *including* the waste of failed attempts.
    /// The number that beats "cost per token": it charges every attempt against the
    /// results actually delivered. `None` when nothing completed.
    ///
    /// The claim is that it "charges every attempt against the results actually
    /// delivered", which it stops doing precisely when nothing was delivered: the
    /// denominator is zero and the ratio is undefined. Reporting `0` there named
    /// the cheapest possible cost per result for spend that produced none.
    pub fn tokens_per_completed_unit(&self) -> Option<u64> {
        self.completed_tokens
            .saturating_add(self.wasted_tokens)
            .checked_div(self.completed_units)
    }

    /// Total microjoules per completed unit, including waste. `None` when nothing
    /// completed — see [`Self::tokens_per_completed_unit`] — and when any
    /// receipt summed was `Partial`: the energy totals then do not cover the
    /// work, so their ratio is not what a result cost (jcp SPEC §5.2).
    pub fn uj_per_completed_unit(&self) -> Option<u64> {
        if !self.coverage.is_whole() {
            return None;
        }
        self.completed_uj
            .saturating_add(self.wasted_uj)
            .checked_div(self.completed_units)
    }

    /// Micro-USD of value delivered per joule spent (including waste) — the ultimate
    /// efficiency figure. `0.0` if no energy spent.
    ///
    /// Kept as `0.0`, unlike the cost-per-unit ratios above: higher is better here,
    /// so the fallback is this figure's *worst* value, not its optimum. The same
    /// holds for [`Efficiency::tokens_per_sec`]. A zero that understates is not the
    /// defect those `Option`s fix.
    ///
    /// `0.0` too when any receipt summed was `Partial`, for the same reason:
    /// value over an energy total that does not cover the work is not value
    /// per joule of it, and this figure's fallback is its worst value.
    pub fn value_per_joule(&self) -> f64 {
        let total_uj = self.completed_uj.saturating_add(self.wasted_uj);
        if total_uj == 0 || !self.coverage.is_whole() {
            0.0
        } else {
            // value (µUSD) per joule = value_uusd / (total_uj / 1e6)
            self.value_uusd as f64 / (total_uj as f64 / 1e6)
        }
    }

    /// The share of spent tokens that bought nothing (0.0–1.0). `None` when no
    /// tokens were spent at all, since `0.0` is this figure's optimum — an empty
    /// ledger reported a perfect zero-waste record.
    pub fn waste_fraction(&self) -> Option<f64> {
        let total = self.completed_tokens.saturating_add(self.wasted_tokens);
        if total == 0 {
            None
        } else {
            Some(self.wasted_tokens as f64 / total as f64)
        }
    }
}

/// Aggregate verified receipts into the honest efficiency ledger. The energy
/// totals carry the floor of what they sum: the weakest provenance and, if any
/// receipt was `Partial`, `Partial` coverage. Aggregation is not a step at
/// which a grade improves (jcp SPEC §5.3), and a sum of partial figures is no
/// more a task total than one of them is.
pub fn aggregate<'a>(receipts: impl IntoIterator<Item = &'a EfficiencyReceipt>) -> Totals {
    let mut t = Totals::default();
    for r in receipts {
        // A label [`read_payload`] would refuse counts as the weakest: a
        // receipt built by hand is not given a grade it does not name.
        let p = provenance_of(&r.provenance).unwrap_or(Provenance::Estimator);
        t.provenance_floor = Some(t.provenance_floor.map_or(p, |f| trace::weakest_provenance(f, p)));
        t.coverage = trace::weakest_coverage(t.coverage, r.energy_coverage);
        if r.completed {
            t.completed_units += 1;
            t.completed_tokens = t.completed_tokens.saturating_add(r.tokens_in).saturating_add(r.tokens_out);
            t.completed_uj = t.completed_uj.saturating_add(r.energy_uj);
            t.value_uusd = t.value_uusd.saturating_add(r.value_uusd.unwrap_or(0));
        } else {
            t.wasted_units += 1;
            t.wasted_tokens = t.wasted_tokens.saturating_add(r.tokens_in).saturating_add(r.tokens_out);
            t.wasted_uj = t.wasted_uj.saturating_add(r.energy_uj);
        }
    }
    t
}

#[cfg(test)]
mod tests {
    use super::*;

    fn key() -> SigningKey {
        SigningKey::from_bytes(&[0xef; 32])
    }

    fn measurement(task: &str, completed: bool, tokens_out: u64, uj: u64, value: Option<u64>) -> Efficiency {
        Efficiency {
            task: task.into(),
            completed,
            verdict: if completed { "tests-pass".into() } else { "gate-failed".into() },
            tokens_in: tokens_out * 4, // context dwarfs output, as in agentic loops
            tokens_out,
            energy: Energy::modeled(uj),
            wall_ns: 1_000_000_000, // 1 s
            value_uusd: value,
            energy_attestation: None,
        }
    }

    /// **A GPU-only figure is not a task total.** It used to seal as
    /// `energy_uj` + `provenance: HwShunt` with no coverage, and a per-token
    /// headline over it, so it reached a verifier as the whole task's energy
    /// per token. Now it seals its coverage, and no headline.
    #[test]
    fn a_partial_figure_seals_its_coverage_and_no_task_total() {
        let sk = key();
        let mut e = measurement("gpu-only", true, 500, 0, None);
        e.energy = Energy::measured_partial(600_000);
        assert_eq!(e.uj_per_accepted_token(), None, "a partial figure gives no per-token cost of the task");
        let p = e.payload(0, &ContentId([0u8; 32]), "did:example:steward");
        assert_eq!(p["energy_coverage"], "Partial");
        assert!(p.get("uj_per_accepted_token").is_none(), "{p}");

        let env = e.seal(0, &ContentId([0u8; 32]), &sk, "did:example:steward");
        let r = verify(&env, "did:example:steward", &sk.verifying_key().to_bytes()).unwrap();
        assert_eq!(r.energy_coverage, Coverage::Partial);
        assert_eq!((r.energy_uj, r.provenance.as_str()), (600_000, "HwShunt"), "what was measured still reads");
        assert_eq!(r.uj_per_accepted_token, None);

        // A whole figure carries no coverage field, so its bytes are what they
        // were before the field existed, and it reads back `Whole`.
        let whole = measurement("whole", true, 500, 1_000_000, None);
        let p = whole.payload(0, &ContentId([0u8; 32]), "did:example:steward");
        assert!(p.get("energy_coverage").is_none(), "{p}");
        assert_eq!(read_payload(&p).unwrap().energy_coverage, Coverage::Whole);
    }

    /// A reader refuses a partial figure presented as a task total, a coverage
    /// other than `"Partial"` (absent is `Whole`), and a provenance label that
    /// is not one of the three.
    #[test]
    fn a_reader_refuses_what_a_conformant_receipt_never_carries() {
        let mut e = measurement("gpu-only", true, 500, 0, None);
        e.energy = Energy::measured_partial(600_000);
        let base = e.payload(0, &ContentId([0u8; 32]), "did:example:steward");
        let refused = |edit: &dyn Fn(&mut Value), because: &str| {
            let mut p = base.clone();
            edit(&mut p);
            let err = read_payload(&p).expect_err(because).to_string();
            assert!(err.contains(because), "{err}");
        };
        refused(&|p| p["uj_per_accepted_token"] = json!(1_200), "presented as a task total");
        refused(&|p| p["energy_coverage"] = json!("Whole"), "energy_coverage");
        refused(&|p| p["energy_coverage"] = json!("partial"), "energy_coverage");
        refused(&|p| p["provenance"] = json!("Measured"), "not a provenance label");
    }

    /// A total is never more measured, nor more complete, than what it sums
    /// (jcp SPEC §5.3): one estimated receipt makes it estimated, and one
    /// partial receipt makes it partial, with no per-unit energy figure.
    #[test]
    fn aggregation_takes_the_floor_of_provenance_and_coverage() {
        let sk = key();
        let pk = sk.verifying_key().to_bytes();
        let mut log = EfficiencyLog::new(sk, "did:example:steward");
        let mut hw = measurement("a", true, 100, 0, Some(1_000_000));
        hw.energy = Energy::measured(500_000);
        let mut gpu = measurement("b", true, 100, 0, Some(1_000_000));
        gpu.energy = Energy::measured_partial(300_000);
        let mut est = measurement("c", false, 100, 0, None);
        est.energy = Energy::estimator(200_000);
        log.append(&hw);
        let whole_only = aggregate(&verify_chain(log.receipts(), "did:example:steward", &pk).unwrap());
        assert_eq!((whole_only.coverage, whole_only.provenance_floor), (Coverage::Whole, Some(Provenance::HwShunt)));
        assert_eq!(whole_only.uj_per_completed_unit(), Some(500_000));

        log.append(&est);
        log.append(&gpu);
        let t = aggregate(&verify_chain(log.receipts(), "did:example:steward", &pk).unwrap());
        assert_eq!(t.provenance_floor, Some(Provenance::Estimator), "one estimate makes the total estimated");
        assert_eq!(t.coverage, Coverage::Partial, "one partial figure makes the total partial");
        assert_eq!(t.uj_per_completed_unit(), None, "a partial total is no cost per result");
        assert_eq!(t.value_per_joule(), 0.0, "nor value per joule of the work");
        assert_eq!(t.completed_uj, 800_000, "what was measured is still summed");
        assert_eq!(t.tokens_per_completed_unit(), Some(750), "token figures do not depend on the energy");
        assert_eq!(aggregate(&[]).provenance_floor, None, "an empty ledger names no grade");
    }

    #[test]
    fn the_four_metrics_compute_from_the_inputs() {
        let e = measurement("t", true, 500, 1_000_000, Some(2_000_000));
        assert_eq!(e.uj_per_accepted_token(), Some(2_000)); // 1e6 µJ / 500 tok
        assert_eq!(e.tokens_per_sec(), 500.0); // 500 tok / 1 s
        assert_eq!(e.uusd_per_accepted_token(), Some(4_000)); // 2e6 µUSD / 500
        assert_eq!(e.tokens_total(), 2_500); // 4×500 in + 500 out
    }

    #[test]
    fn value_is_never_invented() {
        let e = measurement("t", true, 100, 500_000, None);
        assert_eq!(e.uusd_per_accepted_token(), None);
    }

    /// The case the sealed headline figure used to misreport: 10 J spent,
    /// nothing accepted, `completed: false` — which the crate documents as
    /// meaning "the tokens/joules below bought nothing".
    ///
    /// The ratio is undefined, and `0` is the *optimum* of a cost-per-result
    /// figure — better than any successful run — so the receipt seals no figure
    /// rather than the best possible one. `mesh/SPEC.md` §6 specifies the same
    /// convention: "omitted when no tokens were accepted".
    #[test]
    fn spend_that_bought_nothing_seals_no_headline_figure() {
        let sk = key();
        let e = measurement("t", false, 0, 10_000_000, None);
        assert_eq!(e.energy.uj(), 10_000_000, "the spend is real");
        assert_eq!(
            e.uj_per_accepted_token(),
            None,
            "0 uJ/token would read as free, and as better than any completed run"
        );

        let wire = e.wire(0, &ContentId([0u8; 32]), "did:jcp:eff");
        assert!(
            wire.get("uj_per_accepted_token").is_none(),
            "an undefined figure is omitted from the signed core, not sealed as 0: {wire}"
        );

        let env = e.seal(0, &ContentId([0u8; 32]), &sk, "did:jcp:eff");
        let rec = verify(&env, "did:jcp:eff", &sk.verifying_key().to_bytes())
            .expect("a receipt without the figure still verifies");
        assert_eq!(rec.uj_per_accepted_token, None);
        assert_eq!(rec.energy_uj, 10_000_000, "and the spend is still on it");
    }

    /// The value projection is not invented either. `value_uusd` is an input and
    /// still seals; the per-token ratio derived from it does not.
    #[test]
    fn a_value_figure_is_not_invented_without_accepted_tokens() {
        let e = measurement("t", false, 0, 10_000_000, Some(2_000_000));
        assert_eq!(e.uusd_per_accepted_token(), None);

        let wire = e.wire(0, &ContentId([0u8; 32]), "did:jcp:eff");
        assert_eq!(
            wire.get("value_uusd").and_then(Value::as_u64),
            Some(2_000_000),
            "the stated value is an input, not a ratio"
        );
        assert!(wire.get("uusd_per_accepted_token").is_none());
    }

    /// The aggregate half, through the real seal -> verify -> aggregate path:
    /// units that spent energy and completed nothing have no cost per completed
    /// unit. Not 0, which would be the cheapest ledger expressible.
    #[test]
    fn a_ledger_with_nothing_completed_reports_no_cost_per_unit() {
        let sk = key();
        let pk = sk.verifying_key().to_bytes();
        let recs: Vec<EfficiencyReceipt> = (0..3)
            .map(|i| {
                let e = measurement("t", false, 0, 10_000_000, None);
                let env = e.seal(i, &ContentId([0u8; 32]), &sk, "did:jcp:eff");
                verify(&env, "did:jcp:eff", &pk).expect("seals and verifies")
            })
            .collect();
        for r in &recs {
            assert_eq!(r.uj_per_accepted_token, None);
        }

        let t = aggregate(&recs);
        assert_eq!(t.completed_units, 0);
        assert_eq!(t.wasted_units, 3);
        assert_eq!(t.wasted_uj, 30_000_000, "30 J of real spend");
        assert_eq!(
            t.uj_per_completed_unit(),
            None,
            "0 uJ per completed unit would be the cheapest record possible"
        );
        assert_eq!(t.tokens_per_completed_unit(), None);

        // An empty ledger has no waste share at all, rather than a perfect one.
        assert_eq!(Totals::default().waste_fraction(), None);
    }

    /// The figures whose zero fallback is their *worst* value keep it: a zero
    /// that understates is not the defect the `Option`s above fix.
    #[test]
    fn a_fallback_toward_the_worst_value_is_left_alone() {
        let e = measurement("t", true, 0, 1_000, None);
        assert_eq!(e.tokens_per_sec(), 0.0, "throughput: higher is better");
        assert_eq!(Totals::default().value_per_joule(), 0.0, "value: higher is better");
    }

    #[test]
    fn seal_verify_round_trips_and_tamper_fails() {
        let sk = key();
        let e = measurement("fix-123", true, 400, 800_000, Some(1_000_000));
        let env = e.seal(0, &ContentId([0u8; 32]), &sk, "did:jcp:eff");
        let rec = verify(&env, "did:jcp:eff", &sk.verifying_key().to_bytes()).unwrap();
        assert_eq!(rec.task, "fix-123");
        assert!(rec.completed);
        assert_eq!(rec.tokens_out, 400);
        assert_eq!(rec.uj_per_accepted_token, Some(2_000));
        assert_eq!(rec.value_uusd, Some(1_000_000));
        assert_eq!(rec.tokens_per_sec(), 400.0);

        let mut bad = env.clone();
        *bad.last_mut().unwrap() ^= 1;
        assert!(verify(&bad, "did:jcp:eff", &sk.verifying_key().to_bytes()).is_err());
    }

    #[test]
    fn an_energy_attestation_commitment_seals_and_survives_round_trip() {
        let sk = key();
        // Stand-in for the raw attestation-report bytes the attestation layer emits.
        let attestation_report = b"sandbox-tee::energy report bytes";
        let e = measurement("fix-9", true, 400, 800_000, None)
            .with_energy_attestation(attestation_report);
        let commitment = e.energy_attestation.clone().unwrap();
        // The commitment is the content id of the attestation — resolvable + checkable.
        assert_eq!(commitment, ContentId::of_bytes(attestation_report).to_hex());

        let env = e.seal(0, &ContentId([0u8; 32]), &sk, "did:jcp:eff");
        let rec = verify(&env, "did:jcp:eff", &sk.verifying_key().to_bytes()).unwrap();
        assert_eq!(rec.energy_attestation.as_deref(), Some(commitment.as_str()));

        // A receipt with no attestation leaves the field absent (unattested default).
        let plain = measurement("fix-10", true, 100, 200_000, None);
        let env2 = plain.seal(1, &ContentId([0u8; 32]), &sk, "did:jcp:eff");
        let rec2 = verify(&env2, "did:jcp:eff", &sk.verifying_key().to_bytes()).unwrap();
        assert_eq!(rec2.energy_attestation, None);
    }

    #[test]
    fn a_log_hash_chains_and_verifies() {
        let mut log = EfficiencyLog::new(key(), "did:jcp:eff");
        log.append(&measurement("a", true, 300, 600_000, Some(500_000)));
        log.append(&measurement("b", false, 900, 1_800_000, None)); // burned, no result
        log.append(&measurement("c", true, 300, 600_000, Some(500_000)));
        let recs = verify_chain(log.receipts(), log.steward(), &log.steward_pubkey()).unwrap();
        assert_eq!(recs.len(), 3);
    }

    #[test]
    fn aggregate_makes_waste_visible_and_charges_it_to_completed_units() {
        // Two units complete (300 out each), one burns 900 out and completes nothing.
        let recs = [
            measurement("a", true, 300, 600_000, Some(500_000)),
            measurement("b", false, 900, 1_800_000, None),
            measurement("c", true, 300, 600_000, Some(500_000)),
        ]
        .map(|e| {
            let sk = key();
            let env = e.seal(0, &ContentId([0u8; 32]), &sk, "did:jcp:eff");
            verify(&env, "did:jcp:eff", &sk.verifying_key().to_bytes()).unwrap()
        });
        let t = aggregate(&recs);
        assert_eq!(t.completed_units, 2);
        assert_eq!(t.wasted_units, 1);
        // completed tokens: 2 × (1200 in + 300 out) = 3000; wasted: 3600 in + 900 out = 4500
        assert_eq!(t.completed_tokens, 3_000);
        assert_eq!(t.wasted_tokens, 4_500);
        // tokens per completed unit charges ALL spend (7500) to the 2 done units.
        assert_eq!(t.tokens_per_completed_unit(), Some(3_750));
        assert_eq!(t.value_uusd, 1_000_000);
        // more than half the tokens bought nothing — the number "cost/token" hides.
        assert!(t.waste_fraction().expect("tokens were spent") > 0.5);
    }
}
