# LUT-Adapt Wave 5 (`§4.16`) Results: `xck26-sfvc784-2LV-c` Verilator VCD Toggle-Rate & Datasheet `est_j` Audit

- **Pre-registration ID:** `lut-adapt-wave5-xck26-vcd-est-audit-2026-11-23`
- **Pre-registration SHA-256:** `c64505d177515c47770965ef3ef9fb100b73384d164c6149607f1d39aa138f71` (locked prior to execution)
- **Recorded (UTC):** `2026-11-23T12:20:14Z`
- **Source Repository & Commit:** `https://github.com/openIE-dev/lut-adapt-ai` at `af152ba2e63b5c55bcfad9b2fa41e675e8e3946c`
- **Target Device & Nominal Operating Point:** AMD Kria KV260 SOM (`xck26-sfvc784-2LV-c`, `-2LV` speed grade, `VCCINT = 0.72 V`, `VCCBRAM = 0.85 V`, `f_clk = 250.0 MHz` / `4.000 ns`)
- **EDA Toolchains:** `Yosys 0.71+` (`synth_xilinx -family xcup` + `ltp -noff`) + `Verilator 5.054` (`--binary --timing --trace`)
- **Strict Evidence Separation:** **`basis = "est_j"` ONLY** (`measured_j = null`, `reported_j = null`, `board_metered = false`, not Vivado post-PAR timing closure or vector-annotated `report_power`).

## 1. Yosys `xcup` Primitive Inventory & Verilator VCD Trace Coverage

| Module | `xcup` CLB LUTs (`% xck26`) | `MUXF7`/`F8` | `CARRY8` Equiv | `FDRE`/`FDSE` (`%`) | `RAMB36E2` (`%`) | `DSP48E2` | Unique VCD Nets (`dut` Bits) | Co-Sim Errors |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `clai_benes_paged_hotswap_core` (`512` pages) | `41,623` (`35.54%`) | `32` / `16` | `23` (`45 CARRY4`) | `36,464` (`15.57%`) | `81` (`56.25%`) | `0` | `27,157` (`90,124` b) | `0` (`3,072` lookups) |
| `clai_kv260_axi_top` (`AXI4` Rung-0 subsys) | `66,881` (`57.10%`) | `18` / `3` | `285` (`569 CARRY4`) | `16,619` (`7.09%`) | `4` (`2.78%`) | `0` | `3,825` (`128,486` b) | `0` (`CLAI` + stream) |

## 2. Four-Phase VCD Toggle Rates & Activity-Calibrated Dynamic Power (`est_pJ/cycle` & `est_mW` @ `250 MHz`)

