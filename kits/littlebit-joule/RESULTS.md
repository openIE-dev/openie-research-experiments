# Kit 4 (`littlebit-joule`) — Multi-Substrate Hardware-Metered Results (`measured_j` & `reported_j`)

- **Provenance Tier:** `Signed Provenance · Self-Checked` (`Apache-2.0`; offline-verifiable `BLAKE3` + `Ed25519` receipts in [`results/`](./results/))
- **Energy Orthogonality (`measured_j ⊥ reported_j ⊥ est_j ⊥ unmetered`):** Physical DC shunt rails (`measured_j`) and on-chip RAPL counters (`reported_j`) are presented in strictly separate tables and never summed or cross-ratioed.
- **Matrix & Factorization:** `512 × 512` (`262,144` weights), headline rank `r = 22` -> **`0.1517 bits/weight`** (`4,972` B = **`52.72x` smaller than INT8** / `105.45x` smaller than FP16); Walsh-Hadamard outlier crest reduced `5.8006 -> 4.7457`.

---

## Table A — Physical DC Board-Rail Metering (`evidence_class = measured_j`)

- **NVIDIA Jetson AGX Thor (`aarch64`, 14-core ARMv9):** Rootless sysfs `TI INA3221` (`VDD_CPU_SOC_MSS` primary rail `in* × curr*`) + `TI INA238` (`VIN` carrier rail `power1_input`) sampled continuously at `~203 Hz` (`>= 0.70 s` burst windows, trapezoidal integration); `VDD_GPU = 0.0 W` verified idle.
- **AMD Kria KV260 (`aarch64`, 4× ARM Cortex-A53 Zynq UltraScale+ MPSoC):** Rootless sysfs `TI INA260` (`ina260_u14` SOM 5V DC rail `power1_input`) sampled continuously at `~230 Hz` (`>= 0.70 s` burst windows, user-space PS CPU only; PL untouched).

| Board | Primary Rail | Regime | Bits / Weight | Accuracy (`N=1,200`) | Wall `ns / correct` | Gross Rail `measured_j` `µJ / correct` (`IQR`) | Net-Above-Idle `measured_j` `µJ / correct` | Carrier `VIN` `measured_j` `µJ / correct` | Shunt Samples / Trial |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| `Jetson AGX Thor` | `INA3221 VDD_CPU_SOC_MSS` | `deterministic_null_lut` | `n/a (LUT)` | **`96.33%`** | `49.33` | **`0.9283`** (`0.7839–1.0521`) | `0.0` (paired; F6 drift `39.78%`) | `1.7848` | `98` |
| `Jetson AGX Thor` | `INA3221 VDD_CPU_SOC_MSS` | `dense_int8_baseline` | `8.0000` | **`100.00%`** | `43164.95` | **`829.9391`** (`683.9386–1014.2198`) | `0.0` (paired; F6 drift `39.78%`) | `1507.7177` | `171` |
| `Jetson AGX Thor` | `INA3221 VDD_CPU_SOC_MSS` | `subbit_naive_float_unpack` | `0.1517` | **`100.00%`** | `850610.2` | **`15839.3354`** (`14527.9513–18034.2894`) | `0.0` (paired; F6 drift `39.78%`) | `30585.5717` | `211` |
| `Jetson AGX Thor` | `INA3221 VDD_CPU_SOC_MSS` | `littlebit_joule_packed_int` | `0.1517` | **`100.00%`** | `5845.68` | **`104.443`** (`93.7692–118.2784`) | `0.0` (paired; F6 drift `39.78%`) | `202.9402` | `165` |
| `AMD Kria KV260` | `INA260 SOM_5V_DC` | `deterministic_null_lut` | `n/a (LUT)` | **`96.33%`** | `422.89` | **`1.4927`** (`1.4916–1.4954`) | `0.1079` (A1/A2) | `n/a` | `148` |
| `AMD Kria KV260` | `INA260 SOM_5V_DC` | `dense_int8_baseline` | `8.0000` | **`100.00%`** | `220138.29` | **`773.7394`** (`772.3976–775.0188`) | `53.0285` (A1/A2) | `n/a` | `183` |
| `AMD Kria KV260` | `INA260 SOM_5V_DC` | `subbit_naive_float_unpack` | `0.1517` | **`100.00%`** | `18184589.95` | **`63335.56`** (`63319.6008–63347.366`) | `3813.3249` (A1/A2) | `n/a` | `5034` |
| `AMD Kria KV260` | `INA260 SOM_5V_DC` | `littlebit_joule_packed_int` | `0.1517` | **`100.00%`** | `54022.14` | **`187.4928`** (`187.2562–187.8721`) | `10.2965` (A1/A2) | `n/a` | `180` |

- **Same-Rail `measured_j` Summary (`Jetson AGX Thor` `VDD_CPU_SOC_MSS`):** Naive FP32 unpack incurs a **`19.08x` decompression impedance tax** over INT8, whereas `littlebit_joule_packed_int` achieves **`7.95x` lower `measured_j` than INT8** (`151.66x` lower than naive FP32 unpack).
- **Same-Rail `measured_j` Summary (`AMD Kria KV260` `SOM_5V_DC`):** Naive FP32 unpack incurs a **`81.86x` decompression impedance tax** over INT8, whereas `littlebit_joule_packed_int` achieves **`4.13x` lower `measured_j` than INT8** (`337.8x` lower than naive FP32 unpack).

---

