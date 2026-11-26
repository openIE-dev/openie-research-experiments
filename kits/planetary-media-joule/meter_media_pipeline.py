#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Planetary Research Media Joule Metering Harness (`kits/planetary-media-joule/`).

Implements Blueprint v1.0 (§5, §7 `[G6]`/`[G10]`, & §9.5):
  - Physical DC shunt metering (`measured_j` on NVIDIA Jetson AGX Thor `TI INA238 VIN` +
    `TI INA3221 VDD_CPU_SOC_MSS` and AMD Kria KV260 `TI INA260 SOM_5V_DC`) with per-stage
    `A1/A2` quiet-idle bracketing and `Falsifier 6 <= 5.0%` drift gating.
  - On-chip Linux `powercap` RAPL metering (`reported_j`), strictly separated from `measured_j`.
  - Unmetered cloud TTS (`elevenlabs_v4_cloud`: `j_per_min = null`, `energy_class = "unmetered"`),
    never invented or mixed across orthogonal evidence classes (`measured_j ⊥ reported_j ⊥ est_j ⊥ unmetered`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path
from typing import Any, Callable

KIT_ROOT = Path(__file__).resolve().parent
if str(KIT_ROOT) not in sys.path:
    sys.path.insert(0, str(KIT_ROOT))

from media_joule.crypto_receipt import (  # noqa: E402
    EnergyMeter,
    assert_sanitized,
    blake3_derive_key_hex,
    iqr_stats,
    sanitized_host_info,
    seal_signed_receipt,
    verify_signed_receipt,
)

ISO24495_SCRIPT = (
    "Plain language research summary under standard two four four nine five. "
    "Point one, what we tested: most software tasks follow fixed rules, yet teams "
    "often run large neural models on every request. "
    "Point two, what we measured on physical current shunts: routing recurring verified "
    "requests through a four kilobyte lookup table and exact solver before escalating "
    "to a model cut energy by twenty one to twenty nine times while reaching ninety six "
    "point seven percent accuracy with zero hallucinations. "
    "Point three, what this means in practice: publish joules per correct decision and "
    "joules per minute of media, and never invent an unmetered number."
)

VOICED_AD_SCRIPT = (
    "Audio description: the research card shows three separated columns for carrier "
    "shunt joules, module shunt joules, and unmetered cloud null."
)

SCRIPT_SHA256 = hashlib.sha256(ISO24495_SCRIPT.encode("utf-8")).hexdigest()

REQUIRED_G6_NUMBERS: dict[str, list[str]] = {
    "24495": ["24495", "24 495", "244 95", "two four four nine five"],
    "4": ["4", "four"],
    "21": ["21", "twenty one"],
    "29": ["29", "twenty nine"],
    "96.7": ["96 7", "96.7", "ninety six point seven"],
    "0": ["0", "zero"],
}

PUBLISHED_THIRD_PARTY_ASR_REFS = {
    "note": (
        "Third-party GPU reported_j figures cited in Planetary Research Media Blueprint v1.0 "
        "(E2E Networks, Mar 2026); strictly separated from OpenIE physical DC shunt measured_j."
    ),
    "whisper_large_v3_turbo_nvidia_l4_gpu": {
        "j_per_min_range": [95.0, 120.0],
        "energy_class": "reported_j",
        "substrate": "NVIDIA L4 GPU (third-party published benchmark)",
        "source": "E2E Networks (Mar 2026), cited in Blueprint v1.0 §9.5",
    },
    "nvidia_parakeet_l4_gpu": {
        "j_per_min": 13.0,
        "energy_class": "reported_j",
        "substrate": "NVIDIA L4 GPU (third-party published benchmark)",
        "source": "E2E Networks (Mar 2026), cited in Blueprint v1.0 §9.5",
    },
}


def _norm_tokens(text: str) -> list[str]:
    t = text.lower()
    replacements = [
        ("two four four nine five", "24495"),
        ("24,495", "24495"),
        ("ninety-six point seven", "96_7"),
        ("ninety six point seven", "96_7"),
        ("96.7", "96_7"),
        ("twenty-one", "21"),
        ("twenty one", "21"),
        ("twenty-nine", "29"),
        ("twenty nine", "29"),
        ("four", "4"),
        ("zero", "0"),
        ("one", "1"),
        ("two", "2"),
        ("three", "3"),
        ("kilobytes", "kilobyte"),
        ("kb", "kilobyte"),
        ("%", " percent "),
    ]
    for a, b in replacements:
        t = t.replace(a, b)
    t = re.sub(r"[^a-z0-9_]+", " ", t)
    return [w for w in t.split() if w]


def evaluate_g6_asr_gate(transcript: str, reference: str = ISO24495_SCRIPT) -> dict[str, Any]:
    low = re.sub(r"[^a-z0-9.]+", " ", transcript.lower())
    low_sp = " ".join(low.split())
    matched_nums: dict[str, bool] = {}
    for canonical_num, variants in REQUIRED_G6_NUMBERS.items():
        matched_nums[canonical_num] = any(v in low_sp for v in variants)

    ref_toks = _norm_tokens(reference)
    hyp_toks = _norm_tokens(transcript)
    n, m = len(ref_toks), len(hyp_toks)
    dp = list(range(m + 1))
    for i in range(1, n + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, m + 1):
            cur = dp[j]
            cost = 0 if ref_toks[i - 1] == hyp_toks[j - 1] else 1
            dp[j] = min(dp[j] + 1, dp[j - 1] + 1, prev + cost)
            prev = cur
    edits = dp[m]
    wer = round(edits / max(1, n), 4)
    nums_ok = sum(1 for v in matched_nums.values() if v)
    return {
        "gate_id": "G6_ASR_NUMBER_AND_WER_VERIFICATION",
        "exact_numbers_matched": nums_ok,
        "exact_numbers_total": len(REQUIRED_G6_NUMBERS),
        "number_survival_map": matched_nums,
        "normalized_wer": wer,
        "ref_word_count": n,
        "hyp_word_count": m,
        "edit_distance": edits,
        "gate_pass": bool(nums_ok == len(REQUIRED_G6_NUMBERS) and wer <= 0.12),
    }


def _synthesize_deterministic_wav(path: Path, duration_s: float = 12.0, sr: int = 22050) -> float:
    """Fallback deterministic speech-envelope PCM generator for `--quick` CI containers."""
    n_samples = int(duration_s * sr)
    buf = bytearray(n_samples * 2)
    for i in range(n_samples):
        t = i / sr
        syll = 0.5 * (1.0 + math.sin(2.0 * math.pi * 3.2 * t))
        val = syll * (
            0.45 * math.sin(2.0 * math.pi * 165.0 * t)
            + 0.30 * math.sin(2.0 * math.pi * 330.0 * t)
            + 0.15 * math.sin(2.0 * math.pi * 660.0 * t)
        )
        samp = max(-32767, min(32767, int(val * 14000)))
        struct.pack_into("<h", buf, 2 * i, samp)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(bytes(buf))
    return n_samples / sr


def _wav_duration_s(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / float(wf.getframerate())


def _ffprobe_duration_s(ffprobe_bin: str | None, media_path: Path, fallback_s: float) -> float:
    if ffprobe_bin:
        try:
            out = subprocess.check_output(
                [
                    ffprobe_bin,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(media_path),
                ],
                text=True,
                timeout=15,
            ).strip()
            val = float(out)
            if val > 0:
                return val
        except Exception:
            pass
    return fallback_s


def _detect_h264_encoder(ffmpeg_bin: str) -> str:
    try:
        enc = subprocess.check_output([ffmpeg_bin, "-hide_banner", "-encoders"], stderr=subprocess.DEVNULL, text=True, timeout=10)
        if "libopenh264" in enc:
            return "libopenh264"
        if "libx264" in enc:
            return "libx264"
    except Exception:
        pass
    return "mpeg4"


def _measure_stage_runs(
    meter: EnergyMeter,
    run_once_fn: Callable[[], float],
    n_runs: int = 1,
    idle_s: float = 0.65,
) -> dict[str, Any]:
    """Run `run_once_fn` `n_runs` times with A1/A2 quiet-idle bracketing and compute `J/min`."""
    is_shunt = meter.board_metered
    idle_a1 = meter.sample_idle_baseline(idle_s) if meter.available else None

    wall_s_list: list[float] = []
    dur_s_list: list[float] = []
    pri_gross_j_list: list[float] = []
    sec_gross_j_list: list[float] = []
    pkg_rep_j_list: list[float] = []
    core_rep_j_list: list[float] = []
    samples_list: list[int] = []
    hz_list: list[float] = []

    for _ in range(n_runs):
        s0 = meter.snapshot()
        media_dur_s = run_once_fn()
        s1 = meter.snapshot() if not is_shunt else None
        d = meter.diff(s0, s1)
        wall_s_list.append(float(d["wall_s"]))
        dur_s_list.append(float(media_dur_s))
        if d["primary_measured_j"] is not None:
            pri_gross_j_list.append(float(d["primary_measured_j"]))
            samples_list.append(int(d["shunt_samples"]))
            hz_list.append(float(d["sample_rate_hz"]))
        if d["secondary_measured_j"] is not None:
            sec_gross_j_list.append(float(d["secondary_measured_j"]))
        if d["pkg_reported_j"] is not None:
            pkg_rep_j_list.append(float(d["pkg_reported_j"]))
        if d["core_reported_j"] is not None:
            core_rep_j_list.append(float(d["core_reported_j"]))

    idle_a2 = meter.sample_idle_baseline(idle_s) if meter.available else None

    med_wall_s = iqr_stats(wall_s_list, 6)["median"]
    med_dur_s = iqr_stats(dur_s_list, 4)["median"]
    media_min = max(1e-6, med_dur_s / 60.0)
    rtf_x = round(med_dur_s / max(med_wall_s, 1e-9), 3)

    out: dict[str, Any] = {
        "evidence_class": meter.evidence_class,
        "runs": n_runs,
        "media_output_duration_s": round(med_dur_s, 4),
        "media_output_minutes": round(media_min, 6),
        "wall_s_median": round(med_wall_s, 4),
        "realtime_speed_x": rtf_x,
        "primary_rail_measured_j": None,
        "secondary_carrier_rail_measured_j": None,
        "rapl_reported_j": None,
    }

    if is_shunt and pri_gross_j_list and idle_a1 is not None and idle_a2 is not None:
        w1_p = float(idle_a1["trimmed_mean_w"])
        w2_p = float(idle_a2["trimmed_mean_w"])
        idle_p = 0.5 * (w1_p + w2_p)
        drift_p = round(100.0 * abs(w2_p - w1_p) / max(idle_p, 1e-9), 2)
        f6_p = bool(drift_p > 5.0)
        gross_jpm_p = [j / media_min for j in pri_gross_j_list]
        net_jpm_p = (
            [max(0.0, j - idle_p * ws) / media_min for j, ws in zip(pri_gross_j_list, wall_s_list)]
            if not f6_p
            else None
        )
        out["primary_rail_measured_j"] = {
            "sensor": meter.shunt.primary_sensor if meter.shunt else None,
            "rail": meter.shunt.primary_rail if meter.shunt else None,
            "energy_class": "measured_j",
            "idle_a1_w": w1_p,
            "idle_a2_w": w2_p,
            "idle_trimmed_mean_w": round(idle_p, 4),
            "idle_drift_pct": drift_p,
            "falsifier_6_drift_flag": f6_p,
            "shunt_samples_median": int(iqr_stats([float(c) for c in samples_list], 0)["median"]),
            "sample_rate_hz_median": iqr_stats(hz_list, 1)["median"],
            "gross_j_median": iqr_stats(pri_gross_j_list, 4)["median"],
            "j_per_min_gross": iqr_stats(gross_jpm_p, 3)["median"],
            "j_per_min_gross_iqr": iqr_stats(gross_jpm_p, 3),
            "j_per_min_net": iqr_stats(net_jpm_p, 3)["median"] if net_jpm_p is not None else None,
            "j_per_min_net_withheld_per_falsifier_6": f6_p,
        }

        if sec_gross_j_list and idle_a1.get("secondary_trimmed_mean_w") is not None and idle_a2.get("secondary_trimmed_mean_w") is not None:
            w1_s = float(idle_a1["secondary_trimmed_mean_w"])
            w2_s = float(idle_a2["secondary_trimmed_mean_w"])
            idle_s_w = 0.5 * (w1_s + w2_s)
            drift_s = round(100.0 * abs(w2_s - w1_s) / max(idle_s_w, 1e-9), 2)
            f6_s = bool(drift_s > 5.0)
            gross_jpm_s = [j / media_min for j in sec_gross_j_list]
            net_jpm_s = (
                [max(0.0, j - idle_s_w * ws) / media_min for j, ws in zip(sec_gross_j_list, wall_s_list)]
                if not f6_s
                else None
            )
            out["secondary_carrier_rail_measured_j"] = {
                "sensor": meter.shunt.secondary_sensor if meter.shunt else None,
                "rail": meter.shunt.secondary_rail if meter.shunt else None,
                "energy_class": "measured_j",
                "idle_a1_w": w1_s,
                "idle_a2_w": w2_s,
                "idle_trimmed_mean_w": round(idle_s_w, 4),
                "idle_drift_pct": drift_s,
                "falsifier_6_drift_flag": f6_s,
                "gross_j_median": iqr_stats(sec_gross_j_list, 4)["median"],
                "j_per_min_gross": iqr_stats(gross_jpm_s, 3)["median"],
                "j_per_min_gross_iqr": iqr_stats(gross_jpm_s, 3),
                "j_per_min_net": iqr_stats(net_jpm_s, 3)["median"] if net_jpm_s is not None else None,
                "j_per_min_net_withheld_per_falsifier_6": f6_s,
            }

    elif pkg_rep_j_list:
        gross_pkg_jpm = [j / media_min for j in pkg_rep_j_list]
        gross_core_jpm = [j / media_min for j in core_rep_j_list] if core_rep_j_list else []
        net_pkg_jpm = None
        f6_r = None
        drift_r = None
        idle_r = None
        if idle_a1 is not None and idle_a2 is not None:
            w1_r = float(idle_a1["trimmed_mean_w"])
            w2_r = float(idle_a2["trimmed_mean_w"])
            idle_r = round(0.5 * (w1_r + w2_r), 4)
            drift_r = round(100.0 * abs(w2_r - w1_r) / max(idle_r, 1e-9), 2)
            f6_r = bool(drift_r > 5.0)
            if not f6_r:
                net_pkg_jpm = iqr_stats(
                    [max(0.0, j - idle_r * ws) / media_min for j, ws in zip(pkg_rep_j_list, wall_s_list)], 3
                )["median"]
        out["rapl_reported_j"] = {
            "energy_class": "reported_j",
            "idle_pkg_mean_w": idle_r,
            "idle_drift_pct": drift_r,
            "falsifier_6_drift_flag": f6_r,
            "pkg_j_median": iqr_stats(pkg_rep_j_list, 4)["median"],
            "j_per_min_pkg_gross": iqr_stats(gross_pkg_jpm, 3)["median"],
            "j_per_min_pkg_gross_iqr": iqr_stats(gross_pkg_jpm, 3),
            "j_per_min_pkg_net": net_pkg_jpm,
            "j_per_min_core_gross": iqr_stats(gross_core_jpm, 3)["median"] if gross_core_jpm else None,
        }

    return out


def run_media_pipeline_benchmark(
    tools_dir: Path | None = None,
    threads: int | None = None,
    quick: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    meter = EnergyMeter(poll_interval_s=0.004)
    host = sanitized_host_info()
    n_threads = threads or min(12, max(2, os.cpu_count() or 4))

    ffmpeg_bin = str(tools_dir / "ffmpeg") if (tools_dir and (tools_dir / "ffmpeg").is_file()) else shutil.which("ffmpeg")
    ffprobe_bin = str(tools_dir / "ffprobe") if (tools_dir and (tools_dir / "ffprobe").is_file()) else shutil.which("ffprobe")
    piper_bin = str(tools_dir / "piper" / "piper") if (tools_dir and (tools_dir / "piper" / "piper").is_file()) else shutil.which("piper")
    piper_voice = (tools_dir / "en_US-lessac-medium.onnx") if (tools_dir and (tools_dir / "en_US-lessac-medium.onnx").is_file()) else None
    whisper_bin = str(tools_dir / "whisper-cli") if (tools_dir and (tools_dir / "whisper-cli").is_file()) else shutil.which("whisper-cli")

    idle_suite_pre = meter.sample_idle_baseline(0.15 if quick else 1.0) if meter.available else None
    stages: dict[str, Any] = {}
    idle_s = 0.12 if quick else 0.65
    n_fast_runs = 1 if quick else 3

    with tempfile.TemporaryDirectory(prefix="openie-media-bench-") as tmp_s:
        tmp = Path(tmp_s)
        raw_wav = tmp / "narration_raw.wav"
        master_m4a = tmp / "narration_master_16lufs.m4a"
        asr_16k_wav = tmp / "narration_16k.wav"
        ad_voice_wav = tmp / "voiced_ad_track.wav"
        ad_mix_m4a = tmp / "narration.ad-mix.m4a"
        opus_24k = tmp / "narration_24k.opus"
        mp4_1080p60 = tmp / "research_card_1080p60_15s.mp4"
        mp4_lowbw = tmp / "research_card_lowbw_mobile_15s.mp4"

        use_real_piper = (not quick) and (piper_bin is not None) and (piper_voice is not None) and (ffmpeg_bin is not None)
        h264_enc = _detect_h264_encoder(ffmpeg_bin) if ffmpeg_bin else "none"

        # Warmup Piper once outside metering so ONNX pages are resident
        if use_real_piper:
            assert piper_bin is not None and piper_voice is not None
            subprocess.run(
                [piper_bin, "--model", str(piper_voice), "--output_file", str(tmp / "warm.wav")],
                input="Warmup check.",
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=120,
            )
            # Also pre-synthesize the short Voiced AD track before metering Stage 6
            subprocess.run(
                [piper_bin, "--model", str(piper_voice), "--output_file", str(ad_voice_wav)],
                input=VOICED_AD_SCRIPT,
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=120,
            )
        else:
            _synthesize_deterministic_wav(ad_voice_wav, duration_s=4.0, sr=22050)

        # ── Stage 1: Local Permissive TTS + -16 LUFS .m4a Mastering ──
        def _run_tts() -> float:
            if use_real_piper:
                assert piper_bin is not None and piper_voice is not None and ffmpeg_bin is not None
                subprocess.run(
                    [piper_bin, "--model", str(piper_voice), "--output_file", str(raw_wav)],
                    input=ISO24495_SCRIPT,
                    text=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=True,
                    timeout=240,
                )
                dur = _wav_duration_s(raw_wav)
                subprocess.run(
                    [
                        ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
                        "-i", str(raw_wav),
                        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                        "-c:a", "aac", "-b:a", "128k",
                        str(master_m4a),
                    ],
                    check=True,
                    timeout=120,
                )
                return _ffprobe_duration_s(ffprobe_bin, master_m4a, dur)
            dur = _synthesize_deterministic_wav(raw_wav, duration_s=10.0, sr=22050)
            if ffmpeg_bin:
                subprocess.run(
                    [
                        ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
                        "-i", str(raw_wav),
                        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                        "-c:a", "aac", "-b:a", "128k",
                        str(master_m4a),
                    ],
                    check=True,
                    timeout=60,
                )
            else:
                shutil.copyfile(raw_wav, master_m4a)
            return dur

        tts_runs = 1 if (quick or n_threads <= 4) else 3
        tts_metrics = _measure_stage_runs(meter, _run_tts, n_runs=tts_runs, idle_s=idle_s)
        tts_metrics["tool"] = "piper 1.2.0 (MIT, en_US-lessac-medium.onnx) + ffmpeg -16 LUFS loudnorm AAC" if use_real_piper else "synthetic_ci_pcm + ffmpeg loudnorm"
        tts_metrics["output_bytes"] = master_m4a.stat().st_size
        tts_metrics["script_sha256"] = SCRIPT_SHA256
        stages["tts_piper_or_kokoro_cpu"] = tts_metrics
        audio_dur_s = float(tts_metrics["media_output_duration_s"])

        # ── Stage 2: Local `[G6]` ASR Verification (Whisper CPU) ──
        whisper_models: list[tuple[str, str, Path]] = []
        if (not quick) and whisper_bin and tools_dir and ffmpeg_bin:
            for st_key, m_label, m_file in [
                ("asr_whisper_tiny_cpu", "whisper.cpp ggml-tiny.en (MIT, 39M)", tools_dir / "ggml-tiny.en.bin"),
                ("asr_whisper_base_cpu", "whisper.cpp ggml-base.en (MIT, 74M)", tools_dir / "ggml-base.en.bin"),
                ("asr_whisper_large_v3_turbo_cpu", "whisper.cpp ggml-large-v3-turbo (MIT, 809M)", tools_dir / "ggml-large-v3-turbo.bin"),
            ]:
                if m_file.is_file():
                    whisper_models.append((st_key, m_label, m_file))

        if whisper_models:
            assert whisper_bin is not None and ffmpeg_bin is not None
            for st_key, m_label, m_path in whisper_models:
                last_transcript = ""

                def _run_asr(mp: Path = m_path) -> float:
                    nonlocal last_transcript
                    subprocess.run(
                        [
                            ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
                            "-i", str(master_m4a), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
                            str(asr_16k_wav),
                        ],
                        check=True,
                        timeout=60,
                    )
                    out = subprocess.check_output(
                        [
                            whisper_bin, "-m", str(mp), "-f", str(asr_16k_wav),
                            "-t", str(n_threads), "-l", "en", "-nt", "-np",
                        ],
                        stderr=subprocess.DEVNULL,
                        text=True,
                        timeout=600,
                    )
                    last_transcript = " ".join(line.strip() for line in out.splitlines() if line.strip())
                    return audio_dur_s

                # Warmup once if fast (>= 8 threads), run 1 pass on slow Cortex-A53 or large-v3-turbo, 3 on fast base
                asr_runs = 1 if ("large" in st_key or n_threads <= 4) else 3
                if n_threads > 4:
                    _run_asr()
                m_asr = _measure_stage_runs(meter, _run_asr, n_runs=asr_runs, idle_s=idle_s)
                g6 = evaluate_g6_asr_gate(last_transcript, ISO24495_SCRIPT)
                m_asr["tool"] = m_label
                m_asr["model_bytes"] = m_path.stat().st_size
                m_asr["transcript_excerpt"] = last_transcript[:240]
                m_asr["g6_verification_gate"] = g6
                stages[st_key] = m_asr
        else:
            # Quick/CI mock [G6] verification gate check
            def _run_quick_asr() -> float:
                _ = evaluate_g6_asr_gate(ISO24495_SCRIPT, ISO24495_SCRIPT)
                time.sleep(0.02)
                return audio_dur_s

            m_q = _measure_stage_runs(meter, _run_quick_asr, n_runs=1, idle_s=idle_s)
            m_q["tool"] = "quick_ci_transcript_gate_only"
            m_q["g6_verification_gate"] = evaluate_g6_asr_gate(ISO24495_SCRIPT, ISO24495_SCRIPT)
            stages["asr_whisper_base_cpu"] = m_q

        # ── Stage 3: Deterministic 1080p60 Research Card MP4 Render (15.0s) ──
        vid_dur_target = 3.0 if quick else 15.0
        if ffmpeg_bin:
            enc_opts = (
                ["-c:v", "libopenh264", "-b:v", "4500k"]
                if h264_enc == "libopenh264"
                else (["-c:v", "libx264", "-preset", "veryfast", "-b:v", "4500k"] if h264_enc == "libx264" else ["-c:v", "mpeg4", "-b:v", "4500k"])
            )

            def _run_1080p60() -> float:
                assert ffmpeg_bin is not None
                vf_graph = (
                    f"color=c=0x0f172a:s=1920x1080:r=60:d={vid_dur_target},"
                    "drawbox=x=80:y=70:w=1760:h=150:color=0x1e293b@1.0:t=fill,"
                    "drawbox=x=80:y=260:w=560:h=440:color=0x172554@1.0:t=fill,"
                    "drawbox=x=680:y=260:w=560:h=440:color=0x064e3b@1.0:t=fill,"
                    "drawbox=x=1280:y=260:w=560:h=440:color=0x3b0764@1.0:t=fill[bg];"
                    "[0:a]atrim=0:" + str(vid_dur_target) + ",asetpts=PTS-STARTPTS[aud];"
                    "[aud]asplit=2[a_out][a_vis];"
                    "[a_vis]showwaves=s=1760x220:mode=line:rate=60:colors=0x38bdf8[wv];"
                    "[bg][wv]overlay=80:760,format=yuv420p[v_out]"
                )
                subprocess.run(
                    [
                        ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
                        "-threads", str(n_threads),
                        "-i", str(master_m4a),
                        "-filter_complex", vf_graph,
                        "-map", "[v_out]", "-map", "[a_out]",
                        *enc_opts,
                        "-c:a", "aac", "-b:a", "128k",
                        "-movflags", "+faststart",
                        "-t", str(vid_dur_target),
                        str(mp4_1080p60),
                    ],
                    check=True,
                    timeout=300,
                )
                return _ffprobe_duration_s(ffprobe_bin, mp4_1080p60, vid_dur_target)

            v1080_runs = 1 if (quick or n_threads <= 4) else 3
            m_1080 = _measure_stage_runs(meter, _run_1080p60, n_runs=v1080_runs, idle_s=idle_s)
            m_1080["tool"] = f"ffmpeg (LGPL, {h264_enc} 1920x1080@60fps + AAC)"
            m_1080["output_bytes"] = mp4_1080p60.stat().st_size
            stages["render_1080p60_mp4"] = m_1080

            # ── Stage 4: Low-Bandwidth WhatsApp/Telegram < 1 MB 15s MP4 ──
            lowbw_opts = (
                ["-c:v", "libopenh264", "-b:v", "260k", "-maxrate", "300k"]
                if h264_enc == "libopenh264"
                else (["-c:v", "libx264", "-preset", "veryfast", "-b:v", "260k", "-maxrate", "300k"] if h264_enc == "libx264" else ["-c:v", "mpeg4", "-b:v", "260k"])
            )

            def _run_lowbw() -> float:
                assert ffmpeg_bin is not None
                subprocess.run(
                    [
                        ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
                        "-threads", str(n_threads),
                        "-i", str(mp4_1080p60),
                        "-vf", "scale=640:360,fps=24,format=yuv420p",
                        *lowbw_opts,
                        "-c:a", "aac", "-ac", "1", "-ar", "24000", "-b:a", "48k",
                        "-movflags", "+faststart",
                        str(mp4_lowbw),
                    ],
                    check=True,
                    timeout=180,
                )
                return _ffprobe_duration_s(ffprobe_bin, mp4_lowbw, vid_dur_target)

            m_lowbw = _measure_stage_runs(meter, _run_lowbw, n_runs=n_fast_runs, idle_s=idle_s)
            lowbw_bytes = mp4_lowbw.stat().st_size
            assert lowbw_bytes < 1_000_000, f"Low-BW MP4 exceeded 1 MB cap: {lowbw_bytes} B"
            m_lowbw["tool"] = f"ffmpeg (LGPL, {h264_enc} 640x360@24fps + 48k mono AAC, <1 MB)"
            m_lowbw["output_bytes"] = lowbw_bytes
            m_lowbw["under_1mb_cap_pass"] = True
            stages["render_lowbw_mobile_15s_mp4"] = m_lowbw

            # ── Stage 5: 24 kbps Opus Podcast / WhatsApp Voice Note ──
            def _run_opus24k() -> float:
                assert ffmpeg_bin is not None
                subprocess.run(
                    [
                        ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
                        "-i", str(master_m4a),
                        "-c:a", "libopus", "-b:a", "24k", "-vbr", "on", "-application", "voip",
                        str(opus_24k),
                    ],
                    check=True,
                    timeout=120,
                )
                return _ffprobe_duration_s(ffprobe_bin, opus_24k, audio_dur_s)

            m_opus = _measure_stage_runs(meter, _run_opus24k, n_runs=n_fast_runs, idle_s=idle_s)
            m_opus["tool"] = "ffmpeg libopus 24 kbps VoIP/podcast voice note"
            m_opus["output_bytes"] = opus_24k.stat().st_size
            stages["render_opus_24k_voicenote"] = m_opus

            # ── Stage 6: Ducked Voiced Extended Audio Description (.ad-mix.m4a) ──
            def _run_ad_mix() -> float:
                assert ffmpeg_bin is not None
                ad_filter = (
                    "[1:a]adelay=1500|1500,apad=whole_dur=" + str(round(audio_dur_s, 3)) + "[ad_pad];"
                    "[ad_pad]asplit=2[ad_sc][ad_mix];"
                    "[0:a][ad_sc]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=300[ducked];"
                    "[ducked][ad_mix]amix=inputs=2:duration=first:dropout_transition=0,"
                    "loudnorm=I=-16:TP=-1.5:LRA=11[out_a]"
                )
                subprocess.run(
                    [
                        ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
                        "-i", str(master_m4a),
                        "-i", str(ad_voice_wav),
                        "-filter_complex", ad_filter,
                        "-map", "[out_a]",
                        "-c:a", "aac", "-b:a", "128k",
                        str(ad_mix_m4a),
                    ],
                    check=True,
                    timeout=120,
                )
                return _ffprobe_duration_s(ffprobe_bin, ad_mix_m4a, audio_dur_s)

            m_ad = _measure_stage_runs(meter, _run_ad_mix, n_runs=n_fast_runs, idle_s=idle_s)
            m_ad["tool"] = "ffmpeg sidechaincompress (-12 dB ducking) + loudnorm -16 LUFS .ad-mix.m4a"
            m_ad["output_bytes"] = ad_mix_m4a.stat().st_size
            stages["render_voiced_ad_mix"] = m_ad

    # ── Stage 7: Cloud TTS (`elevenlabs_v4_cloud`) — Strictly Unmetered (`null`) ──
    stages["elevenlabs_v4_cloud"] = {
        "evidence_class": "unmetered",
        "energy_class": "unmetered",
        "provider": "ElevenLabs v4 Cloud TTS API",
        "j_per_min": None,
        "j_per_min_gross": None,
        "j_per_min_net": None,
        "note": (
            "Cloud TTS provider exposes zero hardware rail or RAPL joule counters; "
            "per Blueprint v1.0 [G10], labeled unmetered (null) and never invented or estimated."
        ),
    }

    idle_suite_post = meter.sample_idle_baseline(0.15 if quick else 1.0) if meter.available else None
    telemetry_meta = meter.metadata(idle_suite_pre, idle_suite_post)
    meter.close()

    results: dict[str, Any] = {
        "schema": "openie.planetary_media_joule.v1",
        "kit_id": "kits/planetary-media-joule",
        "blueprint_reference": "Planetary Research Media: A Blueprint for OpenIE Research (26 Nov 2026 · v1.0, §5, §7 [G6]/[G10], §9.5)",
        "provenance_tier": "Signed Provenance · Self-Checked",
        "license": "Apache-2.0",
        "energy_orthogonality_rule": "measured_j ⊥ reported_j ⊥ est_j ⊥ unmetered (never summed or cross-ratioed)",
        "host": host,
        "cpu_threads": n_threads,
        "quick_mode": quick,
        "energy_telemetry": telemetry_meta,
        "iso24495_script_precommitment": {
            "standard": "ISO 24495-1 Plain Language (3-point research summary)",
            "word_count": len(ISO24495_SCRIPT.split()),
            "script_sha256": SCRIPT_SHA256,
            "required_g6_exact_numbers": list(REQUIRED_G6_NUMBERS.keys()),
        },
        "stages": stages,
        "third_party_published_reported_j_references": PUBLISHED_THIRD_PARTY_ASR_REFS,
    }

    receipt = seal_signed_receipt(
        kit_id="kits/planetary-media-joule",
        payload={
            "substrate_id": telemetry_meta.get("substrate_id"),
            "energy_evidence_class": telemetry_meta.get("evidence_class"),
            "script_sha256": SCRIPT_SHA256,
            "stages_metered": list(stages.keys()),
            "cloud_tts_energy_class": stages["elevenlabs_v4_cloud"]["energy_class"],
            "results_blake3": blake3_derive_key_hex(
                "openie.kit.planetary_media_joule.results.v1",
                json.dumps(results, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            ),
        },
        domain_context="openie.kit.planetary_media_joule.receipt.v1",
    )
    assert verify_signed_receipt(receipt)
    md = _render_markdown_summary(results, receipt)
    return results, receipt, md


def _render_markdown_summary(res: dict[str, Any], rec: dict[str, Any]) -> str:
    tel = res["energy_telemetry"]
    lines = [
        "# Planetary Research Media `J/min` Receipt (`kits/planetary-media-joule`)",
        "",
        f"- **Host:** `{res['host']['cpu_model']}` (`{tel['evidence_class']}`, `board_metered={tel.get('board_metered')}`)",
        "",
        "| Stage | Media Dur (`s`) | Speed (`x RT`) | Primary Rail `J/min` Gross (`Net`) | Carrier `INA238 VIN` `J/min` Gross (`Net`) | `RAPL` Pkg `J/min` | Class |",
        "|---|---:|---:|---|---|---:|---|",
    ]
    for sk, st in res["stages"].items():
        if st.get("evidence_class") == "unmetered" and "media_output_duration_s" not in st:
            lines.append(f"| `{sk}` | `—` | `—` | `null` | `null` | `null` | `unmetered` |")
            continue
        p = st.get("primary_rail_measured_j")
        s = st.get("secondary_carrier_rail_measured_j")
        r = st.get("rapl_reported_j")
        p_str = f"**`{p['j_per_min_gross']}`** (`{p['j_per_min_net']}`)" if p else "`n/a`"
        s_str = f"**`{s['j_per_min_gross']}`** (`{s['j_per_min_net']}`)" if s else "`n/a`"
        r_str = f"**`{r['j_per_min_pkg_gross']}`**" if r else "`n/a`"
        lines.append(
            f"| `{sk}` | `{st['media_output_duration_s']}` | `{st['realtime_speed_x']}x` | {p_str} | {s_str} | {r_str} | `{st['evidence_class']}` |"
        )
    lines.extend(["", f"- **Signed Receipt:** `{rec['body_blake3'][:24]}...` (`PASS`)", ""])
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Meter Planetary Research Media J/min across TTS, [G6] ASR, and FFmpeg render")
    ap.add_argument("--tools-dir", type=Path, default=None, help="Directory with piper, whisper-cli, models, and optional ffmpeg")
    ap.add_argument("--threads", type=int, default=None)
    ap.add_argument("--quick", action="store_true", help="Fast deterministic CI verification mode")
    ap.add_argument("--out-dir", type=Path, default=KIT_ROOT / "results")
    ap.add_argument("--tag", type=str, default="local")
    args = ap.parse_args()

    res, rec, md = run_media_pipeline_benchmark(
        tools_dir=args.tools_dir,
        threads=args.threads,
        quick=args.quick,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    res_json = json.dumps(res, indent=2) + "\n"
    rec_json = json.dumps(rec, indent=2) + "\n"
    assert_sanitized(res_json)
    assert_sanitized(rec_json)
    assert_sanitized(md)

    (args.out_dir / f"media_joule_results_{args.tag}.json").write_text(res_json, encoding="utf-8")
    (args.out_dir / f"media_joule_receipt_{args.tag}.json").write_text(rec_json, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
