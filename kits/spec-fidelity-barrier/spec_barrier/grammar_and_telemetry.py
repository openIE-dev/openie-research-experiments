# SPDX-License-Identifier: Apache-2.0
"""Standalone BLAKE3, RFC-8032 Ed25519 receipts, Clopper-Pearson exact confidence
intervals, orthogonal hardware energy metering (`measured_j ⊥ reported_j ⊥ est_j ⊥ unmetered`),
and deterministic Earley/Pushdown CFG + Type-Environment Token Masking.

Provenance tier: `Signed Provenance · Self-Checked` (never self-labeled `Verified`).
"""

from __future__ import annotations

import datetime as dt
import getpass
import hashlib
import json
import math
import os
import platform
import re
import resource
import shutil
import socket
import struct
import subprocess
import time
from pathlib import Path
from typing import Any

# ── 1. Reference BLAKE3 (pure Python, Apache-2.0, zero external deps) ────────

_IV = [
    0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A,
    0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19,
]
_PERM = [2, 6, 3, 10, 7, 0, 4, 13, 1, 11, 12, 5, 9, 14, 15, 8]
_CHUNK_START = 1
_CHUNK_END = 2
_PARENT = 4
_ROOT = 8
_DERIVE_KEY_CONTEXT = 32
_DERIVE_KEY_MATERIAL = 64


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
            f = flags | (_CHUNK_START if b == 0 else 0) | (_CHUNK_END if b == 15 else 0)
            cv = _compress(cv, _words64(data[st : st + 64]), chunk, 64, f)[:8]
        chunk += 1
        total = chunk
        node = cv
        while (total & 1) == 0:
            left = stack.pop()
            node = _compress(key, left + node, 0, 64, flags | _PARENT)[:8]
            total >>= 1
        stack.append(node)
        pos += 1024

    rest = data[pos:]
    blocks = max(1, (len(rest) + 63) // 64)
    cv = list(key)
    for b in range(blocks - 1):
        f = flags | (_CHUNK_START if b == 0 else 0)
        cv = _compress(cv, _words64(rest[b * 64 : (b + 1) * 64]), chunk, 64, f)[:8]
    last = rest[(blocks - 1) * 64 :]
    out_cv, out_block, out_counter, out_len, out_flags = (
        cv,
        _words64(last),
        chunk,
        len(last),
        flags | (_CHUNK_START if blocks == 1 else 0) | _CHUNK_END,
    )
    while stack:
        left = stack.pop()
        right_cv = _compress(out_cv, out_block, out_counter, out_len, out_flags)[:8]
        out_cv, out_block, out_counter, out_len, out_flags = key, left + right_cv, 0, 64, flags | _PARENT
    root = _compress(out_cv, out_block, out_counter, out_len, out_flags | _ROOT)
    return struct.pack("<8I", *root[:8])


def blake3_hex(data: bytes) -> str:
    return _blake3_hash_with(data, _IV, 0).hex()


def blake3_derive_key_hex(context: str, data: bytes) -> str:
    ctx_bytes = _blake3_hash_with(context.encode("utf-8"), _IV, _DERIVE_KEY_CONTEXT)
    ctx_words = list(struct.unpack("<8I", ctx_bytes))
    return _blake3_hash_with(data, ctx_words, _DERIVE_KEY_MATERIAL).hex()


# ── 2. Pure-Python RFC-8032 Ed25519 ──────────────────────────────────────────

_P = (1 << 255) - 19
_L = (1 << 252) + 27742317777372353535851937790883648493
_D = (-121665 * pow(121666, _P - 2, _P)) % _P
_I = pow(2, (_P - 1) // 4, _P)


def _xrecover(y: int) -> int:
    xx = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P != 0:
        x = (x * _I) % _P
    if x % 2 != 0:
        x = _P - x
    return x


_BY = 4 * pow(5, _P - 2, _P) % _P
_BX = _xrecover(_BY)
_B_EXT = (_BX, _BY, 1, (_BX * _BY) % _P)
_ID_EXT = (0, 1, 1, 0)


def _ed_add(p: tuple[int, int, int, int], q: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    x1, y1, z1, t1 = p
    x2, y2, z2, t2 = q
    a = ((y1 - x1) * (y2 - x2)) % _P
    b = ((y1 + x1) * (y2 + x2)) % _P
    c = (2 * t1 * t2 * _D) % _P
    d = (2 * z1 * z2) % _P
    e = (b - a) % _P
    f = (d - c) % _P
    g = (d + c) % _P
    h = (b + a) % _P
    return ((e * f) % _P, (g * h) % _P, (f * g) % _P, (e * h) % _P)


def _ed_double(p: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    x1, y1, z1, _ = p
    a = (x1 * x1) % _P
    b = (y1 * y1) % _P
    c = (2 * z1 * z1) % _P
    h = (a + b) % _P
    xy = (x1 + y1) % _P
    e = (h - xy * xy) % _P
    g = (a - b) % _P
    f = (c + g) % _P
    return ((e * f) % _P, (g * h) % _P, (f * g) % _P, (e * h) % _P)


def _scalarmult(p: tuple[int, int, int, int], e: int) -> tuple[int, int, int, int]:
    res = _ID_EXT
    cur = p
    k = e
    while k > 0:
        if k & 1:
            res = _ed_add(res, cur)
        cur = _ed_double(cur)
        k >>= 1
    return res


def _encodepoint(p: tuple[int, int, int, int]) -> bytes:
    x, y, z, _ = p
    zi = pow(z, _P - 2, _P)
    xp = (x * zi) % _P
    yp = (y * zi) % _P
    return (yp | ((xp & 1) << 255)).to_bytes(32, "little")


def _decodepoint(s: bytes) -> tuple[int, int, int, int]:
    if len(s) != 32:
        raise ValueError("Invalid point length")
    val = int.from_bytes(s, "little")
    y = val & ((1 << 255) - 1)
    xsgn = (val >> 255) & 1
    if y >= _P:
        raise ValueError("Point y out of range")
    xx = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P != 0:
        x = (x * _I) % _P
    if (x * x - xx) % _P != 0:
        raise ValueError("Point not on curve")
    if x == 0 and xsgn == 1:
        raise ValueError("Invalid negative zero x")
    if (x & 1) != xsgn:
        x = _P - x
    return (x, y, 1, (x * y) % _P)


def ed25519_pubkey_pure(seed32: bytes) -> bytes:
    h = hashlib.sha512(seed32).digest()
    a = (int.from_bytes(h[:32], "little") & ((1 << 254) - 8)) | (1 << 254)
    return _encodepoint(_scalarmult(_B_EXT, a))


def ed25519_sign_pure(seed32: bytes, msg: bytes) -> bytes:
    h = hashlib.sha512(seed32).digest()
    a = (int.from_bytes(h[:32], "little") & ((1 << 254) - 8)) | (1 << 254)
    prefix = h[32:]
    pub = _encodepoint(_scalarmult(_B_EXT, a))
    r = int.from_bytes(hashlib.sha512(prefix + msg).digest(), "little") % _L
    r_pt = _encodepoint(_scalarmult(_B_EXT, r))
    k = int.from_bytes(hashlib.sha512(r_pt + pub + msg).digest(), "little") % _L
    s = (r + k * a) % _L
    return r_pt + s.to_bytes(32, "little")


def ed25519_verify_pure(pubkey32: bytes, msg: bytes, sig64: bytes) -> bool:
    if len(pubkey32) != 32 or len(sig64) != 64:
        return False
    try:
        a_pt = _decodepoint(pubkey32)
        r_pt = _decodepoint(sig64[:32])
        s = int.from_bytes(sig64[32:], "little")
        if s >= _L:
            return False
        k = int.from_bytes(hashlib.sha512(sig64[:32] + pubkey32 + msg).digest(), "little") % _L
        lhs = _encodepoint(_scalarmult(_B_EXT, s))
        rhs = _encodepoint(_ed_add(r_pt, _scalarmult(a_pt, k)))
        return lhs == rhs
    except Exception:
        return False


def seal_signed_receipt(
    kit_id: str,
    payload: dict[str, Any],
    domain_context: str,
    seed32: bytes | None = None,
) -> dict[str, Any]:
    ephemeral_seed = seed32 if seed32 is not None else hashlib.sha256(
        f"{domain_context}:{kit_id}".encode("utf-8") + os.urandom(16)
    ).digest()
    pubkey = ed25519_pubkey_pure(ephemeral_seed)
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
    sig = ed25519_sign_pure(ephemeral_seed, msg_to_sign)
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
            canonical_bytes = json.dumps(
                body, sort_keys=True, separators=(",", ":"), ensure_ascii=ensure_asc
            ).encode("utf-8")
            expected_b3 = blake3_derive_key_hex(domain_context, canonical_bytes)
            if expected_b3 == receipt.get("body_blake3"):
                msg = f"{domain_context}:{expected_b3}".encode("ascii")
                if ed25519_verify_pure(pub, msg, sig):
                    return True
        return False
    except Exception:
        return False


# ── 3. Exact Clopper-Pearson Confidence Intervals & IQR Stats ────────────────

def _binom_cdf_le(k: int, n: int, p: float) -> float:
    if p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 1.0 if k >= n else 0.0
    log_p = math.log(p)
    log_q = math.log1p(-p)
    lg_n1 = math.lgamma(n + 1)
    total = 0.0
    for j in range(0, k + 1):
        log_pmf = lg_n1 - math.lgamma(j + 1) - math.lgamma(n - j + 1) + j * log_p + (n - j) * log_q
        total += math.exp(log_pmf)
    return min(1.0, max(0.0, total))


def _binom_sf_ge(k: int, n: int, p: float) -> float:
    """Exact P(X >= k) for X ~ Binomial(n, p)."""
    if k <= 0:
        return 1.0
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0 if k <= n else 0.0
    return max(0.0, min(1.0, 1.0 - _binom_cdf_le(k - 1, n, p)))


def clopper_pearson_interval(k: int, n: int, alpha: float = 0.05) -> dict[str, float]:
    """Exact two-sided (1-alpha) Clopper-Pearson interval AND one-sided 95% upper bound."""
    if n <= 0:
        return {"point": 0.0, "ci95_two_sided_lo": 0.0, "ci95_two_sided_hi": 1.0, "ci95_one_sided_hi": 1.0}
    point = k / n
    tail2 = alpha / 2.0

    # Lower bound: P(X >= k | p_lo) = alpha/2
    if k <= 0:
        lo2 = 0.0
    elif k == n:
        lo2 = tail2 ** (1.0 / n)
    else:
        lo, hi = 0.0, 1.0
        for _ in range(80):
            mid = 0.5 * (lo + hi)
            if _binom_sf_ge(k, n, mid) < tail2:
                lo = mid
            else:
                hi = mid
        lo2 = 0.5 * (lo + hi)

    # Two-sided upper bound: P(X <= k | p_hi) = alpha/2
    if k >= n:
        hi2 = 1.0
    elif k == 0:
        hi2 = 1.0 - (tail2 ** (1.0 / n))
    else:
        lo, hi = 0.0, 1.0
        for _ in range(80):
            mid = 0.5 * (lo + hi)
            if _binom_cdf_le(k, n, mid) > tail2:
                lo = mid
            else:
                hi = mid
        hi2 = 0.5 * (lo + hi)

    # One-sided (1-alpha) upper bound: P(X <= k | p_hi1) = alpha
    if k >= n:
        hi1 = 1.0
    elif k == 0:
        hi1 = 1.0 - (alpha ** (1.0 / n))
    else:
        lo, hi = 0.0, 1.0
        for _ in range(80):
            mid = 0.5 * (lo + hi)
            if _binom_cdf_le(k, n, mid) > alpha:
                lo = mid
            else:
                hi = mid
        hi1 = 0.5 * (lo + hi)

    return {
        "k": k,
        "n": n,
        "point": round(point, 6),
        "ci95_two_sided_lo": round(lo2, 6),
        "ci95_two_sided_hi": round(hi2, 6),
        "ci95_one_sided_hi": round(hi1, 6),
    }


def _percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    frac = pos - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def iqr_stats(vals: list[float], ndigits: int = 4) -> dict[str, float]:
    if not vals:
        return {"n": 0, "median": 0.0, "p25": 0.0, "p75": 0.0, "iqr": 0.0, "min": 0.0, "max": 0.0}
    s = sorted(float(v) for v in vals)
    p25 = _percentile(s, 0.25)
    med = _percentile(s, 0.50)
    p75 = _percentile(s, 0.75)
    return {
        "n": len(s),
        "median": round(med, ndigits),
        "p25": round(p25, ndigits),
        "p75": round(p75, ndigits),
        "iqr": round(p75 - p25, ndigits),
        "min": round(s[0], ndigits),
        "max": round(s[-1], ndigits),
    }


# ── 4. Linux RAPL (`reported_j`) / Unmetered Telemetry & Host Scrubbing ──────

class RaplDomain:
    def __init__(self, label: str, energy_path: Path, max_range_path: Path | None) -> None:
        self.label = label
        self.energy_path = energy_path
        self.max_range_uj: int | None = None
        if max_range_path and max_range_path.is_file() and os.access(max_range_path, os.R_OK):
            try:
                self.max_range_uj = int(max_range_path.read_text().strip())
            except Exception:
                self.max_range_uj = None

    def read_uj(self) -> int:
        return int(self.energy_path.read_text().strip())

    def delta_uj(self, start_uj: int, end_uj: int) -> int:
        if end_uj >= start_uj:
            return end_uj - start_uj
        if self.max_range_uj and self.max_range_uj > start_uj:
            return (self.max_range_uj - start_uj) + end_uj
        return 0


class EnergyMeter:
    """Orthogonal hardware meter (`measured_j ⊥ reported_j ⊥ est_j ⊥ unmetered`)."""

    def __init__(self) -> None:
        self.pkg_domain: RaplDomain | None = None
        self.core_domain: RaplDomain | None = None
        self._discover_rapl()

    def _discover_rapl(self) -> None:
        base = Path("/sys/class/powercap")
        if platform.system() != "Linux" or not base.is_dir():
            return
        for p_name in ("intel-rapl:0", "intel-rapl:0:0"):
            d = base / p_name
            e_path = d / "energy_uj"
            n_path = d / "name"
            m_path = d / "max_energy_range_uj"
            if e_path.is_file() and os.access(e_path, os.R_OK):
                try:
                    _ = int(e_path.read_text().strip())
                    label = n_path.read_text().strip() if (n_path.is_file() and os.access(n_path, os.R_OK)) else p_name
                    dom = RaplDomain(label, e_path, m_path)
                    if p_name == "intel-rapl:0":
                        self.pkg_domain = dom
                    else:
                        self.core_domain = dom
                except Exception:
                    continue

    @property
    def evidence_class(self) -> str:
        return "reported_j" if self.pkg_domain is not None else "unmetered"

    @property
    def substrate_id(self) -> str:
        return "x86_rapl" if self.pkg_domain is not None else "unmetered_host"

    def sample_idle_power_w(self, window_s: float = 0.15) -> float | None:
        if self.pkg_domain is None:
            return None
        try:
            e0 = self.pkg_domain.read_uj()
            t0 = time.perf_counter_ns()
            time.sleep(window_s)
            e1 = self.pkg_domain.read_uj()
            dt_s = max(1e-9, (time.perf_counter_ns() - t0) * 1e-9)
            return round((self.pkg_domain.delta_uj(e0, e1) / 1e6) / dt_s, 4)
        except Exception:
            return None

    def snapshot(self) -> dict[str, Any]:
        ru = resource.getrusage(resource.RUSAGE_SELF)
        return {
            "wall_ns": time.perf_counter_ns(),
            "cpu_s": ru.ru_utime + ru.ru_stime,
            "pkg_uj": self.pkg_domain.read_uj() if self.pkg_domain else None,
            "core_uj": self.core_domain.read_uj() if self.core_domain else None,
        }

    def diff(self, s0: dict[str, Any], s1: dict[str, Any]) -> dict[str, Any]:
        wall_ns = max(1, int(s1["wall_ns"] - s0["wall_ns"]))
        cpu_ms = max(0.0, float(s1["cpu_s"] - s0["cpu_s"])) * 1e3
        pkg_j = (
            self.pkg_domain.delta_uj(s0["pkg_uj"], s1["pkg_uj"]) / 1e6
            if (self.pkg_domain and s0["pkg_uj"] is not None and s1["pkg_uj"] is not None)
            else None
        )
        core_j = (
            self.core_domain.delta_uj(s0["core_uj"], s1["core_uj"]) / 1e6
            if (self.core_domain and s0["core_uj"] is not None and s1["core_uj"] is not None)
            else None
        )
        return {
            "wall_ns": wall_ns,
            "wall_us": round(wall_ns / 1e3, 2),
            "wall_ms": round(wall_ns / 1e6, 4),
            "cpu_user_sys_ms": round(cpu_ms, 4),
            "evidence_class": "reported_j" if pkg_j is not None else "unmetered",
            "measured_j": None,
            "pkg_reported_j": round(pkg_j, 6) if pkg_j is not None else None,
            "core_reported_j": round(core_j, 6) if core_j is not None else None,
            "est_j": None,
        }

    def metadata(self, idle_pre_w: float | None, idle_post_w: float | None) -> dict[str, Any]:
        if self.pkg_domain is None:
            return {
                "evidence_class": "unmetered",
                "substrate_id": "unmetered_host",
                "measured_j": None,
                "reported_j_available": False,
                "est_j": None,
                "classes_mixed_or_summed": False,
                "package_counter": None,
                "core_counter": None,
            }
        drift_pct = None
        if idle_pre_w is not None and idle_post_w is not None:
            mean_w = 0.5 * (idle_pre_w + idle_post_w)
            drift_pct = round(100.0 * abs(idle_post_w - idle_pre_w) / max(mean_w, 1e-9), 2)
        return {
            "evidence_class": "reported_j",
            "substrate_id": "x86_rapl",
            "measured_j": None,
            "reported_j_available": True,
            "est_j": None,
            "classes_mixed_or_summed": False,
            "package_counter": str(self.pkg_domain.energy_path),
            "package_domain": self.pkg_domain.label,
            "core_counter": str(self.core_domain.energy_path) if self.core_domain else None,
            "core_domain": self.core_domain.label if self.core_domain else None,
            "idle_pkg_w_pre": idle_pre_w,
            "idle_pkg_w_post": idle_post_w,
            "idle_drift_pct": drift_pct,
        }


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

    cc_bin = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    cc_ver = "not_installed"
    if cc_bin:
        try:
            raw = subprocess.check_output([cc_bin, "--version"], stderr=subprocess.STDOUT, text=True, timeout=5)
            first = re.sub(r"\s*\([^)]*\)", "", raw.splitlines()[0].strip())
            m_ver = re.search(r"(clang|gcc|cc)[^\d]*(\d+\.\d+(?:\.\d+)?)", first, flags=re.IGNORECASE)
            cc_ver = f"{'Clang' if 'clang' in first.lower() else 'GCC'} {m_ver.group(2)}" if m_ver else first
        except Exception:
            cc_ver = "unavailable"

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
        "cc_version": cc_ver,
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


# ── 5. Arm D: Deterministic Earley / Pushdown Typed CFG Token Masker ─────────
#
# Models a concrete 32-token typed expression grammar for candidate guard/kernel
# synthesis where every candidate has target return type T_ret in {"INT", "BOOL", "LIST"}
# and typed context variables `(x0, x1)` of known types.
#
# Unconstrained decoding samples over all 32 vocabulary tokens (syntax delimiters,
# mismatched operators, out-of-type identifiers, premature EOS) and rejects
# syntactically or static-type-invalid sequences post-hoc.
#
# In-loop CFG/Type Masking maintains an exact Earley/pushdown continuation stack
# of expected typed nonterminals (`EXP_INT`, `EXP_BOOL`, `EXP_LIST`, `OP_AFTER_INT`,
# `CLOSE_PAREN`, `EOS_ONLY`), computing a 32-bit valid-next-token bitmask BEFORE
# sampling each token so syntax & static-type rejection is identically 0/1,000.

VOCAB: list[str] = [
    "<EOS>",        # 0
    "(",            # 1
    ")",            # 2
    "if_then_else", # 3  ternary typed combinator: if_then_else ( BOOL , T , T )
    ",",            # 4
    "x_int0",       # 5  INT variable
    "x_int1",       # 6  INT variable
    "x_bool0",      # 7  BOOL variable
    "x_list0",      # 8  LIST<INT> variable
    "0",            # 9  INT literal
    "1",            # 10 INT literal
    "65535",        # 11 INT literal
    "True",         # 12 BOOL literal
    "False",        # 13 BOOL literal
    "+",            # 14 INT x INT -> INT
    "-",            # 15 INT x INT -> INT
    "&",            # 16 INT x INT -> INT
    "clamp_u16",    # 17 clamp_u16 ( INT ) -> INT
    "len_of",       # 18 len_of ( LIST ) -> INT
    "<",            # 19 INT x INT -> BOOL
    "<=",           # 20 INT x INT -> BOOL
    "==",           # 21 INT x INT -> BOOL
    "and_b",        # 22 BOOL x BOOL -> BOOL
    "not_b",        # 23 not_b ( BOOL ) -> BOOL
    "is_sorted",    # 24 is_sorted ( LIST ) -> BOOL
    "sort_asc",     # 25 sort_asc ( LIST ) -> LIST
    "dedup_asc",    # 26 dedup_asc ( LIST ) -> LIST
    "ring_push",    # 27 ring_push ( LIST , INT ) -> LIST
    "empty_list",   # 28 LIST literal
    "bad_delim_]",  # 29 lexical/delimiter stray token
    "type_any_?",   # 30 untyped stray token
    ";;",           # 31 stray statement separator
]
TOKEN_TO_ID = {tok: idx for idx, tok in enumerate(VOCAB)}


class SplitMix64:
    """Deterministic cross-platform 64-bit PRNG for reproducible logit/token draws."""

    def __init__(self, seed: int) -> None:
        self.state = seed & 0xFFFFFFFFFFFFFFFF

    def next_u64(self) -> int:
        self.state = (self.state + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
        return (z ^ (z >> 31)) & 0xFFFFFFFFFFFFFFFF

    def next_float(self) -> float:
        return (self.next_u64() >> 11) * (1.0 / (1 << 53))


def _bit(tok: str) -> int:
    return 1 << TOKEN_TO_ID[tok]


_MASK_EOS = _bit("<EOS>")
_MASK_LPAREN = _bit("(")
_MASK_RPAREN = _bit(")")
_MASK_COMMA = _bit(",")

# Bounded-depth vs terminal masks for typed nonterminals (`EXP_INT`, `EXP_BOOL`, `EXP_LIST`)
_MASK_INT_ATOM = _bit("x_int0") | _bit("x_int1") | _bit("0") | _bit("1") | _bit("65535")
_MASK_INT_REC = _MASK_INT_ATOM | _bit("(") | _bit("clamp_u16") | _bit("len_of") | _bit("if_then_else")

_MASK_BOOL_ATOM = _bit("x_bool0") | _bit("True") | _bit("False")
_MASK_BOOL_REC = _MASK_BOOL_ATOM | _bit("(") | _bit("not_b") | _bit("is_sorted") | _bit("if_then_else")

_MASK_LIST_ATOM = _bit("x_list0") | _bit("empty_list")
_MASK_LIST_REC = _MASK_LIST_ATOM | _bit("sort_asc") | _bit("dedup_asc") | _bit("ring_push") | _bit("if_then_else")

_MASK_INT_BINOP = _bit("+") | _bit("-") | _bit("&")
_MASK_CMP_BINOP = _bit("<") | _bit("<=") | _bit("==")
_MASK_BOOL_BINOP = _bit("and_b")


class TypedEarleyPushdownMasker:
    """Incremental pushdown/Earley continuation state machine over the 32-token typed CFG.

    Guarantees:
      1. Every sequence reaching `<EOS>` parses uniquely into a well-typed AST of `target_type`.
      2. Bounded expansion budget `max_compounds` guarantees termination before `max_steps`
         (zero dead-end / zero-mask states).
    """

    @staticmethod
    def initial_stack(target_type: str) -> list[str]:
        return ["EOS", f"EXP_{target_type}"]

    @staticmethod
    def valid_mask(stack: list[str], compounds_left: int) -> int:
        if not stack:
            return 0
        top = stack[-1]
        if top == "EOS":
            return _MASK_EOS
        if top == "LPAREN":
            return _MASK_LPAREN
        if top == "RPAREN":
            return _MASK_RPAREN
        if top == "COMMA":
            return _MASK_COMMA
        if top == "INT_OP":
            return _MASK_INT_BINOP
        if top == "CMP_OP":
            return _MASK_CMP_BINOP
        if top == "BOOL_OP":
            return _MASK_BOOL_BINOP
        if top == "EXP_INT":
            return _MASK_INT_REC if compounds_left > 0 else _MASK_INT_ATOM
        if top == "EXP_BOOL":
            # Note: `(` starts either `( EXP_INT CMP_OP EXP_INT )` or `( EXP_BOOL BOOL_OP EXP_BOOL )`
            return _MASK_BOOL_REC if compounds_left > 0 else _MASK_BOOL_ATOM
        if top == "EXP_LIST":
            return _MASK_LIST_REC if compounds_left > 0 else _MASK_LIST_ATOM
        if top == "BOOL_PAREN_BODY":
            # Inside `(` of a BOOL expression: can begin with INT atom/call -> CMP_OP, or BOOL atom -> BOOL_OP
            return _MASK_INT_ATOM | _MASK_BOOL_ATOM
        return 0

    @staticmethod
    def step(stack: list[str], tok_id: int, compounds_left: int) -> tuple[list[str], int, bool]:
        """Advance pushdown state by one token; return `(new_stack, new_compounds_left, ok)`."""
        if not stack or tok_id < 0 or tok_id >= len(VOCAB):
            return ([], compounds_left, False)
        mask = TypedEarleyPushdownMasker.valid_mask(stack, compounds_left)
        if ((mask >> tok_id) & 1) == 0:
            return ([], compounds_left, False)

        tok = VOCAB[tok_id]
        nxt = list(stack)
        top = nxt.pop()

        if top in ("EOS", "LPAREN", "RPAREN", "COMMA", "INT_OP", "CMP_OP", "BOOL_OP"):
            return (nxt, compounds_left, True)

        if top == "EXP_INT":
            if tok in ("x_int0", "x_int1", "0", "1", "65535"):
                return (nxt, compounds_left, True)
            if tok == "(":
                # ( EXP_INT INT_OP EXP_INT )
                nxt.extend(["RPAREN", "EXP_INT", "INT_OP", "EXP_INT"])
                return (nxt, compounds_left - 1, True)
            if tok == "clamp_u16":
                nxt.extend(["RPAREN", "EXP_INT", "LPAREN"])
                return (nxt, compounds_left - 1, True)
            if tok == "len_of":
                nxt.extend(["RPAREN", "EXP_LIST", "LPAREN"])
                return (nxt, compounds_left - 1, True)
            if tok == "if_then_else":
                nxt.extend(["RPAREN", "EXP_INT", "COMMA", "EXP_INT", "COMMA", "EXP_BOOL", "LPAREN"])
                return (nxt, compounds_left - 1, True)

        if top == "EXP_BOOL":
            if tok in ("x_bool0", "True", "False"):
                return (nxt, compounds_left, True)
            if tok == "(":
                nxt.append("BOOL_PAREN_BODY")
                return (nxt, compounds_left - 1, True)
            if tok == "not_b":
                nxt.extend(["RPAREN", "EXP_BOOL", "LPAREN"])
                return (nxt, compounds_left - 1, True)
            if tok == "is_sorted":
                nxt.extend(["RPAREN", "EXP_LIST", "LPAREN"])
                return (nxt, compounds_left - 1, True)
            if tok == "if_then_else":
                nxt.extend(["RPAREN", "EXP_BOOL", "COMMA", "EXP_BOOL", "COMMA", "EXP_BOOL", "LPAREN"])
                return (nxt, compounds_left - 1, True)

        if top == "BOOL_PAREN_BODY":
            if tok in ("x_int0", "x_int1", "0", "1", "65535"):
                nxt.extend(["RPAREN", "EXP_INT", "CMP_OP"])
                return (nxt, compounds_left, True)
            if tok in ("x_bool0", "True", "False"):
                nxt.extend(["RPAREN", "EXP_BOOL", "BOOL_OP"])
                return (nxt, compounds_left, True)

        if top == "EXP_LIST":
            if tok in ("x_list0", "empty_list"):
                return (nxt, compounds_left, True)
            if tok in ("sort_asc", "dedup_asc"):
                nxt.extend(["RPAREN", "EXP_LIST", "LPAREN"])
                return (nxt, compounds_left - 1, True)
            if tok == "ring_push":
                nxt.extend(["RPAREN", "EXP_INT", "COMMA", "EXP_LIST", "LPAREN"])
                return (nxt, compounds_left - 1, True)
            if tok == "if_then_else":
                nxt.extend(["RPAREN", "EXP_LIST", "COMMA", "EXP_LIST", "COMMA", "EXP_BOOL", "LPAREN"])
                return (nxt, compounds_left - 1, True)

        return ([], compounds_left, False)


def posthoc_parse_and_typecheck(tokens: list[int], target_type: str) -> tuple[bool, str | None]:
    """Full post-hoc lexer/CFG/static-type validator used when decoding without an in-loop mask."""
    if not tokens or tokens[-1] != 0:
        return (False, "UNTERMINATED_NO_EOS")
    stack = TypedEarleyPushdownMasker.initial_stack(target_type)
    # Unconstrained generator has unbounded depth allowance up to max_tokens
    compounds_left = 64
    for pos, tok_id in enumerate(tokens):
        if tok_id in (29, 30, 31):
            return (False, f"LEXICAL_STRAY_TOKEN@{pos}:{VOCAB[tok_id]}")
        stack, compounds_left, ok = TypedEarleyPushdownMasker.step(stack, tok_id, compounds_left)
        if not ok:
            return (False, f"CFG_OR_TYPE_ERROR@{pos}:{VOCAB[tok_id]}")
    if stack:
        return (False, "INCOMPLETE_PARSE_STACK")
    return (True, None)


def _build_proposal_weights(target_type: str, rng: SplitMix64) -> list[float]:
    """Realistic unnormalized categorical weights (exp(logits)) of a code proposer:
    assigns high mass to plausible tokens for `target_type` PLUS non-zero probability
    mass (~9% per step) to syntax-slip / delimiter-mismatch / type-confusion tokens,
    which accumulate across multi-token rollouts under unconstrained decoding.
    """
    w = [0.18 + 0.08 * rng.next_float() for _ in range(len(VOCAB))]
    # Boost EOS and target-relevant tokens
    w[0] = 1.65
    w[1] = 1.20
    w[2] = 1.20
    w[4] = 0.85
    if target_type == "INT":
        for tid in (5, 6, 9, 10, 11, 14, 15, 17):
            w[tid] = 2.40 + 0.5 * rng.next_float()
    elif target_type == "BOOL":
        for tid in (7, 12, 13, 19, 20, 21, 22, 23, 24):
            w[tid] = 2.40 + 0.5 * rng.next_float()
    else:
        for tid in (8, 25, 26, 27, 28):
            w[tid] = 2.40 + 0.5 * rng.next_float()
    # Non-zero slip mass on stray delimiters / untyped tokens
    w[29] = 0.32
    w[30] = 0.28
    w[31] = 0.25
    return w


def _sample_categorical(weights: list[float], mask: int, rng: SplitMix64) -> int:
    total = 0.0
    n = len(weights)
    for i in range(n):
        if (mask >> i) & 1:
            total += weights[i]
    u = rng.next_float() * total
    acc = 0.0
    last_valid = 0
    for i in range(n):
        if (mask >> i) & 1:
            last_valid = i
            acc += weights[i]
            if u <= acc:
                return i
    return last_valid


def sample_unconstrained_stream(
    weights: list[float], rng: SplitMix64, max_tokens: int = 28
) -> list[int]:
    all_mask = (1 << len(VOCAB)) - 1
    out: list[int] = []
    for _ in range(max_tokens):
        tid = _sample_categorical(weights, all_mask, rng)
        out.append(tid)
        if tid == 0:
            break
    return out


def sample_grammar_masked_stream(
    weights: list[float], target_type: str, rng: SplitMix64, max_compounds: int = 3
) -> list[int]:
    stack = TypedEarleyPushdownMasker.initial_stack(target_type)
    compounds = max_compounds
    out: list[int] = []
    while stack:
        mask = TypedEarleyPushdownMasker.valid_mask(stack, compounds)
        tid = _sample_categorical(weights, mask, rng)
        out.append(tid)
        stack, compounds, ok = TypedEarleyPushdownMasker.step(stack, tid, compounds)
        if not ok:
            raise RuntimeError("Internal invariant violated: masked token failed pushdown transition")
    return out
