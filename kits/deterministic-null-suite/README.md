# Kit 1: `deterministic-null-suite` — Standardized 5-Arm Classical Automation Control Suite & Pluggable Candidate Adapter

- **License:** `Apache-2.0`
- **Provenance Tier:** `Signed Provenance · Self-Checked` (`BLAKE3` + `Ed25519` offline-verifiable receipt; never self-labeled `"Verified"`)
- **Research Scope:** Shot on Goal #1 — A fixed, SHA-256 pre-committed, hardware-energy-metered benchmark suite (`N = 1,500` held-out instances across 3 task strata) that forces neural or agentic candidates to compete directly against **all five classical automation baselines** (`lookup_table`, `if_else_guards`, `bounded_for_loop`, `decision_tree`, `compiled_solver_rules`) on `Joules-per-Correct-Operation`.

---

## 1. 1-Command Reproduction & External Model Adapter

Run the full self-contained suite (requires `python3 >= 3.10` stdlib-only and `cc` / `gcc` / `clang`):

```bash
./kits/deterministic-null-suite/run_kit.sh
```

Benchmark **your own LLM, script, or agent** against all 5 classical control arms in one command:

```bash
# Local command reading JSONL instances on stdin and emitting {"id": ..., "prediction": ...} JSONL:
python3 kits/deterministic-null-suite/dnull_suite/suite_runner.py --candidate-cmd "python3 my_candidate.py"

# Or any OpenAI-compatible HTTP endpoint:
python3 kits/deterministic-null-suite/dnull_suite/suite_runner.py   --openai-compatible-url http://localhost:8000/v1/chat/completions --model my-model
```

---

## 2. Three Held-Out Strata (`N = 1,500`) & Five Classical Control Arms

1. **Stratum A (`bounded_api_dispatch`, `500` instances):** Enterprise schema, auth, quota, idempotency, and SLO routing (`8` classes) — classical `if/else` and rule-scan saturate `100%` accuracy at sub-microjoule cost.
2. **Stratum B (`combinatorial_constraint_3sat`, `500` instances):** 16-variable, 48-clause `3-SAT` feasibility + witness check — shallow heuristics and feed-forward nets stall (`~64–74%`), while `arm5_compiled_solver_rules` (`DPLL` + unit propagation) achieves `100%` (`0` neural FLOPs).
3. **Stratum C (`open_compositional_patch_triage`, `500` instances):** 32-feature AST/log defect localization with an unseen oblique multi-feature tail — isolating the genuine positive `ΔAcc` regime where learned representations outperform shallow classical rules, alongside exact McNemar two-sided `p`-values and marginal joule cost.

---

## 3. Energy Orthogonality (`measured_j ⊥ reported_j ⊥ est_j ⊥ unmetered`)

- Dynamically meters physical DC current shunts (`TI INA260 SOM_5V_DC` on `AMD Kria KV260`; `TI INA3221 VDD_CPU_SOC_MSS` + `TI INA238 VIN` on `NVIDIA Jetson AGX Thor`) as **`measured_j`**, rootless Linux `powercap` RAPL as **`reported_j`**, and unprivileged hosts as **`unmetered`**.
- Multi-substrate receipts live in [`results/multi_substrate_receipts.json`](./results/multi_substrate_receipts.json) and [`RESULTS.md`](./RESULTS.md).
