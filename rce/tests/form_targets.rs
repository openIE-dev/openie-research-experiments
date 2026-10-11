//! One Form, five projections, one trace. The arithmetic-edges Form
//! (examples/form-arith.rce: a op b for add, sub, mul, div, rem, fdiv, min, max, fadd, fsub, fmul) runs on
//! events that hit every edge `form::num` defines, and on seeded random
//! edge values; every target must print the compiler's reference trace
//! byte for byte:
//!
//! - Rust (the emitted crate, native)            always (unless RCE_FORM_SKIP_CARGO)
//! - Python (emit_python, CPython 3)             when python3 is on PATH
//! - WASM (the emitted crate, wasm32-wasip1,
//!   run under node's WASI)                      when the target is installed and node is on PATH
//! - XState v5 and SCXML (SCION)                 when RCE_JS_DIR has node_modules with them
//!
//! The edges are also asserted on the reference itself (`-3 % 2 = -1`,
//! not Python's 1; `-7 / 2 = -3`, not Python's -4; overflow, division by
//! zero and non-finite results are errors; 3.0 is the int 3; null is not
//! absence).

use std::path::{Path, PathBuf};
use std::process::Command;

use rce::form::{self, emit_python, emit_rust, emit_scxml, emit_xstate, FormOptions};
use rce::form::fit::Fit;
use rce::form::ir::{FormEvent, FormIr};
use rce::spec::parser::parse_spec;
use serde_json::{json, Value};

const ARITH: &str = include_str!("../examples/form-arith.rce");
const ARITH_FIT: &str = include_str!("../examples/form-arith.fit.json");
const OPS: [&str; 11] = ["add", "sub", "mul", "div", "rem", "fdiv", "min", "max", "fadd", "fsub", "fmul"];

fn arith_ir() -> FormIr {
    form::compile(&parse_spec(ARITH).unwrap(), &Fit::parse(ARITH_FIT).unwrap(), &FormOptions::default()).unwrap()
}

fn ev(a: Value, b: Value) -> FormEvent {
    FormEvent { name: "IN_dep_DEP1".into(), payload: json!({"a": a, "b": b}) }
}

/// The edge events, in order.
fn edge_events() -> Vec<FormEvent> {
    let mut v = vec![
        ev(json!(-3), json!(2)),                    // 0  rem -1, div -1
        ev(json!(3), json!(-2)),                    // 1  rem 1
        ev(json!(-7), json!(2)),                    // 2  div -3, rem -1
        ev(json!(i64::MAX), json!(1)),              // 3  add overflow
        ev(json!(i64::MIN), json!(-1)),             // 4  div, rem, mul overflow
        ev(json!(1), json!(0)),                     // 5  div, rem by zero
        ev(json!(1.5), json!(0)),                   // 6  div, rem non-finite
        ev(json!(-5.5), json!(2)),                  // 7  rem -1.5 (fmod)
        ev(json!(1i64 << 62), json!(4)),            // 8  mul overflow
        ev(json!(3.0), json!(2)),                   // 9  3.0 is the int 3: div 1
        ev(json!(u64::MAX), json!(1)),              // 10 out of range
        ev(json!(0.1), json!(0.2)),                 // 11 add 0.30000000000000004
        ev(json!(1e308), json!(10)),                // 12 mul non-finite
        ev(json!("x"), json!(1)),                   // 13 contract reject
        ev(Value::Null, json!(1)),                  // 14 contract reject (null is not a float)
        FormEvent { name: "IN_dep_DEP1".into(), payload: json!({"a": 1}) }, // 15 b absent: escalate
        ev(json!(2.5), json!(0.5)),                 // 16 div 5 (normalized)
        ev(json!(-0.0), json!(1)),                  // 17 -0.0 is 0
        ev(json!(9007199254740993i64), json!(1)),   // 18 beyond 2^53: exact
        ev(json!(9007199254740993i64), json!(0.5)), // 19 int→f64 rounds to even
        ev(json!(1e-7), json!(3)),                  // 20 float text 1e-7 → 3.0000001
    ];
    for _ in 0..4 { v.push(FormEvent { name: "TICK".into(), payload: Value::Null }); } // role_R4 times out after 3
    v.push(FormEvent { name: "RESOLVE_role_R4".into(), payload: Value::Null });
    v.push(ev(json!(10), json!(3)));
    // Float text that serde_json's default (fast) parser reads 1 ulp off;
    // every target must parse payload floats exactly (found by the frozen
    // benchmark: 99.99999999995805 read back as ...804).
    v.push(ev(json!(99.99999999995805), json!(0)));
    v.push(ev(json!(2.347854773696718e19), json!(1e-300)));
    // Keys beyond the BMP: canonical order is by code point everywhere
    // (JS sorted UTF-16 units: "😀" before "\u{ffff}"). b is absent, so the
    // escalation output carries the whole input.
    v.push(FormEvent { name: "IN_dep_DEP1".into(), payload: json!({"a": 1, "\u{1F600}": 1, "\u{FFFF}": 2, "é": 3, "\u{10000}": 4}) });
    // An event not in E: no state change, an `unknown_event` output.
    v.push(FormEvent { name: "NOT_AN_EVENT".into(), payload: json!({"x": 1}) });
    v
}

