#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""OpenTelemetry Drop-In Span Builder, Validator, Orthogonal Rollup Guard,
and OTLP/JSON v1 Exporter (`otel/otel_joule_span.py`).

Defines & enforces the `semconv_openie_energy.yaml` contract (`Apache-2.0`, zero external deps):
  - `openie.energy.measured_j`
  - `openie.energy.reported_j`
  - `openie.energy.est_j`
  - `openie.energy.evidence_class` in {"measured_j", "reported_j", "est_j", "unmetered"}
  - `openie.gate.blake3` (64-char hex BLAKE3 digest)
  - `openie.provenance.tier` ("Signed Provenance · Self-Checked"; bare "Verified" rejected)

Raises `OrthogonalityViolationError` on ANY attempt to:
  1. Populate multiple joule fields (`measured_j`, `reported_j`, `est_j`) on one span,
  2. Mismatch `openie.energy.evidence_class` with the populated joule attribute (or set joules on `unmetered`),
  3. Sum, combine, or roll up joules across distinct evidence classes (`measured_j + reported_j`, etc.).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ATTR_MEASURED_J = "openie.energy.measured_j"
ATTR_REPORTED_J = "openie.energy.reported_j"
ATTR_EST_J = "openie.energy.est_j"
ATTR_EVIDENCE_CLASS = "openie.energy.evidence_class"
ATTR_SENSOR_DOMAIN = "openie.energy.sensor_domain"
ATTR_GATE_BLAKE3 = "openie.gate.blake3"
ATTR_GATE_VERDICT = "openie.gate.verdict"
ATTR_PROVENANCE_TIER = "openie.provenance.tier"

VALID_EVIDENCE_CLASSES = ("measured_j", "reported_j", "est_j", "unmetered")
CLASS_TO_JOULE_ATTR = {
    "measured_j": ATTR_MEASURED_J,
    "reported_j": ATTR_REPORTED_J,
    "est_j": ATTR_EST_J,
}
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


class OrthogonalityViolationError(ValueError):
    """Raised when an OpenTelemetry span or aggregation mixes orthogonal energy classes
    (`measured_j ⊥ reported_j ⊥ est_j ⊥ unmetered`) or violates OpenIE epistemic rules.
    """


@dataclass
class OpenIEJouleSpan:
    name: str
    trace_id_hex: str
    span_id_hex: str
    start_time_unix_nano: int
    end_time_unix_nano: int
    attributes: dict[str, Any] = field(default_factory=dict)
    parent_span_id_hex: str = ""
    status_code: str = "STATUS_CODE_OK"


def validate_openie_span_attributes(attrs: dict[str, Any]) -> None:
    """Validate single-span attribute orthogonality and provenance invariants."""
    ev_class = attrs.get(ATTR_EVIDENCE_CLASS)
    if ev_class not in VALID_EVIDENCE_CLASSES:
        raise OrthogonalityViolationError(
            f"Missing or invalid `{ATTR_EVIDENCE_CLASS}`: {ev_class!r} (expected one of {VALID_EVIDENCE_CLASSES})"
        )

    populated_joule_attrs = [
        k for k in (ATTR_MEASURED_J, ATTR_REPORTED_J, ATTR_EST_J) if attrs.get(k) is not None
    ]
    if len(populated_joule_attrs) > 1:
        raise OrthogonalityViolationError(
            f"Span populates multiple orthogonal joule attributes {populated_joule_attrs}; "
            "measured_j, reported_j, and est_j must never coexist on a single span."
        )

    if ev_class == "unmetered":
        if populated_joule_attrs:
            raise OrthogonalityViolationError(
                f"Span has `{ATTR_EVIDENCE_CLASS} == 'unmetered'` but populates {populated_joule_attrs}!"
            )
    else:
        expected_attr = CLASS_TO_JOULE_ATTR[ev_class]
        if populated_joule_attrs != [expected_attr]:
            raise OrthogonalityViolationError(
                f"Span `{ATTR_EVIDENCE_CLASS} == {ev_class!r}` requires `{expected_attr}` and no other joule field, "
                f"got {populated_joule_attrs}."
            )
        val = attrs[expected_attr]
        if isinstance(val, bool) or not isinstance(val, (int, float)) or val < 0.0:
            raise OrthogonalityViolationError(f"`{expected_attr}` must be a non-negative float, got {val!r}")

    blake3_val = attrs.get(ATTR_GATE_BLAKE3)
    if not isinstance(blake3_val, str) or not _HEX64_RE.match(blake3_val):
        raise OrthogonalityViolationError(
            f"`{ATTR_GATE_BLAKE3}` must be a 64-character lowercase hex BLAKE3 digest, got {blake3_val!r}"
        )

    prov = attrs.get(ATTR_PROVENANCE_TIER, "Signed Provenance · Self-Checked")
    if prov.strip().lower() == "verified":
        raise OrthogonalityViolationError(
            f"Self-audited span cannot claim bare `{ATTR_PROVENANCE_TIER} = 'Verified'`; "
            "use `'Signed Provenance · Self-Checked'`."
        )


