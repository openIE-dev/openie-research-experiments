# FormEBM-v2 Contrastive Latent Energy Scorer (`H5` / `H11`) & `H15-Iterative` Bounded Residual Closure

**Pre-Registration IDs & SHA-256 Digests (Locked Prior to Execution)**:
- Deliverable A (`FormEBM-v2`): `rce-jepa-form-ebm-v2-2026-11-23` (`PREREG_form_ebm_v2.json`, SHA-256: `128f17e69361ea891b3f8625fdee949a18ba43e85dc0d02c691d569c2da53256`)
- Deliverable B (`H15-Iterative`): `rce-jepa-h15-iterative-2026-11-23` (`PREREG_h15_iterative.json`, SHA-256: `a7774d3bd03ae4507a0a2c4856cb5ad1f29f15791ecd96e55b2f3207b290bc8b`)

**Engine & Benchmark Provenance**:
- `openIE-dev/rce` commit: `1762fb4bb65a58de07ab00f0d1bfdf4969d0358c` (`2026-11-20`)
- Linux `x86_64` release `rce` binary SHA-256: `331464496009d98ad8f55095aa4c26f7266ae49ce602d3cba2c74f185e766df9`
- `rce rules` SHA-256: `7a8bdcbe7525fe25b285ddd03eadcbb91e6854f19daa7853bd2d49c39a12c247`
- `openIE-dev/openie-research-experiments` commit: `1d73cb38330d62439a9d77f05507113d78690200`
- 40-task residual benchmark (`residual_40.jsonl`) SHA-256: `3ca3a32769145e9b502b9b7b9d2c0402e97ce6a860203668a35a35535d46b25b`

**Measurement Honesty Grammar**:
- `measured_j = None`, `board_metered = false`, `est_j = None`.
- Local AMD Ryzen AI Max+ 395 / Radeon 8060S APU Linux `powercap` RAPL counters (`/sys/class/powercap/intel-rapl:0/energy_uj` package and `intel-rapl:0:0/energy_uj` core) are reported strictly as operating-system/on-chip **`reported_j`**, with `derived_marginal_pkg_reported_j = None` enforced whenever pre/post idle baseline drift exceeds the Falsifier 6 `10.0%` threshold (`13.7%` observed during the CPU scoring microbenchmark).
- Closed-API remote cloud server energy (`Anthropic`, `xAI`) is reported strictly as **`not_available`**.

---

## 1. Deliverable A: `FormEBM-v2` Contrastive + Multi-Step Margin Scalar Energy Scorer (`H5` & `H11`)

### 1.1 Root-Cause Diagnosis of Wave 3 `FormJEPA-v1` (`H5 = 0.618`, `H11 = 36.0%`) & `FormEBM-v2` Design
In Wave 3, `FormJEPA-v1` (`8.42M` trainable parameters) achieved `88.5%` synthetic repair (`177/200`) and `27/40` (`67.5%`) on `H15` via its latent-conditioned typed edit decoder, yet its uncalibrated coordinate Smooth-$L_1$ distance $\|\hat{z}_y - E_{\text{ema}}(y_{\text{cand}})\|_2^2$ reached only `AUROC = 0.618` on `H5` and `36.0%` strict 5-step monotonicity on `H11`. Two structural causes accounted for this gap:
1. **Tokenizer Quotient Collisions**: `FormJEPA-v1`'s `FormSExprTokenizer` mapped both `let foo` (`W-UNUSED-1` failure) and `let _foo` (valid hygiene) to the same `<ID:k>` token, collapsed integer literals `>= 17` into `<INT_SMALL>`, and indexed `local_map` independently per file so an unbound identifier on line $k$ shifted `<ID:j>` slots across all subsequent lines.
2. **No Contrastive Validity or Edit-Depth Margin**: Coordinate Smooth-$L_1$ + VICReg prediction never explicitly separated `rce check`-valid candidates from subtle near-miss negatives or ordered cumulative AST defect depths $d = 0..5$.

