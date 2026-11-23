# Executed Hardware Benchmark Report: CTA Attested Orchestration (`CTA-E1` to `CTA-E3`)

- **Study**: #21 - *The Communication Tool Avalanche: Thresholded Signal Externalization, Event-Driven Orchestration, and Coherence per Joule* (`communication-avalanche`)
- **Pre-Registration Lock**: `PREREG_cta_orchestration.json` (`SHA-256 = 5739bcdd6c35662833a470bc56bd64f991774c2d920a5a9c059c0acebdf55e7f`, locked prior to running `CTA-E1`, `CTA-E2`, and `CTA-E3`)
- **Frozen 60-Task Corpus**: `cta_tasks_60.py` (`corpus_sha256 = b4ea0228270b8e6ae06f935fe8b92ed45cf2da4d9aa0d4868d0a42d4e6e9e802`)
- **Compiled Rust Engine**: `cta_attest_rust` (`rustc 1.100.0`, `blake3 v1.8.7`, `ed25519-dalek v2.2.0`, `subtle v2.6.1`)
- **Execution Platform**: `13th Gen Intel(R) Core(TM) i9-13900H` (`20` logical threads, Linux `x86_64`, `Python 3.14.4`)
- **Measurement Grammar**: Linux `sysfs` `powercap` `reported_j` (`intel-rapl:0` `package-0`, `intel-rapl:0:0` `core`, `intel-rapl:1` `psys`); `measured_j = None`; `board_metered = false`; cloud Application Programming Interface (API) server energy = `not_available` (reported strictly via token counts and United States dollars (USD)).

---

## 1. Pre-Registered Falsifier Verdict Summary (`F1` to `F6`)

| Falsifier | Pre-Registered Criterion | Empirical Result | Verdict |
| :--- | :--- | :--- | :--- |
| **`F1` (`CTA-E1` Polling Tax)** | Zero-clock `eventfd` threshold firing lowers OS wakeups and `pkg_reported_j` vs. `100 Hz`/`1,000 Hz` polling at `1%` and `5%` duty while beating `10 Hz`/`100 Hz` latency | At `1%` duty: `136.32 J` (`559.4` wakes, `2.58 ms` p50) vs. `198.51 J` (`100 Hz`, `55.22 ms` p50) and `300.73 J` (`1,000 Hz`, `150,139.8` wakes, `7.34 ms` p50); `5/5` paired `1 kHz` deltas positive at both `1%` and `5%` duty | **Supported (`F1` not triggered)** |
| **`F2` (Attestation Cost)** | Rust `BLAKE3` (`256`-bit) + `Ed25519` (`64`-byte RFC `8032`) verify stays `< 100 µs` and `< 5 mJ` up to `64 KiB` | `25.95 µs` (`643.03 µJ` pkg) at `64 B` to `37.39 µs` (`926.42 µJ` pkg) at `64 KiB` (`50,000` iters/bucket) | **Supported (`F2` not triggered)** |
| **`F3` (Oracle Isolation)** | Zero access to `HOLD_OUT_ORACLES` by any arm or internal kernel prior to post-commit scoring | Verified structurally: `get_public_tasks()` strips `reference_code` and `test_vectors`; `test_gen_kernel` uses only public docstrings + type/algebraic properties | **Supported (`F3` not triggered)** |
| **`F4` (`CTA-E2` Coherence/J)** | `Arm D` (`CTA-Orchestrator`) matches/exceeds `Arm B` & `Arm C` pass rate while lowering false commits and improving `CpJ` | `Arm D`: `59/60` (`98.33%`), `0/60` (`0.00%`) false commits, `0.1363 tasks/J` (`\$0.26`) vs. `Arm B` (`59/60`, `1` false commit, `0.0654 tasks/J`, `\$0.42`) and `Arm C` (`52/60`, `8` false commits, `0.0091 tasks/J`, `\$2.05`) | **Supported (`F4` not triggered)** |
| **`F5` (`CTA-E3` Containment)** | `0 / 200` downstream corrupt commits across 4 fault classes + `SSP` reroute `< 1,000 µs` across `20` dropouts | `0 / 200` (`0.00%`) corrupt commits vs. `169 / 200` (`84.50%`) unattested; `20 / 20` `SSP` reroutes satisfied in `p50 = 2.40 µs` (`max = 3.58 µs`) | **Supported (`F5` not triggered)** |
| **`F6` (Idle Drift Guard)** | Flag and withhold derived idle-subtracted net joules if pre/post `5.0 s` quiet idle `package-0` power drifts `> 10.0%` | **`CTA-E1`: `410.20%` post-load tail drift (`3.95 W` -> `20.13 W`) -> TRIGGERED (derived net subtraction withheld; raw `reported_j` reported).** **`CTA-E2`: `9.93%` drift (`6.10 W` -> `5.49 W`) -> PASSED (`<= 10.0%`).** | **Enforced transparently** |

