# Planetary Research Media `J/min` Results (`kits/planetary-media-joule`)

- **Blueprint Reference:** *Planetary Research Media: A Blueprint for OpenIE Research (26 Nov 2026 · v1.0, §5, §7 `[G6]`/`[G10]`, §9.5)*
- **Provenance Tier:** `Signed Provenance · Self-Checked` (`BLAKE3 = 5f2fba088308762648bf3f9d...`, [`results/receipt_planetary_media_joule.json`](./results/receipt_planetary_media_joule.json))
- **Canonical `ISO 24495-1` Script (`94` words, `37.4–37.5s` audio):** `SHA-256 = e743ebcaec1a3330d76e9cbaa2e90f649945f5f0eb706cf95d3e983593578f64`
- **Strict Evidence Orthogonality:** `measured_j ⊥ reported_j ⊥ est_j ⊥ unmetered` — never summed or cross-ratioed.

---

## Table A — Physical DC Shunt Metering (`evidence_class = measured_j`: `TI INA238 VIN`, `TI INA3221 VDD_CPU_SOC_MSS`, & `TI INA260 SOM_5V_DC`)

| Board | Stage | Media Out (`s`) | Speed (`x RT`) | `[G6]` ASR Gate | `INA238 VIN` Carrier `J/min` Gross | `INA238 VIN` `J/min` Net (`F6 <= 5%`) | Module/SoC Rail `J/min` Gross | Module/SoC `J/min` Net (`F6 <= 5%`) |
|---|---|---:|---:|---|---:|---:|---:|---:|
| `Jetson AGX Thor` | `tts_piper_or_kokoro_cpu` | `37.4` | `5.322x` | `—` | **`405.202`** | `86.991` | **`217.299`** | `withheld (F6)` |
| `Jetson AGX Thor` | `asr_whisper_base_cpu` | `37.4` | `3.036x` | `PASS` (`WER=0.0638`) | **`797.73`** | `withheld (F6)` | **`467.499`** | `withheld (F6)` |
| `Jetson AGX Thor` | `asr_whisper_large_v3_turbo_cpu` | `37.4` | `0.262x` | `PASS` (`WER=0.0`) | **`10002.978`** | `withheld (F6)` | **`6126.512`** | `withheld (F6)` |
| `Jetson AGX Thor` | `render_1080p60_mp4` | `15.0` | `2.137x` | `—` | **`1063.53`** | `withheld (F6)` | **`537.12`** | `withheld (F6)` |
| `Jetson AGX Thor` | `render_lowbw_mobile_15s_mp4` | `15.0` | `13.79x` | `—` | **`198.736`** | `40.658` | **`109.409`** | `withheld (F6)` |
| `Jetson AGX Thor` | `render_opus_24k_voicenote` | `37.3065` | `70.293x` | `—` | **`26.198`** | `withheld (F6)` | **`12.415`** | `withheld (F6)` |
| `Jetson AGX Thor` | `render_voiced_ad_mix` | `37.3` | `12.598x` | `—` | **`136.056`** | `withheld (F6)` | **`54.9`** | `0.0` |
| `AMD Kria KV260` | `tts_piper_or_kokoro_cpu` | `37.4` | `0.945x` | `—` | `n/a` | `n/a` | **`263.707`** *(SOM 5V)* | `56.038` |
| `AMD Kria KV260` | `asr_whisper_tiny_cpu` | `37.4` | `1.24x` | `FAIL` (`WER=0.0851`) | `n/a` | `n/a` | **`203.49`** *(SOM 5V)* | `44.702` |
| `AMD Kria KV260` | `asr_whisper_base_cpu` | `37.4` | `0.552x` | `PASS` (`WER=0.0426`) | `n/a` | `n/a` | **`455.67`** *(SOM 5V)* | `99.096` |
| `AMD Kria KV260` | `render_1080p60_mp4` | `15.0` | `0.237x` | `—` | `n/a` | `n/a` | **`994.898`** *(SOM 5V)* | `165.136` |
| `AMD Kria KV260` | `render_lowbw_mobile_15s_mp4` | `15.0` | `1.25x` | `—` | `n/a` | `n/a` | **`216.201`** *(SOM 5V)* | `58.539` |
| `AMD Kria KV260` | `render_opus_24k_voicenote` | `37.4065` | `9.323x` | `—` | `n/a` | `n/a` | **`22.758`** *(SOM 5V)* | `1.644` |
| `AMD Kria KV260` | `render_voiced_ad_mix` | `37.4` | `2.381x` | `—` | `n/a` | `n/a` | **`91.128`** *(SOM 5V)* | `8.401` |

