# OpenIE Research — JCP + openie-cad + SATB Spine & MEI-JCP-Tag-v1 Reference Hardware

## 1. Executive Summary & Honesty Contract

This bundle delivers two reproducible Rust and open-hardware artifacts joining the **Joule Context Protocol** (`JCP`, draft `JCR-1`), the **System-and-Task-Boundary Input/Output** (`SATB-IO`) provenance framework, and **`openie-cad`**:

1. **Deliverable A (`jcp-satb-cad-spine/` + `cad-joules-jcp-bridge.patch`)**: A self-contained Rust workspace (`310` passing tests across 7 crates) and clean `git apply`-verified patch for `openie-cad/crates/cad-joules` implementing a monotone provenance meet-semilattice (`280 × 280 = 78,400` tested state pairs, `0` silent provenance or rail-coverage promotions), `SATB` Falsifier 6 (`<= 5.00%` pre/post idle baseline drift gate), `SATB` Step 7 (`<= 1 µJ` sequential phase conservation), and canonical deterministic CBOR (`det-CBOR`) + Ed25519 `COSE_Sign1` `JCR-1` receipt sealing verified by `jcp_receipt::verify_log` and `jcp_receipt::replay_ledger`.
2. **Deliverable B (`hardware/` + `mei-jcp-tag-builder/` + `receipts/`)**: Programmatic CAD, ECAD, and electro-thermal verification of **`MEI-JCP-Tag-v1`**, an open reference sensor tag (`32.0 mm × 24.0 mm` 2-layer PCB with `0` DRC violations + `36.0 mm × 28.0 mm × 7.5 mm` vented 3D B-Rep enclosure + `CR2032` battery simulation across `-20 °C / +4 °C / +25 °C` + `10,000`-wakeup `JCP` two-phase `hold` / `settle` cold-chain gate) backing *Metabolic Intelligence* (`mei`) and *The Search for JouleOS* (`jouleos`).

### Strict Evidence Separation (`measured_j` vs `reported_j` vs `est_j`)

- **`board_metered`: `false`**, **`measured_j`: `null`** across every artifact in this bundle. `MEI-JCP-Tag-v1` is an exported, DRC-certified fabrication and 3D CAD package, not yet physically assembled or wired to a bench shunt.
- **`reported_j` (`380,202,002 µJ` = `380.20 J`)**: Direct Linux Running Average Power Limit (`RAPL`, `package-0`) hardware register deltas recorded on the 32-core build workstation (`$BENCH_ROOT`) during the `openie-cad` B-Rep, autoroute, DRC, and simulation stages, tagged `HwShunt` with `satb_vendor_opaque = 1` and `Coverage::Partial` so they never promote to `measured_j`.
- **`est_j` (`242,073,902 µJ` = `242.07 J` build estimate; `0.00–2,193.12 J` cell discharge model)**: Analytical estimates across embodied material (`45.15 J`), surface-mount assembly batch share (`14.50 J`), analytical compute (`182.42 J`), and `cad-sim::battery` `CR2032` discharge simulations.

---

## 2. Deliverable A: Unified `JCP` ↔ `SATB-IO` ↔ `openie-cad` Spine

### 2.1 Lossless Provenance Meet-Semilattice

| SATB-IO Coordinate (`Boundary × Attribution × Mechanism`) | JCP Rung & Coverage | Vendor Opaque | Evidence Tier | Rank |
|---|---|---|---|---|
| `(L0 \| L1 \| L2) + (A1 \| A2 \| B) + RailShuntWhole` | `HwShunt (Whole)` | `0` | `measured_j` | `4` |
| `(L0 \| L1 \| L2) + (A1 \| A2 \| B) + RailShuntPartial` | `HwShunt (Partial)` | `0` | `measured_j` | `4` |
| `(L1 \| L2 \| L3) + (A1 \| A2 \| B) + IOReport/RAPL/NVML/ri_energy_nj` | `HwShunt (Whole \| Partial)` | `1` | `reported_j` | `3` |
| `(L2 \| L3) + C (Kepler CPU-share)` | `ModelBased (Partial)` | n/a | `reported_j` | `2` |
| `(L0..L3) + D (wall_s × W_est or OpCounter)` | `Estimator (Whole \| Partial)` | n/a | `est_j` | `1` |
| `L4` or `(P \| N)` or unattested closed API | `NotAvailable` | n/a | `not_available` | `0` |

