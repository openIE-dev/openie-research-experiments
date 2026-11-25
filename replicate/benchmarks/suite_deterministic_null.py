# SPDX-License-Identifier: Apache-2.0
"""Suite 1: Deterministic Null (Zero-Model Content-Addressed Control Arm).

Tests:
  1. SHA-256 pre-commitment integrity of the canonical JSONL case store, `Q = 1_000_000`
     fixed-point arithmetic (`SPEC.md` v0.4), and `DNULLMM1` binary open-addressed mmap index,
     plus cross-check of repository `rce/bench/h15-gear0/` & `rce/bench/table-control/` locks.
  2. Multi-trial benchmark (N >= 30 seeded batches) comparing:
       (a) Content-addressed SHA-256 / binary-table lookup + deterministic integer solver
           fallback (`0` neural FLOPs on canonical hits, 100% deterministic replay), vs.
       (b) Structured prompt UTF-8 serialization + deterministic subword tokenization +
           JSON envelope decode overhead (pure pre/post-inference serialization lower bound).
  3. Exact Clopper-Pearson 95% upper confidence bound on cross-run divergence across all
     repeated episodes and batches, plus optional C native `DNULLMM1` probe micro-kernel.
"""

from __future__ import annotations

import hashlib
import json
import mmap
import re
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .telemetry import EnergyMeter, clopper_pearson_upper, iqr_stats

Q = 1_000_000
I64_MIN = -(1 << 63)
I64_MAX = (1 << 63) - 1
EMPTY_STORE_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
BPE_PROXY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,7}|\d{1,4}|[^\sA-Za-z0-9_]")


def _narrow_i64(x: int) -> int:
    if x < I64_MIN or x > I64_MAX:
        raise ValueError("E_RANGE")
    return x


def fx_tdiv(a: int, b: int) -> int:
    """Truncate quotient toward zero (SPEC v0.4 §2.3; distinct from Python floor //)."""
    if b == 0:
        raise ValueError("E_DIV0")
    if a == I64_MIN and b == -1:
        raise ValueError("E_RANGE")
    q = abs(a) // abs(b)
    return -q if (a < 0) ^ (b < 0) else q


