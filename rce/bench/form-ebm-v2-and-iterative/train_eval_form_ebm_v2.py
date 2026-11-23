#!/usr/bin/env python3
"""
FormEBM-v2: Contrastive + Multi-Step Margin Latent Energy Scorer over Canonical RCE Forms
Testing Hypothesis H5 (Validity Ranking AUROC >= 0.85) and Hypothesis H11 (>= 80% 5-Step
Edit-Distance Monotonicity) on the Strictly Disjoint 1,387-Form Split (`openIE-dev/rce` `1762fb4b`).

Strict provenance, zero-leakage, and telemetry guarantees:
  1. Verifies `PREREG_form_ebm_v2.json` against `PREREG_form_ebm_v2.json.sha256` and verifies
     `tasks_151.jsonl` (`6ae255a3...`) + `residual_40_tasks.jsonl` (`3ca3a327...`) digests first.
  2. Applies the exact 4-layer cryptographic & structural exclusion from `FormJEPA-v1` (`0` overlap
     with the 151 ladder or 40 H15 tasks) and the exact deterministic `shape_hash[:16] % 10` split:
     `1,106` train Forms (`0..7`), `144` validation Forms (`8`), and `137` unseen test Forms (`9`).
  3. Trains `FormEBM-v2` (`~5.7M` trainable parameters) strictly on the `1,106` training Forms
     using Contrastive Validity Margin Loss + Pairwise Multi-Step Edit-Depth Ranking Loss + VICReg
     anti-collapse regularization (`OMP_NUM_THREADS=10`, AMD Zen 5 RAPL `reported_j`).
  4. Computes `E_omega(x, y_cand)` purely via neural forward passes (ZERO calls to `rce check` on
     `y_cand` during scoring), then evaluates against `rce check` + `W-MUT-1` oracle on the unseen
     `137` held-out test Forms (`N = 200` H5 beams, `N = 100` H11 5-step chains) and `40` H15 tasks.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Enforce 10-thread cap before PyTorch initializes OpenMP pools
os.environ.setdefault("OMP_NUM_THREADS", "10")
os.environ.setdefault("MKL_NUM_THREADS", "10")

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

HERE = Path(__file__).resolve().parent
BENCH_ROOT = Path(os.environ["BENCH_ROOT"]) if "BENCH_ROOT" in os.environ else HERE.parent
RCE_REPO = Path(os.environ["RCE_REPO"]) if "RCE_REPO" in os.environ else (BENCH_ROOT / "rce")
EXP_REPO = Path(os.environ["EXP_REPO"]) if "EXP_REPO" in os.environ else (BENCH_ROOT / "openie-research-experiments")
WORK_DIR = Path(os.environ["WORK_DIR"]) if "WORK_DIR" in os.environ else (BENCH_ROOT / "work")
RCE_BIN = Path(os.environ["RCE_BIN"]) if "RCE_BIN" in os.environ else (RCE_REPO / "spec/checker/target/release/rce")

PREREG_PATH = HERE / "PREREG_form_ebm_v2.json"
PREREG_SHA_PATH = HERE / "PREREG_form_ebm_v2.json.sha256"
RESULTS_DIR = HERE / "results"

CORPUS_SEED = 20261122  # Preserves exact test_200 alignment with Wave 3 FormJEPA-v1
MODEL_SEED = 20261123
VOCAB_SIZE = 2048
MAX_SEQ_LEN = 256
MAX_WIN_LINES = 88
D_MODEL = 256
D_RULE = 64
N_HEADS = 8
N_ENC_LAYERS = 5

EDIT_OP_NAMES = [
    "OP_CMP_SWAP",
    "OP_CONST_BOUND",
    "OP_ARITH_EXPR",
    "OP_TYPE_ANNOT",
    "OP_SCOPE_IDENT",
    "OP_METHOD_CALL",
    "OP_TOTALITY_KEEP",
    "OP_CAP_WORLD",
]

CMP_VOCAB = ["<", "<=", ">", ">=", "==", "!=", "and", "or", "STRIP_NOT", "ADD_NOT"]
CONST_VOCAB = ["+1", "-1", "0", "1", "2", "true", "false", "-0.0", "BOUND_DOUBLE", "BOUND_INC"]
ARITH_VOCAB = ["+", "-", "*", "/", "%", "TO_CHECKED_SUB", "TO_CHECKED_ADD"]
TYPE_VOCAB = ["u64", "i64", "u32", "i32", "f64", "bool", "text", "usize", "u8", "i8"]
METHOD_VOCAB = ["len_bytes", "len_chars", "len", "is_empty", "words", "lines", "chars", "as_bytes", "clone"]

RULE_CODES = [
    "OK", "UNK_RULE", "W-SYN-1", "W-TY-1", "W-TY-3", "W-NAME-1", "W-NAME-2", "W-INT-1", "W-INT-2",
    "W-LEN-1", "W-WORLD-1", "W-CAP-3", "W-UNUSED-1", "W-DROP-1", "W-MUT-1", "W-MUT-2",
    "W-TOT-1", "W-EXH-1", "W-PAR-1", "W-PAR-3", "W-LEX-1", "W-LEX-3", "W-BOUNDS-1", "W-REC-1",
    "W-OWN-1", "W-OWN-2", "W-BOR-1", "W-UI-1", "W-RES-1", "W-MOD-1", "W-IMP-1", "W-PIN-1",
]
RULE_TO_ID = {r: i for i, r in enumerate(RULE_CODES)}

RCE_KEYWORDS = [
    "intent", "example", "state", "event", "error", "step", "on", "fn", "let", "var",
    "if", "elif", "else", "return", "emit", "fail", "try", "catch", "for", "in",
    "while", "loop", "bound", "match", "with", "arena", "device", "struct", "kind",
    "trait", "impl", "pub", "use", "module", "type", "ghost", "requires", "ensures",
    "decreases", "label", "atomic", "par", "spawn", "chan", "select", "recv", "send",
    "after", "break", "continue", "check", "and", "or", "not", "true", "false", "none",
    "some", "self", "comptime", "extern", "actor", "supervisor", "node", "const",
    "refuse", "refused", "kept", "by", "as", "mut", "then", "ok", "err", "pass", "law",
]

BUILTIN_IDENTIFIERS = [
    "bool", "text", "i8", "i16", "i32", "i64", "u8", "u16", "u32", "u64", "usize",
    "f32", "f64", "List", "Map", "Set", "Box", "Option", "Secret", "Cap", "Guarded",
    "Text", "World", "Template", "Shell", "Prompt", "Header", "mathint", "Tick",
    "main", "Eq", "Ord", "Hash", "Show", "Copy", "Data", "Merge", "Start", "Input",
    "Display", "Exit", "DirRead", "DirWrite", "len", "len_bytes", "len_chars",
    "checked_sub", "checked_add", "words", "lines", "chars", "push", "is_empty",
    "clone", "unwrap_or", "contains", "get", "insert", "remove", "as_bytes",
]

PUNCT_TOKENS = [
    "(", ")", "[", "]", "{", "}", ":", ",", ".", "->", "==", "!=", "<=", ">=",
    "<", ">", "+", "-", "*", "/", "%", "=", "&", "@", "#", "!",
]

TOKEN_RE = re.compile(
    r'"(?:\\.|[^"\\])*"|-0\.0|\d+\.\d+|\d+|->|==|!=|<=|>=|[A-Za-z_][A-Za-z0-9_]*|[^\sA-Za-z0-9_]'
)
RULE_DIAG_RE = re.compile(r"\b(W-[A-Z0-9]+-\d+)\b")
LINE_DIAG_RE = re.compile(r"\bline\s+(\d+)\b")
BACKTICK_IDENT_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)`")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_str(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


class SplitMix64:
    def __init__(self, seed: int) -> None:
        self.s = seed & 0xFFFFFFFFFFFFFFFF

    def next_u64(self) -> int:
        self.s = (self.s + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
        z = self.s
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
        return (z ^ (z >> 31)) & 0xFFFFFFFFFFFFFFFF

    def randbelow(self, n: int) -> int:
        return self.next_u64() % max(1, n)

    def choice(self, seq: list[Any]) -> Any:
        return seq[self.randbelow(len(seq))]

    def shuffle(self, seq: list[Any]) -> None:
        for i in range(len(seq) - 1, 0, -1):
            j = self.randbelow(i + 1)
            seq[i], seq[j] = seq[j], seq[i]


def set_all_seeds(seed: int = MODEL_SEED) -> None:
    np.random.seed(seed % (2**32 - 1))
    torch.manual_seed(seed)


# ============================================================================
# Linux Powercap RAPL Telemetry (`reported_j` Only; `measured_j = None`)
# ============================================================================

def read_rapl_uj() -> dict[str, int | None]:
    out: dict[str, int | None] = {"package_uj": None, "core_uj": None, "max_range_uj": None}
    for key, rel in [
        ("package_uj", "/sys/class/powercap/intel-rapl:0/energy_uj"),
        ("core_uj", "/sys/class/powercap/intel-rapl:0:0/energy_uj"),
        ("max_range_uj", "/sys/class/powercap/intel-rapl:0/max_energy_range_uj"),
    ]:
        p = Path(rel)
        try:
            if p.exists():
                out[key] = int(p.read_text().strip())
        except OSError:
            out[key] = None
    return out


def delta_rapl_j(start: dict[str, int | None], end: dict[str, int | None], field: str) -> float | None:
    s, e = start.get(field), end.get(field)
    if s is None or e is None:
        return None
    if e >= s:
        return round((e - s) / 1e6, 6)
    mx = start.get("max_range_uj") or (1 << 32)
    return round(((mx - s) + e) / 1e6, 6)


# ============================================================================
# Public Standard Library Catalog & Typed Form Edit Mechanics
# ============================================================================

def build_stdlib_catalog(rce_repo: Path) -> dict[str, Any]:
    lib_root = rce_repo / "stdlib/lib"
    mod_to_exports: dict[str, set[str]] = {}
    sym_to_mods: dict[str, list[str]] = {}
    if lib_root.exists():
        for p in sorted(lib_root.rglob("*.rce")):
            rel = p.relative_to(lib_root)
            parts = list(rel.with_suffix("").parts)
            mod_name = ".".join(parts[:-1]) if (len(parts) >= 2 and parts[-1] == parts[-2]) else ".".join(parts)
            exports: set[str] = set()
            for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                ls = line.strip()
                m_fn = re.match(r"^pub\s+fn\s+([A-Za-z_][A-Za-z0-9_]*)\b", ls)
                m_c = re.match(r"^pub\s+const\s+([A-Za-z_][A-Za-z0-9_]*)\b", ls)
                if m_fn:
                    exports.add(m_fn.group(1))
                elif m_c:
                    exports.add(m_c.group(1))
            if exports:
                mod_to_exports[mod_name] = exports
                for sym in sorted(exports):
                    sym_to_mods.setdefault(sym, []).append(mod_name)

    priority_mods = [
        "crypto", "hpke", "mls", "pq", "enc", "hash.blake3", "framing", "protect",
        "treekem", "welcome", "grp", "math", "core.bytes", "core.exact", "col",
        "fmt", "time", "text.utf8", "text.xml", "num.stats", "num.linalg", "ui.view",
        "energy", "rand.det", "os.path", "net.url", "net.http",
    ]
    ordered_mods = [m for m in priority_mods if m in mod_to_exports]
    for m in sorted(mod_to_exports):
        if m not in ordered_mods:
            ordered_mods.append(m)
    ordered_mods = ordered_mods[:40]
    return {
        "ordered_mods": ordered_mods,
        "mod_to_exports": {k: sorted(v) for k, v in mod_to_exports.items()},
        "sym_to_mods": sym_to_mods,
    }


def parse_diagnostic(diag_text: str) -> tuple[str, int | None, list[str]]:
    rules = RULE_DIAG_RE.findall(diag_text)
    rule = rules[0] if rules else "UNK_RULE"
    m_line = LINE_DIAG_RE.search(diag_text)
    line_no = int(m_line.group(1)) if m_line else None
    names: list[str] = []
    for nm in BACKTICK_IDENT_RE.findall(diag_text):
        if nm not in names:
            names.append(nm)
    return rule, line_no, names


def is_obligation_line(lines: list[str], idx: int) -> bool:
    s = lines[idx].strip()
    if s.startswith(("intent ", "example ", "check ", "law ", "requires ", "ensures ")):
        return True
    for j in range(idx - 1, -1, -1):
        lj = lines[j]
        if not lj.strip():
            continue
        if not lj.startswith(" "):
            return lj.startswith("intent ")
    return False


def collect_scope_identifiers(lines: list[str], target_idx: int) -> list[str]:
    state_fields: list[str] = []
    in_state = False
    for line in lines:
        s = line.strip()
        if re.match(r"^(?:state|actor)\s+[A-Za-z_]", s):
            in_state = True
            continue
        if in_state:
            if line.startswith("    ") and ":" in s:
                fname = s.split(":", 1)[0].strip()
                if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", fname) and fname not in state_fields:
                    state_fields.append(fname)
            elif s and not line.startswith(" "):
                in_state = False

    def_start = 0
    for j in range(min(target_idx, len(lines) - 1), -1, -1):
        sj = lines[j].strip()
        if sj.startswith(("fn ", "pub fn ", "step ", "extern ")):
            def_start = j
            break

    locals_in_def: list[str] = []
    header = lines[def_start].strip()
    for m in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*:", header):
        nm = m.group(1)
        if nm not in RCE_KEYWORDS and nm not in locals_in_def:
            locals_in_def.append(nm)
    for j in range(def_start + 1, min(target_idx + 1, len(lines))):
        sj = lines[j].strip()
        for pat in [r"^(?:let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\b", r"^for\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\b"]:
            m = re.match(pat, sj)
            if m:
                nm = m.group(1)
                if nm != "_" and nm not in locals_in_def:
                    locals_in_def.append(nm)

    combined = list(reversed(locals_in_def)) + [f for f in state_fields if f not in locals_in_def]
    return combined[:16]


def _qualify_stdlib_module(src: str, primary_mod: str, stdlib_cat: dict[str, Any]) -> str:
    lines = src.splitlines()
    mods_to_use: list[str] = []
    for ln in lines:
        m = re.match(r"^#!\s*lib\s+([A-Za-z0-9_.]+)", ln.strip())
        if m and m.group(1) in stdlib_cat["mod_to_exports"] and m.group(1) not in mods_to_use:
            mods_to_use.append(m.group(1))
    if primary_mod not in mods_to_use and primary_mod in stdlib_cat["mod_to_exports"]:
        mods_to_use.append(primary_mod)

    existing_uses = {
        m.group(1) for ln in lines if (m := re.match(r"^use\s+([A-Za-z0-9_.]+)\b", ln.strip()))
    }
    sym_to_mods = stdlib_cat["sym_to_mods"]
    local_defs = {
        m.group(1)
        for ln in lines
        if (m := re.match(r"^(?:pub\s+)?(?:fn|const)\s+([A-Za-z_][A-Za-z0-9_]*)\b", ln.strip()))
    }
    bare_calls = set(re.findall(r"(?<![.\w])([a-z_][A-Za-z0-9_]*)\s*\(", src))
    bare_consts = set(re.findall(r"(?<![.\w])([A-Z][A-Z0-9_]{2,})\b", src))
    for sym in sorted(bare_calls | bare_consts):
        if sym in local_defs or sym in RCE_KEYWORDS:
            continue
        owners = sym_to_mods.get(sym, [])
        if len(owners) == 1 and owners[0] not in mods_to_use and owners[0] in ("crypto", primary_mod):
            mods_to_use.append(owners[0])

    active_mods = list(dict.fromkeys(list(existing_uses) + mods_to_use))
    qual_map: dict[str, str] = {}
    for mname in active_mods:
        short = mname.split(".")[-1]
        for sym in stdlib_cat["mod_to_exports"].get(mname, []):
            if sym not in local_defs and sym not in qual_map:
                qual_map[sym] = short

    new_lines: list[str] = []
    inserted_uses = False
    for ln in lines:
        s = ln.strip()
        if re.match(r"^#!\s*lib\s+", s):
            continue
        if not inserted_uses and s and not s.startswith("#") and not s.startswith("module "):
            for mname in mods_to_use:
                if mname not in existing_uses:
                    new_lines.append(f"use {mname}")
                    existing_uses.add(mname)
            inserted_uses = True

        if not s.startswith(("#", "use ", "module ", "fn ", "pub fn ", "const ", "pub const ")):
            for sym, prefix in qual_map.items():
                ln = re.sub(rf"(?<![.\w`\"]){re.escape(sym)}\b", f"{prefix}.{sym}", ln)
        elif s.startswith(("fn ", "pub fn ", "const ", "pub const ")):
            for sep in ("->", "="):
                if sep in ln:
                    lhs, rhs = ln.split(sep, 1)
                    for sym, prefix in qual_map.items():
                        rhs = re.sub(rf"(?<![.\w`\"]){re.escape(sym)}\b", f"{prefix}.{sym}", rhs)
                    ln = lhs + sep + rhs
                    break
        new_lines.append(ln)

    return "\n".join(new_lines) + ("\n" if src.endswith("\n") else "")


def apply_edit(
    src: str,
    line_idx: int,
    op_id: int,
    arg_id: int,
    stdlib_cat: dict[str, Any],
    diag_names: list[str] | None = None,
) -> str:
    lines = src.splitlines()
    if not lines:
        return src
    line_idx = max(0, min(len(lines) - 1, line_idx))
    diag_names = diag_names or []

    if op_id == 0:
        if is_obligation_line(lines, line_idx) or arg_id >= len(CMP_VOCAB):
            return src
        target = CMP_VOCAB[arg_id]
        line = lines[line_idx]
        if target == "STRIP_NOT":
            new_line = re.sub(r"\bnot\s*\(([^()]+)\)", r"\1", line, count=1)
            if new_line == line:
                new_line = re.sub(r"\bnot\s+([A-Za-z_][A-Za-z0-9_.]*)", r"\1", line, count=1)
            lines[line_idx] = new_line
        elif target == "ADD_NOT":
            m = re.search(r"\b(if|elif|while)\s+(.+?)(\s+bound\s+\d+|\s*->.*)?$", line)
            if m:
                lines[line_idx] = line[:m.start(2)] + f"not ({m.group(2)})" + (m.group(3) or "")
        else:
            cmp_re = re.compile(r"(<=|>=|==|!=|<|>|\band\b|\bor\b)")
            m = cmp_re.search(line)
            if m:
                lines[line_idx] = line[:m.start()] + target + line[m.end():]
        return "\n".join(lines) + ("\n" if src.endswith("\n") else "")

    if op_id == 1:
        if is_obligation_line(lines, line_idx) or arg_id >= len(CONST_VOCAB):
            return src
        act = CONST_VOCAB[arg_id]
        line = lines[line_idx]
        if act in ("true", "false"):
            other = "false" if act == "true" else "true"
            lines[line_idx] = re.sub(rf"\b{other}\b", act, line, count=1)
        elif act == "-0.0":
            lines[line_idx] = re.sub(r"(?<![\w.])-?0\.0\b", "-0.0", line, count=1)
        elif act in ("BOUND_DOUBLE", "BOUND_INC"):
            m = re.search(r"\bbound\s+(\d+)\b", line)
            if m:
                v = int(m.group(1))
                nv = (v * 2 if v > 0 else 16) if act == "BOUND_DOUBLE" else (v + 1)
                lines[line_idx] = line[:m.start(1)] + str(nv) + line[m.end(1):]
        else:
            nums = list(re.finditer(r"(?<![A-Za-z_.\d])(\d+)(?![A-Za-z_.\d])", line))
            if nums:
                m = nums[-1]
                v = int(m.group(1))
                nv = (v + 1) if act == "+1" else (max(0, v - 1) if act == "-1" else int(act))
                lines[line_idx] = line[:m.start(1)] + str(nv) + line[m.end(1):]
        return "\n".join(lines) + ("\n" if src.endswith("\n") else "")

    if op_id == 2:
        if is_obligation_line(lines, line_idx) or arg_id >= len(ARITH_VOCAB):
            return src
        act = ARITH_VOCAB[arg_id]
        line = lines[line_idx]
        if act == "TO_CHECKED_SUB":
            lines[line_idx] = re.sub(
                r"\b([A-Za-z_][A-Za-z0-9_]*)\s*-\s*(\d+)\b",
                r"try \1.checked_sub(\2) else Underflow",
                line,
                count=1,
            )
        elif act == "TO_CHECKED_ADD":
            lines[line_idx] = re.sub(
                r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\+\s*(\d+)\b",
                r"\1.checked_add(\2)",
                line,
                count=1,
            )
        else:
            for m in re.finditer(r"(?<!-)(?<!/)[+\-*/%](?!>)", line):
                lines[line_idx] = line[:m.start()] + act + line[m.end():]
                break
        return "\n".join(lines) + ("\n" if src.endswith("\n") else "")

    if op_id == 3:
        if is_obligation_line(lines, line_idx) or arg_id >= len(TYPE_VOCAB):
            return src
        new_ty = TYPE_VOCAB[arg_id]
        line = lines[line_idx]
        ty_pat = r"(:\s*|->\s*)(u64|i64|u32|i32|u16|i16|u8|i8|usize|f64|f32|bool|text)\b"
        lines[line_idx] = re.sub(ty_pat, rf"\g<1>{new_ty}", line, count=1)
        return "\n".join(lines) + ("\n" if src.endswith("\n") else "")

    if op_id == 4:
        if arg_id < 16:
            if is_obligation_line(lines, line_idx):
                return src
            scope_ids = collect_scope_identifiers(lines, line_idx)
            for dn in diag_names:
                if dn not in scope_ids and dn not in RCE_KEYWORDS:
                    scope_ids.append(dn)
            if arg_id >= len(scope_ids):
                return src
            replacement = scope_ids[arg_id]
            line = lines[line_idx]
            for dn in diag_names:
                if dn != replacement and re.search(rf"(?<![.\w]){re.escape(dn)}\b", line):
                    lines[line_idx] = re.sub(rf"(?<![.\w]){re.escape(dn)}\b", replacement, line, count=1)
                    return "\n".join(lines) + ("\n" if src.endswith("\n") else "")
            rhs_split = (
                line.split("=", 1)
                if ("=" in line and "==" not in line and "!=" not in line and "<=" not in line and ">=" not in line)
                else (line.split("->", 1) if "->" in line else [line])
            )
            target_part = rhs_split[-1]
            cands = [
                m for m in re.finditer(r"(?<![.\w])([A-Za-z_][A-Za-z0-9_]*)\b(?!\s*\()", target_part)
                if m.group(1) not in RCE_KEYWORDS and m.group(1) not in BUILTIN_IDENTIFIERS and m.group(1) != replacement
            ]
            if cands:
                m = cands[0]
                prefix_len = len(line) - len(target_part)
                lines[line_idx] = line[:prefix_len + m.start()] + replacement + line[prefix_len + m.end():]
            return "\n".join(lines) + ("\n" if src.endswith("\n") else "")

        if arg_id == 16:
            line = lines[line_idx]
            lines[line_idx] = re.sub(r"^(\s*(?:let|var|for)\s+)([a-z][A-Za-z0-9_]*)\b", r"\1_\2", line, count=1)
            return "\n".join(lines) + ("\n" if src.endswith("\n") else "")

        mod_idx = arg_id - 17
        ordered_mods: list[str] = stdlib_cat["ordered_mods"]
        if 0 <= mod_idx < len(ordered_mods):
            return _qualify_stdlib_module(src, ordered_mods[mod_idx], stdlib_cat)
        return src

    if op_id == 5:
        if is_obligation_line(lines, line_idx) or arg_id >= len(METHOD_VOCAB):
            return src
        new_m = METHOD_VOCAB[arg_id]
        lines[line_idx] = re.sub(
            r"\.(len_bytes|len_chars|len|is_empty|words|lines|chars|as_bytes|clone)\s*\(",
            f".{new_m}(",
            lines[line_idx],
            count=1,
        )
        return "\n".join(lines) + ("\n" if src.endswith("\n") else "")

    if op_id == 6:
        if arg_id == 0:
            out_lines = []
            for ln in lines:
                ln2 = re.sub(r"->\s*refused\s*:", "-> kept:", ln)
                ln2 = re.sub(r"^(\s*(?:step\b.*->\s*|if\b.*->\s*|else\s*->\s*)?)refuse\s+([A-Z][A-Za-z0-9_]*)\b", r"\1fail \2", ln2)
                ln2 = re.sub(r"\brefuse\s+([A-Z][A-Za-z0-9_]*)\b", r"fail \1", ln2)
                out_lines.append(ln2)
            return "\n".join(out_lines) + ("\n" if src.endswith("\n") else "")
        regions = [m.group(1) for ln in lines if (m := re.match(r"^state\s+([A-Za-z_][A-Za-z0-9_]*)\b", ln.strip()))]
        events = [m.group(1) for ln in lines if (m := re.match(r"^event\s+([A-Za-z_][A-Za-z0-9_]*)\b(.*)$", ln.strip()))]
        errors = [m.group(1) for ln in lines if (m := re.match(r"^error\s+([A-Za-z_][A-Za-z0-9_]*)\b", ln.strip()))]
        handled = {
            (m.group(1), m.group(2))
            for ln in lines
            if (m := re.match(r"^step\s+([A-Za-z_][A-Za-z0-9_]*)\s+on\s+([A-Za-z_][A-Za-z0-9_]*)\b", ln.strip()))
        }
        missing = [(r, ev) for r in regions for ev in events if (r, ev) not in handled]
        pick = arg_id - 1
        if 0 <= pick < len(missing):
            reg, ev = missing[pick]
            ev_decl = next((ln.strip() for ln in lines if ln.strip().startswith(f"event {ev}")), f"event {ev}")
            pat = f"{ev}(..)" if "(" in ev_decl else ev
            rhs = f"fail {errors[0]}" if errors else "pass"
            lines.append(f"step {reg} on {pat} -> {rhs}")
            return "\n".join(lines) + "\n"
        return src

    if op_id == 7:
        if arg_id == 0:
            extern_fns: list[str] = []
            out_lines = []
            for ln in lines:
                s = ln.strip()
                m_ext = re.match(r'^(pub\s+)?extern\s+"C"\s+fn\s+([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)(.*)$', s)
                if m_ext:
                    pub_kw = m_ext.group(1) or ""
                    fn_nm = m_ext.group(2)
                    params = m_ext.group(3).strip()
                    rest = m_ext.group(4)
                    extern_fns.append(fn_nm)
                    if "World" not in params:
                        new_params = f"w: &World, {params}" if params else "w: &World"
                        ln = f'{pub_kw}extern "C" fn {fn_nm}({new_params}){rest}'
                elif re.match(r"^(pub\s+)?fn\s+main\s*\(\s*\)", s):
                    ln = re.sub(r"fn\s+main\s*\(\s*\)", "fn main(w: &World)", ln, count=1)
                out_lines.append(ln)
            if extern_fns:
                patched = []
                for ln in out_lines:
                    if not ln.strip().startswith(("extern ", "pub extern ", "intent ", "example ", "check ")):
                        for fn_nm in extern_fns:
                            ln = re.sub(rf"\b{re.escape(fn_nm)}\(\s*(?!w\b)", f"{fn_nm}(w, ", ln)
                            ln = ln.replace(f"{fn_nm}(w, )", f"{fn_nm}(w)")
                    patched.append(ln)
                out_lines = patched
            return "\n".join(out_lines) + ("\n" if src.endswith("\n") else "")
        if arg_id == 1:
            out_lines = [re.sub(r"\bpath\b", "name", ln) if not ln.strip().startswith("#") else ln for ln in lines]
            return "\n".join(out_lines) + ("\n" if src.endswith("\n") else "")

    return src


# ============================================================================
# Obligation Check & Disjoint Form Extraction (Exact 4-Layer Exclusion)
# ============================================================================

def extract_obligations_summary(src: str) -> dict[str, Any]:
    examples_lhs: list[str] = []
    checks_cnt = 0
    decls: dict[str, set[str]] = {
        "state": set(), "event": set(), "error": set(), "struct": set(),
        "kind": set(), "fn": set(), "extern": set(), "step": set(),
    }
    for raw in src.splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("example "):
            examples_lhs.append(s[len("example "):].split("->", 1)[0].strip())
        elif s.startswith("check "):
            checks_cnt += 1
        else:
            m = re.match(r"^(?:pub\s+)?(state|event|error|struct|kind)\s+([A-Za-z_][A-Za-z0-9_]*)", s)
            if m:
                decls[m.group(1)].add(m.group(2))
                continue
            m_fn = re.match(r"^(?:pub\s+)?(?:ct\s+)?fn\s+([A-Za-z_][A-Za-z0-9_]*)", s)
            if m_fn:
                decls["fn"].add(m_fn.group(1))
                continue
            m_ext = re.match(r'^extern\s+"[^"]+"\s+fn\s+([A-Za-z_][A-Za-z0-9_]*)', s)
            if m_ext:
                decls["extern"].add(m_ext.group(1))
                continue
            m_step = re.match(r"^step\s+([A-Za-z_][A-Za-z0-9_]*)\s+on\s+([A-Za-z_][A-Za-z0-9_]*)", s)
            if m_step:
                decls["step"].add(f"{m_step.group(1)}:{m_step.group(2)}")
    return {"examples_lhs": examples_lhs, "checks_cnt": checks_cnt, "decls": decls}


def check_obligations_preserved(mutant_src: str, cand_src: str) -> tuple[bool, str]:
    ob_m = extract_obligations_summary(mutant_src)
    ob_c = extract_obligations_summary(cand_src)
    if len(ob_c["examples_lhs"]) < len(ob_m["examples_lhs"]):
        return False, "example_count_dropped"
    if ob_c["checks_cnt"] < ob_m["checks_cnt"]:
        return False, "check_count_dropped"
    for k, req_names in ob_m["decls"].items():
        if req_names - ob_c["decls"][k]:
            return False, f"missing_decl_{k}"
    m_cnt = Counter(ob_m["examples_lhs"])
    c_cnt = Counter(ob_c["examples_lhs"])
    kept_lhs = sum(min(cnt, c_cnt[lhs]) for lhs, cnt in m_cnt.items())
    if ob_m["examples_lhs"] and kept_lhs < max(1, len(ob_m["examples_lhs"]) - 1):
        return False, "example_lhs_altered"
    return True, "ok"


def _extract_primary_decls(src: str) -> set[str]:
    out: set[str] = set()
    for ln in src.splitlines():
        s = ln.strip()
        m = re.match(r"^(?:state|actor|module)\s+([A-Za-z_][A-Za-z0-9_.]*)", s)
        if m:
            out.add(m.group(1))
    return out


def _check_and_canonicalize_worker(args: tuple[str, str, str, str]) -> dict[str, Any] | None:
    rce_bin, rel_path, origin, src = args
    with tempfile.TemporaryDirectory(prefix="febm_chk_") as td:
        fp = Path(td) / "prog.rce"
        fp.write_text(src, encoding="utf-8")
        try:
            chk = subprocess.run([rce_bin, "check", str(fp)], capture_output=True, text=True, timeout=4.0)
        except subprocess.TimeoutExpired:
            return None
        if chk.returncode != 0:
            return None
        try:
            fmt = subprocess.run([rce_bin, "fmt", str(fp)], capture_output=True, text=True, timeout=4.0)
            canon_src = fp.read_text(encoding="utf-8") if fmt.returncode == 0 else src
            fp.write_text(canon_src, encoding="utf-8")
            nl = subprocess.run([rce_bin, "fmt", "nameless", str(fp)], capture_output=True, text=True, timeout=4.0)
        except subprocess.TimeoutExpired:
            return None
        if nl.returncode != 0 or not nl.stdout.strip():
            return None
        nameless_src = nl.stdout
        return {
            "path": rel_path,
            "origin": origin,
            "canon_src": canon_src,
            "nameless_src": nameless_src,
            "shape_hash": sha256_str(nameless_src),
            "canon_sha256": sha256_str(canon_src),
            "raw_sha256": sha256_str(src),
            "decls": sorted(_extract_primary_decls(canon_src)),
        }


def build_disjoint_form_pool(
    rce_bin: Path,
    rce_repo: Path,
    tasks_151_path: Path,
    residual_40_path: Path,
    forms_jsonl_path: Path,
    workers: int = 16,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    t151 = [json.loads(l) for l in tasks_151_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    t40 = [json.loads(l) for l in residual_40_path.read_text(encoding="utf-8").splitlines() if l.strip()]

    forbidden_paths: set[str] = set()
    forbidden_slugs: set[str] = set()
    forbidden_decls: set[str] = set()
    forbidden_hashes: set[str] = set()

    with tempfile.TemporaryDirectory(prefix="febm_forbid_") as td:
        tmp_f = Path(td) / "t.rce"
        for t in t151 + t40:
            p = t.get("path") or t["id"].split("@")[0].split("#")[0]
            forbidden_paths.add(p)
            stem = Path(p).stem
            forbidden_slugs.add(stem)
            if "_" in stem and stem.split("_", 1)[0].isdigit():
                forbidden_slugs.add(stem.split("_", 1)[1])
            for key in ("original", "mutant"):
                txt = t.get(key, "")
                if not txt:
                    continue
                forbidden_hashes.add(sha256_str(txt))
                forbidden_decls.update(_extract_primary_decls(txt))
                tmp_f.write_text(txt, encoding="utf-8")
                nl = subprocess.run([str(rce_bin), "fmt", "nameless", str(tmp_f)], capture_output=True, text=True)
                if nl.returncode == 0 and nl.stdout:
                    forbidden_hashes.add(sha256_str(nl.stdout))
        for p in sorted(forbidden_paths):
            hp = rce_repo / p
            if hp.exists():
                txt = hp.read_text(encoding="utf-8", errors="ignore")
                forbidden_hashes.add(sha256_str(txt))
                forbidden_decls.update(_extract_primary_decls(txt))
                nl = subprocess.run([str(rce_bin), "fmt", "nameless", str(hp)], capture_output=True, text=True)
                if nl.returncode == 0 and nl.stdout:
                    forbidden_hashes.add(sha256_str(nl.stdout))

    raw_candidates: list[tuple[str, str, str, str]] = []
    seen_paths: set[str] = set()

    def _is_forbidden(rel_p: str, src: str) -> bool:
        if rel_p in forbidden_paths:
            return True
        stem = Path(rel_p).stem
        base = stem.split("_", 1)[1] if ("_" in stem and stem.split("_", 1)[0].isdigit()) else stem
        if stem in forbidden_slugs or base in forbidden_slugs:
            return True
        if _extract_primary_decls(src) & forbidden_decls:
            return True
        if sha256_str(src) in forbidden_hashes:
            return True
        return False

    for sub, origin in [
        ("spec/examples", "spec-examples"),
        ("spec/examples-0.9/ok", "spec-examples-0.9"),
        ("stdlib/lib", "stdlib"),
        ("book/listings", "book-listings"),
        ("apps", "apps"),
        ("programs", "programs"),
    ]:
        d = rce_repo / sub
        if not d.exists():
            continue
        for fp in sorted(d.rglob("*.rce")):
            rel = fp.relative_to(rce_repo).as_posix()
            if "/refused/" in rel or "_FIXTURE" in fp.name:
                continue
            src = fp.read_text(encoding="utf-8", errors="ignore")
            if len(src.splitlines()) > 180 or _is_forbidden(rel, src):
                continue
            seen_paths.add(rel)
            raw_candidates.append((str(rce_bin), rel, origin, src))

    conf_dir = rce_repo / "conformance/tests"
    if conf_dir.exists():
        for fp in sorted(conf_dir.rglob("*.rce")):
            rel = fp.relative_to(rce_repo).as_posix()
            if "_FIXTURE" in fp.name or rel in seen_paths:
                continue
            raw = fp.read_text(encoding="utf-8", errors="ignore")
            if "#--- rce-test" not in raw or "# fixtures:" in raw:
                continue
            src_part, meta_part = raw.split("#--- rce-test", 1)
            if not re.search(r"#\s*expect:\s*(?:accept|run|trace)\b", meta_part):
                continue
            m_prov = re.search(r"#\s*provenance:\s*(.+)", meta_part)
            if m_prov:
                prov = m_prov.group(1)
                if any(fp_p in prov for fp_p in forbidden_paths) or any(
                    re.search(rf"\b{re.escape(sl)}\b", prov) for sl in forbidden_slugs
                ):
                    continue
            src = src_part.strip() + "\n"
            if len(src.splitlines()) < 3 or len(src.splitlines()) > 160 or _is_forbidden(rel, src):
                continue
            seen_paths.add(rel)
            raw_candidates.append((str(rce_bin), rel, "conformance-accept", src))

    if forms_jsonl_path.exists():
        for line in forms_jsonl_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            rel = row["path"]
            src = row["source"]
            if rel in seen_paths or len(src.splitlines()) > 180 or _is_forbidden(rel, src):
                continue
            if row.get("shape_hash") in forbidden_hashes:
                continue
            seen_paths.add(rel)
            raw_candidates.append((str(rce_bin), rel, row.get("origin", "forms-jsonl"), src))

    by_shape: dict[str, dict[str, Any]] = {}
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as ex:
        for res in ex.map(_check_and_canonicalize_worker, raw_candidates, chunksize=8):
            if res is None:
                continue
            if (
                res["shape_hash"] in forbidden_hashes
                or res["canon_sha256"] in forbidden_hashes
                or res["raw_sha256"] in forbidden_hashes
                or (set(res["decls"]) & forbidden_decls)
            ):
                continue
            if res["shape_hash"] not in by_shape:
                by_shape[res["shape_hash"]] = res

    forms = [by_shape[k] for k in sorted(by_shape)]
    audit = {
        "forbidden_paths_count": len(forbidden_paths),
        "forbidden_slugs_count": len(forbidden_slugs),
        "forbidden_primary_decls_count": len(forbidden_decls),
        "forbidden_hashes_count": len(forbidden_hashes),
        "candidates_scanned": len(raw_candidates),
        "disjoint_unique_shapes": len(forms),
        "disjoint_by_origin": dict(sorted(Counter(f["origin"] for f in forms).items())),
        "cryptographic_overlap_count": 0,
    }
    return forms, audit


def _alpha_rename_variant(src: str, variant_seed: int) -> str:
    lines = src.splitlines()
    rng = SplitMix64(variant_seed)
    candidates: list[tuple[int, int, str]] = []
    n = len(lines)
    i = 0
    while i < n:
        s = lines[i].strip()
        if s.startswith(("fn ", "pub fn ", "step ")):
            end = i + 1
            while end < n and (lines[end].startswith("    ") or not lines[end].strip()):
                end += 1
            if not s.startswith(("fn main", "pub fn main")):
                for mp in re.finditer(r"\b([a-z][a-z0-9_]*)\s*:", lines[i]):
                    pnm = mp.group(1)
                    if pnm not in RCE_KEYWORDS and pnm not in BUILTIN_IDENTIFIERS and pnm != "w":
                        candidates.append((i, end, pnm))
            for j in range(i + 1, end):
                m = re.match(r"^\s*(?:let|var|for)\s+([a-z][a-z0-9_]*)\b", lines[j])
                if m and m.group(1) not in RCE_KEYWORDS and m.group(1) not in BUILTIN_IDENTIFIERS:
                    candidates.append((i, end, m.group(1)))
            i = end
        else:
            i += 1
    for j, ln in enumerate(lines):
        if ln.startswith("    ") and ":" in ln and "=" in ln:
            fname = ln.strip().split(":", 1)[0].strip()
            if re.fullmatch(r"[a-z][a-z0-9_]*", fname) and fname not in RCE_KEYWORDS and fname not in BUILTIN_IDENTIFIERS:
                candidates.append((0, n, fname))
    if not candidates:
        return src
    start, end, old_nm = rng.choice(candidates)
    suffix = ["_alt", "_q", "_k", "_m", "_v2", "_s"][rng.randbelow(6)]
    new_nm = f"{old_nm}{suffix}"
    if re.search(rf"\b{re.escape(new_nm)}\b", src):
        return src
    for j in range(start, end):
        if not lines[j].strip().startswith(("#", "intent ", "example ")):
            lines[j] = re.sub(rf"(?<![.\w]){re.escape(old_nm)}\b(?!\s*:)", new_nm, lines[j])
            if j == start or lines[j].strip().startswith(f"{old_nm}:"):
                lines[j] = re.sub(rf"\b{re.escape(old_nm)}(\s*:)", rf"{new_nm}\1", lines[j], count=1)
    return "\n".join(lines) + ("\n" if src.endswith("\n") else "")


def _propose_forward_corruptions(
    canon_src: str,
    stdlib_cat: dict[str, Any],
    rng: SplitMix64,
    max_per_form: int = 14,
) -> list[tuple[str, int, int, int, str]]:
    lines = canon_src.splitlines()
    proposals: list[tuple[str, int, int, int, str]] = []
    ordered_mods: list[str] = stdlib_cat["ordered_mods"]

    for li, ln in enumerate(lines):
        if is_obligation_line(lines, li) or ln.strip().startswith("#"):
            continue
        for m in re.finditer(r"(<=|>=|==|!=|<|>|\band\b|\bor\b)", ln):
            orig_op = m.group(1)
            if orig_op in CMP_VOCAB[:8]:
                orig_arg = CMP_VOCAB.index(orig_op)
                alts = (
                    ["<", "<=", ">", ">="] if orig_op in ("<", "<=", ">", ">=")
                    else (["==", "!="] if orig_op in ("==", "!=") else ["and", "or"])
                )
                bad_op = rng.choice([a for a in alts if a != orig_op])
                b_lines = list(lines)
                b_lines[li] = ln[:m.start()] + bad_op + ln[m.end():]
                proposals.append(("\n".join(b_lines) + "\n", li, 0, orig_arg, "guard_cmp_swap"))
                break
        m_if = re.search(r"\b(if|elif|while)\s+(.+?)(\s+bound\s+\d+|\s*->.*)?$", ln)
        if m_if and "not (" not in m_if.group(2):
            b_lines = list(lines)
            b_lines[li] = ln[:m_if.start(2)] + f"not ({m_if.group(2)})" + (m_if.group(3) or "")
            proposals.append(("\n".join(b_lines) + "\n", li, 0, 8, "guard_negation"))

    for li, ln in enumerate(lines):
        if is_obligation_line(lines, li) or ln.strip().startswith(("#", "use ", "module ")):
            continue
        if re.search(r"\btrue\b", ln):
            b_lines = list(lines)
            b_lines[li] = re.sub(r"\btrue\b", "false", ln, count=1)
            proposals.append(("\n".join(b_lines) + "\n", li, 1, CONST_VOCAB.index("true"), "bool_flip"))
        elif re.search(r"\bfalse\b", ln):
            b_lines = list(lines)
            b_lines[li] = re.sub(r"\bfalse\b", "true", ln, count=1)
            proposals.append(("\n".join(b_lines) + "\n", li, 1, CONST_VOCAB.index("false"), "bool_flip"))
        nums = list(re.finditer(r"(?<![A-Za-z_.\d])(\d+)(?![A-Za-z_.\d])", ln))
        if nums and "bound " not in ln:
            m = nums[-1]
            v = int(m.group(1))
            b_lines = list(lines)
            if 0 <= v < 1000:
                if v > 0 and rng.randbelow(2) == 0:
                    b_lines[li] = ln[:m.start(1)] + str(v - 1) + ln[m.end(1):]
                    proposals.append(("\n".join(b_lines) + "\n", li, 1, 0, "const_off_by_one"))
                else:
                    b_lines[li] = ln[:m.start(1)] + str(v + 1) + ln[m.end(1):]
                    proposals.append(("\n".join(b_lines) + "\n", li, 1, 1, "const_off_by_one"))

    for li, ln in enumerate(lines):
        if is_obligation_line(lines, li) or ln.strip().startswith("#"):
            continue
        for m in re.finditer(r"(?<!-)(?<!/)([+\-*/])(?!>)", ln):
            orig_op = m.group(1)
            orig_arg = ARITH_VOCAB.index(orig_op)
            bad_op = "-" if orig_op == "+" else "+"
            b_lines = list(lines)
            b_lines[li] = ln[:m.start()] + bad_op + ln[m.end():]
            proposals.append(("\n".join(b_lines) + "\n", li, 2, orig_arg, "arith_op_swap"))
            break

    for li, ln in enumerate(lines):
        if is_obligation_line(lines, li) or ln.strip().startswith("#"):
            continue
        m = re.search(r"(:\s*|->\s*)(u64|i64|u32|i32|f64|bool|text)\b", ln)
        if m:
            orig_ty = m.group(2)
            orig_arg = TYPE_VOCAB.index(orig_ty)
            bad_ty = {"u64": "bool", "i64": "bool", "u32": "text", "i32": "text", "f64": "u64", "bool": "u64", "text": "u64"}[orig_ty]
            b_lines = list(lines)
            b_lines[li] = ln[:m.start(2)] + bad_ty + ln[m.end(2):]
            proposals.append(("\n".join(b_lines) + "\n", li, 3, orig_arg, "type_mismatch"))

    for li, ln in enumerate(lines):
        if is_obligation_line(lines, li) or ln.strip().startswith(("#", "fn ", "pub fn ", "state ", "event ", "struct ")):
            continue
        scope_ids = collect_scope_identifiers(lines, li)
        if scope_ids:
            for k_idx, real_id in enumerate(scope_ids[:8]):
                if re.search(rf"(?<![.\w]){re.escape(real_id)}\b(?!\s*\()", ln) and not re.match(rf"^\s*(?:let|var|for)\s+{re.escape(real_id)}\b", ln):
                    b_lines = list(lines)
                    bad_id = scope_ids[(k_idx + 1) % len(scope_ids)] if len(scope_ids) > 1 else f"{real_id}_undef"
                    b_lines[li] = re.sub(rf"(?<![.\w]){re.escape(real_id)}\b(?!\s*\()", bad_id, ln, count=1)
                    proposals.append(("\n".join(b_lines) + "\n", li, 4, k_idx, "scope_ident_defect"))
                    break
        m_unused = re.match(r"^(\s*(?:let|var)\s+)_([a-z][A-Za-z0-9_]*)\b", ln)
        if m_unused:
            b_lines = list(lines)
            b_lines[li] = re.sub(r"^(\s*(?:let|var)\s+)_([a-z][A-Za-z0-9_]*)\b", r"\1\2", ln, count=1)
            proposals.append(("\n".join(b_lines) + "\n", li, 4, 16, "unused_binding_hygiene"))

    for li, ln in enumerate(lines):
        m_use = re.match(r"^use\s+([A-Za-z0-9_.]+)\b", ln.strip())
        if m_use and m_use.group(1) in ordered_mods:
            mod_name = m_use.group(1)
            mod_idx = ordered_mods.index(mod_name)
            short = mod_name.split(".")[-1]
            b_lines = [
                f"#!lib {mod_name}" if ln2.strip() == f"use {mod_name}"
                else re.sub(rf"\b{re.escape(short)}\.([A-Za-z_][A-Za-z0-9_]*)", r"\1", ln2)
                for ln2 in lines
            ]
            proposals.append(("\n".join(b_lines) + "\n", li, 4, 17 + mod_idx, "stdlib_unqualified"))
            break

    for li, ln in enumerate(lines):
        if is_obligation_line(lines, li) or ln.strip().startswith("#"):
            continue
        m_meth = re.search(r"\.(len_bytes|len_chars|is_empty|words|lines|chars)\s*\(", ln)
        if m_meth:
            orig_m = m_meth.group(1)
            orig_arg = METHOD_VOCAB.index(orig_m)
            bad_m = "len" if orig_m in ("len_bytes", "len_chars") else "len_bytes"
            b_lines = list(lines)
            b_lines[li] = ln[:m_meth.start(1)] + bad_m + ln[m_meth.end(1):]
            proposals.append(("\n".join(b_lines) + "\n", li, 5, orig_arg, "method_projection_defect"))

    if any(("fail " in ln or "-> kept:" in ln) for ln in lines):
        b_lines = []
        first_line = 0
        found_first = False
        for li, ln in enumerate(lines):
            ln2 = ln.replace("-> kept:", "-> refused:")
            ln2 = re.sub(r"\bfail\s+([A-Z][A-Za-z0-9_]*)\b", r"refuse \1", ln2)
            if ln2 != ln and not found_first:
                first_line = li
                found_first = True
            b_lines.append(ln2)
        if found_first:
            proposals.append(("\n".join(b_lines) + "\n", first_line, 6, 0, "retired_refuse_syntax"))

    step_indices = [
        li for li, ln in enumerate(lines)
        if re.match(r"^step\s+[A-Za-z_][A-Za-z0-9_]*\s+on\s+[A-Za-z_][A-Za-z0-9_]*\s*->\s*fail\s+", ln.strip())
    ]
    if step_indices:
        drop_li = step_indices[-1]
        b_lines = [ln for idx, ln in enumerate(lines) if idx != drop_li]
        proposals.append(("\n".join(b_lines) + "\n", min(drop_li, len(b_lines) - 1), 6, 1, "missing_totality_step"))

    for li, ln in enumerate(lines):
        if ln.strip().startswith(('extern "C" fn ', 'pub extern "C" fn ')) and "w: &World" in ln:
            b_lines = []
            for ln2 in lines:
                ln3 = re.sub(r'extern\s+"C"\s+fn\s+([A-Za-z_][A-Za-z0-9_]*)\(\s*w:\s*&World\s*,?\s*', r'extern "C" fn \1(', ln2)
                ln3 = re.sub(r"fn\s+main\(\s*w:\s*&World\s*\)", "fn main()", ln3)
                b_lines.append(ln3)
            proposals.append(("\n".join(b_lines) + "\n", li, 7, 0, "missing_world_cap"))
            break

    rng.shuffle(proposals)
    return proposals[:max_per_form]


def _verify_defect_worker(args: tuple[str, dict[str, Any], dict[str, Any], int, int]) -> list[dict[str, Any]]:
    rce_bin, form_row, stdlib_cat, seed_i, max_per_form = args
    rng = SplitMix64(CORPUS_SEED ^ ((seed_i + 1) * 0x9E3779B97F4A7C15))
    variants = [form_row["canon_src"]]
    for k_var in range(3):
        alpha_src = _alpha_rename_variant(form_row["canon_src"], CORPUS_SEED ^ ((seed_i * 7 + k_var + 1) * 1315423911))
        if alpha_src not in variants:
            variants.append(alpha_src)

    verified: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="febm_mut_") as td:
        mut_f = Path(td) / "mut.rce"
        rep_f = Path(td) / "rep.rce"
        for v_idx, valid_src in enumerate(variants):
            if v_idx > 0:
                rep_f.write_text(valid_src, encoding="utf-8")
                try:
                    if subprocess.run([rce_bin, "check", str(rep_f)], capture_output=True, timeout=2.5).returncode != 0:
                        continue
                except subprocess.TimeoutExpired:
                    continue
            per_v = max_per_form if v_idx == 0 else max(5, max_per_form // 2)
            cands = _propose_forward_corruptions(valid_src, stdlib_cat, rng, max_per_form=per_v)
            for broken_src, line_idx, op_id, arg_id, defect_tag in cands:
                if broken_src == valid_src:
                    continue
                mut_f.write_text(broken_src, encoding="utf-8")
                try:
                    chk = subprocess.run([rce_bin, "check", str(mut_f)], capture_output=True, text=True, timeout=3.0)
                except subprocess.TimeoutExpired:
                    continue
                if chk.returncode == 0:
                    continue
                diag = (chk.stdout + "\n" + chk.stderr).strip()
                rule_code, diag_line, diag_names = parse_diagnostic(diag)
                repaired = apply_edit(broken_src, line_idx, op_id, arg_id, stdlib_cat, diag_names)
                rep_f.write_text(repaired, encoding="utf-8")
                try:
                    chk_rep = subprocess.run([rce_bin, "check", str(rep_f)], capture_output=True, text=True, timeout=3.0)
                except subprocess.TimeoutExpired:
                    continue
                if chk_rep.returncode != 0:
                    continue
                verified.append({
                    "parent_path": form_row["path"],
                    "origin": form_row["origin"],
                    "shape_hash": form_row["shape_hash"],
                    "alpha_renamed": v_idx > 0,
                    "defect_tag": defect_tag,
                    "broken_form": broken_src,
                    "checker_rule_code": rule_code,
                    "diag_line": diag_line,
                    "diag_names": diag_names[:4],
                    "diagnostic": re.sub(r"/[^\s:]+/mut\.rce", "MUTANT.rce", diag)[:240],
                    "edit_op_and_span": {
                        "line_idx": line_idx,
                        "op_id": op_id,
                        "op_name": EDIT_OP_NAMES[op_id],
                        "arg_id": arg_id,
                    },
                    "valid_form": repaired,
                    "nameless_valid_form": form_row["nameless_src"],
                })
    return verified


# ============================================================================
# Zero-Leakage Candidate Edit Beam Generator & 5-Step Corruption Chain Builder
# ============================================================================

def enumerate_diagnostic_candidate_beam(
    broken_src: str,
    diag_text: str,
    stdlib_cat: dict[str, Any],
    max_beam: int = 16,
) -> list[dict[str, Any]]:
    """
    Pure, zero-leakage candidate generator given ONLY `(broken_src, diag_text)`.
    Enumerates typed Form edits in the diagnostic neighborhood across the 8 edit families
    WITHOUT ever calling `rce check` or touching `valid_form`.
    """
    rule_code, diag_line, diag_names = parse_diagnostic(diag_text)
    lines = broken_src.splitlines()
    n = len(lines)
    if n == 0:
        return []

    d0 = max(0, min(n - 1, (diag_line or 1) - 1))
    focus_lines = []
    for off in (0, -1, 1, -2, 2):
        li = d0 + off
        if 0 <= li < n and li not in focus_lines:
            focus_lines.append(li)
    # Also include first state/fn declaration lines in case diagnostic points at usage site of a bad decl type
    for li, ln in enumerate(lines[:24]):
        if ln.strip().startswith(("state ", "    ", "fn ", "pub fn ", "extern ")) and li not in focus_lines:
            focus_lines.append(li)
            if len(focus_lines) >= 8:
                break

    # Prioritize edit families by rule family while keeping diverse alternatives in beam
    prioritized_actions: list[tuple[int, int, int]] = []
    if rule_code == "W-SYN-1":
        prioritized_actions.append((d0, 6, 0))
    if rule_code == "W-LEN-1":
        for li in focus_lines[:4]:
            prioritized_actions.extend([(li, 5, 0), (li, 5, 1), (li, 5, 3)])
    if rule_code in ("W-WORLD-1", "W-CAP-3"):
        prioritized_actions.extend([(d0, 7, 0), (d0, 7, 1)])
    if rule_code == "W-UNUSED-1":
        for li in focus_lines[:4]:
            prioritized_actions.append((li, 4, 16))
    if rule_code == "W-NAME-1":
        for li in focus_lines[:4]:
            for k in range(6):
                prioritized_actions.append((li, 4, k))
        for m_i in range(min(6, len(stdlib_cat["ordered_mods"]))):
            prioritized_actions.append((0, 4, 17 + m_i))

    # General typed edits on focus lines (types, comparisons, arithmetic, constants, scope)
    for li in focus_lines[:5]:
        for t_i in range(7):
            prioritized_actions.append((li, 3, t_i))
        prioritized_actions.append((li, 0, 8))
        for c_i in range(8):
            prioritized_actions.append((li, 0, c_i))
        for a_i in range(4):
            prioritized_actions.append((li, 2, a_i))
        for k_i in range(4):
            prioritized_actions.append((li, 4, k_i))
        for b_i in (0, 1, 5, 6, 7):
            prioritized_actions.append((li, 1, b_i))
    prioritized_actions.extend([(0, 6, 0), (0, 6, 1), (0, 7, 0)])

    seen: set[str] = set()
    beam: list[dict[str, Any]] = []
    for li, op_id, arg_id in prioritized_actions:
        cand = apply_edit(broken_src, li, op_id, arg_id, stdlib_cat, diag_names)
        if cand != broken_src and cand not in seen:
            seen.add(cand)
            beam.append({
                "text": cand,
                "line_idx": li,
                "op_id": op_id,
                "op_name": EDIT_OP_NAMES[op_id],
                "arg_id": arg_id,
            })
            if len(beam) >= max_beam - 1:
                break

    # Include unedited broken_src at end of candidate pool as a hard zero-edit negative
    if broken_src not in seen:
        beam.append({
            "text": broken_src,
            "line_idx": d0,
            "op_id": -1,
            "op_name": "NO_OP",
            "arg_id": 0,
        })
    return beam[:max_beam]


def _label_beam_worker(args: tuple[str, dict[str, Any], dict[str, Any]]) -> dict[str, Any] | None:
    """Labels a candidate beam using `rce check` + obligation preservation (training/eval oracle)."""
    rce_bin, ex, stdlib_cat = args
    beam = enumerate_diagnostic_candidate_beam(ex["broken_form"], ex["diagnostic"], stdlib_cat, max_beam=16)
    if not beam:
        return None
    with tempfile.TemporaryDirectory(prefix="febm_bm_") as td:
        fp = Path(td) / "cand.rce"
        labeled = []
        for item in beam:
            kept_ok, _ = check_obligations_preserved(ex["broken_form"], item["text"])
            if not kept_ok:
                ok = False
            else:
                fp.write_text(item["text"], encoding="utf-8")
                try:
                    rc = subprocess.run([rce_bin, "check", str(fp)], capture_output=True, timeout=3.0).returncode
                    ok = rc == 0
                except subprocess.TimeoutExpired:
                    ok = False
            labeled.append({**item, "admitted": ok})
    return {
        "shape_hash": ex["shape_hash"],
        "defect_tag": ex["defect_tag"],
        "broken_form": ex["broken_form"],
        "checker_rule_code": ex["checker_rule_code"],
        "diag_line": ex["diag_line"],
        "diagnostic": ex["diagnostic"],
        "candidates": labeled,
    }


def _corrupt_single_distinct_step(
    cur_src: str,
    used_lines: set[int],
    step_num: int,
    stdlib_cat: dict[str, Any],
    rng: SplitMix64,
) -> tuple[str, int] | None:
    """Apply one additional AST/Form corruption on an untouched line (or fresh cumulative site) so edit depth increases monotonically."""
    muts = _propose_forward_corruptions(cur_src, stdlib_cat, rng, max_per_form=24)
    for m_src, li, _, _, _ in muts:
        if li not in used_lines and m_src != cur_src:
            return m_src, li
    lines = cur_src.splitlines()
    elig = [
        idx for idx, ln in enumerate(lines)
        if idx not in used_lines and ln.strip() and not ln.strip().startswith(("#", "intent ", "example ", "module "))
    ]
    rng.shuffle(elig)
    for li in elig:
        ln = lines[li]
        b_lines = list(lines)
        if ":" in ln and any(t in ln for t in ("u64", "i64", "bool", "text", "f64")):
            b_lines[li] = re.sub(r"\b(u64|i64|bool|text|f64)\b", lambda m: "bool" if m.group(1) != "bool" else "u64", ln, count=1)
        elif "=" in ln and not ln.strip().startswith("check "):
            b_lines[li] = ln + f" + _undef_{step_num}"
        elif "->" in ln:
            b_lines[li] = ln + f" + _undef_{step_num}"
        elif ln.startswith("    "):
            b_lines[li] = f"    let _bad_ty_{step_num}: bool = {step_num}\n" + ln
        else:
            continue
        cand = "\n".join(b_lines) + "\n"
        if cand != cur_src:
            return cand, li

    # Secondary cumulative fallback for compact (<5-line) Forms: insert one typed defect binding inside body block
    body_lines = [idx for idx, ln in enumerate(lines) if ln.startswith("    ") and ln.strip()]
    if body_lines:
        ins_li = rng.choice(body_lines)
        b_lines = list(lines)
        b_lines.insert(ins_li, f"    let _cum_defect_{step_num}: bool = {step_num + 1}")
        return "\n".join(b_lines) + "\n", ins_li
    return None


def _build_5step_chain_worker(args: tuple[str, dict[str, Any], dict[str, Any], int]) -> dict[str, Any] | None:
    """Constructs a checker-verified 5-step cumulative corruption chain y^(0) -> y^(1) -> ... -> y^(5)."""
    rce_bin, form_row, stdlib_cat, seed_i = args
    rng = SplitMix64(MODEL_SEED ^ ((seed_i + 1) * 0x517CC1B727220A95))
    base_src = (
        form_row["canon_src"]
        if seed_i % 2 == 0
        else _alpha_rename_variant(form_row["canon_src"], MODEL_SEED ^ (seed_i * 2654435761))
    )
    with tempfile.TemporaryDirectory(prefix="febm_ch_") as td:
        fp = Path(td) / "c.rce"
        fp.write_text(base_src, encoding="utf-8")
        try:
            if subprocess.run([rce_bin, "check", str(fp)], capture_output=True, timeout=2.5).returncode != 0:
                base_src = form_row["canon_src"]
        except subprocess.TimeoutExpired:
            return None

        chain = [base_src]
        used_lines: set[int] = set()
        cur = base_src
        for step_num in range(1, 6):
            res = _corrupt_single_distinct_step(cur, used_lines, step_num, stdlib_cat, rng)
            if res is None:
                return None
            nxt, touched_li = res
            fp.write_text(nxt, encoding="utf-8")
            try:
                rc = subprocess.run([rce_bin, "check", str(fp)], capture_output=True, timeout=2.5).returncode
            except subprocess.TimeoutExpired:
                return None
            if rc == 0 or nxt in chain:
                return None
            used_lines.add(touched_li)
            chain.append(nxt)
            cur = nxt

    return {
        "shape_hash": form_row["shape_hash"],
        "origin": form_row["origin"],
        "chain": chain,
    }


# ============================================================================
# Pair-Aligned Form AST S-Expression Tokenizer (`PairFormTokenizer`)
# ============================================================================

class PairFormTokenizer:
    """
    Reference-anchored Form AST S-expression tokenizer (`max_seq_len = 256`).
    Fixes three structural blind spots of uncalibrated `FormJEPA-v1`:
      1. Anchors `local_map` on `ref_src` first so identifier edits or newly introduced unbound
         identifiers (`<NEW_ID:0..15>`) never shift subsequent `<ID:k>` slots across the module.
      2. Distinguishes `_`-prefixed unused-hygiene bindings (`<UNDERSCORE_ID:0..31>`) from live
         local identifiers (`<ID:0..63>`), and encodes integer residues (`<NUM_MOD:0..31>`).
      3. Emits per-token structural/diff tags (`0..7`) comparing `cand_src` against `ref_src`
         using purely syntactic surface information (ZERO checker calls!).
    """

    def __init__(self, stdlib_mods: list[str] | None = None) -> None:
        self.tok2id: dict[str, int] = {}
        specials = [
            "<PAD>", "<UNK>", "<CLS>", "<S_OPEN>", "<S_CLOSE>",
            "<INDENT_1>", "<INDENT_2>", "<INDENT_3>", "<INDENT_4>",
            "<STR_LIT>", "<FLOAT_LIT>", "<NEG_ZERO>", "<ZERO_FLOAT>",
        ]
        for s in specials:
            self._add(s)
        for r in RULE_CODES:
            self._add(f"<RULE:{r}>")
        for i in range(MAX_WIN_LINES):
            self._add(f"<L{i}>")
        for kw in RCE_KEYWORDS:
            self._add(kw)
        for bi in BUILTIN_IDENTIFIERS:
            self._add(bi)
        for pt in PUNCT_TOKENS:
            self._add(pt)
        for n in range(0, 17):
            self._add(f"<NUM:{n}>")
        for n in range(32):
            self._add(f"<NUM_MOD:{n}>")
        for i in range(64):
            self._add(f"<ID:{i}>")
        for i in range(32):
            self._add(f"<UNDERSCORE_ID:{i}>")
        for i in range(16):
            self._add(f"<NEW_ID:{i}>")
        for m in (stdlib_mods or []):
            for part in m.split("."):
                self._add(part)
        self.pad_id = self.tok2id["<PAD>"]
        self.unk_id = self.tok2id["<UNK>"]
        self.cls_id = self.tok2id["<CLS>"]
        self.s_open = self.tok2id["<S_OPEN>"]
        self.s_close = self.tok2id["<S_CLOSE>"]
        self.line_toks = [self.tok2id[f"<L{i}>"] for i in range(MAX_WIN_LINES)]

    def _add(self, tok: str) -> None:
        if tok not in self.tok2id and len(self.tok2id) < VOCAB_SIZE:
            self.tok2id[tok] = len(self.tok2id)

    def _select_window(self, n_lines: int, focus_1based: int | None) -> list[int]:
        if n_lines <= MAX_WIN_LINES:
            return list(range(n_lines))
        focus = max(0, min(n_lines - 1, (focus_1based or 1) - 1))
        hdr = 18
        rem = MAX_WIN_LINES - hdr
        start = max(hdr, focus - rem // 2)
        end = min(n_lines, start + rem)
        start = max(hdr, end - rem)
        return (list(range(hdr)) + list(range(start, end)))[:MAX_WIN_LINES]

    def _map_tok(
        self,
        rt: str,
        local_map: dict[str, str],
        allow_new_slot: bool,
        new_map: dict[str, str],
    ) -> int:
        if rt in self.tok2id:
            return self.tok2id[rt]
        if rt.startswith('"'):
            return self.tok2id["<STR_LIT>"]
        if rt == "-0.0":
            return self.tok2id["<NEG_ZERO>"]
        if rt == "0.0":
            return self.tok2id["<ZERO_FLOAT>"]
        if re.fullmatch(r"\d+\.\d+", rt):
            return self.tok2id["<FLOAT_LIT>"]
        if rt.isdigit():
            val = int(rt)
            if val <= 16:
                return self.tok2id[f"<NUM:{val}>"]
            return self.tok2id[f"<NUM_MOD:{val % 32}>"]
        if re.fullmatch(r"_[A-Za-z0-9_]+", rt):
            if rt not in local_map:
                u_cnt = sum(1 for v in local_map.values() if v.startswith("<UNDERSCORE_ID:"))
                local_map[rt] = f"<UNDERSCORE_ID:{min(31, u_cnt)}>"
            return self.tok2id[local_map[rt]]
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", rt):
            if rt in local_map:
                return self.tok2id[local_map[rt]]
            if not allow_new_slot:
                n_cnt = sum(1 for v in local_map.values() if v.startswith("<ID:"))
                local_map[rt] = f"<ID:{min(63, n_cnt)}>"
                return self.tok2id[local_map[rt]]
            if rt not in new_map:
                new_map[rt] = f"<NEW_ID:{min(15, len(new_map))}>"
            return self.tok2id[new_map[rt]]
        return self.unk_id

    def encode_pair(
        self,
        ref_src: str,
        cand_src: str,
        rule_code: str = "OK",
        diag_line_1based: int | None = None,
    ) -> tuple[list[int], list[int], list[int], list[int]]:
        """
        Returns `(ref_ids, ref_tags, cand_ids, cand_tags)` each of length `MAX_SEQ_LEN`.
        """
        ref_lines = ref_src.splitlines() or [""]
        cand_lines = cand_src.splitlines() or [""]

        # If rule_code == "OK" and diag_line is None, center window on first differing line if file > MAX_WIN_LINES
        eff_focus = diag_line_1based
        if eff_focus is None and len(cand_lines) > MAX_WIN_LINES:
            for idx_d in range(min(len(ref_lines), len(cand_lines))):
                if ref_lines[idx_d] != cand_lines[idx_d]:
                    eff_focus = idx_d + 1
                    break

        ref_win = self._select_window(len(ref_lines), eff_focus)
        cand_win = self._select_window(len(cand_lines), eff_focus)

        # Count identifier occurrences across `cand_src` (ignoring comments) to tag singleton symbols
        cand_ident_counts: Counter[str] = Counter()
        for ln in cand_lines:
            s = ln.lstrip(" ")
            if s.startswith("#") and not s.startswith("#!"):
                continue
            for m_id in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\b", s):
                cand_ident_counts[m_id.group(1)] += 1

        local_map: dict[str, str] = {}
        new_map: dict[str, str] = {}
        # Pre-populate `local_map` deterministically across `ref_lines`
        for ln in ref_lines:
            s = ln.lstrip(" ")
            if s.startswith("#") and not s.startswith("#!"):
                continue
            for rt in TOKEN_RE.findall(s):
                self._map_tok(rt, local_map, allow_new_slot=False, new_map=new_map)

        rule_tok = f"<RULE:{rule_code}>" if f"<RULE:{rule_code}>" in self.tok2id else "<RULE:UNK_RULE>"
        diag_0 = (diag_line_1based - 1) if (diag_line_1based and diag_line_1based > 0) else -999

        def _build_stream(
            lines: list[str],
            win: list[int],
            other_lines: list[str],
            is_cand: bool,
        ) -> tuple[list[int], list[int]]:
            ids = [self.cls_id, self.tok2id[rule_tok], self.s_open]
            tags = [7, 1 if rule_code != "OK" else 0, 7]
            for slot_i, li in enumerate(win):
                if len(ids) >= MAX_SEQ_LEN - 4:
                    break
                raw_ln = lines[li]
                other_ln = other_lines[li] if li < len(other_lines) else None
                line_changed = (other_ln is None) or (raw_ln != other_ln)
                near_diag = abs(li - diag_0) <= 1
                ob_flag = is_obligation_line(lines, li)

                if not line_changed:
                    base_tag = 1 if (not is_cand and near_diag) else 0
                else:
                    if ob_flag:
                        base_tag = 3
                    elif near_diag and rule_code != "OK":
                        base_tag = 1
                    else:
                        base_tag = 2

                ids.append(self.line_toks[slot_i])
                tags.append(base_tag)

                stripped = raw_ln.lstrip(" ")
                ind = min(4, (len(raw_ln) - len(stripped)) // 4)
                if ind > 0 and len(ids) < MAX_SEQ_LEN - 2:
                    ids.append(self.tok2id[f"<INDENT_{ind}>"])
                    tags.append(base_tag)

                if stripped.startswith("#") and not stripped.startswith("#!"):
                    continue

                ids.append(self.s_open)
                tags.append(7)
                for rt in TOKEN_RE.findall(stripped)[:20]:
                    if len(ids) >= MAX_SEQ_LEN - 2:
                        break
                    tid = self._map_tok(rt, local_map, allow_new_slot=is_cand, new_map=new_map)
                    tok_tag = base_tag
                    if is_cand and not line_changed:
                        if rt.startswith("_") and len(rt) > 1:
                            tok_tag = 5
                        elif (
                            re.fullmatch(r"[a-z][A-Za-z0-9_]*", rt)
                            and rt not in RCE_KEYWORDS
                            and rt not in BUILTIN_IDENTIFIERS
                            and cand_ident_counts[rt] == 1
                        ):
                            tok_tag = 4
                    elif is_cand and line_changed:
                        if rt.startswith("_") and len(rt) > 1:
                            tok_tag = 5
                        elif (
                            re.fullmatch(r"[a-z][A-Za-z0-9_]*", rt)
                            and rt not in RCE_KEYWORDS
                            and rt not in BUILTIN_IDENTIFIERS
                            and cand_ident_counts[rt] == 1
                        ):
                            tok_tag = 4
                    ids.append(tid)
                    tags.append(tok_tag)
                if len(ids) < MAX_SEQ_LEN - 1:
                    ids.append(self.s_close)
                    tags.append(7)

            if len(ids) < MAX_SEQ_LEN:
                ids.append(self.s_close)
                tags.append(7)
            while len(ids) < MAX_SEQ_LEN:
                ids.append(self.pad_id)
                tags.append(7)
            return ids[:MAX_SEQ_LEN], tags[:MAX_SEQ_LEN]

        r_ids, r_tags = _build_stream(ref_lines, ref_win, cand_lines, is_cand=False)
        c_ids, c_tags = _build_stream(cand_lines, cand_win, ref_lines, is_cand=True)
        return r_ids, r_tags, c_ids, c_tags


# ============================================================================
# `FormEBM-v2` PyTorch Architecture (`~5.85M` Trainable Parameters)
# ============================================================================

class SafeLayerNorm(nn.Module):
    """
    Pure-tensor LayerNorm (identical parameter shape/count to `nn.LayerNorm`) that avoids
    the ROCm 7.13a `gfx1151` `native_layer_norm_backward` non-finite weight-grad bug.
    """

    def __init__(self, d: int, eps: float = 1e-5) -> None:
        super().__init__()
        self.weight = nn.Parameter(torch.ones(d))
        self.bias = nn.Parameter(torch.zeros(d))
        self.eps = eps

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        xf = x.float()
        mu = xf.mean(dim=-1, keepdim=True)
        var = (xf - mu).pow(2).mean(dim=-1, keepdim=True)
        y = (xf - mu) * torch.rsqrt(var + self.eps)
        return (y * self.weight + self.bias).to(x.dtype)


class FastPreLNTransformerBlock(nn.Module):
    def __init__(self, d_model: int = D_MODEL, nhead: int = N_HEADS, dim_ff: int = 1024, dropout: float = 0.1) -> None:
        super().__init__()
        self.nhead = nhead
        self.d_head = d_model // nhead
        self.scale = self.d_head ** -0.5
        self.norm1 = SafeLayerNorm(d_model)
        self.qkv = nn.Linear(d_model, 3 * d_model)
        self.out_proj = nn.Linear(d_model, d_model)
        self.drop = nn.Dropout(dropout)
        self.norm2 = SafeLayerNorm(d_model)
        self.fc1 = nn.Linear(d_model, dim_ff)
        self.fc2 = nn.Linear(dim_ff, d_model)

    def forward(self, x: torch.Tensor, pad_mask: torch.Tensor) -> torch.Tensor:
        bsz, seqlen, dim = x.shape
        qkv = self.qkv(self.norm1(x)).view(bsz, seqlen, 3, self.nhead, self.d_head).permute(2, 0, 3, 1, 4)
        att = (qkv[0] @ qkv[1].transpose(-2, -1)) * self.scale
        att = att.masked_fill(pad_mask[:, None, None, :], -1e4)
        probs = self.drop(att.softmax(dim=-1))
        ctx = (probs @ qkv[2]).transpose(1, 2).reshape(bsz, seqlen, dim)
        x = x + self.drop(self.out_proj(ctx))
        x = x + self.drop(self.fc2(F.gelu(self.fc1(self.norm2(x)))))
        return x


class CrossDifferenceBlock(nn.Module):
    """Cross-attention difference layer comparing candidate token states H_cand to H_ref."""

    def __init__(self, d_model: int = D_MODEL, nhead: int = N_HEADS, dim_ff: int = 512, dropout: float = 0.1) -> None:
        super().__init__()
        self.nhead = nhead
        self.d_head = d_model // nhead
        self.scale = self.d_head ** -0.5
        self.norm_q = SafeLayerNorm(d_model)
        self.norm_kv = SafeLayerNorm(d_model)
        self.q_proj = nn.Linear(d_model, d_model)
        self.kv_proj = nn.Linear(d_model, 2 * d_model)
        self.out_proj = nn.Linear(d_model, d_model)
        self.drop = nn.Dropout(dropout)
        self.norm2 = SafeLayerNorm(d_model)
        self.fc1 = nn.Linear(d_model, dim_ff)
        self.fc2 = nn.Linear(dim_ff, d_model)

    def forward(
        self,
        h_cand: torch.Tensor,
        h_ref: torch.Tensor,
        cand_pad: torch.Tensor,
        ref_pad: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        bsz, clen, dim = h_cand.shape
        rlen = h_ref.size(1)
        q = self.q_proj(self.norm_q(h_cand)).view(bsz, clen, self.nhead, self.d_head).transpose(1, 2)
        kv = self.kv_proj(self.norm_kv(h_ref)).view(bsz, rlen, 2, self.nhead, self.d_head).permute(2, 0, 3, 1, 4)
        att = (q @ kv[0].transpose(-2, -1)) * self.scale
        att = att.masked_fill(ref_pad[:, None, None, :], -1e4)
        aligned_ref = (att.softmax(dim=-1) @ kv[1]).transpose(1, 2).reshape(bsz, clen, dim)
        diff = h_cand - self.drop(self.out_proj(aligned_ref))
        diff = diff + self.drop(self.fc2(F.gelu(self.fc1(self.norm2(diff)))))

        valid_f = (~cand_pad).float().unsqueeze(-1)
        denom = valid_f.sum(dim=1).clamp(min=1.0)
        df = diff.float()
        mean_diff = (df * valid_f).sum(dim=1) / denom
        rms_diff = torch.sqrt((df.pow(2) * valid_f).sum(dim=1) / denom + 1e-4)
        return mean_diff.to(diff.dtype), rms_diff.to(diff.dtype)


class SharedFormEncoder(nn.Module):
    def __init__(self, vocab_size: int = VOCAB_SIZE, d_model: int = D_MODEL) -> None:
        super().__init__()
        self.tok_emb = nn.Embedding(vocab_size, d_model, padding_idx=0)
        self.pos_emb = nn.Embedding(MAX_SEQ_LEN, d_model)
        self.tag_emb = nn.Embedding(8, d_model)
        self.in_norm = SafeLayerNorm(d_model)
        self.layers = nn.ModuleList([
            FastPreLNTransformerBlock(d_model=d_model, nhead=N_HEADS, dim_ff=1024, dropout=0.1)
            for _ in range(N_ENC_LAYERS)
        ])
        self.latent_proj = nn.Linear(d_model * 2, d_model)

    def forward(self, input_ids: torch.Tensor, tag_ids: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        bsz, seqlen = input_ids.shape
        pos = torch.arange(seqlen, device=input_ids.device).unsqueeze(0).expand(bsz, seqlen)
        pad_mask = input_ids == 0
        h = self.in_norm(self.tok_emb(input_ids) + self.pos_emb(pos) + self.tag_emb(tag_ids))
        for blk in self.layers:
            h = blk(h, pad_mask)
        cls_s = h[:, 0, :]
        valid_f = (~pad_mask).float().unsqueeze(-1)
        mean_s = ((h.float() * valid_f).sum(dim=1) / valid_f.sum(dim=1).clamp(min=1.0)).to(h.dtype)
        z = self.latent_proj(torch.cat([cls_s, mean_s], dim=-1))
        return h, z


class FormEBMv2(nn.Module):
    """
    Siamese Bi-Encoder + Cross-Difference Scalar Energy Scorer E_omega(ref, cand) >= 0.
    """

    def __init__(self, vocab_size: int = VOCAB_SIZE) -> None:
        super().__init__()
        self.encoder = SharedFormEncoder(vocab_size=vocab_size, d_model=D_MODEL)
        self.cross_diff = CrossDifferenceBlock(d_model=D_MODEL, nhead=N_HEADS, dim_ff=512, dropout=0.1)
        self.rule_emb = nn.Embedding(len(RULE_CODES), D_RULE)
        feat_dim = D_MODEL * 7 + D_RULE  # 1856
        self.energy_mlp = nn.Sequential(
            SafeLayerNorm(feat_dim),
            nn.Linear(feat_dim, 320),
            nn.GELU(),
            nn.Dropout(0.1),
            nn.Linear(320, 160),
            nn.GELU(),
            nn.Linear(160, 1),
        )

    def forward(
        self,
        ref_ids: torch.Tensor,
        ref_tags: torch.Tensor,
        cand_ids: torch.Tensor,
        cand_tags: torch.Tensor,
        rule_ids: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        h_ref, z_ref = self.encoder(ref_ids, ref_tags)
        h_cand, z_cand = self.encoder(cand_ids, cand_tags)
        mean_d, max_d = self.cross_diff(h_cand, h_ref, cand_ids == 0, ref_ids == 0)
        e_r = self.rule_emb(rule_ids)
        dz = z_cand - z_ref
        feats = torch.cat([z_ref, z_cand, dz, dz.abs(), z_ref * z_cand, mean_d, max_d, e_r], dim=-1)
        raw_e = self.energy_mlp(feats).squeeze(-1)
        energy = F.softplus(raw_e)
        return energy, z_ref, z_cand

    def score_group(
        self,
        ref_ids_1: torch.Tensor,
        ref_tags_1: torch.Tensor,
        cand_ids_k: torch.Tensor,
        cand_tags_k: torch.Tensor,
        rule_id_1: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Encode single reference once and score K candidates against it."""
        dev = next(self.parameters()).device
        ref_ids_1 = ref_ids_1.to(dev)
        ref_tags_1 = ref_tags_1.to(dev)
        cand_ids_k = cand_ids_k.to(dev)
        cand_tags_k = cand_tags_k.to(dev)
        rule_id_1 = rule_id_1.to(dev)
        k = cand_ids_k.size(0)
        h_ref, z_ref = self.encoder(ref_ids_1, ref_tags_1)
        h_cand, z_cand = self.encoder(cand_ids_k, cand_tags_k)
        h_ref_rep = h_ref.expand(k, -1, -1)
        z_ref_rep = z_ref.expand(k, -1)
        r_pad_rep = (ref_ids_1 == 0).expand(k, -1)
        mean_d, max_d = self.cross_diff(h_cand, h_ref_rep, cand_ids_k == 0, r_pad_rep)
        e_r = self.rule_emb(rule_id_1).expand(k, -1)
        dz = z_cand - z_ref_rep
        feats = torch.cat([z_ref_rep, z_cand, dz, dz.abs(), z_ref_rep * z_cand, mean_d, max_d, e_r], dim=-1)
        energy = F.softplus(self.energy_mlp(feats).squeeze(-1))
        return energy, z_ref, z_cand

    def trainable_param_count(self) -> int:
        return sum(p.numel() for p in self.parameters() if p.requires_grad)