def create_gated_energy_span(
    name: str,
    *,
    evidence_class: str,
    joules: float | None,
    gate_blake3: str,
    gate_verdict: str = "COMMIT",
    sensor_domain: str = "unmetered",
    duration_ns: int = 250_000,
    trace_seed: str = "openie-trace",
    provenance_tier: str = "Signed Provenance · Self-Checked",
) -> OpenIEJouleSpan:
    """Construct and validate a standards-compliant OpenIE OpenTelemetry span."""
    t_start = 1_795_852_800_000_000_000
    t_end = t_start + max(1, int(duration_ns))
    h = hashlib.sha256(f"{trace_seed}:{name}:{evidence_class}:{gate_blake3}".encode("utf-8")).hexdigest()
    attrs: dict[str, Any] = {
        ATTR_EVIDENCE_CLASS: evidence_class,
        ATTR_SENSOR_DOMAIN: sensor_domain,
        ATTR_GATE_BLAKE3: gate_blake3,
        ATTR_GATE_VERDICT: gate_verdict,
        ATTR_PROVENANCE_TIER: provenance_tier,
    }
    if joules is not None:
        if evidence_class not in CLASS_TO_JOULE_ATTR:
            # Trigger OrthogonalityViolationError cleanly in validator
            attrs[ATTR_REPORTED_J] = joules
        else:
            attrs[CLASS_TO_JOULE_ATTR[evidence_class]] = float(joules)

    validate_openie_span_attributes(attrs)
    return OpenIEJouleSpan(
        name=name,
        trace_id_hex=h[:32],
        span_id_hex=h[32:48],
        start_time_unix_nano=t_start,
        end_time_unix_nano=t_end,
        attributes=attrs,
    )


def sum_spans_single_class(spans: list[OpenIEJouleSpan]) -> tuple[str, float]:
    """Strict homogeneous energy sum: raises `OrthogonalityViolationError` if spans come from
    more than one energy evidence class (e.g., attempting `measured_j + reported_j` or `+ est_j`).
    """
    if not spans:
        return ("unmetered", 0.0)
    seen_classes: set[str] = set()
    total_j = 0.0
    for sp in spans:
        validate_openie_span_attributes(sp.attributes)
        ec = sp.attributes[ATTR_EVIDENCE_CLASS]
        seen_classes.add(ec)
        if len(seen_classes) > 1:
            raise OrthogonalityViolationError(
                f"Illegal cross-class energy summation across {sorted(seen_classes)}! "
                "OpenIE orthogonality (`measured_j ⊥ reported_j ⊥ est_j ⊥ unmetered`) prohibits summing heterogeneous joule classes."
            )
        if ec in CLASS_TO_JOULE_ATTR:
            total_j += float(sp.attributes[CLASS_TO_JOULE_ATTR[ec]])
    only_class = next(iter(seen_classes))
    return (only_class, round(total_j, 9))


def partition_and_rollup_orthogonal(spans: list[OpenIEJouleSpan]) -> dict[str, Any]:
    """Safe partitioned rollup keeping `measured_j`, `reported_j`, `est_j`, and `unmetered` strictly disjoint."""
    buckets: dict[str, list[float]] = {"measured_j": [], "reported_j": [], "est_j": []}
    unmetered_spans = 0
    for sp in spans:
        validate_openie_span_attributes(sp.attributes)
        ec = sp.attributes[ATTR_EVIDENCE_CLASS]
        if ec == "unmetered":
            unmetered_spans += 1
        else:
            buckets[ec].append(float(sp.attributes[CLASS_TO_JOULE_ATTR[ec]]))
    return {
        "measured_j_total": round(sum(buckets["measured_j"]), 9) if buckets["measured_j"] else None,
        "measured_j_span_count": len(buckets["measured_j"]),
        "reported_j_total": round(sum(buckets["reported_j"]), 9) if buckets["reported_j"] else None,
        "reported_j_span_count": len(buckets["reported_j"]),
        "est_j_total": round(sum(buckets["est_j"]), 9) if buckets["est_j"] else None,
        "est_j_span_count": len(buckets["est_j"]),
        "unmetered_span_count": unmetered_spans,
        "cross_class_sum_prohibited": True,
    }


