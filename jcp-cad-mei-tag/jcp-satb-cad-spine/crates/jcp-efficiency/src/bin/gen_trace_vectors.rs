//! Emit the `energy_trace/1` conformance pack to `jcp/conformance/v1/`.
//!
//! SPEC §5.3–5.6 states rules; a rule nothing emits is a proposal. This writes
//! the vectors a third party replays to check an independent implementation —
//! positives *and* the refusals, since the refusals are the load-bearing half:
//! an implementation that accepts an unbound outcome, a double-counted
//! activity, or a frozen counter has failed in the direction that matters.
//!
//! Run: `cargo run -p jcp-efficiency --bin gen_trace_vectors -- ../conformance/v1`

use std::path::PathBuf;

use jcp_efficiency::dynamics::{
    Baseline, DrawShape, EnergyWindow, OperationalCause, PowerEnvelope,
};
use jcp_efficiency::trace::{ActivityRef, OutcomeTrace};
use jcp_schema::{ContentId, Coverage, Energy, Provenance};
use serde_json::{json, Value};

fn energy(uj: u64, p: Provenance, c: Coverage) -> Energy {
    Energy { measured_uj: Some(uj), estimated_uj: uj, provenance: p, coverage: c }
}

fn act(tag: &[u8], uj: u64, p: Provenance, c: Coverage) -> ActivityRef {
    ActivityRef::new(ContentId::of_bytes(tag), uj, p, c)
}

fn win(i: u64, uj: u64, p: Provenance) -> EnergyWindow {
    EnergyWindow {
        started_ns: i * 1_000_000,
        duration_ns: 1_000_000,
        joules_uj: uj,
        provenance: p,
        coverage: Coverage::Whole,
        declared_work: None,
    }
}

fn series(vals: &[u64]) -> Vec<EnergyWindow> {
    vals.iter().enumerate().map(|(i, &v)| win(i as u64, v, Provenance::HwShunt)).collect()
}

/// A case carries the inputs and the verdict a conformant implementation must
/// reach. Reproducing the verdict is the whole test; a case that only carried
/// inputs would check that an implementation runs, not that it agrees.
fn case(note: &str, input: Value, expected: Value) -> Value {
    json!({ "note": note, "input": input, "expected": expected })
}

