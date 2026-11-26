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

## 4. Oct 12 – Nov 26, 2026 Open-Weight SOTA LLM Panel + Verified Crystallization (`real_llm_eval.py`)

Benchmarks a **6-model open-weight SOTA panel released strictly within `2026-10-23` – `2026-11-24` (`2` to `34` days old at the `2026-11-26` freeze)** head-to-head against all 5 classical control arms AND a 3-stage **Verified Downward Crystallization (`t = 1 -> t = 2` & `300`-query `Zipf(0.85)` live stream)** via mainline `llama.cpp` (`commit 436d7e8`, CPU-only `-ngl 0`, `temperature = 0.0`, `seed = 20261126`, `cache_prompt = false`):

1. **`LiquidAI/LFM3-1.7B-GGUF`** (`LFM3-1.7B-Q4_K_M.gguf`, `2026-10-24`, `1.10 GB`, `gguf_arch = lfm3`)
2. **`LiquidAI/d1-2B-GGUF`** (`d1-2B-Q4_K_M.gguf`, `2026-10-27`, `1.10 GB`, `gguf_arch = lfm3`, `/v1/systemone` non-autoregressive System-1 decision head)
3. **`ggml-org/Qwen3.5-4B-GGUF`** (`Qwen3.5-4B-Q4_K_M.gguf`, `2026-11-12`, `3.03 GB`, `Apache-2.0`, `gguf_arch = qwen35`)
4. **`unsloth/NVIDIA-Nemotron-3.5-Bolt-E4B-GGUF`** (`NVIDIA-Nemotron-3.5-Bolt-E4B-UD-Q4_K_XL.gguf`, `2026-10-23`, `5.06 GB`, `gguf_arch = gemma4`)
5. **`unsloth/Inkling-2-Mini-GGUF`** (`Inkling-2-Mini-UD-IQ4_XS.gguf`, `2026-11-20`, `15.73 GB`, `Apache-2.0`, `gguf_arch = inkling2_loop`, Thinking Machines Lab `26.4B` total / `3.4B` active Looped Transformer MoE)
6. **`prism-ml/Ternary-Bonsai-2.5-27B-GGUF`** (`Ternary-Bonsai-2.5-27B-Q2_0.gguf`, `2026-11-24`, `7.67 GB`, `Apache-2.0`, `gguf_arch = qwen35`, native ternary `27B` in `Q2_0`)

```bash
python3 kits/deterministic-null-suite/real_llm_eval.py \
  --llama-server-bin /path/to/llama-server \
  --models-dir /path/to/gguf-models \
  --k-per-stratum 30 --k-overrides ternary_bonsai_2_5_27b=15 \
  --stream-teacher inkling_2_mini
```

- **Scope Note (per 25 Nov 2026 Review):** Stage-1 `<= 4 KiB` crystallized LUT hits measure exact content-addressed recall on recurring verified inputs (`C(x, z) == 1`), **not** unseen cold generalization; unseen structured/constraint arrivals route to Stage-2 classical rules/`DPLL` and unseen open compositional arrivals escalate to the live Stage-3 teacher.
- **Committed Multi-Substrate Hardware Receipts (`measured_j` & `reported_j`):** [`results/real_llm_multi_substrate_receipts.json`](./results/real_llm_multi_substrate_receipts.json) and [`results/receipt_real_llm_crystallization.json`](./results/receipt_real_llm_crystallization.json) (see [`RESULTS.md`](./RESULTS.md) §4).
