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

---

## 4. Real Pretrained Open-Weight Transformer (`Qwen2.5-0.5B-Instruct`, `494M`) + Verified Crystallization (`N = 90` & `300`-Query `Zipf(0.85)` Stream)

- **Model & Runtime:** Official `Qwen/Qwen2.5-0.5B-Instruct-GGUF/qwen2.5-0.5b-instruct-q4_k_m.gguf` (`24`-layer Transformer, `494M` params, `491,400,032 B`, `SHA-256 = 74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db`), executed CPU-only (`-ngl 0`, `cache_prompt = false`, `temperature = 0.0`, `top_k = 1`, `seed = 20261126`) via `llama.cpp` `llama-server`.
- **Confirmatory Subset Pre-Commitment (`N = 90`, `30` per stratum):** `SHA-256 = e9115baa0110448ce273ef951eeab4b3d927ad526087e75f00fae94092f27844` (`BLAKE3 = e4c459518ef21e58da31fc09f91f13bd0d52e914125ba8e9f6a4a530e7aaeb5d`).
- **Cross-Architecture Determinism:** `0 / 30` pooled spot-check divergences across `Cortex-A53`, `ARMv9`, and `Zen 5` (one-sided 95% Clopper–Pearson upper bound `<= 0.095034`), plus **exact stratum-for-stratum accuracy (`3.33%` / `96.67%` / `10.00%`, overall `36.67%`) and exact stage-routing agreement (`236` Stage-1 LUT / `29` Stage-2 solver / `35` Stage-3 live LLM) across all three hardware architectures**.
- **Scope Note (per 25 Nov 2026 Review):** Stage-1 `<= 4 KiB` LUT hits measure **exact content-addressed recall on recurring verified inputs (`C(x, z) == 1`)**, **not** unseen cold generalization; in the `300`-query `Zipf(0.85)` stream (`85%` recurring arrivals + `15%` unseen cold held-out arrivals from indices `30..49`), unseen structured/constraint arrivals route to Stage-2 classical rules/`DPLL`, and unseen open compositional triage arrivals escalate to the live `Qwen2.5-0.5B-Instruct` Transformer (`35` live LLM calls).
- **Signed Multi-Substrate Receipt Bundle:** [`results/real_llm_multi_substrate_receipts.json`](./results/real_llm_multi_substrate_receipts.json) and [`results/receipt_real_llm_crystallization.json`](./results/receipt_real_llm_crystallization.json) (`BLAKE3 = b8271399c051379477351e3c...`).

### Table C — Physical DC Shunt Metering (`evidence_class = measured_j`: `Qwen2.5-0.5B-Instruct` vs. 5 Classical Controls & Crystallization)

- **AMD Kria KV260 (`TI INA260` `SOM_5V_DC`, user-space PS CPU only):** Idle `A1/A2` trimmed `3.27 W` (`0.43%` drift; `Falsifier 6 = False`; `396,772` shunt samples during `t = 1` cold LLM & `155,893` during the `300`-query live stream).
- **NVIDIA Jetson AGX Thor (`TI INA3221` `VDD_CPU_SOC_MSS` + `TI INA238` `VIN`, CPU-only `-ngl 0`):** Idle `A1/A2` trimmed `6.5612 W` (`3.31%` drift; `Falsifier 6 = False`; `30,989` shunt samples during `t = 1` cold LLM & `11,958` during the `300`-query live stream).

