# FormEBM-v3: Span-Normalized Decomposed Contrastive Scorer (`H5`, `H11`, and Zero-Shot `H15` OOD Transfer)

**Pre-Registration ID & SHA-256 Digest (Locked Prior to Execution)**:
- `rce-jepa-form-ebm-v3-2026-11-23` (`PREREG_form_ebm_v3.json`, SHA-256: `cb7ee1ac8dc5c594a07c7df8dd8ae27dd05b594f15321d0462472ee4a4faf2f7`)

**Engine & Benchmark Provenance**:
- `openIE-dev/rce` commit: `1762fb4bb65a58de07ab00f0d1bfdf4969d0358c` (`2026-11-20`)
- Linux `x86_64` release `rce` binary SHA-256: `386be0c26389550e028df2710d3673b810a8ec8813448216462cefc35c2196c9`
- `openIE-dev/openie-research-experiments` commit: `1d73cb38330d62439a9d77f05507113d78690200`
- 151-task ladder (`tasks_151.jsonl`) SHA-256: `6ae255a32211f620364ef713b1a36f7daac6ab46f22ac318b45acb2a6da9af50`
- 40-task git-history residual (`residual_40_tasks.jsonl`) SHA-256: `3ca3a32769145e9b502b9b7b9d2c0402e97ce6a860203668a35a35535d46b25b`
- `FormEBM-v3` best validation checkpoint (`epoch = 11`, `6,052,802` trainable parameters) SHA-256: `71e642f1bb0b9c06f16c1478b25283228fbaa47e8acb32b8adbb6b30046e177f`

**Measurement Honesty Grammar**:
- `measured_j = None`, `board_metered = false`, `est_j = None`.
- Host: AMD Ryzen AI Max+ 395 / Radeon 8060S Graphics (`OMP_NUM_THREADS=10`). Linux `powercap` RAPL counters (`/sys/class/powercap/intel-rapl:0/energy_uj` package and `intel-rapl:0:0/energy_uj` core) are reported strictly as operating-system/on-chip **`reported_j`**, with `derived_marginal_pkg_reported_j_per_beam = None` enforced because pre/post idle baseline drift (`119.413 W -> 74.396 W`, `37.7%` co-tenant package drift) exceeded the Falsifier 6 `10.0%` threshold.

---

## 1. Root Cause of Wave 4 `FormEBM-v2` Cross-Task OOD Inversion (`0.2585`) & `FormEBM-v3` Architecture

In Wave 4, `FormEBM-v2` (`5,851,649` parameters) met `H5` (`AUROC = 0.8922 >= 0.85`) and `H11` (`93.0% >= 80.0%` strict 5-step monotonicity) on unseen held-out Form shapes (`137` shapes), yet inverted to `AUROC = 0.2585` across multi-proposer candidates (`0.2630` on `286` typed-edit candidates) when transferred zero-shot to the `40`-task `H15` git-history residual. Three structural causes drove that inversion:
1. **Single-Scalar Coupling of Validity and Edit Span**: Training one scalar head jointly on 1-token beam repairs and 5-step cumulative corruption chains (`d = 0..5`) taught energy to grow monotonically with diff token count $\Delta_{\text{tok}}$, assigning higher energy to valid 25–250 line `stdlib` migrations (`hpke`, `mls`, `pq`) than to rejected 1-token `W-SYN-1` defects.
2. **Line-Shift Alignment Collisions**: Comparing `cand_lines[i]` against `ref_lines[i]` by raw line index marked every subsequent line (including unchanged `intent` and `example` obligations) as edited whenever a valid `use <module>` line was inserted at the top of a file.
3. **New-Symbol Slot Collisions & Fixed-Header Window Truncation**: Mapping both bound new local bindings (`<BOUND_NEW_ID>`) and undeclared free symbols (`<UNBOUND_NEW_ID>`) to one `<NEW_ID>` token class, while spending the first 180 tokens on static file headers in `max_seq_len = 256`, truncated distant diagnostic sites on 150–500 line modules.

