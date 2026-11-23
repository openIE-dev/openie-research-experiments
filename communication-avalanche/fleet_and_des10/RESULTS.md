# Executed Hardware Benchmark Report: 5-Host Fleet Energy (`CTA-E4`) & 10 Siloed AI Camps vs. Digital Enzymatic Synthesis (`CTA-E5`)

- **Study**: #21 - *The Communication Tool Avalanche: Thresholded Signal Externalization, Event-Driven Orchestration, and Coherence per Joule* (`communication-avalanche`)
- **Pre-Registration Lock**: `PREREG_cta_e4_e5.json` (`SHA-256 = 3efe68407530d203d7e8a6a1f13d9943713f763fe24034301f85e5330bb2a65b`, locked prior to executing `CTA-E4` and `CTA-E5`)
- **Frozen `100`-Task + `15`-Calibration Corpus**: `cta_e5_corpus.py` (`corpus_sha256 = 79b7f7512c3a5e18eb8a13ed5323d7803a9538decf665a213ced6abdf87eb8d2`, `0` overlap between `15` calibration probes and `100` test tasks)
- **Compiled Cross-Platform Rust Engine**: `cta_fleet_rust v0.2.0` (`rustc 1.100.0` across Linux `aarch64`, Linux `x86_64`, macOS `arm64` Darwin, and Windows 11 `x86_64`)
- **Strict Separation Grammar**:
  - `measured_j` (`board_metered = true`): Populated **strictly** on `NVIDIA Jetson AGX Thor` via physical Texas Instruments `INA3221` channel-2 `VDD_CPU_SOC_MSS` (`L2`) and `INA238` whole-board `VIN` (`L1`) shunt sensors (`CUDA_VISIBLE_DEVICES=""` CPU-only respecting active `GPU_ACTIVE` co-tenant lock).
  - `reported_j` (`board_metered = false`): Populated on `Intel Core i9-13900H` (`intel-rapl:0` `package-0` & `intel-rapl:0:0` `core`), `AMD Ryzen AI Max+ 395` (`intel-rapl:0` APU socket, `intel-rapl:0:0` `core`, & `amdgpu` `PPT`), `Apple M3 Ultra` (`proc_pid_rusage(RUSAGE_INFO_V6).ri_energy_nj` `L3` per-process under `memguard`), and `Windows 11 Pro x86-64` (`nvml.dll` `RTX 2060` cumulative `mJ` `L2` + `QueryProcessCycleTime` `L3`).
  - `measured_j`, `reported_j`, and remote cloud tokens/USD are reported in strictly separate columns and **never summed**.

---

## 1. Pre-Registered Falsifier Verdicts (`F1` to `F6`)

