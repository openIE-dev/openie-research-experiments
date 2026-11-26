# SPDX-License-Identifier: Apache-2.0
"""Unit & conformance tests for Kit 4 (`kits/littlebit-joule/`)."""

from __future__ import annotations

import copy
import ctypes
import sys
import unittest
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parent.parent
if str(KIT_ROOT) not in sys.path:
    sys.path.insert(0, str(KIT_ROOT))

from littlebit_joule.benchmark import (  # noqa: E402
    SUBBIT_BPW,
    SUBBIT_BYTES,
    SUBBIT_STORAGE_BITS,
    TOTAL_WEIGHTS,
    compile_and_load_library,
    run_benchmark,
)
from littlebit_joule.crypto_receipt import (  # noqa: E402
    assert_sanitized,
    blake3_derive_key_hex,
    blake3_hex,
    clopper_pearson_upper,
    ed25519_pubkey_pure,
    ed25519_sign_pure,
    ed25519_verify_pure,
    seal_signed_receipt,
    verify_signed_receipt,
)


class TestLittleBitJouleKit(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.lib = compile_and_load_library()

    def test_subbit_budget_in_target_band(self) -> None:
        self.assertEqual(TOTAL_WEIGHTS, 262_144)
        self.assertEqual(SUBBIT_STORAGE_BITS, 39_776)
        self.assertEqual(SUBBIT_BYTES, 4_972)
        self.assertGreaterEqual(SUBBIT_BPW, 0.14)
        self.assertLessEqual(SUBBIT_BPW, 0.20)

    def test_integer_fwht_involutive_identity(self) -> None:
        """Verify H_512(H_512(x)) == 512 * x with zero floating-point arithmetic."""
        orig = [(i * 17 - 300) for i in range(512)]
        arr = (ctypes.c_int32 * 512)(*orig)
        self.lib.lb_fwht_i32(arr, 512)
        self.lib.lb_fwht_i32(arr, 512)
        for i in range(512):
            self.assertEqual(int(arr[i]), 512 * orig[i])

    def test_xnor_popcount_bipolar_dot_identity(self) -> None:
        """Verify 2*popcount(XNOR(a, b)) - 512 equals exact {-1,+1}^512 inner product."""
        a_words = (ctypes.c_uint64 * 8)(*[0xA5A5A5A55A5A5A5A ^ (w * 0x1111111111111111) for w in range(8)])
        b_words = (ctypes.c_uint64 * 8)(*[0xF0F0F0F00F0F0F0F ^ (w * 0x0123456789ABCDEF) for w in range(8)])
        got = self.lib.lb_bipolar_dot_xnor512(a_words, b_words)

        expected = 0
        for w in range(8):
            aw = int(a_words[w])
            bw = int(b_words[w])
            for bit in range(64):
                va = 1 if ((aw >> bit) & 1) else -1
                vb = 1 if ((bw >> bit) & 1) else -1
                expected += va * vb
        self.assertEqual(got, expected)

    def test_blake3_official_test_vectors_and_ed25519_tamper(self) -> None:
        # Official BLAKE3 empty-input test vector
        self.assertEqual(
            blake3_hex(b""),
            "af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262",
        )
        # RFC-8032 Test Vector 1 (empty message)
        seed1 = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
        pub1 = ed25519_pubkey_pure(seed1)
        sig1 = ed25519_sign_pure(seed1, b"")
        self.assertEqual(pub1.hex(), "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
        self.assertEqual(
            sig1.hex(),
            "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
            "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b",
        )
        self.assertTrue(ed25519_verify_pure(pub1, b"", sig1))

        # Signed receipt + single-bit tamper rejection
        rec = seal_signed_receipt("test-kit", {"metric": 42}, "openie.test.v1")
        self.assertTrue(verify_signed_receipt(rec))
        tampered = copy.deepcopy(rec)
        tampered["body"]["payload"]["metric"] = 43
        self.assertFalse(verify_signed_receipt(tampered))

        sig_tampered = copy.deepcopy(rec)
        b_sig = bytearray.fromhex(sig_tampered["ed25519_signature_hex"])
        b_sig[0] ^= 0x01
        sig_tampered["ed25519_signature_hex"] = b_sig.hex()
        self.assertFalse(verify_signed_receipt(sig_tampered))

    def test_end_to_end_quick_benchmark_and_impedance_tax(self) -> None:
        results, receipt, md = run_benchmark(quick=True)
        self.assertTrue(verify_signed_receipt(receipt))
        assert_sanitized(md)
        self.assertEqual(results["provenance_tier"], "Signed Provenance · Self-Checked")
        self.assertEqual(results["determinism_gate"]["divergent_runs"], 0)
        self.assertLess(clopper_pearson_upper(0, 40), 0.08)

        regs = results["regimes"]
        # Sub-bit packed int must exceed deterministic null accuracy and beat naive float unpack speed
        self.assertGreater(regs["littlebit_joule_packed_int"]["accuracy"], 0.85)
        self.assertGreater(
            regs["littlebit_joule_packed_int"]["accuracy"],
            regs["deterministic_null_lut"]["accuracy"],
        )
        self.assertLess(
            regs["littlebit_joule_packed_int"]["wall_ns_per_correct_decision"]["median"],
            regs["dense_int8_baseline"]["wall_ns_per_correct_decision"]["median"],
        )
        self.assertGreater(
            regs["subbit_naive_float_unpack"]["wall_ns_per_correct_decision"]["median"],
            regs["dense_int8_baseline"]["wall_ns_per_correct_decision"]["median"],
        )


if __name__ == "__main__":
    unittest.main()
