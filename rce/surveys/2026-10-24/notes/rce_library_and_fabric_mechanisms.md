# Working note 18: the RCE repository's mechanisms for the standard library and for compute fabrics

Read directly from `/home/user/rce` on 24 October 2026 (main after PR #26), read-only, with each item marked implemented, specified or proposed.

# RCE inventory: the standard library and one program on many compute fabrics

**Repository:** `/home/user/rce` at commit `fe5fc5d7` (2026-10-24, "Batteries included: the standard library is built into the checker"). Nothing in the repository was edited (`git status` is clean). All builds went to the scratchpad.

**What was run:**
- **Ten test binaries, 44 tests, all pass:** `cargo test` on `stdlib_builtin`, `host_place`, `host_sched`, `spec_data`, `spec_read`, `wasm_float`, `float_rules`, `stdlib_costs`, `method_costs` and `v09_manifest`.
- **One build fails:** `cargo check` of `spec/checker-wasm` (see A1).
- **Small probes with the built `rce` binary:** results are quoted where they are used.

**Terms:**
- CPU, GPU, NPU and FPGA: central, graphics and neural processing units, and field-programmable gate array.
- MCU: microcontroller unit.
- WASM: WebAssembly. WGSL: WebGPU Shading Language.
- FMA: fused multiply-add.
- D: the hash-chained Form log (6.1). δ: the step function.

**Status key:**
- **IMPLEMENTED:** code and a named test exist.
- **SPECIFIED:** normative text, with no code or only part of it.
- **PROPOSED:** a file in `spec/proposals/`, or a rule in the normative file that E.11 marks "(proposed)".

---

## A. Standard library

### A1. 4.1: `use` of any `stdlib/lib` module. IMPLEMENTED, with one claim that is false

- **Text** (`spec/book/04-programs.md` 4.1, lines 14-25): "every module of the standard library (`stdlib/lib` of the repository, pinned by hash in its manifest, F.5.3): `use enc`, `use data.events` and the others resolve with no file given, no directive and no flag, in every tool (`rce lib` lists them)."
- **Code:**
  - `spec/checker/build.rs` `embed_stdlib()` writes `OUT_DIR/stdlib_gen.rs`, which is `LIB: &[(&str, &str)]` with one `include_str!` per `.rce` file.
  - `spec/checker/src/stdlib.rs` has `names`, `has`, `source` and `module`. A module is parsed once, and its `check`, `example` and `intent` items are dropped.
  - `src/link.rs:67` `by_path` falls back to `crate::stdlib::module`.
  - `src/check.rs:244` does not raise W-NAME-1 when `stdlib::has` is true.
  - `src/lib.rs:68,119` prepares the program.
- **Tests** in `spec/checker/tests/stdlib_builtin.rs`:
  - `use_resolves_to_the_built_in_library_in_check_run_and_emit` covers check, run and `emit python` only.
  - `an_unknown_module_is_still_refused`.
- **The "in every tool" claim is false for the browser checker:**
  - `spec/checker-wasm/src/lib.rs` pulls in checker modules by `#[path]` but not `stdlib.rs`.
  - `cargo check` fails with `E0433 cannot find stdlib in crate` at `check.rs:244` and `link.rs:67`, and also on `crate::nameless`.
  - So the `wasm-checker` job in `.github/workflows/ci.yml` (`cargo check --target wasm32-unknown-unknown`) cannot pass at HEAD.
- **Not covered by the test:** `trace`, `test`, `dim`, `host`, and the rust, js and scala emitters. By hand:
  - All four emitters produce a file.
  - The emitted Python and JavaScript print `emit "aGk="`.
  - `trace` and `test` accept the program.

### A2. 4.1: the `#!lib NAME` directive. IMPLEMENTED

- **Code:** `stdlib.rs` `directives` and `with_directives`. `pq`, `hpke` and `mls` bring `crypto` with them.
- **Test:** `the_lib_directive_places_the_library_in_front`.

### A3. 4.1: `rce lib` and `rce lib NAME`. IMPLEMENTED, no test

- **Code:** `cli.rs:915-929`. It lists 46 modules.

### A4. 4.1 S4: `std.text`, `std.collections`, `std.math`. IMPLEMENTED as names only

- **Code:** `check.rs:108` `STD_MODULES`.
- **Test:** `conformance/tests/types-checking/targeted/s4-std-modules.rce`, which expects W-UNUSED-1.
- **The modules hold no items.** `use std.math` followed by `math.exp(1.0)` gives "W-NAME-1 unknown name `math`". `use math` gives `emit 2.718281828459045`. So there are two modules named `math`, and one is empty.

### A5. F.5.3: the hash-pinned manifest. Tool IMPLEMENTED; pinning of the built-in library is incomplete

- **Text** (`spec/book/17-draft09.md`, line 391 onward): "The manifest lists every module (the explicit membership of F.4.3) with its SHA-256, and every dependency by hash." Also: "There is no resolver: the manifest is the whole answer."
- **Code:**
  - `spec/checker/src/manifest.rs`: `generate`, `check`, `verify_advisories`, `unsafe_list`.
  - `cli.rs:930-985`: `rce manifest DIR` and `rce manifest-check`.
- **Tests:** 9 in `tests/v09_manifest.rs`, among them `a_generated_manifest_is_accepted_and_pins_every_module` and `signed_advisories_verify_and_mark_pinned_hashes_unsafe`.
- **`stdlib/lib/MANIFEST.json`:**
  - 46 modules, `"dependencies":[]`.
  - Current at HEAD: regenerating it gives an identical file, and `manifest-check` prints "46 modules pinned, 0 unsafe".
  - Enforced by `stdlib/scripts/check.sh` lines 22-27, run from `.github/workflows/stdlib.yml`.
- **Gaps found by probing:**
  - **The pin is checked in CI only.** `build.rs` embeds whatever `.rce` files are under `stdlib/lib` and never reads `MANIFEST.json`.
  - **A program that uses the built-in library fails its own manifest.** For a one-file program with `use enc`, `rce manifest .` writes `"dependencies":[]` and `rce manifest-check` refuses it: "W-PIN-1 module `app` imports `enc`, which the manifest does not pin by hash".
  - **The dependency form shown in `manifest.rs`'s own doc comment is also refused.** `{"name":"stdlib","sha256":…}` fails because matching is on the import's first segment (`manifest.rs:230`).
  - **Dependency hashes are checked for format only.** `{"name":"enc","sha256":"000…0"}` is accepted ("ok … 1 modules pinned"). Nothing ties a dependency hash to `MANIFEST.json` or to the embedded text.
  - **The provenance record and build cache of F.5.3** "do not exist yet" (12-tooling 10.8).

### A6. 5.15: the closed method table and `spec/data/spec-tables.json`. IMPLEMENTED

- **Text** (`06-regions-effects-extensions.md:164`): "The standard library is closed: it is exactly the builtin methods below plus the concurrency methods of 5.8 and Appendix C … and the num.rs primitives of 6.3. A method not in the table is W-NAME-1 at check time".
- **Code:**
  - `spec/checker/src/specread.rs` (`SPEC_TABLES = include_str!("../../data/spec-tables.json")`, `TABLES`, `has_method`).
  - `src/bin/spec_data.rs` (`rce-spec-data`) writes `spec-tables.json` from the book. The `methods` member comes from `06-regions-effects-extensions.md` and `method_work` from `14-draft06-concurrency.md`.
- **Tests:**
  - `tests/spec_data.rs` fails when the file is stale.
  - `tests/spec_read.rs` checks that every entry is typed and evaluated.
  - `tests/stdlib_costs.rs` checks the table against the evaluator.
- **Gaps:**
  - **"Standard library" has two normative meanings.** In 5.15 it is the closed method table; in 4.1 it is the 46 modules. 6.3's last paragraph repeats "the closed standard library", and 5.15 adds "A capability that is not in this list cannot be added by a library, because the library is closed."
  - **`num.rs` is not in this repository.** 5.15 cites the "num.rs primitives" and 6.3 is headed "from form/num.rs".

### A7. C.6.4: method work classes. IMPLEMENTED

- **Code:** `conc::method_work`, through `specread::Work`.
- **Tests:** `tests/method_costs.rs`, `tests/stdlib_costs.rs`.

### A8. Appendix E introduction: the five primitives. SPECIFIED

- **Text** (`16-host-contract.md:22-26`): "Every target supplies: pure computation on bytes with integer operations and binary64 round-to-nearest-even, append-only storage, SHA-256 as pure code, one input queue and one output queue, and a monotonic counter read only by the admitter. Everything else is an adapter."
- **No code defines the five as an interface.** `Host` in `src/host.rs` is a Rust struct that needs `std` (it uses `std::fs` and `std::thread::scope`).
- **The survey has no FPGA.** `docs/figures/src/host-survey/MATRIX.csv` covers no_std Rust, Zephyr, FreeRTOS, WebGPU, Metal and DirectX 12, but no FPGA.

### A9. E.1 adapters (HC-3, HC-4, HC-10). IMPLEMENTED

- **Code:** `src/adapters.rs` (file, PTY, `WasmCall`, …).
- **Tests:**
  - `tests/host_adapters.rs` (`file_effects_stay_under_the_granted_root`).
  - `tests/host_foreign.rs` (`wasm_calls_are_logged_fuel_bounded_and_replayed`).
  - `host_contract.rs` (`foreign_and_host_entries_replay`).

### A10. HC-5 capabilities. IMPLEMENTED for the checker, Linux and macOS

- **Code:** `src/sandbox.rs` (Landlock and seccomp on Linux, Seatbelt on macOS).
- **Tests:** `host_contract.rs` `capability_examples_check`, `tests/host_sandbox.rs`, `tests/sandbox_seccomp.rs`.
- **SPECIFIED only:** `sandbox.rs` says "To do: Windows (AppContainer), FreeBSD (Capsicum) …" and "The WASM and bare-metal targets … live outside this file (REMAINING-PLAN W1h-wasm, W1h-metal)". REMAINING-PLAN is not in the repository.

### A11. E.2 to E.2b (HC-1 to HC-9, HC-15 to HC-20) and E.3 (HS-1 to HS-5). IMPLEMENTED

- **Tests** are listed in the E.10 table, for example `verify_on_open_cuts_bad_suffix`, `fatal_barrier_stops_admission`, `tests/host_admit.rs` and `tests/host_raft.rs`.
- **The HS-2 storage table has no row for MCU flash or bare metal.** WASI and the browser are `volatile`, so no entry there is ever reported durable.

### A12. `stdlib/README.md`

- **Not constant time:** "The libraries are reference code for correctness and replay. They are **not constant time**."
  - No module in `stdlib/lib` declares a `ct fn` (F.5.4).
  - W-CTFN-2 has every emitter refuse a `ct fn` anyway: "ct fn is not emitted for this target".
- **No `extern` anywhere in `stdlib/lib`:** the library is pure RCE.
- **Stale lines that contradict the README's own "Built into the checker" section:**
  - "`rce` 0.1.3 embeds only `crypto`, `pq`, `hpke` and `mls` for `#!lib`; until a release embeds the foundation modules, give the file to `rce` together with the program".
  - "The `#!lib NAME` directive is not provided by public `rce`".
- **Drift between the spec and `math`:**
  - 6.3 F9 (`07-form-evaluation.md:398`) says: "Present: `sqrt` (F1), `cbrt`, `hypot`, `exp`, `log`, `log2`, `log10`, `sin`, `cos`; any other (`pow`, `tan`, `atan2`, ...) is absent until it meets the same rule."
  - But `stdlib/lib/math/math.rce` exports `tan` (line 814), `atan2` (882), `pow` (1996) and about 20 others, and the README lists them.
- **Platform rules as data:** the `os.*` modules hold POSIX, Windows, WASI and UEFI rules as pure data. `os.target` has `TARGETS = ["wasi-p1", "wasi-p2", "posix", "win32", "darwin", "uefi", "bare"]`, with no GPU or FPGA entry.

---

## B. One program on many compute fabrics

### B1. HC-11 `host.FabricCaps` (E.6). IMPLEMENTED for the CPU only

- **Code:**
  - `host.rs:294` `fabric_caps()` detects CPU ISA flags from a fixed list on aarch64 and x86_64. `gpus`, `npus`, `memory` and `counters` are written as `null`.
  - It is logged at start and on resume (`host.rs:840`, `894`).
- **Test:** `tests/host_priority.rs` `fabric_caps_logged_at_start_and_leave_state_unchanged`.
- **Gaps:**
  - No hot-plug, although HC-11 says "At start and on hot-plug".
  - No query of GPU or NPU float controls.
  - The payload is `cpu: {arch, features}`, where E.7 says "`cpu` lists ISA feature names".

### B2. E.7 the fabric record. SPECIFIED, and the code contradicts it

- **Text** (`16-host-contract.md:515`): "A host that cannot query a field writes `null` for it; placement then treats that fabric as absent."
- **Code:** `place_from` (`host.rs:590`) never reads `host.FabricCaps`. The test `platform_fabric_is_used_only_after_an_exact_probe` places work on `gpu.good` while the logged record has `"gpus":null`.
- **The record has no field for an FPGA or an MCU:** it is `{cpu, gpus, npus, memory, counters}`.

### B3. `host.Calibrated` (E.5, HC-12). IMPLEMENTED as logging only

- **Code:**
  - `Host::calibrate(fabric, class, overhead, throughput)` (`host.rs:1492`) logs numbers the caller supplies. Replay folds them back (`host.rs:1267`).
- **Tests:** `host_sched.rs` `placement_executor_follows_d_and_replays`, `host_contract.rs` `placement_is_a_function_of_host_entries`.
- **Gaps:**
  - **No calibration run.** No code measures overhead or throughput, and `cli.rs` has no `rce host calibrate`.
  - **The CPU's line is a constant, never calibrated:** `pub const CPU_COST: (f64, f64) = (16.0, 1.0);` (`host.rs:583`).
  - **`work` is an element count** (`xs.len() as f64`), not the C.6.4 cost HC-12 names.

### B4. `host.Exact` and `probe_fabric` (HC-13). IMPLEMENTED, with a replay gap

- **Code:**
  - `probe_vector` (`host.rs:749`): signed zeros, subnormal results, infinities, NaN, cancellation, and 1000 mixed lanes.
  - `probe_fabric` (`host.rs:1529`): sums of every length from 0 to 64 plus the whole vector, and each lane class.
  - `bits_digest` (`host.rs:763`) maps every NaN to one value.
- **Test:** `host_place.rs` `platform_fabric_is_used_only_after_an_exact_probe`. The `Loose` double, which reassociates and flushes subnormals, fails its probes; `Good` passes.
- **Gaps:**
  - **`Host::probe` admits any two equal strings** (`host.rs:1502`, public). For example, `host_sched.rs` calls `h.probe("cpu.threads", "sum.f64", "d1", "d1")`.
  - **Replay never recomputes the CPU reference digest.** It checks only `p["probe"] == p["reference"]` (`host.rs:1271`), although that digest is a pure function of the class. This falls short of E.2c law 1: "Replay re-derives each one and refuses D when a derivation differs".

### B5. `host.Placed` and `place_from` (HC-12). IMPLEMENTED as a host API

- **Code:**
  - `place_from` picks the least `overhead + work / throughput` among the CPU and every fabric that has both a Calibrated row and an Exact probe. Ties go to the lexically smaller id, with the CPU first.
  - Replay refuses a placement that does not re-derive: "placement re-derives {got}, D has …".
- **Tests:** `host_sched.rs` `placement_executor_follows_d_and_replays`, `host_place.rs` `lane_and_par_placement_follow_d_and_replay`.
- **Lean:** `spec/lean/RCE/Host.lean:43` `t37_placement`.

### B6. `FabricExec` and `register_fabric`. Interface IMPLEMENTED; no real device implements it

- **Code:** `host.rs:740` defines `trait FabricExec { id, lanes(op, a, b), sum(xs) }`. It covers f64 only and the six `LaneOp`s: add, sub, mul, div, neg, sqrt.
- **The only implementations are CPU-Rust test doubles,** `Good` and `Loose`, in `tests/host_place.rs`.
- **No real fabric exists:**
  - `spec/checker/Cargo.toml` has no wgpu dependency.
  - `ide/crates/rce-ide/src/gpu.rs` uses wgpu as a renderer, not as a `FabricExec`.
- **Text** (`16-host-contract.md:467`): "A GPU through wgpu, or an NPU, enters by implementing `FabricExec`".

### B7. `place_sum`, `place_lanes`, `place_par`. IMPLEMENTED, but no program execution path calls them

- **Code:** `host.rs:1581`, `1599`, `1635`.
- **Callers:** only `tests/host_sched.rs` and `tests/host_place.rs`.
  - `interp.rs:793` evaluates lane-wise operators one lane after another.
  - `conc.rs` combines `for … par` itself.
  - `rce run` and `rce host run` never call placement.
- **So HC-12's first sentence holds on no execution path:** "The engine places each lane-wise array operation, `for … par` body and reduction itself … A program needs no annotation."
- **Bodies cannot leave the CPU** (`place_par`): "Bodies are host closures, so only CPU fabrics can execute them".

### B8. C.8: `tree_split` and the fixed reduction tree. IMPLEMENTED

- **Text** (`14-draft06-concurrency.md:291`): "A reduction is evaluated on a fixed tree, which equals the left fold for an associative operation with an identity (T18). The tree is normative".
- **Code:**
  - `conc.rs:29` `tree_split(m) = 1 << (m - 1).ilog2()`, re-exported by `host`.
  - `fixed_tree_sum`, `fixed_tree_sum_threads`, `fixed_tree` and `fixed_tree_threads` in `host.rs`.
  - The four runtimes: `emit/rt.rs:1135`, `rt.py:1244`, `rt.js:1048`, `rt.scala:1164`.
  - Lean: `RCE.Par.split`, `tree_eq_foldl`.
- **Tests:** `host_place.rs` `forpar_reference_and_placement_share_the_tree` (lengths 1 to 40) and `lanes_and_trees_have_the_same_bits_for_every_thread_count`; `host_sched.rs` `fixed_tree_bits_do_not_depend_on_the_fabric`.
- **Finding (probed): only `for … par` reductions use the tree.** With `xs = [1.0, 1e16, -1e16, 1.0, 0.5]`:

  | Expression | Result |
  |---|---|
  | `xs.sum()` (a left fold, `interp.rs:1984`) | `1.5` |
  | `for i in 0..5 par` with `s += xs[i]` | `0.5` |
  | the same loop without `par` | `1.5` |

  - The placement class `sum.f64` computes the tree. So `sum.f64` can carry only `for … par` sums; placing `List.sum` or a plain loop there would change the bits.
  - E.11 N-9 (proposed), "Every reduction is a left fold unless the program names a different fixed tree", conflicts with C.8. No syntax exists for naming a tree.

### B9. C.6.4: the cost table. IMPLEMENTED, and the same on every target

- **Text:** "Cost is a deterministic accounting of Form operations, the same on every target; it is not a measurement of time or energy".
- **Tests:** `tests/stdlib_costs.rs`, `tests/method_costs.rs`, `tests/call_site_cost.rs`, `tests/loop_cost.rs`.
- **Gaps for placement:**
  - No per-fabric columns.
  - No row for a lane-wise array operation as a whole.
  - No mapping from a C.6.4 operation to a placement class.

### B10. 5.13 device regions, C.7 device kernels, C.11.2 workgroups. IMPLEMENTED as a check, with CPU meaning only

- **Text** (`06-regions-effects-extensions.md:130-140`): "Its meaning is the same as the block run on the CPU, so the region is only a placement hint".
- **Code:**
  - W-DEV-1 in `check.rs` (lines 1069-1093, 1974, 2183-2191, 2357, 3069).
  - `interp.rs:2299/2327` and `emit/stmt.rs:812/848` treat `Stmt::Device` as a plain block.
- **Tests:**
  - `conformance/tests/effects-capabilities/harvested/device-{emit,extern,list}-reject.rce` and `conformance/tests/concurrency/harvested/44-device-region-accept.rce`.
  - They run through `conformance/harness/run.py`, from `.github/workflows/conformance.yml`.
- **No lowering to a kernel exists.** `11-decisions.md:261` lists it as an open question: "(today they run them on the CPU, which 5.13 allows)".

### B11. 6.3: the numeric contract. IMPLEMENTED in the reference and four runtimes

- **Text, by rule:**
  - F2: "Contraction to fused multiply-add, reassociation, excess precision and every other value-changing optimization the standard allows a language to permit are therefore not valid compilations (HC-14)". Also: "RCE has none yet" (no explicit FMA).
  - F3: "flush-to-zero and denormals-are-zero modes are not IEEE operations".
  - F4: an operation whose IEEE result is not finite "is `trap("non-finite float")`".
  - F5: "A fabric or target that can produce NaN (GPU, NPU, WASM SIMD) canonicalizes or traps before a value reaches state".
- **Tests:** `tests/float_rules.rs`, `spec/examples/57_float_vectors.rce`, `tests/emit.rs`, `tests/emit_run.rs`.
- **Cross-architecture parity:** `.github/workflows/xarch-parity.yml` runs linux-x86_64, linux-aarch64, macos-aarch64, windows-x86_64, wasm32-wasip1 under wasmtime, and s390x under QEMU. Each is compared with `scripts/xarch-hashes.x86_64-linux.txt` (79 lines).
- **Gaps:**
  - **The placement executor does not apply F4.** It returns infinities and NaN from lanes and sums without a trap.
  - **The `FabricExec` contract is silent on traps:** neither the N2 integer traps nor F4 are stated.
  - **Classes are f64 only.** HC-13's exact list names "integer operations", but no integer or f32 class exists.

### B12. WASM floats as foreign code (HC-4, HC-13). IMPLEMENTED

- **Code:**
  - `src/wasm_float.rs`: NaN canonicalization, `probe`, `REFERENCE = "47a0426609e8de5f"`.
  - `adapters.rs` `wasm_adapter` (`--wasm DIR`), logged as `host.Exact` at `cli.rs:1210/1267`.
- **Tests:** 3 in `tests/wasm_float.rs`.
- **This is foreign code,** not a placement fabric for the Form.

### B13. The reference evaluator on WASM. IMPLEMENTED

- The `wasm32-wasip1` job of `xarch-parity.yml` checks hash parity.
- The browser build `spec/checker-wasm` does not compile (A1).

### B14. HC-14: no performance flags. SPECIFIED

- **The only test checks that the rule is written:** `host_contract.rs` `every_appendix_e_rule_is_cited_by_a_test` looks for the string.
- **No code** derives a build profile from `host.FabricCaps`.

### B15. The emitters in `spec/checker/src/emit`. IMPLEMENTED for four CPU languages

- **Code:**
  - `emit/mod.rs:33` `enum Lang { Rust, Python, Js, Scala }`.
  - `cli.rs:182` accepts `form|rust|python|js|scala`; anything else is "unknown emit target `{t}` (form, rust, python, js, scala)".
  - Runtimes `rt.rs`, `rt.py`, `rt.js`, `rt.scala`. With the generator files, about 16,068 lines.
- **Tests:**
  - `tests/emit.rs`: `rust_emitter_agrees_with_reference`, `python_emitter_agrees_with_reference`, `js_emitter_agrees_with_reference`, …
  - `tests/emit_run.rs`: `emitted_runtime_agrees_with_run_main`, `program_events_agree_on_every_target`.
  - `tests/emit06.rs`, `tests/emit06b.rs`.
- **Gaps:**
  - No hardware, accelerator or MCU target.
  - Device regions come out as plain blocks.
  - No CI job runs emitted Rust on wasm32, although `emit-targets.md` Tier 0 says "Runs on native, WASM (wasm32-wasip1)".

### B16. `spec/proposals/emit-targets.md`. PROPOSED

- **One emitter over the Form IR** reads a table per target, `emit/targets/<name>.toml`.
- **Tier 3 targets:**
  - "Verilog / SystemVerilog, VHDL | … | one step per clock; bounded state only".
  - "Bluespec, Chisel, SpinalHDL, Amaranth, Clash".
  - "Lustre / SCADE, Esterel".
  - "Futhark, Halide, Triton, CUDA, OpenCL, GLSL/WGSL/HLSL/MSL, SPIR-V | accelerators and shaders | device regions (5.13) only: fixed-size, effect-free kernels".
  - "WebAssembly (direct, component model)".
- **Status in `LEDGER.md`:** "open; gated on the one-emitter change". Neither `emit/targets/` nor the Form-IR emitter exists.

### B17. `spec/proposals/energy-calibration.md`. PROPOSED, and it collides with E.5

- **Content:**
  - Two regimes: A, count-linear ("MCU, FPGA, in-order cores"), and B, time-linear ("out-of-order CPUs and GPUs").
  - The falsifier RCE-F5.
  - First planned measurement: a KV260 FPGA board, on its VCCINT rail.
  - It defines `host.Calibrated {fabric, regime, E: {class: {j_per_unit, se}}, p_idle, p_active, protocol, n, duration_s, meter, hash}`, "written by `rce host calibrate`".
- **The collision:**
  - E.5's normative payload is "fabric id, op class, overhead, throughput": a time model, one class per entry. `host.rs:1492` implements that.
  - The proposal reuses the entry name for an energy model with a different payload.
  - No `rce host calibrate` exists.
- **Related but separate:** `ide/crates/ide-energy/src/calib.rs` fits energy coefficients for the IDE and writes no host entry.

### B18. Other proposed rules

- **E.11** (`16-host-contract.md`; listed in the normative file but marked proposed):
  - N-9 (above).
  - K-5: "worst-case cost bound … per fabric".
  - TU-6: "Placement (HC-12) keys the fabric cost table by (pure operation, element type, shape)".
- **`spec/proposals/CORE-PROPERTIES.md` P5:**
  - "`rce run --target T --validate` … logs the first divergence as `TargetMismatch(T, step)`".
  - "the new PTX emitter for device regions".
  - Neither the flag nor the emitter exists.

---

## C. What is missing for the claim

The claim: *"one Form runs with one meaning on CPU, GPU, FPGA, microcontroller and WebAssembly, placed by the engine from logged calibrations, with no platform-specific library in the program."*

What the spec actually models is one host plus fabrics. The admitter, D, SHA-256 and δ stay on the host (Appendix E introduction, the five primitives). GPU and FPGA appear only as places to run pure lane, sum and `par` work. Running "on" an FPGA or an MCU as the host needs those five primitives there too.

### C1. Placement from logged calibrations (applies to every fabric)

1. **Connect placement to evaluation.** Lane-wise operators (`interp.rs:793`), the `for … par` combine (`conc.rs`) and `rce host run` must call `place_lanes`, `place_par` and `place_sum`. *Belongs in:* E.6 HC-12, `host.rs`, `conc.rs`, `interp.rs`.
2. **Decide which reductions may be placed.** Today the C.8 tree (`for … par`) and the left fold (`List.sum`, plain loops) differ (0.5 against 1.5 above). Adopt or reject N-9, and add syntax for naming a tree if it is adopted. *Belongs in:* C.8, the `sum` row of 5.15, the class list of E.6 HC-12.
3. **A real calibration run.** Measure (overhead, throughput) per (fabric, class) and log `host.Calibrated`, with a CLI command, and calibrate the CPU's own line or make `CPU_COST = (16.0, 1.0)` normative. *Belongs in:* E.5, E.6 HC-12, 12-tooling (10.x).
4. **One schema for `host.Calibrated`.** E.5's time payload and `energy-calibration.md`'s energy payload need distinct names or one merged schema. *Belongs in:* the E.5 table.
5. **Units.** HC-12 says "from the cost table of C.6.4", but the code uses the element count. A normative mapping from operation to class to work is needed (TU-6 proposes keying by operation, element type and shape). *Belongs in:* C.6.4, E.6.
6. **Honour E.7's null rule.** `place_from` must read the logged `host.FabricCaps`. *Belongs in:* `host.rs:590`.
7. **Re-derive probes on replay.** Replay must recompute the reference digest of `host.Exact`, and `Host::probe` with caller-supplied digests should be test-only. *Belongs in:* E.6 HC-13, `host.rs:1271/1502`.
8. **Hot-plug `host.FabricCaps`.** *Belongs in:* HC-11, `host.rs`.
9. **More classes.** Beyond the six f64 lane operations and `sum.f64`: integers (HC-13 already lists them), f32, comparisons, min and max. *Belongs in:* E.6 HC-12, `host.rs` `LaneOp`. The `math` functions stay RCE code; HC-13 keeps device versions "output only or verified".
10. **Traps on a fabric.** The `FabricExec` contract and the executor must apply F4 (`non-finite float`) and the N2 integer traps after a fabric result. *Belongs in:* the "Platform fabrics" paragraph of E.6, `place_*`.
11. **A divergence check per run** (CORE-PROPERTIES P5, `--validate`). *Belongs in:* 10.3, E.6.
12. **HC-14 in code:** a build profile derived from `host.FabricCaps`. *Belongs in:* E.6 HC-14.

### C2. Per fabric

**CPU**
- Holds today for the reference evaluator and four emitted runtimes on six CPU targets (xarch parity).
- Missing: only C1.

**WebAssembly**
- The reference evaluator on wasm32-wasip1 holds (CI parity).
- Missing:
  1. **Fix the browser checker:** include `stdlib.rs` and `nameless.rs`, or name the exception in 4.1's "in every tool". *Belongs in:* `spec/checker-wasm/src/lib.rs`, 4.1.
  2. **A `FabricExec` for a WASM engine.** Today WASM is foreign code only. *Belongs in:* E.6.
  3. **Run emitted programs on wasm32 in CI,** and add a direct WASM emitter (Tier 3). *Belongs in:* `tests/emit.rs` or `xarch-parity.yml`, `emit-targets.md`, then 10.5.
  4. **Durability:** HS-2 makes WASI and the browser `volatile`, so no entry is ever reported durable. *Belongs in:* E.3.

**GPU**
- Missing:
  1. **A real `FabricExec`** (wgpu, Vulkan or CUDA). E.6 assigns it to "the platform worker". *Belongs in:* `host.rs` or a fabric crate.
  2. **A float class a GPU can pass.** "A device without binary64, or one that cannot meet the contract, fails its probe and is never placed". WGSL has no core f64, and HC-13 excludes "any WGSL float operation, whose rounding WGSL does not specify". So WebGPU can never be placed for a float class. Needed: an f32 class with 6.3 f32 semantics, on a backend with IEEE f32 and no contraction. *Belongs in:* the E.6 class list, `LaneOp`.
  3. **A kernel compiler** for `for … par` bodies and device regions ("placing them on a device needs the body compiled to a kernel"). *Belongs in:* 5.13, C.7, `emit-targets.md` Tier 3, CORE-PROPERTIES P5.
  4. **A GPU query** for the E.7 float controls. *Belongs in:* `host.rs` `fabric_caps`.
  5. **Trap semantics** (C1 item 10).

**FPGA**
- Nothing exists in the repository:
  - No executor and no HDL emitter (only Tier 3 rows).
  - No FPGA in the host survey (`MATRIX.csv`).
  - No FPGA field in the E.7 record.
  - No contract for a soft binary64 core, which the five primitives require.
  - No KV260 calibration run yet (`LEDGER.md` row "open").
- *Belongs in:* E.7 (record field), E.6 (executor contract and probe), `emit-targets.md` then 10.5, the survey, the measurement plan in `energy-calibration.md`.

**Microcontroller**
- Missing:
  1. **A host that runs without `std`.** `host.rs` uses `std::fs` and threads. The survey marks no_std Rust L4, "event admission+clock", as "absent".
  2. **An emit target.** Tier 1 C or Zig is only proposed.
  3. **A CI target.** `xarch-parity.yml` has no `thumbv*` or `riscv32` job.
  4. **An HS-2 storage row** for flash or bare metal (E.3).
  5. **Bare-metal enforcement for HC-5,** which points to "REMAINING-PLAN W1h-metal", a file not in the repository.
- *Belongs in:* E.3, HC-5, 10.5, `xarch-parity.yml`.

### C3. No platform-specific library in the program

1. **Nothing forbids `extern "C"`** (5.11: "the platform C calling convention") in a program claimed to be portable. Logging makes such a program replay-portable, not run-portable. Needed: a rule or profile, for example "a multi-fabric program declares no `extern`; foreign code is a WASM component only" (HC-4 already recommends components). *Belongs in:* 5.11, Appendix F, the W-rules of section 9.
2. **The library is pure RCE** (no `extern` in `stdlib/lib`); that part holds. The `os.*` modules choose a platform by argument (POSIX or Windows rules). The claim needs a sentence saying all I/O goes only through adapters (HC-3). *Belongs in:* the 5.15 "Effects and I/O" paragraph, `stdlib/README.md`.
3. **Hash identity of the library a program uses** (A5): a manifest dependency form for the built-in library, `build.rs` checking `MANIFEST.json`, and dependency hashes actually verified. *Belongs in:* F.5.3, `manifest.rs`, `build.rs`, 4.1.
4. **One meaning for "standard library"** (5.15 against 4.1). *Belongs in:* 5.15, the last paragraph of 6.3.
5. **Reconcile 6.3 F9 with `math.rce`'s exports** (`tan`, `atan2`, `pow`, …): either the spec list or the library is stale. *Belongs in:* 6.3 F9 or `stdlib/lib/math/math.rce`.
6. **Fill or remove the empty `std.text`, `std.collections`, `std.math`.** *Belongs in:* 4.1, decision 33 in `11-decisions.md`.
7. **Update the stale `#!lib` and "0.1.3 embeds only" lines.** *Belongs in:* `stdlib/README.md`.