**Runner compatibility note**: Prior to any `CTA-E2` LLM episode completing, Anthropic's `claude-sonnet-5-5` endpoint rejected `"temperature": 0.0` with HTTP `400` (`"temperature is deprecated for this model"`). That single deprecated field was removed from `AnthropicSonnetClient.complete()` in `run_cta_orchestration_bench.py` while keeping `PREREG_cta_orchestration.json` (`5739bcdd6c35...`), `cta_tasks_60.py` (`b4ea0228...`), and `cta_attest_rust` (`eaaabab4...`) byte-identical.

**OEM `psys` counter note**: On this `Intel Core i9-13900H` laptop chassis, `intel-rapl:0` (`package-0`) and `intel-rapl:0:0` (`core`) scale dynamically (`~3.9-6.1 W` idle to `~27.7-40.7 W` active), whereas `intel-rapl:1` (`psys`) reflects an unpopulated OEM Embedded Controller rate of `~0.202 W`. All three rails are preserved verbatim in `results/*.json` and `cta_e2_firing_ledger.jsonl`.

---

## 2. `cost_lut.json`: Heterogeneous Pool & Cryptographic Attestation Profile

### 2.1 Deterministic Python Pool Kernels (`200` Samples / Cell)

| Kernel Node | `< 320 B` (`pkg mJ` / `lat ms`) | `320-640 B` (`pkg mJ` / `lat ms`) | `> 640 B` (`pkg mJ` / `lat ms`) |
| :--- | ---: | ---: | ---: |
| `parse_kernel` | `1.580 mJ` / `0.119 ms` | `1.380 mJ` / `0.057 ms` | `4.725 mJ` / `0.190 ms` |
| `static_type_scope_kernel` | `1.096 mJ` / `0.031 ms` | `0.637 mJ` / `0.029 ms` | `13.802 mJ` / `0.554 ms` |
| `test_gen_kernel` | `0.309 mJ` / `0.013 ms` | `0.361 mJ` / `0.013 ms` | `0.350 mJ` / `0.015 ms` |
| `det_patch_kernel` | `11.565 mJ` / `0.421 ms` | `15.734 mJ` / `0.602 ms` | `45.227 mJ` / `1.724 ms` |
| `diff_verifier_kernel` | `1.186 mJ` / `0.043 ms` | `1.118 mJ` / `0.048 ms` | `5.713 mJ` / `0.209 ms` |

### 2.2 Compiled Rust `BLAKE3` (`256`-bit) + `Ed25519` (`64`-byte RFC `8032`) (`50,000` Iterations / Bucket)

| Payload Size | Sign `p50` / `p99` (`µs`) | Sign `pkg` / `core` (`µJ`) | Verify `p50` / `p99` (`µs`) | Verify `pkg` / `core` (`µJ`) |
| :--- | ---: | ---: | ---: | ---: |
| `64 B` | `10.12` / `12.47 µs` | `287.46` / `243.83 µJ` | `25.95` / `27.49 µs` | `643.03` / `543.65 µJ` |
| `1,024 B` (`1 KiB`) | `10.61` / `11.95 µs` | `268.12` / `227.83 µJ` | `27.04` / `28.73 µs` | `650.59` / `546.58 µJ` |
| `16,384 B` (`16 KiB`) | `12.60` / `13.42 µs` | `316.32` / `267.73 µJ` | `29.32` / `30.44 µs` | `696.16` / `584.07 µJ` |
| `65,536 B` (`64 KiB`) | `21.61` / `22.51 µs` | `540.78` / `458.58 µJ` | `37.39` / `39.54 µs` | `926.42` / `784.95 µJ` |