Exhaustive cartesian verification (`vector_01_satb_jcp_lattice_roundtrip_and_exhaustive_no_upgrade_meet`) tests all `5 × 7 × 8 = 280` provenance states (`280 × 280 = 78,400` pairs) and confirms idempotence, commutativity, `rank(a ∧ b) <= min(rank(a), rank(b))`, and `coverage(a ∧ b) = coverage(a) ∧ coverage(b)` (`0` silent upgrades).

### 2.2 Conformance & Workspace Test Summary

- `jcp-satb-cad-spine` workspace (`cargo test --workspace`): **310 passed, 0 failed** (`jcp-schema`: 57, `jcp-grant`: 72, `jcp-runtime`: 81, `jcp-receipt`: 39, `jcp-energy`: 25, `jcp-efficiency`: 31, `jcp-satb-cad-spine` conformance suite: 5).
- `openie-cad` `cad-joules` with `cad-joules-jcp-bridge.patch` applied (`cargo test -p cad-joules`): **13 unit tests + 1 doctest passed, 0 failed**, `git apply --check` clean.
- Verified conformance vectors cover:
  - `Allow` with Ed25519 `COSE_Sign1` canonical `det-CBOR` verification,
  - `BudgetExceeded` refusal (`debited_uj == 0`),
  - `UntrustedControl` (`Trust::Data`) anti-tool-poisoning refusal (`debited_uj == 0`),
  - `Revoked` grant refusal (`debited_uj == 0`),
  - `AlreadyResolved` duplicate `settle` refusal leaving prior settlement intact,
  - `SATB` Falsifier 6 (`> 5.00%` baseline drift omits `satb_derived_marginal_uj` from signed CBOR bytes while preserving `satb_raw_counter_uj`),
  - `SATB` Step 7 (`|sum(phases) - window| <= 1 µJ` phase-sum check),
  - Multi-tract `openie-cad` (`material` + `supply_chain` + `compute`) `JCR-1` chain + `efficiency/1` outcome receipt + `jcp_receipt::replay_ledger` crash-recovery state reconstruction.

---

## 3. Deliverable B: `MEI-JCP-Tag-v1` Open Hardware & Cold-Chain Verification

### 3.1 2-Layer Routed PCB (`cad-eda` + `cad-router`)

- **Board**: `32.0 mm × 24.0 mm`, 2-layer FR-4 (`F.Cu` + `B.Cu`), `0.18 mm` trace width, `0.30 mm` drill / `0.56 mm` diameter vias (`0.130 mm` annular ring >= `0.125 mm` minimum).
- **Components (10) & Nets (14)**: `U1` (`STM32WBA52CGU6`), `U2` (`INA238AIDR`), `R_SHUNT` (`100 mΩ 0.1%`), `U3` (`MB85RS256B` 256-Kb SPI FRAM), `RT1` (`10 kΩ` NTC), `R_BIAS` (`10 kΩ 0.1%`), `C1` (`100 nF`), `C2` (`1 µF`), `J1` (5-pin SWD/UART PTH header), `BT1` (`Keystone 3034` SMD `CR2032` holder on `B.Cu`).
- **Autorouting**: `32 / 32` (`100.0%`) Steiner connections routed (`135` track segments, `14` vias, `280.23 mm` total copper length).
- **DRC & Round-Trip**: `cad-eda` `DrcEngine` + `certify`: **0 errors, 0 warnings (`CERTIFIED`)**; `.kicad_pcb` round-trip via `import_kicad_pcb` recovers all `10` footprints, `135` tracks, and `14` vias; RS-274X Gerbers (`F_Cu`, `B_Cu`, `Edge_Cuts`, `8,801 B` total), Excellon `mei_jcp_tag_v1.drl`, `bom.csv`, `cpl.csv`, and `mei-jcp-tag-pcb.svg` emitted in `hardware/`.

### 3.2 Native 3D B-Rep Vented Cold-Chain Enclosure (`cad-kernel`)

