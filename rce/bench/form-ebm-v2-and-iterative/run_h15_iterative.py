#!/usr/bin/env python3
"""
H15-Iterative: Bounded Checker-Feedback + Public Stdlib Signature Repair Runner
on the 40 Open Residual Tasks of `rce/bench/ladder/rung-e/` (`openIE-dev/rce` `1762fb4b`).

Strict provenance, zero-leakage, and safety guarantees:
  1. Verifies `PREREG_h15_iterative.json` against `PREREG_h15_iterative.json.sha256` and
     `residual_40_tasks.jsonl` SHA-256 before executing a single call.
  2. Strips `task["original"]` before entering the multi-turn proposer loop (`max_turns = 5`):
     proposers see ONLY `task["mutant"]` (or their own prior candidate), public declaration
     headers (`pub const`, `pub struct`, `pub kind`, `pub fn` without bodies) of imported
     `stdlib/lib/*.rce` modules (strictly excluding `task["path"]` itself), and verbatim
     sanitized `rce check` + obligation-preservation diagnostics.
  3. Loads cloud API keys strictly in memory via `discover_cloud_keys()`; never prints, logs,
     or persists any secret or user home directory path.
  4. Executes all `rce check`, `rce fmt nameless`, `rce hash`, and `rce equiv` calls on the
     configured benchmark host (`RCE_SSH_HOST` or local `RCE_BIN`), crystallizes admitted
     repairs into a `DNULLMM1` Gear-0 store, and verifies `t = 2` zero-call replay.
"""

from __future__ import annotations

import base64
import concurrent.futures
import hashlib
import json
import mmap
import os
import re
import struct
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PREREG_PATH = HERE / "PREREG_h15_iterative.json"
PREREG_SHA_PATH = HERE / "PREREG_h15_iterative.json.sha256"
RESULTS_DIR = HERE / "results"

RCE_SSH_HOST = os.environ.get("RCE_SSH_HOST", "")
REMOTE_BENCH_ROOT = os.environ.get("REMOTE_BENCH_ROOT", "/tmp/wave4_rce_jepa_v2")
LOCAL_BENCH_ROOT = Path(os.environ.get("BENCH_ROOT", str(HERE.parent)))
LOCAL_RCE_BIN = Path(
    os.environ.get("RCE_BIN", str(LOCAL_BENCH_ROOT / "rce/spec/checker/target/release/rce"))
)

PRICING_PER_1M_USD = {
    "claude-opus-5-5": (5.00, 25.00),
    "claude-sonnet-5-5": (3.00, 15.00),
    "xai:grok-4.20-0309-reasoning": (2.00, 10.00),
}

