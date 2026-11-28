# Kit 9: `standards-bridge` — Zero-Lock-In `Apache-2.0` Standards Interop (`OpenTelemetry` + `IETF COSE` / `FlatBuffers` + `Wasmtime` + `LLVM MLIR / CIRCT`)

- **License:** `Apache-2.0` (zero `BSL-1.1` or bespoke language lock-in)
- **Provenance Tier:** `Signed Provenance · Self-Checked` (`BLAKE3` + `Ed25519` offline-verifiable receipt; never self-labeled `"Verified"`)
- **Research Scope:** Track 3 — Adopting OpenIE's metered commit gates, orthogonal energy telemetry (`measured_j ⊥ reported_j ⊥ est_j ⊥ unmetered`), WebAssembly front-door sandboxing, and downward LUT6 hardware compilation directly via mainstream `Apache-2.0` / IETF / IEEE open standards.

---

## 1. 1-Command Reproduction

From the repository root (`python3 >= 3.10` stdlib + `node` or `wasmtime`; auto-detects `wat2wasm`, `wasmtime`, `libcrypto`, `iverilog`/`vvp`, and `yosys` when installed):

```bash
./kits/standards-bridge/run_kit.sh
```

Fast smoke test (`--quick`):

```bash
./kits/standards-bridge/run_kit.sh --quick
```

---

## 2. Four Standalone `Apache-2.0` Reference Modules

1. **`otel/otel_joule_span.py` + `otel/semconv_openie_energy.yaml` (OpenTelemetry Exporter & Orthogonality Guard):**
   - Defines OpenTelemetry Semantic Conventions (`openie.energy.measured_j`, `openie.energy.reported_j`, `openie.energy.est_j`, `openie.energy.evidence_class`, `openie.gate.blake3`, `openie.provenance.tier`) and exports standard `OTLP/JSON` v1 `ExportTraceServiceRequest` batches.
   - Enforces an automated **`OrthogonalityViolationError`** rejecting any span or trace rollup attempting to populate or sum heterogeneous energy classes (`measured_j + reported_j`, `measured_j + est_j`, `reported_j + est_j`).
2. **`wire/cose_flatbuf_bench.py` (IETF RFC 9052 `COSE_Sign1` + Zero-Copy `FlatBuffers` vs. UTF-8 JSON & `WAI1`):**
   - Benchmarks RFC 8949 deterministic CBOR `COSE_Sign1` (Tag `18`, `alg = -8` `EdDSA`/`Ed25519`) and an 8-byte-aligned `FlatBuffers` vtable/table zero-copy receipt payload (`80 B` table) head-to-head against raw UTF-8 JSON and compact `64`-byte `WAI1` fixed headers across **`10,000` signed receipts**, reporting encode/decode `µs`, wire size, and Linux `powercap` RAPL `reported_j`.
3. **`wasm/wasm_fuel_calibration.py` + `wasm/fuel_kernels.wat` (`Wasmtime` Fuel vs. Physical Joules):**
   - Executes two WebAssembly functions with **identical instruction counts (`10,000,000` loop iterations, exact `1.000000x` `wasmtime -W fuel` parity)** — an L1-resident ALU/register loop vs. a strided `64 MiB` (`1,024`-page) linear-memory thrash loop — inside Bytecode Alliance `wasmtime` and `node` `WebAssembly.Instance`, empirically demonstrating why Wasm sandboxing + fuel is the ideal deterministic termination gate AND why **instruction fuel $\neq$ physical joules**.
4. **`circt/emit_circt_hw.py` (LLVM MLIR / CIRCT `hw`+`comb` + Synthesizable IEEE 1364 Verilog + `2^N` Equivalence Proof):**
   - Lowers a verified 6-input OpenIE commit-gate table (`N = 6`, `4` outputs) into valid **LLVM MLIR / CIRCT (`hw.module` + `comb` dialect)** and zero-latch **IEEE 1364-2005 Verilog**, proving bit-exactness across all `2^6 = 64` vectors and a composed `2^10 = 1,024`-vector 2-stage LUT6 cone (`Alive2`-style counterexample soundness + optional `iverilog`/`vvp` & `yosys` `xcup` synthesis).

Committed empirical artifacts: [`results/standards_bridge_receipt.json`](./results/standards_bridge_receipt.json), [`results/sample_otlp_energy_spans.json`](./results/sample_otlp_energy_spans.json), [`results/openie_commit_gate_lut6.circt.mlir`](./results/openie_commit_gate_lut6.circt.mlir), [`results/openie_commit_gate_lut6.v`](./results/openie_commit_gate_lut6.v), and [`RESULTS.md`](./RESULTS.md).
