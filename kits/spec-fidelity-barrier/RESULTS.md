# Kit #8 (`spec-fidelity-barrier`) — Empirical Results

- **Provenance Tier:** `Signed Provenance · Self-Checked` (`BLAKE3` + `Ed25519`; never self-labeled `"Verified"`)
- **Receipt Body `BLAKE3`:** `41514ee6147d636d6bcb27f4ee392e4c9c3ce4ffd2bce2fd88a1afd48e9d1e0a`
- **CPU / OS:** `AMD RYZEN AI MAX+ 395 w/ Radeon 8060S` (`32` logical CPUs, `Linux 7.0.0-43-generic x86_64`)
- **Energy Evidence Class:** `reported_j` (`measured_j ⊥ reported_j ⊥ est_j ⊥ unmetered`, never summed)

## 1. Progressive 4-Arm Commit Gate Fidelity (`40` Tasks, `200` Implanted Bugs, `200` AST Mutants)

| Gate Architecture | Spec Visibility | AST Mutant Kill Rate | Defective Candidates Falsely Accepted (`/ 200`) | Candidate False-Accept Rate (Exact 95% Clopper–Pearson CI) | Tasks Admitting `>=1` Bug (`/ 40`) | Valid Candidates Accepted (`/ 40`) |
|---|---|---|---|---|---|---|
| `arm_a_shared_context_naive` | Shared (`Spec + Impl`) | `72.5%` (`SPEC_VACUOUS_REFUSED`: `31/40`) | `199 / 200` | `0.9950` (`[0.9725, 0.9999]`; 1-sided `<= 0.99974`) | `40 / 40` | `40 / 40` |
| `arm_b_isolated_spec_only` | Isolated (`Spec ⊥ Impl`) | `49.5%` (`SPEC_VACUOUS_REFUSED`: `40/40`) | `146 / 200` | `0.7300` (`[0.6628, 0.7902]`; 1-sided `<= 0.78132`) | `40 / 40` | `40 / 40` |
| `arm_c_mutant_vacuity_barrier` | Isolated (`Spec ⊥ Impl`) | `100.0%` (`SPEC_ADMITTED`: `40/40`) | `0 / 200` | `0.0000` (`[0.0000, 0.0183]`; 1-sided `<= 0.01487`) | `0 / 40` | `40 / 40` |

## 2. Arm D — In-Loop CFG/Type Token Masking vs. Post-Hoc Rejection (`1,000` Seeded Draws)

| Decoding + Gate Regime | Single-Draw Syntax/Type Rejects (`/ 1,000`) | Syntax/Type Wasted Tokens | Total Generated Tokens | Semantic False Accepts | Median Latency / Draw | Median RAPL `reported_j` / Draw |
|---|---|---|---|---|---|---|
| `unconstrained_posthoc_plus_arm_c` | `985 / 1000` (`98.5%`) | `298175` | `298865` | `0` | `570.541 µs` | `55337.409 µJ` (`IQR 20931.315`) |
| `grammar_mask_plus_mutant_gate` (**Arm D**) | **`0 / 1000` (`0.0%`)** | **`0` (`-100.0%`)** | **`4576` (`-98.47%`)** | **`0 / 800`** (1-sided 95% CI `<= 0.00374`) | **`12.912 µs` (`44.187x`)** | **`1223.711 µJ` (`IQR 340.663`)** (`45.221x` saving) |
