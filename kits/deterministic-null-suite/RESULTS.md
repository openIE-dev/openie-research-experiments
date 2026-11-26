# Kit 1 (`deterministic-null-suite`) — Multi-Substrate 5-Arm Classical Control Results (`measured_j` & `reported_j`)

- **Provenance Tier:** `Signed Provenance · Self-Checked` (`Apache-2.0`; offline-verifiable `BLAKE3` + `Ed25519` receipts in [`results/`](./results/))
- **Held-Out Task Suite (`N = 1,500` total, `500` per stratum, `LUT cap = 4,096 B` per stratum):**
  1. **Stratum A (`bounded_api_dispatch`, `500` instances):** Structured schema, auth, quota, idempotency & SLO routing (`8` classes).
  2. **Stratum B (`combinatorial_constraint_3sat`, `500` instances):** 16-variable, 48-clause `3-SAT` feasibility + witness verification (`2` classes).
  3. **Stratum C (`open_compositional_patch_triage`, `500` instances):** 32-feature AST/log defect localization with an unseen oblique multi-feature tail (`8` classes).
- **Determinism:** `0 / 252` pooled arm runs diverged across `Thor` (`0/56`), `KV260` (`0/56`), and `Ryzen AI Max+ 395` (`0/140`); one-sided 95% Clopper–Pearson upper bound `<= 0.01182`.

---

## Table A — Physical DC Board-Rail Metering (`evidence_class = measured_j`)

- **AMD Kria KV260 (`TI INA260` `SOM_5V_DC`, `~233 Hz`):** Idle `A1/A2` trimmed `3.2651 W` (`0.03%` drift; `Falsifier 6 flag = False`).
- **NVIDIA Jetson AGX Thor (`TI INA3221` `VDD_CPU_SOC_MSS` + `TI INA238` `VIN`, `~203 Hz`):** Idle `A1/A2` trimmed `6.9709 W` (`1.68%` drift; `Falsifier 6 flag = False`).

| Board | Primary Rail | Arm | API (`500`) | 3-SAT (`500`) | Triage (`500`) | Overall (`1,500`) | Wall `ns / correct` | Gross Rail `measured_j` `µJ / correct` (`IQR`) | Net-Above-Idle `measured_j` `µJ / correct` | Carrier `VIN` `measured_j` `µJ / correct` |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `AMD Kria KV260` | `INA260 SOM_5V_DC` | `arm1_lookup_table` | `77.4%` | `64.0%` | `38.8%` | **`60.07%`** | `433.3` | **`1.4987`** (`1.4976–1.499`) | `0.0835` (A1/A2) | `n/a` |
| `AMD Kria KV260` | `INA260 SOM_5V_DC` | `arm2_if_else_guards` | `100.0%` | `55.6%` | `27.8%` | **`61.13%`** | `57.81` | **`0.2016`** (`0.2016–0.2017`) | `0.0129` (A1/A2) | `n/a` |
| `AMD Kria KV260` | `INA260 SOM_5V_DC` | `arm3_bounded_for_loop` | `100.0%` | `71.6%` | `49.6%` | **`73.73%`** | `11859.38` | **`40.813`** (`40.7696–40.871`) | `2.0848` (A1/A2) | `n/a` |
| `AMD Kria KV260` | `INA260 SOM_5V_DC` | `arm4_decision_tree` | `91.8%` | `82.4%` | `43.4%` | **`72.53%`** | `105.93` | **`0.3663`** (`0.3662–0.3664`) | `0.0203` (A1/A2) | `n/a` |
| `AMD Kria KV260` | `INA260 SOM_5V_DC` | `arm5_compiled_solver_rules` | `100.0%` | `100.0%` | `57.4%` | **`85.80%`** | `12770.05` | **`43.9344`** (`43.8924–43.9879`) | `2.2296` (A1/A2) | `n/a` |
| `AMD Kria KV260` | `INA260 SOM_5V_DC` | `shape_d_classical_best` | `100.0%` | `100.0%` | `57.4%` | **`85.80%`** | `8227.04` | **`28.2799`** (`28.2696–28.3046`) | `1.4124` (A1/A2) | `n/a` |
| `AMD Kria KV260` | `INA260 SOM_5V_DC` | `candidate_dense_mlp_int16` | `38.4%` | `79.2%` | `70.2%` | **`62.60%`** | `150278.14` | **`518.8062`** (`518.3293–519.2651`) | `28.082` (A1/A2) | `n/a` |
| `Jetson AGX Thor` | `INA3221 VDD_CPU_SOC_MSS` | `arm1_lookup_table` | `77.4%` | `64.0%` | `38.8%` | **`60.07%`** | `104.39` | **`0.8252`** (`0.8043–0.8439`) | `0.077` (A1/A2) | `2.2428` |
| `Jetson AGX Thor` | `INA3221 VDD_CPU_SOC_MSS` | `arm2_if_else_guards` | `100.0%` | `55.6%` | `27.8%` | **`61.13%`** | `4.69` | **`0.0373`** (`0.036–0.0374`) | `0.0042` (A1/A2) | `0.1038` |
| `Jetson AGX Thor` | `INA3221 VDD_CPU_SOC_MSS` | `arm3_bounded_for_loop` | `100.0%` | `71.6%` | `49.6%` | **`73.73%`** | `1916.2` | **`15.2013`** (`15.1464–15.456`) | `1.8048` (A1/A2) | `42.0668` |
| `Jetson AGX Thor` | `INA3221 VDD_CPU_SOC_MSS` | `arm4_decision_tree` | `91.8%` | `82.4%` | `43.4%` | **`72.53%`** | `21.93` | **`0.1749`** (`0.1739–0.1774`) | `0.0216` (A1/A2) | `0.4729` |
| `Jetson AGX Thor` | `INA3221 VDD_CPU_SOC_MSS` | `arm5_compiled_solver_rules` | `100.0%` | `100.0%` | `57.4%` | **`85.80%`** | `2480.68` | **`19.6862`** (`19.6121–20.0675`) | `2.3765` (A1/A2) | `54.3044` |
| `Jetson AGX Thor` | `INA3221 VDD_CPU_SOC_MSS` | `shape_d_classical_best` | `100.0%` | `100.0%` | `57.4%` | **`85.80%`** | `1610.24` | **`13.3439`** (`13.2682–13.4872`) | `2.088` (A1/A2) | `35.3631` |
| `Jetson AGX Thor` | `INA3221 VDD_CPU_SOC_MSS` | `candidate_dense_mlp_int16` | `38.4%` | `79.2%` | `70.2%` | **`62.60%`** | `18686.54` | **`148.5732`** (`147.9811–149.9577`) | `17.8356` (A1/A2) | `401.9959` |