| Falsifier | Pre-Registered Criterion | Empirical Result | Verdict |
| :--- | :--- | :--- | :--- |
| **`F1` (`CTA-E4` Zero-Clock Fleet)** | Zero-clock OS-event threshold (`eventfd` / `kqueue`+pipe / Win32 `Event`) eliminates empty polling wakeups and lowers CPU/rail energy vs. `1,000 Hz` polling (`5.0 s` × `4` AB/BA pairs, `1%` duty) | `0.0` empty wakeups across all `5` hosts (`268–285` vs. `54,132–75,587` wakeups); Thor `VDD_CPU_SOC_MSS` `measured_j`: `63.72 J` (`12.74 W`) vs. `65.07 J` (`13.01 W`, mean `+1.34 J`/win; `INA238` `VIN` `+6.69 J`/win); `i9-13900H` `RAPL` `pkg`: `25.50 J` vs. `82.00 J` (`3.22x`); `M3 Ultra` `ri_energy_nj`: `26.1 mJ` vs. `162.4 mJ` (`6.22x`) | **Supported (`F1` not triggered)** |
| **`F2` (`CTA-E4` Fleet Attestation)** | Rust `BLAKE3` (`256`-bit) + `Ed25519` (`64`-byte RFC `8032`) verify stays `< 100 µs` and `< 5 mJ` at `1 KiB` & `16 KiB` across all `5` hosts (`50,000` iters) | `p50` verify: `23.84–50.13 µs` (`1 KiB`) and `26.16–62.24 µs` (`16 KiB`); Thor `VDD_CPU_SOC_MSS` `measured_j`: `0.927 mJ` (`1 KiB`) & `0.880 mJ` (`16 KiB`), `VIN` `3.885–4.222 mJ`; `reported_j`: `90.81 µJ` (`M3 Ultra`) to `4.760 mJ` (`Zen 5` shared APU) | **Supported (`F2` not triggered)** |
| **`F3` (`CTA-E5` Oracle & LUT Isolation)** | Zero access to `100`-task held-out test oracles by any camp or `V_gate`; `0` overlap with `15` calibration probes | Structurally enforced in `cta_e5_corpus.py`; `0` task overlap asserted (`len(test & cal) == 0`) | **Supported (`F3` not triggered)** |
| **`F4` (`CTA-E5` 10 Camps vs. `DES-10`)** | No solo camp (`C1`–`C10`) matches `DES-10` on pass rate, false-commit containment, and end-to-end `CpJ` | Solo ceiling `<= 49%` (`C1`: `48%` pass / `52%` false commits; `C9`: `49%` pass / `51%` false commits; deterministic specialists `10–30%` pass / `0%` false commits). **`DES-10`: `98 / 100` (`98%`) pass, `1%` false commits (`0%` on `R1`–`R4`), `9.25–9.26x` higher `CpJ` than `C1` and `26.87–27.13x` higher `CpJ` than `C9`** on both hosts | **Supported (`F4` not triggered)** |
| **`F5` (`CTA-E5` Enzymatic Barrier)** | `Digital Enzyme` binary IR + `BLAKE3`+`Ed25519` achieves `> 10,000x` latency & local-energy reduction vs. `Camp 9` live NL LLM handoff | **`i9-13900H` (`reported_j`)**: `23.00 µs` / `0.689 mJ` (`44.43 µs` / `1.140 mJ` pipe) vs. `3,577.58 ms` / `36.38 J` = **`155,554x` latency & `52,815x` energy (`31,921x` pipe)**. **`Jetson Thor` (`measured_j`)**: `49.95 µs` / `0.732 mJ` (`186.98 µs` / `3.406 mJ` pipe) vs. `3,938.49 ms` / `55.14 J` `VDD_CPU_SOC_MSS` = **`78,855x` latency & `75,374x` energy (`16,189x` pipe)** | **Supported (`F5` not triggered)** |
| **`F6` (Shared-Host & Drift Guard)** | Withhold single-window `A2` net idle subtraction whenever co-tenant lock is active or `5.0 s` pre/post idle drifts `> 10.0%` | Enforced on `Jetson Thor` (`GPU_ACTIVE` co-tenant lock active), `M3 Ultra` (`L3` near-zero idle denominator `0.4 mW -> 0.0 mW`), and `CTA-E5` `i9-13900H` (`25.79%` drift); raw unsubtracted rails & AB/BA paired deltas reported | **Enforced transparently** |

**Execution notes**:
1. On `djc-asus-rog`, `/tmp` `tmpfs` had a co-tenant `5.9 GiB` VCD job near user `tmpfs` quota; `run_cta_e4_fleet_energy.py` used `/var/tmp/wave5b_cta_e4` on NVMe (`0` benchmark logic changes).
2. During initial `CTA-E5` cache warm-up with `Claude Sonnet 5.5`, the in-code `\$1.90` spend circuit breaker halted safely at `\$1.9092`. To keep cumulative cloud API spend strictly `< \$2.00`, `CTA-E5` executed its complete `474`-entry cache + live handoff benchmark on pre-approved `GPT-OSS-120B` (`temperature = 0.0`, `reasoning_effort = "low"`, total `CTA-E5` cloud spend `\$0.1248`). All remote scratch directories across all `5` hosts were removed upon completion.

---

## 2. `CTA-E4`: 5-Host Cross-Silicon Fleet Energy Audit Summary

