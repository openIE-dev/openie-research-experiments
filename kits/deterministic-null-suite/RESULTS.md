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

## 4. Oct 23 – Nov 24, 2026 Open-Weight SOTA LLM Panel (`2` to `34` Days Old) + Verified Crystallization

- **Strict 45-Day Recency Window (`2026-10-12` – `2026-11-26`):** Every model in this 6-model open-weight panel was published on Hugging Face between **`2026-10-23` and `2026-11-24`** (`2` to `34` days old at freeze) and executed deterministically (`temperature = 0.0`, `top_k = 1`, `seed = 20261126`, `cache_prompt = false`, CPU-only `-ngl 0`) via mainline `ggml-org/llama.cpp` (`commit 436d7e8`, `2026-11-26` `HEAD`). *(Note: `KRAFTON/Raon-1-nano-gguf` [`2026-11-10`] uses `gguf_arch = raon1nano` from unmerged PR `#32176`, so Tier-A slot #3 uses `ggml-org/Qwen3.5-4B-GGUF` [`2026-11-12`, `Apache-2.0`].)*
- **Confirmatory Subset Pre-Commitment (`subset90`):** `SHA-256 = e9115baa0110448ce273ef951eeab4b3d927ad526087e75f00fae94092f27844` (`BLAKE3 = e4c459518ef21e58da31fc09f91f13bd0d52e914125ba8e9f6a4a530e7aaeb5d`). Where CPU-only latency on `Cortex-A53` or `27B` `Q2_0` required a smaller stratified prefix (`N ∈ {45, 30, 15}`), exact `N`, exact two-sided 95% Clopper–Pearson CIs, and paired McNemar `(b, c)` against `Shape D` on the **identical `N` instances** are reported with zero extrapolation.
- **Pooled Determinism Gate:** **`0 / 42` spot-check divergences** across all 3 substrates (`18` on `Zen 5`, `18` on `Thor`, `6` on `KV260`; one-sided 95% Clopper–Pearson upper bound `<= 0.068846`).
- **Scope Note (per 25 Nov 2026 Outside Review):** Stage-1 `<= 4 KiB` LUT hits measure **exact content-addressed recall on recurring verified inputs (`C(x, z) == 1`)**, **not** unseen cold generalization; unseen structured/constraint arrivals route to Stage-2 classical rules/`DPLL`, and unseen open compositional arrivals escalate to the live Stage-3 teacher.
- **Signed Multi-Substrate Receipt Bundle:** [`results/real_llm_multi_substrate_receipts.json`](./results/real_llm_multi_substrate_receipts.json) and [`results/receipt_real_llm_crystallization.json`](./results/receipt_real_llm_crystallization.json) (`BLAKE3 = 84dd1c1a3c7fc60884546a67...`).

### Table C — Physical DC Shunt Metering (`evidence_class = measured_j`, Strictly Separated from `reported_j`)

- **AMD Kria KV260 (`TI INA260` `SOM_5V_DC`, `4` Cortex-A53 PS CPU threads, `3.3 GiB` free RAM):** Idle `A1/A2` trimmed `3.2721 W` (`0.56%` drift <= `5.0%`; **`Falsifier 6 = False`** — both Gross and Net-Above-Idle `A1/A2` `measured_j` reported).
- **NVIDIA Jetson AGX Thor (`TI INA3221` `VDD_CPU_SOC_MSS` + `TI INA238` `VIN`, `12` ARMv9 CPU threads, `-ngl 0`):** Idle `A1/A2` trimmed `4.9127 W` (`17.46%` drift > `5.0%` on shared host; **`Falsifier 6 = True`** — single-window Net-Above-Idle `A1/A2` withheld as `null` per `Falsifier 6`, while exact Gross `VDD_CPU_SOC_MSS` and Carrier `VIN` `measured_j` are reported).

| Board | Primary Rail | Model / Regime | Release | `N` | API | 3-SAT | Triage | Overall Acc (`95% CI`) | McNemar `(LLM, Null)` | Gross Rail `measured_j` `µJ / correct` (`x Shape D`) | Net `A1/A2` `measured_j` `µJ / correct` | Carrier `VIN` `measured_j` `µJ / correct` |
|---|---|---|---|---:|---:|---:|---:|---|---|---:|---:|---:|
| `AMD Kria KV260` | `INA260 SOM_5V_DC` | `shape_d_classical_best` *(control)* | `—` | `45` | `100.0%` | `100.0%` | `86.7%` | **`95.56%`** (`[84.9%, 99.5%]`) | `(0, 0)` | **`4.7797`** (`1.00x`) | `0.2368` | `n/a` |
| `AMD Kria KV260` | `INA260 SOM_5V_DC` | **`LiquidAI LFM3-1.7B (Q4_K_M)`** | `2026-10-24` | `45` | `20.0%` | `100.0%` | `40.0%` | **`53.33%`** (`[37.9%, 68.3%]`) | `(0, 19)` | **`540571497.75`** (`113097369.66x`) | `127033706.2184` | `n/a` |
| `AMD Kria KV260` | `INA260 SOM_5V_DC` | **`LiquidAI d1-2B System-1 Decision (Q4_K_M)`** | `2026-10-27` | `30` | `50.0%` | `100.0%` | `20.0%` | **`56.67%`** (`[37.4%, 74.5%]`) | `(1, 12)` | **`608503934.0`** (`185859478.92x`) | `142510532.9624` | `n/a` |
| `AMD Kria KV260` | `INA260 SOM_5V_DC` | **`multi_teacher_union_t2_replay`** *(recall+`Shape D`)* | `2026-11-26` | `45` | `100.0%` | `100.0%` | `—` | **`97.78%`** (`[88.2%, 99.9%]`) | `—` | **`0.0643`** | `0.0034` | `n/a` |
| `AMD Kria KV260` | `INA260 SOM_5V_DC` | **`compiled_agency_zipf085_stream`** *(Stage-3 `lfm3_1_7b`)* | `2026-11-26` | `300` | `—` | `—` | `—` | **`91.33%`** (`[87.6%, 94.3%]`) | `—` | **`25011475.8358`** (**`21.61x` < cold LLM**) | `5885444.815` | `n/a` |
| `Jetson AGX Thor` | `INA3221 VDD_CPU_SOC_MSS` | `shape_d_classical_best` *(control)* | `—` | `90` | `100.0%` | `100.0%` | `63.3%` | **`87.78%`** (`[79.2%, 93.7%]`) | `(0, 0)` | **`1.3971`** (`1.00x`) | `withheld (F6)` | `4.6053` |
| `Jetson AGX Thor` | `INA3221 VDD_CPU_SOC_MSS` | **`LiquidAI LFM3-1.7B (Q4_K_M)`** | `2026-10-24` | `90` | `13.3%` | `96.7%` | `20.0%` | **`43.33%`** (`[32.9%, 54.2%]`) | `(0, 40)` | **`57536181.4872`** (`41182579.26x`) | `withheld (F6)` | `97900845.2564` |
| `Jetson AGX Thor` | `INA3221 VDD_CPU_SOC_MSS` | **`LiquidAI d1-2B System-1 Decision (Q4_K_M)`** | `2026-10-27` | `90` | `53.3%` | `96.7%` | `13.3%` | **`54.44%`** (`[43.6%, 65.0%]`) | `(1, 31)` | **`55531431.8776`** (`39747642.89x`) | `withheld (F6)` | `92275204.7551` |
| `Jetson AGX Thor` | `INA3221 VDD_CPU_SOC_MSS` | **`Qwen3.5-4B (Q4_K_M)`** | `2026-11-12` | `45` | `20.0%` | `93.3%` | `20.0%` | **`44.44%`** (`[29.6%, 60.0%]`) | `(0, 23)` | **`153342438.6`** (`184416642.93x`) | `withheld (F6)` | `261973451.0` |
| `Jetson AGX Thor` | `INA3221 VDD_CPU_SOC_MSS` | **`NVIDIA Nemotron-3.5-Bolt-E4B (UD-Q4_K_XL)`** | `2026-10-23` | `45` | `20.0%` | `100.0%` | `33.3%` | **`51.11%`** (`[35.8%, 66.3%]`) | `(0, 20)` | **`153113356.3913`** (`184141138.17x`) | `withheld (F6)` | `259050071.7391` |
| `Jetson AGX Thor` | `INA3221 VDD_CPU_SOC_MSS` | **`TML Inkling-2-Mini 26.4B-A3.4B Looped MoE (UD-IQ4_XS)`** | `2026-11-20` | `45` | `60.0%` | `100.0%` | `46.7%` | **`68.89%`** (`[53.4%, 81.8%]`) | `(0, 12)` | **`396265098.2903`** (`476566564.39x`) | `withheld (F6)` | `666178065.3871` |
| `Jetson AGX Thor` | `INA3221 VDD_CPU_SOC_MSS` | **`PrismML Ternary-Bonsai-2.5-27B (Q2_0)`** | `2026-11-24` | `15` | `100.0%` | `100.0%` | `60.0%` | **`86.67%`** (`[59.5%, 98.3%]`) | `(0, 2)` | **`1512642844.9231`** (`3009036890.64x`) | `withheld (F6)` | `2583006365.7692` |
| `Jetson AGX Thor` | `INA3221 VDD_CPU_SOC_MSS` | **`multi_teacher_union_t2_replay`** *(recall+`Shape D`)* | `2026-11-26` | `45` | `100.0%` | `100.0%` | `—` | **`95.56%`** (`[84.9%, 99.5%]`) | `—` | **`0.0112`** | `withheld (F6)` | `0.0283` |
| `Jetson AGX Thor` | `INA3221 VDD_CPU_SOC_MSS` | **`compiled_agency_zipf085_stream`** *(Stage-3 `inkling_2_mini`)* | `2026-11-26` | `300` | `—` | `—` | `—` | **`96.67%`** (`[94.0%, 98.4%]`) | `—` | **`13272482.631`** (**`29.86x` < cold LLM**) | `withheld (F6)` | `22370986.4276` |

- **Key Physical `measured_j` Findings:**
  1. **System-1 Decision Head (`LiquidAI/d1-2B`, `/v1/systemone`) vs. Autoregressive Generation:** On `Jetson AGX Thor` (`N = 90`), `d1-2B` lifts accuracy from `LFM3-1.7B`'s `43.33%` to **`54.44%`** (`53.3%` vs `13.3%` on `bounded_api_dispatch`) at lower physical energy (`55.53 J` vs `57.54 J/correct`), yet still burns **`39,747,643x` more `VDD_CPU_SOC_MSS` `measured_j` per correct operation than `shape_d_classical_best`** (`1.3971 µJ/correct`).
  2. **2-Day-Old Native Ternary 27B (`PrismML/Ternary-Bonsai-2.5-27B` `Q2_0`, `2026-11-24`) Impedance Tax on ARMv9:** Achieves **`86.67%` (`13/15`, `60.0%` Triage)** on `Thor`, but because `ggml_vec_dot_q2_0_q8_0` falls back to scalar `ggml_vec_dot_q2_0_q8_0_generic` on `aarch64`, it consumes **`1,512.64 J/correct` (`VDD_CPU_SOC_MSS`) / `2,519.86 J/correct` (`INA238 VIN`)** — **`3.82x` more `measured_j` per correct decision than the `26.4B` Looped MoE `Inkling-2-Mini` (`396.27 J/correct`, ARM `I8MM`/`SDOT`)**.
  3. **Compiled Agency `Zipf(0.85)` Live Stream (`300` Queries with `15%` Unseen Cold Arrivals):**
     - **`Jetson AGX Thor` (Stage-3 `Inkling-2-Mini`):** Lifts accuracy from `68.89%` to **`96.67%` (`290/300`)** while cutting physical `VDD_CPU_SOC_MSS` `measured_j` per correct operation by **`29.86x` (`396.27 J -> 13.27 J`)** (`255` Stage-1 LUT hits, `29` Stage-2 solver hits, `16` live `Inkling-2-Mini` escalations).
     - **`AMD Kria KV260` (Stage-3 `LFM3-1.7B`):** Lifts accuracy from `53.33%` to **`91.33%` (`274/300`)** while cutting physical `SOM_5V_DC` `measured_j` per correct operation by **`21.61x` gross (`540.57 J -> 25.01 J`)** and **`21.58x` net-above-idle (`127.03 J -> 5.89 J`)**.

### Table D — On-Chip Hardware Energy Counters (`AMD Ryzen AI Max+ 395`, `evidence_class = reported_j`)

| Model / Regime (`AMD Ryzen AI Max+ 395` `RAPL`) | Release | `N` | API | 3-SAT | Triage | Overall Acc (`95% CI`) | McNemar `(LLM, Null)` | Package `reported_j` `µJ / correct` (`x Shape D`) | Core `reported_j` `µJ / correct` |
|---|---|---:|---:|---:|---:|---|---|---:|---:|
| `shape_d_classical_best` *(control)* | `—` | `90` | `100.0%` | `100.0%` | `63.3%` | **`87.78%`** (`[79.2%, 93.7%]`) | `(0, 0)` | **`4.0006`** (`1.00x`) | `—` |
| **`LiquidAI LFM3-1.7B (Q4_K_M)`** | `2026-10-24` | `90` | `13.3%` | `96.7%` | `20.0%` | **`43.33%`** (`[32.9%, 54.2%]`) | `(0, 40)` | **`76307676.2051`** (`19074057.94x`) | `5091822.6667` |
| **`LiquidAI d1-2B System-1 Decision (Q4_K_M)`** | `2026-10-27` | `90` | `53.3%` | `96.7%` | `16.7%` | **`55.56%`** (`[44.7%, 66.0%]`) | `(2, 31)` | **`63730402.94`** (`15930211.2x`) | `4241514.06` |
| **`Qwen3.5-4B (Q4_K_M)`** | `2026-11-12` | `90` | `16.7%` | `96.7%` | `20.0%` | **`44.44%`** (`[34.0%, 55.3%]`) | `(2, 41)` | **`293012387.925`** (`73242110.66x`) | `18673657.775` |
| **`NVIDIA Nemotron-3.5-Bolt-E4B (UD-Q4_K_XL)`** | `2026-10-23` | `90` | `20.0%` | `96.7%` | `26.7%` | **`47.78%`** (`[37.1%, 58.6%]`) | `(1, 37)` | **`112879729.3488`** (`28215699.98x`) | `7408663.8372` |
| **`TML Inkling-2-Mini 26.4B-A3.4B Looped MoE (UD-IQ4_XS)`** | `2026-11-20` | `90` | `43.3%` | `96.7%` | `33.3%` | **`57.78%`** (`[46.9%, 68.1%]`) | `(0, 27)` | **`673862280.1923`** (`168440304.0x`) | `40434416.8269` |
| **`PrismML Ternary-Bonsai-2.5-27B (Q2_0)`** | `2026-11-24` | `45` | `60.0%` | `100.0%` | `46.7%` | **`68.89%`** (`[53.4%, 81.8%]`) | `(0, 12)` | **`1685972475.8065`** (`724028375.77x`) | `102200163.5161` |
| **`multi_teacher_union_t2_replay`** *(6-model union+`Shape D`)* | `2026-11-26` | `90` | `100.0%` | `100.0%` | `73.3%` | **`91.11%`** (`[83.2%, 96.1%]`) | `—` | **`0.0189`** | `0.0` |
| **`compiled_agency_zipf085_stream`** *(Stage-3 `inkling_2_mini`)* | `2026-11-26` | `300` | `—` | `—` | `—` | **`94.33%`** (`[91.1%, 96.7%]`) | `—` | **`26082824.6007`** (**`25.84x` < cold LLM**) | `1548050.7456` |

- **Multi-Teacher Soundness-Gated Crystallization (`C(x, z) == 1`):** Across the 6 Oct–Nov 2026 models on `N = 90`, `d1-2B` (`b = 2`), `Qwen3.5-4B` (`b = 2`), and `Nemotron-3.5-Bolt-E4B` (`b = 1`) solve **discordant `open_compositional_patch_triage` instances that `Shape D` missed**, while `C(x, z) == 1` rejects every hallucination (`c = 27..41`), lifting `multi_teacher_union_t2_replay` to **`91.11%` (`82/90`)** on `Zen 5` (`0.0189 µJ/correct`), **`95.56%` (`43/45`)** on `Thor` (`0.0112 µJ/correct`), and **`97.78%` (`44/45`)** on `KV260` (`0.0643 µJ/correct`).
- **Live `300`-Query `Zipf(0.85)` Stream on `Zen 5` (Stage-3 `Inkling-2-Mini`):** Achieves **`94.33%` (`283/300`)** accuracy at **`26.08 J/correct` package `reported_j`** — **`25.84x` lower `reported_j` per correct operation and `+36.55%` higher accuracy** than cold `Inkling-2-Mini` (`673.86 J/correct`, `57.78%`).
