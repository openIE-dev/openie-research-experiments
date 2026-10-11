//! The conformance gate as tests: `cargo test -p flowg-conformance` now runs.

use flowg_conformance::{check_against_reference, corpus::full_corpus, run_corpus, spec_edge_corpus, RunOptions, Verdict};

#[test]
fn every_executor_matches_the_reference_on_the_spec_edges() {
    let corpus = spec_edge_corpus();
    assert!(corpus.len() >= 30, "edge corpus too small: {}", corpus.len());
    let bad = check_against_reference(&corpus);
    assert!(bad.is_empty(), "{} mismatches:\n{bad:#?}", bad.len());
}

#[test]
fn scalar_corpus_matches_the_reference() {
    let corpus: Vec<_> = full_corpus().into_iter().filter(|c| c.name.starts_with("scalar/")).collect();
    assert!(!corpus.is_empty());
    let bad = check_against_reference(&corpus);
    assert!(bad.is_empty(), "{bad:#?}");
}

#[test]
fn full_corpus_cpu_sync_and_async_agree() {
    let opts = RunOptions { skip_wgpu: true, ..Default::default() };
    let report = run_corpus(&full_corpus(), &opts);
    let failed: Vec<_> = report
        .iter()
        .filter(|l| matches!(l.verdict, Verdict::Diverge(_) | Verdict::Error(_)))
        .collect();
    assert!(failed.is_empty(), "{failed:#?}");
    assert!(report.len() > 20);
}
