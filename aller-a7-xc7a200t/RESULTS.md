# Numato Aller A7 (`XC7A200T-2FBG484C`) M.2 2280 Gateware Port, Cross-Target Equivalence & Electro-Thermal Envelope Audit

- **Target Hardware (Scale-Out Track):** Numato Aller A7 M.2 2280 M-Key (`AMD Artix-7 XC7A200T-2FBG484C`, `28nm HPL`, `VCCINT = 1.00 V`, `FBG484` `23 × 23 mm` lidless flip-chip BGA) + Particle Tachyon (`QCM6490`) `PCIe Gen2 ×1` FPC (`5V @ 2A` software-switched boost rail)
- **Reference Hardware (Validation Track):** AMD Kria KV260 SOM (`XCK26-SFVC784-2LV-C`, `16nm FinFET+`, `VCCINT = 0.72 V`) & AMD ZCU102 (`XCZU9EG-FFVB1156-2-E`, `VCCINT = 0.85 V`)
- **EDA Toolchains:** `Yosys 0.71+` (`synth_xilinx -family xc7` & `synth_xilinx -family xcup`) + `Verilator 5.054` (`--binary --trace`)
- **Epistemic & Provenance Separation:** **`basis = "est_j / est_mW / est_tj_c"` ONLY** (`board_metered = false`, `measured_j = null`, `vivado_post_par_wns_ns = null`). Host Linux RAPL synthesis compile counters are strictly quarantined under `eda_host_compile_reported_j` in `results/yosys_xc7_vs_xcup_synthesis.json` and never combined with FPGA rail estimates.

---

## 1. 7-Series `XC7A200T` RTL Retargeting Architecture (`rtl/`)

1. **`rtl/ramb36e1_shadow_bank.v`**:
   - Parameterized structural Block RAM wrapper (`xilinx_sdp_bram36_wrapper`, `TARGET_FAMILY = 0` $\to$ 7-Series `RAMB36E1` vs. `TARGET_FAMILY = 1` $\to$ UltraScale+ `RAMB36E2`) configured in `512 × 72-bit` Simple Dual-Port (`SDP`, `READ_FIRST`) mode (`4,096` data bytes + `512` byte-XOR parity bytes = `36 Kb`).
   - Enforces hardware `ENARDEN` read clock-enable (`CE`) gating (`rd_en`) and `ENBWREN`/`WEBWE` write gating (`wr_en`), eliminating unconditional idle bitline precharge.
   - `ramb36e1_shadow_bank`: Zero-stall dual-bank (`Active` / `Shadow` = `2 × RAMB36E1`) `4 KB` crystal store where background PCIe BAR0 updates write strictly to `~active_bank` while fast-path reads target `active_bank`, with 1-cycle atomic bank flip (`atomic_swap_pulse`).
2. **`rtl/compact_lut6_page_engine.v`**:
   - Hardware `4,096`-byte canonical `CompactLut6Page` (`lut6-core` binary ABI: `magic = "LUT6"`, `domain_hash`, `conformal_mask`, `conformal_thresh`, `num_layers`, `gates_per_layer`, `kill_max_rejects`, `routes_lo`, `routes_hi`, `init_masks`) evaluator.
   - 3-stage balanced pipeline (`II = 1`, `CPI = 1.00`, `12` combinational primitive levels max) with `FDRE` clock-enable (`CE`) bubble gating, zero `DSP48E1` slices, a parallel 6-input `LUT6` leaf popcount tree (`64 bits -> 7 bits`), Conformal Wake Gate (`votes >= conformal_thresh` $\to$ `OUTCOME_ACT` vs. `OUTCOME_ESCALATE` asserting `irq_conformal_wake`), and falsifier kill latch (`ledger_rejects >= kill_max_rejects` $\to$ `OUTCOME_KILLED` asserting `irq_verifier_killed`).
