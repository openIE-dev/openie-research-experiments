# SPDX-License-Identifier: Apache-2.0
"""Unit, [G6] ASR verification gate, orthogonality & receipt tests for `kits/planetary-media-joule/`."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parent.parent
if str(KIT_ROOT) not in sys.path:
    sys.path.insert(0, str(KIT_ROOT))

from media_joule.crypto_receipt import (  # noqa: E402
    assert_sanitized,
    blake3_derive_key_hex,
    verify_signed_receipt,
)
from meter_media_pipeline import (  # noqa: E402
    ISO24495_SCRIPT,
    SCRIPT_SHA256,
    evaluate_g6_asr_gate,
    run_media_pipeline_benchmark,
)


class TestPlanetaryMediaJoule(unittest.TestCase):
    def test_g6_asr_exact_number_and_wer_gate(self) -> None:
        exact = evaluate_g6_asr_gate(ISO24495_SCRIPT)
        self.assertTrue(exact["gate_pass"])
        self.assertEqual(exact["exact_numbers_matched"], 6)
        self.assertEqual(exact["normalized_wer"], 0.0)

        # Digit-formatted Whisper transcription should also pass G6 number equivalence
        digit_form = (
            "Plain language research summary under standard 24495. "
            "Point 1 what we tested most software tasks follow fixed rules yet teams "
            "often run large neural models on every request. "
            "Point 2 what we measured on physical current shunts routing recurring verified "
            "requests through a 4 kilobyte lookup table and exact solver before escalating "
            "to a model cut energy by 21 to 29 times while reaching 96.7% accuracy with 0 hallucinations. "
            "Point 3 what this means in practice publish joules per correct decision and "
            "joules per minute of media and never invent an unmetered number."
        )
        g_dig = evaluate_g6_asr_gate(digit_form)
        self.assertTrue(g_dig["gate_pass"])
        self.assertEqual(g_dig["exact_numbers_matched"], 6)

        # Corrupted numeric claim must FAIL G6 gate
        bad_num = digit_form.replace("96.7%", "99.9%")
        g_bad = evaluate_g6_asr_gate(bad_num)
        self.assertFalse(g_bad["gate_pass"])
        self.assertFalse(g_bad["number_survival_map"]["96.7"])

    def test_quick_pipeline_unmetered_cloud_and_tamper_gate(self) -> None:
        res, rec, md = run_media_pipeline_benchmark(quick=True)
        self.assertTrue(verify_signed_receipt(rec))
        assert_sanitized(md)
        self.assertEqual(res["provenance_tier"], "Signed Provenance · Self-Checked")
        self.assertEqual(res["iso24495_script_precommitment"]["script_sha256"], SCRIPT_SHA256)

        cloud = res["stages"]["elevenlabs_v4_cloud"]
        self.assertEqual(cloud["energy_class"], "unmetered")
        self.assertIsNone(cloud["j_per_min"])

        tampered = copy.deepcopy(rec)
        tampered["body"]["payload"]["cloud_tts_energy_class"] = "measured_j"
        self.assertFalse(verify_signed_receipt(tampered))

    def test_committed_multi_substrate_media_receipts_and_orthogonality(self) -> None:
        bundle_p = KIT_ROOT / "results" / "multi_substrate_media_receipts.json"
        master_p = KIT_ROOT / "results" / "receipt_planetary_media_joule.json"
        if not bundle_p.is_file():
            self.skipTest("Multi-substrate bundle not yet assembled")

        bundle_raw = bundle_p.read_text(encoding="utf-8")
        master_raw = master_p.read_text(encoding="utf-8")
        assert_sanitized(bundle_raw)
        assert_sanitized(master_raw)
        assert_sanitized((KIT_ROOT / "README.md").read_text(encoding="utf-8"))
        assert_sanitized((KIT_ROOT / "RESULTS.md").read_text(encoding="utf-8"))

        bundle = json.loads(bundle_raw)
        master = json.loads(master_raw)
        self.assertTrue(verify_signed_receipt(master))

        expected_b3 = blake3_derive_key_hex(
            "openie.kit.planetary_media_joule.multi_substrate.v1",
            json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        )
        self.assertEqual(master["body"]["payload"]["bundle_blake3"], expected_b3)

        # Check Jetson AGX Thor has BOTH INA238 VIN and INA3221 VDD_CPU_SOC_MSS measured_j and zero RAPL mixing
        thor = bundle["measured_j_substrates"]["nvidia_jetson_agx_thor_ina238_ina3221"]
        self.assertTrue(verify_signed_receipt(thor["signed_receipt"]))
        for sk, st in thor["results"]["stages"].items():
            if sk == "elevenlabs_v4_cloud":
                self.assertIsNone(st["j_per_min"])
                self.assertEqual(st["energy_class"], "unmetered")
            else:
                self.assertEqual(st["evidence_class"], "measured_j")
                self.assertGreater(st["primary_rail_measured_j"]["j_per_min_gross"], 0.0)
                self.assertGreater(st["secondary_carrier_rail_measured_j"]["j_per_min_gross"], 0.0)
                self.assertIsNone(st["rapl_reported_j"])

        # Check AMD Kria KV260 has INA260 SOM_5V_DC measured_j and zero RAPL mixing
        kv260 = bundle["measured_j_substrates"]["amd_kria_kv260_ina260"]
        self.assertTrue(verify_signed_receipt(kv260["signed_receipt"]))
        for sk, st in kv260["results"]["stages"].items():
            if sk == "elevenlabs_v4_cloud":
                self.assertIsNone(st["j_per_min"])
            else:
                self.assertEqual(st["evidence_class"], "measured_j")
                self.assertGreater(st["primary_rail_measured_j"]["j_per_min_gross"], 0.0)
                self.assertIsNone(st["rapl_reported_j"])

        # Check Zen 5 RAPL has reported_j and zero measured_j mixing
        zen5 = bundle["reported_j_substrates"]["amd_ryzen_ai_max_395_rapl"]
        self.assertTrue(verify_signed_receipt(zen5["signed_receipt"]))
        for sk, st in zen5["results"]["stages"].items():
            if sk == "elevenlabs_v4_cloud":
                self.assertIsNone(st["j_per_min"])
            else:
                self.assertEqual(st["evidence_class"], "reported_j")
                self.assertGreater(st["rapl_reported_j"]["j_per_min_pkg_gross"], 0.0)
                self.assertIsNone(st["primary_rail_measured_j"])


if __name__ == "__main__":
    unittest.main()
