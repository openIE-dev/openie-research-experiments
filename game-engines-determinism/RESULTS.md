# `game-engines` Wave 3 Empirical Falsifier Suite: Multi-ISA `GE-H1`, Cross-ISA `GE-H2`, and Cross-GPU `GE-H3` (`wgpu`)

- **Pre-registration**: `PREREG_wave3_multi_isa_wgpu.json` (`SHA-256: 1721e5bdffaf035e6a1d7040048d1f6199030a12215e7c39e1f8b0355c0d99fe`)
- **Workspace root**: `$BENCH_ROOT` (all local and remote paths scrubbed)
- **Energy & Telemetry Discipline**:
  - `measured_j = null`, `board_metered = false` across all runs (no external hardware wall/rail watt-meter attached).
  - `SATB L2` (`reported_j` socket/core scope): Linux `/sys/class/powercap/intel-rapl:0/energy_uj` (`package-0`) and `intel-rapl:0:0/energy_uj` (`core`) on AMD Zen 5 and Intel Raptor Lake `x86_64` hosts.
  - `SATB L3` (`reported_j` per-process scope): macOS `proc_pid_rusage(child_pid, RUSAGE_INFO_V6).ri_energy_nj` on Apple M5 Max and Apple M3 Ultra `arm64` hosts.
  - `est_j`: analytical Landauer and Hellman model parameters used strictly inside the `/living/game-engines/` Chrono-Budget Arena mini-game, never mixed with hardware counters.

---

## 1. `GE-H1`: Multi-ISA & Multi-OS 100,000-Tick Determinism (`Q32.32` 64-Bit Integer Physics)

The identical 16-body + 4-pickup 2D arena Form (`arena16_q32_32_v1`, `[-64, +64]` `Q32.32` fixed-point coordinates, `128`-bit intermediate products, integer floor square root `isqrt_u128`, deferred structural pickup respawn, `732`-byte little-endian canonical state vector) was executed across **5 hosts, 3 instruction set architectures (`arm64`/`AArch64`, `x86_64`, `wasm32`), 2 operating systems (`macOS 27.2.1`, `Ubuntu Linux 6.8 / 7.0`), and 6 language/compiler projections (`25` target × host cells)**:

- **Verdict**: **`PASS_ZERO_MISMATCHES`**
  - **`20,500` verified `SHA-256` state checkpoints** (`20` Wave 3 cells × `1,000` stride-`100` checkpoints from tick `100` to `100,000` + `5` Apple M5 Max cells × `100` stride-`1,000` checkpoints) with **`0` mismatches** (`190,000` pairwise cross-host checkpoint comparisons at stride `100`, `0` mismatches).
  - Canonical digests reproduced on every host and runtime:
    - Tick `100`: `2683c3f7cb8b29eb64da8121161b0edbadececcc65b35a8ecf01e90aa3d15445`
    - Tick `1,000`: `21fa688e4ee8dd6e66dc7b2cc3b674a54c59f9b61967bcf97ecb58f99dc738ae`
    - Tick `10,000`: `0c60a804c15b682626442bdcd600869359ebdf1d70ff9f1f6ac5f47a38c95728`
    - Tick `50,000`: `ea01ba7938411e6a087f2ef1b29d2a92bc53ecb774687766f500566bb8206ce7`
    - Tick `100,000`: `82e404df6475d64dbfeaaa0f6cda8092787ea9048446ae862779fa29be0a0a78`
  - **Windows PE / Wine disclosure**: `x86_64-w64-mingw32-g++` and `wine64` were checked and not installed on the shared Linux runners, and the bare-metal Windows fleet host was powered off / outside the active Linux+macOS runner pool during Wave 3 execution.

