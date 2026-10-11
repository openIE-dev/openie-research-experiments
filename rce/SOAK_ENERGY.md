# Energy-receipt soak (Track C): joules per closed task (est_j)

Run 2026-10-09 on the box, branch `rce/sota-core` at `8a4c462`, clean tree.
Preregistered in `bench/track-c.prereg.json` (sha256
`08b4da3c0dfac53f769fb348651e0619ec570ba310def3ade1316f59cc8a1be9`,
matched the committed lock file). Five example specs × {mock, gear stack}
× seed 42 × 20 rounds, `--auto-approve soak`. No API keys, no network:
the bench strips key and endpoint variables from each child run, so G3,
G4 and G5 are off. Reproduce with:

```
cargo build && scripts/energy_soak.sh soak-energy
# = rce bench track-c bench/track-c.prereg.json --out soak-energy
```

Every artifact is kept in `bench/results/track-c-2026-10-09/`: per run
`energy.csv`, `stdout.log`, `stderr.log`, `persist/` (graph.json +
GraphLog), `cassette/cassette.jsonl`, and for the gear stack
`library.json`; plus `manifest.json` and `REPORT.md` (per-run round
tables). measured_j is empty in every row of every CSV.

## What changed since the previous soak

- The example specs now have `flow` edges, so a task walks
  dependency → role(s) → deliverable. est_j per closed task is the cost
  of the whole path (about 2–5 nJ), not one passthrough (0.517 nJ).
- Each round now settles: after the 5 inject+tick steps the harness ticks
  until nothing is in flight (`settle_ticks` column, at most 64). A
  node takes one message per tick, so without this the fan-in nodes
  built a backlog. The first Track C run, at `126167a` before this fix,
  is kept in `bench/results/track-c-2026-10-09-run1-backlog/`: there,
  open tasks grew by 5 per round (web-api ended with 91 open). That run
  is a harness bug, not a result, and is reported here so it isn't lost.
- Escalations are deduped per (node, shape) and nodes with a queued
  approval or shadow candidate are held, so round 1 no longer promotes
  the same node once per pending escalation.
- Promotions pass a coverage shadow run (rule of three at the default 5%
  budget, 60 synthetic same-shape samples). Its cost is in the foreman
  est_j column for both foremen.

## Hypotheses (from the preregistration) and outcome

| | hypothesis | outcome |
|---|---|---|
| H1 | gear stack resolves everything from G0–G2; G3–G5 count zero | **held**. G0 and G1 did all of it; G2 resolved nothing (see below) |
| H2 | gear stack has fewer AI-attributed promotions than mock | **held**. AI fraction at the end is 0.0% on all five specs vs 39–55% for mock, with the same promotion counts |
| H3 | each spec reaches a round with zero new escalations before round 20 | **held**. First quiet round 4–7, identical for both foremen |
| H4 | once quiet, est_j per closed task is flat; all-in falls to handler est_j | **held, with a caveat**. Flat on four specs; `follow-bible-ingest-schemas` moves with payload size (schema-generated inputs). All-in equals handler est_j from the first quiet round |
| H5 | measured_j empty in every row | **held** |

### Gear usage per round (gear stack; resolutions per gear, G3–G5 never fired)

| round | web-api | joule-db | fb-ingest | fb-schemas | ask-server | mock resolutions (all specs) |
|---:|---|---|---|---|---|---|
| 1 | G0 1 · G1 1 | G1 1 | G0 3 · G1 1 | G1 5 | G0 4 · G1 1 | 17 |
| 2 | G0 2 | G0 2 | G0 3 | G1 4 | G0 2 | 13 |
| 3 | G1 2 | G0 1 · G1 1 | G0 2 · G1 1 | G0 2 · G1 1 | G0 2 · G1 2 | 14 |
| 4 | — | G0 1 · G1 1 | G0 1 · G1 1 | G0 2 · G1 2 | G1 2 | 10 |
| 5 | — | G0 1 | G1 1 | G1 2 | — | 4 |
| 6 | — | G1 1 | — | — | — | 1 |
| 7 | — | — | — | — | — | 0 |
| 8 | — | — | — | — | — | 0 |
| 9 | — | — | — | — | — | 0 |
| 10 | — | — | — | — | — | 0 |
| 11 | — | — | — | — | — | 0 |
| 12 | — | — | — | — | — | 0 |
| 13 | — | — | — | — | — | 0 |
| 14 | — | — | — | — | — | 0 |
| 15 | — | — | — | — | — | 0 |
| 16 | — | — | — | — | — | 0 |
| 17 | — | — | — | — | — | 0 |
| 18 | — | — | — | — | — | 0 |
| 19 | — | — | — | — | — | 0 |
| 20 | — | — | — | — | — | 0 |

