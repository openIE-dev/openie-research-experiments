# Kit 4 (`littlebit-joule`) — Hardware-Metered Results

- **Provenance Tier:** `Signed Provenance · Self-Checked` (`Apache-2.0`)
- **Host CPU & OS:** `13th Gen Intel(R) Core(TM) i9-13900H` (`Linux 7.0.0-43-generic x86_64`, `cc (Ubuntu 15.2.0-16ubuntu1) 15.2.0`)
- **Energy Evidence Class:** **`reported_j`** (`measured_j = null`, `est_j` never mixed)
- **RAPL Counters:** `/sys/class/powercap/intel-rapl:0/energy_uj` (`package-0`) & `/sys/class/powercap/intel-rapl:0:0/energy_uj` (`core`), idle pre/post `18.105 W` / `25.75 W` (`34.86%` drift)
- **Matrix & Factorization:** `512×512` (`262,144` weights), rank `r = 22`, **`0.1517 bits/weight`** (`4,972` B = **`52.72x` smaller than INT8** / `105.45x` smaller than FP16)
- **Walsh-Hadamard Internal Rotation Effect:** Peak-to-RMS outlier crest reduced from `5.8006` -> **`4.7457`** prior to 1-bit latent sign quantization
- **Determinism:** `0 / 80` divergent runs across `20` interleaved trials (95% Clopper–Pearson upper bound `<= 0.036754`)
- **Signed Receipt (`BLAKE3` + `Ed25519`):** `8b8f2d5d253b609dc34a669b...` (offline signature check: `PASS`)

## 4-Regime Comparison (`Joules-per-Correct-Decision` vs. `Deterministic Null`)

| Regime | Bits / Weight | Footprint | Held-Out Accuracy | Wall `ns / correct` (`IQR`) | Package `reported_j` `µJ / correct` (`IQR`) | Core `reported_j` `µJ / correct` |
|---|---:|---:|---:|---:|---:|---:|
| `deterministic_null_lut` | `n/a (LUT)` | `4,096 B` | **`96.33%`** (`1156/1200`) | `38.01` (`35.62–38.97`) | **`1.1175`** (`0.9404–1.356`) | `0.9092` |
| `dense_int8_baseline` | `8.0000` | `262,144 B` | **`100.00%`** (`1200/1200`) | `11713.76` (`11342.14–12925.32`) | **`387.3771`** (`368.9003–483.2077`) | `325.9355` |
| `subbit_naive_float_unpack` | `0.1517` | `4,972 B` | **`100.00%`** (`1200/1200`) | `603508.04` (`582265.03–612330.83`) | **`20192.1677`** (`18594.4319–21136.0501`) | `16715.3026` |
| `littlebit_joule_packed_int` | `0.1517` | `4,972 B` | **`100.00%`** (`1200/1200`) | `2949.02` (`2785.01–3085.12`) | **`81.1941`** (`77.3099–87.4953`) | `65.5361` |

## Key Empirical Findings

1. **Decompression Impedance Tax Exposed (`subbit_naive_float_unpack` vs `dense_int8_baseline`):** Compressing weights to `0.1517 bpw` (`52.72x` smaller than INT8) while unpacking to `FP32` at batch-1 decision time costs **`51.52x` more wall time** and **`52.13x` more package `reported_j` per correct decision** than plain INT8.
2. **Packed Integer Execution Resolves the Impedance Tax (`littlebit_joule_packed_int`):** Executing the same `0.1517 bpw` factors via in-place integer Walsh-Hadamard butterfly + `uint64` `XNOR + popcount` achieves **`100.00%`** accuracy while delivering **`3.97x` lower latency than INT8** (`204.65x` faster than naive FP32 unpack) and **`4.77x` lower package `reported_j` per correct decision than INT8** (`248.69x` lower than naive unpack).
3. **Why the Deterministic Null Control Is Mandatory (`deterministic_null_lut`):** A `4 KiB` compiled quadrant table (`0` neural FLOPs) already solves **`96.33%`** of instances at **`346.65x` lower `reported_j` per correct decision than INT8**—isolating the exact `3.67` percentage-point fine-spectral increment paid for by the sub-bit projection.