| Host (`ISA` / `OS`) | Target projection | Wall ms / `100k` (mean ± SD) | `ns / tick` | Telemetry channel | `reported_j` / `100k` (J) | Checkpoints matched |
|---|---|---:|---:|---|---:|:---:|
| **AMD Ryzen AI Max+ 395** (`x86_64` Linux `7.0`) | `rust_native` (`rustc 1.100 -O`) | `21.793 ± 0.558` | `217.9` | `L2` RAPL pkg (core `0.131 J`) | `1.9577 ± 0.2506` | `1,000 / 1,000` |
| **AMD Ryzen AI Max+ 395** (`x86_64` Linux `7.0`) | `cpp20_clang_o3` (`Clang 21.1.8`) | `23.061 ± 0.427` | `230.6` | `L2` RAPL pkg (core `0.197 J`) | `2.3491 ± 0.0415` | `1,000 / 1,000` |
| **AMD Ryzen AI Max+ 395** (`x86_64` Linux `7.0`) | `cpp20_gcc_o3` (`GCC 15.2.0`) | `26.677 ± 0.985` | `266.8` | `L2` RAPL pkg (core `0.210 J`) | `2.9321 ± 0.3152` | `1,000 / 1,000` |
| **AMD Ryzen AI Max+ 395** (`x86_64` Linux `7.0`) | `rust_wasm32_node` (`Node v22.22`) | `145.291 ± 3.844` | `1,452.9` | `L2` RAPL pkg (core `1.007 J`) | `14.4430 ± 1.7730` | `1,000 / 1,000` |
| **AMD Ryzen AI Max+ 395** (`x86_64` Linux `7.0`) | `javascript_bigint_node` (`Node v22.22`) | `1,347.803 ± 35.308` | `13,478.0` | `L2` RAPL pkg (core `6.263 J`) | `115.8125 ± 4.1844` | `1,000 / 1,000` |
| **AMD Ryzen AI Max+ 395** (`x86_64` Linux `7.0`) | `python3_int` (`Python 3.14.4`) | `2,546.420 ± 31.298` | `25,464.2` | `L2` RAPL pkg (core `12.231 J`) | `181.8714 ± 10.5057` | `1,000 / 1,000` |
| **Intel Core i9-13900H** (`x86_64` Linux `7.0`) | `rust_native` (`rustc 1.100 -O`) | `39.718 ± 3.508` | `397.2` | `L2` Intel RAPL pkg (core `1.827 J`) | `2.0620 ± 0.1704` | `1,000 / 1,000` |
| **Intel Core i9-13900H** (`x86_64` Linux `7.0`) | `cpp20_clang_o3` (`Clang 21.1.8`) | `36.868 ± 4.305` | `368.7` | `L2` Intel RAPL pkg (core `1.642 J`) | `1.8880 ± 0.2668` | `1,000 / 1,000` |
| **Intel Core i9-13900H** (`x86_64` Linux `7.0`) | `cpp20_gcc_o3` (`GCC 15.2.0`) | `58.792 ± 24.182` | `587.9` | `L2` Intel RAPL pkg (core `2.678 J`) | `3.0265 ± 1.3587` | `1,000 / 1,000` |
| **Intel Core i9-13900H** (`x86_64` Linux `7.0`) | `rust_wasm32_node` (`Node v22.14`) | `158.348 ± 8.258` | `1,583.5` | `L2` Intel RAPL pkg (core `5.648 J`) | `6.8947 ± 0.8968` | `1,000 / 1,000` |
| **Intel Core i9-13900H** (`x86_64` Linux `7.0`) | `javascript_bigint_node` (`Node v22.14`) | `1,390.455 ± 97.262` | `13,904.6` | `L2` Intel RAPL pkg (core `50.118 J`) | `60.7868 ± 11.1101` | `1,000 / 1,000` |
| **Intel Core i9-13900H** (`x86_64` Linux `7.0`) | `python3_int` (`Python 3.14.4`) | `3,375.073 ± 303.369` | `33,750.7` | `L2` Intel RAPL pkg (core `124.904 J`) | `149.4797 ± 20.0622` | `1,000 / 1,000` |
| **NVIDIA Jetson Thor** (`aarch64` Linux `6.8`) | `rust_native` (`rustc 1.100 -O`) | `40.834 ± 1.061` | `408.3` | CPU-only (`reported_j = null`) | `null` | `1,000 / 1,000` |
| **NVIDIA Jetson Thor** (`aarch64` Linux `6.8`) | `cpp20_clang_o3` (`Clang 18.1.3`) | `48.275 ± 2.250` | `482.8` | CPU-only (`reported_j = null`) | `null` | `1,000 / 1,000` |
| **NVIDIA Jetson Thor** (`aarch64` Linux `6.8`) | `cpp20_gcc_o3` (`GCC 13.3.0`) | `39.284 ± 0.881` | `392.8` | CPU-only (`reported_j = null`) | `null` | `1,000 / 1,000` |
| **NVIDIA Jetson Thor** (`aarch64` Linux `6.8`) | `rust_wasm32_node` (`Node v24.22`) | `171.641 ± 4.265` | `1,716.4` | CPU-only (`reported_j = null`) | `null` | `1,000 / 1,000` |
| **NVIDIA Jetson Thor** (`aarch64` Linux `6.8`) | `javascript_bigint_node` (`Node v24.22`) | `1,449.457 ± 59.252` | `14,494.6` | CPU-only (`reported_j = null`) | `null` | `1,000 / 1,000` |
| **NVIDIA Jetson Thor** (`aarch64` Linux `6.8`) | `python3_int` (`Python 3.12.3`) | `4,407.885 ± 92.489` | `44,078.9` | CPU-only (`reported_j = null`) | `null` | `1,000 / 1,000` |
| **Apple M3 Ultra** (`arm64` `macOS 27.2.1`) | `rust_native` (`rustc 1.100 -O`) | `32.711 ± 1.052` | `327.1` | `L3` per-PID `ri_energy_nj` | `0.0729 ± 0.0024` | `1,000 / 1,000` |
| **Apple M3 Ultra** (`arm64` `macOS 27.2.1`) | `cpp20_clang_o3` (`Apple Clang 21.0`) | `33.727 ± 2.633` | `337.3` | `L3` per-PID `ri_energy_nj` | `0.0755 ± 0.0027` | `1,000 / 1,000` |
| **Apple M5 Max** (`arm64` `macOS 27.2.1`, baseline) | `5` targets (`Rust`, `C++20`, `Wasm`, `JS`, `Py`) | `21.02` – `2,945.82` | `210.2` – `29,458.2` | `L3` per-PID `ri_energy_nj` | `0.1028` – `13.5999` | `5 × 100 / 100` |

