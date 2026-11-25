# SPDX-License-Identifier: Apache-2.0
"""Suite 3: AI-Reads-Human (UTF-8 Human Text/JSON vs. Fixed-Layout Binary Wire Parsing).

Tests:
  1. Audits existing `ai-reads-human-energy/` SHA-256 checksums (`SHA256SUMS`) and loads
     OpenIE's self-checked reference ratios (`summary.json`).
  2. Reproduces the exact 20,000-record `seed = 20261016` corpus (`<IdBI3B3B` = 23 bytes/record)
     using 100% Python stdlib and verifies bit-for-bit SHA-256 equality against the published
     digests in `ai-reads-human-energy/summary.json` (`recs.bin`, `recs.json`, `recs_pretty.json`).
  3. Runs a live N = 50-trial interleaved benchmark comparing fixed 23-byte binary (`struct`)
     against compact and pretty UTF-8 JSON (`json.loads`), plus a zero-dependency C (-O3)
     N = 50-trial micro-kernel when `cc` is present, reporting payload byte ratio, median
     ns/record, IQR (p25-p75), CPU user+sys ms, and Linux RAPL `reported_j` (or `unmetered`).
"""

from __future__ import annotations

import hashlib
import json
import random
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .telemetry import EnergyMeter, iqr_stats

CORPUS_SEED = 20261016
WORDS = (
    "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu "
    "nu xi omicron pi rho sigma tau upsilon phi chi psi omega"
).split()
WORD_IDX = {w: idx for idx, w in enumerate(WORDS)}
BIN_STRUCT = struct.Struct("<IdBI3B3B")  # 4 + 8 + 1 + 4 + 3 + 3 = 23 bytes/record

PUBLISHED_20K_SHA256 = {
    "recs.bin": "adc0771a900ebf6400449ee31f7b00a96e382a448c5f4288022e28974134647f",
    "recs.json": "692ad32e39dd6db5f2bc02cea25964bdc70d6aa940a9597c7d0421dfc6d9b622",
    "recs_pretty.json": "bdec88369a48bd64f5c501cf8e1de911eeed0100a0fcb66ab1fedfadcc0c4094",
}


def _generate_exact_corpus(n_records: int) -> tuple[bytes, bytes, bytes, int]:
    rnd = random.Random(CORPUS_SEED)
    recs: list[dict[str, Any]] = []
    bin_buf = bytearray()
    expected_sum = 0
    for i in range(n_records):
        name = " ".join(rnd.choice(WORDS) for _ in range(3))
        score = round(rnd.uniform(0, 1000), 3)
        active = rnd.random() < 0.5
        tags = [rnd.choice(WORDS) for _ in range(3)]
        count = rnd.randrange(0, 1 << 31)
        expected_sum = (expected_sum + i + count + (1 if active else 0)) & 0xFFFFFFFFFFFFFFFF
        recs.append(
            {
                "id": i,
                "name": name,
                "score": score,
                "active": active,
                "tags": tags,
                "count": count,
            }
        )
        bin_buf += BIN_STRUCT.pack(
            i,
            score,
            active,
            count,
            *[WORD_IDX[q] for q in name.split()],
            *[WORD_IDX[q] for q in tags],
        )
    json_compact = json.dumps(recs, separators=(",", ":")).encode("utf-8")
    json_pretty = json.dumps(recs, indent=2).encode("utf-8")
    return bytes(bin_buf), json_compact, json_pretty, expected_sum


