# `FormJEPA-v1` Latent Form Proposer & `rce repair` Rung `f` Evaluation (`openIE-dev/rce` `1762fb4b`)

- **Pre-registrations (pinned prior to dataset generation, training, and Rung `f` execution)**:
  - `PREREG_form_jepa_v1.json` (`sha256: 22682e6e936ec1205ca6b4285cfb8459aaf392a2ff656e3ef0b3393de9abc77e`)
  - `PREREG_rung_f.json` (`sha256: 04aff4b2b44cdbea1a96a3370a1cbe894c23f1792aab89c8daede46e56aef3be`)
  - Upstream `spec/proposals/repair-observe/criterion.json` (`2026-11-03`, `sha256: abf7f131f240e3f9eece8c2ed9d47cb1592c44ea3a99da20de092c899b104982`)
- **Engine & Gate**: `openIE-dev/rce` commit `1762fb4b` (`1762fb4bb65a58de07ab00f0d1bfdf4969d0358c`), Linux `x86_64` release binary `sha256: 5ef9931ff23a310f89fb34cd1b631ff6b6cd6acf1943da4fc712e6c80db599ed`, `openIE-dev/openie-research-experiments` commit `ce8003f`.
- **Energy Provenance**: Linux `powercap` `intel-rapl:0` (`package-0`) and `intel-rapl:0:0` (`core`) counters on `AMD Ryzen AI Max+ 395` (`$BENCH_ROOT`) are strictly recorded as `reported_j`; Apple M5 Max `L2`/`L3` `reported_j` baselines are cited from `rce/bench/h15-gear0/`; remote cloud API energy is `not_available`; `est_j = None`, `measured_j = None`, `board_metered = false`.

---

## 1. Deliverable A — `FormJEPA-v1`: Architecture, Zero-Leakage Corpus & Anti-Collapse Verification

### 1.1 Zero-Leakage Disjoint Corpus Construction
All candidate `.rce` Forms from `openIE-dev/rce` (`spec/examples`, `spec/examples-0.9/ok`, `stdlib/lib`, `book/listings`, `apps`, `programs`, `conformance/tests` standalone accept/run/trace cases) and `rce/bench/form-space/results/forms.jsonl` were filtered through four exclusion gates against all `151` ladder tasks (`sha256: 6ae255a3...`, `65` paths) and `40` `H15` residual tasks (`sha256: 3ca3a327...`, `40` paths):
1. Exact relative path exclusion (`65` forbidden paths),
2. Filename stem and numeric-stripped slug exclusion (`87` forbidden slugs, plus conformance `# provenance:` rejection),
3. Primary `state`, `actor`, and `module` declaration identifier exclusion (`62` forbidden identifiers), and
4. Cryptographic `rce fmt nameless` (`shape_hash`), canonical `rce fmt`, and raw UTF-8 SHA-256 exclusion across every `original`, `mutant`, and `HEAD` file (`458` forbidden digests).

- **Surviving disjoint valid Form shapes**: **`1,387`** (`0` cryptographic or structural overlap with evaluation tasks), partitioned deterministically by `shape_hash[:16] mod 10` into **`1,106` train shapes**, **`144` validation shapes**, and **`137` held-out test shapes**.
- **Checker-verified defect pairs**: **`6,329` training tuples**, **`500` validation tuples** (`sha256: 1502335d...`), and **`200` held-out synthetic test tuples** (`sha256: cdeac519...`) across `27` checker diagnostic codes (`W-TY-1`, `W-UNUSED-1`, `W-SYN-1`, `W-TY-3`, `W-INT-1`, `W-NAME-1`, `W-PAR-3`, `W-LEX-3`, `W-LEN-1`, `W-WORLD-1`, etc.) and `8` typed Form edit operators (`OP_CMP_SWAP`, `OP_CONST_BOUND`, `OP_ARITH_EXPR`, `OP_TYPE_ANNOT`, `OP_SCOPE_IDENT`, `OP_METHOD_CALL`, `OP_TOTALITY_KEEP`, `OP_CAP_WORLD`).