---

## 2. `GE-H2`: Cross-ISA & Cross-OS 25,000-Tick Floating-Point Drift (`IEEE-754` `f64`)

| Host / Target A | Host / Target B | Mechanism (all without `-ffast-math` unless noted) | `t_div_ieee_bits` | `t_div_macro_1e3` | `t_div_gameplay` |
|---|---|---|---:|---:|---:|
| `arm64` macOS `Clang 21` (`f64_strict`) | AMD Zen 5 & Intel RPL `x86_64` Linux `Clang 21` (`f64_strict`) | Cross-ISA & Cross-OS IEEE-754 `f64` algebraic + `sqrt`, `FMA` off (`-ffp-contract=off`) | `None (>25,000)` | `None (>25,000)` | `None (>25,000)` |
| `aarch64` Thor `GCC 13.3` / `Rust 1.100` (`f64_strict`) | AMD `x86_64` `GCC 15.2` / `Rust 1.100` (`f64_strict`) | Cross-ISA Linux IEEE-754 `f64` algebraic + `sqrt`, `FMA` off | `None (>25,000)` | `None (>25,000)` | `None (>25,000)` |
| **Apple `arm64` macOS (`f64_trig`, `-ffp-contract=off`)** | **AMD/Intel `x86_64` Linux & Thor `aarch64` Linux (`f64_trig`, `-ffp-contract=off`)** | **Cross-OS `libm` `std::sin/cos` (`Apple libSystem` vs `GNU glibc 2.39/2.43`, NO `-ffast-math`)** | **`10`** (`0.17 s`) | **`5,900`** | **`9,798`** (`163.3 s`) |
| `x86_64` Linux `glibc 2.43` (`f64_trig`) | `aarch64` Linux `glibc 2.39` (`f64_trig`) | Cross-ISA GNU `glibc` `std::sin/cos` (`-ffp-contract=off`) | `None (>25,000)` | `None (>25,000)` | `None (>25,000)` |
| **`x86_64` Linux `Node v22.22` (`f64_trig`)** | **`aarch64` Linux `Node v24.22` (`f64_trig`)** | **Cross-ISA Node.js V8 `Math.sin/cos` (`x86_64` vs `aarch64`)** | **`66`** (`1.10 s`) | **`7,617`** | **`10,093`** (`168.2 s`) |
| **`x86_64` Linux `glibc 2.43` (`f64_trig`)** | **`x86_64` Linux `Node v22.22` (`f64_trig`)** | **Same-host `x86_64` Linux `std::sin/cos` vs V8 `Math.sin/cos`** | **`10`** (`0.17 s`) | **`6,190`** | **`9,136`** (`152.3 s`) |
| **AMD/Intel `x86_64` (`-O3 -mavx2 -mfma -ffp-contract=fast`)** | **Apple `arm64` & Thor `aarch64` (`-O3 -ffp-contract=fast`)** | **Cross-ISA hardware `FMA` lowering (`x86_64 VFMADD/VFNMADD` vs `AArch64 FMADD/FMSUB`, algebraic only, NO `-ffast-math`)** | **`406`** (`6.77 s`) | **`7,422`** | **`11,205`** (`186.8 s`) |
| Apple `arm64` `Clang 21` (`f64_fma`) | Thor `aarch64` `Clang 18` (`f64_fma`) | Same-ISA-family `AArch64` `fmadd` (`macOS` vs `Linux`) | `None (>25,000)` | `None (>25,000)` | `None (>25,000)` |
| AMD Zen 5 `x86_64` (`f64_fma`) | Intel Raptor Lake `x86_64` (`f64_fma`) | Same-ISA `x86_64` `AVX2+FMA3` (`AMD` vs `Intel`) | `None (>25,000)` | `None (>25,000)` | `None (>25,000)` |

