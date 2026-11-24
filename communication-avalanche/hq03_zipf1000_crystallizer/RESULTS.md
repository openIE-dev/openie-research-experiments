# CTA-E7 (`HQ03` Closure): Live `1,000`-Task `Zipf(0.85)` Automated `Tier 3 -> Tier 2 -> Tier 1` (`DNULLMM1` `POSIX mmap`) Skill Crystallizer & `Loop 5` `CTA-T45` Auto-Eviction

- **Experiment ID**: `CTA-E7` (Forecast Milestone `HQ03`)
- **Pre-Registration Digest**: `PREREG_cta_e7_hq03.json` (`SHA-256: f5a1af2b5479aa207eb86d78d6a894c0b96c154427b0e6537fe94aa71f1e5b1c`)
- **`FormEBM-v3` Checkpoint (`seed = 20261123`)**: `SHA-256: 3b50620883ab89b5bc29c622fc801cdb0c073b3588fec07016fa681cd47bfd25`
- **Final Cross-Architecture `DNULLMM1` Store Digest (`34` deterministic snapshots)**: `SHA-256: 91a96847d29a023deae4affb663c89153ea680aea075eec823d57743b175fd86` (byte-identical across `x86_64` Linux Zen 5 and `aarch64` `NVIDIA Jetson AGX Thor`).
- **Workload (`seed = 20261123`)**: `N = 1,000` sequential alpha-renamed, parameter-permuted arrivals across `30` structural classes (`24` recurring `Zipf(s = 0.85)` classes spanning `RCE` `Forms`, confounded causal `do(X=x)` DAGs, `5`-variable `FD-SAT` systems, and stateful Python kernels + `6` injected mid-stream distribution-shift transient classes `SHIFT_01..06` at `t = 400..415`).

## Hardware Substrates & Falsifier 6 Audit

| Host Target | Evidence Class | `board_metered` | Primary Rail | Pre/Post `5.0 s` Idle Note | Net Idle Subtraction Policy |
| :--- | :--- | :---: | :--- | :--- | :--- |
| **`NVIDIA Jetson AGX Thor` (`ARMv9` Tegra Linux, CPU-Only)** | `measured_j` | **`true`** | `l2_vdd_cpu_soc_mss_measured_j` (`l1_vin_ina238_measured_j`) | `6.2402 W` -> `6.4261 W` (**`2.98%` `<= 10.0%`**) | Shared-host GPU co-tenant lock respected (`CUDA_VISIBLE_DEVICES=""`); A2 net subtraction withheld per Falsifier 6 |
| **Linux x86-64 (`AMD Ryzen AI Max+ 395`, `32t` Zen 5)** | `reported_j` | `false` | `pkg_reported_j` (`core_reported_j`) | Post-idle `12.1472 W` (`60.74 J`); pre-idle triggered `65,532.61 J` `max_energy_range_uj` sampler-start tick inversion (`56.50 J` / `11.30 W` unwrapped) | Falsifier 6 guard automatically set `withhold_a2_net_idle_subtraction = true`; gross unwrapped stream `reported_j` reported |

## Dual-Host `1,000`-Arrival End-to-End Stream Results (`Loops 1–5`)

| Stream Arm (`1,000` Arrivals) | Verified Solves (`Parity`) | False Commits | Tier Breakdown (`T1` / `T2` / `T3`) | Post-Warmup (`900`) `<= 16 mJ` | Linux Zen 5 `pkg_reported_j` (`core_reported_j`) | Linux `CpJ` (`Gain`) | `Jetson Thor` `VDD_CPU_SOC_MSS` **`measured_j`** (`VIN` **`measured_j`**) | `Thor` `CpJ` (`Gain`) |
| :--- | :---: | :---: | :---: | :---: | ---: | ---: | ---: | ---: |
| **Non-Crystallizing `Tier 3` Baseline** | `1,000 / 1,000` | `0` | `0` / `0` / `1,000` | `0.00%` | `801.32 J` (`39.41 J`) | `1.2479` (`1.00x`) | `533.80 J` (`1,087.96 J`) | `1.8734` (`1.00x`) |
| **Live `Loops 1–5` Crystallizer** | **`1,000 / 1,000` (`100.0%`)** | **`0`** | **`884` / `86` / `30`** (`33.33x` fewer `T3`) | **`99.33%`** (Zen 5) / **`99.11%`** (`Thor`) | **`25.32 J`** (`1.49 J`) | **`39.4950` (`31.65x`)** | **`20.56 J`** (`40.37 J`) | **`48.6335` (`25.96x` `VDD` / `26.95x` `VIN`)** |

### Per-Tier Mean Energy & Loop Latencies

- **Linux Zen 5 (`reported_j`)**: `Tier 1 DNULLMM1` (`POSIX mmap` + `DE10` `BLAKE3+Ed25519` + `0.492 µs` `SSP` route) = **`2.2010 mJ`**, `Tier 2` rule = **`6.0313 mJ`**, `Tier 3` synthesis + `C2+C10` gate = **`0.7618 J`** (`30` `eventfd` wakes in `0.512 s` total stream wall time vs `15.432 s` baseline = **`30.12x` speedup**).
- **`NVIDIA Jetson AGX Thor` (`measured_j`)**: `Tier 1 DNULLMM1` (`POSIX mmap` + `DE10` `BLAKE3+Ed25519` + `1.369 µs` `SSP` route) = **`4.4073 mJ`** `VDD_CPU_SOC_MSS`, `Tier 2` rule = **`7.4150 mJ`**, `Tier 3` synthesis + `C2+C10` gate = **`0.5343 J`** (`1.266 s` total stream wall time vs `30.219 s` baseline = **`23.87x` speedup**).

## `Loop 5` Theorem `CTA-T45` (`h <= h_min`) Auto-Eviction & Payback Audit

- **Injected Distribution-Shift Transients (`6 / 6 = 100%` Evicted)**:
  - `SHIFT_01..04_TRANSIENT` (`1` arrival at `t = 400..403`): promoted to `Tier 2`, observed `H = 0` (`h = 0.000 <= h_min`) at `t = 600..603`, and strictly evicted from `Tier 2`.
  - `SHIFT_05..06_TRANSIENT` (`5` burst arrivals at `t = 404..415`): promoted to `Tier 1 DNULLMM1` at `t = 410..411`, observed `H = 1` (`h = 0.005 <= h_{min,2->1}`) at `t = 610..611` -> demoted from `Tier 1 DNULLMM1` to `Tier 2` (rebuilding and re-hashing `tier1_dnull.mmap`), then observed `H = 0` (`h = 0.000 <= h_{min,3->2}`) at `t = 810..811` -> strictly evicted from `Tier 2`.
- **Recurring `Zipf(0.85)` Classes (`24 / 24 = 100%` Retained & Amortized Before `N = 1,000`, `0` Evicted)**:
  - `23 / 24` finish resident in `Tier 1 DNULLMM1` (`RCE_01_QUORUM_GATE` alone saves `167.11 J` `reported_j` / `116.58 J` `measured_j` vs `0.041 J` compile cost = **`> 2,840x` payback**); the sparsest tail class (`PYALGO_01_RUNLEN_CHUNK`, `10` total arrivals) step-demotes gracefully from `Tier 1` to `Tier 2` (`6.84 J` / `4.77 J` saved vs `0.047 J` compile cost = **`> 101x` payback**).

**Milestone `HQ03` Verdict**: **`Verified [T/E]` (`all_kill_criteria_passed = true` on both hosts)**.
