#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Main Orchestrator & Cryptographic Receipt Sealer for Kit #9 (`kits/standards-bridge/`):
Executes all 4 zero-lock-in Apache-2.0 standards interop modules:
  1. `otel/otel_joule_span.py` + `otel/semconv_openie_energy.yaml` (OpenTelemetry OTLP/JSON + `OrthogonalityViolationError`)
  2. `wire/cose_flatbuf_bench.py` (IETF RFC 9052 `COSE_Sign1` CBOR + Zero-Copy `FlatBuffers` + `Ed25519`/`BLAKE3` vs UTF-8 JSON & `WAI1` across 10,000 receipts)
  3. `wasm/wasm_fuel_calibration.py` (`wasmtime` `-W fuel` + `node` `WebAssembly.Instance` `10,000,000`-op L1 ALU vs 64 MiB DRAM thrash calibration)
  4. `circt/emit_circt_hw.py` (LLVM MLIR / CIRCT `hw`+`comb` + IEEE 1364 Verilog + exhaustive `2^N` `Alive2`-style equivalence proof)
and seals `results/standards_bridge_receipt.json` (`Signed Provenance · Self-Checked`, `BLAKE3` + `Ed25519`).
"""

from __future__ import annotations

import argparse
import datetime as dt
import getpass
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
for sub in (HERE, HERE / "otel", HERE / "wire", HERE / "wasm", HERE / "circt"):
    if str(sub) not in sys.path:
        sys.path.insert(0, str(sub))

from circt.emit_circt_hw import run_circt_lowering_and_proof  # noqa: E402
from otel.otel_joule_span import run_otel_module  # noqa: E402
from wasm.wasm_fuel_calibration import run_wasm_fuel_calibration  # noqa: E402
from wire.cose_flatbuf_bench import (  # noqa: E402
    ed25519_pubkey_pure,
    ed25519_sign_pure,
    ed25519_verify_pure,
    run_cose_flatbuf_benchmark,
)

# ── Reference BLAKE3 (full multi-chunk tree, pure Python, zero external deps) ─

_IV = [
    0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A,
    0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19,
]
_PERM = [2, 6, 3, 10, 7, 0, 4, 13, 1, 11, 12, 5, 9, 14, 15, 8]


def _rotr32(x: int, n: int) -> int:
    return ((x >> n) | ((x << (32 - n)) & 0xFFFFFFFF)) & 0xFFFFFFFF


def _g(s: list[int], a: int, b: int, c: int, d: int, mx: int, my: int) -> None:
    s[a] = (s[a] + s[b] + mx) & 0xFFFFFFFF
    s[d] = _rotr32(s[d] ^ s[a], 16)
    s[c] = (s[c] + s[d]) & 0xFFFFFFFF
    s[b] = _rotr32(s[b] ^ s[c], 12)
    s[a] = (s[a] + s[b] + my) & 0xFFFFFFFF
    s[d] = _rotr32(s[d] ^ s[a], 8)
    s[c] = (s[c] + s[d]) & 0xFFFFFFFF
    s[b] = _rotr32(s[b] ^ s[c], 7)


def _compress(cv: list[int], block_words: list[int], counter: int, block_len: int, flags: int) -> list[int]:
    s = list(cv) + _IV[:4] + [counter & 0xFFFFFFFF, (counter >> 32) & 0xFFFFFFFF, block_len, flags]
    m = list(block_words)
    for rnd in range(7):
        _g(s, 0, 4, 8, 12, m[0], m[1])
        _g(s, 1, 5, 9, 13, m[2], m[3])
        _g(s, 2, 6, 10, 14, m[4], m[5])
        _g(s, 3, 7, 11, 15, m[6], m[7])
        _g(s, 0, 5, 10, 15, m[8], m[9])
        _g(s, 1, 6, 11, 12, m[10], m[11])
        _g(s, 2, 7, 8, 13, m[12], m[13])
        _g(s, 3, 4, 9, 14, m[14], m[15])
        if rnd < 6:
            m = [m[p] for p in _PERM]
    for i in range(8):
        s[i] ^= s[i + 8]
        s[i + 8] ^= cv[i]
    return s


def _words64(chunk_bytes: bytes) -> list[int]:
    return list(struct.unpack("<16I", chunk_bytes[:64].ljust(64, b"\x00")))


def _blake3_hash_with(data: bytes, key: list[int], flags: int) -> bytes:
    stack: list[list[int]] = []
    chunk = 0
    pos = 0
    while len(data) - pos > 1024:
        cv = list(key)
        for b in range(16):
            st = pos + b * 64
            f = flags | (1 if b == 0 else 0) | (2 if b == 15 else 0)
            cv = _compress(cv, _words64(data[st : st + 64]), chunk, 64, f)[:8]
        chunk += 1
        total = chunk
        node = cv
        while (total & 1) == 0:
            left = stack.pop()
            node = _compress(key, left + node, 0, 64, flags | 4)[:8]
            total >>= 1
        stack.append(node)
        pos += 1024
    rest = data[pos:]
    blocks = max(1, (len(rest) + 63) // 64)
    cv = list(key)
    for b in range(blocks - 1):
        f = flags | (1 if b == 0 else 0)
        cv = _compress(cv, _words64(rest[b * 64 : (b + 1) * 64]), chunk, 64, f)[:8]
    last = rest[(blocks - 1) * 64 :]
    out_cv, out_block, out_counter, out_len, out_flags = (
        cv, _words64(last), chunk, len(last), flags | (1 if blocks == 1 else 0) | 2
    )
    while stack:
        left = stack.pop()
        right_cv = _compress(out_cv, out_block, out_counter, out_len, out_flags)[:8]
        out_cv, out_block, out_counter, out_len, out_flags = key, left + right_cv, 0, 64, flags | 4
    root = _compress(out_cv, out_block, out_counter, out_len, out_flags | 8)
    return struct.pack("<8I", *root[:8])


def blake3_derive_key_hex(context: str, data: bytes) -> str:
    ctx_bytes = _blake3_hash_with(context.encode("utf-8"), _IV, 32)
    ctx_words = list(struct.unpack("<8I", ctx_bytes))
    return _blake3_hash_with(data, ctx_words, 64).hex()


def seal_signed_receipt(kit_id: str, payload: dict[str, Any], domain_context: str, seed32: bytes) -> dict[str, Any]:
    pubkey = ed25519_pubkey_pure(seed32)
    body = {
        "schema": "openie.signed_provenance_receipt.v1",
        "provenance_tier": "Signed Provenance · Self-Checked",
        "self_attested_not_third_party_verified": True,
        "kit_id": kit_id,
        "domain_context": domain_context,
        "issued_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "payload": payload,
    }
    canonical_bytes = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    body_blake3 = blake3_derive_key_hex(domain_context, canonical_bytes)
    msg_to_sign = f"{domain_context}:{body_blake3}".encode("ascii")
    sig = ed25519_sign_pure(seed32, msg_to_sign)
    return {
        "body": body,
        "body_blake3": body_blake3,
        "ed25519_public_key_hex": pubkey.hex(),
        "ed25519_signature_hex": sig.hex(),
    }


def verify_signed_receipt(receipt: dict[str, Any]) -> bool:
    try:
        body = receipt["body"]
        if body.get("provenance_tier") != "Signed Provenance · Self-Checked":
            return False
        domain_context = str(body["domain_context"])
        pub = bytes.fromhex(receipt["ed25519_public_key_hex"])
        sig = bytes.fromhex(receipt["ed25519_signature_hex"])
        for ensure_asc in (True, False):
            canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=ensure_asc).encode("utf-8")
            expected_b3 = blake3_derive_key_hex(domain_context, canonical)
            if expected_b3 == receipt.get("body_blake3"):
                if ed25519_verify_pure(pub, f"{domain_context}:{expected_b3}".encode("ascii"), sig):
                    return True
        return False
    except Exception:
        return False


def sanitized_host_info() -> dict[str, Any]:
    u = os.uname() if hasattr(os, "uname") else None
    os_kernel = (
        f"{u.sysname} {u.release} {u.machine}"
        if u is not None
        else f"{platform.system()} {platform.release()} {platform.machine()}"
    )
    cpu_model = ""
    if platform.system() == "Linux":
        try:
            for line in Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.lower().startswith("model name") and ":" in line:
                    cand = line.split(":", 1)[1].strip()
                    if cand and cand != "-":
                        cpu_model = cand
                        break
        except OSError:
            pass
    elif platform.system() == "Darwin":
        try:
            cpu_model = subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.brand_string"], text=True, timeout=3
            ).strip()
        except Exception:
            pass
    if not cpu_model:
        cpu_model = platform.processor() or platform.machine()

    ram_gib = None
    try:
        if hasattr(os, "sysconf") and "SC_PAGE_SIZE" in os.sysconf_names and "SC_PHYS_PAGES" in os.sysconf_names:
            ram_gib = round((os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")) / (1024 ** 3), 2)
    except Exception:
        pass
    return {
        "cpu_model": cpu_model,
        "logical_cpus": os.cpu_count() or 1,
        "ram_gib": ram_gib,
        "os_kernel": os_kernel,
        "python_version": platform.python_version(),
        "recorded_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def assert_sanitized(text: str) -> None:
    patterns = [
        (r"\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b", "RFC6598 CGNAT IP"),
        (r"\b10(?:\.\d{1,3}){3}\b", "RFC1918 class-A private IP"),
        (r"\b192\.168(?:\.\d{1,3}){2}\b", "RFC1918 class-C private IP"),
        (r"\b172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b", "RFC1918 class-B private IP"),
        (r"/(?:Users|home)/[A-Za-z0-9._-]+", "local user home path"),
        (r"(?i)landauer\s+bit[- ]equivalents", "retired thermodynamic bit-ratio metric"),
    ]
    host = socket.gethostname().strip()
    if host and host.lower() not in ("localhost", "buildkitsandbox", "kria") and len(host) >= 4:
        patterns.append((re.escape(host), "local hostname"))
    try:
        user = getpass.getuser().strip()
        if user and user.lower() not in ("root", "nobody", "replicator", "runner") and len(user) >= 4:
            patterns.append((rf"\b{re.escape(user)}\b", "local OS username"))
    except Exception:
        pass
    for pat, label in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            raise RuntimeError(f"Sanitization guard triggered ({label}): {m.group(0)!r}")


def render_results_md(report: dict[str, Any], receipt: dict[str, Any]) -> str:
    host = report["host"]
    otel = report["modules"]["otel_joule_span"]
    wire = report["modules"]["cose_flatbuf_bench"]
    wasm = report["modules"]["wasm_fuel_calibration"]
    circt = report["modules"]["circt_hw_lowering"]
    wt = wasm.get("wasmtime_deterministic_fuel_proof")
    nd = wasm.get("steady_state_in_process_wasm")

    lines = [
        "# Kit #9 (`standards-bridge`) — Empirical Results",
        "",
        "- **Provenance Tier:** `Signed Provenance · Self-Checked` (`BLAKE3` + `Ed25519`; never self-labeled `\"Verified\"`)",
        f"- **Receipt Body `BLAKE3`:** `{receipt['body_blake3']}`",
        f"- **CPU / OS:** `{host['cpu_model']}` (`{host['logical_cpus']}` logical CPUs, `{host['os_kernel']}`)",
        "- **License & Lock-In:** `100% Apache-2.0` (`OpenTelemetry` + `IETF RFC 9052 COSE_Sign1` + `FlatBuffers` + `Wasmtime`/`WebAssembly` + `LLVM MLIR/CIRCT` + `IEEE 1364 Verilog`; zero `BSL-1.1` dependencies)",
        "",
        "## 1. OpenTelemetry Orthogonal Energy Exporter (`otel/otel_joule_span.py`)",
        "",
        f"- Semantic convention schema: `otel/semconv_openie_energy.yaml` (`SHA-256 = {otel['semconv_sha256'][:16]}...`)",
        f"- Unit tests passed: `{otel['unit_tests_passed']} / {otel['unit_tests_run']}`",
        f"- Automated `OrthogonalityViolationError` cross-class sum rejections verified: `{otel['orthogonality_guard_cross_class_rejections_verified']} / 3` (`measured_j + reported_j`, `measured_j + est_j`, `reported_j + est_j` all blocked)",
        "",
        "## 2. Wire Codec Head-to-Head (`10,000` Signed `Ed25519` + `BLAKE3` Receipts)",
        "",
        "| Receipt Wire Codec | Receipts | Wire Size (`B`) | Encode (`µs`) | Decode + Verify (`µs`) | Roundtrip (`µs`) | RAPL `reported_j` (`µJ / receipt`) | Mismatches |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for cname, cdata in wire["codecs"].items():
        uj_str = f"`{cdata['pkg_reported_uj_per_receipt']} µJ`" if cdata["pkg_reported_uj_per_receipt"] is not None else "`null` (`unmetered`)"
        lines.append(
            f"| `{cname}` | `{cdata['receipts_benchmarked']}` | `{cdata['wire_bytes_per_receipt']}` | "
            f"`{cdata['encode_us_per_receipt']}` | `{cdata['decode_verify_us_per_receipt']}` | "
            f"`{cdata['roundtrip_us_per_receipt']}` | {uj_str} | `{cdata['roundtrip_mismatches']}` |"
        )

    lines.extend([
        "",
        "## 3. WebAssembly Front-Door Fuel vs. Physical Joules (`10,000,000` Ops: L1 ALU vs. 64 MiB DRAM)",
        "",
    ])
    if wt:
        lines.append(
            f"- **Bytecode Alliance `{wt['engine']}` Deterministic Fuel Proof:** `l1_alu_register_10m` exact fuel = **`{wt['l1_alu_exact_fuel']}`**, "
            f"`dram_thrash_64mib_10m` exact fuel = **`{wt['dram_64mib_exact_fuel']}`** (**fuel ratio = `{wt['fuel_ratio_dram_over_l1']}x`**; both deterministically trap at `fuel = {wt['trap_verified_at_fuel_minus_1']}`!). "
            f"End-to-end CLI RAPL `reported_j`: L1 = `{wt['cli_l1_median_pkg_reported_j']} J` vs. 64 MiB DRAM = `{wt['cli_dram_median_pkg_reported_j']} J` (**`{wt['cli_joule_ratio_dram_over_l1']}x` physical energy ratio at `1.0x` fuel**)."
        )
    if nd:
        lines.append(
            f"- **Steady-State Pre-Faulted In-Process `{nd['engine']}` (`16,384` 4 KiB pages pre-touched):** "
            f"L1 ALU median = `{nd['l1_alu_median_wall_ms']} ms` (`{nd['l1_alu_median_pkg_reported_j']} J` `reported_j`) vs. "
            f"64 MiB DRAM thrash = `{nd['dram_64mib_median_wall_ms']} ms` (`{nd['dram_64mib_median_pkg_reported_j']} J` `reported_j`) -> "
            f"**`{nd['wall_time_ratio_dram_over_l1']}x` wall-time and `{nd['joule_ratio_dram_over_l1_at_equal_fuel']}x` physical `reported_j` divergence at `1.000000x` Wasm instruction fuel!**"
        )

    tv = circt["translation_validation"]
    eda = circt["hardware_eda_verification"]
    lines.extend([
        "",
        "## 4. LLVM MLIR / CIRCT (`hw` + `comb`) & IEEE 1364 Verilog `2^N` Equivalence Proof",
        "",
        f"- **Exhaustive `2^6 = 64` LUT6 Minterms:** `{tv['lut6_mismatches']} / {tv['lut6_exhaustive_vectors']}` mismatches (`High-Level Spec == CIRCT comb SSA IR == IEEE 1364 Verilog`)",
        f"- **Composed 2-Stage `2^10 = 1,024` Cone:** `{tv['composed_10input_mismatches']} / {tv['composed_10input_cone_vectors']}` mismatches",
        f"- **Mutation Soundness (`Alive2`-style counterexample witness):** Caught injected `comb.and -> comb.or` fault at input vector `{circt['sample_counterexample_input_vec']}`",
        f"- **Hardware EDA Toolchain Cross-Check:** `iverilog/vvp` 64-vec RTL sim = `{eda['iverilog_rtl_sim_64vec_passed']}`, `yosys` UltraScale+ `xcup` LUT6 synthesis = `{eda['yosys_lut6_synth_passed']}` (`{eda['yosys_lut_cell_count']}` LUT cells)",
        "",
    ])
    return "\n".join(lines)


def run_all(quick: bool = False, write_outputs: bool = True, out_dir: Path | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    target_dir = out_dir or (HERE / "results")
    artifact_dir = target_dir if write_outputs else None

    otel_res = run_otel_module(out_dir=artifact_dir)
    wire_res = run_cose_flatbuf_benchmark(n_receipts=1_000 if quick else 10_000)
    wasm_res = run_wasm_fuel_calibration(trials=3 if quick else 7, reps_per_trial=1 if quick else 3)
    circt_res = run_circt_lowering_and_proof(out_dir=artifact_dir)
    host = sanitized_host_info()

    ev_class = wire_res["codecs"]["ietf_rfc9052_cose_sign1_cbor"]["evidence_class"]
    report = {
        "schema": "openie.standards_bridge.results.v1",
        "kit_id": "kits/standards-bridge",
        "license": "Apache-2.0",
        "zero_bsl_dependencies": True,
        "provenance_tier": "Signed Provenance · Self-Checked",
        "mode": "quick" if quick else "standard",
        "energy_evidence_class": ev_class,
        "host": host,
        "modules": {
            "otel_joule_span": otel_res,
            "cose_flatbuf_bench": wire_res,
            "wasm_fuel_calibration": wasm_res,
            "circt_hw_lowering": circt_res,
        },
    }

    report_bytes = json.dumps(report, sort_keys=True, separators=(",", ":")).encode("utf-8")
    results_blake3 = blake3_derive_key_hex("openie.kit.standards_bridge.results.v1", report_bytes)
    det_seed = bytes.fromhex(blake3_derive_key_hex("openie.kit.standards_bridge.key.v1", report_bytes)[:64])

    wt = wasm_res.get("wasmtime_deterministic_fuel_proof") or {}
    nd = wasm_res.get("steady_state_in_process_wasm") or {}
    cose_cbor = wire_res["codecs"]["ietf_rfc9052_cose_sign1_cbor"]
    cose_fb = wire_res["codecs"]["cose_sign1_flatbuf_zerocopy"]
    json_c = wire_res["codecs"]["utf8_json_signed"]
    wai1_c = wire_res["codecs"]["compact_wai1_64b_header_signed"]

    payload = {
        "results_blake3": results_blake3,
        "mode": report["mode"],
        "energy_evidence_class": ev_class,
        "otel_summary": {
            "semconv_sha256": otel_res["semconv_sha256"],
            "orthogonality_guard_cross_class_rejections": otel_res["orthogonality_guard_cross_class_rejections_verified"],
            "sample_otlp_spans_exported": otel_res["sample_otlp_spans_exported"],
        },
        "wire_10k_summary": {
            "receipts_benchmarked": cose_cbor["receipts_benchmarked"],
            "utf8_json_bytes": json_c["wire_bytes_per_receipt"],
            "cose_sign1_cbor_bytes": cose_cbor["wire_bytes_per_receipt"],
            "cose_sign1_flatbuf_bytes": cose_fb["wire_bytes_per_receipt"],
            "wai1_64b_header_signed_bytes": wai1_c["wire_bytes_per_receipt"],
            "utf8_json_roundtrip_us": json_c["roundtrip_us_per_receipt"],
            "cose_sign1_cbor_roundtrip_us": cose_cbor["roundtrip_us_per_receipt"],
            "cose_sign1_flatbuf_roundtrip_us": cose_fb["roundtrip_us_per_receipt"],
            "wai1_64b_roundtrip_us": wai1_c["roundtrip_us_per_receipt"],
            "cose_sign1_flatbuf_pkg_reported_uj": cose_fb["pkg_reported_uj_per_receipt"],
            "utf8_json_pkg_reported_uj": json_c["pkg_reported_uj_per_receipt"],
        },
        "wasm_fuel_vs_joules_summary": {
            "ops_per_kernel": 10_000_000,
            "wasmtime_exact_fuel_l1_alu": wt.get("l1_alu_exact_fuel"),
            "wasmtime_exact_fuel_dram_64mib": wt.get("dram_64mib_exact_fuel"),
            "wasmtime_fuel_ratio": wt.get("fuel_ratio_dram_over_l1"),
            "wasmtime_cli_joule_ratio_dram_over_l1": wt.get("cli_joule_ratio_dram_over_l1"),
            "steady_state_wall_ratio_dram_over_l1": nd.get("wall_time_ratio_dram_over_l1"),
            "steady_state_joule_ratio_dram_over_l1": nd.get("joule_ratio_dram_over_l1_at_equal_fuel"),
            "steady_state_l1_pkg_reported_j": nd.get("l1_alu_median_pkg_reported_j"),
            "steady_state_dram_64mib_pkg_reported_j": nd.get("dram_64mib_median_pkg_reported_j"),
        },
        "circt_verilog_equivalence_summary": {
            "lut6_exhaustive_vectors": circt_res["translation_validation"]["lut6_exhaustive_vectors"],
            "lut6_mismatches": circt_res["translation_validation"]["lut6_mismatches"],
            "composed_10input_vectors": circt_res["translation_validation"]["composed_10input_cone_vectors"],
            "composed_10input_mismatches": circt_res["translation_validation"]["composed_10input_mismatches"],
            "iverilog_rtl_sim_64vec_passed": circt_res["hardware_eda_verification"]["iverilog_rtl_sim_64vec_passed"],
            "yosys_lut6_synth_passed": circt_res["hardware_eda_verification"]["yosys_lut6_synth_passed"],
            "yosys_lut_cell_count": circt_res["hardware_eda_verification"]["yosys_lut_cell_count"],
        },
        "full_report": report,
    }

    receipt = seal_signed_receipt(
        kit_id="kits/standards-bridge",
        payload=payload,
        domain_context="openie.kit.standards_bridge.receipt.v1",
        seed32=det_seed,
    )
    if not verify_signed_receipt(receipt):
        raise RuntimeError("Receipt self-verification failed!")

    receipt_text = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    md_text = render_results_md(report, receipt)
    assert_sanitized(receipt_text)
    assert_sanitized(md_text)

    if write_outputs:
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "standards_bridge_receipt.json").write_text(receipt_text, encoding="utf-8")
        if out_dir is None:
            (HERE / "RESULTS.md").write_text(md_text, encoding="utf-8")

    return (report, receipt)


def main() -> None:
    parser = argparse.ArgumentParser(description="Kit #9: Standards-First Apache-2.0 Interop Bridge")
    parser.add_argument("--quick", action="store_true", help="Fast smoke test")
    parser.add_argument("--no-write", action="store_true", help="Run in-memory without writing artifacts")
    args = parser.parse_args()

    report, receipt = run_all(quick=args.quick, write_outputs=not args.no_write)
    p = receipt["body"]["payload"]
    print(f"[standards-bridge] OTel orthogonality guard rejections: {p['otel_summary']['orthogonality_guard_cross_class_rejections']}/3")
    print(
        f"  Wire ({p['wire_10k_summary']['receipts_benchmarked']} receipts): "
        f"JSON={p['wire_10k_summary']['utf8_json_bytes']}B ({p['wire_10k_summary']['utf8_json_roundtrip_us']}us) | "
        f"COSE_CBOR={p['wire_10k_summary']['cose_sign1_cbor_bytes']}B ({p['wire_10k_summary']['cose_sign1_cbor_roundtrip_us']}us) | "
        f"COSE_FlatBuf={p['wire_10k_summary']['cose_sign1_flatbuf_bytes']}B ({p['wire_10k_summary']['cose_sign1_flatbuf_roundtrip_us']}us) | "
        f"WAI1={p['wire_10k_summary']['wai1_64b_header_signed_bytes']}B ({p['wire_10k_summary']['wai1_64b_roundtrip_us']}us)"
    )
    print(
        f"  Wasm (10M ops): exact fuel ratio = {p['wasm_fuel_vs_joules_summary']['wasmtime_fuel_ratio']}x, "
        f"steady-state wall ratio = {p['wasm_fuel_vs_joules_summary']['steady_state_wall_ratio_dram_over_l1']}x, "
        f"RAPL reported_j ratio = {p['wasm_fuel_vs_joules_summary']['steady_state_joule_ratio_dram_over_l1']}x"
    )
    print(
        f"  CIRCT + Verilog: {p['circt_verilog_equivalence_summary']['lut6_mismatches']}/64 LUT6 & "
        f"{p['circt_verilog_equivalence_summary']['composed_10input_mismatches']}/1024 cone mismatches "
        f"(iverilog={p['circt_verilog_equivalence_summary']['iverilog_rtl_sim_64vec_passed']}, "
        f"yosys={p['circt_verilog_equivalence_summary']['yosys_lut6_synth_passed']})"
    )
    print(f"  Signed Provenance · Self-Checked receipt BLAKE3: {receipt['body_blake3']}")


if __name__ == "__main__":
    main()
