# Kit 4: `littlebit-joule` — Sub-Bit SVD + Binary Latent Factors + Walsh-Hadamard Internal Rotation (`Joules-per-Correct-Decision` vs. Deterministic Null)

- **License:** `Apache-2.0`
- **Provenance Tier:** `Signed Provenance · Self-Checked` (`BLAKE3` + `Ed25519` offline-verifiable receipt; never self-labeled `"Verified"`)
- **Research Scope:** Shot on Goal #2 — Evaluating extreme sub-bit linear/classifier compression (`0.1517 bits/weight`) on **joules-per-correct-decision** against both standard `INT8` and a mandatory **Deterministic Null** compiled lookup-table control.

---

## 1. 1-Command Reproduction

From the repository root (requires `python3 >= 3.10` and a C compiler `cc` / `gcc` / `clang`; zero proprietary or third-party Python packages required):

```bash
./kits/littlebit-joule/run_kit.sh
```

Fast smoke test (`--quick`):

```bash
./kits/littlebit-joule/run_kit.sh --quick
```

Run unit & cryptographic receipt verification tests directly:

```bash
pytest kits/littlebit-joule/tests/test_littlebit_joule.py
# or without pytest:
python3 -m unittest kits/littlebit-joule/tests/test_littlebit_joule.py
```

---

## 2. What This Kit Implements & Measures

Given a `512 × 512` (`262,144`-weight) structured spectral classification layer with `ReLU` nonlinearity and 8-class group pooling over `N = 1,200` held-out instances:

1. **Walsh-Hadamard Internal Rotation + Sub-Bit Binary Latent Factorization (`0.1517 bpw`):**
   - Applies 1-bit Rademacher pre-signs (`512` bits) + normalized $512$-point Fast Walsh-Hadamard Transform (`FWHT`) to spread heavy-tailed channel spikes uniformly before quantization, followed by rank-`22` deflated SVD + alternating binary sign refinement ($U_{\text{sign}} \in \{-1,+1\}^{512 \times 22}$, $V_{\text{sign}} \in \{-1,+1\}^{22 \times 512}$) and `int16` row/column/mode scales (`39,776` total bits = `4,972` B = **`0.1517 bits/weight`**, **`52.72x` smaller than INT8**).
2. **Four Metered Decision Regimes (`measured_j ⊥ reported_j ⊥ est_j ⊥ unmetered`):**
   - `deterministic_null_lut`: `4 KiB` compiled quadrant table + threshold fallback (`0` neural FLOPs — mandatory traditional automation baseline).
   - `dense_int8_baseline`: `8.00 bpw` (`256 KiB`) dense `int8 × int8 -> int32` matrix-vector baseline.
   - `subbit_naive_float_unpack`: `0.1517 bpw` unpacked to `FP32` at batch-1 decision time — **empirically exposing the decompression impedance tax** (wins `52.7x` on storage bits, loses badly on joules-per-correct-decision).
   - `littlebit_joule_packed_int`: `0.1517 bpw` executed directly in packed integers via in-place `O(D log D)` integer Walsh-Hadamard butterfly, reciprocal-shift 5-plane bit-slicing, `uint64` `XNOR + popcount`, and exact 6x 4-bit nibble `U_sign` table accumulation — **eliminating float unpacking to beat `INT8` on both latency and `reported_j` per correct decision**.

---

## 3. Energy & Provenance Discipline

- When `/sys/class/powercap/intel-rapl*` is readable without root on Linux, package and core energy counters are recorded strictly as **`reported_j`** alongside pre/post quiet-window idle power (`W`). When unreadable (unprivileged container or macOS without root), energy fields report `null` under **`evidence_class: "unmetered"`**.
- `measured_j`, `reported_j`, `est_j`, and `unmetered` are never summed or mixed.
- Output artifacts (`results/littlebit_joule_results.json`, `results/littlebit_joule_receipt.json`, and [`RESULTS.md`](./RESULTS.md)) are scrubbed of hostnames, usernames, local paths, and private IPs.

### Shot on Goal #6 — Physical DC Shunt Rail Metering (`measured_j`) & 14-Point `bitwidth_curve`
- Automatically discovers rootless Linux `hwmon` DC current shunts (`TI INA3221 VDD_CPU_SOC_MSS` + `TI INA238 VIN` on `NVIDIA Jetson AGX Thor`; `TI INA260 SOM_5V_DC` on `AMD Kria KV260`) and integrates instantaneous rail power at `~200–235 Hz` across `>= 0.70 s` auto-calibrated burst windows (`measured_j`), reporting both Gross and Falsifier-6-gated Net-Above-Idle `µJ / correct`.
- Sweeps SVD ranks `r ∈ {8, 14, 22, 32, 48}` (both `packed_int` and `naive_fp32_unpack`), `ternary_2bpw`, `int4_4bpw`, `dense_int8_8bpw`, and `deterministic_null_lut`. Cross-substrate signed receipts are stored in [`results/multi_substrate_receipts.json`](./results/multi_substrate_receipts.json) and summarized in [`RESULTS.md`](./RESULTS.md).
