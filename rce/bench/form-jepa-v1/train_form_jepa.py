#!/usr/bin/env python3
"""
FormJEPA-v1: Purpose-Built Joint Embedding Predictive Architecture + Latent-Guided
Typed Edit Proposer over Canonical RCE Forms.

Strict isolation & provenance guarantees:
  1. Verifies PREREG_form_jepa_v1.json against its .sha256 sidecar and verifies
     upstream 151-task ladder + 40-task H15 residual SHA-256 digests before running.
  2. Enforces 4-layer cryptographic and structural exclusion (file path, program slug,
     primary state/actor/module identifier, and nameless/canonical/raw SHA-256) so
     zero evaluation tasks appear in train, synthetic val (N=500), or synthetic test (N=200).
  3. Trains Context Encoder E_theta(x, r), EMA Target Encoder E_ema(y) (tau=0.996),
     Latent Predictor P_phi(z_x, e_r) -> z_hat_y with Smooth-L1 + VICReg variance-covariance
     anti-collapse regularization, and Latent-Conditioned Edit/Span Decoder D_psi(H_x, z_hat_y).
  4. Records Linux powercap RAPL package-0 and core reported_j separately from est_j
     and measured_j (None). Uses $BENCH_ROOT paths only.
"""

from __future__ import annotations

import concurrent.futures
import copy
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

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

# ============================================================================
# Environment-Driven Paths ($BENCH_ROOT) & Deterministic Seeding
# ============================================================================

HERE = Path(__file__).resolve().parent
BENCH_ROOT = Path(os.environ["BENCH_ROOT"]) if "BENCH_ROOT" in os.environ else HERE.parent
RCE_REPO = Path(os.environ["RCE_REPO"]) if "RCE_REPO" in os.environ else (BENCH_ROOT / "rce")
EXP_REPO = Path(os.environ["EXP_REPO"]) if "EXP_REPO" in os.environ else (BENCH_ROOT / "openie-research-experiments")
WORK_DIR = Path(os.environ["WORK_DIR"]) if "WORK_DIR" in os.environ else (BENCH_ROOT / "work")
RCE_BIN = Path(os.environ["RCE_BIN"]) if "RCE_BIN" in os.environ else (RCE_REPO / "spec/checker/target/release/rce")

PREREG_PATH = HERE / "PREREG_form_jepa_v1.json"
PREREG_SHA_PATH = HERE / "PREREG_form_jepa_v1.json.sha256"
RESULTS_DIR = HERE / "results"

SEED = 20261122
VOCAB_SIZE = 2048
MAX_SEQ_LEN = 384
MAX_LINES = 128
D_MODEL = 256
D_RULE = 64
N_HEADS = 8
N_ENC_LAYERS = 6
N_DEC_LAYERS = 2
N_OPS = 8
N_ARGS = 64

EDIT_OP_NAMES = [
    "OP_CMP_SWAP",       # 0: comparison / logical / guard negation repair
    "OP_CONST_BOUND",    # 1: constant / bool / negative-zero / loop-bound repair
    "OP_ARITH_EXPR",     # 2: binary arithmetic / checked_sub / checked_add repair
    "OP_TYPE_ANNOT",     # 3: state / event / parameter / return type repair
    "OP_SCOPE_IDENT",    # 4: in-scope rename / unused _ prefix / stdlib use+qualify repair
    "OP_METHOD_CALL",    # 5: method projection (.len_bytes / .len_chars / collection methods)
    "OP_TOTALITY_KEEP",  # 6: totality handler / pre-0.9 refuse->fail & kept: normalization
    "OP_CAP_WORLD",      # 7: extern World capability threading & W-CAP-3 hygiene
]

CMP_VOCAB = ["<", "<=", ">", ">=", "==", "!=", "and", "or", "STRIP_NOT", "ADD_NOT"]
CONST_VOCAB = ["+1", "-1", "0", "1", "2", "true", "false", "-0.0", "BOUND_DOUBLE", "BOUND_INC"]
ARITH_VOCAB = ["+", "-", "*", "/", "%", "TO_CHECKED_SUB", "TO_CHECKED_ADD"]
TYPE_VOCAB = ["u64", "i64", "u32", "i32", "f64", "bool", "text", "usize", "u8", "i8"]
METHOD_VOCAB = ["len_bytes", "len_chars", "len", "is_empty", "words", "lines", "chars", "as_bytes", "clone"]

RULE_CODES = [
    "OK", "UNK_RULE", "W-SYN-1", "W-TY-1", "W-NAME-1", "W-NAME-2", "W-INT-1", "W-INT-2",
    "W-LEN-1", "W-WORLD-1", "W-CAP-3", "W-UNUSED-1", "W-DROP-1", "W-MUT-1", "W-MUT-2",
    "W-TOT-1", "W-EXH-1", "W-PAR-1", "W-LEX-1", "W-LEX-3", "W-BOUNDS-1", "W-REC-1",
    "W-OWN-1", "W-BOR-1", "W-UI-1", "W-RES-1", "W-MOD-1", "W-IMP-1", "W-PIN-1",
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
    "refuse", "refused", "kept", "by", "as", "mut", "then", "ok", "err",
]

BUILTIN_IDENTIFIERS = [
    "bool", "text", "i8", "i16", "i32", "i64", "u8", "u16", "u32", "u64", "usize",
    "f32", "f64", "List", "Map", "Set", "Box", "Option", "Secret", "Cap", "Guarded",
    "Text", "World", "Template", "Shell", "Prompt", "Header", "mathint", "Tick",
    "main", "Eq", "Ord", "Hash", "Show", "Copy", "Data", "Merge", "Start", "Input",
    "Display", "Exit", "DirRead", "DirWrite", "len", "len_bytes", "len_chars",
    "checked_sub", "checked_add", "words", "lines", "chars", "push", "is_empty",
    "clone", "unwrap_or", "contains", "get", "insert", "remove",
]

PUNCT_TOKENS = [
    "(", ")", "[", "]", "{", "}", ":", ",", ".", "->", "==", "!=", "<=", ">=",
    "<", ">", "+", "-", "*", "/", "%", "=", "&", "@", "#", "!",
]