| Board | Primary Rail | Regime | API (`30`) | 3-SAT (`30`) | Triage (`30`) | Accuracy | Wall `µs / correct` | Gross Rail `measured_j` `µJ / correct` | Net-Above-Idle `measured_j` `µJ / correct` | Carrier `VIN` `measured_j` `µJ / correct` |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `AMD Kria KV260` | `INA260 SOM_5V_DC` | `arm1_lookup_table` (`N=90`) | `100.0%` | `96.7%` | `40.0%` | **`78.89%`** | `0.3255` | **`1.1249`** | `0.0602` | `n/a` |
| `AMD Kria KV260` | `INA260 SOM_5V_DC` | `arm2_if_else_guards` (`N=90`) | `100.0%` | `56.7%` | `33.3%` | **`63.33%`** | `0.0659` | **`0.2322`** | `0.0163` | `n/a` |
| `AMD Kria KV260` | `INA260 SOM_5V_DC` | `arm3_bounded_for_loop` (`N=90`) | `100.0%` | `50.0%` | `60.0%` | **`70.00%`** | `10.8765` | **`37.3093`** | `1.7334` | `n/a` |
| `AMD Kria KV260` | `INA260 SOM_5V_DC` | `arm4_decision_tree` (`N=90`) | `96.7%` | `90.0%` | `50.0%` | **`78.89%`** | `0.1085` | **`0.3767`** | `0.0217` | `n/a` |
| `AMD Kria KV260` | `INA260 SOM_5V_DC` | `arm5_compiled_solver_rules` (`N=90`) | `100.0%` | `100.0%` | `63.3%` | **`87.78%`** | `19.5118` | **`67.0355`** | `3.2228` | `n/a` |
| `AMD Kria KV260` | `INA260 SOM_5V_DC` | `shape_d_classical_best` (`N=90`) | `100.0%` | `100.0%` | `63.3%` | **`87.78%`** | `2.5532` | **`8.784`** | `0.4333` | `n/a` |
| `AMD Kria KV260` | `INA260 SOM_5V_DC` | `candidate_dense_mlp_int16` (`N=90`) | `40.0%` | `83.3%` | `70.0%` | **`64.44%`** | `146.31` | **`506.1481`** | `27.6054` | `n/a` |
| `AMD Kria KV260` | `INA260 SOM_5V_DC` | **`Qwen2.5-0.5B-Instruct` (`t=1` cold, `N=90`)** | `3.3%` | `96.7%` | `10.0%` | **`36.67%`** | `55670991.546` | **`236975509.9091`** | `54931367.5555` | `n/a` |
| `AMD Kria KV260` | `INA260 SOM_5V_DC` | **`crystallized_lut_t2_replay` (`N=90`, recall+`Shape D`)** | `100.0%` | `100.0%` | `70.0%` | **`90.00%`** | `0.018` | **`0.0839`** | `0.0262` | `n/a` |
| `AMD Kria KV260` | `INA260 SOM_5V_DC` | **`compiled_agency_zipf085_stream` (`300` live queries)** | `—` | `—` | `—` | **`89.33%`** | `2693202.046` | **`11466963.1455`** | `2660192.4591` | `n/a` |
| `Jetson AGX Thor` | `INA3221 VDD_CPU_SOC_MSS` | `arm1_lookup_table` (`N=90`) | `100.0%` | `96.7%` | `40.0%` | **`78.89%`** | `0.0744` | **`0.5465`** | `0.0584` | `1.628` |
| `Jetson AGX Thor` | `INA3221 VDD_CPU_SOC_MSS` | `arm2_if_else_guards` (`N=90`) | `100.0%` | `56.7%` | `33.3%` | **`63.33%`** | `0.0053` | **`0.0439`** | `0.0088` | `0.1334` |
| `Jetson AGX Thor` | `INA3221 VDD_CPU_SOC_MSS` | `arm3_bounded_for_loop` (`N=90`) | `100.0%` | `50.0%` | `60.0%` | **`70.00%`** | `0.9945` | **`7.1259`** | `0.5777` | `21.6155` |
| `Jetson AGX Thor` | `INA3221 VDD_CPU_SOC_MSS` | `arm4_decision_tree` (`N=90`) | `96.7%` | `90.0%` | `50.0%` | **`78.89%`** | `0.0217` | **`0.1683`** | `0.0261` | `0.5119` |
| `Jetson AGX Thor` | `INA3221 VDD_CPU_SOC_MSS` | `arm5_compiled_solver_rules` (`N=90`) | `100.0%` | `100.0%` | `63.3%` | **`87.78%`** | `1.6902` | **`12.4435`** | `1.0246` | `37.5815` |
| `Jetson AGX Thor` | `INA3221 VDD_CPU_SOC_MSS` | `shape_d_classical_best` (`N=90`) | `100.0%` | `100.0%` | `63.3%` | **`87.78%`** | `0.2333` | **`1.7672`** | `0.2284` | `5.3093` |
| `Jetson AGX Thor` | `INA3221 VDD_CPU_SOC_MSS` | `candidate_dense_mlp_int16` (`N=90`) | `40.0%` | `83.3%` | `70.0%` | **`64.44%`** | `18.293` | **`123.0199`** | `2.9931` | `395.166` |
| `Jetson AGX Thor` | `INA3221 VDD_CPU_SOC_MSS` | **`Qwen2.5-0.5B-Instruct` (`t=1` cold, `N=90`)** | `3.3%` | `96.7%` | `10.0%` | **`36.67%`** | `4690494.491` | **`85309120.6667`** | `54533848.2527` | `159348166.1818` |
| `Jetson AGX Thor` | `INA3221 VDD_CPU_SOC_MSS` | **`crystallized_lut_t2_replay` (`N=90`, recall+`Shape D`)** | `100.0%` | `100.0%` | `70.0%` | **`90.00%`** | `0.001` | **`0.0466`** | `0.0395` | `0.0597` |
| `Jetson AGX Thor` | `INA3221 VDD_CPU_SOC_MSS` | **`compiled_agency_zipf085_stream` (`300` live queries)** | `—` | `—` | `—` | **`89.33%`** | `217682.228` | **`3460888.8433`** | `2032632.2115` | `6718784.0485` |