## Table B — On-Chip Hardware Energy Counters (`evidence_class = reported_j`)

| Host CPU (`x86_64`) | Regime | Bits / Weight | Accuracy (`N=1,200`) | Wall `ns / correct` (`IQR`) | Package `reported_j` `µJ / correct` (`IQR`) | Core `reported_j` `µJ / correct` |
|---|---|---:|---:|---:|---:|---:|
| `Intel Core i9-13900H` | `deterministic_null_lut` | `n/a (LUT)` | **`96.33%`** | `38.01` (`35.62–38.97`) | **`1.1175`** (`0.9404–1.356`) | `0.9092` |
| `Intel Core i9-13900H` | `dense_int8_baseline` | `8.0000` | **`100.00%`** | `11713.76` (`11342.14–12925.32`) | **`387.3771`** (`368.9003–483.2077`) | `325.9355` |
| `Intel Core i9-13900H` | `subbit_naive_float_unpack` | `0.1517` | **`100.00%`** | `603508.04` (`582265.03–612330.83`) | **`20192.1677`** (`18594.4319–21136.0501`) | `16715.3026` |
| `Intel Core i9-13900H` | `littlebit_joule_packed_int` | `0.1517` | **`100.00%`** | `2949.02` (`2785.01–3085.12`) | **`81.1941`** (`77.3099–87.4953`) | `65.5361` |
| `AMD Ryzen AI Max+ 395` | `deterministic_null_lut` | `n/a (LUT)` | **`96.33%`** | `52.32` (`47.23–53.65`) | **`7.1541`** (`6.0846–7.5137`) | `0.3998` |
| `AMD Ryzen AI Max+ 395` | `dense_int8_baseline` | `8.0000` | **`100.00%`** | `17917.9` (`12956.12–19226.82`) | **`2438.6416`** (`1405.1009–2682.5579`) | `138.6751` |
| `AMD Ryzen AI Max+ 395` | `subbit_naive_float_unpack` | `0.1517` | **`100.00%`** | `830892.33` (`541690.53–888402.13`) | **`113371.8019`** (`50385.953–125150.393`) | `6619.0825` |
| `AMD Ryzen AI Max+ 395` | `littlebit_joule_packed_int` | `0.1517` | **`100.00%`** | `5405.9` (`4737.36–5804.99`) | **`732.1151`** (`623.9043–811.7247`) | `44.9329` |

- **Same-Meter `reported_j` Summary:** `littlebit_joule_packed_int` delivers **`4.77x` (`i9-13900H`)** and **`3.33x` (`Ryzen AI Max+ 395`)** lower package `reported_j` per correct decision than INT8 (`0 / 80` divergent runs across `20` trials on both hosts; 95% Clopper–Pearson `<= 0.036754`).

---

## 3. Multi-Point `bitwidth_curve` Sweep (`r ∈ {8, 14, 22, 32, 48}` + Ternary + INT4 + INT8 + LUT)

| Curve Point | `bpw` | Footprint | Accuracy | Thor `INA3221` Gross `measured_j` (`µJ/correct`) | KV260 `INA260` Gross `measured_j` (`µJ/correct`) | Ryzen `RAPL` `reported_j` (`µJ/correct`) |
|---|---:|---:|---:|---:|---:|---:|
| `deterministic_null_lut` | `0.0000` | `4,096 B` | **`96.33%`** | `0.682` | `1.4941` | `6.7937` |
| `littlebit_packed_int_r8` | `0.0962` | `3,152 B` | **`100.00%`** | `59.2836` | `128.2735` | `513.2264` |
| `subbit_naive_fp32_unpack_r8` | `0.0962` | `3,152 B` | **`100.00%`** | `5702.3873` | `27338.9858` | `46115.2268` |
| `littlebit_packed_int_r14` | `0.1200` | `3,932 B` | **`100.00%`** | `60.7669` | `157.0567` | `249.7658` |
| `subbit_naive_fp32_unpack_r14` | `0.1200` | `3,932 B` | **`100.00%`** | `7960.2567` | `42913.0317` | `31746.2906` |
| `littlebit_packed_int_r22` | `0.1517` | `4,972 B` | **`100.00%`** | `79.7773` | `187.5389` | `723.9648` |
| `subbit_naive_fp32_unpack_r22` | `0.1517` | `4,972 B` | **`100.00%`** | `13038.9017` | `63368.6183` | `94059.7719` |
| `littlebit_packed_int_r32` | `0.1914` | `6,272 B` | **`100.00%`** | `92.6395` | `229.0365` | `151.093` |
| `subbit_naive_fp32_unpack_r32` | `0.1914` | `6,272 B` | **`100.00%`** | `20378.6821` | `87150.11` | `31585.2577` |
| `littlebit_packed_int_r48` | `0.2549` | `8,352 B` | **`100.00%`** | `244.13` | `293.979` | `184.4793` |
| `subbit_naive_fp32_unpack_r48` | `0.2549` | `8,352 B` | **`100.00%`** | `45628.2521` | `125458.7375` | `44467.5212` |
| `ternary_2bpw` | `2.0000` | `65,540 B` | **`100.00%`** | `2278.1423` | `1278.475` | `1476.326` |
| `int4_4bpw` | `4.0000` | `131,076 B` | **`100.00%`** | `664.3051` | `644.3886` | `1245.5922` |
| `dense_int8_8bpw` | `8.0000` | `262,144 B` | **`100.00%`** | `915.9645` | `774.6568` | `528.7535` |