---

## 3. `CTA-E1`: 16-Node DAG Event-Driven Thresholds vs. Clocked Polling (`60` × `10.0 s` Windows)

- **Raw window aggregates** (`results/cta_e1_polling_vs_threshold.json`, net subtraction withheld per `Falsifier 6`):
  - **`1%` Duty (`51` events/window)**:
    - `event_threshold`: `136.32 J` pkg (`96.24 J` core), `559.4` wakeups (`0` empty), `811.4` ctxt switches, `p50 = 2.58 ms`
    - `poll_10hz`: `143.42 J` pkg (`103.76 J` core), `1,600.0` wakeups (`1,284.8` empty), `1,963.0` ctxt switches, `p50 = 570.38 ms`
    - `poll_100hz`: `198.51 J` pkg (`157.35 J` core), `15,799.8` wakeups (`15,475.6` empty), `16,156.2` ctxt switches, `p50 = 55.22 ms`
    - `poll_1000hz`: `300.73 J` pkg (`259.17 J` core), `150,139.8` wakeups (`149,844.2` empty), `150,574.8` ctxt switches, `p50 = 7.34 ms`
    - Paired within-replicate `(poll_1000hz - event_threshold)` `pkg_reported_j` deltas: `[+119.72, +182.96, +313.29, +123.71, +82.32] J` (`5 / 5` positive).
  - **`5%` Duty (`255` events/window)**:
    - `event_threshold`: `318.78 J` pkg (`275.34 J` core), `2,792.6` wakeups (`0` empty), `p50 = 2.75 ms`
    - `poll_10hz`: `315.24 J` pkg, `1,598.6` wakeups, `p50 = 558.26 ms`
    - `poll_100hz`: `331.84 J` pkg, `15,795.0` wakeups (`14,132.2` empty), `p50 = 51.98 ms`
    - `poll_1000hz`: `406.75 J` pkg (`360.50 J` core), `149,823.8` wakeups (`148,335.8` empty), `p50 = 7.46 ms`
    - Paired within-replicate `(poll_1000hz - event_threshold)` `pkg_reported_j` deltas: `[+73.06, +140.18, +60.87, +82.78, +82.98] J` (`5 / 5` positive).
  - **`20%` Duty (`1,020` events/window)**:
    - `event_threshold`: `236.43 J` pkg (`196.07 J` core), `10,260.8` wakeups (`0` empty), `p50 = 2.76 ms`, `p99 = 55.19 ms`
    - `poll_10hz`: `231.45 J` pkg, `1,582.0` wakeups (`999.6` committed), `p50 = 547.62 ms`, `p99 = 721.74 ms`
    - `poll_100hz`: `234.04 J` pkg, `15,649.6` wakeups (`9,280.2` empty), `p50 = 52.07 ms`, `p99 = 99.54 ms`
    - `poll_1000hz`: `269.13 J` pkg (`223.87 J` core), `148,023.6` wakeups (`142,013.6` empty), `p50 = 7.43 ms`, `p99 = 59.39 ms`

---

## 4. `CTA-E2`: 60-Task Code-Repair Benchmark (`240` Episodes, `322` Ledger Receipts)

