#!/usr/bin/env python3
"""
Standalone Apple Silicon Dual-Channel Energy Benchmark (`reported_j` only) for `ai-reads-human`.

Measures the deterministic 20,000-record `ai-reads-human` corpus (seed 20261016) across all 16
parse workloads from `bench_parse.py` and 18 local `tiktoken` (`cl100k_base`, `o200k_base`)
tokenization workloads using two simultaneous rootless Apple Silicon telemetry channels:

  1. `L3` (`SATB` label `D`, per-PID kernel counter):
     `proc_pid_rusage(worker_pid, RUSAGE_INFO_V6)` -> `ri_energy_nj` (slot 42) and
     `ri_instructions` (slot 31), read strictly inside a dedicated single-threaded worker
     subprocess per replicate after imports, corpus load, and warm-up complete. Isolates the
     exact parser/tokenizer PID from co-tenant processes (`yosys-abc`, etc.) and from `macmon`
     JSON reader overhead.

  2. `L2` (`SATB` label `A2`, whole-SoC IOReport/SMC via `macmon`):
     `StabilizedPowerMeter` protocol: waits for Metal `gpu_power <= 1.5 W`, samples trimmed
     `idle_pre_w` and `idle_post_w` baselines around each worker window, records whole-SoC
     `chip_power` `gross_reported_j`, and enforces `SATB` Falsifier 6 (`idle_drift_pct <= 5.0%`)
     on `derived_marginal_j`.

Strict reporting discipline:
  - `measured_j = None`
  - `board_metered = False`
  - All energy figures are strictly `reported_j` (`L3` `ri_energy_nj` and `L2` `IOReport`).
"""

from __future__ import annotations

import argparse
import ctypes
import csv
import datetime as dt
import gc
import hashlib
import io
import json
import math
import os
import platform
import random
import statistics as st
import struct
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape

import cbor2
import msgpack
import numpy as np
import orjson
import tiktoken
import yaml
from lxml import etree
from markdown_it import MarkdownIt

_LIBSYSTEM = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
_RUSAGE_INFO_V6 = 6

CORPUS_SEED = 20261016
DEFAULT_RECORDS = 20000

# Published SHA-256 digests for N=20000, seed=20261016 (from `gen_corpus.py`)
EXPECTED_SHA256_20K = {
    "recs.json": "692ad32e39dd6db5f2bc02cea25964bdc70d6aa940a9597c7d0421dfc6d9b622",
    "recs_pretty.json": "bdec88369a48bd64f5c501cf8e1de911eeed0100a0fcb66ab1fedfadcc0c4094",
    "recs.yaml": "d7e3f07702f21dbc51d072db206d4d4a385035486b502a08753ffbee4becece4",
    "recs.xml": "33a4252af7a1bf4b913cd110f3613ed1fa4e490ab7d31379fbc6c31f17f566f5",
    "recs.csv": "c5a40f493ae07ce6aced95dadbd3a472c3876d6f09eceea666675e250670eec8",
    "recs.msgpack": "1f2d67fabe0afb92168bb79b80de952ff1d2ad13342fdcc5473c02237d93c5b6",
    "recs.cbor": "9511e33f5f4eff4fd99b6ad241211f29d4f73d6c2d67627a1b88cc483ca89cda",
    "recs.bin": "adc0771a900ebf6400449ee31f7b00a96e382a448c5f4288022e28974134647f",
}

WORDS = (
    "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu "
    "nu xi omicron pi rho sigma tau upsilon phi chi psi omega"
).split()

NP_DTYPE = np.dtype(
    [
        ("id", "<u4"),
        ("score", "<f8"),
        ("a", "u1"),
        ("count", "<u4"),
        ("n", "u1", 3),
        ("t", "u1", 3),
    ],
    align=False,
)

# Workloads: (case_id, stage, display_name, corpus_file, default_passes)
PARSE_WORKLOADS: list[tuple[str, str, str, str, int]] = [
    ("parse_bin_struct", "parse", "fixed binary (struct.iter_unpack)", "recs.bin", 100),
    ("parse_bin_numpy", "parse", "fixed binary (numpy frombuffer, zero copy)", "recs.bin", 100000),
    ("parse_csv", "parse", "csv (stdlib)", "recs.csv", 50),
    ("parse_msgpack", "parse", "msgpack", "recs.msgpack", 45),
    ("parse_cbor2", "parse", "cbor2", "recs.cbor", 30),
    ("parse_json_orjson", "parse", "json (orjson)", "recs.json", 50),
    ("parse_json_stdlib", "parse", "json (stdlib)", "recs.json", 40),
    ("parse_json_pretty", "parse", "json pretty (stdlib)", "recs_pretty.json", 35),
    ("parse_jsonl", "parse", "jsonl (stdlib, per line)", "recs.jsonl", 25),
    ("parse_xml_lxml", "parse", "xml (lxml)", "recs.xml", 25),
    ("parse_xml_et", "parse", "xml (ElementTree)", "recs.xml", 25),
    ("parse_md_table", "parse", "markdown table (markdown-it-py, tokens only)", "recs_table.md", 6),
    ("parse_md_list", "parse", "markdown list (markdown-it-py, tokens only)", "recs_list.md", 3),
    ("parse_toml", "parse", "toml (tomllib)", "recs.toml", 3),
    ("parse_yaml_c", "parse", "yaml (libyaml C)", "recs.yaml", 4),
    ("parse_yaml_py", "parse", "yaml (pure python)", "recs.yaml", 3),
]

TOKENIZE_VIEWS = [
    "recs.csv",
    "recs.json",
    "recs_pretty.json",
    "recs.jsonl",
    "recs.yaml",
    "recs.xml",
    "recs.toml",
    "recs_table.md",
    "recs_list.md",
]

TOKENIZE_WORKLOADS: list[tuple[str, str, str, str, int]] = []
for _enc, _passes in [("cl100k_base", 5), ("o200k_base", 7)]:
    for _vf in TOKENIZE_VIEWS:
        _cid = f"tok_{_enc}_{_vf.replace('.', '_')}"
        TOKENIZE_WORKLOADS.append((_cid, "tokenize", f"tiktoken ({_enc}): {_vf}", _vf, _passes))