struct Rng(u64);
impl Rng {
    fn next(&mut self) -> u64 { let mut x = self.0; x ^= x << 13; x ^= x >> 7; x ^= x << 17; self.0 = x; x }
    fn below(&mut self, n: u64) -> u64 { self.next() % n }
}

fn edge_value(r: &mut Rng) -> Value {
    match r.below(14) {
        0 => json!(i64::MAX), 1 => json!(i64::MIN), 2 => json!(-(r.below(9) as i64)), 3 => json!(r.below(9)),
        4 => json!(0), 5 => json!(-1), 6 => json!(3.0), 7 => json!(-5.5), 8 => json!(1e300), 9 => json!(1e-300),
        10 => json!(u64::MAX), 11 => json!(0.1), 12 => Value::Null,
        _ => json!((r.below(2000) as f64 - 1000.0) / 8.0),
    }
}

fn random_events(n: usize, seed: u64) -> Vec<FormEvent> {
    let mut r = Rng(seed);
    (0..n).map(|_| match r.below(10) {
        0 => FormEvent { name: "TICK".into(), payload: Value::Null },
        1 => FormEvent { name: format!("RESOLVE_role_R{}", 1 + r.below(11)), payload: Value::Null },
        _ => {
            let mut m = serde_json::Map::new();
            if r.below(11) != 0 { m.insert("a".into(), edge_value(&mut r)); }
            if r.below(11) != 0 { m.insert("b".into(), edge_value(&mut r)); }
            FormEvent { name: "IN_dep_DEP1".into(), payload: Value::Object(m) }
        }
    }).collect()
}

/// The `r` of the emit to `sink` in step `i`, or the error/escalation.
fn result_at(trace: &Value, i: usize, op: &str) -> Value {
    let sink = format!("del_D{}", OPS.iter().position(|o| *o == op).unwrap() + 1);
    let node = format!("role_R{}", OPS.iter().position(|o| *o == op).unwrap() + 1);
    for o in trace[i]["context"]["last_outputs"].as_array().unwrap() {
        if o["kind"] == "emit" && o["sink"] == sink.as_str() { return o["row"]["r"].clone(); }
        if (o["kind"] == "error" || o["kind"] == "escalate") && o["node"] == node.as_str() {
            return json!({ o["kind"].as_str().unwrap(): o.get("message").or(o.get("reason")).cloned() });
        }
        if o["kind"] == "reject" { return json!({"reject": o["message"]}); }
    }
    Value::Null
}

