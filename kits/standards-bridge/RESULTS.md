# Kit #9 (`standards-bridge`) — Empirical Results

- **Provenance Tier:** `Signed Provenance · Self-Checked` (`BLAKE3` + `Ed25519`; never self-labeled `"Verified"`)
- **Receipt Body `BLAKE3`:** `6ee27b1de540199d9dce9c46b452f0b60faf7eb1f403319de01e9e97976fa5c0`
- **CPU / OS:** `AMD RYZEN AI MAX+ 395 w/ Radeon 8060S` (`32` logical CPUs, `Linux 7.0.0-43-generic x86_64`)
- **License & Lock-In:** `100% Apache-2.0` (`OpenTelemetry` + `IETF RFC 9052 COSE_Sign1` + `FlatBuffers` + `Wasmtime`/`WebAssembly` + `LLVM MLIR/CIRCT` + `IEEE 1364 Verilog`; zero `BSL-1.1` dependencies)

## 1. OpenTelemetry Orthogonal Energy Exporter (`otel/otel_joule_span.py`)

- Semantic convention schema: `otel/semconv_openie_energy.yaml` (`SHA-256 = 3732052aa2d9eb2a...`)
- Unit tests passed: `2 / 2`
- Automated `OrthogonalityViolationError` cross-class sum rejections verified: `3 / 3` (`measured_j + reported_j`, `measured_j + est_j`, `reported_j + est_j` all blocked)

## 2. Wire Codec Head-to-Head (`10,000` Signed `Ed25519` + `BLAKE3` Receipts)

| Receipt Wire Codec | Receipts | Wire Size (`B`) | Encode (`µs`) | Decode + Verify (`µs`) | Roundtrip (`µs`) | RAPL `reported_j` (`µJ / receipt`) | Mismatches |
|---|---|---|---|---|---|---|---|
| `utf8_json_signed` | `10000` | `371.6` | `26.568` | `59.89` | `86.458` | `7925.377 µJ` | `0` |
| `ietf_rfc9052_cose_sign1_cbor` | `10000` | `144.7` | `25.98` | `60.209` | `86.189` | `7938.928 µJ` | `0` |
| `cose_sign1_flatbuf_zerocopy` | `10000` | `161.0` | `23.981` | `59.152` | `83.134` | `8746.707 µJ` | `0` |
| `compact_wai1_64b_header_signed` | `10000` | `128.0` | `20.753` | `56.018` | `76.771` | `8363.873 µJ` | `0` |

## 3. WebAssembly Front-Door Fuel vs. Physical Joules (`10,000,000` Ops: L1 ALU vs. 64 MiB DRAM)

- **Bytecode Alliance `wasmtime 50.0.1 (c307ec81d 2026-10-29)` Deterministic Fuel Proof:** `l1_alu_register_10m` exact fuel = **`330000004`**, `dram_thrash_64mib_10m` exact fuel = **`330000004`** (**fuel ratio = `1.0x`**; both deterministically trap at `fuel = 330000003`!). End-to-end CLI RAPL `reported_j`: L1 = `1.351675 J` vs. 64 MiB DRAM = `14.002923 J` (**`10.36x` physical energy ratio at `1.0x` fuel**).
- **Steady-State Pre-Faulted In-Process `node v22.22.1 WebAssembly.Instance` (`16,384` 4 KiB pages pre-touched):** L1 ALU median = `8.239 ms` (`0.820636 J` `reported_j`) vs. 64 MiB DRAM thrash = `84.127 ms` (`8.043687 J` `reported_j`) -> **`10.211x` wall-time and `9.802x` physical `reported_j` divergence at `1.000000x` Wasm instruction fuel!**

## 4. LLVM MLIR / CIRCT (`hw` + `comb`) & IEEE 1364 Verilog `2^N` Equivalence Proof

- **Exhaustive `2^6 = 64` LUT6 Minterms:** `0 / 64` mismatches (`High-Level Spec == CIRCT comb SSA IR == IEEE 1364 Verilog`)
- **Composed 2-Stage `2^10 = 1,024` Cone:** `0 / 1024` mismatches
- **Mutation Soundness (`Alive2`-style counterexample witness):** Caught injected `comb.and -> comb.or` fault at input vector `1`
- **Hardware EDA Toolchain Cross-Check:** `iverilog/vvp` 64-vec RTL sim = `True`, `yosys` UltraScale+ `xcup` LUT6 synthesis = `None` (`None` LUT cells)