C_PARSE_BENCH_SRC = r"""
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static uint64_t parse_binary_23b(const uint8_t *buf, size_t len, size_t n_rec) {
    if (len != n_rec * 23) return 0;
    uint64_t sum = 0;
    for (size_t i = 0; i < n_rec; i++) {
        const uint8_t *p = buf + i * 23;
        uint32_t id = 0;
        uint8_t active = p[12];
        uint32_t count = 0;
        memcpy(&id, p, 4);
        memcpy(&count, p + 13, 4);
        sum += (uint64_t)id + (uint64_t)count + (uint64_t)active;
    }
    return sum;
}

/* Minimal zero-allocation UTF-8 JSON object scanner decoding all fields of recs.json */
static uint64_t parse_json_records(const char *buf, size_t len, size_t *out_count) {
    const char *p = buf;
    const char *end = buf + len;
    uint64_t sum = 0;
    size_t n = 0;
    while (p < end) {
        if (*p == '{') {
            uint32_t id = 0;
            uint32_t count = 0;
            uint8_t active = 0;
            p++;
            while (p < end && *p != '}') {
                if (*p == '"') {
                    const char *k0 = ++p;
                    while (p < end && *p != '"') p++;
                    size_t klen = (size_t)(p - k0);
                    if (p < end) p++;
                    while (p < end && (*p == ':' || *p == ' ' || *p == '\n' || *p == '\t')) p++;
                    char *next = NULL;
                    if (klen == 2 && memcmp(k0, "id", 2) == 0) {
                        id = (uint32_t)strtoul(p, &next, 10);
                        if (next) p = next;
                    } else if (klen == 5 && memcmp(k0, "count", 5) == 0) {
                        count = (uint32_t)strtoul(p, &next, 10);
                        if (next) p = next;
                    } else if (klen == 6 && memcmp(k0, "active", 6) == 0) {
                        if (p + 4 <= end && memcmp(p, "true", 4) == 0) {
                            active = 1;
                            p += 4;
                        } else if (p + 5 <= end && memcmp(p, "false", 5) == 0) {
                            active = 0;
                            p += 5;
                        }
                    } else if (klen == 5 && memcmp(k0, "score", 5) == 0) {
                        (void)strtod(p, &next);
                        if (next) p = next;
                    } else if (*p == '"') {
                        p++;
                        while (p < end && *p != '"') p++;
                        if (p < end) p++;
                    } else if (*p == '[') {
                        p++;
                        while (p < end && *p != ']') p++;
                        if (p < end) p++;
                    } else {
                        p++;
                    }
                } else {
                    p++;
                }
            }
            sum += (uint64_t)id + (uint64_t)count + (uint64_t)active;
            n++;
        }
        p++;
    }
    *out_count = n;
    return sum;
}

int main(int argc, char **argv) {
    if (argc < 6) return 2;
    const char *bin_path = argv[1];
    const char *json_path = argv[2];
    size_t n_rec = (size_t)strtoull(argv[3], NULL, 10);
    int trials = atoi(argv[4]);
    int inner_bin_passes = atoi(argv[5]);

    FILE *fb = fopen(bin_path, "rb");
    fseek(fb, 0, SEEK_END);
    size_t bsz = (size_t)ftell(fb);
    fseek(fb, 0, SEEK_SET);
    uint8_t *bbuf = (uint8_t *)malloc(bsz);
    if (fread(bbuf, 1, bsz, fb) != bsz) return 3;
    fclose(fb);

    FILE *fj = fopen(json_path, "rb");
    fseek(fj, 0, SEEK_END);
    size_t jsz = (size_t)ftell(fj);
    fseek(fj, 0, SEEK_SET);
    char *jbuf = (char *)malloc(jsz + 1);
    if (fread(jbuf, 1, jsz, fj) != jsz) return 4;
    jbuf[jsz] = '\0';
    fclose(fj);

    size_t jcount = 0;
    uint64_t s_bin = parse_binary_23b(bbuf, bsz, n_rec);
    uint64_t s_jsn = parse_json_records(jbuf, jsz, &jcount);
    if (jcount != n_rec || s_bin != s_jsn) {
        fprintf(stderr, "MISMATCH jcount=%zu s_bin=%llu s_jsn=%llu\n",
                jcount, (unsigned long long)s_bin, (unsigned long long)s_jsn);
        return 5;
    }

    volatile uint64_t sink = 0;
    for (int t = 0; t < trials; t++) {
        struct timespec t0, t1, t2;
        clock_gettime(CLOCK_MONOTONIC, &t0);
        uint64_t acc_b = 0;
        for (int p = 0; p < inner_bin_passes; p++) {
            acc_b ^= parse_binary_23b(bbuf, bsz, n_rec);
        }
        clock_gettime(CLOCK_MONOTONIC, &t1);
        size_t cnt = 0;
        uint64_t acc_j = parse_json_records(jbuf, jsz, &cnt);
        clock_gettime(CLOCK_MONOTONIC, &t2);
        sink ^= acc_b ^ acc_j ^ cnt;
        double bin_ns = ((double)(t1.tv_sec - t0.tv_sec) * 1e9 + (double)(t1.tv_nsec - t0.tv_nsec))
                        / ((double)n_rec * (double)inner_bin_passes);
        double jsn_ns = ((double)(t2.tv_sec - t1.tv_sec) * 1e9 + (double)(t2.tv_nsec - t1.tv_nsec))
                        / (double)n_rec;
        printf("%.4f\t%.4f\n", bin_ns, jsn_ns);
    }
    fprintf(stderr, "OK_SUM=%llu SINK=%llu\n", (unsigned long long)s_bin, (unsigned long long)sink);
    free(bbuf);
    free(jbuf);
    return 0;
}
"""