### Handler est_j per closed-ok task (nJ), per round — mock / gear stack

| round | web-api | joule-db | fb-ingest | fb-schemas | ask-server | measured_j |
|---:|---|---|---|---|---|---|
| 1 | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | empty |
| 2 | n/a / n/a | n/a / n/a | 0.517 / 0.517 | 1.813 / 2.276 | 0.517 / 0.517 | empty |
| 3 | n/a / n/a | n/a / n/a | 0.517 / 0.517 | 1.813 / 2.276 | 0.517 / 0.517 | empty |
| 4 | 2.068 / 2.068 | n/a / n/a | 1.034 / 1.034 | 2.714 / 3.065 | 0.862 / 0.862 | empty |
| 5 | 2.068 / 2.068 | n/a / n/a | 1.034 / 1.034 | 3.350 / 3.701 | 2.378 / 2.378 | empty |
| 6 | 2.068 / 2.068 | n/a / n/a | 2.327 / 2.327 | 5.285 / 5.615 | 2.378 / 2.378 | empty |
| 7 | 2.068 / 2.068 | 4.653 / 4.653 | 2.326 / 2.326 | 4.798 / 5.129 | 2.378 / 2.378 | empty |
| 8 | 2.068 / 2.068 | 4.653 / 4.653 | 2.327 / 2.327 | 5.027 / 5.357 | 2.378 / 2.378 | empty |
| 9 | 2.068 / 2.068 | 4.653 / 4.653 | 2.326 / 2.326 | 5.465 / 5.795 | 2.378 / 2.378 | empty |
| 10 | 2.068 / 2.068 | 4.653 / 4.653 | 2.327 / 2.327 | 5.153 / 5.483 | 2.378 / 2.378 | empty |
| 11 | 2.068 / 2.068 | 4.653 / 4.653 | 2.326 / 2.326 | 5.807 / 6.137 | 2.378 / 2.378 | empty |
| 12 | 2.068 / 2.068 | 4.653 / 4.653 | 2.327 / 2.327 | 5.302 / 5.633 | 2.378 / 2.378 | empty |
| 13 | 2.068 / 2.068 | 4.653 / 4.653 | 2.326 / 2.326 | 5.123 / 5.453 | 2.378 / 2.378 | empty |
| 14 | 2.068 / 2.068 | 4.653 / 4.653 | 2.326 / 2.326 | 5.429 / 5.759 | 2.378 / 2.378 | empty |
| 15 | 2.068 / 2.068 | 4.653 / 4.653 | 2.326 / 2.326 | 5.237 / 5.567 | 2.378 / 2.378 | empty |
| 16 | 2.068 / 2.068 | 4.653 / 4.653 | 2.327 / 2.327 | 5.044 / 5.375 | 2.378 / 2.378 | empty |
| 17 | 2.068 / 2.068 | 4.653 / 4.653 | 2.326 / 2.326 | 5.471 / 5.801 | 2.378 / 2.378 | empty |
| 18 | 2.068 / 2.068 | 4.653 / 4.653 | 2.326 / 2.326 | 5.639 / 5.969 | 2.378 / 2.378 | empty |
| 19 | 2.068 / 2.068 | 4.653 / 4.653 | 2.326 / 2.326 | 5.117 / 5.447 | 2.378 / 2.378 | empty |
| 20 | 2.068 / 2.068 | 4.653 / 4.653 | 2.326 / 2.326 | 5.296 / 5.627 | 2.378 / 2.378 | empty |

### All-in est_j per closed-ok task: handlers + foreman (nJ), per round — mock / gear stack