ALL_WORKLOADS = PARSE_WORKLOADS + TOKENIZE_WORKLOADS
WORKLOAD_MAP = {cid: (stage, name, fname, passes) for cid, stage, name, fname, passes in ALL_WORKLOADS}


def read_pid_l3_rusage(pid: int) -> tuple[int, int]:
    """Returns `(ri_energy_nj, ri_instructions)` for `pid` via rootless `proc_pid_rusage`."""
    buf = (ctypes.c_uint64 * 64)()
    rc = _LIBSYSTEM.proc_pid_rusage(int(pid), _RUSAGE_INFO_V6, ctypes.byref(buf))
    if rc != 0:
        raise RuntimeError(f"proc_pid_rusage failed with rc={rc} for pid={pid}")
    return int(buf[42]), int(buf[31])


def generate_and_verify_corpus(corpus_dir: Path, n_records: int = DEFAULT_RECORDS) -> dict[str, dict[str, int | str]]:
    """Generates the exact `gen_corpus.py` synthetic corpus and verifies byte/digest parity."""
    corpus_dir.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(CORPUS_SEED)
    recs = []
    for i in range(n_records):
        recs.append(
            {
                "id": i,
                "name": " ".join(rnd.choice(WORDS) for _ in range(3)),
                "score": round(rnd.uniform(0, 1000), 3),
                "active": rnd.random() < 0.5,
                "tags": [rnd.choice(WORDS) for _ in range(3)],
                "count": rnd.randrange(0, 1 << 31),
            }
        )

    def write_text(name: str, text: str) -> None:
        (corpus_dir / name).write_bytes(text.encode("utf-8"))

    def write_bin(name: str, data: bytes) -> None:
        (corpus_dir / name).write_bytes(data)

    write_text("recs.json", json.dumps(recs, separators=(",", ":")))
    write_text("recs_pretty.json", json.dumps(recs, indent=2))
    write_text("recs.jsonl", "\n".join(json.dumps(r, separators=(",", ":")) for r in recs) + "\n")
    write_text("recs.yaml", yaml.safe_dump(recs, sort_keys=False))

    xml_lines = ['<?xml version="1.0" encoding="UTF-8"?>\n<records>']
    for r in recs:
        xml_lines.append(
            '<rec id="%d" active="%s" score="%s" count="%d"><name>%s</name>%s</rec>'
            % (
                r["id"],
                "true" if r["active"] else "false",
                repr(r["score"]),
                r["count"],
                escape(r["name"]),
                "".join("<tag>%s</tag>" % t for t in r["tags"]),
            )
        )
    xml_lines.append("</records>\n")
    write_text("recs.xml", "\n".join(xml_lines))

    s_io = io.StringIO()
    writer = csv.writer(s_io, lineterminator="\n")
    writer.writerow(["id", "name", "score", "active", "tag1", "tag2", "tag3", "count"])
    for r in recs:
        writer.writerow(
            [
                r["id"],
                r["name"],
                repr(r["score"]),
                "true" if r["active"] else "false",
                *r["tags"],
                r["count"],
            ]
        )
    write_text("recs.csv", s_io.getvalue())

    toml_chunks = []
    for r in recs:
        toml_chunks.append(
            '[[rec]]\nid = %d\nname = "%s"\nscore = %r\nactive = %s\ntags = [%s]\ncount = %d\n'
            % (
                r["id"],
                r["name"],
                r["score"],
                "true" if r["active"] else "false",
                ", ".join('"%s"' % g for g in r["tags"]),
                r["count"],
            )
        )
    write_text("recs.toml", "\n".join(toml_chunks))

    write_bin("recs.msgpack", msgpack.packb(recs))
    write_bin("recs.cbor", cbor2.dumps(recs))

    wi = {k: idx for idx, k in enumerate(WORDS)}
    bin_buf = bytearray()
    for r in recs:
        bin_buf += struct.pack(
            "<IdBI3B3B",
            r["id"],
            r["score"],
            r["active"],
            r["count"],
            *[wi[q] for q in r["name"].split()],
            *[wi[q] for q in r["tags"]],
        )
    write_bin("recs.bin", bytes(bin_buf))

    md_table = ["| id | name | score | active | tags | count |", "|---|---|---|---|---|---|"]
    for r in recs:
        md_table.append(
            "| %d | %s | %r | %s | %s | %d |"
            % (
                r["id"],
                r["name"],
                r["score"],
                str(r["active"]).lower(),
                ", ".join(r["tags"]),
                r["count"],
            )
        )
    write_text("recs_table.md", "\n".join(md_table) + "\n")

    md_list = []
    for r in recs:
        md_list.append(
            "- **%d** %s: score %r, active %s, tags %s, count %d"
            % (
                r["id"],
                r["name"],
                r["score"],
                str(r["active"]).lower(),
                ", ".join(r["tags"]),
                r["count"],
            )
        )
    write_text("recs_list.md", "\n".join(md_list) + "\n")

    # Verify digests and semantic round-trips
    manifest: dict[str, dict[str, int | str]] = {}
    all_files = sorted(
        {fname for _, _, _, fname, _ in ALL_WORKLOADS}
    )
    for fname in all_files:
        raw = (corpus_dir / fname).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if n_records == DEFAULT_RECORDS and fname in EXPECTED_SHA256_20K:
            exp = EXPECTED_SHA256_20K[fname]
            if digest != exp:
                raise AssertionError(f"Corpus SHA-256 mismatch for {fname}: got {digest}, expected {exp}")
        manifest[fname] = {"bytes": len(raw), "sha256": digest}

    # Spot-check parser equivalence against reference JSON
    ref = json.loads((corpus_dir / "recs.json").read_bytes())
    assert len(ref) == n_records
    assert orjson.loads((corpus_dir / "recs.json").read_bytes()) == ref
    assert msgpack.unpackb((corpus_dir / "recs.msgpack").read_bytes()) == ref
    assert cbor2.loads((corpus_dir / "recs.cbor").read_bytes()) == ref
    assert tomllib.loads((corpus_dir / "recs.toml").read_bytes().decode("utf-8"))["rec"] == ref
    unpacked = list(struct.iter_unpack("<IdBI3B3B", (corpus_dir / "recs.bin").read_bytes()))
    assert len(unpacked) == n_records and unpacked[7][0] == 7 and unpacked[7][1] == ref[7]["score"]
    return manifest


