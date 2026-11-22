# RCE-JEPA Hypothesis `H15` + `Shape D` (`DNULLMM1`) Gear-0 on the 40 Open Residual Tasks

- **Registration**: `PREREG.json` (`sha256: b64c4c671ae85755109c9b5b75b34cda3929a6138dcd525e4640db2085d58f49`), pinned before execution.
- **Engine & Gate**: `openIE-dev/rce` commit `1762fb4b` (`2026-11-20`), binary `sha256: 1d3b0d07ff5b2e8f...`, spec draft `0.9`.
- **Corpus**: `40` open residual tasks (`sha256: 3ca3a32769145e9b...`) left unsolved by `rce repair` rungs `a..e` (`111/151` solved in `rce/bench/ladder/rung-e/`, plain arm).
- **Energy Provenance**: Local Apple M5 Max counters (`proc_pid_rusage` `L3` `ri_energy_nj` label `D` + `macmon` `IOReport` `L2` label `A2`) are `reported_j`; remote cloud server energy is strictly `not_available` (`SATB` label `N`); `measured_j = None` (`board_metered = false`).

## 1. Equal-Budget (`k = 1` Single-Shot) Proposer Comparison (`H15`) + Cold/Warm `Shape D` Gear-0

| Arm / Architecture Class | Model | Calls | Admitted (`C(z)=1`) | Restored + Beh-Eq | Input / Output Tok | Cost (USD) | On-Chip `reported_j` |
|---|---|---:|---:|---:|---:|---:|---:|
| **Arm 0**: `Shape D` Cold Static Gear-0 | `DNULLMM1` (`0` records) + `a..e` | `0` | `0 / 40` (`0.0%`) | `0` | `0 / 0` | `$0.0000` | `< 0.001 J` (probe) |
| `arm1a_claude_opus_5_5` (Cloud Frontier Autoregressive + Adaptive Thinking (Anthropic)) | `claude-opus-5-5` | `40` | **`34 / 40` (`85.0%`)** | `33` (`30` + `3`) | `114,855 / 32,159` | `$1.3782` | `not_available` (cloud `N`) |
| `arm1b_claude_sonnet_5_5` (Cloud Frontier Autoregressive + Adaptive Thinking (Anthropic)) | `claude-sonnet-5-5` | `40` | **`32 / 40` (`80.0%`)** | `32` (`30` + `2`) | `114,855 / 30,764` | `$0.8060` | `not_available` (cloud `N`) |
| `arm2a_openai_gpt_oss_120b` (Cloud Reasoning MoE (OpenAI GPT-OSS-120B on Cerebras)) | `cerebras:gpt-oss-120b` | `40` | **`29 / 40` (`72.5%`)** | `27` (`25` + `2`) | `78,825 / 43,596` | `$0.1340` | `not_available` (cloud `N`) |
| `arm2b_deepseek_v4p1` (Cloud MLA Sparse MoE (DeepSeek V4.1 on Fireworks)) | `fireworks:accounts/fireworks/models/deepseek-v4p1-flash` | `40` | **`17 / 40` (`42.5%`)** | `16` (`15` + `1`) | `63,446 / 64,215` | `$0.0930` | `not_available` (cloud `N`) |
| `arm2c_xai_grok_4_20_reasoning` (Cloud Reasoning Transformer (xAI Grok-4.20-Reasoning)) | `xai:grok-4.20-0309-reasoning` | `40` | **`31 / 40` (`77.5%`)** | `30` (`28` + `2`) | `76,546 / 18,474` | `$0.2747` | `not_available` (cloud `N`) |
| `arm3_local_qwen3.6_35b_a3b` (Local Open-Weight Hybrid Gated-DeltaNet + Sparse MoE (Apple M5 Max)) | `Qwen3.6-35B-A3B-UD-Q5_K_M.gguf` | `40` | **`27 / 40` (`67.5%`)** | `26` (`25` + `1`) | `82,330 / 18,411` | `$0.0000` | `3369.89 J` SUT (`124.811 J/adm`) |
| **Arm 4**: `Shape D` Warm Gear-0 (`t = 2` Replay) | `DNULLMM1` (`34` crystallized) | **`0`** | **`34 / 40` (`85.0%`)** | `33` | `0 / 0` | **`$0.0000`** | **`0.325 µs`/probe** + `rce check` |

## 2. `Shape D` (`DNULLMM1`) Gear-0 Microbenchmark, Quotient Invariance & `Zipf-0.85` (`M = 200`) Stream

- **Frozen `DNULLMM1` Store SHA-256**: `d92a57b40de0b0ecd3530398c9517e80e7f63984ed7a2c98803f8d880e731a50` (post-replay byte-identical: `True`).
- **`40,000`-Probe `mmap` Latency & Energy**: `324.6 ns` (`0.3246 µs`) per lookup, `1771.31 nJ` (`L3` `ri_energy_nj`) and `9516.5` instructions per probe.
- **Name-Free Quotient Invariance (`rce fmt nameless`, Theorem T7)**: `7 / 9` (`77.8%`) alpha-renamed local-variable mutants hit the exact same `DNULLMM1` slot at `0` model calls.
- **Hypothesis `H2` (`C_check / E_model` on Local Apple M5 Max)**: `C_check = 0.04904 J` (`L3` `ri_energy_nj`) vs `E_model = 84.247 J` (`Qwen 3.6 35B-A3B` SUT `GPU + L3`), giving **`C_check / E_model = 0.00058`** (`<= 0.05` threshold -> **`supported`**).

### `Zipf(s = 0.85)`, `M = 200` Recurring Arrival Stream (Verified-Only Crystallization Policy)

| Proposer Arm | Stateless Calls | Gear-0 Stream Calls | `DNULLMM1` Hits | Call Reduction | Stateless Cost / Energy | Gear-0 Cost / Energy |
|---|---:|---:|---:|---:|---:|---:|
| `arm1a_claude_opus_5_5` | `200` | **`48`** | `152` | **`4.17x`** | `$6.8076` | `$2.6326` (saved `$4.1750`) |
| `arm1b_claude_sonnet_5_5` | `200` | **`56`** | `144` | **`3.57x`** | `$3.9343` | `$1.7290` (saved `$2.2053`) |
| `arm2a_openai_gpt_oss_120b` | `200` | **`66`** | `134` | **`3.03x`** | `$0.6532` | `$0.3087` (saved `$0.3444`) |
| `arm2b_deepseek_v4p1` | `200` | **`131`** | `69` | **`1.53x`** | `$0.3719` | `$0.2199` (saved `$0.1520`) |
| `arm2c_xai_grok_4_20_reasoning` | `200` | **`57`** | `143` | **`3.51x`** | `$1.4628` | `$0.7603` (saved `$0.7026`) |
| `arm3_local_qwen3.6_35b_a3b` | `200` | **`94`** | `106` | **`2.13x`** | `16457.9 J` | `10553.5 J` (**`1.56x` lower**) |