TOKEN_RE = re.compile(
    r'"(?:\\.|[^"\\])*"|\d+\.\d+|\d+|->|==|!=|<=|>=|[A-Za-z_][A-Za-z0-9_]*|[^\sA-Za-z0-9_]'
)
RULE_DIAG_RE = re.compile(r"\b(W-[A-Z0-9]+-\d+)\b")
LINE_DIAG_RE = re.compile(r"\bline\s+(\d+)\b")
BACKTICK_IDENT_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)`")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_str(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


class SplitMix64:
    """Deterministic SplitMix64 PRNG matching openIE-dev/rce corpus scripts."""

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


def set_all_seeds(seed: int = SEED) -> None:
    np.random.seed(seed % (2**32 - 1))
    torch.manual_seed(seed)


# ============================================================================
# Linux Powercap RAPL Telemetry (`reported_j` Only; `measured_j = None`)
# ============================================================================

def read_rapl_uj() -> dict[str, int | None]:
    """Read Linux powercap RAPL energy counters in microjoules if world/group-readable."""
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
# Public Standard Library Export Scanner (Derived Strictly from `stdlib/lib/`)
# ============================================================================

def build_stdlib_catalog(rce_repo: Path) -> dict[str, Any]:
    """Scan public `stdlib/lib/*.rce` modules to map module names and exported symbols."""
    lib_root = rce_repo / "stdlib/lib"
    mod_to_exports: dict[str, set[str]] = {}
    sym_to_mods: dict[str, list[str]] = {}
    if lib_root.exists():
        for p in sorted(lib_root.rglob("*.rce")):
            rel = p.relative_to(lib_root)
            parts = list(rel.with_suffix("").parts)
            if len(parts) >= 2 and parts[-1] == parts[-2]:
                mod_name = ".".join(parts[:-1])
            else:
                mod_name = ".".join(parts)
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


# ============================================================================
# Indentation-Aware Form AST S-Expression Tokenizer (Quotient-Normalized)
# ============================================================================

class FormSExprTokenizer:
    """
    Deterministic S-expression tokenizer over RCE Forms.
    Maps syntax structure into `(module (L0 ...) (L1 (indent ...) ...) ...)` tokens
    while normalizing module-local identifiers to positional `id_0 .. id_63` slots
    (approximating `rce fmt nameless` even when `x` has syntax or type defects).
    """

    def __init__(self, stdlib_mods: list[str] | None = None) -> None:
        self.tok2id: dict[str, int] = {}
        specials = [
            "<PAD>", "<UNK>", "<CLS>", "<SEP>", "<S_OPEN>", "<S_CLOSE>",
            "<INDENT_1>", "<INDENT_2>", "<INDENT_3>", "<INDENT_4>",
            "<STR_LIT>", "<FLOAT_LIT>", "<INT_SMALL>", "<INT_LARGE>", "<NEG_ZERO>",
        ]
        for s in specials:
            self._add(s)
        for r in RULE_CODES:
            self._add(f"<RULE:{r}>")
        for i in range(MAX_LINES):
            self._add(f"<L{i}>")
        for kw in RCE_KEYWORDS:
            self._add(kw)
        for bi in BUILTIN_IDENTIFIERS:
            self._add(bi)
        for pt in PUNCT_TOKENS:
            self._add(pt)
        for n in range(-2, 17):
            self._add(f"<NUM:{n}>")
        for i in range(64):
            self._add(f"<ID:{i}>")
        for prefix in ("r", "e", "x", "f", "t", "k", "v"):
            for i in range(32):
                self._add(f"{prefix}{i}")
        for m in (stdlib_mods or []):
            for part in m.split("."):
                self._add(part)
        self.pad_id = self.tok2id["<PAD>"]
        self.unk_id = self.tok2id["<UNK>"]
        self.cls_id = self.tok2id["<CLS>"]
        self.s_open = self.tok2id["<S_OPEN>"]
        self.s_close = self.tok2id["<S_CLOSE>"]
        self.line_token_ids = [self.tok2id[f"<L{i}>"] for i in range(MAX_LINES)]

    def _add(self, tok: str) -> None:
        if tok not in self.tok2id and len(self.tok2id) < VOCAB_SIZE:
            self.tok2id[tok] = len(self.tok2id)

    def select_window(self, lines: list[str], diag_line_1based: int | None) -> tuple[list[int], int]:
        """Select up to MAX_LINES line indices (0-based) covering headers + diagnostic neighborhood."""
        n = len(lines)
        if n <= MAX_LINES:
            return list(range(n)), 0
        focus = max(0, min(n - 1, (diag_line_1based or 1) - 1))
        header_count = min(24, MAX_LINES // 4)
        rem = MAX_LINES - header_count
        half = rem // 2
        start = max(header_count, focus - half)
        end = min(n, start + rem)
        start = max(header_count, end - rem)
        chosen = list(range(header_count)) + list(range(start, end))
        return chosen[:MAX_LINES], start

    def encode(
        self,
        src: str,
        rule_code: str = "OK",
        diag_line_1based: int | None = None,
    ) -> tuple[list[int], list[int], list[int], list[int]]:
        """
        Returns:
          input_ids: length MAX_SEQ_LEN
          diag_mask: length MAX_SEQ_LEN (1 on tokens belonging to diagnostic line)
          line_pos_in_seq: length MAX_LINES (token index of <Lk> in input_ids, or 0 if truncated)
          window_line_indices: actual 0-based line numbers in `src` corresponding to 0..len-1
        """
        lines = src.splitlines()
        if not lines:
            lines = [""]
        win_indices, _ = self.select_window(lines, diag_line_1based)

        rule_tok = f"<RULE:{rule_code}>" if f"<RULE:{rule_code}>" in self.tok2id else "<RULE:UNK_RULE>"
        ids: list[int] = [self.cls_id, self.tok2id[rule_tok], self.s_open]
        dmask: list[int] = [0, 1, 0]
        line_pos = [0] * MAX_LINES

        local_map: dict[str, str] = {}
        diag_0 = (diag_line_1based - 1) if (diag_line_1based and diag_line_1based > 0) else -1

        # Reserve ~3 tokens on average per visible line so headers + focus fit cleanly
        for slot_i, orig_li in enumerate(win_indices):
            if len(ids) >= MAX_SEQ_LEN - 4:
                break
            raw_line = lines[orig_li]
            is_diag = 1 if abs(orig_li - diag_0) <= 1 and diag_0 >= 0 else 0
            line_pos[slot_i] = len(ids)
            ids.append(self.line_token_ids[slot_i])
            dmask.append(is_diag)

            stripped = raw_line.lstrip(" ")
            indent_lvl = min(4, (len(raw_line) - len(stripped)) // 4)
            if indent_lvl > 0 and len(ids) < MAX_SEQ_LEN - 2:
                ids.append(self.tok2id[f"<INDENT_{indent_lvl}>"])
                dmask.append(is_diag)

            # Keep `#!lib` visible as `#`, `!`, `lib` so retired directive defects are observable
            if stripped.startswith("#") and not stripped.startswith("#!lib"):
                continue

            ids.append(self.s_open)
            dmask.append(is_diag)
            raw_toks = TOKEN_RE.findall(stripped)[:22]
            for rt in raw_toks:
                if len(ids) >= MAX_SEQ_LEN - 2:
                    break
                tid = self._map_token(rt, local_map)
                ids.append(tid)
                dmask.append(is_diag)
            if len(ids) < MAX_SEQ_LEN - 1:
                ids.append(self.s_close)
                dmask.append(is_diag)

        if len(ids) < MAX_SEQ_LEN:
            ids.append(self.s_close)
            dmask.append(0)
        while len(ids) < MAX_SEQ_LEN:
            ids.append(self.pad_id)
            dmask.append(0)
        return ids[:MAX_SEQ_LEN], dmask[:MAX_SEQ_LEN], line_pos, win_indices

    def _map_token(self, rt: str, local_map: dict[str, str]) -> int:
        if rt in self.tok2id:
            return self.tok2id[rt]
        if rt.startswith('"'):
            return self.tok2id["<STR_LIT>"]
        if rt == "0.0":
            return self.tok2id["<NEG_ZERO>"]
        if re.fullmatch(r"\d+\.\d+", rt):
            return self.tok2id["<FLOAT_LIT>"]
        if rt.isdigit():
            val = int(rt)
            key = f"<NUM:{val}>"
            if key in self.tok2id:
                return self.tok2id[key]
            return self.tok2id["<INT_SMALL>"] if val < 256 else self.tok2id["<INT_LARGE>"]
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", rt):
            if rt not in local_map:
                idx = min(63, len(local_map))
                local_map[rt] = f"<ID:{idx}>"
            return self.tok2id[local_map[rt]]
        return self.unk_id


# ============================================================================
# Typed Form Edit Semantics (`apply_edit` + Forward Synthetic Corruption)
# ============================================================================

def parse_diagnostic(diag_text: str) -> tuple[str, int | None, list[str]]:
    rules = RULE_DIAG_RE.findall(diag_text)
    rule = rules[0] if rules else "UNK_RULE"
    m_line = LINE_DIAG_RE.search(diag_text)
    line_no = int(m_line.group(1)) if m_line else None
    names = []
    for nm in BACKTICK_IDENT_RE.findall(diag_text):
        if nm not in names:
            names.append(nm)
    return rule, line_no, names


def is_obligation_line(lines: list[str], idx: int) -> bool:
    """True if `lines[idx]` is inside `intent` / `example` / `check` / `law` obligations."""
    s = lines[idx].strip()
    if s.startswith(("intent ", "example ", "check ", "law ", "requires ", "ensures ")):
        return True
    # Check if indented under `intent "..."`
    for j in range(idx - 1, -1, -1):
        lj = lines[j]
        if not lj.strip():
            continue
        if not lj.startswith(" "):
            return lj.startswith("intent ")
    return False


def collect_scope_identifiers(lines: list[str], target_idx: int) -> list[str]:
    """Deterministically collect state fields, parameters, and prior local bindings in scope."""
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

    # Find enclosing top-level `fn` / `pub fn` / `step` above `target_idx`
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


def apply_edit(
    src: str,
    line_idx: int,
    op_id: int,
    arg_id: int,
    stdlib_cat: dict[str, Any],
    diag_names: list[str] | None = None,
) -> str:
    """
    Pure, deterministic typed Form edit operator D_psi action realization.
    Never modifies obligation assertions except pre-0.9 `refused:` keyword syntax token when
    explicitly invoked under OP_TOTALITY_KEEP arg 0 (keeping the trace LHS and error name intact).
    """
    lines = src.splitlines()
    if not lines:
        return src
    line_idx = max(0, min(len(lines) - 1, line_idx))
    diag_names = diag_names or []

    if op_id == 0:  # OP_CMP_SWAP
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

    if op_id == 1:  # OP_CONST_BOUND
        if is_obligation_line(lines, line_idx) or arg_id >= len(CONST_VOCAB):
            return src
        act = CONST_VOCAB[arg_id]
        line = lines[line_idx]
        if act in ("true", "false"):
            other = "false" if act == "true" else "true"
            lines[line_idx] = re.sub(rf"\b{other}\b", act, line, count=1)
        elif act == "-0.0":
            # IEEE-754 negative zero literal repair
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
                if act == "+1":
                    nv = v + 1
                elif act == "-1":
                    nv = max(0, v - 1)
                else:
                    nv = int(act)
                lines[line_idx] = line[:m.start(1)] + str(nv) + line[m.end(1):]
        return "\n".join(lines) + ("\n" if src.endswith("\n") else "")

    if op_id == 2:  # OP_ARITH_EXPR
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
            # Avoid matching `->`
            for m in re.finditer(r"(?<!-)(?<!/)[+\-*/%](?!>)", line):
                lines[line_idx] = line[:m.start()] + act + line[m.end():]
                break
        return "\n".join(lines) + ("\n" if src.endswith("\n") else "")

    if op_id == 3:  # OP_TYPE_ANNOT
        if is_obligation_line(lines, line_idx) or arg_id >= len(TYPE_VOCAB):
            return src
        new_ty = TYPE_VOCAB[arg_id]
        line = lines[line_idx]
        ty_pat = r"(:\s*|->\s*)(u64|i64|u32|i32|u16|i16|u8|i8|usize|f64|f32|bool|text)\b"
        lines[line_idx] = re.sub(ty_pat, rf"\g<1>{new_ty}", line, count=1)
        return "\n".join(lines) + ("\n" if src.endswith("\n") else "")

    if op_id == 4:  # OP_SCOPE_IDENT
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
            # Prefer replacing an identifier flagged in diagnostic backticks if present on the line
            for dn in diag_names:
                if dn != replacement and re.search(rf"(?<![.\w]){re.escape(dn)}\b", line):
                    lines[line_idx] = re.sub(rf"(?<![.\w]){re.escape(dn)}\b", replacement, line, count=1)
                    return "\n".join(lines) + ("\n" if src.endswith("\n") else "")
            # Otherwise replace RHS identifier occurrence
            rhs_split = line.split("=", 1) if ("=" in line and "==" not in line and "!=" not in line and "<=" not in line and ">=" not in line) else (line.split("->", 1) if "->" in line else [line])
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

        if arg_id == 16:  # Prefix unused local binding with `_`
            line = lines[line_idx]
            lines[line_idx] = re.sub(r"^(\s*(?:let|var|for)\s+)([a-z][A-Za-z0-9_]*)\b", r"\1_\2", line, count=1)
            return "\n".join(lines) + ("\n" if src.endswith("\n") else "")

        # arg_id 17..56: Public stdlib module qualification (`#!lib` -> `use <mod>` + `mod.sym`)
        mod_idx = arg_id - 17
        ordered_mods: list[str] = stdlib_cat["ordered_mods"]
        if 0 <= mod_idx < len(ordered_mods):
            mod_name = ordered_mods[mod_idx]
            return _qualify_stdlib_module(src, mod_name, stdlib_cat)
        return src

    if op_id == 5:  # OP_METHOD_CALL
        if is_obligation_line(lines, line_idx) or arg_id >= len(METHOD_VOCAB):
            return src
        new_m = METHOD_VOCAB[arg_id]
        line = lines[line_idx]
        new_line = re.sub(
            r"\.(len_bytes|len_chars|len|is_empty|words|lines|chars|as_bytes|clone)\s*\(",
            f".{new_m}(",
            line,
            count=1,
        )
        lines[line_idx] = new_line
        return "\n".join(lines) + ("\n" if src.endswith("\n") else "")

    if op_id == 6:  # OP_TOTALITY_KEEP
        if arg_id == 0:
            # Public Draft 0.9 grammar rule: retired `refuse <Err>` -> `fail <Err>` and `-> refused:` -> `-> kept:`
            out_lines = []
            for ln in lines:
                ln2 = re.sub(r"->\s*refused\s*:", "-> kept:", ln)
                ln2 = re.sub(r"^(\s*(?:step\b.*->\s*|if\b.*->\s*|else\s*->\s*)?)refuse\s+([A-Z][A-Za-z0-9_]*)\b", r"\1fail \2", ln2)
                ln2 = re.sub(r"\brefuse\s+([A-Z][A-Za-z0-9_]*)\b", r"fail \1", ln2)
                out_lines.append(ln2)
            return "\n".join(out_lines) + ("\n" if src.endswith("\n") else "")
        # arg_id 1..7: Restore missing totality `step <Region> on <Event> -> fail <Err>`
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
            # Check if event has payload fields
            ev_decl = next((ln.strip() for ln in lines if ln.strip().startswith(f"event {ev}")), f"event {ev}")
            pat = f"{ev}(..)" if "(" in ev_decl else ev
            rhs = f"fail {errors[0]}" if errors else "pass"
            lines.append(f"step {reg} on {pat} -> {rhs}")
            return "\n".join(lines) + "\n"
        return src

    if op_id == 7:  # OP_CAP_WORLD
        if arg_id == 0:
            # Public Draft 0.9 F.4.1 rule: `extern "C" fn` requires `w: &World`, `fn main(w: &World)`, and `w` at call sites
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
                            ln = re.sub(
                                rf"\b{re.escape(fn_nm)}\(\s*(?!w\b)",
                                lambda m: f"{fn_nm}(w)" if False else f"{fn_nm}(w, ",
                                ln,
                            )
                            ln = ln.replace(f"{fn_nm}(w, )", f"{fn_nm}(w)")
                    patched.append(ln)
                out_lines = patched
            return "\n".join(out_lines) + ("\n" if src.endswith("\n") else "")
        if arg_id == 1:
            # Public Draft 0.9 F.5.1 W-CAP-3: rename reserved authority parameter name `path` -> `name`
            out_lines = [re.sub(r"\bpath\b", "name", ln) if not ln.strip().startswith("#") else ln for ln in lines]
            return "\n".join(out_lines) + ("\n" if src.endswith("\n") else "")

    return src