---

## Table B — On-Chip Hardware Counters & Published Third-Party GPU References (`evidence_class = reported_j`)

| Substrate / Source | Stage | Media Out (`s`) | Speed (`x RT`) | `[G6]` ASR Gate | Package / GPU `J/min` Gross | `J/min` Net (`F6 <= 5%`) | Core `J/min` Gross | Class |
|---|---|---:|---:|---|---:|---:|---:|---|
| `AMD Ryzen AI Max+ 395` | `tts_piper_or_kokoro_cpu` | `37.5` | `14.666x` | `—` | **`495.112`** | `withheld (F6)` | `32.786` | `reported_j` |
| `AMD Ryzen AI Max+ 395` | `asr_whisper_base_cpu` | `37.5` | `34.749x` | `PASS` (`WER=0.0532`) | **`235.322`** | `withheld (F6)` | `13.756` | `reported_j` |
| `AMD Ryzen AI Max+ 395` | `asr_whisper_large_v3_turbo_cpu` | `37.5` | `5.451x` | `PASS` (`WER=0.0213`) | **`1546.27`** | `withheld (F6)` | `95.799` | `reported_j` |
| `AMD Ryzen AI Max+ 395` | `render_1080p60_mp4` | `15.0` | `2.203x` | `—` | **`3503.165`** | `withheld (F6)` | `197.07` | `reported_j` |
| `AMD Ryzen AI Max+ 395` | `render_lowbw_mobile_15s_mp4` | `15.0` | `24.147x` | `—` | **`318.082`** | `withheld (F6)` | `18.211` | `reported_j` |
| `AMD Ryzen AI Max+ 395` | `render_opus_24k_voicenote` | `37.5065` | `113.217x` | `—` | **`66.829`** | `withheld (F6)` | `3.512` | `reported_j` |
| `AMD Ryzen AI Max+ 395` | `render_voiced_ad_mix` | `37.5` | `30.153x` | `—` | **`279.363`** | `5.779` | `16.327` | `reported_j` |
| `NVIDIA L4 GPU` *(E2E Networks, Mar 2026)* | `whisper_large_v3_turbo_gpu` *(cited ref)* | `60.0` | `—` | `—` | **`95.0–120.0`** | `—` | `—` | `reported_j` |
| `NVIDIA L4 GPU` *(E2E Networks, Mar 2026)* | `nvidia_parakeet_gpu` *(cited ref)* | `60.0` | `—` | `—` | **`13.0`** | `—` | `—` | `reported_j` |

---

## Table C — Unmetered Cloud Services (`evidence_class = unmetered`)

| Provider / Stage | `J/min` | Evidence Class | Policy (`[G10]`) |
|---|---:|---|---|
| `elevenlabs_v4_cloud` (`ElevenLabs v4 Cloud TTS API`) | **`null`** | **`unmetered`** | Provider exposes no hardware rail or RAPL joule telemetry; labeled `unmetered` and never invented. |

---

## Key Findings

1. **Low-Bandwidth Distribution vs. `1080p60` Video (`measured_j`):** Encoding a `24 kbps` Opus voice note (`~117 KB` for `37.4s`) costs **`26.20 J/min` on `Jetson AGX Thor` `INA238 VIN` (`12.42 J/min` `VDD_CPU_SOC_MSS`)** and **`22.76 J/min` gross / `1.64 J/min` net on `AMD Kria KV260` `INA260`** — **`40.6x` (`Thor`) to `43.7x` (`KV260`) lower physical `measured_j` per minute** than rendering `1080p60` H.264 video (`1,063.53 J/min` `Thor` `INA238`; `994.90 J/min` `KV260`), while `< 1 MB` `360p24` mobile video (`~107 KB`) cuts `measured_j/min` by **`5.35x` (`Thor` `198.74 J/min`)** and **`4.60x` (`KV260` `216.20 J/min`)**.
2. **`[G6]` ASR Exact-Number Gate Pareto Knee (`whisper-base` vs `tiny` & `large-v3-turbo`):** On `KV260`, `whisper-tiny` (`39M`, `203.49 J/min`) fails `[G6]` (`5/6` numbers, `Playing language` substitution), whereas `whisper-base` (`74M`) passes **`6/6` exact numeric claims (`WER = 0.0426–0.0638`) across all 3 substrates** at **`12.54x` lower `INA238 VIN` `measured_j/min` than CPU `whisper-large-v3-turbo` (`797.73` vs `10,002.98 J/min` on `Thor`, where `large-v3-turbo` achieves `0.0000` `WER`)**.