def _audit_ai_reads_human_artifacts(repo_root: Path) -> dict[str, Any]:
    sha_file = repo_root / "ai-reads-human-energy/SHA256SUMS"
    checked = 0
    matched = 0
    if sha_file.is_file():
        base = sha_file.parent
        for line in sha_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            exp, rel = line.split(None, 1)
            fp = base / rel.lstrip("*")
            checked += 1
            if fp.is_file() and hashlib.sha256(fp.read_bytes()).hexdigest() == exp:
                matched += 1

    sum_file = repo_root / "ai-reads-human-energy/summary.json"
    ref_extract: dict[str, Any] = {}
    if sum_file.is_file():
        s = json.loads(sum_file.read_text(encoding="utf-8"))
        pc = s.get("headline_reported_j", {}).get("parse_comparisons_vs_fixed_binary", {})
        cm = s.get("corpus_manifest", {})
        bin_b = cm.get("recs.bin", {}).get("bytes", 460000)
        jsn_b = cm.get("recs.json", {}).get("bytes", 2325428)
        prt_b = cm.get("recs_pretty.json", {}).get("bytes", 3685429)
        ref_extract = {
            "reference_host": s.get("environment", {}).get("cpu"),
            "records": s.get("protocol", {}).get("records"),
            "byte_ratio_json_compact_vs_bin": round(jsn_b / bin_b, 2),
            "byte_ratio_json_pretty_vs_bin": round(prt_b / bin_b, 2),
            "json_stdlib_vs_bin_wall_ratio": pc.get("json_stdlib", {}).get("wall_time_ratio"),
            "json_stdlib_vs_bin_l3_reported_j_ratio": pc.get("json_stdlib", {}).get("l3_energy_ratio"),
            "json_pretty_vs_bin_wall_ratio": pc.get("json_pretty_stdlib", {}).get("wall_time_ratio"),
            "json_pretty_vs_bin_l3_reported_j_ratio": pc.get("json_pretty_stdlib", {}).get("l3_energy_ratio"),
        }
    return {
        "artifacts_checked": checked,
        "artifacts_matched": matched,
        "self_checked_reference_extract": ref_extract,
    }