def _qualify_stdlib_module(src: str, primary_mod: str, stdlib_cat: dict[str, Any]) -> str:
    """Apply `use <mod>` and qualify bare stdlib calls exported by `primary_mod` (and `#!lib` directives)."""
    lines = src.splitlines()
    mods_to_use: list[str] = []
    # Check `#!lib` directives if present
    for ln in lines:
        m = re.match(r"^#!\s*lib\s+([A-Za-z0-9_.]+)", ln.strip())
        if m and m.group(1) in stdlib_cat["mod_to_exports"] and m.group(1) not in mods_to_use:
            mods_to_use.append(m.group(1))
    if primary_mod not in mods_to_use and primary_mod in stdlib_cat["mod_to_exports"]:
        mods_to_use.append(primary_mod)

    existing_uses = {
        m.group(1) for ln in lines if (m := re.match(r"^use\s+([A-Za-z0-9_.]+)\b", ln.strip()))
    }
    # Also check if bare calls match `crypto` when `hpke`/`mls`/`pq` are imported
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

    # Build symbol -> module map for `mods_to_use` + `existing_uses`
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
            # Only qualify RHS after `->` or `=` if single-line
            for sep in ("->", "="):
                if sep in ln:
                    lhs, rhs = ln.split(sep, 1)
                    for sym, prefix in qual_map.items():
                        rhs = re.sub(rf"(?<![.\w`\"]){re.escape(sym)}\b", f"{prefix}.{sym}", rhs)
                    ln = lhs + sep + rhs
                    break
        new_lines.append(ln)

    return "\n".join(new_lines) + ("\n" if src.endswith("\n") else "")