- **Geometry**: Y-up base-seated `36.0 mm × 28.0 mm × 7.5 mm` shell (`1.6 mm` walls, `1.4 mm` floor) with `6.1 mm` blind interior pocket, `+X` lanyard mounting ear (`41.5 mm` overall X span, exact NURBS `Ø4.0 mm` bore), convective airflow window above `RT1`, symmetric lid snap-retention slots, and 4 internal PCB standoffs.
- **Physical Verification**: Closed outward-facing B-Rep solid, volume `2,702.12 mm³`, surface area `3,873.99 mm²`, ABS mass `2.837 g`, exported to `mei_jcp_tag_enclosure.step` (`174,694 B`), `mei_jcp_tag_enclosure.stl` (`42,684 B`, `852` triangles round-trip verified), and 4-view HLR engineering drawing `mei-jcp-tag-enclosure.svg`.

### 3.3 `CR2032` Electro-Thermal Simulation (`cad-sim::battery`) & `10,000`-Wakeup `JCP` Gate

| Ambient $T$ | $R_{\text{int}}$ (50% SOC) | 12 mA TX Terminal V (50% SOC) | Usable Energy to 2.00 V (12 mA) | Routine Beacons (`allow / refused`) | Safety-Critical Alerts (`allow / attempts`) | Sealed `JCR-1` Envelopes | `verify_log` & `replay_ledger` |
|---|---|---|---|---|---|---|---|
| `-20 °C` | `71.78 Ω` | `1.951 V` (`861.3 mV` sag) | `0.00 J` (pulse `< 2.00 V`) | `10 / 490` | `40 / 40` (`100.0%`) | `590` | `true / true` |
| `+4 °C` | `25.72 Ω` | `2.504 V` (`308.7 mV` sag) | `2,059.23 J` (`84.74%`) | `430 / 70` | `40 / 40` (`100.0%`) | `1,010` | `true / true` |
| `+25 °C` | `12.00 Ω` | `2.669 V` (`144.0 mV` sag) | `2,193.12 J` (`90.25%`) | `500 / 0` | `40 / 40` (`100.0%`) | `1,080` | `true / true` |

### 3.4 Build Pipeline `JCR-1` Ledger (`receipts/jcr1_build_and_coldchain_ledger.json`)

- **Total wall time**: `6,927.88 ms` (`6.93 s`) on `$BENCH_ROOT` (32-core Linux host).
- **Chain head (`seq 0..7`)**: `d5b3827b429093fd22bc2525e9f574aeb2f52411077ec221ecbc5ec20e01b2cd` (`8` verified `JCR-1` envelopes + `1` `efficiency/1` receipt, `0` unresolved holds, replayed total `439,853,502 µJ`).
- **Live Falsifier 6 & Two-Phase Settle Evidence**: Shared-host background power fluctuations (`7.24%–40.23%` across 1-second repeat windows) automatically triggered `Falsifier 6` (`satb_falsifier6_pass = 0`, omitting `satb_derived_marginal_uj` while sealing `satb_raw_counter_uj`), and `seq 6 → 7` recorded a real post-hold `MaxCostUj` caveat overrun (`268.23 J > 250.00 J` hold ceiling), debiting the full `268,226,638 µJ` while sealing `deny_reason = "caveat-unsatisfied"` per `JCP SPEC §4.9 / §8.1`.

---

## 4. Reproduction Commands (Run on `$BENCH_ROOT` Build Host)

```bash
# 1. Run all 310 tests in the standalone JCP + SATB + CAD spine workspace
cd $BENCH_ROOT/experiment_bundle/jcp-satb-cad-spine
cargo test --workspace

# 2. Apply and test the cad-joules bridge patch against openie-cad
cd $BENCH_ROOT/openie-cad
git apply --check $BENCH_ROOT/experiment_bundle/cad-joules-jcp-bridge.patch
git apply $BENCH_ROOT/experiment_bundle/cad-joules-jcp-bridge.patch
cargo test -p cad-joules

# 3. Regenerate all MEI-JCP-Tag-v1 PCB, 3D STEP/STL, battery sim, and JCR-1 receipts
cd $BENCH_ROOT/experiment_bundle/mei-jcp-tag-builder
cargo run --release -- $BENCH_ROOT/experiment_bundle
```