| round | web-api | joule-db | fb-ingest | fb-schemas | ask-server | measured_j |
|---:|---|---|---|---|---|---|
| 1 | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | empty |
| 2 | n/a / n/a | n/a / n/a | 37.741 / 65.348 | 112.693 / 148.515 | 12.925 / 22.644 | empty |
| 3 | n/a / n/a | n/a / n/a | 37.741 / 65.346 | 94.477 / 120.721 | 25.333 / 45.286 | empty |
| 4 | 2.068 / 2.068 | n/a / n/a | 13.442 / 23.677 | 51.866 / 66.203 | 9.134 / 15.956 | empty |
| 5 | 2.068 / 2.068 | n/a / n/a | 7.238 / 12.355 | 28.334 / 35.773 | 2.378 / 2.378 | empty |
| 6 | 2.068 / 2.068 | n/a / n/a | 2.327 / 2.327 | 5.285 / 5.615 | 2.378 / 2.378 | empty |
| 7 | 2.068 / 2.068 | 4.653 / 4.653 | 2.326 / 2.326 | 4.798 / 5.129 | 2.378 / 2.378 | empty |
| 8 | 2.068 / 2.068 | 4.653 / 4.653 | 2.327 / 2.327 | 5.027 / 5.357 | 2.378 / 2.378 | empty |
| 9 | 2.068 / 2.068 | 4.653 / 4.653 | 2.326 / 2.326 | 5.465 / 5.795 | 2.378 / 2.378 | empty |
| 10 | 2.068 / 2.068 | 4.653 / 4.653 | 2.327 / 2.327 | 5.153 / 5.483 | 2.378 / 2.378 | empty |
| 11 | 2.068 / 2.068 | 4.653 / 4.653 | 2.326 / 2.326 | 5.807 / 6.137 | 2.378 / 2.378 | empty |
| 12 | 2.068 / 2.068 | 4.653 / 4.653 | 2.327 / 2.327 | 5.302 / 5.633 | 2.378 / 2.378 | empty |
| 13 | 2.068 / 2.068 | 4.653 / 4.653 | 2.326 / 2.326 | 5.123 / 5.453 | 2.378 / 2.378 | empty |
| 14 | 2.068 / 2.068 | 4.653 / 4.653 | 2.326 / 2.326 | 5.429 / 5.759 | 2.378 / 2.378 | empty |
| 15 | 2.068 / 2.068 | 4.653 / 4.653 | 2.326 / 2.326 | 5.237 / 5.567 | 2.378 / 2.378 | empty |
| 16 | 2.068 / 2.068 | 4.653 / 4.653 | 2.327 / 2.327 | 5.044 / 5.375 | 2.378 / 2.378 | empty |
| 17 | 2.068 / 2.068 | 4.653 / 4.653 | 2.326 / 2.326 | 5.471 / 5.801 | 2.378 / 2.378 | empty |
| 18 | 2.068 / 2.068 | 4.653 / 4.653 | 2.326 / 2.326 | 5.639 / 5.969 | 2.378 / 2.378 | empty |
| 19 | 2.068 / 2.068 | 4.653 / 4.653 | 2.326 / 2.326 | 5.117 / 5.447 | 2.378 / 2.378 | empty |
| 20 | 2.068 / 2.068 | 4.653 / 4.653 | 2.326 / 2.326 | 5.296 / 5.627 | 2.378 / 2.378 | empty |

### Totals over 20 rounds

