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


if __name__ == "__main__":
    unittest.main()