def vicreg_var_cov_loss(z: torch.Tensor, gamma: float = 1.0) -> tuple[torch.Tensor, torch.Tensor]:
    z = z.float()
    bsz, dim = z.shape
    if bsz < 4:
        zero = torch.zeros((), device=z.device)
        return zero, zero
    zc = z - z.mean(dim=0, keepdim=True)
    std = torch.sqrt(zc.var(dim=0, unbiased=False) + 1e-4)
    var_loss = F.relu(gamma - std).mean()
    cov = (zc.T @ zc) / max(1, bsz - 1)
    off_diag = cov.pow(2).sum() - cov.diagonal().pow(2).sum()
    return var_loss, off_diag / dim


# ============================================================================
# Metrics: AUROC, ROC Curve, Spearman Rho, Spectrum Effective Rank
# ============================================================================

def compute_auroc_and_roc(scores_higher_is_pos: list[float], labels: list[int], n_curve_pts: int = 25) -> tuple[float, list[list[float]]]:
    pos = [s for s, y in zip(scores_higher_is_pos, labels) if y == 1]
    neg = [s for s, y in zip(scores_higher_is_pos, labels) if y == 0]
    if not pos or not neg:
        return 0.5, [[0.0, 0.0], [1.0, 1.0]]
    pos_arr = np.array(pos, dtype=np.float64)
    neg_arr = np.array(neg, dtype=np.float64)
    # Exact vectorized Mann-Whitney U statistic
    gt = (pos_arr[:, None] > neg_arr[None, :]).sum()
    eq = (pos_arr[:, None] == neg_arr[None, :]).sum()
    auroc = float((gt + 0.5 * eq) / (len(pos) * len(neg)))

    all_s = np.sort(np.unique(np.concatenate([pos_arr, neg_arr])))
    if len(all_s) > n_curve_pts - 2:
        idxs = np.linspace(0, len(all_s) - 1, n_curve_pts - 2).astype(int)
        thresh = all_s[idxs][::-1]
    else:
        thresh = all_s[::-1]
    curve = [[0.0, 0.0]]
    for th in thresh:
        tpr = float((pos_arr >= th).mean())
        fpr = float((neg_arr >= th).mean())
        curve.append([round(fpr, 4), round(tpr, 4)])
    curve.append([1.0, 1.0])
    return round(auroc, 4), curve


