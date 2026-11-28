# SPDX-License-Identifier: Apache-2.0
"""Unit, AST Mutant-Kill, Grammar-Mask, and Cryptographic Receipt Tests
for Kit #8 (`kits/spec-fidelity-barrier/`).
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parent.parent
if str(KIT_ROOT) not in sys.path:
    sys.path.insert(0, str(KIT_ROOT))

from spec_barrier.ast_mutator import generate_ast_mutants  # noqa: E402
from spec_barrier.grammar_and_telemetry import (  # noqa: E402
    SplitMix64,
    _build_proposal_weights,
    clopper_pearson_interval,
    posthoc_parse_and_typecheck,
    sample_grammar_masked_stream,
    verify_signed_receipt,
)
from spec_barrier.task_suite import build_40_task_suite  # noqa: E402
from spec_barrier_eval import audit_spec_against_mutants, run_evaluation  # noqa: E402


class TestSpecFidelityBarrier(unittest.TestCase):
    def test_40_tasks_and_200_non_equivalent_ast_mutants(self) -> None:
        tasks = build_40_task_suite()
        self.assertEqual(len(tasks), 40)
        domains = {t.domain for t in tasks}
        self.assertEqual(
            domains,
            {
                "ring_buffers",
                "saturating_ledgers",
                "interval_schedules",
                "capability_acls",
                "parser_state_machines",
                "sorting_invariants",
            },
        )
        for t in tasks:
            muts = generate_ast_mutants(t)
            self.assertEqual(len(muts), 5)
            # Partial specs MUST be refused by the Mutant/Vacuity Barrier (`SPEC_VACUOUS_REFUSED`)
            rep_partial = audit_spec_against_mutants(t.partial_isolated_check, t, muts)
            self.assertEqual(rep_partial["status"], "SPEC_VACUOUS_REFUSED", f"Partial spec not refused on {t.task_id}")
            # Complete isolated specs MUST kill 100% of mutants (`SPEC_ADMITTED`)
            rep_complete = audit_spec_against_mutants(t.complete_isolated_check, t, muts)
            self.assertEqual(rep_complete["status"], "SPEC_ADMITTED")
            self.assertEqual(rep_complete["killed_mutants"], 5)

    def test_progressive_4_arms_ordering_and_clopper_pearson(self) -> None:
        report, receipt = run_evaluation(quick=True, write_outputs=False)
        self.assertTrue(verify_signed_receipt(receipt))
        arms = report["arms_abc"]["arms"]
        fa_a = arms["arm_a_shared_context_naive"]["defective_candidates_falsely_accepted"]
        fa_b = arms["arm_b_isolated_spec_only"]["defective_candidates_falsely_accepted"]
        fa_c = arms["arm_c_mutant_vacuity_barrier"]["defective_candidates_falsely_accepted"]
        self.assertGreater(fa_a, fa_b)
        self.assertGreater(fa_b, 0)
        self.assertEqual(fa_c, 0)
        ci0 = clopper_pearson_interval(0, 200)
        self.assertAlmostEqual(ci0["ci95_one_sided_hi"], 1.0 - (0.05 ** (1.0 / 200)), places=5)

    def test_grammar_mask_zero_syntax_waste_and_tamper_detection(self) -> None:
        rng = SplitMix64(1234567)
        for t_type in ("INT", "BOOL", "LIST"):
            weights = _build_proposal_weights(t_type, rng)
            for _ in range(50):
                toks = sample_grammar_masked_stream(weights, t_type, rng, max_compounds=3)
                ok, err = posthoc_parse_and_typecheck(toks, t_type)
                self.assertTrue(ok, f"Masked stream failed parse: {err}")

        committed_receipt = KIT_ROOT / "results" / "spec_fidelity_receipt.json"
        if committed_receipt.is_file():
            rec = json.loads(committed_receipt.read_text(encoding="utf-8"))
            self.assertTrue(verify_signed_receipt(rec))
            self.assertEqual(rec["body"]["provenance_tier"], "Signed Provenance · Self-Checked")
            # Tamper test: mutating payload invalidates signature
            rec["body"]["payload"]["total_tasks"] = 999
            self.assertFalse(verify_signed_receipt(rec))


if __name__ == "__main__":
    unittest.main()