def _otlp_any_value(val: Any) -> dict[str, Any]:
    if isinstance(val, bool):
        return {"boolValue": val}
    if isinstance(val, int):
        return {"intValue": str(val)}
    if isinstance(val, float):
        return {"doubleValue": val}
    return {"stringValue": str(val)}


class OTLPJsonJouleSpanExporter:
    """Zero-dependency OpenTelemetry Protocol (`OTLP/JSON` v1 `ExportTraceServiceRequest`) span exporter
    with mandatory pre-export `OrthogonalityViolationError` enforcement.
    """

    def __init__(self, service_name: str = "openie-standards-bridge", service_version: str = "1.0.0") -> None:
        self.service_name = service_name
        self.service_version = service_version
        self._exported_batches: list[dict[str, Any]] = []

    def export(self, spans: list[OpenIEJouleSpan]) -> dict[str, Any]:
        otlp_spans: list[dict[str, Any]] = []
        for sp in spans:
            validate_openie_span_attributes(sp.attributes)
            otlp_attrs = [
                {"key": k, "value": _otlp_any_value(v)}
                for k, v in sorted(sp.attributes.items())
                if v is not None
            ]
            otlp_spans.append(
                {
                    "traceId": sp.trace_id_hex,
                    "spanId": sp.span_id_hex,
                    "parentSpanId": sp.parent_span_id_hex,
                    "name": sp.name,
                    "kind": 1,  # SPAN_KIND_INTERNAL
                    "startTimeUnixNano": str(sp.start_time_unix_nano),
                    "endTimeUnixNano": str(sp.end_time_unix_nano),
                    "attributes": otlp_attrs,
                    "status": {"code": 1 if sp.status_code == "STATUS_CODE_OK" else 2},
                }
            )
        payload = {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": self.service_name}},
                            {"key": "service.version", "value": {"stringValue": self.service_version}},
                            {"key": "telemetry.sdk.language", "value": {"stringValue": "python"}},
                            {"key": "openie.semconv.schema", "value": {"stringValue": "semconv_openie_energy.v1"}},
                        ]
                    },
                    "scopeSpans": [
                        {
                            "scope": {"name": "openie.otel.joule_exporter", "version": self.service_version},
                            "spans": otlp_spans,
                        }
                    ],
                }
            ]
        }
        self._exported_batches.append(payload)
        return payload


class TestOTelJouleSpan(unittest.TestCase):
    GATE_DIGEST = "a541323b13653ed36515ff24ef08deb7dfa771e570a434712708fb72552f46f0"

    def test_valid_orthogonal_spans_and_otlp_export(self) -> None:
        s_meas = create_gated_energy_span(
            "kv260.lut6_commit",
            evidence_class="measured_j",
            joules=0.00412,
            gate_blake3=self.GATE_DIGEST,
            sensor_domain="INA260:SOM_5V_DC",
        )
        s_rep = create_gated_energy_span(
            "zen5.wasm_gate",
            evidence_class="reported_j",
            joules=0.01845,
            gate_blake3=self.GATE_DIGEST,
            sensor_domain="intel-rapl:0:package-0",
        )
        s_est = create_gated_energy_span(
            "vcd.toggle_model",
            evidence_class="est_j",
            joules=0.000362,
            gate_blake3=self.GATE_DIGEST,
            sensor_domain="ds925_analytical",
        )
        s_unm = create_gated_energy_span(
            "darwin.unprivileged_gate",
            evidence_class="unmetered",
            joules=None,
            gate_blake3=self.GATE_DIGEST,
        )
        exporter = OTLPJsonJouleSpanExporter()
        otlp_doc = exporter.export([s_meas, s_rep, s_est, s_unm])
        self.assertEqual(len(otlp_doc["resourceSpans"][0]["scopeSpans"][0]["spans"]), 4)
        rollup = partition_and_rollup_orthogonal([s_meas, s_rep, s_est, s_unm])
        self.assertAlmostEqual(rollup["measured_j_total"], 0.00412)
        self.assertAlmostEqual(rollup["reported_j_total"], 0.01845)
        self.assertAlmostEqual(rollup["est_j_total"], 0.000362)
        self.assertEqual(rollup["unmetered_span_count"], 1)

    def test_orthogonality_guard_rejects_mixed_span_and_cross_class_sums(self) -> None:
        # 1. Dual joule attributes on one span -> OrthogonalityViolationError
        bad_attrs = {
            ATTR_EVIDENCE_CLASS: "measured_j",
            ATTR_MEASURED_J: 0.01,
            ATTR_REPORTED_J: 0.02,
            ATTR_GATE_BLAKE3: self.GATE_DIGEST,
        }
        with self.assertRaises(OrthogonalityViolationError):
            validate_openie_span_attributes(bad_attrs)

        # 2. Summing `measured_j` + `reported_j` -> OrthogonalityViolationError
        s1 = create_gated_energy_span("a", evidence_class="measured_j", joules=0.1, gate_blake3=self.GATE_DIGEST)
        s2 = create_gated_energy_span("b", evidence_class="reported_j", joules=0.2, gate_blake3=self.GATE_DIGEST)
        s3 = create_gated_energy_span("c", evidence_class="est_j", joules=0.3, gate_blake3=self.GATE_DIGEST)
        with self.assertRaises(OrthogonalityViolationError):
            sum_spans_single_class([s1, s2])
        with self.assertRaises(OrthogonalityViolationError):
            sum_spans_single_class([s1, s3])
        with self.assertRaises(OrthogonalityViolationError):
            sum_spans_single_class([s2, s3])

        # 3. Bare "Verified" provenance rejected
        with self.assertRaises(OrthogonalityViolationError):
            create_gated_energy_span(
                "bad_prov",
                evidence_class="reported_j",
                joules=0.05,
                gate_blake3=self.GATE_DIGEST,
                provenance_tier="Verified",
            )