fn main() {
    let out = std::env::args()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../conformance/v1")
        });
    std::fs::create_dir_all(&out).expect("create output dir");

    // ---- §5.3 conservation ------------------------------------------------
    let overhead = OutcomeTrace::new(
        energy(1_000_000, Provenance::HwShunt, Coverage::Whole),
        true,
        vec![
            act(b"a1", 400_000, Provenance::HwShunt, Coverage::Whole),
            act(b"a2", 350_000, Provenance::HwShunt, Coverage::Whole),
        ],
    );
    let r = overhead.reconcile().expect("reconciles");
    assert_eq!(r.residual_uj, 250_000);

    let floored = OutcomeTrace::new(
        energy(1_000, Provenance::HwShunt, Coverage::Whole),
        true,
        vec![
            act(b"a1", 300, Provenance::HwShunt, Coverage::Whole),
            act(b"a2", 300, Provenance::Estimator, Coverage::Partial),
        ],
    );
    let fr = floored.reconcile().expect("reconciles");

    let unbound = OutcomeTrace::new(
        energy(1_000_000, Provenance::HwShunt, Coverage::Whole), true, vec![],
    );
    let dup_act = act(b"same", 100, Provenance::HwShunt, Coverage::Whole);
    let dup = OutcomeTrace::new(
        energy(1_000, Provenance::HwShunt, Coverage::Whole), true,
        vec![dup_act.clone(), dup_act],
    );
    let over = OutcomeTrace::new(
        energy(100, Provenance::HwShunt, Coverage::Whole), true,
        vec![act(b"a1", 90, Provenance::HwShunt, Coverage::Whole),
             act(b"a2", 50, Provenance::HwShunt, Coverage::Whole)],
    );

    let conservation = json!({
        "positive": [
            case("the residual names what no operation claims",
                 json!(&overhead),
                 json!({"accounted_uj": r.accounted_uj, "residual_uj": r.residual_uj,
                        "provenance_floor": r.provenance_floor, "coverage_floor": r.coverage_floor,
                        "unattributed_ppm": r.unattributed_ppm(overhead.total_uj())})),
            case("provenance and coverage take the floor, never the average",
                 json!(&floored),
                 json!({"accounted_uj": fr.accounted_uj, "residual_uj": fr.residual_uj,
                        "provenance_floor": fr.provenance_floor, "coverage_floor": fr.coverage_floor})),
        ],
        "negative": [
            case("an outcome traceable to nothing is refused", json!(&unbound),
                 json!({"error": "Unbound"})),
            case("a double-bound activity is refused before the sum", json!(&dup),
                 json!({"error": "DuplicateActivity"})),
            case("activities claiming more than the outcome are refused", json!(&over),
                 json!({"error": "OverAccounted", "accounted_uj": 140, "total_uj": 100})),
        ]
    });

    // ---- §5.5 conservation against a grant --------------------------------
    let budget = json!({
        "positive": [
            case("half a percent over a one-joule grant is 5000 ppm, floor 1 ppm",
                 json!({"granted_uj": 1_000_000u64, "accounted_uj": 1_005_000u64,
                        "provenance_floor": Provenance::HwShunt}),
                 json!({"drift_ppm": 5_000, "detectable_floor_ppm": 1,
                        "drift_is_resolvable": true, "floor_is_physical": true})),
            case("the same floor over modelled windows is exact and meaningless",
                 json!({"granted_uj": 1_000_000u64, "accounted_uj": 1_000_005u64,
                        "provenance_floor": Provenance::Estimator}),
                 json!({"drift_ppm": 5, "detectable_floor_ppm": 1,
                        "floor_is_physical": false})),
            case("underspend is signed, not clamped: allowed joules nothing claimed",
                 json!({"granted_uj": 1_000_000u64, "accounted_uj": 300_000u64,
                        "provenance_floor": Provenance::HwShunt}),
                 json!({"drift_ppm": -700_000})),
        ],
        "negative": [
            case("a ratio against a zero grant is not a figure",
                 json!({"granted_uj": 0u64, "accounted_uj": 5u64}),
                 json!({"drift_ppm": Value::Null, "detectable_floor_ppm": Value::Null})),
        ]
    });

    // ---- §5.6 physical refutation -----------------------------------------
    let env = PowerEnvelope {
        peak_mw: 60_000,
        idle_floor_mw: 1_000,
        source: "burst rating, deliberately permissive".into(),
    };
    let frozen = EnergyWindow { duration_ns: 400_000_000, joules_uj: 0, ..win(0, 0, Provenance::HwShunt) };
    let impossible = EnergyWindow { duration_ns: 1_000_000, joules_uj: 10_000_000, ..win(0, 0, Provenance::HwShunt) };
    let plausible = EnergyWindow { duration_ns: 1_000_000, joules_uj: 30_000, ..win(0, 0, Provenance::HwShunt) };
    let instant = EnergyWindow { duration_ns: 0, joules_uj: 999, ..win(0, 0, Provenance::HwShunt) };

    let physical = json!({
        "envelope": &env,
        "cases": [
            case("a frozen counter on a busy window is refuted from below",
                 json!(&frozen), json!({"verdict": "RefutedBelow", "floor_uj": 400_000})),
            case("a figure past the burst envelope is refuted from above",
                 json!(&impossible), json!({"verdict": "RefutedAbove"})),
            case("inside the envelope is NotRefuted — which is not verification",
                 json!(&plausible), json!({"verdict": "NotRefuted"})),
            case("a zero-duration window is unboundable, not clean",
                 json!(&instant), json!({"verdict": "Unboundable"})),
        ]
    });

    // ---- §5.6 draw character ----------------------------------------------
    let padded = series(&[300_000, 10, 10, 10, 10, 10]);
    let flat = series(&[1_000, 1_020, 980, 1_010, 990, 1_000]);
    let scaled: Vec<u64> = [1_000u64, 1_020, 980, 1_010, 990, 1_000].iter().map(|v| v * 37).collect();
    let ramp = series(&[100, 400, 700, 1_000, 1_100, 1_120]);
    let bursty = series(&[100, 2_000, 100, 2_000, 100, 2_000]);

    let shape = json!({
        "idle_floor_uj": 100,
        "cases": [
            case("a total balanced by padding does not read as sustained",
                 json!({"declared": DrawShape::Sustained, "windows": &padded}),
                 json!({"verdict": "Inconsistent"})),
            case("character is scale-invariant: same shape at 37x the magnitude",
                 json!({"declared": DrawShape::Sustained, "windows": &series(&scaled)}),
                 json!({"verdict": "Consistent", "shape": DrawShape::Sustained})),
            case("flat is sustained", json!({"declared": DrawShape::Sustained, "windows": &flat}),
                 json!({"verdict": "Consistent", "shape": DrawShape::Sustained})),
            case("rising then settling is a ramp", json!({"declared": DrawShape::Ramping, "windows": &ramp}),
                 json!({"verdict": "Consistent", "shape": DrawShape::Ramping})),
            case("alternating is bursty", json!({"declared": DrawShape::Bursty, "windows": &bursty}),
                 json!({"verdict": "Consistent", "shape": DrawShape::Bursty})),
            case("under three windows character is unresolvable, never consistent",
                 json!({"declared": DrawShape::Sustained, "windows": &series(&[1_000, 1_000])}),
                 json!({"verdict": "Unresolvable", "windows": 2})),
        ]
    });

    // ---- §5.4 baselines and causes ----------------------------------------
    let w = win(0, 5_000, Provenance::HwShunt);
    let undeclared = Baseline::new(1_000, 100, "harness:run-1", 1_000);
    let declared = Baseline::new(1_000, 100, "harness:run-1", 1_000).declared_applicable();
    let coarse = Baseline::new(1_000, 100, "harness:coarse", 10_000_000).declared_applicable();
    let cause = OperationalCause::ThermalThrottle { reading: ContentId::of_bytes(b"thermal") };

    let dynamism = json!({
        "cases": [
            case("an undeclared baseline makes no comparison",
                 json!({"window": &w, "baseline": &undeclared}),
                 json!({"deviation": "BaselineInapplicable"})),
            case("a baseline fit coarser than the trace samples does not apply",
                 json!({"window": &w, "baseline": &coarse}),
                 json!({"deviation": "BaselineInapplicable"})),
            case("outside the band with no evidenced cause stays unexplained",
                 json!({"window": &w, "baseline": &declared, "cause": Value::Null}),
                 json!({"deviation": "Unexplained", "excess_uj": 4_000})),
            case("a cause with evidence explains; the token is the claim vocabulary",
                 json!({"window": &w, "baseline": &declared, "cause": &cause}),
                 json!({"deviation": "Explained", "cause_token": cause.token(),
                        "evidence": cause.evidence().to_hex(), "excess_uj": 4_000})),
        ],
        "note": "there is no verdict of intent in this profile, by design"
    });

    let pack = json!({
        "profile": "energy_trace/1",
        "spec": "JCP v0.3 SPEC.md §5.3-5.6",
        "conservation": conservation,
        "budget": budget,
        "physical": physical,
        "shape": shape,
        "dynamism": dynamism,
    });

    let path = out.join("energy_trace.json");
    let body = serde_json::to_string_pretty(&pack).expect("serialize") + "\n";
    std::fs::write(&path, body).unwrap_or_else(|e| panic!("write {}: {e}", path.display()));
    println!("wrote {}", path.display());
}