SYSTEM_RCE_DRAFT09 = """You are a program-repair proposer operating behind the deterministic Reality Code Engine (`rce`, specification draft 0.9) admission gate.

Public RCE Draft 0.9 language & well-formedness rules (`SURFACE.md`, `spec/book/04-programs.md`, `spec/book/08-steps-loops-concurrency.md`, `spec/book/09-wellformedness.md`):
1. Indentation-delimited blocks (4 spaces per level), no semicolons or braces around blocks.
2. Modules & built-in standard library (`stdlib/lib/`):
   - `use <mod>` imports a built-in library module (placed right after `module <name>` if a `module` header is present, or at top of file).
   - `#!lib <name>` is retired and parsed only as a comment; replace `#!lib <mod>` with `use <mod>` (and if a file also calls primitives from `crypto`, import `use crypto` as well).
   - Every function, constant, struct, or kind imported via `use <mod>` MUST be qualified with the short module name `<last_segment>.<item>` (for example `crypto.cat(...)`, `crypto.unhex(...)`, `crypto.tohex(...)`, `crypto.MASK`, `enc.Cbor`, `blake3.blake3(...)`), EXCEPT when defining items inside that module itself. Use ONLY exact item names from the provided Public Standard Library Signatures!
3. Steps, totality, and retired `refuse` grammar (`W-SYN-1`):
   - In `intent` `example` lines, write `-> kept: ErrorName` (never `-> refused: ErrorName`).
   - In `step` bodies, write `fail ErrorName` or `try expr else ErrorName` (never `refuse ErrorName`).
4. Text lengths (`W-LEN-1`, F.5.2):
   - `text` has NO `.len()` method (`List` and `Map` still have `.len()`). On `text` values, use `.len_bytes()` for UTF-8 byte count or `.len_chars()` for Unicode scalar count.
5. Foreign calls & capability hygiene (`W-WORLD-1`, `W-CAP-3`, F.4.1, F.5.1):
   - Every `extern "C" fn` must take `w: &World` as its first parameter (`extern "C" fn f(w: &World, ...)`), `fn main(w: &World)` receives `w: &World` and passes `w` as the first argument to every `extern` call, and avoid reserved authority parameter names like `path` when flagged by `W-CAP-3` (rename parameter e.g. `name: &text` consistently across signature and body).
6. Unused bindings (`W-UNUSED-1`), IEEE-754 negative zero (`W-INT-1`), and non-vacuous obligations (`W-MUT-1`):
   - Prefix intentionally unused bindings with `_` (`_x`), and write IEEE-754 negative zero canonically as `-0.0`.
   - Under `W-MUT-1`, every measured `example` or `check` obligation must fail on at least one single-edit mutant of the program expressions its run evaluates. If `rce check` flags an `example` line under `W-MUT-1` (for instance `1e16 + 1.0 == 1e16` where `+` vs `-` both round to `1e16`, or `Start, Start -> kept: Running` where flipping `!=` to `==` already fails on the first `Start`), refine that single vacuous `example`'s inputs/trace so it genuinely distinguishes the step's operator/guard while keeping all other `example` traces and all declarations intact!
7. NEVER delete any `intent`, `example`, `check`, `state`, `event`, `error`, `struct`, `kind`, `fn`, `extern`, or `step` declaration.
"""


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_str(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ============================================================================
# Safe In-Memory Credential Discovery (Zero Secret Printing or Persistence)
# ============================================================================

def _parse_env_file(p: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not p.exists() or not p.is_file():
        return out
    for line in p.read_text(errors="ignore").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        k = k.replace("export ", "").strip()
        v = v.strip().strip('"').strip("'")
        if v and "your_" not in v.lower() and "xxx" not in v.lower():
            out[k] = v
    return out


def discover_cloud_keys() -> dict[str, str]:
    keys: dict[str, str] = {}
    home = Path.home()
    candidates = [home / ".env"]
    extra_env = os.environ.get("DNULL_ENV_FILE")
    if extra_env:
        candidates.insert(0, Path(extra_env))
    vc = home / "data-share/vibe-coding"
    if vc.exists():
        anh = vc / "ai-null-hypothesis/.env"
        if anh.exists():
            candidates.insert(0, anh)
        candidates.extend(sorted(vc.glob("*/.env")))
    for p in candidates:
        for k, v in _parse_env_file(p).items():
            keys.setdefault(k, v)
    for k, v in os.environ.items():
        if k.endswith("_API_KEY") and v:
            keys[k] = v
    return keys


# ============================================================================
# Remote / Local Deterministic RCE Executor (Zero Dev-Host Load)
# ============================================================================

class RceGateway:
    """Executes all `rce` CLI operations remotely via multiplexed SSH or locally."""

    def __init__(self, ssh_host: str, remote_root: str, local_bin: Path) -> None:
        self.ssh_host = ssh_host.strip()
        self.remote_root = remote_root.rstrip("/")
        self.local_bin = local_bin
        self._ctl_dir = tempfile.TemporaryDirectory(prefix="rce_ssh_ctl_")
        self._ctl_sock = str(Path(self._ctl_dir.name) / "cm.sock")

    def _ssh_base(self) -> list[str]:
        return [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", "ControlMaster=auto",
            "-o", f"ControlPath={self._ctl_sock}",
            "-o", "ControlPersist=300",
            self.ssh_host,
        ]

    def close(self) -> None:
        if self.ssh_host and Path(self._ctl_sock).exists():
            subprocess.run(
                ["ssh", "-o", f"ControlPath={self._ctl_sock}", "-O", "exit", self.ssh_host],
                capture_output=True,
            )
        self._ctl_dir.cleanup()

    def run_remote_py(self, py_code: str, payload: dict[str, Any], timeout_s: float = 60.0) -> dict[str, Any]:
        b64_payload = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
        wrapper = (
            "import base64, json, sys\n"
            f"PAYLOAD = json.loads(base64.b64decode('{b64_payload}').decode('utf-8'))\n"
            + py_code
        )
        if self.ssh_host:
            cmd = self._ssh_base() + ["python3", "-"]
        else:
            cmd = ["python3", "-"]
        res = subprocess.run(cmd, input=wrapper, capture_output=True, text=True, timeout=timeout_s)
        if res.returncode != 0:
            raise RuntimeError(f"Gateway call failed (rc={res.returncode}): {res.stderr[:300]}")
        return json.loads(res.stdout)

    def fetch_bootstrap_context(self) -> dict[str, Any]:
        code = r"""
import hashlib, json, re, subprocess, tempfile
from pathlib import Path

root = Path(PAYLOAD["root"])
rce_repo = root / "rce"
exp_repo = root / "openie-research-experiments"
rce_bin = rce_repo / "spec/checker/target/release/rce"
res40_path = exp_repo / "rce/bench/h15-gear0/residual_40_tasks.jsonl"

rce_head = subprocess.check_output(["git", "-C", str(rce_repo), "rev-parse", "HEAD"], text=True).strip()
exp_head = subprocess.check_output(["git", "-C", str(exp_repo), "rev-parse", "HEAD"], text=True).strip()
bin_sha = hashlib.sha256(rce_bin.read_bytes()).hexdigest()
res40_bytes = res40_path.read_bytes()
res40_sha = hashlib.sha256(res40_bytes).hexdigest()

# Rule-set hash
rules_sha = "rce-rules-0.9"
with tempfile.TemporaryDirectory() as td:
    tp = Path(td)
    f = tp / "min.rce"
    rcp = tp / "rcpt.json"
    f.write_text("fn main()\n    emit 1\n", encoding="utf-8")
    r = subprocess.run([str(rce_bin), "check", "write", str(rcp), str(f)], capture_output=True, text=True)
    if r.returncode == 0 and rcp.exists():
        d = json.loads(rcp.read_text(encoding="utf-8"))
        rules_sha = str((d.get("rules") or {}).get("sha256", "rce-rules-0.9"))

# Extract public stdlib headers ONLY (stripping all function bodies `= ...`)
lib_root = rce_repo / "stdlib/lib"
mod_headers = {}
sym_to_mods = {}
for p in sorted(lib_root.rglob("*.rce")):
    rel = p.relative_to(lib_root)
    parts = list(rel.with_suffix("").parts)
    mod_name = ".".join(parts[:-1]) if (len(parts) >= 2 and parts[-1] == parts[-2]) else ".".join(parts)
    lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    sig_lines = []
    exports = []
    i = 0
    while i < len(lines):
        raw = lines[i]
        s = raw.strip()
        if s.startswith("pub fn "):
            # Strip inline body ` = ...` while preserving `-> RetType ! Err bound N`
            hdr = s
            if " = " in hdr:
                hdr = hdr.split(" = ", 1)[0].rstrip()
            sig_lines.append(hdr)
            m = re.match(r"^pub\s+fn\s+([A-Za-z_][A-Za-z0-9_]*)\b", s)
            if m:
                exports.append(m.group(1))
            i += 1
            while i < len(lines) and (lines[i].startswith("    ") or not lines[i].strip()):
                i += 1
            continue
        elif s.startswith("pub const "):
            hdr = s.split(" = ", 1)[0].rstrip() if " = " in s else s
            sig_lines.append(hdr)
            m = re.match(r"^pub\s+const\s+([A-Za-z_][A-Za-z0-9_]*)\b", s)
            if m:
                exports.append(m.group(1))
            i += 1
            continue
        elif s.startswith(("pub struct ", "pub kind ")):
            sig_lines.append(s)
            m = re.match(r"^pub\s+(?:struct|kind)\s+([A-Za-z_][A-Za-z0-9_]*)\b", s)
            if m:
                exports.append(m.group(1))
            i += 1
            while i < len(lines) and lines[i].startswith("    "):
                fl = lines[i].rstrip()
                if not fl.strip().startswith("#"):
                    sig_lines.append("    " + fl.strip())
                i += 1
            continue
        i += 1
    if sig_lines:
        mod_headers[mod_name] = "\n".join(sig_lines)
        for ex in exports:
            sym_to_mods.setdefault(ex, []).append(mod_name)

tasks = [json.loads(l) for l in res40_bytes.decode("utf-8").splitlines() if l.strip()]
# Compute initial diagnostics on mutants
init_diags = []
with tempfile.TemporaryDirectory() as td:
    fp = Path(td) / "prog.rce"
    for t in tasks:
        fp.write_text(t["mutant"], encoding="utf-8")
        r = subprocess.run([str(rce_bin), "check", str(fp)], capture_output=True, text=True, timeout=20.0)
        msg = (r.stdout + r.stderr).replace(str(fp), "prog.rce").replace(td, "<tmp>").strip()
        init_diags.append(msg)

print(json.dumps({
    "rce_head": rce_head,
    "exp_head": exp_head,
    "rce_bin_sha256": bin_sha,
    "res40_sha256": res40_sha,
    "rules_sha": rules_sha,
    "mod_headers": mod_headers,
    "sym_to_mods": sym_to_mods,
    "tasks": tasks,
    "init_diags": init_diags,
}))
"""
        root_str = self.remote_root if self.ssh_host else str(LOCAL_BENCH_ROOT)
        return self.run_remote_py(code, {"root": root_str}, timeout_s=90.0)

    def check_candidate(self, cand_src: str) -> tuple[int, str]:
        code = r"""
import json, subprocess, tempfile
from pathlib import Path
root = Path(PAYLOAD["root"])
rce_bin = root / "rce/spec/checker/target/release/rce"
with tempfile.TemporaryDirectory(prefix="rce_it_") as td:
    fp = Path(td) / "prog.rce"
    fp.write_text(PAYLOAD["src"], encoding="utf-8")
    try:
        r = subprocess.run([str(rce_bin), "check", str(fp)], capture_output=True, text=True, timeout=25.0)
        msg = (r.stdout + r.stderr).replace(str(fp), "prog.rce").replace(td, "<tmp>").strip()
        rc = r.returncode
    except subprocess.TimeoutExpired:
        rc, msg = 124, "timeout"
print(json.dumps({"rc": rc, "diag": msg}))
"""
        root_str = self.remote_root if self.ssh_host else str(LOCAL_BENCH_ROOT)
        out = self.run_remote_py(code, {"root": root_str, "src": cand_src}, timeout_s=35.0)
        return int(out["rc"]), str(out["diag"])

    def posthoc_audit_and_keys(self, items: list[dict[str, Any]], rules_sha: str) -> list[dict[str, Any]]:
        """Post-hoc comparison against `original` + canonical `DNULLMM1` key calculation (called ONLY after all turns finish!)."""
        code = r"""
import hashlib, json, re, subprocess, tempfile
from pathlib import Path

def sha256_str(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

root = Path(PAYLOAD["root"])
rce_bin = str(root / "rce/spec/checker/target/release/rce")
rules_sha = PAYLOAD["rules_sha"]
out_rows = []

with tempfile.TemporaryDirectory(prefix="rce_post_") as td:
    tp = Path(td)
    fo = tp / "orig.rce"
    fc = tp / "cand.rce"
    fm = tp / "mut.rce"

    def prog_hash(p: Path):
        rh = subprocess.run([rce_bin, "hash", str(p)], capture_output=True, text=True, timeout=15.0)
        ls = [l for l in rh.stdout.splitlines() if l.endswith("  program")]
        return ls[-1].split()[0] if rh.returncode == 0 and ls else None

    for it in PAYLOAD["items"]:
        mut = it["mutant"]
        fm.write_text(mut, encoding="utf-8")
        r_nl = subprocess.run([rce_bin, "fmt", "nameless", str(fm)], capture_output=True, text=True, timeout=10.0)
        if r_nl.returncode == 0 and r_nl.stdout.strip():
            bfh = sha256_str("rce-nameless/1\n" + r_nl.stdout.strip())
            used_nl = True
        else:
            norm = "\n".join(ln.rstrip() for ln in mut.strip().splitlines() if not ln.strip().startswith("#"))
            bfh = sha256_str("rce-surface-fallback/1\n" + norm)
            used_nl = False

        equiv = ""
        if it["admitted"] and it["cand"]:
            fo.write_text(it["original"], encoding="utf-8")
            fc.write_text(it["cand"], encoding="utf-8")
            ho, hc = prog_hash(fo), prog_hash(fc)
            if ho and ho == hc:
                equiv = "restored"
            else:
                try:
                    req = subprocess.run([rce_bin, "equiv", "fuel", "2000", str(fo), str(fc)], capture_output=True, text=True, timeout=20.0)
                    equiv = {0: "behaviour-equal", 1: "contradicts", 3: "undecided"}.get(req.returncode, "not compared")
                except subprocess.TimeoutExpired:
                    equiv = "undecided"
        out_rows.append({"broken_form_hash": bfh, "used_nameless": used_nl, "equivalence": equiv})

print(json.dumps({"rows": out_rows}))
"""
        root_str = self.remote_root if self.ssh_host else str(LOCAL_BENCH_ROOT)
        res = self.run_remote_py(code, {"root": root_str, "items": items, "rules_sha": rules_sha}, timeout_s=180.0)
        return res["rows"]


# ============================================================================
# Obligation Preservation & Public Stdlib Context Resolver
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
        return False, f"example count dropped ({len(ob_c['examples_lhs'])} < {len(ob_m['examples_lhs'])})"
    if ob_c["checks_cnt"] < len(ob_m["examples_lhs"]) * 0 + ob_m["checks_cnt"]:
        return False, f"check count dropped ({ob_c['checks_cnt']} < {ob_m['checks_cnt']})"
    for k, req_names in ob_m["decls"].items():
        missing = req_names - ob_c["decls"][k]
        if missing:
            return False, f"missing declared {k}: {sorted(missing)}"
    m_cnt = Counter(ob_m["examples_lhs"])
    c_cnt = Counter(ob_c["examples_lhs"])
    kept_lhs = sum(min(cnt, c_cnt[lhs]) for lhs, cnt in m_cnt.items())
    if ob_m["examples_lhs"] and kept_lhs < max(1, len(ob_m["examples_lhs"]) - 1):
        return False, f"example event traces altered ({kept_lhs}/{len(ob_m['examples_lhs'])} preserved)"
    return True, "ok"


def self_stdlib_mod_name(task_path: str) -> str | None:
    if not task_path.startswith("stdlib/lib/"):
        return None
    rel = Path(task_path[len("stdlib/lib/"):]).with_suffix("")
    parts = list(rel.parts)
    return ".".join(parts[:-1]) if (len(parts) >= 2 and parts[-1] == parts[-2]) else ".".join(parts)


def resolve_imported_stdlib_signatures(
    task_path: str,
    src_text: str,
    diag_text: str,
    mod_headers: dict[str, str],
    sym_to_mods: dict[str, list[str]],
) -> tuple[list[str], str]:
    """
    Deterministically resolve public declaration signatures of imported/referenced
    `stdlib/lib` modules, strictly excluding `task_path` itself (`F1_original_leakage` guard).
    """
    forbidden_self = self_stdlib_mod_name(task_path)
    chosen: list[str] = []

    def _add_mod(m: str) -> None:
        if m and m != forbidden_self and m in mod_headers and m not in chosen:
            chosen.append(m)

    for ln in src_text.splitlines():
        s = ln.strip()
        m_use = re.match(r"^use\s+([A-Za-z0-9_.]+)\b", s)
        if m_use:
            _add_mod(m_use.group(1))
        m_old = re.match(r"^#!\s*lib\s+([A-Za-z0-9_.]+)\b", s)
        if m_old:
            _add_mod(m_old.group(1))
        for m_doc in re.finditer(r"\blib/([A-Za-z0-9_/]+)\.rce\b", s):
            raw_m = m_doc.group(1).replace("/", ".")
            parts = raw_m.split(".")
            norm_m = ".".join(parts[:-1]) if (len(parts) >= 2 and parts[-1] == parts[-2]) else raw_m
            _add_mod(norm_m)

    # Check unresolved W-NAME-1 identifiers or `module '<m>' has no item` in compiler diagnostic
    for m_mod_err in re.finditer(r"module `([A-Za-z0-9_.]+)` has no item", diag_text):
        _add_mod(m_mod_err.group(1))
    for m_unk in re.finditer(r"unknown name `([A-Za-z_][A-Za-z0-9_]*)`", diag_text):
        sym = m_unk.group(1)
        for owner in sym_to_mods.get(sym, []):
            _add_mod(owner)

    chosen = chosen[:5]
    if not chosen:
        return [], ""
    blocks = []
    for m in chosen:
        short = m.split(".")[-1]
        blocks.append(f"# Public signatures of `use {m}` (qualified as `{short}.<item>`):\n{mod_headers[m]}")
    return chosen, "\n\n".join(blocks)


# ============================================================================
# Multi-Turn Prompting & Patch Extraction
# ============================================================================

def format_numbered_source(src: str) -> str:
    return "\n".join(f"{i:4d}: {ln}" for i, ln in enumerate(src.splitlines(), start=1))


def build_turn1_prompt(task_path: str, mutant_src: str, init_diag: str, stdlib_sig_block: str) -> str:
    n_lines = len(mutant_src.splitlines())
    sig_section = (
        f"Public Standard Library Signatures (`openIE-dev/rce` at `1762fb4b`, declarations only):\n```rce\n{stdlib_sig_block}\n```\n\n"
        if stdlib_sig_block
        else ""
    )
    if n_lines <= 110:
        fmt_inst = (
            "Output ONLY the complete repaired `.rce` file enclosed in a single ```rce ... ``` code block "
            "(no prose outside the code block)."
        )
        src_block = f"Broken RCE module (`{task_path}`, {n_lines} lines):\n```rce\n{mutant_src}```"
    else:
        fmt_inst = (
            "Because this module exceeds 110 lines, output minimal exact search/replace edit blocks against the "
            "broken file (without line-number prefixes inside blocks, one or more blocks, no prose outside blocks):\n"
            "<<<SEARCH\n<exact contiguous lines from the current file>\n===\n<replacement lines>\n>>>REPLACE\n"
            "(A complete ```rce ... ``` code block is also accepted if you prefer.)"
        )
        src_block = (
            f"Broken RCE module (`{task_path}`, {n_lines} lines; line numbers shown for reference — do NOT include "
            f"`123: ` prefixes inside SEARCH/REPLACE blocks):\n```rce\n{format_numbered_source(mutant_src)}\n```"
        )
    return (
        f"Repair `{task_path}` so `rce check` admits it with exit code 0 (including `W-MUT-1`) while preserving all obligations.\n\n"
        f"{sig_section}"
        f"Initial `rce check` output:\n```\n{init_diag}\n```\n\n"
        f"{src_block}\n\n"
        f"{fmt_inst}"
    )


def build_feedback_prompt(
    turn_idx: int,
    max_turns: int,
    task_path: str,
    current_src: str,
    diag_text: str,
    ob_ok: bool,
    ob_note: str,
    applied_ok: bool,
    stdlib_sig_block: str,
) -> str:
    n_lines = len(current_src.splitlines())
    status_lines = []
    if not applied_ok:
        status_lines.append(
            "NOTE: Your previous response could not be cleanly applied (a <<<SEARCH block did not match verbatim or no valid code block was found). The file below is unchanged; copy exact lines when constructing <<<SEARCH blocks."
        )
    if not ob_ok:
        status_lines.append(
            f"OBLIGATION GATE REJECTION: {ob_note}. You MUST preserve all declared items and example/check counts from the original broken task (only refining at most one vacuous `example` if required by `W-MUT-1`)."
        )
    status_lines.append(f"`rce check` diagnostic on your candidate:\n```\n{diag_text}\n```")

    sig_section = (
        f"\nReferenced Public Standard Library Signatures:\n```rce\n{stdlib_sig_block}\n```\n"
        if stdlib_sig_block
        else ""
    )
    if n_lines <= 110:
        src_view = f"Current candidate (`{task_path}`, {n_lines} lines):\n```rce\n{current_src}```"
        fmt_inst = "Return ONLY the complete corrected `.rce` file in a single ```rce ... ``` code block."
    else:
        src_view = (
            f"Current candidate (`{task_path}`, {n_lines} lines, with reference line numbers — omit `123: ` prefixes in blocks):\n"
            f"```rce\n{format_numbered_source(current_src)}\n```"
        )
        fmt_inst = (
            "Return exact `<<<SEARCH\\n...\\n===\\n...\\n>>>REPLACE` blocks against the current candidate above "
            "(or a complete ```rce ... ``` file)."
        )
    return (
        f"Turn {turn_idx} of {max_turns} — `rce check` still requires change.\n\n"
        + "\n\n".join(status_lines)
        + sig_section
        + f"\n{src_view}\n\n{fmt_inst}"
    )


def apply_proposal_output(base_src: str, raw_output: str) -> tuple[str, bool]:
    txt = raw_output.strip()
    if not txt:
        return base_src, False
    txt = re.sub(r"<think>.*?</think>", "", txt, flags=re.DOTALL).strip()

    sr_blocks = re.findall(r"<<<SEARCH\r?\n(.*?)\r?\n===\r?\n(.*?)\r?\n>>>REPLACE", txt, flags=re.DOTALL)
    if sr_blocks:
        patched = base_src
        applied_all = True
        applied_any = False
        for old_s, new_s in sr_blocks:
            # Strip accidental `  12: ` line-number prefixes if model copied them
            if all(re.match(r"^\s*\d+:\s?", ln) for ln in old_s.splitlines() if ln.strip()):
                old_s = "\n".join(re.sub(r"^\s*\d+:\s?", "", ln) for ln in old_s.splitlines())
                new_s = "\n".join(re.sub(r"^\s*\d+:\s?", "", ln) for ln in new_s.splitlines())
            if old_s in patched:
                patched = patched.replace(old_s, new_s, 1)
                applied_any = True
            else:
                # Fallback: trailing-whitespace-normalized line window match
                p_lines = patched.splitlines()
                o_lines = [ln.rstrip() for ln in old_s.splitlines()]
                matched_idx = None
                for i in range(len(p_lines) - len(o_lines) + 1):
                    if [ln.rstrip() for ln in p_lines[i : i + len(o_lines)]] == o_lines:
                        matched_idx = i
                        break
                if matched_idx is not None:
                    p_lines = p_lines[:matched_idx] + new_s.splitlines() + p_lines[matched_idx + len(o_lines) :]
                    patched = "\n".join(p_lines) + "\n"
                    applied_any = True
                else:
                    applied_all = False
        if applied_any:
            return (patched if patched.endswith("\n") else patched + "\n"), applied_all
        return base_src, False

    fences = re.findall(r"```(?:rce)?\s*\n(.*?)```", txt, flags=re.DOTALL)
    if fences:
        cand = fences[-1].strip()
        if cand:
            if all(re.match(r"^\s*\d+:\s?", ln) for ln in cand.splitlines()[:5] if ln.strip()):
                cand = "\n".join(re.sub(r"^\s*\d+:\s?", "", ln) for ln in cand.splitlines())
            return cand + "\n", True

    if any(txt.startswith(k) for k in ("#", "module ", "use ", "intent ", "state ", "event ", "fn ", "pub ", "const ", "extern ")):
        return txt + "\n", True
    return base_src, False


# ============================================================================
# Cloud Multi-Turn API Client
# ============================================================================

def call_cloud_chat(
    spec: str,
    keys: dict[str, str],
    messages: list[dict[str, str]],
    max_tokens: int = 8192,
) -> tuple[str, int, int, int, int, float]:
    """Returns `(assistant_text, inp_tok, out_tok, cached_tok, think_tok, wall_s)`."""
    t0 = time.perf_counter()
    for attempt in range(4):
        try:
            if spec in ("claude-opus-5-5", "claude-sonnet-5-5"):
                body = json.dumps(
                    {
                        "model": spec,
                        "max_tokens": max_tokens,
                        "system": SYSTEM_RCE_DRAFT09,
                        "messages": messages,
                    }
                ).encode("utf-8")
                req = urllib.request.Request(
                    "https://api.anthropic.com/v1/messages",
                    data=body,
                    headers={
                        "x-api-key": keys["ANTHROPIC_API_KEY"],
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=120) as r:
                    rj = json.loads(r.read())
                txt = "".join(b.get("text", "") for b in rj.get("content", []) if b.get("type") == "text")
                u = rj.get("usage", {})
                think = int((u.get("output_tokens_details") or {}).get("thinking_tokens", 0))
                return (
                    txt,
                    int(u.get("input_tokens", 0)),
                    int(u.get("output_tokens", 0)),
                    int(u.get("cache_read_input_tokens", 0)),
                    think,
                    time.perf_counter() - t0,
                )

            provider, model_id = spec.split(":", 1)
            if provider != "xai":
                raise ValueError(f"Unsupported provider: {provider}")
            body = json.dumps(
                {
                    "model": model_id,
                    "max_tokens": max_tokens,
                    "temperature": 0.1,
                    "messages": [{"role": "system", "content": SYSTEM_RCE_DRAFT09}] + messages,
                }
            ).encode("utf-8")
            req = urllib.request.Request(
                "https://api.x.ai/v1/chat/completions",
                data=body,
                headers={
                    "Authorization": f"Bearer {keys['XAI_API_KEY']}",
                    "Content-Type": "application/json",
                    "User-Agent": "rce-h15-iterative/1.0",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=150) as r:
                rj = json.loads(r.read())
            msg = rj["choices"][0]["message"]
            txt = msg.get("content") or ""
            u = rj.get("usage", {})
            comp_details = u.get("completion_tokens_details") or {}
            think = int(comp_details.get("reasoning_tokens", 0))
            return (
                txt,
                int(u.get("prompt_tokens", 0)),
                int(u.get("completion_tokens", 0)),
                int((u.get("prompt_tokens_details") or {}).get("cached_tokens", 0)),
                think,
                time.perf_counter() - t0,
            )
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 529) and attempt < 3:
                time.sleep(2.5 * (2**attempt))
                continue
            return "", 0, 0, 0, 0, time.perf_counter() - t0
        except Exception:
            if attempt < 3:
                time.sleep(2.0 * (attempt + 1))
                continue
            return "", 0, 0, 0, 0, time.perf_counter() - t0
    return "", 0, 0, 0, 0, time.perf_counter() - t0


def compute_turn_usd(spec: str, inp: int, out: int, cached: int, think: int) -> float:
    in_rate, out_rate = PRICING_PER_1M_USD[spec]
    billable_in = max(0, inp - cached) + 0.1 * cached
    # Note: Anthropic `output_tokens` already includes adaptive thinking tokens; xAI `completion_tokens`
    # may report `reasoning_tokens` separately or inside `completion_tokens` depending on endpoint.
    if spec.startswith("xai:"):
        eff_out = out if out >= think else (out + think)
    else:
        eff_out = out
    return (billable_in * in_rate + eff_out * out_rate) / 1_000_000.0


# ============================================================================
# Binary `DNULLMM1` Store Writer & Zero-Call Replay Reader
# ============================================================================

def write_dnullmm1_store(records: list[dict[str, Any]], jsonl_path: Path, mmap_path: Path) -> str:
    lines = []
    offsets = []
    cur_off = 0
    for seq, rec in enumerate(records, start=1):
        row = dict(rec)
        row["seq"] = seq
        enc = (json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
        offsets.append((row, cur_off))
        lines.append(enc)
        cur_off += len(enc)
    raw_jsonl = b"".join(lines)
    jsonl_path.write_bytes(raw_jsonl)
    digest_hex = sha256_bytes(raw_jsonl)
    digest_raw = bytes.fromhex(digest_hex)

    live: dict[str, tuple[dict[str, Any], int]] = {}
    for row, off in offsets:
        kh = row["key"]
        prev = live.get(kh)
        if prev is None or (int(row.get("score", 1_000_000)), int(row["seq"])) >= (
            int(prev[0].get("score", 1_000_000)),
            int(prev[0]["seq"]),
        ):
            live[kh] = (row, off)

    n_rec = len(live)
    cap = 16
    while cap < max(16, 2 * n_rec):
        cap *= 2
    header = struct.pack("<8sQQ32sQ", b"DNULLMM1", n_rec, cap, digest_raw, 0)
    slots = [b"\x00" * 48 for _ in range(cap)]
    mask = cap - 1
    for kh, (row, off) in live.items():
        k16 = bytes.fromhex(kh)
        if k16 == b"\x00" * 16:
            k16 = b"\x00" * 15 + b"\x01"
        pos = struct.unpack("<Q", k16[:8])[0] & mask
        while slots[pos][:16] != b"\x00" * 16:
            pos = (pos + 1) & mask
        slots[pos] = struct.pack(
            "<16sqqqQ",
            k16,
            int(row["seq"]),
            int(row.get("score", 1_000_000)),
            int(row.get("act_id", row["seq"])),
            int(off),
        )
    mmap_path.write_bytes(header + b"".join(slots))
    return digest_hex


class DnullMmapStore:
    def __init__(self, jsonl_path: Path, mmap_path: Path) -> None:
        self.jsonl_bytes = jsonl_path.read_bytes()
        self._fh = open(mmap_path, "rb")
        self._mm = mmap.mmap(self._fh.fileno(), 0, access=mmap.ACCESS_READ)
        magic, self.n_rec, self.cap, digest_raw, _ = struct.unpack("<8sQQ32sQ", self._mm[:64])
        if magic != b"DNULLMM1" or hashlib.sha256(self.jsonl_bytes).digest() != digest_raw:
            raise ValueError("Invalid DNULLMM1 store")
        self.mask = self.cap - 1

    def lookup_record(self, key_hex32: str) -> dict[str, Any] | None:
        k16 = bytes.fromhex(key_hex32)
        if k16 == b"\x00" * 16:
            k16 = b"\x00" * 15 + b"\x01"
        pos = struct.unpack("<Q", k16[:8])[0] & self.mask
        for _ in range(self.cap):
            base = 64 + pos * 48
            slot_k = self._mm[base : base + 16]
            if slot_k == b"\x00" * 16:
                return None
            if slot_k == k16:
                _, _, _, off = struct.unpack("<qqqQ", self._mm[base + 16 : base + 48])
                end = self.jsonl_bytes.find(b"\n", int(off))
                line = self.jsonl_bytes[int(off) : end] if end != -1 else self.jsonl_bytes[int(off) :]
                return json.loads(line.decode("utf-8"))
            pos = (pos + 1) & self.mask
        return None

    def close(self) -> None:
        self._mm.close()
        self._fh.close()


def splitmix64_step(seed: int, index: int) -> int:
    z = (seed + ((index + 1) * 0x9E3779B97F4A7C15)) & 0xFFFFFFFFFFFFFFFF
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
    return (z ^ (z >> 31)) & 0xFFFFFFFFFFFFFFFF


def generate_zipf_stream(n_items: int = 40, m_arrivals: int = 200, s: float = 0.85, seed: int = 0x20261122) -> list[int]:
    order = list(range(n_items))
    for i in range(n_items - 1, 0, -1):
        j = splitmix64_step(seed, i) % (i + 1)
        order[i], order[j] = order[j], order[i]
    weights = [1.0 / ((rank + 1) ** s) for rank in range(n_items)]
    tot = sum(weights)
    cdf, acc = [], 0.0
    for w in weights:
        acc += w / tot
        cdf.append(acc)
    stream = []
    for step in range(m_arrivals):
        u = (splitmix64_step(seed ^ 0xA5A5A5A5, step) % 10_000_000) / 10_000_000.0
        chosen = n_items - 1
        for r_idx, c in enumerate(cdf):
            if u <= c:
                chosen = r_idx
                break
        stream.append(order[chosen])
    return stream


# ============================================================================
# Single Episode Runner (ZERO Access to `original`!)
# ============================================================================

def run_single_episode(
    arm_name: str,
    model_spec: str,
    max_turns: int,
    task_idx: int,
    proposer_task: dict[str, Any],
    init_diag: str,
    mod_headers: dict[str, str],
    sym_to_mods: dict[str, list[str]],
    keys: dict[str, str],
    gw: RceGateway,
) -> dict[str, Any]:
    """
    Runs up to `max_turns = 5` on `proposer_task` (which does NOT even contain `original`!).
    """
    assert "original" not in proposer_task, "Falsifier F1 guard: original must never enter run_single_episode"
    task_path = proposer_task["path"]
    mutant_src = proposer_task["mutant"]

    stdlib_mods, stdlib_block = resolve_imported_stdlib_signatures(
        task_path, mutant_src, init_diag, mod_headers, sym_to_mods
    )
    prompt_t1 = build_turn1_prompt(task_path, mutant_src, init_diag, stdlib_block)
    messages: list[dict[str, str]] = [{"role": "user", "content": prompt_t1}]

    current_src = mutant_src
    turn_logs: list[dict[str, Any]] = []
    candidate_pool_samples: list[dict[str, Any]] = []

    tot_in, tot_out, tot_cached, tot_think = 0, 0, 0, 0
    tot_usd = 0.0
    tot_wall = 0.0
    admitted = False
    winning_cand = ""
    winning_turn = None

    for turn in range(1, max_turns + 1):
        # Keep message history bounded to [initial_request_or_summary, latest_feedback] if > 5 messages
        call_msgs = messages if len(messages) <= 5 else (messages[:1] + messages[-2:])
        raw_txt, inp_t, out_t, cac_t, thk_t, w_s = call_cloud_chat(
            model_spec, keys, call_msgs, max_tokens=8192
        )
        t_usd = compute_turn_usd(model_spec, inp_t, out_t, cac_t, thk_t)
        tot_in += inp_t
        tot_out += out_t
        tot_cached += cac_t
        tot_think += thk_t
        tot_usd += t_usd
        tot_wall += w_s

        cand_src, applied_ok = apply_proposal_output(current_src, raw_txt)
        # Always judge obligations against the original `mutant_src` (Falsifier F3 guard!)
        ob_ok, ob_note = check_obligations_preserved(mutant_src, cand_src)
        rc, diag = gw.check_candidate(cand_src) if applied_ok else (-1, init_diag if turn == 1 else "patch_not_applied")
        turn_adm = applied_ok and ob_ok and (rc == 0)

        if applied_ok and cand_src != mutant_src:
            candidate_pool_samples.append({
                "turn": turn,
                "admitted": turn_adm,
                "text": cand_src,
            })

        turn_logs.append({
            "turn": turn,
            "applied_ok": applied_ok,
            "obligations_kept": ob_ok,
            "obligations_note": ob_note,
            "rce_check_exit": rc,
            "admitted": turn_adm,
            "diagnostic": diag[:320],
            "input_tokens": inp_t,
            "output_tokens": out_t,
            "cached_tokens": cac_t,
            "thinking_tokens": thk_t,
            "cost_usd": round(t_usd, 6),
            "wall_s": round(w_s, 3),
        })

        if turn_adm:
            admitted = True
            winning_cand = cand_src
            winning_turn = turn
            break

        if turn < max_turns:
            if applied_ok and ob_ok:
                current_src = cand_src
            # Refresh stdlib signature block if new W-NAME-1 symbols surfaced
            more_mods, stdlib_block_next = resolve_imported_stdlib_signatures(
                task_path, current_src, diag, mod_headers, sym_to_mods
            )
            for m in more_mods:
                if m not in stdlib_mods:
                    stdlib_mods.append(m)
            fb_prompt = build_feedback_prompt(
                turn + 1,
                max_turns,
                task_path,
                current_src,
                diag,
                ob_ok,
                ob_note,
                applied_ok,
                stdlib_block_next,
            )
            messages.append({"role": "assistant", "content": raw_txt[:12000] if raw_txt else "(empty)"})
            messages.append({"role": "user", "content": fb_prompt})

    return {
        "arm": arm_name,
        "model": model_spec,
        "task_index": task_idx,
        "task_id": proposer_task["id"],
        "path": task_path,
        "source": proposer_task["source"],
        "mutant_rules": proposer_task["mutant_rules"],
        "stdlib_headers_provided": stdlib_mods,
        "max_turns": max_turns,
        "turns_used": len(turn_logs),
        "turn1_admitted": bool(turn_logs[0]["admitted"]) if turn_logs else False,
        "admitted": admitted,
        "winning_turn": winning_turn,
        "total_input_tokens": tot_in,
        "total_output_tokens": tot_out,
        "total_cached_tokens": tot_cached,
        "total_thinking_tokens": tot_think,
        "cost_usd": round(tot_usd, 6),
        "wall_s": round(tot_wall, 3),
        "final_diagnostic": turn_logs[-1]["diagnostic"] if turn_logs else "",
        "turn_history": turn_logs,
        "_winning_cand": winning_cand,
        "_candidate_pool_samples": candidate_pool_samples,
    }


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Verify PREREG_h15_iterative.json SHA-256
    prereg_bytes = PREREG_PATH.read_bytes()
    actual_sha = sha256_bytes(prereg_bytes)
    pinned_sha = PREREG_SHA_PATH.read_text(encoding="utf-8").split()[0]
    if actual_sha != pinned_sha:
        raise RuntimeError(f"PREREG_h15_iterative SHA-256 mismatch: {actual_sha} != {pinned_sha}")
    prereg = json.loads(prereg_bytes.decode("utf-8"))
    print(f"[H15-Iterative] Verified pre-registration SHA-256: {actual_sha[:16]}...")

    keys = discover_cloud_keys()
    for req_k in ("ANTHROPIC_API_KEY", "XAI_API_KEY"):
        if not keys.get(req_k):
            raise RuntimeError(f"Missing required API key in environment: {req_k}")

    gw = RceGateway(RCE_SSH_HOST, REMOTE_BENCH_ROOT, LOCAL_RCE_BIN)
    try:
        boot = gw.fetch_bootstrap_context()
        if boot["rce_head"] != prereg["corpus_and_gate"]["rce_commit"]:
            raise RuntimeError(f"RCE commit mismatch: {boot['rce_head']}")
        if boot["res40_sha256"] != prereg["corpus_and_gate"]["h15_residual_40_sha256"]:
            raise RuntimeError(f"residual_40 SHA-256 mismatch: {boot['res40_sha256']}")
        if RCE_SSH_HOST and boot["rce_bin_sha256"] != prereg["corpus_and_gate"]["rce_linux_x86_64_binary_sha256"]:
            raise RuntimeError(f"RCE binary SHA-256 mismatch: {boot['rce_bin_sha256']}")

        full_tasks: list[dict[str, Any]] = boot["tasks"]
        init_diags: list[str] = boot["init_diags"]
        mod_headers: dict[str, str] = boot["mod_headers"]
        sym_to_mods: dict[str, list[str]] = boot["sym_to_mods"]
        rules_sha: str = boot["rules_sha"]

        # Strip `original` before constructing proposer inputs (`F1_original_leakage` hard wall)
        proposer_tasks = [
            {
                "id": t["id"],
                "path": t.get("path") or t["id"].split("@")[0],
                "mutant": t["mutant"],
                "source": t["source"],
                "mutant_rules": t["mutant_rules"],
            }
            for t in full_tasks
        ]

        arm_configs = [
            ("iter_claude_opus_5_5", "claude-opus-5-5", 5, 6),
            ("iter_claude_sonnet_5_5", "claude-sonnet-5-5", 5, 6),
            ("iter_xai_grok_4_20_reasoning", "xai:grok-4.20-0309-reasoning", 5, 6),
        ]

        ckpt_tmp = Path(tempfile.gettempdir()) / f"h15_iter_ckpt_{actual_sha[:12]}.json"
        cached_by_arm: dict[str, list[dict[str, Any]]] = (
            json.loads(ckpt_tmp.read_text(encoding="utf-8")) if ckpt_tmp.exists() else {}
        )
        all_episodes: list[dict[str, Any]] = []
        for arm_name, model_spec, max_turns, workers in arm_configs:
            if arm_name in cached_by_arm and len(cached_by_arm[arm_name]) == len(proposer_tasks):
                print(f"[H15-Iterative] Resuming cached {arm_name} (40/40 tasks)")
                all_episodes.extend(cached_by_arm[arm_name])
                continue
            t_arm0 = time.perf_counter()
            print(f"[H15-Iterative] Starting {arm_name} ({model_spec}, max_turns={max_turns}) across 40 tasks...")
            arm_eps: list[dict[str, Any]] = [None] * len(proposer_tasks)  # type: ignore[list-item]
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
                fut_map = {
                    ex.submit(
                        run_single_episode,
                        arm_name,
                        model_spec,
                        max_turns,
                        idx,
                        pt,
                        init_diags[idx],
                        mod_headers,
                        sym_to_mods,
                        keys,
                        gw,
                    ): idx
                    for idx, pt in enumerate(proposer_tasks)
                }
                done_cnt = 0
                for fut in concurrent.futures.as_completed(fut_map):
                    idx = fut_map[fut]
                    ep = fut.result()
                    arm_eps[idx] = ep
                    done_cnt += 1
                    if done_cnt % 10 == 0 or done_cnt == len(proposer_tasks):
                        adm_now = sum(1 for x in arm_eps if x and x["admitted"])
                        t1_now = sum(1 for x in arm_eps if x and x["turn1_admitted"])
                        print(
                            f"  [{arm_name}] {done_cnt}/40 done | turn1_adm={t1_now} | "
                            f"iter_adm={adm_now} | elapsed={time.perf_counter()-t_arm0:.1f}s"
                        )
            cached_by_arm[arm_name] = arm_eps
            ckpt_tmp.write_text(json.dumps(cached_by_arm), encoding="utf-8")
            all_episodes.extend(arm_eps)

        # Post-hoc audit against `original` + canonical `DNULLMM1` key calculation
        print("[H15-Iterative] Running post-hoc `rce hash` + `rce equiv fuel 2000` audit against ORIGINAL...")
        audit_inputs = []
        for ep in all_episodes:
            orig_task = full_tasks[ep["task_index"]]
            audit_inputs.append({
                "mutant": orig_task["mutant"],
                "original": orig_task["original"],
                "admitted": ep["admitted"],
                "cand": ep["_winning_cand"],
            })
        audit_rows = gw.posthoc_audit_and_keys(audit_inputs, rules_sha)

        for ep, arow in zip(all_episodes, audit_rows):
            ob = extract_obligations_summary(full_tasks[ep["task_index"]]["mutant"])
            contract_sig = json.dumps(
                {
                    "rules_sha": rules_sha,
                    "examples_cnt": len(ob["examples_lhs"]),
                    "checks_cnt": ob["checks_cnt"],
                    "states": sorted(ob["decls"]["state"]),
                    "events": sorted(ob["decls"]["event"]),
                    "fns_cnt": len(ob["decls"]["fn"]),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            ch = sha256_str(contract_sig)
            bfh = arow["broken_form_hash"]
            ep["dnull_key_hex32"] = sha256_str(f"{bfh}:{ch}")[:32]
            ep["broken_form_hash"] = bfh
            ep["contract_hash"] = ch
            ep["used_nameless_projection"] = arow["used_nameless"]
            ep["equivalence"] = arow["equivalence"]

        # Persist candidate pool on remote/local work dir for Deliverable A H15 evaluation
        cand_pool_by_task: dict[str, list[dict[str, Any]]] = {}
        for ep in all_episodes:
            tid = ep["task_id"]
            for s in ep.pop("_candidate_pool_samples", []):
                existing_txts = {x["text"] for x in cand_pool_by_task.get(tid, [])}
                if s["text"] not in existing_txts:
                    cand_pool_by_task.setdefault(tid, []).append({
                        "origin": ep["arm"],
                        "turn": s["turn"],
                        "admitted": s["admitted"],
                        "text": s["text"],
                    })

        if RCE_SSH_HOST:
            gw.run_remote_py(
                r"""
import json
from pathlib import Path
p = Path(PAYLOAD["root"]) / "work/h15_iterative_candidates.json"
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(PAYLOAD["pool"], sort_keys=True), encoding="utf-8")
print(json.dumps({"ok": True}))
""",
                {"root": REMOTE_BENCH_ROOT, "pool": cand_pool_by_task},
                timeout_s=30.0,
            )

        # Crystallize verified non-contradicting repairs into DNULLMM1 Gear-0
        # Reference crystallizer: iter_claude_opus_5_5 (with fallback to Sonnet/Grok only if non-contradicting)
        cryst_by_idx: dict[int, dict[str, Any]] = {}
        for arm_pref in ("iter_claude_opus_5_5", "iter_claude_sonnet_5_5", "iter_xai_grok_4_20_reasoning"):
            for ep in all_episodes:
                if ep["arm"] != arm_pref or not ep["admitted"]:
                    continue
                if ep["equivalence"] == "contradicts":
                    continue
                t_i = ep["task_index"]
                if t_i not in cryst_by_idx:
                    cryst_by_idx[t_i] = {
                        "key": ep["dnull_key_hex32"],
                        "task_id": ep["task_id"],
                        "origin_arm": ep["arm"],
                        "winning_turn": ep["winning_turn"],
                        "equivalence": ep["equivalence"],
                        "repaired_rce": ep["_winning_cand"],
                        "score": 1_000_000,
                    }

        store_records = [cryst_by_idx[k] for k in sorted(cryst_by_idx)]
        store_jsonl = RESULTS_DIR / "gear0_v2_store.jsonl"
        store_mmap = RESULTS_DIR / "gear0_v2_store.mmap"
        store_sha = write_dnullmm1_store(store_records, store_jsonl, store_mmap)

        # Verify warm DNULLMM1 t=2 zero-call replay across all 40 tasks (re-checking every hit on remote rce!)
        dstore = DnullMmapStore(store_jsonl, store_mmap)
        t_rep0 = time.perf_counter()
        replay_hits = 0
        replay_verified = 0
        key_by_idx = {
            ep["task_index"]: ep["dnull_key_hex32"]
            for ep in all_episodes
            if ep["arm"] == "iter_claude_opus_5_5"
        }
        for idx_t, t_full in enumerate(full_tasks):
            rec = dstore.lookup_record(key_by_idx[idx_t])
            if rec is not None:
                replay_hits += 1
                ob_ok, _ = check_obligations_preserved(t_full["mutant"], rec["repaired_rce"])
                rc_chk, _ = gw.check_candidate(rec["repaired_rce"])
                if ob_ok and rc_chk == 0:
                    replay_verified += 1
        replay_wall_s = round(time.perf_counter() - t_rep0, 4)
        dstore.close()
        if sha256_bytes(store_jsonl.read_bytes()) != store_sha:
            raise RuntimeError("DNULLMM1 store mutated during replay")

        # Strip `_winning_cand` before writing clean `h15_iterative_episodes.jsonl`
        ep_out_path = RESULTS_DIR / "h15_iterative_episodes.jsonl"
        with open(ep_out_path, "w", encoding="utf-8") as fh:
            for ep in all_episodes:
                clean_ep = {k: v for k, v in ep.items() if not k.startswith("_")}
                fh.write(json.dumps(clean_ep, sort_keys=True, ensure_ascii=False) + "\n")

        # Build detailed Deliverable B summary
        unsolved_6 = prereg["baseline_single_shot_wave1"]["unsolved_6_tasks_at_k1"]
        by_arm_summary: dict[str, Any] = {}
        for arm_name, model_spec, max_turns, _ in arm_configs:
            sub = [e for e in all_episodes if e["arm"] == arm_name]
            adm = sum(1 for e in sub if e["admitted"])
            t1_adm = sum(1 for e in sub if e["turn1_admitted"])
            eq_cnt = Counter(e["equivalence"] for e in sub if e["admitted"])
            turn_hist = Counter(e["winning_turn"] for e in sub if e["admitted"])
            by_arm_summary[arm_name] = {
                "model": model_spec,
                "tasks": 40,
                "max_turns": max_turns,
                "turn1_admitted_with_stdlib_headers": t1_adm,
                "iterative_admitted": adm,
                "iterative_admitted_share": round(adm / 40.0, 4),
                "restored": eq_cnt.get("restored", 0),
                "behaviour_equal": eq_cnt.get("behaviour-equal", 0),
                "behaves_the_same": eq_cnt.get("restored", 0) + eq_cnt.get("behaviour-equal", 0),
                "contradicts": eq_cnt.get("contradicts", 0),
                "not_compared_or_undecided": adm - (eq_cnt.get("restored", 0) + eq_cnt.get("behaviour-equal", 0) + eq_cnt.get("contradicts", 0)),
                "winning_turn_distribution": {str(k): v for k, v in sorted(turn_hist.items())},
                "total_turns_called": sum(e["turns_used"] for e in sub),
                "total_input_tokens": sum(e["total_input_tokens"] for e in sub),
                "total_output_tokens": sum(e["total_output_tokens"] for e in sub),
                "total_thinking_tokens": sum(e["total_thinking_tokens"] for e in sub),
                "total_cost_usd": round(sum(e["cost_usd"] for e in sub), 5),
                "total_wall_s": round(sum(e["wall_s"] for e in sub), 3),
                "closed_api_server_energy": "not_available",
                "measured_j": None,
            }

        unsolved_6_breakdown: dict[str, Any] = {}
        for tid in unsolved_6:
            per_m = {}
            for arm_name, _, _, _ in arm_configs:
                ep = next(e for e in all_episodes if e["arm"] == arm_name and e["task_id"] == tid)
                per_m[arm_name] = {
                    "admitted": ep["admitted"],
                    "winning_turn": ep["winning_turn"],
                    "turns_used": ep["turns_used"],
                    "equivalence": ep["equivalence"],
                    "input_tokens": ep["total_input_tokens"],
                    "output_tokens": ep["total_output_tokens"],
                    "thinking_tokens": ep["total_thinking_tokens"],
                    "cost_usd": ep["cost_usd"],
                    "stdlib_headers_provided": ep["stdlib_headers_provided"],
                    "final_diagnostic": ep["final_diagnostic"][:200] if not ep["admitted"] else "ok",
                }
            unsolved_6_breakdown[tid] = per_m

        # Update 3-Gear Zipf(0.85) M=200 simulation with FormJEPA-v1 (27/40 Gear 1) + Opus 5.5 Iterative Gear 2
        # Load FormJEPA-v1 k=16 admitted task IDs from Wave 3 if available on remote
        jepa_27_ids = set(
            gw.run_remote_py(
                r"""
import json
from pathlib import Path
p = Path(PAYLOAD["root"]) / "openie-research-experiments/rce/bench/form-jepa-v1/results/summary.json"
d = json.loads(p.read_text(encoding="utf-8"))
print(json.dumps({"ids": d["deliverable_A_form_jepa_v1"]["eval_3_h15_residual_40"]["form_jepa_v1_k16"]["admitted_task_ids"]}))
""",
                {"root": REMOTE_BENCH_ROOT if RCE_SSH_HOST else str(LOCAL_BENCH_ROOT)},
            )["ids"]
        )
        opus_eps_by_idx = {
            e["task_index"]: e for e in all_episodes if e["arm"] == "iter_claude_opus_5_5"
        }
        zipf_stream = generate_zipf_stream(40, 200, s=0.85, seed=0x20261122)
        dnull_seen: set[int] = set()
        g0_hits, g1_calls, g1_hits, g2_episodes, g2_turns, g2_hits = 0, 0, 0, 0, 0, 0
        g2_usd = 0.0
        adm_arrivals = 0
        for idx_item in zipf_stream:
            if idx_item in dnull_seen:
                g0_hits += 1
                adm_arrivals += 1
                continue
            g1_calls += 1
            if full_tasks[idx_item]["id"] in jepa_27_ids:
                g1_hits += 1
                adm_arrivals += 1
                dnull_seen.add(idx_item)
                continue
            ep_o = opus_eps_by_idx[idx_item]
            g2_episodes += 1
            g2_turns += ep_o["turns_used"]
            g2_usd += ep_o["cost_usd"]
            if ep_o["admitted"]:
                g2_hits += 1
                adm_arrivals += 1
                dnull_seen.add(idx_item)

        h15_iter_summary = {
            "schema": "openie-rce-jepa-h15-iterative-summary/1",
            "completed_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "prereg_id": prereg["id"],
            "prereg_sha256": actual_sha,
            "engine": {
                "rce_commit": boot["rce_head"],
                "rce_linux_x86_64_binary_sha256": boot["rce_bin_sha256"],
                "openie_research_experiments_commit": boot["exp_head"],
                "residual_40_sha256": boot["res40_sha256"],
                "rce_rules_sha256": rules_sha,
            },
            "arms": by_arm_summary,
            "union_admitted_across_3_arms": len(cryst_by_idx),
            "previously_unsolved_6_breakdown": unsolved_6_breakdown,
            "warm_dnullmm1_gear0_v2": {
                "store_format": "DNULLMM1 (64B header + 48B slots)",
                "crystallized_records": len(store_records),
                "store_jsonl_sha256": store_sha,
                "t2_zero_call_replay_hits": replay_hits,
                "t2_zero_call_rce_re_admitted": replay_verified,
                "t2_model_calls": 0,
                "t2_replay_wall_s_with_remote_rce_check": replay_wall_s,
                "apple_m5_max_probe_reference_uj": 1.771,
                "apple_m5_max_probe_reference_us": 0.3246,
            },
            "cascade_3_gear_zipf_0p85_m200_with_opus_5_5_iterative": {
                "arrivals": 200,
                "admitted_arrivals": adm_arrivals,
                "gear0_dnullmm1_hits": g0_hits,
                "gear1_form_jepa_v1_calls": g1_calls,
                "gear1_form_jepa_v1_admissions": g1_hits,
                "gear2_opus_iterative_episodes": g2_episodes,
                "gear2_opus_iterative_api_turns": g2_turns,
                "gear2_opus_iterative_admissions": g2_hits,
                "gear2_opus_iterative_cost_usd": round(g2_usd, 4),
                "episode_reduction_vs_stateless_200": round(200.0 / max(1, g2_episodes), 2),
            },
        }
        out_json = RESULTS_DIR / "h15_iterative_summary.json"
        out_json.write_text(json.dumps(h15_iter_summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(
            f"[H15-Iterative] DONE! Union crystallized={len(store_records)}/40 | "
            f"Opus={by_arm_summary['iter_claude_opus_5_5']['iterative_admitted']}/40 | "
            f"Sonnet={by_arm_summary['iter_claude_sonnet_5_5']['iterative_admitted']}/40 | "
            f"Grok={by_arm_summary['iter_xai_grok_4_20_reasoning']['iterative_admitted']}/40"
        )
    finally:
        gw.close()


if __name__ == "__main__":
    main()
