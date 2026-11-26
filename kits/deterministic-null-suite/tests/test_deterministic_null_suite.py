# SPDX-License-Identifier: Apache-2.0
"""Unit, adapter & receipt tests for Kit 1 (`kits/deterministic-null-suite/`)."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parent.parent
if str(KIT_ROOT) not in sys.path:
    sys.path.insert(0, str(KIT_ROOT))

from dnull_suite.crypto_receipt import assert_sanitized, verify_signed_receipt  # noqa: E402
from dnull_suite.suite_runner import LUT_CAP_BYTES, N_TOTAL, run_suite  # noqa: E402


class TestDeterministicNullSuite(unittest.TestCase):
    def test_precommitment_five_classical_arms_and_strata_physics(self) -> None:
        res, rec, md = run_suite(quick=True)
        self.assertTrue(verify_signed_receipt(rec))
        assert_sanitized(md)
        self.assertEqual(res["provenance_tier"], "Signed Provenance · Self-Checked")
        self.assertEqual(res["dataset_precommitment"]["held_out_instances_total"], 1500)
        self.assertEqual(res["dataset_precommitment"]["lut_memory_cap_bytes_per_stratum"], LUT_CAP_BYTES)
        self.assertEqual(res["determinism_gate"]["divergent_runs"], 0)

        arms = res["arms"]
        # Stratum A: if/else and for-loop must achieve 100%
        self.assertEqual(arms["arm2_if_else_guards"]["stratum_accuracy"]["bounded_api_dispatch"], 1.0)
        self.assertEqual(arms["arm3_bounded_for_loop"]["stratum_accuracy"]["bounded_api_dispatch"], 1.0)
        # Stratum B: DPLL solver must achieve 100% and beat shallow CART/if-else & MLP on 3-SAT
        self.assertEqual(arms["arm5_compiled_solver_rules"]["stratum_accuracy"]["combinatorial_constraint_3sat"], 1.0)
        self.assertGreater(
            arms["arm5_compiled_solver_rules"]["stratum_accuracy"]["combinatorial_constraint_3sat"],
            arms["candidate_dense_mlp_int16"]["stratum_accuracy"]["combinatorial_constraint_3sat"],
        )
        # Stratum C: Neural MLP comparator must beat classical arms on the oblique compositional tail
        self.assertGreater(
            arms["candidate_dense_mlp_int16"]["stratum_accuracy"]["open_compositional_patch_triage"],
            arms["shape_d_classical_best"]["stratum_accuracy"]["open_compositional_patch_triage"],
        )

    def test_pluggable_external_candidate_cli_adapter_and_tamper_gate(self) -> None:
        mock_cmd = (
            f"{sys.executable} -c "
            "'import sys, json; "
            "[print(json.dumps({\"id\": json.loads(l)[\"id\"], \"prediction\": 1})) for l in sys.stdin if l.strip()]'"
        )
        res, rec, _ = run_suite(quick=True, candidate_cmd=mock_cmd)
        self.assertIsNotNone(res["external_candidate_adapter_result"])
        ext = res["external_candidate_adapter_result"]
        self.assertEqual(ext["execution"]["n_instances"], N_TOTAL)
        self.assertIn("mcnemar_exact_two_sided_p", ext["paired_vs_shape_d_classical_best"])

        bad = copy.deepcopy(rec)
        bad["body"]["payload"]["divergent_runs"] = 99
        self.assertFalse(verify_signed_receipt(bad))


    def test_real_llm_crystallization_pipeline_and_subset90_precommitment(self) -> None:
        from real_llm_eval import run_real_llm_crystallization_eval

        res, rec, md = run_real_llm_crystallization_eval(mock_dry_run=True)
        self.assertTrue(verify_signed_receipt(rec))
        assert_sanitized(md)
        self.assertEqual(res["confirmatory_subset_precommitment"]["n_instances_total"], 90)
        self.assertEqual(
            res["classical_arms_on_identical_subset90"]["shape_d_classical_best"]["stratum_accuracy"]["combinatorial_constraint_3sat"],
            1.0,
        )
        st = res["verified_downward_crystallization_t2"]["compiled_agency_zipf085_live_stream"]
        self.assertGreater(st["stage_routing_counts"]["stage1_crystallized_lut"], 10)


    def test_committed_real_llm_multi_substrate_receipts_and_orthogonality(self) -> None:
        import json
        from dnull_suite.crypto_receipt import blake3_derive_key_hex
        from dnull_suite.suite_runner import compile_and_load_dnull_lib
        from real_llm_eval import EXPECTED_GGUF_SHA256, _build_subset90_prompts

        bundle_p = KIT_ROOT / "results" / "real_llm_multi_substrate_receipts.json"
        master_p = KIT_ROOT / "results" / "receipt_real_llm_crystallization.json"
        self.assertTrue(bundle_p.is_file())
        self.assertTrue(master_p.is_file())

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
            "openie.kit.dnull_real_llm.multi_substrate.v1",
            json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        )
        self.assertEqual(master["body"]["payload"]["bundle_blake3"], expected_b3)
        self.assertEqual(bundle["pretrained_model"]["gguf_sha256"], EXPECTED_GGUF_SHA256)

        lib = compile_and_load_dnull_lib()
        ctx = lib.dnull_init()
        try:
            _, live_sha256, live_b3, _ = _build_subset90_prompts(lib, ctx)
        finally:
            lib.dnull_free(ctx)
        self.assertEqual(bundle["confirmatory_subset90"]["prompts_and_labels_sha256"], live_sha256)
        self.assertEqual(bundle["confirmatory_subset90"]["prompts_and_labels_blake3"], live_b3)

        # Verify strict measured_j vs reported_j orthogonality & per-substrate signatures
        for sub_name, sub in bundle["measured_j_substrates"].items():
            self.assertTrue(verify_signed_receipt(sub["signed_receipt"]), sub_name)
            r = sub["results"]
            self.assertEqual(r["energy_telemetry"]["evidence_class"], "measured_j")
            e_t1 = r["pretrained_transformer_cold_t1"]["energy_and_latency"]
            self.assertGreater(e_t1["gross_rail_measured_uj_per_correct"], 0.0)
            self.assertIsNone(e_t1["pkg_reported_uj_per_correct"])

        for sub_name, sub in bundle["reported_j_substrates"].items():
            self.assertTrue(verify_signed_receipt(sub["signed_receipt"]), sub_name)
            r = sub["results"]
            self.assertEqual(r["energy_telemetry"]["evidence_class"], "reported_j")
            e_t1 = r["pretrained_transformer_cold_t1"]["energy_and_latency"]
            self.assertGreater(e_t1["pkg_reported_uj_per_correct"], 0.0)
            self.assertIsNone(e_t1["gross_rail_measured_uj_per_correct"])


if __name__ == "__main__":
    unittest.main()
