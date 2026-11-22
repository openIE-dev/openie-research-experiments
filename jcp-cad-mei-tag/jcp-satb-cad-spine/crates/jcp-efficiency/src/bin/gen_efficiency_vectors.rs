//! Emit the `efficiency/1` payload conformance pack to `jcp/conformance/v1/`.
//!
//! jcp SPEC §5.2 says a `Partial` figure MUST NOT be presented as a task total,
//! and §5.3 that aggregation is not a step at which a grade improves. These are
//! the vectors a third party replays to check an independent `efficiency/1`
//! reader against those rules: payloads (the signed core, once its signature
//! holds) with the reading a conformant reader must reach, the refusals
//! included, and receipt sets with the totals they must sum to. The payloads
//! carry no signature, because the rules are about what a verified receipt
//! says, not about the signature, which `jcr1` vectors already cover.
//!
//! Run: `cargo run -p jcp-efficiency --bin gen_efficiency_vectors -- ../conformance/v1`

use std::path::PathBuf;

use jcp_efficiency::{aggregate, read_payload, Efficiency};
use jcp_schema::{ContentId, Energy};
use serde_json::{json, Value};

fn unit(task: &str, completed: bool, tokens_out: u64, energy: Energy) -> Efficiency {
    Efficiency {
        task: task.into(),
        completed,
        verdict: if completed { "tests-pass".into() } else { "gate-failed".into() },
        tokens_in: tokens_out * 4,
        tokens_out,
        energy,
        wall_ns: 1_000_000_000,
        value_uusd: None,
        energy_attestation: None,
    }
}

fn payload(e: &Efficiency) -> Value {
    e.payload(0, &ContentId([0u8; 32]), "did:example:steward")
}

/// A case carries the input and the verdict a conformant reader must reach.
fn case(note: &str, input: Value, expected: Value) -> Value {
    json!({ "note": note, "input": input, "expected": expected })
}

fn read(note: &str, p: Value) -> Value {
    let r = read_payload(&p).unwrap_or_else(|e| panic!("{note}: a positive must read: {e}"));
    case(
        note,
        p,
        json!({
            "energy_uj": r.energy_uj,
            "provenance": r.provenance,
            "energy_coverage": r.energy_coverage.label(),
            "uj_per_accepted_token": r.uj_per_accepted_token,
        }),
    )
}

fn refuse(note: &str, p: Value, because: &str) -> Value {
    let err = read_payload(&p).expect_err(note).to_string();
    assert!(err.contains(because), "{note}: refused for '{err}', not '{because}'");
    case(note, p, json!({ "refused": because }))
}

/// A set of payloads and the totals a conformant reader must sum them to.
fn totals(note: &str, ps: Vec<Value>) -> Value {
    let rs: Vec<_> = ps.iter().map(|p| read_payload(p).expect("reads")).collect();
    let t = aggregate(&rs);
    case(
        note,
        json!(ps),
        json!({
            "completed_uj": t.completed_uj,
            "wasted_uj": t.wasted_uj,
            "coverage": t.coverage.label(),
            "provenance_floor": t.provenance_floor.map(|p| p.jcr1_label()),
            "uj_per_completed_unit": t.uj_per_completed_unit(),
            "tokens_per_completed_unit": t.tokens_per_completed_unit(),
        }),
    )
}

fn main() {
    let out = std::env::args()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../conformance/v1"));
    std::fs::create_dir_all(&out).expect("create output dir");

    let whole = unit("whole", true, 500, Energy::measured(1_000_000));
    let gpu_only = unit("gpu-only", true, 500, Energy::measured_partial(600_000));
    let estimated = unit("estimated", false, 200, Energy::estimator(400_000));

    let mut presented = payload(&gpu_only);
    presented["uj_per_accepted_token"] = json!(1_200);
    let mut said_whole = payload(&whole);
    said_whole["energy_coverage"] = json!("Whole");
    let mut unnamed = payload(&whole);
    unnamed["provenance"] = json!("Measured");

    let pack = json!({
        "profile": "efficiency/1",
        "spec": "jcp/SPEC.md §5.2-5.3",
        "payload": {
            "positive": [
                read("a whole figure seals its per-token headline and no coverage field", payload(&whole)),
                read(
                    "a GPU-only figure seals its coverage and no per-token headline: it is no task total",
                    payload(&gpu_only)
                ),
            ],
            "negative": [
                refuse(
                    "a GPU-only figure presented as a task total, with a per-token headline",
                    presented,
                    "presented as a task total"
                ),
                refuse("an absent coverage is Whole; \"Whole\" on the wire is refused", said_whole, "energy_coverage"),
                refuse("a provenance that is not one of the three labels", unnamed, "not a provenance label"),
            ],
        },
        "aggregate": { "cases": [
            totals(
                "a total over a partial figure is partial and gives no per-unit energy; its provenance is the floor",
                vec![payload(&whole), payload(&gpu_only), payload(&estimated)],
            ),
            totals(
                "a total over whole figures gives its per-unit energy, at the weakest provenance",
                vec![payload(&whole), payload(&estimated)],
            ),
        ] },
    });
    let path = out.join("efficiency.json");
    std::fs::write(&path, serde_json::to_string_pretty(&pack).expect("serialise") + "\n").expect("write pack");
    println!("wrote {}", path.display());
}