3. **`rtl/lut_adapt_xc7a200t_top.v`**:
   - Integrates the retargeted `81-RAMB36E1` 4-stage `512 × 512` Waksman/Beneš–Copy–Beneš speculative core (`clai_benes_axi_stream_xc7_top`) alongside `compact_lut6_page_engine` (`2 × RAMB36E1`, **`83 × RAMB36E1` total**), `0` `DSP48E1` slices, and explicit CMOS reset / power-down tie-offs (`ddr3_reset_n_tieoff = 0`, `ddr3_cke_tieoff = 0`, `ddr3_odt_tieoff = 0`, `ddr3_cs_n_tieoff = 1`) with **zero `MIG 7-Series` PHY or `SSTL15` `ODT` banks instantiated**.
   - Also provides `ramb36e1_crystal_vault_365`, instantiating all `365 × RAMB36E1` blocks on `XC7A200T-2FBG484C` with 1-hot `ENARDEN` bank gating.

---

## 2. Yosys `0.71+` Synthesis Audit (`xc7` vs. `xcup`) & Multi-FPGA Utilization

| Module | Yosys Family | Total LUTs | `LUT6` / `LUT5` / `LUT4` / `LUT3` / `LUT2` | `MUXF7`/`F8` | `CARRY4` | `FDRE` + `FDSE` | `RAMB36E1` / `E2` | `DSP48` | Sync Levels | `% XC7A200T` LUT / BRAM | `% XCK26` LUT / BRAM | `% XCZU9EG` LUT / BRAM |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `compact_lut6_page_engine` | `xc7` | `17,600` | `7,079 / 6,850 / 856 / 2,738 / 77` | `0 / 0` | `41` | `13,891 + 56` | **`2` / `0`** | **`0`** | **`12`** | `13.08%` / `0.55%` | `15.03%` / `1.39%` | `6.42%` / `0.22%` |
| `compact_lut6_page_engine` | `xcup` | `17,602` | `7,077 / 6,852 / 856 / 2,738 / 79` | `0 / 0` | `41` | `13,891 + 56` | `0` / **`2`** | **`0`** | **`12`** | `13.08%` / `0.55%` | `15.03%` / `1.39%` | `6.42%` / `0.22%` |
| `clai_benes_axi_stream_xc7_top` | `xc7` | `44,488` | `6,217 / 12,476 / 3,958 / 19,578 / 2,259` | `3 / 0` | `45` | `48,978 + 1` | **`81` / `0`** | **`0`** | **`13`** | `33.05%` / `22.19%` | `37.98%` / `56.25%` | `16.23%` / `8.88%` |
| `clai_benes_axi_stream_xc7_top` | `xcup` | `44,569` | `6,136 / 12,557 / 3,958 / 19,578 / 2,340` | `3 / 0` | `45` | `48,978 + 1` | `0` / **`81`** | **`0`** | **`13`** | `33.11%` / `22.19%` | `38.05%` / `56.25%` | `16.26%` / `8.88%` |
| **`lut_adapt_xc7a200t_top` (Unified)** | **`xc7`** | **`62,211`** | `13,390 / 19,195 / 4,882 / 22,391 / 2,353` | `3 / 0` | `86` | `63,056 + 57` | **`83` / `0`** | **`0`** | **`13`** | **`46.22%` / `22.74%`** | `53.12%` / `57.64%` | `22.70%` / `9.10%` |
| `lut_adapt_xc7a200t_top` (Unified) | `xcup` | `62,294` | `13,307 / 19,278 / 4,882 / 22,391 / 2,436` | `3 / 0` | `86` | `63,056 + 57` | `0` / **`83`** | **`0`** | **`13`** | `46.28%` / `22.74%` | `53.19%` / `57.64%` | `22.73%` / `9.10%` |
| `ramb36e1_crystal_vault_365` | `xc7` | `34,406` | `6,889 / 7,847 / 11,322 / 5,022 / 3,326` | `4 / 2` | `0` | `9 + 0` | **`365` / `0`** | **`0`** | **`11`** | **`25.56%` / `100.00%`** | `29.38%` / `253.47%` | `12.55%` / `40.02%` |

