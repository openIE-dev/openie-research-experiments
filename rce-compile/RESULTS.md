# RCE Compile Wave 4 Results: E4-Energy (`reported_j` & Payback Horizon `N*`) and E5-Scale

- **Pre-registration ID:** `rce-compile-wave4-e4-energy-e5-scale-2026-11-23`
- **Pre-registration SHA-256:** `165a12cda4d9c3043ab8803362fe83aa3e17ad7ea5dea505d3c9dc78105b3c4b` (locked prior to execution)
- **Recorded (UTC):** `2026-11-23T05:27:41Z` (`E4-Energy`), `2026-11-23T05:30:48Z` (`E5-Scale`)
- **Hardware & OS:** `AMD Ryzen AI Max+ 395 w/ Radeon 8060S (Zen 5, 32 logical CPUs)` (`Linux 7.0.0-43-generic x86_64`, process & children pinned to CPU `0`)
- **Energy Provenance:** `basis = "reported"`, `regime = "B"`, `board_metered = false`, `measured_j = null`
- **Counters:** `/sys/class/powercap/intel-rapl:0:0/energy_uj` (CPU core domain) and `/sys/class/powercap/intel-rapl:0/energy_uj` (APU package domain)
- **RCE Engine:** `rce commit 1762fb4bb65a (RCE specification draft 0.9; one language, release label 0.9)`

## 1. E4-Energy: Compiler Tier Medians Across 20 Exact-Integer Kernels (`280 / 280` Checksum-Verified)

| Compiler / Lowering Tier | Median `E_compile` Core (`J`) | Median `E_compile` Pkg (`J`) | Median Build (`s`) | Artifact (`B`) | Median `E_run` Core (`uJ`) | Median `E_run` Pkg (`uJ`) | Median Run (`ns`) |
|---|---:|---:|---:|---:|---:|---:|---:|
| `gcc -O0` | 0.290355 | 4.892 | 0.0402 | 16,384 | 4.1683 | 53.24 | 442.54 |
| `gcc -O2` | 0.472266 | 7.528 | 0.0615 | 16,320 | 1.8067 | 27.24 | 231.50 |
| `gcc -O3` | 0.495455 | 7.890 | 0.0658 | 16,320 | 1.7529 | 24.36 | 213.72 |
| `clang -O0` | 0.492908 | 9.038 | 0.0759 | 16,432 | 4.3551 | 52.72 | 438.21 |
| `clang -O2` | 0.639125 | 11.459 | 0.0961 | 16,368 | 1.2721 | 19.61 | 162.25 |
| `clang -O3` | 0.749995 | 11.479 | 0.0962 | 16,368 | 1.1032 | 15.47 | 132.88 |
| `clang -Os` | 0.591722 | 10.800 | 0.0886 | 16,400 | 1.7534 | 22.51 | 190.87 |
| `rustc -C opt-level=0` | 0.644989 | 11.639 | 0.0966 | 4,567,276 | 13.3417 | 159.57 | 1333.45 |
| `rustc -C opt-level=2` | 1.104000 | 19.838 | 0.1636 | 4,533,388 | 1.3548 | 19.54 | 171.19 |
| `rustc -C opt-level=3` | 1.152619 | 20.059 | 0.1664 | 4,533,552 | 0.7890 | 13.29 | 108.50 |
| `rustc wasm32 -O3 (node)` | 0.485345 | 8.132 | 0.0671 | 1,601 | 1.6390 | 20.95 | 157.25 |
| `python3 py_compile + run` | 0.004141 | 0.056 | 0.0005 | 3,546 | 241.7446 | 2685.98 | 23035.44 |
| `rce check + 5-target emit (node js)` | 0.851289 | 11.644 | 0.0979 | 618,402 | 2519.9885 | 38343.84 | 319638.51 |
| `rce check + emit rust -> rustc -O3` | 56.292484 | 896.930 | 7.4738 | 5,190,208 | 1306.9547 | 15049.10 | 123497.62 |

### 1.1 Empirical Optimization Payback Horizons `N* = ceil(Delta E_compile / Delta E_run)`

| Pair (`low -> high`) | Immediate (`N* = 0`) | Finite `N*` | Never Pays Back (`Delta E_run <= 0`) | Median Finite `N*` | Min–Max Finite `N*` |
|---|---:|---:|---:|---:|---:|
| `gcc_O0_to_O2` | 1/20 | 19/20 | 0/20 | 87,459 | 5,589 – 641,829 |
| `gcc_O0_to_O3` | 0/20 | 20/20 | 0/20 | 102,720 | 14,978 – 1,138,397 |
| `gcc_O2_to_O3` | 5/20 | 11/20 | 4/20 | 106,920 | 17,733 – 13,860,300 |
| `clang_O0_to_O2` | 1/20 | 19/20 | 0/20 | 61,637 | 2,980 – 806,401 |
| `clang_O0_to_O3` | 2/20 | 18/20 | 0/20 | 81,004 | 3,345 – 811,780 |
| `clang_O2_to_O3` | 3/20 | 11/20 | 6/20 | 244,165 | 24,054 – 3,868,746 |
| `clang_Os_to_O3` | 0/20 | 13/20 | 7/20 | 125,805 | 8,006 – 6,184,600 |
| `rustc_0_to_2` | 0/20 | 20/20 | 0/20 | 38,262 | 2,655 – 199,808 |
| `rustc_0_to_3` | 0/20 | 20/20 | 0/20 | 53,464 | 3,148 – 315,616 |
| `rustc_2_to_3` | 7/20 | 7/20 | 6/20 | 176,354 | 45,622 – 1,486,233 |
| `python_to_clang_O3` | 0/20 | 20/20 | 0/20 | 2,490 | 648 – 10,141 |
| `python_to_rustc_3` | 0/20 | 20/20 | 0/20 | 5,263 | 851 – 16,692 |
| `wasm_node_to_rustc_3` | 0/20 | 19/20 | 1/20 | 871,412 | 51,495 – 5,076,039 |
| `rce_js_to_rce_rustc_3` | 0/20 | 18/20 | 2/20 | 31,080 | 13,564 – 449,640 |