#[test]
fn reference_has_the_defined_edges() {
    let ir = arith_ir();
    let t = emit_rust::reference_trace(&ir, &edge_events());
    let r = |i, op| result_at(&t, i, op);
    assert_eq!(r(0, "rem"), json!(-1), "-3 % 2 is -1 (Python's % gives 1)");
    assert_eq!(r(0, "div"), json!(-1));
    assert_eq!(r(1, "rem"), json!(1));
    assert_eq!(r(2, "div"), json!(-3), "-7 / 2 truncates to -3 (Python's // gives -4)");
    assert_eq!(r(2, "rem"), json!(-1));
    assert_eq!(r(3, "add"), json!({"error": "add: integer overflow"}));
    assert_eq!(r(3, "sub"), json!(i64::MAX - 1));
    for op in ["div", "rem", "mul"] { assert_eq!(r(4, op), json!({"error": format!("{}: integer overflow", op)})); }
    assert_eq!(r(4, "add"), json!({"error": "add: integer overflow"}));
    assert_eq!(r(4, "sub"), json!(i64::MIN + 1));
    assert_eq!(r(5, "div"), json!({"error": "div: division by zero"}));
    assert_eq!(r(5, "rem"), json!({"error": "rem: division by zero"}));
    assert_eq!(r(6, "div"), json!({"error": "div: non-finite result"}));
    assert_eq!(r(6, "rem"), json!({"error": "rem: non-finite result"}));
    assert_eq!(r(7, "rem"), json!(-1.5));
    assert_eq!(r(2, "fdiv"), json!(-3.5), "true division is always f64");
    assert_eq!(r(5, "fdiv"), json!({"error": "fdiv: division by zero"}), "no ±inf");
    assert_eq!(r(4, "min"), json!(i64::MIN));
    assert_eq!(r(7, "max"), json!(2));
    assert_eq!(r(3, "fadd"), json!(9223372036854775808.0), "f64 add never overflows");
    assert_eq!(r(8, "fmul"), json!(18446744073709551616.0));
    assert_eq!(r(11, "fadd"), json!(0.30000000000000004));
    assert_eq!(r(12, "fmul"), json!({"error": "fmul: non-finite result"}));
    assert_eq!(r(8, "mul"), json!({"error": "mul: integer overflow"}));
    assert_eq!(r(9, "div"), json!(1), "3.0 is the int 3");
    assert_eq!(r(10, "add"), json!({"error": "add: integer out of range"}));
    assert_eq!(r(11, "add"), json!(0.30000000000000004));
    assert_eq!(r(12, "mul"), json!({"error": "mul: non-finite result"}));
    assert!(r(13, "add")["reject"].as_str().unwrap().starts_with("contract: a: expected float"));
    assert!(r(14, "add")["reject"].as_str().unwrap().contains("got null"), "null is a value, not absence");
    assert_eq!(r(15, "add"), json!({"escalate": "field 'b' not found in input"}));
    assert_eq!(r(16, "div"), json!(5));
    assert_eq!(r(17, "add"), json!(1));
    assert_eq!(r(18, "add"), json!(9007199254740994i64));
    assert_eq!(r(19, "add"), json!(9007199254740992i64));
    let timeouts: Vec<&Value> = (21..25).flat_map(|i| t[i]["context"]["last_outputs"].as_array().unwrap())
        .filter(|o| o["kind"] == "timeout").collect();
    assert_eq!(timeouts.len(), 1, "role_R4's escalation expires once, after its 3 ticks");
    assert_eq!(timeouts[0]["node"], "role_R4");
    assert_eq!(rce::canon::canonical_json(&t[20]["context"]["last_outputs"][0]["row"]["a"]), "1e-7");
}

fn scratch(name: &str) -> PathBuf {
    let d = Path::new(env!("CARGO_MANIFEST_DIR")).join("target").join("form-tests").join(name);
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(&d).unwrap();
    d
}

fn cargo() -> String {
    std::env::var("CARGO").unwrap_or_else(|_| "cargo".into())
}

fn run(cmd: &mut Command) -> String {
    let out = cmd.output().unwrap_or_else(|e| panic!("{:?}: {}", cmd, e));
    assert!(out.status.success(), "{:?}: {}", cmd, String::from_utf8_lossy(&out.stderr));
    String::from_utf8(out.stdout).unwrap().trim().to_string()
}

fn have(cmd: &str, arg: &str) -> bool {
    Command::new(cmd).arg(arg).output().map(|o| o.status.success()).unwrap_or(false)
}

fn wasm_target_installed() -> bool {
    Command::new("rustup").args(["target", "list", "--installed"]).current_dir(env!("CARGO_MANIFEST_DIR")).output()
        .map(|o| String::from_utf8_lossy(&o.stdout).lines().any(|l| l.trim() == "wasm32-wasip1")).unwrap_or(false)
}

