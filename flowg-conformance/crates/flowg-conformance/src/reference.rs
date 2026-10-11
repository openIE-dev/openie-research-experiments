//! Conformance against the **reference interpreter**.
//!
//! `lux_flowg::interpret::interpret_strict` is the reference interpreter for
//! flowG (see `docs/FLOWG-ARITHMETIC-SPEC.md`). Every other executor must
//! produce the same outcome on every case: the same value, or the same
//! fault class. This module builds the arithmetic spec v1 edge cases
//! (overflow, `MIN / -1`, `MIN % -1`, the modulo sign, division by zero,
//! IEEE float division, NaN) and checks the CPU VM (sync) and the async
//! scheduler against the reference.

use crate::corpus::{ConformanceCase, DtypeFamily};
use flowg_vm_backend_cpu::{interpret_with_config, InterpretConfig, Inputs, ScalarValue, Value};
use flowg_vm_scheduler::Backends;
use lux_flowg::graph::{FunctionGraph, GraphNode, OpKind, Param, Wire, WireKind};
use lux_flowg::interpret::{interpret_strict, EvalError, Value as RefValue};

/// The outcome class every executor must agree on.
#[derive(Debug, Clone, PartialEq)]
pub enum Outcome {
    Int(i64),
    /// Float compared by bit pattern, except that every NaN is equal.
    Float(u64),
    Bool(bool),
    Overflow,
    DivisionByZero,
    /// Any other error (type fault, unsupported op).
    OtherError,
}

fn float_outcome(v: f64) -> Outcome {
    if v.is_nan() {
        Outcome::Float(f64::NAN.to_bits())
    } else {
        Outcome::Float(v.to_bits())
    }
}

fn classify_message(msg: &str) -> Outcome {
    let m = msg.to_ascii_lowercase();
    if m.contains("overflow") {
        Outcome::Overflow
    } else if m.contains("division by zero") {
        Outcome::DivisionByZero
    } else {
        Outcome::OtherError
    }
}

/// Run the reference interpreter. Params bind positionally in graph order.
pub fn reference_outcome(case: &ConformanceCase) -> Outcome {
    let mut args = Vec::new();
    for node in &case.graph.nodes {
        if let GraphNode::Param(p) = node {
            let v = match case.inputs.get(&p.name) {
                Some(Value::Scalar(ScalarValue::I32(x))) => RefValue::I64(*x as i64),
                Some(Value::Scalar(ScalarValue::I64(x))) => RefValue::I64(*x),
                Some(Value::Scalar(ScalarValue::F32(x))) => RefValue::F64(*x as f64),
                Some(Value::Scalar(ScalarValue::F64(x))) => RefValue::F64(*x),
                Some(Value::Scalar(ScalarValue::Bool(x))) => RefValue::Bool(*x),
                _ => return Outcome::OtherError,
            };
            args.push(v);
        }
    }
    match interpret_strict(&case.graph, &args, None) {
        Ok(RefValue::I64(v)) => Outcome::Int(v),
        Ok(RefValue::F64(v)) => float_outcome(v),
        Ok(RefValue::Bool(b)) => Outcome::Bool(b),
        Ok(_) => Outcome::OtherError,
        Err(EvalError::IntegerOverflow) => Outcome::Overflow,
        Err(EvalError::DivisionByZero) => Outcome::DivisionByZero,
        Err(_) => Outcome::OtherError,
    }
}

fn vm_outcome(r: Result<Value, String>) -> Outcome {
    match r {
        Ok(Value::Scalar(ScalarValue::I32(v))) => Outcome::Int(v as i64),
        Ok(Value::Scalar(ScalarValue::I64(v))) => Outcome::Int(v),
        Ok(Value::Scalar(ScalarValue::F32(v))) => float_outcome(v as f64),
        Ok(Value::Scalar(ScalarValue::F64(v))) => float_outcome(v),
        Ok(Value::Scalar(ScalarValue::Bool(b))) => Outcome::Bool(b),
        Ok(_) => Outcome::OtherError,
        Err(e) => classify_message(&e),
    }
}

/// CPU VM, synchronous path.
pub fn cpu_sync_outcome(case: &ConformanceCase) -> Outcome {
    let cfg = InterpretConfig { leaves: &[], ops: &[], ..Default::default() };
    vm_outcome(interpret_with_config(&case.graph, &case.inputs, cfg).map_err(|e| format!("{e}")))
}