*(Zero `LUT1`, zero `RAMB18E1`/`RAMB18E2`, and **exact `0` `DSP48E1`/`DSP48E2` slices** across all 7 synthesized netlists. `lut_adapt_xc7a200t_top` uses `284 / 285` inferred standalone IOBs; inside PCIe gateware all AXI/CSR ports terminate internally on `PCIE_2_1`, using only `4` physical package pins for DDR3 reset tie-offs.)*

### On-Die `4 KB` `CompactLut6Page` Knowledge Crystal Capacity (`0` DDR3 Required)

Each canonical `4,096`-byte (`512 × 64-bit`) `CompactLut6Page` fits **1:1 inside one `36 Kb` (`512 × 72-bit` SDP) `RAMB36E1`/`RAMB36E2`**, with `512` bytes (`8` bits/word) of dedicated hardware byte-parity/ECC storage included:

| Target Device & Board | Process & Core Rail | Slice / CLB LUTs | `36 Kb` BRAM Blocks | Raw BRAM (`KB` incl. parity) | Usable `4 KB` Page Data (`KB`) | Max Active Single-Bank `4 KB` Crystals (BRAM) | Max Ping-Pong Active/Shadow Pairs | Free `4 KB` Crystals Alongside `81-BRAM` Beneš Core | Additional `URAM288` `4 KB` Pages |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **`XC7A200T-2FBG484C` (Numato Aller A7 M.2)** | `28nm HPL` (`1.00 V`) | **`134,600`** | **`365` `RAMB36E1`** | **`1,642.5 KB`** | **`1,460 KB`** | **`365` pages** | **`182` pairs** | **`284` pages** (`282` w/ `cl6`) | `0` (`0` URAM) |
| **`XCK26-SFVC784-2LV-C` (Kria KV260 SOM)** | `16nm FinFET+` (`0.72 V`) | `117,120` | `144` `RAMB36E2` | `648.0 KB` | `576 KB` | `144` pages | `72` pairs | `63` pages (`61` w/ `cl6`) | `+576` (`64` URAM288) |
| **`XCZU9EG-FFVB1156-2-E` (ZCU102 Flagship)** | `16nm FinFET+` (`0.85 V`) | `274,080` | `912` `RAMB36E2` | `4,104.0 KB` | `3,648 KB` | `912` pages | `456` pairs | `831` pages (`829` w/ `cl6`) | `0` (`0` URAM) |

- **Key Capacity Finding:** `XC7A200T` provides **`1.15×` more LUT6s** and **`2.53×` more `36 Kb` Block RAMs** than `Kria KV260` (`365` vs. `144` `RAMB36` blocks; **`4.51×` more remaining BRAM pages** after instantiating the `81-BRAM` Beneš core: `284` vs. `63` pages), holding **`1.46 MB` of zero-wait `CompactLut6Page` crystals entirely on-die** with external DDR3 powered down.

### Analytical `DS181` `-2` (`28nm`) vs. `DS925` `-2LV` (`16nm`) Critical-Path Timing Budget (`est_ns`)

- **`compact_lut6_page_engine` (`12` levels, pure `FDRE -> LUT6 -> FDRE`):** `4.34 est_ns` (`230.4 est_MHz`) on `XC7A200T-2` — closes **`100 MHz`, `150 MHz`, and `200 MHz`** directly; `2.699 est_ns` (`370.5 est_MHz`) on `XCK26-2LV`.
- **`lut_adapt_xc7a200t_top` (`13` levels + `RAMB36E1` launch):** `6.15 est_ns` (`162.6 est_MHz`) with `DOA_REG = 0` (closes **`100 MHz` & `150 MHz`**); **`4.98 est_ns` (`200.8 est_MHz`)** with `RAMB36E1` `DOA_REG = 1` (closes **`200 MHz`**); reaching `250 MHz` (`4.00 ns`) on `28nm` Artix-7 `-2` requires splitting the `13`-level Beneš half-stage into `7 + 6` levels (`+2` pipeline registers at `CPI = 1.00`).

---

## 3. Verilator `5.054` Cross-Target Functional Equivalence (`12,023` Cycles / `10,500` Vectors) & VCD Activity

