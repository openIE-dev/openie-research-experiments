# Kit 5 (`waios-mosaic-cascade`) — Cross-ISA `waiOS` Conformance & Multi-Substrate 4-Stage Cascade (`measured_j`, `reported_j`, `est_j`)

- **Provenance Tier:** `Signed Provenance · Self-Checked` (`Apache-2.0`; offline-verifiable `BLAKE3` + `Ed25519` receipts in [`results/`](./results/))
- **Cross-ISA `waiOS` `256×128` Reference Digest Agreement:** Bit-exact `BLAKE3 == a541323b13653ed36515ff24ef08deb7dfa771e570a434712708fb72552f46f0` confirmed across **all 5 execution lanes** (`python_scalar_i32`, `c_scalar_i32`, `c_packed_2bit_bitsliced`, `c_tmac_pair_lut`, `c_hetero_mosaic_4worker_pthreads`) on **all 4 silicon substrates** (`ARMv9` Jetson AGX Thor, `ARMv8 Cortex-A53` AMD Kria KV260, `x86_64` Intel Core i9-13900H, `x86_64` AMD Ryzen AI Max+ 395; `0 / 400` pooled HeteroMosaic schedule disagreements, one-sided 95% Clopper–Pearson upper bound `<= 0.00746`).
- **Single-Weight Tamper Halt (`w[77,0]: 0 -> 1`):** Reproduced `4ac7c4fbc2f2a031ac4f3c0e485867fb689d24d4872bdb1b0a6bc80cf88b69dc` -> **HALTED · Receipt Refused** on every architecture.
- **Canonical `1,000`-Query Stage Routing:** Stage 1 `O(1)` LUT = **`550` (`55.0%`)**, Stage 2 Trigram + Edit Gate = **`250` (`25.0%`)**, Stage 3 `waiOS` Integer Mosaic = **`174` (`17.4%`)**, Stage 4 Escalation Gate = **`26` (`2.6%`)**.

---

## Table A — Physical DC Board-Rail Metering (`evidence_class = measured_j`)

| Board | Primary Rail | Pipeline (`1,000` Queries, `100%` Correct) | Wall `µs / correct` (`IQR`) | Gross Rail `measured_j` `µJ / correct` (`IQR`) | Net-Above-Idle `measured_j` `µJ / correct` | Carrier `VIN` `measured_j` `µJ / correct` | Shunt Samples / Trial |
|---|---|---|---:|---:|---:|---:|---:|
| `Jetson AGX Thor` | `INA3221 VDD_CPU_SOC_MSS` | `spellcheck_4stage_cascade` | `24.524` (`24.509–25.29`) | **`530.39`** (`463.69–591.5`) | `4.38` (paired; F6 drift `5.76%`) | `981.55` | `164` |
| `Jetson AGX Thor` | `INA3221 VDD_CPU_SOC_MSS` | `always_stage3_mosaic_plus_gate` | `77.679` (`77.661–77.716`) | **`1579.24`** (`1508.16–1641.0`) | `0.0` (paired; F6 drift `5.76%`) | `3016.01` | `177` |
| `Jetson AGX Thor` | `INA3221 VDD_CPU_SOC_MSS` | `always_dense_teacher_baseline` | `409.941` (`409.776–410.078`) | **`8622.51`** (`8022.11–9295.5`) | `105.83` (paired; F6 drift `5.76%`) | `16479.77` | `168` |
| `AMD Kria KV260` | `INA260 SOM_5V_DC` | `spellcheck_4stage_cascade` | `196.99` (`196.946–197.005`) | **`685.43`** (`685.12–686.76`) | `40.49` (A1/A2) | `n/a` | `183` |
| `AMD Kria KV260` | `INA260 SOM_5V_DC` | `always_stage3_mosaic_plus_gate` | `417.117` (`417.051–417.258`) | **`1456.18`** (`1455.53–1457.48`) | `90.47` (A1/A2) | `n/a` | `194` |
| `AMD Kria KV260` | `INA260 SOM_5V_DC` | `always_dense_teacher_baseline` | `5262.908` (`5262.153–5263.235`) | **`18221.99`** (`18214.52–18230.09`) | `991.71` (A1/A2) | `n/a` | `1212` |

- **Same-Rail `measured_j` Gains (`Jetson AGX Thor` `VDD_CPU_SOC_MSS`):** `spellcheck_4stage_cascade` reduces physical `measured_j` per correct completion by **`16.26x` vs. Always-Dense** and **`2.98x` vs. Always-Mosaic**.
- **Same-Rail `measured_j` Gains (`AMD Kria KV260` `SOM_5V_DC`):** `spellcheck_4stage_cascade` reduces physical `measured_j` per correct completion by **`26.58x` vs. Always-Dense** and **`2.12x` vs. Always-Mosaic**.

---

## Table B — On-Chip Hardware Energy Counters (`evidence_class = reported_j`)

