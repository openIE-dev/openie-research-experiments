# Projections interop: results (critique 9)

Registered in `PREREG.json` (sha256 in `PREREG.json.sha256`, committed
before the run). Run on 2026-10-29 by `run.sh` at openIE-dev/rce
`72823dd2777cb9218c1d9e05706c7ceadae02df0` (branch
`claude/projections-interop`); the `before` binary is rce built from main at
`8ce91cea`. Machine and tool versions: `results/machine.txt` (Intel Xeon
2.30 GHz, 4 processors, shared with other jobs while it ran; CPython
3.13.16, Node v22.22.0, rustc 1.97.0). All tables: `results/summary.md`. The branch's next commit, `5525d04b`, adds the statement of the embedding to spec 10.5 and regenerated spec files, and changes no code.

Checks of the run commit's emitter change: `cargo test --release` of `emit` (7 pass, 1 ignored), `emit06` (2), `emit06b` (8) and `emit_run` (11 pass, 1 ignored; one later rerun had `js_runtime_agrees_with_run_main` stopped by its 120 s timeout at a load average near 150, and it passed when run again); the conformance suites `emit-python` and `emit-js` give 1,459 pass, 0 fail, 520 not applicable each, the counts of the committed whole-trace baseline.

## M4: do emitted programs embed in ordinary hosts?

Eleven event streams over eight programs of `spec/examples/`, each
transcript compared with `rce run FILE EVENTS` byte for byte
(`examples/interop/check.py`).

| Host | Before (main 8ce91cea) | After (72823dd2) |
|---|---|---|
| Python, asyncio TCP service | 2/11 (the import prints every example's observations) | 11/11 |
| Python, FastAPI | 2/11 | 11/11 |
| Python, numpy scalars | 2/11 | 11/11 |
| Rust, tokio TCP service | does not compile (E0603: `initial_state`, `event_fields`, `show_state` private) | 11/11 |
| JavaScript, `node:http` | 0/11 (no exports: `m.fuelReset is not a function`) | 11/11 |
| JavaScript, React `useReducer` under StrictMode | 0/11 | 11/11 |
| JavaScript, realm without `process` | 0/11 (`ReferenceError: process is not defined`) | 11/11 |
| hand-written Python / JavaScript / Rust | | 11/11 each |

P1 holds. The two Python passes before the change are the two programs
with no examples (16, 31), whose import prints nothing.

## M1: lines of emitted code against hand-written code

Counted lines (not blank, not only a comment). "program" is the emitted
code between the runtime and the example driver.

| Language | Runtime per file | Emitted program lines, all eight | Hand-written lines, all eight | Ratio | Range per program |
|---|---|---|---|---|---|
| Python | 2,017 | 496 | 117 | 4.2 | 2.5 to 6.4 |
| JavaScript | 1,955 | 594 | 86 | 6.9 | 4.1 to 14.6 |
| Rust | 2,004 | 1,176 | 194 | 6.1 | 4.4 to 8.1 |

Every emitted file is the runtime plus the program, so a whole emitted file
is 2,004 to 2,214 lines for programs whose hand versions are 5 to 30
lines. P2 holds.

## M2: glue each host needed

| Language | Adapter (written once) | Hosts | Total | Lines naming one program |
|---|---|---|---|---|
| Python | `rce_host.py` 80 | asyncio 52, FastAPI 34, numpy 18 | 184 | 0 |
| JavaScript | `rce_host.mjs` 77 | node:http 40, React component 36 + driver 16, no-`process` realm 22 | 191 | 0 |
| Rust | `adapter.rs` 100 | tokio service 98, bench 25 | 223 | 2 (the `programs!` list) |

The hand-written versions needed drivers of 51 (Python), 32 (JS) and 79
(Rust) lines, mostly display code to match `rce run`. P3 holds.

## M3: cost of one call at the boundary (ns)

Median over 5 repetitions of the mean per call over stream 0. Decode = JSON
text to the event value; encode = the state to JSON text (the Rust hand
version: display text).

| Language | Emitted decode | Emitted step | Emitted encode | Boundary share > 50% | Hand step | Emitted step : hand step |
|---|---|---|---|---|---|---|
| Python | 1,799 to 7,636 | 7,283 to 36,633 | 6,712 to 29,154 | 4 of 8 (40% to 61%) | 791 to 3,691 | 2.3 to 40.5 |
| JavaScript | 1,332 to 4,290 | 777 to 21,742 | 2,115 to 11,476 | 3 of 8 (34% to 82%) | 428 to 2,320 | 1.8 to 13.9 |
| Rust | 170 to 778 | 262 to 3,886 | 530 to 2,470 | 5 of 8 (40% to 74%) | 21 to 178 | 12.4 to 102.3 |

Per program figures are in `results/summary.md`. By the registered rule
(P4), the cost part of the critique holds for Rust (boundary share above
50% for 5 of 8 programs) and does not hold for Python (4 of 8) or
JavaScript (3 of 8). In absolute terms the boundary costs 0.7 to 3.2 µs per
call in Rust, 3.4 to 15.8 µs in JavaScript and 11.3 to 33.2 µs in Python. The
Rust share is high because the emitted step is short in absolute terms,
and the encode goes through the adapter's own conversion of the runtime's
values to `serde_json`. Not registered, but measured in the same run: the
emitted step is 1.8 to 102 times slower than the hand-written step (fuel
counting, range checks and copying values; that is critique 7's subject).
The figures come from one run on a shared machine; read them as orders of
magnitude.

## Where critique 9 holds

- **"Emitted code is not idiomatic": holds.** The program part is 4.2 to
  6.9 times the hand-written code, every file carries about 2,000 lines of
  runtime, names are positional (`s_5`, `l_n`), and values are the
  runtime's classes (`Int`, `Rec`, `Mp`, BigInt, `V::Int(i128, &str)`),
  not dataclasses, objects or structs.
- **"Does not work with ecosystem libraries": held on main, does not hold
  after a change of 20 added and 7 removed lines in the emitter.** As printed on main, no emitted
  file could be imported and used (M4, before). With the change, asyncio,
  FastAPI, numpy values, tokio, `node:http`, React and a realm without
  `process` drive the emitted step function with transcripts equal to the
  reference, and the glue is 184 to 223 lines per language, 0 to 2 of them
  specific to a program. The emit tests and the conformance emit suites
  pass with the change (emit-python and emit-js: 1,459 pass, 0 fail, 520 not
  applicable, as in the committed baseline).
- **The boundary leaks in ways the adapters must handle by hand:** a kept
  step is a display string with the error payload and the HC-21 cause lost;
  JavaScript JSON loses integers above 2^53 and writes -0.0 as `0` (which
  merged the two keys of `58_float_keys` until the adapter wrote numbers
  with `JSON.rawJSON`); the Python and JavaScript runtimes read `--fuel=`
  and `--trace` from the host's process arguments; the Rust file cannot be
  `include!`d and each file brings its own value type. These, with a
  proposed change each, are listed in `examples/interop/README.md` of the
  run commit.

## Not covered

PyTorch (not installed; numpy scalars stand in), TypeScript (the React host
is JavaScript), the Scala target, programs with tasks, actors, `par` or
`fn main`, and multi-writer hosts. The hand versions are checked only on the
eleven streams: they do not trap on overflow and have no fuel, so they are
not equivalent to the emitted code on every input.