| Host & Architecture | OS Event Primitive | Telemetry Grammar (`board_metered`) | `1 KiB` / `16 KiB` Verify `p50` (`µs`) | `1 KiB` / `16 KiB` Energy per Edge | `5.0 s` DAG Zero-Clock vs. `1,000 Hz` Poll (`1%` Duty, `4` Pairs) | Wakeups (`Event` vs. `1 kHz`) | `p50` Commit Latency (`ms`) |
| :--- | :--- | :--- | ---: | ---: | :--- | ---: | ---: |
| **NVIDIA Jetson AGX Thor** (`aarch64` Tegra, CPU-only) | `linux_eventfd` | **`measured_j`** (`true`, `INA3221` `VDD_CPU_SOC_MSS` `L2` / `INA238` `VIN` `L1`) | `50.13` / `62.24 µs` | **`927.30` / `879.53 µJ`** (`CPU_SOC`); `3.89` / `4.22 mJ` (`VIN`) | **`63.72 J` (`12.74 W`) vs. `65.07 J` (`13.01 W`)** `CPU_SOC` (`+1.34 J`/win; `VIN`: `344.02` vs. `350.71 J`, `+6.69 J`/win) | **`284.5`** (`0` empty) vs. `75,140.8` | **`5.28`** vs. `10.04 ms` |
| **Intel Core i9-13900H** (`20t` Raptor Lake Linux) | `linux_eventfd` | `reported_j` (`false`, `intel-rapl:0` `pkg` / `0:0` `core`) | `23.84` / `26.16 µs` | `642.38` / `700.36 µJ` (`pkg`); `550.59` / `599.56 µJ` (`core`) | **`25.50 J` (`5.10 W`) vs. `82.00 J` (`16.40 W`)** `pkg` (`3.22x`; `core`: `6.27 J` vs. `62.52 J`, `9.97x`, `4/4` pairs `+`) | **`275.5`** (`0` empty) vs. `75,035.0` | **`2.45`** vs. `7.30 ms` |
| **AMD Ryzen AI Max+ 395** (`32t` Zen 5 + Radeon 8060S) | `linux_eventfd` | `reported_j` (`false`, `intel-rapl:0:0` `core` + shared APU `pkg`/`PPT`) | `33.12` / `31.83 µs` | **`201.27` / `156.84 µJ`** (`core`); `4.76` / `3.78 mJ` (shared `120 W` APU `pkg`) | `CPU` time **`623.7 ms` vs. `1,040.8 ms`** (`1.67x` reduction; shared `120 W` APU co-tenant masks socket rail) | **`279.8`** (`0` empty) vs. `75,587.2` | **`2.52`** vs. `7.39 ms` |
| **Apple M3 Ultra** (`arm64` Darwin XNU, `memguard`) | `darwin_kqueue_pipe` | `reported_j` (`false`, Darwin `RUSAGE_INFO_V6` `ri_energy_nj` `L3`) | `29.54` / `36.88 µs` | **`90.81` / `108.66 µJ`** (`L3` process) | **`0.0261 J` (`5.2 mW`) vs. `0.1624 J` (`32.5 mW`)** (`6.22x` `L3` reduction, `4/4` pairs `+`; CPU `232` vs. `1,245 ms`) | **`274.8`** (`0` empty) vs. `54,132.2` | **`6.82`** vs. `13.29 ms` |
| **Windows 11 Pro x86-64** (`Bare-Metal` + `RTX 2060`) | `win32_event_wait` | `reported_j` (`false`, `nvml.dll` `mJ` `L2` + `QueryProcessCycleTime` `L3`) | `30.50` / `30.90 µs` | `93,236` / `95,631` CPU cycles; `255.62` / `259.76 µJ` (idle GPU `L2`) | `CPU` time **`89.84 ms` vs. `335.94 ms`** (`3.74x` reduction; idle `RTX 2060` `L2` steady at `38.57` vs. `38.62 J`) | **`268.2`** (`0` empty) vs. `54,414.0` | **`2.41`** vs. `10.35 ms` |

---

## 3. `CTA-E5`: 10 Siloed AI Paradigm Camps vs. `DES-10` (`100` Tasks × `11` Arms × `2` Hosts = `2,200` Episodes)

