# `lut6-core-nucleus`: Zero-Allocation `#![no_std]` 4 KB Knowledge Crystal, 64-Codon Operon ABI, 2-Bit Wobble Walsh Filter, 16 KB 3-Part Bootstrap Nucleus, 6-Kernel Lean 4.36.0 Proof, 4-ISA Cross-Compilation, and Dual-Reality Three-Wave Metered Benchmark

## 1. Epistemic & Energy Evidence Separation

All telemetry in this directory enforces strict separation across measurement classes:
- **`measured_j`** (`board_metered = true`): Physical DC shunt rail integration on **NVIDIA Jetson AGX Thor Developer Kit** (`aarch64` Linux `6.8-tegra`, strictly CPU-only with `CUDA_VISIBLE_DEVICES=""`) via Texas Instruments **`INA3221`** (`VDD_CPU_SOC_MSS` `L2` rail) and **`INA238`** (`VIN` `L1` board input rail) polled at `200 Hz` (`5 ms`) with `5.0 s` pre/post quiet idle drift checks (`1.034%` `VDD_CPU_SOC_MSS` drift; single-window net idle subtraction withheld per `Falsifier 6` due to active shared-host GPU co-tenant lock).
- **`reported_j`** (`board_metered = false`): Linux `powercap` on-chip energy counters on **AMD Ryzen AI Max+ 395** (`x86_64` Zen 5 Linux `7.0`) via `/sys/class/powercap/intel-rapl:0/energy_uj` (`package-0`) and `/sys/class/powercap/intel-rapl:0:0/energy_uj` (`core`) with `5.0 s` pre/post quiet idle drift checks (`12.584%` package drift -> single-window net idle subtraction withheld per `Falsifier 6`).
- **Cross-Compiled Bare-Metal MCU ELFs** (`board_metered = false`, `measured_j = null`, `reported_j = null`): Static section byte footprints and `llvm-objdump` Thumb-2 / ARMv6-M instruction audits for **Alif Ensemble E3/E4 Cortex-M55 HE** (`thumbv8m.main-none-eabihf`) and **Raspberry Pi Pico RP2040 Cortex-M0+** (`thumbv6m-none-eabi`).

`measured_j` and `reported_j` are never summed or mixed.

---

## 2. Stable Rust `1.100.0` (`edition = "2024"`, `#![no_std]`) Architecture Summary

Compiled with **100% stable `rustc 1.100.0 (0ef1bc386 2026-11-09)`** (`edition = "2024"`, zero `#![feature(...)]` flags, zero external crate dependencies; native stable `!` never-type verified in `Result<EvalOutcome, !>` across all 4 ISAs):

