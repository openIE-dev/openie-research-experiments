# RCE Compile Wave 5 Results: `E4-Prelude` Pre-Compiled `librce_rt.rlib` Shared Runtime Crate

- **Pre-registration ID:** `rce-compile-wave5-e4-prelude-rlib-2026-11-23`
- **Pre-registration SHA-256:** `1ba4f28abfaa3783079da01b61cf9bbdff9ff9e441ca0bcbcdfdf5d546735998` (locked prior to execution)
- **Wave 4 Baseline SHA-256:** `165a12cda4d9c3043ab8803362fe83aa3e17ad7ea5dea505d3c9dc78105b3c4b`
- **Recorded (UTC):** `2026-11-23T11:09:47Z` (Zen 5 primary), `2026-11-23T12:23:28Z` (Core i9-13900H quiet dedicated cross-check)
- **Energy Provenance:** `basis = "reported"`, `regime = "B"`, `board_metered = false`, `measured_j = null`
- **RCE & Rust Toolchains:** `rce commit 1762fb4bb65a` + `rustc 1.100.0 (0ef1bc386 2026-11-09)` + `node v22.22.1`

## 1. One-Time `librce_rt.rlib` Runtime Crate Build (`rce_rt.rs`, `2,286` Lines / `143,427` Bytes)

| Host | `.rlib` Size (`B`) | Byte-Identical (`5/5` Trials) | Median `E_compile` Core (`J`) | Median `E_compile` Pkg (`J`) | Median Build (`ms`) | Idle Pkg Drift (`F6`) |
|---|---:|:---:|---:|---:|---:|---:|
| `AMD Ryzen AI Max+ 395` (Zen 5, CPU 0) | `5,409,636` | `true` (`ecfdc64c8d5f141e…`) | `66.0344` | `575.648` | `7,103.8` | `3.40%` (`< 10%`) |
| `Intel Core i9-13900H` (Quiet CPU 0) | `5,409,796` | `true` (`da7118e13d3950ba…`) | `111.8198` (PP0) | `142.630` | `6,581.8` | `6.62%` (`< 10%`) |

## 2. 15th Compiler Tier Summary Across 20 Exact-Integer Kernels (`20 / 20` Checksum-Verified, `0` Mismatches)

| Lowering Tier / Host | Median `E_compile` Core (`J`) | Median `E_compile` Pkg (`J`) | Median Build (`ms`) | Artifact (`B`) | Median `E_run` Core (`uJ`) | Median `E_run` Pkg (`uJ`) | Median Run (`ns`) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Wave 4 `rce check + 5-target emit (node js)` (Zen 5) | `0.8513` | `11.644` | `97.94` | `618,402` | `2,519.99` | `38,343.84` | `319,638.5` |
| Wave 4 `rce check + emit rust -> rustc -O3` (Monolithic, Zen 5) | `56.2925` | `896.930` | `7,473.83` | `5,190,208` | `1,306.95` | `15,049.10` | `123,497.6` |
| Same-Session Monolithic `rce -> rustc -O3` (Zen 5) | `44.4513` | `460.812` | `4,996.61` | `5,190,208` | — | — | — |
| **Wave 5 `rce check + emit rust -> rustc -O3 (shared .rlib)` (Zen 5)** | **`2.8053`** | **`27.045`** | **`304.10`** | **`5,303,456`** (`944,544` stripped) | **`1,212.03`** | **`8,864.82`** | **`94,571.7`** |
| Same-Session Monolithic `rce -> rustc -O3` (Quiet `i9-13900H`) | `84.4024` (PP0) | `104.560` | `4,397.44` | `5,190,264` | — | — | — |
| **Wave 5 `rce check + emit rust -> rustc -O3 (shared .rlib)` (Quiet `i9-13900H`)** | **`5.4661`** (PP0) | **`6.851`** | **`277.47`** | **`5,303,512`** | **`1,717.33`** | **`2,099.70`** | **`97,086.6`** |

- **Per-kernel compile energy reduction:** **`20.07×` lower `compile_core_reported_j`** (`24.58×` faster) vs. Wave 4 monolithic prelude on Zen 5 (`15.85×` core reduction and `16.43×` wall-clock speedup vs. same-session monolithic on Zen 5; **`15.44×` PP0 core reduction**, **`15.26×` full-package reduction**, and **`15.85×` speedup** on the dedicated quiet `i9-13900H` host).
- **20-kernel suite total compile energy (Zen 5 core `reported_j`):** **`128.17 J`** including the one-time `66.03 J` `librce_rt.rlib` build, down from **`1,108.01 J`** monolithic (**`8.65×` suite reduction**).

## 3. Optimization Payback Horizons `N*` (`rce -> node js` vs. `rce -> rustc -O3`)

| Accounting Basis (Zen 5 Core `reported_j`) | Finite `N*` | Never (`Delta E_run <= 0`) | Median Finite `N*` | Min–Max Finite `N*` | Improvement vs. Wave 4 (`31,080`) |
|---|---:|---:|---:|---:|---:|
| Wave 4 Monolithic Prelude (`56.29 J`/kernel) | `18/20` | `2/20` | `31,080` | `13,564 – 449,640` | `1.00×` |
| **Wave 5 Shared `.rlib` — Marginal (`2.81 J`/kernel, toolchain `.rlib`)** | **`17/20`** | **`3/20`** | **`1,079`** | **`404 – 5,650`** | **`28.80×` lower `N*`** |
| **Wave 5 Shared `.rlib` — 20-Kernel Amortized (`+3.30 J`/kernel)** | **`17/20`** | **`3/20`** | **`3,110`** | **`1,294 – 9,326`** | **`9.99×` lower `N*`** |
| Wave 5 Shared `.rlib` — Cold Single-Kernel (`+66.03 J` full `.rlib`) | `17/20` | `3/20` | `37,744` | `18,198 – 79,159` | Breaks even by `>= 2` kernels |
| Wave 5 Shared `.rlib` — Marginal vs. Same-Session Node JS | `18/20` | `2/20` | `1,974` | `732 – 56,133` | `15.74×` lower `N*` |

## 4. Pre-Registered Falsifier Audit

- **`F1_checksum_mismatch`:** `false` (`20 / 20` exact 2,000-seed unsigned batch checksum matches on both Zen 5 and Core i9-13900H; `300 / 300` total cells across all 15 tiers).
- **`F2_no_compile_energy_reduction` (`< 10×`):** `false` (`20.07×` vs. Wave 4 and `15.85×` same-session on Zen 5; `15.44×` PP0 and `15.26×` package on quiet Core i9-13900H).
- **`F6_idle_drift` (`> 10%`):** Package drift **`3.40%`** on Zen 5 (`49.825 W -> 51.517 W`) and **`6.62%`** on quiet Core i9-13900H (`4.461 W -> 4.756 W`), both `< 10%`; sub-watt idle core sleep quantization (`1.33 W -> 1.88 W` and `0.39 W -> 0.77 W`) is flagged transparently alongside gross `core_reported_j` and `pkg_reported_j`.
