# SPDX-License-Identifier: Apache-2.0
"""Unit & conformance tests for Kit 5 (`kits/waios-mosaic-cascade/`)."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parent.parent
if str(KIT_ROOT) not in sys.path:
    sys.path.insert(0, str(KIT_ROOT))

from waios_mosaic.conformance_and_cascade import (  # noqa: E402
    WAIOS_CHANGED_DIGEST,
    WAIOS_REFERENCE_DIGEST,
    WaiosDisagreementHaltError,
    audit_input_python,
    compile_and_load_mosaic_lib,
    execute_and_seal_mosaic,
    run_boot_qualification_checks,
    run_full_kit,
    with_one_weight_changed,
)
from waios_mosaic.crypto_receipt import assert_sanitized, verify_signed_receipt  # noqa: E402


class TestWaiosMosaicCascadeKit(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.lib = compile_and_load_mosaic_lib()

    def test_boot_qualification_odd_dims_and_norm_rope(self) -> None:
        qual = run_boot_qualification_checks(self.lib)
        self.assertTrue(qual["odd_73x35_ternary_passed"])
        self.assertTrue(qual["all_passed"])

    def test_canonical_waios_reference_digest_across_all_lanes(self) -> None:
        weights, acts = audit_input_python()
        receipt = execute_and_seal_mosaic(self.lib, weights, acts, WAIOS_REFERENCE_DIGEST, split_shift=3)
        self.assertTrue(verify_signed_receipt(receipt))
        digests = receipt["body"]["payload"]["lane_digests"]
        self.assertEqual(len(digests), 5)
        for lane, d in digests.items():
            self.assertEqual(d, WAIOS_REFERENCE_DIGEST, f"Lane {lane} differed!")

    def test_single_weight_tamper_row77_halts_and_refuses_receipt(self) -> None:
        weights, acts = audit_input_python()
        w_mut, meta = with_one_weight_changed(weights, acts)
        self.assertEqual(meta["row"], 77)
        with self.assertRaises(WaiosDisagreementHaltError) as ctx:
            execute_and_seal_mosaic(self.lib, w_mut, acts, WAIOS_REFERENCE_DIGEST)
        self.assertEqual(ctx.exception.observed_digest, WAIOS_CHANGED_DIGEST)

    def test_receipt_offline_one_bit_tamper_fails(self) -> None:
        weights, acts = audit_input_python()
        rec = execute_and_seal_mosaic(self.lib, weights, acts, WAIOS_REFERENCE_DIGEST)
        self.assertTrue(verify_signed_receipt(rec))
        bad = copy.deepcopy(rec)
        sig_b = bytearray.fromhex(bad["ed25519_signature_hex"])
        sig_b[17] ^= 0x04
        bad["ed25519_signature_hex"] = sig_b.hex()
        self.assertFalse(verify_signed_receipt(bad))

    def test_end_to_end_cascade_and_meter_class_orthogonality(self) -> None:
        results, receipt, md = run_full_kit(quick=True)
        self.assertTrue(verify_signed_receipt(receipt))
        assert_sanitized(md)
        self.assertEqual(results["provenance_tier"], "Signed Provenance · Self-Checked")

        cas = results["spellcheck_lookup_first_cascade"]
        counts = cas["stage_routing_counts"]
        self.assertEqual(sum(counts.values()), 1000)
        self.assertGreater(counts["stage1_lut"], 400)
        self.assertGreater(counts["stage2_sparse"], 150)
        self.assertGreater(counts["stage3_mosaic"], 100)
        self.assertLessEqual(counts["stage4_escalated"], 100)

        # Verify strict separation between reported_j and analytical est_j
        est_block = cas["analytical_frontier_est_j_reference_strictly_separate"]
        self.assertEqual(est_block["evidence_class"], "est_j")
        self.assertFalse(est_block["mixed_or_summed_with_reported_j"])
        self.assertLess(
            cas["metered_pipelines_local_rapl"]["spellcheck_4stage_cascade"]["wall_us_per_correct_completion"]["median"],
            cas["metered_pipelines_local_rapl"]["always_stage3_mosaic_plus_gate"]["wall_us_per_correct_completion"]["median"],
        )
        self.assertLess(
            cas["metered_pipelines_local_rapl"]["spellcheck_4stage_cascade"]["wall_us_per_correct_completion"]["median"],
            cas["metered_pipelines_local_rapl"]["always_dense_teacher_baseline"]["wall_us_per_correct_completion"]["median"],
        )


    def test_cascade_grid_sweep_monotonic_recurrence(self) -> None:
        results, _, _ = run_full_kit(quick=True)
        grid = results["spellcheck_lookup_first_cascade"]["cascade_grid_sweep"]
        self.assertGreaterEqual(len(grid), 18)
        cold = next(
            g for g in grid if g["zipf_skew_s"] == 0.0 and g["stage2_edit_distance_d_max"] == 2 and g["stage3_margin_tau"] == 4500
        )
        warm = next(
            g for g in grid if g["zipf_skew_s"] == 1.40 and g["stage2_edit_distance_d_max"] == 2 and g["stage3_margin_tau"] == 4500
        )
        self.assertGreater(warm["stage_fractions"]["stage1_lut"], cold["stage_fractions"]["stage1_lut"])
        self.assertFalse(warm["isolated_analytical_cloud_est_j"]["mixed_or_summed"])


    def test_cross_fabric_optional_lanes_invariance(self) -> None:
        from waios_mosaic.conformance_and_cascade import digest_of_i32_output
        from waios_mosaic.cross_fabric import run_cross_fabric_conformance

        w, a = audit_input_python()
        wt, _ = with_one_weight_changed(w, a)
        cf = run_cross_fabric_conformance(
            w, a, wt, digest_of_i32_output, WAIOS_REFERENCE_DIGEST, WAIOS_CHANGED_DIGEST, quick=True
        )
        self.assertEqual(cf["disagreed_fabrics"], [])
        for fname, fmeta in cf["fabrics"].items():
            if fmeta.get("status") == "verified_equal":
                self.assertEqual(fmeta["observed_digest"], WAIOS_REFERENCE_DIGEST, fname)
                self.assertTrue(fmeta["tamper_halt_triggered"], fname)


if __name__ == "__main__":
    unittest.main()
