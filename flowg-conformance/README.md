# flowG cross-backend conformance

flowG is the standalone language project; RCE (research.openie.dev/papers/rce/) is its first academic demonstration. This directory holds the conformance gate every flowG backend must pass to be admitted: bit-equality and tolerance checks across CPU, WGPU and WASM backends and sync and async schedulers.

- `crates/flowg-conformance/`: the suite (Rust). It builds inside the flowG workspace; the backend crates it names are part of that workspace and are not copied here.
- `conformance-fixtures/`: fixtures by tier (A algorithmic, B transcendental, C ordering, D edge cases), plus AV scenario fixtures (Euro NCAP AEB and LSS, NHTSA phases) and a router fixture.
- `conformance-report.md`, `conformance-report.json`: the recorded run, 18 of 18 fixtures passed (tier B).
- `.github/workflows/mgai-conformance.yml`: the CI job that runs it.

Taken from the flowG workspace at commit a1d416104 (committed files only).