| Arm (`100` Tasks: `20` each `R1`–`R5`) | Verified Pass (`R1`/`R2`/`R3`/`R4`/`R5`) | False Commits | LLM Calls & Tokens (`USD`) | `i9-13900H` Local / End-to-End `pkg_reported_j` | `i9-13900H` `CpJ_e2e` (`tasks/J`) | `Jetson Thor` Local / End-to-End `VDD_CPU_SOC_MSS` **`measured_j`** (`INA238` `VIN` **`measured_j`**) | `Jetson Thor` `CpJ_e2e` (`tasks/J`) |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| `C1` Autoregressive LLM Solo (`GPT-OSS-120B`) | `48%` (`17`/`1`/`1`/`11`/`18`) | `52%` | `100` / `67.1k` (`\$0.0359`) | `0.110 J` / `3,637.81 J` | `0.0132` | `0.079 J` / `5,513.77 J` (`28,161.53 J` `VIN`) | `0.0087` |
| `C2` Symbolic Constraint Solo (`FD/SAT`) | `30%` (`0`/`10`/`20`/`0`/`0`) | **`0%`** | `0` / `0` (`\$0.00`) | `0.087 J` / `0.09 J` | `346.6885` | `0.070 J` / `0.07 J` (`0.33 J` `VIN`) | `429.5963` |
| `C3` Latent EBM Scorer Solo (Unverified) | `0%` (`0`/`0`/`0`/`0`/`0`) | `100%` | `0` / `0` (`\$0.00`) | `5.156 J` / `5.16 J` | `0.0000` | `3.991 J` / `3.99 J` (`17.61 J` `VIN`) | `0.0000` |
| `C4` MCTS Rollout Search Solo (`UCB1`, `256`) | `11%`\* (`0`/`0`/`1`\*`/`10`/`0`) | `19%`\* | `0` / `0` (`\$0.00`) | `0.785 J` / `0.78 J` | `14.0197` | `0.617 J` / `0.62 J` (`2.43 J` `VIN`) | `16.2199` |
| `C5` Episodic Case Store Solo (`Shape D`) | `16%` (`16`/`0`/`0`/`0`/`0`) | **`0%`** | `0` / `0` (`\$0.00`) | `0.005 J` / `0.005 J` | `3,363.4644` | `0.003 J` / `0.003 J` (`0.012 J` `VIN`) | `6,254.8866` |
| `C6` Evolutionary AST Mutator Solo (`300` evals) | `4%` (`0`/`0`/`0`/`0`/`4`) | `20%` | `0` / `0` (`\$0.00`) | `5.959 J` / `5.96 J` | `0.6713` | `4.936 J` / `4.94 J` (`22.13 J` `VIN`) | `0.8104` |
| `C7` Causal Bayesian `do(X)` Solo | `10%` (`0`/`0`/`0`/`10`/`0`) | **`0%`** | `0` / `0` (`\$0.00`) | `0.003 J` / `0.003 J` | `3,980.8917` | `0.002 J` / `0.002 J` (`0.007 J` `VIN`) | `6,506.1809` |
| `C8` Sub-Symbolic `LUT6`/FSM Automaton Solo | `20%` (`0`/`20`/`0`/`0`/`0`) | **`0%`** | `0` / `0` (`\$0.00`) | `0.010 J` / `0.010 J` | `1,974.7235` | `0.009 J` / `0.009 J` (`0.041 J` `VIN`) | `2,218.5247` |
| `C9` Multi-Agent NL Debate Solo (`3`-Agent) | `49%` (`19`/`1`/`0`/`12`/`17`) | `51%` | `300` / `254.0k` (`\$0.1282`) | `0.116 J` / `10,913.22 J` | `0.0045` | `0.120 J` / `16,541.19 J` (`84,483.80 J` `VIN`) | `0.0030` |
| `C10` Embodied Sandbox Perturb Solo (`200` probes) | `4%` (`0`/`0`/`0`/`0`/`4`) | `30%` | `0` / `0` (`\$0.00`) | `3.243 J` / `3.24 J` | `1.2334` | `3.045 J` / `3.05 J` (`13.39 J` `VIN`) | `1.3135` |
| **`DES-10` (`Digital Enzymatic Composite`)** | **`98%` (`20`/`20`/`20`/`20`/`18`)** | **`1%`** | **`22` / `12.7k` (`\$0.0067`)** | **`2.155 J` / `802.45 J`** | **`0.1221`** | **`2.760 J` / `1,215.77 J` (`6,208.87 J` `VIN`)** | **`0.0806`** |

\*On `Jetson Thor` (`Python 3.12` string hash seed), `C4_MCTS_Rollout_Search_Solo` scored `10%` pass (`R3: 0/20`, `R4: 10/20`) and `20%` false commits; all other `10` arms produced identical pass/false-commit counts across both `x86_64` and `aarch64` hosts.
