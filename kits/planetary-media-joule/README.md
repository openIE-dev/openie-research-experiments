# Kit: `planetary-media-joule` — Physical `J/min` Metering for Planetary Research Media (Blueprint v1.0)

- **License:** `Apache-2.0`
- **Provenance Tier:** `Signed Provenance · Self-Checked` (`BLAKE3` + `Ed25519` offline-verifiable receipts; never self-labeled `"Verified"`)
- **Blueprint Scope:** *Planetary Research Media: A Blueprint for OpenIE Research (26 Nov 2026 · v1.0)* — §5, §7 `[G6]` / `[G10]`, & §9.5 (*"Make `J/min` a published column. Measure TTS, ASR, and render on the `INA238` rail, and label everything else `reported_j`/`unmetered`. Never invent the number."*)

---

## 1. 1-Command Reproduction

Run the self-contained verification and quick benchmark suite (`python3 >= 3.10` stdlib-only + optional `ffmpeg` / `piper` / `whisper-cli`):

```bash
./kits/planetary-media-joule/run_kit.sh --quick
```

To execute the full multi-stage open-source media pipeline against provisioned `piper` (`MIT`), `whisper-cli` (`MIT`), and `ffmpeg` (`LGPL`) binaries:

```bash
python3 kits/planetary-media-joule/meter_media_pipeline.py --tools-dir /path/to/tools --threads 12 --tag custom
```

---

## 2. Metered Media Stages & `[G6]` / `[G10]` Gates

1. **`tts_piper_or_kokoro_cpu`:** Synthesizes the `SHA-256`-pinned `ISO 24495-1` 3-point plain-language summary (`94` words, `37.4–37.5s` audio, `SHA-256 = e743ebcaec1a3330...`) via `piper 1.2.0` (`en_US-lessac-medium.onnx`) + `ffmpeg` `-16 LUFS` `loudnorm` `.m4a` mastering -> `J / output_audio_minute`.
2. **`asr_whisper_{tiny,base,large_v3_turbo}_cpu` (`[G6]` Gate):** Re-transcribes the mastered `.m4a` via MIT `whisper.cpp` and enforces `[G6]` exact survival of all `6` numeric claims (`24495`, `4`, `21`, `29`, `96.7`, `0`) + normalized `WER <= 0.12` -> `J / verified_audio_minute`.
3. **`render_1080p60_mp4`:** Renders a deterministic `15.0s` `1920x1080 @ 60fps` (`libopenh264` + AAC `-16 LUFS`) research card video with live waveform overlay -> `J / output_video_minute`.
4. **`render_lowbw_mobile_15s_mp4`:** Renders a `< 1 MB` (`~107 KB`, asserted `< 1,000,000 B`) `640x360 @ 24fps` WhatsApp/Telegram mobile MP4 -> `J / output_video_minute`.
5. **`render_opus_24k_voicenote`:** Encodes a `24 kbps` Opus (`libopus`, `~117 KB` for `37.4s`) podcast/WhatsApp voice note -> `J / output_audio_minute`.
6. **`render_voiced_ad_mix`:** Mixes a synthesized Voiced Extended Audio Description (`AD`) track with `-12 dB` `sidechaincompress` ducking + `-16 LUFS` `loudnorm` into `.ad-mix.m4a` -> `J / output_audio_minute`.
7. **`elevenlabs_v4_cloud` (`[G10]` Honesty Gate):** Explicitly recorded as `j_per_min: null, energy_class: "unmetered"` — never invented or mixed with `measured_j` or `reported_j`.

Committed multi-substrate hardware receipts live in [`results/multi_substrate_media_receipts.json`](./results/multi_substrate_media_receipts.json), [`results/receipt_planetary_media_joule.json`](./results/receipt_planetary_media_joule.json), and [`RESULTS.md`](./RESULTS.md).