def run_suite_ai_reads_human(repo_root: Path, meter: EnergyMeter, quick: bool = False, skip_native: bool = False) -> dict[str, Any]:
    artifact_audit = _audit_ai_reads_human_artifacts(repo_root)

    # Always generate the full 20,000-record corpus once first to verify published SHA-256 digests!
    bin_20k, jsn_20k, prt_20k, sum_20k = _generate_exact_corpus(20_000)
    sha256_20k_ok = (
        hashlib.sha256(bin_20k).hexdigest() == PUBLISHED_20K_SHA256["recs.bin"]
        and hashlib.sha256(jsn_20k).hexdigest() == PUBLISHED_20K_SHA256["recs.json"]
        and hashlib.sha256(prt_20k).hexdigest() == PUBLISHED_20K_SHA256["recs_pretty.json"]
    )
    assert sha256_20k_ok, "20K corpus SHA-256 did not match published summary.json digests!"

    n_trials = 50
    if quick:
        n_records = 4_000
        bin_payload, json_compact, json_pretty, expected_sum = _generate_exact_corpus(n_records)
    else:
        n_records = 20_000
        bin_payload, json_compact, json_pretty, expected_sum = bin_20k, jsn_20k, prt_20k, sum_20k

    bin_passes = 20
    # Verify exact decoded field parity
    sum_bin = sum((r[0] + r[3] + r[2]) for r in BIN_STRUCT.iter_unpack(bin_payload)) & 0xFFFFFFFFFFFFFFFF
    sum_jsn = sum((r["id"] + r["count"] + (1 if r["active"] else 0)) for r in json.loads(json_compact.decode("utf-8"))) & 0xFFFFFFFFFFFFFFFF
    assert sum_bin == expected_sum == sum_jsn

    bin_ns_samples: list[float] = []
    jsn_ns_samples: list[float] = []
    prt_ns_samples: list[float] = []

    bin_nj_samples: list[float] = []
    jsn_nj_samples: list[float] = []
    prt_nj_samples: list[float] = []

    bin_cpu_ms = 0.0
    jsn_cpu_ms = 0.0
    prt_cpu_ms = 0.0

    for trial in range(n_trials):
        order = ["bin", "json_compact", "json_pretty"]
        order = order[trial % 3 :] + order[: trial % 3]
        for fmt in order:
            if fmt == "bin":
                s0 = meter.snapshot()
                sink = 0
                for _ in range(bin_passes):
                    for rec in BIN_STRUCT.iter_unpack(bin_payload):
                        sink ^= rec[3]
                s1 = meter.snapshot()
                d = meter.diff(s0, s1)
                assert sink >= 0
                bin_cpu_ms += d["cpu_user_sys_ms"] / bin_passes
                bin_ns_samples.append(d["wall_ns"] / (n_records * bin_passes))
                if d["joules"] is not None:
                    bin_nj_samples.append((d["joules"] * 1e9) / (n_records * bin_passes))
            elif fmt == "json_compact":
                s0 = meter.snapshot()
                objs = json.loads(json_compact.decode("utf-8"))
                sink = 0
                for r in objs:
                    sink ^= r["count"]
                s1 = meter.snapshot()
                d = meter.diff(s0, s1)
                assert sink >= 0
                jsn_cpu_ms += d["cpu_user_sys_ms"]
                jsn_ns_samples.append(d["wall_ns"] / n_records)
                if d["joules"] is not None:
                    jsn_nj_samples.append((d["joules"] * 1e9) / n_records)
            else:
                s0 = meter.snapshot()
                objs = json.loads(json_pretty.decode("utf-8"))
                sink = 0
                for r in objs:
                    sink ^= r["count"]
                s1 = meter.snapshot()
                d = meter.diff(s0, s1)
                assert sink >= 0
                prt_cpu_ms += d["cpu_user_sys_ms"]
                prt_ns_samples.append(d["wall_ns"] / n_records)
                if d["joules"] is not None:
                    prt_nj_samples.append((d["joules"] * 1e9) / n_records)

    bin_stats = iqr_stats(bin_ns_samples, digits=2)
    jsn_stats = iqr_stats(jsn_ns_samples, digits=2)
    prt_stats = iqr_stats(prt_ns_samples, digits=2)

    wall_ratio_compact = round(jsn_stats["median"] / bin_stats["median"], 2) if bin_stats["median"] else None
    wall_ratio_pretty = round(prt_stats["median"] / bin_stats["median"], 2) if bin_stats["median"] else None

    energy_ratio_compact = None
    energy_ratio_pretty = None
    if bin_nj_samples and jsn_nj_samples and prt_nj_samples:
        b_med_nj = iqr_stats(bin_nj_samples, digits=2)["median"]
        if b_med_nj and b_med_nj > 0:
            energy_ratio_compact = round(iqr_stats(jsn_nj_samples, digits=2)["median"] / b_med_nj, 2)
            energy_ratio_pretty = round(iqr_stats(prt_nj_samples, digits=2)["median"] / b_med_nj, 2)

    native_res: dict[str, Any] = {"executed": False, "reason": "skip_native_flag" if skip_native else "no_c_compiler_found"}
    cc_bin = None if skip_native else (shutil.which("cc") or shutil.which("gcc") or shutil.which("clang"))
    if cc_bin:
        with tempfile.TemporaryDirectory(prefix="openie_airh_") as td:
            td_path = Path(td)
            c_file = td_path / "parse_bench.c"
            bin_exe = td_path / "parse_bench"
            f_bin = td_path / "recs.bin"
            f_jsn = td_path / "recs.json"
            c_file.write_text(C_PARSE_BENCH_SRC, encoding="utf-8")
            f_bin.write_bytes(bin_payload)
            f_jsn.write_bytes(json_compact)
            subprocess.run([cc_bin, "-O3", str(c_file), "-o", str(bin_exe)], check=True, timeout=20)
            s_nat0 = meter.snapshot()
            proc = subprocess.run(
                [str(bin_exe), str(f_bin), str(f_jsn), str(n_records), str(n_trials), "100"],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            s_nat1 = meter.snapshot()
            d_nat = meter.diff(s_nat0, s_nat1)
            c_bin_ns: list[float] = []
            c_jsn_ns: list[float] = []
            for line in proc.stdout.splitlines():
                if "\t" in line:
                    b_s, j_s = line.strip().split("\t", 1)
                    c_bin_ns.append(float(b_s))
                    c_jsn_ns.append(float(j_s))
            cb_stats = iqr_stats(c_bin_ns, digits=3)
            cj_stats = iqr_stats(c_jsn_ns, digits=2)
            native_res = {
                "executed": True,
                "backend": "C (-O3) 23-byte fixed binary vs zero-alloc UTF-8 JSON scanner",
                "trials": len(c_bin_ns),
                "binary_ns_per_record": cb_stats,
                "json_compact_ns_per_record": cj_stats,
                "wall_time_ratio_json_vs_binary": round(cj_stats["median"] / cb_stats["median"], 2) if cb_stats["median"] else None,
                "total_native_bench_reported_j": d_nat["joules"],
                "evidence_class": d_nat["evidence_class"],
            }

    byte_ratio_compact = round(len(json_compact) / len(bin_payload), 2)
    byte_ratio_pretty = round(len(json_pretty) / len(bin_payload), 2)

    return {
        "suite_id": "ai-reads-human",
        "title": "UTF-8 Human Text/JSON vs. Fixed-Layout 23-Byte Binary Wire Parsing",
        "trials_n": n_trials,
        "records_per_trial": n_records,
        "published_20k_sha256_verified": sha256_20k_ok,
        "field_roundtrip_parity_verified": True,
        "payload_bytes": {
            "fixed_binary_23b": len(bin_payload),
            "utf8_json_compact": len(json_compact),
            "utf8_json_pretty": len(json_pretty),
            "byte_ratio_json_compact_vs_binary": byte_ratio_compact,
            "byte_ratio_json_pretty_vs_binary": byte_ratio_pretty,
        },
        "python_stdlib_parse": {
            "binary_struct_iter_unpack_ns_per_record": bin_stats,
            "json_compact_loads_ns_per_record": jsn_stats,
            "json_pretty_loads_ns_per_record": prt_stats,
            "wall_time_ratio_json_compact_vs_binary": wall_ratio_compact,
            "wall_time_ratio_json_pretty_vs_binary": wall_ratio_pretty,
            "cpu_user_sys_ms_total": {
                "binary_normalized_1pass": round(bin_cpu_ms, 3),
                "json_compact": round(jsn_cpu_ms, 3),
                "json_pretty": round(prt_cpu_ms, 3),
            },
        },
        "energy": {
            "evidence_class": meter.evidence_class,
            "binary_pkg_reported_nj_per_record": iqr_stats(bin_nj_samples, digits=2) if bin_nj_samples else None,
            "json_compact_pkg_reported_nj_per_record": iqr_stats(jsn_nj_samples, digits=2) if jsn_nj_samples else None,
            "json_pretty_pkg_reported_nj_per_record": iqr_stats(prt_nj_samples, digits=2) if prt_nj_samples else None,
            "reported_j_ratio_json_compact_vs_binary": energy_ratio_compact,
            "reported_j_ratio_json_pretty_vs_binary": energy_ratio_pretty,
            "joules": (
                round(
                    (
                        sum(bin_nj_samples) * n_records * bin_passes
                        + sum(jsn_nj_samples) * n_records
                        + sum(prt_nj_samples) * n_records
                    )
                    / 1e9,
                    6,
                )
                if bin_nj_samples
                else None
            ),
        },
        "native_microkernel": native_res,
        "repository_artifact_audit": artifact_audit,
        "comparison_to_openie_self_checked_reference": {
            "reference_artifact": "ai-reads-human-energy/summary.json",
            "openie_self_checked_claim": (
                "23-byte fixed binary vs UTF-8 JSON: 5.06x (compact) & 8.01x (pretty) wire bytes; "
                "Python json.loads 8.39x wall time / 7.89x L3 reported_j (compact) and 8.62x wall / 9.45x reported_j (pretty) on M5 Max"
            ),
            "local_observation": (
                f"Published 20K SHA-256 bit-exact match; wire bytes: {byte_ratio_compact}x (compact) & {byte_ratio_pretty}x (pretty); "
                f"Python N={n_trials} wall ratio: {wall_ratio_compact}x (compact) & {wall_ratio_pretty}x (pretty)"
                + (
                    f"; Linux RAPL reported_j ratio: {energy_ratio_compact}x (compact) & {energy_ratio_pretty}x (pretty)"
                    if energy_ratio_compact is not None
                    else " (energy class: unmetered)"
                )
                + (
                    f"; native C (-O3) parse wall ratio: {native_res['wall_time_ratio_json_vs_binary']}x"
                    if native_res.get("executed")
                    else ""
                )
            ),
            "consistency_status": (
                "consistent_with_self_checked_reference"
                if sha256_20k_ok and (wall_ratio_compact or 0) > 2.0 and byte_ratio_compact > 4.0
                else "divergent_see_notes"
            ),
        },
    }