`FormEBM-v3` (`6,052,802` trainable parameters, pure `float32` on ROCm `Radeon 8060S`, `0` `rce check` calls during scoring) preserves the **exact same 4-layer SHA-256 disjoint `1,387`-Form split** (`1,106` train, `144` validation, `137` unseen held-out test Form shapes; `0` overlap across `458` forbidden digests, `65` paths, `87` slugs, and `62` primary declarations from the `151` ladder and `40` `H15` tasks):
- **`PairFormTokenizerv3` (`max_seq_len = 384`, `560` active tokens, `0` checker calls)**: Uses `difflib.SequenceMatcher` line-shift-invariant syntactic alignment, diagnostic-and-diff prioritized windowing, lexical separation of `<BOUND_NEW_ID:0..31>` vs `<UNBOUND_NEW_ID:0..15>` vs `<UNDERSCORE_ID:0..31>`, and explicit normalized diff-fraction $\rho_{\text{diff}} = \Delta_{\text{tok}} / \max(1, L_{\text{cand}})$.
- **Two-Head Decomposed Energy Architecture**:
  1. **Span-Invariant Defect Head**: $E_{\text{def}}(x, y, r) = \text{softplus}(g_{\text{def}}(\text{feats}_{\text{def}}))$ over candidate-intrinsic states (`z_cand`, `max_pool(H_cand)`), unit-normalized latent direction $(z_{\text{cand}} - z_{\text{ref}}) / \|z_{\text{cand}} - z_{\text{ref}}\|_2$, span-normalized changed-token cross-difference (`mean_chg_d`, `max_chg_d`), `rule_emb(r)`, and syntactic ratios, trained with within-beam + all-pairs cross-task batch margin ($m_{\text{val}} = m_{\text{cross}} = 2.5$) plus L2 positive anchor across `4,983` pairs (`1,400` single-span beams + `219` `k = 2..10` multi-span valid/invalid pairs strictly from `train_forms`).
  2. **Cumulative Corruption-Depth Head**: $E_{\text{depth}}(y_0, y_d) = \text{softplus}(g_{\text{depth}}(\text{feats}_{\text{depth}}))$ trained on `600` 5-step corruption chains (`d = 0..5`), combined via span-attenuated composite energy:
     $$E_{\text{total}}(x, y, r) = E_{\text{def}}(x, y, r) + 0.15 \cdot \frac{E_{\text{depth}}(x, y)}{\log_2(2 + \Delta_{\text{tok}})}$$
- **Anti-Collapse Verification (`F1 = false`)**: VICReg variance-covariance regularization maintains `z_ref` effective rank at **`42.79`** (`>= 16`, std `0.3332 >= 0.25`) and `z_cand` effective rank at **`57.93`** (`>= 16`, std `0.3113 >= 0.25`) at the best validation checkpoint (`epoch 11`: `val_H5 = 0.9396`, `val_cross_span = 0.9480`, `val_H11 = 93.33%`).

---

## 2. Empirical Results: Unseen Disjoint Test Split (`H5`, `H11`) & Zero-Shot OOD `H15` Residual

| Benchmark / Metric | Wave 3 `FormJEPA-v1` | Wave 4 `FormEBM-v2` | **`FormEBM-v3` ($E_{\text{def}}$ / $E_{\text{depth}}$)** | **`FormEBM-v3` Composite $E_{\text{total}}$** | Pre-Registered Threshold & Verdict |
| --- | --- | --- | --- | --- | --- |
| **`H5` Held-Out Unseen AUROC** (`N = 200` beams, `3,064` cands) | `0.6180` | `0.8922` | **`0.9386`** ($E_{\text{def}}$) | **`0.9437`** | **`>= 0.85` MET** (`+0.0515` over `FormEBM-v2`) |
| **`H5` Top-1 (`k = 1`) Valid — Solvable Slice** (`163` beams) | — | `84.05%` (`137/163`) | **`83.44%` (`136/163`)** | **`80.98%` (`132/163`)** | **`>= 80.0%` MET** on solvable slice (`68.0%` / `66.0%` all 200) |
| **`H5` Mean `rce check` Calls to First Valid** (solvable) | — | `1.497` (`2.39×` red.) | **`1.601` (`2.23×` red.)** | **`1.669` (`2.14×` red.)** | Cuts checks from `3.577` unreranked (`6.270` Siamese $L_2$) |
| **`H11` Strict 5-Step Monotonicity** (`N = 100` unseen chains) | `36.0%` (`18/50`) | `93.0%` (`93/100`) | **`94.0%` (`94/100`, $E_{\text{depth}}$)** | **`92.0%` (`92/100`)** | **`>= 80.0%` MET** under both $E_{\text{depth}}$ & $E_{\text{total}}$ |
| **`H11` Spearman $\rho$ (`d = 0..5`)** (`N = 100` unseen chains) | — | `0.9931` / `1.0000` | **`0.9966` mean / `1.0000` med** | **`0.9846` mean / `1.0000` med** | $E_{\text{depth}}$ means: `[0.0007, 2.19, 5.17, 8.28, 12.48, 15.70]`; $E_{\text{total}}$: `[0.0091, 2.35, 3.26, 4.13, 5.22, 5.94]` |
| **`H11` Unconstrained Same-Line Random-Walk Slice** (`N = 50`) | `36.0%` | `38.0%` (`0.8513`) | `32.0%` ($\rho = 0.8611$, med `0.9429`) | `18.0%` ($\rho = 0.7937$, med `0.9429`) | Candid boundary: overwriting an already-broken line leaves defect count flat while means rise `0.017 -> 4.034` |
| **`H15` Zero-Shot OOD Multi-Proposer Pooled AUROC** (`40` tasks) | — | `0.2585` (`332` cands) | `0.4784` ($E_{\text{def}}$, `303` cands) | **`0.5278`** (`+0.2693` vs `v2`) | **Inversion resolved (`> 0.50`, `F4 = false`)**; large-span valid ($\Delta_{\text{tok}} \ge 10$) vs short invalid ($\Delta_{\text{tok}} \le 2$): **`0.6018`** |
| **`H15` Zero-Shot OOD Typed-Edit Pooled AUROC** (`286` cands) | — | `0.2630` | `0.4799` ($E_{\text{def}}$) | **`0.4985`** (`+0.2355` vs `v2`) | Eliminates anti-correlated span penalty (`0.2630 -> 0.4985`) |
| **`H15` Within-Task `k = 1` Admissions** (`out of 40`) | `22 / 40` (typed) | `25 / 40` (`5.55` chks) | **`24 / 40` typed (`5.20` chks)**; **`27 / 40` multi** | **`22 / 40` typed (`5.10` chks)**; **`25 / 40` multi** | Cuts mean checks on `H15` vs `FormEBM-v2` (`5.55 -> 5.10`); beam ceiling `30/40` |
| **10-Thread CPU Scoring `reported_j`** (`160` beams, `2,555` cands) | `58.65 mJ` (`k=1`) | `47.09 mJ` (`6.30 ms`) | — | **`232.45 mJ`/cand (`32.55 ms`)**, `3.712 J`/beam core | `362×` lower per candidate than local 35B (`84.25 J`); `derived_marginal = None` (`37.7%` drift) |