- **Physical `measured_j` Ratios (`AMD Kria KV260` `SOM_5V_DC`):** `candidate_dense_mlp_int16` burns **`18.35x` MORE `measured_j` per correct operation than `shape_d_classical_best`** (`346.17x` more than `arm1_lookup_table`).
- **Physical `measured_j` Ratios (`Jetson AGX Thor` `VDD_CPU_SOC_MSS`):** `candidate_dense_mlp_int16` burns **`11.13x` MORE `measured_j` per correct operation than `shape_d_classical_best`** (`180.05x` more than `arm1_lookup_table`).

---

## Table B — On-Chip Hardware Energy Counters (`evidence_class = reported_j`)

| Host CPU (`x86_64`) | Arm | API (`500`) | 3-SAT (`500`) | Triage (`500`) | Overall (`1,500`) | Wall `ns / correct` (`IQR`) | Package `reported_j` `µJ / correct` (`IQR`) | Core `reported_j` `µJ / correct` |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `AMD Ryzen AI Max+ 395` | `arm1_lookup_table` | `77.4%` | `64.0%` | `38.8%` | **`60.07%`** | `72.75` (`72.2–73.09`) | **`6.8188`** (`6.4254–7.3283`) | `0.4847` |
| `AMD Ryzen AI Max+ 395` | `arm2_if_else_guards` | `100.0%` | `55.6%` | `27.8%` | **`61.13%`** | `2.18` (`2.17–2.2`) | **`0.2044`** (`0.1881–0.2237`) | `0.0153` |
| `AMD Ryzen AI Max+ 395` | `arm3_bounded_for_loop` | `100.0%` | `71.6%` | `49.6%` | **`73.73%`** | `1425.85` (`1411.41–1433.99`) | **`140.4637`** (`132.5044–151.4562`) | `10.3889` |
| `AMD Ryzen AI Max+ 395` | `arm4_decision_tree` | `91.8%` | `82.4%` | `43.4%` | **`72.53%`** | `8.08` (`8.03–8.12`) | **`0.723`** (`0.6351–0.8909`) | `0.0605` |
| `AMD Ryzen AI Max+ 395` | `arm5_compiled_solver_rules` | `100.0%` | `100.0%` | `57.4%` | **`85.80%`** | `2180.6` (`2173.14–2189.53`) | **`212.7944`** (`201.6476–223.6961`) | `16.902` |
| `AMD Ryzen AI Max+ 395` | `shape_d_classical_best` | `100.0%` | `100.0%` | `57.4%` | **`85.80%`** | `1424.22` (`1416.39–1434.02`) | **`136.8865`** (`126.081–149.1449`) | `10.4642` |
| `AMD Ryzen AI Max+ 395` | `candidate_dense_mlp_int16` | `38.4%` | `79.0%` | `70.2%` | **`62.53%`** | `6918.09` (`6884.28–6947.09`) | **`665.0108`** (`617.8394–720.3827`) | `51.6015` |

- **Same-Meter `reported_j` Ratio (`AMD Ryzen AI Max+ 395`):** `candidate_dense_mlp_int16` burns **`4.86x` MORE package `reported_j` per correct operation than `shape_d_classical_best`** (`97.53x` more than `arm1_lookup_table`).

---

## 3. Paired `ΔAcc` & McNemar Analysis (`candidate_dense_mlp_int16` vs. `shape_d_classical_best`)

| Stratum | Classical `Shape D` Acc | Neural `MLP` Acc | Paired `ΔAcc` (`95% CI`) | McNemar Discordant `(Cand-Only, Null-Only)` | Exact 2-Sided `p` | Scientific Verdict |
|---|---:|---:|---:|---|---:|---|
| `bounded_api_dispatch` | `100.00%` | `38.40%` | **`-61.60%`** (`[-65.86%, -57.34%]`) | `(0, 308)` | `0.0` | Classical `if/else` & LUT saturate `100%`; neural compute is pure energy waste. |
| `combinatorial_constraint_3sat` | `100.00%` | `79.20%` | **`-20.80%`** (`[-24.36%, -17.24%]`) | `(0, 104)` | `0.0` | Exact `DPLL` solver achieves `100%`; feed-forward net stalls on constraint phase transition. |
| `open_compositional_patch_triage` | `57.40%` | `70.20%` | **`+12.80%`** (`[+9.00%, +16.60%]`) | `(83, 19)` | `0.0` | Learned representation achieves genuine `+12.8%` `ΔAcc` on novel oblique feature tail. |
| **Pooled (`N = 1,500`)** | **`85.80%`** | **`62.60%`** | **`-23.20%`** (`[-25.92%, -20.48%]`) | `(83, 431)` | `0.0` | Lookup/solver first on bounded & constraint strata; invoke neural models only on open compositional tail. |