def make_worker_callable(case_id: str, corpus_dir: Path):
    """Builds `(callable_zero_arg, file_bytes_len, extra_meta)` for the isolated worker."""
    stage, _name, fname, _default_passes = WORKLOAD_MAP[case_id]
    raw = (corpus_dir / fname).read_bytes()
    n_bytes = len(raw)

    if stage == "parse":
        if case_id == "parse_bin_struct":
            fn = lambda b=raw: list(struct.iter_unpack("<IdBI3B3B", b))
        elif case_id == "parse_bin_numpy":
            fn = lambda b=raw: np.frombuffer(b, dtype=NP_DTYPE)
        elif case_id == "parse_csv":
            fn = lambda b=raw: list(csv.reader(io.StringIO(b.decode("utf-8"))))
        elif case_id == "parse_msgpack":
            fn = lambda b=raw: msgpack.unpackb(b)
        elif case_id == "parse_cbor2":
            fn = lambda b=raw: cbor2.loads(b)
        elif case_id == "parse_json_orjson":
            fn = lambda b=raw: orjson.loads(b)
        elif case_id in ("parse_json_stdlib", "parse_json_pretty"):
            fn = lambda b=raw: json.loads(b)
        elif case_id == "parse_jsonl":
            fn = lambda b=raw: [json.loads(line) for line in b.splitlines()]
        elif case_id == "parse_xml_lxml":
            fn = lambda b=raw: etree.fromstring(b)
        elif case_id == "parse_xml_et":
            fn = lambda b=raw: ET.fromstring(b)
        elif case_id in ("parse_md_table", "parse_md_list"):
            fn = lambda b=raw: MarkdownIt("commonmark").parse(b.decode("utf-8"))
        elif case_id == "parse_toml":
            fn = lambda b=raw: tomllib.loads(b.decode("utf-8"))
        elif case_id == "parse_yaml_c":
            fn = lambda b=raw: yaml.load(b, Loader=yaml.CSafeLoader)
        elif case_id == "parse_yaml_py":
            fn = lambda b=raw: yaml.load(b, Loader=yaml.SafeLoader)
        else:
            raise ValueError(f"Unknown parse case_id: {case_id}")
        warm_out = fn()
        item_count = len(warm_out) if hasattr(warm_out, "__len__") else 0
        del warm_out
        return fn, n_bytes, {"tokens": 0, "items": item_count}

    if stage == "tokenize":
        enc_name = "cl100k_base" if "cl100k_base" in case_id else "o200k_base"
        enc = tiktoken.get_encoding(enc_name)
        text = raw.decode("utf-8")
        del raw
        fn = lambda e=enc, s=text: e.encode(s, disallowed_special=())
        toks = fn()
        n_tokens = len(toks)
        del toks
        return fn, n_bytes, {"tokens": n_tokens, "encoding": enc_name}

    raise ValueError(f"Unknown stage: {stage}")


def run_worker_mode(case_id: str, corpus_dir: Path, passes: int) -> int:
    """Isolated single-threaded worker: warms up, waits for GO, brackets hot loop with L3 rusage."""
    fn, n_bytes, meta = make_worker_callable(case_id, corpus_dir)
    gc.collect()
    gc.disable()

    sys.stdout.write("READY\n")
    sys.stdout.flush()

    cmd = sys.stdin.readline()
    if not cmd or not cmd.startswith("GO"):
        return 1

    pid = os.getpid()
    e0_nj, i0 = read_pid_l3_rusage(pid)
    t0_ns = time.perf_counter_ns()
    c0_ns = time.process_time_ns()

    sink = 0
    for _ in range(passes):
        res = fn()
        sink ^= len(res)

    c1_ns = time.process_time_ns()
    t1_ns = time.perf_counter_ns()
    e1_nj, i1 = read_pid_l3_rusage(pid)

    payload = {
        "pid": pid,
        "case_id": case_id,
        "passes": passes,
        "bytes": n_bytes,
        "tokens": meta.get("tokens", 0),
        "wall_ns": max(1, t1_ns - t0_ns),
        "cpu_ns": max(0, c1_ns - c0_ns),
        "ri_energy_nj": max(0, e1_nj - e0_nj),
        "ri_instructions": max(0, i1 - i0),
        "sink": sink,
    }
    sys.stdout.write("RESULT\t" + json.dumps(payload) + "\n")
    sys.stdout.flush()
    return 0