1. **`CompactLut6Page` (`lut6-core/src/lib.rs`)**:
   - Exact `4,096`-byte `#[repr(C, align(8))]` little-endian layout verified at `rustc` compile time (`size_of == 4096`, `align_of == 8`, `offset_of!(routes_lo) == 64`, `offset_of!(init_masks) == 2048`), sealed with `const fn` IEEE 802.3 `crc32`.
   - **`eval_raw(&self, state: u64) -> u64`** (`const fn`), **`evaluate(...) -> Result<EvalOutcome, !>`** using Rust 2024 `let_chains` (`if let Some(patch) = overlay && patch.is_valid() && patch.domain_hash == self.domain_hash`), and **`eval_batch_64(&self, states: &[u64; 64]) -> [u64; 64]`** (`64x64` Hacker's Delight bit-matrix transpose + Shannon cofactor subtree short-circuiting).
   - **64-Point Integer Fast Walsh-Hadamard Wobble Filter (`0` floats)**: `lut6_walsh_spectrum(init_mask) -> [i8; 64]`, `high_harmonic_energy(init_mask) -> u32`, and `wobble_codon_mask(target_6bit) -> u64`, with compile-time `const` exhaustiveness assertions confirming `high_harmonic_energy == 0` for all 64 2-bit wobble codons vs `448 / 4096` (`7/64`) for all 64 1-hot masks `1u64 << addr`.
2. **64-Codon Operon ABI (`lut6-core/src/bootstrap.rs`)**:
   - `SEED_AGENCY: CompactLut6Page` (`4,096` bytes, `80` active LUT6 slots across `4` layers, `high_harmonic_energy == 0` on all `256` masks) maps `AgencyStateWord(u64) -> OperonFrame(u64)` across all 9 canonical opcodes (`STOP_HALT 0x00`, `SPLICE_PAGE 0x10`, `FOLD_STATE 0x18`, `BUS_PIO_SPI 0x20`, `BUS_UART_MCP 0x24`, `WAKE_LOCAL_NPU 0x28`, `VERIFY_CHECK 0x2C`, `TRANSCRIBE_FRONTIER 0x30`, `APOPTOSIS_ROLLBACK 0x3C`) and all 4 2-bit LSB wobble variants, verified at `rustc` compile time.
3. **16 KB 3-Part Self-Hosting Bootstrap `Nucleus` (`lut6-core/src/nucleus.rs` & `ratchet_demo.rs`)**:
   - `CrystalArena16K` (`16,384` bytes = `knowledge_root` + `agency_root` + `knowledge_overlay` + `agency_overlay`).
   - `refine_knowledge` & `refine_agency` enforce both Gate 1 (Walsh high-harmonic filter) and Gate 2 (100% zero-regression anchor retention), latching `APOPTOSIS_ROLLBACK` when `verifier_rejects >= kill_max_rejects` (`results/ratchet_demo_receipt.json`).

---

## 3. Lean 4.36.0 Six-Kernel `bwrap` Paranoid Verification (`lean/NucleusWobble.lean`)

Verified on Linux (`bubblewrap 0.11.1` network-isolated namespace, zero `--inadvisably-no-sandbox`) via `lean/verify_six_kernels.py` (`results/six_kernel_paranoid_audit.json`, `results/six_kernel_paranoid_audit.csv`):
- **Cataloged Theorems**: `20` (`28` total `theorem` declarations in `NucleusWobble.lean`)
- **Static Soundness Audit**: `0` `sorry`, `0` custom `axiom`, `0` `opaque` (`CVE-2026-72711`), `0` nested `inductive` (`CVE-2026-72844`; `1` flat `EvalOutcome`), `0` `Prop` structures (`#14977`), `0` `native_decide` / `Lean.ofReduceBool` (`#16693`; pure kernel `decide` & `omega`).
- **Build & Replay Telemetry**: Clean `lake build` in `14,871.72 ms` (`1,026.4009 J` pkg / `98.0754 J` core `reported_j`); 6-kernel `--paranoid` replay in `305,515.47 ms` (`22,587.3221 J` pkg / `1,808.5280 J` core `reported_j`).

| Independent Kernel | Implementation | Verified Declarations | Sandbox | Verdict |
|---|---|---:|---|---|
| `con-leche --verified` | Minimal reference kernel (Joachim Breitner, ZFC consistent) | `58,748` | `bwrap_linux_namespace` | **ACCEPTS** |
| `con-ron --verified` | Aeneas-verified Rust refinement of `con-leche` | `58,748` | `bwrap_linux_namespace` | **ACCEPTS** |
| `lean4lean` | Lean-in-Lean CIC typechecker (Mario Carneiro) | `58,750` | `bwrap_linux_namespace` | **ACCEPTS** |
| `nanoda` | Standalone Rust NDJSON export verifier (`sorryAx` blocked) | `58,750` | `bwrap_linux_namespace` | **ACCEPTS** |
| `leanchecker --paranoid` | Fresh-environment C++ kernel replay (`#16688` hardened) | `58,750` | `bwrap_linux_namespace` | **ACCEPTS** |
| `Lean v4.36.0 (default)` | Post-CVE Lean 4.36.0 C++ kernel (`611c117bfaf7`) | `58,750` | `bwrap_linux_namespace` | **ACCEPTS** |

**Key Theorem Groups Proved**:
1. **Parseval & 1-Hot Noise Leakage (`6` theorems)**: `fwht6_parseval_identity`, `bipolar_lut6_parseval_4096`, `deg_ge5_mode_count_eq_7`, and `onehot_harmonic_leakage_448_of_4096` (`highHarmonicEnergy (1 <<< k) = 448` out of `4096` = `7/64` for all `k : Fin 64`).
2. **2-Bit Wobble Harmonic Immunity (`5` theorems)**: `wobble_codon_zero_harmonic_energy` (`0` for all `target : Fin 64`), `wobble_codon_lsb_flip_invariance` (identical output across all flips of `i0, i1`), `wobble_codon_matches_own_wobble_box`, `wobble_codon_disjoint_stems`, and `universal_wobble_invariant_cube_zero_deg5` (all $2^{16}$ LSB-wobble-invariant truth tables have zero degree-$\ge 5$ energy).
3. **3-Part Nucleus Retention & Apoptosis (`5` theorems)**: `passesRetentionGate_preserves_all_anchors`, `high_harmonic_candidate_rejected`, `nucleus_roots_immutable_under_refinement_and_apoptosis`, `apoptosis_reject_ceiling_reverts_to_killed_root`, and `apoptosis_opcode_0x3C_rolls_back_to_root`.
4. **4-Part Thermodynamic Means Test (`4` theorems)**: `means_test_amortization_iff` (`N * (e_escalate - e_lut6) > e_compile + e_write <-> totalLut6Cost < totalEscalateCost`), `means_test_nonpositive_margin_refusal`, `means_test_post_payback_monotonicity`, and `means_test_three_wave_conformal_hybrid_iff`.

---

## 4. Bare-Metal MCU Cross-Compilation & Yosys `-lut 6` Packer Audits

### 4.1 Bare-Metal Release ELF Footprints (`results/mcu_cross_compile_audit.json`, `board_metered = false`)

| Target MCU & ISA | `.vector_table` | `.text` | `.rodata` | `.lut6_dtcm` / `.lut6` | `.data` | `.bss` | Total Instructions | Float Insns | `WFI` Insns |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **Alif Ensemble E3/E4 Cortex-M55 HE** (`thumbv8m.main-none-eabihf`, MRAM `@ 0x8000_0000` + DTCM `@ 0x2000_0000`) | `8 B` | `12,260 B` | `0 B` | `16,400 B` | `24 B` | `0 B` | `4,259` | **`0`** | `2` |
| **Raspberry Pi Pico RP2040 Cortex-M0+** (`thumbv6m-none-eabi`, Flash `@ 0x1000_0000` + Striped SRAM `@ 0x2000_0000`) | `8 B` | `11,040 B` | `0 B` | `16,400 B` | `32 B` | `0 B` | `5,248` | **`0`** | `2` |

### 4.2 Yosys `0.71+` `-lut 6` -> `.lut6` Crystal Packer (`packer/compile_and_pack.py`)
- Synthesized `packer/verified_skill.v` via `Yosys 0.71+` (`synth -top verified_skill -noalumacc -nordff; abc -lut 6; clean -purge; write_json`) in `110.65 ms` into `27` `$lut` cells, levelized across `4` layers (`[14, 21, 19, 13]` active gates, `84` packed slots) into `packer/verified_skill.lut6` (`4,096` bytes, CRC-32 `0x16ce2bcf`).
- Verified across **all `16,384` exhaustive 14-bit input vectors** inside Rust `lut6-core` (`verify_lut6`): **`0` scalar mismatches**, **`0` bit-sliced `eval_batch_64` mismatches**, and **`0` 2-bit LSB wobble mismatches** (`results/verify_lut6_rust_audit.json`).

---

## 5. Dual-Reality Three-Wave Metered Benchmark (`100,000` Queries)

Evaluated across `100,000` streaming arrivals (`45,000` Wave 1 exact repeats + `42,000` Wave 2 1–2-bit LSB sensor/paraphrase wobble drift + `13,000` Wave 3 out-of-distribution conformal misses) against a dense 3-layer `INT8` neural micro-classifier (`64 -> 256 -> 128 -> 16`, `51,200` `INT8` MACs/query, `52,800` parameter bytes):
- **Wake Suppression Rate**: **`87.00%`** (`87,000 / 100,000` resolved in `4 KB` `lut6-core` crystal without neural wakeup; exceeds `>= 85.0%` target).
- **Discretization Parity**: **`100.00%`** (**`0.00%` silent corruption**, `0 / 100,000` mismatches across all 3 waves). By contrast, the brittle 1-hot LUT6 ablation (`high_harmonic_energy == 448`) suffers **`39,373 / 100,000` (`39.37%`) silent corruptions** (`60.63%` accuracy) when Wave 2 wobble drift arrives.

### 5.1 Host 1: NVIDIA Jetson AGX Thor (`aarch64` ARMv9, CPU-Only, Physical DC Shunts `measured_j`)
Source: `results/three_wave_jetson_thor_shunt.json` (`Falsifier 6` `5.0 s` pre/post `VDD_CPU_SOC_MSS` idle: `35.3434 W` -> `35.7090 W`, drift `1.034%`; `gpu_cotenant_lock_active = true`, raw rail `measured_j` reported without single-window idle subtraction).

| Regime | Wake Suppression | Silent Corruption | Latency (`ns/eval`) | `VDD_CPU_SOC_MSS` (`uJ/eval`, `measured_j`) | `VDD_CPU_SOC_MSS` `CpJ` (`measured_j`) | `INA238 VIN` `CpJ` (`measured_j`) | Speedup vs `INT8` |
|---|---:|---:|---:|---:|---:|---:|---:|
| **Standalone `INT8` Baseline** (`51.2k` MACs) | `0.00%` | `0.00%` | `6,199.44` | `217.037` | `4,607.5` | `1,860.5` | `1.00x` |
| **Scalar `lut6-core` Three-Wave Hybrid** | **`87.00%`** | **`0.00%`** | `822.31` | `28.335` | **`35,292.3`** (`7.66x`) | **`14,403.9`** (`7.74x`) | **`7.54x`** |
| **Bit-Sliced `lut6-core` Three-Wave Hybrid** | **`87.00%`** | **`0.00%`** | `807.51` | `28.257` | **`35,389.2`** (`7.68x`) | **`13,913.2`** (`7.48x`) | **`7.68x`** |
| **Scalar `lut6-core` Pure Crystal** (Wave 1+2) | `100.00%` | `0.00%` | `20.60` | `0.753` | **`1,328,826.0`** (`288.4x`) | **`545,453.7`** (`293.2x`) | **`300.9x`** |
| **Bit-Sliced `eval_batch_64` Pure Crystal** | `100.00%` | `0.00%` | **`4.91`** | **`0.176`** | **`5,696,804.8`** (`1,236.4x`) | **`2,427,337.5`** (`1,304.7x`) | **`1,262.1x`** |

### 5.2 Host 2: AMD Ryzen AI Max+ 395 (`x86_64` Zen 5, Linux `powercap` RAPL `reported_j`)
Source: `results/three_wave_zen5_rapl.json` (`Falsifier 6` `5.0 s` pre/post package idle: `66.1608 W` -> `74.4864 W`, drift `12.584%`; raw `reported_j` reported without single-window idle subtraction).

| Regime | Wake Suppression | Silent Corruption | Latency (`ns/eval`) | RAPL Core (`uJ/eval`, `reported_j`) | RAPL Core `CpJ` (`reported_j`) | RAPL Pkg `CpJ` (`reported_j`) | Speedup vs `INT8` |
|---|---:|---:|---:|---:|---:|---:|---:|
| **Standalone `INT8` Baseline** (`51.2k` MACs) | `0.00%` | `0.00%` | `5,057.37` | `28.265` | `35,379.4` | `3,038.9` | `1.00x` |
| **Scalar `lut6-core` Three-Wave Hybrid** | **`87.00%`** | **`0.00%`** | `674.30` | `3.299` | **`303,087.7`** (`8.57x`) | **`21,926.1`** (`7.22x`) | **`7.50x`** |
| **Bit-Sliced `lut6-core` Three-Wave Hybrid** | **`87.00%`** | **`0.00%`** | `663.29` | `1.868` | **`535,266.1`** (`15.13x`) | **`26,136.3`** (`8.60x`) | **`7.62x`** |
| **Scalar `lut6-core` Pure Crystal** (Wave 1+2) | `100.00%` | `0.00%` | `13.67` | `0.159` | **`6,286,817.2`** (`177.7x`) | **`927,881.8`** (`305.3x`) | **`370.0x`** |
| **Bit-Sliced `eval_batch_64` Pure Crystal** | `100.00%` | `0.00%` | **`2.27`** | **`0.018`** | **`55,346,126.3`** (`1,564.4x`) | **`5,188,718.3`** (`1,707.4x`) | **`2,230.9x`** |