/// Async scheduler path.
pub fn cpu_async_outcome(rt: &tokio::runtime::Runtime, case: &ConformanceCase) -> Outcome {
    vm_outcome(
        rt.block_on(flowg_vm_scheduler::run_async(case.graph.clone(), case.inputs.clone(), Backends::default()))
            .map_err(|e| format!("{e}")),
    )
}

fn binary(name: &str, op: OpKind, ty: &str, a: ScalarValue, b: ScalarValue, family: DtypeFamily) -> ConformanceCase {
    let graph = FunctionGraph {
        name: name.into(),
        nodes: vec![
            GraphNode::Param(Param { name: "x".into(), data_type: ty.into() }),
            GraphNode::Param(Param { name: "y".into(), data_type: ty.into() }),
            GraphNode::Apply { op, output_type: ty.into(), bits_erased: None },
        ],
        wires: vec![
            Wire { from: 0, to: 2, port_in_idx: 0, wire_kind: WireKind::Move },
            Wire { from: 1, to: 2, port_in_idx: 1, wire_kind: WireKind::Move },
        ],
        output_node: 2,
        return_type: ty.into(),
    };
    let mut inputs = Inputs::new();
    inputs.insert("x".into(), Value::Scalar(a));
    inputs.insert("y".into(), Value::Scalar(b));
    ConformanceCase { name: name.into(), graph, inputs, family }
}

/// The arithmetic spec v1 edge corpus.
pub fn spec_edge_corpus() -> Vec<ConformanceCase> {
    use flowg_arith::IntOp;
    let mut out = Vec::new();
    for (op, a, b, _) in flowg_arith::int64_edge_cases() {
        let kind = match op {
            IntOp::Add => OpKind::Add,
            IntOp::Sub => OpKind::Sub,
            IntOp::Mul => OpKind::Mul,
            IntOp::Div => OpKind::Div,
            IntOp::Rem => OpKind::Rem,
            _ => continue,
        };
        out.push(binary(
            &format!("spec/i64/{op:?}({a},{b})"),
            kind,
            "i64",
            ScalarValue::I64(a),
            ScalarValue::I64(b),
            DtypeFamily::Int,
        ));
    }
    let (min, max) = (i32::MIN, i32::MAX);
    for (op, a, b) in [
        (OpKind::Add, max, 1),
        (OpKind::Sub, min, 1),
        (OpKind::Mul, min, -1),
        (OpKind::Div, min, -1),
        (OpKind::Rem, min, -1),
        (OpKind::Div, 5, 0),
        (OpKind::Rem, -7, 2),
        (OpKind::Div, -7, 2),
    ] {
        out.push(binary(
            &format!("spec/i32/{op:?}({a},{b})"),
            op,
            "i32",
            ScalarValue::I32(a),
            ScalarValue::I32(b),
            DtypeFamily::Int,
        ));
    }
    for (op, a, b) in [
        (OpKind::Div, 1.0, 0.0),
        (OpKind::Div, -1.0, 0.0),
        (OpKind::Div, 0.0, 0.0),
        (OpKind::Rem, -7.5, 2.0),
        (OpKind::Rem, 1.0, 0.0),
        (OpKind::Eq, f64::NAN, f64::NAN),
        (OpKind::Lt, f64::NAN, 1.0),
    ] {
        out.push(binary(
            &format!("spec/f64/{op:?}({a},{b})"),
            op,
            "f64",
            ScalarValue::F64(a),
            ScalarValue::F64(b),
            DtypeFamily::Float,
        ));
    }
    out
}

/// One disagreement with the reference.
#[derive(Debug, Clone)]
pub struct Mismatch {
    pub case: String,
    pub executor: &'static str,
    pub reference: Outcome,
    pub got: Outcome,
}

/// Check every case against the reference on the CPU VM (sync) and the
/// async scheduler. Returns the disagreements; empty means conformant.
pub fn check_against_reference(corpus: &[ConformanceCase]) -> Vec<Mismatch> {
    let rt = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .expect("tokio runtime");
    let mut out = Vec::new();
    for case in corpus {
        let reference = reference_outcome(case);
        for (executor, got) in [
            ("cpu·sync", cpu_sync_outcome(case)),
            ("cpu·async", cpu_async_outcome(&rt, case)),
        ] {
            if got != reference {
                out.push(Mismatch { case: case.name.clone(), executor, reference: reference.clone(), got });
            }
        }
    }
    out
}
