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

---

## 4. Real Pretrained Open-Weight Transformer (`Qwen2.5-0.5B-Instruct`) + Verified Crystallization

To evaluate a real pretrained 24-layer Transformer LLM (`Qwen/Qwen2.5-0.5B-Instruct-GGUF` `Q4_K_M`, `494M` parameters, `SHA-256 = 74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db`, greedy `temperature = 0.0`, `top_k = 1`, `seed = 20261126`, `cache_prompt = false`) head-to-head against all 5 classical control arms AND a 3-stage **Verified Downward Crystallization (`t = 1 -> t = 2` & `300`-query `Zipf(0.85)` live stream)** on the `SHA-256`-pinned confirmatory subset (`N = 90`, `30` per stratum, `SHA-256 = e9115baa0110448ce273ef951eeab4b3d927ad526087e75f00fae94092f27844`):

```bash
python3 kits/deterministic-null-suite/real_llm_eval.py \
  --llama-server-bin /path/to/llama-server \
  --auto-download-gguf
```

- **Scope Note (per 25 Nov 2026 Review):** Stage-1 `<= 4 KiB` crystallized LUT hits measure exact content-addressed recall on recurring verified inputs (`C(x, z) == 1`), **not** unseen cold generalization; unseen structured/constraint arrivals route to Stage-2 classical rules/DPLL and unseen open compositional arrivals escalate to the live Transformer.
- **Committed Multi-Substrate Hardware Receipts (`measured_j` & `reported_j`):** [`results/real_llm_multi_substrate_receipts.json`](./results/real_llm_multi_substrate_receipts.json) and [`results/receipt_real_llm_crystallization.json`](./results/receipt_real_llm_crystallization.json) (see [`RESULTS.md`](./RESULTS.md) §4).