`FormEBM-v2` (`5,851,649` trainable parameters, checkpoint SHA-256 `2204a0b9cbd0d96cc5acd7fb725063181f00a0c49ec8e83a43ae23fb6c5341c1`) fixes both over the **exact same strictly disjoint `1,387`-Form split** (`1,106` train, `144` validation, `137` unseen held-out test Form shapes; `0` cryptographic overlap across `458` forbidden hashes, `65` paths, `87` slugs, and `62` primary declarations from the `151` ladder and `40` `H15` tasks):
- **`PairFormTokenizer` (`max_seq_len = 256`, `504` active tokens, `0` checker calls at inference)**: Anchors `local_map` on `ref_src` first (`<ID:0..63>` vs `<NEW_ID:0..15>` vs `<UNDERSCORE_ID:0..31>` plus `<NUM_MOD:0..31>`) and attaches purely syntactic surface diff tags (`0..7`).
- **Siamese Shared Encoder + Cross-Difference Attention + Softplus Energy Head**: A 5-layer shared Transformer (`d = 256`, `8` heads) encodes `ref` and `cand`, a 1-layer cross-attention difference block extracts mean and RMS token-level alignment residuals (`mean_d`, `rms_diff`), and a LayerNorm-GELU MLP outputs $E_\omega(x, y_{\text{cand}}) = \text{softplus}(\cdot) \in \mathbb{R}_{\ge 0}$.
- **Joint Objective (Strictly on `1,106` Training Forms)**:
  1. Contrastive validity margin ($m_{\text{val}} = 1.0$) over `5,955` `(broken, valid, invalid)` triples from `1,400` training beams;
  2. All-pairs 5-step edit-depth ranking margin ($\gamma = 0.50(j - i)$ for $0 \le i < j \le 5$) + $0.10 E(y^{(0)}, y^{(0)})^2$ anchor over `600` training 5-step cumulative corruption chains; and
  3. VICReg variance-covariance anti-collapse regularization (raising `z_ref` effective rank from `26.48` at epoch 0 to **`55.70`** at best checkpoint and `z_cand` effective rank from `46.44` to **`74.72`**, coordinate std `0.1012 -> 0.2817` and `0.0592 -> 0.3272`; Falsifier F1 triggered: `false`).

### 1.2 Held-Out Unseen Test Results (`137` Unseen Test Form Shapes) & Out-of-Distribution `H15` Audit

| Benchmark / Metric | Wave 3 `FormJEPA-v1` (Uncalibrated $L_2$) | `FormEBM-v2` Siamese $L_2$ Baseline | **`FormEBM-v2` Scalar Energy $E_\omega$** | Pre-Registered Threshold & Verdict |
| --- | --- | --- | --- | --- |
| **`H5` Held-Out AUROC** (`N = 200` unseen beams, `3,064` cands) | `0.6180` | `0.7208` | **`0.8922`** | **`>= 0.85` MET** (in-distribution unseen Form shapes) |
| **`H5` Top-1 (`k = 1`) Valid — Solvable Slice** (`163` beams) | — | `30.67%` (`50/163`) | **`84.05%` (`137/163`)** | `3.04×` over unreranked (`45/200 = 22.5%`) |
| **`H5` Top-1 (`k = 1`) Valid — All `200` Beams** (incl. `37` unsolvable) | — | `25.00%` (`50/200`) | **`68.50%` (`137/200`)** | Bounded by 16-item proposer ceiling (`163/200 = 81.5%`) |
| **`H5` Mean `rce check` Calls to First Valid** (solvable) | — | `4.325` | **`1.497`** (`2.39×` fewer vs `3.577` unreranked) | Cuts total checks over `200` beams from `5.235` to `3.540` |
| **`H11` Strict 5-Step Monotonicity** (`N = 100` unseen chains) | `36.0%` (`18/50`) | `18.0%` (`18/100`) | **`93.0%` (`93/100`)** | **`>= 80.0%` MET** (`E_0 < E_1 < E_2 < E_3 < E_4 < E_5`) |
| **`H11` Spearman $\rho$ with Edit Depth `d = 0..5`** | — | `0.8411` (mean) | **`0.9931` mean / `1.0000` median** | Mean $E_{0..5}$: `[0.0007, 2.36, 5.16, 7.99, 12.21, 17.25]` |
| **`H11` Unconstrained Same-Line Random-Walk Slice** (`N = 50`) | `36.0%` | `26.0%` | `38.0%` strict (`46.0%` non-dec, mean $\rho = 0.8513$, median `0.9429`) | Candid boundary: overwriting an already-broken line leaves true defect count flat (`E_{0..5}` means still rise `[0.0007, 2.27, 3.99, 5.37, 6.14, 7.07]`) |
| **`H15` Out-of-Distribution 40-Task Residual (`k = 1` Typed Rerank)** | `22 / 40` (`55.0%`) | — | **`25 / 40` (`62.5%`)** (beam `30/40`, `5.55` mean checks vs `4.925` rule-order) | `+3` tasks over `FormJEPA-v1` `k = 1`; pooled cross-task AUROC drops to `0.2630` (`0.2585` on 332 multi-proposer cands) |
| **10-Thread CPU Scoring `reported_j`** (`160` beams, `2,555` cands) | `58.65 mJ` (`k=1`) / `474.76 mJ` (`k=16`) | — | **`47.09 mJ`/cand (`6.30 ms`)**, `752.03 mJ`/beam core (`11.88 J` gross pkg) | `1,789×` lower per candidate than local 35B (`84.25 J`); `derived_marginal_pkg_reported_j = None` (`13.7%` idle drift) |

