# The Form: laws and compiler

The design is in `program-form-fit.md` (sections 4 and 5). This file says
what the code does on branch `rce/sota-core`, what is tested, and what is
not done.

A program's Form is P = (S, E, δ, D, λ): states, events, a pure step
δ : S × E → S, a log D of events, outputs λ. The law everything below
serves: **state = foldl(δ, s0, L)**. RCE uses the agentic era (a foreman
proposes handlers) without being driven by it: whatever the foreman
proposes enters as a logged event, and the state is still a fold of the
log.

## Part 1. The engine obeys the Form laws

| Law | What the engine does | Code | Test (tests/form_laws.rs) |
|---|---|---|---|
| Reload is a verified fold | `attach_store` reads `log.jsonl` verbatim (`GraphLog::from_entries`), recomputes every hash and link, checks that the stored prefix matches the engine's own log, then folds the rest with δ. Nothing is re-stamped; the file is not rewritten. A broken chain refuses to load. Legacy (v0) logs are adopted verbatim with their graph snapshot. | persistence.rs `load_log`; engine.rs `reload_from`, `fold_log` | `law1_reload_folds_and_never_restamps`, `law1_tampered_payload_fails_reload` |
| Deterministic, name-free tick order | Handlers run in topological rank order; within a rank by a name-free node key (kind, schemas, handler spec with the node's own id replaced by `<self>`). Outputs are staged and delivered after all handlers ran (ASM: every update reads the pre-state). One hop per tick. | engine.rs `topo_ranks`, `node_key`, `step_order`, `step` | `law2_order_and_hashes_do_not_depend_on_names` (every node renamed; same anonymous state hash at every entry), `law2_staged_delivery_moves_one_hop_per_tick` |
| No silent drop | A full mailbox holds the message in an ordered per-mailbox queue and logs `Backpressure {from, to, task_id, payload_sha256, held}`; held messages are released first on later ticks. `inject` refuses past `held_limit` instead of dropping. A message for a node with no mailbox logs `HandlerFault`. | comms.rs `offer`, `release_held`; engine.rs `deliver` | `law3_full_mailbox_logs_backpressure_and_loses_nothing` (capacity 1, 10 tasks, 9 Backpressure entries, 10 tasks closed ok) |
| Payloads are in the log | `Inject`, `Tick {tick}`, `ExternalResult` (result of a handler with no spec, e.g. a process/HTTP handler, keyed by input SHA-256), `InstallHandler`, `HandlerFault`, `HeartbeatFault`, `Backpressure`, `Record` are log entries. Derived entries are re-emitted by δ on replay and compared by content. | graph/mutation.rs; engine.rs `commit`, `emit`, `apply_input` | `law4_fold_reproduces_state_hash_after_every_entry` (hash after every entry, live vs fold from an empty engine), `law4_fold_law_on_random_logs` (RCE_FOLD_CASES, default 200; 1000 checked), `law4_two_runs_write_the_same_log` |
| Logical clock | Liveness counts ticks, not wall time: a node is silent when it has waiting input and made no progress for `interval_ticks × max_missed` ticks; the fault fires once per period and is logged. Idle ticks advance the clock without a log entry; a Tick entry carries its number. | comms.rs `HeartbeatMonitor` | comms unit tests `heartbeat_monitor_detects_silence_on_logical_ticks`, `heartbeat_resets_on_signal` (no `sleep`) |
| Stable hashes | SHA-256 over canonical JSON (keys sorted at every depth) for entry hashes (`hash_v` 2: {v, seq, tick, actor, mutation, prev_hash, approved_by}; the wall-clock timestamp is kept but not hashed), state hashes, shape hashes and rule ids. | canon.rs; graph/log.rs | `law6_entry_hashes_are_sha256_of_canonical_json`, canon unit tests |

Outside the fold, stated plainly: the daemon's tick task fires on a
100 ms wall-clock timer (it decides *when* a Tick event happens, not what
it does); entry timestamps are informational; closures without a
HandlerSpec are outside δ, so their results enter the log as
`ExternalResult` and replay reads them from there.

## Part 2. The Form compiler (`src/form/`, `rce form`)

```
.rce spec + handler fit (terms, input types, relation keys)
   ─ lower ─► paths: every source→sink data-flow path composed into one term
   ─ normalize (pipes right-associated, pass stages dropped, numbers normalized)
   ─ egg e-graph, equality saturation (+ admitted proposals) ─ extract (cost = est_j) ─►
   Form IR (typed relations, regions, contracts, rules with SHA-256 ids, oracles)
   ├─ Rust crate   pure step, typed Σ, SHA-256 log + fold, tests, form-trace bin
   │  └─ WASM      the same crate for wasm32-wasip1, run under node's WASI
   ├─ Python       one module per Form + test_form.py, standard library only
   ├─ XState v5    machine JSON + runner, on the shared JS core
   └─ SCXML        <parallel> of regions, ecmascript datamodel, same JS core, run by SCION
```

Every target is generated; none is authored. `tests/form_targets.rs`
requires all five targets to print the reference trace byte for byte.

| File | Role |
|---|---|
| form/ir.rs | Term (pass, const, proj, wrap, if_has, if_eq, pipe, obj, arith, oracle, esc, err), Rule, FormIr, FormState, the reference δ/λ |
| form/num.rs | the edge semantics of numbers (below); embedded verbatim in the Rust crate |
| form/types.rs | Ty (int, float, text, bool, json, record), inference over terms, payload checks |
| form/fit.rs | the fit file: `handlers`, `types` (input contracts), `keys` (relation keys) |
| form/lower.rs | HandlerSpec/term → paths; guard lifting; name-free rule ids; relations; oracles from `ExternalResult` |
| form/laws.rs | IR checks (only input/tick/resolve events, ids unique per event, content-hash order, CALM tag, SHA-256 log) |
| form/egraph.rs | egg language, `Total` e-class analysis, rewrites, normalization, saturation |
| form/equiv.rs | the randomized check that admits or rejects a proposed equivalence |
| form/extract.rs | est_j cost per constructor from the FGIR host cost table |
| form/emit_rust.rs, emit_python.rs, emit_xstate.rs, emit_scxml.rs; rt/form_core.js, rt/form_core.py | emitters and the two runtime cores |
| brownfield/lift.rs | `rce scan DIR --form`: Rust/Python/TypeScript/Go → relations, regions, events, transitions |

### The Form IR

- **Σc**: one region per node, `Ready | Escalated`.
- **Σd**: the logical clock, an input count, and **typed Codd relations**.
  A sink's relation gets columns from the type inferred for its output
  (`types` gives the input contracts); its key comes from the fit's
  `keys`, else the implicit key (`seq` = input number, `n` = index within
  the step). `escalation(node, input, reason, opened, expired)` keyed by
  (node, input, reason) and `error(node, input, message, at)` keyed by
  (node, input, message). Rows upsert by key; a relation iterates in the
  order of the canonical JSON of its key, in every target.
- **E**: `IN_<source>`, `TICK`, `RESOLVE_<node>`. An input event counts
  the input, normalizes the payload, checks the contract (a mismatch is
  a `reject` output and an `error` row) and runs the rules in order;
  identical escalations and errors in one step count once. `TICK`
  advances the clock; an escalation expires after its node's timeout
  (spec `timeout` in ticks of a nominal 100 ms, rounded up) and emits
  `timeout`. `RESOLVE_n` returns the region to Ready and deletes its
  escalation rows.
- **Π**: per path, the extracted term split at top-level `if_has` into
  guarded rules. Rule id = SHA-256 of the canonical rule with node names
  replaced by path positions; renaming every node leaves the ids
  unchanged (tested).
- **D**: entry = canonical JSON {seq, event, prev_hash, state_hash};
  hash = SHA-256.

### Edge semantics (form/num.rs)

There is one defined behavior per edge, and each emitter reproduces it:

| Edge | The Form | Note |
|---|---|---|
| int overflow | error "integer overflow" (checked i64) | never wraps |
| `/` on ints | truncates toward zero (`-7 / 2 = -3`) | Python's `//` floors; the Python core does not use it |
| `%` on ints | sign of the dividend (`-3 % 2 = -1`) | Python's `%` gives 1 |
| `i64::MIN / -1`, `i64::MIN % -1` | overflow | follows Rust's checked ops |
| division by zero | error "division by zero" | ints, and `fdiv` on anything |
| float ops | IEEE f64; `%` is fmod; a non-finite result is an error | NaN and inf never enter state |
| `fadd fsub fmul fdiv` | always f64 (`a as f64 op b as f64`) | how f64 code is re-expressed |
| `min max` | exact on two ints, f64 otherwise | |
| 3.0, -0.0 | normalized at the boundary to 3, 0 | an integral float below 2^63 is an int |
| ints beyond i64 | u64 above i64::MAX is "integer out of range"; beyond u64, a float | JS parses losslessly (BigInt) |
| float text | serde_json's (`1e+300`, `1.5e-7`); parsing is exact in every target (`float_roundtrip`) | pinned by `float_text` |
| null vs absent | different: null is present; absent makes `proj` escalate | |
| time | the logical clock only (`TICK`) | no target reads a wall clock |

`tests/form_targets.rs` drives `examples/form-arith.rce` (eleven
operators) with 29 edge events plus 500 seeded random edge values. The
generated Rust, Python, WASM, XState and SCXML targets all print the
reference trace byte for byte.

### Every handler compiles

A handler with a spec lowers to a term. A process, HTTP or closure
handler has no term; its `ExternalResult` log entries become an
**oracle**. The oracle carries a typed contract: the input type is
narrowed from upstream, and the output type is the join of the recorded
Ok results. It also carries a table of recorded results keyed by the
SHA-256 of the canonical input. A recorded input replays the result,
and an unseen one escalates as "oracle miss". To record from a
persisted engine, run `rce form --store DIR`.
`opaque_handler_compiles_to_a_recorded_oracle` checks it against the
live engine.

### The e-graph

The compiler links **egg 0.10**, not egglog. Rewrites come from the fit
language's laws: `pipe-pass-l/r`, `esc-absorbs`, `err-absorbs`,
`wrap-proj`, `wrap-ifhas`, `ifhas-same`, `ifhas-nested-then/else`,
`ifhas-dist`, and `const-absorbs` (only when an e-class analysis proves
that x cannot fail). Associativity is not a rewrite. With the identity
laws it grew past 141,325 e-nodes. Pipes are instead right-associated
once, before saturation. The limits are an iteration count and an
e-node count, not wall-clock time.

**Proposed equivalences.** A foreman (`AiForeman::propose_equivalences`),
or a file passed with `--equivalences FILE.json`, proposes rewrite
pairs. Each pattern variable gets a role from its position. The pair is
checked on 300 random instantiations × 12 inputs, where an outcome
includes which node fails. A pair with no counterexample enters the
e-graph as `proposed:<name>`, labeled "unproven: no counterexample in N
randomized trials". A rejected pair keeps its counterexample. The mock
foreman proposes two sound pairs and three unsound ones. The check
admits the two sound pairs and rejects all three unsound ones.
`add-commutes` is rejected because the fault order changes which node
reports. `--foreman-proposals mock` shows this.

Two more proposers sit behind the same check, both off by default
(`form/propose.rs`). **System One** (`--foreman-proposals system-one`)
enumerates 87 familiar identities: commutativity, identities with 0 and
1, idempotence and associativity of all 11 arithmetic ops, plus 10
pipe/branch simplifications. The check admits 9 (all structural) and
rejects all 77 arithmetic ones (fault order, non-numbers, overflow).
**LLM** (`--foreman-proposals llm`) runs `RCE_LLM_PROPOSER_CMD` with a
prompt describing H on stdin and reads JSON lines back; other lines are
dropped and counted. `tests/form_proposers.rs` covers both with a
scripted command, not a live model.

Extraction uses egg's `Extractor` with `EstJ`: op counts priced by the
FGIR host cost table. **Every value is est_j (an estimate); measured_j
is always empty.** Soundness is tested, not proved: extracted and written
terms agree on random inputs.

### Targets

- **Rust crate**: typed relations, pure `step`, SHA-256 log + fold, tests
  (fold law on 500 random logs, replay, golden reference trace,
  properties over relations), and a `form-trace` bin. The bin streams
  its output in writes of at most 64 KiB; one 39 MB write crashed
  node's WASI.
- **WASM**: the same crate, built with `cargo +1.98.0 build --target
  wasm32-wasip1` (the target is installed for the repo toolchain) and run
  by the generated `wasi-run.mjs` under node's WASI.
- **Python**: `<form>.py` + `test_form.py` on `rt/form_core.py` (standard
  library only; arithmetic without `//` and `%`).
- **XState v5** and **SCXML**: both run on one ES5 core
  (`rt/form_core.js`, written out as `form-core.cjs`): lossless JSON
  parsing (BigInt past 2^53), SHA-256, types, arithmetic, δ. The SCXML
  document embeds the core in its datamodel and is **executed by SCION**
  (`@scion-scxml/scxml` 4.3), not only checked for well-formedness. Set
  `RCE_JS_DIR` to a directory with `node_modules/{xstate,@scion-scxml/scxml}`.

### Brownfield lift (`rce scan DIR --form [--out FILE] [--check TRACE.jsonl]`)

tree-sitter (Rust 0.24, Python 0.25, TypeScript 0.23, Go 0.25) reads
existing code into the Form's schema:

- **relations**: struct, class, interface and dataclass fields, typed,
  keyed by `id`/`*_id` when there is one;
- **regions**: enum-typed fields, with the initial state from the
  constructor or default;
- **events**: methods that mutate the receiver;
- **transitions**: guards in DNF over state sets and parameter
  presence (`is_some`, `is not None`, `!== undefined`, `!= nil`). Calls
  to the receiver's own methods are inlined (`settle → pay`), and
  anything else is kept as an opaque guard.

Every element is labeled **unproven (syntactic lift)**.
`Lifted::step` interprets the transitions and refuses to step through an
opaque guard. `--check` replays a JSON-lines trace recorded from the
original program and reports the first disagreement.

Evidence:

- `tests/brownfield_lift.rs` lifts the same order machine from Rust,
  Python, TypeScript and Go fixtures. It executes the original code
  (rustc, python3, tsc+node, go) on 40 seeded sequences of 30 calls.
  The original's state agrees with `Lifted::step` on all 1,200 calls
  per language.
- On a read-only copy of `crates/joule-sales-outreach` (11 files, 4,068
  lines), the lift finds 39 relations, 14 enum-typed regions and 23
  events. It finds 8 transitions, all on `Enrollment.status`, and
  inlines `advance_to → complete` under ¬next_step_id. The verbatim
  crate, driven by a harness (`examples/brownfield/enrollment_harness.rs.txt`),
  recorded 10,000 calls, and `--check` agrees on all of them. Mutating
  one recorded state is caught.

### Frozen benchmark (`bench/forms`)

`PREREG.json` was committed before any result. Three
joule-sales-outreach programs were re-expressed as Forms. The original
code ran verbatim on the preregistered inputs (`recorded/`), and
`tests/form_bench.rs` replays those inputs:

| Program | Original LOC | Fit (JSON lines / term nodes) | est_j written → extracted | Agreement | Targets (first 200 events) |
|---|---|---|---|---|---|
| b1 SequenceMetrics rates | 30 | 208 / 36 | 1.69e-8 → 1.49e-8 J | 1000/1000 | Rust, Python, XState byte-identical |
| b2 SenderHealth reputation | 23 | 182 / 33 | 1.41e-8 → 1.21e-8 J | 1000/1000 | same |
| b3 Enrollment status (closed loop) | 47 | 167 / 26 | 1.42e-8 → 1.21e-8 J | 2500/2500 | same |
| b3full Enrollment, every written field (rule reads its row) | 51 | 875 / — | 7.58e-8 → 7.37e-8 J | 4000/4000 | same |

The benchmark found two bugs, both now fixed and pinned by tests. f64
operators were typed int on int inputs. serde_json's default float
parser was 1 ulp off on some inputs. Read the table with these limits:

- The fit is generated JSON, so its line count is larger than the
  original and is not authored code.
- est_j is an estimate, and the original has no est_j.
- b3 compares status only. b3full is a dated amendment to the prereg,
  added after b1-b3 were known. It compares status, current_step_id,
  next_step_at, step_history length, and whether `updated_at` was
  written. `updated_at` is wall-clock, so only the flag is compared.
- All 50 out-of-domain probes (u64 above i64::MAX) are rejected at the
  contract, while the original computes a float.

### The Form step and the engine

The Form step runs the whole data flow an input reaches; the engine runs
one hop per tick. `form_step_agrees_with_engine` injects random orders
into both and requires the same sink outputs, escalations and notify
messages per input.

### Rules read stored state

A fit can declare `"reads": {"<sink>": {"key": [payload fields], "into": "prev"}}`.
Each rule writing that sink first gets the sink's stored row, selected
by the key, as input field `prev` (null when there is no row). The row
is read from the state at the event's entry. That holds in every
target: reference δ, generated Rust, Python core, JS core. XState guards
and SCXML conds pass the current Form state. The row type is the fixed
point of inference given its own type. A read-modify-write rule is not
monotone, and the CALM law says so. The rule id covers the read.

### Limits

- Reads are of the rule's own sink, by full key. There is no join, no
  scan, and no read of another relation.
- The lift is syntactic and unproven. It follows writes through aliases
  of the receiver and of collection rows, chains sequential `if`s, drops
  enums that are never written, and types a TS `number` as int only
  when every write is provably integral. Calls are inlined only on the
  receiver. Writes inside loops and closures are not modeled.
- Code generated from a lifted machine (`--emit-machine`) inherits the
  lift's limits. It refuses where the lift refuses (opaque guards).
- Paths are enumerated (at most 512); data-flow cycles are refused.

## Demo

```
rce form examples/form-demo.rce --handlers examples/form-demo.fit.json --out form-out/orders
rce form examples/form-demo.rce --handlers examples/form-demo.fit.json --foreman-proposals mock --emit ir
rce scan ../joule-sales-outreach --form --out lift.json
```

Two feeds go into a validator, then a ledger writer and an auditor;
invalid orders escalate to the lead. The whole spec estimates
3.219e-8 J → 1.158e-8 J (est_j). The output directory holds the Rust
crate, the Python module, the XState and SCXML documents with their
runners, and `sample_events.json` (typed edge values, TICKs and
resolves). Every runner prints the same trace on it.