### 1.2 Architecture & Representation Non-Collapse (`F1` Falsifier Check)
- **Model (`FormJEPA-v1`, seed `20261122`)**:
  - **Context Encoder $E_\theta(x, r)$**: `6`-layer Pre-LN Transformer (`d = 256`, `8` heads, `ffn = 1024`) over quotient-normalized Form AST S-expression tokens + checker diagnostic rule token,
  - **EMA Target Encoder $E_{\bar\theta}(y)$**: `6`-layer exponential-moving-average encoder ($\tau = 0.996$, stop-gradient) over canonical `rce fmt nameless` valid Forms,
  - **Latent Predictor $P_\phi(z_x, e_r) \to \hat{z}_y$**: `3`-layer residual MLP (`320 -> 512 -> 512 -> 256`) trained with Smooth-$L_1$ loss plus **VICReg variance-covariance regularization** on $z_x$ and $\hat{z}_y$,
  - **Latent-Conditioned Edit/Span Decoder $D_\psi(H_x, z_x, \hat{z}_y)$ + Latent Energy Reranker**: `2`-layer FiLM + cross-attention decoder conditioned on $[z_x, \hat{z}_y, \hat{z}_y - z_x]$ emitting `(line_span, edit_op, operand)` candidates reranked by $\|\hat{z}_y - E_{\bar\theta}(y_{\text{cand}})\|_2^2 - 0.35 \log p_\psi(a \mid x, \hat{z}_y)$.
- **Parameter count**: **`8,424,073` trainable parameters** (`13,917,577` total including frozen-gradient EMA target buffers; checkpoint `55,753,947` bytes, `sha256: cbfbf2274175c73736f77da413039ccc381c13f6b251a636617afdaa8064e5ee`).
- **Training telemetry (`12` epochs, `batch_size = 192`)**: `3,082.88 s` wall clock, `23,063.33 J` RAPL core `reported_j` (`30,720.08 J` gross RAPL package `reported_j` on shared host). Validation exact `(line, op, arg)` edit accuracy rose from `54.6%` (epoch 1) to **`75.8%`** (epoch 10; `78.8%` line, `91.2%` op, `89.4%` operand at epoch 12).

| Metric on Held-Out Validation (`N = 500`) | Pre-Training (Epoch 0) | Post-Training (Best Checkpoint) | Falsifier `F1` Floor |
|---|---:|---:|---:|
| Effective rank $\operatorname{erank}(z_x)$ (`d = 256`) | `32.899` | **`85.241`** | `< 16.0` (not met) |
| Effective rank $\operatorname{erank}(z_y)$ (`d = 256`) | `38.754` | **`31.919`** | `< 16.0` (not met) |
| Effective rank $\operatorname{erank}(\hat{z}_y)$ (`d = 256`) | `21.636` | **`17.059`** | — |
| Mean per-coordinate std $\sigma(z_x)$ | `0.1038` | **`0.3830`** | `< 0.25` (not met) |
| Positive-pair latent $L_2$ energy $\|\hat{z}_y - z_y\|_2^2$ | `149.249` | **`10.572`** | — |
| Random-pair latent $L_2$ energy $\|\hat{z}_y - z_{y_{\text{rand}}}\|_2^2$ | `149.203` | **`13.020`** | — |

---

## 2. Deliverable A — Benchmark Evaluations & Energy Comparison

