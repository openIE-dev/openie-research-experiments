# Kit 5 (`waios-mosaic-cascade`) — Cross-Lane Conformance & 4-Stage Cascade Results

- **Provenance Tier:** `Signed Provenance · Self-Checked` (`Apache-2.0`)
- **Host CPU & OS:** `13th Gen Intel(R) Core(TM) i9-13900H` (`Linux 7.0.0-43-generic x86_64`, `cc (Ubuntu 15.2.0-16ubuntu1) 15.2.0`)
- **Energy Evidence Class:** **`reported_j`** (`measured_j = null`; analytical `est_j` isolated in §3)
- **RAPL Counters:** `/sys/class/powercap/intel-rapl:0/energy_uj` (`package-0`) & `/sys/class/powercap/intel-rapl:0:0/energy_uj` (`core`), idle pre/post `17.4342 W` / `7.2101 W` (`82.97%` drift)
- **Signed Receipt (`BLAKE3` + `Ed25519`):** `eb360104252adeee3bc87ac1...` (offline signature check: `PASS`)

## 1. Canonical `waiOS` `256×128` Cross-Lane Invariance & Fault-Injection Halt

| Execution Lane / Test | Observed `BLAKE3` (`waios.tmac.v1`) | Matches `a541323b...46f0` | Receipt Action |
|---|---|---|---|
| `python_scalar_i32` | `a541323b13653ed36515ff24ef08deb7dfa771e570a434712708fb72552f46f0` | **`YES`** | Sealed |
| `c_scalar_i32` | `a541323b13653ed36515ff24ef08deb7dfa771e570a434712708fb72552f46f0` | **`YES`** | Sealed |
| `c_packed_2bit_bitsliced` | `a541323b13653ed36515ff24ef08deb7dfa771e570a434712708fb72552f46f0` | **`YES`** | Sealed |
| `c_tmac_pair_lut` | `a541323b13653ed36515ff24ef08deb7dfa771e570a434712708fb72552f46f0` | **`YES`** | Sealed |
| `c_hetero_mosaic_4worker_pthreads` | `a541323b13653ed36515ff24ef08deb7dfa771e570a434712708fb72552f46f0` | **`YES`** | Sealed |
| `fault_injection_row77` (`w[77,0]: 0 -> 1`) | `4ac7c4fbc2f2a031ac4f3c0e485867fb689d24d4872bdb1b0a6bc80cf88b69dc` | **`NO` (expected tamper)** | **HALTED · Receipt Refused** |

- **Boot Qualification:** Odd-sized `73×35` ternary product = `True`; `64`-dim zero-FP `RMSNorm + Q15 RoPE` digest = `2537994ab8583a38da2b9770...`.
- **Multi-Schedule HeteroMosaic Sweep:** `0 / 100` disagreements across shifted 4-worker `pthread` tile partitions (one-sided 95% Clopper–Pearson upper bound `<= 0.029513`).

## 2. 4-Stage Spellcheck Lookup-First Cascade (`1,000` Mixed Queries — Local Silicon `reported_j`)

- **Stage Routing Breakdown (`1,000` queries):** Stage 1 `O(1)` Compiled LUT = **`550`** (`55.0%`), Stage 2 Trigram Sparse + Edit Gate = **`250`** (`25.0%`), Stage 3 `waiOS` Integer Mosaic = **`174`** (`17.4%`), Stage 4 Escalation Gate = **`26`** (`2.6%`).

| Pipeline | Correct / `1,000` | Wall `µs / correct` (`IQR`) | Package `reported_j` `µJ / correct` (`IQR`) | Core `reported_j` `µJ / correct` |
|---|---:|---:|---:|---:|
| `spellcheck_4stage_cascade` | **`1000 / 1000`** (`100.0%`) | `10.672` (`10.533–10.791`) | **`267.45`** (`250.03–290.7`) | `209.21` |
| `always_stage3_mosaic_plus_gate` | **`1000 / 1000`** (`100.0%`) | `32.07` (`31.783–32.289`) | **`759.77`** (`686.33–891.56`) | `570.66` |
| `always_dense_teacher_baseline` | **`1000 / 1000`** (`100.0%`) | `182.355` (`181.4–185.59`) | **`4902.29`** (`4513.06–6584.36`) | `3889.88` |

- **Same-Meter Local Comparison (`reported_j` only):** `spellcheck_4stage_cascade` achieves **`17.09x` lower wall latency** than `always_dense_teacher_baseline` (`3.01x` lower than `always_stage3_mosaic_plus_gate`) and **`18.33x` lower package `reported_j` per correct completion** than `always_dense_teacher_baseline` (`2.84x` lower than `always_stage3_mosaic_plus_gate`).

## 3. Isolated Analytical Cloud Escalation Reference (`est_j` — Never Summed with `reported_j`)

| Analytical Scenario (`evidence_class = est_j`) | Remote Frontier Calls | Analytical `est_j` (`@ 1.50 J/call`) | Call Avoidance |
|---|---:|---:|---:|
| Frontier-Only Pipeline (`100%` remote calls) | `1,000` | `1500.00 est_j` | `1.00x` |
| 4-Stage Cascade (`Stage 4` residual only) | `26` | `39.00 est_j` | **`38.46x`** |
