# Kit 5: `waios-mosaic-cascade` — 4-Stage Spellcheck Lookup-First Cascade & Cross-Lane `waiOS` Conformance (`a541323b...`)

- **License:** `Apache-2.0`
- **Provenance Tier:** `Signed Provenance · Self-Checked` (`BLAKE3` + `Ed25519` offline-verifiable receipt; never self-labeled `"Verified"`)
- **Research Scope:** Shots on Goal #3 & #5 — Cross-lane integer/ternary HeteroMosaic execution sealed by the canonical `waiOS` `256×128` reference digest (`a541323b13653ed36515ff24ef08deb7dfa771e570a434712708fb72552f46f0`), embedded inside a hardware-metered **4-Stage Spellcheck Lookup-First Cascade** (`1,000` mixed recurring + novel queries).

---

## 1. 1-Command Reproduction

From the repository root (requires `python3 >= 3.10` and a C compiler `cc` / `gcc` / `clang` with `pthread`; zero proprietary or third-party Python packages required):

```bash
./kits/waios-mosaic-cascade/run_kit.sh
```

Fast smoke test (`--quick`):

```bash
./kits/waios-mosaic-cascade/run_kit.sh --quick
```

Run unit, invariance, and fault-injection halt tests directly:

```bash
pytest kits/waios-mosaic-cascade/tests/test_waios_mosaic_cascade.py
# or without pytest:
python3 -m unittest kits/waios-mosaic-cascade/tests/test_waios_mosaic_cascade.py
```

---

## 2. What This Kit Implements & Measures

### Part A — Canonical `waiOS` `256×128` Cross-Lane Invariance & Disagreement Halt (Shot #3)
Reproduces the exact deterministic `256×128` ternary matrix-vector program (`SEED = 0xdeadbeefcafebabe`, `BLAKE3` key-derivation context `"waios.tmac.v1"`) and verifies bit-exact equality against `a541323b13653ed36515ff24ef08deb7dfa771e570a434712708fb72552f46f0` across:
1. `python_scalar_i32`: Independent pure-Python `int32` reference loop.
2. `c_scalar_i32`: Native `C (-O2 -mpopcnt)` row-major `int32` reference lane.
3. `c_packed_2bit_bitsliced`: Packed `+1 / -1` `uint64` masks + 7-plane magnitude `popcount` (`0` multiplications).
4. `c_tmac_pair_lut`: 2-column pair lookup table over `waiOS`'s 4-bit packed ternary layout (`0` multiplications).
5. `c_hetero_mosaic_4worker_pthreads`: 4-thread `pthread` HeteroMosaic runtime combining unrolled CPU/SIMD, FPGA-style `64`-wide split-half addition, T-MAC LUT, and bit-sliced `popcount` workers across `100` shifted tile-partition schedules (`0 / 100` disagreements; exact Clopper–Pearson 95% upper bound `<= 0.029513`).
6. **Single-Weight Tamper Fault Injection (`row 77`):** Mutates one weight at `(row=77, first non-zero col)`, reproduces the exact external tamper digest `4ac7c4fbc2f2a031ac4f3c0e485867fb689d24d4872bdb1b0a6bc80cf88b69dc`, triggers `WaiosDisagreementHaltError`, and **refuses to seal a receipt**.

### Part B — 4-Stage Spellcheck Lookup-First Cascade on `1,000` Mixed Queries (Shot #5)
Routes `1,000` deterministic recurring, typo/variant, novel-feature, and hard-boundary queries through:
1. **Stage 1 (`O(1)` Compiled Hash/LUT Lookup):** Resolves recurring canonical/alias commands in `O(1)` with `0` FLOPs.
2. **Stage 2 (Trigram Sparse Inverted Index + Damerau–Levenshtein `<= 2` Gate):** Resolves near-miss typos with `0` neural FLOPs.
3. **Stage 3 (`waiOS`-Boot-Qualified `256×128` Integer Mosaic + Margin Gate):** Resolves novel structured telemetry queries in exact integer arithmetic when top-1 margin exceeds threshold.
4. **Stage 4 (Frontier Escalation Gate):** Escalates only the `2.6%` low-margin residual (`26 / 1,000` queries, `38.46x` call avoidance) to an 8-layer dense verifier.

---

## 3. Energy & Meter-Class Separation (`reported_j ⊥ est_j`)

- Local cascade vs. non-cascaded baselines (`always_stage3_mosaic_plus_gate` and `always_dense_teacher_baseline`) are measured on the **same Linux RAPL hardware counter (`reported_j`)** (or `unmetered` wall-clock when RAPL is unreadable without root).
- Analytical remote cloud inference figures (`est_j`) are reported in a **strictly isolated section and JSON block** (`mixed_or_summed_with_reported_j: false`) and are never added to or divided by `reported_j`.
- Output artifacts (`results/waios_mosaic_cascade_results.json`, `results/waios_mosaic_receipt.json`, and [`RESULTS.md`](./RESULTS.md)) pass `assert_sanitized()`.

### Shot on Goal #6 — Cross-ISA `aarch64`/`x86_64` Conformance, Physical Shunt `measured_j` & 75-Cell Cascade Sweep
- Verifies bit-exact `waiOS` digest `a541323b13653ed36515ff24ef08deb7dfa771e570a434712708fb72552f46f0` across all 5 lanes and `row 77` fault-injection halt (`4ac7c4fb...`) on `NVIDIA Jetson AGX Thor` (`ARMv9`), `AMD Kria KV260` (`Cortex-A53`), and `x86_64`.
- Evaluates a `75`-cell `(Zipf s ∈ {0.0..1.40}, d_max ∈ {0,1,2}, margin tau ∈ {1500..9000})` cascade grid sweep metered on `TI INA3221`/`INA238` (`Thor`) and `TI INA260` (`KV260`) physical DC shunt rails (`measured_j`) and Linux `RAPL` (`reported_j`), keeping Stage-4 analytical `est_j` strictly isolated (`mixed_or_summed: false`). Cross-substrate signed receipts are stored in [`results/multi_substrate_receipts.json`](./results/multi_substrate_receipts.json) and summarized in [`RESULTS.md`](./RESULTS.md).

### Cross-Fabric `waiOS` Conformance (`CPU + GPU + CPU+GPU + WASM + Verilog RTL + RV32IMAC MCU`)
- When optional toolchains are present (`glslc` + `libvulkan`, `clang --target=wasm32` + `node`, `iverilog`/`vvp`, `rustc --target riscv32imac-unknown-none-elf` + `qemu-riscv32`), `cross_fabric.py` compiles and verifies bit-exact `a541323b13653ed36515ff24ef08deb7dfa771e570a434712708fb72552f46f0` and row-`77` tamper halt (`4ac7c4fb...`) across hardware Vulkan GPU compute (`Radeon 8060S`), co-scheduled `CPU + GPU` HeteroMosaic row splits (`20` cuts), `WebAssembly SIMD128` (`1,041 B`), cycle-accurate zero-multiplier Verilog RTL (`waios_ternary_rtl.v`), and a `1,444 B` `#![no_std]` zero-FPU `RV32IMAC` bare-metal microcontroller ELF.