### 2.1 Inference `reported_j` Microbenchmark (Linux `intel-rapl`)
On `AMD Ryzen AI Max+ 395` (`OMP_NUM_THREADS = 8`), pure `FormJEPA-v1` CPU inference costs:
- **`k = 1` greedy**: `10.15 ms` / proposal, **`0.0586 J` (`58.65 mJ`) RAPL core `reported_j`** (`1.1937 J` gross RAPL package `reported_j`; co-tenant idle drift `33.38% > 10%` invalidates `derived_marginal_pkg_reported_j` to `None` under Falsifier 6, matching the discipline of `h15-gear0`; in an earlier low-drift window at `0.82% <= 10%` idle drift, `k = 1` measured `8.79 ms`, `71.78 mJ` RAPL core, `0.2745 J` derived marginal package, and `0.8884 J` gross package `reported_j`).
- **`k = 16` latent beam**: `67.51 ms` / proposal, **`0.4748 J` (`474.76 mJ`) RAPL core `reported_j`** (`6.7364 J` gross RAPL package `reported_j`).
- Against `Qwen 3.6 35B-A3B` (`84.247 J` per single-shot candidate on Apple M5 Max), `FormJEPA-v1` inference is **`70.6×` (`k = 1` gross pkg) to `1,436×` (`k = 1` RAPL core) lower in `reported_j` per proposal** (`12.5×` gross pkg / `177.5×` RAPL core at `k = 16`).

### 2.2 Benchmark 1: Held-Out Disjoint Synthetic Form Defects (`N = 200`, Unseen `shape_hash`es)
- **`FormJEPA-v1 (k = 1)` greedy**: **`156 / 200` (`78.0%`)** admitted by `rce check` + obligation preservation.
- **`FormJEPA-v1 (k = 16)` latent beam**: **`177 / 200` (`88.5%`)** admitted (`65/69` `type_mismatch`, `51/57` `scope_ident_defect`, `29/32` `guard_cmp_swap`, `23/24` `arith_op_swap`, `8/9` `unused_binding_hygiene`, `1/1` `guard_negation`, and `0/8` `const_off_by_one` where exact target constants require trace execution).
- **Honest `H5` & `H11` latent-geometry diagnostics**: Across `925` beam candidates on `60` held-out tasks (`100` accepted), uncalibrated negative latent $L_2$ distance $-\|\hat{z}_y - E_{\bar\theta}(y_{\text{cand}})\|_2^2$ achieves **AUROC `0.618`** (above the `0.60` disproof floor of `H5`, below the `0.85` support threshold without an explicit trace/violation calibration head). Across `50` 5-step synthetic edit chains (`H11`), mean latent $L_2$ distance from $y^\star$ rises across steps `0` to `4` (`0.00 -> 0.99 -> 2.26 -> 3.27 -> 3.89`, then `3.72` at step `5`), with **`18 / 50` (`36.0% < 80%`)** strictly monotone chains. Thus `FormJEPA-v1`'s repair gains come primarily from conditioning the typed edit decoder $D_\psi$ on $(z_x, \hat{z}_y)$, while smooth multi-step latent energy landscapes (`H5`, `H11`) remain open.

### 2.3 Benchmark 2: Frozen `151`-Task Ladder (`H14` Plain Arm)
- **Standalone `FormJEPA-v1`**: `k = 1` admits **`27 / 151` (`17.9%`)**; `k = 16` admits **`57 / 151` (`37.7%`, `52` behaves-the-same)**: `24/33` `history-admit`, `4/8` `history-fix`, `24/83` `rename`, `5/27` `guard`.
- **Deterministic Ladder (`rungs a..e`: `111 / 151`) + `FormJEPA-v1 (k = 16)` on the `40` residual tasks**: closes **`138 / 151` (`91.4%`)** with **zero frontier or multi-billion-parameter LLM calls**!

### 2.4 Benchmark 3: Frozen `40` Open Residual Tasks (`H15`) & 3-Gear Cascade