def spearman_rho_6(vals: list[float]) -> float:
    """Exact Spearman rank correlation with [0, 1, 2, 3, 4, 5] handling ties via average rank."""
    arr = np.asarray(vals, dtype=np.float64)
    order = np.argsort(arr)
    ranks = np.empty_like(arr)
    i = 0
    n = len(arr)
    while i < n:
        j = i
        while j + 1 < n and abs(arr[order[j + 1]] - arr[order[i]]) <= 1e-9:
            j += 1
        avg_r = 0.5 * (i + j)
        for k in range(i, j + 1):
            ranks[order[k]] = avg_r
        i = j + 1
    x = np.arange(n, dtype=np.float64)
    x_c = x - x.mean()
    r_c = ranks - ranks.mean()
    denom = float(np.sqrt((x_c ** 2).sum() * (r_c ** 2).sum()))
    if denom < 1e-12:
        return 0.0
    return float((x_c * r_c).sum() / denom)


def erank_and_std(mat: torch.Tensor) -> tuple[float, float]:
    c = mat.float() - mat.float().mean(dim=0, keepdim=True)
    std_m = float(c.std(dim=0, unbiased=False).mean().item())
    sv = torch.linalg.svdvals(c)
    p = sv / sv.sum().clamp(min=1e-12)
    ent = -(p * torch.log(p.clamp(min=1e-12))).sum().item()
    return round(float(math.exp(ent)), 3), round(std_m, 4)


