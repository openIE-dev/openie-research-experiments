# OpenIE research experiments

Reproducible material for the papers at https://research.openie.dev. The page https://research.openie.dev/data/ maps each result in each paper to a path here.

## Layout

| Path | Paper | Contents |
|---|---|---|
| `agency-run/` | Thermodynamic Bounds and an Optimal Tempo for Goal-Holding Agents, §8.11 | Preregistrations (v1, v2, v2 second machine), agent and meter code, task generator, analysis scripts, episode and receipt results, pilots |
| `rce/bench/track-a/` | Development material (not reported in the paper) | Corpus20 task directories (each registration), preregistrations with SHA-256, solver patches and reports |
| `rce/bench/track-b/` | Development material (not reported in the paper) | RAPL energy runs: `results.jsonl` with raw and idle-subtracted joules, method and report |
| `rce/bench/results/` | RCE §6.3 | Track C soak results and energy receipts |
| `rce/bench/ladder/` | RCE §2.3, §6.1 to §6.3 (held-out results) | LADDER.md, PREREG.json, RESULTS.md, report.py and per-rung results |
| `rce/bench/defects4j/` | RCE §8.1 | Defects4J harness, TBar port comparison, REVIEW.md and results |
| `rce/bench/forms/`, `rce/tests/form_targets.rs`, `rce/FORM.md` | RCE §4.5, §5.1 | Form compiler harness and the five-target differential test |
| `flowg-conformance/` | RCE §1 (flowG) | flowG cross-backend conformance suite, fixtures and the recorded 18 of 18 report |
| `rce/SOAK_RESULTS.md`, `rce/SOAK_ENERGY.md` | RCE §6.3, §6.4 | Soak model-call counts and energy receipts |
| `rce/bench/reported-j/` | RCE, RCE-VC (`aba99fce`), RCE-JEPA (`H2`) | Apple M5 Max `L2`/`L3` `reported_j` receipts for `rce` Form checking (`49.04 mJ/check`, `15.44 J` full 62-Form suite) and `rce-vc` `100,000`-unit admission (`317–365 µJ`) |
| `rce/bench/h15-gear0/` | RCE-JEPA (`H15` & `Shape D` Gear-0) | Preregistration (`PREREG.json`), 40-task residual corpus, multi-vendor proposer receipts (`Opus 5.5`, `Sonnet 5.5`, `Grok 4.20`, `GPT-OSS-120B`, `Qwen 3.6`, `DeepSeek V4.1`), and `DNULLMM1` Gear-0 replay |
| `rce/bench/form-jepa-v1/` | RCE-JEPA (`FormJEPA-v1`, 3-Gear Cascade, & `rce repair` Rung `f`) | Preregistrations (`PREREG_form_jepa_v1.json`, `PREREG_rung_f.json`), `8.42M`-param PyTorch JEPA training & evaluation scripts, `H15` & `151`-task Rung `f` observation/criterion receipts |
| `rce/bench/form-ebm-v2-and-iterative/` | RCE-JEPA (`FormEBM-v2` `H5`/`H11`, `H15-Iterative` `40/40`, & `Gear-0 v2`) | Preregistrations (`PREREG_form_ebm_v2.json`, `PREREG_h15_iterative.json`), `5.85M`-param contrastive + 5-step margin `FormEBM-v2` (`H5` `AUROC = 0.8922`, `H11` `93.0%` strict monotonicity), bounded checker-feedback `H15-Iterative` episodes (`Opus 5.5` `40/40`, `Sonnet 5.5` `40/40`, `Grok 4.20` `39/40`), and `40/40` `DNULLMM1` `Gear-0 v2` store |
| `rce/bench/form_ebm_v3/` | RCE-JEPA (`FormEBM-v3` Span-Normalized Two-Head OOD Scorer) | Preregistration (`PREREG_form_ebm_v3.json`), `6.05M`-param span-attenuated two-head `FormEBM-v3` (`H5` `AUROC = 0.9437`, `H11` `94.0%` strict monotonicity, cross-task OOD `H15` edit-size inversion resolved `0.2585 -> 0.5278` pooled `AUROC` / `0.6018` large-valid vs short-invalid, `27/40` `k=1` admissions) |
| `rce-compile/` | `RCE Compile` §8 (`E4-Energy`, `E4-Prelude` `.rlib`, & `E5-Scale`) | Preregistrations (`PREREG_rce_compile_wave4.json`, `rlib-prelude/PREREG_rce_compile_wave5_rlib.json`), 20-kernel × 15-tier Linux `RAPL` compilation vs. execution energy payback (`N*`) including shared `librce_rt.rlib` (`20.07x` lower `rustc -O3` compile energy, median `N* = 1,079`), `H4` Regime-B receipts, and 245-program / 500-mutant De Bruijn nameless cache soundness |
| `ai-reads-human-energy/` | `"AI" Reads Human` §5c | 34-workload parse + `tiktoken` dual-channel `reported_j` harness, `170` isolated subprocess receipts, and Falsifier 6 baseline-drift flags |
| `game-engines-determinism/` | `Writing a Game Once` §6 (`GE-H1` through `GE-H9`) | Full 9-suite 3-OS (`macOS`/`Linux`/`Windows 11`) closure: 30-cell `100,000`-tick `Q32.32` replay (`0/25,500` mismatches), 3-OS float drift, 28-pair `DX12`/`Metal`/`Vulkan` `wgpu` tolerance, 54 `.rce` Forms (`-76.22%` SLOC vs Unity C#), `10,000`-actor scaling, 260-module interface fault `F1 = 0.9922`, 840-trajectory Lyapunov slopes, 1-hour `216,000`-tick replay from `44.6 KB` gzip input log, and `36/36` `Godot 4.7.2` headless parity |
| `satb-harness/` | `Satiation Benchmark Harness` | `C1–C12` conformance runner, `Falsifier 3/5/6/8` benchmarks, live multi-vendor `satb-proxy` determinism receipts, and `multi-host/` 5-archetype telemetry (`Apple M5 Max`, `Jetson AGX Thor` `INA238`/`INA3221` `measured_j`, `Framework AMD Strix Halo`, `Intel Raptor Lake`, and bare-metal `Windows 11` `NVML`/Job Objects) |
| `lut-adapt-vivado-audit/` | `Downward LUT6 Compilation` §4.15 & §4.16 | `xck26-sfvc784-2LV-c` `clai_kv260_axi_top` & `clai_benes_paged_hotswap_core` Yosys `xcup` primitive/depth reports, `Vivado 2026.1` OOC Tcl script, and `vcd-toggle-audit/` 4-phase `Verilator` VCD toggle-rate + `AMD DS925` dynamic switching `est_j` audit (`361.68 est_pJ/cycle`, `4.50x` `RAMB36E2` `ENARDEN` gating reduction) |
| `lut-adapt-bwrap-paranoid/` | `Downward LUT6 Compilation` (`Claim LA-19`) | Linux `bwrap`-sandboxed Lean 4.36.0 6-kernel `lake check --paranoid` receipts (`27` theorems, `58,683` `con-leche`/`con-ron --verified` & `58,685` `lean4lean`/`nanoda`/`leanchecker --paranoid` declarations, `RAPL` `reported_j`) |
| `jcp-cad-mei-tag/` | `Metabolic Intelligence` & `The Search for JouleOS` | `jcp-satb-cad-spine` (`310` tests, `JCR-1` det-CBOR + Ed25519 receipts), `cad-joules` bridge patch, and `MEI-JCP-Tag-v1` DRC-clean 2-layer PCB Gerbers/KiCad/BOM/STEP/STL + `10,000`-wakeup `CR2032` simulation |
| `time-as-an-index/` | `Time as an Index` | Linux `bwrap`-sandboxed 6-kernel `lake check --paranoid` Lean 4.36.0 proofs (`Horizon.lean`, `Paradox.lean`, `31` theorems, `0` `sorry`, `58,796` `con-leche`/`con-ron --verified` decls), `M1–M8` + `F5` Python/SymPy suite, and `195`-entry structured CSV catalogs (`TA001–TA081`, `AA01–AA40`, `P01–P74`) |
| `communication-avalanche/` | `The Communication Tool Avalanche` | Linux `bwrap`-sandboxed 6-kernel `lake check --paranoid` Lean 4.36.0 proofs (`QuorumRatchet.lean`, `OrchestrationFlow.lean`, `EnzymaticSynthesis.lean`, `45` theorems, `0` `sorry`, `58,928` `con-leche`/`con-ron --verified` decls), `CA-M1–CA-M5` deterministic simulation suite, 5 CSV catalogs (`CL01–CL24`, `AI01–AI38` + live CrossRef/arXiv audits, `HM01–HD04`, `BM01–BM18`, `EV01–EV16`), Rust `BLAKE3`+`Ed25519`+`SSP` orchestrator (`CTA-E1–E3`), and `fleet_and_des10/` 5-host fleet energy (`CTA-E4`, including `Jetson AGX Thor` `INA238`/`INA3221` `measured_j`) + `100`-task 10-camp Digital Enzymatic Synthesis (`CTA-E5` / `DES-10`, `98/100` verified pass) |

Standalone companion repositories under `openIE-dev`: `openIE-dev/deterministic-null` (`Shape D` 5-language engine + `exp-001..exp-003` receipts), `openIE-dev/lut-adapt-ai` (`xck26` LUT6 RTL + AirMoL NVMe logs), `openIE-dev/rce`, and `openIE-dev/rce-vc`.

## Energy labels

`est_j` is an analytical estimate. `reported_j` is an operating-system or on-chip counter (`RAPL`, `IOReport`, `NVML`, or macOS `proc_pid_rusage`). `measured_j` is a wall or physical shunt meter on a named rail: it is populated in `satb-harness/multi-host/multi_host_satb_receipts.json` and `communication-avalanche/fleet_and_des10/results/` for the Texas Instruments `INA238` (`VIN` `L1`) and 3-channel `INA3221` (`VDD_GPU`, `VDD_CPU_SOC_MSS`, `VIN_SYS_5V0` `L2`) rails on `NVIDIA Jetson AGX Thor` (shared host, `A2` single-window net attribution withheld per `Falsifier 6`), and is empty in all other runs here. Labels are never summed.

## Reproducing

Each run is fixed by its preregistration, whose SHA-256 sits beside it. `CHECKSUMS.sha256` covers every file in this repository (`sha256sum -c CHECKSUMS.sha256`). Absolute paths of the original hosts are written as `$BENCH_ROOT` and `$RUSTUP_HOME`. The macOS `powermetrics` plists of the agency run are not published, because they list every process on the host; their role in the paper (the package cross-check) is described in agency §8.11. The RCE engine source lives in its own project; the solver script used by Tracks A and B is `rce/scripts/track_a_solver.py`. Large corpora are pinned in `CORPORA.md`.

## License

Code Apache-2.0, data CC BY 4.0; see `LICENSE`.