Co-simulated **three targets simultaneously** in `Verilator 5.054` (`--trace`, `29,112` unique traced `dut` net codes = `170,630` internal bits):
1. `lut_adapt_xc7a200t_top #(.TARGET_FAMILY(0))` (`XC7A200T` `RAMB36E1` + DDR3 tie-offs),
2. `lut_adapt_xc7a200t_top #(.TARGET_FAMILY(1))` (`XCK26`/`XCZU9EG` `RAMB36E2`), and
3. Original untouched `KV260` `clai_benes_axi_stream_250mhz_top` SystemVerilog + Python `lut6-core` (`CompactLut6Page`) golden reference (`CRC32`: Crystal A = `0x2ADCDDA4`, Crystal B = `0x701F093F`).

- **Bit-Exact Cross-Target Equivalence:** **`0` bit mismatches across `12,023 / 12,023` clock cycles (`100.0000%` equivalence)** between `XC7A200T` (`RAMB36E1`) and `XCK26` (`RAMB36E2`), **`0` mismatches** against original `KV260` RTL (`209` `512-bit` Beneš packets), and **`0` mismatches across `10,500 / 10,500` active `CompactLut6Page` test vectors**!

| Operating Phase (`u_xc7` VCD Waveform) | Measured Cycles | Seq Transitions / Cycle (`alpha_seq`) | Comb Transitions / Cycle (`alpha_comb`) | Beneš `81-BRAM` Rd / Wr Duty | `CL6` `2-BRAM` Rd / Wr Duty | `XC7A200T` Gateware Dynamic (`est_pJ/cyc`) | `XC7A200T` Gateware Dynamic @ `250 MHz` (`est_mW` `[low, high]`) | `XC7` vs. `XCK26` Parity |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `1. ce_gated_idle` (`ENARDEN` + `FDRE` `CE`) | `1,499` | **`0.000`** (`0.000000`) | **`0.000`** (`0.000000`) | `0.00%` / `0.00%` | `0.00%` / `0.00%` | **`202.62`** (`711.8` ungated) | **`50.65`** `[36.37, 66.93]` (`177.96` ungated) | **`100.0%`** (`0` err) |
| `2. certified_lut6_fast_path_hit` (`CPI=1`) | `4,000` | `418.611` (`0.007314`) | `1,962.893` (`0.017310`) | `2.48%` / `0.00%` | `0.00%` / `0.00%` | **`236.27`** | **`59.07`** `[42.89, 77.85]` | **`100.0%`** (`0` err) |
| `3. shadow_page_hotswap_pcie_axi` (`4 KB` swap) | `3,504` | `466.989` (`0.008160`) | `2,259.340` (`0.019924`) | `3.14%` / `0.00%` | `0.91%` / `14.61%` | **`245.24`** | **`61.31`** `[44.65, 80.71]` | **`100.0%`** (`0` err) |
| `4. conformal_wake_gate_escalation` (+ kill) | `3,008` | `129.991` (`0.002271`) | `186.485` (`0.001645`) | `0.00%` / `0.00%` | `0.00%` / `0.00%` | **`204.80`** | **`51.20`** `[36.77, 67.68]` | **`100.0%`** (`0` err) |

- **Clock-Enable (`CE`) Gating Payoff on `28nm` `1.0V` Artix-7:** Gating `RAMB36E1` `ENARDEN` and pipeline `FDRE` `CE` collapses quiescent gateware dynamic power **`3.51×`** (`177.96 est_mW` $\to$ `50.65 est_mW` @ `250 MHz`; `71.18 est_mW` $\to$ `20.26 est_mW` @ `100 MHz`) with `0.000000` data-bit transitions/cycle!

---

## 4. `AMD DS181` + `UG475` (`FBG484`) Electro-Thermal & M.2 `3.3V` / Tachyon `5V @ 2A` Envelope (`est_mW` / `est_C`)