# ============================================================================
# Tensorization for Contrastive Validity Groups & 5-Step Chains
# ============================================================================

def build_validity_pair_tensors(
    beams: list[dict[str, Any]],
    tok: PairFormTokenizer,
    max_neg_per_beam: int = 3,
    seed: int = MODEL_SEED,
) -> dict[str, torch.Tensor]:
    """Build `(ref_ids, ref_tags, pos_ids, pos_tags, neg_ids, neg_tags, rule_id)` tensors."""
    rng = SplitMix64(seed)
    rows_r_id, rows_r_tg = [], []
    rows_p_id, rows_p_tg = [], []
    rows_n_id, rows_n_tg = [], []
    rows_rule = []

    for bm in beams:
        pos_cands = [c for c in bm["candidates"] if c["admitted"]]
        neg_cands = [c for c in bm["candidates"] if not c["admitted"]]
        if not pos_cands or not neg_cands:
            continue
        rc = bm["checker_rule_code"]
        dl = bm["diag_line"]
        rid = RULE_TO_ID.get(rc, RULE_TO_ID["UNK_RULE"])
        rng.shuffle(neg_cands)
        chosen_pos = pos_cands[0]
        r_i, r_t, p_i, p_t = tok.encode_pair(bm["broken_form"], chosen_pos["text"], rule_code=rc, diag_line_1based=dl)
        for nc in neg_cands[:max_neg_per_beam]:
            _, _, n_i, n_t = tok.encode_pair(bm["broken_form"], nc["text"], rule_code=rc, diag_line_1based=dl)
            rows_r_id.append(r_i)
            rows_r_tg.append(r_t)
            rows_p_id.append(p_i)
            rows_p_tg.append(p_t)
            rows_n_id.append(n_i)
            rows_n_tg.append(n_t)
            rows_rule.append(rid)

    return {
        "ref_ids": torch.tensor(rows_r_id, dtype=torch.long),
        "ref_tags": torch.tensor(rows_r_tg, dtype=torch.long),
        "pos_ids": torch.tensor(rows_p_id, dtype=torch.long),
        "pos_tags": torch.tensor(rows_p_tg, dtype=torch.long),
        "neg_ids": torch.tensor(rows_n_id, dtype=torch.long),
        "neg_tags": torch.tensor(rows_n_tg, dtype=torch.long),
        "rule_ids": torch.tensor(rows_rule, dtype=torch.long),
    }


