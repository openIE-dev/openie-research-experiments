# CTA-E6 (`HQ02` Closure): `FormEBM-v3` Live Pre-Filter Gating `MCTS`, Evolutionary Island Search, and `Lean 4.36.0`-Verified `RCE`

- **Experiment ID**: `CTA-E6` (Forecast Milestone `HQ02`)
- **Pre-Registration Digest**: `PREREG_cta_e6_hq02.json` (`SHA-256: 4a6b41d5f5c035b3ee086982732f743c6e0f89b9011f8786b720cc5916238fc8`)
- **`FormEBM-v3` Checkpoint (`6,052,802` params, `seed = 20261123`)**: `SHA-256: 3b50620883ab89b5bc29c622fc801cdb0c073b3588fec07016fa681cd47bfd25`
- **`RCE` Specification Commit**: `f87d6af289df5f406535ed1bf9abaf88fc94ff7a` (`5,393` `Lean 4.36.0` theorem constants)
- **Zero-Leakage Unseen-Shape Corpus (`hq02_unseen_corpus.json`)**: `140` multi-candidate defect tasks (`2,240` candidate `Forms` = `8` `Camp C4` `UCB1` `MCTS` rollouts + `8` `Camp C6` 2-island evolutionary single/multi-span AST/Form mutations per task) strictly drawn from the `137` held-out `test_forms` (`0` overlap with `1,106` `train_forms`, `144` `val_forms`, `151`-task ladder, or `40`-task `H15` residual).

## Hardware Substrates & Falsifier 6 Audit

| Host Target | Evidence Class | `board_metered` | Primary Rail | Pre `5.0 s` Idle | Post `5.0 s` Idle | Quiet Drift | Net Idle Subtraction Policy |
| :--- | :--- | :---: | :--- | ---: | ---: | ---: | :--- |
| **Linux x86-64 (`AMD Ryzen AI Max+ 395`, `32t` Zen 5)** | `reported_j` | `false` | `pkg_reported_j` (`core_reported_j`) | `9.8894 W` | `9.9686 W` | **`0.80%`** (`<= 10.0%`) | Dedicated quiet host; gross `reported_j` reported |
| **`NVIDIA Jetson AGX Thor` (`ARMv9` Tegra Linux, CPU-Only)** | `measured_j` | **`true`** | `l2_vdd_cpu_soc_mss_measured_j` (`l1_vin_ina238_measured_j`) | `6.1861 W` | `6.0757 W` | **`1.78%`** (`<= 10.0%`) | Shared-host GPU co-tenant lock respected (`CUDA_VISIBLE_DEVICES=""`); A2 net subtraction withheld per Falsifier 6 |

## Dual-Host Empirical Results (`140` Unseen Tasks · `2,240` `C4 + C6` Candidate `Forms`)

- **Unseen-Shape Ranking `AUROC`**: **`0.9580`** (`E_total`) / **`0.9577`** (`E_def`) on Linux x86-64 (`0.9579` / `0.9578` on `Jetson AGX Thor` `BF16`; kill gate `>= 0.85`).
- **Attested Digital Enzyme Envelopes**: `140 / 140` (`100%`) `DE10` `BLAKE3 + Ed25519` frames attested via compiled `cta_fleet_rust`.

| Pipeline Arm | Solved Tasks (`%`, Drop) | False Commits | `C2 + C10` Evals (`rce` Subprocs) | Call Reduction (`vs Pool` / `vs Seq`) | Linux Zen 5 `pkg_reported_j` (`core_reported_j`) | Linux `CpJ` (`tasks/J`) | `Jetson Thor` `VDD_CPU_SOC_MSS` **`measured_j`** (`VIN` **`measured_j`**) | `Thor` `CpJ` (`tasks/J`) |
| :--- | :---: | :---: | ---: | :---: | ---: | ---: | ---: | ---: |
| **`A1` Unfiltered Pool** (all `16`/task) | `124 / 140` (`88.57%`) | `0` | `2,240` (`13,833`) | `1.000x` / `0.534x` | `1,949.40 J` (`42.88 J`) | `0.0636` | `1,001.48 J` (`3,285.74 J`) | `0.1238` |
| **`A2` Unfiltered Sequential** (`C4+C6` order) | `124 / 140` (`88.57%`) | `0` | `1,197` (`7,554`) | `1.871x` / `1.000x` | `1,106.93 J` (`27.90 J`) | `0.1120` | `567.51 J` (`1,847.39 J`) | `0.2185` |
| **`B` `FormEBM-v3` Hard Top-`k` / Threshold** | `119 / 140` (`85.00%`, `-3.57%`) | `0` | `311` (`2,223`) | **`7.203x`** / **`3.849x`** | `810.97 J` (`11.03 J`) | `0.1467` | `390.20 J` (`1,075.98 J`) | `0.3050` |
| **`C` `FormEBM-v3` Adaptive Cascade** | **`124 / 140` (`88.57%`, `0.00%`)** | **`0`** | **`469` (`3,186`)** | **`4.776x`** / **`2.552x`** | **`948.67 J`** (`14.41 J`) | **`0.1307`** | **`458.16 J`** (`1,294.57 J`) | **`0.2706`** |

## Theorem `CTA-T21` (`E_gate < F · E_down`) & Kill-Criteria Verdict

1. **`K1` (`AUROC >= 0.85`)**: **PASS** (`0.9580` Linux `x86_64` / `0.9579` `Jetson AGX Thor`).
2. **`K2` (`Terminal solve-rate drop <= 1.0%`)**: **PASS** (`0.00%` drop in `Arm C` Ranked Adaptive Cascade: `124 / 140` vs `124 / 140` unfiltered; contrasts cleanly against `-3.57%` when hard-truncating without tail fallback in `Arm B`).
3. **`K3` (`Downstream RCE checker call reduction > 2.39x`)**: **PASS** (`4.776x` vs Unfiltered Pool and `2.552x` vs Unfiltered Sequential: `469` vs `2,240` and `1,197` candidate evaluations).
4. **`K4` (`CTA-T21` Energy Dominance `E_gate < F · E_down` & total pipeline savings)**: **PASS on both hosts**:
   - **Linux Zen 5 (`reported_j`)**: `E_gate = 404.52 J` (`3.25 J` `core_reported_j`) `< F_seq · E_down = 673.22 J` and `< F_pool · E_down = 1,541.25 J`; total pipeline `948.67 J < 1,106.93 J` (`1.167x` vs Sequential; `1.936x` core) and `< 1,949.40 J` (`2.055x` vs Pool; `2.975x` core).
   - **`NVIDIA Jetson AGX Thor` (`measured_j`)**: `E_gate = 173.38 J` `VDD_CPU_SOC_MSS` (`77.40 mJ`/candidate) `< F_seq · E_down = 345.15 J` and `< F_pool · E_down = 791.79 J`; total pipeline `458.16 J < 567.51 J` (`1.239x` vs Sequential) and `< 1,001.48 J` (`2.186x` vs Pool).
5. **`K5` (`0` corrupt commits)**: **PASS** (`0 / 140` false commits across all arms).

**Milestone `HQ02` Verdict**: **`Verified [T/E]` (`all_kill_criteria_passed = true` on both hosts)**.