| spec | foreman | tasks in | closed ok | closed esc | promotions | G0 | G1 | G2 | G3–G5 | foreman est_j (nJ) | handler est_j (nJ) | first quiet round | AI fraction (end) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| web-api | mock | 200 | 170 | 30 | 6 | 0 | 0 | 0 | 0 | 372.2 | 404.6 | 4 | 42.9% |
| web-api | geared | 200 | 170 | 30 | 6 | 3 | 3 | 0 | 0 | 653.4 | 404.6 | 4 | 0.0% |
| joule-db-core | mock | 100 | 70 | 30 | 9 | 0 | 0 | 0 | 0 | 558.4 | 432.6 | 7 | 39.1% |
| joule-db-core | geared | 100 | 70 | 30 | 9 | 5 | 4 | 0 | 0 | 972.4 | 432.6 | 7 | 0.0% |
| follow-bible-ingest | mock | 400 | 330 | 70 | 13 | 0 | 0 | 0 | 0 | 806.5 | 878.5 | 6 | 46.4% |
| follow-bible-ingest | geared | 400 | 330 | 70 | 13 | 9 | 4 | 0 | 0 | 1420.1 | 878.5 | 6 | 0.0% |
| follow-bible-ingest-schemas | mock | 400 | 330 | 70 | 18 | 0 | 0 | 0 | 0 | 2536.3 | 1957.6 | 6 | 54.5% |
| follow-bible-ingest-schemas | geared | 400 | 330 | 70 | 18 | 4 | 14 | 0 | 0 | 3677.8 | 2083.2 | 6 | 0.0% |
| ask-server | mock | 500 | 435 | 65 | 13 | 0 | 0 | 0 | 0 | 806.5 | 1128.7 | 5 | 46.4% |
| ask-server | geared | 500 | 435 | 65 | 13 | 8 | 5 | 0 | 0 | 1435.6 | 1128.7 | 5 | 0.0% |

## Reading these numbers

- **est_j only.** Handler figures are interpreter op counts priced with
  FGIR's table for the host (`rce-interp-v1`, `x86_64-intel-spr` on this
  box). Allocation, hashing and JSON tree walking are not in the figure.
- **Foreman est_j is not comparable across the two foremen.** The gear
  stack prices its own work (lookups, rule derivation, gate pre-checks).
  The mock foreman's own reasoning is unpriced; its column is only the
  coverage shadow runs the engine does for any foreman. So the gear stack
  looks dearer per round in the convergence phase (1.45–1.78× mock).
  Both are under 4 µJ total per spec for 20 rounds.
- **G2 resolved nothing.** Synthesis needs a JSON output schema; the
  example specs give deliverables type names (`"HttpResponse"`) and only
  `follow-bible-ingest-schemas` has JSON input schemas. G1 rules caught
  every case first. G2 is covered by unit tests, not by this soak.
- **The gear stack's handlers cost a little more per task on
  `follow-bible-ingest-schemas`** (5.63 vs 5.30 nJ at round 20): G1
  installs `Validate` on schema'd nodes, which checks required fields
  that mock's passthrough doesn't. That is the price of the check.
- **Same convergence, different attribution.** Both foremen promote the
  same number of handlers and go quiet in the same round. The gear stack's
  answers are logged as System because they are deterministic rules and
  library hits; mock's are logged as AI even though mock is heuristic.
  The difference in AI fraction is attribution, not a different outcome.
- No convergence failures, blocked promotions or retirement
  recommendations occurred in any run.

## Previous soak (single-hop graphs, mock only), kept for comparison

(The `energy_soak.sh` arguments below are the old ones; the script now runs Track C.)

Run 2026-10-09, branch `rce/sota-core`. Mock foreman: no API keys, no
model calls. Seed 42, 20 rounds, 5 example specs, `--auto-approve soak`.
Reproduce with:

```
cargo build && scripts/energy_soak.sh 20 42 soak-results/energy-seed42
```

Re-running with the same seed produced byte-identical CSVs. Per-round
CSVs are in `soak-results/energy-seed42/`.

### What the numbers are

- **est_j only.** Handler figures come from the metered HandlerSpec
  interpreter: op counts on the path actually taken (calls, returns,
  8-byte word loads/stores, compares, conditional branches) priced with
  FGIR's own per-instruction table for the host. Model
  `rce-interp-v1`; host `x86_64-linux`, table `x86_64-intel-spr` (this
  run was on the box, not the Mac; on Apple Silicon the `arm64-apple`
  table is used). Interpreter overhead the counts don't see
  (allocation, hashing, the JSON tree walk itself) is not in the figure.
- **measured_j: empty.** Nothing in the engine reads a power counter.
  The CSV column exists and is blank on every row.
- **Task** = one injected input. It closes when its last queued message
  is consumed; **closed ok** if no hop escalated or errored.