# ============================================================================
# Disjoint Form Extraction & Synthetic Defect Pair Generation
# ============================================================================

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
    with tempfile.TemporaryDirectory(prefix="fjepa_chk_") as td:
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
    workers: int = 24,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Extract valid Forms strictly disjoint from all 151 ladder and 40 H15 tasks."""
    t151 = [json.loads(l) for l in tasks_151_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    t40 = [json.loads(l) for l in residual_40_path.read_text(encoding="utf-8").splitlines() if l.strip()]

    forbidden_paths: set[str] = set()
    forbidden_slugs: set[str] = set()
    forbidden_decls: set[str] = set()
    forbidden_hashes: set[str] = set()

    with tempfile.TemporaryDirectory(prefix="fjepa_forbid_") as td:
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

    # Gather raw candidate files from rce_repo + forms.jsonl
    raw_candidates: list[tuple[str, str, str, str]] = []
    seen_paths: set[str] = set()

    def _is_path_or_slug_forbidden(rel_p: str, src: str) -> bool:
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
            if len(src.splitlines()) > 180 or _is_path_or_slug_forbidden(rel, src):
                continue
            seen_paths.add(rel)
            raw_candidates.append((str(rce_bin), rel, origin, src))

    # Include standalone conformance accept/run/trace tests (stripping `#--- rce-test` trailer)
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
            # Exclude any conformance test harvested from a forbidden path or slug
            m_prov = re.search(r"#\s*provenance:\s*(.+)", meta_part)
            if m_prov:
                prov = m_prov.group(1)
                if any(fp_p in prov for fp_p in forbidden_paths) or any(
                    re.search(rf"\b{re.escape(sl)}\b", prov) for sl in forbidden_slugs
                ):
                    continue
            src = src_part.strip() + "\n"
            if len(src.splitlines()) < 3 or len(src.splitlines()) > 160 or _is_path_or_slug_forbidden(rel, src):
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
            if rel in seen_paths or len(src.splitlines()) > 180 or _is_path_or_slug_forbidden(rel, src):
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
    origin_counts = Counter(f["origin"] for f in forms)
    audit = {
        "forbidden_paths_count": len(forbidden_paths),
        "forbidden_slugs_count": len(forbidden_slugs),
        "forbidden_primary_decls_count": len(forbidden_decls),
        "forbidden_hashes_count": len(forbidden_hashes),
        "candidates_scanned": len(raw_candidates),
        "disjoint_unique_shapes": len(forms),
        "disjoint_by_origin": dict(sorted(origin_counts.items())),
        "cryptographic_overlap_count": 0,
    }
    return forms, audit


def _alpha_rename_variant(src: str, variant_seed: int) -> str:
    """Create an alpha-renamed surface variant of a valid Form (quotient-equivalent)."""
    lines = src.splitlines()
    rng = SplitMix64(variant_seed)
    candidates: list[tuple[int, int, str]] = []
    n = len(lines)
    # Collect local bindings and non-main fn parameters
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
    # Also support renaming a state field across the whole module (no external API impact on standalone Form)
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
            # Also update declaration site `old_nm:` when inside `fn`/`state`
            if j == start or lines[j].strip().startswith(f"{old_nm}:"):
                lines[j] = re.sub(rf"\b{re.escape(old_nm)}(\s*:)", rf"{new_nm}\1", lines[j], count=1)
    return "\n".join(lines) + ("\n" if src.endswith("\n") else "")


def _propose_forward_corruptions(
    canon_src: str,
    stdlib_cat: dict[str, Any],
    rng: SplitMix64,
    max_per_form: int = 14,
) -> list[tuple[str, int, int, int, str]]:
    """
    Generate candidate `(broken_src, target_line_idx, target_op_id, target_arg_id, defect_tag)`
    tuples such that `apply_edit(broken_src, target_line_idx, target_op_id, target_arg_id)`
    recovers a valid Form!
    """
    lines = canon_src.splitlines()
    proposals: list[tuple[str, int, int, int, str]] = []
    ordered_mods: list[str] = stdlib_cat["ordered_mods"]

    # 1. OP_CMP_SWAP (op=0): comparison swap & guard `not (...)` injection
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

    # 2. OP_CONST_BOUND (op=1): off-by-one integer literals & bool flips
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
            if v >= 0 and v < 1000:
                # Perturb v -> v + 1, inverse is `-1` (arg 1); or if v > 0 perturb v -> v - 1, inverse is `+1` (arg 0)
                if v > 0 and rng.randbelow(2) == 0:
                    b_lines[li] = ln[:m.start(1)] + str(v - 1) + ln[m.end(1):]
                    proposals.append(("\n".join(b_lines) + "\n", li, 1, 0, "const_off_by_one"))
                else:
                    b_lines[li] = ln[:m.start(1)] + str(v + 1) + ln[m.end(1):]
                    proposals.append(("\n".join(b_lines) + "\n", li, 1, 1, "const_off_by_one"))

    # 3. OP_ARITH_EXPR (op=2): binary arithmetic operator defect
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

    # 4. OP_TYPE_ANNOT (op=3): state/event/fn type mismatch
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

    # 5. OP_SCOPE_IDENT (op=4): wrong local/unbound identifier, unused binding, or stdlib qualification
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
            b_lines = []
            for ln2 in lines:
                if ln2.strip() == f"use {mod_name}":
                    b_lines.append(f"#!lib {mod_name}")
                else:
                    b_lines.append(re.sub(rf"\b{re.escape(short)}\.([A-Za-z_][A-Za-z0-9_]*)", r"\1", ln2))
            proposals.append(("\n".join(b_lines) + "\n", li, 4, 17 + mod_idx, "stdlib_unqualified"))
            break

    # 6. OP_METHOD_CALL (op=5): `.len_bytes()` / `.len_chars()` -> `.len()` (`W-LEN-1`) or method swap
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

    # 7. OP_TOTALITY_KEEP (op=6): retired `refuse`/`refused:` syntax (`W-SYN-1`) or missing totality step (`W-TOT-1`)
    has_fail_or_kept = any(("fail " in ln or "-> kept:" in ln) for ln in lines)
    if has_fail_or_kept:
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

    # 8. OP_CAP_WORLD (op=7): `extern "C" fn` missing `w: &World` (`W-WORLD-1`)
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
    rng = SplitMix64(SEED ^ ((seed_i + 1) * 0x9E3779B97F4A7C15))
    variants = [form_row["canon_src"]]
    for k_var in range(3):
        alpha_src = _alpha_rename_variant(form_row["canon_src"], SEED ^ ((seed_i * 7 + k_var + 1) * 1315423911))
        if alpha_src not in variants:
            variants.append(alpha_src)

    verified: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="fjepa_mut_") as td:
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
# Genuine FormJEPA-v1 PyTorch Architecture
# ============================================================================

class FastPreLNTransformerBlock(nn.Module):
    """Explicit matmul Pre-LN Multi-Head Self-Attention + GELU FFN block (avoids CPU SDPA bug)."""

    def __init__(self, d_model: int = D_MODEL, nhead: int = N_HEADS, dim_ff: int = 1024, dropout: float = 0.1) -> None:
        super().__init__()
        self.nhead = nhead
        self.d_head = d_model // nhead
        self.scale = self.d_head ** -0.5
        self.norm1 = nn.LayerNorm(d_model)
        self.qkv = nn.Linear(d_model, 3 * d_model)
        self.out_proj = nn.Linear(d_model, d_model)
        self.drop = nn.Dropout(dropout)
        self.norm2 = nn.LayerNorm(d_model)
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


class FastCrossAttnDecoderBlock(nn.Module):
    """Explicit matmul Pre-LN Self-Attention + Latent Cross-Attention + FFN decoder block."""

    def __init__(self, d_model: int = D_MODEL, nhead: int = N_HEADS, dim_ff: int = 384, dropout: float = 0.1) -> None:
        super().__init__()
        self.self_blk = FastPreLNTransformerBlock(d_model=d_model, nhead=nhead, dim_ff=dim_ff, dropout=dropout)
        self.nhead = nhead
        self.d_head = d_model // nhead
        self.scale = self.d_head ** -0.5
        self.norm_q = nn.LayerNorm(d_model)
        self.q_proj = nn.Linear(d_model, d_model)
        self.kv_proj = nn.Linear(d_model, 2 * d_model)
        self.out_proj = nn.Linear(d_model, d_model)
        self.drop = nn.Dropout(dropout)

    def forward(self, x: torch.Tensor, memory: torch.Tensor, pad_mask: torch.Tensor) -> torch.Tensor:
        bsz, seqlen, dim = x.shape
        mlen = memory.size(1)
        q = self.q_proj(self.norm_q(x)).view(bsz, seqlen, self.nhead, self.d_head).transpose(1, 2)
        kv = self.kv_proj(memory).view(bsz, mlen, 2, self.nhead, self.d_head).permute(2, 0, 3, 1, 4)
        att = ((q @ kv[0].transpose(-2, -1)) * self.scale).softmax(dim=-1)
        ctx = (att @ kv[1]).transpose(1, 2).reshape(bsz, seqlen, dim)
        x = x + self.drop(self.out_proj(ctx))
        return self.self_blk(x, pad_mask)


class FormTransformerEncoder(nn.Module):
    """Transformer encoder over Form AST S-expression tokens producing H_x and latent z in R^256."""

    def __init__(self, vocab_size: int = VOCAB_SIZE, d_model: int = D_MODEL) -> None:
        super().__init__()
        self.tok_emb = nn.Embedding(vocab_size, d_model, padding_idx=0)
        self.pos_emb = nn.Embedding(MAX_SEQ_LEN, d_model)
        self.diag_emb = nn.Embedding(2, d_model)
        self.in_norm = nn.LayerNorm(d_model)
        self.layers = nn.ModuleList([
            FastPreLNTransformerBlock(d_model=d_model, nhead=N_HEADS, dim_ff=1024, dropout=0.1)
            for _ in range(N_ENC_LAYERS)
        ])
        self.latent_proj = nn.Linear(d_model * 2, d_model)

    def forward(self, input_ids: torch.Tensor, diag_mask: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        bsz, seqlen = input_ids.shape
        pos = torch.arange(seqlen, device=input_ids.device).unsqueeze(0).expand(bsz, seqlen)
        pad_mask = input_ids == 0
        h = self.in_norm(self.tok_emb(input_ids) + self.pos_emb(pos) + self.diag_emb(diag_mask))
        for blk in self.layers:
            h = blk(h, pad_mask)
        cls_state = h[:, 0, :]
        valid_mask = (~pad_mask).float().unsqueeze(-1)
        mean_state = (h * valid_mask).sum(dim=1) / valid_mask.sum(dim=1).clamp(min=1.0)
        z = self.latent_proj(torch.cat([cls_state, mean_state], dim=-1))
        return h, z


class LatentPredictor(nn.Module):
    """P_phi(z_x, e_r) -> z_hat_y: predicts clean canonical Form latent from broken Form latent + rule."""

    def __init__(self, d_model: int = D_MODEL, d_rule: int = D_RULE) -> None:
        super().__init__()
        self.rule_emb = nn.Embedding(len(RULE_CODES), d_rule)
        self.in_proj = nn.Linear(d_model + d_rule, 512)
        self.block1 = nn.Sequential(nn.LayerNorm(512), nn.GELU(), nn.Linear(512, 512))
        self.block2 = nn.Sequential(nn.LayerNorm(512), nn.GELU(), nn.Linear(512, 512))
        self.out_proj = nn.Sequential(nn.LayerNorm(512), nn.GELU(), nn.Linear(512, d_model))

    def forward(self, z_x: torch.Tensor, rule_ids: torch.Tensor) -> torch.Tensor:
        e_r = self.rule_emb(rule_ids)
        u = self.in_proj(torch.cat([z_x, e_r], dim=-1))
        u = u + self.block1(u)
        u = u + self.block2(u)
        return self.out_proj(u)


class LatentEditDecoder(nn.Module):
    """
    D_psi(H_x, z_x, z_hat_y): Latent-conditioned Edit/Span Repair Decoder.
    Applies FiLM conditioning from predicted latent displacement (z_hat_y - z_x) and
    cross-attends to [z_x, z_hat_y, z_hat_y - z_x] before predicting (line_span, op, arg).
    """

    def __init__(self, d_model: int = D_MODEL) -> None:
        super().__init__()
        self.film = nn.Linear(d_model * 2, d_model * 2)
        self.dec_layers = nn.ModuleList([
            FastCrossAttnDecoderBlock(d_model=d_model, nhead=N_HEADS, dim_ff=384, dropout=0.1)
            for _ in range(N_DEC_LAYERS)
        ])
        self.mem_proj = nn.Linear(d_model, d_model)
        self.line_head = nn.Sequential(nn.LayerNorm(d_model), nn.GELU(), nn.Linear(d_model, 1))
        self.op_head = nn.Sequential(
            nn.LayerNorm(d_model * 3),
            nn.Linear(d_model * 3, 192),
            nn.GELU(),
            nn.Linear(192, N_OPS),
        )
        self.op_emb = nn.Embedding(N_OPS, 64)
        self.arg_head = nn.Sequential(
            nn.LayerNorm(d_model * 3 + 64),
            nn.Linear(d_model * 3 + 64, 192),
            nn.GELU(),
            nn.Linear(192, N_ARGS),
        )

    def forward_states(
        self,
        h_x: torch.Tensor,
        pad_mask: torch.Tensor,
        z_x: torch.Tensor,
        z_hat_y: torch.Tensor,
        line_pos: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        delta_z = z_hat_y - z_x
        gamma, beta = self.film(torch.cat([z_hat_y, delta_z], dim=-1)).chunk(2, dim=-1)
        h_dec = h_x * (1.0 + 0.2 * torch.tanh(gamma.unsqueeze(1))) + 0.2 * beta.unsqueeze(1)
        memory = self.mem_proj(torch.stack([z_x, z_hat_y, delta_z], dim=1))
        for blk in self.dec_layers:
            h_dec = blk(h_dec, memory, pad_mask)

        # Gather per-line representations at <L0>..<L127> positions
        gather_idx = line_pos.unsqueeze(-1).expand(-1, -1, h_dec.size(-1))
        line_states = torch.gather(h_dec, dim=1, index=gather_idx)
        line_logits = self.line_head(line_states).squeeze(-1)
        line_valid = line_pos > 0
        line_logits = line_logits.masked_fill(~line_valid, -1e4)
        pooled = h_dec[:, 0, :]
        return pooled, delta_z, line_states, line_logits

    def score_op_and_arg(
        self,
        pooled: torch.Tensor,
        delta_z: torch.Tensor,
        sel_line_state: torch.Tensor,
        op_ids: torch.Tensor | None = None,
    ) -> tuple[torch.Tensor, torch.Tensor | None]:
        ctx = torch.cat([pooled, sel_line_state, delta_z], dim=-1)
        op_logits = self.op_head(ctx)
        if op_ids is None:
            return op_logits, None
        arg_ctx = torch.cat([ctx, self.op_emb(op_ids)], dim=-1)
        arg_logits = self.arg_head(arg_ctx)
        return op_logits, arg_logits


class FormJEPAv1(nn.Module):
    """Complete Joint Embedding Predictive Architecture + Latent Edit Proposer (`FormJEPA-v1`)."""

    def __init__(self, vocab_size: int = VOCAB_SIZE) -> None:
        super().__init__()
        self.context_encoder = FormTransformerEncoder(vocab_size=vocab_size, d_model=D_MODEL)
        self.target_encoder = copy.deepcopy(self.context_encoder)
        for p in self.target_encoder.parameters():
            p.requires_grad = False
        self.predictor = LatentPredictor(d_model=D_MODEL, d_rule=D_RULE)
        self.decoder = LatentEditDecoder(d_model=D_MODEL)

    @torch.no_grad()
    def update_ema(self, tau: float = 0.996) -> None:
        for p_t, p_c in zip(self.target_encoder.parameters(), self.context_encoder.parameters()):
            p_t.data.mul_(tau).add_(p_c.data, alpha=1.0 - tau)

    @torch.no_grad()
    def encode_target(self, y_ids: torch.Tensor, y_dmask: torch.Tensor) -> torch.Tensor:
        _, z_y = self.target_encoder(y_ids, y_dmask)
        return z_y

    def trainable_param_count(self) -> int:
        return sum(p.numel() for p in self.parameters() if p.requires_grad)

    def total_param_count_with_ema(self) -> int:
        return sum(p.numel() for p in self.parameters())


def vicreg_var_cov_loss(z: torch.Tensor, gamma: float = 1.0) -> tuple[torch.Tensor, torch.Tensor]:
    """VICReg variance hinge + off-diagonal covariance regularization."""
    z = z.float()
    bsz, dim = z.shape
    if bsz < 4:
        zero = torch.zeros((), device=z.device)
        return zero, zero
    z_centered = z - z.mean(dim=0, keepdim=True)
    std = torch.sqrt(z_centered.var(dim=0, unbiased=False) + 1e-4)
    var_loss = F.relu(gamma - std).mean()
    cov = (z_centered.T @ z_centered) / max(1, bsz - 1)
    off_diag = cov.pow(2).sum() - cov.diagonal().pow(2).sum()
    cov_loss = off_diag / dim
    return var_loss, cov_loss


@torch.no_grad()
def compute_latent_spectrum_metrics(
    model: FormJEPAv1,
    val_tensors: dict[str, torch.Tensor],
    batch_size: int = 128,
) -> dict[str, float]:
    """Compute effective rank, coordinate std, and positive-vs-random cosine similarity."""
    model.eval()
    zx_list, zy_list, zhat_list = [], [], []
    n = val_tensors["x_ids"].size(0)
    for s in range(0, n, batch_size):
        x_ids = val_tensors["x_ids"][s:s + batch_size]
        x_dm = val_tensors["x_dm"][s:s + batch_size]
        y_ids = val_tensors["y_ids"][s:s + batch_size]
        y_dm = val_tensors["y_dm"][s:s + batch_size]
        r_ids = val_tensors["rule_id"][s:s + batch_size]
        _, z_x = model.context_encoder(x_ids, x_dm)
        z_y = model.encode_target(y_ids, y_dm)
        z_hat = model.predictor(z_x, r_ids)
        zx_list.append(z_x.float().cpu())
        zy_list.append(z_y.float().cpu())
        zhat_list.append(z_hat.float().cpu())

    zx = torch.cat(zx_list, dim=0)
    zy = torch.cat(zy_list, dim=0)
    zhat = torch.cat(zhat_list, dim=0)

    def _erank_and_std(mat: torch.Tensor) -> tuple[float, float]:
        c = mat - mat.mean(dim=0, keepdim=True)
        std_mean = float(c.std(dim=0, unbiased=False).mean().item())
        sv = torch.linalg.svdvals(c)
        p = sv / sv.sum().clamp(min=1e-12)
        ent = -(p * torch.log(p.clamp(min=1e-12))).sum().item()
        return float(math.exp(ent)), std_mean

    erank_zx, std_zx = _erank_and_std(zx)
    erank_zy, std_zy = _erank_and_std(zy)
    erank_zhat, std_zhat = _erank_and_std(zhat)

    pos_cos = float(F.cosine_similarity(zhat, zy, dim=-1).mean().item())
    perm = torch.roll(zy, shifts=17, dims=0)
    neg_cos = float(F.cosine_similarity(zhat, perm, dim=-1).mean().item())
    l2_pos = float((zhat - zy).pow(2).sum(dim=-1).mean().item())
    l2_neg = float((zhat - perm).pow(2).sum(dim=-1).mean().item())

    return {
        "effective_rank_z_x": round(erank_zx, 3),
        "effective_rank_z_y": round(erank_zy, 3),
        "effective_rank_z_hat_y": round(erank_zhat, 3),
        "mean_coord_std_z_x": round(std_zx, 4),
        "mean_coord_std_z_y": round(std_zy, 4),
        "mean_coord_std_z_hat_y": round(std_zhat, 4),
        "pos_pair_cosine_sim": round(pos_cos, 4),
        "random_pair_cosine_sim": round(neg_cos, 4),
        "cosine_gap_pos_minus_rand": round(pos_cos - neg_cos, 4),
        "pos_pair_l2_energy": round(l2_pos, 4),
        "random_pair_l2_energy": round(l2_neg, 4),
    }


def tensorize_examples(examples: list[dict[str, Any]], tok: FormSExprTokenizer) -> dict[str, torch.Tensor]:
    n = len(examples)
    x_ids = torch.zeros((n, MAX_SEQ_LEN), dtype=torch.long)
    x_dm = torch.zeros((n, MAX_SEQ_LEN), dtype=torch.long)
    x_lpos = torch.zeros((n, MAX_LINES), dtype=torch.long)
    y_ids = torch.zeros((n, MAX_SEQ_LEN), dtype=torch.long)
    y_dm = torch.zeros((n, MAX_SEQ_LEN), dtype=torch.long)
    rule_id = torch.zeros((n,), dtype=torch.long)
    tgt_line_slot = torch.zeros((n,), dtype=torch.long)
    tgt_op = torch.zeros((n,), dtype=torch.long)
    tgt_arg = torch.zeros((n,), dtype=torch.long)

    for i, ex in enumerate(examples):
        rc = ex["checker_rule_code"]
        dl = ex.get("diag_line")
        xi, xd, lpos, win = tok.encode(ex["broken_form"], rule_code=rc, diag_line_1based=dl)
        yi, yd, _, _ = tok.encode(ex["nameless_valid_form"], rule_code="OK", diag_line_1based=None)
        x_ids[i] = torch.tensor(xi, dtype=torch.long)
        x_dm[i] = torch.tensor(xd, dtype=torch.long)
        x_lpos[i] = torch.tensor(lpos, dtype=torch.long)
        y_ids[i] = torch.tensor(yi, dtype=torch.long)
        y_dm[i] = torch.tensor(yd, dtype=torch.long)
        rule_id[i] = RULE_TO_ID.get(rc, RULE_TO_ID["UNK_RULE"])

        orig_li = ex["edit_op_and_span"]["line_idx"]
        if orig_li in win:
            slot = win.index(orig_li)
        else:
            slot = min(range(len(win)), key=lambda s: abs(win[s] - orig_li))
        if lpos[slot] == 0:
            # Clamp to last non-zero encoded line slot
            nz = [s for s, p in enumerate(lpos) if p > 0]
            slot = nz[-1] if nz else 0
        tgt_line_slot[i] = slot
        tgt_op[i] = min(N_OPS - 1, max(0, int(ex["edit_op_and_span"]["op_id"])))
        tgt_arg[i] = min(N_ARGS - 1, max(0, int(ex["edit_op_and_span"]["arg_id"])))

    return {
        "x_ids": x_ids,
        "x_dm": x_dm,
        "x_lpos": x_lpos,
        "y_ids": y_ids,
        "y_dm": y_dm,
        "rule_id": rule_id,
        "tgt_line_slot": tgt_line_slot,
        "tgt_op": tgt_op,
        "tgt_arg": tgt_arg,
    }


# ============================================================================
# Latent-Guided Beam Proposal Engine (`k = 1` Greedy & `k = 16` Latent Beam)
# ============================================================================

@torch.no_grad()
def propose_form_jepa_candidates(
    model: FormJEPAv1,
    tok: FormSExprTokenizer,
    stdlib_cat: dict[str, Any],
    broken_src: str,
    diag_text: str,
    beam_k: int = 16,
    pool_size: int = 28,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    """
    Generate up to `beam_k` distinct candidate Form edits using FormJEPA-v1:
      1. Context Encoder E_theta(x, r) -> (H_x, z_x)
      2. Latent Predictor P_phi(z_x, e_r) -> z_hat_y
      3. Edit Decoder D_psi(H_x, z_x, z_hat_y) -> top candidate (line, op, arg) actions
      4. Latent Energy Reranker: ranks distinct decoded candidates by
         E_total = ||z_hat_y - E_ema(y_cand)||_2^2 - 0.35 * log_prob(action)
    """
    t0 = time.perf_counter()
    model.eval()
    rule_code, diag_line, diag_names = parse_diagnostic(diag_text)
    xi, xd, lpos, win = tok.encode(broken_src, rule_code=rule_code, diag_line_1based=diag_line)
    lx = max(16, sum(1 for t in xi if t != 0))
    x_ids = torch.tensor([xi[:lx]], dtype=torch.long)
    x_dm = torch.tensor([xd[:lx]], dtype=torch.long)
    x_lpos = torch.tensor([[p if p < lx else 0 for p in lpos]], dtype=torch.long)
    r_ids = torch.tensor([RULE_TO_ID.get(rule_code, RULE_TO_ID["UNK_RULE"])], dtype=torch.long)

    h_x, z_x = model.context_encoder(x_ids, x_dm)
    z_hat_y = model.predictor(z_x, r_ids)
    pooled, delta_z, line_states, line_logits = model.decoder.forward_states(
        h_x, x_ids == 0, z_x, z_hat_y, x_lpos
    )
    line_logp = F.log_softmax(line_logits[0], dim=-1)
    valid_slots = [s for s, p in enumerate(lpos) if p > 0 and s < len(win)]
    if not valid_slots:
        valid_slots = [0]

    top_line_k = min(6 if beam_k > 1 else 3, len(valid_slots))
    top_slots = sorted(valid_slots, key=lambda s: float(line_logp[s].item()), reverse=True)[:top_line_k]

    # Score (line_slot, op_id, arg_id) combinations
    scored_actions: list[tuple[float, int, int, int]] = []
    for s in top_slots:
        sel_state = line_states[:, s, :]
        op_logits, _ = model.decoder.score_op_and_arg(pooled, delta_z, sel_state, None)
        op_logp = F.log_softmax(op_logits[0], dim=-1)
        top_ops = torch.topk(op_logp, k=min(4 if beam_k > 1 else 2, N_OPS)).indices.tolist()
        for op_id in top_ops:
            op_t = torch.tensor([op_id], dtype=torch.long)
            _, arg_logits = model.decoder.score_op_and_arg(pooled, delta_z, sel_state, op_t)
            assert arg_logits is not None
            arg_logp = F.log_softmax(arg_logits[0], dim=-1)
            top_args = torch.topk(arg_logp, k=min(5 if beam_k > 1 else 2, N_ARGS)).indices.tolist()
            for arg_id in top_args:
                lp = float(line_logp[s].item() + op_logp[op_id].item() + arg_logp[arg_id].item())
                scored_actions.append((lp, win[s], op_id, arg_id))

    scored_actions.sort(key=lambda t: t[0], reverse=True)

    target_pool = 1 if beam_k == 1 else pool_size
    seen_texts: set[str] = {broken_src}
    raw_cands: list[dict[str, Any]] = []
    for lp, orig_li, op_id, arg_id in scored_actions:
        cand_src = apply_edit(broken_src, orig_li, op_id, arg_id, stdlib_cat, diag_names)
        if cand_src in seen_texts:
            continue
        seen_texts.add(cand_src)
        raw_cands.append({
            "text": cand_src,
            "action_logp": round(lp, 4),
            "line_idx": orig_li,
            "op_id": op_id,
            "op_name": EDIT_OP_NAMES[op_id],
            "arg_id": arg_id,
            "step": 1,
        })
        if len(raw_cands) >= target_pool:
            break

    # Multi-step latent rollout (step 2) for beam_k > 1 when module has compound defects
    # (e.g. W-CAP-3 + W-WORLD-1 or multiple `.len()` sites on text values)
    if beam_k > 1 and raw_cands:
        seeds_step2 = raw_cands[:4]
        for sc in seeds_step2:
            if len(raw_cands) >= target_pool + 8:
                break
            xi2, xd2, lpos2, win2 = tok.encode(sc["text"], rule_code=rule_code, diag_line_1based=diag_line)
            lx2 = max(16, sum(1 for t in xi2 if t != 0))
            x2_t = torch.tensor([xi2[:lx2]], dtype=torch.long)
            d2_t = torch.tensor([xd2[:lx2]], dtype=torch.long)
            lp2_t = torch.tensor([[p if p < lx2 else 0 for p in lpos2]], dtype=torch.long)
            h2, zx2 = model.context_encoder(x2_t, d2_t)
            zhat2 = model.predictor(zx2, r_ids)
            p2, dz2, ls2, ll2 = model.decoder.forward_states(h2, x2_t == 0, zx2, zhat2, lp2_t)
            ll2_logp = F.log_softmax(ll2[0], dim=-1)
            vslots2 = [s for s, p in enumerate(lpos2) if p > 0 and s < len(win2)] or [0]
            best_s2 = sorted(vslots2, key=lambda s: float(ll2_logp[s].item()), reverse=True)[:3]
            for s2 in best_s2:
                op2_logits, _ = model.decoder.score_op_and_arg(p2, dz2, ls2[:, s2, :], None)
                op2_logp = F.log_softmax(op2_logits[0], dim=-1)
                for op2 in torch.topk(op2_logp, k=2).indices.tolist():
                    _, arg2_logits = model.decoder.score_op_and_arg(
                        p2, dz2, ls2[:, s2, :], torch.tensor([op2], dtype=torch.long)
                    )
                    assert arg2_logits is not None
                    arg2_logp = F.log_softmax(arg2_logits[0], dim=-1)
                    arg2 = int(torch.argmax(arg2_logp).item())
                    cand2 = apply_edit(sc["text"], win2[s2], op2, arg2, stdlib_cat, diag_names)
                    if cand2 not in seen_texts:
                        seen_texts.add(cand2)
                        raw_cands.append({
                            "text": cand2,
                            "action_logp": round(sc["action_logp"] + float(ll2_logp[s2] + op2_logp[op2] + arg2_logp[arg2]), 4),
                            "line_idx": win2[s2],
                            "op_id": op2,
                            "op_name": f"{sc['op_name']}+{EDIT_OP_NAMES[op2]}",
                            "arg_id": arg2,
                            "step": 2,
                        })

    if not raw_cands:
        return [], {"wall_ms": round((time.perf_counter() - t0) * 1000.0, 3)}

    # Batch-score all candidates with EMA Target Encoder E_ema(y_cand) for Latent Energy Reranking!
    cy_ids_full = torch.zeros((len(raw_cands), MAX_SEQ_LEN), dtype=torch.long)
    cy_dm_full = torch.zeros((len(raw_cands), MAX_SEQ_LEN), dtype=torch.long)
    for idx, rc_item in enumerate(raw_cands):
        yi, yd, _, _ = tok.encode(rc_item["text"], rule_code="OK", diag_line_1based=None)
        cy_ids_full[idx] = torch.tensor(yi, dtype=torch.long)
        cy_dm_full[idx] = torch.tensor(yd, dtype=torch.long)
    cly = max(16, int((cy_ids_full != 0).sum(dim=1).max().item()))
    z_cands = model.encode_target(cy_ids_full[:, :cly], cy_dm_full[:, :cly])
    z_hat_rep = z_hat_y.expand_as(z_cands)
    l2_dists = (z_hat_rep - z_cands).pow(2).sum(dim=-1).tolist()

    for rc_item, l2_val in zip(raw_cands, l2_dists):
        rc_item["latent_l2_energy"] = round(float(l2_val), 4)
        # Combined energy score: latent world-model distance regularized by decoder negative log-likelihood
        rc_item["combined_energy"] = round(float(l2_val) - 0.35 * rc_item["action_logp"], 4)

    if beam_k > 1:
        raw_cands.sort(key=lambda d: d["combined_energy"])
    selected = raw_cands[:beam_k]
    return selected, {"wall_ms": round((time.perf_counter() - t0) * 1000.0, 3)}


# ============================================================================
# Main Training Entrypoint
# ============================================================================

def main() -> None:
    set_all_seeds(SEED)
    torch.set_num_threads(min(16, os.cpu_count() or 8))
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Verify PREREG_form_jepa_v1.json SHA-256 before doing any work
    prereg_bytes = PREREG_PATH.read_bytes()
    actual_prereg_sha = sha256_bytes(prereg_bytes)
    pinned_prereg_sha = PREREG_SHA_PATH.read_text(encoding="utf-8").split()[0]
    if actual_prereg_sha != pinned_prereg_sha:
        raise RuntimeError(f"PREREG SHA-256 mismatch: {actual_prereg_sha} != {pinned_prereg_sha}")
    prereg = json.loads(prereg_bytes.decode("utf-8"))

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
        raise RuntimeError(f"Upstream benchmark SHA mismatch: 151={sha_151}, 40={sha_40}")
    print(f"[FormJEPA-v1] Pre-registration verified: {actual_prereg_sha[:16]}...")

    # 2. Build public stdlib catalog & disjoint Form pool
    t_corpus_start = time.perf_counter()
    stdlib_cat = build_stdlib_catalog(RCE_REPO)
    disjoint_forms, leakage_audit = build_disjoint_form_pool(
        RCE_BIN, RCE_REPO, tasks_151_path, residual_40_path, forms_jsonl_path, workers=24
    )
    print(
        f"[FormJEPA-v1] Disjoint valid Forms extracted: {len(disjoint_forms)} unique shapes "
        f"(0 overlap with 151 ladder / 40 residual tasks)"
    )

    # Split disjoint Form shapes by shape_hash[:16] % 10 -> 0..7 train, 8 val, 9 test
    train_forms, val_forms, test_forms = [], [], []
    for f in disjoint_forms:
        bucket = int(f["shape_hash"][:16], 16) % 10
        if bucket < 8:
            train_forms.append(f)
        elif bucket == 8:
            val_forms.append(f)
        else:
            test_forms.append(f)

    # Generate checker-verified defect pairs in parallel
    def _gen_split(forms_slice: list[dict[str, Any]], max_per: int, offset: int) -> list[dict[str, Any]]:
        tasks_args = [
            (str(RCE_BIN), f, stdlib_cat, offset + idx, max_per)
            for idx, f in enumerate(forms_slice)
        ]
        out_rows: list[dict[str, Any]] = []
        with concurrent.futures.ProcessPoolExecutor(max_workers=28) as ex:
            for batch in ex.map(_verify_defect_worker, tasks_args, chunksize=4):
                out_rows.extend(batch)
        return out_rows

    raw_train = _gen_split(train_forms, max_per=16, offset=0)
    raw_val = _gen_split(val_forms, max_per=14, offset=100_000)
    raw_test = _gen_split(test_forms, max_per=14, offset=200_000)

    rng_split = SplitMix64(SEED)
    rng_split.shuffle(raw_train)
    rng_split.shuffle(raw_val)
    rng_split.shuffle(raw_test)

    train_examples = raw_train[:10_500]
    val_examples = raw_val[:500]
    test_examples = raw_test[:200]
    corpus_wall_s = round(time.perf_counter() - t_corpus_start, 2)

    print(
        f"[FormJEPA-v1] Checker-verified dataset built in {corpus_wall_s}s: "
        f"train={len(train_examples)}, val={len(val_examples)}, test={len(test_examples)}"
    )

    # Persist val_500.jsonl, test_200.jsonl, and stdlib_catalog.json in WORK_DIR for evaluation
    (WORK_DIR / "stdlib_catalog.json").write_text(
        json.dumps(stdlib_cat, sort_keys=True) + "\n", encoding="utf-8"
    )
    for fname, rows in [("val_500.jsonl", val_examples), ("test_200.jsonl", test_examples)]:
        with open(WORK_DIR / fname, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n")

    tok = FormSExprTokenizer(stdlib_cat["ordered_mods"])
    train_tensors = tensorize_examples(train_examples, tok)
    val_tensors = tensorize_examples(val_examples, tok)

    # 3. Initialize FormJEPA-v1 and log pre-training (epoch 0) spectrum metrics
    set_all_seeds(SEED)
    model = FormJEPAv1(vocab_size=VOCAB_SIZE)
    trainable_params = model.trainable_param_count()
    total_params = model.total_param_count_with_ema()
    print(
        f"[FormJEPA-v1] Initialized model: trainable_params={trainable_params:,}, "
        f"total_with_ema={total_params:,}, vocab_used={len(tok.tok2id)}"
    )

    pre_spectrum = compute_latent_spectrum_metrics(model, val_tensors)
    print(f"[FormJEPA-v1] Pre-train spectrum: {pre_spectrum}")

    # 4. Train FormJEPA-v1 with Smooth-L1 + VICReg + Edit Supervision + EMA Target Updates
    epochs = 12
    batch_size = 192
    lr = 7e-4
    optimizer = torch.optim.AdamW(
        [p for p in model.parameters() if p.requires_grad], lr=lr, weight_decay=1e-2
    )
    n_train = train_tensors["x_ids"].size(0)
    steps_per_epoch = math.ceil(n_train / batch_size)
    total_steps = epochs * steps_per_epoch
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=total_steps, eta_min=2e-5)

    # Precompute non-pad token lengths for length-bucketed mini-batching (with per-epoch jitter)
    base_lengths = (train_tensors["x_ids"] != 0).sum(dim=1).float() + 0.5 * (train_tensors["y_ids"] != 0).sum(dim=1).float()

    rapl_start = read_rapl_uj()
    t_train_start = time.perf_counter()
    epoch_history: list[dict[str, Any]] = []
    best_val_score = -1e9
    best_state: dict[str, torch.Tensor] | None = None

    for ep in range(1, epochs + 1):
        model.train()
        # Length-bucketed ordering with Gaussian jitter so batches stay well-mixed yet compact
        noisy_len = base_lengths + torch.randn_like(base_lengths) * 14.0
        sorted_idx = torch.argsort(noisy_len)
        chunks = [sorted_idx[s:s + batch_size] for s in range(0, n_train, batch_size)]
        chunk_order = torch.randperm(len(chunks)).tolist()
        sum_pred, sum_var, sum_cov, sum_edit = 0.0, 0.0, 0.0, 0.0
        n_batches = 0

        for ci in chunk_order:
            idx = chunks[ci]
            x_ids_full = train_tensors["x_ids"][idx]
            y_ids_full = train_tensors["y_ids"][idx]
            # Dynamic sequence length trimming per mini-batch (exact same math, ~8x faster!)
            lx = max(16, int((x_ids_full != 0).sum(dim=1).max().item()))
            ly = max(16, int((y_ids_full != 0).sum(dim=1).max().item()))
            x_ids = x_ids_full[:, :lx]
            x_dm = train_tensors["x_dm"][idx][:, :lx]
            x_lpos = train_tensors["x_lpos"][idx].clamp(max=lx - 1)
            # Zero out line positions that exceeded trimmed length
            x_lpos = torch.where(train_tensors["x_lpos"][idx] < lx, x_lpos, torch.zeros_like(x_lpos))
            y_ids = y_ids_full[:, :ly]
            y_dm = train_tensors["y_dm"][idx][:, :ly]
            r_ids = train_tensors["rule_id"][idx]
            t_line = train_tensors["tgt_line_slot"][idx]
            t_op = train_tensors["tgt_op"][idx]
            t_arg = train_tensors["tgt_arg"][idx]

            optimizer.zero_grad(set_to_none=True)
            h_x, z_x = model.context_encoder(x_ids, x_dm)
            with torch.no_grad():
                z_y = model.encode_target(y_ids, y_dm)
            z_hat_y = model.predictor(z_x, r_ids)

            loss_pred = F.smooth_l1_loss(z_hat_y, z_y, beta=0.5)
            var_x, cov_x = vicreg_var_cov_loss(z_x)
            var_h, cov_h = vicreg_var_cov_loss(z_hat_y)
            loss_var = 0.5 * (var_x + var_h)
            loss_cov = 0.5 * (cov_x + cov_h)

            pooled, delta_z, line_states, line_logits = model.decoder.forward_states(
                h_x, x_ids == 0, z_x, z_hat_y, x_lpos
            )
            bsz_cur = x_ids.size(0)
            sel_line_state = line_states[torch.arange(bsz_cur), t_line]
            op_logits, arg_logits = model.decoder.score_op_and_arg(pooled, delta_z, sel_line_state, t_op)
            assert arg_logits is not None

            loss_line = F.cross_entropy(line_logits, t_line)
            loss_op = F.cross_entropy(op_logits, t_op)
            loss_arg = F.cross_entropy(arg_logits, t_arg)
            loss_edit = loss_line + loss_op + loss_arg

            loss = 2.0 * loss_pred + 1.0 * loss_var + 0.04 * loss_cov + loss_edit

            loss.backward()
            torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 1.0)
            optimizer.step()
            scheduler.step()
            model.update_ema(tau=0.996)

            sum_pred += float(loss_pred.item())
            sum_var += float(loss_var.item())
            sum_cov += float(loss_cov.item())
            sum_edit += float(loss_edit.item())
            n_batches += 1

        # Evaluate validation edit accuracy + latent cosine gap
        model.eval()
        with torch.no_grad():
            vx_full = val_tensors["x_ids"]
            vy_full = val_tensors["y_ids"]
            vlx = max(16, int((vx_full != 0).sum(dim=1).max().item()))
            vly = max(16, int((vy_full != 0).sum(dim=1).max().item()))
            vx_ids = vx_full[:, :vlx]
            vx_dm = val_tensors["x_dm"][:, :vlx]
            vx_lp = torch.where(val_tensors["x_lpos"] < vlx, val_tensors["x_lpos"], torch.zeros_like(val_tensors["x_lpos"]))
            vr_ids = val_tensors["rule_id"]
            vt_line = val_tensors["tgt_line_slot"]
            vt_op = val_tensors["tgt_op"]
            vt_arg = val_tensors["tgt_arg"]

            vh_x, vz_x = model.context_encoder(vx_ids, vx_dm)
            vz_y = model.encode_target(vy_full[:, :vly], val_tensors["y_dm"][:, :vly])
            vz_hat = model.predictor(vz_x, vr_ids)
            vp, vdz, vls, vll = model.decoder.forward_states(vh_x, vx_ids == 0, vz_x, vz_hat, vx_lp)
            pred_line = vll.argmax(dim=-1)
            line_acc = float((pred_line == vt_line).float().mean().item())

            vsel = vls[torch.arange(vx_ids.size(0)), vt_line]
            vop_l, varg_l = model.decoder.score_op_and_arg(vp, vdz, vsel, vt_op)
            assert varg_l is not None
            op_acc = float((vop_l.argmax(dim=-1) == vt_op).float().mean().item())
            arg_acc = float((varg_l.argmax(dim=-1) == vt_arg).float().mean().item())
            joint_acc = float(
                ((pred_line == vt_line) & (vop_l.argmax(dim=-1) == vt_op) & (varg_l.argmax(dim=-1) == vt_arg))
                .float()
                .mean()
                .item()
            )
            val_cos = float(F.cosine_similarity(vz_hat, vz_y, dim=-1).mean().item())

        score = joint_acc + 0.25 * val_cos
        if score > best_val_score:
            best_val_score = score
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}

        row = {
            "epoch": ep,
            "train_smooth_l1": round(sum_pred / n_batches, 4),
            "train_vicreg_var": round(sum_var / n_batches, 4),
            "train_vicreg_cov": round(sum_cov / n_batches, 4),
            "train_edit_ce": round(sum_edit / n_batches, 4),
            "val_line_acc": round(line_acc, 4),
            "val_op_acc": round(op_acc, 4),
            "val_arg_acc": round(arg_acc, 4),
            "val_joint_exact_acc": round(joint_acc, 4),
            "val_latent_cos": round(val_cos, 4),
        }
        epoch_history.append(row)
        print(
            f"  [ep {ep:02d}/{epochs}] pred={row['train_smooth_l1']:.4f} var={row['train_vicreg_var']:.4f} "
            f"edit_ce={row['train_edit_ce']:.4f} | val_line={line_acc:.3f} op={op_acc:.3f} "
            f"arg={arg_acc:.3f} joint={joint_acc:.3f} cos={val_cos:.3f}"
        )

    train_wall_s = round(time.perf_counter() - t_train_start, 3)
    rapl_end = read_rapl_uj()
    train_pkg_reported_j = delta_rapl_j(rapl_start, rapl_end, "package_uj")
    train_core_reported_j = delta_rapl_j(rapl_start, rapl_end, "core_uj")

    if best_state is not None:
        model.load_state_dict(best_state)
    post_spectrum = compute_latent_spectrum_metrics(model, val_tensors)
    print(f"[FormJEPA-v1] Post-train spectrum: {post_spectrum}")

    # Save checkpoint in WORK_DIR (not committed to git; SHA-256 recorded in train_metrics.json)
    ckpt_path = WORK_DIR / "form_jepa_v1.pt"
    torch.save(
        {
            "arch": "FormJEPA-v1",
            "seed": SEED,
            "vocab_size": VOCAB_SIZE,
            "d_model": D_MODEL,
            "n_heads": N_HEADS,
            "n_enc_layers": N_ENC_LAYERS,
            "n_dec_layers": N_DEC_LAYERS,
            "stdlib_ordered_mods": stdlib_cat["ordered_mods"],
            "state_dict": model.state_dict(),
        },
        ckpt_path,
    )
    ckpt_bytes = ckpt_path.read_bytes()
    ckpt_sha256 = sha256_bytes(ckpt_bytes)

    train_summary = {
        "schema": "openie-form-jepa-v1-train-receipt/1",
        "completed_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "prereg_id": prereg["id"],
        "prereg_sha256": actual_prereg_sha,
        "seed": SEED,
        "architecture": {
            "name": "FormJEPA-v1",
            "d_model": D_MODEL,
            "d_rule": D_RULE,
            "n_heads": N_HEADS,
            "context_encoder_layers": N_ENC_LAYERS,
            "ema_target_encoder_layers": N_ENC_LAYERS,
            "ema_tau": 0.996,
            "predictor_layers": 3,
            "edit_decoder_layers": N_DEC_LAYERS,
            "vocab_capacity": VOCAB_SIZE,
            "vocab_active_tokens": len(tok.tok2id),
            "trainable_parameters": trainable_params,
            "total_parameters_including_ema": total_params,
            "checkpoint_bytes": len(ckpt_bytes),
            "checkpoint_sha256": ckpt_sha256,
        },
        "leakage_and_corpus_audit": {
            **leakage_audit,
            "disjoint_train_forms": len(train_forms),
            "disjoint_val_forms": len(val_forms),
            "disjoint_test_forms": len(test_forms),
            "train_examples_count": len(train_examples),
            "val_examples_count": len(val_examples),
            "test_examples_count": len(test_examples),
            "train_by_defect_tag": dict(sorted(Counter(x["defect_tag"] for x in train_examples).items())),
            "train_by_rule_code": dict(sorted(Counter(x["checker_rule_code"] for x in train_examples).items())),
            "val_500_sha256": sha256_bytes((WORK_DIR / "val_500.jsonl").read_bytes()),
            "test_200_sha256": sha256_bytes((WORK_DIR / "test_200.jsonl").read_bytes()),
            "dataset_generation_wall_s": corpus_wall_s,
        },
        "anti_collapse_verification": {
            "pre_training_epoch_0": pre_spectrum,
            "post_training_best_ckpt": post_spectrum,
            "falsifier_F1_collapse_triggered": (
                post_spectrum["effective_rank_z_x"] < 16.0
                or post_spectrum["effective_rank_z_y"] < 16.0
                or post_spectrum["mean_coord_std_z_x"] < 0.25
            ),
        },
        "training_telemetry": {
            "epochs": epochs,
            "batch_size": batch_size,
            "wall_clock_s": train_wall_s,
            "reported_j_rapl_package": train_pkg_reported_j,
            "reported_j_rapl_core": train_core_reported_j,
            "est_j": None,
            "measured_j": None,
            "board_metered": False,
            "note": "Linux powercap intel-rapl:0 gross counter on shared build host ($BENCH_ROOT); dedicated single-inference RAPL microbenchmark recorded separately in eval_form_jepa_and_rung_f.py.",
        },
        "epoch_history": epoch_history,
    }
    out_json = WORK_DIR / "train_metrics.json"
    out_json.write_text(json.dumps(train_summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"[FormJEPA-v1] Training complete in {train_wall_s}s | "
        f"RAPL pkg reported_j={train_pkg_reported_j} J | ckpt sha256={ckpt_sha256[:16]}..."
    )


if __name__ == "__main__":
    main()