- **`UG475` Table 5-1 `XC7A200T-FBG484` (`23 × 23 mm` lidless flip-chip BGA):** $\theta_{JC\text{ (top)}} = 0.2\,^\circ\text{C/W}$, $\theta_{JB} = 5.9\,^\circ\text{C/W}$, open JEDEC 2S2P $\theta_{JA} = 17.6 / 14.8 / 14.1\,^\circ\text{C/W}$ (`0 / 200 / 400 LFM`).
- **M.2 `2280` (`22 × 80 mm` = `1,760 mm²` PCB) Effective $\theta_{JA,\text{eff}}$:** `23.5 °C/W` (`0 LFM` bare M.2 slot), `14.2 °C/W` (`0 LFM` passive Numato heatsink), `9.4 °C/W` (`200 LFM` + heatsink), `7.2 °C/W` (`400 LFM` + heatsink).
- **Coupled `DS181` Leakage Fixed Point:** Solved $T_J^* = T_A + \theta_{JA,\text{eff}} \cdot P_{\text{die}}(T_J^*)$ anchored to exact `DS181` `85 °C` quiescent currents ($I_{\text{CCINTQ}} = 328\text{ mA @ }1.0\text{V}$, $I_{\text{CCBRAMQ}} = 11\text{ mA @ }1.0\text{V}$, $I_{\text{CCAUXQ}} = 73\text{ mA @ }1.8\text{V}$, $I_{\text{CCOQ}} = 5\text{ mA @ }3.3\text{V} \implies 486.9\text{ mW}$ @ `85 °C`). Full `673`-row sweep in `results/aller_a7_power_thermal_envelope.csv`.

### Representative Operating Envelope Matrix (`board_metered = false`, `measured_j = null`)