def build_chain_tensors(chains: list[dict[str, Any]], tok: PairFormTokenizer) -> dict[str, torch.Tensor]:
    """Build `[N, 6, MAX_SEQ_LEN]` tensors for 5-step edit chains `d = 0..5`."""
    n = len(chains)
    r_ids = torch.zeros((n, MAX_SEQ_LEN), dtype=torch.long)
    r_tags = torch.zeros((n, MAX_SEQ_LEN), dtype=torch.long)
    c_ids = torch.zeros((n, 6, MAX_SEQ_LEN), dtype=torch.long)
    c_tags = torch.zeros((n, 6, MAX_SEQ_LEN), dtype=torch.long)
    for idx, ch in enumerate(chains):
        y0 = ch["chain"][0]
        for d in range(6):
            ri, rt, ci, ct = tok.encode_pair(y0, ch["chain"][d], rule_code="OK", diag_line_1based=None)
            if d == 0:
                r_ids[idx] = torch.tensor(ri, dtype=torch.long)
                r_tags[idx] = torch.tensor(rt, dtype=torch.long)
            c_ids[idx, d] = torch.tensor(ci, dtype=torch.long)
            c_tags[idx, d] = torch.tensor(ct, dtype=torch.long)
    return {"ref_ids": r_ids, "ref_tags": r_tags, "cand_ids": c_ids, "cand_tags": c_tags}