| Module & Workload Phase | Cycles | Comb Transitions / Cycle (`alpha_comb`) | Seq Transitions / Cycle (`alpha_seq`) | BRAM Read / Write Duty | Clock + Seq + Comb (`est_pJ/cyc`) | `RAMB36E2` (`est_pJ/cyc`) | Total Dynamic (`est_pJ/cyc`) | Dynamic Power @ `250 MHz` (`est_mW` `[low, high]`) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **`clai_benes_paged_hotswap_core`** | | | | | | | | |
| `idle_quiescent` (as-written `EN=1`) | `256` | `0.00` (`0.000000`) | `0.00` (`0.000000`) | `0.0%` / `0.0%` | `41.59 + 0 + 0` | `200.07` (`12.15` CE-gated) | **`241.66`** (`53.74` CE) | **`60.41`** `[47.25, 76.21]` (`13.43` CE-gated) |
| `steady_lut6_eval_2048_cycles` (`CPI=1`) | `2,048` | `5,010.17` (`0.078035`) | `90.97` (`0.004387`) | `100.0%` / `0.0%` | `41.59 + 0.50 + 11.80` | `307.80` | **`361.68`** | **`90.42`** `[69.29, 116.04]` |
| `single_cycle_page_switch_512_burst` | `512` | `12,406.83` (`0.193241`) | `269.46` (`0.012996`) | `100.0%` / `0.0%` | `41.59 + 1.47 + 29.21` | `307.80` | **`380.07`** | **`95.02`** `[72.58, 122.60]` |
| `shadow_page_stream_write` | `512` | `1,987.33` (`0.030953`) | `35.98` (`0.001735`) | `100.0%` / `100.0%` (`1/81`) | `41.59 + 0.20 + 4.68` | `312.40` | **`358.86`** | **`89.72`** `[68.82, 114.89]` |
| **`clai_kv260_axi_top`** | | | | | | | | |
| `idle_quiescent` (`EN` gated) | `256` | `0.00` (`0.000000`) | `0.00` (`0.000000`) | `0.0%` / `0.0%` | `18.95 + 0 + 0` | `0.60` | **`19.55`** | **`4.89`** `[4.89, 4.89]` |
| `steady_lut6_eval_2048_cycles` (`31B` pkts) | `2,048` | `120.31` (`0.001108`) | `44.62` (`0.002258`) | `3.12%` / `0.0%` | `18.95 + 0.12 + 0.27` | `1.06` | **`20.40`** | **`5.10`** `[5.04, 5.18]` |
| `single_cycle_page_switch_512_burst` (`8B`+swap) | `512` | `325.21` (`0.002995`) | `60.66` (`0.003069`) | `11.13%` / `0.0%` | `18.95 + 0.16 + 0.73` | `2.23` | **`22.07`** | **`5.52`** `[5.34, 5.75]` |
| `shadow_page_stream_write` (`AXI4` prog) | `512` | `198.84` (`0.001831`) | `71.92` (`0.003639`) | `5.86%` / `8.20%` (`2/4`) | `18.95 + 0.19 + 0.45` | `2.21` | **`21.80`** | **`5.45`** `[5.30, 5.64]` |

## 3. Key Hardware & Analytical `DS925` `-2LV` Findings

1. **Event-gated vs. unconditional BRAM read enable (`4.50×` quiescent gap):** `clai_engram_streamer` gates its `4` `RAMB36E2` read ports on `accept_byte && s_axis_tlast` (`3.12%` read duty on `31`-byte packets; `0%` in `idle_quiescent`, `4.89 est_mW`), and registers `core_bus_reg` once per packet so `66,881` combinational LUTs toggle at only `0.0011–0.0030` transitions/bit/cycle (`5.10–5.52 est_mW` active). By contrast, `clai_uram_lut6_page_cache` leaves `ENARDEN = 1'b1` continuously asserted across all `81` `RAMB36E2`s (`60.41 est_mW` quiescent vs. `90.42–95.02 est_mW` active); gating `ENARDEN` with `bus_valid` reduces quiescent dynamic power `4.50×` to `13.43 est_mW`.
2. **Analytical `DS925` `-2LV` logic-stage delay budget (`0.72 V`, not Vivado post-PAR):** Using `T_ILO = 0.068 ns`, `T_CKO = 0.148 ns`, `RAMB36E2` `T_RCKO_DO = 1.390 ns` (`0.610 ns` with `DOA_REG = 1`), and `0.145–0.220 ns/level` interconnect estimates, the unpipelined `81`-level Beneš–Copy–Beneš path spans `18.76–24.83 est_ns` (`40.3–53.3 MHz` analytical `est_Fmax`) and the flattened `162`-level `clai_kv260_axi_top` path (spanning `clai_rung0_core` + the unrolled `64`-iteration serial `pop_acc` adder chain, vs. `73` levels per hierarchical sub-module) spans `34.77–46.92 est_ns` (`21.3–28.8 MHz`). Enabling `RAMB36E2` `DOA_REG = 1` + `4`–`5` pipeline stages (`<= 18` levels/stage) in `clai_benes_paged_hotswap_core` and replacing the serial `64`-add loop in `clai_kv260_axi_top` with a `6`-level Wallace/LUT6 compressor + `2` pipeline registers brings per-stage analytical delay below `3.7 est_ns` (`<= 4.000 ns` `250 MHz` budget) at `CPI = 1.0`.
3. **Falsifiers:** `F1 = false` (`0` co-sim errors), `F2 = false` (`0.000000` quiescent data toggle rate), `F3 = false` (`est_j` strictly isolated from `measured_j = null` and `reported_j = null`).