class PersistentMacmonStream:
    """Continuous `macmon pipe -s 0 -i 100` `L2` (`A2`) power stream with `StabilizedPowerMeter` windows."""

    def __init__(
        self,
        interval_ms: int = 100,
        gpu_idle_ceiling_w: float = 1.5,
        max_cooldown_s: float = 4.0,
        baseline_window_s: float = 0.8,
    ):
        self.interval_ms = interval_ms
        self.gpu_idle_ceiling_w = gpu_idle_ceiling_w
        self.max_cooldown_s = max_cooldown_s
        self.baseline_window_s = baseline_window_s
        self._lock = threading.Lock()
        self._samples: list[tuple[float, float, float, float, float, float]] = []
        self._stop = threading.Event()
        self._proc: subprocess.Popen[str] | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._proc = subprocess.Popen(
            ["macmon", "pipe", "-s", "0", "-i", str(self.interval_ms)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()
        # Wait until first sample arrives
        t_wait = time.perf_counter()
        while time.perf_counter() - t_wait < 5.0:
            with self._lock:
                if self._samples:
                    break
            time.sleep(0.05)

    def _reader(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        for line in self._proc.stdout:
            if self._stop.is_set():
                break
            now = time.perf_counter()
            try:
                d = json.loads(line)
                chip_w = float(d.get("chip_power", d.get("all_power", 0.0)))
                cpu_w = float(d.get("cpu_power", 0.0))
                gpu_w = float(d.get("gpu_power", 0.0))
                sys_w = float(d.get("sys_power", 0.0))
                temp_obj = d.get("temp") or {}
                gpu_temp = float(temp_obj.get("gpu_temp_avg", 0.0))
                with self._lock:
                    self._samples.append((now, chip_w, cpu_w, gpu_w, sys_w, gpu_temp))
            except Exception:
                continue

    def stop(self) -> None:
        self._stop.set()
        if self._proc is not None:
            self._proc.kill()
        if self._thread is not None:
            self._thread.join(timeout=0.5)

    def sample_idle_baseline(self) -> tuple[float, float, float]:
        """Waits for `gpu_power <= ceiling` (up to cap), then computes trimmed mean over `baseline_window_s`."""
        t_cool0 = time.perf_counter()
        while time.perf_counter() - t_cool0 < self.max_cooldown_s:
            with self._lock:
                latest_gpu = self._samples[-1][3] if self._samples else 0.0
            if latest_gpu <= self.gpu_idle_ceiling_w:
                break
            time.sleep(0.05)
        cool_s = time.perf_counter() - t_cool0

        t_win0 = time.perf_counter()
        time.sleep(self.baseline_window_s)
        t_win1 = time.perf_counter()

        with self._lock:
            win = [s for s in self._samples if t_win0 <= s[0] <= t_win1]
            if not win and self._samples:
                win = self._samples[-6:]

        chip_vals = [s[1] for s in win]
        sys_vals = [s[4] for s in win]
        if len(chip_vals) >= 6:
            c_trim = sorted(chip_vals)[1:-1]
            s_trim = sorted(sys_vals)[1:-1]
            mean_chip = sum(c_trim) / len(c_trim)
            mean_sys = sum(s_trim) / len(s_trim)
        elif chip_vals:
            mean_chip = sum(chip_vals) / len(chip_vals)
            mean_sys = sum(sys_vals) / len(sys_vals)
        else:
            mean_chip, mean_sys = 20.0, 50.0
        return mean_chip, mean_sys, round(cool_s, 3)

    def slice_window(self, t0: float, t1: float) -> list[tuple[float, float, float, float, float, float]]:
        with self._lock:
            win = [s for s in self._samples if t0 <= s[0] <= t1]
            if not win and self._samples:
                # Fallback to nearest sample if window is very short
                nearest = min(self._samples, key=lambda s: abs(s[0] - 0.5 * (t0 + t1)))
                win = [nearest]
            return win


def measure_one_replicate(
    script_path: Path,
    corpus_dir: Path,
    meter: PersistentMacmonStream,
    case_id: str,
    passes: int,
    round_idx: int,
) -> dict:
    proc = subprocess.Popen(
        [
            sys.executable,
            str(script_path),
            "--worker",
            "--corpus-dir",
            str(corpus_dir),
            "--case-id",
            case_id,
            "--passes",
            str(passes),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None

    ready_line = proc.stdout.readline().strip()
    if ready_line != "READY":
        err = proc.stderr.read()
        proc.kill()
        raise RuntimeError(f"Worker {case_id} failed to become READY (got {ready_line!r}): {err}")

    # Worker is now completely warmed up and sleeping on stdin (0% CPU). Measure L2 pre-idle:
    idle_pre_w, idle_pre_sys_w, cool_pre_s = meter.sample_idle_baseline()
    load1 = os.getloadavg()[0]

    t_win0 = time.perf_counter()
    proc.stdin.write("GO\n")
    proc.stdin.flush()

    res_line = proc.stdout.readline().strip()
    t_win1 = time.perf_counter()
    proc.wait(timeout=30.0)

    if not res_line.startswith("RESULT\t"):
        err = proc.stderr.read()
        raise RuntimeError(f"Worker {case_id} failed during run (got {res_line!r}): {err}")

    wres = json.loads(res_line.split("\t", 1)[1])
    samples = meter.slice_window(t_win0, t_win1)

    # Worker has exited. Measure L2 post-idle:
    idle_post_w, idle_post_sys_w, cool_post_s = meter.sample_idle_baseline()

    mean_idle_w = 0.5 * (idle_pre_w + idle_post_w)
    drift_pct = abs(idle_post_w - idle_pre_w) / max(0.1, mean_idle_w) * 100.0
    falsifier6_valid = drift_pct <= 5.0

    n_s = len(samples)
    mean_chip_w = sum(s[1] for s in samples) / n_s
    mean_cpu_w = sum(s[2] for s in samples) / n_s
    mean_gpu_w = sum(s[3] for s in samples) / n_s
    mean_sys_w = sum(s[4] for s in samples) / n_s
    peak_gpu_temp_c = max((s[5] for s in samples), default=0.0)

    wall_s = wres["wall_ns"] / 1e9
    l2_gross_j = mean_chip_w * wall_s
    l2_marginal_j = (mean_chip_w - mean_idle_w) * wall_s
    l3_energy_nj = wres["ri_energy_nj"]

    stage, workload_name, fname, _ = WORKLOAD_MAP[case_id]
    return {
        "round": round_idx,
        "case_id": case_id,
        "stage": stage,
        "workload": workload_name,
        "corpus_file": fname,
        "bytes": wres["bytes"],
        "tokens": wres["tokens"],
        "passes": passes,
        "wall_ns_total": wres["wall_ns"],
        "cpu_ns_total": wres["cpu_ns"],
        "wall_ms_per_20k": (wres["wall_ns"] / 1e6) / passes,
        "l3_ri_energy_nj_total": l3_energy_nj,
        "l3_ri_energy_nj_per_20k": l3_energy_nj / passes,
        "l3_nj_per_record": l3_energy_nj / (passes * DEFAULT_RECORDS),
        "l3_ri_instructions_total": wres["ri_instructions"],
        "l3_instructions_per_record": wres["ri_instructions"] / (passes * DEFAULT_RECORDS),
        "l2_samples": n_s,
        "l2_idle_pre_w": round(idle_pre_w, 4),
        "l2_idle_post_w": round(idle_post_w, 4),
        "l2_idle_drift_pct": round(drift_pct, 3),
        "falsifier6_valid_5pct": falsifier6_valid,
        "l2_mean_chip_w": round(mean_chip_w, 4),
        "l2_mean_cpu_w": round(mean_cpu_w, 4),
        "l2_mean_gpu_w": round(mean_gpu_w, 4),
        "l2_mean_sys_w": round(mean_sys_w, 4),
        "l2_peak_gpu_temp_c": round(peak_gpu_temp_c, 2),
        "l2_gross_reported_j_per_20k": l2_gross_j / passes,
        "l2_derived_marginal_j_per_20k": l2_marginal_j / passes,
        "loadavg_1m": round(load1, 2),
        "cooldown_pre_s": cool_pre_s,
        "cooldown_post_s": cool_post_s,
    }


def safe_sd(vals: list[float]) -> float:
    return st.stdev(vals) if len(vals) > 1 else 0.0


def run_benchmark(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    script_path = Path(__file__).resolve()

    start_utc = dt.datetime.now(dt.timezone.utc).isoformat()
    cpu_brand = subprocess.run(
        ["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, check=False
    ).stdout.strip()
    mem_bytes = int(
        subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, check=False).stdout.strip()
        or "0"
    )
    macmon_ver = subprocess.run(
        ["macmon", "--version"], capture_output=True, text=True, check=False
    ).stdout.strip()
    sw_ver = subprocess.run(
        ["sw_vers", "-productVersion"], capture_output=True, text=True, check=False
    ).stdout.strip()

    with tempfile.TemporaryDirectory(prefix="ai_reads_human_20k_") as tmp_corpus:
        corpus_dir = Path(args.corpus_dir).resolve() if args.corpus_dir else Path(tmp_corpus)
        print(f"[1/3] Generating & verifying {DEFAULT_RECORDS}-record deterministic corpus...", flush=True)
        corpus_manifest = generate_and_verify_corpus(corpus_dir, DEFAULT_RECORDS)

        meter = PersistentMacmonStream(
            interval_ms=100,
            gpu_idle_ceiling_w=1.5,
            max_cooldown_s=4.0,
            baseline_window_s=args.baseline_window_s,
        )
        meter.start()
        all_rep_rows: list[dict] = []
        raw_jsonl_path = out_dir / "raw_replicates.jsonl"

        try:
            with raw_jsonl_path.open("w", encoding="utf-8") as raw_f:
                for r_idx in range(args.replicates):
                    order = list(ALL_WORKLOADS)
                    rnd = random.Random(20261122 + r_idx)
                    rnd.shuffle(order)
                    print(
                        f"[2/3] Round {r_idx + 1}/{args.replicates}: running {len(order)} interleaved workloads...",
                        flush=True,
                    )
                    for w_i, (cid, _stage, wname, _fname, default_passes) in enumerate(order, 1):
                        passes = max(1, int(round(default_passes * args.pass_scale)))
                        rep = measure_one_replicate(script_path, corpus_dir, meter, cid, passes, r_idx)
                        all_rep_rows.append(rep)
                        raw_f.write(json.dumps(rep) + "\n")
                        raw_f.flush()
                        print(
                            f"  [{r_idx + 1}.{w_i:02d}/{len(order)}] {wname:45s} "
                            f"wall={rep['wall_ms_per_20k']:8.2f}ms  "
                            f"L3={rep['l3_nj_per_record']:9.1f} nJ/rec  "
                            f"L2_chip={rep['l2_mean_chip_w']:5.1f}W  "
                            f"drift={rep['l2_idle_drift_pct']:5.2f}% "
                            f"F6={'PASS' if rep['falsifier6_valid_5pct'] else 'FAIL'}",
                            flush=True,
                        )
        finally:
            meter.stop()

    end_utc = dt.datetime.now(dt.timezone.utc).isoformat()
    print("[3/3] Aggregating statistics and writing TSV + summary.json...", flush=True)

    by_case: dict[str, list[dict]] = {}
    for row in all_rep_rows:
        by_case.setdefault(row["case_id"], []).append(row)

    ref_rows = by_case["parse_bin_struct"]
    ref_l3_nj_per_rec = st.mean(r["l3_nj_per_record"] for r in ref_rows)
    ref_wall_ms = st.mean(r["wall_ms_per_20k"] for r in ref_rows)

    tok_csv_cl100k_nj = st.mean(r["l3_nj_per_record"] for r in by_case["tok_cl100k_base_recs_csv"])
    tok_csv_o200k_nj = st.mean(r["l3_nj_per_record"] for r in by_case["tok_o200k_base_recs_csv"])

    tsv_headers = [
        "stage",
        "workload",
        "corpus_file",
        "bytes",
        "records",
        "tokens",
        "replicates",
        "passes_per_rep",
        "wall_ms_per_20k_mean",
        "wall_ms_per_20k_sd",
        "ns_per_record_mean",
        "l3_ri_energy_nj_per_20k_mean",
        "l3_ri_energy_nj_per_20k_sd",
        "l3_reported_j_per_20k_mean",
        "l3_nj_per_record_mean",
        "l3_nj_per_record_sd",
        "l3_nj_per_byte_mean",
        "l3_nj_per_token_mean",
        "l3_instructions_per_record_mean",
        "l3_effective_pid_w_mean",
        "l2_ioreport_gross_reported_j_per_20k_mean",
        "l2_ioreport_gross_reported_j_per_20k_sd",
        "l2_ioreport_derived_marginal_j_per_20k",
        "l2_chip_w_mean",
        "l2_idle_w_mean",
        "l2_idle_drift_pct_mean",
        "l2_idle_drift_pct_max",
        "falsifier6_valid_replicates",
        "falsifier6_flag",
        "l3_energy_ratio_vs_fixed_binary",
        "wall_time_ratio_vs_fixed_binary",
    ]

    summary_workloads: list[dict] = []
    tsv_path = out_dir / "energy_reported_j.tsv"
    with tsv_path.open("w", encoding="utf-8", newline="\n") as tf:
        tf.write(
            f"# host={cpu_brand} ({round(mem_bytes / (1024**3))} GB) | macOS {sw_ver} ({platform.machine()}) | "
            f"Python {platform.python_version()} | {macmon_ver} | records={DEFAULT_RECORDS} | "
            f"replicates={args.replicates} | start_utc={start_utc}\n"
        )
        tf.write(
            "# telemetry discipline: measured_j=None, board_metered=false, strictly reported_j "
            "(L3=proc_pid_rusage RUSAGE_INFO_V6 ri_energy_nj [label D]; L2=macmon IOReport chip_power [label A2] + Falsifier 6 <=5% idle drift gate)\n"
        )
        writer = csv.writer(tf, delimiter="\t", lineterminator="\n")
        writer.writerow(tsv_headers)

        for cid, stage, wname, fname, _default_passes in ALL_WORKLOADS:
            rows = by_case[cid]
            n_rep = len(rows)
            passes = rows[0]["passes"]
            n_bytes = rows[0]["bytes"]
            n_tokens = rows[0]["tokens"]

            w_ms_vals = [r["wall_ms_per_20k"] for r in rows]
            w_ms_mean = st.mean(w_ms_vals)
            w_ms_sd = safe_sd(w_ms_vals)
            ns_per_rec = w_ms_mean * 1e6 / DEFAULT_RECORDS

            l3_20k_vals = [r["l3_ri_energy_nj_per_20k"] for r in rows]
            l3_20k_mean = st.mean(l3_20k_vals)
            l3_20k_sd = safe_sd(l3_20k_vals)
            l3_j_20k = l3_20k_mean / 1e9

            l3_rec_vals = [r["l3_nj_per_record"] for r in rows]
            l3_rec_mean = st.mean(l3_rec_vals)
            l3_rec_sd = safe_sd(l3_rec_vals)
            l3_nj_per_byte = l3_20k_mean / n_bytes
            l3_nj_per_tok = (l3_20k_mean / n_tokens) if n_tokens > 0 else None

            inst_rec_mean = st.mean(r["l3_instructions_per_record"] for r in rows)
            eff_pid_w = st.mean(
                (r["l3_ri_energy_nj_total"] / 1e9) / (r["wall_ns_total"] / 1e9) for r in rows
            )

            l2_gross_vals = [r["l2_gross_reported_j_per_20k"] for r in rows]
            l2_gross_mean = st.mean(l2_gross_vals)
            l2_gross_sd = safe_sd(l2_gross_vals)

            l2_marg_vals = [r["l2_derived_marginal_j_per_20k"] for r in rows]
            l2_marg_raw_mean = st.mean(l2_marg_vals)

            f6_valid_cnt = sum(1 for r in rows if r["falsifier6_valid_5pct"])
            f6_all_valid = f6_valid_cnt == n_rep
            f6_flag = (
                "VALID_5PCT"
                if f6_all_valid
                else f"INVALIDATED_COTENANT_DRIFT_{n_rep - f6_valid_cnt}_OF_{n_rep}"
            )
            l2_marg_cell = (
                f"{l2_marg_raw_mean:.6f}"
                if f6_all_valid
                else f"invalidated_falsifier6(raw={l2_marg_raw_mean:.6f})"
            )

            chip_w_mean = st.mean(r["l2_mean_chip_w"] for r in rows)
            idle_w_mean = st.mean(0.5 * (r["l2_idle_pre_w"] + r["l2_idle_post_w"]) for r in rows)
            drift_mean = st.mean(r["l2_idle_drift_pct"] for r in rows)
            drift_max = max(r["l2_idle_drift_pct"] for r in rows)

            e_ratio = l3_rec_mean / ref_l3_nj_per_rec
            t_ratio = w_ms_mean / ref_wall_ms

            writer.writerow(
                [
                    stage,
                    wname,
                    fname,
                    n_bytes,
                    DEFAULT_RECORDS,
                    n_tokens,
                    n_rep,
                    passes,
                    f"{w_ms_mean:.4f}",
                    f"{w_ms_sd:.4f}",
                    f"{ns_per_rec:.2f}",
                    f"{l3_20k_mean:.1f}",
                    f"{l3_20k_sd:.1f}",
                    f"{l3_j_20k:.6f}",
                    f"{l3_rec_mean:.2f}",
                    f"{l3_rec_sd:.2f}",
                    f"{l3_nj_per_byte:.3f}",
                    f"{l3_nj_per_tok:.2f}" if l3_nj_per_tok is not None else "NA",
                    f"{inst_rec_mean:.1f}",
                    f"{eff_pid_w:.3f}",
                    f"{l2_gross_mean:.6f}",
                    f"{l2_gross_sd:.6f}",
                    l2_marg_cell,
                    f"{chip_w_mean:.3f}",
                    f"{idle_w_mean:.3f}",
                    f"{drift_mean:.2f}",
                    f"{drift_max:.2f}",
                    f"{f6_valid_cnt}/{n_rep}",
                    f6_flag,
                    f"{e_ratio:.2f}",
                    f"{t_ratio:.2f}",
                ]
            )

            entry = {
                "case_id": cid,
                "stage": stage,
                "workload": wname,
                "corpus_file": fname,
                "bytes": n_bytes,
                "records": DEFAULT_RECORDS,
                "tokens": n_tokens,
                "replicates": n_rep,
                "passes_per_replicate": passes,
                "wall_ms_per_20k_mean": round(w_ms_mean, 4),
                "wall_ms_per_20k_sd": round(w_ms_sd, 4),
                "ns_per_record_mean": round(ns_per_rec, 2),
                "l3_ri_energy_nj_per_20k_mean": round(l3_20k_mean, 1),
                "l3_ri_energy_nj_per_20k_sd": round(l3_20k_sd, 1),
                "l3_reported_j_per_20k_mean": round(l3_j_20k, 6),
                "l3_nj_per_record_mean": round(l3_rec_mean, 2),
                "l3_nj_per_record_sd": round(l3_rec_sd, 2),
                "l3_nj_per_byte_mean": round(l3_nj_per_byte, 3),
                "l3_nj_per_token_mean": round(l3_nj_per_tok, 2) if l3_nj_per_tok is not None else None,
                "l3_instructions_per_record_mean": round(inst_rec_mean, 1),
                "l3_effective_pid_w_mean": round(eff_pid_w, 3),
                "l2_ioreport_gross_reported_j_per_20k_mean": round(l2_gross_mean, 6),
                "l2_ioreport_gross_reported_j_per_20k_sd": round(l2_gross_sd, 6),
                "l2_ioreport_derived_marginal_j_per_20k_mean": round(l2_marg_raw_mean, 6)
                if f6_all_valid
                else None,
                "l2_ioreport_derived_marginal_j_raw_unfiltered": round(l2_marg_raw_mean, 6),
                "l2_chip_w_mean": round(chip_w_mean, 3),
                "l2_idle_w_mean": round(idle_w_mean, 3),
                "l2_idle_drift_pct_mean": round(drift_mean, 2),
                "l2_idle_drift_pct_max": round(drift_max, 2),
                "falsifier6_valid_replicates": f6_valid_cnt,
                "falsifier6_all_valid_5pct": f6_all_valid,
                "falsifier6_flag": f6_flag,
                "l3_energy_ratio_vs_fixed_binary": round(e_ratio, 2),
                "wall_time_ratio_vs_fixed_binary": round(t_ratio, 2),
            }
            if stage == "tokenize":
                base_csv_nj = tok_csv_cl100k_nj if "cl100k_base" in cid else tok_csv_o200k_nj
                entry["l3_energy_ratio_vs_csv_same_tokenizer"] = round(l3_rec_mean / base_csv_nj, 3)
            summary_workloads.append(entry)

    by_id_sum = {e["case_id"]: e for e in summary_workloads}
    total_windows = len(all_rep_rows)
    total_f6_valid = sum(1 for r in all_rep_rows if r["falsifier6_valid_5pct"])
    mean_loadavg = st.mean(r["loadavg_1m"] for r in all_rep_rows)

    summary_doc = {
        "study": "ai-reads-human",
        "measured_j": None,
        "board_metered": False,
        "energy_reporting_level": "reported_j",
        "telemetry_channels": {
            "L3_process_D": {
                "source": "proc_pid_rusage(worker_pid, RUSAGE_INFO_V6).ri_energy_nj",
                "satb_level": "L3_process_cgroup",
                "shared_host_label": "D",
                "cotenant_isolated": True,
            },
            "L2_soc_A2": {
                "source": "macmon pipe (Apple Silicon IOReport chip_power / SMC sys_power)",
                "satb_level": "L2_socket_package",
                "shared_host_label": "A2",
                "cotenant_isolated": False,
                "falsifier6_idle_drift_ceiling_pct": 5.0,
            },
        },
        "environment": {
            "cpu": cpu_brand,
            "ram_gb": round(mem_bytes / (1024**3)),
            "os": f"macOS {sw_ver}",
            "arch": platform.machine(),
            "python": platform.python_version(),
            "macmon": macmon_ver,
            "shared_host_loadavg_1m_mean": round(mean_loadavg, 2),
            "start_utc": start_utc,
            "end_utc": end_utc,
        },
        "protocol": {
            "corpus_seed": CORPUS_SEED,
            "records": DEFAULT_RECORDS,
            "replicates": args.replicates,
            "interleaved_shuffled_rounds": True,
            "dedicated_worker_subprocess_per_measurement": True,
            "baseline_window_s": args.baseline_window_s,
            "total_measurement_windows": total_windows,
            "l2_falsifier6_valid_windows": total_f6_valid,
            "l2_falsifier6_invalidated_windows": total_windows - total_f6_valid,
        },
        "headline_reported_j": {
            "reference_fixed_binary_struct": {
                "l3_nj_per_record_mean": by_id_sum["parse_bin_struct"]["l3_nj_per_record_mean"],
                "l3_nj_per_record_sd": by_id_sum["parse_bin_struct"]["l3_nj_per_record_sd"],
                "l3_reported_j_per_20k_mean": by_id_sum["parse_bin_struct"]["l3_reported_j_per_20k_mean"],
                "wall_ms_per_20k_mean": by_id_sum["parse_bin_struct"]["wall_ms_per_20k_mean"],
            },
            "parse_comparisons_vs_fixed_binary": {
                "csv_stdlib": {
                    "l3_nj_per_record_mean": by_id_sum["parse_csv"]["l3_nj_per_record_mean"],
                    "l3_nj_per_record_sd": by_id_sum["parse_csv"]["l3_nj_per_record_sd"],
                    "l3_energy_ratio": by_id_sum["parse_csv"]["l3_energy_ratio_vs_fixed_binary"],
                    "wall_time_ratio": by_id_sum["parse_csv"]["wall_time_ratio_vs_fixed_binary"],
                },
                "json_orjson": {
                    "l3_nj_per_record_mean": by_id_sum["parse_json_orjson"]["l3_nj_per_record_mean"],
                    "l3_nj_per_record_sd": by_id_sum["parse_json_orjson"]["l3_nj_per_record_sd"],
                    "l3_energy_ratio": by_id_sum["parse_json_orjson"]["l3_energy_ratio_vs_fixed_binary"],
                    "wall_time_ratio": by_id_sum["parse_json_orjson"]["wall_time_ratio_vs_fixed_binary"],
                },
                "json_stdlib": {
                    "l3_nj_per_record_mean": by_id_sum["parse_json_stdlib"]["l3_nj_per_record_mean"],
                    "l3_nj_per_record_sd": by_id_sum["parse_json_stdlib"]["l3_nj_per_record_sd"],
                    "l3_energy_ratio": by_id_sum["parse_json_stdlib"]["l3_energy_ratio_vs_fixed_binary"],
                    "wall_time_ratio": by_id_sum["parse_json_stdlib"]["wall_time_ratio_vs_fixed_binary"],
                },
                "json_pretty_stdlib": {
                    "l3_nj_per_record_mean": by_id_sum["parse_json_pretty"]["l3_nj_per_record_mean"],
                    "l3_nj_per_record_sd": by_id_sum["parse_json_pretty"]["l3_nj_per_record_sd"],
                    "l3_energy_ratio": by_id_sum["parse_json_pretty"]["l3_energy_ratio_vs_fixed_binary"],
                    "wall_time_ratio": by_id_sum["parse_json_pretty"]["wall_time_ratio_vs_fixed_binary"],
                },
                "xml_lxml": {
                    "l3_nj_per_record_mean": by_id_sum["parse_xml_lxml"]["l3_nj_per_record_mean"],
                    "l3_nj_per_record_sd": by_id_sum["parse_xml_lxml"]["l3_nj_per_record_sd"],
                    "l3_energy_ratio": by_id_sum["parse_xml_lxml"]["l3_energy_ratio_vs_fixed_binary"],
                    "wall_time_ratio": by_id_sum["parse_xml_lxml"]["wall_time_ratio_vs_fixed_binary"],
                },
                "markdown_table": {
                    "l3_nj_per_record_mean": by_id_sum["parse_md_table"]["l3_nj_per_record_mean"],
                    "l3_nj_per_record_sd": by_id_sum["parse_md_table"]["l3_nj_per_record_sd"],
                    "l3_energy_ratio": by_id_sum["parse_md_table"]["l3_energy_ratio_vs_fixed_binary"],
                    "wall_time_ratio": by_id_sum["parse_md_table"]["wall_time_ratio_vs_fixed_binary"],
                },
                "markdown_list": {
                    "l3_nj_per_record_mean": by_id_sum["parse_md_list"]["l3_nj_per_record_mean"],
                    "l3_nj_per_record_sd": by_id_sum["parse_md_list"]["l3_nj_per_record_sd"],
                    "l3_energy_ratio": by_id_sum["parse_md_list"]["l3_energy_ratio_vs_fixed_binary"],
                    "wall_time_ratio": by_id_sum["parse_md_list"]["wall_time_ratio_vs_fixed_binary"],
                },
                "toml_tomllib": {
                    "l3_nj_per_record_mean": by_id_sum["parse_toml"]["l3_nj_per_record_mean"],
                    "l3_nj_per_record_sd": by_id_sum["parse_toml"]["l3_nj_per_record_sd"],
                    "l3_energy_ratio": by_id_sum["parse_toml"]["l3_energy_ratio_vs_fixed_binary"],
                    "wall_time_ratio": by_id_sum["parse_toml"]["wall_time_ratio_vs_fixed_binary"],
                },
                "yaml_libyaml_c": {
                    "l3_nj_per_record_mean": by_id_sum["parse_yaml_c"]["l3_nj_per_record_mean"],
                    "l3_nj_per_record_sd": by_id_sum["parse_yaml_c"]["l3_nj_per_record_sd"],
                    "l3_energy_ratio": by_id_sum["parse_yaml_c"]["l3_energy_ratio_vs_fixed_binary"],
                    "wall_time_ratio": by_id_sum["parse_yaml_c"]["wall_time_ratio_vs_fixed_binary"],
                },
                "yaml_pure_python": {
                    "l3_nj_per_record_mean": by_id_sum["parse_yaml_py"]["l3_nj_per_record_mean"],
                    "l3_nj_per_record_sd": by_id_sum["parse_yaml_py"]["l3_nj_per_record_sd"],
                    "l3_energy_ratio": by_id_sum["parse_yaml_py"]["l3_energy_ratio_vs_fixed_binary"],
                    "wall_time_ratio": by_id_sum["parse_yaml_py"]["wall_time_ratio_vs_fixed_binary"],
                },
            },
            "tokenize_cl100k_base_comparisons": {
                "csv": by_id_sum["tok_cl100k_base_recs_csv"],
                "json_compact": by_id_sum["tok_cl100k_base_recs_json"],
                "json_pretty": by_id_sum["tok_cl100k_base_recs_pretty_json"],
                "yaml": by_id_sum["tok_cl100k_base_recs_yaml"],
                "xml": by_id_sum["tok_cl100k_base_recs_xml"],
                "toml": by_id_sum["tok_cl100k_base_recs_toml"],
                "markdown_table": by_id_sum["tok_cl100k_base_recs_table_md"],
            },
            "tokenize_o200k_base_comparisons": {
                "csv": by_id_sum["tok_o200k_base_recs_csv"],
                "json_compact": by_id_sum["tok_o200k_base_recs_json"],
                "json_pretty": by_id_sum["tok_o200k_base_recs_pretty_json"],
                "yaml": by_id_sum["tok_o200k_base_recs_yaml"],
            },
        },
        "corpus_manifest": corpus_manifest,
        "workloads": summary_workloads,
    }

    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary_doc, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {tsv_path.name} and {summary_path.name} ({ len(summary_workloads) } workloads).", flush=True)
    return 0


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Apple Silicon L2+L3 reported_j benchmark for ai-reads-human")
    ap.add_argument("--worker", action="store_true", help="Internal single-workload isolated worker mode")
    ap.add_argument("--case-id", type=str, default="", help="Workload case ID (worker mode)")
    ap.add_argument("--passes", type=int, default=1, help="Number of passes (worker mode)")
    ap.add_argument("--corpus-dir", type=str, default="", help="Optional corpus directory path")
    ap.add_argument(
        "--out-dir",
        type=str,
        default=str(Path(__file__).resolve().parent),
        help="Output directory for TSV and JSON artifacts",
    )
    ap.add_argument("--replicates", type=int, default=5, help="Interleaved replicates per workload (default: 5)")
    ap.add_argument("--baseline-window-s", type=float, default=0.8, help="L2 idle baseline window in seconds")
    ap.add_argument("--pass-scale", type=float, default=1.0, help="Multiplier on per-window pass count")
    return ap.parse_args()


if __name__ == "__main__":
    cli_args = parse_args()
    if cli_args.worker:
        sys.exit(run_worker_mode(cli_args.case_id, Path(cli_args.corpus_dir), cli_args.passes))
    sys.exit(run_benchmark(cli_args))