| Host CPU (`x86_64`) | Pipeline (`1,000` Queries, `100%` Correct) | Wall `µs / correct` (`IQR`) | Package `reported_j` `µJ / correct` (`IQR`) | Core `reported_j` `µJ / correct` |
|---|---|---:|---:|---:|
| `Intel Core i9-13900H` | `spellcheck_4stage_cascade` | `10.672` (`10.533–10.791`) | **`267.45`** (`250.03–290.7`) | `209.21` |
| `Intel Core i9-13900H` | `always_stage3_mosaic_plus_gate` | `32.07` (`31.783–32.289`) | **`759.77`** (`686.33–891.56`) | `570.66` |
| `Intel Core i9-13900H` | `always_dense_teacher_baseline` | `182.355` (`181.4–185.59`) | **`4902.29`** (`4513.06–6584.36`) | `3889.88` |
| `AMD Ryzen AI Max+ 395` | `spellcheck_4stage_cascade` | `10.67` (`10.619–10.796`) | **`793.56`** (`606.97–893.49`) | `29.47` |
| `AMD Ryzen AI Max+ 395` | `always_stage3_mosaic_plus_gate` | `29.753` (`29.47–30.181`) | **`2553.79`** (`2066.15–3009.56`) | `148.47` |
| `AMD Ryzen AI Max+ 395` | `always_dense_teacher_baseline` | `213.508` (`212.889–214.289`) | **`16493.2`** (`14342.0–20794.15`) | `1077.33` |

- **Same-Meter `reported_j` Gains:** **`18.33x` (`i9-13900H`)** and **`20.78x` (`Ryzen AI Max+ 395`)** lower package `reported_j` vs. Always-Dense.

---

## Table C — Isolated Analytical Cloud Escalation Reference (`evidence_class = est_j`)

*(Strictly isolated from Tables A & B; never summed or divided across meter classes.)*

| Scenario (`est_j`) | Remote Frontier Calls | Analytical `est_j` (`@ 1.50 J/call`) | Call Avoidance |
|---|---:|---:|---:|
| Frontier-Only (`100%` remote calls) | `1,000` | `1500.00 est_j` | `1.00x` |
| 4-Stage Cascade (`Stage 4` residual only) | `26` | `39.00 est_j` | **`38.46x`** |

---

## 4. Selected Points from the `75`-Cell `(Zipf s, d_max, margin tau)` Cascade Grid Sweep

*(Full `75`-cell sweep stored in `results/multi_substrate_receipts.json` across `s ∈ {0.0, 0.50, 0.85, 1.15, 1.40}`, `d_max ∈ {0, 1, 2}`, `tau ∈ {1500, 3000, 4500, 6500, 9000}`.)*

| Zipf `s` | `d_max` | `tau` | Accuracy | Stage `1 / 2 / 3 / 4` Fractions | Thor `INA3221` Gross `measured_j` (`µJ/correct`) | KV260 `INA260` Gross `measured_j` (`µJ/correct`) | Ryzen `RAPL` `reported_j` (`µJ/correct`) | Isolated Stage-4 `est_j` |
|---:|---:|---:|---:|---|---:|---:|---:|---:|
| `0.00` | `0` | `4500` | **`98.50%`** | `0.10 / 0.00 / 0.77 / 0.13` | `2700.451` | `3337.661` | `3163.954` | `195.0 est_j` (`130` calls) |
| `0.00` | `2` | `4500` | **`98.50%`** | `0.10 / 0.18 / 0.59 / 0.13` | `1760.138` | `3149.982` | `2526.996` | `195.0 est_j` (`130` calls) |
| `0.50` | `2` | `4500` | **`99.10%`** | `0.28 / 0.21 / 0.41 / 0.10` | `1239.936` | `2478.395` | `1981.695` | `157.5 est_j` (`105` calls) |
| `0.85` | `2` | `4500` | **`99.50%`** | `0.43 / 0.23 / 0.25 / 0.09` | `1366.639` | `1931.433` | `5465.758` | `129.0 est_j` (`86` calls) |
| `1.15` | `0` | `4500` | **`99.70%`** | `0.58 / 0.00 / 0.35 / 0.07` | `928.969` | `1702.125` | `3634.391` | `105.0 est_j` (`70` calls) |
| `1.15` | `1` | `4500` | **`99.70%`** | `0.58 / 0.11 / 0.24 / 0.07` | `893.626` | `1603.771` | `2339.552` | `105.0 est_j` (`70` calls) |
| `1.15` | `2` | `1500` | **`99.70%`** | `0.58 / 0.21 / 0.17 / 0.04` | `503.366` | `856.016` | `1355.822` | `52.5 est_j` (`35` calls) |
| `1.15` | `2` | `4500` | **`99.70%`** | `0.58 / 0.21 / 0.13 / 0.07` | `749.216` | `1498.9` | `2130.177` | `105.0 est_j` (`70` calls) |
| `1.15` | `2` | `9000` | **`99.70%`** | `0.58 / 0.21 / 0.13 / 0.07` | `762.025` | `1501.485` | `1825.869` | `105.0 est_j` (`70` calls) |
| `1.40` | `2` | `4500` | **`99.90%`** | `0.72 / 0.20 / 0.03 / 0.06` | `480.321` | `1098.204` | `1642.977` | `82.5 est_j` (`55` calls) |
