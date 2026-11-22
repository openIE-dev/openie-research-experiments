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
| `ai-reads-human-energy/` | `"AI" Reads Human` §5c | 34-workload parse + `tiktoken` dual-channel `reported_j` harness, `170` isolated subprocess receipts, and Falsifier 6 baseline-drift flags |
| `game-engines-determinism/` | `Writing a Game Once` §6 (`GE-H1`, `GE-H2`, `GE-H3`) | 25-cell multi-ISA (`arm64`/`aarch64`/`x86_64`/`wasm32`) `100,000`-tick Q32.32 simulation, cross-ISA float drift, and 4-vendor headless `wgpu` (`Metal`/`Vulkan`) rendering tolerance receipts |
| `satb-harness/` | `Satiation Benchmark Harness` | `C1–C12` conformance runner, `Falsifier 3/5/6/8` benchmarks, live multi-vendor `satb-proxy` determinism receipts, and `multi-host/` 4-archetype telemetry (`Apple M5 Max`, `Jetson AGX Thor` `INA238`/`INA3221` `measured_j`, `Framework AMD Strix Halo`, `Intel Raptor Lake`) |
| `lut-adapt-vivado-audit/` | `Downward LUT6 Compilation` §4.12 | `xck26-sfvc784-2LV-c` `clai_kv260_axi_top` (`67,366` CLB LUTs) & `clai_benes_paged_hotswap_core` Yosys `xcup` primitive/topological-depth reports, `hw_server` JTAG check, and `Vivado 2026.1` OOC Tcl script |
| `jcp-cad-mei-tag/` | `Metabolic Intelligence` & `The Search for JouleOS` | `jcp-satb-cad-spine` (`310` tests, `JCR-1` det-CBOR + Ed25519 receipts), `cad-joules` bridge patch, and `MEI-JCP-Tag-v1` DRC-clean 2-layer PCB Gerbers/KiCad/BOM/STEP/STL + `10,000`-wakeup `CR2032` simulation |
| `time-as-an-index/` | `Time as an Index` | Kernel-checked Lean 4.36.0 proofs (`Horizon.lean`, `Paradox.lean`, `31` theorems, `0` `sorry`), `M1–M8` + `F5` Python/SymPy suite, and `195`-entry structured CSV catalogs (`TA001–TA081`, `AA01–AA40`, `P01–P74`) |

Standalone companion repositories under `openIE-dev`: `openIE-dev/deterministic-null` (`Shape D` 5-language engine + `exp-001..exp-003` receipts), `openIE-dev/lut-adapt-ai` (`xck26` LUT6 RTL + AirMoL NVMe logs), `openIE-dev/rce`, and `openIE-dev/rce-vc`.

## Energy labels

`est_j` is an analytical estimate. `reported_j` is an operating-system or on-chip counter (`RAPL`, `IOReport`, or macOS `proc_pid_rusage`). `measured_j` is a wall or physical shunt meter on a named rail: it is populated in `satb-harness/multi-host/multi_host_satb_receipts.json` for the Texas Instruments `INA238` (`VIN` `L1`) and 3-channel `INA3221` (`VDD_GPU`, `VDD_CPU_SOC_MSS`, `VIN_SYS_5V0` `L2`) rails on `NVIDIA Jetson AGX Thor` (shared host, `A2` net attribution withheld), and is empty in all other runs here. Labels are never summed.

## Reproducing

Each run is fixed by its preregistration, whose SHA-256 sits beside it. `CHECKSUMS.sha256` covers every file in this repository (`sha256sum -c CHECKSUMS.sha256`). Absolute paths of the original hosts are written as `$BENCH_ROOT` and `$RUSTUP_HOME`. The macOS `powermetrics` plists of the agency run are not published, because they list every process on the host; their role in the paper (the package cross-check) is described in agency §8.11. The RCE engine source lives in its own project; the solver script used by Tracks A and B is `rce/scripts/track_a_solver.py`. Large corpora are pinned in `CORPORA.md`.

## License

Code Apache-2.0, data CC BY 4.0; see `LICENSE`.
