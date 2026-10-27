# Emit targets at the edges of 6.3 (track T4): results

Differential test of the program emit targets of spec 10.5 against the
reference evaluator, on a module written from spec 6.3 and 5.15. The scope
is T9-L (the program emitters). No claim is made here for a Form IR target
(T9-F), for XState or SCXML, or for a target that did not run.

## Registration and run

| Item | Value |
|---|---|
| Preregistration | `PREREG.json`, sha256 `0bb9fdeb6013ce01195532fd1f84e7ea8b4a00cf0393891cfeb8a1a49e4f1bef`, commit `675e01b` (committer time 2026-10-27T06:11:13Z), pushed before the run. Its field `registered` reads 06:12Z, an estimate written before the commit; the commit time is the time of record. |
| Code under test | openIE-dev/rce `2aad87f6c6a3733badeefb2d75fbd544305f1142` (branch `claude/rebuild-t4-emit-edges`, parent `d2b28e76`) |
| Command | `rce/bench/emit-edges/run.sh` (a clean fetch of the run commit, `cargo test --release --test emit_edges`, `summarize.py`) |
| Run | 2026-10-27T06:11:33Z to 06:19:22Z, on the host of `PREREG.json` (rustc 1.98.1 with wasm32-wasip1, Python 3.13.16, Node v22.22.0; no scala-cli, no wasmtime) |
| Summary digest | `dc7170401ebbb9a8da8992dabd8711bb5dd5470fd6a2113251689f4495b12f95` (`results/summary.json.sha256`) |

## Outcome

The module (76 operators, 159 edge examples, 500 seeded examples with 843
values from seed `0x63ed6e20261027`, and one text holding every 97th
Unicode scalar value; 660 examples, 118 of which end in a trap) is admitted
by `rce check`: the reference evaluator gives every outcome the module
states.

| Target | Outcome | Line for line | Byte for byte | Heads of D |
|---|---|---|---|---|
| rust (rustc 1.98.1, native) | agrees | 1,980 of 1,980 lines | 181,183 of 181,183 bytes | 660 of 660 |
| python (3.13.16) | agrees | 1,980 of 1,980 | 181,183 of 181,183 | 660 of 660 |
| js (Node v22.22.0) | agrees | 1,980 of 1,980 | 181,183 of 181,183 | 660 of 660 |
| wasm32-wasip1 (rustc 1.98.1, node:wasi) | agrees | 1,980 of 1,980 | 181,183 of 181,183 | 660 of 660 |
| scala | skipped: scala-cli not found | | | |

The pass criterion of `PREREG.json` holds. Every target that ran prints the
reference observations in full, both comparisons hold on the whole output,
and every head of D is equal. The Scala target was not run, so no claim is
made for it.

Rows: `results/examples.jsonl` (660 rows: the source line of each example,
its reference observation lines and the head of its log D) and
`results/targets.jsonl` (5 rows: tool, outcome and the digests of what each
target printed). `results/module.rce` is the module with its seeded
examples.

Reproduce: `rce/bench/emit-edges/run.sh OUT_DIR` prints the summary digest.
It equals the one above on a host where the same targets run. On a host
with scala-cli, the set of targets in the summary changes, and so does the
digest.

## Findings

Development runs before the registration found the following. Each is
traced to its cause. Files under `repro/` reproduce each one.

1. **Text display (fixed in the run commit).** The reference evaluator and
   the Rust runtime displayed a text with Rust's `{:?}`. Its escapes come
   from the toolchain's printable and grapheme-extend tables, against the
   Unicode pin of 6.3 N7. The Python, JavaScript and Scala runtimes escape a
   fixed set: `\t \r \n \\ \" \0`, the other code points below U+0020,
   U+007F to U+009F and U+0300 to U+036F. The two rules give different
   displays for 954,409 scalar values, among them U+00A0, U+200B, U+3000,
   U+FEFF and U+FFFF. Python and JavaScript printed 31 of 1,965 observation
   lines differently from the reference. The trap text of `toint` quotes
   the text in the same way. The run commit gives the reference and the
   Rust runtime the fixed set (`interp::show_text`), and spec 10.5 states
   it. Repro: `repro/f1-display.rce`, emitted to python or js and compared
   with `rce run` at `d2b28e76`.
2. **SIZE_LIMIT on `[x; n]` and list comprehensions (fixed in the run
   commit).** The reference applies 6.3 N9 to the result of every
   expression. The four runtimes applied it only after arithmetic and
   builtin methods. So rust, python, js and wasm32-wasip1 kept a list of
   1,000,001 elements where the reference ends the step with
   `trap(size limit)`. Repro: `repro/f3-size-limit.rce`.
