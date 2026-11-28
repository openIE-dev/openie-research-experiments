# Kit 8: `spec-fidelity-barrier` — Architectural Information Barrier (`Spec ⊥ Impl`), AST Mutant/Vacuity Kill Gate & In-Loop Grammar/Type Token Masking

- **License:** `Apache-2.0`
- **Provenance Tier:** `Signed Provenance · Self-Checked` (`BLAKE3` + `Ed25519` offline-verifiable receipt; never self-labeled `"Verified"`)
- **Research Scope:** Track 2 — Resolving the **Specification Bottleneck (`Goodhart's Law` on $C(z) \in \{0,1\}$)** and **Post-Hoc Syntax/Type Token Waste** across a deterministic `40`-task systems benchmark (`1,000` test vectors, `200` implanted defective candidates, `200` programmatic AST mutants, and `1,000` seeded candidate token-stream draws).

---

## 1. 1-Command Reproduction

From the repository root (`python3 >= 3.10` stdlib-only; zero third-party packages or `BSL-1.1` dependencies):

```bash
./kits/spec-fidelity-barrier/run_kit.sh
```

Fast smoke test (`--quick`):

```bash
./kits/spec-fidelity-barrier/run_kit.sh --quick
```

Run unit, programmatic AST-mutant, grammar-mask, and receipt tamper tests directly:

```bash
python3 -m unittest discover -s kits/spec-fidelity-barrier/tests -p "test_*.py"
```

---

## 2. Deterministic 40-Task Suite & 4 Progressive Gate Architectures

Evaluates `40` real systems tasks across **6 canonical domains** (`ring_buffers`, `saturating_ledgers`, `interval_schedules`, `capability_acls`, `parser_state_machines`, and `sorting_invariants`):

1. **Arm A (`shared_context_naive` — Goodhart Baseline):** Spec and candidate share context; tautological specs checking return type/shape or echoing candidate constants falsely admit defective implementations (`false_accept > 0`).
2. **Arm B (`isolated_spec_only` — `Spec ⊥ Impl` Without Mutant Auditing):** Context-isolated partial relational specs eliminate constant-echoing tautologies, yet still admit subtle boundary, conservation, deduplication, and tie-stability defects (`false_accept > 0`).
3. **Arm C (`mutant_vacuity_barrier` — `Spec ⊥ Impl` + Automated AST Mutant/Vacuity Kill Gate):** Synthesizes `5` programmatic AST mutants per task (`M1_zero_constant_stub`, `M2_boundary_off_by_one`, `M3_sign_or_bitop_flip`, `M4_branch_drop`, `M5_invariant_bypass` = `200` total AST mutants) via `ast.NodeTransformer` and **refuses the spec itself (`SPEC_VACUOUS_REFUSED`) unless it kills `100%` of mutants** before gating candidates. Reports exact two-sided and one-sided 95% Clopper–Pearson confidence intervals.
4. **Arm D (`grammar_mask_plus_mutant_gate` — In-Loop Earley/Pushdown CFG+Type Token Mask + Arm C Gate):** Pairs a deterministic 32-token typed pushdown/Earley token masker (`1,000` seeded candidate draws) with the Arm C semantic commit gate, eliminating `100%` of post-hoc syntax/type token waste while metering host CPU latency and rootless Linux `powercap` RAPL `reported_j` (`measured_j ⊥ reported_j ⊥ est_j ⊥ unmetered`).

Committed empirical artifacts: [`results/spec_fidelity_receipt.json`](./results/spec_fidelity_receipt.json) and [`RESULTS.md`](./RESULTS.md).