**Scientific Candor on `FormEBM-v2` Domain Boundary**:
On unseen held-out test Form shapes (`137` shapes, `0` training overlap), replacing uncalibrated coordinate distance with `FormEBM-v2`'s contrastive + multi-step edit-depth margin head lifts **`H5` AUROC from `0.6180` to `0.8922` (`>= 0.85`)**, lifts solvable top-1 valid selection without beam checking to **`84.05%` (`137/163`; `68.50%` across all `200` beams)** while cutting `rce check` calls by **`2.39×` (`3.577 -> 1.497`)**, and lifts **`H11` strict 5-step monotonicity on cumulative 1..5-defect chains from `36.0%` to `93.0%` (`>= 80%`, mean Spearman $\rho = 0.9931$)**. At the same time, two explicit boundaries hold:
1. When 5-step mutations are unconstrained random walks that may mutate an already-defective line a second time without increasing true AST defect count, mean energy still rises strictly (`0.0007 -> 7.0687`, median $\rho = 0.9429$), while per-chain strict inequality is `38.0%`.
2. When transferred zero-shot to the out-of-distribution `40`-task `H15` git-history residual, `FormEBM-v2` improves `k = 1` within-task typed-edit admissions over `FormJEPA-v1` (`22/40 -> 25/40`), but its pooled cross-task AUROC (`0.2630` typed, `0.2585` multi-proposer) inverts because the single-line edit-depth margin assigns higher raw energy to valid *multi-line* stdlib migrations (`hpke`, `mls`, `pq`, `washer`) than to rejected 1-token `W-SYN-1` edits. Scaling calibrated energy ranking to multi-line git-history synthesis requires multi-line trajectory training and trace-rollout terms.

---

## 2. Deliverable B: Closing `40 / 40` Residual Tasks (`H15-Iterative` + `DNULLMM1` Gear-0 v2)

### 2.1 Protocol & Zero-Leakage Guarantee
Wave 1 single-shot proposers (`k = 1`, zero compiler feedback, and no actual `stdlib/lib` signature headers) peaked at `34 / 40` (`85.0%`), missing `6` tasks: four multi-module cryptographic stdlib migrations (`stdlib/lib/hpke.rce`, `stdlib/lib/mls.rce`, `stdlib/lib/pq.rce`, `programs/ecosystem/pqxdh.rce` at `a828e934`) and two pre-`W-MUT-1` vacuous-example obligations (`spec/examples/57_float_vectors.rce@b2b932da`, `programs/multi/washer.rce@2cc82de7`).

Under `PREREG_h15_iterative.json` (`max_turns = 5`), each proposer received **ONLY**:
1. `task["mutant"]` (with `task["original"]` stripped before `run_single_episode`),
2. Public declaration headers (`pub const`, `pub struct`, `pub kind`, `pub fn` signatures with function bodies stripped, strictly excluding `task["path"]` itself!) of `stdlib/lib/*.rce` modules imported via `use ...` at `openIE-dev/rce` `1762fb4b` (exposing real exports such as `crypto.cat`, `crypto.unhex`, `crypto.tohex`, `crypto.MASK`), and
3. Verbatim deterministic `rce check` + `no_spec_deletion` + `W-MUT-1` diagnostics after each rejected turn.

### 2.2 Aggregate `H15-Iterative` Results Across `40` Residual Tasks

| Arm | Model | Wave 1 Single-Shot (`k=1`) | Turn-1 (`t=1`) w/ Stdlib Headers | **Iterative Admitted (`<=5` turns)** | `restored` + `behaviour-equal` | `contradicts` | Total API Calls | Tokens (In / Out / Think) | Total Cost (USD) | Server Energy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `iter_claude_opus_5_5` | `claude-opus-5-5` | `34 / 40` (`85.0%`) | `38 / 40` (`95.0%`) | **`40 / 40` (`100.0%`)** | `39` (`34 + 5`, `1` fuel-undecided) | **`0`** | `42` (`38@t1, 2@t2`) | `133,527 / 45,711 / 16,572` | `$1.8104` | `not_available` |
| `iter_claude_sonnet_5_5` | `claude-sonnet-5-5` | `32 / 40` (`80.0%`) | `38 / 40` (`95.0%`) | **`40 / 40` (`100.0%`)** | `39` (`35 + 4`, `1` fuel-undecided) | **`0`** | `43` (`38@t1, 1@t2, 1@t3`) | `137,385 / 46,668 / 17,846` | **`$1.1122`** | `not_available` |
| `iter_xai_grok_4_20_reasoning` | `xai:grok-4.20-0309-reasoning` | `31 / 40` (`77.5%`) | `35 / 40` (`87.5%`) | **`39 / 40` (`97.5%`)** | `37` (`30 + 7`, `2` fuel-undecided) | **`0`** | `50` (`35@t1, 2@t2, 2@t3`) | `269,930 / 28,903 / 341,027` | `$4.0555` | `not_available` |
| **Warm Gear-0 v2 (`t = 2` Replay)** | **`DNULLMM1` (`40` records)** | `34 / 40` (`v1`) | — | **`40 / 40` (`100.0%`)** | `39` (`34 + 5`) | **`0`** | **`0`** | `0 / 0 / 0` | **`$0.0000`** | `1.771 µJ` / `0.325 µs` probe |