3. **node:wasi on Node v22.22.0 (host, not an emitter).** The WASI host
   ends with SIGSEGV on a WASI call made after the wasm memory has grown by
   tens of MB, while V8 calls the WASI functions through its fast API path.
   `--no-turbo-fast-api-calls` turns that path off and changes no
   instruction of the program. The test runs node:wasi with it. Repro:
   `repro/node-wasi-segv.rs` with `repro/node-wasi-host.mjs`.
4. **VALUE_LIMIT is not enforced (spec against the reference; recorded,
   not fixed).** 6.3 N9 and 6.4 item 3 state that a value written to
   state is at most 1,048,576 bytes of canonical JSON
   (`trap("value limit")`). 10.3 states that the reference evaluator
   applies it. Neither the reference evaluator nor any runtime has the
   check. Every target agrees with the reference here, so this test shows
   no difference, and the module states no outcome that depends on it.
   Repro: `repro/f2-value-limit.rce`, which `rce check` records as an
   example that does not hold.

## Where 6.3 states a behaviour without its exact text or order

The model in the test follows the reference evaluator at these points, and
every target agrees with it:

- `<<` on a signed type keeps the two's-complement bits. For example
  `1 << 63` is `i64.MIN`, and only the amount is checked. N2 states the
  trap on the amount and no overflow trap for `<<`.
- For a slice, an end above the length takes precedence over reversed
  bounds, and reversed bounds over a split character.
- `isdigit`, `isalpha` and `isspace` of the empty text are false.
- `x as f32` with a result outside the binary32 range is
  `trap("non-finite float")`. N3 states this for the f32 operations.
- The trap text of `toint` on a text that is not an integer is
  `not an integer: ` followed by the displayed text. A value read at i128
  and outside it gives that text, and a value outside i64 gives N2's
  overflow text.
- The trap text of `utf8` is `utf8: invalid UTF-8` or
  `utf8: byte outside 0..255`.
- 6.2 lists the trap texts as "exactly those of 6.3". The reference also
  has other trap texts, for example the two above.

## After the registered run

A full `cargo test --release` of the checker at `e4f91ced`, the run commit
plus the dated sentence of spec 10.5, was run on the same host. It passed
451 tests and recorded 6 failures, 2 ignored, in 119 test targets. None of
the failures concerns `tests/emit_edges.rs` or its record. Each was traced
to its cause:

- `tests/form_roundtrip.rs` (2 tests): a finding. `unparse` printed the
  characters that W-LEX-4 keeps out of source raw inside string literals,
  so the printed source of the edge module, and `rce unform` of its Form,
  were not admitted. openIE-dev/rce `39e160a1` adds `unparse_source`, which
  writes them `\u{...}`, and uses it in `rce unform` and in the round-trip
  test. `unparse` keeps its bytes, because module, brick and program
  hashes, and the pins of `stdlib/lib/MANIFEST.json`, are taken over it.
  The test then passes 4 of 4.
- `tests/tree_sitter_sync.rs`: a finding, and also an artefact of the host.
  The tree-sitter grammar had only `refused: NAME`, while spec 3.2 and the
  Rust parser also have `refused: trap("K")`. `39e160a1` adds the trap
  form (a scanner token for `trap` before `(`) and regenerates the parser
  with tree-sitter 0.27.1. The six other files listed, all with
  `refused: NAME`, came from the shared parser cache
  `~/.cache/tree-sitter/lib/rce.so`, which another job on the host had
  compiled from a different grammar. With a private cache
  (`TREE_SITTER_LIBDIR`), tree_sitter_sync agrees on 365 of 365 files,
  grammar_fuzz passes, and `tree-sitter test` passes 26 of 26.
  `tree-sitter-rce.wasm` was not rebuilt (no emscripten on the host).
- `tests/unicode_pin.rs` (1 test): an artefact of the host. The shared
  target directory's `rce` binary had been rebuilt by another job from
  sources without the display rule. With this branch's own binary the
  test passes 3 of 3.
- `tests/emit_run.rs` (2 tests): `rustc` ended without a message. The test
  writes to the fixed directory `$TMPDIR/rce-emit-run`, which other jobs
  on the host were writing at the same time. The test passed 11 of 11 in
  the earlier run of the emit tests, and 11 of 11 again when it was rerun
  at `39e160a1` with a private `TMPDIR`.