| Mode (`PCIe` + `DDR3`) & Workload | Clock (`MHz`) | FPGA Die `est_mW` | M.2 `3.3V` `est_mW` (`est_mA` / `% 4.5A`) | Tachyon `5V` `est_mW` (`est_mA` / `% 2.0A`) | $T_A = 25\,^\circ\text{C}$ Bare `0 LFM` / Heatsink (`est_C`) | $T_A = 45\,^\circ\text{C}$ Bare `0 LFM` (`est_C` `[lo, hi]`) | $T_A = 45\,^\circ\text{C}$ Passive Heatsink (`est_C`) | $T_A = 45\,^\circ\text{C}$ `200 / 400 LFM` (`est_C`) | `< 85 °C` Safe in Bare `45 °C` Slot? |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| **Tachyon Cold-Rail GPIO OFF (`5V` Cut)** | `0` | **`0.0`** | **`0.0`** (`0.0 mA` / `0.0%`) | **`0.0`** (`0.0 mA` / `0.0%`) | `25.0` / `25.0` | **`45.0`** `[45.0, 45.0]` | **`45.0`** | `45.0` / `45.0` | **YES (`0 W` sleep)** |
| **`PCIe ×1` + `DDR3 Off` · `CE` Idle (`0%`)** | `100` | `651.7` | `791.2` (`239.8 mA` / `5.3%`) | `890.0` (`178.0 mA` / `8.9%`) | `39.1` / `33.2` | `61.1` `[58.8, 63.6]` | **`54.3`** | `51.0` / `49.6` | **YES (`+23.9 °C` margin)** |
| **`PCIe ×1` + `DDR3 Off` · Fast-Path (`100%`)** | `100` | `655.2` | `795.3` (`241.0 mA` / `5.4%`) | `894.4` (`178.9 mA` / `8.9%`) | `39.1` / `33.3` | `61.2` `[58.8, 63.8]` | **`54.3`** | `51.1` / `49.6` | **YES (`+23.8 °C` margin)** |
| **`PCIe ×1` + `DDR3 Off` · Fast-Path (`100%`)** | `150` | `674.2` | `816.8` (`247.5 mA` / `5.5%`) | `917.8` (`183.6 mA` / `9.2%`) | `39.6` / `33.6` | `61.6` `[59.2, 64.4]` | **`54.6`** | `51.2` / `49.7` | **YES (`+23.4 °C` margin)** |
| **`PCIe ×1` + `DDR3 Off` · Fast-Path (`100%`)** | `200` | `693.1` | `838.3` (`254.0 mA` / `5.7%`) | `941.2` (`188.3 mA` / `9.4%`) | `40.0` / `33.8` | `62.1` `[59.5, 65.0]` | **`54.9`** | `51.4` / `49.9` | **YES (`+22.9 °C` margin)** |
| **`PCIe ×1` + `DDR3 Off` · Hot-Swap (`100%`)** | `250` | **`714.5`** | **`862.6`** (`261.4 mA` / `5.8%`) | **`967.6`** (`193.5 mA` / `9.7%`) | `40.6` / `34.1` | `62.6` `[59.9, 65.7]` | **`55.2`** | `51.6` / `50.0` | **YES (`+22.4 °C` margin)** |
| `PCIe ×1` + `DDR3 Off` · Ungated Idle (`0%`) | `250` | `838.8` | `1,003.9` (`304.2 mA` / `6.8%`) | `1,121.2` (`224.2 mA` / `11.2%`) | `43.5` / `35.8` | `65.8` `[62.2, 70.0]` | `56.9` | `52.7` / `50.9` | YES (`+141 mW` waste) |
| **`PCIe ×4` + `DDR3 Off` · Hot-Swap (`100%`)** | `200` | `1,106.4` | `1,307.9` (`396.4 mA` / `8.8%`) | `1,451.7` (`290.3 mA` / `14.5%`) | `50.0` / `39.6` | `72.5` `[67.8, 78.0]` | **`60.7`** | `55.2` / `52.7` | **YES (Heatsink rec'd)** |
| **`PCIe ×4` + `DDR3 Off` · Hot-Swap (`100%`)** | `250` | `1,126.0` | `1,330.2` (`403.1 mA` / `9.0%`) | `1,475.9` (`295.2 mA` / `14.8%`) | `50.4` / `39.8` | `73.0` `[68.2, 78.6]` | **`61.0`** | `55.4` / `52.9` | **YES (Heatsink rec'd)** |
| `PCIe ×1` + `DDR3 Active` · Fast-Path (`100%`) | `200` | `1,431.2` | `2,046.3` (`620.1 mA` / `13.8%`) | `2,254.3` (`450.9 mA` / `22.5%`) | `60.6` / `45.6` | **`83.9`** `[77.0, 91.9]` | `67.0` | `59.2` / `55.8` | **MARGINAL (`91.9 °C` hi)** |
| `PCIe ×4` + `DDR3 Active` · Fast-Path (`100%`) | `100` | `1,811.3` | `2,478.2` (`751.0 mA` / `16.7%`) | `2,723.7` (`544.8 mA` / `27.2%`) | `70.0` / `50.9` | **`94.1`** `[85.0, 105.2]` | `72.4` | `62.6` / `58.3` | **FAILS `85 °C` (`>100 °C` hi)** |
| **`PCIe ×4` + `DDR3 Active` · Hot-Swap (`100%`)** | `250` | **`1,872.2`** | **`2,547.5`** (`772.0 mA` / `17.2%`) | **`2,799.0`** (`559.8 mA` / `28.0%`) | `71.5` / `51.7` | **`95.8`** `[86.1, 107.7]` | `73.2` | **`63.2` / `58.8`** | **FAILS `85 °C` (Airflow req'd)** |

*(Note: Die/rail power columns above are quoted at the $T_A = 45\,^\circ\text{C}$ passive Numato heatsink operating point; bare-slot self-heating raises static leakage by `+34` to `+175 est_mW`, as recorded in `results/aller_a7_power_thermal_envelope.csv`.)*

### Engineering Envelope Conclusions

1. **Pure-BRAM (`DDR3 Disabled`) + `PCIe Gen2 ×1` Unlocks Passive Sealed-Enclosure Operation:** Holding the external Micron `MT41J128M16` DDR3 in CMOS reset (`CKE=0, RST#=0`, `0` MIG PHY) and running 1 GTP lane (`PCIe Gen2 ×1` on Particle Tachyon) eliminates **`+1,395 mW` of non-compute FPGA + DRAM heat** (`680 mW` MIG PHY + `330 mW` DRAM + `385 mW` unused 3 GTP lanes), keeping `XC7A200T` junction temperature at **`54.3–55.2 est_C`** (`~30 °C` below the `85 °C` commercial rating) inside a `45 °C` enclosure with only the passive Numato heatsink (`61.1–62.6 est_C` even in a `0 LFM` bare slot).
2. **When Heatsink & Forced Airflow Are Mandatory:** Whenever `DDR3` (`800 MT/s`) is enabled alongside `PCIe ×4` inside a `45 °C` enclosure, a bare `0 LFM` M.2 slot **violates the `85 °C` commercial junction limit across all frequencies (`100–250 MHz`, reaching `94.1–95.8 est_C` nominal and `105.2–107.7 est_C` upper bound)**. The passive Numato heatsink is **strictly mandatory** whenever `DDR3` or `PCIe ×4` is active (`72.4–73.2 est_C` nominal), and **`>= 200 LFM` (`1.0 m/s`) forced airflow** is required to restore a `> 20 °C` safety margin (`62.6–63.2 est_C`).
3. **Abundant Electrical Headroom on M.2 `3.3V` & Particle Tachyon `5V @ 2A` Rails:** Peak pure-BRAM operation on Particle Tachyon (`200–250 MHz`, `100%` lookup + hot-swap burst) draws only **`254–261 est_mA` on M.2 `3.3V`** (`5.8%` of `4.5 A` 9-pin rating; `10.5%` of `2.5 A` conservative CEM slot limit) and **`188–194 est_mA` (`0.94–0.97 est_W`) on Tachyon's shared `5V @ 2A` (`10 W`) PCIe FPC boost regulator** — leaving **`> 1.80 A` (`> 9.0 W`, `> 90%`)** continuous budget for 40-pin expansion HATs, with **`0.00 W` cold-rail cutoff** when Tachyon switches its PCIe `5V` rail off in software.

---

## 5. Physical Hardware Metering & Falsifier Protocol (`est_j` $\to$ `measured_j`)

To promote these pre-validation `est_mW` / `est_tj_c` bounds to `measured_j` (`board_metered = true`) once the physical Numato Aller A7 M.2 module is attached to the Particle Tachyon PCIe FPC adapter:
1. **Inline `3.3V` & `5V` Shunt Telemetry:** Interpose an M.2 M-Key PCIe Gen2 riser carrying a Kelvin-sensed `10 mΩ` (`0.1%`) high-side shunt on the `+3.3V` supply pins monitored by a **`TI INA228` / `INA226`** (`20-bit`/`16-bit` I2C power monitor at `>= 1 kHz` sampling) or **`PowerSensor3`**, paired with a second shunt on Particle Tachyon's shared `5V` PCIe FPC rail.
2. **Dual-Sensor Junction & Case Thermometry:** Continuously poll the on-die 7-Series **`XADC` (`SYSMON` register `0x00`, $\pm 4\,^\circ\text{C}$)** over PCIe AXI-XADC / JTAG alongside a fine-wire **Type-K thermocouple** bonded to the lidless `FBG484` die perimeter / Numato heatsink base.
3. **Pre-Registered Falsifiers:**
   - **`F_EQV_1`:** Any bit mismatch (`> 0`) between `XC7A200T` (`RAMB36E1`) and `XCK26` (`RAMB36E2`) hardware outputs across the `10,500`-vector suite.
   - **`F_PWR_1`:** Metered M.2 `3.3V` sustained current `> 1,000 mA` (`3.3 W`) in `DDR3-Disabled` + `PCIe ×1` mode.
   - **`F_PWR_2`:** Combined Particle Tachyon `5V` PCIe FPC + 40-pin HAT current `> 1,600 mA` (`80%` continuous derating of the `2.0 A` boost ceiling).
   - **`F_THM_1`:** Steady-state `XADC` $T_J \ge 85.0\,^\circ\text{C}$ under passive Numato heatsink at $T_A \le 45\,^\circ\text{C}$ in `DDR3-Disabled` mode (triggers mandatory `>= 200 LFM` fan crossflow or `150 MHz` clock step-down).
