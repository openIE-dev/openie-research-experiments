# OpenIE research experiments

Reproducible material for the papers at https://research.openie.dev. The page https://research.openie.dev/data/ maps each result in each paper to a path here.

## Layout

| Path | Paper | Contents |
|---|---|---|
| `agency-run/` | Thermodynamic Bounds and an Optimal Tempo for Goal-Holding Agents, §8.11 | Preregistrations (v1, v2, v2 second machine), agent and meter code, task generator, analysis scripts, episode and receipt results, pilots |
| `rce/bench/track-a/` | The Reality Code Engine, §6.1 | Corpus20 task directories (each registration), preregistrations with SHA-256, solver patches and reports |
| `rce/bench/track-b/` | RCE §6.2 | RAPL energy runs: `results.jsonl` with raw and idle-subtracted joules, method and report |
| `rce/bench/results/` | RCE §6.3 | Track C soak results and energy receipts |
| `rce/bench/ladder/` | RCE §2.3 | LADDER.md, PREREG.json, RESULTS.md, report.py and per-rung results |
| `rce/bench/defects4j/` | RCE §8.1 | Defects4J harness, TBar port comparison, REVIEW.md and results |
| `rce/bench/forms/`, `rce/tests/form_targets.rs`, `rce/FORM.md` | RCE §4.5, §5.1 | Form compiler harness and the five-target differential test |
| `flowg-conformance/` | RCE §1 (flowG) | flowG cross-backend conformance suite, fixtures and the recorded 18 of 18 report |
| `rce/SOAK_RESULTS.md`, `rce/SOAK_ENERGY.md` | RCE §6.3, §6.4 | Soak model-call counts and energy receipts |

## Energy labels

`est_j` is an analytical estimate. `reported_j` is an operating-system or on-chip counter (RAPL, or the macOS per-process counter). `measured_j` is a wall or shunt meter on a named rail and is empty in every result here. Labels are never summed.

## Reproducing

Each run is fixed by its preregistration, whose SHA-256 sits beside it. `CHECKSUMS.sha256` covers every file in this repository (`sha256sum -c CHECKSUMS.sha256`). Absolute paths of the original hosts are written as `$BENCH_ROOT` and `$RUSTUP_HOME`. The macOS `powermetrics` plists of the agency run are not published, because they list every process on the host; their role in the paper (the package cross-check) is described in agency §8.11. The RCE engine source lives in its own project; the solver script used by Tracks A and B is `rce/scripts/track_a_solver.py`. Large corpora are pinned in `CORPORA.md`.

## License

Code Apache-2.0, data CC BY 4.0; see `LICENSE`.