### 2.3 Exact Breakdown of All 6 Previously Unsolved Residual Tasks

| Previously Unsolved Task ID | Root Blocker in Wave 1 (`k = 1`) | `Claude Opus 5.5` | `Claude Sonnet 5.5` | `xAI Grok 4.20 Reasoning` | Post-Hoc `rce hash` / `rce equiv` vs `ORIGINAL` |
| --- | --- | --- | --- | --- | --- |
| `stdlib/lib/hpke.rce@a828e934` | Missing `crypto` + `core.bytes` public headers | **Closed Turn 1** (`$0.1627`) | **Closed Turn 1** (`$0.0941`) | **Closed Turn 1** (`$0.1764`) | **`restored`** (`rce hash` exact match on all 3) |
| `stdlib/lib/mls.rce@a828e934` | Missing `crypto` + `core.bytes` public headers | **Closed Turn 1** (`$0.1171`) | **Closed Turn 1** (`$0.0667`) | **Closed Turn 1** (`$0.1493`) | **`restored`** (`rce hash` exact match on all 3) |
| `stdlib/lib/pq.rce@a828e934` | Missing `crypto` + `core.bytes` public headers + 220-line module | **Closed Turn 1** (`$0.2261`) | **Closed Turn 1** (`$0.1436`) | **Closed Turn 2** (`$0.3080`) | **`restored`** (`rce hash` exact match on all 3) |
| `programs/ecosystem/pqxdh.rce@a828e934` | Missing `pq` + `crypto` + `core.bytes` headers | **Closed Turn 1** (`$0.0689`) | **Closed Turn 1** (`$0.0417`) | **Closed Turn 3** (`$0.2894`) | **`restored`** (`rce hash` exact match on all 3) |
| `spec/examples/57_float_vectors.rce@b2b932da` | Historical original predates `W-MUT-1` vacuous-example check | **Closed Turn 2** (`$0.1411`) | **Closed Turn 2** (`$0.0659`) | **Closed Turn 1** (`$0.1521`) | **`behaviour-equal`** (`rce equiv` exit `0` on all 3) |
| `programs/multi/washer.rce@2cc82de7` | Historical original predates `W-MUT-1` vacuous-example check | **Closed Turn 2** (`$0.1359`) | **Closed Turn 3** (`$0.1696`) | Open after 5 turns (`$0.5718`, `W-MUT-1` line 6) | **`behaviour-equal`** (`Opus 5.5` & `Sonnet 5.5`, `0` contradictions) |

### 2.4 Warm `DNULLMM1` Gear-0 (`40 / 40`) & Updated 3-Gear `Zipf(0.85)` Cascade (`200 / 200`)
- **Full `40 / 40` Gear-0 Crystallization (`gear0_v2_store.jsonl`, SHA-256 `80cf265038bcd5ebd74a2e02c1d71e7185e7ce8475c586bcdaeb417987704046`)**: Re-querying all `40` residual tasks at `t = 2` against the memory-mapped `DNULLMM1` store hits **`40 / 40` (`100.0%`)** and re-admits **`40 / 40`** under `rce check` + `no_spec_deletion` at **`0` model calls** (`$0.0000`, `0.3246 µs` / `1.771 µJ` Apple M5 Max reference probe latency/energy).
- **Updated 3-Gear Cascade (`DNULLMM1` -> `FormJEPA-v1 k=16` -> `Opus 5.5 Iterative`, `Zipf(0.85)`, `M = 200` arrivals)**: Admits **`200 / 200` (`100.0%`)** of recurring stream arrivals (up from `184 / 200` in Wave 3), serving **`163` arrivals (`81.5%`) at Gear 0 (`0` calls)**, **`25` arrivals (`12.5%`) at local sub-joule Gear 1**, and waking Gear-2 frontier search on only **`12` episodes (`14` API turns, `$0.9822`, a `16.67×` episode reduction** vs `200` stateless frontier episodes).