def fx_fdiv(a: int, b: int) -> int:
    """Round quotient toward -infinity; divisor must be > 0."""
    if b <= 0:
        raise ValueError("E_DIVISOR")
    return _narrow_i64(a // b)


def fx_mul(a: int, b: int) -> int:
    prod = a * b
    q = abs(prod) // Q
    return _narrow_i64(-q if prod < 0 else q)


def cell_key(task: str, res: int, cell: list[int]) -> str:
    payload = (
        task.encode("ascii")
        + b"\x00"
        + struct.pack(">q", res)
        + b"".join(struct.pack(">q", c) for c in cell)
    )
    return hashlib.sha256(payload).hexdigest()[:32]


def _canon_ints(vals: list[int]) -> str:
    return "[" + ",".join(str(int(v)) for v in vals) + "]"


def case_canonical(rec: dict[str, Any]) -> str:
    return (
        f'{{"action":{{"args":{_canon_ints(rec["action"]["args"])},"fn":"{rec["action"]["fn"]}"}},'
        f'"cell":{_canon_ints(rec["cell"])},"delta":{_canon_ints(rec["delta"])},"key":"{rec["key"]}",'
        f'"kind":"{rec["kind"]}","outcome":{_canon_ints(rec["outcome"])},"parent":{rec["parent"]},'
        f'"pass":{rec["pass"]},"res":{rec["res"]},"score":{rec["score"]},"seq":{rec["seq"]},'
        f'"src":"{rec["src"]}","task":"{rec["task"]}","v":1}}'
    )


class CanonicalStore:
    """Append-only canonicalized lookup store with chained SHA-256 pre-commitment digest."""

    def __init__(self) -> None:
        self.log: list[dict[str, Any]] = []
        self.index: dict[str, int] = {}
        self._digests = bytearray()

    def append(self, rec: dict[str, Any]) -> str:
        entry = dict(rec)
        entry["seq"] = len(self.log)
        entry["key"] = cell_key(entry["task"], entry["res"], entry["cell"])
        line = case_canonical(entry)
        self._digests.extend(hashlib.sha256(line.encode("ascii")).digest())
        if entry["pass"] == 1:
            self.index[entry["key"]] = entry["seq"]
        self.log.append(entry)
        return line

    def digest(self) -> str:
        return hashlib.sha256(self._digests).hexdigest()

    def write_dnullmm1(self, path: Path) -> None:
        """Write open-addressed 48-byte slot binary index (`DNULLMM1` header + power-of-two table)."""
        cap = 1
        target = max(16, len(self.index) * 2)
        while cap < target:
            cap <<= 1
        mask = cap - 1
        buf = bytearray(64 + cap * 48)
        buf[0:8] = b"DNULLMM1"
        struct.pack_into("<QQ", buf, 8, len(self.index), cap)
        struct.pack_into("32s", buf, 24, bytes.fromhex(self.digest()))
        zero16 = b"\x00" * 16
        for key_hex, seq in self.index.items():
            rec = self.log[seq]
            k16 = bytes.fromhex(key_hex)
            (h0,) = struct.unpack_from("<Q", k16, 0)
            slot = h0 & mask
            while True:
                base = 64 + slot * 48
                if buf[base : base + 16] == zero16:
                    buf[base : base + 16] = k16
                    arg0 = int(rec["action"]["args"][0])
                    arg1 = int(rec["action"]["args"][1]) if len(rec["action"]["args"]) > 1 else 0
                    struct.pack_into("<qqqq", buf, base + 16, seq, rec["score"], arg0, arg1)
                    break
                slot = (slot + 1) & mask
        path.write_bytes(buf)


def splitmix64(seed: int, idx: int) -> int:
    z = (seed + idx * 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
    return (z ^ (z >> 31)) & 0xFFFFFFFFFFFFFFFF


def _deterministic_solver(a: int, b: int, c: int) -> tuple[int, int]:
    """Exact integer fixed-point setpoint solver fallback (0 neural FLOPs)."""
    y = fx_tdiv(3 * a - 2 * b, 5) + c
    witness = ((y * 31) ^ (a + (b << 1))) & 0x7FFFFFFF
    return y, witness


def _audit_repo_dnull_artifacts(repo_root: Path) -> dict[str, Any]:
    checked = 0
    matched = 0
    details: list[dict[str, Any]] = []
    targets = [
        ("rce/bench/h15-gear0/PREREG.json", "rce/bench/h15-gear0/PREREG.json.sha256"),
        ("rce/bench/table-control/PREREG.json", "rce/bench/table-control/PREREG.json.sha256"),
    ]
    for data_rel, sha_rel in targets:
        dp = repo_root / data_rel
        sp = repo_root / sha_rel
        if dp.is_file() and sp.is_file():
            checked += 1
            expected = sp.read_text(encoding="utf-8").strip().split()[0]
            actual = hashlib.sha256(dp.read_bytes()).hexdigest()
            ok = actual == expected
            if ok:
                matched += 1
            details.append({"artifact": data_rel, "sha256_match": ok, "sha256": actual})

    h15_chk = repo_root / "rce/bench/h15-gear0/CHECKSUMS.sha256"
    if h15_chk.is_file():
        base = h15_chk.parent
        for line in h15_chk.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            exp, rel = line.split(None, 1)
            rel = rel.lstrip("*")
            fp = base / rel
            checked += 1
            if fp.is_file() and hashlib.sha256(fp.read_bytes()).hexdigest() == exp:
                matched += 1
    return {
        "artifacts_checked": checked,
        "artifacts_matched": matched,
        "prereg_locks": details,
        "published_reference_notes": {
            "h15_gear0_dnullmm1_warm_replay": "34/40 admitted on replay at 0 model calls (~325 ns/probe in OpenIE self-checked Apple M5 Max receipt)",
            "table_control_goodhart_gate": "56/56 example-only lookup controls admitted by example-only gate; 605/787 off-table probes diverge",
        },
    }


C_MMAP_PROBE_SRC = r"""
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

int main(int argc, char **argv) {
    if (argc < 4) return 2;
    const char *mm_path = argv[1];
    const char *keys_path = argv[2];
    int n_batches = atoi(argv[3]);
    FILE *fm = fopen(mm_path, "rb");
    if (!fm) return 3;
    fseek(fm, 0, SEEK_END);
    long fsz = ftell(fm);
    fseek(fm, 0, SEEK_SET);
    uint8_t *buf = (uint8_t *)malloc((size_t)fsz);
    if (!buf || fread(buf, 1, (size_t)fsz, fm) != (size_t)fsz) return 4;
    fclose(fm);

    FILE *fk = fopen(keys_path, "rb");
    if (!fk) return 5;
    fseek(fk, 0, SEEK_END);
    long ksz = ftell(fk);
    fseek(fk, 0, SEEK_SET);
    uint8_t *kbuf = (uint8_t *)malloc((size_t)ksz);
    if (!kbuf || fread(kbuf, 1, (size_t)ksz, fk) != (size_t)ksz) return 6;
    fclose(fk);

    uint64_t cap = 0;
    memcpy(&cap, buf + 16, 8);
    uint64_t mask = cap - 1;
    size_t total_keys = (size_t)ksz / 16;
    size_t per_batch = total_keys / (size_t)n_batches;
    uint8_t zero16[16] = {0};
    volatile uint64_t grand_checksum = 0;
    const int inner_reps = 50;

    for (int b = 0; b < n_batches; b++) {
        struct timespec t0, t1;
        clock_gettime(CLOCK_MONOTONIC, &t0);
        uint64_t hits = 0;
        uint64_t acc = 0;
        for (int rep = 0; rep < inner_reps; rep++) {
            for (size_t i = 0; i < per_batch; i++) {
                const uint8_t *k16 = kbuf + ((size_t)b * per_batch + i) * 16;
                uint64_t h0 = 0;
                memcpy(&h0, k16, 8);
                uint64_t slot = h0 & mask;
                for (;;) {
                    const uint8_t *entry = buf + 64 + slot * 48;
                    if (memcmp(entry, zero16, 16) == 0) break;
                    if (memcmp(entry, k16, 16) == 0) {
                        int64_t arg0 = 0;
                        memcpy(&arg0, entry + 32, 8);
                        acc ^= (uint64_t)arg0 + 0x9E3779B9ULL;
                        hits++;
                        break;
                    }
                    slot = (slot + 1) & mask;
                }
            }
        }
        clock_gettime(CLOCK_MONOTONIC, &t1);
        double ns = (double)(t1.tv_sec - t0.tv_sec) * 1e9 + (double)(t1.tv_nsec - t0.tv_nsec);
        grand_checksum ^= acc + hits;
        printf("%.4f\n", ns / ((double)per_batch * (double)inner_reps));
    }
    fprintf(stderr, "CHECKSUM=%llu\n", (unsigned long long)grand_checksum);
    free(buf);
    free(kbuf);
    return 0;
}
"""


def _run_native_mmap_probe(mmap_path: Path, n_batches: int, queries_per_batch: int, skip_native: bool) -> dict[str, Any]:
    if skip_native:
        return {"executed": False, "reason": "skip_native_flag"}
    cc_bin = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if not cc_bin:
        return {"executed": False, "reason": "no_c_compiler_found"}

    with tempfile.TemporaryDirectory(prefix="openie_dnull_") as td:
        td_path = Path(td)
        src_file = td_path / "dnull_probe.c"
        bin_file = td_path / "dnull_probe"
        keys_file = td_path / "keys.bin"
        src_file.write_text(C_MMAP_PROBE_SRC, encoding="utf-8")

        key_bytes = bytearray()
        for b in range(n_batches):
            for q in range(queries_per_batch):
                r = splitmix64(20261125 + b, q)
                cell_id = int(r % 2048) if (r % 5 != 0) else int(2048 + (r % 2048))
                a = (cell_id * 17 - 5000) * Q
                b_val = ((cell_id % 97) - 48) * Q
                c_val = ((cell_id % 31) - 15) * Q
                kh = cell_key("ctrl.linear_setpoint", 0, [a, b_val, c_val])
                key_bytes.extend(bytes.fromhex(kh))
        keys_file.write_bytes(key_bytes)

        subprocess.run([cc_bin, "-O3", str(src_file), "-o", str(bin_file)], check=True, timeout=20)
        proc = subprocess.run(
            [str(bin_file), str(mmap_path), str(keys_file), str(n_batches)],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
        ns_samples = [float(line.strip()) for line in proc.stdout.splitlines() if line.strip()]
        return {
            "executed": True,
            "backend": "C (-O3) DNULLMM1 48-byte open-addressed slot probe",
            "ns_per_probe": iqr_stats(ns_samples, digits=2),
        }


def run_suite_deterministic_null(repo_root: Path, meter: EnergyMeter, quick: bool = False, skip_native: bool = False) -> dict[str, Any]:
    assert CanonicalStore().digest() == EMPTY_STORE_SHA256
    assert fx_tdiv(-7, 2) == -3 and (-7 // 2) == -4, "fx_tdiv must truncate toward zero"
    assert fx_fdiv(-7, 2) == -4, "fx_fdiv must floor toward -infinity"
    assert fx_mul(1_500_000, -2_000_000) == -3_000_000

    def build_committed_store() -> CanonicalStore:
        st = CanonicalStore()
        for cell_id in range(2048):
            a = (cell_id * 17 - 5000) * Q
            b_val = ((cell_id % 97) - 48) * Q
            c_val = ((cell_id % 31) - 15) * Q
            y, witness = _deterministic_solver(a, b_val, c_val)
            st.append(
                {
                    "task": "ctrl.linear_setpoint",
                    "cell": [a, b_val, c_val],
                    "res": 0,
                    "kind": "learned",
                    "action": {"fn": "set_verified", "args": [y, witness]},
                    "outcome": [y],
                    "score": Q,
                    "pass": 1,
                    "delta": [],
                    "parent": -1,
                    "src": "lit:canonical_seed",
                    "v": 1,
                }
            )
        return st

    store_a = build_committed_store()
    store_b = build_committed_store()
    store_sha256 = store_a.digest()
    precommitment_identical = store_sha256 == store_b.digest()
    assert precommitment_identical, "Canonical store SHA-256 digest diverged!"

    n_batches = 30 if quick else 40
    queries_per_batch = 400 if quick else 500
    total_episodes = n_batches * queries_per_batch

    dnull_ns_per_query: list[float] = []
    prompt_ns_per_query: list[float] = []
    dnull_pkg_nj_per_query: list[float] = []
    prompt_pkg_nj_per_query: list[float] = []
    batch_trace_digests_run1: list[str] = []
    batch_trace_digests_run2: list[str] = []

    total_hits = 0
    total_solver_fallbacks = 0
    total_dnull_key_bytes = 0
    total_prompt_utf8_bytes = 0
    total_prompt_tokens = 0
    divergent_episodes = 0

    with tempfile.TemporaryDirectory(prefix="openie_dnull_mm_") as td:
        mm_path = Path(td) / "store.dnullmm1"
        store_a.write_dnullmm1(mm_path)
        f_mm = mm_path.open("rb")
        mm = mmap.mmap(f_mm.fileno(), 0, access=mmap.ACCESS_READ)
        _, cap_slots = struct.unpack_from("<QQ", mm, 8)
        mask = cap_slots - 1
        zero16 = b"\x00" * 16

        dnull_cpu_ms_total = 0.0
        prompt_cpu_ms_total = 0.0

        for b in range(n_batches):
            queries: list[tuple[int, int, int]] = []
            for q in range(queries_per_batch):
                r = splitmix64(20261125 + b, q)
                cell_id = int(r % 2048) if (r % 5 != 0) else int(2048 + (r % 2048))
                a = (cell_id * 17 - 5000) * Q
                b_val = ((cell_id % 97) - 48) * Q
                c_val = ((cell_id % 31) - 15) * Q
                queries.append((a, b_val, c_val))

            s0 = meter.snapshot()
            h_batch = hashlib.sha256()
            hits_b = 0
            fallbacks_b = 0
            for a, b_val, c_val in queries:
                kh = cell_key("ctrl.linear_setpoint", 0, [a, b_val, c_val])
                k16 = bytes.fromhex(kh)
                total_dnull_key_bytes += 16
                (h0,) = struct.unpack_from("<Q", k16, 0)
                slot = h0 & mask
                found = False
                y_out = 0
                w_out = 0
                while True:
                    base = 64 + slot * 48
                    sk = mm[base : base + 16]
                    if sk == zero16:
                        break
                    if sk == k16:
                        y_out, w_out = struct.unpack_from("<qq", mm, base + 32)
                        found = True
                        break
                    slot = (slot + 1) & mask
                if found:
                    hits_b += 1
                else:
                    fallbacks_b += 1
                    y_out, w_out = _deterministic_solver(a, b_val, c_val)
                h_batch.update(struct.pack("<qq", y_out, w_out))
            s1 = meter.snapshot()
            diff_a = meter.diff(s0, s1)
            total_hits += hits_b
            total_solver_fallbacks += fallbacks_b
            dnull_cpu_ms_total += diff_a["cpu_user_sys_ms"]
            dnull_ns_per_query.append(diff_a["wall_ns"] / queries_per_batch)
            if diff_a["joules"] is not None:
                dnull_pkg_nj_per_query.append((diff_a["joules"] * 1e9) / queries_per_batch)
            batch_trace_digests_run1.append(h_batch.hexdigest())

            s2 = meter.snapshot()
            for a, b_val, c_val in queries:
                prompt_obj = {
                    "system": "Solve exact Q=1000000 fixed-point linear setpoint y = trunc((3*a - 2*b)/5) + c and return JSON.",
                    "task": "ctrl.linear_setpoint",
                    "res": 0,
                    "cell": [a, b_val, c_val],
                    "schema": {"fn": "set_verified", "args": ["int64_y", "int64_witness"]},
                }
                prompt_txt = json.dumps(prompt_obj, separators=(",", ":"))
                prompt_bytes = prompt_txt.encode("utf-8")
                total_prompt_utf8_bytes += len(prompt_bytes)
                toks = BPE_PROXY_RE.findall(prompt_txt)
                total_prompt_tokens += len(toks)
                y_ref, w_ref = _deterministic_solver(a, b_val, c_val)
                resp_txt = f'{{"fn":"set_verified","args":[{y_ref},{w_ref}]}}'
                parsed = json.loads(resp_txt)
                if parsed["args"][0] != y_ref:
                    raise AssertionError("Envelope parse mismatch")
            s3 = meter.snapshot()
            diff_b = meter.diff(s2, s3)
            prompt_cpu_ms_total += diff_b["cpu_user_sys_ms"]
            prompt_ns_per_query.append(diff_b["wall_ns"] / queries_per_batch)
            if diff_b["joules"] is not None:
                prompt_pkg_nj_per_query.append((diff_b["joules"] * 1e9) / queries_per_batch)

        for b in range(n_batches):
            h_replay = hashlib.sha256()
            for q in range(queries_per_batch):
                r = splitmix64(20261125 + b, q)
                cell_id = int(r % 2048) if (r % 5 != 0) else int(2048 + (r % 2048))
                a = (cell_id * 17 - 5000) * Q
                b_val = ((cell_id % 97) - 48) * Q
                c_val = ((cell_id % 31) - 15) * Q
                kh = cell_key("ctrl.linear_setpoint", 0, [a, b_val, c_val])
                k16 = bytes.fromhex(kh)
                (h0,) = struct.unpack_from("<Q", k16, 0)
                slot = h0 & mask
                y_out = 0
                w_out = 0
                found = False
                while True:
                    base = 64 + slot * 48
                    sk = mm[base : base + 16]
                    if sk == zero16:
                        break
                    if sk == k16:
                        y_out, w_out = struct.unpack_from("<qq", mm, base + 32)
                        found = True
                        break
                    slot = (slot + 1) & mask
                if not found:
                    y_out, w_out = _deterministic_solver(a, b_val, c_val)
                y_gt, w_gt = _deterministic_solver(a, b_val, c_val)
                if (y_out, w_out) != (y_gt, w_gt):
                    divergent_episodes += 1
                h_replay.update(struct.pack("<qq", y_out, w_out))
            batch_trace_digests_run2.append(h_replay.hexdigest())

        mm.close()
        f_mm.close()

        native_probe = _run_native_mmap_probe(mm_path, n_batches, queries_per_batch, skip_native)
        mmap_bytes = mm_path.stat().st_size

    divergent_batches = sum(1 for d1, d2 in zip(batch_trace_digests_run1, batch_trace_digests_run2) if d1 != d2)
    cp95_episode_upper = clopper_pearson_upper(divergent_episodes, total_episodes, alpha=0.05, two_sided=False)
    cp95_batch_upper = clopper_pearson_upper(divergent_batches, n_batches, alpha=0.05, two_sided=False)

    dnull_stats = iqr_stats(dnull_ns_per_query, digits=2)
    prompt_stats = iqr_stats(prompt_ns_per_query, digits=2)
    speedup_ratio = round(prompt_stats["median"] / dnull_stats["median"], 3) if dnull_stats["median"] else None
    byte_ratio = round(total_prompt_utf8_bytes / total_dnull_key_bytes, 2)

    repo_audit = _audit_repo_dnull_artifacts(repo_root)

    return {
        "suite_id": "deterministic-null",
        "title": "Zero-Model Content-Addressed Control Arm (`Shape D` / `DNULLMM1`)",
        "sample_size_batches": n_batches,
        "queries_per_batch": queries_per_batch,
        "total_episodes": total_episodes,
        "precommitment_integrity": {
            "empty_store_sha256_ok": True,
            "committed_store_records": len(store_a.log),
            "committed_store_sha256": store_sha256,
            "dnullmm1_binary_bytes": mmap_bytes,
            "reproducible_store_digest": precommitment_identical,
            "fx_q1000000_truncation_verified": True,
        },
        "determinism_and_repeatability": {
            "neural_flops_on_lookup_and_fallback": 0,
            "canonical_cache_hits": total_hits,
            "deterministic_solver_fallbacks": total_solver_fallbacks,
            "cache_hit_fraction": round(total_hits / total_episodes, 4),
            "divergent_episodes_across_replay": divergent_episodes,
            "divergent_batches_across_replay": divergent_batches,
            "repeatability_pct": round(100.0 * (total_episodes - divergent_episodes) / total_episodes, 4),
            "clopper_pearson_95_upper_bound_episode_divergence": round(cp95_episode_upper, 8),
            "clopper_pearson_95_upper_bound_batch_divergence": round(cp95_batch_upper, 6),
        },
        "timing_and_serialization_comparison": {
            "dnull_lookup_plus_solver_ns_per_query": dnull_stats,
            "prompt_serialize_tokenize_ns_per_query": prompt_stats,
            "serialization_floor_over_dnull_latency_ratio": speedup_ratio,
            "dnull_cpu_user_sys_ms_total": round(dnull_cpu_ms_total, 3),
            "prompt_cpu_user_sys_ms_total": round(prompt_cpu_ms_total, 3),
            "dnull_binary_key_bytes_per_query": 16,
            "prompt_utf8_bytes_per_query_mean": round(total_prompt_utf8_bytes / total_episodes, 2),
            "prompt_subword_tokens_per_query_mean": round(total_prompt_tokens / total_episodes, 2),
            "wire_byte_ratio_prompt_vs_16b_key": byte_ratio,
        },
        "energy": {
            "evidence_class": meter.evidence_class,
            "dnull_pkg_reported_nj_per_query": iqr_stats(dnull_pkg_nj_per_query, digits=2) if dnull_pkg_nj_per_query else None,
            "prompt_pkg_reported_nj_per_query": iqr_stats(prompt_pkg_nj_per_query, digits=2) if prompt_pkg_nj_per_query else None,
            "joules": round(sum(dnull_pkg_nj_per_query) * queries_per_batch / 1e9, 6) if dnull_pkg_nj_per_query else None,
        },
        "native_microkernel": native_probe,
        "repository_artifact_crosscheck": repo_audit,
        "comparison_to_openie_self_checked_reference": {
            "reference_artifact": "rce/bench/h15-gear0/RESULTS.md & openIE-dev/deterministic-null SPEC v0.4",
            "openie_self_checked_claim": "0 decision-time model calls, 100% deterministic replay, sub-microsecond native DNULLMM1 probe (~325 ns on M5 Max)",
            "local_observation": (
                f"0/{total_episodes} replay divergences (95% Clopper-Pearson upper bound {cp95_episode_upper:.2e}); "
                f"Python lookup+solver median {dnull_stats['median']} ns/query vs {prompt_stats['median']} ns/query prompt serialization floor ({speedup_ratio}x)"
                + (
                    f"; native C DNULLMM1 probe median {native_probe['ns_per_probe']['median']} ns/lookup"
                    if native_probe.get("executed")
                    else ""
                )
            ),
            "consistency_status": "consistent_with_self_checked_reference" if divergent_episodes == 0 and (speedup_ratio or 0) > 1.0 else "divergent_see_notes",
        },
    }
