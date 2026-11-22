# `game-engines` Empirical Falsifier Suite (`GE-H1` & `GE-H2`)

- **Host**: `Apple M5 Max`, `macOS 27.2.1` (`arm64`)
- **Toolchains**: `rustc 1.100.0 (0ef1bc386 2026-11-09)` | `Apple clang version 21.0.0 (clang-2100.4.1.1)` | `Node.js v26.13.1` | `Python 3.13.14`
- **Energy Discipline**: `measured_j = None`, `board_metered = false`, strictly `reported_j` via macOS kernel per-PID `proc_pid_rusage(child_pid, RUSAGE_INFO_V6).ri_energy_nj` (`SATB` level `L3`, label `D`).

## 1. `GE-H1`: Cross-Target 100,000-Tick Determinism (`Q32.32` Integer Physics)

- **Verdict**: **`PASS_ZERO_MISMATCHES`** (`0` mismatches across `1000` pairwise SHA-256 checkpoint comparisons; `10` target pairs x `100` checkpoints from tick `1,000` to `100,000`).
- **Canonical SHA-256 at tick `1,000`**: `21fa688e4ee8dd6e66dc7b2cc3b674a54c59f9b61967bcf97ecb58f99dc738ae`
- **Canonical SHA-256 at tick `50,000`**: `ea01ba7938411e6a087f2ef1b29d2a92bc53ecb774687766f500566bb8206ce7`
- **Canonical SHA-256 at tick `100,000`**: `82e404df6475d64dbfeaaa0f6cda8092787ea9048446ae862779fa29be0a0a78`

| Target | Wall ms / 100k (mean ± SD) | ns / tick | `L3` `reported_j` / 100k (J) | `L3` nJ / tick | Energy ratio vs Rust | 100/100 SHA-256 match |
|---|---:|---:|---:|---:|---:|:---:|
| `rust_native_aarch64` | `22.333 ± 5.043` | `223.3` | `0.102809 ± 0.024662` | `1028.09` | `1.00x` | `YES` |
| `rust_wasm32_node` | `84.299 ± 11.334` | `843.0` | `0.447975 ± 0.088130` | `4479.75` | `4.36x` | `YES` |
| `cpp20_clang_o3` | `21.022 ± 1.657` | `210.2` | `0.108996 ± 0.013359` | `1089.96` | `1.06x` | `YES` |
| `javascript_bigint_node` | `717.955 ± 36.304` | `7179.6` | `4.402059 ± 0.404803` | `44020.59` | `42.82x` | `YES` |
| `python_3_13` | `2945.816 ± 284.033` | `29458.2` | `13.599870 ± 1.908592` | `135998.70` | `132.28x` | `YES` |

## 2. `GE-H2`: Floating-Point Drift & Chaotic Cascade Boundary Control (`25,000` Ticks)

Each tick records three SHA-256 observables over the 16-body arena:
1. `t_div_ieee_bits`: first tick where canonical IEEE-754 state bits diverge;
2. `t_div_macro_1e3`: first tick where quantized `10^-3` arena-unit positions diverge;
3. `t_div_gameplay`: first tick where discrete gameplay state (`score`, `cooldown FSM`, `active pickups`, `arena quadrant`) diverges.

| Reference | Candidate | Mechanism | `t_div_ieee_bits` | `t_div_macro_1e3` | `t_div_gameplay` |
|---|---|---|---:|---:|---:|
| `cpp_f64_strict` | `rust_f64_strict` | Same-ISA IEEE-754 f64 algebraic+sqrt (FMA off): Clang vs Rustc | `None (>25,000)` | `None (>25,000)` | `None (>25,000)` |
| `cpp_f64_strict` | `js_f64_strict` | Same-ISA IEEE-754 f64 algebraic+sqrt (FMA off): Clang vs V8 Number | `None (>25,000)` | `None (>25,000)` | `None (>25,000)` |
| `cpp_f64_strict` | `py_f64_strict` | Same-ISA IEEE-754 f64 algebraic+sqrt (FMA off): Clang vs CPython float | `None (>25,000)` | `None (>25,000)` | `None (>25,000)` |
| `cpp_f64_strict` | `cpp_f64_fastmath_fma` | Compiler FMA contraction & reassociation: -ffp-contract=off vs -O3 -ffast-math | `192` | `6576` | `10093` |
| `cpp_f64_strict` | `cpp_f32_strict` | Precision step-down: IEEE-754 binary64 (f64) vs binary32 (f32) | `1` | `9` | `2240` |
| `cpp_f64_strict_trig` | `rust_f64_strict_trig` | Same-OS libm sin/cos (f64 strict): Clang vs Rustc | `None (>25,000)` | `None (>25,000)` | `None (>25,000)` |
| `cpp_f64_strict_trig` | `py_f64_strict_trig` | Same-OS libm sin/cos (f64 strict): Clang vs CPython math.sin | `None (>25,000)` | `None (>25,000)` | `None (>25,000)` |
| `cpp_f64_strict_trig` | `js_f64_math_sin_trig` | Cross-runtime transcendental drift (f64 strict, no fast-math): system libm vs Node.js V8 Math.sin/cos | `37` | `5900` | `9136` |
| `cpp_f64_strict_trig` | `cpp_f64_fastmath_trig` | Transcendental + FMA contraction: f64 strict vs -O3 -ffast-math | `7` | `6750` | `9802` |
| `cpp_f64_strict_trig` | `cpp_f32_strict_trig` | Transcendental + binary32 precision: f64 strict vs f32 strict | `1` | `8` | `1370` |