### 1.2 H4 Regime-B Variance Analysis on Linux RAPL (`140` Clang + Rust Rows, `2,000` Bootstrap Resamples)

- **WebAssembly IR description length `lambda` (`ir_nodes`, `wasm_bytes`) adjusted `R^2`:** `0.1154` (95% CI `[0.0654, 0.4058]`)
- **Regime-B `wall_s * mean_core_power_w` baseline adjusted `R^2`:** `0.9999` (95% CI `[0.9987, 1.0]`)
- **Baseline minus `lambda` (`Delta` adjusted `R^2`):** `+0.8845` (95% CI `[0.5979, 0.9352]`; Regime-B prediction holds: `True`).

## 2. E5-Scale: Name-Free Reuse Hashing (`245` Base Programs & `500` Verified Semantic Mutants)

### 2.1 Equivalence-Preserving Hit Rates

| Corpus & Transform | Pairs | Raw SHA-256 | Comment/WS-Stripped | Naive AST Token-Kind | De Bruijn / Nameless |
|---|---:|---:|---:|---:|---:|
| 185 W1 RCE Forms (`rce fmt nameless`) · `fmt_shift` | 185 | 0 | 185 | 185 | **0** |
| 185 W1 RCE Forms (`rce fmt nameless`) · `alpha_rename` | 185 | 0 | 50 | 185 | **128** |
| 185 W1 RCE Forms (`rce fmt nameless`) · `decl_reorder` | 23 | 0 | 0 | 8 | **0** |
| 60 C/Rust/Python Kernels · `fmt_shift` | 60 | 0 | 60 | 60 | **60** |
| 60 C/Rust/Python Kernels · `alpha_rename` | 60 | 0 | 0 | 60 | **40** |
| 60 C/Rust/Python Kernels · `decl_reorder` | 60 | 0 | 0 | 0 | **60** |

*Diagnostic note on `rce fmt nameless` at `1762fb4b`:* `rce fmt nameless` preserves `#` comments in formatted output so that the emitted text remains valid source with comments intact (`0/185` on comment-bearing `fmt_shift`, `128/185 = 69.2%` on `alpha_rename` where 50 no-identifier or stdlib-field Forms fell back to comment shifts). Stripping `#` comments from `rce fmt nameless` raises `fmt_shift` to `185/185` (`100.0%`).

### 2.2 Soundness on `500` Test-Vector-Verified Non-Equivalent Semantic Mutants

| Mutant Class | Verified Non-Equivalent Mutants | Raw SHA-256 Collisions | WS-Strip Collisions | Naive AST ID-Strip Collisions | De Bruijn Nameless Collisions |
|---|---:|---:|---:|---:|---:|
| `binding_swap` | 150 | 0 | 0 | **150** | **0** |
| `operator` | 150 | 0 | 0 | **0** | **0** |
| `literal` | 125 | 0 | 0 | **0** | **0** |
| `guard` | 75 | 0 | 0 | **0** | **0** |
| `all_500` | 500 | 0 | 0 | **150** | **0** |

- **Cross-program unordered pairs checked (`245` base programs):** `29,890` (`0` De Bruijn collisions).
- **Verdict (`H5_Scale`):** Supported (`0 / 500 = 0.00%` false-positive collisions on De Bruijn nameless vs `150 / 150 = 100.0%` binding-swap collisions and `150 / 500 = 30.0%` overall false hits on naive AST identifier-stripping).

### 2.3 Avoided Compilation `reported_j` Under Warm De Bruijn Cache

- **`clang -O3` (per C kernel):** `0.6823 J` core cold (`82.03 ms`) vs `4.066 mJ` warm (`342.0 us`) -> **`167.8x` reduction** (`0.6782 J` core avoided per hit).
- **`rustc -C opt-level=3` (per Rust kernel):** `1.1660 J` core cold (`143.81 ms`) vs `2.600 mJ` warm (`288.1 us`) -> **`448.5x` reduction** (`1.1634 J` core avoided per hit).
- **`rce check + 5-target emit` (per W1 Form):** `78.71 mJ` core cold (`9.85 ms`) vs `4.59 mJ` warm `rce fmt nameless` (`0.74 ms`) -> **`17.15x` reduction** (`74.12 mJ` core avoided per hit).