@torch.no_grad()
def compute_val_spectrum_and_metrics(
    model: FormEBMv2,
    val_beams: list[dict[str, Any]],
    val_chains: list[dict[str, Any]],
    tok: PairFormTokenizer,
) -> dict[str, Any]:
    model.eval()
    z_refs, z_cands = [], []
    scores_ebm, labels = [], []
    for bm in val_beams:
        rc = bm["checker_rule_code"]
        dl = bm["diag_line"]
        rid = torch.tensor([RULE_TO_ID.get(rc, RULE_TO_ID["UNK_RULE"])], dtype=torch.long)
        c_i_list, c_t_list = [], []
        r_i0, r_t0 = None, None
        for c in bm["candidates"]:
            ri, rt, ci, ct = tok.encode_pair(bm["broken_form"], c["text"], rule_code=rc, diag_line_1based=dl)
            if r_i0 is None:
                r_i0, r_t0 = ri, rt
            c_i_list.append(ci)
            c_t_list.append(ct)
            labels.append(1 if c["admitted"] else 0)
        assert r_i0 is not None and r_t0 is not None
        r_ids = torch.tensor([r_i0], dtype=torch.long)
        r_tgs = torch.tensor([r_t0], dtype=torch.long)
        c_ids = torch.tensor(c_i_list, dtype=torch.long)
        c_tgs = torch.tensor(c_t_list, dtype=torch.long)
        lr = max(16, int((r_ids != 0).sum().item()))
        lc = max(16, int((c_ids != 0).sum(dim=1).max().item()))
        en, zr, zc = model.score_group(r_ids[:, :lr], r_tgs[:, :lr], c_ids[:, :lc], c_tgs[:, :lc], rid)
        scores_ebm.extend((-en).float().cpu().tolist())
        z_refs.append(zr.cpu())
        z_cands.append(zc[:2].cpu())

    auroc_val, _ = compute_auroc_and_roc(scores_ebm, labels)

    # Validation 5-step strict monotonicity
    mono_cnt = 0
    ok_id = torch.tensor([RULE_TO_ID["OK"]], dtype=torch.long)
    for ch in val_chains:
        y0 = ch["chain"][0]
        c_i_l, c_t_l = [], []
        r_i0, r_t0 = None, None
        for d in range(6):
            ri, rt, ci, ct = tok.encode_pair(y0, ch["chain"][d], rule_code="OK", diag_line_1based=None)
            if d == 0:
                r_i0, r_t0 = ri, rt
            c_i_l.append(ci)
            c_t_l.append(ct)
        assert r_i0 is not None and r_t0 is not None
        r_ids = torch.tensor([r_i0], dtype=torch.long)
        r_tgs = torch.tensor([r_t0], dtype=torch.long)
        c_ids = torch.tensor(c_i_l, dtype=torch.long)
        c_tgs = torch.tensor(c_t_l, dtype=torch.long)
        lr = max(16, int((r_ids != 0).sum().item()))
        lc = max(16, int((c_ids != 0).sum(dim=1).max().item()))
        en, _, _ = model.score_group(r_ids[:, :lr], r_tgs[:, :lr], c_ids[:, :lc], c_tgs[:, :lc], ok_id)
        ev = en.float().cpu().tolist()
        if all(ev[k] < ev[k + 1] for k in range(5)):
            mono_cnt += 1

    zr_mat = torch.cat(z_refs, dim=0)
    zc_mat = torch.cat(z_cands, dim=0)
    er_r, std_r = erank_and_std(zr_mat)
    er_c, std_c = erank_and_std(zc_mat)
    return {
        "val_h5_auroc": auroc_val,
        "val_h11_strict_mono": round(mono_cnt / max(1, len(val_chains)), 4),
        "effective_rank_z_ref": er_r,
        "effective_rank_z_cand": er_c,
        "mean_coord_std_z_ref": std_r,
        "mean_coord_std_z_cand": std_c,
    }


# ============================================================================
# RAPL Inference Microbenchmark (Falsifier 6 Pre/Post Idle Drift Guard)
# ============================================================================

@torch.no_grad()
def benchmark_rapl_ebm_scoring(
    model: FormEBMv2,
    tok: PairFormTokenizer,
    sample_beams: list[dict[str, Any]],
) -> dict[str, Any]:
    model.eval()
    idle_pre_0 = read_rapl_uj()
    t_i0 = time.perf_counter()
    time.sleep(1.5)
    dt_pre = time.perf_counter() - t_i0
    idle_pre_1 = read_rapl_uj()
    j_pre = delta_rapl_j(idle_pre_0, idle_pre_1, "package_uj")
    w_pre = (j_pre / dt_pre) if j_pre is not None else None

    # Pre-encode 16-candidate beam scoring workloads & Measure full (tokenize + forward) per-beam cost
    n_iters = 160
    bm0 = sample_beams[0]

    def _score_one_beam(bm: dict[str, Any]) -> None:
        rc = bm["checker_rule_code"]
        dl = bm["diag_line"]
        rid = torch.tensor([RULE_TO_ID.get(rc, RULE_TO_ID["UNK_RULE"])], dtype=torch.long)
        c_i, c_t = [], []
        r_i0, r_t0 = None, None
        for c in bm["candidates"]:
            ri, rt, ci, ct = tok.encode_pair(bm["broken_form"], c["text"], rule_code=rc, diag_line_1based=dl)
            if r_i0 is None:
                r_i0, r_t0 = ri, rt
            c_i.append(ci)
            c_t.append(ct)
        assert r_i0 is not None and r_t0 is not None
        r_ids = torch.tensor([r_i0], dtype=torch.long)
        r_tgs = torch.tensor([r_t0], dtype=torch.long)
        c_ids = torch.tensor(c_i, dtype=torch.long)
        c_tgs = torch.tensor(c_t, dtype=torch.long)
        lr = max(16, int((r_ids != 0).sum().item()))
        lc = max(16, int((c_ids != 0).sum(dim=1).max().item()))
        model.score_group(r_ids[:, :lr], r_tgs[:, :lr], c_ids[:, :lc], c_tgs[:, :lc], rid)

    _score_one_beam(bm0)
    r0 = read_rapl_uj()
    t0 = time.perf_counter()
    tot_cands = 0
    for i in range(n_iters):
        bm = sample_beams[i % len(sample_beams)]
        _score_one_beam(bm)
        tot_cands += len(bm["candidates"])
    dt = time.perf_counter() - t0
    r1 = read_rapl_uj()
    pkg_j = delta_rapl_j(r0, r1, "package_uj")
    core_j = delta_rapl_j(r0, r1, "core_uj")

    idle_post_0 = read_rapl_uj()
    t_i1 = time.perf_counter()
    time.sleep(1.5)
    dt_post = time.perf_counter() - t_i1
    idle_post_1 = read_rapl_uj()
    j_post = delta_rapl_j(idle_post_0, idle_post_1, "package_uj")
    w_post = (j_post / dt_post) if j_post is not None else None

    drift = round(abs(w_post - w_pre) / w_pre, 4) if (w_pre and w_post and w_pre > 0) else None
    f6_pass = bool(drift is not None and drift <= 0.10)
    marg_per_beam = None
    if f6_pass and w_pre is not None and pkg_j is not None:
        idle_mean = 0.5 * (w_pre + (w_post or w_pre))
        marg_per_beam = round(max(0.0, pkg_j - idle_mean * dt) / n_iters, 6)

    return {
        "beam_rerank_iterations": n_iters,
        "candidates_scored_total": tot_cands,
        "wall_s": round(dt, 4),
        "mean_beam_rerank_latency_ms": round((dt * 1000.0) / n_iters, 3),
        "mean_per_candidate_latency_ms": round((dt * 1000.0) / max(1, tot_cands), 3),
        "gross_rapl_pkg_reported_j_per_beam": round(pkg_j / n_iters, 6) if pkg_j is not None else None,
        "gross_rapl_core_reported_j_per_beam": round(core_j / n_iters, 6) if core_j is not None else None,
        "gross_rapl_core_reported_j_per_candidate": round(core_j / max(1, tot_cands), 6) if core_j is not None else None,
        "derived_marginal_pkg_reported_j_per_beam": marg_per_beam,
        "idle_baseline_check": {
            "idle_pre_w": round(w_pre, 3) if w_pre is not None else None,
            "idle_post_w": round(w_post, 3) if w_post is not None else None,
            "idle_drift_fraction": drift,
            "falsifier_6_threshold_le": 0.10,
            "falsifier_6_passed": f6_pass,
            "measured_j": None,
            "est_j": None,
            "board_metered": False,
        },
    }


# ============================================================================
# Main Training & Evaluation Pipeline
# ============================================================================

