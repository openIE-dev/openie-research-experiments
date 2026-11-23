# Wave 4 · Lane 1: Bare-Metal Windows 11 (`x86_64` PE + `DirectX 12`) & 5-Host `SATB` Empirical Bundle

- **Benchmark Root**: `$BENCH_ROOT`
- **Energy Discipline**: `measured_j = None` and `board_metered = false` on `game-engines` and on the Windows 11 host in `satb-harness`. `macOS L3 ri_energy_nj`, `Linux L2 RAPL`, `Jetson Thor INA238/INA3221 measured_j`, and `Windows 11 RTX 2060 NVML cumulative mJ reported_j` are kept strictly separated and never summed.

## 1. Bare-Metal Windows 11 Testbed (`NT 10.0.26300`)

- **CPU**: `11th Gen Intel(R) Core(TM) i7-1165G7 @ 2.80GHz` (`4` cores / `8` threads, `63.7 GiB` RAM)
- **GPUs**: `NVIDIA GeForce RTX 2060` (`WDDM` driver `32.0.15.9174` / `591.74`) + `Intel(R) Iris(R) Xe Graphics` (`31.0.101.3222`) + `Microsoft Basic Render Driver` (`DirectX 12 WARP`)
- **OS & Math Runtime**: `Microsoft Windows 11 Pro` (`Windows NT 10.0.26300`), `Windows Universal C Runtime` (`ucrtbase.dll 10.0.26100.9711`)
- **Compilers & Runtimes**: `rustc 1.100.0 (x86_64-pc-windows-msvc)`, `MSVC cl.exe 19.44.35207`, `Node.js v26.13.0`, `Python 3.10.11`

## 2. Deliverable A (`game-engines`): 3-OS (`macOS` + `Linux` + `Windows 11`) × 3-ISA × 3-API (`Metal` + `Vulkan` + `DirectX 12`)

1. **`GE-H1` (`100,000` ticks, `Q32.32` 64-bit integer physics, `30` cells across `6` hosts)**:
   - **`0 / 25,500` verified `SHA-256` checkpoint mismatches** (`0 / 300,000` pairwise stride-`100` comparisons across the `25` full-trace cells; `H(100) = 2683c3f7cb8b...`, `H(100,000) = 82e404df6475d64d...`).
   - Windows 11 `x86_64` cells (`1,000 / 1,000` stride-`100` checkpoints each):
     - `rust_native` (`rustc 1.100 -O`, `x86_64-pc-windows-msvc`): `49.730 ± 1.727 ms` (`497.3 ns/tick`, `138.86M` CPU cycles)
     - `cpp20_msvc_o2` (`MSVC cl.exe 19.44 /O2 /fp:strict` via `<__msvc_int128.hpp>` `std::_Signed128`): `343.363 ± 3.827 ms` (`3,433.6 ns/tick`, `958.93M` CPU cycles — `6.90×` slower than `rustc` LLVM `i128`, `100%` bit-identical)
     - `rust_wasm32_node` (`Node v26.13.0`): `198.011 ± 4.337 ms` (`1,980.1 ns/tick`, `553.79M` cycles)
     - `javascript_bigint_node` (`ES2024 BigInt`): `1,776.957 ± 77.561 ms` (`17,769.6 ns/tick`, `5,043.67M` cycles)
     - `python3_int` (`CPython 3.10.11`): `8,899.233 ± 2,794.284 ms` (`88,992.3 ns/tick`, `24,722.17M` cycles)

2. **`GE-H2` (`25,000` ticks, 3-OS & Cross-ISA `IEEE 754` `f64` / `f32` drift)**:
   - **Strict algebraic `+`, `-`, `*`, `/`, `sqrt` (`f64_strict` & `f32_strict` with `/fp:strict` and `-ffp-contract=off`)**: `0` mismatches (`> 25,000` ticks) across `Windows 11`, `macOS`, and `Linux`.
   - **3-OS `libm` Transcendental Triangle (`no fast-math`)**:
     - `Windows 11 UCRT` vs `Linux x86_64 GNU glibc 2.43` (same `x86_64` ISA): `t_div_ieee_bits = 10`, `t_div_macro_1e3 = 7,899`, `t_div_gameplay = 10,392` (`173.2 s`).
     - `Windows 11 UCRT` vs `Apple arm64 libSystem`: `t_div_ieee_bits = 37`, `t_div_macro_1e3 = 5,900`, `t_div_gameplay = 9,798` (`163.3 s`).
     - `Apple arm64 libSystem` vs `Linux GNU glibc`: `t_div_ieee_bits = 10`, `t_div_macro_1e3 = 5,900`, `t_div_gameplay = 9,798` (`163.3 s`).
   - **Compiler & Cross-ISA `FMA` Contraction**:
     - `Windows 11 MSVC` (`/O2 /arch:AVX2 /fp:precise` default) vs `Linux x86_64 Clang 21` (`-O3 -mavx2 -mfma -ffp-contract=fast` default): `t_div_ieee_bits = 192`, `t_div_macro_1e3 = 5,927`, `t_div_gameplay = 8,869`.
     - `x86_64` (`-mavx2 -mfma`) vs `arm64`/`aarch64` (`fmadd`): `t_div_ieee_bits = 406`, `t_div_macro_1e3 = 7,422`, `t_div_gameplay = 11,205`.