- **LLM est_j**: 0 calls in this soak (mock foreman). That is "no calls",
  not "0 J per call". With the federated foreman the column carries
  verity-llm's `LlmEnergyCost` point estimate per call; Claude-direct
  calls are counted with tokens and no estimate (unpriced).

### est_j per closed-ok task, by round (nanojoules)

| round | web-api | joule-db-core | follow-bible-ingest | follow-bible-ingest-schemas | ask-server |
|---|---|---|---|---|---|
| 1 | n/a (10 esc) | n/a (5 esc) | n/a (20 esc) | n/a (20 esc) | n/a (25 esc) |
| 2 | 0.517 | 0.517 | 0.517 | 1.369 | 0.517 |
| 3 | 0.517 | 0.517 | 0.517 | 1.435 | 0.517 |
| 4 | 0.517 | 0.517 | 0.517 | 1.273 | 0.517 |
| 5 | 0.517 | 0.517 | 0.517 | 1.411 | 0.517 |
| 6 | 0.517 | 0.517 | 0.517 | 1.345 | 0.517 |
| 7 | 0.517 | 0.517 | 0.517 | 1.267 | 0.517 |
| 8 | 0.517 | 0.517 | 0.517 | 1.357 | 0.517 |
| 9 | 0.517 | 0.517 | 0.517 | 1.399 | 0.517 |
| 10 | 0.517 | 0.517 | 0.517 | 1.351 | 0.517 |
| 11 | 0.517 | 0.517 | 0.517 | 1.561 | 0.517 |
| 12 | 0.517 | 0.517 | 0.517 | 1.411 | 0.517 |
| 13 | 0.517 | 0.517 | 0.517 | 1.399 | 0.517 |
| 14 | 0.517 | 0.517 | 0.517 | 1.381 | 0.517 |
| 15 | 0.517 | 0.517 | 0.517 | 1.351 | 0.517 |
| 16 | 0.517 | 0.517 | 0.517 | 1.357 | 0.517 |
| 17 | 0.517 | 0.517 | 0.517 | 1.441 | 0.517 |
| 18 | 0.517 | 0.517 | 0.517 | 1.501 | 0.517 |
| 19 | 0.517 | 0.517 | 0.517 | 1.375 | 0.517 |
| 20 | 0.517 | 0.517 | 0.517 | 1.399 | 0.517 |

Round 1 closes no task ok: every source starts on a stub, every input
escalates, and the mock foreman promotes a passthrough. From round 2 on,
every task closes ok.

### Totals over 20 rounds

| spec | tasks in | closed ok | closed escalated | handler est_j total (nJ) | est_j / closed-ok task (nJ) | promotions | LLM calls | AI fraction (end) |
|---|---|---|---|---|---|---|---|---|
| web-api | 200 | 190 | 10 | 108.2 | 0.517 | 10 | 0 | 55.6% |
| joule-db-core | 100 | 95 | 5 | 54.1 | 0.517 | 5 | 0 | 26.3% |
| follow-bible-ingest | 400 | 380 | 20 | 216.4 | 0.517 | 20 | 0 | 57.1% |
| follow-bible-ingest-schemas | 400 | 380 | 20 | 562.2 | 1.389 | 20 | 0 | 57.1% |
| ask-server | 500 | 475 | 25 | 270.5 | 0.517 | 25 | 0 | 62.5% |

### What this run shows, and what it doesn't

- The mock converges in one round on every spec, so per-task est_j is
  flat after round 1. It is a check that the receipts are wired end to
  end, not evidence of learning.
- **All five example graphs compile with 0 edges.** A task is therefore a
  single hop at a source node, and est_j per task is the cost of one
  passthrough over the payload: 0.517 nJ for `{"round": N}`, about
  1.3–1.6 nJ for the schema-generated payloads of
  `follow-bible-ingest-schemas` (it varies with payload size, which is
  why that column moves round to round).
- Round 1 promotes the same source node once per pending escalation
  (5 injections → 5 promotions per source). That is existing behavior.
- Every handler installed at the end passed the property run (64 seeded
  cases each, 0 failures), and no promotion was refused by the path.
  Step 3 (currency) records `fail(recorded)` on every promotion: none of
  the example specs has a recorded currency check.
