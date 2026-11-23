# `game-engines` Full Empirical Bundle (`GE-H1` through `GE-H9` + Bare-Metal Windows 11 `SATB`)

- **Benchmark Root**: `$BENCH_ROOT`
- **Pre-Registrations**:
  - Wave 3/4 (`GE-H1`–`GE-H3`): `PREREG_wave3_multi_isa_wgpu.json` (`SHA-256: 1721e5bdffaf035e6a1d7040048d1f6199030a12215e7c39e1f8b0355c0d99fe`)
  - Wave 5 (`GE-H4`–`GE-H9`): `PREREG_wave5_ge_h4_h9.json` (`SHA-256: 7d02115e37d308873f5e34245091988d662f811e3276735ab9a6786051923dbb`)
- **Compiler & Engine Pins**: `openIE-dev/rce` commit `1762fb4bb65a58de07ab00f0d1bfdf4969d0358c` (spec draft `0.9`), `Godot Engine v4.7.2.stable.official.ed1daf0bf` (`--headless`), `rustc 1.100.0`, `Clang 21`, `MSVC cl.exe 19.44.35207`, `Microsoft Visual C# csc.exe v4.0.30319`, `Node.js v22.22.1 / v26.13.0`, `CPython 3.10–3.15`.
- **Energy Discipline**: `measured_j = None` and `board_metered = false` on `game-engines` and on the Windows 11 host in `satb-harness`. `macOS L3 ri_energy_nj`, `Linux L2 RAPL`, `Jetson Thor INA238/INA3221 measured_j`, and `Windows 11 RTX 2060 NVML cumulative mJ reported_j` are kept strictly separated and never summed.

## 1. Bare-Metal Windows 11 Testbed (`NT 10.0.26300`)

- **CPU**: `11th Gen Intel(R) Core(TM) i7-1165G7 @ 2.80GHz` (`4` cores / `8` threads, `63.7 GiB` RAM)
- **GPUs**: `NVIDIA GeForce RTX 2060` (`WDDM` driver `32.0.15.9174` / `591.74`) + `Intel(R) Iris(R) Xe Graphics` (`31.0.101.3222`) + `Microsoft Basic Render Driver` (`DirectX 12 WARP`)
- **OS & Math Runtime**: `Microsoft Windows 11 Pro` (`Windows NT 10.0.26300`), `Windows Universal C Runtime` (`ucrtbase.dll 10.0.26100.9711`)
- **Compilers & Runtimes**: `rustc 1.100.0 (x86_64-pc-windows-msvc)`, `MSVC cl.exe 19.44.35207`, `csc.exe 4.0.30319`, `Node.js v26.13.0`, `Python 3.10.11`

## 2. Wave 3 & Wave 4 (`GE-H1`–`GE-H3`): 3-OS (`macOS` + `Linux` + `Windows 11`) × 3-ISA × 3-API (`Metal` + `Vulkan` + `DirectX 12`)

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

## 3. Wave 5 (`GE-H4`–`GE-H9`): Full Multi-Engine Behavior, Scaling, Interface, Lyapunov, 1-Hour Replay, & Godot 4 Closure (`ge_h4_h9_results.json`)