def run_otel_module(out_dir: Path | None = None) -> dict[str, Any]:
    t0 = time.perf_counter_ns()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestOTelJouleSpan)
    res = unittest.TextTestRunner(stream=open(Path("/dev/null"), "w")).run(suite)
    if not res.wasSuccessful():
        raise RuntimeError(f"OTel Joule Span unit tests failed: {res.failures} {res.errors}")

    gate_b3 = TestOTelJouleSpan.GATE_DIGEST
    sample_spans = [
        create_gated_energy_span(
            "openie.gate.ina3221_shunt",
            evidence_class="measured_j",
            joules=0.003910,
            gate_blake3=gate_b3,
            sensor_domain="INA3221:VDD_CPU_SOC_MSS",
        ),
        create_gated_energy_span(
            "openie.gate.linux_rapl_pkg",
            evidence_class="reported_j",
            joules=0.014280,
            gate_blake3=gate_b3,
            sensor_domain="intel-rapl:0:package-0",
        ),
        create_gated_energy_span(
            "openie.gate.ds925_vcd_toggle",
            evidence_class="est_j",
            joules=0.000362,
            gate_blake3=gate_b3,
            sensor_domain="amd_ds925_analytical",
        ),
        create_gated_energy_span(
            "openie.gate.unprivileged_container",
            evidence_class="unmetered",
            joules=None,
            gate_blake3=gate_b3,
            sensor_domain="unmetered",
        ),
    ]
    exporter = OTLPJsonJouleSpanExporter()
    otlp_payload = exporter.export(sample_spans)
    rollup = partition_and_rollup_orthogonal(sample_spans)

    # Confirm guard trips on all 3 cross-class pairs
    guard_trips = 0
    for idx_a, idx_b in ((0, 1), (0, 2), (1, 2)):
        try:
            sum_spans_single_class([sample_spans[idx_a], sample_spans[idx_b]])
        except OrthogonalityViolationError:
            guard_trips += 1
    assert guard_trips == 3

    semconv_path = Path(__file__).resolve().parent / "semconv_openie_energy.yaml"
    semconv_sha256 = hashlib.sha256(semconv_path.read_bytes()).hexdigest()

    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "sample_otlp_energy_spans.json").write_text(
            json.dumps(otlp_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    elapsed_us = round((time.perf_counter_ns() - t0) / 1e3, 2)
    return {
        "module": "otel/otel_joule_span.py",
        "semconv_file": "otel/semconv_openie_energy.yaml",
        "semconv_sha256": semconv_sha256,
        "unit_tests_run": res.testsRun,
        "unit_tests_passed": res.testsRun,
        "orthogonality_guard_cross_class_rejections_verified": guard_trips,
        "sample_otlp_spans_exported": len(sample_spans),
        "partitioned_rollup": rollup,
        "validation_wall_us": elapsed_us,
    }


if __name__ == "__main__":
    summary = run_otel_module()
    print(json.dumps(summary, indent=2))