3. **`GE-H3` (`512×512` `RGBA8Unorm`, `8` hardware `GPU × API` endpoints across `DirectX 12`, `Metal`, and `Vulkan` + `WARP` + `llvmpipe` + `CPU Q16.16`)**:
   - **`28 / 28` hardware `GPU × API` pairs (`112 / 112` frames) pass the `GE-H3` tolerance gate** (`PSNR >= 64.16 dB`, `SSIM >= 0.999833`, `Δ_max <= 2 / 255`, `0` outliers `> 8`).
   - **Same-GPU `DirectX 12` (`HLSL`/`DXIL`) vs `Vulkan` (`SPIR-V`) on Windows 11**:
     - `NVIDIA GeForce RTX 2060 (Win11 DirectX 12)` vs `NVIDIA GeForce RTX 2060 (Win11 Vulkan)`: `0.0002%` mean diff (`0` px at `t = 0, 250`; `1` px by `1` LSB at `t = 1000, 10000`), `min_PSNR = 108.34 dB`, `min_SSIM = 1.000000`.
     - `Intel Iris Xe Graphics (Win11 DirectX 12)` vs `Intel Iris Xe Graphics (Win11 Vulkan)`: `0.2832%` mean diff (`729–758` px/frame, `Δ_max = 1`), `min_PSNR = 79.52 dB`, `min_SSIM = 0.999996`.
     - `NVIDIA GeForce RTX 2060 (Win11 DirectX 12)` vs `NVIDIA GeForce RTX 4050 (Linux Vulkan)`: `0.0000%` diff (`4 / 4` frames bit-for-bit identical!).
     - `CPU Q16.16` integer software reference: `0` mismatches across all `4` hosts (`macOS arm64`, `Linux AMD x86_64`, `Linux Intel x86_64`, `Windows 11 x86_64`).

## 3. Deliverable B (`satb-harness`): Bare-Metal Windows 11 (`5th` Hardware Archetype)

- **`Shape D` `DNULLMM1` (`1,000,000` records via Win32 `MapViewOfFile` & Python `mmap`)**: `10,000`-probe checksum **`15027705736`** (`1,474.22 ns` `MSVC /O2`, `2,885.63 ns` Python `mmap`) + `test.setpoint` digest `0da4df8d9ccbce1e49b8863490e6ef44b4f803bdb31414e4e19b881e04485781` (`passed = true`).
- **`SATB C9` (`14` turns on `NTFS`)**: `149,747` bytes, `SHA-256 = d697ed147612993952aec0b695cebfc3177534584d742d92d4a17e87831460dc`, **`0` `NTFS` `CRLF` drift bytes** (`passed = true`).
- **`SATB C10` (`4`-PID process-tree kill, `5` trials)**: Win32 `TerminateJobObject` reaped in **`2.458 ms` mean** (`2.383–2.617 ms`, `0` surviving PIDs), **`50.0×` faster** than `taskkill.exe /F /T /PID` (`122.817 ms` mean, `0` surviving PIDs).
- **Rootless Basic User (`0x20000`) Telemetry & Falsifier Audit**:
  - Verified under `runas.exe /trustlevel:0x20000` (`IsUserAnAdmin() == false`): `nvml.dll` `nvmlDeviceGetTotalEnergyConsumption` (`mJ`) succeeds rootlessly (`1,174.15 µs` median FFI read vs `43.88 ms` `nvidia-smi` subprocess; `64.64 Hz` at `100 Hz` NT sleep ceiling, `9.45 Hz` at `100 ms` `SATB` reference tick).
  - Unprivileged Intel `RAPL` `MSR 0x611` is blocked in Windows `NT` user mode without a ring-0 kernel driver (barred by `OQ-5` & `HVCI`), and `WMI` `EMI` exposes `0` `PowerMeter` instances (`CPU` package `L2 = "not_available"`, label `N`).
  - `Step 7` sum check on `NVML` cumulative energy passed with **`0 mJ` residual** (`8.769 J + 8.816 J = 17.585 J`, `3.0%` pre/post drift), while Windows `GetProcessTimes` (`15.625 ms` tick aliasing) triggered `Falsifier 3` at **`-89.88%`** Phase-2 error (`-77.05%` using `QueryProcessCycleTime` `RDTSC` cycles).