| Proposer / Cascade Arm | Params | Calls | Admitted (`C(z)=1`) | Restored + Beh-Eq | `reported_j` per Proposal | API Cost (`$`) |
|---|---:|---:|---:|---:|---:|---:|
| **`FormJEPA-v1 (k = 1)`** (Latent Form JEPA + greedy edit) | `8.42M` | `40` | **`22 / 40` (`55.0%`)** | **`22`** (`20` + `2`) | **`0.0586 J` core / `1.194 J` pkg** | `$0.0000` |
| **`FormJEPA-v1 (k = 16)`** (Latent Form JEPA + `k=16` beam) | `8.42M` | `40` | **`27 / 40` (`67.5%`)** | **`27`** (`25` + `2`) | **`0.4748 J` core / `6.736 J` pkg** | `$0.0000` |
| Local `Qwen 3.6 35B-A3B` (`k = 1`, `[B33]`) | `35B` (`3B` act) | `40` | `27 / 40` (`67.5%`) | `26` (`25` + `1`) | `84.247 J` SUT (Apple M5 Max) | `$0.0000` |
| Cloud `Claude Opus 5.5` (`k = 1`, `[B33]`) | Frontier | `40` | `34 / 40` (`85.0%`) | `33` (`30` + `3`) | `not_available` (cloud `N`) | `$1.3783` |
| **3-Gear Cascade (`t = 1` Cold Gear-0 $\to$ `FormJEPA-v1 k=16` $\to$ `Opus 5.5`)** | Hybrid | `13` G2 | **`34 / 40` (`85.0%`)** | `33` | `FormJEPA` + `13` cloud calls | **`$0.8108`** |
| **3-Gear Cascade (`t = 1` Cold Gear-0 $\to$ `FormJEPA-v1 k=16` $\to$ `Qwen 3.6`)** | Local | `13` G2 | **`30 / 40` (`75.0%`)** | `29` | `FormJEPA` + `13 × 84.25 J` | `$0.0000` |

- **Where `FormJEPA-v1` succeeds vs where Gear-2 Frontier Proposers remain essential**:
  - `FormJEPA-v1 (k = 16)` closes **`24 / 25` (`96.0%`)** `W-SYN-1` pre-0.9 grammar tasks (missing only `washer.rce` whose original has a vacuous `W-MUT-1` example), **`2 / 5`** `W-LEN-1` text-length tasks (`11_arena.rce`, `41_arena_bound_wrapping.rce`), and **`1 / 1`** `W-WORLD-1` capability task (`40_extern.rce`), with **`27 / 27` (`100%`)** of its admitted Forms verified `restored` (`25`) or `behaviour-equal` (`2`) (`5.33` mean `rce check` calls/task).
  - It closes **`0 / 9`** tasks requiring multi-module cryptographic stdlib refactoring (`W-NAME-1` / `W-TY-1` across `hpke`, `mls`, `pq`, `pqxdh`, `energy`), compound `W-CAP-3 + W-WORLD-1` (`48_linear_handle.rce`), or synthesizing new non-vacuous examples (`57_float_vectors.rce`).
- **`Zipf(s = 0.85)`, `M = 200` Recurring Arrival Stream (3-Gear Cascade)**:
  - With `Claude Opus 5.5` as Gear 2: Gear 0 (`DNULLMM1`) serves **`152`** arrivals (`0` model calls), Gear 1 (`FormJEPA-v1 k=16`) intercepts **`25`** first-seen misses locally (`$0.00`), and Gear 2 (`Opus 5.5`) is called only **`23` times** (`184 / 200` arrivals admitted) — an **`8.70×` frontier-call reduction** versus stateless (`200` calls) and **`2.09×` fewer frontier calls** than 2-Gear `DNULLMM1 + Opus 5.5` (`48` calls).
  - With local `Qwen 3.6 35B-A3B` as Gear 2: `Qwen 3.6` calls drop from `200` (stateless) and `94` (2-Gear) to **`49` calls (`4.08×` call reduction)**, admitting **`154 / 200`** arrivals (up from `141 / 200` with `Qwen 3.6` + Gear-0 alone) while cutting `Qwen 3.6` generation energy to `4,128.1 J`.

---

