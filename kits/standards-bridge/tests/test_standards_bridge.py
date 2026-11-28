# SPDX-License-Identifier: Apache-2.0
"""Unit & Conformance Tests for Kit #9 (`kits/standards-bridge/`)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parent.parent
for sub in (KIT_ROOT, KIT_ROOT / "otel", KIT_ROOT / "wire", KIT_ROOT / "wasm", KIT_ROOT / "circt"):
    if str(sub) not in sys.path:
        sys.path.insert(0, str(sub))

from circt.emit_circt_hw import (  # noqa: E402
    emit_circt_mlir,
    emit_ieee1364_verilog,
    translation_validate_exhaustive_lut6,
)
from otel.otel_joule_span import (  # noqa: E402
    OrthogonalityViolationError,
    create_gated_energy_span,
    sum_spans_single_class,
)
from run_standards_bridge import verify_signed_receipt  # noqa: E402
from wire.cose_flatbuf_bench import (  # noqa: E402
    FastEd25519Signer,
    blake3_32,
    cose_sign1_decode_and_verify,
    cose_sign1_encode,
    flatbuf_encode_receipt_table,
    flatbuf_zerocopy_read,
)


class TestStandardsBridge(unittest.TestCase):
    GATE_B3 = "a541323b13653ed36515ff24ef08deb7dfa771e570a434712708fb72552f46f0"

    def test_otel_orthogonality_guard(self) -> None:
        s_meas = create_gated_energy_span("m", evidence_class="measured_j", joules=0.01, gate_blake3=self.GATE_B3)
        s_rep = create_gated_energy_span("r", evidence_class="reported_j", joules=0.02, gate_blake3=self.GATE_B3)
        s_est = create_gated_energy_span("e", evidence_class="est_j", joules=0.03, gate_blake3=self.GATE_B3)
        with self.assertRaises(OrthogonalityViolationError):
            sum_spans_single_class([s_meas, s_rep])
        with self.assertRaises(OrthogonalityViolationError):
            sum_spans_single_class([s_meas, s_est])
        with self.assertRaises(OrthogonalityViolationError):
            sum_spans_single_class([s_rep, s_est])

    def test_cose_sign1_and_flatbuf_zerocopy_roundtrip(self) -> None:
        signer = FastEd25519Signer(b"\x11" * 32)
        g_b3 = blake3_32(b"openie-cose-test")
        fb = flatbuf_encode_receipt_table(42, "reported_j", 0.00125, 98765, g_b3)
        self.assertEqual(len(fb), 80)
        wire = cose_sign1_encode(fb, signer)
        decoded_fb = cose_sign1_decode_and_verify(wire, signer, verify_sig=True)
        seq, ev, j, w_ns, got_b3 = flatbuf_zerocopy_read(decoded_fb)
        self.assertEqual((seq, ev, w_ns, got_b3), (42, "reported_j", 98765, g_b3))
        self.assertAlmostEqual(float(j), 0.00125)
        # Bit-flip tamper must reject signature
        tampered = wire[:-1] + bytes([wire[-1] ^ 0x01])
        with self.assertRaises(ValueError):
            cose_sign1_decode_and_verify(tampered, signer, verify_sig=True)

    def test_circt_comb_and_verilog_2n_equivalence(self) -> None:
        mlir = emit_circt_mlir()
        vlog = emit_ieee1364_verilog()
        tv = translation_validate_exhaustive_lut6(mlir, vlog)
        self.assertTrue(tv["bit_exact_proven"])
        self.assertEqual(tv["lut6_mismatches"], 0)
        self.assertEqual(tv["composed_10input_mismatches"], 0)
        # Single gate mutation must fail translation validation
        bad_tv = translation_validate_exhaustive_lut6(mlir, vlog.replace(" & ", " | ", 1))
        self.assertFalse(bad_tv["bit_exact_proven"])

    def test_committed_receipt_if_present(self) -> None:
        rec_path = KIT_ROOT / "results" / "standards_bridge_receipt.json"
        if rec_path.is_file():
            rec = json.loads(rec_path.read_text(encoding="utf-8"))
            self.assertTrue(verify_signed_receipt(rec))
            rec["body"]["payload"]["mode"] = "tampered"
            self.assertFalse(verify_signed_receipt(rec))


if __name__ == "__main__":
    unittest.main()