---

## 3. `GE-H3`: Cross-GPU Headless `wgpu` (`Metal` / `Vulkan`) Rendering Tolerance (`512×512` `RGBA8Unorm`)

Four canonical `Q32.32` simulation states (`ticks 0, 250, 1000, 10000`) were rendered into `512×512` `RGBA8Unorm` framebuffers (`262,144` pixels = `1,048,576` bytes/frame) across **4 physical GPUs spanning 4 hardware vendors and 2 graphics APIs**, plus `Mesa llvmpipe` software Vulkan and a zero-float `CPU Q16.16` integer software reference rasterizer:

- **Upstream Exact Zone (`S`)**: `0` `SHA-256` mismatches across all GPU hosts at ticks `0, 250, 1000, 10000`.
- **CPU `Q16.16` Integer Rasterizer**: `0` `SHA-256` framebuffer mismatches across `Apple M3 Ultra arm64`, `AMD Zen 5 x86_64`, and `Intel Raptor Lake x86_64` (`100%` bitwise identical, `~17–21 ms/frame`).
- **Physical GPU Tolerance Verdict (`GE-H3`)**: **`PASS_BOUNDED_TOLERANCE_CONFIRMED`**
  - **`24 / 24` physical GPU frame comparisons (`6` GPU pairs × `4` frames) produce distinct `SHA-256` digests** (`1.30%` to `9.34%` of pixels differ by `1–2 LSB`), confirming WGSL/hardware SFU and ROP non-bit-exactness.
  - **`24 / 24` pass the pre-registered tolerance gate** (`PSNR = 64.16`–`72.06 dB > 40.0 dB`, `SSIM = 0.999833`–`0.999986 > 0.999`, $\Delta_{\max} \le 2 \le 8$, outlier fraction `0.000000 <= 0.001`).

| GPU Adapter A | GPU Adapter B | Mean differing pixels (`%`) | Max $|\Delta|$ (`0..255`) | Mean MAE (`u8`) | Mean RMSE (`u8`) | Min PSNR (`dB`) | Min SSIM | `GE-H3` Gate |
|---|---|---:|---:|---:|---:|---:|---:|:---:|
| **Apple M3 Ultra (`Metal`)** | **Intel Iris Xe (`ANV` Vulkan)** | `1.301%` | `2` | `0.00386` | `0.06215` | **`72.06`** | **`0.999986`** | **PASS** |
| **AMD Radeon 8060S (`RADV` Vulkan)** | **Apple M3 Ultra (`Metal`)** | `3.103%` | `1` | `0.00788` | `0.08876` | **`69.09`** | **`0.999956`** | **PASS** |
| **AMD Radeon 8060S (`RADV` Vulkan)** | **Intel Iris Xe (`ANV` Vulkan)** | `3.774%` | `2` | `0.01022` | `0.10116` | **`67.97`** | **`0.999951`** | **PASS** |
| **AMD Radeon 8060S (`RADV` Vulkan)** | **NVIDIA RTX 4050 (`NVIDIA` Vulkan)** | `6.553%` | `2` | `0.01735` | `0.13179` | **`65.64`** | **`0.999874`** | **PASS** |
| **Intel Iris Xe (`ANV` Vulkan)** | **NVIDIA RTX 4050 (`NVIDIA` Vulkan)** | `8.280%` | `2` | `0.02149` | `0.14667` | **`64.79`** | **`0.999844`** | **PASS** |
| **Apple M3 Ultra (`Metal`)** | **NVIDIA RTX 4050 (`NVIDIA` Vulkan)** | `9.337%` | `2` | `0.02467` | `0.15720` | **`64.16`** | **`0.999833`** | **PASS** |
| Physical GPUs (`4` vendors) | `Mesa llvmpipe` (LLVM `21.1.8` Vulkan) | `1.541%` – `9.633%` | `2` – `3` | `0.00477` – `0.02601` | `0.06895` – `0.16173` | `63.86` – `70.87` | `0.999828` – `0.999984` | **PASS** |
| Physical GPUs (`4` vendors) | `CPU Q16.16` Zero-Float Reference | `20.400%` – `27.626%` | `2` | `0.05612` – `0.07864` | `0.23689` – `0.28068` | `59.13` – `60.58` | `0.999556` – `0.999693` | **PASS** |