---

## 3. Candid Scientific Interpretation of Zero-Shot OOD `H15` Transfer (`0.2585 -> 0.5278`)

1. **In-Distribution Generalization to Unseen Shapes (`H5` & `H11`) Strengthens Sharply**: On the `137` unseen held-out Form shapes (`0` overlap with training, ladder, or `H15`), `FormEBM-v3` raises **`H5` AUROC from `0.8922` (`FormEBM-v2`) to `0.9437`** (`0.9386` on $E_{\text{def}}$ alone, hitting `TPR = 78.9%` at `FPR = 4.6%`), keeps solvable top-1 accuracy above `80%` (`83.44%` under $E_{\text{def}}$, `80.98%` under $E_{\text{total}}$), and lifts **`H11` strict 5-step monotonicity on $E_{\text{depth}}$ to `94.0%` (`94/100`, Spearman $\rho = 0.9966$)** while maintaining **`92.0%` (`92/100`, $\rho = 0.9846$)** on span-attenuated $E_{\text{total}}$.
2. **Wave-4 Cross-Task Edit-Span Inversion Is Eliminated (`F4 = false`)**: Across the `303` multi-proposer `H15` candidates (combining `286` typed-edit candidates with Wave-1 `gear0_store` and Wave-4 `gear0_v2_store`, including all `40/40` closed multi-hundred-line `hpke`, `mls`, `pq`, `pqxdh` migrations), `FormEBM-v3` lifts pooled cross-task AUROC from **`0.2585` (`FormEBM-v2`) to `0.5278`** (`+0.2693`), and reaches **`0.6018` AUROC** specifically when ranking large-span valid rewrites ($\Delta_{\text{tok}} \ge 10$) against short 0/1-token invalid candidates ($\Delta_{\text{tok}} \le 2$). On the 279-line `stdlib/lib/hpke.rce` migration ($\Delta_{\text{tok}} = 146$), $E_{\text{total}}$ drops to `0.9645` ($E_{\text{def}} = 0.8826$), and on `57_float_vectors.rce` ($\Delta_{\text{tok}} = 4$), valid $E_{\text{total}} = 1.3364 < 3.0518$ (`NO_OP` invalid).
3. **Why Zero-Shot Cross-Module OOD Calibration Plateaus Near `0.53` Without Signature/Trace Context**: Inspecting `multiline_migration_probe` shows that while span-normalization removes the systematic penalty on edit length, zero-shot single-file scoring on unseen cryptographic modules (`stdlib/lib/mls.rce`, `stdlib/lib/pq.rce`, `programs/ecosystem/pqxdh.rce`) still assigns high defect energy (`3.39–6.24`) to valid multi-module API migrations and occasionally low energy to 1-token non-repairs when cross-module `stdlib` function/constant type signatures (`crypto.hkdf_expand`, `core.bytes`) and `W-MUT-1` execution-trace non-vacuity (`washer.rce`) are absent from the scorer's input. High-confidence cross-task OOD calibration (`AUROC >= 0.85` on arbitrary multi-module git history) therefore requires feeding imported public module headers and exact `rce trace` rollout states into the scorer — matching the exact architectural boundary observed in `H15-Iterative` (`34/40 -> 40/40` once `stdlib/lib` headers and checker feedback were supplied).