- **Same-Meter `measured_j` Ratios (`AMD Kria KV260` `SOM_5V_DC`):**
  - Cold `Qwen2.5-0.5B-Instruct` (`236.98 J/correct` gross, `54.93 J/correct` net) burns **`26,978,086x` MORE gross `measured_j` per correct operation than `shape_d_classical_best`** (`8.784 µJ/correct`) while scoring `-51.11%` lower accuracy (`36.67%` vs `87.78%`).
  - On the live `300`-query `Zipf(0.85)` stream (`15%` unseen cold arrivals), **Compiled Agency (`Stage 1 LUT -> Stage 2 Rules/DPLL -> Stage 3 Live Qwen2.5-0.5B`)** lifts accuracy to **`89.33%` (`268/300`)** and cuts physical `SOM_5V_DC` `measured_j` per correct operation by **`20.67x` gross (`236.98 J -> 11.47 J`)** and **`20.65x` net-above-idle (`54.93 J -> 2.66 J`)**.
- **Same-Meter `measured_j` Ratios (`NVIDIA Jetson AGX Thor` `VDD_CPU_SOC_MSS`):**
  - Cold `Qwen2.5-0.5B-Instruct` (`85.31 J/correct` gross, `54.53 J/correct` net; `159.35 J/correct` carrier `VIN`) burns **`48,273,608x` MORE `VDD_CPU_SOC_MSS` `measured_j` per correct operation than `shape_d_classical_best`** (`1.7672 µJ/correct`).
  - On the live `300`-query `Zipf(0.85)` stream, **Compiled Agency** achieves **`89.33%` (`268/300`)** accuracy while cutting `VDD_CPU_SOC_MSS` `measured_j` per correct operation by **`24.65x` gross (`85.31 J -> 3.46 J`)** and **`26.83x` net-above-idle (`54.53 J -> 2.03 J`)** (`23.72x` on whole-carrier `INA238` `VIN`).

### Table D — On-Chip Hardware Energy Counters (`evidence_class = reported_j`, Strictly Separated from `measured_j`)