4. **`GE-H4` (`17` behavior modules across `Haunted Jaunt` [5], `Survival Shooter` [7], and `Tanks` [5] × `4` languages = `68` implementations, `680` verified trace runs)**:
   - **`0 / 680` cross-language state-transition mismatches** across `openIE-dev/rce` (`1762fb4b`), Windows 11 `csc.exe` (`MonoBehaviour` C#), `Godot 4.7.2 --headless` (`Node` GDScript), and `rustc 1.100` (Bevy-style Rust ECS).
   - **Code & boilerplate reduction (`>= 50%` threshold passed)**:
     - `.rce` Forms require **`326` behavior SLOC** (`377` total SLOC *including* `34` gate-checked `intent` `example` traces, `2,348` behavior tokens, `61` glue lines) vs **`1,371` SLOC** in Unity `MonoBehaviour` C# (`-76.22%` behavior SLOC, `-72.50%` including `intent`, `-66.15%` tokens, `-92.51%` glue lines vs GameRule's `-81.3%` domain-specific Unity verb reference), **`846` SLOC** in Bevy-style Rust ECS (`-61.47%`), **`679` SLOC** in Godot 4 `Node` GDScript (`-51.99%`), and **`2,896` combined SLOC** across all three engine codebases (`-88.74%`).

5. **`GE-H5` (`Q32.32` `16×16` spatial-grid patrol/chase/projectile Form across $N \in \{64, 128, 256, 300, 350, 500, 1{,}000, 2{,}500, 5{,}000, 10{,}000\}$, `500` ticks/cell, `5` tiers on idle `Intel Core i9-13900H` with `SATB L2` `RAPL`)**:
   - **`0 / 50` cross-tier `SHA-256` state-digest mismatches** at tick `500` across all `5` tiers and all `10` actor counts.
   - **Actor ceilings at $T = 20\text{ ms}$ (`N_20ms`) and $N = 10{,}000$ step cost**:
     - `rce_python3` (`rce emit python`): `13.66 ms` (`300`), `18.12 ms` (`350`), `25.25 ms` (`500`) -> **`N_20ms = 390` actors** (`564.57 ms` p50, `13,090.57 mJ/tick` RAPL package at $N = 10{,}000$).
     - `rce_nodejs_v22` (`rce emit js` on Node `v22.22.1`): `1.85 ms` (`350`), `12.60 ms` (`2,500`), `25.75 ms` (`5,000`) -> **`N_20ms = 3,906` actors** (`11.2×` above $N = 350$; `57.05 ms` p50, `1,559.77 mJ/tick` at $N = 10{,}000$).
     - `form_wasm32_v8` (Rust `wasm32-unknown-unknown` on Node V8): **`0.0044 ms`** at $N = 350$, **`0.0724 ms` p50** (`0.0810 ms` p99, **`2.21 mJ/tick`** RAPL package — `5,921×` lower energy/tick than `rce emit python`) at $N = 10{,}000$ (`> 10,000` verified; `~2.76M` linear-extrapolated ceiling).
     - `form_cpp20_o3` (`clang++ -std=c++20 -O3`): **`0.0036 ms`** at $N = 350$, **`0.0583 ms` p50** (`0.0654 ms` p99, **`1.69 mJ/tick`** RAPL package — `7,728×` lower energy/tick) at $N = 10{,}000$ (`~3.43M` linear-extrapolated ceiling).
     - `form_rust_o3` (`rustc -C opt-level=3`): **`0.0041 ms`** at $N = 350$, **`0.1248 ms` p50** (`0.1274 ms` p99, **`3.67 mJ/tick`** RAPL package) at $N = 10{,}000$ (`~1.60M` linear-extrapolated ceiling).

6. **`GE-H6` (`26` game-interface defect patterns × `[5 faulty + 5 valid]` = `260` modules, zero engine runtime ticks)**:
   - **Static Form + 4-Edge Typed Manifest Checker** (`rce check` + `rce test` + static scene/physics/WGSL/wire/save/audio/UI/schedule verifier): **`TP = 128, FP = 0, FN = 2, TN = 130`**, **Detection Rate = `98.46%`** (`>= 90.0%` kill criterion), **Precision = `100.00%`**, **Fault F1 = `0.9922`** (admitted-pool valid precision `0.9848`). The `2` inspectable false negatives (`P10_fault_5` and `P19_fault_5`) isolate bare untagged `i64` scalars lacking dimensional/coordinate newtype wrappers.
   - **Untyped String-Keyed Dynamic Scripting Baseline** (`Godot 4.7.2 --headless --check-only` without Form IR): **`TP = 8, FP = 0, FN = 122, TN = 130`**, **Detection Rate = `6.15%`**, **Fault F1 = `0.1159`** (matching Mage's `0.12` no-IR baseline; `admitted_valid_precision = 0.5159`).

7. **`GE-H7` (`840` paired `IEEE 754` `f64` trajectories across `3` chaotic physics templates × `7` perturbations $\delta_0 \in [2^{-52}, 2^{-10}]$ × `40` seeds at `60 Hz`, $\Delta = 1.0$)**:
   - **`GE-T1` (`16-Body Chaotic Bumper Arena`)**: `0 / 280` right-censored; slope $\hat{\beta} = 0.4025\text{ s/nat}$ (`95%` bootstrap CI `[0.3823, 0.4246]`), $\hat{\Lambda} = 2.4846\text{ s}^{-1}$ (`[2.3554, 2.6157]`), $R^2_{\text{traj}} = 0.8569$, $R^2_{\text{mean}} = 0.99953$, $t_{278} = 40.81$, two-sided $p = 10^{-118.7}$.
   - **`GE-T2` (`12-Peg Galton/Pinball Elastic Lattice`)**: `0 / 280` right-censored; slope $\hat{\beta} = 0.1974\text{ s/nat}$ (`[0.1804, 0.2145]`), $\hat{\Lambda} = 5.0671\text{ s}^{-1}$ (`[4.6611, 5.5436]`), $R^2_{\text{traj}} = 0.7176$, $R^2_{\text{mean}} = 0.99629$, $t_{278} = 26.58$, $p = 10^{-77.6}$.
   - **`GE-T3` (`8-Node Coupled Spring-Pendulum Bridge`)**: `0 / 280` right-censored; slope $\hat{\beta} = 0.5121\text{ s/nat}$ (`[0.4802, 0.5440]`), $\hat{\Lambda} = 1.9528\text{ s}^{-1}$ (`[1.8382, 2.0823]`), $R^2_{\text{traj}} = 0.8169$, $R^2_{\text{mean}} = 0.99395$, $t_{278} = 35.21$, $p = 10^{-103.7}$.

8. **`GE-H8` (`3` one-hour `216,000`-tick `60 Hz` sessions replayed from compact input log $D$ alone across `macOS arm64`, `Linux x86_64`, and `Windows 11 x86_64`)**:
   - **`0 / 6,480` checkpoint `SHA-256` mismatches** (`2,160` stride-`100` checkpoints × `3` sessions) and **`0 / 3` final 1-hour `SHA-256` mismatches** across `Apple M5 Max` (`macOS 27.2.1 arm64`, `2.79–8.32 ms`), `Intel Core i9-13900H` (`Linux 7.0 x86_64`), and `Intel Core i7-1165G7` (`Windows 11 26300 x86_64`, `4.94–11.02 ms`).
   - **Compact log $|D|$ vs state-snapshot stream**: each 1-hour log $D$ is `432,024` bytes raw (**`44.58–44.60 KB` gzip**), whereas full state-snapshot streams occupy `36.50–78.84 MB` raw (`5.19–13.03 MB` gzip) — a **`116.3×` to `292.3×` compressed storage reduction** (`84.5×`–`182.5×` raw).
   - **Positive falsifier control (`4` ambient leaks)**: injecting wall-clock nanoseconds (`L1`), stack-address RNG (`L2`), randomized `HashMap` iteration (`L3`), or host `f64::sin` (`L4`) breaks replay from $D$ at **`t_div = 1`**, with `L4_host_libm_sin_f64` producing three mutually distinct 1-hour `SHA-256` digests across `macOS` (`0d1722cf...`), `Linux` (`50f9ff25...`), and `Windows 11` (`54d0f774...`).

9. **`GE-H9` (`form_to_gdscript.py` + `36`-task deterministic Form-to-Godot 4.7.2 `--headless` parity suite + `GameCraft-Bench` archive audit)**:
   - **Public `GameCraft-Bench` archive audit**: verified that `FreedomIntelligence/gamecraft-bench` publicly releases `140` natural-language task directories across `15` 2D game families, whose official `gamecraft_bench.verifier` scores open-ended agent projects via `Xvfb` + `xdotool` + `ffmpeg` video capture and an external multimodal VLM judge (`GAMECRAFT_BENCH_JUDGE`, `148.5M–2.24B` LLM tokens).
   - **36-task deterministic Godot 4.7.2 parity suite**: across `36` gameplay tasks (`2` per `GameCraft-Bench` family = `30` + `6` reference/multiplayer systems) stepped for `500` events each under `Godot Engine v4.7.2.stable.official.ed1daf0bf --headless`, `form_to_gdscript.py` achieved **`36 / 36` (`100.0%`) pass parity** and **`0 / 18,000` per-tick `SHA-256` state-hash mismatches** against hand-written idiomatic native GDScript.

## 4. Companion `satb-harness`: Bare-Metal Windows 11 (`5th` Hardware Archetype)

- **`Shape D` `DNULLMM1` (`1,000,000` records via Win32 `MapViewOfFile` & Python `mmap`)**: `10,000`-probe checksum **`15027705736`** (`1,474.22 ns` `MSVC /O2`, `2,885.63 ns` Python `mmap`) + `test.setpoint` digest `0da4df8d9ccbce1e49b8863490e6ef44b4f803bdb31414e4e19b881e04485781` (`passed = true`).
- **`SATB C9` (`14` turns on `NTFS`)**: `149,747` bytes, `SHA-256 = d697ed147612993952aec0b695cebfc3177534584d742d92d4a17e87831460dc`, **`0` `NTFS` `CRLF` drift bytes** (`passed = true`).
- **`SATB C10` (`4`-PID process-tree kill, `5` trials)**: Win32 `TerminateJobObject` reaped in **`2.458 ms` mean** (`2.383–2.617 ms`, `0` surviving PIDs), **`50.0×` faster** than `taskkill.exe /F /T /PID` (`122.817 ms` mean, `0` surviving PIDs).