## 3. Deliverable B — Pre-Registered `rce repair` Rung `f` Observation & Promotion Evaluation (`151` Tasks)

Evaluated across all `151` frozen tasks of ladder runs 2 and 3 (`sha256: 6ae255a3...`) via `rce repair json known ORIGINAL proposals PROPOSALS MUTANT` (`mode = observe`, `bound = 2000`) and verified by `rce repair criterion` against both `spec/proposals/repair-observe/criterion.json` (`2026-11-03`, `sha256: abf7f131...`) and `PREREG_rung_f.json` (`sha256: 04aff4b2...`):

| Metric (`rce repair criterion`, `151` Tasks) | Arm A: Combined External (`FormJEPA-v1` + Recorded `H15`) | Arm B: `FormJEPA-v1` Proposals Only | Promotion Rule (`RF-5` / `RF-6`) |
|---|---:|---:|---|
| Exact deterministic closes (`E`, rungs `a..e` with `known GOOD`) | `116 / 151` | `116 / 151` | Exact rungs run first (`0` model calls) |
| Tasks left open by `a..e` | `35` | `35` | — |
| Open tasks skipped by Rung `f` (`W-SYN-1` unparsable `MUTANT`, `RF-2`) | `25` | `25` | `RF-2` requires parsed `FILE` obligations |
| Open parsing tasks judged by Rung `f` (`no_proposal = 0`) | `10` (`91` proposals judged) | `10` (`88` proposals judged) | `>= 1` proposal judged per open parsing task |
| **Rung `f` observed admissions (`F`, stochastic closes in `auto`)** | **`3`** (`3 / 119 = 2.5%`) | **`0`** (`0 / 116 = 0.0%`) | `C1`: $100 F \le 2(E + F)$ ($\le 2.0\%$) |
| **Mutation-gate (`W-MUT-1`) pass rate** | **`3 / 3` (`100.0%`)** | `0 / 0` (`n/a`, `0` vacuous) | `C2`: `100%` of observed pass `W-MUT-1` |
| **Contradictions against `ORIGINAL` (`GOOD`)** | **`0`** (`3 / 3` `restored`) | **`0`** | `C3`: `0` contradictions under `rce equiv` |
| **`rce repair criterion` verdict (`holds`)** | **`false` (`exit = 1`)** | **`true` (`exit = 0`)** | `C1`, `C2`, and `C3` all hold |

### Key Architectural & Governance Findings from Rung `f`
1. **The 2% stochastic ceiling (`C1`) works as designed**: When external frontier + JEPA proposals are fed into Rung `f` (`Arm A`), `3` of the `10` open parsing tasks are admitted and restored (`programs/ecosystem/hpke.rce@a828e934`, `programs/ecosystem/mls_key_schedule.rce@a828e934`, `stdlib/lib/energy/energy.rce@a828e934`), `100%` pass `W-MUT-1` (`C2` holds), and `0` contradict `ORIGINAL` (`C3` holds). Because `3 / 119 = 2.5% > 2.0%`, `rce repair criterion` deterministically rejects promotion (`holds: false`), keeping Rung `f` in `observe` mode (`RF-7`).
2. **Interaction between `RF-2` parse gating and pre-0.9 syntax defects**: `25` of the `35` open tasks fail parsing (`W-SYN-1`) and are skipped by Rung `f` (`RF-2`), whereas `FormJEPA-v1` + standalone `C(z) = 1` (`rce check` + external obligation preservation) admits `24 / 25` of them; additionally, on `spec/examples/40_extern.rce@013e21ed` (which `FormJEPA-v1` restores under `rce check`), `rce repair`'s internal `unparse` canonicalizer maps the proposal onto `base` (`not judged: the proposal is FILE itself`). Placing Gear-0 (`DNULLMM1`) and Gear-1 (`FormJEPA-v1`) behind the full `C(z) = 1` gate handles unparsable surface migrations while Rung `f` remains an `observe`-mode audit rail.