- **Quiet Idle Baseline (`Falsifier 6` passed at `9.934% <= 10.0%`)**: Pre-run `6.101 W` (`30.58 J` over `5.01 s`), post-run `5.495 W` (`27.53 J` over `5.01 s`).
- **Epoch-0 `SSP` Min-Cost Flow Schedule**: Solved in `2.106 µs` (`flow = 60`, `total_cost = 1,159,800` scaled `µJ`), routing initial flow strictly through the deterministic 5-kernel spine (`source -> parse_kernel -> static_type_scope_kernel -> test_gen_kernel -> det_patch_kernel -> diff_verifier_kernel -> commit_gate`).
- **Four-Arm Summary (`Claude Sonnet 5.5`, list pricing `\$3 / \$15` per `1M` tokens)**:
  - **`Arm A` (`Det-Only` Pool)**: `40 / 60` (`66.67%`) pass, `0 / 60` (`0.00%`) false commits, `20` refused, `0` LLM calls, `\$0.00`, `1.5072 J` pkg (`1.2834 J` core), `0.057 s`, `CpJ_pkg = 26.5393 tasks/J`.
  - **`Arm B` (`Monolithic-LLM`)**: `59 / 60` (`98.33%`) pass, `1 / 60` (`1.67%`) false commit (`C3_05` output truncation `SyntaxError`), `60` LLM calls, `44,843` tokens (`\$0.4202`), `902.5098 J` pkg (`160.9307 J` core), `193.881 s`, `CpJ_pkg = 0.0654 tasks/J`.
  - **`Arm C` (`Unattested-4-Agent` Avalanche)**: `52 / 60` (`86.67%`) pass, `8 / 60` (`13.33%`) false commits (`C3_02`, `C3_03`, `C3_06`, `C3_11`, `C3_13`, `C3_15`, `C3_17`, `C3_18`), `240` LLM calls, `288,583` tokens (`\$2.0486`), mean input prompt amplification `[330.6, 600.0, 1011.2, 1225.1]` tokens across the `4` conversational hops, `5,710.7714 J` pkg (`1,043.3957 J` core), `1,229.148 s`, `CpJ_pkg = 0.0091 tasks/J`.
  - **`Arm D` (`CTA-Orchestrator`)**: `59 / 60` (`98.33%`) pass, `0 / 60` (`0.00%`) false commits, `1` clean refusal (`C3_17`), `21` LLM calls (`0` on Categories 1 & 2, `21` on Category 3), `28,452` tokens (`\$0.2578`), `432.7478 J` pkg (`74.0815 J` core), `95.119 s`, `CpJ_pkg = 0.1363 tasks/J` (`CpJ_core = 0.7964 tasks/J`), `322` attested edge receipts logged in `results/cta_e2_firing_ledger.jsonl`.

---

## 5. `CTA-E3`: Byzantine Fault Containment (`200` Events) & `SSP` Topology Failover (`20` Dropouts)

- **Valid Control Channel Envelopes**: `200 / 200` admitted (`verify_p50 = 27.51 µs`, `mean = 31.80 µs`, `p99 = 78.09 µs`).
- **Corrupted Channel Injections (`200` Events)**:
  - `50` payload bit-flips: `50 / 50` rejected by `BLAKE3` (`p50 = 0.186 µs`, `p99 = 0.230 µs`, `0` corrupt commits vs. `43 / 50` unattested cascades).
  - `50` spoofed sender IDs: `50 / 50` rejected by `Ed25519` (`p50 = 27.561 µs`, `p99 = 32.443 µs`, `0` corrupt commits vs. `50 / 50` unattested cascades).
  - `50` truncated JSON/AST frames: `50 / 50` rejected by typed frame schema guard (`p50 = 27.551 µs`, `p99 = 30.956 µs`, `0` corrupt commits vs. `26 / 50` unattested cascades).
  - `50` semantic regression patches: `50 / 50` rejected by `diff_verifier_kernel` (`p50 = 332.43 µs`, `21.12 mJ` pkg/gate, `0` corrupt commits vs. `50 / 50` unattested commits).
  - **Aggregate**: `0 / 200` (`0.00%`) corrupt commits in `CTA-Orchestrator` vs. `169 / 200` (`84.50%`) in the unattested baseline.
- **`SSP` Min-Cost Flow Topology Failover (`20` Mid-Stream Node Dropouts)**:
  - Baseline solve (`14` nodes, `26` directed arcs, `demand = 8`): `7.21 µs` (`cost = 93,000`).
  - Across `20` single-, dual-, triple-, and quad-node primary/standby dropout scenarios: `20 / 20` (`100%`) satisfied full flow demand `8`, with recomputation latency `mean = 2.41 µs`, `p50 = 2.40 µs`, `p99 = 3.58 µs`, `max = 3.58 µs`.