| Host CPU (`x86_64`) | Regime | API (`30`) | 3-SAT (`30`) | Triage (`30`) | Accuracy | Wall `µs / correct` | Package `reported_j` `µJ / correct` | Core `reported_j` `µJ / correct` |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `AMD Ryzen AI Max+ 395` | `arm1_lookup_table` (`N=90`) | `100.0%` | `96.7%` | `40.0%` | **`78.89%`** | `0.051` | **`3.211`** | `—` |
| `AMD Ryzen AI Max+ 395` | `arm2_if_else_guards` (`N=90`) | `100.0%` | `56.7%` | `33.3%` | **`63.33%`** | `0.0034` | **`0.2692`** | `—` |
| `AMD Ryzen AI Max+ 395` | `arm3_bounded_for_loop` (`N=90`) | `100.0%` | `50.0%` | `60.0%` | **`70.00%`** | `0.4329` | **`30.559`** | `—` |
| `AMD Ryzen AI Max+ 395` | `arm4_decision_tree` (`N=90`) | `96.7%` | `90.0%` | `50.0%` | **`78.89%`** | `0.0048` | **`0.2797`** | `—` |
| `AMD Ryzen AI Max+ 395` | `arm5_compiled_solver_rules` (`N=90`) | `100.0%` | `100.0%` | `63.3%` | **`87.78%`** | `1.9904` | **`134.7349`** | `—` |
| `AMD Ryzen AI Max+ 395` | `shape_d_classical_best` (`N=90`) | `100.0%` | `100.0%` | `63.3%` | **`87.78%`** | `0.1315` | **`8.1931`** | `—` |
| `AMD Ryzen AI Max+ 395` | `candidate_dense_mlp_int16` (`N=90`) | `40.0%` | `83.3%` | `70.0%` | **`64.44%`** | `6.7811` | **`423.5118`** | `—` |
| `AMD Ryzen AI Max+ 395` | **`Qwen2.5-0.5B-Instruct` (`t=1` cold, `N=90`)** | `3.3%` | `96.7%` | `10.0%` | **`36.67%`** | `488361.592` | **`62822336.7273`** | `5279840.3939` |
| `AMD Ryzen AI Max+ 395` | **`crystallized_lut_t2_replay` (`N=90`, recall+`Shape D`)** | `100.0%` | `100.0%` | `70.0%` | **`90.00%`** | `0.002` | `0.0 (<1 ms RAPL tick)` | `0.0` |
| `AMD Ryzen AI Max+ 395` | **`compiled_agency_zipf085_stream` (`300` live queries)** | `—` | `—` | `—` | **`89.33%`** | `23637.199` | **`3067419.6455`** | `246641.8134` |

- **Same-Meter `reported_j` Ratios (`AMD Ryzen AI Max+ 395`):** Cold `Qwen2.5-0.5B-Instruct` (`62.82 J/correct` package `reported_j`) burns **`7,667,713x` MORE package `reported_j` per correct operation than `shape_d_classical_best`** (`8.1931 µJ/correct`), and **Compiled Agency** on the `300`-query `Zipf(0.85)` live stream cuts package `reported_j` per correct operation by **`20.48x` (`62.82 J -> 3.07 J`)** while raising accuracy from `36.67%` to `89.33%`.

### Table E — Paired `ΔAcc` & McNemar Analysis (`Qwen2.5-0.5B-Instruct` Cold `t = 1` vs. `shape_d_classical_best`, `N = 90`)

| Stratum (`30` instances each) | Classical `Shape D` Acc | `Qwen2.5-0.5B` (`t=1`) Acc | Paired `ΔAcc` (`95% CI`) | McNemar Discordant `(LLM-Only, Null-Only)` | Exact 2-Sided `p` | Mechanistic Takeaway |
|---|---:|---:|---:|---|---:|---|
| `bounded_api_dispatch` | `100.00%` | `3.33%` | **`-96.67%`** (`[-100.0%, -90.24%]`) | `(0, 29)` | `0.0` | Compact instruction LLM fails multi-branch numeric threshold chains that `20`-line `if/else` solves at `100%` for `<0.3 µJ`. |
| `combinatorial_constraint_3sat` | `100.00%` | `96.67%` | **`-3.33%`** (`[-9.76%, +3.09%]`) | `(0, 1)` | `1.0` | LLM matches `29/30` instances (`p = 1.0`), yet burns `3.5M–6.9M×` more `measured_j` than exact `DPLL` (`arm5_compiled_solver_rules`). |
| `open_compositional_patch_triage` | `63.33%` | `10.00%` | **`-53.33%`** (`[-75.46%, -31.21%]`) | `(2, 18)` | `0.000402` | Zero-shot `0.5B` LLM struggles on raw 12-channel integer vectors (`3/30`), yet finds **`2` novel discordant wins** missed by `Shape D` (admitted into `t=2` LUT via `C(x,z)=1`, lifting `t=2` triage recall to `70.0%`). |
| **Pooled (`N = 90`)** | **`87.78%`** | **`36.67%`** | **`-51.11%`** (`[-62.32%, -39.90%]`) | `(2, 48)` | `0.0` | Ephemeral cold LLM inference on bounded/constraint work wastes `7.7M–48.3M×` joules; Verified Downward Crystallization (`Zipf(0.85)` stream) recovers `89.33%` accuracy at `20.5–24.7x` lower energy than cold LLM. |