#[test]
fn every_target_prints_the_reference_trace() {
    if std::env::var("RCE_FORM_SKIP_CARGO").is_ok() {
        eprintln!("RCE_FORM_SKIP_CARGO set: not building the emitted crate");
        return;
    }
    let ir = arith_ir();
    let dir = scratch("targets");
    let sets = [("edges.json", edge_events()), ("random.json", random_events(500, 4242))];
    for (f, e) in &sets { std::fs::write(dir.join(f), serde_json::to_string(e).unwrap()).unwrap(); }
    let reference: Vec<String> = sets.iter().map(|(_, e)| rce::canon::canonical_json(&emit_rust::reference_trace(&ir, e))).collect();
    let mut checked: Vec<&str> = vec![];

    // Rust, native.
    let krate = dir.join("crate");
    emit_rust::write(&krate, &emit_rust::emit(&ir)).unwrap();
    for (i, (f, _)) in sets.iter().enumerate() {
        let t = run(Command::new(cargo()).args(["run", "-q", "--bin", "form-trace", "--"]).arg(dir.join(f))
            .current_dir(&krate).env_remove("CARGO_TARGET_DIR"));
        assert_eq!(t, reference[i], "Rust vs reference on {}", f);
    }
    checked.push("Rust");

    // Python.
    if have("python3", "--version") {
        let py = dir.join("python");
        emit_python::write(&py, &emit_python::emit(&ir)).unwrap();
        let m = format!("{}.py", emit_python::module_name(&ir));
        for (i, (f, _)) in sets.iter().enumerate() {
            let t = run(Command::new("python3").arg(&m).arg(dir.join(f)).current_dir(&py));
            assert_eq!(t, reference[i], "Python vs reference on {}", f);
        }
        run(Command::new("python3").args(["-m", "unittest", "-q", "test_form"]).current_dir(&py));
        checked.push("Python");
    } else {
        eprintln!("python3 not found: Python target not checked");
    }

    // WASM through Rust, under node's WASI.
    if wasm_target_installed() && have("node", "--version") {
        run(Command::new(cargo()).args(["build", "-q", "--release", "--target", "wasm32-wasip1", "--bin", "form-trace"])
            .current_dir(&krate).env_remove("CARGO_TARGET_DIR"));
        let wasm = krate.join("target/wasm32-wasip1/release/form-trace.wasm");
        for (i, (f, _)) in sets.iter().enumerate() {
            let t = run(Command::new("node").arg("--no-warnings").arg("wasi-run.mjs").arg(&wasm).arg(dir.join(f)).current_dir(&krate));
            assert_eq!(t, reference[i], "WASM vs reference on {}", f);
        }
        checked.push("WASM (wasm32-wasip1 under node WASI)");
    } else {
        eprintln!("wasm32-wasip1 target or node missing: WASM target not checked");
    }

    // XState and SCXML.
    let js = std::env::var("RCE_JS_DIR").or_else(|_| std::env::var("RCE_XSTATE_DIR")).ok().map(|d| Path::new(&d).join("node_modules"));
    if let Some(nm) = js {
        std::fs::write(dir.join("machine.xstate.json"), serde_json::to_string(&emit_xstate::export(&ir)).unwrap()).unwrap();
        std::fs::write(dir.join("form-xstate.mjs"), emit_xstate::RUNNER).unwrap();
        std::fs::write(dir.join("form-core.cjs"), emit_xstate::CORE).unwrap();
        std::fs::write(dir.join("machine.scxml"), emit_scxml::export(&ir)).unwrap();
        std::fs::write(dir.join("form-scxml.cjs"), emit_scxml::SCION_RUNNER).unwrap();
        #[cfg(unix)]
        std::os::unix::fs::symlink(&nm, dir.join("node_modules")).unwrap();
        for (i, (f, _)) in sets.iter().enumerate() {
            if nm.join("xstate").exists() {
                assert_eq!(run(Command::new("node").args(["form-xstate.mjs", "machine.xstate.json", f]).current_dir(&dir)),
                    reference[i], "XState vs reference on {}", f);
            }
            if nm.join("@scion-scxml/scxml").exists() {
                assert_eq!(run(Command::new("node").args(["form-scxml.cjs", "machine.scxml", f]).current_dir(&dir)),
                    reference[i], "SCXML (SCION) vs reference on {}", f);
            }
        }
        if nm.join("xstate").exists() { checked.push("XState"); }
        if nm.join("@scion-scxml/scxml").exists() { checked.push("SCXML (SCION)"); }
    } else {
        eprintln!("RCE_JS_DIR not set: XState and SCXML targets not checked");
    }
    eprintln!("same trace in {:?} on {} edge + {} random events", checked, sets[0].1.len(), sets[1].1.len());
}