def main() -> None:
    set_all_seeds(MODEL_SEED)
    torch.set_num_threads(10)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Verify PREREG_form_ebm_v2.json SHA-256
    prereg_bytes = PREREG_PATH.read_bytes()
    actual_sha = sha256_bytes(prereg_bytes)
    pinned_sha = PREREG_SHA_PATH.read_text(encoding="utf-8").split()[0]
    if actual_sha != pinned_sha:
        raise RuntimeError(f"PREREG_form_ebm_v2 SHA-256 mismatch: {actual_sha} != {pinned_sha}")
    prereg = json.loads(prereg_bytes.decode("utf-8"))
    print(f"[FormEBM-v2] Pre-registration verified: {actual_sha[:16]}...")

    tasks_151_path = WORK_DIR / "tasks_151.jsonl"
    if not tasks_151_path.exists():
        frozen_py = EXP_REPO / "rce/bench/ladder/rung-e/frozen.py"
        tsv_path = EXP_REPO / "rce/bench/ladder/real-defects/tasks.list.tsv"
        subprocess.run(
            ["python3", "-I", str(frozen_py), str(RCE_REPO), str(tsv_path), str(tasks_151_path)],
            check=True,
        )
    residual_40_path = EXP_REPO / "rce/bench/h15-gear0/residual_40_tasks.jsonl"
    forms_jsonl_path = EXP_REPO / "rce/bench/form-space/results/forms.jsonl"

    sha_151 = sha256_bytes(tasks_151_path.read_bytes())
    sha_40 = sha256_bytes(residual_40_path.read_bytes())
    exp_151 = prereg["data_and_leakage_controls"]["forbidden_corpora"]["ladder_151_sha256"]
    exp_40 = prereg["data_and_leakage_controls"]["forbidden_corpora"]["h15_residual_40_sha256"]
    if sha_151 != exp_151 or sha_40 != exp_40:
        raise RuntimeError(f"Forbidden corpora SHA mismatch: 151={sha_151}, 40={sha_40}")

    # 2. Extract exact 1,387 disjoint Forms (`0` overlap) & apply exact `shape_hash[:16] % 10` split
    t_c0 = time.perf_counter()
    stdlib_cat = build_stdlib_catalog(RCE_REPO)
    disjoint_forms, leakage_audit = build_disjoint_form_pool(
        RCE_BIN, RCE_REPO, tasks_151_path, residual_40_path, forms_jsonl_path, workers=10
    )
    train_forms, val_forms, test_forms = [], [], []
    for f in disjoint_forms:
        b = int(f["shape_hash"][:16], 16) % 10
        if b < 8:
            train_forms.append(f)
        elif b == 8:
            val_forms.append(f)
        else:
            test_forms.append(f)

    # Verify strict Form-level disjointness (Falsifier F2)
    if (
        {f["shape_hash"] for f in train_forms} & {f["shape_hash"] for f in test_forms}
        or {f["shape_hash"] for f in val_forms} & {f["shape_hash"] for f in test_forms}
    ):
        raise RuntimeError("Falsifier F2: split overlap detected")
    print(
        f"[FormEBM-v2] Disjoint split verified: total={len(disjoint_forms)} "
        f"(train={len(train_forms)}, val={len(val_forms)}, test={len(test_forms)}, overlap=0)"
    )

    # 3. Generate defect tasks, candidate beams, and 5-step corruption chains strictly per split
    def _gen_defects(forms_slice: list[dict[str, Any]], max_per: int, offset: int) -> list[dict[str, Any]]:
        args = [(str(RCE_BIN), f, stdlib_cat, offset + idx, max_per) for idx, f in enumerate(forms_slice)]
        out: list[dict[str, Any]] = []
        with concurrent.futures.ProcessPoolExecutor(max_workers=10) as ex:
            for batch in ex.map(_verify_defect_worker, args, chunksize=4):
                out.extend(batch)
        return out

    raw_train_defects = _gen_defects(train_forms, max_per=10, offset=0)
    raw_val_defects = _gen_defects(val_forms, max_per=12, offset=100_000)
    raw_test_defects = _gen_defects(test_forms, max_per=14, offset=200_000)

    rng_corpus = SplitMix64(CORPUS_SEED)
    rng_corpus.shuffle(raw_train_defects)
    rng_corpus.shuffle(raw_val_defects)
    rng_corpus.shuffle(raw_test_defects)

    train_defect_slice = raw_train_defects[:1400]
    val_defect_slice = raw_val_defects[:140]
    test_200_slice = raw_test_defects[:200]

    def _build_beams(defects: list[dict[str, Any]]) -> list[dict[str, Any]]:
        args = [(str(RCE_BIN), d, stdlib_cat) for d in defects]
        with concurrent.futures.ProcessPoolExecutor(max_workers=10) as ex:
            return [r for r in ex.map(_label_beam_worker, args, chunksize=8) if r is not None]

    train_beams = _build_beams(train_defect_slice)
    val_beams = _build_beams(val_defect_slice)[:120]
    test_200_beams = _build_beams(test_200_slice)

    def _build_chains(forms_slice: list[dict[str, Any]], target_n: int, seed_base: int) -> list[dict[str, Any]]:
        candidates_args = []
        reps = math.ceil((target_n * 3.5) / max(1, len(forms_slice)))
        for r_i in range(reps):
            for idx_f, f in enumerate(forms_slice):
                candidates_args.append((str(RCE_BIN), f, stdlib_cat, seed_base + r_i * 10000 + idx_f))
        out_chains: list[dict[str, Any]] = []
        with concurrent.futures.ProcessPoolExecutor(max_workers=10) as ex:
            for ch in ex.map(_build_5step_chain_worker, candidates_args, chunksize=6):
                if ch is not None:
                    out_chains.append(ch)
                    if len(out_chains) >= target_n:
                        break
        return out_chains[:target_n]

    train_chains = _build_chains(train_forms, target_n=600, seed_base=10_000)
    val_chains = _build_chains(val_forms, target_n=60, seed_base=500_000)
    test_100_chains = _build_chains(test_forms, target_n=100, seed_base=900_000)

    corpus_wall_s = round(time.perf_counter() - t_c0, 2)
    print(
        f"[FormEBM-v2] Built datasets in {corpus_wall_s}s: "
        f"train_beams={len(train_beams)}, val_beams={len(val_beams)}, test_beams={len(test_200_beams)} | "
        f"train_chains={len(train_chains)}, val_chains={len(val_chains)}, test_chains={len(test_100_chains)}"
    )

    tok = PairFormTokenizer(stdlib_cat["ordered_mods"])
    train_chain_tensors = build_chain_tensors(train_chains, tok)
    tpairs = build_validity_pair_tensors(train_beams, tok, max_neg_per_beam=5, seed=MODEL_SEED)

    # 4. Initialize FormEBM-v2 on accelerator (`cuda` ROCm Radeon 8060S if available, else `cpu`)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    set_all_seeds(MODEL_SEED)
    model = FormEBMv2(vocab_size=VOCAB_SIZE).to(device)
    n_params = model.trainable_param_count()
    if not (4_000_000 <= n_params <= 6_000_000):
        raise RuntimeError(f"Parameter count {n_params} outside pre-registered [4M, 6M] target")
    print(
        f"[FormEBM-v2] Initialized FormEBM-v2 on {device}: trainable_params={n_params:,}, "
        f"vocab_used={len(tok.tok2id)}, train_val_pairs={tpairs['ref_ids'].size(0)}"
    )

    pre_metrics = compute_val_spectrum_and_metrics(model, val_beams, val_chains, tok)
    print(f"[FormEBM-v2] Epoch 0 (untrained) validation metrics: {pre_metrics}")

    # 5. Train FormEBM-v2 (<6 min, recording AMD RAPL reported_j)
    epochs = 10
    val_bsz = 112
    chain_bsz = 24
    lr = 6e-4
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-2, foreach=False)

    n_vpairs = tpairs["ref_ids"].size(0)
    n_tchains = train_chain_tensors["ref_ids"].size(0)
    steps_per_epoch = max(math.ceil(n_vpairs / val_bsz), math.ceil(n_tchains / chain_bsz))
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=epochs * steps_per_epoch, eta_min=2e-5
    )

    # Precompute pairwise index matrices i < j for d = 0..5 on device
    idx_i, idx_j = [], []
    margin_ij = []
    gamma_step = 0.50
    m_val = 1.0
    for i in range(6):
        for j in range(i + 1, 6):
            idx_i.append(i)
            idx_j.append(j)
            margin_ij.append(gamma_step * (j - i))
    t_idx_i = torch.tensor(idx_i, dtype=torch.long, device=device)
    t_idx_j = torch.tensor(idx_j, dtype=torch.long, device=device)
    t_margin_ij = torch.tensor(margin_ij, dtype=torch.float32, device=device).unsqueeze(0)

    tpairs_dev = {k: v.to(device) for k, v in tpairs.items()}
    chains_dev = {k: v.to(device) for k, v in train_chain_tensors.items()}

    if device.type == "cuda":
        torch.cuda.synchronize()
    rapl_train_start = read_rapl_uj()
    t_train0 = time.perf_counter()
    epoch_history: list[dict[str, Any]] = []
    best_val_obj = -1e9
    best_state: dict[str, torch.Tensor] | None = None

    for ep in range(1, epochs + 1):
        model.train()
        perm_v = torch.randperm(n_vpairs, device=device)
        perm_c = torch.randperm(n_tchains, device=device)

        sum_lval, sum_lrank, sum_lvic = 0.0, 0.0, 0.0
        for st in range(steps_per_epoch):
            v_sl = perm_v[(st * val_bsz) % n_vpairs : ((st * val_bsz) % n_vpairs) + val_bsz]
            if v_sl.numel() < 16:
                v_sl = perm_v[:val_bsz]
            c_sl = perm_c[(st * chain_bsz) % n_tchains : ((st * chain_bsz) % n_tchains) + chain_bsz]
            if c_sl.numel() < 4:
                c_sl = perm_c[:chain_bsz]

            optimizer.zero_grad(set_to_none=True)

            with torch.amp.autocast(device.type, dtype=torch.bfloat16, enabled=(device.type == "cuda")):
                # A. Contrastive Validity Margin Loss: max(0, m_val + E(x, y^+) - E(x, y^-))
                r_full = tpairs_dev["ref_ids"][v_sl]
                p_full = tpairs_dev["pos_ids"][v_sl]
                n_full = tpairs_dev["neg_ids"][v_sl]
                lr_v = max(16, int((r_full != 0).sum(dim=1).max().item()))
                lc_v = max(
                    16,
                    max(
                        int((p_full != 0).sum(dim=1).max().item()),
                        int((n_full != 0).sum(dim=1).max().item()),
                    ),
                )
                r_ids_v = r_full[:, :lr_v]
                r_tgs_v = tpairs_dev["ref_tags"][v_sl][:, :lr_v]
                p_ids_v = p_full[:, :lc_v]
                p_tgs_v = tpairs_dev["pos_tags"][v_sl][:, :lc_v]
                n_ids_v = n_full[:, :lc_v]
                n_tgs_v = tpairs_dev["neg_tags"][v_sl][:, :lc_v]
                rul_v = tpairs_dev["rule_ids"][v_sl]

                # Encode reference x once for both y^+ and y^-
                h_rx, z_rx = model.encoder(r_ids_v, r_tgs_v)
                pn_ids = torch.cat([p_ids_v, n_ids_v], dim=0)
                pn_tgs = torch.cat([p_tgs_v, n_tgs_v], dim=0)
                h_pn, z_pn = model.encoder(pn_ids, pn_tgs)

                h_rx2 = h_rx.repeat(2, 1, 1)
                z_rx2 = z_rx.repeat(2, 1)
                rpad2 = (r_ids_v == 0).repeat(2, 1)
                md_pn, mxd_pn = model.cross_diff(h_pn, h_rx2, pn_ids == 0, rpad2)
                er2 = model.rule_emb(rul_v).repeat(2, 1)
                dz_pn = z_pn - z_rx2
                feats_pn = torch.cat([z_rx2, z_pn, dz_pn, dz_pn.abs(), z_rx2 * z_pn, md_pn, mxd_pn, er2], dim=-1)
                e_pn = F.softplus(model.energy_mlp(feats_pn).float().squeeze(-1))
                bsz_v = r_ids_v.size(0)
                e_pos, e_neg = e_pn[:bsz_v], e_pn[bsz_v:]
                loss_val = F.relu(m_val + e_pos - e_neg).mean()

                # B. Pairwise Multi-Step Edit-Depth Ranking Loss: sum_{0<=i<j<=5} max(0, gamma*(j-i) + E(y0, yi) - E(y0, yj))
                cr_full = chains_dev["ref_ids"][c_sl]
                cc_full = chains_dev["cand_ids"][c_sl]  # [B_c, 6, L]
                bc = cr_full.size(0)
                lr_c = max(16, int((cr_full != 0).sum(dim=1).max().item()))
                lc_c = max(16, int((cc_full.view(bc * 6, -1) != 0).sum(dim=1).max().item()))

                cr_ids = cr_full[:, :lr_c]
                cr_tgs = chains_dev["ref_tags"][c_sl][:, :lr_c]
                cc_ids = cc_full[:, :, :lc_c].reshape(bc * 6, lc_c)
                cc_tgs = chains_dev["cand_tags"][c_sl][:, :, :lc_c].reshape(bc * 6, lc_c)

                h_y0, z_y0 = model.encoder(cr_ids, cr_tgs)
                h_yd, z_yd = model.encoder(cc_ids, cc_tgs)

                h_y0_rep = h_y0.repeat_interleave(6, dim=0)
                z_y0_rep = z_y0.repeat_interleave(6, dim=0)
                cpad_rep = (cr_ids == 0).repeat_interleave(6, dim=0)
                md_c, mxd_c = model.cross_diff(h_yd, h_y0_rep, cc_ids == 0, cpad_rep)
                ok_rul = torch.zeros((bc * 6,), dtype=torch.long, device=device)
                er_c = model.rule_emb(ok_rul)
                dz_c = z_yd - z_y0_rep
                feats_c = torch.cat([z_y0_rep, z_yd, dz_c, dz_c.abs(), z_y0_rep * z_yd, md_c, mxd_c, er_c], dim=-1)
                e_chain = F.softplus(model.energy_mlp(feats_c).float().squeeze(-1)).view(bc, 6)

                ei = e_chain[:, t_idx_i]
                ej = e_chain[:, t_idx_j]
                loss_rank = F.relu(t_margin_ij + ei - ej).mean() + 0.10 * (e_chain[:, 0].pow(2).mean())

                # C. Anti-collapse VICReg regularizer
                z_all = torch.cat([z_rx.float(), z_pn.float(), z_y0.float()], dim=0)
                v_l, c_l = vicreg_var_cov_loss(z_all)
                loss_vic = 0.25 * v_l + 0.01 * c_l

                total_loss = loss_val + loss_rank + loss_vic

            total_loss.backward()
            grads = [p.grad for p in model.parameters() if p.grad is not None]
            tot_sq = torch.zeros((), device=device, dtype=torch.float32)
            for g in grads:
                tot_sq = tot_sq + g.detach().float().pow(2).sum()
            clip_coef = (1.0 / (torch.sqrt(tot_sq) + 1e-6)).clamp(max=1.0)
            for g in grads:
                g.mul_(clip_coef)
            optimizer.step()
            scheduler.step()

            sum_lval += float(loss_val.item())
            sum_lrank += float(loss_rank.item())
            sum_lvic += float(loss_vic.item())

        v_metrics = compute_val_spectrum_and_metrics(model, val_beams, val_chains, tok)
        val_obj = v_metrics["val_h5_auroc"] + 0.5 * v_metrics["val_h11_strict_mono"]
        if val_obj > best_val_obj:
            best_val_obj = val_obj
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}

        ep_row = {
            "epoch": ep,
            "train_validity_margin_loss": round(sum_lval / steps_per_epoch, 4),
            "train_edit_rank_loss": round(sum_lrank / steps_per_epoch, 4),
            "train_vicreg_loss": round(sum_lvic / steps_per_epoch, 4),
            **v_metrics,
        }
        epoch_history.append(ep_row)
        print(
            f"  [ep {ep:02d}/{epochs}] l_val={ep_row['train_validity_margin_loss']:.4f} "
            f"l_rank={ep_row['train_edit_rank_loss']:.4f} | val_H5_auroc={v_metrics['val_h5_auroc']:.4f} "
            f"val_H11_mono={v_metrics['val_h11_strict_mono']:.3f} erank={v_metrics['effective_rank_z_ref']:.1f}"
        )

    if device.type == "cuda":
        torch.cuda.synchronize()
    train_wall_s = round(time.perf_counter() - t_train0, 3)
    rapl_train_end = read_rapl_uj()
    train_pkg_j = delta_rapl_j(rapl_train_start, rapl_train_end, "package_uj")
    train_core_j = delta_rapl_j(rapl_train_start, rapl_train_end, "core_uj")

    if best_state is not None:
        model.load_state_dict({k: v.to(device) for k, v in best_state.items()})
    model.eval()
    post_metrics = compute_val_spectrum_and_metrics(model, val_beams, val_chains, tok)
    f1_collapsed = (
        post_metrics["effective_rank_z_ref"] < 16.0
        or post_metrics["effective_rank_z_cand"] < 16.0
        or post_metrics["mean_coord_std_z_ref"] < 0.25
        or post_metrics["mean_coord_std_z_cand"] < 0.25
    )

    ckpt_path = WORK_DIR / "form_ebm_v2.pt"
    torch.save(
        {
            "arch": "FormEBM-v2",
            "seed": MODEL_SEED,
            "trainable_params": n_params,
            "state_dict": {k: v.detach().cpu() for k, v in model.state_dict().items()},
        },
        ckpt_path,
    )
    ckpt_sha = sha256_bytes(ckpt_path.read_bytes())
    print(f"[FormEBM-v2] Training complete in {train_wall_s}s (core RAPL={train_core_j} J, pkg RAPL={train_pkg_j} J)")

    # 6. CPU RAPL Inference Microbenchmark (10 threads, matching FormJEPA-v1 CPU RAPL protocol)
    model_cpu = FormEBMv2(vocab_size=VOCAB_SIZE)
    model_cpu.load_state_dict({k: v.detach().cpu() for k, v in model.state_dict().items()})
    model_cpu.eval()
    rapl_inf = benchmark_rapl_ebm_scoring(model_cpu, tok, test_200_beams[:32])
    del model_cpu
    print(f"[FormEBM-v2] RAPL inference bench: {rapl_inf}")

    # 7. Benchmark 1 — Held-Out Unseen Test Candidate Beams (`N = 200`, `137` Test Form Shapes) for `H5`
    h5_scores_ebm: list[float] = []
    h5_scores_l2: list[float] = []
    h5_labels: list[int] = []

    ebm_top1_valid = 0
    l2_top1_valid = 0
    unreranked_top1_valid = 0
    any_valid_in_beam = 0

    ebm_checks_on_solvable: list[int] = []
    unreranked_checks_on_solvable: list[int] = []
    l2_checks_on_solvable: list[int] = []
    ebm_total_checks_200 = 0
    unreranked_total_checks_200 = 0

    with torch.no_grad():
        for bm in test_200_beams:
            rc = bm["checker_rule_code"]
            dl = bm["diag_line"]
            rid = torch.tensor([RULE_TO_ID.get(rc, RULE_TO_ID["UNK_RULE"])], dtype=torch.long)
            c_i_l, c_t_l, adm_l = [], [], []
            r_i0, r_t0 = None, None
            for c in bm["candidates"]:
                ri, rt, ci, ct = tok.encode_pair(bm["broken_form"], c["text"], rule_code=rc, diag_line_1based=dl)
                if r_i0 is None:
                    r_i0, r_t0 = ri, rt
                c_i_l.append(ci)
                c_t_l.append(ct)
                adm_l.append(1 if c["admitted"] else 0)
            assert r_i0 is not None and r_t0 is not None
            r_ids = torch.tensor([r_i0], dtype=torch.long)
            r_tgs = torch.tensor([r_t0], dtype=torch.long)
            c_ids = torch.tensor(c_i_l, dtype=torch.long)
            c_tgs = torch.tensor(c_t_l, dtype=torch.long)
            lr_len = max(16, int((r_ids != 0).sum().item()))
            lc_len = max(16, int((c_ids != 0).sum(dim=1).max().item()))

            en, zr, zc = model.score_group(r_ids[:, :lr_len], r_tgs[:, :lr_len], c_ids[:, :lc_len], c_tgs[:, :lc_len], rid)
            e_list = en.float().cpu().tolist()
            l2_list = (zc.float() - zr.float()).pow(2).sum(dim=-1).cpu().tolist()

            h5_scores_ebm.extend([-x for x in e_list])
            h5_scores_l2.extend([-x for x in l2_list])
            h5_labels.extend(adm_l)

            has_valid = any(a == 1 for a in adm_l)
            if has_valid:
                any_valid_in_beam += 1

            # Unreranked order
            if adm_l[0] == 1:
                unreranked_top1_valid += 1
            chk_un = next((idx + 1 for idx, a in enumerate(adm_l) if a == 1), len(adm_l))
            unreranked_total_checks_200 += chk_un

            # Siamese uncalibrated L2 order
            ord_l2 = sorted(range(len(adm_l)), key=lambda i: l2_list[i])
            if adm_l[ord_l2[0]] == 1:
                l2_top1_valid += 1
            chk_l2 = next((rank + 1 for rank, i in enumerate(ord_l2) if adm_l[i] == 1), len(adm_l))

            # FormEBM-v2 scalar energy order (lowest E first)
            ord_ebm = sorted(range(len(adm_l)), key=lambda i: e_list[i])
            if adm_l[ord_ebm[0]] == 1:
                ebm_top1_valid += 1
            chk_ebm = next((rank + 1 for rank, i in enumerate(ord_ebm) if adm_l[i] == 1), len(adm_l))
            ebm_total_checks_200 += chk_ebm

            if has_valid:
                unreranked_checks_on_solvable.append(chk_un)
                l2_checks_on_solvable.append(chk_l2)
                ebm_checks_on_solvable.append(chk_ebm)

    h5_auroc_ebm, h5_roc_ebm = compute_auroc_and_roc(h5_scores_ebm, h5_labels)
    h5_auroc_l2, h5_roc_l2 = compute_auroc_and_roc(h5_scores_l2, h5_labels)
    n_test_bm = len(test_200_beams)

    h5_eval = {
        "beam_sets_N": n_test_bm,
        "total_candidates_scored": len(h5_labels),
        "accepted_candidates_total": sum(h5_labels),
        "solvable_beams_count": any_valid_in_beam,
        "auroc_form_ebm_v2": h5_auroc_ebm,
        "auroc_siamese_l2_uncalibrated": h5_auroc_l2,
        "auroc_wave3_form_jepa_v1_reference": 0.618,
        "h5_auroc_threshold_ge_0_85_met": h5_auroc_ebm >= 0.85,
        "top1_k1_valid_without_beam_checks": {
            "form_ebm_v2_admitted": ebm_top1_valid,
            "form_ebm_v2_rate_all_200": round(ebm_top1_valid / max(1, n_test_bm), 4),
            "form_ebm_v2_rate_on_solvable": round(ebm_top1_valid / max(1, any_valid_in_beam), 4),
            "siamese_l2_admitted": l2_top1_valid,
            "siamese_l2_rate_all_200": round(l2_top1_valid / max(1, n_test_bm), 4),
            "unreranked_admitted": unreranked_top1_valid,
            "unreranked_rate_all_200": round(unreranked_top1_valid / max(1, n_test_bm), 4),
        },
        "check_call_efficiency": {
            "mean_checks_per_task_all_200_form_ebm_v2": round(ebm_total_checks_200 / max(1, n_test_bm), 3),
            "mean_checks_per_task_all_200_unreranked": round(unreranked_total_checks_200 / max(1, n_test_bm), 3),
            "mean_checks_on_solvable_form_ebm_v2": round(float(np.mean(ebm_checks_on_solvable)), 3),
            "mean_checks_on_solvable_siamese_l2": round(float(np.mean(l2_checks_on_solvable)), 3),
            "mean_checks_on_solvable_unreranked": round(float(np.mean(unreranked_checks_on_solvable)), 3),
            "check_call_reduction_factor_on_solvable": round(
                float(np.mean(unreranked_checks_on_solvable)) / max(1e-9, float(np.mean(ebm_checks_on_solvable))), 3
            ),
        },
        "roc_curve_form_ebm_v2_fpr_tpr": h5_roc_ebm,
        "roc_curve_siamese_l2_fpr_tpr": h5_roc_l2,
    }
    print(
        f"[FormEBM-v2] H5 (N={n_test_bm} unseen test beams): AUROC={h5_auroc_ebm:.4f} "
        f"(vs Wave3 FormJEPA-v1 0.618, Siamese L2 {h5_auroc_l2:.4f}) | "
        f"top-1 k=1={ebm_top1_valid}/{n_test_bm} ({h5_eval['top1_k1_valid_without_beam_checks']['form_ebm_v2_rate_all_200']*100:.1f}%)"
    )

    # 8. Benchmark 2 — Unseen `N = 100` 5-Step Edit Chains (`137` Test Forms) for `H11`
    def _eval_chains_h11(chains_list: list[dict[str, Any]]) -> dict[str, Any]:
        strict_mono_ebm = 0
        nondec_mono_ebm = 0
        strict_mono_l2 = 0
        rhos_ebm: list[float] = []
        rhos_l2: list[float] = []
        by_d_ebm: list[list[float]] = [[] for _ in range(6)]
        by_d_l2: list[list[float]] = [[] for _ in range(6)]
        ok_id = torch.tensor([RULE_TO_ID["OK"]], dtype=torch.long)

        with torch.no_grad():
            for ch in chains_list:
                y0 = ch["chain"][0]
                c_i_l, c_t_l = [], []
                r_i0, r_t0 = None, None
                for d in range(6):
                    ri, rt, ci, ct = tok.encode_pair(y0, ch["chain"][d], rule_code="OK", diag_line_1based=None)
                    if d == 0:
                        r_i0, r_t0 = ri, rt
                    c_i_l.append(ci)
                    c_t_l.append(ct)
                assert r_i0 is not None and r_t0 is not None
                r_ids = torch.tensor([r_i0], dtype=torch.long)
                r_tgs = torch.tensor([r_t0], dtype=torch.long)
                c_ids = torch.tensor(c_i_l, dtype=torch.long)
                c_tgs = torch.tensor(c_t_l, dtype=torch.long)
                lr_l = max(16, int((r_ids != 0).sum().item()))
                lc_l = max(16, int((c_ids != 0).sum(dim=1).max().item()))
                en, zr, zc = model.score_group(r_ids[:, :lr_l], r_tgs[:, :lr_l], c_ids[:, :lc_l], c_tgs[:, :lc_l], ok_id)
                ev = en.float().cpu().tolist()
                lv = (zc.float() - zr.float()).pow(2).sum(dim=-1).cpu().tolist()

                for d in range(6):
                    by_d_ebm[d].append(ev[d])
                    by_d_l2[d].append(lv[d])
                if all(ev[k] < ev[k + 1] for k in range(5)):
                    strict_mono_ebm += 1
                if all(ev[k] <= ev[k + 1] + 1e-4 for k in range(5)) and ev[5] > ev[1]:
                    nondec_mono_ebm += 1
                if all(lv[k] < lv[k + 1] for k in range(5)):
                    strict_mono_l2 += 1
                rhos_ebm.append(spearman_rho_6(ev))
                rhos_l2.append(spearman_rho_6(lv))

        nc = max(1, len(chains_list))
        return {
            "chains_N": len(chains_list),
            "strict_5step_monotone_count": strict_mono_ebm,
            "strict_5step_monotone_rate": round(strict_mono_ebm / nc, 4),
            "nondecreasing_5step_monotone_rate": round(nondec_mono_ebm / nc, 4),
            "siamese_l2_strict_5step_monotone_rate": round(strict_mono_l2 / nc, 4),
            "wave3_form_jepa_v1_monotone_reference": 0.36,
            "h11_threshold_ge_0_80_met": (strict_mono_ebm / nc) >= 0.80,
            "mean_spearman_rho_form_ebm_v2": round(float(np.mean(rhos_ebm)), 4),
            "median_spearman_rho_form_ebm_v2": round(float(np.median(rhos_ebm)), 4),
            "mean_spearman_rho_siamese_l2": round(float(np.mean(rhos_l2)), 4),
            "mean_energy_by_distance_0_to_5": [round(float(np.mean(v)), 4) for v in by_d_ebm],
            "p25_energy_by_distance_0_to_5": [round(float(np.percentile(v, 25)), 4) for v in by_d_ebm],
            "p75_energy_by_distance_0_to_5": [round(float(np.percentile(v, 75)), 4) for v in by_d_ebm],
            "mean_siamese_l2_by_distance_0_to_5": [round(float(np.mean(v)), 4) for v in by_d_l2],
        }

    h11_eval_100 = _eval_chains_h11(test_100_chains)

    # Also evaluate exact Wave-3 unconstrained random-walk 50-chain construction for direct comparison
    rng_w3 = SplitMix64(CORPUS_SEED ^ 0x1111)
    unique_valid_w3 = list({ex["shape_hash"]: ex["valid_form"] for ex in test_200_slice}.values())[:50]
    w3_chains = []
    for vf in unique_valid_w3:
        cur = vf
        ch = [vf]
        for _ in range(1, 6):
            muts = _propose_forward_corruptions(cur, stdlib_cat, rng_w3, max_per_form=6)
            picked = next((m[0] for m in muts if m[0] not in ch), None)
            if picked is None:
                break
            cur = picked
            ch.append(cur)
        if len(ch) == 6:
            w3_chains.append({"chain": ch})
    h11_eval_w3_slice = _eval_chains_h11(w3_chains)

    print(
        f"[FormEBM-v2] H11 (N=100 unseen test 5-step chains): strict_mono={h11_eval_100['strict_5step_monotone_rate']*100:.1f}% "
        f"(rho={h11_eval_100['mean_spearman_rho_form_ebm_v2']:.4f}, E_0..5={h11_eval_100['mean_energy_by_distance_0_to_5']}) | "
        f"Wave3-style random-walk slice ({h11_eval_w3_slice['chains_N']}): {h11_eval_w3_slice['strict_5step_monotone_rate']*100:.1f}%"
    )

    # 9. Benchmark 3 — 40-Task H15 Residual Candidate Pool Evaluation
    residual_40 = [json.loads(l) for l in residual_40_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    rce_bin_str = str(RCE_BIN)

    # 9a. Typed-edit candidate beams on the 40 H15 tasks
    h15_typed_scores: list[float] = []
    h15_typed_labels: list[int] = []
    h15_ebm_k1_adm = 0
    h15_unrerank_k1_adm = 0
    h15_beam_any_adm = 0
    h15_ebm_checks_total = 0
    h15_unrerank_checks_total = 0

    # Also score multi-proposer candidate pool if present (Wave 1 + Wave 4 H15-Iterative)
    iter_pool_path = WORK_DIR / "h15_iterative_candidates.json"
    iter_pool: dict[str, list[dict[str, Any]]] = (
        json.loads(iter_pool_path.read_text(encoding="utf-8")) if iter_pool_path.exists() else {}
    )
    wave1_eps_path = EXP_REPO / "rce/bench/h15-gear0/results/gear0_store.jsonl"
    wave1_adm_by_id = {}
    if wave1_eps_path.exists():
        for ln in wave1_eps_path.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                g = json.loads(ln)
                wave1_adm_by_id[g["task_id"]] = g["repaired_rce"]

    h15_multi_scores: list[float] = []
    h15_multi_labels: list[int] = []

    with tempfile.TemporaryDirectory(prefix="febm_h15_") as td:
        fp = Path(td) / "c.rce"
        for t40 in residual_40:
            tid = t40["id"]
            mut = t40["mutant"]
            fp.write_text(mut, encoding="utf-8")
            chk_m = subprocess.run([rce_bin_str, "check", str(fp)], capture_output=True, text=True, timeout=10.0)
            diag_m = (chk_m.stdout + chk_m.stderr).replace(str(fp), "MUTANT.rce").strip()
            rc_m, dl_m, _ = parse_diagnostic(diag_m)
            rid = torch.tensor([RULE_TO_ID.get(rc_m, RULE_TO_ID["UNK_RULE"])], dtype=torch.long)

            beam_40 = enumerate_diagnostic_candidate_beam(mut, diag_m, stdlib_cat, max_beam=16)
            adm_flags: list[int] = []
            c_i_l, c_t_l = [], []
            r_i0, r_t0 = None, None
            for b_item in beam_40:
                kept_ok, _ = check_obligations_preserved(mut, b_item["text"])
                if kept_ok and b_item["text"] != mut:
                    fp.write_text(b_item["text"], encoding="utf-8")
                    rc_c = subprocess.run([rce_bin_str, "check", str(fp)], capture_output=True, timeout=10.0).returncode
                    ok = 1 if rc_c == 0 else 0
                else:
                    ok = 0
                adm_flags.append(ok)
                ri, rt, ci, ct = tok.encode_pair(mut, b_item["text"], rule_code=rc_m, diag_line_1based=dl_m)
                if r_i0 is None:
                    r_i0, r_t0 = ri, rt
                c_i_l.append(ci)
                c_t_l.append(ct)

            if c_i_l and r_i0 is not None and r_t0 is not None:
                with torch.no_grad():
                    r_ids = torch.tensor([r_i0], dtype=torch.long)
                    r_tgs = torch.tensor([r_t0], dtype=torch.long)
                    c_ids = torch.tensor(c_i_l, dtype=torch.long)
                    c_tgs = torch.tensor(c_t_l, dtype=torch.long)
                    lr_l = max(16, int((r_ids != 0).sum().item()))
                    lc_l = max(16, int((c_ids != 0).sum(dim=1).max().item()))
                    en, _, _ = model.score_group(r_ids[:, :lr_l], r_tgs[:, :lr_l], c_ids[:, :lc_l], c_tgs[:, :lc_l], rid)
                    ev = en.float().cpu().tolist()

                h15_typed_scores.extend([-x for x in ev])
                h15_typed_labels.extend(adm_flags)
                if any(a == 1 for a in adm_flags):
                    h15_beam_any_adm += 1
                if adm_flags[0] == 1:
                    h15_unrerank_k1_adm += 1
                ord_ebm = sorted(range(len(adm_flags)), key=lambda i: ev[i])
                if adm_flags[ord_ebm[0]] == 1:
                    h15_ebm_k1_adm += 1
                h15_unrerank_checks_total += next((i + 1 for i, a in enumerate(adm_flags) if a == 1), len(adm_flags))
                h15_ebm_checks_total += next((rk + 1 for rk, i in enumerate(ord_ebm) if adm_flags[i] == 1), len(adm_flags))

            # Build combined multi-proposer pool (typed edits + H15-Iterative + Wave 1)
            mp_seen = set()
            mp_items: list[tuple[str, int]] = []
            for b_item, ok in zip(beam_40, adm_flags):
                if b_item["text"] not in mp_seen:
                    mp_seen.add(b_item["text"])
                    mp_items.append((b_item["text"], ok))
            for it_c in iter_pool.get(tid, []):
                if it_c["text"] not in mp_seen:
                    mp_seen.add(it_c["text"])
                    mp_items.append((it_c["text"], 1 if it_c["admitted"] else 0))
            if tid in wave1_adm_by_id and wave1_adm_by_id[tid] not in mp_seen:
                mp_seen.add(wave1_adm_by_id[tid])
                mp_items.append((wave1_adm_by_id[tid], 1))

            if mp_items:
                mc_i, mc_t, mlabs = [], [], []
                mr_i0, mr_t0 = None, None
                for txt_c, ok_c in mp_items:
                    ri, rt, ci, ct = tok.encode_pair(mut, txt_c, rule_code=rc_m, diag_line_1based=dl_m)
                    if mr_i0 is None:
                        mr_i0, mr_t0 = ri, rt
                    mc_i.append(ci)
                    mc_t.append(ct)
                    mlabs.append(ok_c)
                assert mr_i0 is not None and mr_t0 is not None
                with torch.no_grad():
                    r_ids = torch.tensor([mr_i0], dtype=torch.long)
                    r_tgs = torch.tensor([mr_t0], dtype=torch.long)
                    c_ids = torch.tensor(mc_i, dtype=torch.long)
                    c_tgs = torch.tensor(mc_t, dtype=torch.long)
                    lr_l = max(16, int((r_ids != 0).sum().item()))
                    lc_l = max(16, int((c_ids != 0).sum(dim=1).max().item()))
                    en_m, _, _ = model.score_group(r_ids[:, :lr_l], r_tgs[:, :lr_l], c_ids[:, :lc_l], c_tgs[:, :lc_l], rid)
                    h15_multi_scores.extend((-en_m).float().cpu().tolist())
                    h15_multi_labels.extend(mlabs)

    h15_typed_auroc, _ = compute_auroc_and_roc(h15_typed_scores, h15_typed_labels)
    h15_multi_auroc, _ = compute_auroc_and_roc(h15_multi_scores, h15_multi_labels)

    h15_pool_eval = {
        "tasks_N": 40,
        "typed_edit_candidate_pool": {
            "candidates_scored": len(h15_typed_labels),
            "accepted_candidates": sum(h15_typed_labels),
            "auroc_form_ebm_v2": h15_typed_auroc,
            "beam_k16_admitted_tasks": h15_beam_any_adm,
            "top1_k1_admitted_with_form_ebm_v2_rerank": h15_ebm_k1_adm,
            "top1_k1_admitted_unreranked": h15_unrerank_k1_adm,
            "wave3_form_jepa_v1_k1_reference": 22,
            "wave3_form_jepa_v1_k16_reference": 27,
            "mean_rce_checks_per_task_form_ebm_v2": round(h15_ebm_checks_total / 40.0, 3),
            "mean_rce_checks_per_task_unreranked": round(h15_unrerank_checks_total / 40.0, 3),
            "wave3_form_jepa_v1_mean_checks_reference": 5.33,
        },
        "combined_multi_proposer_pool": {
            "candidates_scored": len(h15_multi_labels),
            "accepted_candidates": sum(h15_multi_labels),
            "auroc_form_ebm_v2": h15_multi_auroc,
        },
    }
    print(
        f"[FormEBM-v2] H15 40-task pool: typed_AUROC={h15_typed_auroc:.4f}, multi_proposer_AUROC={h15_multi_auroc:.4f} | "
        f"k=1 top-1 admitted={h15_ebm_k1_adm}/40 (beam={h15_beam_any_adm}/40), mean_checks={h15_pool_eval['typed_edit_candidate_pool']['mean_rce_checks_per_task_form_ebm_v2']}"
    )

    ebm_summary = {
        "schema": "openie-rce-jepa-form-ebm-v2-summary/1",
        "completed_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "prereg_id": prereg["id"],
        "prereg_sha256": actual_sha,
        "engine": {
            "rce_commit": prereg["data_and_leakage_controls"]["upstream_repositories"]["rce_commit"],
            "rce_linux_x86_64_binary_sha256": sha256_bytes(RCE_BIN.read_bytes()),
            "openie_research_experiments_commit": prereg["data_and_leakage_controls"]["upstream_repositories"]["openie_research_experiments_commit"],
        },
        "architecture_and_training": {
            "name": "FormEBM-v2",
            "trainable_parameters": n_params,
            "checkpoint_sha256": ckpt_sha,
            "vocab_active_tokens": len(tok.tok2id),
            "vocab_capacity": VOCAB_SIZE,
            "max_seq_len": MAX_SEQ_LEN,
            "omp_num_threads": 10,
            "epochs": epochs,
            "dataset_generation_wall_s": corpus_wall_s,
            "training_wall_s": train_wall_s,
            "training_rapl_core_reported_j": train_core_j,
            "training_rapl_package_reported_j": train_pkg_j,
            "measured_j": None,
            "est_j": None,
            "board_metered": False,
            "leakage_and_split_audit": {
                **leakage_audit,
                "train_forms": len(train_forms),
                "val_forms": len(val_forms),
                "test_forms": len(test_forms),
                "train_beams": len(train_beams),
                "val_beams": len(val_beams),
                "test_beams": len(test_200_beams),
                "train_5step_chains": len(train_chains),
                "val_5step_chains": len(val_chains),
                "test_5step_chains": len(test_100_chains),
            },
            "anti_collapse_verification": {
                "falsifier_F1_collapse_triggered": f1_collapsed,
                "epoch_0_untrained": pre_metrics,
                "best_checkpoint_val": post_metrics,
            },
            "epoch_history": epoch_history,
        },
        "rapl_inference_microbenchmark": rapl_inf,
        "eval_H5_unseen_test_200_beams": h5_eval,
        "eval_H11_unseen_test_100_chains": h11_eval_100,
        "eval_H11_wave3_random_walk_slice": h11_eval_w3_slice,
        "eval_H15_residual_40_pool": h15_pool_eval,
    }

    out_path = RESULTS_DIR / "form_ebm_v2_summary.json"
    out_path.write_text(json.dumps(ebm_summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[FormEBM-v2] Wrote {out_path}")


if __name__ == "__main__":
    main()
